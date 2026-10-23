#!/usr/bin/env python3
"""Domestic cups: the round calendar, the draw, and the handover to a simulator.

`uefa_bracket.py` does this for the three UEFA competitions, whose bracket is a FIXED TREE whose
slots are drawn under band constraints. A domestic cup is the opposite shape and needs its own
module: there is no seeding, no tree, and no constraint. Every surviving team goes back in the
hat, and the next round is a free pairing of whoever is left. That is why the draw here is a
permutation rather than a slot assignment, and why it must be redrawn IN EVERY WORLD -- a world
that reached the quarter-finals with a different eight teams cannot reuse another world's draw.

WHAT IS READ FROM DATA, AND WHAT IS NOT

Everything in `CUP_RULES` below was measured on the completed 2025 seasons in
`data/master_fixtures.pkl` (and the played part of 2026), not taken from a rulebook. Each field
carries its own count. Two things are NOT derivable from the fixture table and are marked as
rulebook facts: whether a final is played at a neutral venue (there is no venue column -- the
`Location` field Fotmob returns is empty), and nothing else. Neutrality only removes home
advantage from one match, so the exposure is small and it is stated rather than hidden.

THE ROUNDS ARE READ BACKWARDS FROM THE FINAL

A cup's early rounds are full of replays, reschedules, byes and sides entering late: the 2025 FA
Cup's fifth-round week holds 9 matches between 17 teams, and the Copa del Rey's third round has
15 ties, not 16. Counting rounds forwards from the start therefore gets them wrong. Counting
backwards cannot: the last tie of any cup is the final, the two before it are the semi-finals, and
no reschedule ever reaches that far. So `split_rounds` walks the FIXTURES from the end -- 1, then
2, then 4 -- and stops the moment a slice contains the same team twice, which is the signal that
it has run back past the knockout proper into the qualifying rounds. Whatever is left is
preliminary, and is labelled as such rather than forced into a name it does not have.

Two things this buys that date-clustering does not. A two-legged round finds its first leg by
MATCHING PAIRINGS -- the same two teams, played earlier -- so it survives the 2025 Copa del Rey
playing its quarter-finals on 3-5 February and its semi-final first legs on the 11th, eight days
later and therefore in the same date bucket. And a tie played late lands in its own round rather
than swelling the next one, which is what gave the 2025 Coppa Italia a five-tie quarter-final.

A season whose calendar has not reached a final yet is the one case the backward walk cannot read,
because the last thing on it is an early round. That is detected first, on the only signal that
separates the two -- a finished knockout ends in exactly one tie -- and such a season is labelled
from its last round forwards instead.

Dates for a round with no fixtures at all come from the PREVIOUS season, matched by round label
and shifted by a whole number of weeks, because a cup round is pinned to a weekday.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from functools import cached_property
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CupRules:
    """One competition's rules, each measured on our own fixture table.

    `extra_time`      -- a tie level at the final whistle plays extra time before a shootout.
    `two_leg_labels`  -- rounds played over two legs, by label.
    `neutral_final`   -- the final is at a neutral venue (rulebook: there is no venue column).
    `lower_hosts`     -- P(the lower-division side hosts) when a drawn tie is between a top-flight
                         team and one from outside it. 0.5 is a coin, 1.0 a hard rule.
    `evidence`        -- what the numbers above were counted from.
    """
    extra_time: bool
    two_leg_labels: frozenset
    neutral_final: bool
    lower_hosts: float
    evidence: str


# Extra time. Read off `minutes` on shootout rows, which is unambiguous: a tie that played extra
# time before its shootout is recorded at 120 minutes, one that went straight there at 90.
#   FA Cup            17 shootouts, ALL at 120'  + 12 ties settled in extra time -> extra time
#   Copa del Rey      12 shootouts, ALL at 120'  + 15 settled in extra time      -> extra time
#   DFB Pokal         12 shootouts, ALL at 120'  +  8 settled in extra time      -> extra time
#   EFL Cup           30 shootouts, ALL at  90'  +  0 settled in extra time      -> none
#   Coupe de France   90 shootouts, ALL at  90'  +  0 settled in extra time      -> none
#   Coppa Italia      17 shootouts, 16 at 90' and ONE at 120' -- and that one is the 2026-04-22
#                     Atalanta v Lazio SEMI-FINAL SECOND LEG. So the single-leg rounds go straight
#                     to penalties and only the two-legged semi plays extra time, which is the
#                     ordinary aggregate rule and needs no special case: `resolve_two_legs` always
#                     plays extra time, `resolve_single_leg` is passed this flag.
#
# Two-legged rounds. Counted as pairings that appear TWICE in a competition-season. Exactly two
# such pairings in the EFL Cup 2025, the Coppa Italia 2025 and the Copa del Rey 2025 -- the two
# semi-finals -- and none at all in the FA Cup, the DFB Pokal or the Coupe de France.
#
# Who hosts a drawn tie, when one side is outside the modelled top flight. Counted over the rounds
# a simulator would actually DRAW, so the first round is excluded where its rule differs:
#   Copa del Rey      52 of 52 (1.00) in every round -- a hard rule, the lower side always hosts
#   DFB Pokal         R1 18 of 18 (1.00), but R2 onward 6 of 13 (0.46) -- the amateur-hosts rule
#                     stops binding once only professional clubs are left, so a coin from R2
#   FA Cup            17 of 30 from R3 (0.57) -- a coin
#   EFL Cup           14 of 27 from R2 (0.52) -- a coin
#   Coupe de France   17 of 28 from R3 (0.61) -- leans to the lower side but z = +1.1, a coin
#   Coppa Italia      2 of 26 (0.08) -- the SEEDED side hosts, the reverse of the others. By the
#                     round of 16 every survivor is a Serie A club, so the case never arises in a
#                     round this module draws; 0.0 records the direction rather than doing work.
CUP_RULES: Dict[str, CupRules] = {
    "English FA Cup": CupRules(
        extra_time=True, two_leg_labels=frozenset(), neutral_final=True, lower_hosts=0.5,
        evidence="17 shootouts all at 120'; no repeated pairing; lower side hosts 17/30 from R3"),
    "English League Cup": CupRules(
        extra_time=False, two_leg_labels=frozenset({"SF"}), neutral_final=True, lower_hosts=0.5,
        evidence="30 shootouts all at 90'; 2 repeated pairings (SF); lower hosts 14/27 from R2"),
    "German DFB Pokal": CupRules(
        extra_time=True, two_leg_labels=frozenset(), neutral_final=True, lower_hosts=0.5,
        evidence="12 shootouts all at 120'; no repeated pairing; lower hosts 6/13 from R2"),
    "Italian Coppa Italia": CupRules(
        extra_time=False, two_leg_labels=frozenset({"SF"}), neutral_final=True, lower_hosts=0.0,
        evidence="16 of 17 shootouts at 90', the 120' one a two-leg SF; lower hosts 2/26"),
    "Spanish Copa del Rey": CupRules(
        extra_time=True, two_leg_labels=frozenset({"SF"}), neutral_final=True, lower_hosts=1.0,
        evidence="12 shootouts all at 120'; 2 repeated pairings (SF); lower hosts 52/52"),
    "French Coupe de France": CupRules(
        extra_time=False, two_leg_labels=frozenset(), neutral_final=True, lower_hosts=0.5,
        evidence="90 shootouts all at 90'; no repeated pairing; lower hosts 17/28 from R3"),
}

# A round is named the way a reader names it. The tail of every cup is 1 tie, then 2, then 4, so
# the labels are assigned by counting BACKWARDS from the final -- which is also the only direction
# that survives the mess in a cup's early rounds. A block that does not fit the doubling sequence
# is a preliminary feeding the round after it, and is labelled as one rather than being forced
# into a name it does not have: the Coppa Italia plays two ties in mid-September whose winners
# take two of the sixteen round-of-16 places, and calling that a semi-final because it has two
# ties in it would be wrong twice over.
_NAMED: Dict[int, str] = {1: "F", 2: "SF", 4: "QF"}


def round_label(n_ties: int) -> str:
    """"F", "SF", "QF", else "R<teams>" -- R16 for eight ties, R32 for sixteen."""
    if n_ties < 1:
        raise ValueError(f"a round needs at least one tie, got {n_ties}")
    return _NAMED.get(n_ties, f"R{2 * n_ties}")


def labels_after(n_ties: int) -> List[str]:
    """Every round AFTER one of `n_ties` ties, in order, down to the final."""
    out, n = [], n_ties
    while n > 1:
        n //= 2
        out.append(round_label(n))
    return out


# --------------------------------------------------------------------------- the calendar
@dataclass
class CupRound:
    """One round on the calendar.

    `ties` is set wherever the fixture list names the pairings, and an entry may be a bracket SLOT
    ("Genoa/Sudtirol") rather than a club -- the runner resolves those against the teams actually
    alive in its own world. `ties` is None when the round must be drawn.
    """
    competition: str
    season: int
    label: str
    n_ties: int
    leg1: pd.Timestamp
    leg2: Optional[pd.Timestamp]
    neutral: bool
    ties: Optional[List[Tuple[str, str]]] = None      # (leg-1 host, leg-1 visitor)
    entrants: Tuple[str, ...] = ()                    # sides entering the cup AT this round
    walkovers: Tuple[str, ...] = ()                   # through without playing: see cup_handover
    fixture_index: Tuple[Any, ...] = ()
    # (leg-1 host, leg-1 visitor) -> who went through, for ties in THIS round already played. The
    # handover round is routinely half-played -- six of the League Cup's sixteen third-round ties
    # were done on the night this was written -- and a shootout is not in the fixture table, so
    # the winner is settled once here rather than re-flipped in all 10,000 worlds.
    settled: Dict[Tuple[str, str], str] = dc_field(default_factory=dict)

    @property
    def two_leg(self) -> bool:
        return self.leg2 is not None

    @cached_property
    def fixture_ids(self) -> frozenset:
        """`fixture_index` as a set, built once: it is asked of every tie in every world."""
        return frozenset(self.fixture_index)


def date_blocks(rows: pd.DataFrame, gap_days: int = 9) -> List[pd.DataFrame]:
    """Split fixtures into rounds by gaps in the calendar. A cup round spans a few days; the gap
    to the next is weeks. 9 days separates them in every competition-season we hold."""
    if rows.empty:
        return []
    rows = rows.sort_values("kickoff")
    days = rows["kickoff"].dt.normalize()
    out: List[List[Any]] = [[]]
    prev: Optional[pd.Timestamp] = None
    for idx, day in zip(rows.index, days):
        if prev is not None and (day - prev).days > gap_days:
            out.append([])
        out[-1].append(idx)
        prev = day
    return [rows.loc[b] for b in out if b]


def split_rounds(comp_season: pd.DataFrame, rules: CupRules
                 ) -> List[Tuple[str, List[Any], Optional[List[Any]]]]:
    """(label, leg-1 row labels, leg-2 row labels or None) per round, in calendar order.

    Works on FIXTURES, not on date blocks, because a block is not reliably a round. Two rounds
    eight days apart merge into one block -- the 2025 Copa del Rey played its quarter-finals on
    3-5 February and the first legs of its semi-finals on the 11th-12th, and a nine-day gap rule
    puts all six in the same bucket, after which the semi-final looks like a single-leg round and
    the quarter-final vanishes. Clustering by date also mis-assigns a postponed tie, which is how
    the 2025 Coppa Italia's quarter-final came out with five ties in it.

    So the walk goes BACKWARDS from the final over the fixtures themselves, taking the last tie,
    then the last two, then four. A two-legged round finds its first leg by MATCHING PAIRINGS
    rather than by counting -- the same two teams, played earlier -- which no amount of calendar
    drift can confuse.

    It stops as soon as the next slice is not a round: a round cannot contain the same team twice,
    so a slice that does is a sign the doubling has run past the start of the knockout proper.
    Everything before that point is preliminary and keeps its own date blocks, because those
    rounds are uneven by design (teams enter at different stages) and no arithmetic describes them.
    """
    rows = comp_season.sort_values("kickoff")
    home = rows["home"].to_dict()
    away = rows["away"].to_dict()
    pair = {i: frozenset((home[i], away[i])) for i in rows.index}

    def is_round(labels: Sequence[Any]) -> bool:
        seen: Set[str] = set()
        for i in labels:
            if home[i] in seen or away[i] in seen:
                return False
            seen.update((home[i], away[i]))
        return True

    # A season whose calendar does not reach a final cannot be walked backwards at all: the last
    # thing on it is an early round, not the trophy. The English League Cup in September has three
    # rounds scheduled and nothing after them, and reading the third round as a final labels every
    # round in the competition wrongly. So the two cases are separated first, on the one signal
    # that distinguishes them -- a completed knockout ends in exactly one tie.
    blocks = date_blocks(rows)
    if not blocks:
        return []
    if len(blocks[-1]) != 1:
        last = list(blocks[-1].index)
        out: List[Tuple[str, List[Any], Optional[List[Any]]]] = [
            ("PR", list(b.index), None) for b in blocks[:-1]]
        out.append((round_label(len(last)) if is_round(last) else "PR", last, None))
        return _number_prelims(out)

    idx: List[Any] = list(rows.index)
    tail: List[Tuple[str, List[Any], Optional[List[Any]]]] = []
    want = 1
    while len(idx) >= want:
        label = round_label(want)
        if label in rules.two_leg_labels and len(idx) >= 2 * want:
            leg2 = idx[-want:]
            wanted = {pair[i] for i in leg2}
            rest = idx[:-want]
            leg1 = [i for i in rest if pair[i] in wanted][-want:]
            if len(leg1) == want and is_round(leg2) and is_round(leg1):
                tail.append((label, leg1, leg2))
                drop = set(leg1)
                idx = [i for i in rest if i not in drop]
                want *= 2
                continue
        slice_ = idx[-want:]
        if not is_round(slice_):
            break
        tail.append((label, slice_, None))
        idx = idx[:-want]
        want *= 2
    tail.reverse()

    prelim = [("PR", list(b.index), None) for b in date_blocks(rows.loc[idx])] if idx else []
    return _number_prelims(prelim + tail)


def _number_prelims(rounds: List[Tuple[str, List[Any], Optional[List[Any]]]]
                    ) -> List[Tuple[str, List[Any], Optional[List[Any]]]]:
    """Number the preliminary rounds in calendar order -- PR1, PR2 -- rather than by a block
    index, which is an implementation detail and reads as a gap when early blocks merge."""
    n = sum(1 for lab, _, _ in rounds if lab == "PR")
    if n == 0:
        return rounds
    out, k = [], 0
    for lab, a, b in rounds:
        if lab == "PR":
            k += 1
            out.append((f"PR{k}" if n > 1 else "PR", a, b))
        else:
            out.append((lab, a, b))
    return out


def tail_calendar(comp_season: pd.DataFrame, rules: CupRules
                  ) -> Dict[str, Tuple[pd.Timestamp, Optional[pd.Timestamp]]]:
    """Round label -> (leg 1, leg 2), for dating a round this season has not scheduled yet."""
    out: Dict[str, Tuple[pd.Timestamp, Optional[pd.Timestamp]]] = {}
    for label, leg1, leg2 in split_rounds(comp_season, rules):
        if label.startswith("PR"):
            continue
        out[label] = (comp_season.loc[leg1, "kickoff"].min(),
                      comp_season.loc[leg2, "kickoff"].min() if leg2 else None)
    return out


def _season_shift(this: pd.DataFrame, prev: pd.DataFrame) -> pd.Timedelta:
    """How far the previous season's calendar moves to land on this one, in whole weeks.

    Whole weeks because a cup round is pinned to a weekday -- a midweek round stays midweek and a
    weekend round stays on the weekend. Measured between the two seasons' first fixtures, the only
    round both are guaranteed to have.
    """
    days = (this["kickoff"].min() - prev["kickoff"].min()).days
    return pd.Timedelta(weeks=round(days / 7))


# --------------------------------------------------------------------------- the draw
def draw_round(label: str, field: Sequence[str], rules: CupRules,
               lower_division: Set[str], rng, n_ties: Optional[int] = None
               ) -> Tuple[List[Tuple[str, str]], Tuple[str, ...]]:
    """A free draw: shuffle the field, pair it off, then decide each tie's host.

    Returns ((leg-1 host, leg-1 visitor) per tie, teams receiving a bye). Unlike the UEFA draw
    there is no band, no seeding and no same-association protection to respect -- a domestic cup
    puts every survivor in one hat. The only structure is who gets home advantage, and that is
    `rules.lower_hosts`, measured per competition.

    `n_ties` caps the round: a field bigger than twice it sends the surplus through on a bye. That
    is how a round holding places for sides the fixture list does not name is played -- see
    `_late_entry_rounds` -- and a field that fits draws exactly as it always did.
    """
    order = list(np.array(field, dtype=object)[rng.permutation(len(field))])
    spare = len(order) % 2
    if n_ties is not None and len(order) > 2 * n_ties:
        spare = len(order) - 2 * n_ties
    byes: Tuple[str, ...] = ()
    if spare:
        byes = tuple(order[-spare:])   # the shuffle already made these uniform
        del order[-spare:]
    ties: List[Tuple[str, str]] = []
    for a, b in zip(order[0::2], order[1::2]):
        a_low, b_low = a in lower_division, b in lower_division
        if a_low == b_low:
            host_a = bool(rng.integers(2))            # same tier: a coin, in every competition
        else:
            low_hosts = rng.random() < rules.lower_hosts
            host_a = (a_low == low_hosts)
        ties.append((a, b) if host_a else (b, a))
    return ties, byes


# --------------------------------------------------------------------------- slot names
def _canon(name: str) -> str:
    """Fold a name to letters and digits. The published slot drops diacritics -- "Sudtirol" for
    "Südtirol" -- so the comparison has to as well."""
    text = str(name).lower()
    for a, b in (("ü", "u"), ("ö", "o"), ("ä", "a"), ("ø", "o"), ("å", "a"), ("é", "e"),
                 ("è", "e"), ("á", "a"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"),
                 ("ç", "c"), ("ß", "ss")):
        text = text.replace(a, b)
    return "".join(ch for ch in text if ch.isalnum())


def is_slot(name: object) -> bool:
    """True for a bracket slot rather than a club. Mirrors `master_fixtures.is_placeholder_team`,
    which is what put these rows in the table in the first place."""
    text = str(name).strip()
    low = text.lower()
    if low.startswith(("winner ", "loser ", "sieger ", "verlierer ", "vainqueur ", "ganador ",
                       "vincente ", "perdente ", "tbd", "to be determined", "bye")):
        return True
    return "/" in text and " / " not in text


def resolve_slot(slot: str, candidates: Sequence[str]) -> Optional[str]:
    """Match a bracket slot like "Genoa/Sudtirol" to one of `candidates`.

    A cup with a fixed bracket publishes a tie before its feeder has been played, naming the slot
    after the two teams that could fill it. The answer is whichever candidate matches either half.
    Returns None when nothing matches, which the caller fills from the unplaced survivors instead
    -- with only a handful of slots and the same handful of unplaced teams, that fallback lands on
    the right field even when the text does not parse.
    """
    halves = {_canon(h) for h in str(slot).split("/") if h.strip()}
    for cand in candidates:
        if _canon(cand) in halves:
            return cand
    return None


# --------------------------------------------------------------------------- handover
@dataclass
class CupHandover:
    """Where a simulator takes over a cup, and the field it takes over with.

    `rounds` are the rounds still to play, in order, `ties` set where the fixture list already
    names them. `field` is every team alive entering the first of those rounds -- survivors of the
    rounds already played, plus any side entering at this round rather than an earlier one, which
    is how a cup that seeds its top division straight into the round of 16 is handled.
    """
    competition: str
    season: int
    rules: CupRules
    rounds: List[CupRound] = dc_field(default_factory=list)
    field: List[str] = dc_field(default_factory=list)
    coin_flipped: List[str] = dc_field(default_factory=list)
    fixture_index: Tuple[Any, ...] = ()
    note: str = ""


def _tie_winner(row, next_round_teams: Set[str], rng, flipped: List[str]) -> str:
    """Who went through, from a played row.

    A shootout is not in the fixture table -- a `penalties` row carries only the score when the
    shootout began, which is a draw. So a level tie is decided by whoever appears in the next
    round, and only when that is unknown too by the fair coin `knockout.py` fits from 186 real
    shootouts.
    """
    gh, ga = float(row.home_goals), float(row.away_goals)
    if gh != ga:
        return str(row.home) if gh > ga else str(row.away)
    home_on, away_on = str(row.home) in next_round_teams, str(row.away) in next_round_teams
    if home_on != away_on:
        return str(row.home) if home_on else str(row.away)
    flipped.append(f"{row.home} v {row.away}")
    return str(row.home) if rng.integers(2) else str(row.away)


def _teams_after(comp_season: pd.DataFrame, when: pd.Timestamp) -> Set[str]:
    """Every team named in a fixture kicking off later than `when`.

    This is how a level tie is settled: the shootout is not in the table -- a `penalties` row
    carries only the score when it began, which is a draw -- but whoever went through usually
    turns up in a later fixture, and that is decisive where it applies.
    """
    later = comp_season[comp_season["kickoff"] > when]
    return set(later["home"]) | set(later["away"])


def _two_leg_winners(leg1: pd.DataFrame, leg2: pd.DataFrame, next_round_teams: Set[str],
                     rng, flipped: List[str]) -> List[str]:
    """Who went through a two-legged round, on aggregate over both legs.

    Leg 2 reverses the venue, so a tie is found by its unordered pair rather than by (home, away).
    A level aggregate was settled by extra time or a shootout the table does not record, so it
    falls to the same next-round-membership test the single-leg case uses.
    """
    agg: Dict[frozenset, Dict[str, float]] = {}
    for leg in (leg1, leg2):
        for r in leg.itertuples():
            key = frozenset((str(r.home), str(r.away)))
            tally = agg.setdefault(key, {})
            tally[str(r.home)] = tally.get(str(r.home), 0.0) + float(r.home_goals)
            tally[str(r.away)] = tally.get(str(r.away), 0.0) + float(r.away_goals)
    out: List[str] = []
    for r in leg1.itertuples():
        key = frozenset((str(r.home), str(r.away)))
        tally = agg[key]
        a, b = str(r.home), str(r.away)
        if tally.get(a, 0.0) != tally.get(b, 0.0):
            out.append(a if tally.get(a, 0.0) > tally.get(b, 0.0) else b)
            continue
        a_on, b_on = a in next_round_teams, b in next_round_teams
        if a_on != b_on:
            out.append(a if a_on else b)
        else:
            flipped.append(f"{a} v {b} (agg)")
            out.append(a if rng.integers(2) else b)
    return out


def _sides(rows: pd.DataFrame) -> Set[str]:
    """Every club named in `rows`, bracket slots aside."""
    return {str(t) for t in pd.concat([rows["home"], rows["away"]]) if not is_slot(t)}


def _date_round(label: str, hand: CupHandover,
                prev_cal: Dict[str, Tuple[pd.Timestamp, Optional[pd.Timestamp]]],
                shift: pd.Timedelta, prev_leg: pd.Timestamp
                ) -> Tuple[pd.Timestamp, Optional[pd.Timestamp]]:
    """(leg 1, leg 2) for a round the calendar does not hold yet, borrowed from last season."""
    two = label in hand.rules.two_leg_labels
    dates = prev_cal.get(label)
    if dates is not None:
        leg1: pd.Timestamp = dates[0] + shift
        leg2 = (dates[1] + shift) if dates[1] is not None else None
    else:
        leg1, leg2 = prev_leg + pd.Timedelta(weeks=6), None
        hand.note = (hand.note + f" {label} undated, spaced 6 weeks;").strip()
    if two and leg2 is None:
        leg2 = leg1 + pd.Timedelta(weeks=3)
    if not two:
        leg2 = None
    # a borrowed date that lands before the round it follows is worse than useless
    if leg1 <= prev_leg:
        leg1 = prev_leg + pd.Timedelta(weeks=4)
        leg2 = (leg1 + pd.Timedelta(weeks=3)) if two else None
        hand.note = (hand.note + f" {label} date pulled forward;").strip()
    return leg1, leg2


# --------------------------------------------------------------------------- late entrants
# A cup's top clubs do not play its first rounds. The FA Cup's Premier League and Championship
# sides enter at the third round, the Copa del Rey's Supercopa four at the round of 32, Ligue 1 at
# the Coupe de France's round of 64 -- and none of them is in the fixture list until that round is
# drawn. Halving the last scheduled round down to a final therefore built a cup without them: on
# 20 Oct 2026 the FA Cup's 40 first-round ties halved 20, 10, 5, 2, 1, a side took a bye into a
# three-team "final", and no Premier League club could win it.
#
# So a cup whose calendar stops short of where its late entrants come in is finished with LAST
# season's knockout proper, which the backward walk reads exactly, and they are seated in its
# first round. Who they are is read from the fixture list, never assumed:
#   * a top-flight club not yet named anywhere in the cup is exempt to a later round;
#   * if last season's first knockout round also took sides from outside the top flight, the
#     same number come from clubs this season's OTHER domestic cups name and this one does not.
#     That is the Championship, read off the EFL Cup -- Premier League sides and the 48 League
#     One and Two clubs, who all play the FA Cup's first round, are both excluded. Nothing is
#     carried over from last season alone: a club named only there may since have dropped out of
#     the tier, and a cup tab naming a club that is not in it is worse than a gap.
# The rounds between the end of the calendar and the knockout proper halve the survivors into
# the places left over. A place nothing names -- the Coupe de France's Ligue 2 and overseas
# entrants, who are in no fixture of this season's -- is played as a bye, so the knockout proper
# keeps its exact size and the gap is stated rather than filled with an invention.
def _template_tail(prev_season: pd.DataFrame, rules: CupRules
                   ) -> List[Tuple[str, int, Set[str]]]:
    """Last season's knockout proper: (label, ties, sides first seen in that round) in order."""
    seen: Set[str] = set()
    tail: List[Tuple[str, int, Set[str]]] = []
    for label, leg1, _ in split_rounds(prev_season, rules):
        named = _sides(prev_season.loc[leg1])
        if not label.startswith("PR"):
            tail.append((label, len(leg1), named - seen))
        seen |= named
    return tail


