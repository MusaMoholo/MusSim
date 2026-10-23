"""Model-free scenario catalogue, request validation and bounded in-memory job lifecycle."""
from __future__ import annotations
import csv
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
MODEL='2026-10-23-cutoff'
MAX_CONDITIONS=6


class ScenarioError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


def key_for(row):
    raw=json.dumps([row['competition'],int(float(row['season'])),row['kickoff'],row['home'],row['away']],ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def source_manifest(root=ROOT):
    root=Path(root)
    paths=[root/'data/master_fixtures.csv',root/'data/master_fixtures.pkl',root/'data/external/elo_ratings.csv',root/'data/external/opta_path.json',root/'football_common.py']
    paths+=sorted((root/'scripts').glob('*.py'))
    paths+=sorted((root/'data/team_rankings_history').glob('team_rankings-*.csv'))
    refs={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths}
    return {'sha256':hashlib.sha256(json.dumps(refs,sort_keys=True).encode()).hexdigest(),'files':refs}


_CODE_AT_IMPORT={k:v for k,v in source_manifest()['files'].items() if k.endswith('.py')}

def catalog(snaps,day,revision,*,root=ROOT):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(day or '')):raise ScenarioError('Choose a pinned snapshot date.')
    payload=snaps.load(day)
    if not payload:raise ScenarioError('Snapshot unavailable.',404)
    if not revision or revision!=payload['source']['projection_sha256']:raise ScenarioError('The forecast revision changed. Reload the selected snapshot.',409)
    latest=snaps.list()[-1]['date']
    out={'source':payload['source'],'as_of':payload['as_of'],'available':False,'fixtures':[],
         'competitions':[b['competition'] for b in payload.get('leagues',[])],'max_conditions':MAX_CONDITIONS}
    if day!=latest:
        out['reason']='Scenario Lab currently uses the latest stored snapshot. Open the latest date to run an experiment.';return out
    if payload.get('model')!=MODEL:
        out['reason']='This snapshot uses a different model generation; its simulation inputs cannot be reproduced by this Scenario Lab.';return out
    rows=[];last_played=''
    with (Path(root)/'data/master_fixtures.csv').open(newline='') as source:
        for r in csv.DictReader(source):
            if int(float(r['season']))!=int(payload['params']['season']):continue
            if r['played'].lower() in ('true','1'):
                if r.get('home_goals') and r.get('away_goals'):last_played=max(last_played,r['kickoff'][:10])
                continue
            if r['kind']!='league' or r.get('tbd','').lower() in ('true','1') or r.get('outcome')=='aborted':continue
            if r['kickoff'][:10]<=payload['as_of']:continue
            if r['competition'] not in out['competitions']:continue
            rows.append({'id':key_for(r),'competition':r['competition'],'season':int(float(r['season'])),
                         'home':r['home'],'away':r['away'],'kickoff':r['kickoff'],'round':int(float(r['round'])) if r.get('round') else None})
    if last_played!=payload['as_of']:
        out['reason']='Retained results and this snapshot have different cutoffs. Publish a current snapshot before running Scenario Lab.';return out
    ids=[r['id'] for r in rows]
    if len(ids)!=len(set(ids)):raise ScenarioError('Duplicate fixture identities in retained inputs.',409)
    out.update(available=bool(rows),fixtures=sorted(rows,key=lambda r:(r['kickoff'],r['competition'],r['home'],r['away'])),
               input_revision=source_manifest(root)['sha256'],params=payload['params'],model=payload['model'],
               method='complete-world rejection',minimum_accepted=100)
    if not rows:out['reason']='No supported future league fixtures are available.'
    return out


def validate(body,catalogue):
    if not catalogue['available']:raise ScenarioError(catalogue.get('reason','Scenario inputs unavailable.'))
    if body.get('input_revision')!=catalogue['input_revision']:raise ScenarioError('Retained inputs changed. Reload Scenario Lab before running.',409)
    comp=body.get('competition')
    if comp not in catalogue['competitions']:raise ScenarioError('Choose a supported league to compare.')
    worlds=body.get('worlds',5000);seed=body.get('seed',1)
    if type(worlds) is not int or not 200<=worlds<=10000:raise ScenarioError('Choose 200–10,000 proposal worlds.')
    if type(seed) is not int or not 0<=seed<=2**31-1:raise ScenarioError('Seed must be an integer from 0 to 2,147,483,647.')
    raw=body.get('conditions',[])
    if not isinstance(raw,list) or len(raw)>MAX_CONDITIONS:raise ScenarioError('Use at most six fixture assumptions.')
    fixtures={f['id']:f for f in catalogue['fixtures']};conditions={}
    for c in raw:
        if not isinstance(c,dict) or c.get('fixture') not in fixtures:raise ScenarioError('An assumed fixture is unavailable or no longer future.')
        outcome=c.get('outcome')
        if outcome not in ('home','draw','away','score'):raise ScenarioError('Choose home win, draw, away win or an exact score.')
        entry={'fixture':c['fixture'],'outcome':outcome}
        if outcome=='score':
            score=c.get('score')
            if not isinstance(score,list) or len(score)!=2 or any(type(v) is not int or not 0<=v<=10 for v in score):raise ScenarioError('Exact scores require two integers from 0 to 10.')
            entry['score']=score
        previous=conditions.get(c['fixture'])
        if previous and previous!=entry:
            score=entry if outcome=='score' else previous if previous['outcome']=='score' else None
            result=previous if outcome=='score' else entry
            if score is None:raise ScenarioError('Conflicting assumptions for the same fixture.')
            h,a=score['score'];result_of_score='home' if h>a else 'away' if a>h else 'draw'
            if result['outcome']!=result_of_score:raise ScenarioError('The exact score contradicts the result assumption.')
            entry=score
        conditions[c['fixture']]=entry
    return {'competition':comp,'worlds':worlds,'seed':seed,'conditions':[conditions[k] for k in sorted(conditions)],
            'date':catalogue['source']['date'],'revision':catalogue['source']['projection_sha256'],
            'input_revision':catalogue['input_revision']}


