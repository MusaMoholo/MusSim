#!/usr/bin/env python3
"""Season simulation with per-world state propagation, calibrated against real dispersion.

The problem this solves. Sharp single-match probabilities are NOT sufficient for a believable
season: holding every team's strength fixed for a year leaves only Poisson sampling noise, and
measured over 15 real league-seasons that produces final-points spreads 13% too narrow
(ratio 0.868). Every simulated table clusters too tightly around its starting ratings, so a title
favourite essentially never collapses.

Real seasons carry extra variance because strength MOVES -- the ~140-day half-life on Q measured
in scripts/backtest_qt.py, plus managers, injuries and form runs. So each world starts from the
fit through the data cutoff (`projection.Engine.prepare`) and carries its own mutable state from
there, updated match by match. A match is drawn in two stages -- each side's npxG from the state,
then the goals from that npxG (`sample_goals`) -- and then moves:

    rating   <- Elo update from the result (K=19.58, home_adv 70 domestic / 80 UEFA, win-draw-
                loss only: the published series ignores margin, and margin already reaches the
                model through npxG)
    Q        <- npxG created minus conceded against expectation (the dominant channel), plus the
                result against the world's own expected points
    T        <- npxG created plus conceded against expectation: open games tilt towards attack
    drift    <- an optional exogenous random walk on Q, for the part of strength movement that
                results do not explain

The three strength channels keep the ratios of the fitted model's own response to one match
(analysis/tilt_response.py), and every surprise averages zero under the world's own draw, so no
side drifts in expectation. One overall gain is calibrated so simulated seasons spread like real
ones AND carry a good or bad first half into the second as real ones do (analysis/
calibrate_drift3.py): a simulated season should be statistically indistinguishable from a real one.

UEFA KNOCKOUTS ARE BUILT, NOT READ. A UEFA season's fixture list stops at the league phase until
the draw is made, so simulating past January means deriving the bracket. `uefa_bracket.py` holds
the seeding and draw constraints (verified against six real 36-team knockouts) and this module
runs them. Three properties are worth stating because each was a bug first:

  * A knockout leg goes through the SAME `_World.play` as a league match, so it ages state, moves
    Elo and Q, and lands in the output. A March quarter-final therefore reflects the world's own
    February rather than the January ratings.
  * The two legs of a tie are separate calendar events, interleaved with domestic fixtures in
    kickoff order, so strength moves between them.
  * The simulator takes over at a HANDOVER point, not at a fixed date: stages already drawn and
    played are replayed from the fixture list and only seed the next draw, so a run started in
    March keeps the real play-off and R16 results and draws the quarter-finals onward.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.attack_defence_qt import NPXG_ELO_SLOPE, NPXG_PHI, R_CLIP  # noqa: E402
from scripts.backtest_qt import score_matrix  # noqa: E402
from scripts.elo_engine import expected_home  # noqa: E402
from scripts.knockout import (  # noqa: E402
    ET_FRACTION, resolve_single_leg, resolve_two_legs,
)
from scripts.cup_bracket import (  # noqa: E402
    CupHandover, CupRound, cup_handovers, draw_round, is_slot, resolve_slot,
)
from scripts.uefa_bracket import (  # noqa: E402
    Handover, StageSpec, draw_stage, knockout_handover, league_phase_table, split_phases,
)

ELO_TO_Q = NPXG_ELO_SLOPE / 200.0     # a 1-point Elo move is this much Q (see attack_defence_qt)
K_ELO, HOME_ADV, UEFA_HOME_ADV = 19.58, 70.0, 80.0
Q_HALF_LIFE = 140.0           # the fitted Q half-life -- of EVIDENCE in the estimator, see `_age`
T_DECAY = np.log(2) / 1460.0  # and T's
# The feedback a world applies after a match is the ESTIMATOR'S OWN response to it, read off by
# refitting with one synthetic match appended (analysis/tilt_response.py), times one factor --
# `npxg_gain` relative to Q_GAIN_FIT -- calibrated so simulated seasons spread like real ones.
# Per unit of surprise: Q 0.0260 on npxG (created minus conceded, against expectation), T 0.0047
# on npxG (created plus conceded), and Q 0.0176 on the result (points against the world's own
# expectation; 0.297 of a rating move reaches Q through the prior). Dispersion can only see the
# overall scale -- T changes how a side gets its goal difference, not its size -- so the three
# keep the estimator's ratios.
Q_GAIN_FIT = 0.0260
TILT_RATIO = 0.18
RESULT_RATIO = 0.68
# The calibrated defaults (analysis/calibrate_drift3.py, 15 league-seasons). A world starts from a
# draw around the fit at its posterior SD, then moves at the estimator's own gain, and its moves
# never fade: spread of final points 1.004 against real, and a side's first-half residual carries
# into its second half at +0.41 against +0.38 real (se 0.05). Nothing here is tuned. Letting moves
# fade cannot match both: at the 140-day half-life the spread is right at gain 0.06 but the
# carry-over is +0.28, two standard errors short.
DEFAULT_GAIN = Q_GAIN_FIT
DEFAULT_HALF_LIFE: Optional[float] = None
DEFAULT_START_NOISE = 1.0
# How a drawn match is drawn, per kind of match (analysis/match_shock.py, 9,958 walk-forward
# matches): (sigma, phi_w, rho).
#   sigma  a one-match shock to the strength gap -- who turned up, rotation, game state -- that
#          moves the two sides' expected npxG apart or together for that match only. It is what
#          makes their npxG surprises correlate negatively (-0.061 league, -0.159 UEFA, -0.251
#          cup), net of the part the posterior start draw already explains.
#   phi_w  the within-match Gamma dispersion of npxG, below the walk-forward 0.36-0.62 because
#          the start draw and the shock carry the rest; with them the marginal matches.
#   rho    Dixon-Coles on the second stage, fitted per kind on the 90-minute result. UEFA draws
#          less than a domestic match of the same balance (19.9% real against 22.7% at the league
#          rho), cups and leagues more.
MATCH_DRAW: Dict[str, Tuple[float, float, float]] = {
    "league": (0.15, 0.34, -0.15),
    "uefa": (0.40, 0.34, 0.05),
    "cup": (0.60, 0.46, -0.10),
}
GOAL_RHO = MATCH_DRAW["league"][2]

OUT_COLS = ["competition", "season", "phase", "kickoff", "stage", "leg", "fixture_id", "home",
            "away", "home_goals", "away_goals", "minutes", "neutral", "sampled",
            "home_npxg", "away_npxg"]
# `fixture_id` is the row's label in the master table, or -1 for a knockout leg the simulator drew
# itself. It is what lets a caller pool 10,000 worlds of ONE fixture: a scheduled match is the
# same match in every world, whereas a drawn tie is only a matchup that happened to occur.
# `sampled` separates a drawn scoreline from a replayed real one. Without it a goal-count summary
# over a part-played season silently mixes the model's distribution with reality's.
# `home_npxg`/`away_npxg` are the npxG the world drew for the match -- the thing its goals were
# drawn from and its strength moved on -- or the real npxG of a replayed one.
#
# Each row's RATINGS ride beside it, not in it: `result.attrs["state"]` is a float array, one row
# per output row, holding each side's (Elo, Q, T) going into the match and coming out of it, in
# STATE_COLS order. A world's ratings are its own -- the reason a side can collapse in one world
# and not another -- and this is the only place they leave the world. A replayed real result
# carries NaN: before the cutoff a world's state is today's fit, not what it was then.
STATE_COLS = ["home_elo", "home_q", "home_t", "away_elo", "away_q", "away_t",
              "home_elo_after", "home_q_after", "home_t_after",
              "away_elo_after", "away_q_after", "away_t_after"]
_NO_STATE = [np.nan] * len(STATE_COLS)


def _phase_of(row) -> str:
    """`round` is populated only for a league phase, so a UEFA or cup row without one is a
    knockout leg. Kept in one place because the seeding reads this column."""
    return "knockout" if pd.isna(row.round) and row.kind in ("uefa", "cup") else "league"


def sample_scoreline(rng, lam_h, lam_a, rho=-0.10):
    """Draw from the Dixon-Coles-corrected joint distribution, not two independent Poissons.

    Inverse-CDF rather than `rng.choice(p=...)`: same distribution, and `choice` normalises and
    validates the 169-cell vector on every call, which a season of 2,300 matches per world feels.
    """
    M = score_matrix(np.array([lam_h]), np.array([lam_a]), rho)[0]
    cum = np.cumsum(M.ravel())
    idx = int(np.searchsorted(cum, rng.random() * cum[-1]))
    return divmod(min(idx, M.size - 1), M.shape[1])


def expected_points(lam_h: float, lam_a: float, rho: float = GOAL_RHO) -> float:
    """P(home win) + P(draw)/2 at expected goals (lam_h, lam_a): what the result channel measures
    a result against. The world's OWN expectation, not Elo's -- against Elo's, a side the rating
    under-rates out-performs it on average, and its strength drifts up every match on a rating
    that is merely catching up.

    Read off a precomputed grid by bilinear interpolation: it is asked ~5,000 times a world, and
    building a score matrix each time was a third of the runtime. Agrees with the direct
    Dixon-Coles computation to ~1e-4 (pinned in smoke)."""
    g = _ep_grid(rho)
    x = min(max(lam_h, 0.0), _EP_MAX) / _EP_STEP
    y = min(max(lam_a, 0.0), _EP_MAX) / _EP_STEP
    i, j = min(int(x), g.shape[0] - 2), min(int(y), g.shape[1] - 2)
    fx, fy = x - i, y - j
    return float((g[i, j] * (1 - fx) + g[i + 1, j] * fx) * (1 - fy)
                 + (g[i, j + 1] * (1 - fx) + g[i + 1, j + 1] * fx) * fy)


_EP_STEP, _EP_MAX, _EP_CACHE = 0.02, 8.0, {}


def _ep_grid(rho: float) -> np.ndarray:
    """Expected home points over a (lam_h, lam_a) grid, Dixon-Coles corrected, built once."""
    if rho not in _EP_CACHE:
        lam = np.arange(0.0, _EP_MAX + 2 * _EP_STEP, _EP_STEP)
        lam[0] = 1e-6
        k = np.arange(25)
        lf = np.cumsum(np.r_[0.0, np.log(np.arange(1, 25))])
        P = np.exp(-lam[:, None] + k * np.log(lam)[:, None] - lf)          # (n, 25) pmfs
        C = np.cumsum(P, axis=1)
        below = np.c_[np.zeros(len(lam)), C[:, :-1]]                        # P(X <= k-1)
        win, draw = P @ below.T, P @ P.T
        p0, p1 = P[:, 0], P[:, 1]
        d00 = np.outer(p0, p0) * (-np.outer(lam, lam) * rho)
        d01 = np.outer(p0, p1) * (lam[:, None] * rho)                      # home 0, away 1
        d10 = np.outer(p1, p0) * (lam[None, :] * rho)                      # home 1, away 0
        d11 = np.outer(p1, p1) * (-rho)
        total = win + draw + (P @ below.T).T + d00 + d01 + d10 + d11
        _EP_CACHE[rho] = (win + d10 + 0.5 * (draw + d00 + d11)) / total
    return _EP_CACHE[rho]


def _gmean(layer: Dict[str, Any], competition: str, x: float, mu: float) -> float:
    """`attack_defence_qt.goal_mean` for one value, without numpy's per-call overhead."""
    return max(layer["c0"].get(competition, layer["c0_mean"]) + layer["c1"] * x
               + layer["c2"] * mu, 0.02)


