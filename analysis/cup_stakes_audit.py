"""Reproduce cup-stakes cost, regulation-score preservation and snapshot exactness.

    .venv/bin/python analysis/cup_stakes_audit.py profile --worlds 100
    .venv/bin/python analysis/cup_stakes_audit.py snapshot BEFORE AFTER

Each command archives an existing output log outside the repo before replacing it. Profile worlds
use identical seeds and inputs in archived/current simulators, then offer the current world's
unchanged final rows to both accumulators, alternating complete add() timing order. No derived
frame is read through simulation attrs. Snapshot comparison permits only domestic-cup forecast
score/stakes fields and generation/elapsed timing; all other forecast values and players bytes
must remain exact.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path('/private/tmp/Football_archive_2026-10-21_v11_cupstakes/scripts')
sys.path.insert(0, str(ROOT))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def equal(old: Any, new: Any, where: str) -> int:
    """Strict structure/value equality and a count of the scalar values it covered."""
    if isinstance(old, np.ndarray):
        assert isinstance(new, np.ndarray) and old.shape == new.shape, where
        assert np.array_equal(old, new, equal_nan=True), where
        return int(old.size)
    if isinstance(old, dict):
        assert isinstance(new, dict) and old.keys() == new.keys(), (where, set(old) ^ set(new))
        return sum(equal(value, new[key], f'{where}.{key}') for key, value in old.items())
    if isinstance(old, (list, tuple)):
        assert isinstance(new, type(old)) and len(old) == len(new), where
        return sum(equal(left, right, f'{where}[{i}]') for i, (left, right) in enumerate(zip(old, new)))
    assert old == new, (where, old, new)
    return 1


def profile(args) -> None:
    baseline = load_module(args.baseline.resolve(), 'cup_stakes_baseline_projection')
    candidate = load_module(args.candidate.resolve(), 'cup_stakes_candidate_projection')
    reference = load_module(args.reference.resolve(), 'cup_stakes_unoptimized_projection') if args.reference else None
    old_sim = load_module(args.baseline_sim.resolve(), 'cup_stakes_baseline_simulate')
    new_sim = load_module(args.candidate_sim.resolve(), 'cup_stakes_candidate_simulate')
    params = candidate.coerce_params({'season': args.season, 'worlds': args.worlds,
                                     'seed': args.seed, 'as_of': args.as_of}, args.season,
                                    max_worlds=2_000_000)
    engine = candidate.Engine()
    prep = candidate.prepare_for(engine, params)
    fixtures = prep['fixtures']
    hands, _ = candidate.build_handovers(engine, fixtures, params)
    cups = candidate.cup_handovers(fixtures, engine.master, np.random.default_rng(params['seed']))
    unseen = candidate.unseen_for(prep, fixtures, params)
    track, nxt = candidate.tracked_fixtures(fixtures, params['match_rounds'])
    stages = candidate.first_pending_stages(hands, candidate.match_horizon(fixtures))
    kwargs = {'places': prep['places'], 'scale': prep['scale'], 'pen_xg': prep['pen_xg']}
    old = baseline.Accumulator(fixtures, track, stages, nxt, **kwargs)
    new = candidate.Accumulator(fixtures, track, stages, nxt, **kwargs)
    unoptimized = reference.Accumulator(fixtures, track, stages, nxt, **kwargs) if reference else None
    expected90 = np.zeros_like(new.fx_counts)
    elapsed = {'baseline': [], 'candidate': []}
    world_rows = state_values = report_values = regulation_values = aet_rows = 0
    simulation_seconds = {'baseline': 0.0, 'candidate': 0.0}
    print(f'Baseline projection: {args.baseline.resolve()}')
    print(f'Candidate projection: {args.candidate.resolve()}')
    print(f'Baseline simulator: {args.baseline_sim.resolve()}')
    print(f'Candidate simulator: {args.candidate_sim.resolve()}')
    if reference:
        print(f'Unoptimized cup-stakes reference: {args.reference.resolve()}')
    print(f'Season {args.season}, as_of {args.as_of}, seed {args.seed}, {args.worlds} paired worlds')
    for index in range(args.worlds):
        worlds = []
        for label, module in [('baseline', old_sim), ('candidate', new_sim)]:
            start = time.perf_counter()
            world = module.simulate(fixtures, prep['model'], prep['calib'], prep['elo0'],
                np.random.default_rng(params['seed'] * 1_000_003 + index),
                **candidate.world_kwargs(prep, params), master=engine.master,
                handovers=hands, cups=cups, unseen=unseen)
            simulation_seconds[label] += time.perf_counter() - start
            worlds.append(world)
        previous, world = worlds
        old_attrs, previous.attrs = previous.attrs, {}
        attrs, world.attrs = world.attrs, {}
        try:
            pd.testing.assert_frame_equal(previous, world, check_exact=True)
            assert attrs.keys() == old_attrs.keys() | {'score90'}, (index, attrs.keys(), old_attrs.keys())
            state_values += equal(old_attrs['state'], attrs['state'], f'world{index}.state')
            report_values += equal({k: v for k, v in old_attrs.items() if k != 'state'},
                                  {k: v for k, v in attrs.items() if k not in {'state', 'score90'}},
                                  f'world{index}.reports')
            rows = world.to_dict('records')
            score90 = np.asarray(attrs['score90'])
            assert score90.shape == (len(rows), 2)
            world_rows += len(rows)
            for row_index, row in enumerate(rows):
                if not row['sampled']:
                    continue
                h, a = score90[row_index]
                assert np.isfinite([h, a]).all() and h >= 0 and a >= 0
                if row['minutes'] <= 90:
                    assert (h, a) == (row['home_goals'], row['away_goals'])
                else:
                    aet_rows += 1
                    assert row['phase'] == 'knockout'
                    # ET is entered only from an aggregate draw; a return leg can itself be
                    # decisive at 90, so no blanket h==a assumption belongs here.
                    assert row['home_goals'] >= h and row['away_goals'] >= a
                regulation_values += 2
                fid = int(row['fixture_id'])
                if 0 <= fid < len(new.fx_pos) and new.fx_pos[fid] >= 0:
                    slot = int(new.fx_pos[fid])
                    expected90[slot, min(int(h), candidate.MAXG - 1),
                               min(int(a), candidate.MAXG - 1)] += 1
        finally:
            previous.attrs, world.attrs = old_attrs, attrs
        order = [('baseline', old), ('candidate', new)]
        if index % 2:
            order.reverse()
        for label, accumulator in order:
            start = time.perf_counter()
            accumulator.add(world, world_index=index)
            elapsed[label].append(time.perf_counter() - start)
        if unoptimized is not None:
            unoptimized.add(world, world_index=index)
        if (index + 1) % max(1, args.worlds // 10) == 0 or index + 1 == args.worlds:
            print(f'  worlds {index + 1}/{args.worlds}; complete add() '
                  f'baseline {sum(elapsed["baseline"]):.6f}s / candidate {sum(elapsed["candidate"]):.6f}s', flush=True)
    if unoptimized is not None:
        exact_reference = equal(unoptimized.result(), new.result(), 'unoptimized aggregates')
        exact_reference += equal(unoptimized.fx_counts, new.fx_counts, 'unoptimized score tables')
        exact_reference += equal(unoptimized.fx_cup_keys, new.fx_cup_keys, 'unoptimized cup keys')
        exact_reference += equal(unoptimized.fx_cup_stakes, new.fx_cup_stakes, 'unoptimized cup counts')
        expected_matches = reference.match_payload(unoptimized)
        for row in expected_matches['fixtures']:
            if row.get('kind') == 'cup':
                row['p_occurs'] = round(row['n'] / max(unoptimized.worlds, 1), 4)
                if row['n'] != unoptimized.worlds:
                    row.pop('stakes', None); row.pop('stakes_of', None)
                    row['stakes_unavailable'] = 'conditional_fixture'
        exact_reference += equal(expected_matches, candidate.match_payload(new), 'unoptimized matches plus occurrence guard')
        print(f'PASS: {exact_reference:,} values exactly match unoptimized cup-stakes output/counts; only occurrence metadata/guard added')
    aggregate_values = equal(old.result(), new.result(), 'aggregates')
    gw_values = equal(baseline.gw_payload(old), candidate.gw_payload(new), 'GW')
    path_values = equal(baseline.paths_payload(old), candidate.paths_payload(new), 'paths')
    old_matches, new_matches = baseline.match_payload(old), candidate.match_payload(new)
    old_non_cup = [f for f in old_matches['fixtures'] if f['kind'] != 'cup']
    new_non_cup = [f for f in new_matches['fixtures'] if f['kind'] != 'cup']
    match_values = equal(old_non_cup, new_non_cup, 'noncup fixtures')
    assert np.array_equal(expected90, new.fx_counts), 'independently tallied regulation score tables differ'
    cup_slots = [i for i, meta in enumerate(new.fx_meta) if meta['kind'] == 'cup']
    changed_scores = sum(not np.array_equal(old.fx_counts[i], new.fx_counts[i]) for i in cup_slots)
    arrays = list(new.fx_cup_stakes.values())
    assert arrays and all(a.dtype == np.int32 for a in arrays)
    shapes = Counter(str(a.shape) for a in arrays)
    old_seconds, new_seconds = sum(elapsed['baseline']), sum(elapsed['candidate'])
    delta = new_seconds - old_seconds
    print(f'PASS: {world_rows:,} final simulated rows and {state_values:,} state values exactly match archived simulator')
    print(f'PASS: {report_values:,} existing report values exact; only new attrs field score90')
    print(f'PASS: {regulation_values:,} sampled regulation scores checked, including {aet_rows:,} AET rows')
    print(f'PASS: {aggregate_values + gw_values + path_values + match_values:,} existing aggregate/GW/path/noncup-match values exact')
    print(f'PASS: {int(expected90.sum()):,} tracked regulation score occurrences independently tallied; {changed_scores}/{len(cup_slots)} cup tables corrected')
    print(f'Cup-stakes arrays: {len(arrays)}, shape counts {dict(sorted(shapes.items()))}, int32, {sum(a.nbytes for a in arrays):,} bytes')
    print(f'Baseline complete add(): {old_seconds:.6f}s')
    print(f'Candidate complete add(): {new_seconds:.6f}s')
    print(f'Increment: {delta:+.6f}s ({100 * delta / old_seconds:+.3f}%), {1000 * delta / args.worlds:+.6f}ms/world')
    print(f'Paired median increment: {1000 * float(np.median(np.asarray(elapsed["candidate"]) - elapsed["baseline"])):+.6f}ms/world')
    print(f'Simulation excluded from add timings: {simulation_seconds}')


CUP_FIELDS = {'ladder', 'top', 'over25', 'btts', 'cs_h', 'cs_a', 'mean_goals', 'mean_h',
              'mean_a', 'stakes', 'stakes_of', 'score_basis', 'p_occurs', 'stakes_unavailable'}


def read(folder: Path, name: str):
    data = (folder / name).read_bytes()
    return json.loads(gzip.decompress(data) if name.endswith('.gz') else data)


def snapshot(args) -> None:
    before, after = args.before.resolve(), args.after.resolve()
    print(f'Before: {before}')
    print(f'After: {after}')
    cells = 0
    old_matches, new_matches = read(before, 'matches.json'), read(after, 'matches.json')
    old_rows, new_rows = old_matches['fixtures'], new_matches['fixtures']
    assert len(old_rows) == len(new_rows)
    cup_count = changed = draw_changed = stakes = fate_values = 0
    max_change = (0.0, '')
    examples = []
    all_fate_swings, trophy_swings = [], []
    for old, new in zip(old_rows, new_rows):
        if old.get('kind') != 'cup':
            continue
        cup_count += 1
        assert new.get('kind') == 'cup' and new.get('score_basis') == '90min'
        assert new['p_occurs'] == round(new['n'] / new_matches['worlds'], 4)
        if new['n'] != new_matches['worlds']:
            assert 'stakes' not in new and 'stakes_of' not in new
            assert new.get('stakes_unavailable') == 'conditional_fixture' 
        if old['ladder'] != new['ladder']:
            changed += 1
            if old['ladder']['d'] != new['ladder']['d']:
                draw_changed += 1
            for key in ('h1', 'd', 'a1'):
                difference = abs(new['ladder'][key] - old['ladder'][key])
                if difference > max_change[0]:
                    max_change = (difference, f'{new["competition"]}: {new["home"]} v {new["away"]} {key}')
            if len(examples) < 3:
                examples.append({'competition': new['competition'], 'home': new['home'], 'away': new['away'],
                                 'before': {k: old['ladder'][k] for k in ('h1', 'd', 'a1')},
                                 'after': {k: new['ladder'][k] for k in ('h1', 'd', 'a1')}})
        if 'stakes' in new:
            stakes += 1
            fate_values += 2 * len(new['stakes_of'])
            swings, wins = [], []
            for side in new['stakes']:
                for key, values in zip(new['stakes_of'], side):
                    values = values if isinstance(values, list) else [values] * 3
                    known = [v for v in values if v is not None]
                    swing = max(known) - min(known) if known else 0
                    swings.append(swing)
                    if key == 'win':
                        wins.append(swing)
            all_fate_swings.append(max(swings)); trophy_swings.append(max(wins))
        for field in CUP_FIELDS:
            old.pop(field, None); new.pop(field, None)
    # Matchups are empty at the current cutoff. If drawn domestic-cup rows exist in a replay,
    # allow their same regulation-score fields, while retaining every matchup's exact identity/n.
    cup_names = {cup['competition'] for cup in read(after, 'projection.json')['cups']}
    assert len(old_matches['matchups']) == len(new_matches['matchups'])
    for old, new in zip(old_matches['matchups'], new_matches['matchups']):
        if old.get('competition') in cup_names:
            for field in CUP_FIELDS:
                old.pop(field, None); new.pop(field, None)
    cells += equal(old_matches, new_matches, 'matches.json outside cup forecast fields')
    print(f'PASS exact outside cup forecast fields: matches.json ({cup_count} cup fixtures)')
    for name in ('projection.json', 'gw.json.gz', 'paths.json.gz'):
        old, new = read(before, name), read(after, name)
        if name == 'projection.json':
            for key in ('generated', 'elapsed'):
                old.pop(key); new.pop(key)
        count = equal(old, new, name)
        cells += count
        print(f'PASS {count:,} exact existing values: {name}')
    assert (before / 'players.json').read_bytes() == (after / 'players.json').read_bytes()
    print(f'PASS players.json byte-identical ({(after / "players.json").stat().st_size:,} bytes)')
    assert cup_count > 0 and stakes > 0, 'cup audit must cover real fixtures and stakes'
    print(f'PASS {cells:,} existing scalar values unchanged outside permitted cup forecast fields/timing')
    print(f'Cup fixture odds changed: {changed}/{cup_count}; draw chances changed: {draw_changed}; stakes on {stakes} named fixtures ({fate_values} side-fates)')
    print(f'Largest H/D/A correction: {100 * max_change[0]:.4f}pp, {max_change[1]}')
    print(f'Largest-any-fate swing is 100pp on {sum(s == 1 for s in all_fate_swings)}/{len(all_fate_swings)} ties; trophy swings '
          f'min/median/max {100 * min(trophy_swings):.3f}/{100 * float(np.median(trophy_swings)):.3f}/{100 * max(trophy_swings):.3f}pp '
          f'({len(set(trophy_swings))} distinct rounded values)')
    for example in examples:
        print('Example:', json.dumps(example, ensure_ascii=False))


class Tee:
    def __init__(self, *handles):
        self.handles = handles

    def write(self, text):
        for handle in self.handles:
            handle.write(text)
        return len(text)

    def flush(self):
        for handle in self.handles:
            handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('profile')
    p.add_argument('--baseline', type=Path, default=BASELINE / 'projection.py')
    p.add_argument('--candidate', type=Path, default=ROOT / 'scripts/projection.py')
    p.add_argument('--reference', type=Path,
                   default=BASELINE.parent / 'unoptimized_candidate/projection.py')
    p.add_argument('--baseline-sim', type=Path, default=BASELINE / 'simulate_season.py')
    p.add_argument('--candidate-sim', type=Path, default=ROOT / 'scripts/simulate_season.py')
    p.add_argument('--worlds', type=int, default=100)
    p.add_argument('--season', type=int, default=2026)
    p.add_argument('--as-of', default='2026-10-20')
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--log', type=Path, default=ROOT / 'analysis/logs/cup_stakes_profile.log')
    p = sub.add_parser('snapshot')
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    p.add_argument('--log', type=Path, default=ROOT / 'analysis/logs/cup_stakes_compare.log')
    args = parser.parse_args()
    if args.command == 'profile' and args.worlds < 2:
        parser.error('at least two worlds are needed to alternate timing order')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    if args.log.exists():
        archive = Path(tempfile.mkdtemp(prefix='Football_archive_cup_stakes_audit_'))
        shutil.copy2(args.log, archive / args.log.name)
        print(f'Archived old log to {archive / args.log.name}')
    with args.log.open('w') as handle, contextlib.redirect_stdout(Tee(sys.stdout, handle)):
        (profile if args.command == 'profile' else snapshot)(args)


if __name__ == '__main__':
    main()
