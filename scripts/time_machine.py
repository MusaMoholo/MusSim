"""Stored-only two-date forecast bridges. No current master/provider/model dependencies."""
from __future__ import annotations
import gzip
import hashlib
import json
import math
import re
import threading
from decimal import Decimal
from pathlib import Path

PROBABILITIES=('p_win','p_ucl','p_uel','p_uecl','p_releg')


class TimeMachineError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


def numeric(value):return type(value) in (int,float) and math.isfinite(value)


def difference(a,b):return float(Decimal(str(b))-Decimal(str(a))) if numeric(a) and numeric(b) else None


def bridge(a,b):
    if a is None or b is None:return None
    if any(not numeric(row.get(key)) for row in (a,b) for key in ('banked','expected_final','expected_remaining')):return None
    exact={}
    for row in (a,b):
        remaining=Decimal(str(row['expected_final']))-Decimal(str(row['banked']))
        if abs(remaining-Decimal(str(row['expected_remaining'])))>Decimal('0.0000000001'):
            raise TimeMachineError('Stored points bridge does not reconcile.',409)
    exact['banked']=Decimal(str(b['banked']))-Decimal(str(a['banked']))
    exact['expected_final']=Decimal(str(b['expected_final']))-Decimal(str(a['expected_final']))
    exact['expected_remaining']=(Decimal(str(b['expected_final']))-Decimal(str(b['banked'])))-(Decimal(str(a['expected_final']))-Decimal(str(a['banked'])))
    error=exact['expected_final']-exact['banked']-exact['expected_remaining']
    if error:raise TimeMachineError('Stored points bridge does not reconcile.',409)
    return {**{k:float(v) for k,v in exact.items()},'exact':{k:str(v) for k,v in exact.items()},'residual':float(error)}