def _gdisp(layer: Dict[str, Any], x: float) -> float:
    """`attack_defence_qt.goal_dispersion` for one value."""
    return min(max(layer["r"][0] + layer["r"][1] * x, R_CLIP[0]), R_CLIP[1])


def draw_npxg(rng, mu_h: float, mu_a: float, kind: str = "league") -> Tuple[float, float]:
    """The first stage of a match: each side's npxG, given the state's expectation, through the
    match-day shock and the within-match Gamma (`MATCH_DRAW`). Mean-preserving: E[npxG] = mu."""
    sigma, phi, _ = MATCH_DRAW.get(kind, MATCH_DRAW["league"])
    if sigma:
        eps = rng.normal(0.0, sigma)
        c = sigma * sigma / 8.0
        mu_h, mu_a = mu_h * np.exp(eps / 2 - c), mu_a * np.exp(-eps / 2 - c)
    return (float(rng.gamma(max(mu_h, 1e-6) / phi, phi)),
            float(rng.gamma(max(mu_a, 1e-6) / phi, phi)))


def sample_goals(rng, m_h: float, m_a: float, r_h: float, r_a: float,
                 rho: float = GOAL_RHO) -> Tuple[int, int]:
    """The second stage of a match: goals given the npxG each side produced.

    Each side's goals are a binomial with mean m and variance r*m -- underdispersed, because a sum
    of shot probabilities is (see `attack_defence_qt.fit_goal_layer`) -- and the pair takes the
    Dixon-Coles low-score correction by rejection: draw, then accept with probability tau/max tau.
    That is exact for the corrected distribution and costs ~1.05-1.1 draws on average at the rho
    values in `MATCH_DRAW`.
    """
    n_h = max(int(round(m_h / (1.0 - r_h))), int(np.ceil(m_h)) + 1)
    n_a = max(int(round(m_a / (1.0 - r_a))), int(np.ceil(m_a)) + 1)
    p_h, p_a = m_h / n_h, m_a / n_a
    if rho == 0.0:
        return int(rng.binomial(n_h, p_h)), int(rng.binomial(n_a, p_a))
    tau = {(0, 0): 1.0 - m_h * m_a * rho, (0, 1): max(1.0 + m_h * rho, 0.0),
           (1, 0): max(1.0 + m_a * rho, 0.0), (1, 1): 1.0 - rho}
    top = max(1.0, *tau.values())
    while True:
        gh, ga = int(rng.binomial(n_h, p_h)), int(rng.binomial(n_a, p_a))
        if rng.random() * top <= tau.get((gh, ga), 1.0):
            return gh, ga


