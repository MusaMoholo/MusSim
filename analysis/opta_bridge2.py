"""Opta (0-100, max-normalised) -> ClubElo-equivalent, done three ways and compared.

The metric that matters is NOT the error in a team's rating level: the model consumes
slope*(elo_home - elo_away)/200, so any bias common to both teams cancels. What matters is the
error in the PAIRWISE DIFFERENCE between two teams that could actually play each other.

Route C is the interesting one: it skips ClubElo entirely. We already have per-team Q fitted from
npxG alone (prior switched off), so Opta can be mapped straight onto the model's own units
instead of being converted into Elo and then into Q -- which would compound two errors.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from football_common import canonical_team_name, canonical_elo_team_name
from scripts.attack_defence_qt import fit, NPXG_ELO_SLOPE

BIG5_OPTA = {'Premier League', 'Primera División', 'Serie A', 'Bundesliga', 'Ligue 1'}

# ---- Opta today
r = pd.read_csv('data/team_rankings_history/team_rankings-2026-09-10.csv')
r = r[r.domesticLeagueName.isin(BIG5_OPTA)][['contestantName', 'contestantClubName',
                                             'currentRating', 'domesticLeagueName']]
for c in ['contestantName', 'contestantClubName']:
    r['k_' + c] = r[c].map(canonical_team_name).map(canonical_elo_team_name)

# ---- ClubElo latest
e = pd.read_csv('data/external/elo_ratings.csv'); e['date'] = pd.to_datetime(e['date'])
e = e[e.date == e.date.max()][['club', 'elo']]
m = pd.concat([e.merge(r, left_on='club', right_on='k_contestantName'),
               e.merge(r, left_on='club', right_on='k_contestantClubName')]).drop_duplicates('club')
print(f'matched {len(m)} big-5 clubs')

x = m.currentRating.to_numpy(float); y = m.elo.to_numpy(float)
lg = m.domesticLeagueName.to_numpy()

def pair_err(resid, groups):
    """sd of residual DIFFERENCES within the same league (the quantity the model consumes)."""
    out = []
    for g in np.unique(groups):
        rr = resid[groups == g]
        if len(rr) < 3: continue
        d = rr[:, None] - rr[None, :]
        out.append(d[np.triu_indices(len(rr), 1)])
    return np.concatenate(out).std(ddof=1)

L = pd.get_dummies(lg).to_numpy(float)
routes = {}
A = np.column_stack([np.ones_like(x), x]);            routes['A linear'] = A
A2 = np.column_stack([np.ones_like(x), x, x**2]);     routes['A quadratic'] = A2
A3 = np.column_stack([L, x, x**2]);                   routes['B quad + league intercepts'] = A3
A4 = np.column_stack([L, x, x**2, x**3]);             routes['B cubic + league intercepts'] = A4

print(f"\n{'route':34s} {'level err':>10s} {'PAIR err':>10s}")
for name, X in routes.items():
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    res = y - X @ b
    print(f'{name:34s} {res.std(ddof=X.shape[1]):10.0f} {pair_err(res, lg):10.0f}')

# ---- rank-percentile mapping, within league (respects Opta's non-linearity by construction)
res_rank = np.full(len(x), np.nan)
for g in np.unique(lg):
    i = np.where(lg == g)[0]
    oi = np.argsort(np.argsort(x[i]))          # Opta rank within league
    ei = np.sort(y[i])                          # ClubElo values sorted
    res_rank[i] = y[i] - ei[oi]                 # residual of rank-matched prediction
print(f"{'C rank-percentile within league':34s} {np.nanstd(res_rank, ddof=1):10.0f} "
      f"{pair_err(res_rank, lg):10.0f}")

print(f"\nfor scale: within-league Elo DIFFERENCE sd = {pair_err(y - y.mean(), lg):.0f}")

# ---- Route D: Opta -> the model's own Q units, skipping ClubElo
mf = pd.read_pickle('data/master_fixtures.pkl')
tr = mf[mf.played & mf.has_npxg & mf.kind.isin(['league', 'uefa'])]
asof = tr.kickoff.max() + pd.Timedelta(days=1)
pure = fit(tr, asof, xi_q=np.log(2)/140, xi_t=np.log(2)/1460, lam_q=0.02, lam_t=10.0)
qdf = pd.DataFrame({'club': list(pure['Q']), 'Q_npxg': list(pure['Q'].values())})
qm = qdf.merge(m[['club', 'currentRating', 'domesticLeagueName']], on='club')
print(f'\nRoute D: Opta -> model Q directly (prior switched off, Q from npxG alone)')
print(f'  {len(qm)} clubs with both a pure-npxG Q and an Opta rating')
xo = qm.currentRating.to_numpy(float); q = qm.Q_npxg.to_numpy(float)
XD = np.column_stack([np.ones_like(xo), xo, xo**2])
bD = np.linalg.lstsq(XD, q, rcond=None)[0]
rD = q - XD @ bD
print(f'  corr(Opta, pure-npxG Q) = {np.corrcoef(xo, q)[0,1]:.3f}')
print(f'  residual sd in Q units  = {rD.std(ddof=3):.3f}   (sd of Q itself {q.std():.3f})')
print(f'  pair err in Q units     = {pair_err(rD, qm.domesticLeagueName.to_numpy()):.3f}')
print(f'\n  compare: going via ClubElo, a {pair_err(y - np.column_stack([L,x,x**2]) @ np.linalg.lstsq(np.column_stack([L,x,x**2]),y,rcond=None)[0], lg):.0f}-pt pair error'
      f' = {NPXG_ELO_SLOPE*pair_err(y - np.column_stack([L,x,x**2]) @ np.linalg.lstsq(np.column_stack([L,x,x**2]),y,rcond=None)[0], lg)/200:.3f} in Q units')
