#!/usr/bin/env python3
"""Does carrying the sides we do not see forward make the live season's predictions better?

    .venv/bin/python analysis/unseen_backtest.py               # old vs new, by kind of match
    .venv/bin/python analysis/unseen_backtest.py decompose     # starts alone vs starts + paths
    .venv/bin/python analysis/unseen_backtest.py variance      # is K^2 Var(S) the right step size

A world replaying the played matches is deterministic, so one replay gives the state before every
real match. Each match is scored by the log-loss of its W/D/L under the model's own scoreline
matrix, with the Opta machinery (`scripts/opta_ratings.py`) off and on. Only matches from 23 Aug:
the starts come from the 22 Aug snapshot and a snapshot is used from the day after it is pulled,
so nothing scored was visible to what scored it. The level map and beta ARE fitted on everything
up to today, a mild look-ahead in two parameters, not in any rating.

20 Oct 2026, 472 matches: all -0.017 (se 0.007); league matches with a promoted side -0.072
(0.049); league matches without one -0.0005 (0.001) -- untouched, as designed; UEFA with a side
outside the five leagues -0.055 (0.029); cups -0.008 (0.010). Starts and priors carry most of it;
the paths add -0.005 (0.004) on UEFA after eight weeks of movement. FINDINGS 2d.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.simulate_season as ss  # noqa: E402
import scripts.projection as pj  # noqa: E402
from scripts.backtest_qt import score_matrix  # noqa: E402
from scripts.elo_engine import expected_home  # noqa: E402
from scripts.opta_ratings import FULLY_SEEN, Unseen, load  # noqa: E402

SEASON, FROM = 2026, "2026-08-23"
PROMOTED = {"Le Mans FC", "Málaga CF", "R. Racing Club", "RC Deportivo", "SC Paderborn 07",
            "SV Elversberg"}
ROWS = []
_replay = ss._World.replay


def scored_replay(self, row):
    """Record the state's prediction for a real match, then replay it as usual."""
    self._age(row.home, row.kickoff)
    self._age(row.away, row.kickoff)
    _, _, lh, la = self.rates(row.competition, row.home, row.away)
    ROWS.append((row.competition, row.kind, row.kickoff, row.home, row.away,
                 int(row.home_goals), int(row.away_goals), lh, la))
    _replay(self, row)


def run(engine: pj.Engine, opta: bool, paths: bool = True) -> pd.DataFrame:
    ROWS.clear()
    # the season-start fit: this scores each real match on the state replayed up to it
    prep = engine.prepare(SEASON, opta=opta, from_start=True)
    fx = prep["fixtures"]
    u = pj.unseen_for(prep, fx, pj.coerce_params({"unseen": opta}, SEASON))
    if u is not None and not paths:
        u.anchors, u.calendar = {}, {}
    ss.simulate(fx[fx.played], prep["model"], prep["calib"], prep["elo0"],
                np.random.default_rng(1), master=engine.master, unseen=u, build_knockouts=False)
    d = pd.DataFrame(ROWS, columns=["comp", "kind", "kickoff", "home", "away", "hg", "ag",
                                    "lh", "la"])
    m = score_matrix(d.lh.to_numpy(), d.la.to_numpy(), -0.10)
    ph = np.array([np.tril(x, -1).sum() for x in m])
    pdraw = np.array([np.trace(x) for x in m])
    p = np.where(d.hg > d.ag, ph, np.where(d.hg == d.ag, pdraw, 1 - ph - pdraw))
    d["ll"] = -np.log(np.clip(p, 1e-9, None))
    return d