def _late_entry(comp_season: pd.DataFrame, prev_season: Optional[pd.DataFrame],
                hand: CupHandover, top_flight: Optional[Set[str]],
                prev_top_flight: Optional[Set[str]], elsewhere: Optional[Set[str]]
                ) -> Optional[Tuple[List[Tuple[str, int, Set[str]]], List[str]]]:
    """(last season's knockout proper, who joins at its first round), or None to halve instead.

    None whenever nothing this season enters late, which is every cup whose fixture list already
    names its whole field -- or when there is no finished season to borrow the shape from.
    """
    if not top_flight or prev_season is None or prev_season.empty:
        return None
    tail = _template_tail(prev_season, hand.rules)
    if not tail or tail[-1][0] != "F":
        return None
    final = prev_season.loc[split_rounds(prev_season, hand.rules)[-1][1]]
    if not bool(final["played"].all()):
        return None
    named = _sides(comp_season)
    halves = {_canon(h) for t in pd.concat([comp_season["home"], comp_season["away"]])
              if is_slot(t) for h in str(t).split("/")}

    def unseen(t: str) -> bool:
        return t not in named and _canon(t) not in halves

    late = sorted(t for t in top_flight if unseen(t))
    if not late:
        return None
    entry, ties, entered = tail[0]
    want = len(entered - (prev_top_flight or set()))
    # clubs that also entered here last season first, so a surplus drops the least corroborated
    pool = sorted((t for t in (elsewhere or set()) if t not in top_flight and unseen(t)),
                  key=lambda t: (t not in entered, t))
    late += pool[:want]
    slots = 2 * ties - len(late)
    if not 0 < slots <= hand.rounds[-1].n_ties:
        hand.note = (hand.note + f" {len(late)} late entrants do not fit last season's {entry} "
                                 f"behind {hand.rounds[-1].n_ties} ties; halved instead;").strip()
        return None
    return tail, late


