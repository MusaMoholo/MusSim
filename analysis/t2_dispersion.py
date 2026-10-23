"""Why did DerSimonian-Laird return tau^2 = 0? Check the Poisson dispersion assumption.
npxG is a CONTINUOUS response. A Poisson GLM's covariance is only correct if Var(y)=mu."""
import sys
from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
import numpy as np, pandas as pd
from _helpers import poisson_glm


# RENAME SHIM: the master table calls the kickoff column `kickoff`; this script was written
# against an earlier frame that called it `date`.
def _shim(df):
    if 'kickoff' in df.columns and 'date' not in df.columns:
        df = df.rename(columns={'kickoff': 'date'})
    return df[df.played] if 'played' in df.columns else df

SP = str(Path(__file__).resolve().parent)
m = _shim(pd.read_pickle(os.environ.get('MATCHES_PKL', str(Path(__file__).resolve().parent.parent / 'data' / 'master_fixtures.pkl'))))
m = m[(m.kind == 'league') & m.has_npxg & m.elo_ok].copy()

print('marginal moments of the response (per team-match):')
for lbl, v in [('npxg', np.r_[m.home_npxg, m.away_npxg]), ('goals', np.r_[m.home_goals, m.away_goals])]:
    print(f'  {lbl:6s} mean={v.mean():.3f}  var={v.var():.3f}  var/mean={v.var()/v.mean():.3f}')

def dl_tau2(theta, se):
    w = 1.0 / se**2
    tbar = (w * theta).sum() / w.sum()
    Q = (w * (theta - tbar)**2).sum()
    k = len(theta)
    c = w.sum() - (w**2).sum() / w.sum()
    return max(0.0, (Q - (k - 1)) / c), Q, k - 1

# Replicate the repo's fit exactly (pinned slope 0.742, ridge 1e-6), per league
SLOPE = 0.7420
print(f'\n{"league":26s} {"phi":>6s} {"Q":>8s} {"df":>4s} | tau_att  tau_def   (as coded)'
      f' | tau_att  tau_def   (phi-corrected)')
for target in ['npxg']:
    for league, tr in m.groupby('competition'):
        teams = sorted(set(tr.home) | set(tr.away))
        ref, others = teams[-1], teams[:-1]
        col = {t: i for i, t in enumerate(others)}
        n, k = len(tr), len(others)
        p = 2 + 2 * k
        X = np.zeros((2 * n, p)); X[:n, 0] = 1; X[:n, 1] = 1; X[n:, 0] = 1
        for r, (h, a) in enumerate(zip(tr.home, tr.away)):
            if h in col: X[r, 2 + col[h]] = 1.0
            if a in col: X[r, 2 + k + col[a]] = -1.0
            if a in col: X[n + r, 2 + col[a]] = 1.0
            if h in col: X[n + r, 2 + k + col[h]] = -1.0
        od = SLOPE * (tr.home_elo.to_numpy() - tr.away_elo.to_numpy()) / 400.0
        offset = np.r_[od, -od]
        y = np.r_[tr[f'home_{target}'].to_numpy(float), tr[f'away_{target}'].to_numpy(float)]
        beta, cov, it = poisson_glm(X, y, offset=offset, ridge=1e-6)
        mu = np.exp(X @ beta + offset)
        # Pearson dispersion
        phi = (((y - mu) ** 2) / mu).sum() / (2 * n - p)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
        a_raw, d_raw = beta[2:2 + k], beta[2 + k:]
        a_se, d_se = np.clip(se[2:2 + k], 1e-6, None), np.clip(se[2 + k:], 1e-6, None)
        ta, Qa, dfa = dl_tau2(a_raw, a_se)
        td, Qd, dfd = dl_tau2(d_raw, d_se)
        # phi-corrected: cov scales by phi  ->  se scales by sqrt(phi)
        ta_c, Qa_c, _ = dl_tau2(a_raw, a_se * np.sqrt(phi))
        td_c, Qd_c, _ = dl_tau2(d_raw, d_se * np.sqrt(phi))
        print(f'{league:26s} {phi:6.3f} {Qa:8.1f} {dfa:4d} | {ta**.5:7.4f} {td**.5:8.4f}'
              f'          | {ta_c**.5:7.4f} {td_c**.5:8.4f}')
        print(f'{"":26s} {"":6s} {"":8s} {"":4s} |  observed sd of raw estimates:'
              f' att {a_raw.std():.4f}  def {d_raw.std():.4f};  mean se: att {a_se.mean():.4f} def {d_se.mean():.4f}')
