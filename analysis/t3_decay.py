"""TEST 3: measure the decay of per-team attack/defence signal DIRECTLY.
Autocorrelation between non-overlapping blocks of a team's matches, as a function of the
time gap. Model-free: no GLM refit, no log-loss, no shrinkage. r(lag) = reliability * rho(lag)."""
import sys
from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
import numpy as np, pandas as pd
from _helpers import to_long, elo_only_expected


# RENAME SHIM: the master table calls the kickoff column `kickoff`; this script was written
# against an earlier frame that called it `date`.
def _shim(df):
    if 'kickoff' in df.columns and 'date' not in df.columns:
        df = df.rename(columns={'kickoff': 'date'})
    return df[df.played] if 'played' in df.columns else df

SP = str(Path(__file__).resolve().parent)
m = _shim(pd.read_pickle(os.environ.get('MATCHES_PKL', str(Path(__file__).resolve().parent.parent / 'data' / 'master_fixtures.pkl'))))
m = m[(m.kind == 'league') & m.has_npxg & m.elo_ok].copy()
L = to_long(m)

mu_for, info_f = elo_only_expected(L, target='npxg')
flip = L.assign(npxg=L.npxg_conc, team_elo=L.opp_elo, opp_elo=L.team_elo, is_home=1 - L.is_home)
mu_ag, info_a = elo_only_expected(flip, target='npxg')
L['rf'] = L.npxg.to_numpy(float) / mu_for
L['ra'] = L.npxg_conc.to_numpy(float) / mu_ag
L['tilt'] = L.rf + L.ra      # attack resid + conceded resid; high = open/attacking tilt
L['lvl']  = L.rf - L.ra      # overall quality beyond Elo

BLOCK = 6                     # matches per block
L = L.sort_values(['team', 'date']).reset_index(drop=True)
L['bidx'] = L.groupby('team').cumcount() // BLOCK
blocks = L.groupby(['team', 'bidx']).agg(
    date=('date', 'mean'), n=('rf', 'size'),
    att=('rf', 'mean'), dfn=('ra', 'mean'), tilt=('tilt', 'mean'), lvl=('lvl', 'mean'),
).reset_index()
blocks = blocks[blocks.n == BLOCK]
print(f'{len(blocks)} blocks of {BLOCK} matches, {blocks.team.nunique()} teams')

# all ordered pairs of distinct blocks for the same team
pairs = blocks.merge(blocks, on='team', suffixes=('_1', '_2'))
pairs = pairs[pairs.bidx_1 < pairs.bidx_2].copy()
pairs['gap'] = (pairs.date_2 - pairs.date_1).dt.days
print(f'{len(pairs)} same-team block pairs, gap {pairs.gap.min()}-{pairs.gap.max()} days')

EDGES = [0, 45, 90, 150, 250, 400, 600, 900, 1400]
print(f'\n{"gap (days)":>14s} {"n pairs":>8s} {"r_attack":>9s} {"r_defence":>10s} {"r_tilt":>8s} {"r_level":>8s}')
rows = []
for lo, hi in zip(EDGES[:-1], EDGES[1:]):
    s = pairs[(pairs.gap >= lo) & (pairs.gap < hi)]
    if len(s) < 200: continue
    out = {}
    for k, lbl in [('att', 'attack'), ('dfn', 'defence'), ('tilt', 'tilt'), ('lvl', 'level')]:
        out[lbl] = np.corrcoef(s[f'{k}_1'], s[f'{k}_2'])[0, 1]
    rows.append((f'{lo}-{hi}', len(s), s.gap.mean(), out))
    print(f'{lo:6d}-{hi:<6d} {len(s):8d} {out["attack"]:+9.3f} {out["defence"]:+10.3f}'
          f' {out["tilt"]:+8.3f} {out["level"]:+8.3f}')

# reliability ceiling: split-half WITHIN the same block-pair distance ~ 0. Use adjacent-in-time
# random split of each block to estimate r(0).
rng = np.random.default_rng(1)
r0 = {k: [] for k in ('att', 'dfn', 'tilt', 'lvl')}
for _ in range(100):
    h = rng.integers(0, 2, len(L))
    g0 = L[h == 0].groupby(['team', 'bidx']).agg(att=('rf','mean'), dfn=('ra','mean'), tilt=('tilt','mean'), lvl=('lvl','mean'), n=('rf','size'))
    g1 = L[h == 1].groupby(['team', 'bidx']).agg(att=('rf','mean'), dfn=('ra','mean'), tilt=('tilt','mean'), lvl=('lvl','mean'), n=('rf','size'))
    j = g0[g0.n >= 3].join(g1[g1.n >= 3], lsuffix='_0', rsuffix='_1', how='inner')
    for k in r0: r0[k].append(np.corrcoef(j[f'{k}_0'], j[f'{k}_1'])[0, 1])
rel = {k: np.mean(v) for k, v in r0.items()}
print(f'\nwithin-block split-half r(0) (the noise ceiling for a {BLOCK}-match block, 3v3):')
print('   ' + '  '.join(f'{k}={rel[k]:+.3f}' for k in rel))

print(f'\nimplied TRUE autocorrelation rho(gap) = r(gap) / r(0), rescaled to the 3v3 ceiling:')
print(f'{"gap (days)":>14s} {"rho_attack":>11s} {"rho_defence":>12s} {"rho_tilt":>10s} {"rho_level":>10s}')
for lbl, n, gmean, out in rows:
    print(f'{lbl:>14s} {out["attack"]/rel["att"]:+11.3f} {out["defence"]/rel["dfn"]:+12.3f}'
          f' {out["tilt"]/rel["tilt"]:+10.3f} {out["level"]/rel["lvl"]:+10.3f}')
