"""Calibrate the simulator's feedback against real seasons, on two statistics.

  SPREAD       simulated SD of final league points / real SD, per league-season, averaged.
               Fixed strengths give ~0.87: sampling noise alone is too narrow.
  PERSISTENCE  correlation, across team-seasons, between a side's first-half and second-half
               points RESIDUALS -- points minus what the pre-season state expected from those
               fixtures. Strength that moves and stays moved (a random walk) carries a good half
               into the second half; strength that drifts back (a decaying shift) does not. Spread
               cannot tell the two apart, since either can be tuned to the right width.

Each of the 15 league-seasons (big five, 2023-25) is re-sampled from a fit at its first fixture
(`replay_played=False`: these seasons are finished, and replaying reality would score 1.00 for
free), with the two-stage match and the zero-mean feedback of `scripts/simulate_season.py`. The
grid is the Q gain (per unit of npxG surprise; the estimator's own response is 0.026) against the
half-life of in-world shifts (None = they never fade).

    .venv/bin/python analysis/calibrate_drift3.py           # NSIM env-configurable
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from football_common import canonical_elo_team_name  # noqa: E402
from scripts.attack_defence_qt import (  # noqa: E402
    fit, fit_goal_calibration, fit_goal_layer, predict_npxg,
)
from scripts.backtest_qt import load_master, score_matrix  # noqa: E402
from scripts.simulate_season import GOAL_RHO, _World, points_table, simulate  # noqa: E402

NSIM = int(os.environ.get("NSIM", 100))
GAINS = [float(g) for g in os.environ.get("GAINS", "0.026,0.04,0.05,0.06,0.07").split(",")]
HALF_LIVES = [None if h == "none" else float(h)
              for h in os.environ.get("HALF_LIVES", "140,280,none").split(",")]
START_NOISES = [float(x) for x in os.environ.get("START_NOISES", "0").split(",")]

m = load_master(Path("data/master_fixtures.pkl"))
m = m[m.kind.isin(["league", "uefa"])]
elo_raw = pd.read_csv("data/external/elo_ratings.csv", parse_dates=["date"])
wide = elo_raw.pivot_table(index="date", columns="club", values="elo", aggfunc="last").sort_index()


def elo_at(when):
    row = wide.iloc[max(wide.index.searchsorted(when, side="left") - 1, 0)].dropna()
    return {canonical_elo_team_name(c): float(v) for c, v in row.items()}


def halves(sim: pd.DataFrame, exp_pts: dict) -> pd.DataFrame:
    """Per team: (first-half residual, second-half residual), split at its 19th match."""
    rows = []
    for side in ("home", "away"):
        gf = sim.home_goals if side == "home" else sim.away_goals
        ga = sim.away_goals if side == "home" else sim.home_goals
        pts = np.where(gf > ga, 3, np.where(gf == ga, 1, 0))
        ex = np.array([exp_pts[(h, a)][0 if side == "home" else 1]
                       for h, a in zip(sim.home, sim.away)])
        rows.append(pd.DataFrame({"team": sim[side].to_numpy(), "kickoff": sim.kickoff.to_numpy(),
                                  "res": pts - ex}))
    r = pd.concat(rows).sort_values(["team", "kickoff"])
    r["half"] = r.groupby("team").cumcount() >= r.groupby("team").team.transform("size") // 2
    return r.groupby(["team", "half"]).res.sum().unstack()


def seasons():
    out = []
    for (comp, season), g in m[m.kind == "league"].groupby(["competition", "season"]):
        if g.played.sum() <= 300 or season not in (2023, 2024, 2025):
            continue
        sf = g[g.played].sort_values("kickoff")
        start = sf.kickoff.min()
        train = m[(m.kickoff < start) & m.played & m.has_npxg]
        mdl = fit(train, start, xi_q=np.log(2) / 140, xi_t=np.log(2) / 1460, lam_q=5.0, lam_t=40.0)
        th, ta = predict_npxg(train, mdl)
        cal, gl = fit_goal_calibration(train, th, ta), fit_goal_layer(train, th, ta)
        look = elo_at(start)
        e0 = {t: look[canonical_elo_team_name(t)] for t in set(sf.home) | set(sf.away)
              if canonical_elo_team_name(t) in look}
        # the pre-season state's expected points for every fixture: what a residual is against
        w0 = _World(mdl, cal, e0, None, drift_per_day=0.0, feedback=False, npxg_feedback=False,
                    npxg_gain=0.0, rho=-0.10, goals=gl)
        exp_pts = {}
        for r in sf.itertuples():
            w0._touch(r.home)
            w0._touch(r.away)
            _, _, lh, la = w0.rates(comp, r.home, r.away)
            M = score_matrix(np.array([lh]), np.array([la]), GOAL_RHO)[0]
            pw, pd_, pl = np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()
            exp_pts[(r.home, r.away)] = (3 * pw + pd_, 3 * pl + pd_)
        real_sd = np.std(list(points_table(sf).values()), ddof=1)
        out.append((comp, season, sf, mdl, cal, gl, e0, exp_pts, real_sd, halves(sf, exp_pts)))
    return out


def run(data, gain, half_life, feedback=True, npxg_fb=True, start_noise=0.0):
    ratios, sim_h = [], []
    for comp, season, sf, mdl, cal, gl, e0, exp_pts, real_sd, _ in data:
        rng = np.random.default_rng(abs(hash((comp, season))) % 2 ** 31)
        sds = []
        for _ in range(NSIM):
            sim = simulate(sf, mdl, cal, e0, rng, replay_played=False, feedback=feedback,
                           npxg_feedback=npxg_fb, npxg_gain=gain, goals=gl, q_half_life=half_life,
                           start_noise=start_noise)
            sds.append(np.std(list(points_table(sim).values()), ddof=1))
            sim_h.append(halves(sim, exp_pts))
        ratios.append(np.mean(sds) / real_sd)
    h = pd.concat(sim_h)
    return float(np.mean(ratios)), float(np.corrcoef(h[False], h[True])[0, 1])


def main() -> int:
    data = seasons()
    real = pd.concat([d[-1] for d in data])
    rc = float(np.corrcoef(real[False], real[True])[0, 1])
    se = (1 - rc ** 2) / np.sqrt(len(real) - 1)
    print(f"{len(data)} league-seasons, {len(real)} team-seasons, NSIM={NSIM}")
    print(f"REAL persistence: corr(first-half residual, second-half residual) = {rc:+.3f} "
          f"(se ~{se:.3f})\n")
    r, c = run(data, 0.0, 140.0, feedback=False, npxg_fb=False)
    print(f"{'fixed strengths':>24s}  spread {r:.3f}  persistence {c:+.3f}", flush=True)
    for sn in START_NOISES:
        for hl in HALF_LIVES:
            for g in GAINS:
                r, c = run(data, g, hl, start_noise=sn)
                flag = "  <-- spread on target" if abs(r - 1.0) < 0.025 else ""
                print(f"  start {sn:.1f} gain {g:.3f} half-life {str(hl):>5s}  spread {r:.3f}  "
                      f"persistence {c:+.3f}{flag}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
