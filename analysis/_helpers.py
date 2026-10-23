"""Shared helpers: Poisson IRLS, team-match long format, Elo-only baseline."""
import numpy as np, pandas as pd

def poisson_glm(X, y, offset=None, weights=None, ridge=1e-8, tol=1e-10, maxit=200):
    """Weighted Poisson GLM, log link, IRLS. Returns (beta, cov, iters)."""
    X = np.asarray(X, float); y = np.asarray(y, float)
    n, p = X.shape
    off = np.zeros(n) if offset is None else np.asarray(offset, float)
    w = np.ones(n) if weights is None else np.asarray(weights, float)
    beta = np.zeros(p)
    R = ridge * np.eye(p)
    for it in range(1, maxit + 1):
        eta = X @ beta + off
        mu = np.exp(np.clip(eta, -30, 30))
        W = w * mu
        z = (y - mu)
        grad = X.T @ z - ridge * beta          # weights already inside via W below
        # IRLS: solve (X' W X + R) d = X'(y-mu)*w
        H = X.T @ (X * W[:, None]) + R
        rhs = X.T @ (w * z) - ridge * beta
        try:
            d = np.linalg.solve(H, rhs)
        except np.linalg.LinAlgError:
            d = np.linalg.lstsq(H, rhs, rcond=None)[0]
        # damped step for stability
        step = 1.0
        for _ in range(30):
            cand = beta + step * d
            if np.all(np.abs(X @ cand + off) < 30): break
            step *= 0.5
        beta = beta + step * d
        if np.max(np.abs(step * d)) < tol: break
    eta = X @ beta + off
    mu = np.exp(np.clip(eta, -30, 30))
    H = X.T @ (X * (w * mu)[:, None]) + R
    try: cov = np.linalg.inv(H)
    except np.linalg.LinAlgError: cov = np.linalg.pinv(H)
    return beta, cov, it


def to_long(m):
    """One row per team-match: (team, opp, is_home, npxg_for, goals_for, ...)."""
    a = pd.DataFrame({
        'match_id': m.match_id.values, 'date': m.date.values, 'season': m.season.values,
        'competition': m.competition.values, 'kind': m.kind.values,
        'team': m.home.values, 'opp': m.away.values, 'is_home': 1.0,
        'team_elo': m.home_elo.values, 'opp_elo': m.away_elo.values,
        'npxg': m.home_npxg.values, 'npxg_conc': m.away_npxg.values,
        'goals': m.home_goals.values, 'goals_conc': m.away_goals.values,
    })
    b = pd.DataFrame({
        'match_id': m.match_id.values, 'date': m.date.values, 'season': m.season.values,
        'competition': m.competition.values, 'kind': m.kind.values,
        'team': m.away.values, 'opp': m.home.values, 'is_home': 0.0,
        'team_elo': m.away_elo.values, 'opp_elo': m.home_elo.values,
        'npxg': m.away_npxg.values, 'npxg_conc': m.home_npxg.values,
        'goals': m.away_goals.values, 'goals_conc': m.home_goals.values,
    })
    return pd.concat([a, b], ignore_index=True).sort_values('date').reset_index(drop=True)


def elo_only_expected(L, target='npxg', fit_slope=True, slope=0.7420):
    """Elo-only baseline: log(mu) = base[comp] + home*is_home + s*(elo_team-elo_opp)/400.
    Returns expected values (mu) aligned to L, plus fitted params."""
    comps = sorted(L.competition.unique())
    ci = {c: i for i, c in enumerate(comps)}
    d = (L.team_elo.to_numpy() - L.opp_elo.to_numpy()) / 400.0
    cols = [np.eye(len(comps))[[ci[c] for c in L.competition]], L.is_home.to_numpy()[:, None]]
    if fit_slope:
        cols.append(d[:, None]); off = None
    else:
        off = slope * d
    X = np.hstack(cols)
    y = L[target].to_numpy(float)
    beta, cov, it = poisson_glm(X, y, offset=off, ridge=1e-8)
    mu = np.exp(X @ beta + (0 if off is None else off))
    return mu, dict(comps=comps, beta=beta, cov=cov, slope=(beta[-1] if fit_slope else slope))


# --------------------------------------------------------------- repo-path compatibility shim
def load_matches(kind=('league',), need_npxg=True, need_elo=True, seasons=None):
    """Load data/master_fixtures.pkl in the shape these analysis scripts expect.

    The master table calls the kickoff column `kickoff`; these scripts were written against an
    earlier frame that called it `date`, so it is aliased here rather than editing every script.
    """
    import pandas as pd
    from pathlib import Path
    m = pd.read_pickle(Path(__file__).resolve().parent.parent / 'data' / 'master_fixtures.pkl')
    if 'kickoff' in m.columns and 'date' not in m.columns:
        m = m.rename(columns={'kickoff': 'date'})
    m = m[m.played] if 'played' in m.columns else m
    if kind is not None:
        m = m[m.kind.isin(kind)]
    if need_npxg:
        m = m[m.has_npxg]
    if need_elo:
        m = m[m.elo_ok]
    if seasons is not None:
        m = m[m.season.isin(seasons)]
    return m.sort_values('date').reset_index(drop=True)