# --------------------------------------------------------------------------- one world's state
class _World:
    """Mutable per-world strength state, plus the one code path that plays a match.

    Every match -- league, cup, UEFA league phase, UEFA knockout leg -- goes through `play`, so a
    knockout cannot silently skip state propagation.

    WHERE A WORLD STARTS. With `live_from` set, the model was fitted on everything played before it
    and `elo0` is every side's rating at it (`elo_walk`), so the past is already in the state: a
    played match is recorded but moves nothing, and every world reaches `live_from` identical --
    today's fit, today's ratings. From there each world moves on its own draws. Without
    `live_from` (a season re-sampled from its start, as calibration does) every event is live, and
    a replayed result moves the state exactly as a drawn one would.

    WHAT A MATCH MOVES. A drawn match has two stages: each side's npxG from the current state,
    then the goals from that npxG (`sample_goals`, when a goal layer is given). The RESULT moves the
    Elo rating -- win/draw/loss against Elo's expectation, the published rule. Strength moves on
    three surprises, each zero on average under the world's own draw, with the estimator's ratios:

      Q  += gain * (e_for - e_against)            e = npxG - expected npxG, in npxG
      T  += gain * TILT_RATIO * (e_for + e_against)   an open game tilts both sides to attack
      Q  += gain * RESULT_RATIO * (points - expected points), the world's expectation

    A side that loses while winning the npxG drops in rating but gains, or barely loses, strength;
    a side outplayed and beaten drops in both.

    Zero on average matters. The log ratio log(npxG/mu) used before averages below zero, the more
    so the lower mu, so favourites gained strength in every world and underdogs lost it -- a
    systematic spread the dispersion calibration then absorbed (analysis/tilt_response.py).
    """

    def __init__(self, model: Dict[str, Any], calib: Dict[str, Any], elo0: Dict[str, float], rng, *,
                 drift_per_day: float, feedback: bool, npxg_feedback: bool, npxg_gain: float,
                 rho: float, unseen=None, goals: Optional[Dict[str, Any]] = None,
                 live_from: Optional[pd.Timestamp] = None, tilt_feedback: bool = True,
                 q_half_life: Optional[float] = DEFAULT_HALF_LIFE,
                 seed_elo: Optional[float] = None, calendar: bool = True,
                 start_noise: float = DEFAULT_START_NOISE):
        self.model, self.calib, self.rng, self.rho = model, calib, rng, rho
        self.drift_per_day, self.feedback = drift_per_day, feedback
        self.npxg_feedback, self.npxg_gain = npxg_feedback, npxg_gain
        self.tilt_feedback, self.tilt_gain = tilt_feedback, TILT_RATIO * npxg_gain
        self.result_gain = RESULT_RATIO * npxg_gain
        self.q_decay = 0.0 if q_half_life is None else np.log(2) / q_half_life
        self.goals, self.live_from, self.use_calendar = goals, live_from, calendar
        self.Q: Dict[str, float] = dict(model["Q"])
        self.T: Dict[str, float] = dict(model["T"])
        # `start_noise` > 0 starts the world from a DRAW around the fit, at that multiple of each
        # estimate's posterior SD, instead of the point estimate itself: the world's truth is not
        # the model's best guess at it, and the gap persists all season, as a real one does.
        self.start_noise = start_noise if (start_noise > 0 and rng is not None
                                           and "q_sd" in model) else 0.0
        if self.start_noise:
            teams = model["teams"]
            zq, zt = rng.standard_normal(len(teams)), rng.standard_normal(len(teams))
            for i, t in enumerate(teams):
                self.Q[t] += self.start_noise * model["q_sd"][t] * zq[i]
                self.T[t] += self.start_noise * model["t_sd"][t] * zt[i]
        self.elo: Dict[str, float] = dict(elo0)
        self.q_shift: Dict[str, float] = {}
        self.t_shift: Dict[str, float] = {}
        self.last_day: Dict[str, pd.Timestamp] = {}
        self.base_mean = float(np.mean(list(model["base"].values())))
        self.home_mean = float(np.mean(list(model["home"].values())))
        # the default for a side nobody rates is set from the sides ClubElo rates, before any
        # Opta start is merged in, so it means what it always meant. A world started mid-season
        # is handed it, since its `elo0` is the walk's ratings, not ClubElo's.
        self.seed_elo = (float(seed_elo) if seed_elo is not None else
                         float(np.percentile(list(elo0.values()), 5)) if elo0 else 1400.0)
        # Sides we do not see every match of keep moving between their appearances: see
        # `scripts/opta_ratings.py` and `_anchors`/`_calendar` below. Without the artefact, none
        # of this runs. Their Opta history is part of the start a mid-season world is handed, so
        # only the calendar of unseen matches after it is left to play.
        self.unseen = unseen
        self._anchor_at: Dict[str, int] = {}
        self._anchor_base: Dict[str, float] = {}
        self._calendar_at: Dict[str, int] = {}
        if unseen is not None:
            for team, v in unseen.start.items():
                self.elo.setdefault(team, v)
            if live_from is not None:
                self._anchor_at = {t: len(a[0]) for t, a in unseen.anchors.items()}
        self.rows: List[List[Any]] = []
        self.state_rows: List[List[float]] = []      # STATE_COLS, one per row
        self.score90_rows: List[List[float]] = []    # regulation goals, before extra time
        # `apply_goal_calibration` takes a fixtures frame, so calling it per match meant building
        # a one-row DataFrame ~2,300 times per world -- 40% of the runtime, all pandas overhead.
        # The mapping is just (alpha, beta) per competition, so hoist it into a dict lookup. The
        # arithmetic below is identical, and `test_calibration_agrees` pins it to the vectorised
        # function at 1e-12.
        self._cal: Dict[str, Tuple[float, float]] = dict(calib)
        self._cal_default = ((float(np.mean([v[0] for v in calib.values()])),
                              float(np.mean([v[1] for v in calib.values()]))) if calib
                             else (0.0, 1.0))

    # -- the strength base of a side the fit does not rate
    def _touch(self, team: str) -> None:
        """Fix the Q of a side the fit does not rate, from its rating at this moment.

        Such a side's Q is its rating's prior. It used to be re-read off the LIVE rating on every
        call while every rating move also went into `q_shift`, so each Elo step counted twice and
        the rating half never decayed -- on 2026/27, 429 sides (cup entrants, and 18 UEFA clubs
        such as Hajduk Split and Levski Sofia, whose Opta paths and unseen matches doubled too).
        Fixed once, when the world's own draws take over, every later move goes through `q_shift`
        alone, as it does for a fitted side."""
        if team not in self.Q:
            self.Q[team] = ELO_TO_Q * (self.elo.get(team, self.seed_elo) - self.model["elo_mean"])
            if self.start_noise:
                # no data: the prior's own uncertainty
                self.Q[team] += self.start_noise * self.model["q_sd_prior"] * self.rng.standard_normal()

    # -- state ageing. The estimator decay-weights EVIDENCE at HL_Q, and this used to decay the
    # world's shifts at the same rate, on the argument that a move earned months ago should carry
    # less weight now. But a world's state is its truth, not an estimate of it: decaying it pulls
    # every side back towards its starting fit, so a side that collapses in November drifts back
    # by spring, and the fit's own up-to-date form fades with it. The data side with not fading
    # (DEFAULT_HALF_LIFE, above); `q_half_life` keeps the decay available for that comparison.
    # T's shift still decays at T's 4-year half-life, which a season barely touches.
    def _age(self, team: str, kickoff: pd.Timestamp, live: bool = True) -> None:
        prev = self.last_day.get(team)
        if self.live_from is None:
            self._touch(team)
        dq = dt = 0.0
        if self.unseen is not None:
            dq += self._anchors(team, kickoff)
        if live:
            self._touch(team)
            if self.unseen is not None and self.use_calendar:
                cq, ct = self._calendar(team, kickoff)
                dq, dt = dq + cq, dt + ct
        if prev is not None:
            days = max((kickoff - prev).days, 0)
            if days:
                if self.q_decay and team in self.q_shift:
                    self.q_shift[team] *= np.exp(-self.q_decay * days)
                if team in self.t_shift:
                    self.t_shift[team] *= np.exp(-T_DECAY * days)
                if self.drift_per_day > 0 and live:
                    # the past is known: no drift before the world takes over
                    since = prev if self.live_from is None else max(prev, self.live_from)
                    dd = max((kickoff - since).days, 0)
                    if dd:
                        self.q_shift[team] = self.q_shift.get(team, 0.0) + self.rng.normal(
                            0, self.drift_per_day * np.sqrt(dd))
        if dq:
            self.q_shift[team] = self.q_shift.get(team, 0.0) + dq
        if dt:
            self.t_shift[team] = self.t_shift.get(team, 0.0) + dt
        self.last_day[team] = kickoff

    def _anchors(self, team: str, kickoff: pd.Timestamp) -> float:
        """Opta snapshots up to the data cutoff: the side's rating is set to where Opta's movement
        since its first snapshot puts it (beta-scaled into our walk's units). That is real history
        -- its unseen league matches -- so it is the same in every world, and it replaces whatever
        our own updates did between snapshots, since Opta saw those too. Returns the Q shift that
        adds, decayed to `kickoff`; a mid-season world starts with all of it already applied."""
        anchors = self.unseen.anchors.get(team)
        if anchors is None:
            return 0.0
        when, cum = anchors
        i = self._anchor_at.get(team, 0)
        add = 0.0
        while i < len(when) and when[i] <= kickoff:
            elo = self.elo.get(team, self.seed_elo)
            if i == 0:
                self._anchor_base[team] = elo
            target = self._anchor_base[team] + cum[i]
            self.elo[team] = target
            if self.live_from is None:
                add += ELO_TO_Q * (target - elo) * np.exp(-self.q_decay * (kickoff - when[i]).days)
            i += 1
        self._anchor_at[team] = i
        return add

    def _calendar(self, team: str, kickoff: pd.Timestamp) -> Tuple[float, float]:
        """The side's unseen league matches since it last played, each a draw from this world.

        Played as a seen match is, against the mean of the side's own league at a random venue:
        npxG for both sides from the current state, goals from the npxG, the rating moved on the
        result, Q and T on the npxG. Without a goal layer the rating step is a normal with the
        variance the result would carry (K, home advantage, draws), as it was before the two-stage
        match existed. Returns the (Q, T) shifts, each decayed from its match to `kickoff`; the
        state is the one the side brought into this catch-up, which a run of more than a few
        matches -- a winter break -- slightly flattens."""
        u = self.unseen
        calendar = u.calendar.get(team)
        if calendar is None:
            return 0.0, 0.0
        j = self._calendar_at.get(team, 0)
        n = 0
        while j + n < len(calendar) and calendar[j + n] <= kickoff:
            n += 1
        if not n:
            return 0.0, 0.0
        opp = u.opponent[team]
        elo = self.elo.get(team, self.seed_elo)
        q, t = self._state(team)
        qo = ELO_TO_Q * (opp - self.model["elo_mean"])
        b, hv = self.base_mean, self.home_mean
        cq = ct = 0.0
        for k in range(n):
            home = self.rng.random() < 0.5
            mu_t = float(np.exp(b + (hv if home else 0.0) + (q + t) / 2 - qo / 2))
            mu_o = float(np.exp(b + (0.0 if home else hv) + qo / 2 - (q - t) / 2))
            dq = dtk = 0.0
            if self.goals is not None:
                x_t, x_o = draw_npxg(self.rng, mu_t, mu_o, "league")
                g_t, g_o = sample_goals(
                    self.rng, _gmean(self.goals, "", x_t, mu_t),
                    _gmean(self.goals, "", x_o, mu_o),
                    _gdisp(self.goals, x_t), _gdisp(self.goals, x_o), GOAL_RHO)
                ha = u.home_adv if home else -u.home_adv
                e = 1.0 / (1.0 + 10.0 ** (-(elo - opp + ha) / 400.0))
                pts = 1.0 if g_t > g_o else 0.5 if g_t == g_o else 0.0
                step = K_ELO * (pts - e)
                if self.feedback:
                    dq += self.result_gain * (pts - expected_points(
                        _gmean(self.goals, "", mu_t, mu_t), _gmean(self.goals, "", mu_o, mu_o)))
            else:
                x_t = self.rng.gamma(mu_t / NPXG_PHI, NPXG_PHI)
                x_o = self.rng.gamma(mu_o / NPXG_PHI, NPXG_PHI)
                step = float(self.rng.normal(0.0, np.sqrt(u.var(elo, opp))))
                dq += self.result_gain * step / K_ELO
            if self.npxg_feedback:
                e_t, e_o = x_t - mu_t, x_o - mu_o
                dq += self.npxg_gain * (e_t - e_o)
                if self.tilt_feedback:
                    dtk = self.tilt_gain * (e_t + e_o)
            age = (kickoff - calendar[j + k]).days
            cq += dq * np.exp(-self.q_decay * age)
            ct += dtk * np.exp(-T_DECAY * age)
            elo += step
        self.elo[team] = elo
        self._calendar_at[team] = j + n
        return cq, ct

    def _snap(self, team: str) -> Tuple[float, float, float]:
        """(Elo, Q, T) as the side stands now -- what the state rows record."""
        q, t = self._state(team)
        return self.elo.get(team, self.seed_elo), q, t

    def _state(self, team: str) -> Tuple[float, float]:
        q = self.Q.get(team)
        if q is None:
            q = ELO_TO_Q * (self.elo.get(team, self.seed_elo) - self.model["elo_mean"])
        return q + self.q_shift.get(team, 0.0), self.T.get(team, 0.0) + self.t_shift.get(team, 0.0)

    def rates(self, competition: str, home: str, away: str, *,
              neutral: bool = False) -> Tuple[float, float, float, float]:
        """(mu_npxg_home, mu_npxg_away, lam_goals_home, lam_goals_away) at the current state.

        With a goal layer, lam is the two-stage model's expected goals, c0 + (c1 + c2)*mu (npxG
        averages mu). It is what extra time and a replayed cup tie are resolved with."""
        qh, th = self._state(home)
        qa, ta = self._state(away)
        b = self.model["base"].get(competition, self.base_mean)
        hv = 0.0 if neutral else self.model["home"].get(competition, self.home_mean)
        mu_h = float(np.exp(b + hv + (qh + th) / 2 - (qa - ta) / 2))
        mu_a = float(np.exp(b + (qa + ta) / 2 - (qh - th) / 2))
        if self.goals is not None:
            return (mu_h, mu_a, _gmean(self.goals, competition, mu_h, mu_h),
                    _gmean(self.goals, competition, mu_a, mu_a))
        ca, cb = self._cal.get(competition, self._cal_default)
        lam_h = max(np.exp(ca + cb * np.log(max(mu_h, 1e-6))), 1e-4)
        lam_a = max(np.exp(ca + cb * np.log(max(mu_a, 1e-6))), 1e-4)
        return mu_h, mu_a, float(lam_h), float(lam_a)

    def _feedback(self, competition: str, home: str, away: str, gh: int, ga: int,
                  rates: Optional[Tuple[float, float, float, float]], *,
                  npxg: Optional[Tuple[float, float]], neutral: bool, uefa: bool,
                  kind: str = "league") -> None:
        """Move both sides after a match. `rates` is the state's (mu_h, mu_a, lam_h, lam_a) going
        in; strength moves only when it is given, a rating always (with `feedback`)."""
        # --- npxG: the DOMINANT channel, and the one a results-only sim omits. Over a typical
        # match its surprise has ~13x the variance of the result channel's (analysis/tilt_response).
        if self.npxg_feedback and npxg is not None and rates is not None:
            e_h, e_a = npxg[0] - rates[0], npxg[1] - rates[1]
            self.q_shift[home] = self.q_shift.get(home, 0.0) + self.npxg_gain * (e_h - e_a)
            self.q_shift[away] = self.q_shift.get(away, 0.0) - self.npxg_gain * (e_h - e_a)
            if self.tilt_feedback:
                # attack minus defence: home's attack surprise is e_h, its defence surprise -e_a
                self.t_shift[home] = self.t_shift.get(home, 0.0) + self.tilt_gain * (e_h + e_a)
                self.t_shift[away] = self.t_shift.get(away, 0.0) + self.tilt_gain * (e_h + e_a)
        if self.feedback:
            eh = self.elo.setdefault(home, self.seed_elo)
            ea = self.elo.setdefault(away, self.seed_elo)
            ha = 0.0 if neutral else (UEFA_HOME_ADV if uefa else HOME_ADV)
            exp_h = float(expected_home(np.array([eh]), np.array([ea]), ha)[0])
            act = 1.0 if gh > ga else (0.5 if gh == ga else 0.0)
            d = K_ELO * (act - exp_h)
            self.elo[home], self.elo[away] = eh + d, ea - d
            if rates is not None:
                rho = MATCH_DRAW.get(kind, MATCH_DRAW["league"])[2]
                r = self.result_gain * (act - expected_points(rates[2], rates[3], rho))
                self.q_shift[home] = self.q_shift.get(home, 0.0) + r
                self.q_shift[away] = self.q_shift.get(away, 0.0) - r

    def play(self, competition: str, season: int, home: str, away: str, kickoff: pd.Timestamp, *,
             stage: str = "", leg: int = 0, phase: str = "league", neutral: bool = False,
             uefa: bool = False, fixture_id: int = -1,
             kind: Optional[str] = None) -> Tuple[int, int, float, float]:
        """Age the state, draw the match, propagate feedback, record the row. `kind` (league /
        uefa / cup) picks the match draw; without it a UEFA match is "uefa", any other knockout
        a cup tie, and the rest league matches."""
        kind = kind or ("uefa" if uefa else "cup" if phase == "knockout" else "league")
        self._age(home, kickoff)
        self._age(away, kickoff)
        before = [*self._snap(home), *self._snap(away)]
        mu_h, mu_a, lam_h, lam_a = self.rates(competition, home, away, neutral=neutral)
        if self.goals is not None:
            x_h, x_a = draw_npxg(self.rng, mu_h, mu_a, kind)
            gh, ga = sample_goals(
                self.rng, _gmean(self.goals, competition, x_h, mu_h),
                _gmean(self.goals, competition, x_a, mu_a),
                _gdisp(self.goals, x_h), _gdisp(self.goals, x_a),
                MATCH_DRAW.get(kind, MATCH_DRAW["league"])[2])
            npxg: Optional[Tuple[float, float]] = (x_h, x_a)
        else:
            # the one-stage match: score and npxG drawn independently from the expectation
            gh, ga = sample_scoreline(self.rng, lam_h, lam_a, self.rho)
            npxg = (self.rng.gamma(max(mu_h, 1e-6) / NPXG_PHI, NPXG_PHI),
                    self.rng.gamma(max(mu_a, 1e-6) / NPXG_PHI, NPXG_PHI)) \
                if self.npxg_feedback else None
        self._feedback(competition, home, away, gh, ga, (mu_h, mu_a, lam_h, lam_a),
                       npxg=npxg if self.npxg_feedback else None, neutral=neutral, uefa=uefa,
                       kind=kind)
        self.rows.append([competition, season, phase, kickoff, stage, leg, fixture_id,
                          home, away, gh, ga, 90.0, neutral, True,
                          npxg[0] if npxg else np.nan, npxg[1] if npxg else np.nan])
        self.state_rows.append(before + [*self._snap(home), *self._snap(away)])
        self.score90_rows.append([gh, ga])
        return gh, ga, lam_h, lam_a

    def replay(self, row) -> None:
        """Record a real result. Before `live_from` it is already in the start, so it moves
        nothing; otherwise it moves the state as a drawn result would, without sampling one."""
        gh, ga = int(row.home_goals), int(row.away_goals)
        has_npxg = getattr(row, "has_npxg", False) and pd.notna(row.home_npxg)
        if self.live_from is None or row.kickoff >= self.live_from:
            self._age(row.home, row.kickoff)
            self._age(row.away, row.kickoff)
            # a 120-minute result is scored on the state's 90-minute expectation, as Elo's is
            rates = self.rates(row.competition, row.home, row.away)
            npxg = (float(row.home_npxg), float(row.away_npxg)) if has_npxg else None
            self._feedback(row.competition, row.home, row.away, gh, ga, rates,
                           npxg=npxg, neutral=False, uefa=(row.kind == "uefa"),
                           kind=str(row.kind))
        self.rows.append([row.competition, row.season, _phase_of(row),
                          row.kickoff, "" if pd.isna(row.round) else f"R{int(row.round)}", 0,
                          int(row.Index), row.home, row.away, gh, ga,
                          90.0 if pd.isna(row.minutes) else float(row.minutes), False, False,
                          float(row.home_npxg) if has_npxg else np.nan,
                          float(row.away_npxg) if has_npxg else np.nan])
        self.state_rows.append(_NO_STATE)
        # Played AET rows hold final scores; only sampled rows enter forecast tables.
        self.score90_rows.append([np.nan, np.nan])

    def add_extra_time(self, extra_home: int, extra_away: int) -> None:
        """Fold a tie's extra-time goals into the leg that was played in -- always the last row.

        Extra time deliberately does NOT feed Elo: the update rule was fitted on domestic league
        matches, which have none, and ClubElo's published series scores knockouts on 90 minutes.
        The goals are recorded so the output's goal counts carry the same 120-minute semantics as
        `data/master_fixtures.csv`, where an `afterextratime` row holds the full score.
        """
        if extra_home or extra_away:
            self.rows[-1][9] += extra_home
            self.rows[-1][10] += extra_away
        self.rows[-1][11] = 120.0


