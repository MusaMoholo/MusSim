#!/usr/bin/env python3
"""UEFA league phase -> knockout bracket: standings, the draw, and the handover to a simulator.

`knockout.py` resolves a tie once you know who is in it. This module is the missing half: it turns
a finished 36-team league phase into the eight play-off ties, the sixteen R16 places and the
bracket that links them through to the final. Without it a simulated UEFA season stops in January.

Everything here was DERIVED FROM THE FIXTURE LIST and then verified against every 36-team knockout
we have (Champions, Europa and Conference League x 2024, 2025 -- six competition-seasons, 270
knockout matches, zero violations; `verify_bracket`). It is not read off a rulebook, which matters
because the 2024/25 reformat invalidated the older shape: pre-2024 the CL ran 62 two-leg pairs out
of 63 pairings and had no play-off round at all, so nothing about the old bracket transfers.

The shape, identical in all three competitions from 2024:

    league phase (36 teams)  seeds  1-8   -> straight to the R16
                             seeds  9-24  -> play-off round, two legs
                             seeds 25-36  -> eliminated
    PO (8 ties) -> R16 (8) -> QF (4) -> SF (2) -> final (1 leg, neutral)        = 45 matches

The constraints, all confirmed on the six seasons:

  * PO pairings come in four bands -- {9,10}x{23,24}, {11,12}x{21,22}, {13,14}x{19,20},
    {15,16}x{17,18} -- drawn WITHIN the band. Observed pairs are 13v19/14v20 in one season and
    13v20/14v19 in another, so the band is the rule and the pair inside it is a draw.
  * The 17-24 seed hosts leg 1; the 9-16 seed hosts leg 2.
  * Each band's two play-off winners meet a fixed pair of top-8 seeds: band {9,10,23,24} -> seeds
    {7,8}, {11,12,21,22} -> {5,6}, {13,14,19,20} -> {3,4}, {15,16,17,18} -> {1,2}. Which of the
    two is drawn. The top-8 seed hosts leg 2, which is what labels an R16 tie T1..T8.
  * The QF pairs {T1,T2} against {T7,T8} (two ties) and {T3,T4} against {T5,T6} (two ties). The
    SF then pairs one tie from each of those two groups. So the bracket is a fixed tree whose slot
    assignment is drawn; drawing it stage by stage under these constraints is equivalent, and it
    is what lets a live simulation start from a PARTLY drawn knockout (see `knockout_handover`).
    The pairing WITHIN a group is a draw, not a fixed slot: 2024 gave T1-T8 and T2-T7, 2025 gave
    T1-T7 and T2-T8. (`simulation.ipynb`'s legacy draw hard-codes T1-T8/T2-T7 and so cannot
    produce the real 2025 CL bracket. Its play-off bands and band-to-top-8 feed do agree with the
    table above, which is independent corroboration of both.)
  * Leg-2 home advantage in the QF and SF is DRAWN, not seeded. Over the 36 QF and SF ties we
    have, the better league-phase seed hosted leg 2 in 22 (0.611, z=+1.33 against a coin) and the
    better R16 bracket slot in 25 (0.694, z=+2.33). Neither is a rule -- 14 and 11 ties
    respectively go the other way -- so `_ordered` flips a coin. Note this barely matters: both
    sides host one leg, so the only asymmetry is that extra time is played at leg 2's rates.
    (`simulation.ipynb`'s legacy draw gives leg 2 to the better rank deterministically, which the
    14 counter-examples rule out.)
  * There is NO same-association protection. AS Monaco drew Paris Saint-Germain in the 2025 CL
    play-off round, so do not filter the draw by country.

Standings use the six tiebreakers we can compute -- points, goal difference, goals scored, away
goals scored, wins, away wins -- in that order. They are doing real work, not decoration: each of
the six seasons has 19-22 adjacent point-ties and every one has a tie straddling a band edge
(seed 8/16/24), yet they reproduce the real seeding exactly, which is what lets `verify_bracket`
pass. They also leave NO unbroken tie in 216 team-slots, so UEFA's remaining criteria
(disciplinary points, then club coefficient) never bind and a random last resort is harmless.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# band -> (seeds that host leg 2 of the play-off, seeds that host leg 1, the top-8 seeds they feed)
BANDS: Tuple[Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]], ...] = (
    ((9, 10), (23, 24), (7, 8)),
    ((11, 12), (21, 22), (5, 6)),
    ((13, 14), (19, 20), (3, 4)),
    ((15, 16), (17, 18), (1, 2)),
)
# the two QF groups, as pairs of R16 tie labels: {T1,T2} x {T7,T8} and {T3,T4} x {T5,T6}
QF_GROUPS: Tuple[Tuple[Tuple[int, int], Tuple[int, int]], ...] = (((1, 2), (7, 8)), ((3, 4), (5, 6)))

# (label, number of ties, two legs?) in order. Uniform across all three competitions from 2024.
STAGE_SHAPE: Tuple[Tuple[str, int, bool], ...] = (
    ("PO", 8, True), ("R16", 8, True), ("QF", 4, True), ("SF", 2, True), ("F", 1, False),
)
STAGE_ORDER: Tuple[str, ...] = tuple(lab for lab, _, _ in STAGE_SHAPE)
PREV_STAGE: Dict[str, Optional[str]] = {
    lab: (STAGE_ORDER[i - 1] if i else None) for i, lab in enumerate(STAGE_ORDER)}

TIEBREAKERS = ["pts", "gd", "gf", "away_gf", "wins", "away_wins"]


# --------------------------------------------------------------------------- standings
def league_phase_table(results: pd.DataFrame, rng=None) -> pd.DataFrame:
    """Order a league phase by the UEFA criteria. `results` needs home/away/home_goals/away_goals.

    Returns one row per team with a 1-based `seed`. `rng`, if given, breaks any tie that survives
    all six computable criteria -- which never happened in 216 real team-slots, so it stands in for
    UEFA's disciplinary-points and club-coefficient rules at no measurable cost.
    """
    rec: Dict[str, Dict[str, float]] = {}
    hg = pd.to_numeric(results["home_goals"]).to_numpy()
    ag = pd.to_numeric(results["away_goals"]).to_numpy()
    for home, away, gh, ga in zip(results["home"], results["away"], hg, ag):
        for team, gf, against, is_home in ((home, gh, ga, True), (away, ga, gh, False)):
            d = rec.setdefault(team, dict(played=0, pts=0, gf=0, ga=0, away_gf=0,
                                          wins=0, away_wins=0))
            d["played"] += 1
            d["gf"] += gf
            d["ga"] += against
            if not is_home:
                d["away_gf"] += gf
            if gf > against:
                d["pts"] += 3
                d["wins"] += 1
                if not is_home:
                    d["away_wins"] += 1
            elif gf == against:
                d["pts"] += 1
    tbl = pd.DataFrame([dict(team=t, **v) for t, v in rec.items()])
    tbl["gd"] = tbl["gf"] - tbl["ga"]
    tbl["_jitter"] = rng.random(len(tbl)) if rng is not None else np.zeros(len(tbl))
    tbl = (tbl.sort_values(TIEBREAKERS + ["_jitter"], ascending=False)
              .drop(columns="_jitter").reset_index(drop=True))
    tbl["seed"] = np.arange(1, len(tbl) + 1)
    return tbl


# --------------------------------------------------------------------------- the draw
def _band_of_seed(seed: int) -> int:
    for b, (hi, lo, _) in enumerate(BANDS):
        if seed in hi or seed in lo:
            return b
    raise ValueError(f"seed {seed} is not in the play-off range 9-24")


def _ordered(a: str, b: str, rng) -> Tuple[str, str]:
    """Which of two qualifiers hosts leg 1. Drawn: QF and SF home advantage is not seeded."""
    return (a, b) if rng.integers(2) else (b, a)


def draw_stage(label: str, seeds: Dict[int, str], ties: Dict[str, List[Tuple[str, str]]],
               winners: Dict[str, List[str]], rng) -> List[Tuple[str, str]]:
    """(leg-1 host, leg-1 visitor) for one stage, drawn from the earlier stages' state.

    `seeds` maps league-phase seed -> team; `ties[label]` and `winners[label]` carry the stages
    already decided. Drawing lazily per stage, rather than a whole bracket up front, is what lets
    a live simulation take over a knockout that is PARTLY drawn: in March the play-off and R16
    ties are in the fixture list and only the quarter-finals onward need drawing.
    """
    seed_of = {team: s for s, team in seeds.items()}

    if label == "PO":
        out = []
        for hi, lo, _ in BANDS:
            order = rng.permutation(2)
            out += [(seeds[lo[int(order[j])]], seeds[hi[j]]) for j in range(2)]
        return out

    if label == "R16":
        # each band's two play-off winners meet that band's two top-8 seeds, drawn.
        # the play-off winner hosts leg 1; the top-8 seed hosts leg 2.
        band_of_tie = [_band_of_seed(seed_of[visitor]) for _, visitor in ties["PO"]]
        out = []
        for b, (_, _, top8) in enumerate(BANDS):
            idx = [i for i, bb in enumerate(band_of_tie) if bb == b]
            if len(idx) != 2:
                raise ValueError(f"band {b} has {len(idx)} play-off ties, expected 2")
            order = rng.permutation(2)
            out += [(winners["PO"][i], seeds[top8[int(order[j])]]) for j, i in enumerate(idx)]
        return out

    if label in ("QF", "SF"):
        src = PREV_STAGE[label]
        assert src is not None
        groups = _tie_groups(label, seeds, ties)
        out = []
        for g in (0, 1) if label == "QF" else (0,):
            left = [i for i, gg in enumerate(groups) if gg == (g, 0)] if label == "QF" \
                else [i for i, gg in enumerate(groups) if gg == 0]
            right = [i for i, gg in enumerate(groups) if gg == (g, 1)] if label == "QF" \
                else [i for i, gg in enumerate(groups) if gg == 1]
            if len(left) != len(right):
                raise ValueError(f"{label}: {len(left)} vs {len(right)} qualifiers in group {g}")
            order = rng.permutation(len(right))
            out += [_ordered(winners[src][i], winners[src][right[int(order[j])]], rng)
                    for j, i in enumerate(left)]
        return out

    if label == "F":
        a, b = winners["SF"]
        return [_ordered(a, b, rng)]      # neutral venue: the order is nominal

    raise ValueError(f"unknown stage label {label}")


def _tie_groups(label: str, seeds: Dict[int, str],
                ties: Dict[str, List[Tuple[str, str]]]) -> List[Any]:
    """Bracket-group of each tie in the stage FEEDING `label`.

    For the QF that is the R16 ties, grouped as (QF group, side) so {T1,T2} can be paired against
    {T7,T8}. For the SF it is the QF ties, grouped 0/1 by which QF group they came from, because
    an SF always pairs one tie from each.
    """
    seed_of = {team: s for s, team in seeds.items()}
    r16_label: Dict[str, int] = {}
    for host, visitor in ties["R16"]:
        lab = seed_of[visitor]
        if lab > 8:
            raise ValueError(f"R16 tie {host} v {visitor}: leg-2 host is seed {lab}, not top-8")
        r16_label[host] = r16_label[visitor] = lab

    if label == "QF":
        out: List[Any] = []
        for host, visitor in ties["R16"]:
            lab = r16_label[visitor]
            hit = [(g, side) for g, group in enumerate(QF_GROUPS)
                   for side, members in enumerate(group) if lab in members]
            out.append(hit[0])
        return out

    groups: List[int] = []
    for a, b in ties["QF"]:
        labs = {r16_label[a], r16_label[b]}
        hit = [g for g, group in enumerate(QF_GROUPS)
               if labs <= set(group[0]) | set(group[1])]
        if not hit:
            raise ValueError(f"QF tie {a} v {b} spans both bracket groups (labels {sorted(labs)})")
        groups.append(hit[0])
    return groups


# --------------------------------------------------------------------------- the calendar
@dataclass
class StageSpec:
    """One knockout stage on the calendar. `ties` is set only when the draw is already known."""
    competition: str
    season: int
    label: str
    leg1: pd.Timestamp
    leg2: Optional[pd.Timestamp]
    n_ties: int
    neutral: bool
    ties: Optional[List[Tuple[str, str]]] = None      # (leg-1 host, leg-1 visitor)
    fixture_index: Tuple[Any, ...] = ()               # the rows in the master this stage occupies

    @property
    def two_leg(self) -> bool:
        return self.leg2 is not None


def _date_blocks(ko: pd.DataFrame, gap_days: int = 4) -> List[pd.DataFrame]:
    """Split knockout rows into midweek blocks. Legs are a week apart, a stage spans 1-2 days."""
    if ko.empty:
        return []
    days = np.sort(ko["kickoff"].dt.normalize().unique())
    bounds: List[List[Any]] = []
    for d in days:
        if bounds and (pd.Timestamp(d) - pd.Timestamp(bounds[-1][-1])).days <= gap_days:
            bounds[-1].append(d)
        else:
            bounds.append([d])
    norm = ko["kickoff"].dt.normalize()
    return [ko[(norm >= b[0]) & (norm <= b[-1])].sort_values("kickoff") for b in bounds]


def split_phases(comp_season: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Numbered phase matches, then unnumbered knockout matches after phase completion.

    Unnumbered qualifying rounds remain in the master/world but precede this knockout.
    Without a numbered phase, retain the legacy partition rather than inventing a boundary.
    """
    phase = comp_season[comp_season["round"].notna()]
    knockout = comp_season[comp_season["round"].isna()]
    if not phase.empty:
        knockout = knockout[knockout["kickoff"] > phase["kickoff"].max()]
    return phase, knockout


