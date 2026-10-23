#!/usr/bin/env python3
"""Read-only snapshot coverage and probability-bound audit; never rewrites forecasts.

    .venv/bin/python analysis/overview_snapshot_audit.py

Exit 1 means stored out-of-range/nonfinite probability cells were found. Historical
replays may finish their pipeline successfully yet still fail these numerical bounds.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=Path(__file__).resolve().parents[1] / "data/snapshots")
    args = parser.parse_args()
    files = sorted(args.snapshots.glob("*/projection.json"))
    models: Counter = Counter()
    versions: Counter = Counter()
    cells = 0
    bad = []
    for file in files:
        payload = json.loads(file.read_text())
        models[payload.get("model", "unavailable")] += 1
        versions[payload.get("version", 1)] += 1
        for family in ("leagues", "uefa", "cups"):
            for block in payload.get(family, []):
                for team in block.get("teams", []):
                    for metric, value in team.items():
                        if not metric.startswith("p_") or not isinstance(value, (int, float)):
                            continue
                        cells += 1
                        if not math.isfinite(value) or not 0 <= value <= 1:
                            bad.append((file.parent.name, block["competition"], team["team"], metric, value))
    print(f"Snapshots: {len(files)}; {files[0].parent.name if files else 'none'} through {files[-1].parent.name if files else 'none'}")
    print(f"Payload versions: {dict(versions)}; models: {dict(models)}")
    print(f"Probability bounds: {cells} stored cells; {len(bad)} invalid on {len({row[0] for row in bad})} dates")
    for date, competition, team, metric, value in bad:
        print(f"FAIL {date} | {competition} | {team} | {metric} = {value}")
    return int(bool(bad) or not files)


if __name__ == "__main__":
    raise SystemExit(main())