def elo_walk(fixtures: pd.DataFrame, elo0: Dict[str, float], cutoff: pd.Timestamp,
             unseen=None) -> Tuple[Dict[str, float], float]:
    """Every side's Elo rating at `cutoff`, and the default for a side nobody rates.

    The real results before the cutoff, in kickoff order, through the same update rule a world
    uses, with the sides we do not see moved along their Opta paths -- all of them, to the last
    snapshot, since every snapshot is history. Deterministic, so it is computed once per run and
    handed to every world as its start (`simulate(..., live_from=cutoff)`), and to the fit as its
    prior (`attack_defence_qt.fit(..., elo_now=)`), which is how the two agree by construction.
    The unseen sides' calendar of simulated matches is not walked: those are draws, not history.
    """
    stub = {"Q": {}, "T": {}, "base": {"": 0.0}, "home": {"": 0.0}, "elo_mean": 0.0}
    w = _World(stub, {}, elo0, None, drift_per_day=0.0, feedback=True, npxg_feedback=False,
               npxg_gain=0.0, rho=0.0, unseen=unseen, q_half_life=None, calendar=False)
    played = fixtures[(fixtures.kickoff < cutoff) & fixtures.played
                      & fixtures.home_goals.notna()].sort_values("kickoff")
    for row in played.itertuples():
        w.replay(row)
    if unseen is not None:
        for team, (when, _) in unseen.anchors.items():
            w._anchors(team, max(when))
    return dict(w.elo), w.seed_elo


