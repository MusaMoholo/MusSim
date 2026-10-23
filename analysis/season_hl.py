"""Does the optimal Q half-life lengthen as training history deepens?
One walk_forward run scores all four test seasons, so this is 6 runs, not 24."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from scripts.backtest_qt import load_master, walk_forward, log_loss

m = load_master(); m = m[m.kind.isin(['league', 'uefa'])]
tf = pd.Timestamp('2022-08-01')
HL = [None, 500, 280, 200, 140, 100, 70]
res = {}
for hl in HL:
    p = walk_forward(m, tf, xi_q=0.0 if hl is None else np.log(2)/hl,
                     xi_t=np.log(2)/1460, lam_q=5.0, lam_t=10.0)
    res[hl] = (log_loss(p), p.season.to_numpy())
seasons = sorted(set(res[HL[0]][1].tolist()))

# training depth per test season
depth = {}
for s in seasons:
    first = m[(m.season == s) & (m.kind == 'league')].kickoff.min()
    depth[s] = int((m.kickoff < first).sum())

print(f'{"hl_Q":>7s} ' + ' '.join(f'{s:>9d}' for s in seasons) + f' {"pooled":>9s}')
for hl in HL:
    v, sv = res[hl]
    row = ' '.join(f'{v[sv==s].mean():9.4f}' for s in seasons)
    print(f'{str(hl):>7s} ' + row + f' {v.mean():9.4f}')
print()
print('best hl_Q per test season, against how much history that season had:')
for s in seasons:
    best = min(HL, key=lambda h: res[h][0][res[h][1] == s].mean())
    print(f'  {s}: best hl_Q = {str(best):>5s}   training fixtures available at season start: {depth[s]:5d}')
