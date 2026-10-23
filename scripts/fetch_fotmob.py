#!/usr/bin/env python3
"""Fetch per-match stats (above all non-penalty xG) from Fotmob's JSON API.

Fotmob is the only source verified to carry Opta xG across domestic leagues, UEFA competitions
and domestic cups alike, so all 14 competitions come from one provider and one xG model. See
PLAN.md Part II.

Two stages, with very different costs:

    enumerate   /api/data/leagues?id={id}&season={YYYY/YYYY}   1 request per competition-season
    detail      /api/data/matchDetails?matchId={id}            1 request PER MATCH

so a season of all 14 competitions is ~2,460 requests. Every response is cached to disk and a
finished match is reused by normal collection. `--refresh-details` deliberately re-fetches
all finished matches, retaining previous raw responses before updating the current cache.

Usage
-----
    # one competition-season, the way to smoke-test a change
    .venv/bin/python scripts/fetch_fotmob.py --season 2025 --competition "English Premier League"

    # everything for one season
    .venv/bin/python scripts/fetch_fotmob.py --season 2025

    # enumerate only: cheap, writes the fixture list, fetches no match detail
    .venv/bin/python scripts/fetch_fotmob.py --season 2025 --fixtures-only

    # rebuild player rows from existing fixture files and cached details; no network
    .venv/bin/python scripts/fetch_fotmob.py --season 2026 --players-only

Outputs
-------
    data/fotmob/matches/{match_id}.json.gz  complete permanent raw detail responses
    data/fotmob/semantic_stats/{match_id}.json.gz  full typed player/team stat groups
    data/fotmob/league_responses/<sha256>.json.gz  complete fetched league responses
    data/fotmob/league_responses/observations.jsonl  UTC/source/season/hash observations
    data/fotmob/fixtures-{season}.csv     one row per fixture, from the enumerate stage
    data/fotmob/match_stats-{season}.csv  legacy aggregate; per-competition files are current
    data/fotmob/players/<region>/<slug>-<season>.csv  one row per match participant

Season numbering follows the repo: season N is the campaign N/N+1, so `--season 2025` is
2025/2026. Fotmob's own season strings are resolved from its `allAvailableSeasons` list rather
than assumed, because the format is not uniform across competitions.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import sys
import tempfile
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.ops_storage import archive_paths, atomic_write_files
from scripts.source_retention import retain_response
from scripts.player_metrics import (
    PLAYER_FIELDS, PLAYER_SCHEMA_VERSION, SEMANTIC_SCHEMA_VERSION, additional_values,
)

BASE_URL = "https://www.fotmob.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DATA_DIR = Path("data") / "fotmob"
CACHE_DIR = DATA_DIR / "matches"

THROTTLE_SECONDS = 1.0     # be a good citizen; this is someone else's free API
MAX_RETRIES = 3

# Fotmob league ids, resolved from /api/data/allLeagues and pinned here deliberately.
#
# NEVER resolve these by name. Fotmob carries women's competitions with near-identical names
# ("FA Cup (Women)", "DFB Pokal Frauen", "Women's Champions League") and qualification rounds as
# separate leagues ("Champions League Qualification"). Matching on a name substring would silently
# merge or replace a competition — the exact failure that once merged the women's Opta rankings
# into the men's and corrupted data/team_rankings.csv without raising anything. Ids only.
#
# Keys are the canonical competition names used by LEAGUE_CONFIGS in simulation.ipynb.
COMPETITIONS: Dict[str, int] = {
    "English Premier League": 47,
    "Spanish La Liga": 87,
    "German Bundesliga": 54,
    "Italian Serie A": 55,
    "French Ligue 1": 53,
    "UEFA Champions League": 42,
    "UEFA Europa League": 73,
    "UEFA Conference League": 10216,
    "English FA Cup": 132,
    "English League Cup": 133,
    "German DFB Pokal": 209,
    "Spanish Copa del Rey": 138,
    "Italian Coppa Italia": 141,
    "French Coupe de France": 134,
}

# region / slug / timezone per competition. region and slug MUST match LEAGUE_CONFIGS in
# simulation.ipynb, because the per-competition output mirrors the repo's own derived path layout
# <region>/<competition>/<slug>-<season>.csv.
#
# The timezone converts Fotmob's UTC kickoff back to local, which is what the repo's files hold.
# Measured: 0 of 3,084 fixtures in 2025 change calendar date under UTC, so this cannot currently
# shift a rest-day calculation — it is done for honest kickoff times and to stay safe if a
# near-midnight fixture ever appears.
LAYOUT: Dict[str, tuple] = {
    "English Premier League": ("England", "epl", "Europe/London"),
    "English FA Cup": ("England", "fa-cup", "Europe/London"),
    "English League Cup": ("England", "efl-cup", "Europe/London"),
    "German Bundesliga": ("Germany", "bundesliga", "Europe/Berlin"),
    "German DFB Pokal": ("Germany", "dfb-pokal", "Europe/Berlin"),
    "Spanish La Liga": ("Spain", "la-liga", "Europe/Madrid"),
    "Spanish Copa del Rey": ("Spain", "copa-del-rey", "Europe/Madrid"),
    "Italian Serie A": ("Italy", "serie-a", "Europe/Rome"),
    "Italian Coppa Italia": ("Italy", "coppa-italia", "Europe/Rome"),
    "French Ligue 1": ("France", "ligue-1", "Europe/Paris"),
    "French Coupe de France": ("France", "coupe-de-france", "Europe/Paris"),
    "UEFA Champions League": ("UEFA", "champions-league", "Europe/Zurich"),
    "UEFA Europa League": ("UEFA", "europa-league", "Europe/Zurich"),
    "UEFA Conference League": ("UEFA", "conference-league", "Europe/Zurich"),
}

# Fotmob's knockout round labels -> the repo's. 1/2 is the semi-final, 1/4 the quarter, 1/8 the
# round of 16. Anything not listed (1/16, 1/32, 1/64, and the numbered qualifying rounds) is an
# EARLY round the model does not currently carry: those are written out but must not be pooled
# into the cup constants, which are fitted from the Ro16 on. See PLAN.md.
ROUND_LABELS = {"final": "Final", "1/2": "SF", "1/4": "QF", "1/8": "Ro16"}

# xG is NOT available for the full fixture history. Verified: present 2023-04-19, absent
# 2019-04-17 and 2016-11-22. Seasons before this are enumerable but will come back with empty xG.
EARLIEST_XG_SEASON = 2021

# Stats lifted from each match. Fotmob's keys are inconsistent — some snake_case, some CamelCase,
# and `BallPossesion` is misspelled upstream. Left exactly as the API spells them.
STAT_KEYS = {
    "xg": "expected_goals",
    "npxg": "expected_goals_non_penalty",
    "xgot": "expected_goals_on_target",
    "xg_open_play": "expected_goals_open_play",
    "xg_set_play": "expected_goals_set_play",
    "shots": "total_shots",
    "shots_on_target": "ShotsOnTarget",
    "shots_inside_box": "shots_inside_box",
    "big_chances": "big_chance",
    "possession": "BallPossesion",
    "corners": "corners",
}


# --------------------------------------------------------------------------- HTTP


def fetch_json(url: str, *, throttle: bool = True) -> Any:
    """GET a Fotmob JSON endpoint.

    Two things bite here and both are silent:

    1. Responses are gzipped. urllib does NOT transparently decompress the way requests does, so
       json.loads on the raw bytes dies with "Expecting value: line 1 column 1". A truncated read
       produces the identical error from a different cause, so read the whole body.
    2. The Content-Type is text/javascript, not application/json. Do not gate on it.
    """
    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Referer": f"{BASE_URL}/",
                    "Accept-Encoding": "gzip",
                },
            )
            with urlopen(request, timeout=40) as response:
                payload = response.read()
            if payload[:2] == b"\x1f\x8b":
                payload = gzip.decompress(payload)
            if throttle:
                time.sleep(THROTTLE_SECONDS)
            return json.loads(payload.decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError, OSError) as error:
            last_error = error
            # A 404 is a real answer (no such match), not a transient failure.
            if isinstance(error, HTTPError) and error.code == 404:
                raise
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {url}") from last_error


# --------------------------------------------------------------------------- enumerate


def retain_league_response(url: str, data: Any, season: int) -> dict:
    """Keep each already-fetched league response, deduplicated by complete JSON content.

    Canonical JSON preserves all decoded fields, independent of whitespace/key order. This
    function performs no request. Observations retain UTC time, actual URL and requested season;
    a season-resolution response can describe the provider's current season rather than that year.
    """
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    root = DATA_DIR / "league_responses"
    path = root / f"{digest}.json.gz"
    _write_derived(path, raw, compressed=True)
    observation = {"observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "source_url": url, "season": int(season), "sha256": digest,
                   "file": path.name, "representation": "canonical_json", "decoded_bytes": len(raw)}
    with (root / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, sort_keys=True) + "\n")
    return observation


def resolve_season(league_id: int, season: int) -> str:
    """Map repo season N (the campaign N/N+1) onto Fotmob's own season string.

    Resolved from the competition's `allAvailableSeasons` rather than assumed: the format is not
    uniform across competitions, and guessing produces an empty fixture list rather than an error.
    """
    url = f"{BASE_URL}/api/data/leagues?id={league_id}"
    data = fetch_json(url)
    retain_league_response(url, data, season)
    available = data.get("allAvailableSeasons") or []
    wanted = f"{season}/{season + 1}"
    if wanted in available:
        return wanted
    for candidate in (str(season), f"{season}/{str(season + 1)[-2:]}"):
        if candidate in available:
            return candidate
    raise RuntimeError(
        f"league {league_id}: cannot resolve season {season}. Available: {available[:8]}"
    )


def fixture_round(match: Dict[str, Any]) -> Any:
    """Only an explicit phase label may turn a named UEFA round into a matchday number.

    A qualifier's roundName can also be 1/2/3; those numbers never classify it as a phase.
    Ordinary numeric league rounds and knockout/qualifying labels retain their old values.
    """
    raw = match.get("round")
    phase = r"(?:league|group)\s+(?:stage|phase)"
    candidates = (raw, match.get("roundName")) if raw in (None, "") or isinstance(raw, str) and re.fullmatch(phase, raw.strip(), re.I) else (raw,)
    for value in candidates:
        if isinstance(value, str):
            found = re.fullmatch(phase + r"\s*(?:[-–:]\s*)?(?:round|matchday)\s*(\d+)", value.strip(), re.I)
            if found and int(found[1]) > 0:
                return int(found[1])
    if isinstance(raw, str) and re.fullmatch(phase, raw.strip(), re.I):
        number = str(match.get("roundName", ""))
        if number.isdigit() and int(number) > 0:
            return int(number)
    return raw


def list_fixtures(competition: str, league_id: int, season: int) -> List[Dict[str, Any]]:
    season_string = resolve_season(league_id, season)
    url = f"{BASE_URL}/api/data/leagues?id={league_id}&season={season_string.replace('/', '%2F')}"
    data = fetch_json(url)
    retain_league_response(url, data, season)
    matches = (data.get("fixtures") or {}).get("allMatches") or []

    rows = []
    for match in matches:
        status = match.get("status") or {}
        rows.append(
            {
                "competition": competition,
                "season": season,
                "match_id": match.get("id"),
                "round": fixture_round(match),
                "status": status,
                "utc_time": status.get("utcTime"),
                "finished": bool(status.get("finished")),
                "home": (match.get("home") or {}).get("name"),
                "away": (match.get("away") or {}).get("name"),
                "home_id": (match.get("home") or {}).get("id"),
                "away_id": (match.get("away") or {}).get("id"),
                "score": status.get("scoreStr"),
            }
        )
    return rows


# --------------------------------------------------------------------------- detail


def read_cached(match_id: str) -> Optional[dict]:
    """Read a cached response, gzipped or plain. Returns None if absent or corrupt.

    A corrupt file is archived outside the repo before removal: the usual cause is an
    interrupted write. A normal fetch can re-fetch it; a cache-only rebuild reports it missing.
    """
    for path, opener in ((CACHE_DIR / f"{match_id}.json.gz", gzip.open),
                         (CACHE_DIR / f"{match_id}.json", open)):
        if not path.exists():
            continue
        try:
            with opener(path, "rt") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError, EOFError, zlib.error):
            archive, saved = archive_paths([path])
            path.unlink(missing_ok=True)
            print(f"  ! corrupt cache archived: {path} -> {saved[path]}")
    return None


def fetch_match_detail(match_id: str, *, refresh: bool = False) -> Optional[dict]:
    """Return a match's detail response, from the cache when present.

    Normal collection reuses the permanent cache. Explicit refresh rechecks provider revisions
    while retaining every prior response.

    Responses are ~300 KB of JSON each and compress about 10x, which matters at 3,084 matches per
    season: 0.94 GB raw against ~0.10 GB gzipped, or 4.7 GB against ~0.5 GB over five seasons.
    Written gzipped; plain `.json` from older runs is still read, and `--compact` converts it.
    """
    cached = read_cached(match_id)
    if cached is not None and not refresh:
        return cached

    try:
        data = fetch_json(f"{BASE_URL}/api/data/matchDetails?matchId={match_id}")
    except HTTPError as error:
        if error.code == 404:
            if refresh and cached is not None:
                raise RuntimeError(f"FotMob refresh returned404 for retained match {match_id}; old evidence kept") from error
            return None
        raise
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    store=DATA_DIR/'match_responses'
    # Preserve legacy bytes before replacing the current cache, including plain-cache readers.
    if refresh and cached is not None:
        old=json.dumps(cached,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        retain_response(store,f"{BASE_URL}/api/data/matchDetails?matchId={match_id}",old,
                        representation='canonical_json',match_id=str(match_id),origin='previous_cache')
    retain_response(store,f"{BASE_URL}/api/data/matchDetails?matchId={match_id}",raw,
                    representation='canonical_json',match_id=str(match_id),origin='provider_response')
    if not isinstance(data,dict) or not (data.get('general') or data.get('header')):
        raise RuntimeError(f'Invalid FotMob detail response for match {match_id}; current cache kept')
    atomic_write_files({CACHE_DIR/f"{match_id}.json.gz":gzip.compress(raw,mtime=0)})
    return data


def compact_cache() -> None:
    """Compress raw files without losing bytes; archive originals before removal.

    An existing gzip with different contents is never taken as proof the plain file is safe to
    remove, even when both are valid JSON. A corrupt/different existing gzip is kept and reported.
    """
    plain = sorted(CACHE_DIR.glob("*.json"))
    if not plain:
        print("  cache already compact")
        return
    before = sum(path.stat().st_size for path in plain)
    converted, failed, archive = 0, [], None
    for path in plain:
        target = path.with_suffix(".json.gz")
        temporary = None
        try:
            raw = path.read_bytes()
            json.loads(raw)
            if not target.exists():
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".compact-", suffix=".gz", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(gzip.compress(raw, mtime=0))
                if gzip.decompress(temporary.read_bytes()) != raw:
                    raise ValueError("gzip round-trip differs")
                temporary.replace(target)
            if gzip.decompress(target.read_bytes()) != raw:
                raise ValueError("existing gzip differs from plain source")
            archive, _ = archive_paths([path])
            path.unlink()
            converted += 1
        except (OSError, EOFError, ValueError, zlib.error) as error:
            failed.append(path.name)
            print(f"  ! kept {path.name}: {error}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    after = sum(path.stat().st_size for path in CACHE_DIR.glob("*.json.gz"))
    print(f"  compacted {converted} files: {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB")
    if archive is not None:
        print(f"  archived plain originals: {archive}")
    if failed:
        print(f"  ! {len(failed)} plain files retained (no verified identical gzip): {failed[:5]}")


def _stat_pairs(detail: dict) -> Dict[str, List[Any]]:
    """Flatten the nested stat groups into {key: [home, away]}.

    `expected_goals` appears three times in the response: twice as a section-header row carrying
    [None, None], and once with real values. Header rows are skipped, so the surviving entry is
    the real one whatever order they arrive in.
    """
    out: Dict[str, List[Any]] = {}
    periods = ((detail.get("content") or {}).get("stats") or {}).get("Periods") or {}
    groups = (periods.get("All") or {}).get("stats") or []
    for group in groups:
        for stat in group.get("stats") or []:
            key, values = stat.get("key"), stat.get("stats")
            if not key or not isinstance(values, list) or len(values) != 2:
                continue
            if values[0] is None and values[1] is None:
                continue
            out.setdefault(key, values)
    return out


def _as_number(value: Any) -> Optional[float]:
    # Several fields arrive as "408 (85%)" or as strings holding a float.
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).split("(")[0].strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def extract_outcome(detail: Optional[dict], fixture: Optional[dict] = None) -> Dict[str, Any]:
    """How a match was decided, as structured fields.

    The legacy fixture files encode this in the Result STRING — "1 - 1 (3 - 4 pens)",
    "3 - 4 (a.e.t.)" — because fixturedownload.com only ever supplied free text. Fotmob supplies
    it properly, so it is stored properly. Re-encoding structured facts back into a string just to
    match the old parser would be throwing away information to please legacy code.

    Observed across the full 2025 cache (3,084 matches):
        fulltime_short 2882 | penalties_short 161 | afterextratime_short 40 | aborted_short 1
    plus 81 that went to extra time and 72 two-legged ties decided on aggregate.

    `aborted_short` matters more than its count suggests: an abandoned match still carries a
    plausible-looking scoreStr, so anything reading the score without checking `outcome` will
    silently treat it as a real result.
    """
    out: Dict[str, Any] = {
        "outcome": None, "home_pens": None, "away_pens": None,
        "went_to_extra_time": None, "lost_on_aggregate": None,
    }
    status = (((detail or {}).get("header") or {}).get("status") or {})
    reason = status.get("reason") or {}
    if not reason.get("shortKey") and fixture:
        fallback = fixture.get("status") or {}
        fallback_reason = fallback.get("reason") or {}
        outcome = (fallback_reason.get("shortKey") or "").removesuffix("_short")
        score = str(fixture.get("score") or "").replace("−", "-")
        # finished alone cannot distinguish regulation, extra time, shootouts or abandonment.
        known_result = bool(fixture.get("finished")) and bool(re.fullmatch(r"\s*\d+\s*-\s*\d+\s*", score))
        if outcome == "aborted" or known_result and outcome in {"fulltime", "afterextratime", "penalties"}:
            status, reason = fallback, fallback_reason
    out["outcome"] = (reason.get("shortKey") or "").removesuffix("_short") or None

    penalties = reason.get("penalties")
    if isinstance(penalties, list) and len(penalties) == 2:
        out["home_pens"], out["away_pens"] = penalties[0], penalties[1]

    halfs = status.get("halfs") or {}
    if out["outcome"] == "afterextratime":
        out["went_to_extra_time"] = True
    elif halfs.get("firstExtraHalfStarted") is not None:
        out["went_to_extra_time"] = bool(halfs["firstExtraHalfStarted"])
    elif out["outcome"] == "fulltime":
        out["went_to_extra_time"] = False
    out["lost_on_aggregate"] = status.get("whoLostOnAggregated") or None
    return out


def extract_pen_goals(detail: Optional[dict], home_id: Any, away_id: Any
                      ) -> Tuple[Optional[int], Optional[int]]:
    """Penalty goals per side, off the match's shot map: a shot whose `situation` is "Penalty"
    and went in, in play. A shootout's kicks sit in their own period (`PenaltyShootout`) and
    are no part of the score, so they are left out. (None, None) when the match has no shot
    map, so an unknown never reads as zero -- the Goals v xG chart's non-penalty goals count
    only matches that have one."""
    shots = (((detail or {}).get("content") or {}).get("shotmap") or {}).get("shots")
    if not isinstance(shots, list) or not shots:
        return None, None
    goals = {str(home_id): 0, str(away_id): 0}
    for shot in shots:
        if (shot.get("situation") == "Penalty" and shot.get("eventType") == "Goal"
                and not shot.get("isOwnGoal") and shot.get("period") != "PenaltyShootout"):
            team = str(shot.get("teamId"))
            if team in goals:
                goals[team] += 1
    return goals[str(home_id)], goals[str(away_id)]


def extract_stats(fixture: Dict[str, Any], detail: Optional[dict]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "competition": fixture["competition"],
        "season": fixture["season"],
        "match_id": fixture["match_id"],
        "round": fixture["round"],
        "utc_time": fixture["utc_time"],
        "home": fixture["home"],
        "away": fixture["away"],
        "home_id": fixture["home_id"],
        "away_id": fixture["away_id"],
    }

    score = (fixture.get("score") or "").replace("−", "-")
    home_goals, away_goals = None, None
    if "-" in score:
        parts = [part.strip() for part in score.split("-", 1)]
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            home_goals, away_goals = int(parts[0]), int(parts[1])
    row["home_goals"], row["away_goals"] = home_goals, away_goals
    row.update(extract_outcome(detail, fixture))

    pairs = _stat_pairs(detail) if detail else {}
    for name, key in STAT_KEYS.items():
        values = pairs.get(key)
        row[f"home_{name}"] = _as_number(values[0]) if values else None
        row[f"away_{name}"] = _as_number(values[1]) if values else None
    row["home_pen_goals"], row["away_pen_goals"] = extract_pen_goals(
        detail, fixture["home_id"], fixture["away_id"])
    return row


# --------------------------------------------------------------------------- players

def _player_values(player: Dict[str, Any]) -> Dict[str, Optional[float]]:
    values = {}
    for group in player.get("stats") or []:
        if not isinstance(group, dict):
            continue
        entries = group.get("stats") or {}
        entries = entries.values() if isinstance(entries, dict) else entries if isinstance(entries, list) else []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("key") or not isinstance(entry.get("stat"), dict):
                continue
            value = _as_number(entry["stat"].get("value"))
            values[entry["key"]] = value if value is not None and math.isfinite(value) else None
    return values


def extract_players(fixture: Dict[str, Any], detail: Optional[dict], *,
                    xg_source: str = "player_stats") -> List[Dict[str, Any]]:
    """One participant per finished match; bench rows, own shots and shootouts stay distinct.

    Player-stat expected_goals is authoritative xG; a missing stat with attempts is unknown.
    A nonempty match shot map establishes genuine no-shot zeroes and supplies goals/penalties;
    its unrounded xG is retained separately for source audits. Nothing is rescaled to team xG.
    Own-goal shot teamId belongs to its COMMITTING side in the cache; playerStats is authoritative
    when present, so an own goal never becomes that player's goal or the other club's player.
    """
    if xg_source not in {"player_stats", "shotmap"}:
        raise ValueError(f"unknown player xG source: {xg_source}")
    if not detail or not fixture.get("finished", True):
        return []
    general, content = detail.get("general") or {}, detail.get("content") or {}
    if general.get("finished") is False:
        return []
    ids = {str(fixture.get(f"{side}_id") or (general.get(f"{side}Team") or {}).get("id")): side
           for side in ("home", "away")}
    players = content.get("playerStats") or {}
    players = {str(pid): dict(player) for pid, player in players.items()
               if isinstance(player, dict)} if isinstance(players, dict) else {}
    shots = (content.get("shotmap") or {}).get("shots")
    shot_coverage = isinstance(shots, list) and bool(shots)
    by_player: Dict[str, List[Dict[str, Any]]] = {}
    named_players: Dict[Tuple[str, str], List[str]] = {}
    for pid, player in players.items():
        key = (str(player.get("teamId")), str(player.get("name") or "").casefold())
        named_players.setdefault(key, []).append(pid)
    seen_shots = set()
    for number, shot in enumerate(shots if isinstance(shots, list) else []):
        if not isinstance(shot, dict) or shot.get("period") == "PenaltyShootout":
            continue
        shot_id = str(shot.get("id", f"row-{number}"))
        if shot_id in seen_shots:
            continue
        seen_shots.add(shot_id)
        pid = str(shot.get("playerId") or "")
        if pid not in players:
            # Lower-division cache entries can use -1 for several DIFFERENT shooters while
            # playerStats retains positive dictionary keys (and its nested id can be zero).
            # Recover only an unambiguous same-side name, otherwise preserve a local identity.
            named = named_players.get((str(shot.get("teamId")),
                                       str(shot.get("playerName") or "").casefold()), [])
            pid = (named[0] if len(named) == 1 else
                   f"unknown:{fixture['match_id']}:{shot.get('teamId')}:{shot.get('playerName') or pid}")
        by_player.setdefault(pid, []).append(shot)
        players.setdefault(pid, {"id": pid, "name": shot.get("playerName") or pid,
                                 "teamId": shot.get("teamId"), "stats": []})
    rows = []
    for pid, player in sorted(players.items()):
        values = _player_values(player)
        own_shots = by_player.get(pid, [])
        if not values and not own_shots:
            continue                         # unused substitute, not a zero-minute appearance
        side = ids.get(str(player.get("teamId")))
        if side is None:
            continue                         # cannot attach this participant to either real side
        attempts = [shot for shot in own_shots if not shot.get("isOwnGoal")]
        def shot_total(key: str) -> Optional[float]:
            numbers = [_as_number(shot.get(key)) for shot in attempts]
            if any(value is None or not math.isfinite(value) for value in numbers):
                return None
            return math.fsum(numbers)
        if shot_coverage:
            goals = sum(shot.get("eventType") == "Goal" for shot in attempts)
            pens = sum(shot.get("eventType") == "Goal" and shot.get("situation") == "Penalty"
                       for shot in attempts)
            own = sum(bool(shot.get("isOwnGoal")) and shot.get("eventType") == "Goal"
                      for shot in own_shots)
            count, xg, xgot = len(attempts), shot_total("expectedGoals"), shot_total("expectedGoalsOnTarget")
        else:
            goals, pens, own = values.get("goals"), None, None
            count, xg = values.get("total_shots"), values.get("expected_goals")
            xgot = values.get("expected_goals_on_target_variant")
        shot_xg, stat_xg = xg if shot_coverage else None, values.get("expected_goals")
        if xg_source == "shotmap":
            xg, source = shot_xg, "shotmap" if shot_xg is not None else "unknown"
        elif stat_xg is not None:
            xg, source = stat_xg, "player_stats"
        elif shot_coverage and count == 0:
            xg, source = 0, "no_shots"
        else:
            xg, source = None, "unknown"
        explicit_xgot = values.get("expected_goals_on_target_variant")
        if explicit_xgot is not None:
            xgot = explicit_xgot
        rows.append({"competition": fixture["competition"], "season": fixture["season"],
                     "match_id": fixture["match_id"],
                     "kickoff": fixture.get("kickoff") or fixture.get("utc_time"),
                     "player_id": pid, "name": player.get("name") or pid,
                     "team": fixture.get(side) or player.get("teamName"), "side": side,
                     "minutes": values.get("minutes_played"), "goals": goals, "pen_goals": pens,
                     "assists": values.get("assists"), "shots": count, "xg": xg, "xgot": xgot,
                     "own_goals": own, "stat_xg": stat_xg, "shot_xg": shot_xg,
                     "xg_source": source, **additional_values(player),
                     "player_schema": PLAYER_SCHEMA_VERSION})
    return rows


def player_file_path(competition: str, season: int) -> Path:
    region, slug, _ = LAYOUT[competition]
    return DATA_DIR / "players" / region / f"{slug}-{season}.csv"


def _write_derived(path: Path, raw: bytes, *, compressed: bool = False) -> bool:
    """Atomic derived output; unchanged data is not rewritten or repeatedly archived."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        previous = path.read_bytes()
        try:
            if (gzip.decompress(previous) if compressed else previous) == raw:
                return False
        except (OSError, EOFError, zlib.error):
            pass
    packed = gzip.compress(raw, mtime=0) if compressed else raw
    if (gzip.decompress(packed) if compressed else packed) != raw:
        raise ValueError(f"derived file round-trip differs: {path}")
    archive = atomic_write_files({path: packed})
    if archive is not None:
        print(f"  archived previous {path} -> {archive}")
    return True


