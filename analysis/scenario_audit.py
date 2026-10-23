"""Conditional-law proof, independent reference tallies, exact parallelism and cost; no publishing."""
from __future__ import annotations
import argparse,copy,json,sys,time
from fractions import Fraction as F
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import scenario_lab as s
from scripts.scenario_store import catalog,validate,ScenarioError
from scripts.dashboard_store import Snapshots


def exact_reference():
    # An exactly soluble evolving latent-state match law: npxG -> goals -> feedback -> npxG.
    worlds=[]
    for latent in (0,1):
      h1=F(1+2*latent,4)
      for x1 in (1,2):
       for g1 in (0,1):
        q=latent+g1;h2=F(q+1,4)
        for x2 in (1,2):
         for g2 in (0,1):
          weight=F(1,2)*(h1 if x1==2 else 1-h1)*(F(x1,3) if g1 else 1-F(x1,3))*(h2 if x2==2 else 1-h2)*(F(x2,3) if g2 else 1-F(x2,3))
          worlds.append(dict(latent=latent,xg2=x2,state=q,scores={'first':(g1,0),'second':(g2,0)},weight=weight))
    conditions=[{'fixture':'first','outcome':'score','score':[1,0]},{'fixture':'second','outcome':'draw'}]
    accepted=[w for w in worlds if s.accepts(w['scores'],conditions)];z=sum(w['weight'] for w in accepted)
    assert sum(w['weight'] for w in worlds)==1 and z==F(65,288)
    assert sum(w['weight']*w['latent'] for w in accepted)/z==F(7,13)
    assert sum(w['weight']*w['state'] for w in accepted)/z==F(20,13)
    assert sum(w['weight']*w['xg2'] for w in accepted)/z==F(96,65)
    assert all(s.accepts(w['scores'],[]) for w in worlds)
    wrong=[{**w,'scores':{'first':(1,0),'second':(0,0)}} for w in worlds]
    assert sum(w['weight']*w['latent'] for w in wrong)==F(1,2)!=F(7,13)
    print('PASS exact32-world evolving-state law:joint normalizer65/288,posterior latent7/13,state20/13,npxG96/65;forced-score fault disagrees')
    # Direct per-proposal influence vectors are independent of the sufficient-moment formula.
    x=np.asarray([0,3,1,0,3,1,3,0,1,3,0,1.],float);a=np.asarray([0,1,1,0,1,0,1,0,0,1,0,0],bool)
    n,m=len(x),a.sum();p,q=x.mean(),x[a].mean();influence=a/(m/n)*(x-q)-(x-p)
    expected=float(influence.std(ddof=1)/np.sqrt(n));actual=float(s.paired_se(x.sum(),(x*x).sum(),n,x[a].sum(),(x[a]**2).sum(),m))
    assert abs(expected-actual)<1e-12 and expected>0
    assert s.paired_se(x.sum(),(x*x).sum(),n,x.sum(),(x*x).sum(),n)==0
    assert abs(float(s.paired_se(x.sum(),(x*x).sum(),n,x[a].sum(),(x[a]**2).sum(),m+1))-expected)>1e-4
    print('PASS paired Monte CarloSE equals direct influence variance;identity assumption gives zero;wrong-denominator fault fails')


def request_cases(cat):
    base=dict(date=cat['source']['date'],revision=cat['source']['projection_sha256'],input_revision=cat['input_revision'],competition=cat['competitions'][0],worlds=200,seed=1)
    fixture=cat['fixtures'][0]['id'];condition={'fixture':fixture,'outcome':'home'}
    for conditions in [[condition,{'fixture':fixture,'outcome':'away'}],[condition,{'fixture':fixture,'outcome':'score','score':[0,0]}],[{'fixture':'unknown','outcome':'draw'}],[{'fixture':fixture,'outcome':'score','score':[1.5,0]}]]:
        try:validate({**base,'conditions':conditions},cat)
        except ScenarioError:pass
        else:raise AssertionError('Impossible/invalid condition accepted')
    assert validate({**base,'conditions':[condition,{'fixture':fixture,'outcome':'score','score':[2,0]}]},cat)['conditions']==[{'fixture':fixture,'outcome':'score','score':[2,0]}]
    print('PASS four contradiction/identity/score cases reject before simulation;compatible duplicates collapse to one exact event')


