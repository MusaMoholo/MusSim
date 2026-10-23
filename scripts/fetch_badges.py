#!/usr/bin/env python3
"""Each league and UEFA league-phase side's badge, for the dashboard's Visualisations view.

    .venv/bin/python scripts/fetch_badges.py            # only the badges not on disk yet

FotMob names a team by id in every fixture row it gives us (`home_id` / `away_id` in
`data/fotmob/<country>/<comp>/*.csv`) and serves its logo at a URL built from that id. The id is
joined to OUR team name through the same `canonical_fotmob_team_name` the master table uses, so a
badge belongs to exactly the side the tables show. Logos are fetched once and kept in
`data/badges/<id>.png` with `index.json` mapping team -> file; `serve.py` serves them, so the page
never calls FotMob. A side with no badge is drawn as a dot with its name -- nothing breaks.

Run nightly by `nightly.py` (the `badges` step). A normal night fetches nothing: badges change
when a promoted or newly qualified side appears, about once a season.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from football_common import canonical_fotmob_team_name  # noqa: E402
from scripts.fetch_fotmob import USER_AGENT  # noqa: E402

FOTMOB_DIR = ROOT / "data/fotmob"
BADGE_DIR = ROOT / "data/badges"
MASTER = ROOT / "data/master_fixtures.pkl"
URL = "https://images.fotmob.com/image_resources/logo/teamlogo/{id}_small.png"   # 150 x 150


def team_ids() -> Dict[str, int]:
    """Our name -> FotMob id, from every fixture CSV. Where one name has had two ids, the latest
    season's wins."""
    out: Dict[str, int] = {}
    for path in sorted(FOTMOB_DIR.glob("*/*/*.csv"), key=lambda p: p.stem.rsplit("-", 1)[-1]):
        try:
            raw = pd.read_csv(path, usecols=["Home Team", "Away Team", "home_id", "away_id"])
        except (ValueError, KeyError):
            continue                                   # an old file without ids
        for name_col, id_col in (("Home Team", "home_id"), ("Away Team", "away_id")):
            for name, tid in zip(raw[name_col], pd.to_numeric(raw[id_col], errors="coerce")):
                if pd.notna(name) and pd.notna(tid):
                    out[canonical_fotmob_team_name(name)] = int(tid)
    return out


def wanted(season: int | None) -> set:
    """The sides a league table or a UEFA league phase shows in the live season."""
    m = pd.read_pickle(MASTER)
    season = season or int(m[m.played].season.max())
    fx = m[(m.season == season) & ((m.kind == "league") | ((m.kind == "uefa") & m["round"].notna()))]
    if "tbd" in fx:
        fx = fx[~fx.tbd]
    return set(fx.home) | set(fx.away)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, default=None)
    args = ap.parse_args()
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    ids = team_ids()
    teams = sorted(wanted(args.season))
    index_path = BADGE_DIR / "index.json"
    index: Dict[str, str] = json.loads(index_path.read_text()) if index_path.exists() else {}
    fetched, failed, unknown = 0, [], []
    for team in teams:
        tid = ids.get(team)
        if tid is None:
            unknown.append(team)
            continue
        f = BADGE_DIR / f"{tid}.png"
        if not f.exists():
            try:
                with urlopen(Request(URL.format(id=tid), headers={"User-Agent": USER_AGENT}),
                             timeout=30) as r:
                    body = r.read()
                if not body.startswith(b"\x89PNG"):
                    raise ValueError("not a PNG")
                f.write_bytes(body)
                fetched += 1
                time.sleep(0.2)
            except Exception as exc:                                 # noqa: BLE001
                failed.append(f"{team} ({exc})")
                continue
        index[team] = f.name
    index_path.write_text(json.dumps(dict(sorted(index.items())), indent=0))
    for t in unknown:
        print(f"! no FotMob id for {t}")
    for t in failed:
        print(f"! badge not fetched: {t}")
    have = sum(1 for t in teams if t in index)
    print(f"fetched {fetched} badge(s); {have} of {len(teams)} sides have one")
    # a side without a badge is drawn as a dot, so a miss is a warning, never a failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
