#!/usr/bin/env python3
"""Match forecasts against 90-minute results, using the last eligible nightly snapshot.

A folder date is the nominal forecast date, including retrospective backfills. ``as_of`` is
the last day of results the snapshot saw, so it must be strictly before the match's day. A
morning forecast on match day is eligible when its data ends the day before; a catch-up run
through match day is not. The real file-generation timestamp cannot order a backfilled history.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from scripts.projection import MODEL_GENERATION


MODEL = MODEL_GENERATION
LEGACY_MODEL = "2026-10-21"  # unstamped v10 / dated v4 files predate qualification generation
OUTCOMES = ("h1", "d", "a1")


def _result(row: Dict[str, Any], first_leg: Optional[Dict[str, Any]] = None) -> int:
    """Recover the match's result at 90, including aggregate-level return legs (FINDINGS §2e)."""
    if row.get("outcome") in ("afterextratime", "penalties"):
        # A single leg was level at 90; in a return leg the AGGREGATE was level. Its home
        # side was away in leg one, so its 90-minute margin equals leg one's home margin.
        # This is the existing analysis/match_shock.py convention, used for the goal layer.
        margin = (float(first_leg["home_goals"]) - float(first_leg["away_goals"])
                  if first_leg is not None else 0.0)
        if not math.isfinite(margin):
            raise ValueError("first leg has no finite score")
        return 0 if margin > 0 else 2 if margin < 0 else 1
    home, away = float(row["home_goals"]), float(row["away_goals"])
    if not math.isfinite(home) or not math.isfinite(away):
        raise ValueError("played fixture has no finite score")
    return 0 if home > away else 2 if home < away else 1


def _key(row: Dict[str, Any]) -> tuple:
    return (row["competition"], row["home"], row["away"], str(row["kickoff"])[:10])


def _results90(rows: list) -> Dict[tuple, int]:
    """Recover once per played fixture, using a chronological lookup rather than each forecast."""
    results: Dict[tuple, int] = {}
    first_legs: Dict[tuple, Optional[Dict[str, Any]]] = {}
    previous: Dict[tuple, Dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: (pd.Timestamp(r["kickoff"]), int(r["season"]),
                                          r["competition"], r["home"], r["away"])):
        key = _key(row)
        if key in results:
            if _result(row, first_legs[key]) != results[key]:
                raise ValueError(f"conflicting played results for {key}")
            continue
        # UEFA phases have numbered rounds; knockout stages have no round number. All 58
        # reversed ET pairings in the current master have null rounds on both legs. Comparing
        # any explicit stage too prevents a different stage's meeting acting as a first leg.
        stage = row.get("stage")
        stage = "" if stage is None or pd.isna(stage) else str(stage)
        knockout = row.get("kind") != "league" and pd.isna(row.get("round"))
        pair = (row["competition"], int(row["season"]), row["home"], row["away"], stage)
        reverse = (pair[0], pair[1], pair[3], pair[2], stage)
        first = previous.get(reverse) if knockout else None
        if first is not None:
            gap = pd.Timestamp(row["kickoff"]) - pd.Timestamp(first["kickoff"])
            if not pd.Timedelta(0) < gap < pd.Timedelta(days=60):
                first = None
        results[key] = _result(row, first)
        first_legs[key] = first
        if knockout:
            previous[pair] = row
    return results


def _model(payload: Dict[str, Any], day: str) -> str:
    return payload.get("model") or (LEGACY_MODEL if payload.get("version", 1) >= 10
                                    or day >= "2026-10-09" else "before " + LEGACY_MODEL)


