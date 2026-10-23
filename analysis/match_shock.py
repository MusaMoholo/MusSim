"""The match-day gap shock: does the gap between two sides on the day differ from the gap on paper?

The two sides' npxG surprises are negatively correlated within a match -- -0.061 in leagues,
-0.159 UEFA, -0.251 cups (walk-forward, against the fit's expectation). Part of that is the model's
own estimation error, which a world already carries since it starts from a draw at the fit's
posterior SD; the rest is match-level (rotation, who turned up, game state) and is not a bias:
the favourite does not systematically out-surprise the underdog, at any size of mismatch.

A world can carry the rest as a one-match shock to the strength gap, eps ~ N(0, sigma[kind]),
moving the two sides' expected npxG apart or together for that match only:

    mu_h' = mu_h * exp(+eps/2 - sigma^2/8)      mu_a' = mu_a * exp(-eps/2 - sigma^2/8)

(mean-preserving), then npxG ~ Gamma around mu'. This script, walk-forward (refit every 28 days)
from 2022-08-01 and mirroring the production draw exactly -- posterior start draw, shock, Gamma,
goal layer, Dixon-Coles:

  1. picks, per kind, sigma AND the within-match Gamma dispersion phi_w so the simulated
     surprise correlation and marginal dispersion (against the fit) both match the real ones --
     the world's posterior start draw already adds estimation error to the marginal, so phi_w is
     below the walk-forward phi;
  2. fits the Dixon-Coles rho on matches that cannot go to extra time (leagues, UEFA league
     phase) -- only there is the 90-minute result always the recorded one;
  3. scores the match predictive, old draw against new, per kind. A knockout that went to extra
     time is scored on its RECOVERED 90-minute result (a single leg was level; a second leg
     left the aggregate level, so its result is the first leg's margin), never dropped -- dropping
     them keeps only decisive knockouts and reads the real draw rate low (cups: 11.8% vs ~20.6%).

    .venv/bin/python analysis/match_shock.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from npxg_to_goals import cond_pmf, scores  # noqa: E402
from scripts.attack_defence_qt import NPXG_PHI, R_CLIP, fit, fit_goal_layer, predict_npxg  # noqa: E402
from scripts.backtest_qt import MAXG, load_master  # noqa: E402

KW = dict(xi_q=np.log(2) / 140, xi_t=np.log(2) / 1460, lam_q=5.0, lam_t=40.0)
CACHE = ROOT / "analysis/logs/match_shock_wf.pkl"
SIGMAS = [0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]
RHO = -0.05


def walk_forward() -> pd.DataFrame:
    m = load_master()
    out = []
    edges = pd.date_range("2022-08-01", m.kickoff.max().normalize() + pd.Timedelta(days=28),
                          freq="28D")
    for a, b in zip(edges[:-1], edges[1:]):
        w = m[(m.kickoff >= a) & (m.kickoff < b)]
        if w.empty:
            continue
        tr = m[m.kickoff < a]
        mdl = fit(tr, a, **KW)
        th, ta = predict_npxg(tr, mdl)
        gl = fit_goal_layer(tr, th, ta)
        mh, ma = predict_npxg(w, mdl)

        def sd(t, k):
            return mdl[k].get(t, mdl["q_sd_prior"] if k == "q_sd" else 0.0)
        out.append(pd.DataFrame({
            "kind": w.kind.values, "competition": w.competition.values, "season": w.season.values,
            "kickoff": w.kickoff.values, "home": w.home.values, "away": w.away.values,
            "round": w["round"].values,
            "minutes": pd.to_numeric(w.minutes, errors="coerce").fillna(90).values,
            "mu_h": mh, "mu_a": ma, "x_h": w.home_npxg.values.astype(float),
            "x_a": w.away_npxg.values.astype(float), "g_h": w.home_goals.values.astype(float),
            "g_a": w.away_goals.values.astype(float), "result": w.result.values,
            "qh": [sd(t, "q_sd") for t in w.home], "qa": [sd(t, "q_sd") for t in w.away],
            "th": [sd(t, "t_sd") for t in w.home], "ta": [sd(t, "t_sd") for t in w.away],
            "c0": [gl["c0"].get(c, gl["c0_mean"]) for c in w.competition],
            "c1": gl["c1"], "c2": gl["c2"], "r0": gl["r"][0], "r1": gl["r"][1]}))
    d = pd.concat(out, ignore_index=True)
    d = d[d.x_h.notna() & d.x_a.notna()].reset_index(drop=True)
    # the 90-minute result of a match that went to extra time
    d["et"] = d.minutes > 90
    d["no_et"] = (d.kind == "league") | ((d.kind == "uefa") & d["round"].notna())
    allm = m[m.played].sort_values("kickoff")
    for i in d.index[d.et]:
        r = d.loc[i]
        leg1 = allm[(allm.competition == r.competition) & (allm.season == r.season)
                    & (allm.home == r.away) & (allm.away == r.home) & (allm.kickoff < r.kickoff)
                    & (allm.kickoff > r.kickoff - pd.Timedelta(days=60))]
        if leg1.empty:
            d.loc[i, "result"] = 1                       # a single leg level at 90
        else:
            l1 = leg1.iloc[-1]
            m1 = l1.home_goals - l1.away_goals           # leg 2's home side was leg 1's away side
            d.loc[i, "result"] = 0 if m1 > 0 else (1 if m1 == 0 else 2)
    return d


def draws(g: pd.DataFrame, sigma: float, rng, K: int, phi: float = NPXG_PHI):
    """(npxG home, npxG away, state mu home, state mu away), each (n, K): a posterior start draw,
    then the match-day shock, then the Gamma -- exactly as a world draws a match."""
    n = len(g)
    dqh, dqa = rng.normal(0, g.qh.values[:, None], (n, K)), rng.normal(0, g.qa.values[:, None], (n, K))
    dth, dta = rng.normal(0, g.th.values[:, None], (n, K)), rng.normal(0, g.ta.values[:, None], (n, K))
    sh = g.mu_h.values[:, None] * np.exp((dqh + dth) / 2 - (dqa - dta) / 2)
    sa = g.mu_a.values[:, None] * np.exp((dqa + dta) / 2 - (dqh - dth) / 2)
    eps = rng.normal(0, sigma, (n, K)) if sigma else 0.0
    corr = sigma ** 2 / 8
    xh = rng.gamma(sh * np.exp(eps / 2 - corr) / phi, phi)
    xa = rng.gamma(sa * np.exp(-eps / 2 - corr) / phi, phi)
    return xh, xa, sh, sa


def surprise_stats(g, xh, xa):
    """Correlation of log surprises against the FIT's expectation, and the Pearson phi."""
    lh = np.log(np.maximum(xh, .05) / g.mu_h.values[:, None])
    la = np.log(np.maximum(xa, .05) / g.mu_a.values[:, None])
    c = np.mean([np.corrcoef(lh[:, k], la[:, k])[0, 1] for k in range(lh.shape[1])])
    mu = np.r_[g.mu_h.values, g.mu_a.values][:, None]
    phi = float(np.mean((np.r_[xh, xa] - mu) ** 2 / mu))
    return c, phi


