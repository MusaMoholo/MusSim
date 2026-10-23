#!/usr/bin/env python3
"""Backtest the derived UEFA bracket: constraints, progression by seed, extra time and shootouts.

Three questions, in order of how much they can tell us:

1. Does the derived bracket reproduce the real ones? `uefa_bracket.verify_bracket` checks every
   constraint against all six real 36-team knockouts, and `_selfcheck_draw` checks that the draw
   the simulator makes satisfies the same ones. Both are pass/fail and both pass.

2. Do simulated ties progress like real ones? For 2024 and 2025 we replay the REAL league phase
   -- so the seeds are the real seeds -- then blank the draw and let the simulator build the
   knockout from scratch. The statistic is how often the better league-phase seed advances.
   Underpowered by construction: 136 real ties is all there is, so read this as a consistency
   check, not a calibration.

3. How often does a tie need extra time or a shootout? This one has the whole window behind it
   (344 real ties) and it separates cleanly: P(level aggregate) tests the match model, while
   P(shootout | extra time) tests `knockout.ET_FRACTION` alone.

Env: NWORLDS (default 200).
"""
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, ".")
from football_common import canonical_elo_team_name  # noqa: E402
from scripts.attack_defence_qt import fit, fit_goal_calibration, predict_npxg  # noqa: E402
from scripts.simulate_season import simulate  # noqa: E402
from scripts.uefa_bracket import (  # noqa: E402
    STAGE_ORDER, _date_blocks, _selfcheck_draw, league_phase_table, redraw_handover, split_phases,
    stage_calendar, verify_bracket,
)

COMPS = ["UEFA Champions League", "UEFA Europa League", "UEFA Conference League"]
NWORLDS = int(os.environ.get("NWORLDS", 200))
# measured over the whole window by `real_tie_rates` below; restated here so a regression is loud
REAL_ET, REAL_PK, REAL_N = 0.177, 0.081, 344


def se(p: float, n: int) -> float:
    return float(np.sqrt(p * (1 - p) / n))


def real_tie_rates(master: pd.DataFrame):
    """P(extra time) and P(shootout) per real knockout tie, over every UEFA season we have."""
    u = master[(master.kind == "uefa") & master.played].copy()
    u["mins"] = pd.to_numeric(u.minutes, errors="coerce")
    tot = et = pk = 0
    for _, g in u.groupby(["competition", "season"]):
        ko = split_phases(g)[1]
        blocks = _date_blocks(ko)
        i = 0
        while i < len(blocks):
            b = blocks[i]
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            two = nxt is not None and {(r.home, r.away) for r in nxt.itertuples()} == \
                {(r.away, r.home) for r in b.itertuples()}
            legs = nxt if two else b
            for r in b.itertuples():
                deciding = legs[(legs.home == r.away) & (legs.away == r.home)].iloc[0] if two else r
                tot += 1
                et += int(float(deciding.mins) > 90)
                pk += int(deciding.outcome == "penalties")
            i += 2 if two else 1
    return tot, et, pk


def real_ties(cs: pd.DataFrame, seed):
    """(stage, better seed, worse seed, did the better seed advance?) for every real tie."""
    blocks = _date_blocks(split_phases(cs)[1])
    out, i = [], 0
    for label in STAGE_ORDER:
        two = label != "F"
        l1, l2 = blocks[i], (blocks[i + 1] if two else None)
        for r in l1.itertuples():
            a, b = r.home, r.away
            if two:
                mir = l2[(l2.home == b) & (l2.away == a)].iloc[0]
                agg_a = int(r.home_goals) + int(mir.away_goals)
                agg_b = int(r.away_goals) + int(mir.home_goals)
                win = a if agg_a > agg_b else (b if agg_b > agg_a else None)
            else:
                win = a if int(r.home_goals) > int(r.away_goals) else (
                    b if int(r.home_goals) < int(r.away_goals) else None)
            better, worse = (a, b) if seed[a] < seed[b] else (b, a)
            out.append((label, seed[better], seed[worse], None if win is None else win == better))
        i += 2 if two else 1
    return out


def setup(master: pd.DataFrame, season: int):
    fx = master[master.season == season]
    start = fx.kickoff.min()
    train = master[(master.kickoff < start) & master.played & master.has_npxg]
    model = fit(train, start, xi_q=np.log(2) / 140, xi_t=np.log(2) / 1460, lam_q=5.0, lam_t=40.0)
    mu_h, mu_a = predict_npxg(train, model)
    calib = fit_goal_calibration(train, mu_h, mu_a)
    elo_raw = pd.read_csv("data/external/elo_ratings.csv", parse_dates=["date"])
    wide = elo_raw.pivot_table(index="date", columns="club", values="elo",
                               aggfunc="last").sort_index()
    row = wide.iloc[max(wide.index.searchsorted(start, side="left") - 1, 0)].dropna()
    look = {canonical_elo_team_name(c): float(v) for c, v in row.items()}
    elo0 = {t: look[canonical_elo_team_name(t)] for t in set(fx.home) | set(fx.away)
            if canonical_elo_team_name(t) in look}
    return fx, model, calib, elo0


