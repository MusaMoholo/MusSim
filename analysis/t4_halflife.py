"""Fit r(gap) = C*(p + (1-p)*exp(-gap/T)) to the measured block autocorrelation.
C absorbs the (unknown) noise ceiling, so the HALF-LIFE is identified by shape alone."""
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
mu_f, _ = elo_only_expected(L, target='npxg')
mu_a, _ = elo_only_expected(L.assign(npxg=L.npxg_conc, team_elo=L.opp_elo,
                                     opp_elo=L.team_elo, is_home=1-L.is_home), target='npxg')
L['rf'] = L.npxg.to_numpy(float)/mu_f
L['ra'] = L.npxg_conc.to_numpy(float)/mu_a
L['tilt'] = L.rf + L.ra
L = L.sort_values(['team','date']).reset_index(drop=True)

BLOCK = int(os.environ.get('BLOCK', '6'))
L['bidx'] = L.groupby('team').cumcount() // BLOCK
bl = L.groupby(['team','bidx']).agg(date=('date','mean'), n=('rf','size'),
        att=('rf','mean'), dfn=('ra','mean'), tilt=('tilt','mean')).reset_index()
bl = bl[bl.n == BLOCK]
pr = bl.merge(bl, on='team', suffixes=('_1','_2'))
pr = pr[pr.bidx_1 < pr.bidx_2].copy()
pr['gap'] = (pr.date_2 - pr.date_1).dt.days

# fine bins with equal pair counts
NB = int(os.environ.get('NBINS', '14'))
pr['bin'] = pd.qcut(pr.gap, NB, labels=False, duplicates='drop')
pts = {}
for k in ('att','dfn','tilt'):
    rows = []
    for b, s in pr.groupby('bin'):
        rows.append((s.gap.mean(), np.corrcoef(s[f'{k}_1'], s[f'{k}_2'])[0,1], len(s)))
    pts[k] = np.array(rows)

def fit(g, r, w, allow_perm=True):
    best = None
    Ts = np.exp(np.linspace(np.log(30), np.log(6000), 220))
    ps = np.linspace(0, 0.9, 46) if allow_perm else [0.0]
    for T in Ts:
        for p in ps:
            basis = p + (1-p)*np.exp(-g/T)
            C = (w*r*basis).sum()/max((w*basis*basis).sum(), 1e-12)
            ss = (w*(r - C*basis)**2).sum()
            if best is None or ss < best[0]: best = (ss, T, p, C)
    return best

print(f'{"quantity":10s} {"half-life":>12s} {"permanent frac":>15s} {"ceiling C":>10s}   pure-exponential half-life')
for k, lbl in [('att','attack'), ('dfn','defence'), ('tilt','tilt')]:
    g, r, n = pts[k][:,0], pts[k][:,1], pts[k][:,2]
    ss, T, p, C = fit(g, r, n)
    ss0, T0, _, C0 = fit(g, r, n, allow_perm=False)
    print(f'{lbl:10s} {T*np.log(2):9.0f} d {p:15.2f} {C:10.3f}   {T0*np.log(2):.0f} d')

print(f'\nmeasured curve (attack / defence / tilt), {NB} equal-count bins:')
print(f'{"gap(d)":>8s} {"n":>6s} {"r_att":>8s} {"r_dfn":>8s} {"r_tilt":>8s}')
for i in range(len(pts["att"])):
    print(f'{pts["att"][i,0]:8.0f} {int(pts["att"][i,2]):6d} {pts["att"][i,1]:+8.3f}'
          f' {pts["dfn"][i,1]:+8.3f} {pts["tilt"][i,1]:+8.3f}')

# Dixon-Coles reference
for xi in (0.00186, 0.0065, 0.018):
    print(f'\nxi={xi:.5f}  ->  half-life {np.log(2)/xi:.0f} days')
