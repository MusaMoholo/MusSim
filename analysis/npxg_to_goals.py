"""How goals follow npxG, measured -- the evidence behind the simulator drawing npxG first and the
goals from it, rather than both independently from the pre-match expectation.

Walk-forward (refit every 14 days, all competitions in training, strictly causal) from 2022-08-01,
recording for every match: the model's expected npxG (mu), the realised npxG (x) and the goals.
Then, on 90-minute matches only (extra time accrues npxG over 120 minutes):

  1. npxG | mu   -- is a Gamma with Var = phi*mu the right shape (PIT deciles), and are the two
                    sides' surprises correlated?
  2. goals | x   -- the mean (power law vs linear-plus-penalties), the dispersion, and whether
                    the two sides' goal residuals are correlated once npxG is known.
  3. the two-stage predictive -- x ~ Gamma, goals | x from a conditional layer -- against the
                    one-stage model on outcome, total-goal and exact-score log-loss, the draw rate
                    and the goal dispersion.

    .venv/bin/python analysis/npxg_to_goals.py

CAVEAT: every comparison here is on 90-minute matches, which drops each knockout that went to extra
time -- i.e. was level at 90 -- so its real draw rate for cups and UEFA reads low and the pooled
one is not a calibration target. `analysis/match_shock.py` scores those on their recovered
90-minute result, and is where the per-kind Dixon-Coles rho and the match-day shock come from.
"""
import sys
from math import lgamma
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.attack_defence_qt import (  # noqa: E402
    _irls, apply_goal_calibration, fit, fit_goal_calibration, fit_goal_layer, predict_npxg,
)
from scripts.backtest_qt import MAXG, load_master, score_matrix  # noqa: E402

CACHE = ROOT / "analysis/logs/npxg_to_goals_wf.pkl"
TEST_FROM = pd.Timestamp("2022-08-01")
KW = dict(xi_q=np.log(2) / 140, xi_t=np.log(2) / 1460, lam_q=5.0, lam_t=40.0)
PHI = 0.356
_LGN = np.vectorize(lgamma)


def walk_forward(m: pd.DataFrame) -> pd.DataFrame:
    target = m[m.kickoff >= TEST_FROM]
    edges = pd.date_range(target.kickoff.min().normalize(),
                          target.kickoff.max().normalize() + pd.Timedelta(days=14), freq="14D")
    out = []
    for start, end in zip(edges[:-1], edges[1:]):
        w = m[(m.kickoff >= start) & (m.kickoff < end)]
        if w.empty:
            continue
        tr = m[m.kickoff < start]
        mdl = fit(tr, start, **KW)
        th, ta = predict_npxg(tr, mdl)
        cal = fit_goal_calibration(tr, th, ta)
        mh, ma = predict_npxg(w, mdl)
        lh, la = apply_goal_calibration(w, mh, ma, cal)
        out.append(pd.DataFrame({
            "season": w.season.to_numpy(), "competition": w.competition.to_numpy(),
            "kind": w.kind.to_numpy(), "kickoff": w.kickoff.to_numpy(),
            "minutes": pd.to_numeric(w.minutes, errors="coerce").fillna(90.0).to_numpy(),
            "mu_h": mh, "mu_a": ma, "lam_h": lh, "lam_a": la,
            "x_h": w.home_npxg.to_numpy(float), "x_a": w.away_npxg.to_numpy(float),
            "g_h": w.home_goals.to_numpy(float), "g_a": w.away_goals.to_numpy(float),
            "result": w.result.to_numpy()}))
    return pd.concat(out, ignore_index=True)


def gamma_cdf_mc(x, shape, scale, rng, n=4000):
    """P(X <= x) for X ~ Gamma(shape, scale), per row, by Monte Carlo (no scipy here)."""
    out = np.empty(len(x))
    for i in range(0, len(x), 500):
        s = rng.gamma(shape[i:i + 500, None], scale, (min(500, len(x) - i), n))
        out[i:i + 500] = (s <= x[i:i + 500, None]).mean(1)
    return out


def poisson_ll(y, lam):
    return y * np.log(lam) - lam - _LGN(y + 1)


