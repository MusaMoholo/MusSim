"""Pure post-2024 UEFA entry allocation from one world's final tables and champions.

UCL/UEL/UECL here mean entry rights, including qualifying rounds, not guaranteed league-phase
places. The supported five associations have four base UCL entries, two UEL and one UECL; France
has three direct UCL places plus one qualifier. The frozen EPS assumption defaults to England
and Spain, rather than forecasting association coefficients. Clubs choose the higher competition.
Pre-2024 access lists and non-five-league association quotas belong to the caller's legacy/global
handling. No random draws, simulation state, data frames, I/O or input mutation occur here.

Official rules: UCL Article 3.03 (titleholder lower-quota consumption), 3.08–3.09 (EPS last and
its domestic cascade); UEL Article 3.03–3.05 (domestic cup cascades), 3.08–3.14 (Conference TH).
https://documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2026/27/Article-3-Entries-for-the-competition-Online
https://documents.uefa.com/r/Regulations-of-the-UEFA-Europa-League-2026/27/Article-3-Entries-for-the-competition-Online
The 2027/28 access list supplies the base quotas; domestic cups/English League Cup own their
association slots even when the winner is outside the simulated top division.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

UCL = "UEFA Champions League"
UEL = "UEFA Europa League"
UECL = "UEFA Conference League"

# Main cup supplies one of the two UEL entries; England's League Cup supplies its UECL entry.
DOMESTIC_CUPS = {
    "English Premier League": ("English FA Cup", "English League Cup"),
    "Spanish La Liga": ("Spanish Copa del Rey", None),
    "Italian Serie A": ("Italian Coppa Italia", None),
    "German Bundesliga": ("German DFB Pokal", None),
    "French Ligue 1": ("French Coupe de France", None),
}
FROZEN_EPS = ("English Premier League", "Spanish La Liga")


def qualification_policies(season: int, eps_leagues: Iterable[str] = FROZEN_EPS
                           ) -> dict[str, dict[str, Any]]:
    """Five-league entry quotas for the post-2024 format, with an explicit frozen EPS choice."""
    if int(season) < 2024:
        raise ValueError("Pre-2024 qualification requires the caller's legacy access-list policy")
    eps = set(eps_leagues)
    unknown = eps - DOMESTIC_CUPS.keys()
    if unknown:
        raise ValueError(f"Unknown EPS association(s): {sorted(unknown)}")
    return {league: {"ucl": 4, "uel": 2, "uecl": 1, "eps": int(league in eps),
                     "cup": cup, "league_cup": league_cup,
                     "ucl_direct": 3 if league == "French Ligue 1" else 4}
            for league, (cup, league_cup) in DOMESTIC_CUPS.items()}


def _quota(policy: Mapping[str, Any], name: str) -> int:
    value = policy.get(name, 0)
    number = int(value)
    if number < 0 or number != value:
        raise ValueError(f"Invalid {name} qualification quota: {value!r}")
    return number


def _fill(order: Sequence[str], selected: set[str], blocked: set[str], target: int) -> None:
    for team in order:
        if len(selected) >= target:
            break
        if team not in blocked:
            selected.add(team)


def _domestic_base(order: Sequence[str], policy: Mapping[str, Any], champions: Mapping[str, str]
                   ) -> dict[str, set[str]]:
    """Domestic entry rights before titleholders and EPS; quotas already include the cup seats."""
    ucl = set(order[:_quota(policy, "ucl")])
    uel: set[str] = set()
    cup = champions.get(policy.get("cup"))
    if _quota(policy, "uel") and cup and cup not in ucl:
        uel.add(cup)
    _fill(order, uel, ucl, _quota(policy, "uel"))
    uecl: set[str] = set()
    league_cup = champions.get(policy.get("league_cup"))
    if _quota(policy, "uecl") and league_cup and league_cup not in ucl | uel:
        uecl.add(league_cup)
    _fill(order, uecl, ucl | uel, _quota(policy, "uecl"))
    return {"ucl": ucl, "uel": uel, "uecl": uecl}


def seat_world(orders: Mapping[str, Sequence[str]], champions: Mapping[str, str],
               policies: Mapping[str, Mapping[str, Any]], associations: Mapping[str, str]
               ) -> dict[str, dict[str, set[str]]]:
    """Seat one world's UEFA entrants, retaining lower-division cup winners in their association.

    Classify CL/EL titleholders against the original domestic base. Moving one from UEL/UECL
    consumes that association's lower quota; no replacement is created by the titleholder.
    EPS is then awarded to the highest league finisher outside UCL, and its vacancies cascade.
    Only afterwards apply the Conference titleholder's UEL right if it is not already in UCL.
    A Conference TH already in base UEL reserves an ordinary quota seat; base UECL instead
    consumes that lower seat and adds a UEL right; otherwise its UEL right is additional.
    """
    tables = {league: list(order) for league, order in orders.items() if league in policies}
    affiliation = dict(associations)
    domestic_owner: dict[str, str] = {}
    for league, order in tables.items():
        if len(order) != len(set(order)):
            raise ValueError(f"Duplicate clubs in {league}'s final order")
        for team in order:
            if team in domestic_owner and domestic_owner[team] != league:
                raise ValueError(f"{team} appears in two domestic associations")
            domestic_owner[team] = league
        # A cup route supplies the association even when no top-flight/mapping row exists.
        for key in ("cup", "league_cup"):
            team = champions.get(policies[league].get(key))
            if team:
                if team in domestic_owner and domestic_owner[team] != league:
                    raise ValueError(f"{team} wins a domestic cup in another association")
                domestic_owner[team] = league
    affiliation.update(domestic_owner)
    cl_holders = {champions.get(UCL), champions.get(UEL)} - {None, ""}
    conference_holder = champions.get(UECL)
    result = {}
    for league, order in tables.items():
        policy = policies[league]
        base = _domestic_base(order, policy, champions)
        ucl = set(base["ucl"])
        uel_quota, uecl_quota = _quota(policy, "uel"), _quota(policy, "uecl")
        for team in cl_holders:
            if affiliation.get(team) != league:
                continue
            if team not in ucl:
                if team in base["uel"]:
                    uel_quota -= 1
                elif team in base["uecl"]:
                    uecl_quota -= 1
                ucl.add(team)
        # For France an EPS promotes its qualifier and cascades that qualifying entry. As an
        # ENTRY set this is equivalent to adding the best league finisher outside the base set.
        for _ in range(_quota(policy, "eps")):
            next_team = next((team for team in order if team not in ucl), None)
            if next_team is not None:
                ucl.add(next_team)
        reserve_conference = (conference_holder if affiliation.get(conference_holder) == league
                              and conference_holder not in ucl else None)
        if reserve_conference:
            if reserve_conference not in base["uel"]:
                uel_quota += 1
            if reserve_conference in base["uecl"]:
                uecl_quota -= 1
        if min(uel_quota, uecl_quota) < 0:
            raise ValueError(f"Titleholders over-consumed {league}'s domestic qualification quota")
        uel: set[str] = set()
        cup = champions.get(policy.get("cup"))
        if uel_quota and cup and cup not in ucl:
            uel.add(cup)
        if reserve_conference:
            uel.add(reserve_conference)
        if len(uel) > uel_quota:
            raise ValueError(f"Reserved winners exceed {league}'s Europa League quota")
        _fill(order, uel, ucl, uel_quota)
        uecl: set[str] = set()
        league_cup = champions.get(policy.get("league_cup"))
        if uecl_quota and league_cup and league_cup not in ucl | uel:
            uecl.add(league_cup)
        _fill(order, uecl, ucl | uel, uecl_quota)
        assert not (ucl & uel or ucl & uecl or uel & uecl), league
        result[league] = {"ucl": ucl, "uel": uel, "uecl": uecl}
    return result
