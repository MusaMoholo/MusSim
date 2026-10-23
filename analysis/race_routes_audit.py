"""Profile draft exclusive routes against unchanged entry allocations; no publication.

.venv/bin/python analysis/race_routes_audit.py --worlds 100 --output /private/tmp/routes-review.json
"""
from __future__ import annotations
import argparse, copy, gzip, json, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import projection as p
from scripts.europe_places import seat_world, qualification_policies, UCL, UEL, UECL
from scripts.race_routes import RouteTally, exclusive_routes
COMP='English Premier League'


def specified_cases():
    order=list('ABCDEFGHIJ');policy=qualification_policies(2026)[COMP]
    cases=[({}, {'A':('ucl','league'),'E':('ucl','eps'),'F':('uel','league'),'H':('uecl','league')}),
           ({policy['cup']:'G',policy['league_cup']:'I'}, {'G':('uel','cup'),'I':('uecl','league_cup')}),
           ({UCL:'H'}, {'H':('ucl','ucl_holder'),'E':('ucl','eps')}),
           ({UEL:'E'}, {'E':('ucl','uel_holder'),'F':('ucl','eps')}),
           ({UECL:'F'}, {'F':('uel','league')}),
           ({UECL:'I'}, {'I':('uel','uecl_holder')}),
           ({UECL:'I',policy['cup']:'I'}, {'I':('uel','cup')}),
           ({UECL:'I',policy['league_cup']:'I'}, {'I':('uel','uecl_holder')}),
           ({policy['cup']:'Outside'}, {'Outside':('uel','cup')})]
    for champions,expected in cases:
        seats=seat_world({COMP:order},champions,{COMP:policy},{t:COMP for t in order})[COMP]
        actual=exclusive_routes(order,policy,champions,seats)
        assert all(actual.get(t)==route for t,route in expected.items()), (champions,expected,actual)
        assert len(actual)==sum(map(len,seats.values()))
        tally=RouteTally(order);tally.add(order,policy,champions,seats)
        tally.validate({t:np.asarray([int(t in seats[k]) for k in ('ucl','uel','uecl')]) for t in actual})
    print('PASS 9 independently specified league/EPS/cup/holder/overlap/outside-club cases')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--worlds',type=int,default=100);ap.add_argument('--output',type=Path);args=ap.parse_args()
    assert args.worlds>=8
    if args.output:assert not args.output.exists() and ROOT/'data' not in args.output.resolve().parents
    specified_cases()
    params=p.coerce_params(dict(season=2026,worlds=args.worlds),2026)
    engine=p.Engine();prep=p.prepare_for(engine,params);fx=prep['fixtures'];hands,_=p.build_handovers(engine,fx,params)
    cups=p.cup_handovers(fx,engine.master,np.random.default_rng(params['seed']));track,nxt=p.tracked_fixtures(fx)
    stages=p.first_pending_stages(hands,p.match_horizon(fx))
    kw=dict(places=prep['places'],scale=prep['scale'],pen_xg=prep['pen_xg'],race_competition=COMP)
    old=p.Accumulator(fx,track,stages,nxt,**kw);new=p.Accumulator(fx,track,stages,nxt,**kw,route_competition=COMP)
    parts=[p.Accumulator(fx,track,stages,nxt,**kw,route_competition=COMP) for _ in range(4)]
    ctx=dict(prep=prep,fx=fx,engine=engine,hands=hands,cups=cups,unseen=p.unseen_for(prep,fx,params))
    times=[0.,0.]
    for i in range(args.worlds):
        world=p._simulate_world(ctx,params,i)
        for j in ([0,1] if i%2==0 else [1,0]):
            start=time.perf_counter();[old,new][j].add(world,world_index=i);times[j]+=time.perf_counter()-start
        parts[i%4].add(world,world_index=i)
        if (i+1)%max(1,args.worlds//10)==0:print(f'Worlds {i+1}/{args.worlds}',flush=True)
    baseline,candidate=old.result(),new.result()
    for block in candidate['leagues']:block.pop('entry_routes',None)
    assert baseline==candidate
    assert p.match_payload(old)==p.match_payload(new) and p.gw_payload(old)==p.gw_payload(new) and p.paths_payload(old)==p.paths_payload(new)
    tally=new.entry_routes[COMP];draft=tally.payload(new.europe_counts)
    for part in parts:part.entry_routes[COMP].validate(part.europe_counts)
    merged=RouteTally(tally.teams)
    for part in reversed(parts):merged.merge(part.entry_routes[COMP])
    assert merged.payload(new.europe_counts)==draft
    fault=copy.deepcopy(tally);fault.counts[tally.teams[0]][0,0]+=1
    try:fault.validate(new.europe_counts)
    except ValueError:print('PASS deliberate route-count fault rejected')
    else:raise AssertionError('Route fault escaped validation')
    raw=json.dumps(draft,separators=(',',':')).encode();delta=times[1]-times[0]
    report=dict(worlds=args.worlds,baseline_add_seconds=times[0],candidate_add_seconds=times[1],increment_percent=100*delta/times[0],increment_ms_per_world=1000*delta/args.worlds,
                teams=len(tally.counts),array_bytes=sum(v.nbytes for v in tally.counts.values()),json_bytes=len(raw),gzip_bytes=len(gzip.compress(raw,mtime=0)))
    block=next(b for b in new.result()['leagues'] if b['competition']==COMP)
    if args.output:args.output.write_text(json.dumps(dict(review_only=True,report=report,block=block,gw=p.gw_payload(new)['leagues'][COMP])))
    print(json.dumps(report,indent=2));print('PASS all route sums equal entry marginals; four reversed chunks exact; existing outputs unchanged')

if __name__=='__main__':main()
