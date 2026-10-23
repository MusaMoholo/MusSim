#!/usr/bin/env python3
"""Per-team attack/defence on non-penalty xG, with a rating as a PRIOR rather than a pinned anchor.

Design, and why it differs from scripts/attack_defense.py
---------------------------------------------------------
The earlier module pinned the rating gap as a GLM `offset` (coefficient fixed at 1) and fitted
per-team attack/defence as residuals shrunk toward ZERO. Under that spec a team's own npxG can
never override the rating when the two disagree: the rating's contribution is structurally fixed.

Here the rating enters only as the centre of the shrinkage penalty, so attack/defence is the
primary driver and the rating is a fallback that matters most where data is thin (promoted teams,
early season, clubs outside ClubElo's 19 countries):

    log mu_for = base[comp] + home[comp]*is_home + a_team - d_opp
    a_i = (Q_i + T_i)/2          d_i = (Q_i - T_i)/2
    penalty  lam_q * (Q_i - Q_prior_i)^2  +  lam_t * T_i^2
    Q_prior_i = slope * (elo_i - mean_elo) / 200

Q is overall quality, T is the attack-vs-defence TILT. The split is not cosmetic:

  * A single rating cannot express T at all -- two teams on the same rating get identical
    predicted scorelines however differently they are built. Measured on 2023-25, Arsenal and PSG
    sit at near-identical Q (0.80 vs 0.89) but T -0.39 vs +0.20: Arsenal concedes 0.55x and scores
    1.23x, PSG concedes 0.71x and scores 1.72x. So T is shrunk toward zero, never toward the rating.
  * They decay at different rates. Measured block autocorrelation over 5 seasons puts Q's fast
    component near 100-180 days while T is far more persistent, and forcing one decay rate on both
    (as a single `xi` does) cancels the gain on Q against a loss on T. Hence xi_q and xi_t.
  * The whole null direction of the old parametrisation (add c to every attack AND every defence)
    lives inside Q alone, so penalising Q toward a per-team prior fixes the gauge everywhere at
    once. No reference team is pinned, which also removes the old spec's accidental over-constraint
    (it zeroed one team's attack AND defence, removing 2 dof to kill a 1-dim null space).

Because the prior is per-team and globally comparable, ALL competitions can be fitted jointly --
per-competition baseline and home advantage, per-team attack/defence shared across every
competition a club plays in. That answers PLAN.md Phase 2.2's identifiability question without
needing a pinned global reference.

Fitting note: npxG is a continuous, ~3x UNDERDISPERSED response (Pearson phi 0.32-0.36), so a
Poisson GLM gives valid point estimates but its covariance overstates every standard error by
~1.7x. Shrinkage here is therefore a ridge whose strength is chosen by out-of-sample log-loss, not
a DerSimonian-Laird tau^2 computed from those standard errors -- with the Poisson covariance,
DL's Q statistic lands below its degrees of freedom in 4 of 5 leagues and tau^2 returns exactly
zero, which silently zeroes every deviation.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

NPXG_ELO_SLOPE = 0.6061   # refit on 5 seasons of npxG. NOT 0.7420: that is the GOALS slope
                          # (this repo's staleness.py fit A); goals refit here gives 0.7331.
NPXG_PHI = 0.356          # Var(npxG | mu) = phi * mu, measured (FINDINGS 3)


def _irls(X, y, offset, weights, penalty, centre=None, maxit: int = 80, tol: float = 1e-9):
    """Poisson IRLS, log link, with penalty sum_j penalty_j * (beta_j - centre_j)^2."""
    n, p = X.shape
    off = np.zeros(n) if offset is None else np.asarray(offset, float)
    c = np.zeros(p) if centre is None else np.asarray(centre, float)
    beta = c.copy()
    P = np.diag(penalty)
    Pc = penalty * c
    for _ in range(maxit):
        eta = np.clip(X @ beta + off, -30.0, 30.0)
        mu = np.exp(eta)
        working = eta - off + (y - mu) / mu
        XtW = X.T * (mu * weights)
        new = np.linalg.solve(XtW @ X + P, XtW @ working + Pc)
        if np.max(np.abs(new - beta)) < tol:
            return new
        beta = new
    return beta


def _pair_irls(hi, ai, sign_a, y, offset, weights, lam, centre, k, maxit=60, tol=1e-9):
    """IRLS for a design whose every row has exactly TWO non-zeros: +0.5 on team `hi` and
    sign_a*0.5 on team `ai`. Both the Q and T blocks have that shape (Q: sign_a=-1, T: sign_a=+1).

    Building X.T @ diag(W) @ X densely costs O(n*k^2) -- 18k x 424 for a 5-season pooled fit --
    when the Gram matrix has only four contributions per row. Accumulating them directly with
    np.add.at is O(n) and gives bit-comparable results (verified against the dense path).
    """
    n = len(hi)
    beta = centre.astype(float).copy()
    pen_c = lam * centre
    c_hh = 0.25
    c_ha = 0.25 * sign_a
    for _ in range(maxit):
        eta = 0.5 * (beta[hi] + sign_a * beta[ai]) + offset
        np.clip(eta, -30.0, 30.0, out=eta)
        mu = np.exp(eta)
        W = weights * mu
        work = eta - offset + (y - mu) / mu            # IRLS working response
        Wz = W * work
        G = np.zeros((k, k))
        np.add.at(G, (hi, hi), c_hh * W)
        np.add.at(G, (ai, ai), c_hh * W)
        np.add.at(G, (hi, ai), c_ha * W)
        np.add.at(G, (ai, hi), c_ha * W)
        G[np.diag_indices(k)] += lam
        rhs = np.zeros(k)
        np.add.at(rhs, hi, 0.5 * Wz)
        np.add.at(rhs, ai, (0.5 * sign_a) * Wz)
        rhs += pen_c
        new = np.linalg.solve(G, rhs)
        if np.max(np.abs(new - beta)) < tol:
            return new
        beta = new
    return beta


def _pair_sd(hi, ai, sign_a, mu, weights, lam, k, phi: float = NPXG_PHI) -> np.ndarray:
    """Posterior SD of each team's coefficient in one `_pair_irls` block at the fitted mu.

    The ridge is a prior of precision lam/phi on the quasi-Poisson scale, so the posterior
    covariance is phi * (X'WX + lam)^-1 -- with the decayed weights, which is what makes it the
    uncertainty about strength NOW rather than averaged over the window."""
    W = weights * mu
    G = np.zeros((k, k))
    np.add.at(G, (hi, hi), 0.25 * W)
    np.add.at(G, (ai, ai), 0.25 * W)
    np.add.at(G, (hi, ai), 0.25 * sign_a * W)
    np.add.at(G, (ai, hi), 0.25 * sign_a * W)
    G[np.diag_indices(k)] += lam
    return np.sqrt(phi * np.diag(np.linalg.inv(G)))


def fit(fixtures: pd.DataFrame, asof: pd.Timestamp, *, xi_q: float, xi_t: float,
        lam_q: float, lam_t: float, slope: float = NPXG_ELO_SLOPE,
        xi_level: float = 0.0, normalise_minutes: bool = True,
        target: str = "npxg", outer: int = 16,
        prior: Optional[Dict[str, float]] = None,
        elo_now: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """One joint fit over every competition present in `fixtures` (which must be strictly before
    `asof` for a causal backtest). Q and T need different row weights, so they are alternated to
    convergence by block-coordinate IRLS on a shared linear predictor.

    `prior` rates sides the window leaves unrated, in place of the low fallback. The projection
    passes Opta-based starts (`scripts/opta_ratings.py`): a promoted side ClubElo never rated was
    otherwise centred at the 5th percentile, and with a handful of cup matches to go on its Q
    stayed there -- all six promoted 2026/27 sides started near -0.65, bottom of the pile. The
    centre and the fallback are still computed from the window's own ratings, so every other
    side's prior is exactly what it was.

    `elo_now` replaces each listed side's rating outright, rated or not. A fit through a mid-season
    date needs it: the window's ratings are read off the fixture rows, and ClubElo's mirror stopped
    on 2026-09-01, so without it every side's prior would be its 1 September rating however the
    autumn went. The projection passes the season's own Elo walk to the cutoff -- the same walk
    every world replays -- so the prior a world starts from and the rating it carries agree."""
    f = fixtures
    teams = sorted(set(f.home) | set(f.away))
    comps = sorted(f.competition.unique())
    ti = {t: i for i, t in enumerate(teams)}
    ci = {c: i for i, c in enumerate(comps)}
    k, n, nc = len(teams), len(f), len(comps)

    days = np.clip((asof - f.kickoff).dt.total_seconds().to_numpy() / 86400.0, 0.0, None)
    hi = np.array([ti[t] for t in f.home])
    ai = np.array([ti[t] for t in f.away])
    cc = np.array([ci[c] for c in f.competition])
    r = np.arange(n)

    # Each team's latest point-in-time rating anywhere in the window. A club ClubElo does not
    # cover keeps a low fallback prior rather than being dropped (see module docstring).
    elo = np.full(k, np.nan)
    for j in np.argsort(f.kickoff.to_numpy()):
        if np.isfinite(f.home_elo.iat[j]):
            elo[hi[j]] = f.home_elo.iat[j]
        if np.isfinite(f.away_elo.iat[j]):
            elo[ai[j]] = f.away_elo.iat[j]
    rated = np.isfinite(elo)
    if not rated.any():
        raise RuntimeError("attack_defence_qt: no rated team in the training window")
    elo_mean = float(elo[rated].mean())
    fallback = float(np.percentile(elo[rated], 5))
    for team, v in (prior or {}).items():
        i = ti.get(team)
        if i is not None and not rated[i]:
            elo[i] = v
    for team, v in (elo_now or {}).items():
        i = ti.get(team)
        if i is not None and np.isfinite(v):
            elo[i] = v
    elo = np.where(np.isfinite(elo), elo, fallback)
    q_prior = slope * (elo - elo_mean) / 200.0

    Xlev = np.zeros((2 * n, 2 * nc))
    Xlev[r, cc] = 1.0
    Xlev[n + r, cc] = 1.0
    Xlev[r, nc + cc] = 1.0                       # home advantage on home-scoring rows only

    XQ = np.zeros((2 * n, k))
    XT = np.zeros((2 * n, k))
    np.add.at(XQ, (r, hi), 0.5);      np.add.at(XQ, (r, ai), -0.5)
    np.add.at(XT, (r, hi), 0.5);      np.add.at(XT, (r, ai), 0.5)
    np.add.at(XQ, (n + r, ai), 0.5);  np.add.at(XQ, (n + r, hi), -0.5)
    np.add.at(XT, (n + r, ai), 0.5);  np.add.at(XT, (n + r, hi), 0.5)

    y = np.concatenate([f[f"home_{target}"].to_numpy(float), f[f"away_{target}"].to_numpy(float)])
    # xG accrues over the minutes actually played, so a cup tie settled in extra time carries 120
    # minutes of it and would make both sides look ~33% more dangerous than they are. Scale to a
    # 90-minute rate. Only ~66 matches in five seasons, all in cups, but free to get right.
    if normalise_minutes and "minutes" in f:
        mins = pd.to_numeric(f["minutes"], errors="coerce").fillna(90.0).to_numpy(float)
        y = y * np.tile(90.0 / np.clip(mins, 45.0, None), 2)
    hi2 = np.concatenate([hi, ai])      # "scoring" team on each stacked row
    ai2 = np.concatenate([ai, hi])      # "conceding" team on each stacked row
    wq = np.tile(np.exp(-xi_q * days), 2)
    wt = np.tile(np.exp(-xi_t * days), 2)
    # Competition baseline and home advantage were previously fitted UNDECAYED, so a 2025
    # prediction used a scoring level averaged over 2021-2025. Measured drift is up to 0.26
    # goals/team-match within a league (EPL 1.375-1.639) and home advantage swings wider still
    # (EPL 0.092-0.416), so these are not constants either -- they get their own, slower, rate.
    w_level = np.tile(np.exp(-xi_level * days), 2) if xi_level > 0 else np.ones(2 * n)

    blev = np.zeros(2 * nc)
    bq = q_prior.copy()
    bt = np.zeros(k)
    for _ in range(outer):
        prev = np.concatenate([blev, bq, bt])
        blev = _irls(Xlev, y, XQ @ bq + XT @ bt, w_level, np.full(2 * nc, 1e-8))
        lin = Xlev @ blev
        bq = _pair_irls(hi2, ai2, -1.0, y, lin + XT @ bt, wq, lam_q, q_prior, k)
        bt = _pair_irls(hi2, ai2, +1.0, y, lin + XQ @ bq, wt, lam_t, np.zeros(k), k)
        if np.max(np.abs(np.concatenate([blev, bq, bt]) - prev)) < 1e-7:
            break

    Q = dict(zip(teams, bq))
    T = dict(zip(teams, bt))
    mu_fit = np.exp(np.clip(Xlev @ blev + XQ @ bq + XT @ bt, -30.0, 30.0))
    q_sd = _pair_sd(hi2, ai2, -1.0, mu_fit, wq, lam_q, k)
    t_sd = _pair_sd(hi2, ai2, +1.0, mu_fit, wt, lam_t, k)
    return {
        "teams": teams, "competitions": comps,
        "base": {c: float(blev[ci[c]]) for c in comps},
        "home": {c: float(blev[nc + ci[c]]) for c in comps},
        "Q": Q, "T": T,
        "attack": {t: (Q[t] + T[t]) / 2 for t in teams},
        "defence": {t: (Q[t] - T[t]) / 2 for t in teams},
        "q_prior": dict(zip(teams, q_prior)),
        # how uncertain each estimate is, for a simulator that samples a world's starting state
        # rather than plugging in the point estimate; a side with no data has the prior's
        "q_sd": dict(zip(teams, q_sd)), "t_sd": dict(zip(teams, t_sd)),
        "q_sd_prior": float(np.sqrt(NPXG_PHI / lam_q)),
        "elo_mean": elo_mean, "elo_fallback": fallback, "slope": slope, "n": n,
    }


def predict_npxg(fixtures: pd.DataFrame, model: Dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Expected npxG for both sides. A team absent from the fit (newly promoted, or a cup entrant
    never seen before) falls back to its rating-implied prior with zero tilt -- the rating's job."""
    base_mean = float(np.mean(list(model["base"].values())))
    home_mean = float(np.mean(list(model["home"].values())))
    mh = np.empty(len(fixtures))
    ma = np.empty(len(fixtures))

    def qt(team: str, elo: float):
        if team in model["Q"]:
            return model["Q"][team], model["T"][team]
        e = elo if np.isfinite(elo) else model["elo_fallback"]
        return model["slope"] * (e - model["elo_mean"]) / 200.0, 0.0

    for i, row in enumerate(fixtures.itertuples()):
        qh, th = qt(row.home, row.home_elo)
        qa, ta = qt(row.away, row.away_elo)
        b = model["base"].get(row.competition, base_mean)
        h = model["home"].get(row.competition, home_mean)
        mh[i] = np.exp(b + h + (qh + th) / 2 - (qa - ta) / 2)
        ma[i] = np.exp(b + (qa + ta) / 2 - (qh - th) / 2)
    return mh, ma


CONVERSION_RIDGE = 1000.0   # see fit_goal_conversion: heavy by necessity, weak signal


def fit_goal_conversion(fixtures: pd.DataFrame, mu_h, mu_a,
                        ridge: float = CONVERSION_RIDGE) -> Dict[str, Any]:
    """npxG -> goals, with per-competition (alpha, beta) AND per-team finishing / keeping.

        log lam_home = alpha_c + beta_c * log(mu_npxg_home) + finishing_home - keeping_away

    Why the team terms belong here and not in the strength layer. npxG is CHANCE CREATION: it is
    the probability an average finisher beats an average keeper, and keeper identity is not an
    input. What separates npxG from goals is conversion -- shot placement (npxG -> xGOT) and
    shot-stopping (xGOT -> goals). Both are persistent team traits, measured by split-half:
    finishing 0.208 (reliability 0.344), keeping 0.205 (0.340), against 0.395 for the npxG
    attack/defence signal. Measuring at keeper level rather than team level adds nothing
    (0.485 vs 0.487): the first-choice keeper plays the bulk of the minutes, so the team number
    is already mostly him.

    The ridge has to be HEAVY. Swept out-of-sample over five test seasons, the term is worth
    -0.0002 log-loss at ridge 800-2000 (t = -1.25, i.e. free but not significant) and actively
    harmful below ~400: +0.0031 at ridge 80, +0.0087 at ridge 10. One free parameter per team
    fitted against the same goals it predicts overfits fast on a signal this weak.

    It is kept despite the negligible 1X2 gain because the pipeline then mirrors the real causal
    chain -- creation, then conversion, then the score -- so a sampled scoreline IS the score, and
    GF/GA follow from it with no post-processing. It should matter more for totals and
    correct-score than for 1X2, where conversion largely cancels between the two sides.
    """
    f = fixtures
    teams = sorted(set(f.home) | set(f.away))
    comps = sorted(f.competition.unique())
    ti = {t: i for i, t in enumerate(teams)}
    ci = {c: i for i, c in enumerate(comps)}
    n, k, nc = len(f), len(teams), len(comps)
    lm = np.log(np.clip(np.r_[mu_h, mu_a], 1e-6, None))
    y = np.r_[f.home_goals.to_numpy(float), f.away_goals.to_numpy(float)]
    cc = np.array([ci[c] for c in f.competition]); cc2 = np.r_[cc, cc]
    hi = np.array([ti[t] for t in f.home]); ai = np.array([ti[t] for t in f.away])
    scorer = np.r_[hi, ai]
    conceder = np.r_[ai, hi]
    rows = np.arange(2 * n)

    X = np.zeros((2 * n, 2 * nc + 2 * k))
    X[rows, cc2] = 1.0                          # alpha per competition
    X[rows, nc + cc2] = lm                      # beta per competition
    np.add.at(X, (rows, 2 * nc + scorer), 1.0)          # finishing of the scoring side
    np.add.at(X, (rows, 2 * nc + k + conceder), -1.0)   # keeping of the conceding side
    pen = np.full(2 * nc + 2 * k, 1e-8); pen[2 * nc:] = ridge
    ok = np.isfinite(y)
    beta = _irls(X[ok], y[ok], None, np.ones(int(ok.sum())), pen)
    return {
        "alpha": {c: float(beta[ci[c]]) for c in comps},
        "beta": {c: float(beta[nc + ci[c]]) for c in comps},
        "finishing": dict(zip(teams, beta[2 * nc:2 * nc + k])),
        "keeping": dict(zip(teams, beta[2 * nc + k:])),
    }


def apply_goal_conversion(fixtures: pd.DataFrame, mu_h, mu_a, conv: Dict[str, Any]):
    a_m = float(np.mean(list(conv["alpha"].values())))
    b_m = float(np.mean(list(conv["beta"].values())))
    a = np.array([conv["alpha"].get(c, a_m) for c in fixtures.competition])
    b = np.array([conv["beta"].get(c, b_m) for c in fixtures.competition])
    fin_h = np.array([conv["finishing"].get(t, 0.0) for t in fixtures.home])
    fin_a = np.array([conv["finishing"].get(t, 0.0) for t in fixtures.away])
    kee_h = np.array([conv["keeping"].get(t, 0.0) for t in fixtures.home])
    kee_a = np.array([conv["keeping"].get(t, 0.0) for t in fixtures.away])
    lam_h = np.exp(a + b * np.log(np.clip(mu_h, 1e-6, None)) + fin_h - kee_a)
    lam_a = np.exp(a + b * np.log(np.clip(mu_a, 1e-6, None)) + fin_a - kee_h)
    return np.clip(lam_h, 1e-4, None), np.clip(lam_a, 1e-4, None)


def fit_goal_calibration(fixtures: pd.DataFrame, mu_h, mu_a) -> Dict[str, tuple[float, float]]:
    """goals ~ exp(a + b*log(mu_npxg)), fitted PER COMPETITION.

    Never pooled: leagues differ in scoring level (Bundesliga runs ~27% higher than Serie A) and
    one global (a, b) conflates that real difference with the xG-to-goals mapping itself."""
    out: Dict[str, tuple[float, float]] = {}
    frame = fixtures.assign(_mh=mu_h, _ma=mu_a)
    for comp, g in frame.groupby("competition"):
        lm = np.log(np.clip(np.r_[g._mh, g._ma], 1e-6, None))
        y = np.r_[g.home_goals.to_numpy(float), g.away_goals.to_numpy(float)]
        ok = np.isfinite(y)
        if ok.sum() < 20:
            continue
        X = np.column_stack([np.ones(ok.sum()), lm[ok]])
        beta = _irls(X, y[ok], None, np.ones(int(ok.sum())), np.full(2, 1e-8))
        out[comp] = (float(beta[0]), float(beta[1]))
    return out


R_CLIP = (0.55, 0.95)   # the goal-dispersion line is only measured inside this range


def fit_goal_layer(fixtures: pd.DataFrame, mu_h, mu_a) -> Dict[str, Any]:
    """Goals given the npxG a side actually produced (x) and the npxG it was expected to (mu):

        E[goals | x, mu]   = c0[comp] + c1*x + c2*mu
        Var[goals | x, mu] = r(x) * E[goals | x, mu],   r(x) = r0 + r1*x

    This is the second stage of the simulator's two-stage match: npxG is drawn first, then the
    goals from it, so a side can win the npxG and lose the match -- and its strength moves on the
    npxG, its rating on the result. Every term is measured (`analysis/npxg_to_goals.py`):

      * LINEAR, with an intercept. Goals exceed npxG by ~0.2 a side at low npxG and by nothing at
        high npxG: the intercept is penalties and own goals, which npxG excludes. It beats the
        one-stage power law on held-out seasons.
      * mu carries information x does not. Realised npxG is a noisy reading of the chances a side
        really made, and better sides convert better: on 9,850 walk-forward matches the pooled
        fit is -0.25 + 0.80*x + 0.52*mu. Without mu the two-stage model is worse than the
        one-stage one on 1X2 (+0.009, t=5.9); with it, better on 1X2 (-0.0012), total goals
        (-0.0058, t=-5.3) and exact score, and its draw rate is 23.5% against 23.4% real.
      * UNDERDISPERSED. Var/mean of goals given npxG runs 0.90 at low npxG down to ~0.72 at high
        (a sum of shot probabilities is Poisson-binomial, not Poisson), and a Poisson second
        stage overshoots the real spread of goals by a third. The sampler draws a binomial with
        this variance.
      * Slopes pooled, intercept per competition. Per-competition slopes are noisy in the cups
        (the League Cup's mu slope came out at 0.91) and the levels are where competitions differ.

    Fitted on 90-minute matches only -- extra time accrues npxG for 120 -- and on the fit's own
    (in-sample) mu, which gives coefficients within ~0.04 of the walk-forward ones."""
    f = fixtures
    mins = pd.to_numeric(f["minutes"], errors="coerce").fillna(90.0).to_numpy(float) \
        if "minutes" in f else np.full(len(f), 90.0)
    x = np.r_[f.home_npxg.to_numpy(float), f.away_npxg.to_numpy(float)]
    g = np.r_[f.home_goals.to_numpy(float), f.away_goals.to_numpy(float)]
    mu = np.r_[np.asarray(mu_h, float), np.asarray(mu_a, float)]
    comp = np.r_[f.competition.to_numpy(), f.competition.to_numpy()]
    ok = np.isfinite(x) & np.isfinite(g) & np.isfinite(mu) & np.tile(mins <= 90.0, 2)
    x, g, mu, comp = x[ok], g[ok], mu[ok], comp[ok]
    comps = sorted(set(comp))
    ci = {c: i for i, c in enumerate(comps)}
    A = np.zeros((len(x), len(comps) + 2))
    A[np.arange(len(x)), [ci[c] for c in comp]] = 1.0
    A[:, -2], A[:, -1] = x, mu
    coef = np.linalg.lstsq(A, g, rcond=None)[0]
    m = np.maximum(A @ coef, 0.02)
    edges = np.quantile(x, np.linspace(0, 1, 13)[1:-1])
    b = np.digitize(x, edges)
    xs = [x[b == k].mean() for k in np.unique(b)]
    rs = [np.mean((g[b == k] - m[b == k]) ** 2) / m[b == k].mean() for k in np.unique(b)]
    r1, r0 = np.polyfit(xs, rs, 1)
    c0 = {c: float(coef[ci[c]]) for c in comps}
    counts = pd.Series(comp).value_counts()
    return {"c0": c0, "c0_mean": float(np.average([c0[c] for c in comps],
                                                   weights=[counts[c] for c in comps])),
            "c1": float(coef[-2]), "c2": float(coef[-1]), "r": (float(r0), float(r1)),
            "rows": int(len(x))}


def goal_mean(layer: Dict[str, Any], competition: str, x, mu):
    """E[goals | realised npxG x, expected npxG mu] under `fit_goal_layer`."""
    c0 = layer["c0"].get(competition, layer["c0_mean"])
    return np.maximum(c0 + layer["c1"] * np.asarray(x, float) + layer["c2"] * np.asarray(mu, float),
                      0.02)


def goal_dispersion(layer: Dict[str, Any], x):
    """Var/mean of goals given realised npxG x, clipped to where it was measured."""
    r0, r1 = layer["r"]
    return np.clip(r0 + r1 * np.asarray(x, float), *R_CLIP)


def apply_goal_calibration(fixtures: pd.DataFrame, mu_h, mu_a,
                           calibration: Dict[str, tuple[float, float]]):
    if calibration:
        mean_a = float(np.mean([v[0] for v in calibration.values()]))
        mean_b = float(np.mean([v[1] for v in calibration.values()]))
    else:
        mean_a, mean_b = 0.0, 1.0
    a = np.array([calibration.get(c, (mean_a, mean_b))[0] for c in fixtures.competition])
    b = np.array([calibration.get(c, (mean_a, mean_b))[1] for c in fixtures.competition])
    lam_h = np.exp(a + b * np.log(np.clip(mu_h, 1e-6, None)))
    lam_a = np.exp(a + b * np.log(np.clip(mu_a, 1e-6, None)))
    return np.clip(lam_h, 1e-4, None), np.clip(lam_a, 1e-4, None)