def predictive(g, sigma, rng, K=300, phi=NPXG_PHI, rho=RHO):
    """P(score) by Monte Carlo over the full production draw."""
    P = np.zeros((len(g), MAXG + 1, MAXG + 1))
    for s in range(0, len(g), 400):
        e = slice(s, min(s + 400, len(g)))
        h = g.iloc[e]
        xh, xa, sh, sa = draws(h, sigma, rng, K, phi)
        c0, c1, c2 = h.c0.values[:, None], h.c1.values[:, None], h.c2.values[:, None]
        mh = np.maximum(c0 + c1 * xh + c2 * sh, 0.02)
        ma = np.maximum(c0 + c1 * xa + c2 * sa, 0.02)
        rh = np.clip(h.r0.values[:, None] + h.r1.values[:, None] * xh, *R_CLIP)
        ra = np.clip(h.r0.values[:, None] + h.r1.values[:, None] * xa, *R_CLIP)
        ph, pa = cond_pmf(mh, rh, "binomial"), cond_pmf(ma, ra, "binomial")
        Q = np.einsum("nki,nkj->nij", ph, pa) / K
        Q[:, 0, 0] += np.mean(ph[:, :, 0] * pa[:, :, 0] * (-mh * ma * rho), 1)
        Q[:, 0, 1] += np.mean(ph[:, :, 0] * pa[:, :, 1] * (mh * rho), 1)
        Q[:, 1, 0] += np.mean(ph[:, :, 1] * pa[:, :, 0] * (ma * rho), 1)
        Q[:, 1, 1] += np.mean(ph[:, :, 1] * pa[:, :, 1] * (-rho), 1)
        P[e] = Q
    return P


PHIS = [0.28, 0.30, 0.32, 0.34, 0.356, 0.38, 0.42, 0.46, 0.50]
RHOS = [-0.05, -0.08, -0.10, -0.12, -0.15]