def metadata(p,day,sha):
    cutoff=p.get('as_of');season=(p.get('params') or {}).get('season')
    if not isinstance(cutoff,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',cutoff) or type(season) is not int or cutoff>day:raise TimeMachineError('Snapshot season/cutoff unavailable.',409)
    generated=p.get('generated');timing='unknown'
    if isinstance(generated,str) and re.match(r'^\d{4}-\d{2}-\d{2}T',generated):timing='rebuilt_later' if generated[:10]>day else 'same_day' if generated[:10]==day else 'earlier_generation'
    return {'date':day,'as_of':cutoff,'season':season,'model':p.get('model'),'payload':p.get('version',1),
            'worlds':p.get('worlds'),'generated':generated,'timing':timing,'projection_sha256':sha,'params':p.get('params',{})}


def compact(p,day,sha):
    meta=metadata(p,day,sha);issues=[];blocks={}
    # Scan all stored scalar team probabilities, including known-invalid cup fields outside a selected league.
    for category in ('leagues','uefa','cups'):
        for block in p.get(category,[]):
            for team in block.get('teams',[]):
                for key,value in team.items():
                    if key.startswith('p_') and value is not None and (not numeric(value) or not 0<=value<=1):
                        issues.append({'date':day,'competition':block['competition'],'team':team['team'],'field':key,'value':value,'reason':'Invalid probability; excluded.'})
    ratings={r['team']:r for r in (p.get('ratings') or {}).get('teams',[])}
    scales=(p.get('ratings') or {}).get('rel') or {}
    for block in p.get('leagues',[]):
        comp=block['competition'];rows={};factor=(scales.get(comp) or {}).get('now')
        scale_ok=isinstance(factor,list) and len(factor)==2 and all(numeric(v) and v>0 for v in factor)
        for t in block.get('teams',[]):
            team=t['team']
            if team in rows:raise TimeMachineError('Duplicate team identity in stored league.',409)
            now=t.get('now') or {};real=t.get('real') or {};banked=now.get('pts',real.get('pts'));played=now.get('pl',real.get('pl'))
            if banked is not None and (not numeric(banked) or banked<0):
                issues.append({'date':day,'competition':comp,'team':team,'field':'banked','value':banked,'reason':'Invalid stored points.'});banked=None
            if numeric(now.get('pts')) and numeric(real.get('pts')) and now['pts']!=real['pts']:
                issues.append({'date':day,'competition':comp,'team':team,'field':'banked','value':[now['pts'],real['pts']],'reason':'Conflicting stored banked points.'});banked=None
            final=t.get('mean_pts')
            if not numeric(final):final=None
            remaining=difference(banked,final)
            if remaining is not None and remaining<0:
                issues.append({'date':day,'competition':comp,'team':team,'field':'expected_remaining','value':remaining,'reason':'Expected final points below banked points.'});remaining=None
            row={'team':team,'banked':banked,'played':played if numeric(played) else None,'expected_final':final,'expected_remaining':remaining,
                 'mean_position':t.get('mean_pos') if numeric(t.get('mean_pos')) else None,'goals_for':now.get('gf',real.get('gf')),'goals_against':now.get('ga',real.get('ga'))}
            for key in PROBABILITIES:
                v=t.get(key);row[key]=v if numeric(v) and 0<=v<=1 else None
            r=ratings.get(team) or {};att=r.get('att');defence=r.get('def');ok=all(numeric(v) and v>0 for v in (att,defence))
            row['strength']={'elo':r.get('elo') if numeric(r.get('elo')) else None,
                'five_leagues':{'att':att,'def':defence,'net':difference(defence,att)} if ok else None,
                'competition':{'att':att*factor[0],'def':defence*factor[1],'net':difference(defence*factor[1],att*factor[0])} if ok and scale_ok else None}
            rows[team]=row
        blocks[comp]=rows
    return {'meta':meta,'leagues':blocks,'issues':issues}


def points(f,team):
    if f is None:return 0
    h,a=f['result'];own,other=(h,a) if f['home']==team else (a,h)
    return 3 if own>other else 1 if own==other else 0


def fixture_identity(f):return '|'.join([f['competition'],f['home'],f['away'],f['kickoff'][:10]])


class TimeMachine:
    def __init__(self,snapshots):self.snaps=snapshots;self.lock=threading.Lock();self.files={}

    def _archive(self,day,revision):
        index=self.snaps.root/'index.json';index_sha=hashlib.sha256(index.read_bytes()).hexdigest() if index.exists() else None
        listed=sorted({r['date'] for r in self.snaps.list()});available={d for d in listed if d<=str(day)}
        if day not in available:raise TimeMachineError('Choose an available dashboard snapshot.',404)
        snapshots={};refs={str(index):index_sha}
        for date in sorted(available):
            path=self.snaps.root/date/'projection.json'
            if not path.exists():raise TimeMachineError('A listed historical snapshot is missing.',409)
            raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest();refs[str(path)]=sha
            with self.lock:item=self.files.get((date,sha))
            if item is None:
                item=compact(json.loads(raw),date,sha)
                with self.lock:
                    self.files[(date,sha)]=item
                    while len(self.files)>128:self.files.pop(next(iter(self.files)))
            snapshots[date]=item
        anchor=snapshots[day]
        if not revision or revision!=anchor['meta']['projection_sha256']:raise TimeMachineError('The pinned dashboard snapshot changed. Reload it.',409)
        season=anchor['meta']['season'];snapshots={d:s for d,s in snapshots.items() if s['meta']['season']==season}
        return snapshots,refs,anchor

    def _verify(self,refs):
        for name,sha in refs.items():
            path=Path(name);actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if actual!=sha:raise TimeMachineError('Stored history changed during the read. Reload Time Machine.',409)

    def catalog(self,day,revision):
        snapshots,refs,anchor=self._archive(day,revision);self._verify(refs)
        return {'schema':1,'source':anchor['meta'],'dates':[{**s['meta'],'competitions':list(s['leagues']),'invalid_cells':len(s['issues'])} for s in snapshots.values()],
                'notice':'Stored snapshot evidence only. Folder date and data cutoff are different. Later rebuilds do not establish what was published at the time.'}

    def _fixtures(self,meta,competition,refs):
        folder=self.snaps.root/meta['date'];packed,plain=folder/'gw.json.gz',folder/'gw.json'
        for path in (packed,plain):refs[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        path=packed if packed.exists() else plain if plain.exists() else None
        if path is None:return None
        raw=path.read_bytes();body=gzip.decompress(raw) if path==packed else raw
        block=json.loads(body).get('leagues',{}).get(competition)
        if block is None:return None
        out={}
        for f in block.get('fixtures',[]):
            if f.get('result') is None:continue
            score=f['result'];stamp=f.get('kickoff','')
            if not isinstance(score,list) or len(score)!=2 or any(type(v) is not int or v<0 for v in score):raise TimeMachineError('Invalid stored league fixture score.',409)
            if stamp[:10]>meta['as_of']:raise TimeMachineError('Stored fixture result exceeds its snapshot cutoff.',409)
            item={key:f[key] for key in ('home','away','kickoff')};item.update(competition=competition,result=score,xg=f.get('xg'),round=f.get('round'))
            key=fixture_identity(item)
            if key in out:raise TimeMachineError('Duplicate stored fixture identity.',409)
            out[key]=item
        return out

    def compare(self,day,revision,a,ap,b,bp,competition):
        snapshots,refs,anchor=self._archive(day,revision)
        for date,pin in ((a,ap),(b,bp)):
            if date not in snapshots:raise TimeMachineError('Both dates must be available in this season at or before the dashboard snapshot.',400)
            if not pin or snapshots[date]['meta']['projection_sha256']!=pin:raise TimeMachineError('An endpoint revision changed. Reload the date catalogue.',409)
            if competition not in snapshots[date]['leagues']:raise TimeMachineError('Choose a league covered on both dates.',400)
        before,after=snapshots[a],snapshots[b];left,right=before['leagues'][competition],after['leagues'][competition]
        names=sorted(set(left)|set(right));rows=[]
        for team in names:
            x,y=left.get(team),right.get(team);delta={key:difference(x.get(key),y.get(key)) if x and y else None for key in ('banked','expected_final','expected_remaining','mean_position',*PROBABILITIES)}
            points_bridge=bridge(x,y)
            if points_bridge:delta.update({key:points_bridge[key] for key in ('banked','expected_final','expected_remaining')})
            rows.append({'team':team,'before':x,'after':y,'delta':delta,'bridge':points_bridge})
        rows.sort(key=lambda r:(-(r['after'] or {}).get('banked') if numeric((r['after'] or {}).get('banked')) else math.inf,r['team']))
        ga,gb=self._fixtures(before['meta'],competition,refs),self._fixtures(after['meta'],competition,refs)
        ledger=None;reconciliation=[]
        if ga is not None and gb is not None:
            ledger=[]
            for key in sorted(set(ga)|set(gb)):
                x,y=ga.get(key),gb.get(key)
                if x==y:continue
                f=y or x;deltas={team:points(y,team)-points(x,team) for team in (f['home'],f['away'])}
                ledger.append({'id':hashlib.sha256(key.encode()).hexdigest()[:24],'fixture':key,'home':f['home'],'away':f['away'],'competition':competition,
                    'kickoff':f['kickoff'],'before':x,'after':y,'points_delta':deltas,'change':'added' if x is None else 'removed' if y is None else 'revised',
                    'evidence_date':b if y else a,'evidence_revision':bp if y else ap})
            ledger.sort(key=lambda f:(f['kickoff'],f['home'],f['away'],f['id']))
            for row in rows:
                team=row['team'];counts={}
                for label,fixtures,source in [('before',ga,row['before']),('after',gb,row['after'])]:
                    played=[f for f in fixtures.values() if team in (f['home'],f['away'])];total=sum(points(f,team) for f in played)
                    counts[label]={'fixtures':len(played),'match_points':total,'stored_banked':source.get('banked') if source else None,
                        'points_difference':difference(total,source.get('banked')) if source else None,
                        'played_difference':difference(len(played),source.get('played')) if source else None}
                total=sum(f['points_delta'].get(team,0) for f in ledger);d=row['delta']['banked']
                reconciliation.append({'team':team,**counts,'ledger_points_delta':total,'banked_delta':d,'delta_gap':difference(total,d),
                    'valid':all(counts[k]['points_difference']==0 and counts[k]['played_difference']==0 for k in ('before','after')) and difference(total,d)==0})
        lo,hi=sorted((a,b));timeline=[{'meta':s['meta'],'teams':s['leagues'].get(competition,{})} for d,s in snapshots.items() if lo<=d<=hi]
        issues=[issue for d,s in snapshots.items() if lo<=d<=hi for issue in s['issues']]
        self._verify(refs)
        return {'schema':1,'source':anchor['meta'],'competition':competition,'before':before['meta'],'after':after['meta'],'rows':rows,'timeline':timeline,
            'ledger':ledger,'reconciliation':reconciliation,'issues':issues,
            'changes':{'model':before['meta']['model']!=after['meta']['model'],'payload':before['meta']['payload']!=after['meta']['payload'],
                       'params':[k for k in sorted(set(before['meta']['params'])|set(after['meta']['params'])) if before['meta']['params'].get(k)!=after['meta']['params'].get(k)]},
            'input_revision':hashlib.sha256(json.dumps(refs,sort_keys=True).encode()).hexdigest(),
            'input_files':{str(Path(k).relative_to(self.snaps.root)):v for k,v in refs.items()},
            'notice':'Coincident forecast changes are not causal match attribution. The points bridge uses stored snapshot precision. Fixture changes come only from the two stored GW files; no current provider or master data is used.'}
