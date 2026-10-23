"""Fit K and home_adv on CLEAN club-fortnights only: every match visible, every opponent rated.
That removes the attenuation that made UEFA/cup look down-weighted."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from scripts.elo_engine import load_snapshots, load_fixtures, expected_home

snaps = load_snapshots(); fx = load_fixtures()
fx = fx[fx.season.isin([2025])]
dates = [d for d in snaps.index if fx.kickoff.min() <= d <= fx.kickoff.max()]

def build(home_adv):
    rows = []
    for t0, t1 in zip(dates[:-1], dates[1:]):
        start, end = snaps.loc[t0].dropna(), snaps.loc[t1].dropna()
        bt = fx[(fx.kickoff > t0) & (fx.kickoff <= t1)]
        if bt.empty: continue
        for team in set(start.index) & set(end.index):
            mh = bt[bt.home == team]; ma = bt[bt.away == team]
            if len(mh) + len(ma) == 0: continue
            # CLEAN only: every match has a finite result AND a rated opponent
            opps = list(mh.away) + list(ma.home)
            res_ok = all(np.isfinite(v) for v in list(mh.home_goals) + list(ma.away_goals))
            if not res_ok or not all(o in start.index for o in opps): continue
            exp_p = act_p = 0.0; gd = 0.0
            for r in mh.itertuples():
                exp_p += float(expected_home(np.array([start[team]]), np.array([start[r.away]]), home_adv)[0])
                act_p += 1.0 if r.home_goals > r.away_goals else (0.5 if r.home_goals == r.away_goals else 0.0)
                gd += r.home_goals - r.away_goals
            for r in ma.itertuples():
                exp_p += 1.0 - float(expected_home(np.array([start[r.home]]), np.array([start[team]]), home_adv)[0])
                act_p += 1.0 if r.away_goals > r.home_goals else (0.5 if r.away_goals == r.home_goals else 0.0)
                gd += r.away_goals - r.home_goals
            rows.append(dict(actual=end[team]-start[team], surprise=act_p-exp_p, gd=gd,
                             uefa=int(mh.kind.eq('uefa').sum()+ma.kind.eq('uefa').sum()),
                             cup=int(mh.kind.eq('cup').sum()+ma.kind.eq('cup').sum()),
                             n=len(mh)+len(ma)))
    return pd.DataFrame(rows)

print(f'{"home_adv":>9s} {"n":>6s} {"K":>6s} {"corr":>7s} {"rmse":>7s}')
best = None
for ha in [0, 20, 40, 50, 60, 65, 70, 80, 100]:
    d = build(ha)
    if len(d) < 50: continue
    k = np.polyfit(d.surprise, d.actual, 1)[0]
    r = d.actual - np.polyval(np.polyfit(d.surprise, d.actual, 1), d.surprise)
    c = d.actual.corr(d.surprise)
    print(f'{ha:9d} {len(d):6d} {k:6.2f} {c:7.4f} {np.sqrt((r**2).mean()):7.3f}')
    if best is None or np.sqrt((r**2).mean()) < best[0]: best = (np.sqrt((r**2).mean()), ha, k, c, d)

rmse, ha, k, c, d = best
print(f'\nBEST: home_adv={ha}  K={k:.2f}  corr={c:.4f}  rmse={rmse:.3f} Elo pts  (n={len(d)})')
print(f'\ndoes goal difference add anything on the clean subset?')
X1 = np.column_stack([np.ones(len(d)), d.surprise])
X2 = np.column_stack([np.ones(len(d)), d.surprise, d.gd])
for nm, X in [('surprise only', X1), ('surprise + gd', X2)]:
    b = np.linalg.lstsq(X, d.actual, rcond=None)[0]
    r = d.actual - X @ b
    print(f'  {nm:16s} rmse {np.sqrt((r**2).mean()):.4f}  R2 {1-r.var()/d.actual.var():.4f}  coefs {np.round(b,3)}')
print(f'\nper-competition K on the clean subset:')
for lbl, mask in [('league only',(d.uefa==0)&(d.cup==0)), ('has UEFA',d.uefa>0), ('has cup',d.cup>0)]:
    s = d[mask]
    if len(s) < 30: continue
    print(f'  {lbl:12s} n={len(s):5d}  K={np.polyfit(s.surprise,s.actual,1)[0]:5.2f}  corr={s.actual.corr(s.surprise):.4f}')
