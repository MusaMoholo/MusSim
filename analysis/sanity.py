"""Limiting-case validation: with BOTH penalties driven to infinity, Q is pinned to the rating
prior and T to zero, so the model must collapse onto a rating-only baseline. If it does not, the
parametrisation (or the Q_prior scale) is wrong. Also checks insensitivity to the prior slope.

    .venv/bin/python analysis/sanity.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scripts.backtest_qt import load_master, walk_forward, log_loss

m = load_master(Path(__file__).resolve().parent.parent / 'data' / 'master_fixtures.pkl')
m = m[m.kind.isin(['league', 'uefa'])]
tf = pd.Timestamp('2022-08-01')

ref = log_loss(walk_forward(m, tf, xi_q=0.0, xi_t=0.0, lam_q=1e9, lam_t=1e9))
print(f'rating-only reference (both penalties infinite): {ref.mean():.4f}\n')
print('prior-slope sweep at the operating point (should be FLAT -- nothing is hand-tuned):')
for slope in [0.45, 0.55, 0.6061, 0.65, 0.75]:
    import scripts.attack_defence_qt as aq
    old = aq.NPXG_ELO_SLOPE
    aq.NPXG_ELO_SLOPE = slope
    v = log_loss(walk_forward(m, tf, xi_q=np.log(2)/140, xi_t=np.log(2)/1460,
                              lam_q=5.0, lam_t=40.0))
    aq.NPXG_ELO_SLOPE = old
    print(f'  slope {slope:.4f}: pooled {v.mean():.4f}')