def knockout_is_complete(comp_season: pd.DataFrame) -> bool:
    """True when the knockout already runs to a single final in the fixture list.

    Format-agnostic on purpose: the last midweek block of a finished knockout is exactly one
    match, whatever the shape of the rounds before it. That lets a caller replay the 32-team
    seasons (2021-2023, whose brackets we never have to derive) without tripping the 36-team
    checks in `stage_calendar`.
    """
    blocks = _date_blocks(split_phases(comp_season)[1])
    return bool(blocks) and len(blocks[-1]) == 1


def stage_calendar(comp_season: pd.DataFrame,
                   prev_season: Optional[pd.DataFrame]) -> List[StageSpec]:
    """All five knockout stages, dated, with `ties` filled in wherever the draw is already known.

    Dates for stages with no fixtures yet are the previous season's, shifted by the whole number of
    WEEKS between the two league-phase end dates -- whole weeks because UEFA's midweek slots are
    fixed by weekday. The measured shift into 2026/27 is 364 days in all three competitions.
    """
    comp = str(comp_season["competition"].iloc[0])
    season = int(comp_season["season"].iloc[0])
    lp, ko = split_phases(comp_season)
    n_teams = len(set(lp["home"]) | set(lp["away"]))
    if n_teams != 36:
        raise NotImplementedError(
            f"{comp} {season} has a {n_teams}-team league phase. Only the 36-team format "
            "(2024 onward) has a derived bracket; earlier seasons must be replayed from fixtures.")

    blocks = _date_blocks(ko)
    expected = [n for _, n, two in STAGE_SHAPE for n in ([n, n] if two else [n])]
    if len(blocks) > len(expected) or any(len(b) != e for b, e in zip(blocks, expected)):
        raise ValueError(f"{comp} {season}: knockout blocks {[len(b) for b in blocks]} do not "
                         f"match the expected {expected}")

    shift: Optional[pd.Timedelta] = None
    prev_dates: Dict[str, Tuple[pd.Timestamp, Optional[pd.Timestamp]]] = {}
    if len(blocks) < len(expected):
        if prev_season is None or prev_season.empty:
            raise ValueError(f"{comp} {season}: {len(blocks)} of {len(expected)} knockout blocks "
                             "present and no previous season to take the calendar from")
        prev_lp, prev_ko = split_phases(prev_season)
        weeks = round((lp["kickoff"].max() - prev_lp["kickoff"].max()).days / 7)
        shift = pd.Timedelta(weeks=weeks)
        prev_blocks = _date_blocks(prev_ko)
        if len(prev_blocks) != len(expected):
            raise ValueError(f"{comp} {season - 1}: {len(prev_blocks)} knockout blocks, cannot "
                             "supply a calendar (a pre-2024 season has a different shape)")
        i = 0
        for label, _, two in STAGE_SHAPE:
            prev_dates[label] = (prev_blocks[i]["kickoff"].min(),
                                 prev_blocks[i + 1]["kickoff"].min() if two else None)
            i += 2 if two else 1

    specs: List[StageSpec] = []
    i = 0
    for label, n_ties, two in STAGE_SHAPE:
        need = 2 if two else 1
        if i + need <= len(blocks):
            legs = blocks[i:i + need]
            specs.append(StageSpec(
                comp, season, label, legs[0]["kickoff"].min(),
                legs[1]["kickoff"].min() if two else None, n_ties, neutral=not two,
                ties=[(str(r.home), str(r.away)) for r in legs[0].itertuples()],
                fixture_index=tuple(idx for leg in legs for idx in leg.index)))
        else:
            l1, l2 = prev_dates[label]
            specs.append(StageSpec(comp, season, label, l1 + shift,
                                   (l2 + shift) if l2 is not None else None,
                                   n_ties, neutral=not two))
        i += need
    return specs


