"""Face validity of the attack/defence tilt: does T identify teams we would independently
describe as attack- or defence-built? Reproduces the PSG-vs-Arsenal contrast in FINDINGS.md §2.

    .venv/bin/python analysis/facevalid.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scripts.attack_defence_qt import fit

m = pd.read_pickle(Path(__file__).resolve().parent.parent / 'data' / 'master_fixtures.pkl')
tr = m[m.played & m.has_npxg & m.kind.isin(['league', 'uefa'])]
asof = tr.kickoff.max() + pd.Timedelta(days=1)
mdl = fit(tr, asof, xi_q=np.log(2)/140, xi_t=np.log(2)/1460, lam_q=5.0, lam_t=40.0)

rows = [dict(team=t, Q=mdl['Q'][t], T=mdl['T'][t],
             scores=np.exp(mdl['attack'][t]), concedes=np.exp(-mdl['defence'][t]))
        for t in mdl['teams']]
d = pd.DataFrame(rows)
# restrict to teams with a real sample, so the extremes are not cup minnows
lg = tr[tr.kind == 'league']
n = pd.concat([lg.home, lg.away]).value_counts()
d = d[d.team.map(n).fillna(0) >= 60]
fmt = lambda v: f'{v:+.3f}'
print('T < 0 = defence-tilted;  T > 0 = attack-tilted')
print('scores/concedes are multipliers on what the team\'s QUALITY alone would imply\n')
print('=== most DEFENCE-tilted ===')
print(d.nsmallest(10, 'T').to_string(index=False, float_format=fmt))
print('\n=== most ATTACK-tilted ===')
print(d.nlargest(10, 'T').to_string(index=False, float_format=fmt))
print(f'\nspread: sd(T) = {d["T"].std():.3f}   sd(Q) = {d["Q"].std():.3f}')
print('\nthe headline contrast -- near-identical quality, opposite tilt:')
print(d[d.team.isin(['Arsenal', 'Paris Saint-Germain'])].to_string(index=False, float_format=fmt))
