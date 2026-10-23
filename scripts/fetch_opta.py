"""Opta Power Rankings — ratings and a dated snapshot. Nothing else.

PLAN.md Phase 1.1: `scripts/update_team_rankings.py` did two unrelated jobs (scrape Opta ratings,
and re-download fixturedownload.com CSVs for the current season). This is the Opta half, split out
because Phase 1 needs it to run independently of the fixture-download half (which Fotmob is
replacing). The scrape internals below — `repair_js_escapes`, the men's/women's split in
`extract_rankings` — are ported **verbatim**: PLAN.md Part III marks them "keep, untouched", because
both fix silent corruption that already happened once (see their docstrings and
HANDOFF.md's "Critical gotchas"). `scripts/update_team_rankings.py` keeps the fixturedownload half.

    .venv/bin/python scripts/fetch_opta.py

Writes data/team_rankings.csv (the 4-column file the model loads) and a dated detailed snapshot
under data/team_rankings_history/. Every complete feed response is retained by content hash;
same-day CSV replacements are archived and retrieval observations use their actual UTC time.
"""
from __future__ import annotations

import ast
import csv
import io
import sys
import tempfile
import json
import re
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

APP_URL = "https://dataviz.theanalyst.com/opta-power-rankings/"
JS_URL = "https://dataviz.theanalyst.com/opta-power-rankings/index.js"
OUT_FILE = Path("data/team_rankings.csv")
SNAPSHOT_DIR = Path("data/team_rankings_history")
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from scripts.source_retention import retain_response
from scripts.ops_storage import atomic_write_files

TOP_N = 10000


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": APP_URL})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_json_object(text: str, start: int) -> dict | None:
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None

    return None


def repair_js_escapes(bundle: str) -> str:
    """Make the JS bundle's string literals parseable as JSON.

    The feed is JavaScript, not JSON, and uses two escapes JSON does not have. Both silently
    dropped teams before this existed:

      \\'  -> '   JS escapes an apostrophe; JSON rejects the escape outright.
      \\\\" -> \\"  A value containing an apostrophe is re-quoted with double quotes and escaped
                  one level too deep, so JSON reads \\\\ as an escaped backslash and the very next
                  quote ENDS the string early. That corrupts the object boundary too, not just
                  json.loads, which is why the repair has to happen before scanning.

    Concretely: "Hapoel Be\\'er Sheva" plays in "Ligat Ha'al", so its comps field carried both
    forms and the club — genuinely rank 182, rating 82.75 — was dropped from every snapshot.
    58 of 14202 men's teams were lost this way.
    """
    return bundle.replace('\\\\"', '\\"').replace("\\'", "'")


def extract_rankings(bundle: str) -> list[dict]:
    """Every men's team, in rank order.

    The bundle holds the men's rankings followed by the women's, each numbered from 1. Merging them
    on `rank` let a women's team claim a men's slot: HJK (Kansallinen Liiga, rating 70.8) sat at
    global rank 182 while the real occupant was absent. The two lists are separated structurally --
    there is exactly one point where `rank` decreases -- so reading stops there rather than relying
    on league-name heuristics.
    """
    bundle = repair_js_escapes(bundle)
    rankings: dict[int, dict] = {}
    pattern = re.compile(r'\{"rank":\d+,"contestantId"')
    previous = 0

    for match in pattern.finditer(bundle):
        item = extract_json_object(bundle, match.start())
        if not item:
            continue
        if not {"rank", "contestantName", "currentRating"} <= set(item):
            continue

        rank = int(item["rank"])
        if rank < previous:
            break  # the women's list restarts at 1
        previous = rank
        if rank in rankings:
            raise RuntimeError(
                f"duplicate rank {rank} within the men's list "
                f"({rankings[rank]['contestantName']!r} vs {item['contestantName']!r})"
            )
        rankings[rank] = item

    return [rankings[rank] for rank in sorted(rankings)]


def ranking_change_7d(item: dict) -> int | None:
    current = item.get("currentGlobalRank")
    previous = item.get("lastWeekGlobalRank")
    if current in (None, "") or previous in (None, ""):
        return None
    return int(previous) - int(current)