# --------------------------------------------------------------------------- handover
@dataclass
class Handover:
    """Where a simulator takes over a UEFA knockout, and what is already decided.

    `specs` are the stages it must play, in order, `ties` set where the draw is in the fixture
    list. `settled_*` are the stages already played, whose results the simulator replays as
    ordinary fixtures but whose ties and winners it needs in order to draw what comes next.
    """
    competition: str
    season: int
    specs: List[StageSpec] = field(default_factory=list)
    settled_ties: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    settled_winners: Dict[str, List[str]] = field(default_factory=dict)
    coin_flipped: List[str] = field(default_factory=list)
    fixture_index: Tuple[Any, ...] = ()      # rows the simulator must NOT play as plain fixtures


def _stage_result(spec: StageSpec, ko: pd.DataFrame) -> Optional[List[Optional[str]]]:
    """Winner of each tie in an already-played stage, or None if the stage is not fully played.

    A level aggregate after extra time was settled by a shootout the fixture table does not
    record (28 such matches in our window -- `outcome == 'penalties'` carries only the 120-minute
    score), so those entries come back as None for the caller to resolve or flip.
    """
    assert spec.ties is not None
    rows = ko.loc[list(spec.fixture_index)]
    if not rows["played"].all() or rows["home_goals"].isna().any():
        return None
    score = {(str(r.home), str(r.away)): (int(r.home_goals), int(r.away_goals))
             for r in rows.itertuples()}
    out: List[Optional[str]] = []
    for a, b in spec.ties:
        if spec.two_leg:
            l1, l2 = score[(a, b)], score[(b, a)]
            agg_a, agg_b = l1[0] + l2[1], l1[1] + l2[0]
        else:
            agg_a, agg_b = score[(a, b)]
        out.append(a if agg_a > agg_b else (b if agg_b > agg_a else None))
    return out