def compare() -> None:
    engine = pj.Engine()
    old, new = run(engine, False), run(engine, True)
    key = ["kickoff", "home", "away"]
    j = old.merge(new[key + ["ll"]], on=key, suffixes=("_old", "_new"))
    j = j[j.kickoff >= FROM]
    lg = j.comp.isin(FULLY_SEEN)
    watched = set(new[new.comp.isin(FULLY_SEEN)].home) | set(new[new.comp.isin(FULLY_SEEN)].away)
    prom = j.home.isin(PROMOTED) | j.away.isin(PROMOTED)
    groups = {"all": j, "league, a promoted side": j[lg & prom],
              "league, no promoted side": j[lg & ~prom],
              "UEFA, a side outside the five leagues":
                  j[(j.kind == "uefa") & ~(j.home.isin(watched) & j.away.isin(watched))],
              "cups": j[j.kind == "cup"]}
    print(f"{'matches from ' + FROM:40} {'n':>5} {'old':>7} {'new':>7} {'new-old':>8} {'se':>6}")
    for name, g in groups.items():
        dl = g.ll_new - g.ll_old
        se = dl.std(ddof=1) / np.sqrt(len(g)) if len(g) > 1 else float("nan")
        print(f"{name:40} {len(g):5d} {g.ll_old.mean():7.4f} {g.ll_new.mean():7.4f} "
              f"{dl.mean():+8.4f} {se:6.4f}")


def decompose() -> None:
    engine = pj.Engine()
    old, part, full = run(engine, False), run(engine, True, paths=False), run(engine, True)
    key = ["kickoff", "home", "away"]
    j = old.merge(part[key + ["ll"]].rename(columns={"ll": "part"}), on=key).merge(
        full[key + ["ll"]].rename(columns={"ll": "full"}), on=key)
    j = j[(j.kickoff >= FROM) & (j.kind == "uefa")]
    d = j.full - j.part
    print(f"UEFA from {FROM} ({len(j)}): old {j.ll.mean():.4f}, starts and priors only "
          f"{j.part.mean():.4f}, plus Opta paths {j.full.mean():.4f}; the paths add "
          f"{d.mean():+.4f} (se {d.std(ddof=1) / np.sqrt(len(j)):.4f})")


def variance() -> None:
    """Five-league sides from 1 Sep: realised Elo change variance against K^2 Var(S)."""
    engine = pj.Engine()
    prep = engine.prepare(SEASON, from_start=True)
    fx = prep["fixtures"]
    u = Unseen(load(SEASON), None, fx.kickoff.max())
    sides = set(fx[fx.competition.isin(FULLY_SEEN)].home)
    elo, seed = dict(prep["elo0"]), float(np.percentile(list(prep["elo0"].values()), 5))
    pred, moved = dict.fromkeys(sides, 0.0), dict.fromkeys(sides, 0.0)
    for r in fx[fx.played].sort_values("kickoff").itertuples():
        eh, ea = elo.get(r.home, seed), elo.get(r.away, seed)
        e = float(expected_home(np.array([eh]), np.array([ea]),
                                ss.UEFA_HOME_ADV if r.kind == "uefa" else ss.HOME_ADV)[0])
        s = 1.0 if r.home_goals > r.away_goals else (0.5 if r.home_goals == r.away_goals else 0.0)
        d = ss.K_ELO * (s - e)
        v = ss.K_ELO ** 2 * (e * (1 - e) - u.draw0 * np.sqrt(max(1 - (2 * e - 1) ** 2, 0)) / 4)
        if r.kickoff >= pd.Timestamp("2026-09-01"):
            for t, sign in ((r.home, 1), (r.away, -1)):
                if t in sides:
                    pred[t] += v
                    moved[t] += sign * d
        elo[r.home], elo[r.away] = eh + d, ea - d
    p, m = np.array(list(pred.values())), np.array(list(moved.values()))
    print(f"five-league sides ({len(sides)}) from 1 Sep: realised Elo change variance "
          f"{m.var():.0f}, K^2 Var(S) predicts {p.mean():.0f} (ratio {m.var() / p.mean():.2f})")


if __name__ == "__main__":
    ss._World.replay = scored_replay
    {"decompose": decompose, "variance": variance}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", compare)()
