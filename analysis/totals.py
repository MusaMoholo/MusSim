"""Does the conversion layer (finishing / keeping) pay on TOTALS, where it should?

For 1X2 a conversion edge largely cancels: if both sides convert a bit better, the balance of the
match barely moves. For over/under and correct-score it does not cancel -- it shifts the whole
goal distribution. So this is the test where the signal should show up if it is worth anything.
"""
import sys; sys.path.insert(0,'/Users/moholom/Repos/Football')
from pathlib import Path
import numpy as np, pandas as pd
from scripts.attack_defence_qt import (fit, predict_npxg, fit_goal_calibration,
                                       apply_goal_calibration, fit_goal_conversion,
                                       apply_goal_conversion)
from scripts.backtest_qt import load_master, score_matrix, MAXG, paired

m = load_master(Path('data/master_fixtures.pkl')); m = m[m.kind.isin(['league','uefa'])]
TF = pd.Timestamp('2022-08-01'); REFIT = 14
KW = dict(xi_q=np.log(2)/140, xi_t=np.log(2)/1460, lam_q=5.0, lam_t=40.0)
RHO = -0.10

def run(mode, ridge=1000.0):
    rows=[]
    tgt = m[(m.kickoff>=TF)&(m.kind=='league')]
    edges = pd.date_range(tgt.kickoff.min().normalize(),
                          tgt.kickoff.max().normalize()+pd.Timedelta(days=REFIT), freq=f'{REFIT}D')
    for s,e in zip(edges[:-1], edges[1:]):
        win = m[(m.kickoff>=s)&(m.kickoff<e)&(m.kind=='league')]
        if win.empty: continue
        tr = m[m.kickoff<s]
        if len(tr)<300: continue
        mdl = fit(tr, s, **KW)
        th, ta = predict_npxg(tr, mdl)
        wh, wa = predict_npxg(win, mdl)
        if mode == 'plain':
            cal = fit_goal_calibration(tr, th, ta)
            lh, la = apply_goal_calibration(win, wh, wa, cal)
        else:
            conv = fit_goal_conversion(tr, th, ta, ridge=ridge)
            lh, la = apply_goal_conversion(win, wh, wa, conv)
        rows.append(pd.DataFrame({'season':win.season.values,
                                  'tot':(win.home_goals+win.away_goals).values,
                                  'lam_h':lh,'lam_a':la}))
    return pd.concat(rows, ignore_index=True)

def totals_metrics(p, line=2.5):
    M = score_matrix(p.lam_h.to_numpy(), p.lam_a.to_numpy(), RHO)
    g = np.arange(MAXG+1)
    tot = g[:,None] + g[None,:]
    p_over = np.array([M[i][tot > line].sum() for i in range(len(p))])
    p_over = np.clip(p_over, 1e-9, 1-1e-9)
    y = (p.tot.to_numpy() > line).astype(float)
    ll = -(y*np.log(p_over) + (1-y)*np.log(1-p_over))
    brier = (p_over - y)**2
    # also the full goal-total distribution log-loss
    ptot = np.zeros((len(p), 2*MAXG+1))
    for i in range(len(p)):
        np.add.at(ptot[i], tot.ravel(), M[i].ravel())
    tt = np.clip(p.tot.to_numpy().astype(int), 0, 2*MAXG)
    ll_full = -np.log(np.clip(ptot[np.arange(len(p)), tt], 1e-12, None))
    return ll, brier, ll_full, p_over, y

res = {}
for mode, lbl in [('plain','npxG only (no conversion layer)'), ('conv','+ finishing / keeping')]:
    p = run(mode)
    ll, br, llf, po, y = totals_metrics(p)
    res[mode] = (ll, br, llf, po, y, p)
    print(f'{lbl:34s} O/U2.5 logloss {ll.mean():.4f}  Brier {br.mean():.4f}  '
          f'full-total logloss {llf.mean():.4f}')
    print(f'{"":34s} predicted over-rate {po.mean():.4f} vs actual {y.mean():.4f}')
a, b = res['conv'], res['plain']
for i, nm in [(0,'O/U 2.5 log-loss'), (1,'O/U 2.5 Brier'), (2,'full goal-total log-loss')]:
    d, se, t = paired(a[i], b[i])
    print(f'\npaired {nm:26s} {d:+.5f} ± {se:.5f}  t={t:+.2f}  (negative = conversion layer better)')