def write_player_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Archive changed CSVs before atomic replacement, including an empty rebuild."""
    import io
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=PLAYER_FIELDS)
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda row: (str(row.get("kickoff") or ""),
                              str(row["match_id"]), str(row["side"]), str(row["player_id"]))))
    _write_derived(path, handle.getvalue().encode("utf-8"))


def semantic_stats_payload(match_id: str, detail: Optional[dict]) -> Optional[dict]:
    """Losslessly retain typed stat groups, including unused/unknown/non-additive statistics.

    This is one derived file per match, never copied into dated snapshots. Full raw detail,
    including lineups/events/shots, remains the permanent authoritative recovery source.
    """
    if not detail:
        return None
    content = detail.get("content") or {}
    players = content.get("playerStats") or {}
    return {"schema": SEMANTIC_SCHEMA_VERSION, "player_schema": PLAYER_SCHEMA_VERSION,
            "match_id": str(match_id), "source": "fotmob_match_details",
            "teams": {side: (detail.get("general") or {}).get(side + "Team")
                      for side in ("home", "away")},
            "players": {str(pid): {key: player[key] for key in
                         ("id", "optaId", "name", "teamId", "teamName", "isGoalkeeper",
                          "positionId", "usualPosition", "shirtNumber", "stats") if key in player}
                        for pid, player in players.items() if isinstance(player, dict)}
                       if isinstance(players, dict) else {},
            "team_stats": content.get("stats")}


def write_semantic_stats(match_id: str, detail: Optional[dict]) -> None:
    payload = semantic_stats_payload(match_id, detail)
    if payload is not None:
        path = DATA_DIR / "semantic_stats" / f"{match_id}.json.gz"
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        _write_derived(path, raw, compressed=True)


def rebuild_players(season: int, names: List[str]) -> List[Path]:
    """Read existing fixture metadata and cached details only; never enumerate or fetch."""
    written = []
    for competition in names:
        source = season_file_path(competition, season)
        if not source.exists():
            print(f"  skip {competition}: no existing season file")
            continue
        rows, finished, missing = [], 0, 0
        with source.open(newline="") as handle:
            for raw in csv.DictReader(handle):
                if not (raw.get("Result") or "").strip() or raw.get("outcome") == "aborted":
                    continue
                finished += 1
                fixture = {"competition": competition, "season": season,
                           "match_id": raw.get("match_id"), "home": raw.get("Home Team"),
                           "away": raw.get("Away Team"), "home_id": raw.get("home_id"),
                           "away_id": raw.get("away_id"), "finished": True,
                           "kickoff": raw.get("Date")}
                detail = read_cached(str(fixture["match_id"]))
                if detail is None:
                    missing += 1
                write_semantic_stats(str(fixture["match_id"]), detail)
                rows.extend(extract_players(fixture, detail))
        target = player_file_path(competition, season)
        write_player_csv(target, rows)
        written.append(target)
        print(f"  {competition}: {finished} finished, {len(rows)} player rows, {missing} cache missing; {target}")
    return written


# --------------------------------------------------------------------------- main


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def local_kickoff(utc_time: Optional[str], timezone: str) -> str:
    """Fotmob's UTC ISO timestamp -> the repo's `DD/MM/YYYY HH:MM` local kickoff."""
    if not utc_time:
        return ""
    stamp = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
    return stamp.astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y %H:%M")


def season_file_path(competition: str, season: int) -> Path:
    """Where `write_competition_csvs` would put this competition-season. Used to check whether a
    competition that returned nothing has left a stale file behind."""
    region, slug, _ = LAYOUT[competition]
    return DATA_DIR / region / competition / f"{slug}-{season}.csv"


def write_competition_csvs(season: int, fixtures: List[Dict[str, Any]],
                           stats_by_id: Dict[Any, Dict[str, Any]]) -> List[Path]:
    """One file per competition, in the repo's own layout and fixture format, plus xG columns.

    Mirrors `data/<region>/<competition>/<slug>-<season>.csv` under `data/fotmob/` rather than
    overwriting the live fixture files. That keeps the source migration reversible: pointing the
    model at these is a one-line change to `season_file()`, and reverting it is the same edit.

    Extra columns are safe. `load_competition_fixtures` SELECTS its five columns by name, so xG
    columns ride along untouched — verified: a fixture file with xG columns bolted on loads
    byte-identically apart from the recorded filename.
    """
    written: List[Path] = []
    by_competition: Dict[str, List[Dict[str, Any]]] = {}
    for fixture in fixtures:
        by_competition.setdefault(fixture["competition"], []).append(fixture)

    for competition, rows in sorted(by_competition.items()):
        region, slug, timezone = LAYOUT[competition]
        rows = sorted(rows, key=lambda row: (row["utc_time"] or "", str(row["home"])))

        out_rows = []
        for number, fixture in enumerate(rows, start=1):
            stats = dict(stats_by_id.get(fixture["match_id"], {}))
            for key, value in extract_outcome(None, fixture).items():
                if stats.get(key) is None:
                    stats[key] = value
            round_token = str(fixture["round"])
            out_rows.append(
                {
                    "Match Number": number,
                    "Round Number": ROUND_LABELS.get(round_token, round_token),
                    "Date": local_kickoff(fixture["utc_time"], timezone),
                    "Location": "",          # Fotmob does not return it here; the loader drops it
                    "Home Team": fixture["home"],
                    "Away Team": fixture["away"],
                    # The plain score, and ONLY the score. How the tie was decided lives in the
                    # structured columns below rather than in a parenthetical — see
                    # extract_outcome().
                    "Result": fixture["score"] if fixture["finished"] else "",
                    "outcome": stats.get("outcome"),
                    "home_pens": stats.get("home_pens"),
                    "away_pens": stats.get("away_pens"),
                    "went_to_extra_time": stats.get("went_to_extra_time"),
                    "lost_on_aggregate": stats.get("lost_on_aggregate"),
                    "match_id": fixture["match_id"],
                    "home_id": fixture["home_id"],
                    "away_id": fixture["away_id"],
                    **{key: stats.get(key) for key in
                       (f"{side}_{name}" for name in STAT_KEYS for side in ("home", "away"))},
                    # penalty goals off the shot map (`extract_pen_goals`)
                    "home_pen_goals": stats.get("home_pen_goals"),
                    "away_pen_goals": stats.get("away_pen_goals"),
                }
            )

        path = DATA_DIR / region / competition / f"{slug}-{season}.csv"
        write_csv(path, out_rows)
        written.append(path)
    return written


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=None,
                        help="repo season: N is the campaign N/N+1. Required unless --compact")
    parser.add_argument("--competition", action="append", default=None,
                        help="canonical competition name; repeatable. Default: all 14")
    parser.add_argument("--refresh-details", action="store_true", help="re-fetch every finished match despite cache; archive previous responses")
    parser.add_argument("--players-only", action="store_true",
                        help="rebuild player CSVs from existing fixture files and cache; no network")
    parser.add_argument("--fixtures-only", action="store_true",
                        help="enumerate only; fetch no match detail")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many match-detail fetches (for smoke tests)")
    parser.add_argument("--compact", action="store_true",
                        help="gzip any plain-JSON cache entries from an older run, then exit")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.compact:
        compact_cache()
        return 0
    if args.season is None:
        parser.error("--season is required unless --compact is given")

    names = args.competition or list(COMPETITIONS)
    unknown = [name for name in names if name not in COMPETITIONS]
    if unknown:
        parser.error(f"unknown competition(s): {unknown}\nknown: {list(COMPETITIONS)}")

    if args.players_only:
        rebuild_players(args.season, names)
        return 0

    if args.season < EARLIEST_XG_SEASON:
        print(f"  ! season {args.season} predates Fotmob xG (~{EARLIEST_XG_SEASON}); "
              f"fixtures will load but xG columns will be empty")

    fixtures: List[Dict[str, Any]] = []
    empty: List[str] = []
    failed: List[str] = []
    for name in names:
        try:
            found = list_fixtures(name, COMPETITIONS[name], args.season)
        except RuntimeError as error:
            print(f"  ! {name}: {error}")
            failed.append(name)
            continue
        played = sum(1 for row in found if row["finished"])
        print(f"  {name:<26} {len(found):>4} fixtures, {played:>4} finished")
        if not found:
            empty.append(name)
        fixtures.extend(found)

    # A failed request is not an empty competition. Keep the previous complete CSV set and
    # report failure so an explicit backfill cannot mistake stale inputs for a fresh collection.
    if failed:
        print(f"\n  ! refresh FAILED for {len(failed)} competition(s): " + ", ".join(failed))
        print("  ! previous fixture/player CSVs retained; retry the source refresh")
        return 1

    # A competition that returns NOTHING must be said out loud, because `write_competition_csvs`
    # only writes competitions that came back with rows: a season file already on disk is left
    # exactly as it was, and every downstream step keeps reading it as if it were current.
    #
    # This is not hypothetical. On 2026-09-14 the FA Cup, the Copa del Rey and the Coupe de France
    # had not been drawn, so Fotmob returned nothing for all three -- and `data/fotmob/.../
    # fa-cup-2026.csv` still held eight hand-made "Ro16" ties dated March 2027 (Mansfield v
    # Arsenal, Wrexham v Chelsea) from a template written before the Fotmob migration. Those 24
    # invented matches loaded into the master table and were played in every simulated world,
    # moving the Elo and Q of 34 teams that also play in a projected league. The step printed
    # "fotmob: ok" every night throughout.
    if empty:
        print(f"\n  ! {len(empty)} competition(s) returned NO fixtures for {args.season}: "
              + ", ".join(empty))
        stale = [p for p in (season_file_path(name, args.season) for name in empty) if p.exists()]
        if stale:
            print("  ! a season file is still on disk for: "
                  + ", ".join(f"{p}" for p in stale))
            print("  ! it was NOT refreshed by this run. If the competition has not started, that "
                  "file is stale;")
            print("  ! check it carries real match_ids before trusting anything downstream of it.")

    # Per-season aggregates (fixtures-{season}.csv / match_stats-{season}.csv) are no longer
    # written. They duplicated the per-competition files that master_fixtures.py actually
    # reads, and write_csv opens in mode "w" -- so fetching one competition silently
    # truncated every other competition already in that season's aggregate.
    print(f"\n  enumerated {len(fixtures)} fixtures")
    if args.fixtures_only:
        # Still write the per-competition files, with the xG columns empty. The fixture LIST is
        # the point of this flag -- the simulator needs every scheduled fixture, not just the
        # played ones -- and those files are now the only place fixtures are stored.
        print()
        for path in write_competition_csvs(args.season, fixtures, {}):
            print(f"  wrote {path}")
        return 0

    finished = [row for row in fixtures if row["finished"]]
    if args.limit:
        finished = finished[: args.limit]
    print(f"  fetching detail for {len(finished)} finished matches "
          f"(~{len(finished) * THROTTLE_SECONDS / 60:.0f} min if uncached)\n")

    rows, missing = [], 0
    player_rows: Dict[str, List[Dict[str, Any]]] = {name: [] for name in names}
    for index, fixture in enumerate(finished, start=1):
        detail = (fetch_match_detail(str(fixture["match_id"]),refresh=True) if args.refresh_details
                  else fetch_match_detail(str(fixture["match_id"])))
        if detail is None:
            missing += 1
        write_semantic_stats(str(fixture["match_id"]), detail)
        rows.append(extract_stats(fixture, detail))
        player_rows[fixture["competition"]].extend(extract_players(fixture, detail))
        if index % 50 == 0 or index == len(finished):
            with_xg = sum(1 for row in rows if row.get("home_xg") is not None)
            print(f"    {index:>5}/{len(finished)}  with xG: {with_xg}")

    with_xg = sum(1 for row in rows if row.get("home_xg") is not None)
    print(f"\n  {len(rows)} matches normalised;  with xG: {with_xg}/{len(rows)}"
          f"   detail missing: {missing}")

    # Per-competition files in the repo's own layout: this is what the model will read.
    stats_by_id = {row["match_id"]: row for row in rows}
    print()
    written = write_competition_csvs(args.season, fixtures, stats_by_id)
    for path in written:
        print(f"  wrote {path}")
    if args.limit:
        print("  skipped player CSV writes for a limited detail run; use --players-only for a full cache rebuild")
    else:
        for competition, players in sorted(player_rows.items()):
            path = player_file_path(competition, args.season)
            write_player_csv(path, players)
            print(f"  wrote {len(players)} player rows: {path}")
    # last, so it is the line nightly.py reports: the step's one line used to be whichever file
    # happened to be written last ("wrote .../europa-league-2026.csv"), which says nothing
    print(f"\n  fetched {len(fixtures)} fixtures in "
          f"{len({row['competition'] for row in fixtures})} competitions, "
          f"{len(rows)} finished ({with_xg} with xG); wrote {len(written)} season files"
          + (f"; {len(empty)} returned none" if empty else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