def _late_entry_rounds(hand: CupHandover, tail: List[Tuple[str, int, Set[str]]],
                       entrants: List[str],
                       prev_cal: Dict[str, Tuple[pd.Timestamp, Optional[pd.Timestamp]]],
                       shift: pd.Timedelta) -> None:
    """Finish `hand` with bridging rounds, then last season's knockout proper, entrants seated."""
    rules = hand.rules
    entry, entry_ties, _ = tail[0]
    slots = 2 * entry_ties - len(entrants)
    last = hand.rounds[-1]
    prev_leg = last.leg2 or last.leg1
    # each bridging round halves at most, so enough of them to fit the field into the slots
    field, k = last.n_ties, 0
    while field > slots * 2 ** k:
        k += 1
    dates = prev_cal.get(entry)
    entry_at = ((dates[0] + shift) if dates is not None
                else prev_leg + pd.Timedelta(weeks=6 * (k + 1)))
    if entry_at <= prev_leg:
        entry_at = prev_leg + pd.Timedelta(weeks=4 * (k + 1))
    byes: List[Tuple[CupRound, int]] = []
    for i in range(1, k + 1):
        target = slots * 2 ** (k - i)
        rnd = CupRound(hand.competition, hand.season, "PR", field - target,
                       prev_leg + (entry_at - prev_leg) * (i / (k + 1)), None, neutral=False)
        hand.rounds.append(rnd)
        if 2 * target > field:
            byes.append((rnd, 2 * target - field))
        field = target
    # everything before the knockout proper is preliminary, numbered in calendar order, which is
    # what a finished season's backward walk calls the same rounds
    for i, rnd in enumerate(hand.rounds, 1):
        rnd.label = "PR" if len(hand.rounds) == 1 else f"PR{i}"
    for rnd, n in byes:
        hand.note = (hand.note + f" {rnd.label}: {n} byes hold places no fixture names;").strip()
    prev_leg = hand.rounds[-1].leg2 or hand.rounds[-1].leg1
    for j, (label, ties, _) in enumerate(tail):
        leg1, leg2 = _date_round(label, hand, prev_cal, shift, prev_leg)
        hand.rounds.append(CupRound(hand.competition, hand.season, label, ties, leg1, leg2,
                                    neutral=(label == "F" and rules.neutral_final),
                                    entrants=tuple(entrants) if j == 0 else ()))
        prev_leg = leg2 or leg1
    hand.note = (hand.note + f" {entry}: {len(entrants)} enter late;").strip()