def knockout_handover(comp_season: pd.DataFrame, prev_season: Optional[pd.DataFrame],
                      rng) -> Handover:
    """Split a UEFA competition-season into what reality has settled and what must be simulated.

    Walks the stages in order. A stage that is drawn AND fully played is settled: its result moves
    the world's state through the ordinary fixture path, and its winners seed the next draw. The
    first stage that is not fully played is where the simulator takes over, and everything from
    there on is handed to it -- with `ties` still attached if UEFA has already made that draw.
    """
    hand = Handover(str(comp_season["competition"].iloc[0]), int(comp_season["season"].iloc[0]))
    ko = split_phases(comp_season)[1]
    specs = stage_calendar(comp_season, prev_season)
    for k, spec in enumerate(specs):
        result = _stage_result(spec, ko) if spec.ties is not None else None
        if result is None:
            hand.specs = specs[k:]
            hand.fixture_index = tuple(i for s in specs[k:] for i in s.fixture_index)
            break
        hand.settled_ties[spec.label] = list(spec.ties)
        hand.settled_winners[spec.label] = [
            w if w is not None else "?" for w in result]
        hand.coin_flipped += [f"{spec.label}:{spec.ties[i][0]} v {spec.ties[i][1]}"
                              for i, w in enumerate(result) if w is None]
    # a tie the data left level was decided by a shootout it does not record. If the NEXT stage is
    # drawn, the survivor is simply the one that appears in it; otherwise flip the fair coin that
    # knockout.py fits from 186 real shootouts.
    for k, spec in enumerate(specs):
        if spec.label not in hand.settled_winners:
            continue
        unknown = [i for i, w in enumerate(hand.settled_winners[spec.label]) if w == "?"]
        if not unknown:
            continue
        nxt = specs[k + 1] if k + 1 < len(specs) else None
        alive = set()
        if nxt is not None and nxt.ties is not None:
            alive = {t for tie in nxt.ties for t in tie}
        for i in unknown:
            a, b = hand.settled_ties[spec.label][i]
            if a in alive and b not in alive:
                hand.settled_winners[spec.label][i] = a
            elif b in alive and a not in alive:
                hand.settled_winners[spec.label][i] = b
            else:
                hand.settled_winners[spec.label][i] = a if rng.integers(2) else b
    return hand


