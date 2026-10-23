#!/usr/bin/env python3
"""Reproduce player-stat/shot-map/team xG disagreements using cached matches only.

    .venv/bin/python analysis/player_source_audit.py --season 2026 --as-of 2026-10-20

The grouped bound is 0.005 per explicit two-decimal player xG plus 0.005 for team xG.
Shot-map xG has full precision, so only the team's 0.005 rounding enters its bound.
Neither source is rescaled. Optional extractor checking compares each output xG directly to
the independently read semantic player stat; source disagreements are counted separately.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def number(value):
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def semantic(player):
    result = {}
    for group in player.get("stats") or []:
        entries = group.get("stats") or {}
        for entry in entries.values() if isinstance(entries, dict) else entries:
            if isinstance(entry, dict) and entry.get("key"):
                result[entry["key"]] = number((entry.get("stat") or {}).get("value"))
    return result


def read_detail(mid, cache_root):
    for suffix in (".json.gz", ".json"):
        path = Path(cache_root) / (str(mid) + suffix)
        if path.exists():
            raw = path.read_bytes()
            return json.loads(gzip.decompress(raw) if suffix.endswith("gz") else raw)
    return None


def audit_sources(master, season, as_of, cache_root=None, extractor=None):
    """Return source accounting and, optionally, independent extractor identities."""
    cache_root = cache_root or ROOT / "data/fotmob/matches"
    attrs, master.attrs = master.attrs, {}
    try:
        records = master.to_dict("records")
    finally:
        master.attrs = attrs
    eligible = [r for r in records if int(r["season"]) == int(season) and bool(r["played"])
                and not bool(r.get("tbd", False)) and str(r["kickoff"])[:10] <= str(as_of)
                and number(r.get("home_goals")) is not None and number(r.get("away_goals")) is not None]
    eligible.sort(key=lambda r: (str(r["kickoff"]), r["competition"], r["home"], r["away"]))
    counters = {s: Counter() for s in ("shot_xg", "player_xg", "goals")}
    comps = {}; exceptions = {s: [] for s in counters}; missing = []
    feature = {"rows": 0, "semantic_values": 0, "goal_sides": 0, "errors": []}
    sources = Counter(); own_goals = 0; cache_matches = 0; mapped_matches = 0
    for fixture in eligible:
        mid = str(int(float(fixture["match_id"])))
        detail = read_detail(mid, cache_root)
        if detail is None:
            missing.append([mid, fixture["competition"], "missing cache"])
            continue
        cache_matches += 1
        content, general = detail.get("content") or {}, detail.get("general") or {}
        ids = {str((general.get(side + "Team") or {}).get("id")): side for side in ("home", "away")}
        players = {str(pid): p for pid, p in (content.get("playerStats") or {}).items() if isinstance(p, dict)}
        stats = {pid: semantic(p) for pid, p in players.items()}
        raw = (content.get("shotmap") or {}).get("shots")
        has_map = isinstance(raw, list) and bool(raw)
        if has_map:
            mapped_matches += 1
        else:
            missing.append([mid, fixture["competition"], "empty/missing shot map"])
        shots = []; seen = set()
        for i, shot in enumerate(raw if isinstance(raw, list) else []):
            sid = str(shot.get("id", f"row-{i}"))
            if sid in seen or shot.get("period") == "PenaltyShootout":
                continue
            seen.add(sid); shots.append(shot)
        by_player = {pid: [] for pid in players}
        side_shots = {side: [] for side in ("home", "away")}
        for shot in shots:
            pid = str(shot.get("playerId") or "")
            if pid not in players:
                candidates = [p for p, rec in players.items() if str(rec.get("teamId")) == str(shot.get("teamId"))
                              and rec.get("name") == shot.get("playerName")]
                pid = candidates[0] if len(candidates) == 1 else f"unknown:{shot.get('teamId')}:{shot.get('playerName') or shot.get('id')}"
            by_player.setdefault(pid, []).append(shot)
            tid = str(players.get(pid, {}).get("teamId", shot.get("teamId")))
            side = ids.get(tid)
            if side:
                side_shots[side].append(shot)
        chosen = {side: [] for side in ("home", "away")}; explicit = Counter()
        expected = {}
        for pid, player in players.items():
            values, mine = stats[pid], by_player.get(pid, [])
            if not values and not mine:
                continue
            side = ids.get(str(player.get("teamId")))
            if not side:
                continue
            attempts = [s for s in mine if not s.get("isOwnGoal")]
            value = values.get("expected_goals")
            source = "player_stats" if value is not None else "no_shots" if has_map and not attempts else "unknown"
            value = 0.0 if source == "no_shots" else value
            chosen[side].append(value); explicit[side] += source == "player_stats"; sources[source] += 1
            expected[pid, side] = (value, source)
        # Unidentified shooters cannot manufacture a known team total.
        for pid, mine in by_player.items():
            if pid not in players and mine:
                side = ids.get(str(mine[0].get("teamId")))
                if side:
                    chosen[side].append(None); sources["unknown"] += 1
        extracted = None
        if extractor:
            fx = {**fixture, "match_id": mid, "finished": True,
                  **{side + "_id": (general.get(side + "Team") or {}).get("id") for side in ("home", "away")}}
            extracted = extractor(fx, detail)
            feature["rows"] += len(extracted)
            present = set()
            for row in extracted:
                side, pid = row.get("side"), str(row.get("player_id"))
                if side not in {"home", "away"} or row.get("team") != fixture.get(side):
                    feature["errors"].append(f"{mid}/{pid}: noncanonical club or side")
                    continue
                want = expected.get((pid, side))
                if want:
                    present.add((pid, side)); feature["semantic_values"] += 1
                    value = number(row.get("xg"))
                    if (want[0] is None) != (value is None) or want[0] is not None and abs(value - want[0]) > 1e-9:
                        feature["errors"].append(f"{mid}/{pid}: extracted xG {value}, semantic source {want[0]}")
                elif number(row.get("xg")) is not None:
                    feature["errors"].append(f"{mid}/{pid}: unidentified shooter has invented xG")
            for absent in set(expected) - present:
                feature["errors"].append(f"{mid}/{absent[0]}: participant missing")
        comp_counts = comps.setdefault(fixture["competition"], {s: Counter() for s in counters})
        for side, opposite in (("home", "away"), ("away", "home")):
            team = fixture[side]
            normal = [s for s in side_shots[side] if not s.get("isOwnGoal")]
            own = sum(s.get("eventType") == "Goal" and bool(s.get("isOwnGoal")) for s in side_shots[opposite])
            own_goals += own
            source_goals = sum(s.get("eventType") == "Goal" for s in normal) + own if has_map else None
            raw_xg = [number(s.get("expectedGoals")) for s in normal]
            raw_total = math.fsum(raw_xg) if has_map and all(v is not None for v in raw_xg) else None
            vals = chosen[side]
            grouped = math.fsum(vals) if vals and all(v is not None for v in vals) else None
            for label, value, target, bound in (("goals", source_goals, number(fixture[side + "_goals"]), 0),
                    ("shot_xg", raw_total, number(fixture.get(side + "_xg")), .005),
                    ("player_xg", grouped, number(fixture.get(side + "_xg")), .005 * explicit[side] + .005)):
                state = "unknown" if value is None or target is None else "within" if abs(value - target) <= bound + 1e-9 else "unreconciled"
                counters[label][state] += 1; comp_counts[label][state] += 1
                if state == "unreconciled":
                    exceptions[label].append({"match_id": mid, "competition": fixture["competition"], "team": team,
                        "value": value, "team_value": target, "difference": value - target, "bound": bound})
            if extracted and has_map:
                mine = [r for r in extracted if r.get("side") == side]
                other = [r for r in extracted if r.get("side") == opposite]
                if mine and other and all(number(r.get("goals")) is not None for r in mine) and all(number(r.get("own_goals")) is not None for r in other):
                    feature["goal_sides"] += 1
                    actual = sum(r["goals"] for r in mine) + sum(r["own_goals"] for r in other)
                    if actual != fixture[side + "_goals"]:
                        feature["errors"].append(f"{mid}/{team}: player goals+benefiting own goals {actual}, GF {fixture[side + '_goals']}")
                else:
                    feature["errors"].append(f"{mid}/{team}: known shot-map goals became unavailable")
    return {"season": int(season), "as_of": str(as_of), "matches": len(eligible), "cache_matches": cache_matches,
            "mapped_matches": mapped_matches, "own_goals": own_goals, "sources": dict(sources),
            **{k: dict(v) for k, v in counters.items()}, "by_competition": comps,
            "missing": missing, "exceptions": exceptions, "feature": feature}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--as-of", default="2026-10-20")
    parser.add_argument("--exceptions-json", type=Path)
    args = parser.parse_args()
    audit = audit_sources(pd.read_pickle(ROOT / "data/master_fixtures.pkl"), args.season, args.as_of)
    print(f"season {args.season}, through {args.as_of}: {audit['matches']} played matches, {audit['cache_matches']} caches, {audit['mapped_matches']} nonempty shot maps")
    print(f"player xG sources: {audit['sources']}; own goals: {audit['own_goals']}")
    for source in ("goals", "shot_xg", "player_xg"):
        print(f"{source}: {audit[source]}")
        if audit["exceptions"][source]:
            print("  largest:", json.dumps(max(audit["exceptions"][source], key=lambda r: abs(r["difference"])), ensure_ascii=False))
    for comp, values in sorted(audit["by_competition"].items()):
        print(comp + ": " + json.dumps(values, sort_keys=True))
    print("missing:", json.dumps(audit["missing"], ensure_ascii=False))
    if args.exceptions_json:
        if args.exceptions_json.exists():
            archive = Path(tempfile.mkdtemp(prefix="Football_archive_player_source_audit_"))
            shutil.copy2(args.exceptions_json, archive / args.exceptions_json.name)
        args.exceptions_json.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
        print("complete accounting:", args.exceptions_json)
    return 1 if audit["goals"].get("unreconciled", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