def cup_handover(comp_season: pd.DataFrame, prev_season: Optional[pd.DataFrame],
                 rng, top_flight: Optional[Set[str]] = None,
                 prev_top_flight: Optional[Set[str]] = None,
                 elsewhere: Optional[Set[str]] = None) -> CupHandover:
    """Split one cup-season into what is settled and what must be simulated.

    `top_flight` and `prev_top_flight` are the country's league this season and last, and
    `elsewhere` every club this season's other domestic cups of that country name. They are what
    finds the sides who enter late -- see `_late_entry`. Without them the cup halves down to a
    final from the end of its calendar, which is right only when nobody enters late.

    Walks the rounds in calendar order. A round every one of whose ties is played is settled: its
    rows stay on the ordinary fixture path, where they move each world's state like any other
    match, and only its WINNERS carry forward. The first round holding an unplayed tie is the
    handover, and everything from there is the simulator's -- including that round's already-played
    ties, which it replays itself so that one round is resolved in one place.

    Survivors are tracked as a running set, not as "the winners of the last block". A cup lets a
    team sit out a round: twenty ties in August produce twenty survivors, only twelve of whom play
    again in September, and the other eight are still very much in the competition. Taking the last
    block's winners as the field lost them, and the round of 16 came out with ten teams in it.
    """
    comp = str(comp_season["competition"].iloc[0])
    season = int(comp_season["season"].iloc[0])
    rules = CUP_RULES.get(comp)
    if rules is None:
        raise NotImplementedError(f"no rules recorded for {comp}")
    hand = CupHandover(comp, season, rules)

    tbd = comp_season.get("tbd", pd.Series(False, index=comp_season.index)).astype(bool)
    if comp_season[~tbd].empty:
        hand.note = "no fixtures"
        return hand

    labelled = split_rounds(comp_season, rules)

    # ---- walk the settled rounds, carrying every survivor forward
    alive: List[str] = []
    take_from: Optional[int] = None
    for k, (label, leg1_idx, leg2_idx) in enumerate(labelled):
        idx = [leg1_idx] + ([leg2_idx] if leg2_idx else [])
        rows = comp_season.loc[leg1_idx + (leg2_idx or [])]
        if bool(tbd.reindex(rows.index, fill_value=False).any()) \
                or not rows["played"].all() or rows["home_goals"].isna().any():
            take_from = k
            break
        if leg2_idx:
            on = _teams_after(comp_season, rows["kickoff"].max())
            winners = _two_leg_winners(comp_season.loc[leg1_idx], comp_season.loc[leg2_idx],
                                       on, rng, hand.coin_flipped)
            for t in dict.fromkeys(list(rows["home"]) + list(rows["away"])):
                if t not in alive:
                    alive.append(t)
            alive = [t for t in alive
                     if t in set(winners) or t not in {tt for r in rows.itertuples()
                                                       for tt in (r.home, r.away)}]
            continue
        # One tie at a time, in kickoff order. A date block is not always one round: the Coppa
        # Italia's opening fortnight holds a preliminary round AND the round it feeds, five days
        # apart, so 20 ties are played between 36 teams. Resolving the block as a set let a side
        # that won on the 8th and lost on the 14th count as a winner and stay alive, and the field
        # came out one too big. Walking the ties in order cannot make that mistake.
        for r in rows.sort_values("kickoff").itertuples():
            for t in (str(r.home), str(r.away)):
                if t not in alive:
                    alive.append(t)
            winner = _tie_winner(r, _teams_after(comp_season, r.kickoff), rng, hand.coin_flipped)
            loser = str(r.away) if winner == str(r.home) else str(r.home)
            if loser in alive:
                alive.remove(loser)
    if take_from is None:
        hand.note = "complete"
        return hand

    # ---- the rounds still to play. Those the calendar holds keep their own size and pairings;
    # anything past the end of the calendar is last season's knockout proper with the late
    # entrants seated in it, or, when nobody enters late, halves down to a final. Either way it
    # is dated from last season.
    prev_cal: Dict[str, Tuple[pd.Timestamp, Optional[pd.Timestamp]]] = {}
    shift = pd.Timedelta(0)
    if prev_season is not None and not prev_season.empty:
        prev_cal = tail_calendar(prev_season, rules)
        shift = _season_shift(comp_season, prev_season)

    for label, leg1_idx, leg2_idx in labelled[take_from:]:
        first = comp_season.loc[leg1_idx].sort_values("kickoff")
        rows = comp_season.loc[leg1_idx + (leg2_idx or [])]
        named, booked, walk = [], set(), []
        for r in first.itertuples():
            tie = (str(r.home), str(r.away))
            # A side cannot have two ties still to play in one round, but Fotmob can list it in
            # two: the 2026 Coupe de France's sixth round has Ginglin Cesson Saint Brieuc v Rennes
            # TA AND v Plaintel, under one team id. Played as listed it could go through twice and
            # meet itself in the next draw. Which listing is wrong is unknowable, so the first is
            # kept and the other tie's opponent goes through on a walkover, which is noted. Only
            # UNPLAYED ties are compared: a block can hold two rounds back to back (the 2025
            # Coupe de France's sixth and seventh), where a side that won its first tie
            # legitimately plays again, and a played tie is history that must replay exactly.
            if not bool(r.played):
                twice = [t for t in tie if t in booked and not is_slot(t)]
                if twice:
                    walk.append(tie[1] if tie[0] == twice[0] else tie[0])
                    hand.note = (hand.note + f" {twice[0]} listed twice in one round; "
                                             f"{walk[-1]} given a walkover;").strip()
                    continue
                booked.update(tie)
            named.append(tie)
        # A round in which EVERY side is a bracket slot tells us nothing about the pairings. The
        # Coppa Italia's quarter-finals read "Winner EF1 v Winner EF2", and which round-of-16 tie
        # is EF1 is not in the data -- the numbering is Fotmob's and appears nowhere we can join
        # on. So the fixed bracket is honoured exactly as far as it is legible (the round of 16,
        # whose pairings ARE named) and drawn beyond that, which is the same rule `uefa_bracket`
        # applies: take the draw from the fixture list where it exists, draw the rest.
        all_slots = all(is_slot(t) for tie in named for t in tie)
        hand.rounds.append(CupRound(
            comp, season, label, len(first),
            first["kickoff"].min(),
            comp_season.loc[leg2_idx, "kickoff"].min() if leg2_idx else None,
            neutral=(label == "F" and rules.neutral_final),
            ties=None if all_slots else named,
            entrants=tuple(t for t in dict.fromkeys(list(first["home"]) + list(first["away"]))
                           if not is_slot(t)),
            walkovers=tuple(walk),
            fixture_index=tuple(rows.index)))

    # A side named in a later round's UNPLAYED tie while it still has a tie to play in an earlier
    # one is a place that tie decides, not a club already through. Live, that cannot happen --
    # Fotmob writes a slot ("Genoa/Südtirol") until the feeder is played -- but a season REWOUND
    # by `projection.as_of_fixtures` keeps the names Fotmob has since written: rewound to 11 Sep
    # 2026, Genoa had still to play Südtirol on the 15th yet stood in the round of 16, and so
    # reached it in every world whatever happened. So such a side becomes the slot its earlier tie
    # fills. Two things it must leave alone: a later tie already PLAYED, which is history, and an
    # earlier tie ABANDONED -- one that was never replayed was decided off the pitch, and the club
    # Fotmob names after it is the one that went through (Caen PTT v Evreux, Coupe de France 2025).
    pending: Dict[str, str] = {}
    for rnd in hand.rounds:
        rows = (comp_season.loc[list(rnd.fixture_index)] if rnd.fixture_index
                else comp_season.iloc[:0])
        if rnd.ties is not None and pending:
            done = {(str(r.home), str(r.away)) for r in rows[rows["played"]].itertuples()}
            moved: Set[str] = set()
            ties: List[Tuple[str, str]] = []
            for tie in rnd.ties:
                if tie not in done:
                    moved.update(t for t in tie if t in pending)
                    tie = (f"{tie[0]}/{pending[tie[0]]}" if tie[0] in pending else tie[0],
                           f"{tie[1]}/{pending[tie[1]]}" if tie[1] in pending else tie[1])
                ties.append(tie)
            rnd.ties = ties
            rnd.entrants = tuple(t for t in rnd.entrants if t not in moved)
        aborted = (rows["outcome"].eq("aborted") if "outcome" in rows
                   else pd.Series(False, index=rows.index))
        for r in rows[~rows["played"] & ~aborted].itertuples():
            if not is_slot(r.home) and not is_slot(r.away):
                pending[str(r.home)], pending[str(r.away)] = str(r.away), str(r.home)

    for rnd in hand.rounds:
        if not rnd.fixture_index:
            continue
        rows = comp_season.loc[list(rnd.fixture_index)]
        rows = rows[rows["played"] & rows["home_goals"].notna()]
        for r in rows.itertuples():
            rnd.settled[(str(r.home), str(r.away))] = _tie_winner(
                r, _teams_after(comp_season, r.kickoff), rng, hand.coin_flipped)

    late = _late_entry(comp_season, prev_season, hand, top_flight, prev_top_flight, elsewhere)
    if late is not None:
        _late_entry_rounds(hand, *late, prev_cal, shift)
    else:
        last = hand.rounds[-1]
        prev_leg = last.leg2 or last.leg1
        for label in labels_after(last.n_ties):
            leg1, leg2 = _date_round(label, hand, prev_cal, shift, prev_leg)
            n = hand.rounds[-1].n_ties // 2
            hand.rounds.append(CupRound(comp, season, label, n, leg1, leg2,
                                        neutral=(label == "F" and rules.neutral_final)))
            prev_leg = leg2 or leg1

    hand.field = list(hand.rounds[0].entrants) + [t for t in alive
                                                  if t not in set(hand.rounds[0].entrants)]
    # rows the ordinary fixture path must NOT play: every round from the handover on, plus every
    # slot-only row anywhere, which names no team and is only ever read for its date
    hand.fixture_index = tuple(i for r in hand.rounds for i in r.fixture_index) \
        + tuple(comp_season.index[tbd.to_numpy()])
    hand.fixture_index = tuple(dict.fromkeys(hand.fixture_index))
    return hand


