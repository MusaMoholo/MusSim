"""Fill a default rating for unrated opponents instead of skipping them, so every match counts.
(Forward-looking, those blanks get filled from Opta anyway, so this matches production.)
Then ask why UEFA and cup fortnights still fit worse than league-only ones."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from scripts.elo_engine import load_snapshots, load_fixtures, expected_home

snaps = load_snapshots(); fx = load_fixtures()
fx = fx[fx.season.isin([2025])]
dates = [d for d in snaps.index if fx.kickoff.min() <= d <= fx.kickoff.max()]
HOME_ADV = 70.0

def build(default_elo):
    rows = []
    for t0, t1 in zip(dates[:-1], dates[1:]):
        start, end = snaps.loc[t0].dropna(), snaps.loc[t1].dropna()
        bt = fx[(fx.kickoff > t0) & (fx.kickoff <= t1)]
        if bt.empty: continue
        for team in set(start.index) & set(end.index):
            mh = bt[bt.home == team]; ma = bt[bt.away == team]
            if len(mh)+len(ma) == 0: continue
            exp_p = act_p = 0.0; gd = 0.0; nfill = 0
            ok = True
            for r in mh.itertuples():
                if not np.isfinite(r.home_goals): ok = False; break
                e = start.get(r.away, np.nan)
                if not np.isfinite(e): e = default_elo; nfill += 1
                exp_p += float(expected_home(np.array([start[team]]), np.array([e]), HOME_ADV)[0])
                act_p += 1.0 if r.home_goals>r.away_goals else (0.5 if r.home_goals==r.away_goals else 0.0)
                gd += r.home_goals - r.away_goals
            if not ok: continue
            for r in ma.itertuples():
                if not np.isfinite(r.away_goals): ok = False; break
                e = start.get(r.home, np.nan)
                if not np.isfinite(e): e = default_elo; nfill += 1
                exp_p += 1.0 - float(expected_home(np.array([e]), np.array([start[team]]), HOME_ADV)[0])
                act_p += 1.0 if r.away_goals>r.home_goals else (0.5 if r.away_goals==r.home_goals else 0.0)
                gd += r.away_goals - r.home_goals
            if not ok: continue
            rows.append(dict(actual=end[team]-start[team], surprise=act_p-exp_p, gd=gd, nfill=nfill,
                             uefa=int(mh.kind.eq('uefa').sum()+ma.kind.eq('uefa').sum()),
                             cup=int(mh.kind.eq('cup').sum()+ma.kind.eq('cup').sum()),
                             n=len(mh)+len(ma)))
    return pd.DataFrame(rows)

rated = snaps.loc[dates[0]].dropna()
print(f'ClubElo distribution at window start: p5={np.percentile(rated,5):.0f} '
      f'median={np.median(rated):.0f} min={rated.min():.0f}')
print(f'\n{"default":>9s} {"n":>6s} {"K":>6s} {"corr":>7s} {"rmse":>7s}')
best=None
for dflt in [1200, 1300, 1400, 1450, 1500, 1600]:
    d = build(dflt)
    k = np.polyfit(d.surprise, d.actual, 1)[0]
    r = d.actual - np.polyval(np.polyfit(d.surprise,d.actual,1), d.surprise)
    print(f'{dflt:9d} {len(d):6d} {k:6.2f} {d.actual.corr(d.surprise):7.4f} {np.sqrt((r**2).mean()):7.3f}')
    if best is None or np.sqrt((r**2).mean())<best[0]: best=(np.sqrt((r**2).mean()), dflt, d)

rmse, dflt, d = best
print(f'\nBEST default = {dflt}   rmse {rmse:.3f}   n={len(d)}')
print(f'\nper-competition K with defaults filled:')
for lbl, mask in [('league only',(d.uefa==0)&(d.cup==0)), ('has UEFA',d.uefa>0), ('has cup',d.cup>0)]:
    s=d[mask]
    if len(s)<30: continue
    print(f'  {lbl:12s} n={len(s):5d}  K={np.polyfit(s.surprise,s.actual,1)[0]:5.2f}  corr={s.actual.corr(s.surprise):.4f}')
print(f'\nis the remaining UEFA/cup misfit explained by filled ratings?')
for lbl, mask in [('no fills needed', d.nfill==0), ('some fills', d.nfill>0)]:
    s=d[mask]
    if len(s)<30: continue
    print(f'  {lbl:16s} n={len(s):5d}  K={np.polyfit(s.surprise,s.actual,1)[0]:5.2f}  corr={s.actual.corr(s.surprise):.4f}')
print(f'\nCUP fortnights with no fills needed (all opponents genuinely rated):')
s = d[(d.cup>0)&(d.nfill==0)]
if len(s)>=20:
    print(f'  n={len(s)}  K={np.polyfit(s.surprise,s.actual,1)[0]:.2f}  corr={s.actual.corr(s.surprise):.4f}')