# --------------------------------------------------------------------------- knockout bookkeeping
@dataclass
class _Knockout:
    """One competition-season's knockout as it unfolds inside a world."""
    competition: str
    season: int
    seeds: Dict[int, str] = field(default_factory=dict)
    ties: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    leg1: Dict[str, List[Tuple[int, int]]] = field(default_factory=dict)
    winners: Dict[str, List[str]] = field(default_factory=dict)
    losers: Dict[str, List[str]] = field(default_factory=dict)
    shootouts: int = 0
    extra_times: int = 0
    champion: Optional[str] = None

    def report(self) -> Dict[str, Any]:
        return {"seeds": dict(self.seeds),
                "ties": {k: list(v) for k, v in self.ties.items()},
                "winners": {k: list(v) for k, v in self.winners.items()},
                "losers": {k: list(v) for k, v in self.losers.items()},
                "extra_times": self.extra_times, "shootouts": self.shootouts,
                "champion": self.champion}


def _seed_league_phase(world: _World, ko: _Knockout, expected: int) -> None:
    """Rank the world's own league phase. Called once, at the first stage that needs a draw."""
    sim = pd.DataFrame(world.rows, columns=OUT_COLS)
    played = sim[(sim.competition == ko.competition) & (sim.season == ko.season)
                 & (sim.phase == "league")]
    if len(played) != expected:
        raise ValueError(
            f"{ko.competition} {ko.season}: seeding needs all {expected} league-phase results but "
            f"the world has {len(played)}. Pass the full competition-season to `simulate`.")
    tbl = league_phase_table(played, rng=world.rng)
    if len(tbl) != 36 or tbl["played"].nunique() != 1:
        raise ValueError(
            f"{ko.competition} {ko.season}: league phase has {len(tbl)} teams playing "
            f"{sorted(tbl['played'].unique())} matches each; seeding needs 36 teams on an equal "
            "number. (A whole round missing from `fixtures` is indistinguishable from a shorter "
            "format and is NOT caught here -- pass the complete competition-season.)")
    ko.seeds = dict(zip(tbl["seed"], tbl["team"]))