def real_reference(cat,worlds):
    from scripts import projection as p
    comp='English Premier League';params={**cat['params'],'worlds':worlds,'seed':1}
    fixtures=[f for f in cat['fixtures'] if f['competition']==comp][:2]
    conditions=[{'fixture':fixtures[0]['id'],'outcome':'home'},{'fixture':fixtures[1]['id'],'outcome':'draw'}]
    ctx=s.prepare_context(params,comp,conditions);fx=ctx['fx'];track,nxt=p.tracked_fixtures(fx)
    reference=p.Accumulator(fx,track,p.first_pending_stages(ctx['hands'],p.match_horizon(fx)),nxt,places=ctx['prep']['places'],race_competition=comp)
    base=s.Tally(ctx['league_teams'][comp]);accepted=s.Tally(base.teams);single=s.Tally(base.teams)
    observed=[];timing={'simulation':0.,'reduction':0.}
    for i in range(worlds):
        t=time.perf_counter();world=p._simulate_world(ctx,params,i);timing['simulation']+=time.perf_counter()-t
        t=time.perf_counter();values,keep=s.reduce_world(world,ctx);base.add(values)
        if keep:accepted.add(values)
        first_id=next(fid for fid,key in ctx['fixture_ids'].items() if key==conditions[0]['fixture'])
        first=world[(world.fixture_id==first_id)&(world.phase=='league')].iloc[0]
        if first.home_goals>first.away_goals:single.add(values)
        timing['reduction']+=time.perf_counter()-t
        reference.add(world,world_index=i);observed.append(keep)
    original=reference.leagues[comp]
    assert np.array_equal(base.points,original['pts']) and np.array_equal(base.positions,original['pos'])
    assert np.array_equal(base.above,reference.rivals[comp].gaps[:,:,len(base.teams):].sum(axis=2))
    for i,team in enumerate(base.teams):
        assert np.array_equal(base.sums[i,3:6],reference.europe_counts[team])
    first_slot=int(reference.fx_pos[first_id]);whatif=int(reference.whatif_pos[first_slot]);assert whatif>=0
    expected=np.c_[single.sums[:,2],single.sums[:,3],single.sums[:,3:6].sum(axis=1),single.sums[:,6]]
    assert np.array_equal(expected,reference.fx_whatif[whatif,0,:len(base.teams),:])
    assert single.worlds==int(np.tril(reference.fx_counts[first_slot],-1).sum())>0
    print('PASS single-match title/UCL/Europe/relegation conditionals exactly match existing production what-if counts and normalizer')
    assert accepted.worlds==sum(observed) and len(conditions)==2
    serial=s.summary(base,accepted,minimum=2)
    parallel=s.run(params,comp,conditions,processes=4,minimum=2)
    assert serial==parallel,'Serial/four-process scientific results differ'
    empty=s.run({**params,'worlds':8},comp,[],processes=1,minimum=2)
    assert all(all(v==0 for v in row['delta'].values()) and all(v==0 for v in row['paired_se'].values()) for row in empty['teams'])
    rare=s.summary(base,s.Tally(base.teams));assert not rare['usable'] and rare['rivals'] is None and all(t['scenario'] is None for t in rare['teams'])
    broken=copy.deepcopy(base);broken.above[0,1]+=1
    try:broken.validate()
    except ValueError:pass
    else:raise AssertionError('Count fault escaped validation')
    try:s.run(params,comp,conditions,cancel=lambda:True)
    except s.Cancelled:pass
    else:raise AssertionError('Pre-start cancellation failed')
    print('PASS full-world league histogram/positions/rivals/entry marginals equal production accumulator;two conditions;serial/four-process exact;empty baseline identity;rare-event refusal;count fault and cancellation')
    print(json.dumps(dict(worlds=worlds,accepted=accepted.worlds,**timing,ms_reduction_per_world=timing['reduction']*1000/worlds,
                          count_array_bytes=sum(v.nbytes for v in vars(base).values() if isinstance(v,np.ndarray))),indent=2))
    return serial,conditions


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worlds',type=int,default=64);parser.add_argument('--output',type=Path);a=parser.parse_args()
    if a.output:assert not a.output.exists() and ROOT/'data' not in a.output.resolve().parents
    exact_reference();snaps=Snapshots();payload=snaps.load();cat=catalog(snaps,payload['source']['date'],payload['source']['projection_sha256']);assert cat['available'],cat
    request_cases(cat);out,conditions=real_reference(cat,a.worlds)
    if a.output:a.output.write_text(json.dumps(dict(result=out,conditions=conditions,catalog=cat)))

if __name__=='__main__':main()
