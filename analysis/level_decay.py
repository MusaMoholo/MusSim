"""Does decaying the competition baseline / home advantage help? And does the minutes
normaliser change anything? Both were just added; neither is assumed to help."""
import sys; sys.path.insert(0,'/Users/moholom/Repos/Football')
from pathlib import Path
import numpy as np, pandas as pd
from scripts.backtest_qt import load_master, walk_forward, log_loss, paired

m = load_master(Path('data/master_fixtures.pkl')); m = m[m.kind.isin(['league','uefa'])]
tf = pd.Timestamp('2022-08-01')
KW = dict(xi_q=np.log(2)/140, xi_t=np.log(2)/1460, lam_q=5.0, lam_t=40.0)
HL = [None, 2920, 1460, 730, 500, 365, 200]
V, S = {}, None
for hl in HL:
    p = walk_forward(m, tf, xi_level=0.0 if hl is None else np.log(2)/hl, **KW)
    V[hl] = log_loss(p); S = p.season.to_numpy()
seasons = sorted(set(S.tolist()))
print(f'{"level half-life":>16s} {"pooled":>8s} ' + ' '.join(f'{s:>7d}' for s in seasons) + f' {"vs none":>18s}')
ref = V[None]
for hl in HL:
    v = V[hl]; d, se, t = paired(v, ref)
    tag = 'none (as before)' if hl is None else f'{hl}d'
    extra = '   (reference)' if hl is None else f' {d:+.5f} ± {se:.5f} t={t:+.2f}'
    print(f'{tag:>16s} {v.mean():8.4f} ' + ' '.join(f'{v[S==s].mean():7.4f}' for s in seasons) + extra)
best = min(HL, key=lambda h: V[h].mean())
print(f'\nbest level half-life: {best}')