def outcome_ll(P, res):
    iu = np.triu_indices(MAXG + 1, 1)
    P = P / P.sum((1, 2), keepdims=True)
    pw = np.stack([P[:, iu[1], iu[0]].sum(1), np.einsum("ijj->i", P), P[:, iu[0], iu[1]].sum(1)], 1)
    return -np.log(np.clip(pw[np.arange(len(P)), res], 1e-12, 1)), pw[:, 1]


def main() -> int:
    if CACHE.exists():
        d = pd.read_pickle(CACHE)
    else:
        d = walk_forward()
        d.to_pickle(CACHE)
    rng = np.random.default_rng(0)
    print(f"{len(d)} walk-forward matches with npxG, {int(d.et.sum())} of them to extra time "
          f"(scored on their recovered 90-minute result; npxG statistics use 90-minute matches)\n")
    print("1. per kind, (sigma, phi_w) matching the real surprise correlation and dispersion")
    pick = {}
    for kind, g in d[~d.et].groupby("kind"):
        lh = np.log(np.maximum(g.x_h, .05) / g.mu_h); la = np.log(np.maximum(g.x_a, .05) / g.mu_a)
        real_c = np.corrcoef(lh, la)[0, 1]
        mu = np.r_[g.mu_h, g.mu_a]
        real_phi = float(np.mean((np.r_[g.x_h, g.x_a] - mu) ** 2 / mu))
        se_c, se_p = 1 / np.sqrt(len(g)), real_phi * np.sqrt(2 / (2 * len(g)))
        best = None
        for phi in PHIS:
            for sg in SIGMAS:
                c, ph = surprise_stats(g, *draws(g, sg, rng, 60, phi)[:2])
                dist = ((c - real_c) / se_c) ** 2 + ((ph - real_phi) / se_p) ** 2
                if best is None or dist < best[0]:
                    best = (dist, sg, phi, c, ph)
        pick[kind] = best[1:3]
        print(f"   {kind:7s} n={len(g):5d} real corr {real_c:+.3f} phi {real_phi:.3f}  ->  sigma "
              f"{best[1]:.2f}, phi_w {best[2]:.3f} (sim corr {best[3]:+.3f}, phi {best[4]:.3f})")

    print("\n2. Dixon-Coles rho on matches that cannot go to extra time")
    ne = d[d.no_et].reset_index(drop=True)
    sg_of = {k: v[0] for k, v in pick.items()}; ph_of = {k: v[1] for k, v in pick.items()}
    best_rho = None
    for rho in RHOS:
        P = np.zeros((len(ne), MAXG + 1, MAXG + 1))
        for kind, g in ne.groupby("kind"):
            P[g.index] = predictive(g, sg_of[kind], rng, K=200, phi=ph_of[kind], rho=rho)
        ll, dr = outcome_ll(P, ne.result.to_numpy())
        print(f"   rho {rho:+.2f}: 1X2 {ll.mean():.5f}  draw {dr.mean():.4f}  (real {(ne.result == 1).mean():.4f})")
        if best_rho is None or ll.mean() < best_rho[1]:
            best_rho = (rho, ll.mean())
    rho = best_rho[0]

    print(f"\n3. match predictive per kind: OLD draw (phi 0.356, no shock, rho -0.05) vs NEW "
          f"(sigma/phi_w per kind, rho {rho:+.2f}); one-stage DC -0.10 for reference")
    from scripts.backtest_qt import score_matrix
    old = predictive(d, 0.0, rng, rho=-0.05)
    new = np.zeros_like(old)
    for kind, g in d.groupby("kind"):
        new[g.index] = predictive(g, sg_of[kind], rng, phi=ph_of[kind], rho=rho)
    res = d.result.to_numpy().astype(int)
    lo, do = outcome_ll(old, res)
    ln, dn = outcome_ll(new, res)
    print(f"   {'kind':7s} {'n':>5s} {'1X2 old':>8s} {'new-old':>8s} {'t':>6s} {'draw real':>9s} {'old':>6s} {'new':>6s}")
    for kind, g in [("all", d), ("no-ET", d[d.no_et])] + list(d.groupby("kind")):
        i = g.index.to_numpy()
        dd = ln[i] - lo[i]
        print(f"   {kind:7s} {len(i):5d} {lo[i].mean():8.5f} {dd.mean():+8.5f} "
              f"{dd.mean() / (dd.std(ddof=1) / np.sqrt(len(i))):+6.2f} {(res[i] == 1).mean():9.4f} "
              f"{do[i].mean():6.4f} {dn[i].mean():6.4f}")
    print(f"\n   chosen: sigma {sg_of}, phi_w {ph_of}, rho {rho}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