def _run_stage_leg(world: _World, ko: _Knockout, spec: StageSpec, leg: int,
                   lp_size: int) -> None:
    if leg == 1:
        if spec.ties is not None:
            ko.ties[spec.label] = list(spec.ties)
        else:
            if not ko.seeds:
                _seed_league_phase(world, ko, lp_size)
            ko.ties[spec.label] = draw_stage(spec.label, ko.seeds, ko.ties, ko.winners, world.rng)

    ties = ko.ties[spec.label]
    if spec.two_leg and leg == 1:
        ko.leg1[spec.label] = [
            world.play(ko.competition, ko.season, h, a, spec.leg1, stage=spec.label, leg=1,
                       phase="knockout", uefa=True)[:2] for h, a in ties]
        return

    winners: List[str] = []
    losers: List[str] = []
    for i, (team_a, team_b) in enumerate(ties):
        if spec.two_leg:
            # leg 2 is hosted by team_b, and extra time -- if the aggregate is level -- is in it
            l1 = ko.leg1[spec.label][i]
            gb, ga, lam_h, lam_a = world.play(ko.competition, ko.season, team_b, team_a,
                                              spec.leg2, stage=spec.label, leg=2,
                                              phase="knockout", uefa=True)
            res = resolve_two_legs(team_a, team_b, l1, (gb, ga), (lam_h, lam_a), world.rng,
                                   sample_scoreline=sample_scoreline, rho=world.rho)
            if res.went_to_extra_time:
                world.add_extra_time(res.agg_away - (l1[1] + gb), res.agg_home - (l1[0] + ga))
        else:
            gh, ga, lam_h, lam_a = world.play(ko.competition, ko.season, team_a, team_b,
                                              spec.leg1, stage=spec.label, leg=1,
                                              phase="knockout", neutral=spec.neutral, uefa=True)
            res = resolve_single_leg(team_a, team_b, (gh, ga), (lam_h, lam_a), world.rng,
                                     neutral=spec.neutral, sample_scoreline=sample_scoreline,
                                     rho=world.rho)
            if res.went_to_extra_time:
                world.add_extra_time(res.agg_home - gh, res.agg_away - ga)
        ko.extra_times += int(res.went_to_extra_time)
        ko.shootouts += int(res.went_to_penalties)
        winners.append(res.winner)
        losers.append(team_b if res.winner == team_a else team_a)
    ko.winners[spec.label] = winners
    ko.losers[spec.label] = losers
    if spec.label == "F":
        ko.champion = winners[0]


# --------------------------------------------------------------------------- domestic cups
@dataclass
class _Cup:
    """One domestic cup as it unfolds inside a world.

    `reached` is the point of the whole exercise: the set of teams that played in each round, from
    which a reach probability falls out by counting worlds. `alive` is carried across rounds
    rather than recomputed, because a cup lets a side sit a round out.
    """
    competition: str
    season: int
    alive: List[str] = field(default_factory=list)
    ties: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    reached: Dict[str, List[str]] = field(default_factory=dict)
    winners: Dict[str, List[str]] = field(default_factory=dict)
    leg1: Dict[str, List[Tuple[int, int]]] = field(default_factory=dict)
    byes: Dict[str, List[str]] = field(default_factory=dict)
    # round -> how many sides joined the cup there rather than in the first round played
    late: Dict[str, int] = field(default_factory=dict)
    # a tie whose slot was resolved in this world -> the fixture it came from, which is still
    # named after the slot, so the match is counted against that fixture's per-match detail
    origin: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)
    shootouts: int = 0
    extra_times: int = 0
    drawn_rounds: List[str] = field(default_factory=list)
    champion: Optional[str] = None

    def report(self) -> Dict[str, Any]:
        return {"reached": {k: list(v) for k, v in self.reached.items()},
                "winners": {k: list(v) for k, v in self.winners.items()},
                "ties": {k: list(v) for k, v in self.ties.items()},
                "byes": {k: list(v) for k, v in self.byes.items()},
                "late": dict(self.late),
                "drawn_rounds": list(self.drawn_rounds),
                "extra_times": self.extra_times, "shootouts": self.shootouts,
                "champion": self.champion}


def _cup_ties(cup: _Cup, rnd: CupRound, rules, lower_division: Set[str],
              rng, feeder=None) -> Tuple[List[Tuple[str, str]], List[str]]:
    """This round's pairings in THIS world: taken from the fixture list where it names them,
    drawn from the survivors where it does not.

    A named tie may carry a bracket SLOT on one side ("Napoli v Pisa/Fiorentina"), which is
    resolved against the teams actually alive here -- in a world where Pisa went through it is
    Napoli v Pisa, and in the next world along it is Napoli v Fiorentina. A slot that will not
    parse falls back to the unplaced survivors, so the round still has the right field even if
    the naming changes.

    A slot whose feeder is not in the data at all -- the FA Cup's first round names eleven
    "Harrogate Town/Bury" places, the winners of qualifying ties nothing here holds -- has no
    survivor to fall back on, and used to fall back to ITSELF: "Harrogate Town/Bury" played the
    cup as a club, at the default rating. `feeder(a, b)` plays that qualifying tie in this world
    instead and returns its winner, so the place is filled by one of the two clubs it names.
    """
    first = not cup.reached
    added = 0
    for t in rnd.entrants:
        if t not in cup.alive:
            cup.alive.append(t)
            added += 1
    if added and not first:
        cup.late[rnd.label] = added
    if rnd.ties is None:
        cup.drawn_rounds.append(rnd.label)
        ties, byes = draw_round(rnd.label, cup.alive, rules, lower_division, rng,
                                n_ties=rnd.n_ties)
        return ties, list(byes)

    placed = {t for tie in rnd.ties for t in tie if not is_slot(t)}
    # a side going through on a walkover is not free to fill a slot, or it plays AND walks over
    spare = [t for t in cup.alive if t not in placed and t not in rnd.walkovers]
    out: List[Tuple[str, str]] = []
    for a, b in rnd.ties:
        side: List[str] = []
        for t in (a, b):
            if not is_slot(t):
                side.append(t)
                continue
            pick = resolve_slot(t, spare)
            if pick is None:
                halves = [h.strip() for h in str(t).split("/") if h.strip()]
                if spare:
                    pick = spare[int(rng.integers(len(spare)))]
                elif feeder is not None and len(halves) == 2:
                    pick = feeder(*halves)
                else:
                    pick = t
            if pick in spare:
                spare.remove(pick)
            side.append(pick)
        out.append((side[0], side[1]))
        if (side[0], side[1]) != (a, b):
            cup.origin[(side[0], side[1])] = (a, b)
    # the opponent of a tie dropped as a duplicate listing goes through without playing -- see
    # `cup_bracket.cup_handover`. Any other survivor no named tie places is out, as it always was:
    # that is a tie decided off the pitch, whose winner the fixture list names instead.
    return out, [t for t in rnd.walkovers if t in cup.alive and t not in placed]


def _play_cup_leg(world: _World, cup: _Cup, rnd: CupRound, home: str, away: str, when,
                  leg: int, rows: Dict[Tuple[str, str], Any], replay_played: bool
                  ) -> Tuple[int, int, float, float, bool]:
    """One cup match. Returns (home goals, away goals, lam_h, lam_a, was_replayed).

    A tie already played is REPLAYED rather than re-sampled, exactly as an ordinary fixture would
    be: its real result moves the world's state and its real scoreline decides the tie. Half the
    handover round is routinely in this state.
    """
    row = rows.get((home, away)) or rows.get(cup.origin.get((home, away), ()))
    # only THIS round's listing is this tie. The same pairing listed for another round -- a
    # duplicate dropped from round one, met again in a drawn round two -- is a different match,
    # and taking its row would count this one against it, or replay its result if it had one.
    if row is not None and row.Index not in rnd.fixture_ids:
        row = None
    if replay_played and row is not None and getattr(row, "played", False) \
            and pd.notna(row.home_goals):
        world.replay(row)
        lam_h, lam_a = world.rates(cup.competition, home, away, neutral=rnd.neutral)[2:]
        return int(row.home_goals), int(row.away_goals), lam_h, lam_a, True
    gh, ga, lam_h, lam_a = world.play(
        cup.competition, cup.season, home, away, when, stage=rnd.label, leg=leg,
        phase="knockout", neutral=rnd.neutral,
        fixture_id=int(row.Index) if row is not None else -1)
    return gh, ga, lam_h, lam_a, False


