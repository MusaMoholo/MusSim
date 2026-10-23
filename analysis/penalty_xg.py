#!/usr/bin/env python3
"""Penalty xG: how much xG a side's penalties add to its npxG, by competition and kind.

    .venv/bin/python analysis/penalty_xg.py

FotMob's xG includes penalties and its npxG does not, so xG - npxG is a side's penalty xG in a
match, and it moves in steps of ~0.79 (one penalty). The model fits npxG and never uses xG; the
dashboard's x+/x-, xGD and xG PTS turn a projected match's drawn npxG into xG by adding a
competition's MEAN penalty xG a side a match (`projection.penalty_xg`). This prints that constant
per competition, and the facts behind keeping it a per-competition constant rather than a per-team
model: the value of one penalty, the rate by kind of competition and venue, and how weakly the
rate rises with a side's own npxG.
"""
import numpy as np
import pandas as pd

m = pd.read_pickle("data/master_fixtures.pkl")
p = m[m.played & m.home_xg.notna() & m.home_npxg.notna() & m.away_xg.notna() & m.away_npxg.notna()]
d = pd.concat([pd.DataFrame({"comp": p.competition, "kind": p.kind, "season": p.season,
                             "home": s == "home", "npxg": p[f"{s}_npxg"],
                             "pxg": p[f"{s}_xg"] - p[f"{s}_npxg"]}) for s in ("home", "away")],
              ignore_index=True)
d["pens"] = np.round(d.pxg / 0.785).clip(lower=0)
per = d.pxg[d.pens > 0] / d.pens[d.pens > 0]
print(f"{len(d)} side-matches; xG a penalty {per.mean():.4f} (sd {per.std():.4f}); "
      f"penalties a side a match {d.pens.mean():.4f}; penalty xG a side a match {d.pxg.mean():.4f}")
print("penalties a side a match, by kind:", d.groupby("kind").pens.mean().round(4).to_dict())
print("by venue (home True):", d.groupby("home").pens.mean().round(4).to_dict())
print("by season:", d.groupby("season").pens.mean().round(4).to_dict())
d["bin"] = pd.qcut(d.npxg, 8)
print("\nby the side's own npxG (octiles):")
print(d.groupby("bin", observed=True).agg(n=("pens", "size"), pens=("pens", "mean"),
                                          npxg=("npxg", "mean")).round(3).to_string())
coef = np.linalg.lstsq(np.c_[np.ones(len(d)), d.npxg], d.pens, rcond=None)[0]
print(f"pens = {coef[0]:.4f} + {coef[1]:.4f} * npxG")
print("\nthe constant the dashboard uses, penalty xG a side a match:")
print(d.groupby("comp").pxg.mean().round(4).sort_values().to_string())
