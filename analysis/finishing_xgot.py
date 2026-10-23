"""Does a per-team FINISHING / GOALKEEPING term on the npxG->goals layer improve prediction?

The model's strength layer is npxG-based, so it assumes league-average finishing and keeping.
Measured split-half reliability says both are persistent traits (0.268 and 0.214 full-season),
weaker than npxG attack/defence (0.566) but not noise. This adds

    log lam_home = alpha_c + beta_c*log(mu_npxg_home) + fin_home - kee_away

with fin/kee per team, ridge-shrunk toward zero, fitted on TRAINING data only at every origin.
"""
import sys; sys.path.insert(0,'/Users/moholom/Repos/Football')
from pathlib import Path
import numpy as np, pandas as pd
from scripts.attack_defence_qt import fit, predict_npxg, _irls, _pair_irls
from scripts.backtest_qt import load_master, log_loss, paired, outcome_probs

m = load_master(Path('data/master_fixtures.pkl')); m = m[m.kind.isin(['league','uefa'])]
TF = pd.Timestamp('2022-08-01'); REFIT = 14
KW = dict(xi_q=np.log(2)/140, xi_t=np.log(2)/1460, lam_q=5.0, lam_t=40.0)

def fit_goals_layer(tr, mu_h, mu_a, lam_fin):
    """Per-competition (alpha,beta) plus per-team fin/kee, all in one Poisson GLM."""
    teams = sorted(set(tr.home)|set(tr.away)); comps = sorted(tr.competition.unique())
    ti={t:i for i,t in enumerate(teams)}; ci={c:i for i,c in enumerate(comps)}
    n,k,nc = len(tr), len(teams), len(comps)
    r=np.arange(n)
    lm = np.log(np.clip(np.r_[mu_h, mu_a], 1e-6, None))
    # xGOT-based: finishing = the team own xGOT surplus over npxG; keeping = xGOT faced vs conceded.
    # A cleaner decomposition than goals-vs-xG (reliability 0.344/0.340 vs 0.268/0.214).
    y  = np.r_[tr.home_goals.to_numpy(float), tr.away_goals.to_numpy(float)]
    cc = np.array([ci[c] for c in tr.competition]); cc2=np.r_[cc,cc]
    hi=np.array([ti[t] for t in tr.home]); ai=np.array([ti[t] for t in tr.away])
    # columns: alpha per comp, beta per comp, fin per team, kee per team
    p = 2*nc + 2*k
    X = np.zeros((2*n, p))
    X[np.arange(2*n), cc2] = 1.0
    X[np.arange(2*n), nc+cc2] = lm
    sc = np.r_[hi, ai]          # scoring team
    cn = np.r_[ai, hi]          # conceding team
    X[np.arange(2*n), 2*nc+sc] += 1.0          # finishing of the scorer
    X[np.arange(2*n), 2*nc+k+cn] -= 1.0        # keeping of the conceder
    pen = np.full(p, 1e-8); pen[2*nc:] = lam_fin
    ok = np.isfinite(y)
    beta = _irls(X[ok], y[ok], None, np.ones(int(ok.sum())), pen)
    return dict(comps=comps, teams=teams,
                alpha={c: beta[ci[c]] for c in comps},
                beta={c: beta[nc+ci[c]] for c in comps},
                fin=dict(zip(teams, beta[2*nc:2*nc+k])),
                kee=dict(zip(teams, beta[2*nc+k:])))

def apply_goals_layer(df, mu_h, mu_a, gl, use_team=True):
    am = np.mean(list(gl['alpha'].values())); bm = np.mean(list(gl['beta'].values()))
    a = np.array([gl['alpha'].get(c, am) for c in df.competition])
    b = np.array([gl['beta'].get(c, bm) for c in df.competition])
    fh = np.array([gl['fin'].get(t,0.0) for t in df.home]) if use_team else 0.0
    fa = np.array([gl['fin'].get(t,0.0) for t in df.away]) if use_team else 0.0
    kh = np.array([gl['kee'].get(t,0.0) for t in df.home]) if use_team else 0.0
    ka = np.array([gl['kee'].get(t,0.0) for t in df.away]) if use_team else 0.0
    lh = np.exp(a + b*np.log(np.clip(mu_h,1e-6,None)) + fh - ka)
    la = np.exp(a + b*np.log(np.clip(mu_a,1e-6,None)) + fa - kh)
    return np.clip(lh,1e-4,None), np.clip(la,1e-4,None)

def run(lam_fin, use_team):
    rows=[]
    tgt = m[(m.kickoff>=TF)&(m.kind=='league')]
    edges = pd.date_range(tgt.kickoff.min().normalize(), tgt.kickoff.max().normalize()+pd.Timedelta(days=REFIT), freq=f'{REFIT}D')
    for s,e in zip(edges[:-1], edges[1:]):
        win = m[(m.kickoff>=s)&(m.kickoff<e)&(m.kind=='league')]
        if win.empty: continue
        tr = m[m.kickoff<s]
        if len(tr)<300: continue
        mdl = fit(tr, s, **KW)
        th, ta = predict_npxg(tr, mdl)
        gl = fit_goals_layer(tr, th, ta, lam_fin)
        wh, wa = predict_npxg(win, mdl)
        lh, la = apply_goals_layer(win, wh, wa, gl, use_team)
        rows.append(pd.DataFrame({'season':win.season.values,'result':win.result.values,'lam_h':lh,'lam_a':la}))
    return pd.concat(rows, ignore_index=True)

base = run(1e9, False)            # no team terms: reproduces the current model
V = {'no fin/kee': log_loss(base)}
S = base.season.to_numpy()
for lf in [2000, 800, 400, 200, 80]:
    p = run(float(lf), True)
    V[f'lam_fin={lf}'] = log_loss(p)
print(f'{"config":16s} {"pooled":>8s} ' + ' '.join(f'{s:>7d}' for s in sorted(set(S.tolist()))) + f' {"vs base":>20s}')
for k,v in V.items():
    d,se,t = paired(v, V['no fin/kee'])
    extra = '   (reference)' if k=='no fin/kee' else f' {d:+.5f} ± {se:.5f} t={t:+.2f}'
    print(f'{k:16s} {v.mean():8.4f} ' + ' '.join(f'{v[S==s].mean():7.4f}' for s in sorted(set(S.tolist()))) + extra)