def build_track(master: pd.DataFrame, snapshot_root: Path, season: int,
                as_of: Optional[str] = None) -> Dict[str, Any]:
    """Build a track-record payload without writing files or modifying the master frame.

    Forecast keys are competition, home, away and kickoff day, because a later snapshot may
    know a corrected kickoff time. A postponement to another day is a different forecast key.
    Stored probabilities keep their four-decimal rounding; H+D+A may therefore miss one by
    0.0001. Invalid ladders fail the isolated nightly step rather than silently entering scores.
    """
    # Never read a column through a frame carrying the simulator's potentially large attrs.
    fixtures = master.copy(deep=False)
    fixtures.attrs = {}
    rows = fixtures.to_dict("records")
    live = [r for r in rows if int(r["season"]) == season and bool(r["played"])
            and not bool(r.get("tbd", False))]
    cutoff = str(pd.Timestamp(as_of).date()) if as_of else (
        max((str(r["kickoff"])[:10] for r in live), default=None))
    result_rows = [r for r in rows if bool(r["played"]) and not bool(r.get("tbd", False))
                   and (2021 <= int(r["season"]) <= 2025
                        or (int(r["season"]) == season and cutoff is not None
                            and str(r["kickoff"])[:10] <= cutoff))]
    results90 = _results90(result_rows)
    unique: Dict[tuple, Dict[str, Any]] = {}
    for row in live:
        if cutoff is not None and str(row["kickoff"])[:10] > cutoff:
            continue
        unique.setdefault(_key(row), row)

    base_counts: Dict[str, list] = {}
    for row in rows:
        if 2021 <= int(row["season"]) <= 2025 and bool(row["played"]) \
                and not bool(row.get("tbd", False)):
            counts = base_counts.setdefault(row["kind"], [0, 0, 0])
            counts[results90[_key(row)]] += 1
    base_rates = {kind: {"n": sum(counts), "prob": [n / sum(counts) for n in counts]}
                  for kind, counts in sorted(base_counts.items())}

    snapshots: Counter = Counter(total=0, current=0, older=0)
    selected: Dict[tuple, Dict[str, Any]] = {}
    root = Path(snapshot_root)
    for directory in sorted(root.iterdir()) if root.exists() else []:
        if not directory.is_dir():
            continue
        day = directory.name
        try:
            if date.fromisoformat(day).isoformat() != day:
                continue
        except ValueError:
            continue
        if cutoff is None or day > cutoff:
            continue
        projection, matches = directory / "projection.json", directory / "matches.json"
        if not projection.exists() or not matches.exists():
            continue
        payload = json.loads(projection.read_text())
        if payload.get("params", {}).get("season") != season:
            continue
        source_asof = payload.get("as_of") or day
        model = _model(payload, day)
        current = model == MODEL
        snapshots["total"] += 1
        snapshots["current" if current else "older"] += 1
        for forecast in json.loads(matches.read_text()).get("fixtures", []):
            key = _key(forecast)
            if key not in unique or day > key[3] or source_asof >= key[3] \
                    or forecast.get("result") is not None:
                continue
            ladder = forecast.get("ladder", {})
            if not all(k in ladder for k in OUTCOMES):
                continue
            prob = [float(ladder[k]) for k in OUTCOMES]
            if any(not math.isfinite(p) or p < 0 or p > 1 for p in prob) \
                    or abs(sum(prob) - 1) > 0.000150001:
                raise ValueError(f"invalid H/D/A ladder in snapshot {day}: {key}: {prob}")
            real = unique[key]
            # Dates are traversed oldest first: the final assignment IS the last eligible one.
            selected[key] = {"date": key[3], "kickoff": str(real["kickoff"]),
                             "competition": key[0], "kind": real["kind"],
                             "home": key[1], "away": key[2], "prob": prob,
                             "result": results90[key], "snapshot": day,
                             "version": payload.get("version", 1), "current": current,
                             "model": model, "as_of": source_asof}
    evaluated = sorted(selected.values(), key=lambda r: (
        r["kickoff"], r["competition"], r["home"], r["away"]))
    return {"season": season, "as_of": cutoff,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "snapshots": dict(snapshots), "base_rates": base_rates, "matches": evaluated,
            "coverage": {"played": len(unique), "forecast": len(evaluated),
                         "missing": len(unique) - len(evaluated)}, "selection": "last"}


def write_track(payload: Dict[str, Any], snapshot_root: Path) -> Path:
    """Archive an existing report outside the repo, then atomically publish its replacement."""
    root = Path(snapshot_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "track.json"
    if destination.exists():
        archive = Path(tempfile.gettempdir()) / f"Football_archive_{date.today()}_track"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, archive / f"track_{time.time_ns()}.json")
    with tempfile.NamedTemporaryFile(mode="w", dir=root, prefix=".track-", suffix=".json",
                                     delete=False, encoding="utf-8") as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, allow_nan=False)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