# --------------------------------------------------------------------------- conditional layer
def fit_linear(d: pd.DataFrame, use_mu: bool = False):
    """goals = c0 + c1*npxG (+ c2*mu) per competition, least squares on both sides' rows."""
    x = np.r_[d.x_h, d.x_a]; g = np.r_[d.g_h, d.g_a]; comp = np.r_[d.competition, d.competition]
    mu = np.r_[d.mu_h, d.mu_a] if use_mu else np.zeros(len(x))

    def ls(i):
        A = np.column_stack([np.ones(i.sum()), x[i], mu[i]])
        return tuple(np.linalg.lstsq(A, g[i], rcond=None)[0])
    out = {"_": ls(np.ones(len(x), bool))}
    for c in np.unique(comp):
        i = comp == c
        if i.sum() >= 200:
            out[c] = ls(i)
    return out


def cond_mean(comp, x, lin, mu):
    c = np.array([lin.get(k, lin["_"]) for k in comp])
    return np.maximum(c[:, 0] + c[:, 1] * x + c[:, 2] * mu, 0.02)


def fit_dispersion(d: pd.DataFrame, lin):
    """Var(goals | x, mu) / E(goals | x, mu) as a line in x, from binned moments."""
    x = np.r_[d.x_h, d.x_a]; g = np.r_[d.g_h, d.g_a]
    m = cond_mean(np.r_[d.competition, d.competition], x, lin, np.r_[d.mu_h, d.mu_a])
    b = np.digitize(x, np.quantile(x, np.linspace(0, 1, 13)[1:-1]))
    xs, rs = [], []
    for k in np.unique(b):
        i = b == k
        xs.append(x[i].mean()); rs.append(np.mean((g[i] - m[i]) ** 2) / m[i].mean())
    return tuple(np.polyfit(xs, rs, 1)[::-1])


def cond_pmf(m, r, cond):
    """pmf over 0..MAXG of goals given npxG: Poisson(m), or a binomial with Var ~= r*m."""
    k = np.arange(MAXG + 1, dtype=float)
    if cond == "poisson":
        return np.exp(-m[..., None] + k * np.log(m[..., None]) - _LGN(k + 1))
    n = np.maximum(np.rint(m / np.clip(1 - r, 0.0, 0.45)), np.ceil(m) + 1)
    p = m / n
    with np.errstate(invalid="ignore", divide="ignore"):
        logc = _LGN(n[..., None] + 1) - _LGN(k + 1) - _LGN(np.maximum(n[..., None] - k + 1, 1e-9))
        lp = logc + k * np.log(p[..., None]) + (n[..., None] - k) * np.log1p(-p[..., None])
    pm = np.where(k <= n[..., None], np.exp(lp), 0.0)
    return pm / pm.sum(-1, keepdims=True)


def two_stage(d, lin, rr, phi, cond, rho, rng, K=300):
    """P(score) = E_x[ P(score | x) ], x ~ Gamma(mu/phi, phi) per side, by Monte Carlo."""
    out = np.zeros((len(d), MAXG + 1, MAXG + 1))
    comp = d.competition.to_numpy()
    for s in range(0, len(d), 400):
        e = slice(s, min(s + 400, len(d)))
        n = e.stop - e.start
        xh = rng.gamma(d.mu_h.to_numpy()[e, None] / phi, phi, (n, K))
        xa = rng.gamma(d.mu_a.to_numpy()[e, None] / phi, phi, (n, K))
        c = np.repeat(comp[e], K)
        mh = cond_mean(c, xh.ravel(), lin, np.repeat(d.mu_h.to_numpy()[e], K)).reshape(n, K)
        ma = cond_mean(c, xa.ravel(), lin, np.repeat(d.mu_a.to_numpy()[e], K)).reshape(n, K)
        rh = np.clip(rr[0] + rr[1] * xh, 0.55, 1.0); ra = np.clip(rr[0] + rr[1] * xa, 0.55, 1.0)
        ph = cond_pmf(mh, rh, cond); pa = cond_pmf(ma, ra, cond)
        P = np.einsum("nki,nkj->nij", ph, pa) / K
        if rho:
            P[:, 0, 0] += np.mean(ph[:, :, 0] * pa[:, :, 0] * (-mh * ma * rho), 1)
            P[:, 0, 1] += np.mean(ph[:, :, 0] * pa[:, :, 1] * (mh * rho), 1)
            P[:, 1, 0] += np.mean(ph[:, :, 1] * pa[:, :, 0] * (ma * rho), 1)
            P[:, 1, 1] += np.mean(ph[:, :, 1] * pa[:, :, 1] * (-rho), 1)
        out[e] = P
    return out


