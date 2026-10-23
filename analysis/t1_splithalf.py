"""TEST 1: is there ANY real per-team attack/defence signal beyond point-in-time Elo?
Split-half reliability. No shrinkage estimator, no SEs, no heterogeneity test."""
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
print(f'league matches with npxg+elo: {len(m)}')
L = to_long(m)
print(f'team-match rows: {len(L)}')

for target, conc in [('npxg', 'npxg_conc'), ('goals', 'goals_conc')]:
    print(f'\n{"="*74}\nTARGET = {target}\n{"="*74}')
    mu_for, info = elo_only_expected(L, target=target)
    mu_ag, _ = elo_only_expected(L.assign(**{target: L[conc], 'team_elo': L.opp_elo,
                                             'opp_elo': L.team_elo, 'is_home': 1 - L.is_home}),
                                 target=target)
    print(f'fitted elo slope ({target}): {info["slope"]:.4f}   (repo pins 0.7420)')
    # residual ratios: >1 means outperformed Elo-implied expectation
    L['_rf'] = L[target].to_numpy(float) / mu_for
    L['_ra'] = L[conc].to_numpy(float) / mu_ag

    rng = np.random.default_rng(0)
    res = {k: [] for k in ('att', 'def', 'tilt', 'sum')}
    NREP = 200
    for rep in range(NREP):
        h = rng.integers(0, 2, len(L))
        rows = []
        for half in (0, 1):
            g = L[h == half].groupby(['team', 'season'])
            agg = pd.DataFrame({'att': g._rf.mean(), 'dfn': g._ra.mean(), 'n': g.size()})
            agg = agg[agg.n >= 6]
            rows.append(agg)
        j = rows[0].join(rows[1], lsuffix='_A', rsuffix='_B', how='inner')
        if len(j) < 20: continue
        # attack: high = good.  defence: low conceded = good, so flip sign
        A_att, B_att = j.att_A, j.att_B
        A_def, B_def = -j.dfn_A, -j.dfn_B
        res['att'].append(np.corrcoef(A_att, B_att)[0, 1])
        res['def'].append(np.corrcoef(A_def, B_def)[0, 1])
        res['tilt'].append(np.corrcoef(A_att - A_def, B_att - B_def)[0, 1])
        res['sum'].append(np.corrcoef(A_att + A_def, B_att + B_def)[0, 1])

    print(f'\nSplit-half correlation over {len(res["att"])} random splits '
          f'({len(j)} team-seasons, ~{L.groupby(["team","season"]).size().median()/2:.0f} matches per half):')
    print(f'{"quantity":10s} {"r(A,B)":>9s} {"sd":>7s}  {"Spearman-Brown (full-sample reliability)":>10s}')
    for k, label in [('att', 'attack'), ('def', 'defence'), ('tilt', 'att-def tilt'), ('sum', 'att+def level')]:
        r = np.array(res[k]); rm = r.mean()
        sb = 2 * rm / (1 + rm)
        print(f'{label:12s} {rm:+9.3f} {r.std():7.3f}   {sb:+.3f}')