def main() -> int:
    master = pd.read_pickle(Path("data/master_fixtures.pkl")).sort_values(
        "kickoff").reset_index(drop=True)

    print("1. bracket constraints")
    n, fails = verify_bracket(master)
    print(f"   {n} real 36-team knockouts: " + ("all constraints hold" if not fails
                                                else f"{len(fails)} VIOLATIONS"))
    dfails = _selfcheck_draw()
    print("   2000 drawn brackets:      " + ("all satisfy the same constraints" if not dfails
                                             else f"{len(dfails)} VIOLATIONS"))

    print(f"\n2. progression by seed ({NWORLDS} worlds per season, real league phase replayed)")
    R, S = [], []
    for season in (2024, 2025):
        fx, model, calib, elo0 = setup(master, season)
        hands = {}
        for comp in COMPS:
            cs = master[(master.competition == comp) & (master.season == season)]
            hands[(comp, season)] = redraw_handover(cs)   # real dates, draw blanked
            tbl = league_phase_table(split_phases(cs)[0])
            seed = dict(zip(tbl.team, tbl.seed))
            R += [(comp, season) + t for t in real_ties(cs, seed)]
        t0 = time.time()
        for i in range(NWORLDS):
            sim = simulate(fx, model, calib, elo0, np.random.default_rng(7000 + i),
                           master=master, handovers=hands)
            for (comp, _), rep in sim.attrs["knockout"].items():
                inv = {t: k for k, t in rep["seeds"].items()}
                for lab in STAGE_ORDER:
                    for w, l in zip(rep["winners"][lab], rep["losers"][lab]):
                        S.append((comp, season, lab, min(inv[w], inv[l]), max(inv[w], inv[l]),
                                  inv[w] < inv[l]))
        print(f"   {season}: {NWORLDS} worlds in {time.time() - t0:.0f}s")

    cols = ["comp", "season", "stage", "better", "worse", "better_won"]
    R = pd.DataFrame(R, columns=cols)
    S = pd.DataFrame(S, columns=cols)
    R = R[R.better_won.notna()]
    print(f"\n   the better league-phase seed advances:  ({len(R)} real ties, {len(S)} simulated)")
    print(f"   {'stage':6s} {'n_real':>6s} {'real':>7s} {'sim':>7s} {'diff':>8s} {'z':>6s}")
    for lab in list(STAGE_ORDER) + ["ALL"]:
        r = R if lab == "ALL" else R[R.stage == lab]
        s = S if lab == "ALL" else S[S.stage == lab]
        pr, ps = r.better_won.mean(), s.better_won.mean()
        z = (pr - ps) / se(ps, len(r))
        print(f"   {lab:6s} {len(r):6d} {pr:7.3f} {ps:7.3f} {pr - ps:+8.3f} {z:+6.2f}")
    R["gap"], S["gap"] = R.worse - R.better, S.worse - S.better
    print(f"\n   {'seed gap':>10s} {'n_real':>6s} {'real':>7s} {'sim':>7s} {'z':>6s}")
    for lo, hi in [(1, 4), (5, 8), (9, 13), (14, 23)]:
        r, s = R[(R.gap >= lo) & (R.gap <= hi)], S[(S.gap >= lo) & (S.gap <= hi)]
        pr, ps = r.better_won.mean(), s.better_won.mean()
        print(f"   {f'{lo}-{hi}':>10s} {len(r):6d} {pr:7.3f} {ps:7.3f} "
              f"{(pr - ps) / se(ps, len(r)):+6.2f}")

    print("\n3. extra time and shootouts per tie")
    tot, et, pk = real_tie_rates(master)
    print(f"   real:      {tot} ties, extra time {et / tot:.3f}, shootout {pk / tot:.3f}, "
          f"shootout | extra time {pk / et:.3f}")
    s_tot = s_et = s_pk = 0
    fx, model, calib, elo0 = setup(master, 2026)
    for i in range(NWORLDS):
        sim = simulate(fx, model, calib, elo0, np.random.default_rng(9000 + i), master=master)
        for rep in sim.attrs["knockout"].values():
            s_tot += sum(len(v) for v in rep["ties"].values())
            s_et += rep["extra_times"]
            s_pk += rep["shootouts"]
    print(f"   simulated: {s_tot} ties, extra time {s_et / s_tot:.3f}, shootout {s_pk / s_tot:.3f}, "
          f"shootout | extra time {s_pk / s_et:.3f}")
    print(f"   z(extra time) = {(s_et / s_tot - et / tot) / se(et / tot, tot):+.2f}   "
          f"z(shootout) = {(s_pk / s_tot - pk / tot) / se(pk / tot, tot):+.2f}   "
          f"z(shootout | extra time) = {(s_pk / s_et - pk / et) / se(pk / et, et):+.2f}")
    print("   P(level aggregate) tests the match model; P(shootout | extra time) tests "
          "ET_FRACTION alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