def _country(fixtures: pd.DataFrame, src: pd.DataFrame, comp: str, season: int,
             prev_season: int) -> Dict[str, Set[str]]:
    """The `cup_handover` keywords that find late entrants: the cup's country's top flight this
    season and in `prev_season`, and every club the country's other cups name this season."""
    country = comp.split()[0] + " "
    home = fixtures[(fixtures.season == season) & fixtures.competition.str.startswith(country)]
    prev_league = src[(src.season == prev_season) & (src.kind == "league")
                      & src.competition.str.startswith(country)]
    return {"top_flight": _sides(home[home.kind == "league"]),
            "prev_top_flight": _sides(prev_league),
            "elsewhere": _sides(home[(home.kind == "cup") & (home.competition != comp)])}


def cup_handovers(fixtures: pd.DataFrame, master: Optional[pd.DataFrame], rng
                  ) -> Dict[Tuple[str, int], CupHandover]:
    """Where the simulator takes over each domestic cup in `fixtures`.

    `master` supplies the previous season, which is where an undated round's calendar comes from,
    and last season's league, which is half of how a late entrant is recognised. A competition's
    country is its first word -- "English", "Spanish" -- which is how the data names all fourteen.
    A cup with no rules recorded, no fixtures, or nothing left to play is skipped.
    """
    src = fixtures if master is None else master
    out: Dict[Tuple[str, int], CupHandover] = {}
    for (comp, season), g in fixtures[fixtures.kind == "cup"].groupby(["competition", "season"]):
        prev = src[(src.competition == comp) & (src.season == season - 1)]
        try:
            hand = cup_handover(g, prev if not prev.empty else None, rng,
                                **_country(fixtures, src, comp, season, season - 1))
        except NotImplementedError:
            continue
        if hand.rounds:
            out[(comp, season)] = hand
    return out