def redraw_handover(comp_season: pd.DataFrame,
                    prev_season: Optional[pd.DataFrame] = None) -> Handover:
    """A handover that re-draws the WHOLE knockout, ignoring any draw already in the fixture list.

    For re-simulating a finished season from scratch. Replaying the historical R16 pairings on top
    of a re-sampled league phase is incoherent -- the real draw was made from the real standings,
    and in a re-simulated world those standings are different. So blank every stage's `ties` while
    keeping its real dates, and let the world draw its own bracket from its own table.

    Used by `analysis/bracket_backtest.py` and by the `replay_played=False` path in
    `scripts/serve.py`. Raises for the pre-2024 32-team format, which has no derived bracket.
    """
    specs = stage_calendar(comp_season, prev_season)
    return Handover(
        competition=str(comp_season["competition"].iloc[0]),
        season=int(comp_season["season"].iloc[0]),
        specs=[replace(s, ties=None) for s in specs],
        fixture_index=tuple(i for s in specs for i in s.fixture_index))


# --------------------------------------------------------------------------- verification
def check_knockout(seed: Dict[str, int], blocks: Sequence[pd.DataFrame], ctx: str) -> List[str]:
    """Check one 36-team knockout against every constraint in the module docstring.

    `blocks` is the nine midweek blocks in order (PO leg 1, PO leg 2, R16 leg 1, ..., final), each
    a frame with `home`/`away`. Taking the seed map as an argument is what lets the DRAW be checked
    by the same code the real seasons pass -- see `_selfcheck_draw`.
    """
    fails: List[str] = []
    if len(blocks) != 9:
        return [f"{ctx}: {len(blocks)} knockout blocks, expected 9"]
    po1, po2, r16a, r16b, qf1, qf2, sf1, sf2, fin = blocks

    band_of: Dict[str, int] = {}
    po_pairs = set()
    for r in po1.itertuples():
        sh, sa = seed[r.home], seed[r.away]
        band = [b for b, (hi, lo, _) in enumerate(BANDS) if sa in hi and sh in lo]
        if not band:
            fails.append(f"{ctx}: PO tie seeds {sa}v{sh} fit no band")
            continue
        band_of[r.home] = band_of[r.away] = band[0]
        po_pairs.add((r.away, r.home))
    if {(r.home, r.away) for r in po2.itertuples()} != po_pairs:
        fails.append(f"{ctx}: PO leg 2 is not the 9-16 seed at home")

    label: Dict[str, int] = {}
    for r in r16a.itertuples():
        sh, sa = seed[r.home], seed[r.away]
        if sa > 8 or sh <= 8:
            fails.append(f"{ctx}: R16 leg 1 has seeds {sh}v{sa}, expected PO winner at home")
            continue
        if sa not in BANDS[band_of[r.home]][2]:
            fails.append(f"{ctx}: seed {sa} drew a band-{band_of[r.home]} winner")
        label[r.home] = label[r.away] = sa
    if {(r.home, r.away) for r in r16b.itertuples()} != {(r.away, r.home) for r in r16a.itertuples()}:
        fails.append(f"{ctx}: R16 leg 2 is not reversed")

    group_of: Dict[str, int] = {}
    for r in qf1.itertuples():
        pair = {label[r.home], label[r.away]}
        match = [g for g, (left, right) in enumerate(QF_GROUPS)
                 if len(pair & set(left)) == 1 and len(pair & set(right)) == 1]
        if not match:
            fails.append(f"{ctx}: QF tie T{sorted(pair)} fits no bracket group")
            continue
        group_of[r.home] = group_of[r.away] = match[0]
    if {(r.home, r.away) for r in qf2.itertuples()} != {(r.away, r.home) for r in qf1.itertuples()}:
        fails.append(f"{ctx}: QF leg 2 is not reversed")
    for r in sf1.itertuples():
        if {group_of.get(r.home), group_of.get(r.away)} != {0, 1}:
            fails.append(f"{ctx}: SF tie does not cross the two bracket groups")
    if {(r.home, r.away) for r in sf2.itertuples()} != {(r.away, r.home) for r in sf1.itertuples()}:
        fails.append(f"{ctx}: SF leg 2 is not reversed")
    if len(fin) != 1:
        fails.append(f"{ctx}: final is not a single match")
    return fails


