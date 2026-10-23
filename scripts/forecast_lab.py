"""Read-only, content-pinned match forecast evaluation. Standard library only."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ZONES={'English Premier League':'Europe/London','English FA Cup':'Europe/London','English League Cup':'Europe/London','German Bundesliga':'Europe/Berlin','German DFB Pokal':'Europe/Berlin','Spanish La Liga':'Europe/Madrid','Spanish Copa del Rey':'Europe/Madrid','Italian Serie A':'Europe/Rome','Italian Coppa Italia':'Europe/Rome','French Ligue 1':'Europe/Paris','French Coupe de France':'Europe/Paris','UEFA Champions League':'Europe/Zurich','UEFA Europa League':'Europe/Zurich','UEFA Conference League':'Europe/Zurich'}
METRICS=('log_loss','brier','rps')

class ForecastError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status

def key(f):return (f['competition'],f['home'],f['away'],f['kickoff'][:10])
def flag(v):return str(v).lower() in ('1','true','yes')
def instant(value,competition):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=ZoneInfo(ZONES[competition]))
    return stamp.astimezone(timezone.utc)
def probability(values):
    return isinstance(values,list) and len(values)==3 and all(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1 for p in values) and abs(sum(values)-1)<=.000150001

def outcomes90(rows):
    """Existing Track 90-minute convention, without pandas/model imports.

    At extra time the aggregate was tied: a return-leg home margin equals the first-leg home
    margin. Single-leg ties were drawn at90. Keep an explicit provenance label, not a fake score.
    """
    previous={};results={}
    for r in sorted(rows,key=lambda r:(instant(r['kickoff'],r['competition']),int(float(r['season'])),r['competition'],r['home'],r['away'])):
        k=(int(float(r['season'])),*key(r))
        if k in results:raise ForecastError('Duplicate retained result identity.',409)
        pair=(r['competition'],k[0],r['home'],r['away']);reverse=(pair[0],pair[1],pair[3],pair[2])
        knockout=r['kind']!='league' and r.get('round') in ('',None)
        first=previous.get(reverse) if knockout else None
        if first and not timedelta(0)<instant(r['kickoff'],r['competition'])-instant(first['kickoff'],first['competition'])<timedelta(days=60):first=None
        if r.get('outcome') in ('afterextratime','penalties'):
            if first and first.get('outcome') not in ('','fulltime'):continue
            try:margin=float(first['home_goals'])-float(first['away_goals']) if first else 0
            except (ValueError,TypeError):continue
            if not math.isfinite(margin):continue
            results[k]=(0 if margin>0 else 2 if margin<0 else 1,None,'aggregate level at90 / first-leg margin' if first else 'extra time / level at90')
        elif r.get('outcome') in ('','fulltime') and r.get('minutes') in ('','90','90.0',None):
            try:score=[float(r.get(side+'_goals','')) for side in ('home','away')]
            except (ValueError,TypeError):continue
            if any(not math.isfinite(v) or v<0 or not v.is_integer() for v in score):continue
            results[k]=(0 if score[0]>score[1] else 2 if score[0]<score[1] else 1,[int(v) for v in score],'full-time90')
        if knockout:previous[pair]=r
    return results

def scores(prob,result):
    if not probability(prob) or result not in (0,1,2):raise ForecastError('Invalid probability/result in evaluation.',409)
    cumulative=0;rps=0
    for i,p in enumerate(prob):
        cumulative+=p
        if i<2:rps+=(cumulative-int(result<=i))**2/2
    return {'log_loss':-math.log(prob[result]) if prob[result]>0 else None,
            'brier':sum((p-int(i==result))**2 for i,p in enumerate(prob)),'rps':rps}

def wilson(successes,n):
    if not n:return None
    z=1.959963984540054;p=successes/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,c-h),min(1,c+h)]

def summary(rows,baseline='historical'):
    paired=[r for r in rows if r['baselines'].get(baseline) is not None];out={'n':len(paired),'model':{},'baseline':{},'improvement':{},'weekly_se':{},'weeks':0}
    weeks={r['week'] for r in paired};out['weeks']=len(weeks)
    for metric in METRICS:
        a=[r['scores'][metric] for r in paired];b=[r['baseline_scores'][baseline][metric] for r in paired]
        out['model'][metric]=sum(a)/len(a) if a and all(v is not None for v in a) else None
        out['baseline'][metric]=sum(b)/len(b) if b and all(v is not None for v in b) else None
        delta=[y-x if x is not None and y is not None else None for x,y in zip(a,b)]
        mean=sum(delta)/len(delta) if delta and all(v is not None for v in delta) else None;out['improvement'][metric]=mean
        if mean is not None and len(weeks)>=6:
            sums=[sum(d-mean for r,d in zip(paired,delta) if r['week']==w) for w in sorted(weeks)]
            out['weekly_se'][metric]=math.sqrt(len(weeks)/(len(weeks)-1)*sum(v*v for v in sums))/len(paired)
        else:out['weekly_se'][metric]=None
    out['zero_support']=sum(r['scores']['log_loss'] is None for r in paired)
    return out

def calibration(rows,outcome=0,bins=10):
    out=[]
    for b in range(bins):
        selected=[r for r in rows if min(bins-1,int(r['prob'][outcome]*bins))==b];n=len(selected);wins=sum(r['result']==outcome for r in selected)
        out.append({'bin':b,'n':n,'predicted':sum(r['prob'][outcome] for r in selected)/n if n else None,'observed':wins/n if n else None,'successes':wins,'interval':wilson(wins,n),'ids':[r['id'] for r in selected]})
    return out

class ForecastLab:
    def __init__(self,snapshots):self.snaps=snapshots;self.lock=threading.Lock();self.cache={}
    def read(self,day,revision,input_revision=''):
        dates=sorted(r['date'] for r in self.snaps.list() if r['date']<=str(day))
        if day not in dates:raise ForecastError('Choose an available stored snapshot.',404)
        selected=self.snaps.load(day)
        if not revision or selected['source']['projection_sha256']!=revision:raise ForecastError('Pinned forecast changed. Reload the snapshot.',409)
        paths=[self.snaps.master_csv,self.snaps.root/'index.json']+[self.snaps.root/d/name for d in dates for name in ('projection.json','matches.json')]
        def manifest():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths}
        refs=manifest();digest=hashlib.sha256(json.dumps(refs,sort_keys=True).encode()).hexdigest()
        if input_revision and input_revision!=digest:raise ForecastError('Evaluation evidence changed. Reset evidence to adopt the current revision.',409)
        cache_key=(day,revision,digest)
        with self.lock:cached=self.cache.get(cache_key)
        if cached is not None:return cached
        out=self._build(selected,dates,refs)
        if refs!=manifest() or self.snaps.load(day)['source']!=selected['source']:raise ForecastError('Evidence changed during evaluation. Reload Forecast Lab.',409)
        out['input_revision']=digest;out['input_files']={str(Path(k).relative_to(self.snaps.root.parent)) if Path(k).is_relative_to(self.snaps.root.parent) else Path(k).name:v for k,v in refs.items()}
        with self.lock:self.cache={cache_key:out}
        return out
    def _build(self,selected,dates,refs):
        season=selected['params']['season'];cutoff=selected['as_of'];raw=list(csv.DictReader(io.StringIO(self.snaps.master_csv.read_text(encoding='utf-8-sig'))));fixtures={};exclusions=[]
        eligible=[r for r in raw if flag(r['played']) and not flag(r.get('tbd')) and r['competition'] in ZONES and r['kickoff'][:10]<=cutoff and 2021<=int(float(r['season']))<=season]
        results=outcomes90(eligible)
        for r in raw:
            if int(float(r['season']))!=season or not flag(r['played']) or r['kickoff'][:10]>cutoff:continue
            k=key(r)
            if k in fixtures:raise ForecastError('Duplicate retained played fixture identity.',409)
            f={name:r[name] for name in ('competition','home','away','kickoff','kind')};f.update(id=hashlib.sha256(json.dumps([season,*k],ensure_ascii=False).encode()).hexdigest()[:24],match_id=r.get('match_id') or None)
            fixtures[k]=f;reason=None
            if flag(r.get('tbd')) or r.get('outcome')=='aborted':reason='Unconfirmed or aborted fixture'
            elif r['competition'] not in ZONES:reason='Unsupported kickoff timezone'
            else:
                try:
                    f['result'],f['score'],f['result_basis']=results[(season,*k)]
                    time=instant(r['kickoff'],r['competition']);uk=time.astimezone(ZoneInfo('Europe/London'));f.update(uk_day=uk.date().isoformat(),week=(uk.date()-timedelta(days=uk.weekday())).isoformat())
                except (ValueError,KeyError):reason='90-minute result unresolved'
            f['reason']=reason;f['forecast']=None
        start=min((instant(f['kickoff'],f['competition']) for f in fixtures.values() if not f['reason']),default=None)
        base_counts={};training_seen=set();training_excluded=Counter();training_last=None
        for r in raw:
            yr=int(float(r['season']))
            if not 2021<=yr<season or not flag(r['played']) or flag(r.get('tbd')):continue
            try:
                t=instant(r['kickoff'],r['competition'])
                if start is None or t>=start:training_excluded['not_before_evaluation']+=1;continue
                outcome=results[(yr,*key(r))][0]
            except (ValueError,KeyError):training_excluded['unresolved_90min_or_timezone']+=1;continue
            k=(yr,*key(r))
            if k in training_seen:raise ForecastError('Duplicate training fixture identity.',409)
            training_seen.add(k);training_last=max(training_last,t) if training_last else t
            counts=base_counts.setdefault(r['kind'],[0,0,0]);counts[outcome]+=1
        bases={k:{'n':sum(v),'counts':v,'prob':[x/sum(v) for x in v]} for k,v in sorted(base_counts.items())}
        snapshots=[];health=[]
        for day in dates:
            path=self.snaps.root/day/'projection.json';mp=self.snaps.root/day/'matches.json'
            if not path.exists():continue
            p=json.loads(path.read_bytes())
            if p.get('params',{}).get('season')!=season:continue
            meta={'date':day,'as_of':p.get('as_of'),'fitted_through':p.get('fitted_through'),'generated':p.get('generated'),'model':p.get('model') or 'unstamped','payload':p.get('version',1),'projection_sha256':refs[str(path)],'matches_sha256':refs[str(mp)]}
            snapshots.append(meta)
            for block in p.get('cups',[]):
                for team in block.get('teams',[]):
                    for field,value in team.items():
                        if field.startswith('p_') and value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1):health.append({'date':day,'competition':block['competition'],'team':team['team'],'field':field,'value':value})
            if not mp.exists():continue
            seen=set()
            for candidate in json.loads(mp.read_bytes()).get('fixtures',[]):
                k=key(candidate);f=fixtures.get(k)
                if f is None or f['reason'] or day>k[3] or not meta['as_of'] or meta['as_of']>=k[3]:continue
                if k in seen:raise ForecastError('Duplicate retained forecast identity.',409)
                seen.add(k)
                # Latest nominally eligible record wins even if invalid; never fall back silently.
                f['forecast']={'source':meta,'candidate':candidate}
        evaluated=[]
        for f in fixtures.values():
            reason=f['reason'];choice=f.pop('forecast')
            if not reason and choice is None:reason='No retained pre-match forecast'
            if not reason:
                meta,c=choice['source'],choice['candidate'];prob=[(c.get('ladder') or {}).get(k) for k in ('h1','d','a1')]
                if c.get('result') is not None:reason='Forecast already contains a result'
                elif c.get('score_basis') not in (None,'90min') or f['kind']=='cup' and c.get('score_basis')!='90min':reason='90-minute forecast basis not established'
                elif not probability(prob):reason='Invalid H/D/A probabilities'
                elif not meta['fitted_through'] or meta['fitted_through']>=f['kickoff'][:10]:reason='Training cutoff not before match day'
            if reason:
                exclusions.append({**f,'reason':reason,'source':choice['source'] if choice else None});continue
            try:
                gen=datetime.fromisoformat(meta['generated'].replace('Z','+00:00'))
                timing='pre_kickoff' if gen.tzinfo is not None and gen<instant(f['kickoff'],f['competition']) else 'retrospective' if gen.tzinfo is not None else 'unknown'
            except (ValueError,TypeError,AttributeError):timing='unknown'
            f.pop('reason',None);f.update(prob=prob,source=meta,timing=timing,model=meta['model'],scores=scores(prob,f['result']),baselines={'uniform':[1/3]*3,'historical':bases.get(f['kind'],{}).get('prob')})
            f['baseline_scores']={k:scores(v,f['result']) if v else None for k,v in f['baselines'].items()};evaluated.append(f)
        order=lambda f:(f['uk_day'] if 'uk_day' in f else f['kickoff'][:10],f['competition'],f['home'],f['away'],f['id'])
        evaluated.sort(key=order);exclusions.sort(key=order);counts=Counter(r['reason'] for r in exclusions);timings=Counter(r['timing'] for r in evaluated)
        assert len(evaluated)+len(exclusions)==len(fixtures)
        cohorts={timing:summary([r for r in evaluated if r['timing']==timing]) for timing in ('pre_kickoff','retrospective','unknown')}
        return {'schema':1,'source':selected['source'],'season':season,'as_of':cutoff,'current_model':selected.get('model') or 'unstamped','fixtures':evaluated,'exclusions':exclusions,'snapshots':snapshots,'archive_issues':health,
                'coverage':{'played':len(fixtures),'evaluated':len(evaluated),'excluded':len(exclusions),'reasons':dict(counts),'timings':dict(timings)},'cohorts':cohorts,
                'training':{'first_season':2021,'last_season':season-1,'last_kickoff':training_last.isoformat() if training_last else None,'evaluation_starts':start.isoformat() if start else None,'excluded':dict(training_excluded),'by_kind':bases},
                'notice':'Rebuilt forecasts are retrospective reconstruction, not a prospective or untouched held-out model test. Retained results may include provider revisions. 90-minute outcomes only; extra-time aggregate ties use the retained first-leg margin, never the final tie winner. Unresolved results are excluded. No score-grid overflow bins are treated as exact scores.'}