# --------------------------------------------------------------------------- verification
def _verify_late_entry(g: pd.DataFrame, master: pd.DataFrame, rules: CupRules,
                       ctx: str) -> List[str]:
    """Cut a cup-season whose final is played back to its first round and rebuild it."""
    season = int(g["season"].iloc[0])
    cut = g.loc[date_blocks(g)[0].index].copy()
    cut["played"] = False
    cut[["home_goals", "away_goals"]] = np.nan
    hand = cup_handover(cut, g, np.random.default_rng(0),
                        **_country(master, master, str(g["competition"].iloc[0]), season, season))
    real = split_rounds(g, rules)
    want = [(lab, len(l1)) for lab, l1, _ in real if not lab.startswith("PR")]
    got = [(r.label, r.n_ties) for r in hand.rounds if not r.label.startswith("PR")]
    if got != want:
        return [f"{ctx}: cut to its first round, rebuilt {got}, really {want}"]
    seen: Set[str] = set()
    for lab, l1, _ in real:
        named = _sides(g.loc[l1])
        if lab == want[0][0]:
            entry = next(r for r in hand.rounds if r.label == lab)
            # a round the cut still holds names its own field; only a rebuilt one has entrants to
            # check, and they must be exactly the clubs first seen there
            if entry.fixture_index:
                return []
            if set(entry.entrants) != named - seen:
                extra = sorted(set(entry.entrants) - (named - seen))[:3]
                lost = sorted((named - seen) - set(entry.entrants))[:3]
                return [f"{ctx}: late entrants at {lab} wrong — seated {extra}, missed {lost}"]
            return []
        seen |= named
    return []


