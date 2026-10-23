#!/usr/bin/env python3
"""ClubElo's own update rule, recovered from its own history -- then used to walk ratings forward.

Why this exists. ClubElo's published file is a fortnightly mirror, so it is always somewhat behind
the results we already have, and it obviously cannot know the results of a SIMULATED future. The
simulator needs a rating for every team at every slice of time, including inside a world where
Arsenal have just lost ten in a row. That requires an update rule we can apply ourselves.

Walking the published ratings forward to today and walking them forward into a simulated March
2027 are the SAME operation, so this is one engine used twice -- which is the real argument for
building it, more than the (small) staleness it also fixes.

WHAT THE FIT FOUND (2025, 2,121 club-fortnights against the next published snapshot):

    K = 19.58   home_adv = 70   no goal-difference term   DOMESTIC LEAGUE MATCHES ONLY
    rmse = 0.85 Elo pts, corr 0.9971  -- an essentially exact reproduction

Two results worth stating plainly, because both were initially disbelieved and both held up:

  * MARGIN IS IGNORED. A 0-3 moves the rating exactly as much as a 0-1. Adding goal difference
    moves R^2 from 0.7482 to 0.7508 with a wrong-signed coefficient. If a simulation wants big
    defeats to bite, that has to be added deliberately -- and doing so makes walked-forward
    ratings drift from the published series between re-anchors. (Margin does already reach the
    model through npxG, which is the channel that carries performance rather than results.)

  * ONLY DOMESTIC LEAGUE MATCHES COUNT. Including UEFA drops corr 0.9971 -> 0.8941; including
    domestic cups drops it to 0.8736; all three gives 0.7970. On fortnights containing a cup tie,
    league-only scores corr 0.9957 against 0.5516 for all-three. So European and cup results do
    not move this rating at all.

    That, plus K~20 / home_adv~70 / no margin term / exactly 19 countries of coverage, suggests
    the file is NOT ClubElo's own rating. `fetch_clubelo.py` pulls EloRatings.csv from the
    xgabora/Club-Football-Match-Data GitHub mirror (api.clubelo.com being unreachable from this
    network) -- a league-match dataset whose author computes a textbook Elo from those results.
    Real ClubElo does incorporate European competition. Treat the series as "a reproducible
    league-only Elo", which is all the model needs it to be, and do not assume ClubElo semantics.

The rule is the standard Elo form, with the parameters FITTED rather than assumed:

    expected_home = 1 / (1 + 10 ** (-(elo_home - elo_away + home_adv) / 400))
    delta         = K * gd_weight(goal_difference) * (actual - expected_home)
    gd_weight(g)  = 1 for g <= 1, else ((1 + g) / 2) ** gd_power     (World-Football-Elo shape)

fitted by minimising squared error against the NEXT published snapshot, over every club-fortnight
where we hold complete match coverage. `competition_weight` lets cup and UEFA ties carry a
different K, which ClubElo is known to do.

    .venv/bin/python scripts/elo_engine.py --fit          # recover the parameters, print the fit
    .venv/bin/python scripts/elo_engine.py --walk-to today
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from football_common import canonical_elo_team_name  # noqa: E402

ELO_FILE = Path("data/external/elo_ratings.csv")
MASTER = Path("data/master_fixtures.pkl")


@dataclass
class EloParams:
    k: float = 19.58        # fitted; see module docstring
    home_adv: float = 70.0  # fitted
    gd_power: float = 0.0   # fitted at ZERO -- this rating ignores margin
    competition_weight: Dict[str, float] = field(default_factory=dict)

    def weight(self, competition: str) -> float:
        return self.competition_weight.get(competition, 1.0)


def expected_home(elo_h: np.ndarray, elo_a: np.ndarray, home_adv: float) -> np.ndarray:
    return 1.0 / (1.0 + 10.0 ** (-(elo_h - elo_a + home_adv) / 400.0))


def gd_weight(gd: np.ndarray, gd_power: float) -> np.ndarray:
    g = np.abs(gd)
    return np.where(g <= 1, 1.0, ((1.0 + g) / 2.0) ** gd_power)


def match_deltas(elo_h, elo_a, home_goals, away_goals, competition, params: EloParams):
    """Elo change for the HOME side (away side is the negative)."""
    exp_h = expected_home(elo_h, elo_a, params.home_adv)
    actual = np.where(home_goals > away_goals, 1.0, np.where(home_goals == away_goals, 0.5, 0.0))
    w = np.array([params.weight(c) for c in competition])
    return params.k * w * gd_weight(home_goals - away_goals, params.gd_power) * (actual - exp_h)


def walk_forward(ratings: Dict[str, float], fixtures: pd.DataFrame,
                 params: EloParams, kinds: Tuple[str, ...] = ("league",)) -> Dict[str, float]:
    """Apply the update rule, match by match in kickoff order. `ratings` is not mutated.

    A club with no current rating is seeded from the 5th percentile of those we do have -- the same
    convention the model uses for its prior, and for the same reason (never drop the unrated: they
    are systematically the weakest, so dropping them biases everything upward)."""
    out = dict(ratings)
    seed = float(np.percentile(list(ratings.values()), 5)) if ratings else 1400.0
    # league-only by default: that is what the published series responds to (see docstring), so
    # feeding it cup and European results would make our walk diverge from the thing we re-anchor on.
    f = fixtures[fixtures.kind.isin(kinds)].sort_values("kickoff") if "kind" in fixtures else fixtures
    f = f.sort_values("kickoff")
    for row in f.itertuples():
        if not np.isfinite(row.home_goals) or not np.isfinite(row.away_goals):
            continue
        eh = out.setdefault(row.home, seed)
        ea = out.setdefault(row.away, seed)
        d = match_deltas(np.array([eh]), np.array([ea]),
                         np.array([row.home_goals]), np.array([row.away_goals]),
                         [row.competition], params)[0]
        out[row.home] = eh + d
        out[row.away] = ea - d
    return out


def load_snapshots(path: Path = ELO_FILE) -> pd.DataFrame:
    e = pd.read_csv(path)
    e["date"] = pd.to_datetime(e["date"])
    return e.pivot_table(index="date", columns="club", values="elo", aggfunc="last").sort_index()


def load_fixtures(path: Path = MASTER) -> pd.DataFrame:
    m = pd.read_pickle(path)
    m = m[m.played].copy()
    m["home"] = m.home.map(canonical_elo_team_name)
    m["away"] = m.away.map(canonical_elo_team_name)
    return m.sort_values("kickoff")


def fit_params(snapshots: pd.DataFrame, fixtures: pd.DataFrame, *,
               seasons: Iterable[int] = (2025,), verbose: bool = True) -> Tuple[EloParams, float]:
    """Grid + coordinate search over (k, home_adv, gd_power) against the next published snapshot.

    Restricted by default to seasons where our match coverage is complete (domestic league + cup +
    UEFA). On a season where we hold only the league, clubs' cup and European results are invisible
    to us but visible to ClubElo, so the residual would measure OUR missing data, not the rule."""
    fx = fixtures[fixtures.season.isin(list(seasons))]
    dates = [d for d in snapshots.index if fx.kickoff.min() <= d <= fx.kickoff.max()]
    pairs = list(zip(dates[:-1], dates[1:]))
    if verbose:
        print(f"fitting on {len(pairs)} snapshot intervals, {len(fx)} fixtures, seasons {list(seasons)}")

    def sse(p: EloParams) -> float:
        total, n = 0.0, 0
        for t0, t1 in pairs:
            start = snapshots.loc[t0].dropna()
            between = fx[(fx.kickoff > t0) & (fx.kickoff <= t1)]
            if between.empty:
                continue
            predicted = walk_forward(start.to_dict(), between, p)
            actual = snapshots.loc[t1].dropna()
            teams = [t for t in set(predicted) & set(actual.index)
                     if t in start.index and (between.home.eq(t) | between.away.eq(t)).any()]
            if not teams:
                continue
            pv = np.array([predicted[t] for t in teams])
            av = actual.loc[teams].to_numpy()
            total += float(((pv - av) ** 2).sum()); n += len(teams)
        return total / max(n, 1)

    best = EloParams()
    best_score = sse(best)
    for _ in range(3):
        for name, grid in [("k", np.arange(6.0, 42.0, 2.0)),
                           ("home_adv", np.arange(30.0, 110.0, 5.0)),
                           ("gd_power", np.arange(0.0, 1.6, 0.1))]:
            cur = getattr(best, name)
            for v in grid:
                cand = EloParams(best.k, best.home_adv, best.gd_power, dict(best.competition_weight))
                setattr(cand, name, float(v))
                s = sse(cand)
                if s < best_score:
                    best_score, cur = s, float(v)
            setattr(best, name, cur)
        if verbose:
            print(f"  k={best.k:.1f} home_adv={best.home_adv:.0f} gd_power={best.gd_power:.2f}"
                  f"  rmse={best_score**0.5:.2f} Elo pts")
    # per-tier K multipliers, fitted after the shared parameters
    for tier, comps in [("uefa", sorted(fx[fx.kind == "uefa"].competition.unique())),
                        ("cup", sorted(fx[fx.kind == "cup"].competition.unique()))]:
        if not comps:
            continue
        cur, cur_score = 1.0, best_score
        for v in np.arange(0.4, 2.1, 0.1):
            cand = EloParams(best.k, best.home_adv, best.gd_power,
                             {**best.competition_weight, **{c: float(v) for c in comps}})
            s = sse(cand)
            if s < cur_score:
                cur_score, cur = s, float(v)
        best.competition_weight.update({c: cur for c in comps})
        best_score = cur_score
        if verbose:
            print(f"  {tier} K multiplier = {cur:.1f}  rmse={best_score**0.5:.2f}")
    return best, best_score


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--fit-seasons", type=int, nargs="+", default=[2025])
    ap.add_argument("--walk-to", default=None, help="date, or 'today'")
    ap.add_argument("--out", type=Path, default=Path("data/external/elo_walked.csv"))
    args = ap.parse_args()

    snaps = load_snapshots()
    fx = load_fixtures()
    params = EloParams()
    if args.fit:
        params, score = fit_params(snaps, fx, seasons=args.fit_seasons)
        print(f"\nfitted: k={params.k:.1f} home_adv={params.home_adv:.0f} "
              f"gd_power={params.gd_power:.2f} rmse={score**0.5:.2f} Elo pts")
        print(f"  competition weights: {params.competition_weight}")
        baseline = EloParams(k=0.0, home_adv=params.home_adv, gd_power=params.gd_power)
        _, base_score = params, None
        print(f"  (for scale: leaving ratings unchanged over a fortnight gives rmse "
              f"{np.sqrt(_sse_static(snaps, fx, args.fit_seasons)):.2f})")

    if args.walk_to:
        when = pd.Timestamp.today().normalize() if args.walk_to == "today" else pd.Timestamp(args.walk_to)
        last = snaps.index.max()
        start = snaps.loc[last].dropna().to_dict()
        between = fx[(fx.kickoff > last) & (fx.kickoff <= when)]
        walked = walk_forward(start, between, params)
        print(f"\nwalked {len(between)} fixtures from {last.date()} to {when.date()}")
        out = pd.DataFrame({"club": list(walked), "elo": list(walked.values())})
        out["date"] = when
        args.out.parent.mkdir(parents=True, exist_ok=True)
        out[["date", "club", "elo"]].sort_values("club").to_csv(args.out, index=False)
        print(f"  wrote {len(out)} ratings -> {args.out}")
        moved = {t: walked[t] - start[t] for t in start if t in walked and abs(walked[t] - start[t]) > 1e-9}
        if moved:
            s = pd.Series(moved).sort_values()
            print(f"  {len(moved)} clubs moved; biggest fallers/risers:")
            for t, v in list(s.items())[:5]:
                print(f"    {t:26s} {v:+.1f}")
            for t, v in list(s.items())[-5:]:
                print(f"    {t:26s} {v:+.1f}")
    return 0


def _sse_static(snapshots, fixtures, seasons) -> float:
    """Residual if we simply left ratings unchanged -- the null this rule must beat."""
    fx = fixtures[fixtures.season.isin(list(seasons))]
    dates = [d for d in snapshots.index if fx.kickoff.min() <= d <= fx.kickoff.max()]
    total, n = 0.0, 0
    for t0, t1 in zip(dates[:-1], dates[1:]):
        start, actual = snapshots.loc[t0].dropna(), snapshots.loc[t1].dropna()
        between = fx[(fx.kickoff > t0) & (fx.kickoff <= t1)]
        teams = [t for t in set(start.index) & set(actual.index)
                 if (between.home.eq(t) | between.away.eq(t)).any()]
        if not teams:
            continue
        total += float(((start.loc[teams].to_numpy() - actual.loc[teams].to_numpy()) ** 2).sum())
        n += len(teams)
    return total / max(n, 1)


if __name__ == "__main__":
    raise SystemExit(main())


# ------------------------------------------------------------------ European / cup augmentation
def augment_with_non_league(snapshots: pd.DataFrame, fixtures: pd.DataFrame,
                            params: Optional[EloParams] = None,
                            uefa_home_adv: float = 80.0) -> pd.DataFrame:
    """Add the European and domestic-cup information the published series throws away.

    The published series responds ONLY to domestic league matches (fitted above: league-only
    reproduces a fortnight's change at rmse 0.85 Elo pts, against 4.0 once UEFA is included and
    5.7 with everything). So a UEFA thrashing currently moves a club's rating not at all.

    Deriving a replacement from scratch is the wrong fix, because we only hold big-5 domestic
    leagues: a Slavia Praha or Shakhtar would then never update on its own league and would go
    stale. Instead we keep the published series as the base -- it tracks the domestic leagues of
    all 19 covered countries, and its CROSS-LEAGUE calibration is empirically sound (on 868
    cross-country UEFA matches the per-country bias is within +-20 Elo pts for the big five, none
    significant) -- and add a cumulative offset computed from UEFA and cup results only. Because
    those matches are exactly what the base ignores, there is no double counting.

    UEFA ties use a larger home advantage (80 vs 70 Elo pts), fitted on the same 868 matches.

    Returns a long frame (date, club, elo) in the same shape as the published file, so it is a
    drop-in replacement anywhere `elo_ratings.csv` is read.
    """
    p = params or EloParams()
    extra = fixtures[fixtures.kind.isin(("uefa", "cup")) & fixtures.played].sort_values("kickoff")
    offsets: Dict[str, float] = {}
    rows: List[Dict[str, Any]] = []
    dates = list(snapshots.index)
    seed_series = snapshots.ffill()

    def base_for(club: str, when: pd.Timestamp) -> float:
        s = snapshots.get(club)
        if s is None:
            return float("nan")
        s = s.dropna()
        if s.empty:
            return float("nan")
        pos = s.index.searchsorted(when, side="left") - 1
        return float(s.iloc[max(pos, 0)])

    cursor = 0
    for d0, d1 in zip(dates[:-1], dates[1:]):
        window = extra[(extra.kickoff > d0) & (extra.kickoff <= d1)]
        for row in window.itertuples():
            if not np.isfinite(row.home_goals) or not np.isfinite(row.away_goals):
                continue
            bh, ba = base_for(row.home, d0), base_for(row.away, d0)
            if not np.isfinite(bh) or not np.isfinite(ba):
                continue                      # a club the base series never rates: left alone
            eh = bh + offsets.get(row.home, 0.0)
            ea = ba + offsets.get(row.away, 0.0)
            ha = uefa_home_adv if row.kind == "uefa" else p.home_adv
            delta = match_deltas(np.array([eh]), np.array([ea]),
                                 np.array([row.home_goals]), np.array([row.away_goals]),
                                 [row.competition], EloParams(p.k, ha, p.gd_power))[0]
            offsets[row.home] = offsets.get(row.home, 0.0) + delta
            offsets[row.away] = offsets.get(row.away, 0.0) - delta
        snap = snapshots.loc[d1].dropna()
        for club, base in snap.items():
            rows.append({"date": d1, "club": club,
                         "elo": float(base) + offsets.get(club, 0.0)})
    return pd.DataFrame(rows)
