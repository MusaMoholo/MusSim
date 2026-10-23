"""Audit UEFA 90-minute results against the local FotMob cache, without network access.

The Track record roadmap initially called every extra-time or shootout match a draw.
In a return leg only the aggregate must be level: its match result at 90 minutes has
the first leg's margin. This checks the existing ``match_shock.py`` reconstruction
against cached full-time events for every such UEFA match in seasons 2021–2025.

    .venv/bin/python analysis/track_90min.py
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

EXTRA = {"afterextratime", "penalties"}
LABELS = ("H", "D", "A")


def result(home: object, away: object) -> int:
    home, away = float(home), float(away)
    if not all(math.isfinite(x) and x >= 0 and x.is_integer() for x in (home, away)):
        raise ValueError(f"invalid score: {home}, {away}")
    return 0 if home > away else 2 if home < away else 1


def first_leg(row: dict, rows: list[dict]) -> dict | None:
    """Mirror match_shock.py's same-competition, reversed-sides, prior-60-day rule."""
    candidates = [other for other in rows
                  if other["competition"] == row["competition"]
                  and other["season"] == row["season"]
                  and other["home"] == row["away"] and other["away"] == row["home"]
                  and row["kickoff"] - pd.Timedelta(days=60)
                  < other["kickoff"] < row["kickoff"]]
    return max(candidates, key=lambda other: (
        other["kickoff"], other["home"], other["away"], int(other["match_id"]))) \
        if candidates else None


def cached_result(row: dict) -> tuple[int, tuple[int, int]]:
    match_id = int(row["match_id"])
    path = ROOT / "data/fotmob/matches" / f"{match_id}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if int(payload["general"]["matchId"]) != match_id:
        raise ValueError(f"cache ID mismatch for {match_id}")
    events = payload["content"]["matchFacts"]["events"]["events"]
    full_time = [event for event in events if event.get("type") == "Half"
                 and event.get("time") == 90 and event.get("halfStrKey") == "fulltime_short"]
    if len(full_time) != 1:
        raise ValueError(f"match {match_id} has {len(full_time)} full-time-at-90 events")
    score = (full_time[0]["homeScore"], full_time[0]["awayScore"])
    return result(*score), score


def main() -> int:
    master = pd.read_pickle(ROOT / "data/master_fixtures.pkl")
    master.attrs = {}
    population = master[(master.kind == "uefa") & master.season.between(2021, 2025)
                        & master.played & ~master.tbd].copy()
    rows = population.sort_values(["kickoff", "competition", "home", "away"]).to_dict("records")
    extra = [row for row in rows if row["outcome"] in EXTRA]
    if not rows or not extra:
        raise ValueError("the audit population is empty")

    before, after, summary = Counter(), Counter(), Counter()
    mismatches, examples = [], []
    for row in rows:
        final = result(row["home_goals"], row["away_goals"])
        before[1 if row["outcome"] in EXTRA else final] += 1
        recovered = final
        if row["outcome"] in EXTRA:
            leg = first_leg(row, rows)
            recovered = result(leg["home_goals"], leg["away_goals"]) if leg else 1
            cached, score = cached_result(row)
            if cached != recovered:
                mismatches.append((row["match_id"], LABELS[recovered], LABELS[cached]))
            summary[("return leg" if leg else "single final", row["outcome"], LABELS[cached])] += 1
            if int(row["match_id"]) in {4384185, 3846342, 4737723}:
                examples.append((int(row["match_id"]), row["home"], row["away"], score,
                                 (row["home_goals"], row["away_goals"]), LABELS[cached]))
        after[recovered] += 1

    print(f"UEFA seasons 2021–2025: {len(rows)} played matches; {len(extra)} ET/shootout matches")
    print(f"Cached full-time-at-90 events: {len(extra)}/{len(extra)}; reconstruction mismatches: {len(mismatches)}")
    for (stage, outcome, label), count in sorted(summary.items()):
        print(f"  {stage:12s} {outcome:14s} {label}: {count}")
    changed = sum(count for (_, _, label), count in summary.items() if label != "D")
    print(f"Calling all ET/shootout matches draws changes {changed}/{len(extra)} outcomes")
    print("Base counts H / D / A:")
    print("  all ET as draws:", " / ".join(str(before[i]) for i in range(3)))
    print("  recovered at 90:", " / ".join(str(after[i]) for i in range(3)))
    print("Base rates H / D / A:")
    print("  all ET as draws:", " / ".join(f"{before[i] / len(rows):.6f}" for i in range(3)))
    print("  recovered at 90:", " / ".join(f"{after[i] / len(rows):.6f}" for i in range(3)))
    print(f"Draw-base overstatement: {100 * (before[1] - after[1]) / len(rows):.4f} percentage points")
    for match_id, home, away, score, final, label in examples:
        print(f"  example {match_id}: {home} v {away}: at 90 {score}, final {final}, result {label}")
    if mismatches:
        print("FAIL:", mismatches)
        return 1
    print(f"PASS: all {len(extra)} inferred results equal their cached 90-minute results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
