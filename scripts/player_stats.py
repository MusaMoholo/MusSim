"""Cutoff-safe player totals from extracted FotMob match rows; no fetching or model work."""
from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.player_metrics import METRICS, METRIC_REGISTRY, PLAYER_FIELDS, PLAYER_SCHEMA_VERSION


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _id(value: Any) -> str:
    value = str(value or "").strip()
    return value[:-2] if value.endswith(".0") and value[:-2].isdigit() else value


def _true(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1"}


def _day(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _total(values: list[float | None]) -> int | float | None:
    if not values or any(v is None for v in values):
        return None
    total = math.fsum(values)
    return int(total) if total.is_integer() else round(total, 8)


def _observed(values: list[float | None]) -> int | float | None:
    """Sum known values explicitly; this is a partial contribution, never an assumed zero."""
    return _total([value for value in values if value is not None])


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = {key: [_number(row.get(key)) for row in rows] for key in METRICS}
    known = {key: sum(value is not None for value in vals) for key, vals in values.items()}
    return {"matches": len(rows), **{key: _total(vals) for key, vals in values.items()},
            "observed": {key: _observed(vals) for key, vals in values.items()
                         if 0 < known[key] < len(rows)}, "known": known}


def validate_player_inputs(players_root: str | Path, season: int, master=None) -> dict[str, int]:
    """Fail before simulation when project-only would silently consume an obsolete extraction.

    The field contract and every row's independent player-schema tag are checked. Empty files
    still need current headers. `master` is optional for callers that only have extracted inputs.
    """
    paths = sorted(Path(players_root).rglob(f"*-{season}.csv"))
    errors, count = [], 0
    if not paths:
        # A new season with no played matches may legitimately have no input files yet.
        if master is not None:
            attrs, master.attrs = master.attrs, {}
            try:
                records = master.to_dict("records")
            finally:
                master.attrs = attrs
            if not any(_number(r.get("season")) == int(season) and _true(r.get("played"))
                       and not _true(r.get("tbd")) for r in records):
                return {"schema": PLAYER_SCHEMA_VERSION, "files": 0, "rows": 0}
        errors.append("no extracted season files")
    for path in paths:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            missing = sorted(set(PLAYER_FIELDS) - set(reader.fieldnames or []))
            if missing:
                errors.append(f"{path.name}: missing columns {', '.join(missing[:5])}")
                continue
            for line, row in enumerate(reader, 2):
                count += 1
                if _number(row.get("player_schema")) != PLAYER_SCHEMA_VERSION:
                    errors.append(f"{path.name}:{line}: stale player_schema {row.get('player_schema')!r}")
                    break
    if errors:
        raise ValueError(f"Player inputs need schema {PLAYER_SCHEMA_VERSION}: " + "; ".join(errors[:4])
                         + f". Rebuild from the permanent cache (no network): "
                           f".venv/bin/python scripts/fetch_fotmob.py --season {season} --players-only")
    return {"schema": PLAYER_SCHEMA_VERSION, "files": len(paths), "rows": count}


def build_players(master, season: int, cutoff: str | None,
                  players_root: str | Path) -> dict[str, Any]:
    """Pool IDs within a competition while preserving every club's transfer contribution.

    `cutoff` is the snapshot's inclusive as_of calendar day, not the folder or generation date.
    Canonical clubs come from master fixture ID + home/away side, never a fuzzy name lookup.
    A total stays unknown if any included appearance is unknown; `known` exposes its coverage.
    """
    validate_player_inputs(players_root, season, master)
    cut = _day(cutoff)
    result: dict[str, Any] = {"schema": PLAYER_SCHEMA_VERSION, "metrics": METRIC_REGISTRY,
                              "observed_policy": "partial_only",
                              "season": int(season), "as_of": str(cut) if cut else None,
                              "competitions": {}}
    if cut is None:
        return result
    # Frames can carry a complete simulated world in attrs. Do not derive a column through it.
    attrs = master.attrs
    master.attrs = {}
    try:
        fixtures = master.to_dict("records")
    finally:
        master.attrs = attrs
    matches = {}
    for fixture in fixtures:
        kickoff = _day(fixture.get("kickoff"))
        if (_number(fixture.get("season")) != int(season) or not _true(fixture.get("played"))
                or _true(fixture.get("tbd")) or kickoff is None or kickoff > cut
                or not fixture.get("home") or not fixture.get("away")
                or _number(fixture.get("home_goals")) is None
                or _number(fixture.get("away_goals")) is None):
            continue
        key = (str(fixture["competition"]), _id(fixture.get("match_id")))
        if key[1]:
            matches[key] = fixture
    # One row per player per match. Prefer a more complete duplicate, then a total order, so
    # repeated/reshuffled CSV rows cannot double a transferred player's contribution.
    extracted: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for path in sorted(Path(players_root).rglob(f"*-{season}.csv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("competition", ""), _id(row.get("match_id")))
                fixture = matches.get(key)
                side, pid = row.get("side"), _id(row.get("player_id"))
                if fixture is None or side not in {"home", "away"} or not pid:
                    continue
                if _number(row.get("season")) != int(season):
                    continue
                clean = {"id": pid, "name": row.get("name") or pid,
                         "team": str(fixture[side]), "side": side,
                         **{metric: _number(row.get(metric))
                            for metric in (*METRICS, "own_goals", "stat_xg", "shot_xg")},
                         "xg_source": row.get("xg_source") or "unspecified"}
                fullkey = (*key, pid, side)
                previous = extracted.get(fullkey)
                rank = lambda r: (sum(r[m] is not None for m in (*METRICS, "own_goals")),
                                  tuple(str(r.get(m)) for m in sorted(r)))
                if previous is None or rank(clean) > rank(previous):
                    extracted[fullkey] = clean
    by_match: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (comp, mid, _, _), row in sorted(extracted.items()):
        by_match[comp, mid].append(row)
    by_comp: dict[str, list[tuple[tuple[str, str], dict[str, Any]]]] = defaultdict(list)
    for key, fixture in sorted(matches.items()):
        by_comp[key[0]].append((key, fixture))
    for comp, competition_matches in sorted(by_comp.items()):
        people: dict[str, list[dict[str, Any]]] = defaultdict(list)
        names: dict[str, list[tuple[str, str]]] = defaultdict(list)
        team_games: dict[str, list[dict[str, Any]]] = defaultdict(list)
        covered = 0
        xg_sources: Counter[str] = Counter()
        accounting = {key: {"compared": 0, "within_rounding": 0, "outside_rounding": 0,
                            "unknown": 0, "max_abs_difference": 0.0}
                      for key in ("xg", "shot_xg")}
        for key, fixture in competition_matches:
            rows = by_match.get(key, [])
            sides = {side: [r for r in rows if r["side"] == side] for side in ("home", "away")}
            covered += bool(sides["home"] and sides["away"])
            for row in rows:
                xg_sources[row["xg_source"]] += 1
                people[row["id"]].append(row)
                names[row["id"]].append((str(fixture["kickoff"]), row["name"]))
            for side, opposite in (("home", "away"), ("away", "home")):
                own_for = _total([r["own_goals"] for r in sides[opposite]])
                discrepancies = {}
                for metric in accounting:
                    observed = _total([r[metric] for r in sides[side]])
                    expected = _number(fixture.get(f"{side}_xg"))
                    comparison = accounting[metric]
                    if observed is None or expected is None:
                        comparison["unknown"] += 1
                        discrepancies[metric] = None
                    else:
                        comparison["compared"] += 1
                        difference = abs(observed - expected)
                        # Grouped player xG and team xG are each rounded to two decimals;
                        # no-shot zeroes are exact. Raw shot sums have only the team's .005.
                        rounded_players = sum(r["xg_source"] == "player_stats" for r in sides[side])
                        tolerance = .005 * (1 + (rounded_players if metric == "xg" else 0)) + 1e-9
                        outside = difference > tolerance
                        comparison["outside_rounding" if outside else "within_rounding"] += 1
                        comparison["max_abs_difference"] = max(comparison["max_abs_difference"], difference)
                        discrepancies[metric] = outside
                team_games[str(fixture[side])].append({
                    "covered": bool(sides[side]),
                    "xg_unreconciled": discrepancies["xg"],
                    "shot_xg_unreconciled": discrepancies["shot_xg"],
                    **{metric: _total([r[metric] for r in sides[side]]) for metric in METRICS},
                    "observed": {metric: _observed([r[metric] for r in sides[side]]) for metric in METRICS},
                    "appearances": len(sides[side]),
                    "known_appearances": {metric: sum(r[metric] is not None for r in sides[side]) for metric in METRICS},
                    "own_goals_for": own_for})
        players = []
        for pid, rows in sorted(people.items()):
            contributions = {team: _totals([r for r in rows if r["team"] == team])
                             for team in sorted({r["team"] for r in rows})}
            players.append({"id": pid, "name": max(names[pid])[1], "teams": list(contributions),
                            **_totals(rows), "by_team": contributions})
        players.sort(key=lambda p: (-(p["goals"] if p["goals"] is not None else -1),
                                    p["name"], p["id"]))
        teams = {}
        for team, games in sorted(team_games.items()):
            teams[team] = {"played": len(games), "covered": sum(g["covered"] for g in games),
                           "appearances": sum(g["appearances"] for g in games),
                           "known_appearances": {metric: sum(g["known_appearances"][metric] for g in games) for metric in METRICS},
                           "observed": {metric: _observed([g["observed"][metric] for g in games]) for metric in METRICS
                                        if any(g[metric] is None for g in games)
                                        and any(g["known_appearances"][metric] for g in games)},
                           "xg_unreconciled": sum(g["xg_unreconciled"] is True for g in games),
                           "shot_xg_unreconciled": sum(g["shot_xg_unreconciled"] is True for g in games),
                           **{metric: _total([g[metric] for g in games])
                              for metric in (*METRICS, "own_goals_for")},
                           "known": {metric: sum(g[metric] is not None for g in games)
                                     for metric in (*METRICS, "own_goals_for")}}
        for comparison in accounting.values():
            comparison["max_abs_difference"] = round(comparison["max_abs_difference"], 8)
        result["competitions"][comp] = {
            "coverage": {"played": len(competition_matches), "covered": covered,
                         "appearances": sum(len(rows) for rows in people.values()),
                         "missing": len(competition_matches) - covered,
                         "xg_sources": dict(sorted(xg_sources.items())),
                         "xg_accounting": accounting["xg"],
                         "shot_xg_accounting": accounting["shot_xg"],
                         "unknown": {metric: sum(r[metric] is None for rows in people.values()
                                                  for r in rows) for metric in METRICS}},
            "players": players, "teams": teams}
    return result


def main(argv=None) -> int:
    import argparse
    import json
    import sys
    import pandas as pd
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--players-root", type=Path, default=root / "data/fotmob/players")
    parser.add_argument("--master", type=Path, default=root / "data/master_fixtures.pkl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_players(pd.read_pickle(args.master), args.season, args.as_of, args.players_root)
    from scripts.fetch_fotmob import _write_derived
    raw = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
    _write_derived(args.output, raw, compressed=args.output.suffix == ".gz")
    print(f"wrote player schema {PLAYER_SCHEMA_VERSION}: {args.output} ({len(raw)} decoded bytes)")
    return 0


if __name__ == "__main__":
    # Direct script execution needs the repository package path before imports above as well.
    raise SystemExit(main())
