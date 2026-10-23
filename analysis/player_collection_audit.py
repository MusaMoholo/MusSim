#!/usr/bin/env python3
"""Audit cached collection, typed retention and cutoff-safe player contributions; no network.

.venv/bin/python analysis/player_collection_audit.py --season 2026 --as-of 2026-10-20

Optional --previous compares every old player-payload scalar to the additive new sidecar.
The source audit reads semantic stat values/denominators directly from the raw cached JSON,
never the production extractor. Absent xA is unknown; chance counts cannot establish its zero.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.player_metrics import METRIC_REGISTRY, ADDITIONAL_METRICS
from scripts.player_stats import build_players, validate_player_inputs


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def semantic(player):
    result = {}
    for group in player.get("stats") or []:
        if not isinstance(group, dict):
            continue
        entries = group.get("stats") or {}
        entries = entries.values() if isinstance(entries, dict) else entries if isinstance(entries, list) else []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("key") and isinstance(entry.get("stat"), dict):
                result[entry["key"]] = entry["stat"]
    return result


def read_json(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def compare_old(old, new):
    count, errors = 0, []
    def walk(a, b, path=""):
        nonlocal count
        if isinstance(a, dict):
            for key, value in a.items():
                if not isinstance(b, dict) or key not in b:
                    errors.append(path + "." + key + " missing")
                else:
                    walk(value, b[key], path + "." + key)
        elif isinstance(a, list):
            if not isinstance(b, list) or len(a) != len(b):
                errors.append(path + " length differs")
                return
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + f"[{i}]")
        else:
            count += 1
            if a != b:
                errors.append([path, a, b])
    walk(old, new)
    return {"compared": count, "mismatches": len(errors), "examples": errors[:10]}


def audit(season, cutoff, previous=None):
    started = time.perf_counter()
    master = pd.read_pickle(ROOT / "data/master_fixtures.pkl")
    master.attrs = {}
    records = master.to_dict("records")
    eligible = [r for r in records if number(r.get("season")) == season and r.get("played")
                and not r.get("tbd") and str(r.get("kickoff"))[:10] <= cutoff
                and number(r.get("home_goals")) is not None and number(r.get("away_goals")) is not None]
    eligible.sort(key=lambda r: (str(r["kickoff"]), r["competition"], str(r["match_id"])))
    selected = {(r["competition"], str(int(float(r["match_id"])))): r for r in eligible}
    cache = ROOT / "data/fotmob/matches"
    files = list(cache.glob("*.json.gz")) + list(cache.glob("*.json"))
    source = Counter()
    per_comp = defaultdict(Counter)
    player_keys, team_keys, shot_keys = Counter(), Counter(), Counter()
    values = defaultdict(list)
    expected = {}
    missing, errors = [], []
    typed_matches = typed_players = typed_groups = source_values = 0
    for (comp, mid), fixture in selected.items():
        path = cache / f"{mid}.json.gz"
        if not path.exists():
            path = cache / f"{mid}.json"
        if not path.exists():
            errors.append(f"missing raw cache {mid}")
            continue
        packed = path.read_bytes()
        raw = gzip.decompress(packed) if path.suffix == ".gz" else packed
        detail = json.loads(raw)
        content = detail.get("content") or {}
        players = content.get("playerStats") or {}
        players = players if isinstance(players, dict) else {}
        source["matches"] += 1
        source["compressed_bytes"] += len(packed)
        source["decoded_bytes"] += len(raw)
        source["player_dict_rows"] += len(players)
        per_comp[comp]["matches"] += 1
        active = 0
        for pid, player in players.items():
            stats = semantic(player)
            if not stats:
                source["empty_stat_players"] += 1
                continue
            active += 1
            source["active_stats"] += 1
            player_keys.update(stats.keys())
            xa = number(stats.get("expected_assists", {}).get("value"))
            chances = number(stats.get("chances_created", {}).get("value"))
            if xa is None:
                source["xa_absent"] += 1
                source["xa_absent_chances_" + ("unknown" if chances is None else "zero" if chances == 0 else "positive")] += 1
            else:
                source["xa_positive" if xa > 0 else "xa_zero"] += 1
                if chances == 0 and xa > 0:
                    source["xa_positive_with_zero_chances"] += 1
            expected[comp, mid, str(pid)] = stats
        per_comp[comp]["active_stats"] += active
        periods = (content.get("stats") or {}).get("Periods") or {}
        for group in (periods.get("All") or {}).get("stats") or []:
            for stat in group.get("stats") or []:
                pair = stat.get("stats")
                if stat.get("key") and isinstance(pair, list) and len(pair) == 2 and any(v is not None for v in pair):
                    team_keys[stat["key"]] += 1
        shots = (content.get("shotmap") or {}).get("shots") or []
        if shots:
            source["shotmap_matches"] += 1
        source["shots"] += len(shots)
        for shot in shots:
            shot_keys.update(shot.keys())
        typed_path = ROOT / "data/fotmob/semantic_stats" / f"{mid}.json.gz"
        if not typed_path.exists():
            errors.append(f"missing typed sidecar {mid}")
        else:
            typed = read_json(typed_path)
            if typed.get("team_stats") != content.get("stats"):
                errors.append(f"{mid}: typed team stat object differs")
            for pid, player in players.items():
                if (typed.get("players", {}).get(str(pid)) or {}).get("stats") != player.get("stats"):
                    errors.append(f"{mid}/{pid}: typed player stat groups differ")
                typed_players += 1
                typed_groups += len(player.get("stats") or [])
            typed_matches += 1
        if not active:
            lineup = content.get("lineup") or {}
            events = ((content.get("matchFacts") or {}).get("events") or {}).get("events") or []
            missing.append({"id": mid, "competition": comp, "home": fixture["home"], "away": fixture["away"],
                            "coverage_level": (detail.get("general") or {}).get("coverageLevel"),
                            "starters": sum(len(lineup.get(side, {}).get("starters") or []) for side in ("homeTeam", "awayTeam")),
                            "bench": sum(len(lineup.get(side, {}).get("subs") or []) for side in ("homeTeam", "awayTeam")),
                            "goal_events": sum(e.get("type") == "Goal" and not e.get("isPenaltyShootoutEvent") for e in events),
                            "shots": len(shots), "team_stat_periods": len(periods)})
    input_info = validate_player_inputs(ROOT / "data/fotmob/players", season, master)
    csv_rows = 0
    for path in sorted((ROOT / "data/fotmob/players").rglob(f"*-{season}.csv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                comp, mid, pid = row["competition"], str(row["match_id"]), str(row["player_id"])
                if (comp, mid) not in selected:
                    continue
                csv_rows += 1
                stats = expected.get((comp, mid, pid), {})
                for metric in ADDITIONAL_METRICS:
                    info = METRIC_REGISTRY[metric]
                    want = number(stats.get(info["source_key"], {}).get(info["source_part"]))
                    actual = number(row.get(metric))
                    source_values += 1
                    if (want is None) != (actual is None) or want is not None and abs(want - actual) > 1e-9:
                        errors.append(f"{mid}/{pid}/{metric}: CSV {actual} differs from semantic source {want}")
                for metric in METRIC_REGISTRY:
                    value = number(row.get(metric))
                    if value is not None:
                        values[metric].append(value)
    build_start = time.perf_counter()
    payload = build_players(master, season, cutoff, ROOT / "data/fotmob/players")
    build_seconds = time.perf_counter() - build_start
    raw = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
    packed = gzip.compress(raw, mtime=0)
    parse = {"skipped": "node unavailable"}
    if shutil.which("node"):
        code = """const fs=require('fs'),p=require('perf_hooks');const raw=fs.readFileSync(0,'utf8');global.gc();const b=process.memoryUsage();const t=p.performance.now();const x=JSON.parse(raw);const ms=p.performance.now()-t;global.gc();const a=process.memoryUsage();console.log(JSON.stringify({milliseconds:ms,retained_heap_bytes:a.heapUsed-b.heapUsed,rss_bytes:a.rss-b.rss,competitions:Object.keys(x.competitions).length}));"""
        process = subprocess.run(["node", "--expose-gc", "-e", code], input=raw, capture_output=True, check=True)
        parse = json.loads(process.stdout)
    metrics = {}
    for metric, numbers in sorted(values.items()):
        players = [p for c in payload["competitions"].values() for p in c["players"]]
        metrics[metric] = {"known_appearances": len(numbers), "observed_sum": round(math.fsum(numbers), 8),
                           "complete_player_totals": sum(p[metric] is not None for p in players),
                           "partial_player_totals": sum(metric in p["observed"] for p in players)}
    typed_files = list((ROOT / "data/fotmob/semantic_stats").glob("*.json.gz"))
    return {"season": season, "as_of": cutoff, "schema": payload["schema"], "metrics": metrics,
            "cache": {"files": len(files), "gzip_files": sum(p.suffix == ".gz" for p in files),
                      "bytes": sum(p.stat().st_size for p in files)},
            "source": dict(source), "competitions": {k: dict(v) for k, v in sorted(per_comp.items())},
            "input": {**input_info, "eligible_rows": csv_rows,
                      "bytes": sum(p.stat().st_size for p in (ROOT / "data/fotmob/players").rglob(f"*-{season}.csv"))},
            "semantic_player_keys": dict(sorted(player_keys.items())), "team_stat_keys": dict(sorted(team_keys.items())),
            "shot_keys": sorted(shot_keys), "missing_player_stats": missing,
            "typed": {"files": len(typed_files), "bytes": sum(p.stat().st_size for p in typed_files),
                      "matches_checked": typed_matches, "player_entries_checked": typed_players,
                      "stat_groups_checked": typed_groups},
            "checks": {"semantic_scalar_cells": source_values, "errors": len(errors), "examples": errors[:20]},
            "payload": {"compact_decoded_bytes": len(raw), "compact_gzip_bytes": len(packed),
                        "default_decoded_bytes": len(json.dumps(payload, allow_nan=False).encode()),
                        "default_gzip_bytes": len(gzip.compress(json.dumps(payload, allow_nan=False).encode(), mtime=0)),
                        "build_seconds": build_seconds,
                        "json_parse": parse, "observed_policy": payload["observed_policy"]},
            "previous": compare_old(read_json(previous), payload) if previous else {"skipped": "--previous not supplied"},
            "seconds": time.perf_counter() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    result = audit(args.season, args.as_of, args.previous)
    print(json.dumps(result, indent=2, allow_nan=False))
    return int(result["checks"]["errors"] > 0 or result["previous"].get("mismatches", 0) > 0)


if __name__ == "__main__":
    raise SystemExit(main())