def _run_cup_round(world: _World, cup: _Cup, rnd: CupRound, leg: int, rules,
                   lower_division: Set[str], rows: Dict[Tuple[str, str], Any],
                   replay_played: bool) -> None:
    """One leg of one cup round, inside one world."""
    def feeder(a: str, b: str) -> str:
        """A qualifying tie the data does not hold, played on the day of the round it feeds."""
        gh, ga, lam_h, lam_a = world.play(cup.competition, cup.season, a, b, rnd.leg1,
                                          stage="Q", leg=1, phase="knockout", neutral=False)
        res = resolve_single_leg(a, b, (gh, ga), (lam_h, lam_a), world.rng, neutral=False,
                                 sample_scoreline=sample_scoreline, rho=world.rho,
                                 et_fraction=ET_FRACTION if rules.extra_time else 0.0)
        if res.went_to_extra_time:
            world.add_extra_time(res.agg_home - gh, res.agg_away - ga)
        return res.winner

    if leg == 1:
        ties, byes = _cup_ties(cup, rnd, rules, lower_division, rng=world.rng, feeder=feeder)
        cup.ties[rnd.label] = ties
        cup.byes[rnd.label] = byes
        cup.reached[rnd.label] = [t for tie in ties for t in tie] + byes

    ties = cup.ties[rnd.label]
    if rnd.two_leg and leg == 1:
        cup.leg1[rnd.label] = [
            _play_cup_leg(world, cup, rnd, h, a, rnd.leg1, 1, rows, replay_played)[:2]
            for h, a in ties]
        return

    winners: List[str] = []
    for i, (team_a, team_b) in enumerate(ties):
        settled = rnd.settled.get((team_a, team_b))
        if rnd.two_leg:
            l1 = cup.leg1[rnd.label][i]
            gb, ga, lam_h, lam_a, _ = _play_cup_leg(
                world, cup, rnd, team_b, team_a, rnd.leg2, 2, rows, replay_played)
            res = resolve_two_legs(team_a, team_b, l1, (gb, ga), (lam_h, lam_a), world.rng,
                                   sample_scoreline=sample_scoreline, rho=world.rho)
        else:
            gh, ga, lam_h, lam_a, replayed = _play_cup_leg(
                world, cup, rnd, team_a, team_b, rnd.leg1, 1, rows, replay_played)
            if replayed and settled is not None:
                # a real result, and a real shootout the fixture table does not record. The winner
                # was settled once at handover; re-deciding it here would make the same tie go
                # different ways in different worlds when reality has already answered it.
                winners.append(settled)
                cup.alive = [t for t in cup.alive
                             if t != (team_b if settled == team_a else team_a)]
                continue
            res = resolve_single_leg(team_a, team_b, (gh, ga), (lam_h, lam_a), world.rng,
                                     neutral=rnd.neutral, sample_scoreline=sample_scoreline,
                                     rho=world.rho,
                                     et_fraction=ET_FRACTION if rules.extra_time else 0.0)
            if res.went_to_extra_time:
                world.add_extra_time(res.agg_home - gh, res.agg_away - ga)
        if rnd.two_leg and res.went_to_extra_time:
            world.add_extra_time(res.agg_away - (cup.leg1[rnd.label][i][1] + gb),
                                 res.agg_home - (cup.leg1[rnd.label][i][0] + ga))
        cup.extra_times += int(res.went_to_extra_time)
        cup.shootouts += int(res.went_to_penalties)
        winners.append(res.winner)
    cup.winners[rnd.label] = winners
    cup.alive = winners + list(cup.byes.get(rnd.label, []))
    if rnd.label == "F":
        cup.champion = winners[0]


# --------------------------------------------------------------------------- the simulation
def uefa_handovers(fixtures: pd.DataFrame, master: Optional[pd.DataFrame], rng
                   ) -> Dict[Tuple[str, int], Handover]:
    """Where the simulator takes over each UEFA knockout in `fixtures`.

    `master` supplies the previous season, which is where an undrawn stage's dates come from;
    without it the previous season must be inside `fixtures` itself. Competition-seasons in the
    pre-2024 32-team format have no derived bracket and are left to plain replay.
    """
    src = fixtures if master is None else master
    out: Dict[Tuple[str, int], Handover] = {}
    for (comp, season), g in fixtures[fixtures.kind == "uefa"].groupby(["competition", "season"]):
        prev = src[(src.competition == comp) & (src.season == season - 1)]
        try:
            hand = knockout_handover(g, prev if not prev.empty else None, rng)
        except NotImplementedError:
            continue
        if hand.specs:
            out[(comp, season)] = hand
    return out


def simulate(fixtures: pd.DataFrame, model: Dict, calib: Dict, elo0: Dict[str, float],
             rng, drift_per_day: float = 0.0, feedback: bool = True,
             npxg_feedback: bool = True, npxg_gain: float = DEFAULT_GAIN,
             rho: float = -0.10, replay_played: bool = True, build_knockouts: bool = True,
             master: Optional[pd.DataFrame] = None,
             handovers: Optional[Dict[Tuple[str, int], Handover]] = None,
             cups: Optional[Dict[Tuple[str, int], CupHandover]] = None,
             unseen=None, goals: Optional[Dict[str, Any]] = None,
             live_from: Optional[pd.Timestamp] = None, seed_elo: Optional[float] = None,
             tilt_feedback: bool = True,
             q_half_life: Optional[float] = DEFAULT_HALF_LIFE,
             start_noise: float = DEFAULT_START_NOISE) -> pd.DataFrame:
    """One world.

    `fixtures` is processed in kickoff order and may mix played and unplayed matches. With
    `replay_played` (the default) a played row is NOT re-sampled: its real result is kept, so a
    mid-season run continues from reality. Pass `replay_played=False` to re-sample a finished
    season from scratch, which is what a dispersion calibration needs -- see
    `analysis/calibrate_drift3.py`.

    `live_from` is the date the world takes over from reality, for a model fitted on everything
    played before it. `elo0` must then be the ratings AT that date (`elo_walk`, with its
    `seed_elo`): played results are already in the start, so they are recorded, not replayed into
    the state. Without it the world starts from `elo0` at the first fixture and every replayed
    result moves its state. `goals` is the two-stage match's goal layer
    (`attack_defence_qt.fit_goal_layer`); without it a match is the one-stage Dixon-Coles draw
    from `calib`, with npxG drawn independently of the score.

    With `build_knockouts`, every UEFA competition-season whose bracket is missing or unfinished
    is handed over to the bracket machinery (see `uefa_bracket`). Pass `handovers` from
    `uefa_handovers` to compute that once for a batch of worlds. The per-competition knockout
    report -- seeds, ties, winners and losers by round, shootout counts, champion -- lands in
    `result.attrs["knockout"]`.
    """
    if live_from is not None and not replay_played:
        raise ValueError("live_from means the model was fitted on the played matches, so "
                         "re-sampling them (replay_played=False) would score the fit on its own "
                         "training data -- fit at the season start instead")
    world = _World(model, calib, elo0, rng, drift_per_day=drift_per_day, feedback=feedback,
                   npxg_feedback=npxg_feedback, npxg_gain=npxg_gain, rho=rho, unseen=unseen,
                   goals=goals, live_from=live_from, seed_elo=seed_elo,
                   tilt_feedback=tilt_feedback, q_half_life=q_half_life, start_noise=start_noise)
    hands: Dict[Tuple[str, int], Handover] = {}
    cup_hands: Dict[Tuple[str, int], CupHandover] = {}
    if build_knockouts:
        hands = dict(handovers) if handovers is not None else uefa_handovers(fixtures, master, rng)
        cup_hands = dict(cups) if cups is not None else cup_handovers(fixtures, master, rng)

    kos: Dict[Tuple[str, int], _Knockout] = {}
    lp_sizes: Dict[Tuple[str, int], int] = {}
    skip: set = set()
    for key, hand in hands.items():
        ko = _Knockout(*key)
        ko.ties.update({k: list(v) for k, v in hand.settled_ties.items()})
        ko.winners.update({k: list(v) for k, v in hand.settled_winners.items()})
        kos[key] = ko
        lp_sizes[key] = len(split_phases(fixtures[(fixtures.competition == key[0])
                                                 & (fixtures.season == key[1])])[0])
        skip.update(hand.fixture_index)
    # Every side outside the modelled top flight, for the one draw rule that is not a coin: a cup
    # tie between divisions is hosted by the lower side in some competitions and not others.
    top_flight: Set[str] = set()
    for _, g in fixtures[fixtures.kind == "league"].groupby(["competition", "season"]):
        top_flight |= set(g["home"]) | set(g["away"])
    lower_division = (set(fixtures["home"]) | set(fixtures["away"])) - top_flight

    cup_states: Dict[Tuple[str, int], _Cup] = {}
    cup_rows: Dict[Tuple[str, int], Dict[Tuple[str, str], Any]] = {}
    for key, hand in cup_hands.items():
        cup_states[key] = _Cup(*key)
        idx = [i for i in hand.fixture_index if i in fixtures.index]
        cup_rows[key] = {(str(r.home), str(r.away)): r
                         for r in fixtures.loc[idx].itertuples()} if idx else {}
        skip.update(hand.fixture_index)

    missing = skip - set(fixtures.index)
    if missing:
        raise ValueError(
            f"{len(missing)} handover rows are not in `fixtures`. `handovers` must be built from "
            "the same frame (same index labels) that is being simulated.")

    # one chronological timeline: the fixtures the simulator plays directly, plus each handed-over
    # stage's legs. Legs are separate events so state moves between them.
    events: List[Tuple[pd.Timestamp, int, int, Any]] = []
    for i, row in enumerate(fixtures.sort_values("kickoff").itertuples()):
        if row.Index not in skip:
            events.append((row.kickoff, 0, i, row))
    for j, (key, hand) in enumerate(hands.items()):
        for spec in hand.specs:
            events.append((spec.leg1, 1, j, (key, spec, 1)))
            if spec.leg2 is not None:
                events.append((spec.leg2, 1, j, (key, spec, 2)))
    for j, (key, chand) in enumerate(cup_hands.items()):
        for rnd in chand.rounds:
            events.append((rnd.leg1, 2, j, (key, rnd, 1)))
            if rnd.leg2 is not None:
                events.append((rnd.leg2, 2, j, (key, rnd, 2)))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    for _, kind, _, payload in events:
        if kind == 0:
            row = payload
            if replay_played and getattr(row, "played", False) and pd.notna(row.home_goals):
                world.replay(row)
            else:
                world.play(row.competition, row.season, row.home, row.away, row.kickoff,
                           stage=("" if pd.isna(row.round) else f"R{int(row.round)}"),
                           phase=_phase_of(row), uefa=(row.kind == "uefa"),
                           fixture_id=int(row.Index), kind=str(row.kind))
        elif kind == 1:
            key, spec, leg = payload
            _run_stage_leg(world, kos[key], spec, leg, lp_sizes[key])
        else:
            key, rnd, leg = payload
            _run_cup_round(world, cup_states[key], rnd, leg, cup_hands[key].rules,
                           lower_division, cup_rows[key], replay_played)

    out = pd.DataFrame(world.rows, columns=OUT_COLS)
    out.attrs["state"] = np.asarray(world.state_rows, float).reshape(-1, len(STATE_COLS))
    out.attrs["score90"] = np.asarray(world.score90_rows, float).reshape(-1, 2)
    out.attrs["knockout"] = {k: v.report() for k, v in kos.items()}
    out.attrs["cups"] = {k: v.report() for k, v in cup_states.items()}
    return out


