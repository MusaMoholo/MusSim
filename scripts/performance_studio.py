"""Read-only match evidence and retained domestic-league expectations; stdlib only."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ZONES={'English Premier League':'Europe/London','French Ligue 1':'Europe/Paris','German Bundesliga':'Europe/Berlin','Italian Serie A':'Europe/Rome','Spanish La Liga':'Europe/Madrid'}


class PerformanceError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


def identity(f):return (f['competition'],f['home'],f['away'],str(f['kickoff'])[:10])


def number(value):
    if value in (None,'','nan','NaN'):return None
    try:n=float(value)
    except (TypeError,ValueError):raise PerformanceError('Invalid retained numerical value.',409)
    if not math.isfinite(n) or n<0:raise PerformanceError('Invalid retained numerical value.',409)
    return n


def probabilities(f):
    ladder=f.get('ladder') or {};values=[ladder.get(k) for k in ('h1','d','a1')]
    if any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1 for v in values) or abs(sum(values)-1)>.0002:
        raise PerformanceError('Invalid retained win/draw/loss probabilities.',409)
    return values


def generation_timing(generated,fixture):
    try:
        stamp=datetime.fromisoformat(generated.replace('Z','+00:00'));kickoff=datetime.fromisoformat(fixture['kickoff'])
        if kickoff.tzinfo is None:kickoff=kickoff.replace(tzinfo=ZoneInfo(ZONES[fixture['competition']]))
        if stamp.tzinfo is None:return 'unknown'
        return 'before_kickoff' if stamp<kickoff else 'retrospective'
    except (ValueError,TypeError,AttributeError,KeyError):return 'unknown'


class PerformanceStudio:
    def __init__(self,snapshots):self.snaps=snapshots;self.lock=threading.Lock();self.cache={}

    def _paths(self,day):
        dates=sorted(r['date'] for r in self.snaps.list() if r['date']<=day)
        paths=[self.snaps.master_csv,self.snaps.root/'index.json']
        for date in dates:paths.extend([self.snaps.root/date/'projection.json',self.snaps.root/date/'matches.json'])
        return dates,paths

    def _manifest(self,paths):
        refs={}
        for path in paths:
            path=Path(path);refs[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return refs

    def read(self,day,revision,*,all_competitions=False):
        if day not in {r['date'] for r in self.snaps.list()}:raise PerformanceError('Choose an available stored snapshot.',404)
        selected=self.snaps.load(day)
        if not revision or selected['source']['projection_sha256']!=revision:raise PerformanceError('The pinned forecast changed. Reload the snapshot.',409)
        dates,paths=self._paths(day);refs=self._manifest(paths)
        digest=hashlib.sha256(json.dumps(refs,sort_keys=True).encode()).hexdigest()
        cache_key=(day,revision,digest,bool(all_competitions))
        with self.lock:
            if cache_key in self.cache:return self.cache[cache_key]
        out=self._build(selected,dates,refs,all_competitions=all_competitions)
        if refs!=self._manifest(paths):raise PerformanceError('Retained inputs changed during the read. Reload club performance.',409)
        if self.snaps.load(day)['source']!=selected['source']:raise PerformanceError('The pinned forecast changed during the read.',409)
        out['input_revision']=digest
        # Reference labels are relative to the snapshot root's parent, or exact master filename.
        out['input_files']={str(Path(k).relative_to(self.snaps.root.parent)) if Path(k).is_relative_to(self.snaps.root.parent) else Path(k).name:v for k,v in refs.items()}
        with self.lock:self.cache={cache_key:out}
        return out

    def _build(self,selected,dates,refs,*,all_competitions=False):
        season,cutoff=selected['params']['season'],selected['as_of']
        blocks=[(b,'league') for b in selected['leagues'] if b['competition'] in ZONES]
        if all_competitions:blocks += [(b,'uefa') for b in selected.get('uefa',[])]+[(b,'cup') for b in selected.get('cups',[])]
        comps=[{'competition':b['competition'],'kind':kind,'teams':[t['team'] for t in b['teams']]} for b,kind in blocks]
        supported={c['competition'] for c in comps};fixtures={};issues=[]
        raw=self.snaps.master_csv.read_bytes().decode('utf-8-sig')
        for row in csv.DictReader(io.StringIO(raw)):
            if int(float(row['season']))!=season or row['competition'] not in supported:continue
            if not all_competitions and row['kind']!='league':continue
            if row['played'].lower() not in ('true','1') or row.get('tbd','').lower() in ('true','1') or row['kickoff'][:10]>cutoff or row.get('outcome')=='aborted':continue
            k=identity(row)
            if k in fixtures:raise PerformanceError('Ambiguous duplicate fixture in retained results.',409)
            try:
                score=[number(row.get(s+'_goals')) for s in ('home','away')]
                if any(v is None or not v.is_integer() for v in score):raise PerformanceError('Missing or invalid retained match score.',409)
                if row['kind']=='league' and row.get('outcome') not in ('','fulltime'):raise PerformanceError('Non-90-minute league outcome is unsupported.',409)
                minutes=number(row.get('minutes'))
                if row['kind']=='league' and minutes not in (None,90):raise PerformanceError('Non-90-minute league exposure is unsupported.',409)
            except PerformanceError as error:
                issues.append({'fixture':'|'.join(k),'reason':str(error)});continue
            def pair(metric,integer=False):
                values=[]
                for side in ('home','away'):
                    try:
                        value=number(row.get(side+'_'+metric))
                        if integer and value is not None and not value.is_integer():raise PerformanceError('Invalid retained attempt count.',409)
                    except PerformanceError:
                        # Keep the actual match in rolling windows; invalid components stay unavailable.
                        issues.append({'fixture':'|'.join(k),'reason':'Invalid retained '+side+' '+metric+' value: '+str(row.get(side+'_'+metric))})
                        value=None
                    values.append(value)
                return values
            xg,xgot,npxg,shots=pair('xg'),pair('xgot'),pair('npxg'),pair('shots',integer=True)
            provider=number(row.get('match_id'))
            f={name:row[name] for name in ('competition','home','away','kickoff')}
            f.update(id=hashlib.sha256(json.dumps([season,*k],ensure_ascii=False).encode()).hexdigest()[:24],season=season,
                     match_id=str(int(provider)) if provider is not None else None,result=[int(v) for v in score],
                     xg=xg,xgot=xgot,npxg=npxg,shots=shots,minutes=minutes,kind=row['kind'],outcome=row.get('outcome') or None,
                     round=number(row.get('round')),round_label=row.get('round_label') or None,stage=row.get('stage') or None,phase=row.get('phase') or None,forecast=None,forecast_error=None)
            fixtures[k]=f
        for date in dates:
            projection_path=self.snaps.root/date/'projection.json';match_path=self.snaps.root/date/'matches.json'
            if not projection_path.exists() or not match_path.exists():continue
            p=json.loads(projection_path.read_bytes())
            if p['params']['season']!=season or not p.get('as_of') or p['as_of']>cutoff:continue
            seen=set()
            for candidate in json.loads(match_path.read_bytes()).get('fixtures',[]):
                k=identity(candidate);target=fixtures.get(k)
                if target is None or target['kind']!='league' or date>target['kickoff'][:10] or not p.get('as_of') or p['as_of']>=target['kickoff'][:10]:continue
                if k in seen:raise PerformanceError('Ambiguous duplicate fixture in retained forecasts.',409)
                seen.add(k)
                # The latest eligible retained snapshot wins, including a visible invalid-source refusal.
                try:wdl=probabilities(candidate);error=None
                except PerformanceError as exc:wdl=None;error=str(exc)
                target['forecast_error']=error
                target['forecast']={'snapshot':date,'as_of':p['as_of'],'model':p.get('model'),
                    'generated':p.get('generated'),'timing':generation_timing(p.get('generated'),target),
                    'projection_sha256':refs[str(projection_path)],'matches_sha256':refs[str(match_path)],
                    'wdl':wdl} if wdl else None
        rows=sorted(fixtures.values(),key=lambda f:(f['kickoff'],f['competition'],f['home'],f['away'],f['id']))
        for comp in comps:
            # Knockout forecast blocks may retain only survivors; completed entrants still have evidence.
            comp['teams']=sorted(set(comp['teams'])|{t for f in rows if f['competition']==comp['competition'] for t in (f['home'],f['away'])})
        return {'schema':1,'all_competitions':bool(all_competitions),'source':selected['source'],'season':season,'as_of':cutoff,'competitions':comps,
                'fixtures':rows,'issues':issues,'coverage':{'fixtures':len(rows),'xg':sum(all(v is not None for v in f['xg']) for f in rows),
                'forecasts':sum(f['forecast'] is not None for f in rows),'invalid_forecasts':sum(f['forecast_error'] is not None for f in rows)},
                'notice':'Retained forecasts use a cutoff before match day. Rebuilt after kickoff is retrospective evidence, not prospective evaluation. Historical result/provider revisions may also be present.'}
