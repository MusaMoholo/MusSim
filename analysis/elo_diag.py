"""Why did the ClubElo rule fit come out degenerate (gd_power=0, competition weight at the floor)?

Rather than guess at a functional form, look at the residual directly: for every club-fortnight,
compare the ACTUAL published Elo change against what a plain Elo rule predicts, then ask what the
residual still correlates with. If it tracks goal difference, GD belongs in the model and the fit
failed for another reason. If it tracks match count, we are missing matches ClubElo can see."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from scripts.elo_engine import load_snapshots, load_fixtures, EloParams, expected_home

snaps = load_snapshots()
fx = load_fixtures()
fx = fx[fx.season.isin([2025])]
dates = [d for d in snaps.index if fx.kickoff.min() <= d <= fx.kickoff.max()]

rows = []
for t0, t1 in zip(dates[:-1], dates[1:]):
    start, end = snaps.loc[t0].dropna(), snaps.loc[t1].dropna()
    between = fx[(fx.kickoff > t0) & (fx.kickoff <= t1)]
    if between.empty: continue
    for team in set(start.index) & set(end.index):
        mh = between[between.home == team]; ma = between[between.away == team]
        n = len(mh) + len(ma)
        if n == 0: continue
        # plain-Elo expectation with no GD term, home_adv 60
        exp_pts, act_pts, gd, ncomp = 0.0, 0.0, 0.0, 0
        for r in mh.itertuples():
            if not np.isfinite(r.home_goals): continue
            e = start.get(r.away, np.nan)
            if not np.isfinite(e): continue
            exp_pts += float(expected_home(np.array([start[team]]), np.array([e]), 60.0)[0])
            act_pts += 1.0 if r.home_goals > r.away_goals else (0.5 if r.home_goals == r.away_goals else 0.0)
            gd += r.home_goals - r.away_goals; ncomp += 1
        for r in ma.itertuples():
            if not np.isfinite(r.home_goals): continue
            e = start.get(r.home, np.nan)
            if not np.isfinite(e): continue
            exp_pts += 1.0 - float(expected_home(np.array([e]), np.array([start[team]]), 60.0)[0])
            act_pts += 1.0 if r.away_goals > r.home_goals else (0.5 if r.away_goals == r.home_goals else 0.0)
            gd += r.away_goals - r.home_goals; ncomp += 1
        if ncomp == 0: continue
        rows.append(dict(team=team, t0=t0, n=ncomp, n_seen=n,
                         actual=end[team] - start[team],
                         surprise=act_pts - exp_pts, gd=gd,
                         uefa=int((mh.kind.eq('uefa').sum() + ma.kind.eq('uefa').sum())),
                         cup=int((mh.kind.eq('cup').sum() + ma.kind.eq('cup').sum()))))
d = pd.DataFrame(rows)
print(f'{len(d)} club-fortnights with at least one match we can see\n')
print(f'corr(actual Elo change, surprise)          = {d.actual.corr(d.surprise):.3f}')
print(f'implied K (regression actual ~ surprise)   = {np.polyfit(d.surprise, d.actual, 1)[0]:.1f}')
resid = d.actual - np.polyval(np.polyfit(d.surprise, d.actual, 1), d.surprise)
print(f'residual sd                                = {resid.std():.2f} Elo pts')
print()
print('what does the RESIDUAL still correlate with?')
for col in ['gd', 'n', 'uefa', 'cup']:
    print(f'  corr(resid, {col:6s}) = {np.corrcoef(resid, d[col])[0,1]:+.3f}')
print()
# does GD add explanatory power beyond win/draw/loss surprise?
X1 = np.column_stack([np.ones(len(d)), d.surprise])
X2 = np.column_stack([np.ones(len(d)), d.surprise, d.gd])
for name, X in [('surprise only', X1), ('surprise + gd', X2)]:
    b = np.linalg.lstsq(X, d.actual, rcond=None)[0]
    r = d.actual - X @ b
    print(f'  {name:16s} rmse {np.sqrt((r**2).mean()):.2f}  R2 {1-r.var()/d.actual.var():.3f}  coefs {np.round(b,2)}')
print()
print('by competition mix (does ClubElo weight UEFA/cup differently?):')
for lbl, mask in [('league only', (d.uefa==0)&(d.cup==0)), ('has UEFA', d.uefa>0), ('has cup', d.cup>0)]:
    s = d[mask]
    if len(s) < 30: continue
    k = np.polyfit(s.surprise, s.actual, 1)[0]
    print(f'  {lbl:12s} n={len(s):5d}  implied K={k:5.1f}  corr={s.actual.corr(s.surprise):.3f}')
