"""Isolated multi-fixture conditioning by rejection of complete ordinary simulated worlds.

No match is overwritten. An accepted world's latent npxG, goals, feedback, cups and rights are
exactly those drawn by the production simulator. All new tallies are integers; no files publish.
"""
from __future__ import annotations
import hashlib
import json
import math
import multiprocessing as mp
import time
from pathlib import Path
import numpy as np
import pandas as pd
from scripts import projection as p
from scripts.europe_places import seat_world
from scripts.cup_bracket import cup_handovers

METRICS = ('points','position','title','ucl','uel','uecl','relegation')
MIN_ACCEPTED = 100


def fixture_key(competition, season, kickoff, home, away):
    raw=json.dumps([str(competition),int(season),str(kickoff),str(home),str(away)],ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def accepts(scores, conditions):
    """`scores` maps exact fixture keys to ordinary regulation home/away goals."""
    for c in conditions:
        if c['fixture'] not in scores:return False
        h,a=scores[c['fixture']]
        if c['outcome']=='score':
            if [int(h),int(a)]!=c['score']:return False
        elif ('home' if h>a else 'away' if a>h else 'draw')!=c['outcome']:return False
    return True


class Tally:
    def __init__(self, teams):
        self.teams=tuple(teams);n=len(teams);self.worlds=0
        self.sums=np.zeros((n,len(METRICS)),np.int64)
        self.squares=np.zeros_like(self.sums)
        self.points=np.zeros((n,p.MAX_PTS),np.int64)
        self.positions=np.zeros((n,n),np.int64)
        self.above=np.zeros((n,n),np.int64)

    def add(self, evidence):
        values=np.asarray(evidence,dtype=np.int64);n=len(self.teams)
        if values.shape!=(n,len(METRICS)):raise ValueError('Scenario evidence shape differs')
        pts,pos=values[:,0],values[:,1]
        if not np.array_equal(np.sort(pos),np.arange(1,n+1)) or (pts<0).any() or (pts>=p.MAX_PTS).any():
            raise ValueError('Scenario requires complete final orders and supported integer points')
        if not np.isin(values[:,2:],[0,1]).all() or values[:,2].sum()!=1 or (values[:,3:6].sum(axis=1)>1).any():
            raise ValueError('Invalid title or mutually exclusive entry evidence')
        self.sums+=values;self.squares+=values*values
        self.points[np.arange(n),pts]+=1;self.positions[np.arange(n),pos-1]+=1
        self.above+=(pos[:,None]<pos[None,:]);self.worlds+=1

    def merge(self,other):
        if self.teams!=other.teams:raise ValueError('Cannot merge different scenario team orders')
        for key in ('sums','squares','points','positions','above'):getattr(self,key)[:]+=getattr(other,key)
        self.worlds+=other.worlds;return self

    def validate(self):
        n,w=len(self.teams),self.worlds
        if not w:return
        if (not (self.points.sum(axis=1)==w).all() or not (self.positions.sum(axis=1)==w).all()
            or not (self.positions.sum(axis=0)==w).all() or self.sums[:,2].sum()!=w
            or not np.array_equal(self.above+self.above.T,(1-np.eye(n,dtype=int))*w)
            or not np.array_equal(self.above.sum(axis=1),self.positions@np.arange(n-1,-1,-1))
            or not np.array_equal(self.sums[:,0],self.points@np.arange(p.MAX_PTS))
            or not np.array_equal(self.squares[:,0],self.points@(np.arange(p.MAX_PTS)**2))
            or not np.array_equal(self.sums[:,1],self.positions@np.arange(1,n+1))
            or not np.array_equal(self.squares[:,1],self.positions@(np.arange(1,n+1)**2))
            or not np.array_equal(self.sums[:,2:],self.squares[:,2:])
            or (self.sums[:,2:]<0).any() or (self.sums[:,2:]>w).any()
            or (self.sums[:,3:6].sum(axis=1)>w).any()):
            raise ValueError('Scenario sample accounting failed')


def paired_se(total_sum,total_sq,n,accepted_sum,accepted_sq,m):
    """Paired delta standard error for a conditional mean minus its nested baseline.

    Uses the rejection estimator influence A/pi*(X-q) - (X-p). Group-centred moments avoid
    subtracting near-equal large variance terms. Same accepted/proposal populations throughout.
    """
    x=np.asarray(total_sum,dtype=float);xx=np.asarray(total_sq,dtype=float)
    y=np.asarray(accepted_sum,dtype=float);yy=np.asarray(accepted_sq,dtype=float)
    if m==n:return np.zeros_like(x)
    if m<2 or n-m<1:return np.full_like(x,np.nan)
    pi=m/n;mean=x/n;cond=y/m;rest=(x-y)/(n-m)
    va=yy/m-cond*cond;vr=(xx-yy)/(n-m)-rest*rest
    if (va < -1e-8).any() or (vr < -1e-8).any():raise ValueError('Invalid paired sample moments')
    va=np.maximum(va,0);vr=np.maximum(vr,0)
    influence=pi*((1/pi-1)**2*va+(mean-cond)**2)+(1-pi)*(vr+(mean-rest)**2)
    return np.sqrt(influence/(n-1))


def summary(baseline,conditional,minimum=MIN_ACCEPTED):
    baseline.validate();conditional.validate();n,m=baseline.worlds,conditional.worlds
    if n<1 or m>n:raise ValueError('Invalid proposal/accepted populations')
    usable=m>=minimum;out=dict(proposals=n,accepted=m,effective_sample_size=m,
        acceptance=m/n,acceptance_se=math.sqrt((m/n)*(1-m/n)/n),usable=usable,minimum_accepted=minimum,
        teams=[],rivals=None)
    se=paired_se(baseline.sums,baseline.squares,n,conditional.sums,conditional.squares,m) if usable else None
    for i,team in enumerate(baseline.teams):
        row={'team':team,'baseline':{},'scenario':{} if usable else None,'delta':{} if usable else None,'paired_se':{} if usable else None}
        for k,key in enumerate(METRICS):
            row['baseline'][key]=float(baseline.sums[i,k]/n)
            if usable:
                row['scenario'][key]=float(conditional.sums[i,k]/m)
                row['delta'][key]=row['scenario'][key]-row['baseline'][key]
                row['paired_se'][key]=float(se[i,k])
        row['points']={'baseline':baseline.points[i].tolist(),'scenario':conditional.points[i].tolist() if usable else None}
        row['position']={'baseline':baseline.positions[i].tolist(),'scenario':conditional.positions[i].tolist() if usable else None}
        out['teams'].append(row)
    out['teams'].sort(key=lambda r:(r['baseline']['position'],r['team']))
    if usable:
        out['rivals']={'teams':list(baseline.teams),'baseline':(baseline.above/n).tolist(),
                       'scenario':(conditional.above/m).tolist(),
                       'paired_se':paired_se(baseline.above,baseline.above,n,conditional.above,conditional.above,m).tolist()}
    else:out['refusal']=f'Only {m} matching worlds out of {n}. At least {minimum} are needed; increase the world budget or use more common assumptions.'
    return out


def prepare_context(params,competition,conditions):
    engine=p.Engine();prep=p.prepare_for(engine,params);fx=prep['fixtures']
    league_teams={comp:pd.Index(sorted(set(g.home)|set(g.away))) for comp,g in fx[fx.kind=='league'].groupby('competition')}
    if competition not in league_teams:raise ValueError('Unsupported scenario competition')
    policies={comp:{**meta['qualification']['base'],**{k:meta['qualification'][k] for k in ('eps','ucl_direct','cup','league_cup')}}
              for comp,meta in prep['places'].items() if meta.get('qualification',{}).get('mode')=='per_world'}
    if set(league_teams)-set(policies):raise ValueError('Scenario requires complete per-world European-entry policies')
    affiliations={t:comp for comp,teams in league_teams.items() for t in teams}
    for comp,policy in policies.items():
        cup_fx=fx[fx.competition.isin([v for v in (policy['cup'],policy['league_cup']) if v])]
        for t in set(cup_fx.home)|set(cup_fx.away):affiliations.setdefault(t,comp)
    fixture_ids={}
    wanted={c['fixture'] for c in conditions}
    for row in fx[fx.kind=='league'].itertuples():
        key=fixture_key(row.competition,row.season,row.kickoff,row.home,row.away)
        if key in wanted:
            if row.played or row.tbd or str(row.kickoff)[:10]<str(prep['cutoff'].date()):raise ValueError('Assumed fixture is no longer future/unplayed')
            fixture_ids[int(row.Index)]=key
    if set(fixture_ids.values())!=wanted:raise ValueError('Selected fixtures no longer match the retained simulation inputs')
    hands,_=p.build_handovers(engine,fx,params)
    return dict(engine=engine,prep=prep,fx=fx,hands=hands,cups=cup_handovers(fx,engine.master,np.random.default_rng(params['seed'])),
                unseen=p.unseen_for(prep,fx,params),league_teams=league_teams,policies=policies,affiliations=affiliations,
                fixture_ids=fixture_ids,competition=competition,conditions=conditions)


def reduce_world(sim,ctx):
    attrs,sim.attrs=sim.attrs,{}
    try:
        league=sim[sim.phase=='league'];tables={}
        for comp,teams in ctx['league_teams'].items():
            g=league[league.competition==comp]
            if g.empty:raise ValueError('Incomplete simulated league')
            tables[comp]=p.final_table(g,teams)
        champions={comp:str(ctx['league_teams'][comp][int(np.argmin(tbl['position']))]) for comp,tbl in tables.items()}
        for family in ('cups','knockout'):
            for (comp,_),report in attrs.get(family,{}).items():
                if report.get('champion'):champions[comp]=report['champion']
        orders={comp:list(ctx['league_teams'][comp][np.argsort(tbl['position'])]) for comp,tbl in tables.items()}
        seats=seat_world(orders,champions,ctx['policies'],ctx['affiliations'])[ctx['competition']]
        teams=ctx['league_teams'][ctx['competition']];tbl=tables[ctx['competition']];rel=3 if len(teams)>=18 else 2
        values=np.c_[tbl['pts'].astype(int),tbl['position'],tbl['position']==1,
                       [[t in seats[k] for k in ('ucl','uel','uecl')] for t in teams],tbl['position']>len(teams)-rel].astype(np.int64)
        scores={ctx['fixture_ids'][int(r.fixture_id)]:(int(r.home_goals),int(r.away_goals)) for r in league.itertuples() if int(r.fixture_id) in ctx['fixture_ids']}
        return values,accepts(scores,ctx['conditions'])
    finally:sim.attrs=attrs


_WORKER={}


def _init_worker(params,competition,conditions):
    _WORKER.clear();_WORKER.update(params=params,competition=competition,conditions=conditions,ctx=None)


def _chunk(bounds):
    if _WORKER['ctx'] is None:_WORKER['ctx']=prepare_context(_WORKER['params'],_WORKER['competition'],_WORKER['conditions'])
    ctx=_WORKER['ctx'];teams=ctx['league_teams'][ctx['competition']];base=Tally(teams);accepted=Tally(teams)
    for i in range(*bounds):
        world=p._simulate_world(ctx,_WORKER['params'],i);values,keep=reduce_world(world,ctx)
        base.add(values)
        if keep:accepted.add(values)
    return base,accepted


class Cancelled(Exception):pass


def run(params,competition,conditions,processes=1,progress=None,cancel=None,minimum=MIN_ACCEPTED):
    """Fixed proposal budget; bounded in-memory reduction, cancellation never publishes partials."""
    n=int(params['worlds']);processes=max(1,min(int(processes),4));total=accepted=None
    def report(stage):
        if cancel and cancel():raise Cancelled()
        if progress:progress(total.worlds if total else 0,n,accepted.worlds if accepted else 0,stage)
    def merge(pair):
        nonlocal total,accepted
        b,a=pair
        if total is None:total,accepted=Tally(b.teams),Tally(b.teams)
        total.merge(b);accepted.merge(a);report('simulating')
    report('preparing')
    if processes==1:
        _init_worker(params,competition,conditions)
        for i in range(n):
            report('simulating');merge(_chunk((i,i+1)))
    else:
        pool=mp.get_context('spawn').Pool(processes,initializer=_init_worker,initargs=(params,competition,conditions))
        try:
            chunks=pool.imap_unordered(_chunk,[(i,min(i+8,n)) for i in range(0,n,8)])
            remaining=(n+7)//8
            while remaining:
                report('simulating')
                try:pair=chunks.next(timeout=.2)
                except mp.TimeoutError:continue
                merge(pair);remaining-=1
            pool.close();pool.join()
        finally:pool.terminate();pool.join()
    report('finishing')
    return summary(total,accepted,minimum)