def verify(master: pd.DataFrame) -> List[str]:
    """Check the module against every cup-season we hold. Returns failures, empty when clean.

    Three properties, each of which was wrong at some point while this was written:

      * a COMPLETE season hands over nothing. If the walk cannot resolve a finished cup all the
        way to its final, the round labelling or the survivor tracking is broken.
      * the labels a complete season derives run ... QF, SF, F, and every non-preliminary round is
        exactly twice the size of the one after it.
      * a drawn round uses every team once and nobody twice, and its host split matches the rule
        that competition was given.
      * a finished season cut back to its first round, as on the night only that round had been
        drawn, rebuilds to its real knockout proper, with exactly the clubs who really joined
        late seated in its first round. Built from its OWN shape, because the cups begin in 2025
        and no finished season has a finished one before it -- so this tests who is found to
        enter late, which is the part that has to be inferred, not the shape, which is borrowed.
    """
    fails: List[str] = []
    for (comp, season), g in master[master.kind == "cup"].groupby(["competition", "season"]):
        rules = CUP_RULES.get(comp)
        if rules is None:
            continue
        ctx = f"{comp} {season}"
        labelled = split_rounds(g, rules)
        if labelled and labelled[-1][0] == "F" and bool(g.loc[labelled[-1][1], "played"].all()):
            fails += _verify_late_entry(g, master, rules, ctx)
        if not bool(g["played"].all()):
            continue
        hand = cup_handover(g, None, np.random.default_rng(0))
        if hand.note != "complete":
            fails.append(f"{ctx}: a finished cup did not resolve — note={hand.note!r}, "
                         f"{len(hand.rounds)} rounds left")
            continue
        labels = [lab for lab, _, _ in labelled]
        real = [lab for lab in labels if not lab.startswith("PR")]
        if real[-3:] != ["QF", "SF", "F"]:
            fails.append(f"{ctx}: tail is {real[-3:]}, expected QF SF F")

    # the draw itself, over a field big enough for the host split to mean something
    rng = np.random.default_rng(7)
    field = [f"T{i}" for i in range(32)]
    lower = {t for i, t in enumerate(field) if i % 2}
    for comp, rules in CUP_RULES.items():
        seen: Dict[str, int] = {}
        low_hosted = mixed = 0
        for _ in range(400):
            ties, byes = draw_round("R32", field, rules, lower, rng)
            if len(ties) * 2 + len(byes) != len(field):
                fails.append(f"{comp}: draw produced {len(ties)} ties + {len(byes)} byes "
                             f"for {len(field)} teams")
                break
            flat = [t for tie in ties for t in tie] + list(byes)
            if sorted(flat) != sorted(field):
                fails.append(f"{comp}: a draw did not use every team exactly once")
                break
            for t in flat:
                seen[t] = seen.get(t, 0) + 1
            for host, away in ties:
                if (host in lower) != (away in lower):
                    mixed += 1
                    low_hosted += int(host in lower)
        if mixed:
            rate = low_hosted / mixed
            if abs(rate - rules.lower_hosts) > 0.05:
                fails.append(f"{comp}: lower side hosted {rate:.3f} of {mixed} mixed ties, "
                             f"rule says {rules.lower_hosts}")
    return fails


if __name__ == "__main__":
    import sys as _sys
    _master = pd.read_pickle("data/master_fixtures.pkl")
    _fails = verify(_master)
    for f in _fails:
        print("  FAIL  " + f)
    print(f"cup_bracket: {len(_fails)} failure(s)")
    _sys.exit(1 if _fails else 0)
