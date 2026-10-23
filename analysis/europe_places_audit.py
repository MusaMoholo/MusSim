"""Paired European-entry allocation cost and a strict pre/post qualification snapshot audit.

    .venv/bin/python analysis/europe_places_audit.py profile --worlds 100
    .venv/bin/python analysis/europe_places_audit.py snapshot BEFORE AFTER

The 2027/28 base access list is UEFA circular 54/2026, enclosure 2:
https://editorial.uefa.com/resources/02a9-218cd2086a08-882d0ce02937-1000/20260909_circular_2026_54_en.zip
Local source copies: /private/tmp/football_uefa_2027_access.{zip,pdf,png,txt}. The PDF is an image;
the rendered table confirms four UCL entries (France: three direct + one qualifier), two UEL and
one UECL per supported association. EPS is the explicit previous allocation, not a coefficient
forecast. Rules and titleholder/EPS ordering are linked in scripts/europe_places.py.

Each log is archived outside the repo before replacement. Only qualification probabilities,
qualification metadata/thresholds, European stake/what-if fates, sample entry sets and model/run
stamps may change. All common what-if title/relegation fates are checked, and fresh raw counts
also check sides that disappear from the serialized selection. Other simulation values stay exact.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path('/private/tmp/Football_archive_2026-10-21_v11_europe/scripts/projection.py')
sys.path.insert(0, str(ROOT))
EURO = ('ucl', 'uel', 'uecl')


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def equal(old: Any, new: Any, where: str) -> int:
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


def projection_core(old: dict, new: dict) -> int:
    """Keep every unchanged forecast, checking common point thresholds before trimming metadata."""
    old, new = copy.deepcopy(old), copy.deepcopy(new)
    for obj in (old, new):
        for key in ('model', 'generated', 'elapsed'):
            obj.pop(key, None)
    new.pop('europe', None)
    assert len(old['samples']) == len(new['samples'])
    for left, right in zip(old['samples'], new['samples']):
        right.pop('europe', None)
    assert len(old['leagues']) == len(new['leagues'])
    checked = 0
    for left, right in zip(old['leagues'], new['leagues']):
        assert left['competition'] == right['competition']
        right.pop('qualification', None)
        for key in ('ucl_spots', 'uel_spots', 'uecl_spots'):
            left.pop(key); right.pop(key)
        old_lines = {row['place']: row for row in left.pop('lines')}
        new_lines = {row['place']: row for row in right.pop('lines')}
        for place in old_lines.keys() & new_lines.keys():
            l, r = dict(old_lines[place]), dict(new_lines[place])
            if l['label'] == 'Title' or l['label'].startswith('Survival'):
                assert l['label'] == r['label'], (left['competition'], place, 'non-European line label')
            l.pop('label'); r.pop('label')
            checked += equal(l, r, f'{left["competition"]}.points line {place}')
        for old_row, new_row in zip(left['teams'], right['teams']):
            assert old_row['team'] == new_row['team']
            for key in EURO:
                old_row.pop('p_' + key); new_row.pop('p_' + key)
            # New positional context is checked against the unchanged rounded position matrix.
            top4 = new_row.pop('p_top4')
            assert abs(top4 - sum(old_row['dist'][:4])) <= .000250001
            if 'p_top4' in old_row:
                assert old_row.pop('p_top4') == top4
    return checked + equal(old, new, 'projection outside qualification fields')


def fixture_core(old: dict, new: dict, kind: str, where: str) -> int:
    checked = 0
    if kind == 'league':
        if 'stakes' in old or 'stakes' in new:
            assert 'stakes' in old and 'stakes' in new, where
            assert len(old['stakes']) == len(new['stakes']) == 2
            for side in (0, 1):
                assert len(old['stakes'][side]) == len(new['stakes'][side]) == 4
                checked += equal([old['stakes'][side][k] for k in (0, 3)],
                                 [new['stakes'][side][k] for k in (0, 3)], where + '.title/rel')
            old.pop('stakes'); new.pop('stakes')
        if 'whatif' in old or 'whatif' in new:
            assert 'whatif' in old and 'whatif' in new, where
            for team in old['whatif'].keys() & new['whatif'].keys():
                assert len(old['whatif'][team]) == len(new['whatif'][team]) == 4
                checked += equal([old['whatif'][team][k] for k in (0, 3)],
                                 [new['whatif'][team][k] for k in (0, 3)], where + '.whatif.' + team)
            old.pop('whatif'); new.pop('whatif')
    return checked


def matches_core(old: dict, new: dict) -> int:
    old, new = copy.deepcopy(old), copy.deepcopy(new)
    assert len(old['fixtures']) == len(new['fixtures'])
    checked = 0
    for i, (left, right) in enumerate(zip(old['fixtures'], new['fixtures'])):
        assert left['kind'] == right['kind']
        checked += fixture_core(left, right, left['kind'], f'matches.fixture{i}')
    return checked + equal(old, new, 'matches outside league European fates')


def gw_core(old: dict, new: dict) -> int:
    old, new = copy.deepcopy(old), copy.deepcopy(new)
    checked = 0
    assert old['leagues'].keys() == new['leagues'].keys()
    for comp in old['leagues']:
        assert len(old['leagues'][comp]['fixtures']) == len(new['leagues'][comp]['fixtures'])
        for i, (left, right) in enumerate(zip(old['leagues'][comp]['fixtures'], new['leagues'][comp]['fixtures'])):
            checked += fixture_core(left, right, 'league', f'GW.{comp}.fixture{i}')
    return checked + equal(old, new, 'GW outside league European fates')


def unchanged_raw(old, new) -> int:
    checked = equal(old.fx_counts, new.fx_counts, 'raw score tables')
    checked += equal(old.fx_cup_keys, new.fx_cup_keys, 'raw cup keys')
    checked += equal(old.fx_cup_stakes, new.fx_cup_stakes, 'raw cup counts')
    checked += equal(old.whatif_pos, new.whatif_pos, 'whatif slots')
    for i, meta in enumerate(new.fx_meta):
        fates = [0, 3] if meta['kind'] == 'league' else list(range(4))
        checked += equal(old.fx_stakes[i][:, :, fates], new.fx_stakes[i][:, :, fates],
                         f'raw fixture{i} unchanged fates')
        slot = int(new.whatif_pos[i])
        if slot >= 0:
            checked += equal(old.fx_whatif[slot][:, :, fates], new.fx_whatif[slot][:, :, fates],
                             f'raw whatif{i} unchanged fates')
    return checked


def profile(args) -> None:
    load_module(args.helper.resolve(), 'scripts.europe_places')
    baseline = load_module(args.baseline.resolve(), 'europe_places_baseline')
    candidate = load_module(args.candidate.resolve(), 'europe_places_candidate')
    params = candidate.coerce_params({'season': args.season, 'worlds': args.worlds,
                                     'seed': args.seed, 'as_of': args.as_of}, args.season,
                                    max_worlds=2_000_000)
    engine = candidate.Engine()
    prep = candidate.prepare_for(engine, params)
    fx = prep['fixtures']
    hands, _ = candidate.build_handovers(engine, fx, params)
    cups = candidate.cup_handovers(fx, engine.master, np.random.default_rng(params['seed']))
    unseen = candidate.unseen_for(prep, fx, params)
    track, nxt = candidate.tracked_fixtures(fx, params['match_rounds'])
    stages = candidate.first_pending_stages(hands, candidate.match_horizon(fx))
    common = {'scale': prep['scale'], 'pen_xg': prep['pen_xg']}
    old_places = baseline.euro_places(engine.master, args.season)
    old = baseline.Accumulator(fx, track, stages, nxt, places=old_places, **common)
    new = candidate.Accumulator(fx, track, stages, nxt, places=prep['places'], **common)
    elapsed = {'baseline': [], 'candidate': []}
    print(f'Baseline: {args.baseline.resolve()}')
    print(f'Candidate: {args.candidate.resolve()}')
    print(f'Qualification helper: {args.helper.resolve()}')
    print(f'Season {args.season}, as_of {args.as_of}, seed {args.seed}, {args.worlds} identical worlds')
    print('Old place policy:', json.dumps(old_places, sort_keys=True))
    print('New place policy:', json.dumps(prep['places'], sort_keys=True))
    simulation_seconds = 0.0
    for index in range(args.worlds):
        start = time.perf_counter()
        world = candidate.simulate(fx, prep['model'], prep['calib'], prep['elo0'],
            np.random.default_rng(params['seed'] * 1_000_003 + index),
            **candidate.world_kwargs(prep, params), master=engine.master,
            handovers=hands, cups=cups, unseen=unseen)
        simulation_seconds += time.perf_counter() - start
        order = [('baseline', old), ('candidate', new)]
        if index % 2:
            order.reverse()
        for label, accumulator in order:
            start = time.perf_counter()
            accumulator.add(world, world_index=index)
            elapsed[label].append(time.perf_counter() - start)
        if (index + 1) % max(1, args.worlds // 10) == 0 or index + 1 == args.worlds:
            print(f'  worlds {index + 1}/{args.worlds}; complete add() baseline '
                  f'{sum(elapsed["baseline"]):.6f}s / candidate {sum(elapsed["candidate"]):.6f}s', flush=True)
    raw_count = unchanged_raw(old, new)
    stored_count = projection_core(old.result(), new.result())
    stored_count += matches_core(baseline.match_payload(old), candidate.match_payload(new))
    stored_count += gw_core(baseline.gw_payload(old), candidate.gw_payload(new))
    stored_count += equal(baseline.paths_payload(old), candidate.paths_payload(new), 'paths')
    old_seconds, new_seconds = sum(elapsed['baseline']), sum(elapsed['candidate'])
    delta = new_seconds - old_seconds
    print(f'PASS {raw_count:,} unchanged raw score/cup/TITLE/REL/UEFA/whatif count values exact')
    print(f'PASS {stored_count:,} stored values exact outside European qualification fields')
    vector_bytes = sum(a.nbytes for a in new.europe_counts.values())
    total_bytes = sum(a.nbytes for a in new.europe_association_totals.values())
    print(f'European integer vectors: {len(new.europe_counts)} teams, {vector_bytes:,} bytes; association totals {total_bytes:,} bytes')
    print(f'Baseline complete add(): {old_seconds:.6f}s')
    print(f'Candidate complete add(): {new_seconds:.6f}s')
    print(f'Increment: {delta:+.6f}s ({100 * delta / old_seconds:+.3f}%), {1000 * delta / args.worlds:+.6f}ms/world')
    print(f'Paired median increment: {1000 * float(np.median(np.asarray(elapsed["candidate"]) - elapsed["baseline"])):+.6f}ms/world')
    print(f'Simulation excluded from add timings: {simulation_seconds:.6f}s')


def read(folder: Path, name: str):
    data = (folder / name).read_bytes()
    return json.loads(gzip.decompress(data) if name.endswith('.gz') else data)


def differential(old: dict, new: dict) -> None:
    changes = []
    global_rows = new['europe']['teams']
    print('European scope:', json.dumps({k: v for k, v in new['europe'].items() if k != 'teams'}, sort_keys=True))
    for old_league, league in zip(old['leagues'], new['leagues']):
        comp = league['competition']
        assert comp == old_league['competition']
        old_rows = {row['team']: row for row in old_league['teams']}
        names = set(old_rows)
        q = league['qualification']
        outsiders = [row for row in global_rows if row['association'] == comp and row['team'] not in names]
        mean_outside = {key: round(q['association_mean'][key] - q['mean'][key], 4) for key in EURO}
        print('BUDGET', comp, json.dumps({
            'before_slots': {key: old_league[key + '_spots'] for key in EURO},
            'before_league_probability_sums': {key: round(sum(r['p_' + key] for r in old_rows.values()), 6) for key in EURO},
            'after_league_mean': q['mean'], 'after_association_mean': q['association_mean'],
            'outside_top_division_mean': mean_outside, 'outside_clubs': len(outsiders),
            'base': q['base'], 'eps': q['eps'], 'ucl_direct': q['ucl_direct']}, sort_keys=True))
        for row in sorted(league['teams'], key=lambda r: r['team']):
            previous = old_rows[row['team']]
            before, after = [previous['p_' + key] for key in EURO], [row['p_' + key] for key in EURO]
            deltas = [round(100 * (r - l), 8) for l, r in zip(before, after)]
            print('TEAM', comp, row['team'], json.dumps({'before': before, 'after': after, 'delta_pp': deltas}))
            for key, left, right in zip(EURO, before, after):
                changes.append({'competition': comp, 'team': row['team'], 'route': key,
                                'before': left, 'after': right, 'delta_pp': round(100 * (right - left), 8)})
        for row in outsiders:
            print('OUTSIDE_TOP_DIVISION', comp, json.dumps(row, sort_keys=True))
    foreign = [row for row in global_rows if row['association'] is None]
    print('FOREIGN_TITLEHOLDER_ROUTES', json.dumps({
        'clubs': len(foreign), 'mean': {key: round(sum(r['p_' + key] for r in foreign), 6) for key in EURO},
        'scope': 'guaranteed UEFA titleholder routes only; other foreign domestic qualification unknown'}, sort_keys=True))
    for row in foreign:
        print('FOREIGN_TITLEHOLDER', json.dumps(row, sort_keys=True))
    ranked = sorted(changes, key=lambda row: (-abs(row['delta_pp']), row['competition'], row['team'], row['route']))
    nonzero = [row for row in ranked if row['delta_pp'] != 0]
    l1 = sum(abs(row['delta_pp']) for row in ranked)
    print('SUMMARY', json.dumps({'cells': len(ranked), 'changed': len(nonzero), 'unchanged': len(ranked) - len(nonzero),
                                 'L1_pp': round(l1, 8), 'mean_abs_pp': round(l1 / len(ranked), 8),
                                 'max_abs_pp': abs(ranked[0]['delta_pp'])}, sort_keys=True))
    for row in ranked[:15]:
        print('LARGEST_CHANGE', json.dumps(row, sort_keys=True))
    for row in nonzero[-10:]:
        print('SMALLEST_CHANGE', json.dumps(row, sort_keys=True))


def snapshot(args) -> None:
    before, after = args.before.resolve(), args.after.resolve()
    old, new = read(before, 'projection.json'), read(after, 'projection.json')
    assert new.get('europe', {}).get('mode') == 'per_world'
    print(f'Before: {before}')
    print(f'After: {after}')
    print(f'Model generation: {old["model"]} -> {new["model"]}; match simulation unchanged')
    cells = projection_core(old, new)
    print('PASS projection core exact: tables, distributions, title/REL, trophies, core samples')
    cells += matches_core(read(before, 'matches.json'), read(after, 'matches.json'))
    print('PASS matches exact outside league European fates; every common title/REL whatif exact')
    cells += gw_core(read(before, 'gw.json.gz'), read(after, 'gw.json.gz'))
    print('PASS GW exact outside league European stake fates')
    cells += equal(read(before, 'paths.json.gz'), read(after, 'paths.json.gz'), 'paths')
    print('PASS paths exact')
    assert (before / 'players.json').read_bytes() == (after / 'players.json').read_bytes()
    print(f'PASS players byte-identical ({(after / "players.json").stat().st_size:,} bytes)')
    print(f'PASS {cells:,} unchanged stored values outside qualification-only fields')
    differential(old, new)


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
    p.add_argument('--baseline', type=Path, default=BASELINE)
    p.add_argument('--candidate', type=Path, default=ROOT / 'scripts/projection.py')
    p.add_argument('--helper', type=Path, default=ROOT / 'scripts/europe_places.py')
    p.add_argument('--worlds', type=int, default=100)
    p.add_argument('--season', type=int, default=2026)
    p.add_argument('--as-of', default='2026-10-20')
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--log', type=Path, default=ROOT / 'analysis/logs/europe_places_profile.log')
    p = sub.add_parser('snapshot')
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    p.add_argument('--log', type=Path, default=ROOT / 'analysis/logs/europe_places_compare.log')
    args = parser.parse_args()
    if args.command == 'profile' and args.worlds < 2:
        parser.error('at least two worlds are needed to alternate timing order')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    if args.log.exists():
        archive = Path(tempfile.mkdtemp(prefix='Football_archive_europe_places_audit_'))
        shutil.copy2(args.log, archive / args.log.name)
        print(f'Archived old log to {archive / args.log.name}')
    with args.log.open('w') as handle, contextlib.redirect_stdout(Tee(sys.stdout, handle)):
        (profile if args.command == 'profile' else snapshot)(args)


if __name__ == '__main__':
    main()
