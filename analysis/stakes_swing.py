"""What rides on a match, per competition: the widest swing a result makes to either side's
season (`projection.Accumulator._stakes`, payload version 10), over a snapshot's projected
league and league-phase fixtures.

The swing is, over both sides and every fate (a league's title / UCL / Europe / relegation, a
league phase's top 8 / top 24 / R16 / win), the gap between the fate's chance with the best and
worst result. Printed per competition: the median and the 90th percentile over its fixtures --
the reason the Big matches tab ranks inside each competition rather than across them.

    .venv/bin/python analysis/stakes_swing.py [SNAPSHOT_DATE]   # default: the newest
"""
import gzip
import json
import sys
from pathlib import Path

import numpy as np

root = Path("data/snapshots")
day = sys.argv[1] if len(sys.argv) > 1 else sorted(p.name for p in root.iterdir() if p.is_dir())[-1]
compressed, plain = root / day / "gw.json.gz", root / day / "gw.json"
if compressed.exists():
    with gzip.open(compressed, "rt", encoding="utf-8") as handle:
        gw = json.load(handle)
else:
    gw = json.loads(plain.read_text())
print(f"snapshot {day}")
for kind, blocks in (("league", gw["leagues"]), ("uefa", gw.get("phases", {}))):
    for comp, g in sorted(blocks.items()):
        sw = []
        for f in g["fixtures"]:
            if f.get("result") or "stakes" not in f:
                continue
            best = 0.0
            for side in f["stakes"]:
                for v in side:
                    r = [x for x in (v if isinstance(v, list) else [v, v, v]) if x is not None]
                    best = max(best, max(r) - min(r))
            sw.append(100 * best)
        if sw:
            print(f"  {comp:28s} {len(sw):4d} matches  median {np.median(sw):5.1f}pp  90th {np.percentile(sw, 90):5.1f}pp")
