#!/usr/bin/env python3
"""Extra-time scoring rate: why 0.126 was wrong and 0.357 (~ pro-rata) is right.

FINDINGS section 3 recorded "extra-time scoring 0.126 of the 90-minute rate, NOT 30/90" from
"252 ties past 90 min; 73.8% reach penalties", and section 5 listed pro-rata as a wrong domain
prior. Both came from one pool: 186 rows with `outcome == 'penalties'` plus 66 with
`outcome == 'afterextratime'`, across ALL competitions.

120 of those 186 penalty rows are domestic-cup ties recorded at 90 minutes. The Coupe de France,
the English League Cup and the Coppa Italia send a level tie straight to a shootout -- no extra
time is played. Counting them as "still level AFTER extra time" is the same selection trap
section 5 warns about for the 3.82-goals figure, one conditioning step earlier.

This script prints the pooled figure, the UEFA-only figure, and the scoring fraction each implies.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.knockout import ET_FRACTION  # noqa: E402

PRO_RATA = 30.0 / 90.0


def p_level(f: float, lam: float, maxg: int = 25) -> float:
    """P(the 30 minutes of extra time are drawn) at fraction `f` of a 90-minute rate `lam`."""
    r = f * lam
    k = np.arange(maxg)
    logfact = np.array([float(np.sum(np.log(np.arange(1, i + 1)))) for i in k])
    pk = np.exp(-r + k * np.log(r) - logfact)
    return float((pk ** 2).sum())


def solve(target: float, lam: float) -> float:
    lo, hi = 1e-4, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if p_level(mid, lam) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main() -> int:
    m = pd.read_pickle(Path("data/master_fixtures.pkl"))
    p = m[m.played].copy()
    p["mins"] = pd.to_numeric(p.minutes, errors="coerce")

    pens_all = int((p.outcome == "penalties").sum())
    aet_all = int((p.outcome == "afterextratime").sum())
    print("the pooled figure FINDINGS recorded")
    print(f"  outcome == 'penalties'      {pens_all}")
    print(f"  outcome == 'afterextratime' {aet_all}")
    print(f"  pooled 'still level after extra time' = {pens_all}/{pens_all + aet_all} "
          f"= {pens_all / (pens_all + aet_all):.3f}")

    noet = p[(p.kind == "cup") & (p.outcome == "penalties") & (p.mins <= 90)]
    print(f"\n  but {len(noet)} of those {pens_all} are cup ties recorded at 90 minutes, i.e. no "
          "extra time was played:")
    for comp, n in noet.competition.value_counts().items():
        print(f"    {comp:26s} {n}")

    u = p[(p.kind == "uefa") & (p.mins > 90)]
    n_et, n_pk = len(u), int((u.outcome == "penalties").sum())
    lvl = n_pk / n_et
    se = np.sqrt(lvl * (1 - lvl) / n_et)
    ci = (lvl - 1.96 * se, lvl + 1.96 * se)
    print(f"\nUEFA knockouts only ({u.season.min()}-{u.season.max()})")
    print(f"  reached extra time            {n_et}")
    print(f"  still level after extra time  {n_pk}  = {lvl:.3f}  (95% CI {ci[0]:.3f}-{ci[1]:.3f})")

    reg = p[(p.kind == "uefa") & p["round"].isna() & (p.mins == 90.0)]
    lam = (pd.to_numeric(reg.home_goals, errors="coerce")
           + pd.to_numeric(reg.away_goals, errors="coerce")).mean() / 2
    print(f"  goals per team per 90         {lam:.3f}  (over {len(reg)} matches that finished in 90)")

    f_hat = solve(lvl, lam)
    f_lo, f_hi = solve(ci[1], lam), solve(ci[0], lam)
    print(f"\n  => extra-time fraction {f_hat:.3f}  (95% CI {f_lo:.3f}-{f_hi:.3f})")
    print(f"     pro-rata 30/90 = {PRO_RATA:.3f} is inside it, {abs(f_hat - PRO_RATA) / ((f_hi - f_lo) / 3.92):.2f} "
          "standard errors from the point estimate")

    print(f"\n{'fraction':>10s} {'P(level after ET)':>18s}   verdict against the CI above")
    for f, name in [(0.126, "the old constant"), (PRO_RATA, "pro-rata 30/90"),
                    (f_hat, "fitted here"), (ET_FRACTION, "knockout.ET_FRACTION")]:
        q = p_level(f, lam)
        verdict = "inside" if ci[0] <= q <= ci[1] else "OUTSIDE"
        print(f"{f:10.4f} {q:18.3f}   {verdict}   ({name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