def points_table(sim: pd.DataFrame) -> Dict[str, int]:
    """League points over whatever rows you pass. Filter to one competition-season first --
    knockout legs are in the output too and do not award points."""
    pts: Dict[str, int] = {}
    for r in sim.itertuples():
        hp = 3 if r.home_goals > r.away_goals else (1 if r.home_goals == r.away_goals else 0)
        ap = 3 if r.away_goals > r.home_goals else (1 if r.home_goals == r.away_goals else 0)
        pts[r.home] = pts.get(r.home, 0) + hp
        pts[r.away] = pts.get(r.away, 0) + ap
    return pts


def real_points(fixtures: pd.DataFrame) -> Dict[str, int]:
    return points_table(fixtures)


# --------------------------------------------------------------------------- CLI
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--worlds", type=int, default=200)
    ap.add_argument("--npxg-gain", type=float, default=DEFAULT_GAIN)
    ap.add_argument("--drift", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--master", default="data/master_fixtures.pkl")
    ap.add_argument("--top", type=int, default=8, help="rows to show per competition")
    args = ap.parse_args()

    from scripts.attack_defence_qt import fit, fit_goal_calibration, fit_goal_layer, predict_npxg
    sys.path.insert(0, ".")
    from football_common import canonical_elo_team_name

    master = pd.read_pickle(args.master).sort_values("kickoff").reset_index(drop=True)
    fx = master[master.season == args.season]
    start = fx.kickoff.min()
    train = master[(master.kickoff < start) & master.played & master.has_npxg]
    model = fit(train, start, xi_q=np.log(2) / 140, xi_t=np.log(2) / 1460, lam_q=5.0, lam_t=40.0)
    mu_h, mu_a = predict_npxg(train, model)
    calib = fit_goal_calibration(train, mu_h, mu_a)
    goals = fit_goal_layer(train, mu_h, mu_a)

    elo_raw = pd.read_csv("data/external/elo_ratings.csv", parse_dates=["date"])
    wide = elo_raw.pivot_table(index="date", columns="club", values="elo",
                               aggfunc="last").sort_index()
    row = wide.iloc[max(wide.index.searchsorted(start, side="left") - 1, 0)].dropna()
    lookup = {canonical_elo_team_name(c): float(v) for c, v in row.items()}
    elo0 = {t: lookup[canonical_elo_team_name(t)] for t in set(fx.home) | set(fx.away)
            if canonical_elo_team_name(t) in lookup}
    print(f"season {args.season}: {len(fx)} fixtures, {int(fx.played.sum())} played; "
          f"trained on {len(train)}; Elo for {len(elo0)} teams")

    hands = uefa_handovers(fx, master, np.random.default_rng(args.seed))
    for (comp, season), h in hands.items():
        print(f"  {comp}: settled {sorted(h.settled_ties) or '-'}, playing "
              + ", ".join(f"{s.label}{'*' if s.ties is None else ''}" for s in h.specs)
              + (f"  [coin-flipped: {h.coin_flipped}]" if h.coin_flipped else ""))

    reach: Dict[Tuple[str, str], Dict[str, int]] = {}
    league_pts: Dict[Tuple[str, str], List[int]] = {}
    for i in range(args.worlds):
        sim = simulate(fx, model, calib, elo0, np.random.default_rng(args.seed * 100003 + i),
                       drift_per_day=args.drift, npxg_gain=args.npxg_gain,
                       master=master, handovers=hands, goals=goals)
        for (comp, _), rep in sim.attrs["knockout"].items():
            for lab in ("QF", "SF", "F"):
                for t in rep["winners"].get(lab, []):
                    key = (comp, {"QF": "SF", "SF": "F", "F": "WIN"}[lab])
                    reach.setdefault(key, {})
                    reach[key][t] = reach[key].get(t, 0) + 1
        lg = sim[(sim.phase == "league") & sim.competition.isin(
            master[master.kind == "league"].competition.unique())]
        for comp, g in lg.groupby("competition"):
            for team, pts in points_table(g).items():
                league_pts.setdefault((comp, team), []).append(pts)

    print(f"\n{args.worlds} worlds. UEFA reach probabilities:")
    for comp in sorted({c for c, _ in reach}):
        print(f"\n  {comp}")
        win = reach.get((comp, "WIN"), {})
        for t, _ in sorted(win.items(), key=lambda kv: -kv[1])[:args.top]:
            print(f"    {t:28s} SF {reach.get((comp,'SF'),{}).get(t,0)/args.worlds:6.1%}"
                  f"  final {reach.get((comp,'F'),{}).get(t,0)/args.worlds:6.1%}"
                  f"  win {win[t]/args.worlds:6.1%}")

    print("\nprojected league tables (mean points):")
    for comp in sorted({c for c, _ in league_pts}):
        rows = sorted(((t, np.mean(v)) for (c, t), v in league_pts.items() if c == comp),
                      key=lambda kv: -kv[1])
        print(f"\n  {comp}")
        for t, p in rows[:args.top]:
            print(f"    {t:28s} {p:5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
