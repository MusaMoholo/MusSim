"""Penalty goals off FotMob's shot maps, cross-checked against xG minus npxG.

Two independent counts of penalties TAKEN per side and match: the shot map's shots whose
`situation` is "Penalty" (a shootout's kicks, period "PenaltyShootout", left out), and FotMob's
xG minus npxG, which moves in steps of 0.785 a penalty. Agreement on every side-match is what
licenses the shot map's penalty GOALS (`fetch_fotmob.extract_pen_goals`) as the non-penalty
goals the Goals v xG chart reads against npxG.

    .venv/bin/python analysis/penalty_goals.py [SEASON]     # default: the latest in the master
"""
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from scripts.fetch_fotmob import CACHE_DIR, extract_pen_goals  # noqa: E402

m = pd.read_pickle("data/master_fixtures.pkl")
season = int(sys.argv[1]) if len(sys.argv) > 1 else int(m.season.max())
g = m[(m.season == season) & m.played & m.home_xg.notna() & m.home_npxg.notna()]
tot = agree = nomap = taken_shot = taken_xg = goals = impossible = 0
for r in g.itertuples():
    p = CACHE_DIR / f"{int(r.match_id)}.json.gz"
    if not p.exists():
        continue
    d = json.load(gzip.open(p))
    hid, aid = d["general"]["homeTeam"]["id"], d["general"]["awayTeam"]["id"]
    hg, ag = extract_pen_goals(d, hid, aid)
    if hg is None:
        nomap += 1
        continue
    shots = [s for s in d["content"]["shotmap"]["shots"]
             if s.get("situation") == "Penalty" and s.get("period") != "PenaltyShootout"]
    for tid, xg, npxg, pg, gl in ((hid, r.home_xg, r.home_npxg, hg, r.home_goals),
                                  (aid, r.away_xg, r.away_npxg, ag, r.away_goals)):
        a = sum(1 for s in shots if s["teamId"] == tid)
        b = int(round((xg - npxg) / 0.785))
        tot += 1
        agree += a == b
        taken_shot += a
        taken_xg += b
        goals += pg
        impossible += pg > a or pg > gl
print(f"season {season}: {tot} side-matches ({nomap} matches without a shot map)")
print(f"  penalties taken agree on {agree} of {tot}: shot map {taken_shot}, xG - npxG {taken_xg}")
print(f"  penalty goals {goals} ({goals / max(taken_shot, 1):.0%} converted); impossible counts {impossible}")
