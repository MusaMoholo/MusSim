"""Profile the draft Premier League rivals contract without publishing any snapshot.

.venv/bin/python analysis/race_room_audit.py --worlds 100 --output /private/tmp/race-room-review.json
Each full simulated world is offered to ordinary/opt-in accumulators, alternating add timing.
Independent goals/points ledgers establish pair orders, not five stored illustrative samples.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import json
import multiprocessing as mp
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import projection as p
from scripts.race_room import RivalTally

COMP = 'English Premier League'


def independent_positions(world, teams):
    attrs, world.attrs = world.attrs, {}
    try:
        ledger = {t: [0, 0, 0] for t in teams}
        for r in world.itertuples():
            if r.competition != COMP or r.phase != 'league':
                continue
            h, a = ledger[r.home], ledger[r.away]
            hg, ag = int(r.home_goals), int(r.away_goals)
            h[0] += 3 if hg > ag else 1 if hg == ag else 0
            a[0] += 3 if ag > hg else 1 if hg == ag else 0
            h[1] += hg-ag; a[1] += ag-hg
            h[2] += hg; a[2] += ag
        order = sorted(teams, key=lambda t: (-ledger[t][0], -ledger[t][1], -ledger[t][2], t))
        return [order.index(t)+1 for t in teams]
    finally:
        world.attrs = attrs


def reduce_orders(job):
    teams, orders = job
    tally = RivalTally(teams)
    for order in orders:
        tally.add(order)
    return tally


def check_reference(tally, orders):
    tally.validate()
    n = len(tally.teams)
    reference = np.zeros_like(tally.gaps)
    for order in orders:
        for a in range(n):
            for b in range(n):
                reference[a, b, order[b]-order[a]+n-1] += 1
    assert np.array_equal(reference, tally.gaps), 'Independent final-world gap counts disagree'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--worlds', type=int, default=100)
    ap.add_argument('--as-of', default='2026-10-21')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    assert args.worlds >= 8
    if args.output:
        assert not args.output.exists(), 'Use a new review output path; never overwrite an artifact'
        assert ROOT / 'data' not in args.output.resolve().parents, 'No production data output'
    params = p.coerce_params(dict(season=2026, worlds=args.worlds, as_of=args.as_of), 2026)
    engine = p.Engine(); prep = p.prepare_for(engine, params); fx = prep['fixtures']
    hands, _ = p.build_handovers(engine, fx, params)
    cups = p.cup_handovers(fx, engine.master, np.random.default_rng(params['seed']))
    track, nxt = p.tracked_fixtures(fx)
    stages = p.first_pending_stages(hands, p.match_horizon(fx))
    kw = dict(places=prep['places'], scale=prep['scale'], pen_xg=prep['pen_xg'])
    baseline = p.Accumulator(fx, track, stages, nxt, **kw)
    candidate = p.Accumulator(fx, track, stages, nxt, **kw, race_competition=COMP)
    ctx = dict(prep=prep, fx=fx, engine=engine, hands=hands, cups=cups,
               unseen=p.unseen_for(prep, fx, params))
    tally = candidate.rivals[COMP]; times = [0., 0.]; orders=[]; simulation=0.
    for i in range(args.worlds):
        start=time.perf_counter(); world=p._simulate_world(ctx, params, i)
        simulation += time.perf_counter()-start
        for j in ([0,1] if i%2==0 else [1,0]):
            start=time.perf_counter(); [baseline,candidate][j].add(world, world_index=i)
            times[j] += time.perf_counter()-start
        orders.append(independent_positions(world, tally.teams))
        if (i+1)%max(1,args.worlds//10)==0:
            print(f'Worlds {i+1}/{args.worlds}', flush=True)
    old,new=baseline.result(),candidate.result()
    for block in new['leagues']: block.pop('rivals',None)
    assert old==new, 'Existing projections changed'
    assert p.match_payload(baseline)==p.match_payload(candidate), 'Existing matches changed'
    assert p.gw_payload(baseline)==p.gw_payload(candidate), 'Existing gameweeks changed'
    assert p.paths_payload(baseline)==p.paths_payload(candidate), 'Existing paths changed'
    check_reference(tally,orders)
    assert np.array_equal(tally.positions, candidate.leagues[COMP]['pos'])
    # A real spawn process boundary with four independent integer reductions, reversed arrival.
    with mp.get_context('spawn').Pool(4) as pool:
        parts=pool.map(reduce_orders, [(tally.teams,orders[i::4]) for i in range(4)])
    parallel=RivalTally(tally.teams)
    for part in reversed(parts): parallel.merge(part)
    assert parallel.payload()==tally.payload(), 'One/four-process rival reductions disagree'
    broken=copy.deepcopy(tally); broken.gaps[0,1,0]+=1
    try: check_reference(broken, orders)
    except (ValueError,AssertionError): print('PASS deliberate count fault rejected')
    else: raise AssertionError('Count corruption escaped validation')
    block=next(b for b in candidate.result()['leagues'] if b['competition']==COMP)
    draft=tally.payload(); raw=json.dumps(draft,separators=(',',':')).encode()
    block['rivals']=draft
    report=dict(worlds=tally.worlds, as_of=args.as_of,competition=COMP,
                baseline_add_seconds=times[0],candidate_add_seconds=times[1],
                increment_ms_per_world=1000*(times[1]-times[0])/args.worlds,
                increment_percent=100*(times[1]/times[0]-1),
                simulation_seconds=simulation,
                tally_array_bytes=tally.gaps.nbytes+tally.positions.nbytes,
                working_index_bytes=tally._row.nbytes+tally._col.nbytes,
                draft_json_bytes=len(raw),draft_gzip_bytes=len(gzip.compress(raw,mtime=0)))
    if args.output:
        args.output.write_text(json.dumps(dict(review_only=True,report=report,block=block)))
    print(json.dumps(report,indent=2))
    print('PASS independent full-world orders, complements, expected ranks, gap counts, '
          'one/four-process reductions, existing projection/matches/gw/paths unchanged')

if __name__=='__main__': main()