def rating_value(item: dict, key: str) -> float | None:
    try:
        return round(float(item.get(key)), 3)
    except (TypeError, ValueError):
        return None


def competition_names(item: dict) -> str:
    raw = item.get("comps")
    if not raw:
        return ""
    comps = raw
    if isinstance(raw, str):
        try:
            comps = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return ""
    names: list[str] = []
    for entry in comps:
        name = entry.get("competitionName") if isinstance(entry, dict) else None
        if name and name not in names:
            names.append(name)
    return "; ".join(names)


# Dated snapshots keep every raw feed field verbatim (full precision) so nothing Opta
# exposes is ever lost, plus a few derived convenience columns for calibration:
# weekly_rating_delta (currentRating - lastWeekRating), ranking_change_7d, and a
# human-readable competition_names. Raw "comps" is preserved as a JSON string.
# Important columns first for readability; every other raw field is appended alphabetically.
SNAPSHOT_PREFERRED_ORDER = (
    "rank",
    "contestantName",
    "contestantClubName",
    "currentRating",
    "lastWeekRating",
    "weekly_rating_delta",
    "seasonAverageRating",
    "lastWeekSeasonAverageRating",
    "highestSeasonRating",
    "lowestSeasonRating",
    "currentGlobalRank",
    "lastWeekGlobalRank",
    "currentConfederationRank",
    "lastWeekConfederationRank",
    "ranking_change_7d",
    "domesticLeagueName",
    "country",
    "association",
    "confederation",
    "competition_names",
    "comps",
)


def build_snapshot_row(item: dict) -> dict:
    row = dict(item)

    comps = item.get("comps")
    if isinstance(comps, str):
        try:
            comps = ast.literal_eval(comps)
        except (ValueError, SyntaxError):
            comps = None
    row["comps"] = json.dumps(comps) if comps is not None else ""

    current = rating_value(item, "currentRating")
    last_week = rating_value(item, "lastWeekRating")
    row["weekly_rating_delta"] = round(current - last_week, 3) if current is not None and last_week is not None else None
    row["ranking_change_7d"] = ranking_change_7d(item)
    row["competition_names"] = competition_names(item)
    return row


def snapshot_fieldnames(prepared_rows: list[dict]) -> list[str]:
    keys: set[str] = set()
    for row in prepared_rows:
        keys.update(row)
    ordered = [field for field in SNAPSHOT_PREFERRED_ORDER if field in keys]
    ordered.extend(sorted(field for field in keys if field not in SNAPSHOT_PREFERRED_ORDER))
    return ordered


def write_rankings_detailed(rows: list[dict], out_file: Path, top_n: int) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    prepared = [build_snapshot_row(item) for item in rows[:top_n]]
    fieldnames = snapshot_fieldnames(prepared)
    with out_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(prepared)


def write_rankings(rows: list[dict], out_file: Path, top_n: int) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["rank", "team", "rating", "ranking_change_7d"])
        writer.writeheader()
        for item in rows[:top_n]:
            writer.writerow(
                {
                    "rank": int(item["rank"]),
                    "team": item["contestantName"],
                    "rating": round(float(item["currentRating"]), 3),
                    "ranking_change_7d": ranking_change_7d(item),
                }
            )


def main() -> None:
    bundle = fetch_text(JS_URL)
    retain_response(SNAPSHOT_DIR/'responses',JS_URL,bundle.encode('utf-8'),representation='decoded_utf8')
    rankings = extract_rankings(bundle)
    if not rankings:
        raise RuntimeError("No Opta Power Rankings found in the downloaded bundle")
    snapshot_file = SNAPSHOT_DIR / f"team_rankings-{date.today().isoformat()}.csv"
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);current=root/'current.csv';detailed=root/'detailed.csv'
        write_rankings(rankings,current,TOP_N);write_rankings_detailed(rankings,detailed,TOP_N)
        atomic_write_files({OUT_FILE:current.read_bytes(),snapshot_file:detailed.read_bytes()})
    print(f"Wrote {min(TOP_N,len(rankings))} rankings to {OUT_FILE}; detailed snapshot {snapshot_file}")


if __name__ == "__main__":
    main()
