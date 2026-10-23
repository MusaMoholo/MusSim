"""Fetch the configured dated Elo history; retain every response and archive replacements.

Used by the nightly ratings step. Source dates remain the provider's dates; retrieval time
is recorded independently. An unchanged/delayed mirror is reported, never stamped as new data.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
import sys
import csv
import io
import math
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from scripts.source_retention import retain_response
from scripts.ops_storage import atomic_write_files
from urllib.request import Request, urlopen

ELO_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/main/data/EloRatings.csv"
OUT_FILE = Path("data/external/elo_ratings.csv")
# The mirror has published on the 1st and the 15th. Three weeks without a new date is a missed
# update, not a quiet fortnight.
STALE_DAYS = 21


def newest(raw: bytes) -> Optional[str]:
    """The latest rating date in the file, as YYYY-MM-DD."""
    dates = [ln.split(b",", 1)[0].strip(b'"') for ln in raw.splitlines()[1:] if ln.strip()]
    return max(dates).decode() if dates else None


def main() -> None:
    request = Request(ELO_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        raw = response.read()

    retain_response(OUT_FILE.parent/'elo_responses',ELO_URL,raw)

    if not raw.startswith(b'"date","club","country","elo"') and not raw.startswith(b"date,club,country,elo"):
        raise RuntimeError("downloaded file does not look like EloRatings.csv — header mismatch")

    parsed=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    if not parsed:raise RuntimeError('Elo history response has no observations; previous history kept')
    for row in parsed:
        date.fromisoformat(row['date'])
        if not row['club'] or not math.isfinite(float(row['elo'])):raise RuntimeError('Invalid Elo history observation; previous history kept')
    before = OUT_FILE.read_bytes() if OUT_FILE.exists() else None
    if before and newest(raw)<newest(before):raise RuntimeError('Elo history response is older than retained history; previous history kept')
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_files({OUT_FILE:raw})
    rows = sum(1 for ln in raw.splitlines()[1:] if ln.strip())
    latest = newest(raw)
    age = (date.today() - date.fromisoformat(latest)).days if latest else None
    # Re-downloading an unchanged file used to read "Wrote 273973 rows" every night, a success
    # message for a mirror that had not updated since 2026-09-01. Say what is new, and when the
    # answer is "nothing for weeks", warn.
    change = ("first fetch" if before is None
              else "unchanged since the last fetch" if before == raw
              else f"was {newest(before)}")
    print(f"wrote {rows} rows to {OUT_FILE}; newest ratings {latest} ({age} days old), {change}")
    if age is not None and age > STALE_DAYS:
        print(f"! the ClubElo mirror has not published since {latest} ({age} days)")


if __name__ == "__main__":
    main()