def scores(d, P, label):
    """Per-match log-losses (outcome, total goals, exact score) and the home-goal moments."""
    P = P / P.sum((1, 2), keepdims=True)
    gh = np.minimum(d.g_h.to_numpy(int), MAXG); ga = np.minimum(d.g_a.to_numpy(int), MAXG)
    iu = np.triu_indices(MAXG + 1, 1)
    pw = np.stack([P[:, iu[1], iu[0]].sum(1), np.einsum("ijj->i", P), P[:, iu[0], iu[1]].sum(1)], 1)
    tot = np.zeros((len(P), 2 * MAXG + 1))
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            tot[:, i + j] += P[:, i, j]
    g = np.arange(MAXG + 1)
    mh = (P.sum(2) * g).sum(1)
    return {"label": label,
            "res": -np.log(np.clip(pw[np.arange(len(P)), d.result.to_numpy()], 1e-12, 1)),
            "tot": -np.log(np.clip(tot[np.arange(len(P)), gh + ga], 1e-12, 1)),
            "sc": -np.log(np.clip(P[np.arange(len(P)), gh, ga], 1e-12, 1)),
            "draw": pw[:, 1], "mean_h": mh, "var_h": (P.sum(2) * g ** 2).sum(1) - mh ** 2}


# --------------------------------------------------------------------------- report
def main() -> int:
    if CACHE.exists():
        wf = pd.read_pickle(CACHE)
    else:
        wf = walk_forward(load_master())
        CACHE.parent.mkdir(exist_ok=True)
        wf.to_pickle(CACHE)
    d = wf[(wf.minutes <= 90) & wf.x_h.notna() & wf.x_a.notna()].reset_index(drop=True)
    print(f"{len(wf)} walk-forward matches, {len(d)} at 90 minutes with npxG\n")
    rng = np.random.default_rng(0)

    # ---- 1. npxG | mu
    print("1. npxG | mu")
    x = np.r_[d.x_h, d.x_a]; mu = np.r_[d.mu_h, d.mu_a]
    print(f"   Pearson phi {np.mean((x - mu) ** 2 / mu):.3f} (repo constant {PHI}); "
          f"mean x/mu {x.mean() / mu.mean():.3f}")
    pit = gamma_cdf_mc(x, mu / PHI, PHI, rng)
    dec = np.histogram(pit, bins=np.linspace(0, 1, 11))[0] / len(pit)
    print("   PIT deciles under Gamma(phi):", " ".join(f"{v:.3f}" for v in dec),
          "(0.100 each = right shape)")
    rh = np.log(np.maximum(d.x_h, 0.05) / d.mu_h); ra = np.log(np.maximum(d.x_a, 0.05) / d.mu_a)
    print(f"   corr(log surprise home, away) = {np.corrcoef(rh, ra)[0, 1]:+.3f}")
    for k, g in d.groupby("kind"):
        a = np.log(np.maximum(g.x_h, .05) / g.mu_h); b = np.log(np.maximum(g.x_a, .05) / g.mu_a)
        print(f"      {k:7s} n={len(g):5d}  corr {np.corrcoef(a, b)[0, 1]:+.3f}")

    # ---- 2. goals | x
    print("\n2. goals | realised npxG (team-match rows)")
    g = np.r_[d.g_h, d.g_a]
    tab = pd.DataFrame({"x": x, "g": g, "b": pd.cut(x, [0, .3, .6, .9, 1.2, 1.5, 1.9, 2.4, 3.0, 9])}
                       ).groupby("b", observed=True).agg(n=("g", "size"), x=("x", "mean"),
                                                         g=("g", "mean"), v=("g", "var"))
    tab["g-x"] = tab.g - tab.x
    tab["var/mean"] = tab.v / tab.g
    print(tab.round(3).to_string())
    comp = np.r_[d.competition, d.competition]; season = np.r_[d.season, d.season]
    trn, tst = season < 2025, season >= 2025
    res = {}
    for name in ("power", "linear"):
        pred = np.full(len(g), np.nan)
        for c in np.unique(comp):
            i, j = trn & (comp == c), tst & (comp == c)
            if i.sum() < 100 or j.sum() == 0:
                i = trn
            if name == "power":
                X = np.column_stack([np.ones(i.sum()), np.log(np.maximum(x[i], .05))])
                b = _irls(X, g[i], None, np.ones(i.sum()), np.full(2, 1e-8))
                pred[j] = np.exp(b[0] + b[1] * np.log(np.maximum(x[j], .05)))
            else:
                b = np.linalg.lstsq(np.column_stack([np.ones(i.sum()), x[i]]), g[i], rcond=None)[0]
                pred[j] = np.maximum(b[0] + b[1] * x[j], 1e-3)
        res[name] = float(np.mean(poisson_ll(g[tst], pred[tst])))
    print(f"   held-out (2025-26) Poisson log-lik per team-match: power {res['power']:.5f}  "
          f"linear {res['linear']:.5f}  (higher is better)")
    for cols, name in (((x,), "x"), ((x, mu), "x + mu")):
        A = np.column_stack([np.ones(len(g)), *cols])
        b = np.linalg.lstsq(A, g, rcond=None)[0]
        print(f"   pooled linear on {name:6s}: coef {np.round(b, 3)}, residual var {np.var(g - A @ b):.4f}")
    lin = fit_linear(d, True)
    m_h = cond_mean(d.competition.to_numpy(), d.x_h.to_numpy(), lin, d.mu_h.to_numpy())
    m_a = cond_mean(d.competition.to_numpy(), d.x_a.to_numpy(), lin, d.mu_a.to_numpy())
    print(f"   corr(goal residual home, away | npxG, mu) = "
          f"{np.corrcoef(d.g_h - m_h, d.g_a - m_a)[0, 1]:+.3f}")

    # ---- 3. the two-stage predictive against the one-stage model
    print("\n3. predictive comparison; conditional layer fitted on seasons < 2025")
    test = (d.season >= 2025).to_numpy()
    out = [scores(d, score_matrix(d.lam_h.to_numpy(), d.lam_a.to_numpy(), -0.10),
                  "one-stage, DC -0.10 (current)")]
    for use_mu in (False, True):
        lin = fit_linear(d[d.season < 2025], use_mu)
        rr = fit_dispersion(d[d.season < 2025], lin)
        tag = "x+mu" if use_mu else "x"
        print(f"   mean on {tag:4s}: pooled {np.round(lin['_'], 3)}; r(x) = {rr[0]:.3f} {rr[1]:+.3f}*x")
        for phi in (PHI, 0.383):
            for rho in (0.0, -0.05):
                P = two_stage(d, lin, rr, phi, "binomial", rho, rng)
                out.append(scores(d, P, f"binom {tag:4s} phi {phi:.3f} DC {rho:+.2f}"))
    # the production layer: per-competition intercept, pooled slopes (scripts/attack_defence_qt)
    tr = d[d.season < 2025]
    layer = fit_goal_layer(pd.DataFrame({
        "competition": tr.competition, "home_npxg": tr.x_h, "away_npxg": tr.x_a,
        "home_goals": tr.g_h, "away_goals": tr.g_a, "minutes": tr.minutes}), tr.mu_h, tr.mu_a)
    lin = {c: (v, layer["c1"], layer["c2"]) for c, v in layer["c0"].items()}
    lin["_"] = (layer["c0_mean"], layer["c1"], layer["c2"])
    print(f"   production layer: c1 {layer['c1']:.3f} c2 {layer['c2']:.3f} r {np.round(layer['r'], 3)}")
    P = two_stage(d, lin, layer["r"], PHI, "binomial", -0.05, rng)
    out.append(scores(d, P, "PRODUCTION layer phi 0.356 DC -0.05"))
    base = out[0]
    for name, mask in (("2025-26 only", test),
                       ("all 2022-26 (conditional layer in-sample before 2025)", np.ones(len(d), bool))):
        print(f"\n   {name}: real draw rate {float((d.result[mask] == 1).mean()):.4f}, n={mask.sum()}")
        print(f"   {'model':34s} {'1X2':>8s} {'d1X2':>8s} {'t':>6s} {'d total':>8s} {'t':>6s} "
              f"{'d score':>8s} {'draw':>7s} {'var/mean':>8s}")
        for o in out:
            def delta(k):
                dd = o[k][mask] - base[k][mask]
                se = dd.std(ddof=1) / np.sqrt(mask.sum())
                return dd.mean(), (dd.mean() / se if se > 0 else 0.0)
            r, rt = delta("res"); t_, tt = delta("tot"); s_, _ = delta("sc")
            print(f"   {o['label']:34s} {o['res'][mask].mean():8.5f} {r:+8.5f} {rt:+6.2f} "
                  f"{t_:+8.5f} {tt:+6.2f} {s_:+8.5f} {o['draw'][mask].mean():7.4f} "
                  f"{o['var_h'][mask].mean() / o['mean_h'][mask].mean():8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