class ScenarioManager:
    def __init__(self,snaps,processes=4,*,root=ROOT,executor=None):
        self.snaps=snaps;self.processes=max(1,min(processes or 4,4));self.root=Path(root)
        self.jobs={};self.lock=threading.Lock();self.executor=executor

    def start(self,body):
        cat=catalog(self.snaps,body.get('date'),body.get('revision'),root=self.root);definition=validate(body,cat)
        with self.lock:
            if any(j['status']=='running' for j in self.jobs.values()):raise ScenarioError('A scenario is already running. Cancel it or wait for completion.',409)
            while len(self.jobs)>=8:self.jobs.pop(next(iter(self.jobs)))
            key=uuid.uuid4().hex[:16]
            self.jobs[key]={'status':'running','done':0,'total':definition['worlds'],'accepted':0,'stage':'preparing',
                            'started':time.monotonic(),'definition':definition,'cancel':threading.Event()}
        threading.Thread(target=self._run,args=(key,cat),daemon=True).start()
        return key,definition

    def _run(self,key,cat):
        job=self.jobs[key];definition=job['definition'];cancel=job['cancel']
        try:
            if self.executor is None:
                from scripts.scenario_lab import run
            else:run=self.executor
            if cancel.is_set():job['status']='cancelled';return
            before=source_manifest(self.root)
            if self.root==ROOT and {k:v for k,v in before['files'].items() if k.endswith('.py')}!=_CODE_AT_IMPORT:
                raise ScenarioError('Simulation code changed after server startup. Restart scripts/serve.py before running Scenario Lab.',409)
            if before['sha256']!=definition['input_revision']:raise ScenarioError('Inputs changed before the experiment started. Reload Scenario Lab.',409)
            params={**cat['params'],'worlds':definition['worlds'],'seed':definition['seed']}
            def progress(done,total,accepted,stage):job.update(done=done,total=total,accepted=accepted,stage=stage)
            result=run(params,definition['competition'],definition['conditions'],self.processes,progress,cancel.is_set)
            after=source_manifest(self.root)
            if cancel.is_set():job['status']='cancelled';return
            if before!=after:raise ScenarioError('Inputs changed during the experiment. Its result was discarded; reload Scenario Lab.',409)
            snapshot=self.snaps.load(definition['date'])
            if not snapshot or snapshot['source']!=cat['source']:raise ScenarioError('The pinned forecast changed during the experiment. Its result was discarded.',409)
            result.update(schema=1,competition=definition['competition'],definition=definition,source=cat['source'],as_of=cat['as_of'],
                          input_revision=before['sha256'],input_files=before['files'],model=cat['model'],params=params,
                          method='Complete ordinary worlds; keep only worlds matching every assumption.',
                          baseline_note='Fresh paired baseline using retained inputs at the selected cutoff; not a republished forecast.')
            job.update(result=result,status='done',stage='complete')
        except Exception as error:
            from scripts.scenario_lab import Cancelled
            if isinstance(error,Cancelled) or cancel.is_set():job['status']='cancelled'
            else:job.update(status='error',error=str(error),stage='failed')
        finally:job['finished']=time.monotonic()

    def get(self,key):
        with self.lock:job=self.jobs.get(key)
        if not job:raise ScenarioError('Scenario job unavailable. It may have expired after a server restart.',404)
        out={k:job[k] for k in ('status','done','total','accepted','stage','definition','result','error') if k in job}
        out['elapsed']=round(job.get('finished',time.monotonic())-job['started'],1);return out

    def cancel(self,key):
        with self.lock:job=self.jobs.get(key)
        if not job:raise ScenarioError('Unknown scenario job.',404)
        if job['status']=='running':job['cancel'].set();job['stage']='cancelling'
        return self.get(key)
