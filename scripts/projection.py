#!/usr/bin/env python3
"""Turn N simulated worlds into the distributions a dashboard shows. Shared by the app and the job.

`simulate_season.simulate` gives one world. What anyone actually wants is the DISTRIBUTION over
worlds, and the interesting object is the full team x final-position matrix rather than a mean.
This module owns that aggregation so `scripts/serve.py` (interactive) and `scripts/nightly.py`
(scheduled) cannot drift apart -- a dashboard comparing today's snapshot with last week's is only
meaningful if both were reduced by the same code.

Aggregation is incremental: each world is folded in and dropped, so the world count is bounded by
patience, not memory.

Domestic tables are ordered on points, goal difference, goals for. That is the Premier League
rule; Spain and Italy break ties on head-to-head first, so those two will occasionally disagree by
one place. It moves the position matrix, never the points distribution.
"""
from __future__ import annotations

import sys
import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from football_common import canonical_elo_team_name  # noqa: E402
from scripts.attack_defence_qt import (  # noqa: E402
    fit, fit_goal_calibration, fit_goal_layer, predict_npxg,
)
from scripts.cup_bracket import CUP_RULES, cup_handovers  # noqa: E402
from scripts.opta_ratings import Unseen, build as build_opta, OPTA_DIR  # noqa: E402
from scripts.simulate_season import (  # noqa: E402
    DEFAULT_GAIN, DEFAULT_HALF_LIFE, DEFAULT_START_NOISE, ELO_TO_Q, MATCH_DRAW, STATE_COLS,
    elo_walk, simulate, uefa_handovers,
)
from scripts.uefa_bracket import STAGE_ORDER, redraw_handover  # noqa: E402

from scripts.rating_priors import starting_ratings

HL_Q, HL_T, LAM_Q, LAM_T = 140.0, 1460.0, 5.0, 40.0    # the fitted hyperparameters, FINDINGS 2
MASTER = ROOT / "data/master_fixtures.pkl"
ELO_CSV = ROOT / "data/external/elo_ratings.csv"

MIN_MATCHUP = 30       # below this many occurrences a drawn tie's distribution is not worth showing
MATCH_ROUNDS = 2       # rounds of per-match detail to keep, per competition, AT LEAST
# Two, not one, because a "round" empties gradually. The next round is the round of the EARLIEST
# unplayed fixture, so once a league round is part-played it contains only its own leftovers --
# and every side that already played it has no upcoming fixture in the payload at all. Measured on
# a Sunday with the Premier League 7/10 through a round: one round covers 6 of 20 teams, two cover
# 20 of 20, and the same held for all five leagues. The app shows each team's EARLIEST fixture, so
# the second round only fills the gaps; it never changes what an already-covered team displays.
# Cost is 125 -> 226 fixtures a night.
#
# Two is a floor, not a count: a postponed game is a one-match "round" that can sit at the bottom
# of the table for weeks, so `next_round_fixtures` keeps taking rounds until every side has one.
NULL_ROUND_DAYS = 14   # for fixtures with no round number (cups), the window that counts as "next"


def upcoming(fixtures: pd.DataFrame) -> pd.Series:
    """Unplayed fixtures that have a date to be played on.

    An abandoned match awaiting a new date is unplayed but not upcoming: it kicked off, stopped,
    and is owed on a date nobody has set. The simulator still plays it, since the season is a
    fixture short without it, but it is nobody's NEXT match. Counted as one, Rayo v Athletic
    (abandoned 10 Oct 2026) was La Liga's earliest unplayed fixture for as long as it went
    unrescheduled, and so defined both the next round and the horizon below.
    """
    mask = ~fixtures.played
    if "outcome" in fixtures:
        mask &= ~fixtures.outcome.eq("aborted")
    return mask


def next_round_fixtures(fixtures: pd.DataFrame, rounds: int = MATCH_ROUNDS) -> pd.Index:
    """The row labels worth keeping a per-match distribution for: the next rounds per competition.

    Not every fixture. A scoreline distribution for a match in April is dominated by four months
    of strength movement, so it says almost nothing about the match and costs 900 KB a night to
    store. The next round says something you can act on, and it is 30 KB.

    Rounds are taken in order from the lowest upcoming one, and all upcoming fixtures carrying a
    round come with it -- a league round spread over Friday to Monday stays whole. At least
    `rounds` of them, and then as many more as it takes for every side to have a fixture: on
    20 Oct 2026 La Liga's two lowest were a lone postponed round-6 game and the abandoned round-8
    one, and 17 of 20 sides had no next fixture at all. Placeholder slots ("Winner EF1") are not
    sides, so they never count towards that. Cup fixtures with no round number are taken by a
    date window instead.
    """
    keep: List[Any] = []
    for _, g in fixtures[upcoming(fixtures)].groupby("competition"):
        g = g.sort_values("kickoff")
        numbered = g[g["round"].notna()]
        if len(numbered):
            real = numbered[~numbered["tbd"]] if "tbd" in numbered else numbered
            sides, seen, wanted = set(real.home) | set(real.away), set(), []
            for r, rows in numbered.groupby("round", sort=True):
                if len(wanted) >= rounds and seen >= sides:
                    break
                wanted.append(r)
                seen |= set(rows.home) | set(rows.away)
            keep += list(numbered[numbered["round"].isin(wanted)].index)
        undated = g[g["round"].isna()]
        if len(undated):
            cutoff = undated.kickoff.min() + pd.Timedelta(days=NULL_ROUND_DAYS)
            keep += list(undated[undated.kickoff <= cutoff].index)
    return pd.Index(keep)


def tracked_fixtures(fixtures: pd.DataFrame, rounds: int = MATCH_ROUNDS
                     ) -> Tuple[pd.Index, set]:
    """Every fixture worth a per-match distribution, and which of them are the next rounds.

    The next rounds of every competition are what `matches.json` carries, as before. On top of
    them goes EVERY upcoming league fixture, for the Gameweek view (`gw_payload`): a GW30 match
    pooled over the worlds integrates over every path each side can take to get there, which is
    what makes a distribution that far out worth having rather than noise.
    """
    nxt = next_round_fixtures(fixtures, rounds)
    # every unplayed one, an abandoned match awaiting a date included: it is nobody's NEXT
    # fixture, but every world plays it, and its gameweek's table counts it. A UEFA league phase
    # is a 36-team league over six or eight matchdays and gets the same view.
    league = (fixtures.index[((fixtures.kind == "league")
                              | ((fixtures.kind == "uefa") & fixtures["round"].notna()))
                             & ~fixtures.played]
              if "kind" in fixtures else pd.Index([]))
    return nxt.union(league), {int(i) for i in nxt}


DEFAULTS: Dict[str, Any] = {"worlds": 200, "npxg_gain": DEFAULT_GAIN, "drift": 0.0, "seed": 1,
                            "replay_played": True, "elo_feedback": True, "npxg_feedback": True,
                            "tilt_feedback": True, "q_half_life": DEFAULT_HALF_LIFE,
                            "start_noise": DEFAULT_START_NOISE,
                            "unseen": True, "as_of": None, "match_rounds": MATCH_ROUNDS}


HTTP_MAX_WORLDS = 5_000    # a browser request should not be able to occupy the box for an hour


def coerce_params(body: Dict[str, Any], default_season: int,
                  max_worlds: int = HTTP_MAX_WORLDS) -> Dict[str, Any]:
    """Validate a request. `max_worlds` guards the interactive path only -- the scheduled job
    passes its own ceiling, because 10,000 worlds is the whole point of running it overnight."""
    return {"season": int(body.get("season", default_season)),
            "worlds": max(1, min(int(body.get("worlds", DEFAULTS["worlds"])), max_worlds)),
            "match_rounds": max(0, min(int(body.get("match_rounds", MATCH_ROUNDS)), 38)),
            "npxg_gain": float(body.get("npxg_gain", DEFAULTS["npxg_gain"])),
            "drift": max(0.0, float(body.get("drift", DEFAULTS["drift"]))),
            "seed": int(body.get("seed", DEFAULTS["seed"])),
            "replay_played": bool(body.get("replay_played", DEFAULTS["replay_played"])),
            "elo_feedback": bool(body.get("elo_feedback", DEFAULTS["elo_feedback"])),
            "npxg_feedback": bool(body.get("npxg_feedback", DEFAULTS["npxg_feedback"])),
            "tilt_feedback": bool(body.get("tilt_feedback", DEFAULTS["tilt_feedback"])),
            # null/0 turns the decay of in-world strength moves off; see simulate_season
            "q_half_life": _half_life(body.get("q_half_life", DEFAULTS["q_half_life"])),
            # 1 = each world starts from a draw at the fit's posterior SD; 0 = the point estimate
            "start_noise": max(0.0, float(body.get("start_noise", DEFAULTS["start_noise"]))),
            "unseen": bool(body.get("unseen", DEFAULTS["unseen"])),
            "as_of": body.get("as_of") or None}


def _half_life(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "none", "null")):
        return None
    v = float(v)
    return v if v > 0 else None


def unseen_for(prep: Dict[str, Any], fx: pd.DataFrame, params: Dict[str, Any]):
    """The run's view of the sides we do not see every match of, or None to leave them still.

    Built with the run's fit (`Engine.prepare`) because it depends on the cutoff: an Opta
    snapshot after `as_of` is the future to a rewound run, so only the snapshots up to it are
    history -- walked into the start every world is handed -- and the rest are simulated."""
    if not params.get("unseen", True):
        return None
    return prep.get("unseen")


def prepare_for(engine: "Engine", params: Dict[str, Any]) -> Dict[str, Any]:
    """`Engine.prepare` for a run's parameters -- one place, so every caller keys the cache the
    same way and a worker process starts from exactly the fit the parent reports."""
    return engine.prepare(params["season"], opta=params.get("unseen", True),
                          as_of=params.get("as_of"),
                          from_start=not params.get("replay_played", True))


def penalty_xg(train: pd.DataFrame) -> Dict[str, float]:
    """Each competition's penalty xG a side a match (FotMob's xG less npxG), over the matches
    before the cutoff, with "" the mean over all of them. The model never uses xG -- it fits on
    npxG -- so a projected match's xG is its world's drawn npxG plus this one constant, an
    illustration for the Gameweek view's x+/x-, xGD and xG PTS, not a model of who wins penalties.
    Measured over 24,372 side-matches, 2021-2026: 0.1552 penalties a side a match at 0.788 xG
    each; 0.135 a side in cups, 0.154 in leagues, 0.163 in UEFA."""
    if train.empty or "home_xg" not in train:
        return {"": 0.12}
    d = pd.concat([pd.DataFrame({"comp": train.competition, "p": train[f"{s}_xg"] - train[f"{s}_npxg"]})
                   for s in ("home", "away")], ignore_index=True).dropna()
    d = d[d.p > -0.01]
    out = {c: round(float(v), 4) for c, v in d.groupby("comp").p.mean().items()}
    out[""] = round(float(d.p.mean()), 4) if len(d) else 0.12
    return out