def verify_bracket(master: pd.DataFrame) -> Tuple[int, List[str]]:
    """Re-derive the constraints from every real 36-team knockout."""
    fails: List[str] = []
    n = 0
    for (comp, season), g in master[master["kind"] == "uefa"].groupby(["competition", "season"]):
        lp, ko = split_phases(g)
        if len(set(lp["home"]) | set(lp["away"])) != 36 or len(ko) != 45:
            continue
        n += 1
        tbl = league_phase_table(lp)
        fails += check_knockout(dict(zip(tbl["team"], tbl["seed"])), _date_blocks(ko),
                                f"{comp} {season}")
    return n, fails


def _selfcheck_draw(n: int = 2000, seed: int = 7) -> List[str]:
    """Every bracket `draw_stage` produces must pass the checker the real seasons pass.

    Random winners are enough: the constraints are about who CAN meet whom, so a checker that
    accepts the real brackets but rejects a drawn one would mean the draw is wrong.
    """
    rng = np.random.default_rng(seed)
    seeds = {i: f"T{i:02d}" for i in range(1, 37)}
    fails: List[str] = []
    for it in range(n):
        ties: Dict[str, List[Tuple[str, str]]] = {}
        winners: Dict[str, List[str]] = {}
        blocks: List[pd.DataFrame] = []
        for label, _, two in STAGE_SHAPE:
            ties[label] = draw_stage(label, seeds, ties, winners, rng)
            blocks.append(pd.DataFrame(ties[label], columns=["home", "away"]))
            if two:
                blocks.append(pd.DataFrame([(b, a) for a, b in ties[label]],
                                           columns=["home", "away"]))
            winners[label] = [t[int(rng.integers(2))] for t in ties[label]]
        fails += check_knockout({v: k for k, v in seeds.items()}, blocks, f"draw#{it}")
    return fails


