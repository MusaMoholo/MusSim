"""Does a team's cup/UEFA npxG measure the same team as its league npxG?
If cup line-ups are heavily rotated the answer is partly no, and pooling cup data in would add
matches without adding proportionate information. Test: estimate each team's attack/defence
residual SEPARATELY from league matches and from cup/UEFA matches, then correlate the two.
Benchmark it against the league split-half correlation on the SAME number of matches."""
import sys
from pathlib import Path, os
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from _helpers import to_long, elo_only_expected


# RENAME SHIM: the master table calls the kickoff column `kickoff`; this script was written
# against an earlier frame that called it `date`.
def _shim(df):
    if 'kickoff' in df.columns and 'date' not in df.columns:
        df = df.rename(columns={'kickoff': 'date'})
    return df[df.played] if 'played' in df.columns else df

SP = sys.path[0]
m = _shim(pd.read_pickle(os.environ.get('MATCHES_PKL', str(Path(__file__).resolve().parent.parent / 'data' / 'master_fixtures.pkl'))))
m = m[m.has_npxg & m.elo_ok & (m.season == 2025)].copy()
L = to_long(m)
# one Elo-only expectation fitted across ALL competitions (per-competition baseline via `competition`)
mu_f, _ = elo_only_expected(L, target='npxg')
mu_a, _ = elo_only_expected(L.assign(npxg=L.npxg_conc, team_elo=L.opp_elo,
                                     opp_elo=L.team_elo, is_home=1-L.is_home), target='npxg')
L['rf'] = L.npxg.to_numpy(float)/mu_f
L['ra'] = L.npxg_conc.to_numpy(float)/mu_a

big5 = set(m[m.kind=='league'].home) | set(m[m.kind=='league'].away)
L = L[L.team.isin(big5)]
lg, cp = L[L.kind=='league'], L[L.kind=='cup']

g_l = lg.groupby('team').agg(att_l=('rf','mean'), def_l=('ra','mean'), n_l=('rf','size'))
g_c = cp.groupby('team').agg(att_c=('rf','mean'), def_c=('ra','mean'), n_c=('rf','size'))
j = g_l.join(g_c, how='inner')
print(f'teams with both: {len(j)}')
for minn in (4, 6, 8, 10):
    s = j[j.n_c >= minn]
    if len(s) < 15: continue
    ra = np.corrcoef(s.att_l, s.att_c)[0,1]
    rd = np.corrcoef(-s.def_l, -s.def_c)[0,1]
    rt = np.corrcoef(s.att_l+s.def_l, s.att_c+s.def_c)[0,1]
    print(f'  cup n>={minn:2d}: {len(s):3d} teams, mean cup matches {s.n_c.mean():4.1f}'
          f' | r(attack) {ra:+.3f}  r(defence) {rd:+.3f}  r(tilt) {rt:+.3f}')

# benchmark: split the LEAGUE matches into a small slice of the same size + the rest
rng = np.random.default_rng(0)
print('\nbenchmark -- same test using two disjoint LEAGUE slices (upper bound on transferability):')
for minn in (4, 6, 8, 10):
    sub = j[j.n_c >= minn]
    if len(sub) < 15: continue
    ras, rds, rts = [], [], []
    for _ in range(120):
        keep = []
        for t, grp in lg[lg.team.isin(sub.index)].groupby('team'):
            k = int(sub.loc[t, 'n_c'])
            idx = rng.permutation(grp.index)
            keep.append(pd.Series(np.where(np.isin(grp.index, idx[:k]), 1, 0), index=grp.index))
        flag = pd.concat(keep)
        a = lg.loc[flag.index[flag==1]].groupby('team').agg(att=('rf','mean'), dfn=('ra','mean'))
        b = lg.loc[flag.index[flag==0]].groupby('team').agg(att=('rf','mean'), dfn=('ra','mean'))
        q = a.join(b, lsuffix='_s', rsuffix='_r', how='inner')
        ras.append(np.corrcoef(q.att_r, q.att_s)[0,1])
        rds.append(np.corrcoef(-q.dfn_r, -q.dfn_s)[0,1])
        rts.append(np.corrcoef(q.att_r+q.dfn_r, q.att_s+q.dfn_s)[0,1])
    print(f'  slice n>={minn:2d}: {len(sub):3d} teams'
          f' | r(attack) {np.mean(ras):+.3f}  r(defence) {np.mean(rds):+.3f}  r(tilt) {np.mean(rts):+.3f}')