def training_rows(master: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Everything the fit may see at `cutoff`: every played match with npxG strictly before it."""
    return master[(master.kickoff < cutoff) & master.played & master.has_npxg]


def fit_model(train: pd.DataFrame, cutoff: pd.Timestamp, art: Optional[Dict[str, Any]],
              elo_now: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """The fit at the published hyperparameters. One call, shared by a run's own fit
    (`Engine.prepare`) and the rating history behind the Gameweek and Visualisations views
    (`rating_history`), so a past round's ratings are made exactly as today's are -- smoke asserts
    the history's refit at a run's cutoff reproduces the run's fit."""
    return fit(train, cutoff, xi_q=np.log(2) / HL_Q, xi_t=np.log(2) / HL_T,
               lam_q=LAM_Q, lam_t=LAM_T, prior=(art or {}).get("start"), elo_now=elo_now)


# --------------------------------------------------------------------------- model cache
class Engine:
    """Loads the master table once and each season's fit on demand."""

    def __init__(self, master_path: Path = MASTER, elo_path: Path = ELO_CSV):
        self.master_path, self.elo_path = Path(master_path), Path(elo_path)
        self._source_stats = {}
        self._opta_cache = {}
        self.master = pd.read_pickle(master_path).sort_values("kickoff").reset_index(drop=True)
        elo = pd.read_csv(elo_path, parse_dates=["date"])
        self._elo = elo.pivot_table(index="date", columns="club", values="elo",
                                    aggfunc="last").sort_index()
        self._cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        self._history: Dict[Tuple[Any, ...], Dict[str, Any]] = {}     # `rating_history`
        self._lock = threading.Lock()

    def fingerprint(self, path):
        path = Path(path)
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        old = self._source_stats.get(path)
        if old is None or old[0] != key:
            self._source_stats[path] = (key, hashlib.sha256(path.read_bytes()).hexdigest())
        return self._source_stats[path][1]

    def refresh_inputs(self):
        refs = (self.fingerprint(self.master_path), self.fingerprint(self.elo_path))
        previous = getattr(self, "_input_refs", None)
        if previous is not None and previous != refs:
            self.master = pd.read_pickle(self.master_path).sort_values("kickoff").reset_index(drop=True)
            elo = pd.read_csv(self.elo_path, parse_dates=["date"])
            self._elo = elo.pivot_table(index="date", columns="club", values="elo", aggfunc="last").sort_index()
            self._cache.clear(); self._history.clear(); self._opta_cache.clear()
        self._input_refs = refs
        return refs

    def opta_references(self, before):
        return tuple((p.name, self.fingerprint(p)) for p in sorted(OPTA_DIR.glob("team_rankings-*.csv"))
                     if before is None or pd.Timestamp(re.search(r"\d{4}-\d{2}-\d{2}", p.name).group()) < before)

    def opta_at(self, season, before):
        refs = self.opta_references(before)
        key = (season, str(before), self.refresh_inputs(), refs)
        if key not in self._opta_cache:
            self._opta_cache[key] = build_opta(self.master, season, elo_csv=self.elo_path,
                                             directory=OPTA_DIR, before=before) if refs else None
            while len(self._opta_cache) > 64:
                self._opta_cache.pop(next(iter(self._opta_cache)))
        return self._opta_cache[key]

    @staticmethod
    def apply_observed_levels(elo, art, assumed):
        """An eligible later level is evidence at this cutoff, never a preseason observation."""
        observed = {}
        if art:
            for team, entry in sorted(art["teams"].items()):
                if team in assumed and entry["path"]:
                    value = round(float(entry["elo"] + entry["path"][-1][1]), 2)
                    elo[team] = value
                    observed[team] = {"elo": value, "date": entry["path"][-1][0],
                                      "basis": "eligible Opta level and movement"}
        return observed

    def seasons(self) -> List[int]:
        return sorted(int(s) for s in self.master.season.unique())

    def live_season(self) -> int:
        """The season currently in progress: the one holding the most recent played fixture.

        NOT "the earliest season with unplayed fixtures" -- old seasons keep a handful of rows
        that were never played and never will be (Spurs v Rennes, cancelled; Spartak Moscow's
        two expelled ties), so that rule
        picks 2021 forever. If the latest played season has nothing left to play, move on to the
        next season that has fixtures -- which is the state during the summer.
        """
        latest = int(self.master[self.master.played].season.max())
        remaining = self.master[(self.master.season == latest) & ~self.master.played]
        if remaining.empty:
            later = [s for s in self.seasons() if s > latest]
            return later[0] if later else latest
        return latest

    def season_meta(self, season: int) -> Dict[str, Any]:
        fx = self.master[self.master.season == season]
        by = fx.groupby("competition").agg(n=("played", "size"), played=("played", "sum"))
        return {"season": season, "fixtures": int(len(fx)), "played": int(fx.played.sum()),
                "first": str(fx.kickoff.min().date()), "last": str(fx.kickoff.max().date()),
                "competitions": [{"competition": c, "fixtures": int(r.n), "played": int(r.played),
                                  "kind": str(fx[fx.competition == c].kind.iloc[0])}
                                 for c, r in by.iterrows()]}

    CACHE_SIZE = 6     # fits are ~1s, but an interactive session flips between a few cutoffs

    def prepare(self, season: int, opta: bool = True, as_of: Optional[str] = None,
                from_start: bool = False) -> Dict[str, Any]:
        """Prepare a fit and rating state at the requested end-of-day cutoff.

        Results and rating observations after the cutoff are excluded, including every Opta
        calibration. Quiet dates keep their own cutoff. Unrated clubs get explicit preseason
        population priors; later eligible observations inform the current cutoff only.
        `from_start` fits before the first fixture for season resampling. The retained fixture
        calendar may include later scheduling revisions; this remains a reconstruction.
        """
        revision = self.refresh_inputs()
        source_before = (pd.Timestamp(as_of) + pd.Timedelta(days=1) if as_of else None)
        opta_refs = self.opta_references(source_before) if opta else ()
        key = (season, bool(opta), as_of or None, bool(from_start), revision, opta_refs)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        fx = self.master[self.master.season == season]
        if fx.empty:
            raise ValueError(f"no fixtures for season {season}")
        if as_of:
            fx = as_of_fixtures(fx, as_of)
        start = fx.kickoff.min()
        done = fx[fx.played & fx.home_goals.notna()]
        cutoff = (start if from_start or done.empty
                  else done.kickoff.max().normalize() + pd.Timedelta(days=1))
        # A quiet matchday is still a dated snapshot: retain all inputs available by its end,
        # rather than silently freezing the fit/ratings at the most recent played fixture.
        if as_of and not from_start:
            cutoff = pd.Timestamp(as_of) + pd.Timedelta(days=1)
        train = training_rows(self.master, cutoff)
        if len(train) < 500:
            raise ValueError(f"season {season} has only {len(train)} training matches before it")
        # Every derived Opta coefficient is rebuilt using eligible observations only.
        art = self.opta_at(season, cutoff) if opta else None
        unseen = Unseen(art, cutoff - pd.Timedelta(days=1), fx.kickoff.max()) if art else None
        rated, priors, provenance = starting_ratings(self.master, fx, self._elo, min(start, cutoff))
        elo_start = {**rated, **priors}
        if cutoff > start:
            elo_now, seed_elo = elo_walk(fx, elo_start, cutoff, unseen)
            live_from: Optional[pd.Timestamp] = cutoff
        else:
            elo_now, seed_elo, live_from = None, None, None
        observed = self.apply_observed_levels(elo_now if elo_now is not None else elo_start,
                                              art, priors)
        model = fit_model(train, cutoff, art, elo_now if elo_now is not None else elo_start)
        mu_h, mu_a = predict_npxg(train, model)
        calib = fit_goal_calibration(train, mu_h, mu_a)
        goals = fit_goal_layer(train, mu_h, mu_a)
        elo0 = elo_now if elo_now is not None else elo_start
        prep = {"fixtures": fx, "model": model, "calib": calib, "goals": goals,
                "places": euro_places(self.master, season),
                # what turns a side's (Q, T) into npxG for and against, on one scale (`npxg_scale`)
                "scale": npxg_scale(model, fx, team_qt(model, elo0, seed_elo)),
                # npxG to xG for a projected match, a competition-wide constant (`penalty_xg`)
                "pen_xg": penalty_xg(train),
                # a mid-season world is handed the ratings AT the cutoff, and the default for a
                # side nobody rates as it was set at the season start
                "elo0": elo0, "seed_elo": seed_elo,
                "elo_start": elo_start,
                "live_from": live_from, "cutoff": cutoff, "unseen": unseen,
                "train": len(train), "elo_teams": len(rated),
                "asof": provenance["elo_date"],
                "rating_inputs": {**provenance, "cutoff": str(cutoff.date()),
                                  "sources": {"master_sha256": revision[0], "elo_sha256": revision[1],
                                              "opta": dict(self.opta_references(cutoff)) if opta else {}},
                                  "opta_dates": art["snapshots"] if art else [],
                                  "observed_at_cutoff": observed,
                                  "reconstruction": "cutoff-filtered inputs; retained fixture calendar"},
                "opta_enabled": bool(opta), "source_key": key,
                # the Opta-built paths and starts for this season, if they have been built
                "opta": art}
        with self._lock:
            self._cache[key] = prep
            while len(self._cache) > self.CACHE_SIZE:
                self._cache.pop(next(iter(self._cache)))
        return prep


# --------------------------------------------------------------------------- aggregation
def final_table(g: pd.DataFrame, teams: pd.Index) -> Dict[str, np.ndarray]:
    """One world's finished league table per team: points, goals, W/D/L, finishing position.

    Everything here except `position` was already being computed to ORDER the table and then
    thrown away. Returning it is what makes the goals and W/D/L distributions free: no second
    pass over the fixtures, no re-simulation, no change to the model.
    """
    h = teams.get_indexer(g.home.to_numpy())
    a = teams.get_indexer(g.away.to_numpy())
    hg = g.home_goals.to_numpy(float)
    ag = g.away_goals.to_numpy(float)
    n = len(teams)
    pts, gf, ga = np.zeros(n), np.zeros(n), np.zeros(n)
    wins, draws, losses = np.zeros(n), np.zeros(n), np.zeros(n)
    home_win, drew, away_win = hg > ag, hg == ag, ag > hg
    np.add.at(pts, h, np.where(home_win, 3.0, np.where(drew, 1.0, 0.0)))
    np.add.at(pts, a, np.where(away_win, 3.0, np.where(drew, 1.0, 0.0)))
    np.add.at(gf, h, hg)
    np.add.at(ga, h, ag)
    np.add.at(gf, a, ag)
    np.add.at(ga, a, hg)
    np.add.at(wins, h, home_win.astype(float))
    np.add.at(wins, a, away_win.astype(float))
    np.add.at(draws, h, drew.astype(float))
    np.add.at(draws, a, drew.astype(float))
    np.add.at(losses, h, away_win.astype(float))
    np.add.at(losses, a, home_win.astype(float))
    order = np.lexsort((teams.to_numpy(str), -gf, -(gf - ga), -pts))  # stable name last
    position = np.empty(n, int)
    position[order] = np.arange(1, n + 1)
    return {"pts": pts, "gd": gf - ga, "gf": gf, "ga": ga,
            "wins": wins, "draws": draws, "losses": losses, "position": position}


def _sample_table(tbl: Dict[str, np.ndarray], teams: pd.Index,
                  places: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """An actual world's table, reusing its already computed totals and official phase seeds."""
    rows = []
    for i, team in enumerate(teams):
        w, d, l = (int(tbl[k][i]) for k in ("wins", "draws", "losses"))
        rows.append({"team": str(team),
                     "pos": int(places[team] if places is not None else tbl["position"][i]),
                     "pl": w + d + l, "w": w, "d": d, "l": l,
                     "gf": int(tbl["gf"][i]), "ga": int(tbl["ga"][i]),
                     "gd": int(tbl["gd"][i]), "pts": int(tbl["pts"][i])})
    return sorted(rows, key=lambda row: (row["pos"], row["team"]))


SAMPLE_WORLDS = 5      # absolute world indices 0..4, independent of process/chunk arrival
MAX_PTS = 130          # 38 matches * 3 = 114; the bound only has to be loose
MAX_GOALS = 200        # a 38-game side has never neared 130 for or against; headroom is free
MAX_MATCHES = 60       # wins / draws / losses over a 38-game season
GD_SPAN = 300          # goal difference is signed, so it carries an offset

# Every league quantity is accumulated the same way: a per-team histogram over integer counts.
# Exact percentiles, memory flat in world count, and two accumulators add by summing arrays --
# which is what lets a run split across processes. Do NOT replace these with per-world samples:
# 100,000 worlds of seven quantities across five leagues would be ~560 MB and merging would cost
# more than the simulation. (key, bins, offset, dashboard label)
# Which quantities ship their full distribution, as opposed to just mean and percentiles. The
# span has to be LEAGUE-wide for a heatmap to share one axis, so a team carries the whole league's
# range: goal difference runs -85..+95, which is 180 bins of which any one team fills ~50. Emitting
# all seven costs 415 KB a snapshot against 60 KB, almost entirely zeros, for views that do not
# exist yet. The accumulator keeps every histogram, so adding one here is a one-line change.
DIST_KEYS = frozenset({"pts"})

# Which quantities ship their full distribution, versus just mean and percentiles. The span has to
# be LEAGUE-wide for a heatmap to share one axis, so every team carries the whole league's range:
# goal difference runs about -85..+95, 180 bins of which one team fills ~50. Emitting all seven
# costs 415 KB a snapshot against 60 KB, nearly all zeros, for views that do not exist yet. The
# accumulator keeps every histogram either way, so promoting one here is a one-line change.
DIST_KEYS = frozenset({"pts"})

LEAGUE_DISTS: Tuple[Tuple[str, int, int, str], ...] = (
    ("pts", MAX_PTS, 0, "Points"),
    ("gd", GD_SPAN, -GD_SPAN // 2, "Goal difference"),
    ("gf", MAX_GOALS, 0, "Goals for"),
    ("ga", MAX_GOALS, 0, "Goals against"),
    ("wins", MAX_MATCHES, 0, "Wins"),
    ("draws", MAX_MATCHES, 0, "Draws"),
    ("losses", MAX_MATCHES, 0, "Losses"),
)
# What rode on a league or league-phase match (`Accumulator._stakes`): the fates each side's
# season is read against, in this order, by the match's result.
STAKES = {"league": ["title", "ucl", "euro", "down"], "uefa": ["top8", "top24", "r16", "win"]}
MAXG = 13              # goal cells per side in a per-match table, matching backtest_qt's MAXG+1
PATH_TOP = 6           # opponents listed per knockout round in a team's path; the rest are pooled
PAYLOAD_VERSION = 15   # cutoff-safe rating inputs and explicit assumed-start provenance
MODEL_GENERATION = "2026-10-23-cutoff"
HAUL_TOP = 8           # trophy combinations listed per team; the rest are pooled
HAUL_MIN = 0.001       # a team expecting fewer trophies than this is pooled into "others": at
                       # 10,000 worlds 400+ amateur sides win the Coupe de France somewhere, and
                       # listing each was 60 KB of every projection.json for 0.13 trophies
PATH_MIN = 0.01        # a knockout round a side plays in fewer worlds than this is left out of its
PATH_MIN_CUP = 0.05    # path. A domestic cup's is higher: the Coupe de France alone is 300+ amateur
                       # sides, most of whom reach the later rounds in a few worlds in a hundred, and
                       # listing them made paths.json 800 KB


def ordinal(k: int) -> str:
    return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def _round_tally(g: pd.DataFrame) -> Dict[str, Any]:
    """The per-round tally behind a Gameweek (league) or Matchday (UEFA league phase) view.

    `gw` sums, over worlds, each side's W, D, L, GF and GA after every round -- index r holds the
    total through round r, index 0 the start -- so a mean table after any round is one division.
    `pl` is the same count of matches, which needs no world: a round is a round in all of them.
    `now` is the real record so far, the same in every world.
    """
    teams = pd.Index(sorted(set(g.home) | set(g.away)))
    nr = g["round"].dropna()
    rounds = int(nr.max()) if len(nr) else 0
    pl = np.zeros((len(teams), rounds + 1), int)
    for r in g[g["round"].notna()].itertuples():
        pl[teams.get_loc(r.home), int(r.round)] += 1
        pl[teams.get_loc(r.away), int(r.round)] += 1
    done = g[g.played & g.home_goals.notna() & g["round"].notna()] if "home_goals" in g \
        else g.iloc[:0]
    now = {t: {"pl": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0} for t in teams}
    for r in done.itertuples():
        for t, f, a in ((r.home, r.home_goals, r.away_goals), (r.away, r.away_goals, r.home_goals)):
            d = now[t]
            d["pl"] += 1
            d["gf"] += int(f)
            d["ga"] += int(a)
            d["w" if f > a else "d" if f == a else "l"] += 1
    for d in now.values():
        d["pts"] = 3 * d["w"] + d["d"]
    return {"teams": teams, "rounds": rounds, "gw": np.zeros((5, len(teams), rounds + 1), float),
            # each side's state going into each round (index r - 1 for round r) and after its
            # last (index `rounds`), summed over the worlds that simulated that match: Elo,
            # ln ATT, ln DEF, then their squares, in RATING_SCALE fixed point; `st_n` counts them
            "st": np.zeros((6, len(teams), rounds + 1), np.int64),
            "st_n": np.zeros((len(teams), rounds + 1), np.int64),
            # xG for, xG against and xG points, run totals after each round like `gw`, in
            # thousandths (fixed point, so the parallel runner stays exact): a played match its
            # real xG, a projected one its world's drawn npxG plus the competition's penalty xG
            "gx": np.zeros((3, len(teams), rounds + 1), np.int64),
            "pl": np.cumsum(pl, axis=1), "now": now,
            "results": _played_rows(done)}


def _played_rows(done: pd.DataFrame) -> List[Dict[str, Any]]:
    """A league's or league phase's played matches for `gw.json`: the result, and where FotMob
    has them each side's xG, npxG and the points its xG would have earned (`xpts`, as
    `real_rates` reckons them) -- the Gameweek view's xG PTS column and the form chart."""
    out = []
    if done.empty:
        return out
    has = {c: c in done for c in ("home_xg", "home_npxg")}
    xh = (done.home_xg.fillna(done.home_npxg) if has["home_xg"] else pd.Series(np.nan, done.index)).to_numpy(float)
    xa = (done.away_xg.fillna(done.away_npxg) if has["home_xg"] else pd.Series(np.nan, done.index)).to_numpy(float)
    ok = np.isfinite(xh) & np.isfinite(xa)
    P = np.full((len(done), 3), np.nan)
    if ok.any():
        from scripts.backtest_qt import outcome_probs
        kind = str(done["kind"].iloc[0]) if "kind" in done else "league"
        P[ok] = outcome_probs(np.clip(xh[ok], 0.01, None), np.clip(xa[ok], 0.01, None),
                              MATCH_DRAW.get(kind, MATCH_DRAW["league"])[2])
    for k, r in enumerate(done.itertuples()):
        row = {"round": int(r.round), "kickoff": str(r.kickoff), "home": r.home, "away": r.away,
               "result": [int(r.home_goals), int(r.away_goals)]}
        if ok[k]:
            row["xg"] = [round(float(xh[k]), 2), round(float(xa[k]), 2)]
            row["xpts"] = [round(float(3 * P[k, 0] + P[k, 1]), 3), round(float(3 * P[k, 2] + P[k, 1]), 3)]
            if has["home_npxg"] and pd.notna(r.home_npxg) and pd.notna(r.away_npxg):
                row["npxg"] = [round(float(r.home_npxg), 2), round(float(r.away_npxg), 2)]
        out.append(row)
    return out


def _blank_team() -> Dict[str, Any]:
    """A fresh per-team record. It MUST be built per call, not copied from a template: `reach` is
    a nested dict, so `{**template}` would hand all 36 teams the same one and every reach count
    would come out 36x too large. `p_win` would still look right, because that one is an int."""
    return {"seed": [], "reach": {k: 0 for k in STAGE_ORDER}, "win": 0}


UEFA_COMPS = (("ucl", "UEFA Champions League"), ("uel", "UEFA Europa League"),
              ("uecl", "UEFA Conference League"))


def euro_places(master: pd.DataFrame, season: int) -> Dict[str, Dict[str, Any]]:
    """Entry policy and explicit EPS assumption; historical prefix allocation before 2024.

    The old entrant walk supplies the last observed EPS assumption. Current-format base entry
    quotas include qualifying rounds and are independent of who survived last season's qualifiers.
    Actual entries are seated per world after domestic and UEFA winners are known. The previous
    contiguous-band counts remain the fallback for seasons before the 2024 format change.
    """
    fx = master[master.season == season]
    prev = master[(master.season == season - 1) & master.played]
    entrants = {k: set() for k, _ in UEFA_COMPS}
    for k, comp in UEFA_COMPS:
        g = fx[(fx.competition == comp) & fx["round"].notna()]
        entrants[k] = set(g.home) | set(g.away)
    out: Dict[str, Dict[str, Any]] = {}
    for comp, g in fx[fx.kind == "league"].groupby("competition"):
        last = prev[prev.competition == comp]
        if last.empty:
            continue
        teams = pd.Index(sorted(set(last.home) | set(last.away)))
        order = list(teams[np.argsort(final_table(last, teams)["position"])])
        counts = {k: 0 for k, _ in UEFA_COMPS}
        for team in order:
            k = next((k for k, _ in UEFA_COMPS if team in entrants[k]), None)
            if k is None:
                break
            counts[k] += 1
        if counts["ucl"]:
            out[comp] = {**counts, "from": int(season - 1)}
    if season >= 2024:
        from scripts.europe_places import qualification_policies
        # Hold the last known EPS allocation explicitly. Phase participants are insufficient to
        # infer base entry quotas: France also has a qualifying place, and cup/UEFA winners move
        # the lower competition counts. Current-format base quotas come from the access list.
        eps = tuple(comp for comp, pl in out.items() if pl["ucl"] > 4)
        policies = qualification_policies(season, eps_leagues=eps)
        for comp, pl in out.items():
            policy = policies.get(comp)
            if policy is None:
                continue
            pl.update(ucl=policy["ucl"] + policy["eps"], uel=policy["uel"],
                      uecl=policy["uecl"])
            pl["qualification"] = {
                "mode": "per_world", "scope": "competition_entry", "season": season + 1,
                "base": {key: policy[key] for key in ("ucl", "uel", "uecl")},
                **{key: policy[key] for key in ("eps", "ucl_direct", "cup", "league_cup")},
                "eps_policy": "previous_allocation"}
    return out


def run_in(prep: Dict[str, Any], fx: pd.DataFrame, n: int = 5) -> Dict[str, Dict[str, Any]]:
    """Each side's next `n` fixtures in its league (or UEFA league phase), each scored by how many
    points an AVERAGE side of that competition would expect from it -- the opponent's strength and
    the venue, on today's fit, nothing of the team's own. One scale for every side in the
    competition, so two run-ins compare directly. Banded at the quintiles of every remaining
    fixture in the competition: 1 very hard .. 5 very easy."""
    model, layer = prep["model"], prep["goals"]
    elo, mean_elo = prep["elo0"], model["elo_mean"]
    from scripts.attack_defence_qt import goal_mean
    from scripts.backtest_qt import score_matrix
    from scripts.simulate_season import ELO_TO_Q, MATCH_DRAW

    def qt(team):
        if team in model["Q"]:
            return model["Q"][team], model["T"][team]
        return ELO_TO_Q * (elo.get(team, prep.get("seed_elo") or mean_elo) - mean_elo), 0.0

    out: Dict[str, Dict[str, Any]] = {}
    groups = [(c, g, "league") for c, g in fx[fx.kind == "league"].groupby("competition")]
    groups += [(c, g, "uefa") for c, g in fx[(fx.kind == "uefa") & fx["round"].notna()]
               .groupby("competition")]
    base_mean = float(np.mean(list(model["base"].values())))
    home_mean = float(np.mean(list(model["home"].values())))
    for comp, g, kind in groups:
        teams = sorted(set(g.home) | set(g.away))
        qa = float(np.mean([qt(t)[0] for t in teams]))
        ta = float(np.mean([qt(t)[1] for t in teams]))
        b = model["base"].get(comp, base_mean)
        hv = model["home"].get(comp, home_mean)
        rho = MATCH_DRAW[kind][2]
        todo = g[upcoming(g)].sort_values("kickoff")

        def avg_xpts(opp: str, home: bool) -> float:
            qo, to = qt(opp)
            mu_f = float(np.exp(b + (hv if home else 0) + (qa + ta) / 2 - (qo - to) / 2))
            mu_a = float(np.exp(b + (0 if home else hv) + (qo + to) / 2 - (qa - ta) / 2))
            lf = float(goal_mean(layer, comp, mu_f, mu_f))
            la = float(goal_mean(layer, comp, mu_a, mu_a))
            M = score_matrix(np.array([lf]), np.array([la]), rho)[0]
            return float(3 * np.tril(M, -1).sum() + np.trace(M))

        rows = []
        for r in todo.itertuples():
            rows.append((r.home, r.away, True, avg_xpts(r.away, True), r.kickoff))
            rows.append((r.away, r.home, False, avg_xpts(r.home, False), r.kickoff))
        if not rows:
            continue
        cuts = [float(x) for x in np.quantile([x[3] for x in rows], [0.2, 0.4, 0.6, 0.8])]
        per: Dict[str, List[Any]] = {}
        for team, opp, home, d, k in rows:
            lst = per.setdefault(team, [])
            if len(lst) < n:
                lst.append([opp, home, round(d, 2), int(np.searchsorted(cuts, d)) + 1,
                            str(pd.Timestamp(k).date())])
        out[comp] = {"cuts": [round(c, 2) for c in cuts], "teams": per}
    return out


# --------------------------------------------------------------------------- ratings
# A side has two numbers worth showing beside a table: its RATING (Elo, the results-only walk)
# and its STRENGTH (Q and T, the npxG fit). Q and T are in log-npxG units, which read as nothing,
# so a side's strength is shown as the npxG a match it would make (ATT) and concede (DEF) against
# an average side of the five leagues -- one scale on every tab, so a number means the same on
# the Premier League's table, the Champions League's and the Ratings tab.
ROUND_BODY_DAYS = 4    # a round's fixtures within this many days of its median kickoff are its
                       # body; a game brought forward a fortnight is not when the round started
# How far back a rating's change is measured, counted back from the data cutoff: what has moved
# in the last week or month, not since one fixed date. The season's first league round is the
# last window, kept as one option among them. (key, label, days)
RATING_WINDOWS = (("1w", "1 week", 7), ("1m", "1 month", 30), ("3m", "3 months", 91))
RATING_SCALE = (100, 100_000, 100_000)   # per-world fixed point for Elo, ln ATT, ln DEF -- see
                                         # Accumulator._state_tally


def team_qt(model: Dict[str, Any], elo: Dict[str, float],
            seed_elo: Optional[float]) -> Callable[[str], Tuple[float, float]]:
    """(Q, T) of any side as a world starting today holds it: the fit's, or for a side the fit
    does not rate, its rating's prior with no tilt (`simulate_season._World._state`)."""
    mean = model["elo_mean"]
    seed = (float(seed_elo) if seed_elo is not None
            else float(np.percentile(list(elo.values()), 5)) if elo else mean)

    def qt(team: str) -> Tuple[float, float]:
        if team in model["Q"]:
            return float(model["Q"][team]), float(model["T"][team])
        return ELO_TO_Q * (elo.get(team, seed) - mean), 0.0
    return qt


def npxg_scale(model: Dict[str, Any], fx: pd.DataFrame,
               qt: Callable[[str], Tuple[float, float]], comp: Optional[str] = None) -> Dict[str, Any]:
    """The reference that turns (Q, T) into npxG a match. With a = (Q + T)/2 and d = (Q - T)/2,

        ATT = exp(c + a - d_ref)      the npxG the side makes against the average side
        DEF = exp(c + a_ref - d)      the npxG it concedes to it

    where a_ref, d_ref average the five leagues' sides and c is the five leagues' mean scoring
    level with home and away averaged. A league's own level moves all its sides together, so it is
    left out: ATT says how good an attack is, not how open its league plays. By construction the
    average side has ATT = DEF, and over the reference sides the geometric means of ATT and DEF are
    equal -- smoke asserts it.

    With `comp`, the same against that competition's OWN average side at its own scoring level:
    the npxG the model expects a side to make and concede there against a typical opponent. That
    is the scale a competition's own views read on (the owner's call, 2026-10-21): on the
    five-league one the average Conference League side is NET -0.67 and every club in it reads as
    bad, which says nothing about who is good in the Conference League. Within one competition
    the two scales differ by one factor for ATT and one for DEF (`comp_shift`), so the order of
    ATT and of DEF is the same on both."""
    if comp is None:
        lg = fx[fx.kind == "league"]
        leagues = sorted(lg.competition.unique())
    else:
        # Cup rounds are often null. Their reference is every named participant in the
        # fixture list, including eliminated sides; league/UEFA references keep their own rule.
        lg = fx[(fx.competition == comp)
                & (fx.kind.isin(["league", "cup"]) | fx["round"].notna())]
        leagues = [comp]
    if "tbd" in lg:
        lg = lg[~lg.tbd]
    teams = sorted(set(lg.home) | set(lg.away))
    qs = np.array([qt(t) for t in teams], float).reshape(-1, 2)
    q, t = qs[:, 0], qs[:, 1]
    base = [model["base"][c] for c in leagues if c in model["base"]] or list(model["base"].values())
    home = [model["home"][c] for c in leagues if c in model["home"]] or list(model["home"].values())
    return {"c": float(np.mean(base) + np.mean(home) / 2),
            "a_ref": float(np.mean((q + t) / 2)) if len(q) else 0.0,
            "d_ref": float(np.mean((q - t) / 2)) if len(q) else 0.0,
            "teams": len(teams), "elo_mean": float(model["elo_mean"]),
            "slope": float(model.get("slope", ELO_TO_Q * 200.0))}


def comp_shift(cs: Dict[str, Any], gs: Dict[str, Any]) -> Tuple[float, float]:
    """The log factors taking a five-league ATT and DEF (`gs`) to a competition's own (`cs`), from
    the same fit: ATT_c = ATT * exp(ka), DEF_c = DEF * exp(kd)."""
    return ((cs["c"] - cs["d_ref"]) - (gs["c"] - gs["d_ref"]),
            (cs["c"] + cs["a_ref"]) - (gs["c"] + gs["a_ref"]))


def to_npxg(scale: Dict[str, Any], q, t):
    """(ATT, DEF) for Q and T, scalars or arrays, on `scale` (`npxg_scale`)."""
    q, t = np.asarray(q, float), np.asarray(t, float)
    return (np.exp(scale["c"] + (q + t) / 2 - scale["d_ref"]),
            np.exp(scale["c"] + scale["a_ref"] - (q - t) / 2))


def rated_teams(fx: pd.DataFrame) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Each side's league and UEFA league phase this season, for the sides a table shows."""
    lg = fx[fx.kind == "league"]
    ph = fx[(fx.kind == "uefa") & fx["round"].notna()]
    if "tbd" in fx:
        lg, ph = lg[~lg.tbd], ph[~ph.tbd]
    league = {t: c for c, g in lg.groupby("competition") for t in set(g.home) | set(g.away)}
    uefa = {t: c for c, g in ph.groupby("competition") for t in set(g.home) | set(g.away)}
    return league, uefa


def round_days(fx: pd.DataFrame) -> Dict[str, List[pd.Timestamp]]:
    """When each round of every league and UEFA league phase starts, as the day its body kicks
    off, then the day after its last match for the Final: index r - 1 is going into round r,
    index `rounds` the end, the Gameweek view's own indexing.

    The body, not the first kickoff: a game brought forward or a postponement replayed out of
    order makes the first kickoff a fortnight early (La Liga's round 6 in 2026/27 has one on
    3 September, before round 5), and the ratings going into a round would then predate the
    round before it."""
    out: Dict[str, List[pd.Timestamp]] = {}
    g_all = fx[(fx.kind == "league") | ((fx.kind == "uefa") & fx["round"].notna())]
    if "tbd" in g_all:
        g_all = g_all[~g_all.tbd]
    for comp, g in g_all.groupby("competition"):
        rounds = int(g["round"].max())
        days: List[pd.Timestamp] = []
        for r in range(1, rounds + 1):
            k = g.loc[g["round"] == r, "kickoff"]
            if k.empty:
                days.append(days[-1] if days else g.kickoff.min().normalize())
                continue
            body = k[(k - k.median()).abs() <= pd.Timedelta(days=ROUND_BODY_DAYS)]
            days.append((body if len(body) else k).min().normalize())
        days.append(g.kickoff.max().normalize() + pd.Timedelta(days=1))
        out[comp] = days
    return out


def _ratings_at(model: Dict[str, Any], elo: Dict[str, float], seed_elo: Optional[float],
                fx: pd.DataFrame, teams: List[str], comps: List[str] = ()
                ) -> Tuple[Dict[str, Tuple[float, ...]], Dict[str, Dict[str, Any]]]:
    """{team: (Elo, Q, T, ATT, DEF, Q sd, T sd)} for one fit, ATT and DEF on that fit's
    five-league scale; and the fit's scales, five-league as "_all" and each of `comps`' own."""
    qt = team_qt(model, elo, seed_elo)
    scale = npxg_scale(model, fx, qt)
    scales = {"_all": scale, **{c: npxg_scale(model, fx, qt, c) for c in comps}}
    seed = (float(seed_elo) if seed_elo is not None
            else float(np.percentile(list(elo.values()), 5)) if elo else model["elo_mean"])
    prior_sd = float(model.get("q_sd_prior", 0.0))
    out = {}
    for team in teams:
        q, t = qt(team)
        att, dfn = to_npxg(scale, q, t)
        out[team] = (float(elo.get(team, seed)), q, t, float(att), float(dfn),
                     float(model["q_sd"].get(team, prior_sd)), float(model["t_sd"].get(team, 0.0)))
    return out, scales


def rating_history(engine: "Engine", params: Dict[str, Any]) -> Dict[str, Any]:
    """The real ratings going into every round already started, for the Gameweek and Matchday
    tables and the Visualisations view: the Elo walk to that round's start and the fit through
    the day before it, made by the same `fit_model` as today's, Opta paths cut at that day.

    A world cannot supply these. It starts from today's fit, and a played match is recorded in it,
    not replayed into its state, so no world holds a rating for a round already played. Rounds
    still to come are the worlds' own: `Accumulator` averages each side's state going into each
    of them. The same fits are made at each RATING_WINDOWS day back from the cutoff and at the
    season's first league round, for the changes the Ratings tab and the charts show. About 0.6 s
    a fit and ~25 by October; cached per run key, and the parallel runner makes them while the
    workers simulate."""
    prep = prepare_for(engine, params)
    key = prep["source_key"]
    with engine._lock:
        if key in engine._history:
            return engine._history[key]
    fx, cutoff, art = prep["fixtures"], prep["cutoff"], prep.get("opta")
    days = round_days(fx)
    league, uefa = rated_teams(fx)
    teams = sorted(set(league) | set(uefa))
    lg_days = [ds[0] for c, ds in days.items() if c in set(league.values())]
    start = min(lg_days) if lg_days else None
    # a fixed window reaching back past the first league round would be the season's change plus
    # a preseason no match moved; the season's own window says that, so it is left out
    windows = [(k, label, cutoff - pd.Timedelta(days=n)) for k, label, n in RATING_WINDOWS
               if start is None or cutoff - pd.Timedelta(days=n) > start]
    if start is not None and start < cutoff:
        windows.append(("season", "season", start))
    # Cup scales are display metadata too; rating rows remain league/league-phase sides.
    comps = sorted(set(league.values()) | set(uefa.values())
                   | set(fx.loc[fx.kind == "cup", "competition"]))
    fits, scales = {}, {}
    fits[cutoff], scales[cutoff] = _ratings_at(prep["model"], prep["elo0"], prep["seed_elo"], fx,
                                               teams, comps)
    want = {d for ds in days.values() for d in ds if d < cutoff} | {d for _, _, d in windows}
    for day in sorted(d for d in want if d < cutoff):
        model, elo, seed = fit_through(engine, prep, day)
        fits[day], scales[day] = _ratings_at(model, elo, seed, fx, teams, comps)
    out = {"days": days, "fits": fits, "scales": scales, "cutoff": cutoff, "teams": teams,
           "league": league, "uefa": uefa, "start": start,
           "windows": [w for w in windows if w[2] in fits]}
    with engine._lock:
        engine._history[key] = out
    return out


def fit_through(engine: "Engine", prep: Dict[str, Any], day: pd.Timestamp,
                until: Optional[pd.Timestamp] = None
                ) -> Tuple[Dict[str, Any], Dict[str, float], Optional[float]]:
    """The fit and the Elo ratings as they stood at `day`, on data strictly before it: what a run
    on that morning would have started from. `until` is the last Opta snapshot counted as history
    (default the day before)."""
    fx = prep["fixtures"]
    until = until if until is not None else day - pd.Timedelta(days=1)
    art = engine.opta_at(int(fx.season.iloc[0]), min(day, until + pd.Timedelta(days=1))) if prep.get("opta_enabled") else None
    unseen = Unseen(art, until, fx.kickoff.max()) if art is not None else None
    rated, priors, _ = starting_ratings(engine.master, fx, engine._elo, min(fx.kickoff.min(), day))
    elo, seed = elo_walk(fx, {**rated, **priors}, day, unseen)
    engine.apply_observed_levels(elo, art, priors)
    return fit_model(training_rows(engine.master, day), day, art, elo), elo, seed


def ratings_payload(prep: Dict[str, Any], hist: Dict[str, Any]) -> Dict[str, Any]:
    """Every side in a league or a UEFA league phase: today's Elo, Q, T and their npxG reading,
    and its Elo, ATT and DEF at the start of each window (`RATING_WINDOWS`, then the season) as
    `past` -- the Ratings tab, the team card and the Visualisations view. A window's `date` is the
    last day of data its fit saw, so "since" reads true."""
    now = hist["fits"][hist["cutoff"]]
    wins = hist.get("windows", [])
    rows = []
    for team in hist["teams"]:
        elo, q, t, att, dfn, qsd, tsd = now[team]
        row = {"team": team, "league": hist["league"].get(team), "uefa": hist["uefa"].get(team),
               "elo": round(elo, 1), "q": round(q, 4), "t": round(t, 4),
               "q_sd": round(qsd, 4), "t_sd": round(tsd, 4),
               "att": round(att, 3), "def": round(dfn, 3)}
        row["past"] = {}
        for k, _, day in wins:
            e0, _, _, a0, d0, _, _ = hist["fits"][day][team]
            row["past"][k] = [round(e0, 1), round(a0, 3), round(d0, 3)]
        rows.append(row)
    rows.sort(key=lambda r: (-r["elo"], r["team"]))
    sc = prep["scale"]
    day1 = pd.Timedelta(days=1)
    # ATT and DEF above are on the five-league scale, for comparing across leagues. A competition's
    # own scale is one factor away for each (`comp_shift`), per fit: `rel` holds them, now and at
    # each window's start, so a view of one competition multiplies through
    scales = hist.get("scales") or {}
    rel = {}
    for comp in sorted(c for c in scales.get(hist["cutoff"], {}) if c != "_all"):
        f = {"now": [round(float(np.exp(k)), 6) for k in comp_shift(scales[hist["cutoff"]][comp],
                                                                     scales[hist["cutoff"]]["_all"])]}
        for k, _, day in wins:
            f[k] = [round(float(np.exp(x)), 6) for x in comp_shift(scales[day][comp], scales[day]["_all"])]
        rel[comp] = f
    return {"as_of": str((hist["cutoff"] - day1).date()), "rel": rel,
            "windows": [{"key": k, "label": label, "date": str((day - day1).date())}
                        for k, label, day in wins],
            "scale": {k: round(v, 6) if isinstance(v, float) else v for k, v in sc.items()},
            "teams": rows}


def real_rates(fx: pd.DataFrame, comp: str, kind: str) -> Dict[str, Dict[str, Any]]:
    """Each side's real npxG for and against this season in one competition (a league, or a UEFA
    league phase), and the points its matches' xG would have earned: per match, the chance of
    each result with each side's goals Poisson at its xG (penalties included, since points are),
    Dixon-Coles at the competition's rho. Over the same matches, `pts` is what it really took --
    the gap is finishing and goalkeeping, the luck a table hides.

    `home` / `away` split points, goals and xG by venue (the Stats hub).
    `shots`, `sot`, `bigch`, `corners` (and each `_a`, against) are totals over `n_stats`
    matches, `poss` the mean possession over them: the Stats view and the shot-quality chart.

    And the totals behind the Goals v xG chart, over the same matches: goals for and against
    (`gf`, `ga`), FotMob's xG for and against with penalties (`xg`, `xga`) -- like for like with
    goals, which include them -- and xG on target (`xgot`, `xgota`: the shots' xG after where they
    were placed), with `n_xg` / `n_xgot` the matches each covers. `pens` / `pens_a` count
    penalties taken, read off xG minus npxG, which moves in steps of FotMob's 0.79 a penalty.
    `pen_g` / `pen_g_a` are those penalties scored, for and against, off each match's shot map
    (version 10)."""
    g = fx[(fx.competition == comp) & fx.played & fx.home_goals.notna() & fx["round"].notna()]
    if g.empty:
        return {}
    from scripts.backtest_qt import outcome_probs
    xh = g.home_xg.fillna(g.home_npxg).to_numpy(float)
    xa = g.away_xg.fillna(g.away_npxg).to_numpy(float)
    ok = np.isfinite(xh) & np.isfinite(xa)
    g, xh, xa = g[ok], np.clip(xh[ok], 0.01, None), np.clip(xa[ok], 0.01, None)
    if g.empty:
        return {}
    P = outcome_probs(xh, xa, MATCH_DRAW.get(kind, MATCH_DRAW["league"])[2])
    out: Dict[str, Dict[str, Any]] = {}
    for r, ph, pd_, pa, hx, ax in zip(g.itertuples(), P[:, 0], P[:, 1], P[:, 2], xh, xa):
        hg, ag = int(r.home_goals), int(r.away_goals)
        nh = float(r.home_npxg) if pd.notna(r.home_npxg) else np.nan
        na = float(r.away_npxg) if pd.notna(r.away_npxg) else np.nan
        for team, xpts, pts, nf, nag in ((r.home, 3 * ph + pd_, 3 * (hg > ag) + (hg == ag), nh, na),
                                         (r.away, 3 * pa + pd_, 3 * (ag > hg) + (hg == ag), na, nh)):
            d = out.setdefault(team, {"pl": 0, "pts": 0, "xpts": 0.0, "npxg": 0.0, "npxga": 0.0,
                                      "n_npxg": 0, "gf": 0, "ga": 0, "xg": 0.0, "xga": 0.0,
                                      "xgot": 0.0, "xgota": 0.0, "n_xg": 0, "n_xgot": 0,
                                      "pens": 0, "pens_a": 0, "n_stats": 0, "shots": 0,
                                      "shots_a": 0, "sot": 0, "sot_a": 0, "bigch": 0, "bigch_a": 0,
                                      "corners": 0, "corners_a": 0, "poss": 0.0,
                                      "pen_g": 0, "pen_g_a": 0})
            d["pl"] += 1
            d["pts"] += int(pts)
            d["xpts"] += float(xpts)
            home = team == r.home
            gf_, ga_ = (hg, ag) if home else (ag, hg)
            d["gf"] += gf_
            d["ga"] += ga_
            # the same, split by venue, for the Stats hub's home and away table
            v = d.setdefault("home" if home else "away", {"pl": 0, "pts": 0, "gf": 0, "ga": 0,
                                                           "xg": 0.0, "xga": 0.0, "n_xg": 0})
            v["pl"] += 1
            v["pts"] += int(pts)
            v["gf"] += gf_
            v["ga"] += ga_
            side = ("home", "away") if home else ("away", "home")
            xs = [getattr(r, f"{x}_{k}") for x in side for k in ("xg", "npxg", "xgot")]
            if all(pd.notna(x) for x in xs[0:2] + xs[3:5]):
                d["xg"] += float(xs[0])
                d["xga"] += float(xs[3])
                d["n_xg"] += 1
                v["xg"] += float(xs[0])
                v["xga"] += float(xs[3])
                v["n_xg"] += 1
                d["pens"] += int(round((xs[0] - xs[1]) / 0.785))
                d["pens_a"] += int(round((xs[3] - xs[4]) / 0.785))
                # and of those, the ones scored, off the match's shot map where it has one
                pg = [getattr(r, f"{x}_pen_goals", np.nan) for x in side]
                if all(pd.notna(v) for v in pg):
                    d["pen_g"] += int(pg[0])
                    d["pen_g_a"] += int(pg[1])
            if pd.notna(xs[2]) and pd.notna(xs[5]):
                d["xgot"] += float(xs[2])
                d["xgota"] += float(xs[5])
                d["n_xgot"] += 1
            st = [getattr(r, f"{x}_{k}", np.nan) for x in side
                  for k in ("shots", "sot", "bigch", "corners", "possession")]
            if all(pd.notna(v) for v in st):
                d["n_stats"] += 1
                for k, (mine, theirs) in zip(("shots", "sot", "bigch", "corners"),
                                             zip(st[0:4], st[5:9])):
                    d[k] += int(mine)
                    d[k + "_a"] += int(theirs)
                d["poss"] += float(st[4])
            if np.isfinite(nf) and np.isfinite(nag):
                d["npxg"] += nf
                d["npxga"] += nag
                d["n_npxg"] += 1
    for d in out.values():
        n = max(d.pop("n_npxg"), 1)
        d["npxg"], d["npxga"] = round(d["npxg"] / n, 3), round(d["npxga"] / n, 3)
        d["xpts"] = round(d["xpts"], 2)
        for k in ("xg", "xga", "xgot", "xgota"):
            d[k] = round(d[k], 2)
        d["poss"] = round(d["poss"] / d["n_stats"], 1) if d["n_stats"] else None
        for side in ("home", "away"):
            if side in d:
                d[side]["xg"], d[side]["xga"] = round(d[side]["xg"], 2), round(d[side]["xga"], 2)
    return out


def _merge_pairs(mine: Dict[Tuple[str, str, str], List[int]],
                 other: Dict[Tuple[str, str, str], List[int]]) -> None:
    for key, c in other.items():
        m = mine.get(key)
        if m is None:
            mine[key] = list(c)
        else:
            m[0] += c[0]
            m[1] += c[1]


def _line_rows(lines: Dict[int, np.ndarray], labels: Dict[int, str]) -> List[Dict[str, Any]]:
    """Each points line's mean and 10th / 50th / 90th percentile, over the worlds."""
    out = []
    for k in sorted(lines):
        h = lines[k]
        tot = h.sum()
        if not tot:
            continue
        c = np.cumsum(h) / tot
        out.append({"place": int(k), "label": labels.get(k, ordinal(int(k))),
                    "mean": round(float((h * np.arange(len(h))).sum() / tot), 1),
                    "p10": int(np.searchsorted(c, 0.10)), "p50": int(np.searchsorted(c, 0.50)),
                    "p90": int(np.searchsorted(c, 0.90))})
    return out


def _count_pairs(pairs: Dict[Tuple[str, str, str], List[int]], rep: Dict[str, Any],
                 rounds) -> None:
    """Who met whom in each knockout round of one world's report, and who went through. Both
    sides of a tie are counted, so P(through) over a round's opponents sums to the side's chance
    of going through it -- the identity smoke and render_check assert."""
    for label in rounds:
        won = rep["winners"].get(label, [])
        for k, (a, b) in enumerate(rep["ties"].get(label, [])):
            w = won[k] if k < len(won) else None
            for t, o in ((a, b), (b, a)):
                c = pairs.get((label, t, o))
                if c is None:
                    c = pairs[(label, t, o)] = [0, 0]
                c[0] += 1
                c[1] += int(w == t)


class Accumulator:
    """Folds worlds in one at a time.

    Points are kept as a per-team HISTOGRAM over integer point totals rather than a list of
    samples. Percentiles come out exact either way, but the histogram is O(1) in world count --
    holding 100,000 samples for five leagues would be ~80 MB -- and two accumulators add by
    summing arrays, which is what lets the run split across processes.
    """

    def __init__(self, fixtures: pd.DataFrame, track: Optional[pd.Index] = None,
                 track_stages: Optional[set] = None, next_ids: Optional[set] = None,
                 places: Optional[Dict[str, Dict[str, Any]]] = None,
                 scale: Optional[Dict[str, Any]] = None,
                 pen_xg: Optional[Dict[str, float]] = None,
                 race_competition: Optional[str] = None,
                 route_competition: Optional[str] = None):
        self.track_stages = track_stages if track_stages is not None else set()
        # Explicit competition opt-ins; production runners request only approved EPL contracts.
        self.rivals: Dict[str, Any] = {}
        self.entry_routes: Dict[str, Any] = {}
        if route_competition not in (None,"English Premier League"):
            raise ValueError("Route accounting currently supports English Premier League only")
        if race_competition is not None and race_competition != "English Premier League":
            raise ValueError("Rival accounting currently supports English Premier League only")
        # what turns a world's (Q, T) into ATT and DEF (`npxg_scale`); without it, as in the
        # parallel runner's empty total, nothing is added here and only merged in
        self.scale = scale
        self.pen_xg = pen_xg
        self.leagues: Dict[str, Dict[str, Any]] = {}
        self.uefa: Dict[str, Dict[str, Any]] = {}
        self.cups: Dict[str, Dict[str, Any]] = {}
        self.europe_policy: Dict[str, Dict[str, Any]] = {}
        self.europe_associations: Dict[str, str] = {}
        self.europe_counts: Dict[str, np.ndarray] = {}     # exclusive UCL / UEL / UECL entries
        self.europe_association_totals: Dict[str, np.ndarray] = {}
        # Per-match scoreline tables. A SCHEDULED fixture is the same match in all N worlds, so
        # its 13x13 table is a straight N-sample distribution; `fixture_id` indexes it. A tie the
        # simulator drew is different -- Arsenal v PSG in the final may occur 40 times in 10,000 --
        # so those are pooled by matchup and carry their own occurrence count.
        self.fx_index: Dict[int, int] = {}
        self.fx_meta: List[Dict[str, Any]] = []
        tracked = fixtures.loc[track] if track is not None else fixtures[~fixtures.played]
        for row in tracked.itertuples():
            self.fx_index[int(row.Index)] = len(self.fx_meta)
            self.fx_meta.append({
                "fixture_id": int(row.Index), "competition": row.competition,
                "season": int(row.season), "kind": row.kind,
                "round": None if pd.isna(row.round) else int(row.round),
                "kickoff": str(row.kickoff), "home": row.home, "away": row.away,
                # in the next rounds, so `matches.json`; otherwise a later league fixture kept
                # for the Gameweek view only
                "next": next_ids is None or int(row.Index) in next_ids})
        self.fx_counts = np.zeros((len(self.fx_meta), MAXG, MAXG), np.int32)
        # Per tracked league or league-phase fixture, what rode on it (`_stakes`): how each side's
        # season ended, by this match's result -- [fixture, home win / draw / away win, side,
        # fate], the fates `STAKES` names. (A projected match's xG needs no tally of its own: a
        # side plays once a round, so its step in the x+/x− run totals IS that match's xG.)
        self.fx_stakes = np.zeros((len(self.fx_meta), 3, 2, len(STAKES["league"])), np.int32)
        # Cup rounds have a variable number of later fates. Keep their exact integer counts
        # separately, keyed by tracked fixture slot; keys follow the cup calendar, then Win.
        self.fx_cup_keys: Dict[int, List[str]] = {}
        self.fx_cup_stakes: Dict[int, np.ndarray] = {}
        self._cup_slots = np.asarray([meta["kind"] == "cup" for meta in self.fx_meta], bool)
        # dense id -> slot, -1 for anything untracked. A dict comprehension per world would both
        # be slower and raise on the fixtures we deliberately do not keep detail for.
        top_id = (max(self.fx_index) + 1) if self.fx_index else 1
        self.fx_pos = np.full(top_id, -1, np.int32)
        for fid, pos in self.fx_index.items():
            self.fx_pos[fid] = pos
        self.matchups: Dict[Tuple[str, str, str, str], np.ndarray] = {}
        # How many Champions League places a league has, COUNTED from this season's fixture list
        # rather than hardcoded: the allocation moves with the UEFA coefficient, and England and
        # Spain currently get five while France gets three. Derived, 2026/27 comes out 5/5/4/4/3,
        # which is correct.
        #
        # Caveat: this counts PARTICIPANTS, so a side entering by winning a European trophy
        # inflates it -- 2025/26 England reads 6 because the Europa League winner took an extra
        # place on top of the five league spots. And strictly the current table decides NEXT
        # season's entry, whose allocation is not knowable yet. Good enough to label the column
        # honestly; do not treat it as a rule.
        cl = fixtures[(fixtures.competition == "UEFA Champions League") & fixtures["round"].notna()]
        cl_teams = set(cl.home) | set(cl.away)
        # fixture id -> round, for league and UEFA league-phase fixtures, so a world's rows can be
        # binned by gameweek or matchday
        lg_fx = fixtures[fixtures.kind.isin(["league", "uefa"]) & fixtures["round"].notna()] \
            if "kind" in fixtures else fixtures.iloc[:0]
        self.round_of = np.full((int(lg_fx.index.max()) + 1) if len(lg_fx) else 1, -1, np.int32)
        self.round_of[lg_fx.index.to_numpy(int)] = lg_fx["round"].to_numpy(int)
        # a played match's real xG and xG points, the same in every world: [xg_h, xg_a, xpts_h,
        # xpts_a] by fixture id, as `_played_rows` and `real_rates` reckon them
        self.real_xg = np.full((len(self.round_of), 4), np.nan)
        played = lg_fx[lg_fx.played & lg_fx.home_goals.notna()] if len(lg_fx) else lg_fx
        if len(played) and "home_xg" in played:
            from scripts.backtest_qt import outcome_probs
            xh = played.home_xg.fillna(played.home_npxg).to_numpy(float)
            xa = played.away_xg.fillna(played.away_npxg).to_numpy(float)
            ok = np.isfinite(xh) & np.isfinite(xa)
            ids, kinds = played.index.to_numpy(int)[ok], played.kind.to_numpy()[ok]
            for kind in ("league", "uefa"):
                sel = kinds == kind
                if sel.any():
                    hx, ax = xh[ok][sel], xa[ok][sel]
                    P = outcome_probs(np.clip(hx, 0.01, None), np.clip(ax, 0.01, None),
                                      MATCH_DRAW[kind][2])
                    self.real_xg[ids[sel]] = np.c_[hx, ax, 3 * P[:, 0] + P[:, 1],
                                                   3 * P[:, 2] + P[:, 1]]
        for comp, g in fixtures[fixtures.kind == "league"].groupby("competition"):
            acc: Dict[str, Any] = _round_tally(g)
            teams = acc["teams"]
            # places by league position (`euro_places`); without it, the old count of entrants
            pl = (places or {}).get(comp)
            acc["ucl_spots"] = pl["ucl"] if pl else max(len(set(teams) & cl_teams), 1)
            acc["uel_spots"] = pl["uel"] if pl else 0
            acc["uecl_spots"] = pl["uecl"] if pl else 0
            acc["places_from"] = pl["from"] if pl else None
            qualification = pl.get("qualification") if pl else None
            if qualification and qualification.get("mode") == "per_world":
                acc["qualification"] = dict(qualification)
                self.europe_policy[comp] = {**qualification["base"], **{
                    key: qualification[key] for key in ("eps", "ucl_direct", "cup", "league_cup")}}
                self.europe_association_totals[comp] = np.zeros(3, np.int64)
                for team in teams:
                    self.europe_associations[team] = comp
                    self.europe_counts[team] = np.zeros(3, np.int32)
            acc["pos"] = np.zeros((len(teams), len(teams)), float)
            # the round each world's title and relegation places were decided (`_decided`)
            acc["relegated_n"] = 3 if len(teams) >= 18 else 2
            acc["clinch"] = np.zeros((len(teams), acc["rounds"] + 1), float)
            acc["down"] = np.zeros((len(teams), acc["rounds"] + 1), float)
            for key, width, _, _ in LEAGUE_DISTS:
                acc[key] = np.zeros((len(teams), width), float)
            self.leagues[comp] = acc
            if comp == race_competition:
                from scripts.race_room import RivalTally
                self.rivals[comp] = RivalTally(teams)
            if comp == route_competition:
                if comp not in self.europe_policy:
                    raise ValueError("Routes require supported per-world qualification policy")
                from scripts.race_routes import RouteTally
                self.entry_routes[comp] = RouteTally(teams)
        for comp, policy in self.europe_policy.items():
            cups = [policy["cup"], policy["league_cup"]]
            rows = fixtures[fixtures.competition.isin([cup for cup in cups if cup])]
            for team in set(rows.home) | set(rows.away):
                self.europe_associations.setdefault(team, comp)
        # UEFA league phases: the same tally, plus a points histogram (at most 3 a match) and the
        # goal totals. The finishing PLACE comes from the knockout seeding instead, which applies
        # UEFA's own tiebreakers (`uefa_bracket.league_phase_table`).
        self.phases: Dict[str, Dict[str, Any]] = {}
        for comp, g in fixtures[(fixtures.kind == "uefa") & fixtures["round"].notna()].groupby(
                "competition") if "kind" in fixtures else []:
            acc = _round_tally(g)
            games = int(acc["pl"][:, -1].max()) if acc["pl"].size else 0
            acc["pts"] = np.zeros((len(acc["teams"]), 3 * games + 1), float)
            acc["gd_sum"] = np.zeros(len(acc["teams"]))
            acc["gf_sum"] = np.zeros(len(acc["teams"]))
            self.phases[comp] = acc
        # The points lines -- what it takes. A place is won by beating the side BELOW it, so each
        # line is the points of the first side outside a zone, per world: the runner-up for the
        # title, the first side outside the Champions League places, outside Europe, and the top
        # relegated side for survival; a league phase's 9th and 25th. The champion's own total
        # is not the bar -- Barcelona's 95 says how good Barcelona are, not what winning La Liga
        # takes, which is beating a runner-up on 82.
        for acc in self.leagues.values():
            n = len(acc["teams"])
            rel = 3 if n >= 18 else 2
            u = min(int(acc["ucl_spots"]), n)
            euro = min(u + int(acc.get("uel_spots", 0)) + int(acc.get("uecl_spots", 0)), n)
            acc["line_places"] = sorted({2, u + 1, euro + 1, n - rel + 1})
            acc["lines"] = {k: np.zeros(MAX_PTS, float) for k in acc["line_places"]}
        for acc in self.phases.values():
            acc["line_places"] = [9, 25]
            acc["lines"] = {k: np.zeros(acc["pts"].shape[1], float) for k in acc["line_places"]}
        # fixture id -> the block it is in and its sides' places there, for `_state_tally`
        self._blocks = list(self.leagues.values()) + list(self.phases.values())
        self.fx_block = np.full(len(self.round_of), -1, np.int32)
        self.fx_hi = np.zeros(len(self.round_of), np.int64)
        self.fx_ai = np.zeros(len(self.round_of), np.int64)
        for b, (kind, comp) in enumerate([("league", c) for c in self.leagues]
                                         + [("uefa", c) for c in self.phases]):
            sub = lg_fx[(lg_fx.kind == kind) & (lg_fx.competition == comp)]
            teams = self._blocks[b]["teams"]
            ix = sub.index.to_numpy(int)
            self.fx_block[ix] = b
            self.fx_hi[ix] = teams.get_indexer(sub.home.to_numpy())
            self.fx_ai[ix] = teams.get_indexer(sub.away.to_numpy())
        # Next-round what-if: the same final fates as stakes, for EVERY side in the fixture's
        # competition. Only next=True league/phase fixtures get slots. Padding to the largest
        # field keeps one compact int32 array; the unused team rows stay zero.
        self.whatif_pos = np.full(len(self.fx_meta), -1, np.int32)
        next_slots = [i for i, m in enumerate(self.fx_meta) if m.get("next", True)
                      and (m["kind"] == "league" and m["competition"] in self.leagues
                           or m["kind"] == "uefa" and m["round"] is not None
                           and m["competition"] in self.phases)]
        self.whatif_pos[next_slots] = np.arange(len(next_slots), dtype=np.int32)
        max_teams = max((len(block["teams"]) for block in self._blocks), default=0)
        self.fx_whatif = np.zeros((len(next_slots), 3, max_teams, 4), np.int32)
        # Trophies: per team, how many it wins in a world (a histogram) and which ones (a count
        # per combination). Every competition with a champion awards one trophy per world, so the
        # expected hauls sum to that number exactly -- asserted in smoke.
        self.trophies: Dict[str, np.ndarray] = {}
        self.combos: Dict[Tuple[str, Tuple[str, ...]], int] = {}
        self.decided = 0
        self.goal_hist = np.zeros(16, float)
        self.outcome = np.zeros(3, float)
        self.matches = 0
        self.worlds = 0
        self.samples: Dict[int, Dict[str, Any]] = {}

    def add(self, sim: pd.DataFrame, world_index: Optional[int] = None) -> None:
        # pandas deep-copies a frame's `attrs` into every frame and column derived from it, and a
        # world's carry its whole rating state and every knockout and cup report -- read through
        # them, one column of a league's rows cost 1.8 ms, and the tallies read hundreds a world.
        # So they come off once here, are read from `attrs`, and go back on before returning.
        attrs, sim.attrs = sim.attrs, {}
        try:
            self._add(sim, attrs, world_index)
        finally:
            sim.attrs = attrs

    def _add(self, sim: pd.DataFrame, attrs: Dict[str, Any],
             world_index: Optional[int] = None) -> None:
        # Standalone callers get sequential indices. Runners pass the absolute simulation index,
        # so whichever worker finishes first cannot choose the sample seasons.
        index = self.worlds if world_index is None else int(world_index)
        sample = ({"index": index, "world": index + 1, "leagues": {}, "phases": {},
                   "champions": {}} if 0 <= index < SAMPLE_WORLDS else None)
        phase_tables: Dict[str, Dict[str, np.ndarray]] = {}
        self.worlds += 1
        state = attrs.get("state")
        score90 = attrs.get("score90")
        if score90 is not None and np.asarray(score90).shape != (len(sim), 2):
            raise ValueError("90-minute scores must align with every simulated match row")
        if state is not None and len(state) != len(sim):
            raise ValueError(f"{len(state)} state rows for {len(sim)} match rows: a row was "
                             "recorded without its ratings")
        lg = sim[sim.phase == "league"]
        won: Dict[str, List[str]] = {}          # team -> the competitions it wins in this world
        phase_pts: Dict[str, Dict[str, float]] = {}
        phase_rows: Dict[str, pd.DataFrame] = {}
        league_rows: Dict[str, pd.DataFrame] = {}
        league_tables: Dict[str, Dict[str, np.ndarray]] = {}
        for comp, acc in self.leagues.items():
            g = lg[lg.competition == comp]
            if g.empty:
                continue
            tbl = final_table(g, acc["teams"])
            if comp in self.rivals:
                self.rivals[comp].add(tbl["position"])
            if sample is not None:
                sample["leagues"][comp] = _sample_table(tbl, acc["teams"])
            idx = np.arange(len(acc["teams"]))
            for key, width, offset, _ in LEAGUE_DISTS:
                acc[key][idx, np.clip(tbl[key].astype(int) - offset, 0, width - 1)] += 1
            acc["pos"][idx, tbl["position"] - 1] += 1
            by_place = tbl["pts"][np.argsort(tbl["position"])]
            for k in acc["line_places"]:
                acc["lines"][k][int(by_place[k - 1])] += 1
            won.setdefault(acc["teams"][int(np.argmin(tbl["position"]))], []).append(comp)
            n_t, place, u = len(acc["teams"]), tbl["position"], int(acc["ucl_spots"])
            euro = u + int(acc.get("uel_spots", 0)) + int(acc.get("uecl_spots", 0))
            if comp in self.europe_policy:
                league_rows[comp], league_tables[comp] = g, tbl
            else:
                self._stakes(g, acc["teams"], np.c_[place == 1, place <= u, place <= euro,
                                                  place > n_t - acc["relegated_n"]])
            cum = self._tally(acc, g)
            self._xg_tally(acc, g, comp, "league")
            if cum is not None and acc["rounds"]:
                n = len(acc["teams"])
                self._decided(acc, cum, int(np.argmin(tbl["position"])),
                              np.flatnonzero(tbl["position"] > n - acc["relegated_n"]))
        for comp, acc in self.phases.items():
            g = lg[lg.competition == comp]
            if g.empty:
                continue
            tbl = final_table(g, acc["teams"])
            if sample is not None:
                phase_tables[comp] = tbl
            width = acc["pts"].shape[1]
            acc["pts"][np.arange(len(acc["teams"])),
                       np.clip(tbl["pts"].astype(int), 0, width - 1)] += 1
            acc["gd_sum"] += tbl["gd"]
            acc["gf_sum"] += tbl["gf"]
            phase_pts[comp] = dict(zip(acc["teams"], tbl["pts"]))
            phase_rows[comp] = g
            self._tally(acc, g)
            self._xg_tally(acc, g, comp, "uefa")
        self._state_tally(sim, state)

        for (comp, _), rep in attrs.get("knockout", {}).items():
            acc = self.uefa.setdefault(comp, {"teams": {}, "n": 0, "pairs": {}})
            acc["n"] += 1
            # the points lines, at UEFA's own order: the seeding applies every tiebreaker
            ph = self.phases.get(comp)
            if ph is not None and comp in phase_pts and rep["seeds"]:
                for k in ph["line_places"]:
                    team = rep["seeds"].get(k)
                    if team in phase_pts[comp]:
                        ph["lines"][k][int(phase_pts[comp][team])] += 1
                # what rode on each league-phase match: the place UEFA's seeding gave each side
                seed = {t: k for k, t in rep["seeds"].items()}
                if sample is not None and comp in phase_tables and all(t in seed for t in ph["teams"]):
                    # A phase's finishing order uses UEFA's full tiebreakers, not the domestic
                    # table helper's points/GD/GF order. Its goals and W/D/L totals are shared.
                    sample["phases"][comp] = _sample_table(phase_tables[comp], ph["teams"], seed)
                r16 = {t for tie in rep["ties"].get("R16", []) for t in tie}
                fate = np.array([[seed.get(t, 99) <= 8, seed.get(t, 99) <= 24, t in r16,
                                  t == rep["champion"]] for t in ph["teams"]], np.int32)
                self._stakes(phase_rows[comp], ph["teams"], fate)
            # who met whom in each round, and who went through: a team's knockout PATH. Both
            # sides of a tie are counted, so P(through) over a round's opponents sums to the
            # team's chance of reaching the next round -- asserted in smoke and render_check.
            _count_pairs(acc["pairs"], rep, STAGE_ORDER)
            for seed, team in rep["seeds"].items():
                acc["teams"].setdefault(team, _blank_team())["seed"].append(seed)
            for label in STAGE_ORDER:
                for tie in rep["ties"].get(label, []):
                    for team in tie:
                        acc["teams"].setdefault(team, _blank_team())["reach"][label] += 1
            if rep["champion"]:
                acc["teams"][rep["champion"]]["win"] += 1
                won.setdefault(rep["champion"], []).append(comp)

        cup_rows = self._cup_rows(sim) if attrs.get("cups") else {}
        # Domestic cups. A cup has no table and no seeding, so the only quantity worth counting is
        # how often each team is still in it at each round -- which is exactly the set the runner
        # records. `rounds` is kept in calendar order the first time a competition is seen; every
        # world of a given competition plays the same rounds, because the calendar is derived once
        # at handover and shared, and only the PAIRINGS are redrawn per world.
        for (comp, _), rep in attrs.get("cups", {}).items():
            acc = self.cups.setdefault(comp, {"teams": {}, "n": 0, "rounds": [],
                                              "drawn": [], "et": 0, "pens": 0,
                                              "late": {}, "byes": {}, "pairs": {}})
            acc["n"] += 1
            self._cup_stakes(cup_rows.get(comp, []), comp, rep, score90)
            _count_pairs(acc.setdefault("pairs", {}), rep, rep["reached"])
            if not acc["rounds"]:
                acc["rounds"] = list(rep["reached"])
                acc["drawn"] = list(rep["drawn_rounds"])
                # structural, so the same in every world: who joins where, and how many places
                # in a round go through unplayed
                acc["late"] = dict(rep.get("late", {}))
                acc["byes"] = {k: len(v) for k, v in rep.get("byes", {}).items() if v}
            acc["et"] += rep["extra_times"]
            acc["pens"] += rep["shootouts"]
            for label, teams in rep["reached"].items():
                for team in teams:
                    reach = acc["teams"].setdefault(team, {"reach": {}, "win": 0})["reach"]
                    reach[label] = reach.get(label, 0) + 1
            if rep["champion"]:
                acc["teams"].setdefault(rep["champion"], {"reach": {}, "win": 0})["win"] += 1
                won.setdefault(rep["champion"], []).append(comp)

        if self.europe_policy:
            champions = {comp: team for team, comps in won.items() for comp in comps}
            self._europe(league_rows, league_tables, champions, sample)

        if sample is not None:
            sample["leagues"] = dict(sorted(sample["leagues"].items()))
            sample["phases"] = dict(sorted(sample["phases"].items()))
            sample["champions"] = dict(sorted((comp, str(team)) for team, comps in won.items()
                                                for comp in comps))
            if index in self.samples and self.samples[index] != sample:
                raise ValueError(f"conflicting sample world {index}")
            self.samples[index] = sample

        self.decided += sum(len(v) for v in won.values())
        for team, comps in won.items():
            h = self.trophies.get(team)
            if h is None:
                h = self.trophies[team] = np.zeros(15, float)
            h[min(len(comps), 14)] += 1
            key = (team, tuple(sorted(comps)))
            self.combos[key] = self.combos.get(key, 0) + 1

        s = sim[sim.sampled]
        hg, ag = s.home_goals.to_numpy(int), s.away_goals.to_numpy(int)
        self.goal_hist += np.bincount(np.clip(hg + ag, 0, 15), minlength=16)
        self.outcome += [np.sum(hg > ag), np.sum(hg == ag), np.sum(hg < ag)]
        self.matches += len(s)

        fid = s.fixture_id.to_numpy()
        # Forecast odds and scorelines are over 90 minutes; final goals remain unchanged for
        # season summaries, reports and trophy winners. No draw or feedback is repeated here.
        regulation = np.c_[hg, ag].copy()
        ko = s.phase.to_numpy() == "knockout"
        if ko.any():
            if score90 is None:
                if (s.minutes.to_numpy()[ko] > 90).any():
                    raise ValueError("Sampled extra-time matches need preserved 90-minute scores")
            else:
                values = np.asarray(score90)[sim.sampled.to_numpy()][ko]
                if not np.isfinite(values).all():
                    raise ValueError("Sampled knockout 90-minute scores must be known")
                regulation[ko] = values.astype(int)
        ch, ca = np.clip(regulation[:, 0], 0, MAXG - 1), np.clip(regulation[:, 1], 0, MAXG - 1)
        safe = np.clip(fid, 0, len(self.fx_pos) - 1)
        pos = np.where((fid >= 0) & (fid < len(self.fx_pos)), self.fx_pos[safe], -1)
        tracked = pos >= 0
        if tracked.any():
            np.add.at(self.fx_counts, (pos[tracked], ch[tracked], ca[tracked]), 1)
        drawn = fid < 0
        for row, h, a in zip(s[drawn].itertuples(), ch[drawn], ca[drawn]):
            # only the next pending stage per competition: a quarter-final matchup drawn in a
            # world whose play-off round we also invented is two draws deep and says nothing
            if (row.competition, row.stage) not in self.track_stages:
                continue
            key = (row.competition, row.stage, row.home, row.away)
            tbl = self.matchups.get(key)
            if tbl is None:
                tbl = self.matchups[key] = np.zeros((MAXG, MAXG), np.int32)
            tbl[h, a] += 1

    def _europe(self, rows: Dict[str, pd.DataFrame],
                tables: Dict[str, Dict[str, np.ndarray]], champions: Dict[str, str],
                sample: Optional[Dict[str, Any]]) -> None:
        """Seat this world's winners before counting any league fate or what-if outcome."""
        from scripts.europe_places import seat_world
        orders = {comp: list(self.leagues[comp]["teams"][np.argsort(tbl["position"])])
                  for comp, tbl in tables.items()}
        seats = seat_world(orders, champions, self.europe_policy, self.europe_associations)
        for comp, tally in self.entry_routes.items():
            tally.add(orders[comp], self.europe_policy[comp], champions, seats[comp])
        all_seats = {key: set() for key in ("ucl", "uel", "uecl")}
        for comp, by_comp in seats.items():
            for key, teams in by_comp.items():
                all_seats[key].update(teams)
                for team in teams:
                    self.europe_associations.setdefault(team, comp)
            self.europe_association_totals[comp] += [len(by_comp[key]) for key in all_seats]
            acc, tbl = self.leagues[comp], tables[comp]
            fate = np.asarray([[tbl["position"][i] == 1, team in by_comp["ucl"],
                                any(team in by_comp[key] for key in all_seats),
                                tbl["position"][i] > len(acc["teams"]) - acc["relegated_n"]]
                               for i, team in enumerate(acc["teams"])], np.int32)
            self._stakes(rows[comp], acc["teams"], fate)
        # Other domestic leagues are outside the simulation. Their UEFA winners nevertheless
        # have these guaranteed titleholder entries; absence of another foreign club is unknown.
        for comp in ("UEFA Champions League", "UEFA Europa League"):
            team = champions.get(comp)
            if team and team not in self.europe_associations:
                all_seats["ucl"].add(team)
        team = champions.get("UEFA Conference League")
        if team and team not in self.europe_associations and team not in all_seats["ucl"]:
            all_seats["uel"].add(team)
        if any(all_seats[a] & all_seats[b] for a, b in (("ucl", "uel"), ("ucl", "uecl"),
                                                        ("uel", "uecl"))):
            raise ValueError("European entry sets overlap")
        for key, teams in all_seats.items():
            k = ("ucl", "uel", "uecl").index(key)
            for team in teams:
                self.europe_counts.setdefault(team, np.zeros(3, np.int32))[k] += 1
        if sample is not None:
            sample["europe"] = {key: sorted(teams) for key, teams in all_seats.items()}

    def europe_payload(self, n: int) -> Dict[str, Any]:
        """Known entry routes: five domestic systems plus foreign UEFA titleholders."""
        return {"mode": "per_world", "scope": "five_leagues_and_titleholders",
                "season": max(a["qualification"]["season"] for a in self.leagues.values()
                              if "qualification" in a),
                "eps_policy": "previous_allocation",
                "teams": [{"team": team, "association": self.europe_associations.get(team),
                           **{f"p_{key}": round(int(counts[k]) / n, 4)
                              for k, key in enumerate(("ucl", "uel", "uecl"))}}
                          for team, counts in sorted(self.europe_counts.items()) if counts.any()]}

    def _cup_rows(self, sim: pd.DataFrame) -> Dict[str, List[tuple]]:
        """Select tracked, named cup legs once per world, without six frame filters/itertuples."""
        if not self._cup_slots.any():
            return {}
        fid = sim.fixture_id.to_numpy()
        ix = np.flatnonzero(sim.sampled.to_numpy(bool) & (fid >= 0) & (fid < len(self.fx_pos)))
        slots = self.fx_pos[fid[ix]]
        keep = (slots >= 0) & self._cup_slots[np.maximum(slots, 0)]
        ix, slots = ix[keep], slots[keep]
        if not len(ix):
            return {}
        # The parent add() has already removed attrs; these column reads do not copy world state.
        columns = [sim[name].to_numpy()[ix] for name in
                   ("stage", "home", "away", "minutes", "home_goals", "away_goals")]
        grouped: Dict[str, List[tuple]] = {}
        for index, slot, stage, home, away, minutes, hg, ag in zip(ix, slots, *columns):
            meta = self.fx_meta[slot]
            # A bracket slot can represent several clubs; its odds are role-based, not a
            # named club's conditional fate. Keep the same exact-name eligibility as before.
            if meta["home"] == home and meta["away"] == away:
                grouped.setdefault(meta["competition"], []).append(
                    (int(index), int(slot), stage, home, away, minutes, hg, ag))
        return grouped

    def _cup_stakes(self, rows: List[tuple], comp: str, report: Dict[str, Any],
                    score90: Optional[np.ndarray]) -> None:
        """Batch later-round fates by stage, preserving every actual fixture occurrence."""
        if not rows:
            return
        rounds = list(report["reached"])
        reached = {label: set(teams) for label, teams in report["reached"].items()}
        stages: Dict[str, List[tuple]] = {}
        for row in rows:
            if row[2] in reached:
                stages.setdefault(row[2], []).append(row)
        for stage, group in stages.items():
            later = rounds[rounds.index(stage) + 1:]
            keys = [label.lower() for label in later] + ["win"]
            if score90 is None:
                if any(row[5] > 90 for row in group):
                    raise ValueError("Cup stakes need preserved 90-minute scores before extra time")
                scores = np.asarray([(row[6], row[7]) for row in group])
            else:
                scores = np.asarray(score90)[[row[0] for row in group]]
            if not np.isfinite(scores).all():
                raise ValueError("Cup stakes need known 90-minute scores")
            outcomes = np.where(scores[:, 0] > scores[:, 1], 0,
                                np.where(scores[:, 0] == scores[:, 1], 1, 2))
            fate = np.asarray([[[team in reached[label] for label in later]
                                + [team == report["champion"]] for team in (row[3], row[4])]
                               for row in group], np.int32)
            for row, result, values in zip(group, outcomes, fate):
                slot = row[1]
                if slot not in self.fx_cup_keys:
                    self.fx_cup_keys[slot] = list(keys)
                    self.fx_cup_stakes[slot] = np.zeros((3, 2, len(keys)), np.int32)
                if self.fx_cup_keys[slot] != keys:
                    raise ValueError(f"Cup fixture slot {slot} changed its later-round calendar")
                self.fx_cup_stakes[slot][result] += values

    def _stakes(self, g: pd.DataFrame, teams: pd.Index, fate: np.ndarray) -> None:
        """What rode on each tracked fixture in this world: its result -- home win, draw, away
        win -- against how each side's season ended. `fate` is (teams, 4), 0 or 1. Summed over
        the worlds and divided by each result's count, it is P(fate | result); weighted by the
        results' own chances it gives back P(fate), which smoke asserts.

        Plain arrays throughout: a tracked fixture is unplayed, so every world simulates it once,
        and a fancy-indexed += over distinct (fixture, result) pairs is exact without np.add.at.
        The sides' places come from `fx_hi` / `fx_ai`, set up once by fixture id."""
        fid = g.fixture_id.to_numpy()
        ok = (fid >= 0) & (fid < len(self.fx_pos)) & (fid < len(self.fx_hi))
        fid = fid[ok]
        pos = self.fx_pos[fid]
        tr = pos >= 0
        if not tr.any():
            return
        fid, pos = fid[tr], pos[tr]
        hg = g.home_goals.to_numpy()[ok][tr]
        ag = g.away_goals.to_numpy()[ok][tr]
        out = np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
        f = np.asarray(fate, np.int32)
        self.fx_stakes[pos, out, 0] += f[self.fx_hi[fid]]
        self.fx_stakes[pos, out, 1] += f[self.fx_ai[fid]]
        wi = self.whatif_pos[pos]
        keep = wi >= 0
        if keep.any():
            # Each (fixture, result) occurs once a world. Broadcast that world's competition
            # fates across its next fixtures, without another frame read or np.add.at.
            self.fx_whatif[wi[keep], out[keep], :len(teams), :] += f

    def _tally(self, acc: Dict[str, Any], g: pd.DataFrame) -> Optional[np.ndarray]:
        """This world's W/D/L/GF/GA in the round each match belongs to, then run totals.
        Returns this world's run totals, (5, teams, rounds + 1), for `_decided`."""
        fid = g.fixture_id.to_numpy()
        ok = (fid >= 0) & (fid < len(self.round_of))
        r = np.where(ok, self.round_of[np.clip(fid, 0, len(self.round_of) - 1)], -1)
        ok &= r > 0
        if not ok.any():
            return None
        h = acc["teams"].get_indexer(g.home.to_numpy()[ok])
        a = acc["teams"].get_indexer(g.away.to_numpy()[ok])
        hg, ag, r = g.home_goals.to_numpy(float)[ok], g.away_goals.to_numpy(float)[ok], r[ok]
        inc = np.zeros_like(acc["gw"])
        for k, (hv, av) in enumerate(((hg > ag, ag > hg), (hg == ag, hg == ag),
                                      (ag > hg, hg > ag), (hg, ag), (ag, hg))):
            np.add.at(inc[k], (h, r), hv)
            np.add.at(inc[k], (a, r), av)
        cum = np.cumsum(inc, axis=2)
        acc["gw"] += cum
        return cum

    def _xg_tally(self, acc: Dict[str, Any], g: pd.DataFrame, comp: str, kind: str) -> None:
        """This world's xG for and against and xG points, by round, as run totals: a played
        match's real ones, a projected match its drawn npxG plus the competition's penalty xG
        (`penalty_xg`), valued the way a played match is (Poisson at each side's xG, Dixon-Coles
        at the competition's rho). Thousandths, so integer sums stay exact in any order."""
        if self.pen_xg is None or g.empty:
            return
        fid = g.fixture_id.to_numpy()
        ok = (fid >= 0) & (fid < len(self.round_of))
        r = np.where(ok, self.round_of[np.clip(fid, 0, len(self.round_of) - 1)], -1)
        ok &= r > 0
        if not ok.any():
            return
        f, r = fid[ok], r[ok]
        samp = g.sampled.to_numpy(bool)[ok]
        c = self.pen_xg.get(comp, self.pen_xg.get("", 0.12))
        real = self.real_xg[f]
        xh = np.where(samp, g.home_npxg.to_numpy(float)[ok] + c, real[:, 0])
        xa = np.where(samp, g.away_npxg.to_numpy(float)[ok] + c, real[:, 1])
        ph, pa = real[:, 2].copy(), real[:, 3].copy()
        if samp.any():
            from scripts.backtest_qt import outcome_probs
            P = outcome_probs(np.clip(xh[samp], 0.01, None), np.clip(xa[samp], 0.01, None),
                              MATCH_DRAW.get(kind, MATCH_DRAW["league"])[2])
            ph[samp], pa[samp] = 3 * P[:, 0] + P[:, 1], 3 * P[:, 2] + P[:, 1]
        keep = np.isfinite(xh) & np.isfinite(xa) & np.isfinite(ph) & np.isfinite(pa)
        if not keep.any():
            return
        h = acc["teams"].get_indexer(g.home.to_numpy()[ok][keep])
        a = acc["teams"].get_indexer(g.away.to_numpy()[ok][keep])
        r = r[keep]
        q = lambda v: np.rint(v[keep] * 1000).astype(np.int64)
        qh, qa, qph, qpa = q(xh), q(xa), q(ph), q(pa)
        inc = np.zeros_like(acc["gx"])
        for k, (hv, av) in enumerate(((qh, qa), (qa, qh), (qph, qpa))):
            np.add.at(inc[k], (h, r), hv)
            np.add.at(inc[k], (a, r), av)
        acc["gx"] += np.cumsum(inc, axis=2)

    def _state_tally(self, sim: pd.DataFrame, state: Optional[pd.DataFrame] = None) -> None:
        """This world's ratings: each side's Elo, ATT and DEF going into each of its simulated
        league and league-phase matches, at the index of that match's round, and coming out of
        its last-round match, at the end index. A world's state is its own -- the reason a side
        can be relegated in one world and win the league in another -- and this is where it is
        counted. One pass a world: a scheduled fixture's block and sides are fixed by its id.

        ATT and DEF are summed as LOGS, so the page shows their geometric mean over the worlds.
        A world's strength moves are zero-mean in log space, and the arithmetic mean of exp() rises
        with the spread between worlds (Jensen): every side's attack would have read as improving
        by May with nothing expected to change. Elo moves linearly and is averaged as it is.

        Fixed point, not floats. Floats summed in a different order round differently, so the
        parallel runner's chunking would move the last digit and its answer would no longer be
        identical to one process's; integer sums are exact in any order (and a world's few
        integers per cell are exact in bincount's float64 too)."""
        if state is None:
            state = sim.attrs.get("state")
        if state is None or self.scale is None or not self._blocks:
            return
        fid = sim.fixture_id.to_numpy()
        rows = np.flatnonzero(sim.sampled.to_numpy(bool) & (fid >= 0) & (fid < len(self.fx_block)))
        f = fid[rows]
        keep = self.fx_block[f] >= 0
        rows, f = rows[keep], f[keep]
        if not len(rows):
            return
        S, blk, r = state[rows], self.fx_block[f], self.round_of[f]
        hi, ai = self.fx_hi[f], self.fx_ai[f]
        sc = self.scale
        # columns: home before, away before, home after, away after (STATE_COLS)
        elo, q, t = S[:, [0, 3, 6, 9]], S[:, [1, 4, 7, 10]], S[:, [2, 5, 8, 11]]
        V = np.rint(np.stack([elo, sc["c"] + (q + t) / 2 - sc["d_ref"],
                              sc["c"] + sc["a_ref"] - (q - t) / 2])
                    * np.array(RATING_SCALE, float)[:, None, None])           # (3, rows, 4)
        for b, acc in enumerate(self._blocks):
            mb = blk == b
            if not mb.any():
                continue
            width, n = acc["rounds"] + 1, len(acc["teams"])
            rb = r[mb]
            last = rb == acc["rounds"]
            team = np.concatenate([hi[mb], ai[mb], hi[mb][last], ai[mb][last]])
            at = np.concatenate([rb - 1, rb - 1, rb[last], rb[last]])
            Vb = V[:, mb]
            vals = np.concatenate([Vb[:, :, 0], Vb[:, :, 1], Vb[:, last, 2], Vb[:, last, 3]],
                                  axis=1)
            flat, size = team * width + at, n * width
            acc["st_n"] += np.bincount(flat, minlength=size).reshape(n, width)
            for k in range(3):
                for j, w in ((k, vals[k]), (k + 3, vals[k] * vals[k])):
                    acc["st"][j] += np.rint(np.bincount(flat, weights=w, minlength=size)
                                            ).astype(np.int64).reshape(n, width)

    @staticmethod
    def _decided(acc: Dict[str, Any], cum: np.ndarray, champion: int, down: np.ndarray) -> None:
        """When this world's title and relegation places were DECIDED: the first round after
        which no result left could change them.

        The leader has clinched once its points beat every other side's most possible -- points
        so far plus three for each match left. A side is relegated once enough sides are above
        its most possible to fill every safe place. Level on points is not decided (goal
        difference is not), so the strict inequality. Whatever is still open after the last
        round was settled on the final day. Rounds are the fixture list's, as the Gameweek view's
        are, so a postponed match counts in the round it belongs to."""
        pts = 3 * cum[0] + cum[1]                                # (teams, rounds + 1)
        games = acc["pl"]
        most = pts + 3 * (games[:, -1:] - games)
        n, last = pts.shape[0], pts.shape[1] - 1
        # the title: the eventual champion's points against the best of the others' most possible
        others = np.delete(most, champion, axis=0).max(axis=0)
        won = np.flatnonzero(pts[champion] > others)
        acc["clinch"][champion, int(won[0]) if won.size else last] += 1
        # relegation: sides strictly above a side's most possible, against the safe places
        safe = n - int(acc.get("relegated_n", 3))
        for t in down:
            above = (pts[:, None, :] > most[None, t:t + 1, :]).sum(axis=0)[0]   # (rounds + 1,)
            gone = np.flatnonzero(above >= safe)
            acc["down"][t, int(gone[0]) if gone.size else last] += 1

    def merge(self, other: "Accumulator") -> "Accumulator":
        """Add another accumulator's counts into this one. Exact: everything here is a count."""
        for comp, tally in other.entry_routes.items():
            if comp not in self.entry_routes:
                from scripts.race_routes import RouteTally
                self.entry_routes[comp] = RouteTally(tally.teams)
            self.entry_routes[comp].merge(tally)
        for comp, tally in other.rivals.items():
            if comp not in self.rivals:
                from scripts.race_room import RivalTally
                self.rivals[comp] = RivalTally(tally.teams)
            self.rivals[comp].merge(tally)
        if other.fx_counts.size:
            if not self.fx_counts.size:
                self.fx_index, self.fx_meta = other.fx_index, other.fx_meta
                self.fx_pos, self.track_stages = other.fx_pos, other.track_stages
                self.fx_counts = other.fx_counts.copy()
                self.fx_stakes = other.fx_stakes.copy()
                self._cup_slots = other._cup_slots.copy()
                self.whatif_pos = other.whatif_pos.copy()
                self.fx_whatif = other.fx_whatif.copy()
            else:
                self.fx_counts += other.fx_counts
                self.fx_stakes += other.fx_stakes
                self.fx_whatif += other.fx_whatif
        for slot, counts in other.fx_cup_stakes.items():
            keys = other.fx_cup_keys[slot]
            if slot in self.fx_cup_stakes:
                if self.fx_cup_keys[slot] != keys:
                    raise ValueError(f"Cup fixture slot {slot} has inconsistent round keys")
                self.fx_cup_stakes[slot] += counts
            else:
                self.fx_cup_keys[slot] = list(keys)
                self.fx_cup_stakes[slot] = counts.copy()
        if not self.europe_policy and other.europe_policy:
            self.europe_policy = dict(other.europe_policy)
        for team, association in other.europe_associations.items():
            if team in self.europe_associations and self.europe_associations[team] != association:
                raise ValueError(f"Conflicting European association for {team}")
            self.europe_associations[team] = association
        for team, counts in other.europe_counts.items():
            if team in self.europe_counts:
                self.europe_counts[team] += counts
            else:
                self.europe_counts[team] = counts.copy()
        for comp, counts in other.europe_association_totals.items():
            if comp in self.europe_association_totals:
                self.europe_association_totals[comp] += counts
            else:
                self.europe_association_totals[comp] = counts.copy()
        # Retain by absolute index, never by arrival order. This also handles a finished season
        # with no tracked future fixtures (and therefore no fx_counts to merge).
        for index, sample in other.samples.items():
            if index in self.samples and self.samples[index] != sample:
                raise ValueError(f"conflicting sample world {index}")
            self.samples[index] = sample
        for key, tbl in other.matchups.items():
            if key in self.matchups:
                self.matchups[key] += tbl
            else:
                self.matchups[key] = tbl.copy()
        self.worlds += other.worlds
        self.matches += other.matches
        self.goal_hist += other.goal_hist
        self.outcome += other.outcome
        for comp, acc in other.leagues.items():
            mine = self.leagues.setdefault(comp, acc)
            if mine is not acc:
                mine["pos"] += acc["pos"]
                for key, _, _, _ in LEAGUE_DISTS:
                    mine[key] += acc[key]
                mine["gw"] += acc["gw"]
                mine["st"] += acc["st"]
                mine["st_n"] += acc["st_n"]
                mine["gx"] += acc["gx"]
                mine["clinch"] += acc["clinch"]
                mine["down"] += acc["down"]
                for k, h in acc["lines"].items():
                    mine["lines"][k] += h
        for comp, acc in other.phases.items():
            mine = self.phases.setdefault(comp, acc)
            if mine is not acc:
                for key in ("pts", "gd_sum", "gf_sum", "gw", "st", "st_n", "gx"):
                    mine[key] += acc[key]
                for k, h in acc["lines"].items():
                    mine["lines"][k] += h
        if not len(self.round_of) > 1 and len(other.round_of) > 1:
            self.round_of = other.round_of
        if self.scale is None:
            self.scale = other.scale
        if self.pen_xg is None:
            self.pen_xg = other.pen_xg
        for comp, acc in other.uefa.items():
            mine = self.uefa.setdefault(comp, {"teams": {}, "n": 0, "pairs": {}})
            mine["n"] += acc["n"]
            _merge_pairs(mine["pairs"], acc.get("pairs", {}))
            for team, d in acc["teams"].items():
                t = mine["teams"].setdefault(team, _blank_team())
                t["seed"] += d["seed"]
                t["win"] += d["win"]
                for k, v in d["reach"].items():
                    t["reach"][k] += v
        for comp, acc in other.cups.items():
            mine = self.cups.setdefault(comp, {"teams": {}, "n": 0, "rounds": [],
                                               "drawn": [], "et": 0, "pens": 0,
                                               "late": {}, "byes": {}, "pairs": {}})
            mine["n"] += acc["n"]
            _merge_pairs(mine.setdefault("pairs", {}), acc.get("pairs", {}))
            mine["et"] += acc["et"]
            mine["pens"] += acc["pens"]
            if not mine["rounds"]:
                mine["rounds"], mine["drawn"] = list(acc["rounds"]), list(acc["drawn"])
                mine["late"], mine["byes"] = dict(acc.get("late", {})), dict(acc.get("byes", {}))
            for team, d in acc["teams"].items():
                t = mine["teams"].setdefault(team, {"reach": {}, "win": 0})
                t["win"] += d["win"]
                for k, v in d["reach"].items():
                    t["reach"][k] = t["reach"].get(k, 0) + v
        for team, h in other.trophies.items():
            if team in self.trophies:
                self.trophies[team] += h
            else:
                self.trophies[team] = h.copy()
        for key, c in other.combos.items():
            self.combos[key] = self.combos.get(key, 0) + c
        self.decided += other.decided
        return self

    def result(self) -> Dict[str, Any]:
        n = max(self.worlds, 1)
        leagues = []
        for comp, acc in sorted(self.leagues.items()):
            if comp in self.entry_routes and self.entry_routes[comp].worlds != self.worlds:
                raise ValueError("Route sample does not cover every projection world")
            if comp in self.rivals and self.rivals[comp].worlds != self.worlds:
                raise ValueError("Rival sample does not cover every projection world")
            if not acc["pts"].any():
                continue
            size = len(acc["teams"])
            releg = 3 if size >= 18 else 2
            ucl = min(int(acc.get("ucl_spots", 4)), size)
            uel = min(int(acc.get("uel_spots", 0)), size - ucl)
            uecl = min(int(acc.get("uecl_spots", 0)), size - ucl - uel)
            # trim each quantity to the range any team reaches. 200 bins per team per quantity is
            # for accumulation, not for the wire -- untrimmed this payload is ~1.2 MB of zeros.
            spans = {}
            for key, width, offset, _ in LEAGUE_DISTS:
                # Trim to where pooled mass is NON-ZERO, not to a percentile. A percentile trim
                # (the outer 0.05% per side) was worth having when all seven quantities shipped a
                # distribution, but it discards real probability: a team near the edge of the
                # league's span lost ~0.8%, so its bands could not sum to 100%. Only points ships
                # a distribution now, and for that the two trims differ by two bins -- so the
                # exact one is free.
                pooled = acc[key].sum(0)
                nz = np.flatnonzero(pooled)
                lo, hi = (int(nz[0]), int(nz[-1]) + 1) if nz.size else (0, 1)
                spans[key] = (lo, min(hi, width), offset)
            rows = []
            for i, team in enumerate(acc["teams"]):
                dist = acc["pos"][i] / n
                row = {"team": team,
                       "mean_pos": round(float((dist * np.arange(1, size + 1)).sum()), 2),
                       "p_win": round(float(dist[0]), 4),
                       **({f"p_{key}": round(int(self.europe_counts[team][k]) / n, 4)
                           for k, key in enumerate(("ucl", "uel", "uecl"))}
                          if comp in self.europe_policy else {
                           "p_ucl": round(float(dist[:ucl].sum()), 4),
                           "p_uel": round(float(dist[ucl:ucl + uel].sum()), 4),
                           "p_uecl": round(float(dist[ucl + uel:ucl + uel + uecl].sum()), 4)}),
                       "p_top4": round(float(dist[:4].sum()), 4),
                       "p_releg": round(float(dist[size - releg:].sum()), 4),
                       "dist": [round(float(x), 4) for x in dist]}
                for key, _, _, _ in LEAGUE_DISTS:
                    lo, hi, offset = spans[key]
                    h = acc[key][i]
                    tot = max(h.sum(), 1)
                    c = np.cumsum(h) / tot
                    values = np.arange(len(h)) + offset
                    row[key] = {
                        "mean": round(float((h * values).sum() / tot), 1),
                        "p10": int(np.searchsorted(c, 0.10)) + offset,
                        "p50": int(np.searchsorted(c, 0.50)) + offset,
                        "p90": int(np.searchsorted(c, 0.90)) + offset}
                    if key in DIST_KEYS:
                        row[key]["offset"] = lo + offset
                        row[key]["dist"] = [round(float(x / tot), 4) for x in h[lo:hi]]
                # kept at the top level so anything reading older snapshots still works
                row["mean_pts"] = row["pts"]["mean"]
                row["now"] = dict(acc["now"][team])         # the real table so far
                row["p10"], row["p50"], row["p90"] = (row["pts"]["p10"], row["pts"]["p50"],
                                                      row["pts"]["p90"])
                rows.append(row)
            rows.sort(key=lambda r: r["mean_pos"])
            leagues.append({"competition": comp, "size": size, "relegated": releg,
                            "ucl_spots": ucl, "uel_spots": uel, "uecl_spots": uecl,
                            "places_from": acc.get("places_from"),
                            **({"qualification": {**acc["qualification"],
                                "mean": {key: round(sum(int(self.europe_counts[t][k]) for t in acc["teams"]) / n, 4)
                                         for k, key in enumerate(("ucl", "uel", "uecl"))},
                                "association_mean": {key: round(int(self.europe_association_totals[comp][k]) / n, 4)
                                                     for k, key in enumerate(("ucl", "uel", "uecl"))}}}
                               if comp in self.europe_policy else {}),
                            "lines": _line_rows(acc["lines"], {
                                2: "Title",
                                ucl + 1: f"UCL (top {ucl})",
                                ucl + uel + uecl + 1: f"Europe (top {ucl + uel + uecl})",
                                size - releg + 1: f"Survival (top {size - releg})"}),
                            **({"rivals": self.rivals[comp].payload()} if comp in self.rivals else {}),
                            **({"entry_routes": self.entry_routes[comp].payload(self.europe_counts)}
                               if comp in self.entry_routes else {}),
                            "stats": [{"key": k, "label": lab} for k, _, _, lab in LEAGUE_DISTS],
                            "teams": rows})

        uefa = []
        for comp, acc in sorted(self.uefa.items()):
            if not acc["teams"]:
                continue
            m = max(acc["n"], 1)
            rows = []
            phase_size = max((int(np.max(np.array(d["seed"]))) if d["seed"] else 0)
                             for d in acc["teams"].values()) or 36
            ph = self.phases.get(comp)
            if ph is not None:
                nz = np.flatnonzero(ph["pts"].sum(0))
                p_lo, p_hi = (int(nz[0]), int(nz[-1]) + 1) if nz.size else (0, 1)
            for team, d in acc["teams"].items():
                seeds = np.array(d["seed"], float)
                # the league-phase finishing distribution, same shape as a league's position
                # matrix, so one view can render either
                sd = (np.bincount(np.asarray(d["seed"], int) - 1, minlength=phase_size)
                      / max(len(d["seed"]), 1)) if len(d["seed"]) else np.zeros(phase_size)
                rows.append({"team": team,
                             "mean_seed": round(float(seeds.mean()), 1) if len(seeds) else None,
                             "mean_pos": round(float(seeds.mean()), 2) if len(seeds) else None,
                             "dist": [round(float(x), 4) for x in sd],
                             "p_top8": round(float(np.mean(seeds <= 8)), 4) if len(seeds) else None,
                             "p_out": round(float(np.mean(seeds >= 25)), 4) if len(seeds) else None,
                             "p_mid": (round(float(np.mean((seeds >= 9) & (seeds <= 24))), 4)
                                       if len(seeds) else None),
                             **{f"p_{k.lower()}": round(d["reach"][k] / m, 4) for k in STAGE_ORDER},
                             "p_win": round(d["win"] / m, 4)})
                row = rows[-1]
                if ph is not None and team in ph["teams"]:
                    i = ph["teams"].get_loc(team)
                    h = ph["pts"][i]
                    tot = max(h.sum(), 1)
                    c = np.cumsum(h) / tot
                    row["pts"] = {"mean": round(float((h * np.arange(len(h))).sum() / tot), 1),
                                  "p10": int(np.searchsorted(c, 0.10)),
                                  "p50": int(np.searchsorted(c, 0.50)),
                                  "p90": int(np.searchsorted(c, 0.90)),
                                  "offset": p_lo,
                                  "dist": [round(float(x / tot), 4) for x in h[p_lo:p_hi]]}
                    row["mean_pts"] = row["pts"]["mean"]
                    row["mean_gd"] = round(float(ph["gd_sum"][i] / tot), 1)
                    row["now"] = dict(ph["now"][team])
            # a total order: at a few dozen worlds sides tie on all three, and a stable sort then
            # keeps the order the teams were first SEEN in -- which in the parallel runner is
            # whichever chunk arrived first, so the rows came out in a different order run to run
            rows.sort(key=lambda r: (-r["p_win"], -(r["p_f"] or 0), r["mean_seed"] or 99,
                                     r["team"]))
            uefa.append({"competition": comp, "worlds": acc["n"], "size": phase_size,
                         "rounds": int(ph["rounds"]) if ph is not None else None,
                         "lines": (_line_rows(ph["lines"], {
                             9: "Top 8 (straight to the R16)",
                             25: "Top 24 (the play-off)"}) if ph is not None else []),
                         "teams": rows})

        # Domestic cups. One row per team, one column per round: P(still in it at that round),
        # then P(lifts it). There is no table and no seed to report -- a cup has neither -- so the
        # reach ladder IS the projection. `rounds` is in calendar order, which matters: a
        # preliminary round is not "smaller" than the round of 16 it feeds, so the columns cannot
        # be sorted by size and must keep the order the calendar gave them.
        cups = []
        for comp, acc in sorted(self.cups.items()):
            if not acc["teams"] or not acc["rounds"]:
                continue
            m = max(acc["n"], 1)
            labels = list(acc["rounds"])
            rows = [{"team": team,
                     **{f"p_{lab.lower()}": round(d["reach"].get(lab, 0) / m, 4)
                        for lab in labels},
                     "p_win": round(d["win"] / m, 4)}
                    for team, d in acc["teams"].items()]
            rows.sort(key=lambda r: (-r["p_win"], -r[f"p_{labels[-1].lower()}"], r["team"]))
            cups.append({"competition": comp, "worlds": acc["n"], "rounds": labels,
                         "drawn_from": (acc["drawn"] or [None])[0],
                         "late_entrants": acc.get("late", {}),
                         "bye_slots": acc.get("byes", {}),
                         "mean_extra_times": round(acc["et"] / m, 2),
                         "mean_shootouts": round(acc["pens"] / m, 2),
                         "teams": rows})

        # Trophies: each team's haul. `p` is P(0), P(1), ... trophies; `combos` the likeliest sets
        # won, with the rest pooled.
        trophies = []
        by_team: Dict[str, List[Tuple[Tuple[str, ...], int]]] = {}
        for (team, comps), c in self.combos.items():
            by_team.setdefault(team, []).append((comps, c))
        for team, h in self.trophies.items():
            p = h / n
            p[0] = 1.0 - p[1:].sum()
            top = sorted(by_team.get(team, []), key=lambda x: (-x[1], x[0]))
            rest = sum(c for _, c in top[HAUL_TOP:])
            hi = int(np.flatnonzero(h)[-1]) + 1 if h.any() else 1
            trophies.append({"team": team,
                             "mean": round(float((p * np.arange(len(p))).sum()), 4),
                             "p": [round(float(x), 4) for x in p[:max(hi, 2)]],
                             "combos": [[list(cs), round(c / n, 4)] for cs, c in top[:HAUL_TOP]],
                             "other": round(rest / n, 4)})
        trophies.sort(key=lambda t: (-t["mean"], t["team"]))
        rare = [t for t in trophies if t["mean"] < HAUL_MIN]
        trophies = [t for t in trophies if t["mean"] >= HAUL_MIN]

        tot = max(self.goal_hist.sum(), 1)
        return {"worlds": self.worlds, "version": PAYLOAD_VERSION, "model": MODEL_GENERATION,
                "leagues": leagues, "uefa": uefa, "cups": cups,
                **({"europe": self.europe_payload(n)} if self.europe_policy else {}),
                "samples": [self.samples[i] for i in sorted(self.samples)],
                "trophies": {"per_world": round(self.decided / n, 4), "teams": trophies,
                             "others": {"teams": len(rare),
                                        "mean": round(sum(t["mean"] for t in rare), 4)}},
                "match": {"sampled": self.matches,
                          "goal_dist": [round(float(x / tot), 4) for x in self.goal_hist[:9]],
                          "over25": round(float(self.goal_hist[3:].sum() / tot), 4),
                          "outcome": [round(float(x / max(self.outcome.sum(), 1)), 4)
                                      for x in self.outcome],
                          "mean_goals": round(float((self.goal_hist * np.arange(16)).sum() / tot),
                                              3)}}


def _paths_of(a: Dict[str, Any], rounds, min_reach: float = PATH_MIN) -> Dict[str, Any]:
    """One competition's paths. Opponents are indices into `names`, written once: spelled out in
    every entry, the six domestic cups' paths alone were 700 KB a snapshot."""
    m = max(a["n"], 1)
    by: Dict[str, Dict[str, List[Tuple[str, int, int]]]] = {}
    for (label, t, o), (met, thr) in a.get("pairs", {}).items():
        by.setdefault(t, {}).setdefault(label, []).append((o, met, thr))
    names = sorted({o for st in by.values() for opps in st.values() for o, _, _ in opps} | set(by))
    ix = {t: i for i, t in enumerate(names)}
    teams = {}
    for team, stages in sorted(by.items()):
        path = {}
        for label in rounds:
            opps = sorted(stages.get(label, []), key=lambda x: (-x[1], x[0]))
            if not opps or sum(x[1] for x in opps) < min_reach * m:
                continue
            rest = opps[PATH_TOP:]
            met_r, thr_r = sum(x[1] for x in rest), sum(x[2] for x in rest)
            path[label] = {"top": [[ix[o], round(met / m, 4), round(thr / met, 3)]
                                   for o, met, thr in opps[:PATH_TOP]],
                           "other": ([round(met_r / m, 4), round(thr_r / met_r, 3), len(rest)]
                                     if rest else None)}
        if path:
            teams[team] = path
    # names only of what is listed, once the rare rounds are gone
    used = sorted({o for p in teams.values() for b in p.values() for o, _, _ in b["top"]})
    remap = {i: k for k, i in enumerate(used)}
    for p in teams.values():
        for b in p.values():
            b["top"] = [[remap[o], x, y] for o, x, y in b["top"]]
    return {"worlds": a["n"], "rounds": list(rounds), "min_reach": min_reach,
            "names": [names[i] for i in used], "teams": teams}


def paths_payload(acc: "Accumulator") -> Dict[str, Any]:
    """Each UEFA and domestic-cup side's knockout PATH: per round, its likeliest opponents with
    P(meet them) and P(go through | met), the rest pooled. `paths.json` beside the snapshot, read
    only when a Paths view opens -- it is a third of the UEFA payload and the history chart
    re-reads every snapshot.

    Identity: over a round's opponents, the sum of P(meet) is the chance of playing that round,
    and the sum of P(meet) x P(through | met) the chance of going through it -- for UEFA, the next
    round's reach (less P(top 8) for the play-off, which the top eight skip)."""
    return {"worlds": acc.worlds, "top": PATH_TOP,
            "competitions": {c: _paths_of(a, STAGE_ORDER) for c, a in sorted(acc.uefa.items())},
            "cups": {c: _paths_of(a, a["rounds"], PATH_MIN_CUP) for c, a in sorted(acc.cups.items())
                     if a.get("rounds")}}


def first_pending_stages(hands: Dict[Any, Any], horizon: Optional[pd.Timestamp] = None) -> set:
    """(competition, stage) of the first stage each UEFA knockout must draw, if it is IMMINENT.

    The horizon matters. Without it, a run in August pools the February play-off round and finds
    3,600 distinct matchups clearing the occurrence threshold -- technically true, useless to read,
    and it bloats the snapshot. A drawn tie is only worth pooling when it is the next thing that
    happens; until then the useful UEFA rows are the scheduled league-phase fixtures.
    """
    out = set()
    for (comp, _), hand in hands.items():
        undrawn = [sp for sp in hand.specs if sp.ties is None]
        if undrawn and (horizon is None or undrawn[0].leg1 <= horizon):
            out.add((comp, undrawn[0].label))
    return out


def match_horizon(fx: pd.DataFrame, days: int = 21) -> pd.Timestamp:
    """How far ahead counts as imminent: three weeks from the next upcoming fixture."""
    unplayed = fx[upcoming(fx)]
    base = unplayed.kickoff.min() if len(unplayed) else fx.kickoff.max()
    return base + pd.Timedelta(days=days)


def _match_row(meta: Dict[str, Any], tbl: np.ndarray, top: int = 5) -> Dict[str, Any]:
    """One match's distribution: the outcome ladder, the likeliest scorelines, each side's clean
    sheet, a couple of totals.

    The ladder is CUMULATIVE by margin -- `h1` is a home win, `h2` a home win by two or more,
    `h3` by three or more -- so reading down it gives the shape of the match, not just who wins.
    A clean sheet is the OTHER side scoring nothing, so `cs_h`, the home side keeping one, is the
    away-goals-zero column; rows of the table are home goals.
    """
    n = int(tbl.sum())
    if not n:
        return {**meta, "n": 0}
    g = np.arange(MAXG)
    margin = g[:, None] - g[None, :]
    p = tbl / n
    lad = {f"h{k}": float(p[margin >= k].sum()) for k in (1, 2, 3)}
    lad["d"] = float(p[margin == 0].sum())
    lad.update({f"a{k}": float(p[margin <= -k].sum()) for k in (1, 2, 3)})
    flat = np.argsort(tbl.ravel())[::-1][:top]
    tot = g[:, None] + g[None, :]
    return {**meta, "n": n,
            "ladder": {k: round(v, 4) for k, v in lad.items()},
            "top": [[f"{i // MAXG}-{i % MAXG}", round(float(tbl.ravel()[i] / n), 4)]
                    for i in flat if tbl.ravel()[i] > 0],
            "over25": round(float(p[tot >= 3].sum()), 4),
            "btts": round(float(p[1:, 1:].sum()), 4),
            "cs_h": round(float(p[:, 0].sum()), 4),
            "cs_a": round(float(p[0, :].sum()), 4),
            "mean_goals": round(float((p * tot).sum()), 3),
            "mean_h": round(float((p.sum(1) * g).sum()), 3),
            "mean_a": round(float((p.sum(0) * g).sum()), 3)}


def _projected_extras(acc: "Accumulator", i: int) -> Dict[str, Any]:
    """A tracked league or league-phase fixture's stakes: for each side, each fate's chance given
    a home win, a draw or an away win (`Accumulator._stakes`)."""
    tbl = acc.fx_counts[i]
    out: Dict[str, Any] = {}
    if not int(tbl.sum()):
        return out
    meta = acc.fx_meta[i]
    cup = meta["kind"] == "cup"
    if cup or (meta["kind"] == "uefa" and meta["round"] is None):
        out["score_basis"] = "90min"
    if cup:
        out["p_occurs"] = round(int(tbl.sum()) / max(acc.worlds, 1), 4)
    st = acc.fx_cup_stakes.get(i) if cup else acc.fx_stakes[i]
    if cup and int(tbl.sum()) != acc.worlds:
        # A speculative later pairing's result conditions on reaching that fixture as well.
        # It cannot be compared with an unconditional reach chance, so do not publish stakes.
        st = None
        out["stakes_unavailable"] = "conditional_fixture"
    if st is not None and (cup or st.any()):
        g = np.arange(MAXG)
        margin = g[:, None] - g[None, :]
        by = [int(tbl[margin > 0].sum()), int(tbl[margin == 0].sum()), int(tbl[margin < 0].sum())]
        # [side][fate][home win, draw, away win]; null for a result no world produced. A fate
        # the result cannot move -- the same whatever happens, as a title is for a side already
        # out of it -- is one number in place of three, which halves the file.
        def row(side: int, k: int) -> Any:
            v = [round(float(st[o, side, k]) / by[o], 3) if by[o] else None for o in range(3)]
            return v[0] if v[0] is not None and v.count(v[0]) == 3 else v
        out["stakes"] = [[row(side, k) for k in range(st.shape[2])] for side in range(2)]
        if cup:
            out["stakes_of"] = list(acc.fx_cup_keys[i])
    return out


def head_to_head(master: pd.DataFrame, cutoff: pd.Timestamp) -> Dict[Tuple[str, str], List[list]]:
    """Newest six real meetings per pair, in any competition, strictly before a run's cutoff.

    This is static metadata computed once after the worlds, never a simulation input. Using
    the preparation cutoff also protects rewound and replay-from-season-start runs from seeing
    real results their fit had not seen. Opponents retain their actual home/away orientation.
    """
    end = pd.Timestamp(cutoff)
    if pd.isna(end):
        return {}
    # Strip attrs before deriving any frame/column: a caller may hold simulation reports there.
    attrs = master.attrs
    master.attrs = {}
    try:
        played = master[master.played & (master.kickoff < end)]
        if "tbd" in played:
            played = played[~played.tbd]
        records = list(played.itertuples(index=False))
    finally:
        master.attrs = attrs

    def known(value: Any) -> Optional[float]:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if np.isfinite(value) and value >= 0 else None

    meetings = []
    for row in records:
        hg, ag = known(row.home_goals), known(row.away_goals)
        if hg is None or ag is None or not hg.is_integer() or not ag.is_integer():
            continue
        hx, ax = known(getattr(row, "home_xg", None)), known(getattr(row, "away_xg", None))
        meetings.append((pd.Timestamp(row.kickoff), str(row.competition), str(row.home),
                         str(row.away), int(hg), int(ag), hx, ax))
    meetings.sort(key=lambda r: (-r[0].value, r[1], r[2], r[3], r[4], r[5],
                                 -1 if r[6] is None else r[6], -1 if r[7] is None else r[7]))
    history: Dict[Tuple[str, str], List[list]] = {}
    seen = set()
    for stamp, comp, home, away, hg, ag, hx, ax in meetings:
        fixture = (stamp, comp, home, away)
        if fixture in seen:
            continue
        seen.add(fixture)
        pair = tuple(sorted((home, away)))
        previous = history.setdefault(pair, [])
        if len(previous) < 6:
            previous.append([str(stamp.date()), comp, home, away, hg, ag, hx, ax])
    return history


def _add_head_to_head(acc: "Accumulator", master: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    history = head_to_head(master, cutoff)
    for fixture in acc.fx_meta:
        fixture["h2h"] = history.get(tuple(sorted((fixture["home"], fixture["away"]))), [])


def whatif_payload(acc: "Accumulator", fixture_index: int,
                   include_all: bool = False) -> Optional[Dict[str, List[list]]]:
    """All four fates by H/D/A for sides a next-round result moves by at least 0.5pp.

    The filter uses unrounded counts against the unconditional fate chance. Comparing integer
    cross-products makes 0.5pp exactly 1/200, including its boundary. ``include_all`` exposes
    every side for accounting checks; production emits only the qualifying sides. An absent
    result is null, never a made-up conditional probability. None means ineligible fixture.
    """
    slot = int(acc.whatif_pos[fixture_index])
    if slot < 0:
        return None
    meta = acc.fx_meta[fixture_index]
    block = (acc.leagues if meta["kind"] == "league" else acc.phases)[meta["competition"]]
    teams = block["teams"]
    table = acc.fx_counts[fixture_index]
    goals = np.arange(MAXG)
    margin = goals[:, None] - goals[None, :]
    by = np.array([table[margin > 0].sum(), table[margin == 0].sum(),
                   table[margin < 0].sum()], np.int64)
    n = int(by.sum())
    if not n:
        return {}
    counts = acc.fx_whatif[slot, :, :len(teams), :].astype(np.int64)
    totals = counts.sum(axis=0)
    distance = np.abs(counts * n - totals[None, :, :] * by[:, None, None])
    selected = np.ones(len(teams), bool) if include_all else np.any(
        (by[:, None, None] > 0) & (200 * distance >= n * by[:, None, None]), axis=(0, 2))
    return {str(team): [[round(int(counts[o, t, k]) / int(by[o]), 3) if by[o] else None
                         for o in range(3)] for k in range(4)]
            for t, team in enumerate(teams) if selected[t]}


def match_payload(acc: "Accumulator") -> Dict[str, Any]:
    """The next rounds' distributions, plus drawn matchups that occurred often enough."""
    fixtures = []
    for i, meta in enumerate(acc.fx_meta):
        if not meta.get("next", True):
            continue
        row = {**_match_row({k: v for k, v in meta.items() if k != "next"}, acc.fx_counts[i]),
               "h2h": meta.get("h2h", []), **_projected_extras(acc, i)}
        if not row["n"]:
            continue
        # Preserve the existing fixed-point tally; this changes no simulated world or odds.
        # Last row/column are MAXG-1 or more, not exact scores at that boundary.
        row["score_counts"] = acc.fx_counts[i].tolist()
        row["score_cap"] = MAXG - 1
        whatif = whatif_payload(acc, i)
        if whatif is not None:
            row["whatif"] = whatif
        fixtures.append(row)
    matchups = []
    for (comp, stage, home, away), tbl in acc.matchups.items():
        if int(tbl.sum()) < MIN_MATCHUP:
            continue
        matchups.append(_match_row({"competition": comp, "stage": stage,
                                    "home": home, "away": away,
                                    "score_basis": "90min"}, tbl))
    matchups.sort(key=lambda m: -m["n"])
    return {"worlds": acc.worlds, "fixtures": fixtures, "matchups": matchups,
            "matchups_seen": len(acc.matchups), "min_matchup": MIN_MATCHUP}


def _round_ratings(comp: str, a: Dict[str, Any], hist: Optional[Dict[str, Any]]
                   ) -> Dict[str, Any]:
    """A block's ratings at every index of its Gameweek view: index r - 1 going into round r,
    `rounds` after the last. A round already started carries the REAL ratings as of its start
    (`rating_history`); a later one, each side's state over the worlds going into its match in
    that round -- Elo's mean and SD, ATT's and DEF's geometric mean and the SD of their logs
    (`_lsd`). A side whose match there no world simulated -- played early in reality -- takes
    today's, with no spread.

    ATT and DEF are on the COMPETITION's own scale (`npxg_scale(..., comp)`): a real round's from
    that day's fit against that day's average side here; a projected round's are the worlds'
    five-league geometric means moved by today's `comp_shift`, which is exact for a geometric
    mean, so the accumulator's sums need no second scale."""
    if hist is None or comp not in hist["days"]:
        return {}
    days, cutoff, now = hist["days"][comp], hist["cutoff"], hist["fits"][hist["cutoff"]]
    scales = hist.get("scales") or {}
    own = comp in scales.get(cutoff, {})
    ka, kd = comp_shift(scales[cutoff][comp], scales[cutoff]["_all"]) if own else (0.0, 0.0)
    width = a["rounds"] + 1
    if len(days) != width:
        return {}
    keys = ("elo", "att", "def")
    spreads = ("elo_sd", "att_lsd", "def_lsd")
    out: Dict[str, Any] = {k: [] for k in keys + spreads}
    real = [d <= cutoff for d in days]
    fx_pt = np.array(RATING_SCALE, float)
    for i, team in enumerate(a["teams"]):
        rows = {k: [] for k in out}
        for at in range(width):
            n = int(a["st_n"][i, at])
            if real[at] or not n:
                day = days[at] if real[at] else cutoff
                src = hist["fits"][day]
                e, q, t, att, dfn, _, _ = src.get(team, now.get(team, (np.nan,) * 7))
                if own and np.isfinite(q):
                    att, dfn = (float(x) for x in to_npxg(scales[day][comp], q, t))
                vals = [e, att, dfn]
                sds = [None, None, None]
            else:
                m = a["st"][:3, i, at] / n
                var = np.maximum(a["st"][3:, i, at] / n - m * m, 0.0)
                m, sd = m / fx_pt, np.sqrt(var) / fx_pt
                vals = [m[0], np.exp(m[1] + ka), np.exp(m[2] + kd)]
                sds = list(sd)
            for k, sk, v, sd, dp in zip(keys, spreads, vals, sds, (1, 3, 3)):
                rows[k].append(None if v is None or not np.isfinite(v) else round(float(v), dp))
                rows[sk].append(None if sd is None else round(float(sd), dp))
        for k in out:
            out[k].append(rows[k])
    return {"rating_days": [str(d.date()) for d in days], "rating_real": real,
            "rating_scale": "competition" if own else "five leagues", **out}


def gw_payload(acc: "Accumulator", hist: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Per league, and per UEFA league phase: each side's mean W, D, L, GF and GA after every
    round, its matches played, every fixture -- the result if it has been played, its
    distribution if not -- and its ratings at every round (`_round_ratings`). What the page's
    Gameweek and Matchday views build their tables from; `gw.json` beside the snapshot."""
    n = max(acc.worlds, 1)

    def block(comp: str, a: Dict[str, Any], kind: str) -> Dict[str, Any]:
        mean = np.round(a["gw"] / n, 2)
        fixtures = list(a["results"])
        for i, m in enumerate(acc.fx_meta):
            if m["competition"] != comp or m["kind"] != kind or m["round"] is None:
                continue
            row = _match_row(m, acc.fx_counts[i])
            if row.get("n"):
                # version 10: the likeliest scores and the stakes. Its xG and expected goals are
                # the round's steps in each side's run totals (`xgf`, `gf`), so are not repeated
                fixtures.append({"round": m["round"], "kickoff": row["kickoff"],
                                 "home": m["home"], "away": m["away"], "ladder": row["ladder"],
                                 "cs_h": row["cs_h"], "cs_a": row["cs_a"], "n": row["n"],
                                 "top": row["top"][:3], "h2h": m.get("h2h", []),
                                 **_projected_extras(acc, i)})
        fixtures.sort(key=lambda f: (f["round"], f["kickoff"]))
        gx = np.round(a["gx"] / (1000.0 * n), 2) if "gx" in a else None
        out = {"rounds": a["rounds"], "teams": list(a["teams"]), "pl": a["pl"].tolist(),
               **{k: mean[j].tolist() for j, k in enumerate(("w", "d", "l", "gf", "ga"))},
               # xG for, against and xG points after each round (`Accumulator._xg_tally`)
               **({k: gx[j].tolist() for j, k in enumerate(("xgf", "xga", "xgpts"))}
                  if gx is not None and a["gx"].any() else {}),
               "fixtures": fixtures, **_round_ratings(comp, a, hist),
               # what a projected fixture's `stakes` are, in order (`Accumulator._stakes`)
               "stakes_of": STAKES[kind]}
        # when it was decided: per side, the rounds with any chance -- [team index, round, p]
        for key in ("clinch", "down"):
            if key in a:
                ii, rr = np.nonzero(a[key])
                out[key] = [[int(i), int(r), round(float(a[key][i, r] / n), 4)]
                            for i, r in zip(ii, rr)]
        return out

    return {"worlds": acc.worlds,
            "leagues": {c: block(c, a, "league") for c, a in sorted(acc.leagues.items())
                        if a["rounds"]},
            "phases": {c: block(c, a, "uefa") for c, a in sorted(acc.phases.items())
                       if a["rounds"]}}


def real_reference(master: pd.DataFrame,
                   competitions: Optional[List[str]] = None) -> Dict[str, Any]:
    """The same summary in reality, so the match panel has something to miss by.

    Restricted to the competitions the run contains: the Bundesliga scores ~27% above Serie A, so
    pooling all fourteen would make the comparison meaningless. Still every season against one, so
    it is a level check rather than a calibration test.
    """
    p = master[master.played & master.home_goals.notna()]
    if competitions is not None:
        p = p[p.competition.isin(competitions)]
    hg = pd.to_numeric(p.home_goals).to_numpy(int)
    ag = pd.to_numeric(p.away_goals).to_numpy(int)
    hist = np.bincount(np.clip(hg + ag, 0, 15), minlength=16).astype(float)
    n = max(hist.sum(), 1)
    return {"matches": int(n), "competitions": int(p.competition.nunique()),
            "goal_dist": [round(float(x / n), 4) for x in hist[:9]],
            "over25": round(float(hist[3:].sum() / n), 4),
            "outcome": [round(float(np.mean(hg > ag)), 4), round(float(np.mean(hg == ag)), 4),
                        round(float(np.mean(hg < ag)), 4)],
            "mean_goals": round(float((hist * np.arange(16)).sum() / n), 3)}


# --------------------------------------------------------------------------- the run
def build_handovers(engine: Engine, fx: pd.DataFrame, params: Dict[str, Any]
                    ) -> Tuple[Dict[Any, Any], List[str]]:
    """Where each UEFA knockout is taken over, and which ones could not be.

    With `replay_played` the real draw is honoured as far as it goes. Without it the whole season
    is being re-sampled, so the real draw cannot be reused -- it was made from standings this
    world does not have -- and every stage is re-drawn (`redraw_handover`).
    """
    if params["replay_played"]:
        return uefa_handovers(fx, engine.master, np.random.default_rng(params["seed"])), []
    hands, skipped = {}, []
    for (comp, season), g in fx[fx.kind == "uefa"].groupby(["competition", "season"]):
        prev = engine.master[(engine.master.competition == comp)
                             & (engine.master.season == season - 1)]
        try:
            hands[(comp, season)] = redraw_handover(g, prev if not prev.empty else None)
        except (NotImplementedError, ValueError) as exc:
            skipped.append(f"{comp}: {exc}")
    return hands, skipped


def as_of_fixtures(fx: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """Retained season calendar with results after `as_of` removed.

    This reconstructs ratings/results at a cutoff. Retained pairings and kickoff revisions are
    not proof of the exact calendar originally published on that date.
    """
    cut = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    fx = fx.copy()
    future = fx.kickoff >= cut
    fx.loc[future, "played"] = False
    fx.loc[future, "has_npxg"] = False
    for col in ("home_goals", "away_goals", "home_npxg", "away_npxg", "outcome", "minutes"):
        if col in fx.columns:
            fx.loc[future, col] = np.nan
    return fx


_WORKER: Dict[str, Any] = {}


def _worker_init(params: Dict[str, Any]) -> None:
    """Each process builds the engine and the season fit once, then reuses them for its chunks."""
    engine = Engine()
    _WORKER["engine"] = engine
    _WORKER["prep"] = prepare_for(engine, params)
    fx = _WORKER["prep"]["fixtures"]
    _WORKER["fx"] = fx
    # handovers are seeded from params["seed"], so every process derives the same calendar
    _WORKER["hands"], _WORKER["skipped"] = build_handovers(engine, fx, params)
    _WORKER["cups"] = cup_handovers(fx, engine.master, np.random.default_rng(params["seed"]))
    _WORKER["unseen"] = unseen_for(_WORKER["prep"], fx, params)
    _WORKER["track"], _WORKER["next"] = tracked_fixtures(fx, params.get("match_rounds",
                                                                        MATCH_ROUNDS))
    _WORKER["stages"] = first_pending_stages(_WORKER["hands"], match_horizon(fx))
    _WORKER["params"] = params


def _worker_chunk(bounds: Tuple[int, int]) -> "Accumulator":
    lo, hi = bounds
    p = _WORKER["params"]
    acc = Accumulator(_WORKER["fx"], _WORKER["track"], _WORKER["stages"], _WORKER["next"],
                      places=_WORKER["prep"].get("places"), scale=_WORKER["prep"].get("scale"),
                      pen_xg=_WORKER["prep"].get("pen_xg"),
                      race_competition="English Premier League",
                      route_competition="English Premier League")
    for i in range(lo, hi):
        acc.add(_simulate_world(_WORKER, p, i), world_index=i)
    return acc


def _simulate_world(ctx: Dict[str, Any], params: Dict[str, Any], i: int) -> pd.DataFrame:
    prep = ctx["prep"]
    return simulate(ctx["fx"], prep["model"], prep["calib"], prep["elo0"],
                    np.random.default_rng(params["seed"] * 1_000_003 + i),
                    **world_kwargs(prep, params),
                    master=ctx["engine"].master, handovers=ctx["hands"],
                    cups=ctx.get("cups"), unseen=ctx.get("unseen"))


def world_kwargs(prep: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Everything `simulate` takes from a run's parameters and its fit, in one place, so the
    serial and parallel paths cannot drift apart."""
    return {"drift_per_day": params["drift"], "npxg_gain": params["npxg_gain"],
            "feedback": params["elo_feedback"], "npxg_feedback": params["npxg_feedback"],
            "tilt_feedback": params.get("tilt_feedback", DEFAULTS["tilt_feedback"]),
            "q_half_life": params.get("q_half_life", DEFAULTS["q_half_life"]),
            "start_noise": params.get("start_noise", DEFAULTS["start_noise"]),
            "replay_played": params["replay_played"], "goals": prep["goals"],
            "live_from": prep["live_from"], "seed_elo": prep["seed_elo"]}


def run_projection_parallel(params: Dict[str, Any], processes: int,
                            progress: Optional[Callable[[int, int, str], None]] = None,
                            engine: Optional[Engine] = None) -> Dict[str, Any]:
    """The same run, split across processes. Worlds are independent, so this is exact.

    Each world's seed is `seed * 1_000_003 + i` regardless of which process draws it, so the
    result does not depend on the process count -- 8 processes and 1 give the same numbers.
    Accumulators merge by summing counts, which is why the points histogram replaced the sample
    list: merging lists of 100,000 arrays would cost more than the simulation.
    """
    import multiprocessing as mp

    started = time.time()
    n = params["worlds"]
    chunk = max(1, min(50, n // (processes * 4) or 1))
    bounds = [(i, min(i + chunk, n)) for i in range(0, n, chunk)]
    if progress:
        progress(0, n, "fitting")
    ctx = mp.get_context("spawn")
    # An empty accumulator to merge the workers' results into. It must carry every column
    # `Accumulator.__init__` touches, or the constructor raises on a frame with no rows -- which
    # is how a missing "round" broke the parallel path while the serial one was fine.
    total = Accumulator(pd.DataFrame({c: [] for c in
                                      ("kind", "competition", "home", "away", "played",
                                       "round", "season", "kickoff", "home_goals",
                                       "away_goals")}), pd.Index([]), set())
    done = 0
    pool = ctx.Pool(processes, initializer=_worker_init, initargs=(params,))
    try:
        chunks = pool.imap_unordered(_worker_chunk, bounds)
        # the real ratings at every round already started: ~20 fits, made here while the
        # workers simulate, so they cost the run nothing it would not spend waiting
        engine = engine or Engine()      # reuse the caller's if it has one; loading costs ~0.5s
        hist = rating_history(engine, params)
        for acc in chunks:
            total.merge(acc)
            done += acc.worlds
            if progress:
                progress(done, n, "simulating")
        # close() then join() rather than letting the context manager terminate(): workers can
        # still be mid-`put` when the last result arrives, and tearing the queues down under them
        # prints a BrokenPipeError and a leaked-semaphore warning into the nightly log for a run
        # that in fact succeeded.
        pool.close()
        pool.join()
    finally:
        pool.terminate()
    fx = prepare_for(engine, params)["fixtures"]
    out = total.result()
    _finish(out, engine, fx, params, started, *build_handovers(engine, fx, params))
    out["processes"] = processes
    _add_head_to_head(total, engine.master, prepare_for(engine, params)["cutoff"])
    out["matches"] = match_payload(total)
    out["gw"] = gw_payload(total, hist)
    out["paths"] = paths_payload(total)
    return out


def run_projection(engine: Engine, params: Dict[str, Any],
                   progress: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
    """N worlds of one season, reduced to the dashboard payload."""
    started = time.time()
    if progress:
        progress(0, params["worlds"], "fitting")
    prep = prepare_for(engine, params)
    fx = prep["fixtures"]
    hands, skipped = build_handovers(engine, fx, params)
    cups = cup_handovers(fx, engine.master, np.random.default_rng(params["seed"]))
    unseen = unseen_for(prep, fx, params)
    if progress:
        progress(0, params["worlds"], "simulating")
    track, nxt = tracked_fixtures(fx, params.get("match_rounds", MATCH_ROUNDS))
    acc = Accumulator(fx, track, first_pending_stages(hands, match_horizon(fx)), nxt,
                      places=prep.get("places"), scale=prep.get("scale"),
                      pen_xg=prep.get("pen_xg"), race_competition="English Premier League",
                      route_competition="English Premier League")
    for i in range(params["worlds"]):
        sim = simulate(fx, prep["model"], prep["calib"], prep["elo0"],
                       np.random.default_rng(params["seed"] * 1_000_003 + i),
                       **world_kwargs(prep, params),
                       master=engine.master, handovers=hands, cups=cups, unseen=unseen)
        acc.add(sim, world_index=i)
        if progress:
            progress(i + 1, params["worlds"], "simulating")
    out = acc.result()
    _finish(out, engine, fx, params, started, hands, skipped)
    out["processes"] = 1
    _add_head_to_head(acc, engine.master, prep["cutoff"])
    out["matches"] = match_payload(acc)
    out["gw"] = gw_payload(acc, rating_history(engine, params))
    out["paths"] = paths_payload(acc)
    return out


def _finish(out: Dict[str, Any], engine: Engine, fx: pd.DataFrame, params: Dict[str, Any],
            started: float, hands: Dict[Any, Any], skipped: List[str]) -> None:
    """Everything the payload carries besides the distributions themselves."""
    prep = prepare_for(engine, params)
    # each side's next five, scored for an average side of its competition (`run_in`)
    ri = run_in(prep, fx)
    for block in out["leagues"] + out["uefa"]:
        r = ri.get(block["competition"])
        if not r:
            continue
        block["difficulty_cuts"] = r["cuts"]
        for t in block["teams"]:
            t["next5"] = r["teams"].get(t["team"], [])
    # each side's real npxG for and against in the competition, and what its xG would have
    # earned (`real_rates`): the Visualisations view's "to date" charts
    for kind, blocks in (("league", out["leagues"]), ("uefa", out["uefa"])):
        for block in blocks:
            rr = real_rates(fx, block["competition"], kind)
            for t in block["teams"]:
                if t["team"] in rr:
                    t["real"] = rr[t["team"]]
    out["ratings"] = ratings_payload(prep, rating_history(engine, params))
    out["real"] = real_reference(engine.master[engine.master.kickoff < prep["cutoff"]],
                                 sorted(fx.competition.unique().tolist()))
    out["params"] = params
    out["skipped"] = skipped
    out["elapsed"] = round(time.time() - started, 1)
    fitted = (prep["cutoff"] - pd.Timedelta(days=1)).date()
    out["note"] = (f"{len(fx)} fixtures, {int(fx.played.sum())} already played; model fitted "
                   f"through {fitted} on {prep['train']} matches, every world starting there; "
                   f"season-start Elo as of {prep['asof']} for {prep['elo_teams']} teams; "
                   f"{len(prep['rating_inputs']['assumed'])} explicit assumed starts")
    out["fitted_through"] = str(fitted)
    out["rating_inputs"] = prep["rating_inputs"]
    out["as_of"] = params.get("as_of") or (str(fx[fx.played].kickoff.max().date()) if fx.played.any() else None)
    out["mc_se_pp"] = round(float(100 * np.sqrt(0.25 / max(out["worlds"], 1))), 3)
    out["handover"] = [
        {"competition": c, "season": s,
         "settled": sorted(h.settled_ties, key=STAGE_ORDER.index),
         "playing": [{"label": sp.label, "drawn": sp.ties is not None,
                      "leg1": str(sp.leg1.date())} for sp in h.specs],
         "coin_flipped": h.coin_flipped}
        for (c, s), h in hands.items()]
    # A cup we KNOW about but could not run, and why. This is deliberately reported rather than
    # left as an absence: a competition silently missing from the page is indistinguishable from
    # one we forgot, and the three cups here went the other way for weeks -- a stale hand-made
    # fixture file stood in for a competition that had not been drawn, and the page showed eight
    # invented ties as though they were the round of 16. Saying "not under way" is the honest
    # state, and it becomes a real tab on the night Fotmob returns the draw.
    ran = {c["competition"] for c in out.get("cups", [])}
    pending = []
    for comp in sorted(CUP_RULES):
        if comp in ran:
            continue
        g = fx[(fx.competition == comp) & (fx.season == params["season"])]
        if g.empty:
            why = "no fixtures for this season yet — the draw has not been made"
        elif bool(g["played"].all()):
            why = "already complete"
        else:
            why = f"{len(g)} fixtures, but no round could be taken over"
        pending.append({"competition": comp, "reason": why})
    out["cups_pending"] = pending