def _selfcheck_handover(master: pd.DataFrame) -> List[str]:
    """Taking over a real knockout at each possible point must reproduce the real ties before it.

    Truncating a finished season after stage k and asking for a handover should settle exactly the
    first k stages and hand over the rest -- which is the live path every February to May.
    """
    fails: List[str] = []
    rng = np.random.default_rng(3)
    for comp in ("UEFA Champions League", "UEFA Europa League", "UEFA Conference League"):
        for season in (2024, 2025):
            cs = master[(master["competition"] == comp) & (master["season"] == season)]
            prev = master[(master["competition"] == comp) & (master["season"] == season - 1)]
            full = stage_calendar(cs, None)
            for k in range(len(full)):
                keep = set(cs.index) - {i for s in full[k:] for i in s.fixture_index}
                trunc = cs.loc[sorted(keep)]
                hand = knockout_handover(trunc, prev if not prev.empty else None, rng)
                got = [s.label for s in hand.specs]
                want = list(STAGE_ORDER[k:])
                if got != want:
                    fails.append(f"{comp} {season} cut at {k}: handed over {got}, expected {want}")
                if sorted(hand.settled_ties) != sorted(STAGE_ORDER[:k]):
                    fails.append(f"{comp} {season} cut at {k}: settled "
                                 f"{sorted(hand.settled_ties)}, expected {sorted(STAGE_ORDER[:k])}")
                for lab in STAGE_ORDER[:k]:
                    real = set(full[STAGE_ORDER.index(lab)].ties or [])
                    if set(hand.settled_ties[lab]) != real:
                        fails.append(f"{comp} {season} cut at {k}: {lab} ties do not match")
                    nxt = STAGE_ORDER.index(lab) + 1
                    if nxt < len(full) and nxt < k:
                        survivors = {t for tie in (full[nxt].ties or []) for t in tie}
                        stray = [w for w in hand.settled_winners[lab] if w not in survivors]
                        if stray:
                            fails.append(f"{comp} {season} cut at {k}: {lab} winners {stray} "
                                         "do not appear in the next round")
    return fails


