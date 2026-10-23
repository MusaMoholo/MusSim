#!/usr/bin/env python3
"""Knockout tie resolution: two legs, aggregate, extra time, penalties.

Without this, simulating a UEFA knockout is meaningless -- the match-level model gives a scoreline
per leg, but who PROGRESSES depends on rules the scoreline does not encode.

Rules as they currently stand (and the ones that bite):

  * THE AWAY-GOALS RULE IS ABOLISHED (UEFA scrapped it from 2021/22). Aggregate alone decides; a
    2-1 home / 1-2 away tie goes to extra time, it is not settled on away goals. Every season in
    our window (2021-2026) is post-abolition, so the old rule is never applied.
  * Extra time is played in the SECOND leg only, and its goals count toward the aggregate.
  * Still level after extra time -> penalty shootout.

Calibrated from our own data rather than assumed:

  * 186 shootouts: the deciding leg's home side won 87 (0.468, 95% CI 0.396-0.540). 50/50 sits
    comfortably inside, so shootouts are modelled as a fair coin -- no home edge, no rating edge.
  * Extra time scores at 0.357 of the 90-minute rate, which is pro-rata 30/90 to within a third of
    a standard error. 61 UEFA ties reached extra time and 28 of them (0.459, 95% CI 0.334-0.584)
    were still level at the end of it; at our 1.436 goals per team per 90 in UEFA knockout
    football that level rate implies ET_FRACTION 0.357 (95% CI 0.222-0.611), and pro-rata 0.333
    predicts 0.477. So teams do NOT visibly play for the shootout.

    CORRECTION, 2026-09-11. This constant was 0.126, from a pooled "252 ties past 90 minutes, 186
    (0.738) still level". That pool was 186 `penalties` rows plus 66 `afterextratime` rows across
    ALL competitions, and 120 of those 186 are domestic-cup ties recorded at 90 minutes --
    the Coupe de France (90), the English League Cup (19) and the Coppa Italia (11) send a level
    tie straight to a shootout with no extra time at all. Counting ties that never played extra
    time as "still level after extra time" pushed the level rate from 0.459 to 0.738 and forced
    the scoring fraction down to a third of pro-rata. 0.126 predicts 0.719, outside the CI above.
    This is the selection trap FINDINGS section 5 warns about, in the opposite direction from the
    3.82-goals figure: that one conditions on somebody scoring, this one conditions on extra time
    having been played, and only the second pool was checked.

    So do NOT reuse ET_FRACTION for the three cups named above -- their level ties have no extra
    time and go to `resolve_single_leg` with a zero fraction.
  * The 3.82 goals/match seen in matches labelled `afterextratime` is still NOT the unconditional
    rate -- those matches are selected on someone having scored, which is exactly why they did not
    go to penalties.

The 2024/25 format change matters too: pre-2024 the CL had 62 two-leg pairs out of 63 pairings,
while the 36-team league phase has only ~15 of ~160. So a simulator must read the structure from
the fixture list, never assume every UEFA tie has two legs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

# Extra time is 30 minutes and scores at very close to pro-rata. FITTED on UEFA knockouts only:
# 61 ties reached extra time, 28 (0.459, 95% CI 0.334-0.584) were still level at the end of it.
# Solving P(level) = sum_k Pois(k; f*lam)^2 = 0.459 at lam = 1.436 goals per team per 90 (measured
# over the 564 UEFA knockout matches that finished in 90) gives f = 0.357, CI 0.222-0.611.
# Pro-rata 30/90 = 0.333 sits inside that; the old 0.126 does not. See the module docstring for
# why 0.126 was wrong, and why the French, English League and Italian cups need f = 0 instead.
ET_FRACTION = 0.357
SHOOTOUT_HOME_EDGE = 0.5       # fitted: 0.468 (95% CI 0.396-0.540), i.e. a fair coin


@dataclass
class TieResult:
    winner: str
    agg_home: int              # aggregate for the team that hosted leg 1
    agg_away: int
    went_to_extra_time: bool
    went_to_penalties: bool
    pens: Optional[Tuple[int, int]] = None


def resolve_two_legs(team_a: str, team_b: str,
                     leg1: Tuple[int, int], leg2: Tuple[int, int],
                     lam_leg2: Tuple[float, float], rng,
                     sample_scoreline=None, rho: float = -0.10) -> TieResult:
    """`team_a` hosts leg 1, `team_b` hosts leg 2.

    leg1 = (goals_a, goals_b) with A at home; leg2 = (goals_b, goals_a) with B at home.
    `lam_leg2` is leg 2's (home, away) expected-goal rates, reused (scaled) for extra time.
    """
    a_goals = leg1[0] + leg2[1]
    b_goals = leg1[1] + leg2[0]
    if a_goals != b_goals:
        return TieResult(team_a if a_goals > b_goals else team_b, a_goals, b_goals, False, False)

    # level on aggregate -> extra time in leg 2, at the same rate scaled to 30 minutes
    if sample_scoreline is None:
        from scripts.simulate_season import sample_scoreline as _ss
        sample_scoreline = _ss
    et_b, et_a = sample_scoreline(rng, lam_leg2[0] * ET_FRACTION, lam_leg2[1] * ET_FRACTION, rho)
    a_goals += et_a
    b_goals += et_b
    if a_goals != b_goals:
        return TieResult(team_a if a_goals > b_goals else team_b, a_goals, b_goals, True, False)

    # still level -> shootout, a fair coin (see module docstring)
    b_wins = rng.random() < SHOOTOUT_HOME_EDGE
    winner = team_b if b_wins else team_a
    # a plausible shootout scoreline, for reporting only
    losing = int(rng.integers(2, 5))
    pens = (losing, losing + 1) if b_wins else (losing + 1, losing)
    return TieResult(winner, a_goals, b_goals, True, True, pens)


def resolve_single_leg(home: str, away: str, goals: Tuple[int, int],
                       lam: Tuple[float, float], rng, neutral: bool = False,
                       sample_scoreline=None, rho: float = -0.10,
                       et_fraction: float = ET_FRACTION) -> TieResult:
    """One-off knockout match (a final, or the single-leg rounds of the new league phase).

    `neutral=True` is the caller's signal that no home advantage was applied upstream.

    `et_fraction=0.0` sends a level match STRAIGHT to the shootout, which is what the English
    League Cup, the Coupe de France and the Coppa Italia's single-leg rounds actually do -- see
    the module docstring, and `cup_bracket.CUP_RULES` for the per-competition counts. Playing
    extra time where it is not played is not a small error: it hands the stronger side a second
    30 minutes to win in, and the docstring above records how badly the pooled version of this
    same confusion distorted ET_FRACTION itself.
    """
    h, a = goals
    if h != a:
        return TieResult(home if h > a else away, h, a, False, False)
    if sample_scoreline is None:
        from scripts.simulate_season import sample_scoreline as _ss
        sample_scoreline = _ss
    if et_fraction <= 0.0:
        home_wins = rng.random() < SHOOTOUT_HOME_EDGE
        losing = int(rng.integers(2, 5))
        return TieResult(home if home_wins else away, h, a, False, True,
                         (losing + 1, losing) if home_wins else (losing, losing + 1))
    eh, ea = sample_scoreline(rng, lam[0] * et_fraction, lam[1] * et_fraction, rho)
    h += eh; a += ea
    if h != a:
        return TieResult(home if h > a else away, h, a, True, False)
    home_wins = rng.random() < SHOOTOUT_HOME_EDGE
    winner = home if home_wins else away
    losing = int(rng.integers(2, 5))
    pens = (losing + 1, losing) if home_wins else (losing, losing + 1)
    return TieResult(winner, h, a, True, True, pens)
