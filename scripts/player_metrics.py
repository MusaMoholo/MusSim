"""Versioned, additive player metrics derived from FotMob's typed semantic statistics.

The complete original stat groups live once per match in semantic_stats/*.json.gz; this registry
only chooses useful sums. Ratings, percentages, speed and unknown fields are retained there,
never silently summed. An absent semantic value remains unknown, including sparse xA.
"""
from __future__ import annotations

import math
from typing import Any

PLAYER_SCHEMA_VERSION = 2
SEMANTIC_SCHEMA_VERSION = 1
BASE_METRICS = ("minutes", "goals", "pen_goals", "assists", "shots", "xg", "xgot")
# key, label, upstream semantic key, upstream stat member, unit
_ADDITIONAL = (
    ("xa", "xA", "expected_assists", "value", "expected_assists"),
    ("chances_created", "Chances created", "chances_created", "value", "count"),
    ("big_chances_created", "Big chances created", "big_chance_created_team_title", "value", "count"),
    ("big_chances_missed", "Big chances missed", "big_chance_missed_title", "value", "count"),
    ("touches", "Touches", "touches", "value", "count"),
    ("touches_opp_box", "Touches in opposition box", "touches_opp_box", "value", "count"),
    ("passes_completed", "Passes completed", "accurate_passes", "value", "count"),
    ("passes_attempted", "Passes attempted", "accurate_passes", "total", "count"),
    ("crosses_completed", "Crosses completed", "accurate_crosses", "value", "count"),
    ("crosses_attempted", "Crosses attempted", "accurate_crosses", "total", "count"),
    ("long_balls_completed", "Long balls completed", "long_balls_accurate", "value", "count"),
    ("long_balls_attempted", "Long balls attempted", "long_balls_accurate", "total", "count"),
    ("dribbles_completed", "Dribbles completed", "dribbles_succeeded", "value", "count"),
    ("dribbles_attempted", "Dribbles attempted", "dribbles_succeeded", "total", "count"),
    ("passes_final_third", "Passes into final third", "passes_into_final_third", "value", "count"),
    ("line_breaking_passes", "Line breaking passes", "line_breaking_passes", "value", "count"),
    ("duels_won", "Duels won", "duel_won", "value", "count"),
    ("duels_lost", "Duels lost", "duel_lost", "value", "count"),
    ("ground_duels_won", "Ground duels won", "ground_duels_won", "value", "count"),
    ("ground_duels_total", "Ground duels contested", "ground_duels_won", "total", "count"),
    ("aerial_duels_won", "Aerial duels won", "aerials_won", "value", "count"),
    ("aerial_duels_total", "Aerial duels contested", "aerials_won", "total", "count"),
    ("tackles", "Tackles", "matchstats.headers.tackles", "value", "count"),
    ("blocks", "Blocks", "shot_blocks", "value", "count"),
    ("clearances", "Clearances", "clearances", "value", "count"),
    ("headed_clearances", "Headed clearances", "headed_clearance", "value", "count"),
    ("interceptions", "Interceptions", "interceptions", "value", "count"),
    ("recoveries", "Recoveries", "recoveries", "value", "count"),
    ("fouls", "Fouls committed", "fouls", "value", "count"),
    ("fouled", "Fouls won", "was_fouled", "value", "count"),
    ("dispossessed", "Dispossessed", "dispossessed", "value", "count"),
    ("dribbled_past", "Dribbled past", "dribbled_past", "value", "count"),
    ("offsides", "Offsides", "Offsides", "value", "count"),
    ("saves", "Saves", "saves", "value", "count"),
    ("saves_inside_box", "Saves inside box", "saves_inside_box", "value", "count"),
    ("goals_conceded", "Goals conceded", "goals_conceded", "value", "count"),
    ("xgot_faced", "xGOT faced", "expected_goals_on_target_faced", "value", "expected_goals"),
    ("goals_prevented", "Goals prevented", "goals_prevented", "value", "expected_goals"),
    ("keeper_claims", "Keeper high claims", "keeper_high_claim", "value", "count"),
    ("keeper_sweeps", "Keeper sweeps", "keeper_sweeper", "value", "count"),
    ("keeper_punches", "Keeper punches", "punches", "value", "count"),
    ("penalties_won", "Penalties won", "penalties_won", "value", "count"),
    ("penalties_conceded", "Penalties conceded", "conceded_penalties", "value", "count"),
    ("penalties_saved", "Penalties saved", "saved_penalties", "value", "count"),
    ("penalties_missed", "Penalties missed", "missed_penalty", "value", "count"),
)
ADDITIONAL_METRICS = tuple(row[0] for row in _ADDITIONAL)
METRICS = (*BASE_METRICS, *ADDITIONAL_METRICS)
METRIC_REGISTRY = {
    "minutes": {"label": "Minutes", "unit": "minutes", "source_key": "minutes_played", "source_part": "value"},
    "goals": {"label": "Goals", "unit": "count", "source_key": "shotmap.Goal", "source_part": "count"},
    "pen_goals": {"label": "Penalty goals", "unit": "count", "source_key": "shotmap.Penalty.Goal", "source_part": "count"},
    "assists": {"label": "Assists", "unit": "count", "source_key": "assists", "source_part": "value"},
    "shots": {"label": "Shots", "unit": "count", "source_key": "shotmap.attempts", "source_part": "count"},
    "xg": {"label": "xG", "unit": "expected_goals", "source_key": "expected_goals", "source_part": "value"},
    "xgot": {"label": "xGOT", "unit": "expected_goals", "source_key": "expected_goals_on_target_variant", "source_part": "value"},
    **{key: {"label": label, "unit": unit, "source_key": source, "source_part": part}
       for key, label, source, part, unit in _ADDITIONAL},
}
for _key, _metric in METRIC_REGISTRY.items():
    _metric.update(aggregation="sum", missing="unknown")
# Existing model-independent extraction provenance remains explicit.
METRIC_REGISTRY["goals"]["fallback"] = "semantic goals if shot map absent; own goals excluded"
METRIC_REGISTRY["shots"]["fallback"] = "semantic total_shots if shot map absent; own goals excluded"
METRIC_REGISTRY["xg"]["fallback"] = "zero only for a known no-shot appearance"
METRIC_REGISTRY["xgot"]["fallback"] = "shotmap expectedGoalsOnTarget when semantic stat absent"

PLAYER_FIELDS = ("competition", "season", "match_id", "kickoff", "player_id", "name", "team",
                 "side", *BASE_METRICS, "own_goals", "stat_xg", "shot_xg", "xg_source",
                 *ADDITIONAL_METRICS, "player_schema")


def numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def semantic_stats(player: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read semantic keys, without display-label dependence or discarding typed stat members."""
    result = {}
    for group in player.get("stats") or []:
        if not isinstance(group, dict):
            continue
        entries = group.get("stats") or {}
        entries = entries.values() if isinstance(entries, dict) else entries if isinstance(entries, list) else []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("key") and isinstance(entry.get("stat"), dict):
                result[entry["key"]] = entry["stat"]
    return result


def additional_values(player: dict[str, Any]) -> dict[str, float | None]:
    stats = semantic_stats(player)
    return {key: numeric(stats.get(source, {}).get(part))
            for key, _, source, part, _ in _ADDITIONAL}