def main() -> int:
    from pathlib import Path
    master = pd.read_pickle(Path("data/master_fixtures.pkl"))

    n, fails = verify_bracket(master)
    print(f"real 36-team knockouts checked: {n}")
    for f in fails:
        print("  FAIL", f)
    print("  all bracket constraints hold" if not fails else f"  {len(fails)} violations")

    dfails = _selfcheck_draw()
    print("\ndrawn brackets checked: 2000")
    for f in dfails[:10]:
        print("  FAIL", f)
    print("  every drawn bracket satisfies the same constraints" if not dfails
          else f"  {len(dfails)} violations")

    hfails = _selfcheck_handover(master)
    print("\nhandover points checked: 30 (6 competition-seasons x 5 cut points)")
    for f in hfails[:10]:
        print("  FAIL", f)
    print("  every handover reproduces the real ties before it" if not hfails
          else f"  {len(hfails)} violations")

    print("\nstages a simulator must play, per competition-season:")
    rng = np.random.default_rng(0)
    for (comp, season), g in master[master["kind"] == "uefa"].groupby(["competition", "season"]):
        prev = master[(master["competition"] == comp) & (master["season"] == season - 1)]
        try:
            hand = knockout_handover(g, prev if not prev.empty else None, rng)
        except (NotImplementedError, ValueError) as exc:
            print(f"  {comp} {season}: replay only ({type(exc).__name__})")
            continue
        todo = ", ".join(f"{s.label}{'*' if s.ties is None else ''}@{s.leg1.date()}"
                         for s in hand.specs) or "nothing (complete)"
        print(f"  {comp} {season}: settled {sorted(hand.settled_ties) or '-'} | play {todo}")
    print("  (* = the draw itself must be made)")
    return 1 if (fails or dfails or hfails) else 0


if __name__ == "__main__":
    raise SystemExit(main())
