"""Disentangle training DEPTH from CALENDAR TIME.

The expanding-window backtest confounds them: later test seasons necessarily have more history.
Here the training window is capped at a fixed length, so every test season sees roughly the same
amount of data. If the optimal half-life goes FLAT across seasons, the trend was a depth effect.
If it still rises, team strength really has become more persistent."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from scripts.attack_defence_qt import fit, predict_npxg, fit_goal_calibration, apply_goal_calibration
from scripts.backtest_qt import load_master, log_loss

WINDOW_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 730     # ~2 seasons of history, always
m = load_master(); m = m[m.kind.isin(['league', 'uefa'])]
HL = [None, 500, 280, 200, 140, 100, 70]

def run(hl, refit=14):
    xi_q = 0.0 if hl is None else np.log(2)/hl
    rows = []
    tgt = m[(m.kickoff >= pd.Timestamp('2022-08-01')) & (m.kind == 'league')]
    edges = pd.date_range(tgt.kickoff.min().normalize(),
                          tgt.kickoff.max().normalize()+pd.Timedelta(days=refit), freq=f'{refit}D')
    for s, e in zip(edges[:-1], edges[1:]):
        win = m[(m.kickoff >= s) & (m.kickoff < e) & (m.kind == 'league')]
        if win.empty: continue
        tr = m[(m.kickoff < s) & (m.kickoff >= s - pd.Timedelta(days=WINDOW_DAYS))]
        if len(tr) < 300: continue
        mdl = fit(tr, s, xi_q=xi_q, xi_t=np.log(2)/1460, lam_q=5.0, lam_t=10.0)
        th, ta = predict_npxg(tr, mdl); cal = fit_goal_calibration(tr, th, ta)
        mu_h, mu_a = predict_npxg(win, mdl)
        lh, la = apply_goal_calibration(win, mu_h, mu_a, cal)
        rows.append(pd.DataFrame({'season': win.season.to_numpy(), 'result': win.result.to_numpy(),
                                  'lam_h': lh, 'lam_a': la}))
    return pd.concat(rows, ignore_index=True)

res = {hl: run(hl) for hl in HL}
seasons = sorted(res[HL[0]].season.unique())
print(f'FIXED {WINDOW_DAYS}-day training window (every season sees ~the same history)\n')
print(f'{"hl_Q":>7s} ' + ' '.join(f'{s:>9d}' for s in seasons) + f' {"pooled":>9s}')
for hl in HL:
    p = res[hl]; v = log_loss(p); sv = p.season.to_numpy()
    print(f'{str(hl):>7s} ' + ' '.join(f'{v[sv==s].mean():9.4f}' for s in seasons) + f' {v.mean():9.4f}')
print('\nbest hl_Q per season, and mean training size:')
for s in seasons:
    best = min(HL, key=lambda h: log_loss(res[h])[res[h].season.to_numpy()==s].mean())
    print(f'  {s}: best hl_Q = {str(best):>5s}')
