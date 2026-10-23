#!/usr/bin/env python3
"""One command that checks the whole stack still works. Run it after changing anything.

    .venv/bin/python scripts/smoke.py

It is not a substitute for the model verification -- `scripts/uefa_bracket.py` and the scripts in
`analysis/` own that. This checks the plumbing: that the bracket self-checks pass, that a finished
season still replays exactly, that the parallel path agrees with the serial one to the last
decimal, that a snapshot round-trips, and that the dashboard serves without touching the model.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = "  ok    ", "  FAIL  "
results: list[bool] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    """`detail` is a failure explanation, so it is printed only when the check fails."""
    results.append(bool(ok))
    print((PASS if ok else FAIL) + label + ("" if ok else (f" — {detail}" if detail else "")),
          flush=True)


def check_track_record() -> None:
    """Point-in-time forecasts: use independently specified miniature seasons and snapshots."""
    from scripts.track_record import build_track, _model, MODEL, LEGACY_MODEL

    def match(comp: str, kind: str, home: str, away: str, kickoff: str, hg: int, ag: int,
              season: int = 2026, outcome: str = "finished", **extras: object) -> dict:
        return {"competition": comp, "kind": kind, "home": home, "away": away,
                "kickoff": kickoff, "home_goals": hg, "away_goals": ag, "season": season,
                "played": True, "outcome": outcome, "tbd": False, **extras}

    played = [match("Test League", "league", "Alpha", "Beta", "2026-09-05 15:00:00", 2, 0),
              match("Test League", "league", "Alpha", "Beta", "2026-09-06 12:00:00", 0, 1),
              match("Test Cup", "cup", "Gamma", "Delta", "2026-09-05 16:00:00", 3, 2,
                    outcome="afterextratime"),
              match("Test UEFA", "uefa", "Alpha", "Beta", "2026-09-05 15:00:00", 0, 0),
              match("Test League", "league", "No forecast", "Absent", "2026-09-05 18:00:00", 1, 0)]
    historical = [match("Test League", "league", "Past H", "Past A", f"2025-05-0{i} 15:00:00",
                        hg, ag, season=2025) for i, (hg, ag) in enumerate([(2, 0), (0, 0), (0, 1)], 1)]
    historical += [match("Test Cup", "cup", "Past H", "Past A", f"2025-05-0{i} 16:00:00",
                         hg, ag, season=2025, outcome=outcome)
                   for i, (hg, ag, outcome) in enumerate([(2, 1, "afterextratime"),
                                                         (4, 3, "penalties"), (0, 1, "finished")], 1)]
    historical += [match("Test UEFA", "uefa", "Past H", "Past A", "2025-05-01 17:00:00", 1, 0, season=2025)]
    # Outside the forecast population: a duplicate, a future result, a placeholder, an unplayed
    # fixture, and an old season outside the fixed 2021-25 base-rate reference.
    extras = [played[0].copy(), match("Test League", "league", "Future", "Absent", "2026-09-07 12:00:00", 2, 0),
              match("Test Cup", "cup", "TBD", "TBD", "2026-09-05 12:00:00", 0, 0, tbd=True),
              match("Test League", "league", "Unplayed", "Absent", "2026-09-05 12:00:00", 1, 0, played=False),
              match("Test League", "league", "Very old", "Absent", "2020-05-01 12:00:00", 1, 0, season=2020)]
    master = pd.DataFrame(historical + played + extras)
    master["kickoff"] = pd.to_datetime(master["kickoff"])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshots = [("2026-09-02", "2026-09-01", 1, [[.2, .3, .5]] * 4),
                     ("2026-09-04", "2026-09-03", 10, [[.6, .25, .15], [.5, .25, .25], [.7, .2, .1], [.3, .5, .2]]),
                     ("2026-09-05", "2026-09-05", 10, [[.99, .005, .005]] * 4),
                     ("2026-09-06", "2026-09-05", 4, [[.1, .2, .7], [.2, .3, .5], [.1, .8, .1], [.2, .7, .1]]),
                     ("2026-09-07", "2026-09-06", 10, [[.005, .005, .99]] * 4)]
        for day, as_of, version, probs in snapshots:
            folder = root / day
            folder.mkdir()
            (folder / "projection.json").write_text(json.dumps({"params": {"season": 2026},
                                                                "as_of": as_of, "version": version,
                                                                **({"model": MODEL} if version == 10 else {})}))
            fixtures = [{"competition": f["competition"], "home": f["home"], "away": f["away"],
                         "kickoff": f["kickoff"], "ladder": dict(zip(("h1", "d", "a1"), p))}
                        for f, p in zip(played[:4], probs)]
            (folder / "matches.json").write_text(json.dumps({"fixtures": fixtures}))
        (root / "index.json").write_text(json.dumps([{"date": day} for day, *_ in snapshots]))
        track = build_track(master, root, 2026, "2026-09-06")
        rows = track["matches"]
        key = lambda f: (f["competition"], f["home"], f["away"], f["date"])
        expected = {("Test League", "Alpha", "Beta", "2026-09-05"): ("2026-09-04", [.6, .25, .15]),
                    ("Test League", "Alpha", "Beta", "2026-09-06"): ("2026-09-06", [.2, .3, .5]),
                    ("Test Cup", "Gamma", "Delta", "2026-09-05"): ("2026-09-04", [.7, .2, .1]),
                    ("Test UEFA", "Alpha", "Beta", "2026-09-05"): ("2026-09-04", [.3, .5, .2])}
        source_ok = len(rows) == 4 and all(key(f) in expected and f["snapshot"] == expected[key(f)][0]
            and np.allclose(f["prob"], expected[key(f)][1], rtol=0, atol=1e-12)
            and f["as_of"] < f["date"] for f in rows)
        check(source_ok, "track record: 4 matches take the last eligible forecast by competition, sides and date; same-day cutoff leakage excluded",
              str([(key(f), f["snapshot"], f["prob"]) for f in rows]))
        coverage = track["coverage"]
        check(len(rows) == len({key(f) for f in rows}) == 4 and coverage == {"played": 5, "forecast": 4, "missing": 1},
              "track record: 5 unique played fixtures = 4 forecasts + 1 missing; duplicate, future, unplayed and TBD rows excluded", str(coverage))
        cup = [f for f in rows if f["competition"] == "Test Cup"]
        models = [f["current"] for f in rows]
        # A return leg reaches extra time when the aggregate is level. It can itself be a home
        # win or an away win at 90; the reversed first leg's margin determines which. Decoys
        # independently exercise competition, season, orientation, played status and 60 days.
        ties = [match("Return UEFA", "uefa", "First H", "Return H", "2026-08-20 15:00:00", 2, 0),
                match("Return UEFA", "uefa", "Return H", "First H", "2026-09-05 15:00:00", 3, 0, outcome="afterextratime"),
                match("Return UEFA", "uefa", "First A", "Return A", "2026-08-20 16:00:00", 0, 2),
                match("Return UEFA", "uefa", "Return A", "First A", "2026-09-05 16:00:00", 2, 3, outcome="afterextratime"),
                match("Return UEFA", "uefa", "First D", "Return D", "2026-08-20 17:00:00", 1, 1),
                match("Return UEFA", "uefa", "Return D", "First D", "2026-09-05 17:00:00", 1, 1, outcome="penalties"),
                match("Single Cup", "cup", "One", "Two", "2026-09-05 18:00:00", 3, 2, outcome="afterextratime")]
        decoys = [match("Other Cup", "cup", "Two", "One", "2026-09-04 18:00:00", 2, 0),
                  match("Single Cup", "cup", "Two", "One", "2026-09-03 18:00:00", 0, 2, season=2025),
                  match("Single Cup", "cup", "One", "Two", "2026-09-02 18:00:00", 0, 2),
                  match("Single Cup", "cup", "Two", "One", "2026-09-01 18:00:00", 2, 0, played=False),
                  match("Single Cup", "cup", "Two", "One", "2026-07-07 18:00:00", 2, 0),
                  match("Single Cup", "cup", "Two", "One", "2026-09-06 18:00:00", 0, 2)]
        old_ties = [{**f, "season": 2025, "kickoff": f["kickoff"].replace("2026-", "2025-")}
                    for f in ties]
        et_master = pd.DataFrame(ties + decoys + old_ties)
        et_master["kickoff"] = pd.to_datetime(et_master["kickoff"])
        et_root = root / "return-leg-cases"
        et_snapshot = et_root / "2026-09-04"
        et_snapshot.mkdir(parents=True)
        (et_snapshot / "projection.json").write_text(json.dumps({"params": {"season": 2026},
                                                                  "as_of": "2026-09-03", "version": 10}))
        et_fixtures = [{"competition": f["competition"], "home": f["home"], "away": f["away"],
                        "kickoff": f["kickoff"], "ladder": {"h1": .4, "d": .3, "a1": .3}}
                       for f in ties if f["outcome"] in ("afterextratime", "penalties")]
        (et_snapshot / "matches.json").write_text(json.dumps({"fixtures": et_fixtures}))
        et_track = build_track(et_master, et_root, 2026, "2026-09-06")
        recovered = {f["home"]: f["result"] for f in et_track["matches"]}
        uefa_base = et_track["base_rates"]["uefa"]
        et_ok = recovered == {"Return H": 0, "Return A": 2, "Return D": 1, "One": 1} \
            and uefa_base["n"] == 6 and np.allclose(uefa_base["prob"], [1/3, 1/3, 1/3], rtol=0, atol=1e-12)
        check(len(cup) == 1 and cup[0]["result"] == 1 and models.count(True) == 3 and models.count(False) == 1 and et_ok
              and _model({"version":10}, "2026-09-04") == LEGACY_MODEL != MODEL
              and _model({"version":4}, "2026-10-09") == LEGACY_MODEL,
              "track record: 4 ET cases recover H/D/A return legs and a single-leg draw, ignoring 6 false first legs; 3 current/1 older forecasts stay distinct",
              f"90-minute results {recovered}; UEFA base {uefa_base}; model groups {models}")
        bases = track["base_rates"]
        base_ok = all(k in bases and bases[k]["n"] == n and np.allclose(bases[k]["prob"], p, rtol=0, atol=1e-12)
                      for k, n, p in [("league", 3, [1/3, 1/3, 1/3]), ("cup", 3, [0, 2/3, 1/3]), ("uefa", 1, [1, 0, 0])])
        check(base_ok and all(abs(sum(f["prob"]) - 1) < 0.00015 for f in rows),
              "track record: 7 historical matches give normalized H/D/A base rates by kind; single-leg extra time and penalties count as draws", str(bases))
        reordered = build_track(master.sample(frac=1, random_state=13), root, 2026, "2026-09-06")
        order = lambda f: (f["kickoff"], f["competition"], f["home"], f["away"])
        check(rows == sorted(rows, key=order) and rows == reordered["matches"] and bases == reordered["base_rates"],
              "track record: 4 forecast rows keep a total order and identical values when the master rows are shuffled")


def check_team_data() -> None:
    """Ratings history alignment and the played-match endpoint on small independent files."""
    from scripts.serve import Snapshots

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        days = ["2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23"]
        rating_rows = [[{"team": "Alpha", "elo": 1000, "att": 1.2, "def": .8}], None,
                       [{"team": "Beta", "elo": 900, "att": .9, "def": 1.1}],
                       [{"team": "Alpha", "elo": 1002, "att": 1.21, "def": .79}]]
        for day, ratings in zip(days, rating_rows):
            folder = root / day
            folder.mkdir()
            cutoff = str((pd.Timestamp(day) - pd.Timedelta(days=1)).date())
            payload = {"params": {"season": 2026}, "worlds": 100, "as_of": cutoff,
                       "version": 10, "leagues": [], "uefa": []}
            if ratings is not None:
                payload["ratings"] = {"teams": ratings}
            (folder / "projection.json").write_text(json.dumps(payload))
        (root / "index.json").write_text(json.dumps([{"date": day} for day in days]))
        csv_path = root / "master.csv"
        columns = ["season", "competition", "kind", "kickoff", "home", "away", "played", "tbd",
                   "home_goals", "away_goals", "home_xg", "away_xg", "outcome", "minutes", "round"]
        fixtures = [[2026, "Test League", "league", "2026-08-20 15:00:00", "Alpha", "Beta", True, False, 2, 1, 1.2, .5, "finished", 90, 1],
                    [2026, "Test Cup", "cup", "2026-08-22 23:59:00", "Gamma", "Alpha", True, False, 0, 1, None, None, "finished", 90, None],
                    [2026, "Test UEFA", "uefa", "2026-08-22 20:00:00", "Alpha", "Delta", True, False, 1, 1, .8, 1.0, "finished", 90, 1],
                    [2025, "Test League", "league", "2025-08-21 15:00:00", "Alpha", "Beta", True, False, 2, 0, 1.5, .4, "finished", 90, 1],
                    [2026, "Test League", "league", "2026-08-23 00:00:00", "Alpha", "Future", True, False, 1, 0, 1.1, .2, "finished", 90, 2],
                    [2026, "Test Cup", "cup", "2026-08-22 14:00:00", "Alpha", "TBD", True, True, 0, 0, None, None, "finished", 90, None],
                    [2026, "Test League", "league", "2026-08-22 15:00:00", "Alpha", "Unplayed", False, False, 1, 0, None, None, "", None, 2],
                    [2026, "Test League", "league", "2026-08-22 16:00:00", "Alpha", "No score", True, False, None, 0, None, None, "finished", 90, 2],
                    [2026, "Test League", "league", "2026-08-22 17:00:00", "Beta", "Gamma", True, False, 1, 0, 1.0, .6, "finished", 90, 2]]
        pd.DataFrame(fixtures, columns=columns).to_csv(csv_path, index=False)
        snapshots = Snapshots(root, master_csv=csv_path)
        history = snapshots.history(2026)
        expected = {"Alpha": {"elo": [1000, None, None, 1002], "att": [1.2, None, None, 1.21], "def": [.8, None, None, .79]},
                    "Beta": {"elo": [None, None, 900, None], "att": [None, None, .9, None], "def": [None, None, 1.1, None]}}
        check(history["dates"] == days and history.get("ratings") == expected,
              "team page: 24 ratings-history cells preserve exact Elo/ATT/DEF and leading, middle and trailing holes across 4 snapshots",
              str(history.get("ratings")))
        current = snapshots.team_fixtures("Alpha", days[-1])
        past = snapshots.team_fixtures("Alpha", days[-2])
        actual = current["fixtures"] if current else []
        expected_keys = [("Test League", "Alpha", "Beta", "2026-08-20"),
                         ("Test UEFA", "Alpha", "Delta", "2026-08-22"),
                         ("Test Cup", "Gamma", "Alpha", "2026-08-22")]
        keys = [(f["competition"], f["home"], f["away"], f["kickoff"][:10]) for f in actual]
        values_ok = len(actual) == 3 and actual[0]["result"] == [2, 1] and actual[0].get("xg") == [1.2, .5] \
            and actual[1]["result"] == [1, 1] and actual[1].get("xg") == [.8, 1.0] \
            and actual[2]["result"] == [0, 1] and "xg" not in actual[2]
        check(current is not None and current["season"] == 2026 and current["as_of"] == "2026-08-22"
              and keys == expected_keys and values_ok and past is not None and len(past["fixtures"]) == 1
              and snapshots.team_fixtures("Alpha", "2026-01-01") is None,
              "team page: 3 of 9 CSV fixtures include leagues, UEFA and cups through the cutoff's last minute, preserve scores/xG, and respect season, TBD, played and finite scores",
              str(current))


def check_gw_compression() -> None:
    """Compressed snapshots win over stale plain files, while old plain snapshots still load."""
    from scripts import nightly
    from unittest.mock import patch
    from scripts.serve import Snapshots

    fresh = {"worlds": 2, "leagues": {"Test League": {"teams": ["Alpha", "Beta"],
             "fixtures": [{"round": 1, "kickoff": "2026-08-22 15:00:00", "home": "Alpha", "away": "Beta",
                           "result": [2, 0], "xg": [1.3, .4]}],
             "elo": [[1000, 1001], [900, 899]], "att": [[1.2, 1.21], [.9, .89]],
             "def": [[.8, .79], [1.1, 1.11]], "rating_days": ["2026-08-21", "2026-08-22"],
             "rating_real": [True, False]}}, "phases": {}}
    stale = json.loads(json.dumps(fresh))
    stale["worlds"] = 99
    stale["leagues"]["Test League"]["fixtures"][0]["result"] = [8, 8]
    stale["leagues"]["Test League"]["elo"][0][0] = 777
    raw = json.dumps(fresh).encode()
    packed = gzip.compress(raw, mtime=0)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        days = ["2026-08-22", "2026-08-23", "2026-08-24"]
        for day in days:
            folder = root / day
            folder.mkdir()
            (folder / "projection.json").write_text(json.dumps({"params": {"season": 2026},
                                                               "worlds": 2, "as_of": "2026-08-22"}))
            (folder / "gw.json").write_text(json.dumps(stale))
        (root / "index.json").write_text(json.dumps([{"date": day} for day in days]))
        (root / days[0] / "gw.json.gz").write_bytes(packed)
        snapshots = Snapshots(root)
        compressed = snapshots.gw_bytes(days[0])
        plain = snapshots.gw_bytes(days[1])
        check(snapshots.gw(days[0]) == fresh and snapshots.gw(days[1]) == stale
              and compressed == (packed, "gzip") and plain is not None and plain[1] is None
              and json.loads(plain[0]) == stale,
              "gameweek gzip: 2 snapshots prove gzip priority over different stale plain data and old plain-file fallback, preserving fixtures and 12 rating values")
        with patch.object(nightly, "ARCHIVE_ROOT", root / "archives"):
            output = nightly.write_gw_snapshot(root / days[2], fresh)
        check(output == root / days[2] / "gw.json.gz" and output.exists()
              and not (root / days[2] / "gw.json").exists()
              and json.loads(gzip.decompress(output.read_bytes())) == fresh
              and snapshots.gw(days[2]) == fresh,
              "gameweek gzip: the nightly writer round-trips 1 fixture and 12 rating values and leaves no stale plain file")


def check_gw_http(base: str, snapshots, day: str) -> None:
    """Assert on the actual HTTP bytes, headers and complete decoded snapshot object."""
    import urllib.request

    stored = snapshots.gw_bytes(day)
    if not stored:
        print("  skip    gameweek gzip HTTP identity (snapshot has no gw.json or gw.json.gz)")
        return
    with urllib.request.urlopen(base + "/api/gw?date=" + day) as response:
        body = response.read()
        encoding = response.headers.get("Content-Encoding")
        content_type = response.headers.get("Content-Type", "")
        content_length = response.headers.get("Content-Length")
    decode_error = ""
    try:
        decoded = json.loads(gzip.decompress(body) if encoding == "gzip" else body)
    except (OSError, ValueError) as exc:
        decoded = None
        decode_error = str(exc)
    expected_gw = snapshots.gw(day)
    blocks = list(expected_gw.get("leagues", {}).values()) + list(expected_gw.get("phases", {}).values())
    fixture_n = sum(len(b.get("fixtures", [])) for b in blocks)
    rating_n = sum(len(row) for b in blocks for key in ("elo", "att", "def") for row in b.get(key, []))
    check(body == stored[0] and encoding == stored[1] and content_type.startswith("application/json")
          and content_length == str(len(body)) and decoded == expected_gw and fixture_n > 0
          and json.load(urllib.request.urlopen(base + "/api/meta"))["model_loaded"] is False,
          f"gameweek gzip: HTTP serves the exact {encoding or 'plain'} file with correct headers; JSON preserves {fixture_n} fixtures and {rating_n} rating values without loading the model",
          decode_error or f"encoding {encoding!r}/{stored[1]!r}, bytes {len(body)}/{len(stored[0])}, Content-Type {content_type}")


def check_head_to_head() -> None:
    """The shared history is cross-competition, cutoff-safe, newest first, and bounded at six."""
    from scripts.projection import head_to_head

    dates = ["2025-05-20", "2025-05-21", "2025-05-22"] + [f"2026-08-{d}" for d in range(20, 27)]
    meetings = []
    for i, day in enumerate(dates):
        meetings.append({"competition": ["Test League", "Test Cup", "Test UEFA"][i % 3],
                         "season": 2025 if i < 3 else 2026, "kind": ["league", "cup", "uefa"][i % 3],
                         "home": "Alpha" if i % 2 == 0 else "Beta", "away": "Beta" if i % 2 == 0 else "Alpha",
                         "kickoff": day + (" 23:59:00" if day == "2026-08-24" else " 15:00:00"),
                         "home_goals": i % 4, "away_goals": (i + 1) % 3,
                         "home_xg": None if i == 7 else round(.2 + i / 10, 2), "away_xg": round(.1 + i / 10, 2),
                         "played": True, "tbd": False})
    template = {**meetings[-1], "home": "Alpha", "away": "Beta", "home_goals": 9, "away_goals": 9}
    decoys = [{**template, "kickoff": "2026-09-05 15:00:00"},  # the target fixture now present as played
              {**template, "kickoff": "2026-09-06 15:00:00"},
              {**template, "kickoff": "2026-08-24 18:00:00", "away": "Other opponent"},
              {**template, "kickoff": "2026-08-24 19:00:00", "played": False},
              {**template, "kickoff": "2026-08-24 20:00:00", "tbd": True}]
    master = pd.DataFrame(meetings + decoys)
    master["kickoff"] = pd.to_datetime(master["kickoff"])
    master.attrs = {"sentinel": {"values": [1, 2, 3]}}
    before = master.copy()
    as_rows = lambda rs: [[r["kickoff"][:10], r["competition"], r["home"], r["away"],
                          r["home_goals"], r["away_goals"], r["home_xg"], r["away_xg"]] for r in rs]
    cases = [("2026-08-25", as_rows(meetings[2:8][::-1])),
             ("2026-08-22", as_rows(meetings[:5][::-1])),
             ("2026-09-01", as_rows(meetings[4:][::-1]))]
    wrong = []
    for cutoff, expected in cases:
        actual = head_to_head(master, pd.Timestamp(cutoff)).get(("Alpha", "Beta"), [])
        shuffled = head_to_head(master.sample(frac=1, random_state=17), pd.Timestamp(cutoff)).get(("Alpha", "Beta"), [])
        if actual != expected or shuffled != expected:
            wrong.append(f"{cutoff}: {actual}")
    check(not wrong and master.equals(before) and master.attrs == before.attrs,
          "head-to-head: 3 cutoffs select 6/5/6 exact newest meetings across seasons and competitions, preserve home/away and unknown xG, exclude target/future/TBD/unplayed/opponent decoys",
          "; ".join(wrong))


def check_projection_head_to_head(payload: dict, master: pd.DataFrame) -> None:
    """Audit serialized match and GW history directly against independent master-table rows."""
    from scripts.projection import MODEL_GENERATION, PAYLOAD_VERSION

    pairs = {}
    cutoff = pd.Timestamp(payload["as_of"]) + pd.Timedelta(days=1)
    for r in master.to_dict("records"):
        if not r["played"] or r.get("tbd", False) or r["kickoff"] >= cutoff:
            continue
        if pd.isna(r["home_goals"]) or pd.isna(r["away_goals"]):
            continue
        pairs.setdefault(tuple(sorted((r["home"], r["away"]))), []).append(r)
    for rows in pairs.values():
        rows.sort(key=lambda r: (r["kickoff"], r["competition"], r["home"], r["away"]), reverse=True)
    fixtures = list(payload["matches"]["fixtures"])
    fixtures += [{**f, "competition": comp} for comp, block in
                 {**payload["gw"]["leagues"], **payload["gw"]["phases"]}.items()
                 for f in block["fixtures"] if not f.get("result")]
    wrong, meetings = [], 0
    for f in fixtures:
        source = pairs.get(tuple(sorted((f["home"], f["away"]))), [])[:6]
        expected = [[str(r["kickoff"].date()), r["competition"], r["home"], r["away"],
                     int(r["home_goals"]), int(r["away_goals"]),
                     None if pd.isna(r.get("home_xg")) else float(r["home_xg"]),
                     None if pd.isna(r.get("away_xg")) else float(r["away_xg"])] for r in source]
        meetings += len(expected)
        if f.get("h2h") != expected:
            wrong.append(f"{f['competition']} {f['home']} v {f['away']}")
    check(len(fixtures) > 0 and meetings > 0 and not wrong and payload.get("model") == MODEL_GENERATION
          and isinstance(MODEL_GENERATION, str) and bool(MODEL_GENERATION) and payload.get("version") == PAYLOAD_VERSION,
          f"head-to-head: {len(fixtures)} match/GW forecasts carry {meetings} exact played master rows, newest six and cutoff-safe; model stamp {MODEL_GENERATION}",
          "; ".join(wrong[:4]))


def check_cup_reference() -> None:
    """Null cup rounds still carry all named entrants on the competition's strength scale."""
    from scripts.projection import comp_shift, npxg_scale, to_npxg

    fixtures = pd.DataFrame([
        {"kind": "league", "competition": "Test League", "home": "Alpha", "away": "Beta", "round": 1, "tbd": False},
        {"kind": "cup", "competition": "Test Cup", "home": "Alpha", "away": "Cup only", "round": None, "tbd": False},
        {"kind": "cup", "competition": "Test Cup", "home": "Beta", "away": "Eliminated", "round": None, "tbd": False},
        {"kind": "cup", "competition": "Test Cup", "home": "TBD one", "away": "TBD two", "round": None, "tbd": True}])
    values = {"Alpha": (.2, .1), "Beta": (-.2, -.1), "Cup only": (.5, -.2), "Eliminated": (-.5, .2)}
    model = {"base": {"Test League": .1, "Test Cup": .2}, "home": {"Test League": .2, "Test Cup": .1},
             "elo_mean": 1000, "slope": .6061}
    global_scale = npxg_scale(model, fixtures, values.__getitem__)
    cup_scale = npxg_scale(model, fixtures, values.__getitem__, "Test Cup")
    q, t = np.array(list(values.values())).T
    ga, gd = to_npxg(global_scale, q, t)
    shift = comp_shift(cup_scale, global_scale)
    a, d = ga * np.exp(shift[0]), gd * np.exp(shift[1])
    ca, cd = to_npxg(cup_scale, q, t)
    check(cup_scale["teams"] == 4 and global_scale["teams"] == 2
          and np.allclose(a, ca, rtol=0, atol=1e-12) and np.allclose(d, cd, rtol=0, atol=1e-12)
          and abs(float(np.exp(np.log(a).mean()) / np.exp(np.log(d).mean())) - 1) < 1e-12,
          "match card: 2 null-round cup fixtures reference all 4 named participants, including eliminated/lower-division sides; TBD excluded and scaled ATT/DEF balance")


def check_whatif(acc, payload: dict) -> None:
    """All competition sides, before wire filtering: conditional counts partition each fate."""
    from scripts.projection import STAKES, whatif_payload

    failures, wire_failures, scope_failures = [], [], []
    cells = side_cells = included = omitted = eligible = excluded = 0
    observed_slots = []
    by_key = {(f["competition"], f["home"], f["away"], f["kickoff"]): f
              for f in payload["matches"]["fixtures"]}
    for i, meta in enumerate(acc.fx_meta):
        slot = int(acc.whatif_pos[i])
        wanted = bool(meta["next"] and meta["kind"] in STAKES and meta["round"] is not None)
        if wanted != (slot >= 0):
            scope_failures.append(f"{meta['competition']} {i}: wrong eligibility")
        full = whatif_payload(acc, i, include_all=True)
        wire = whatif_payload(acc, i)
        key = tuple(meta[k] for k in ("competition", "home", "away", "kickoff"))
        fixture = by_key.get(key)
        if not wanted:
            excluded += 1
            if full is not None or wire is not None or fixture and "whatif" in fixture:
                scope_failures.append(f"{key}: ineligible what-if leaked")
            continue
        eligible += 1
        observed_slots.append(slot)
        block = (acc.leagues if meta["kind"] == "league" else acc.phases)[meta["competition"]]
        teams = list(block["teams"])
        tally = acc.fx_whatif[slot, :, :len(teams), :]
        if meta["kind"] == "league":
            pos = block["pos"]
            if hasattr(acc, "europe_counts"):
                entry = np.array([acc.europe_counts.get(t, np.zeros(3, np.int32)) for t in teams], np.int64)
                unconditional = np.c_[pos[:, 0], entry[:, 0], entry.sum(axis=1),
                                       pos[:, -int(block["relegated_n"]):].sum(axis=1)].astype(np.int64)
            else:
                u = int(block["ucl_spots"])
                e = u + int(block.get("uel_spots", 0)) + int(block.get("uecl_spots", 0))
                unconditional = np.c_[pos[:, 0], pos[:, :u].sum(axis=1), pos[:, :e].sum(axis=1),
                                       pos[:, -int(block["relegated_n"]):].sum(axis=1)].astype(np.int64)
        else:
            stats = acc.uefa[meta["competition"]]["teams"]
            unconditional = np.array([[sum(s <= 8 for s in stats[t]["seed"]),
                                       sum(s <= 24 for s in stats[t]["seed"]),
                                       stats[t]["reach"]["R16"], stats[t]["win"]]
                                      for t in teams], dtype=np.int64)
        cells += len(teams) * 4
        if not np.array_equal(tally.sum(axis=0, dtype=np.int64), unconditional):
            failures.append(f"{key}: sum of conditional fate counts differs from final tables")
        if np.any(acc.fx_whatif[slot, :, len(teams):, :]):
            failures.append(f"{key}: nonzero padded team slots")
        scores = acc.fx_counts[i]
        by_result = np.array([np.tril(scores, -1).sum(), np.trace(scores),
                              np.triu(scores, 1).sum()], dtype=np.int64)
        if int(by_result.sum()) != acc.worlds:
            failures.append(f"{key}: result counts do not partition all {acc.worlds} worlds")
        for side, team in enumerate((meta["home"], meta["away"])):
            side_cells += 12
            if not np.array_equal(tally[:, teams.index(team), :], acc.fx_stakes[i, :, side, :]):
                failures.append(f"{key} {team}: playing side differs from stakes counts")
        wanted_teams = []
        expected_full = {}
        for t, team in enumerate(teams):
            # >= 0.005, using integers: no rounded wire value decides the threshold.
            keep = any(int(by_result[o]) > 0 and any(
                200 * abs(int(tally[o, t, k]) * acc.worlds
                          - int(unconditional[t, k]) * int(by_result[o]))
                >= int(by_result[o]) * acc.worlds for k in range(4)) for o in range(3))
            if keep:
                wanted_teams.append(team)
            expected_full[team] = [[round(int(tally[o, t, k]) / int(by_result[o]), 3)
                                    if by_result[o] else None for o in range(3)] for k in range(4)]
        included += len(wanted_teams)
        omitted += len(teams) - len(wanted_teams)
        if full != expected_full or wire != {t: expected_full[t] for t in wanted_teams}:
            wire_failures.append(f"{key}: wrong all-team values, threshold or four-fate shape")
        if fixture is None or fixture.get("whatif") != wire:
            wire_failures.append(f"{key}: matches.json differs from exact filtered counts")
    scope_ok = (acc.fx_whatif.dtype == np.int32 and acc.fx_whatif.ndim == 4
                and acc.fx_whatif.shape[1] == 3 and acc.fx_whatif.shape[-1] == 4
                and sorted(observed_slots) == list(range(acc.fx_whatif.shape[0]))
                and not any("whatif" in f for g in {**payload["gw"]["leagues"],
                                                       **payload["gw"]["phases"]}.values()
                            for f in g["fixtures"]))
    # Deliberately put one side exactly on 0.5pp, another just below, and a third above.
    # A second state removes draws completely: an unseen outcome must serialize as null.
    import copy
    probe = copy.copy(acc)
    probe.fx_counts = acc.fx_counts.copy()
    probe.fx_whatif = acc.fx_whatif.copy()
    probe_i = next(i for i, m in enumerate(acc.fx_meta) if m["kind"] == "league"
                   and acc.whatif_pos[i] >= 0)
    probe_slot = int(acc.whatif_pos[probe_i])
    probe_teams = list(acc.leagues[acc.fx_meta[probe_i]["competition"]]["teams"])
    probe.fx_counts[probe_i].fill(0)
    probe.fx_counts[probe_i, 2, 0] = 200
    probe.fx_counts[probe_i, 1, 1] = 300
    probe.fx_counts[probe_i, 0, 2] = 500
    probe.fx_whatif[probe_slot].fill(0)
    for t, counts in enumerate(((21, 30, 49), (20, 31, 49), (22, 30, 48))):
        probe.fx_whatif[probe_slot, :, t, 0] = counts
    boundary_ok = set(whatif_payload(probe, probe_i)) == {probe_teams[0], probe_teams[2]}
    probe.fx_counts[probe_i, 1, 1] = 0
    probe.fx_counts[probe_i, 2, 0] = 500
    probe.fx_whatif[probe_slot, 1].fill(0)
    no_draw = whatif_payload(probe, probe_i, include_all=True)
    boundary_ok &= all(len(fates) == 4 and all(len(row) == 3 and row[1] is None
                                              for row in fates) for fates in no_draw.values())
    check(eligible > 0 and cells > 1000 and side_cells > 0 and not failures,
          f"what-if: {cells} unfiltered side-fates across {eligible} fixtures partition every final-table fate exactly; {side_cells} playing-side values equal stakes",
          "; ".join(failures[:3]))
    check(included > 0 and boundary_ok and not wire_failures,
          f"what-if: {included} included/{omitted} omitted side rows use the exact 0.5pp threshold (3 boundary probes); all four fates retained, unseen results null",
          "; ".join(wire_failures[:3]) or "threshold boundary or unseen-result probe failed")
    check(eligible > 0 and excluded > 0 and scope_ok and not scope_failures,
          f"what-if: {eligible} next-round league/phase fixtures only, {excluded} later/cup fixtures excluded; int32 counts stay out of GW",
          "; ".join(scope_failures[:3]) or str(acc.fx_whatif.shape))


def sample_from_world(acc, sim: pd.DataFrame, world_index: int) -> dict:
    """Independent, plain-Python result tally for one absolute-indexed simulated world."""
    blocks = {**acc.leagues, **acc.phases}
    tables = {comp: {str(team): {"team": str(team), "pl": 0, "w": 0, "d": 0, "l": 0,
                                "gf": 0, "ga": 0, "gd": 0, "pts": 0, "pos": 0}
                     for team in block["teams"]} for comp, block in blocks.items()}
    attrs, sim.attrs = sim.attrs, {}
    try:
        for row in sim.itertuples(index=False):
            if row.phase != "league" or row.competition not in tables:
                continue
            for team, gf, ga in ((row.home, row.home_goals, row.away_goals),
                                  (row.away, row.away_goals, row.home_goals)):
                rec = tables[row.competition][team]
                rec["pl"] += 1
                rec["gf"] += int(gf)
                rec["ga"] += int(ga)
                rec["w" if gf > ga else "l" if gf < ga else "d"] += 1
        for comp, rows in tables.items():
            for rec in rows.values():
                rec["gd"] = rec["gf"] - rec["ga"]
                rec["pts"] = 3 * rec["w"] + rec["d"]
            if comp in acc.leagues:
                order = sorted(rows, key=lambda team: (-rows[team]["pts"], -rows[team]["gd"],
                                                       -rows[team]["gf"], team))
                for pos, team in enumerate(order, 1):
                    rows[team]["pos"] = pos
        champions = {comp: next(t for t, r in rows.items() if r["pos"] == 1)
                     for comp, rows in tables.items() if comp in acc.leagues}
        for (comp, _), report in attrs.get("knockout", {}).items():
            if comp in acc.phases:
                for pos, team in report["seeds"].items():
                    tables[comp][team]["pos"] = int(pos)
            if report.get("champion"):
                champions[comp] = report["champion"]
        for (comp, _), report in attrs.get("cups", {}).items():
            if report.get("champion"):
                champions[comp] = report["champion"]
    finally:
        sim.attrs = attrs
    sample = {"index": world_index, "world": world_index + 1,
              "leagues": {comp: sorted(tables[comp].values(), key=lambda r: r["pos"])
                          for comp in sorted(acc.leagues)},
              "phases": {comp: sorted(tables[comp].values(), key=lambda r: r["pos"])
                         for comp in sorted(acc.phases)},
              "champions": dict(sorted(champions.items()))}
    if getattr(acc, "europe_policy", None):
        from scripts.europe_places import seat_world
        orders = {comp: [r["team"] for r in rows] for comp, rows in sample["leagues"].items()}
        by_association = seat_world(orders, champions, acc.europe_policy, acc.europe_associations)
        seats = {key: set().union(*(row[key] for row in by_association.values()))
                 for key in ("ucl", "uel", "uecl")}
        for comp in ("UEFA Champions League", "UEFA Europa League"):
            team = champions.get(comp)
            if team and team not in acc.europe_associations:
                seats["ucl"].add(team)
        team = champions.get("UEFA Conference League")
        if team and team not in acc.europe_associations and team not in seats["ucl"]:
            seats["uel"].add(team)
        sample["europe"] = {key: sorted(teams) for key, teams in seats.items()}
    return sample


def check_samples(payload: dict, expected: list[dict]) -> None:
    """Validity alone is not enough: the first five worlds must be the actual named worlds."""
    samples = payload.get("samples", [])
    failures, champion_failures = [], []
    tables = rows = champions = 0
    blocks = {b["competition"]: {r["team"]: r for r in b["teams"]}
              for b in payload["leagues"] + payload["uefa"] + payload["cups"]}
    required = {"leagues": {b["competition"] for b in payload["leagues"]},
                "phases": {b["competition"] for b in payload["uefa"] if b.get("rounds")}}
    for sample in samples:
        for family in ("leagues", "phases"):
            if set(sample.get(family, {})) != required[family]:
                failures.append(f"world{sample.get('world')}: {family} coverage differs")
            for comp, record in sample.get(family, {}).items():
                tables += 1
                rows += len(record)
                names = [r["team"] for r in record]
                if (len(names) != len(set(names)) or set(names) != set(blocks.get(comp, {}))
                        or [r["pos"] for r in record] != list(range(1, len(record) + 1))):
                    failures.append(f"world{sample.get('world')} {comp}: names or places differ")
                if (sum(r["gf"] for r in record) != sum(r["ga"] for r in record)
                        or sum(r["w"] for r in record) != sum(r["l"] for r in record)
                        or sum(r["d"] for r in record) % 2):
                    failures.append(f"world{sample.get('world')} {comp}: goals or match totals fail")
                for r in record:
                    if (any(not isinstance(r[k], int) for k in ("pl", "w", "d", "l", "gf", "ga", "gd", "pts", "pos"))
                            or any(r[k] < 0 for k in ("pl", "w", "d", "l", "gf", "ga", "pts"))
                            or r["pl"] != r["w"] + r["d"] + r["l"]
                            or r["pts"] != 3 * r["w"] + r["d"] or r["gd"] != r["gf"] - r["ga"]):
                        failures.append(f"world{sample.get('world')} {comp} {r['team']}: record fails")
        for comp, team in sample.get("champions", {}).items():
            champions += 1
            if not blocks.get(comp, {}).get(team, {}).get("p_win", 0) > 0:
                champion_failures.append(f"world{sample.get('world')} {comp}: {team} has no winning chance")
            league = sample.get("leagues", {}).get(comp)
            if league and (not league or league[0]["team"] != team):
                champion_failures.append(f"world{sample.get('world')} {comp}: champion not first")
        if set(sample.get("champions", {})) != set(blocks):
            champion_failures.append(f"world{sample.get('world')}: not exactly one champion per competition")
    check(len(samples) == len(expected) == 5 and [s["index"] for s in samples] == list(range(5))
          and [s["world"] for s in samples] == list(range(1, 6)) and samples == expected,
          "sample worlds: absolute indices 0–4 equal five independently tallied simulated worlds and their official UEFA seeds/champions",
          f"indices {[s.get('index') for s in samples]}; independent equality {samples == expected}")
    check(tables > 0 and rows > 0 and not failures,
          f"sample worlds: {tables} final tables / {rows} real unique sides satisfy W+D+L=PL, PTS=3W+D, GD=GF−GA, balanced goals and places1..n",
          "; ".join(failures[:3]))
    check(champions > 0 and not champion_failures,
          f"sample worlds: {champions} champions, one per competition/world, each with positive projected title chance",
          "; ".join(champion_failures[:3]))


def check_sample_merge(init_args: tuple, init_kwargs: dict, worlds: dict,
                       expected: list[dict]) -> None:
    """Force later-index chunks to finish first instead of depending on worker timing."""
    from scripts.projection import Accumulator
    early = Accumulator(*init_args, **init_kwargs)
    late = Accumulator(*init_args, **init_kwargs)
    total = Accumulator(*init_args, **init_kwargs)
    for i in (9, 5, 8, 6, 7):
        late.add(worlds[i], world_index=i)
    late_samples = late.result().get("samples")
    for i in (4, 0, 3, 1, 2):
        early.add(worlds[i], world_index=i)
    total.merge(late).merge(early)
    merged = total.result().get("samples")
    import copy
    duplicate = Accumulator(*init_args, **init_kwargs)
    duplicate.samples = {0: copy.deepcopy(expected[0])}
    total.merge(duplicate)
    same_ok = total.result().get("samples") == expected
    conflict = Accumulator(*init_args, **init_kwargs)
    changed = copy.deepcopy(expected[0])
    next(iter(changed["leagues"].values()))[0]["pts"] += 1
    conflict.samples = {0: changed}
    rejects_conflict = False
    try:
        total.merge(conflict)
    except ValueError:
        rejects_conflict = True
    check(late_samples == [] and merged == expected and same_ok and rejects_conflict,
          "sample worlds: forced chunk5–9 before0–4 keeps absolute worlds0–4; duplicate index is idempotent, conflicting index rejected",
          f"late indices {[s.get('index') for s in late_samples or []]}; merged {[s.get('index') for s in merged or []]}; duplicate {same_ok}, conflict rejected {rejects_conflict}")


def check_rivals(init_args: tuple, init_kwargs: dict, worlds: dict) -> None:
    """Every retained smoke world, compared to an independent fixture-ledger reference."""
    import copy
    from scripts.projection import Accumulator, final_table
    from scripts.race_room import RivalTally
    comp = 'English Premier League'
    candidate = Accumulator(*init_args, **{**init_kwargs, 'race_competition': comp, 'route_competition': comp})
    tally = candidate.rivals[comp]
    n = len(tally.teams)
    expected = np.zeros_like(tally.gaps)
    timing = np.zeros_like(candidate.leagues[comp]["clinch"])
    for index, world in sorted(worlds.items()):
        reference = sample_from_world(candidate, world, index)
        positions = {r['team']: r['pos'] for r in reference['leagues'][comp]}
        for a, team in enumerate(tally.teams):
            for b, other in enumerate(tally.teams):
                expected[a, b, positions[other]-positions[team]+n-1] += 1
        # Independently count a points clinch from raw match ledgers, grouping original rounds.
        attrs, world.attrs = world.attrs, {}
        try:
            matches = [(row.home,row.away,int(row.home_goals),int(row.away_goals),int(candidate.round_of[row.fixture_id]))
                       for row in world.itertuples() if row.competition==comp and row.phase=='league']
        finally:
            world.attrs = attrs
        champion = reference['leagues'][comp][0]['team']
        total_games = {t:sum(t in (h,a) for h,a,*_ in matches) for t in tally.teams}
        clinch_round = candidate.leagues[comp]['rounds']
        for round_no in range(clinch_round+1):
            points = dict.fromkeys(tally.teams,0);played = dict.fromkeys(tally.teams,0)
            for home,away,hg,ag,round_id in matches:
                if round_id>round_no:continue
                points[home]+=3 if hg>ag else 1 if hg==ag else 0
                points[away]+=3 if ag>hg else 1 if hg==ag else 0
                played[home]+=1;played[away]+=1
            if all(points[champion]>points[t]+3*(total_games[t]-played[t]) for t in tally.teams if t!=champion):
                clinch_round=round_no;break
        timing[tally.teams.index(champion),clinch_round]+=1
        candidate.add(world, world_index=index)
    check(timing.sum()==len(worlds)==10 and np.array_equal(timing,candidate.leagues[comp]['clinch']),
          'Race Room Timing:10 independent full-fixture points/max-remaining ledgers reproduce every champion/clinch round')
    routes=candidate.entry_routes[comp]
    routes.validate(candidate.europe_counts)
    broken_routes=copy.deepcopy(routes);broken_routes.counts[tally.teams[0]][0,0]+=1
    route_fault=False
    try:broken_routes.validate(candidate.europe_counts)
    except ValueError:route_fault=True
    check(route_fault and routes.worlds==10 and sum(int(v.sum()) for v in routes.counts.values())>0,
          'Race Room Routes:nonempty exclusive counts reconcile to independent entry totals;deliberate route-count fault rejected')
    tally.validate()
    candidate.entry_routes[comp].validate(candidate.europe_counts)
    check(len(worlds) == 10 and np.array_equal(expected, tally.gaps)
          and np.array_equal(tally.positions, candidate.leagues[comp]['pos']),
          'Race Room: all 10 smoke worlds agree with independent fixture-ledger rival gaps and final-position marginals')
    parts = [Accumulator(*init_args, **{**init_kwargs, 'race_competition': comp, 'route_competition': comp}) for _ in range(4)]
    for i, world in worlds.items():
        parts[i % 4].add(world, world_index=i)
    total = Accumulator(*init_args, **init_kwargs)
    for part in reversed(parts):
        total.merge(part)
    check(total.rivals[comp].payload() == tally.payload()
          and total.entry_routes[comp].payload(total.europe_counts) == candidate.entry_routes[comp].payload(candidate.europe_counts),
          'Race Room: reverse-arrival four-chunk Accumulator merge preserves rival and exclusive-route integer counts')
    corrupted = copy.deepcopy(tally)
    corrupted.gaps[0, 1, 0] += 1
    rejected = False
    try:
        corrupted.validate()
    except ValueError:
        rejected = True
    bad_order = False
    before = tally.payload()
    try:
        tally.add([1] * n)
    except ValueError:
        bad_order = True
    mismatched = False
    try:
        tally.merge(RivalTally(list(reversed(tally.teams))))
    except ValueError:
        mismatched = True
    check(rejected and bad_order and mismatched and tally.payload() == before,
          'Race Room: deliberate count fault, incomplete order and conflicting team order rejected without changing counts')
    # Independent tied scores with deliberately unsorted identities enforce a total order.
    ties = pd.DataFrame([dict(home='Zulu', away='Alpha', home_goals=0, away_goals=0)])
    positions = final_table(ties, pd.Index(['Zulu', 'Alpha']))['position']
    check(list(positions) == [2, 1], 'Race Room: exact points/GD/GF ties end in stable full team identity')


def check_player_data() -> None:
    """Semantic stats, result attribution and cutoff-safe transfers on small, specified games."""
    import copy
    import csv
    from scripts.fetch_fotmob import extract_players, PLAYER_FIELDS
    from scripts.player_stats import build_players
    from scripts.player_metrics import PLAYER_SCHEMA_VERSION
    from scripts.serve import Snapshots

    def player(pid, team_id, **values):
        return {"id": pid, "name": f"Player {pid}", "teamId": team_id,
                "teamName": "Untrusted alias", "stats": [{"stats": {
                    f"Display label {key}": {"key": key, "stat": {"value": value}}
                    for key, value in values.items()}}] if values else []}
    def shot(sid, pid, team_id, event="Miss", xg=0, xgot=0, **extras):
        return {"id": sid, "playerId": pid, "teamId": team_id, "eventType": event,
                "expectedGoals": xg, "expectedGoalsOnTarget": xgot,
                "situation": "RegularPlay", "period": "FirstHalf", "isOwnGoal": False,
                **extras}
    fixture = {"competition": "Test League", "season": 2026, "match_id": "1",
               "kickoff": "2026-09-01 15:00:00", "home": "Alpha", "away": "Beta",
               "home_id": 1, "away_id": 2, "finished": True}
    detail = {"general": {"finished": True}, "content": {"playerStats": {
        "11": player(11, 1, minutes_played=90, goals=2, assists=1,
                     expected_goals=.9, expected_goals_on_target_variant=1.1),
        "12": player(12, 1, minutes_played=45, goals=0, assists=0),
        "13": player(13, 2, minutes_played=90, goals=0, assists=0,
                     expected_goals=.1, expected_goals_on_target_variant=0),
        "14": player(14, 1), "15": player(15, 2, assists=None)}, "shotmap": {"shots": [
            shot(1, 11, 1, "Goal", .2, .3),
            shot(2, 11, 1, "Goal", .785, .8, situation="Penalty"),
            shot(2, 11, 1, "Goal", .785, .8, situation="Penalty"),  # repeated shot ID
            shot(3, 13, 2, "Miss", .1, 0),
            # Deliberately use the beneficiary's shot teamId: playerStats still owns the side.
            shot(4, 13, 1, "Goal", 0, 0, isOwnGoal=True),
            shot(5, 15, 2, "Goal", None, None),
            shot(6, 11, 1, "Goal", .785, .9, situation="Penalty", period="PenaltyShootout"),
            shot(7, 14, 1, "Goal", .785, .9, situation="Penalty", period="PenaltyShootout")]}}}
    rows = extract_players(fixture, detail)
    by_id = {r["player_id"]: r for r in rows}
    expected = {"11": ("Alpha", "home", 90, 2, 1, 1, 2, .9, 1.1, 0),
                "12": ("Alpha", "home", 45, 0, 0, 0, 0, 0, 0, 0),
                "13": ("Beta", "away", 90, 0, 0, 0, 1, .1, 0, 1),
                "15": ("Beta", "away", None, 1, 0, None, 1, None, None, 0)}
    fields = ("team", "side", "minutes", "goals", "pen_goals", "assists", "shots", "xg", "xgot", "own_goals")
    off = [f"{pid}: {tuple(by_id.get(pid, {}).get(k) for k in fields)}"
           for pid, values in expected.items()
           if tuple(by_id.get(pid, {}).get(k) for k in fields) != values]
    goals = sum(r["goals"] for r in rows if r["side"] == "home") + sum(r["own_goals"] for r in rows if r["side"] == "away")
    odd_home = player(16, 1, minutes_played=30, goals=1, expected_goals=.2)
    odd_away = player(17, 2, minutes_played=30, goals=0, expected_goals=.3)
    odd_home["id"] = 0; odd_away["id"] = 0
    odd = {"general": {"finished": True}, "content": {"playerStats": {"16": odd_home, "17": odd_away},
        "shotmap": {"shots": [shot(10, -1, 1, "Goal", .2, .3, playerName="Player 16"),
                                shot(11, -1, 2, "Miss", .3, 0, playerName="Player 17")]}}}
    odd_rows = {r["player_id"]: r for r in extract_players(fixture, odd)}
    odd_ok = (set(odd_rows) == {"16", "17"} and odd_rows["16"]["team"] == "Alpha"
              and odd_rows["17"]["team"] == "Beta" and odd_rows["16"]["goals"] == 1
              and odd_rows["17"]["goals"] == 0 and odd_rows["16"]["shots"] == odd_rows["17"]["shots"] == 1
              and odd_rows["16"]["xg"] == .2 and odd_rows["17"]["xg"] == .3)
    check(set(by_id) == set(expected) and not off and goals == 3 and odd_ok,
          "players: 4 appearances preserve goals/pens/own-benefit and semantic xG; 2 nested-zero/shared-negative IDs resolve by team/name; duplicate shots, shootout and bench excluded",
          "; ".join(off) or f"IDs {sorted(by_id)}, home goals {goals}")
    missing = copy.deepcopy(detail)
    del missing["content"]["shotmap"]
    missing_rows = {r["player_id"]: r for r in extract_players(fixture, missing)}
    empty = copy.deepcopy(missing); empty["content"]["shotmap"] = {"shots": []}
    empty_rows = {r["player_id"]: r for r in extract_players(fixture, empty)}
    missing_ok = (missing_rows == empty_rows and set(missing_rows) == set(expected)
                  and missing_rows["11"]["xg"] == .9 and missing_rows["11"]["goals"] == 2
                  and all(missing_rows["12"][k] is None for k in ("shots", "xg", "xgot", "pen_goals", "own_goals"))
                  and missing_rows["15"]["minutes"] is None
                  and extract_players({**fixture, "finished": False}, detail) == []
                  and extract_players(fixture, {**detail, "general": {"finished": False}}) == []
                  and extract_players(fixture, None) == [])
    check(missing_ok, "players: 2 missing/empty shot-map cases preserve explicit fallback stats and unknown minutes/metrics; 3 unfinished/missing-detail cases emit no appearances")

    def game(mid, home, away, kickoff="2026-09-02 23:59:00", comp="Test League", **extra):
        return {"competition": comp, "season": 2026, "match_id": mid, "home": home,
                "away": away, "kickoff": kickoff, "played": True, "tbd": False,
                "home_goals": 1, "away_goals": 0, **extra}
    master = pd.DataFrame([game("1", "Alpha", "Beta", fixture["kickoff"], home_goals=3, away_goals=1),
                           game("2", "Gamma", "Beta"), game("6", "Alpha", "Beta"),
                           game("3", "Alpha", "Gamma", "2026-09-03 00:00:00"),
                           game("4", "Alpha", "Beta", played=False),
                           game("5", "Alpha", "Beta", tbd=True),
                           game("1", "Past", "Other", season=2025),
                           game("1", "Delta", "Epsilon", comp="Test UEFA", home_goals=0)])
    sentinel = object(); master.attrs = {"sentinel": sentinel}
    def csv_row(mid, pid, side, comp="Test League", **metrics):
        return {"competition": comp, "season": 2026, "match_id": mid,
                "kickoff": "2099-01-01", "player_id": str(pid), "name": f"Player {pid}",
                "team": "Wrong club", "side": side, "minutes": 90, "goals": 0,
                "pen_goals": 0, "assists": 0, "shots": 0, "xg": 0, "xgot": 0,
                "own_goals": 0, "player_schema": PLAYER_SCHEMA_VERSION, **metrics}
    transfer = csv_row("2", 11, "home", minutes=60, goals=1, shots=2, xg=.4, xgot=.7)
    valid = [*rows, transfer, csv_row("2", 22, "away", shots=1, xg=.2),
             csv_row("1", 31, "home", comp="Test UEFA"), csv_row("1", 32, "away", comp="Test UEFA")]
    data = valid + [rows[0].copy(), {**rows[0], "xg": None},
                    csv_row("3", 11, "home", goals=99), csv_row("4", 11, "home", goals=99),
                    csv_row("5", 11, "home", goals=99), csv_row("1", 11, "other", goals=99),
                    {**csv_row("1", 11, "home", goals=99), "season": 2025}]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Test" / "test-2026.csv"; path.parent.mkdir()
        def write(records):
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=PLAYER_FIELDS)
                writer.writeheader(); writer.writerows(records)
        write(data)
        pooled = build_players(master, 2026, "2026-09-02", Path(tmp))
        write(list(reversed(data)))
        reordered = build_players(master, 2026, "2026-09-02", Path(tmp))
        league, uefa = pooled["competitions"]["Test League"], pooled["competitions"]["Test UEFA"]
        people = {p["id"]: p for p in league["players"]}
        transfer_row = people.get("11", {})
        canonical = all(set(p["teams"]) <= set(block["teams"]) and set(p["by_team"]) == set(p["teams"])
                        for block in pooled["competitions"].values() for p in block["players"])
        check(pooled == reordered and pooled["as_of"] == "2026-09-02" and canonical
              and league["coverage"]["played"] == 3 and league["coverage"]["covered"] == 2
              and league["coverage"]["missing"] == 1 and uefa["coverage"]["covered"] == 1
              and len(people) == 5 and master.attrs.get("sentinel") is sentinel,
              "players: 8 valid club appearances survive cutoff/season/competition/played/TBD guards and duplicate rows exactly once; aliases canonicalize, shuffled input is exact",
              str({c: b["coverage"] for c, b in pooled["competitions"].items()}))
        totals = {"matches": 2, "minutes": 150, "goals": 3, "pen_goals": 1,
                  "assists": 1, "shots": 4, "xg": 1.3, "xgot": 1.8}
        total_ok = all(abs(transfer_row.get(k, -999) - v) < 1e-8 for k, v in totals.items())
        clubs = transfer_row.get("by_team", {})
        club_ok = set(clubs) == {"Alpha", "Gamma"} and all(
            abs(sum(c[k] for c in clubs.values()) - v) < 1e-8 for k, v in totals.items())
        unknown = people.get("15", {})
        check(total_ok and club_ok and clubs["Alpha"]["goals"] == 2 and clubs["Gamma"]["goals"] == 1
              and unknown["minutes"] is None and unknown["known"]["minutes"] == 0
              and unknown["xg"] is None and unknown["known"]["xg"] == 0
              and league["teams"]["Alpha"]["goals"] is None and league["teams"]["Beta"]["own_goals_for"] is None
              and league["teams"]["Gamma"]["own_goals_for"] == 0,
              "players: transferred player totals equal both clubs' contributions across 8 metrics; unknown appearances and uncovered fixtures retain null totals/known counts")
        # Payload11 is a batch: its version cannot imply that this optional file already exists.
        root = Path(tmp) / "snapshots"; root.mkdir()
        index = []
        for day, as_of in (("2026-09-01", "2026-08-31"), ("2026-09-03", "2026-09-02")):
            folder = root / day; folder.mkdir(); index.append({"date": day})
            (folder / "projection.json").write_text(json.dumps({"version": 11, "as_of": as_of, "params": {"season": 2026}}))
        (root / "index.json").write_text(json.dumps(index))
        (root / "2026-09-03" / "players.json").write_text(json.dumps(pooled))
        snapshots = Snapshots(root)
        check(snapshots.players("2026-09-01") is None and snapshots.players("2026-09-03") == pooled
              and snapshots.players() == pooled and snapshots.players("1900-01-01") is None,
              "players: 2 v11 snapshots isolate the optional file by date; older missing fields never inherit newer aggregates")


def check_player_sources(master: pd.DataFrame, snapshot: dict | None = None,
                         report: dict | None = None) -> None:
    """CSV/extractor equality and semantic xG are exact; source conflicts stay explicit."""
    import csv
    from analysis.player_source_audit import audit_sources, number
    from scripts.fetch_fotmob import extract_players
    from scripts.player_stats import build_players, METRICS
    from scripts.player_metrics import ADDITIONAL_METRICS, METRIC_REGISTRY, PLAYER_SCHEMA_VERSION
    from scripts.serve import Snapshots
    live = Snapshots()
    snapshot = snapshot or live.load()
    report = report or live.players(snapshot["source"]["date"])
    if report is None:
        print("  skip    player source/aggregation checks (snapshot has no players.json)")
        return
    season, as_of = snapshot["params"]["season"], snapshot["as_of"]
    root = ROOT / "data/fotmob/players"
    by_match = {}; csv_errors = []; semantic_errors = []; typed_errors = []
    source_counts = {m: 0 for m in ADDITIONAL_METRICS}; typed_matches = typed_groups = 0
    for path in sorted(root.rglob(f"*-{season}.csv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                mid = row["match_id"].removesuffix(".0")
                by_match.setdefault((row["competition"], mid), []).append(row)
    def extracted(fixture, detail):
        nonlocal typed_matches, typed_groups
        key = (fixture["competition"], str(fixture["match_id"]))
        stored = by_match.get(key, [])
        fresh = extract_players(fixture, detail)
        fresh_by_id = {(str(r["player_id"]), r["side"]): r for r in fresh}
        content = detail.get("content") or {}
        raw_players = content.get("playerStats") or {}
        for row in fresh:
            raw = raw_players.get(str(row["player_id"]), {})
            semantic = {}
            for group in raw.get("stats") or []:
                entries = group.get("stats") or {}
                for entry in entries.values() if isinstance(entries, dict) else entries:
                    if isinstance(entry, dict) and entry.get("key") and isinstance(entry.get("stat"), dict):
                        semantic[entry["key"]] = entry["stat"]
            for metric in ADDITIONAL_METRICS:
                spec = METRIC_REGISTRY[metric]
                want = number(semantic.get(spec["source_key"], {}).get(spec["source_part"]))
                actual_value = row.get(metric)
                source_counts[metric] += want is not None
                if (want is None) != (actual_value is None) or want is not None and abs(want-actual_value)>1e-9:
                    semantic_errors.append(f"{key}/{row['player_id']}: {metric} != typed semantic source")
        typed_path = ROOT / "data/fotmob/semantic_stats" / (str(fixture["match_id"])+".json.gz")
        if typed_path.exists():
            typed = json.loads(gzip.decompress(typed_path.read_bytes())); typed_matches += 1
            expected = {str(pid): p.get("stats") for pid,p in raw_players.items() if isinstance(p,dict)}
            actual_stats = {pid:p.get("stats") for pid,p in typed.get("players",{}).items()}
            typed_groups += sum(len(p.get("stats") or []) for p in raw_players.values() if isinstance(p,dict))
            if actual_stats != expected or typed.get("team_stats") != content.get("stats"):
                typed_errors.append(f"{key}: original typed player/team groups differ")
        else:
            typed_errors.append(f"{key}: typed sidecar missing")
        actual = {}
        for raw in stored:
            row = {**raw, **{m: number(raw.get(m)) for m in (*METRICS, "own_goals", "stat_xg", "shot_xg")}}
            row["team"] = fixture.get(row["side"])
            identity = (str(row["player_id"]), row["side"])
            if identity in actual:
                csv_errors.append(f"{key}/{identity}: duplicate stored appearance")
            actual[identity] = row
        if set(actual) != set(fresh_by_id):
            csv_errors.append(f"{key}: stored and fresh participant IDs differ")
        for identity, row in actual.items():
            want = fresh_by_id.get(identity)
            if want is None:
                continue
            for metric in (*METRICS, "own_goals", "stat_xg", "shot_xg"):
                a, b = row.get(metric), want.get(metric)
                if (a is None) != (b is None) or a is not None and abs(a - b) > 1e-9:
                    csv_errors.append(f"{key}/{identity}: stored {metric} differs from cache extractor")
            if row.get("xg_source") != want.get("xg_source"):
                csv_errors.append(f"{key}/{identity}: source label differs")
        return list(actual.values())
    audit = audit_sources(master, season, as_of, extractor=extracted)
    feature = audit["feature"]
    check(feature["rows"] > 1000 and feature["semantic_values"] > 1000
          and not feature["errors"] and not csv_errors,
          f"players: {feature['rows']} cached CSV appearances equal fresh extraction; {feature['semantic_values']} xG values equal independent player-stat/no-shot sources, all clubs canonical",
          "; ".join((feature["errors"] + csv_errors)[:4]))
    check(len(source_counts)==45 and all(n>0 for n in source_counts.values()) and not semantic_errors
          and typed_matches==audit["matches"] and typed_groups>1000 and not typed_errors,
          f"players schema2: {sum(source_counts.values())} known values across all 45 added metrics equal typed sources; {typed_matches} complete match sidecars retain {typed_groups} player groups and every team period exactly",
          "; ".join((semantic_errors+typed_errors)[:4]) or str(source_counts))
    check(feature["goal_sides"] > 1000 and feature["goal_sides"] == audit["goals"].get("within", 0)
          and not audit["goals"].get("unreconciled", 0) and not any("goals" in e for e in feature["errors"]),
          f"players: exact player goals + benefiting own goals = GF on {feature['goal_sides']} covered match sides ({audit['own_goals']} own goals); {audit['goals'].get('unknown', 0)} uncovered sides stay unknown",
          "; ".join(feature["errors"][:3]))
    rebuilt = build_players(master, season, as_of, root)
    population = {}; attrs, master.attrs = master.attrs, {}
    try:
        for r in master.itertuples():
            if r.season == season and r.played and not r.tbd and str(r.kickoff)[:10] <= as_of:
                population.setdefault(r.competition, set()).update((r.home, r.away))
    finally:
        master.attrs = attrs
    accounting_ok = rebuilt == report and report["season"] == season and report["as_of"] == as_of
    players = transfer_values = observed_values = 0
    observed_ok = report.get("schema")==PLAYER_SCHEMA_VERSION and report.get("observed_policy")=="partial_only"
    for comp, block in report["competitions"].items():
        accounting_ok &= set(block["teams"]) <= population[comp]
        for p in block["players"]:
            players += 1
            clubs = p["by_team"]
            accounting_ok &= set(p["teams"]) == set(clubs) and set(clubs) <= population[comp]
            for metric in ("matches", *METRICS):
                values = [club[metric] for club in clubs.values()]
                expected = sum(values) if all(v is not None for v in values) else None
                actual = p[metric]
                if len(clubs) > 1:
                    transfer_values += 1
                accounting_ok &= ((expected is None) == (actual is None) and
                                  (actual is None or abs(expected - actual) <= .5e-8 * (len(clubs) + 1) + 1e-9))
            for metric in METRICS:
                accounting_ok &= 0 <= p["known"][metric] <= p["matches"] and ((p[metric] is not None) == (p["known"][metric] == p["matches"]))
                values=[c[metric] if c[metric] is not None else c.get("observed",{}).get(metric) for c in clubs.values()]
                values=[v for v in values if v is not None]
                want=sum(values) if values else None
                actual=p[metric] if p[metric] is not None else p.get("observed",{}).get(metric)
                observed_values+=actual is not None
                observed_ok &= ((want is None)==(actual is None) and (actual is None or abs(want-actual)<=1e-7))
                observed_ok &= (metric in p.get("observed",{})) == (0 < p["known"][metric] < p["matches"])
            for club, contribution in clubs.items():
                for metric in METRICS:
                    observed_ok &= (metric in contribution.get("observed",{})) == (0 < contribution["known"][metric] < contribution["matches"])
        for team, totals in block["teams"].items():
            parts=[p["by_team"][team] for p in block["players"] if team in p["by_team"]]
            observed_ok &= totals["appearances"]==sum(p["matches"] for p in parts)
            for metric in METRICS:
                known=sum(p["known"][metric] for p in parts)
                values=[p[metric] if p[metric] is not None else p.get("observed",{}).get(metric) for p in parts]
                values=[v for v in values if v is not None]
                want=sum(values) if values else None
                actual=totals[metric] if totals[metric] is not None else totals.get("observed",{}).get(metric)
                observed_ok &= known==totals["known_appearances"][metric] and ((want is None)==(actual is None))
                observed_ok &= actual is None or abs(want-actual)<=1e-6
                observed_ok &= (metric in totals.get("observed",{})) == (totals[metric] is None and known>0)
    for comp, comparison in audit["by_competition"].items():
        coverage = report["competitions"][comp]["coverage"]
        for source, metric in (("player_xg", "xg_accounting"), ("shot_xg", "shot_xg_accounting")):
            expected = comparison[source]; actual = coverage[metric]
            accounting_ok &= (actual["within_rounding"] == expected.get("within", 0)
                              and actual["outside_rounding"] == expected.get("unreconciled", 0)
                              and actual["unknown"] == expected.get("unknown", 0))
    for source in ("player_xg", "shot_xg"):
        counts = audit[source]
        accounting_ok &= sum(counts.values()) == 2 * audit["matches"] and len(audit["exceptions"][source]) == counts.get("unreconciled", 0)
    check(players > 0 and accounting_ok and audit["player_xg"].get("within", 0) > 0,
          f"players: {players} competition/player totals equal cutoff CSVs, with {transfer_values} transfer-contribution values; xG source accounting partitions all {2 * audit['matches']} match sides",
          f"rebuilt equality {rebuilt == report}; grouped {audit['player_xg']}; shots {audit['shot_xg']}")
    check(players>1000 and observed_values>1000 and observed_ok,
          f"players schema2: {observed_values} known/partial player totals across 52 metrics equal club contributions; team totals and known appearances equal all club rows; complete/all-unknown totals never duplicate partial sums")
    print(f"  note    player-stat xG/team source: {audit['player_xg'].get('within', 0)} within per-player rounding, {audit['player_xg'].get('unreconciled', 0)} cached contradictions, {audit['player_xg'].get('unknown', 0)} unknown; raw shots: {audit['shot_xg']}")
    print(f"  note    missing player-shot coverage: {audit['missing']}")


def check_players_http(base: str, snapshots, day: str) -> None:
    import urllib.error
    import urllib.request
    report = snapshots.players(day)
    if report is None:
        print("  skip    player HTTP equality (snapshot has no players.json)")
        return
    url = base + "/api/players?date=" + day
    with urllib.request.urlopen(url) as response:
        raw, encoding = response.read(), response.headers.get("Content-Encoding")
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request) as response:
        compressed, zipped, vary = response.read(), response.headers.get("Content-Encoding"), response.headers.get("Vary", "")
        content_type = response.headers.get_content_type()
    missing = next((d["date"] for d in snapshots.list() if snapshots.players(d["date"]) is None), None)
    missing_ok = True
    if missing:
        try:
            urllib.request.urlopen(base + "/api/players?date=" + missing)
            missing_ok = False
        except urllib.error.HTTPError as error:
            missing_ok = error.code == 404
    check(json.loads(raw) == report and not encoding and zipped == "gzip"
          and json.loads(gzip.decompress(compressed)) == report and content_type == "application/json"
          and "Accept-Encoding" in vary and len(compressed) < len(raw) and missing_ok
          and json.load(urllib.request.urlopen(base + "/api/meta"))["model_loaded"] is False,
          f"players: HTTP plain/gzip equal the file ({sum(len(b['players']) for b in report['competitions'].values())} competition/player rows, {len(raw)}→{len(compressed)} bytes); older missing file is404, model stays unloaded")


def check_player_schema() -> None:
    """Typed semantic fractions, missing values and partial sums are separate contracts."""
    import csv
    from scripts.fetch_fotmob import extract_players, semantic_stats_payload
    from scripts.player_metrics import PLAYER_FIELDS, PLAYER_SCHEMA_VERSION, METRICS
    from scripts.player_stats import build_players, validate_player_inputs
    fixture = {"competition":"Test", "season":2026, "match_id":"1", "home":"A", "away":"B",
               "home_id":1, "away_id":2, "finished":True, "kickoff":"2026-09-01"}
    stats = {"minutes":{"key":"minutes_played","stat":{"value":90}},
             "xa":{"key":"expected_assists","stat":{"value":.25,"type":"double"}},
             "assists":{"key":"assists","stat":{"value":1}},
             "passing":{"key":"accurate_passes","stat":{"value":24,"total":30,"type":"fraction"}},
             "duels":{"key":"aerials_won","stat":{"value":0,"total":4}},
             "keeper":{"key":"goals_prevented","stat":{"value":-.35}},
             "missing":{"key":"saves","stat":{"value":None}},
             "invalid":{"key":"touches","stat":{"value":"NaN"}},
             "boolean":{"key":"recoveries","stat":{"value":True}},
             "percent":{"key":"unregistered_percentage","stat":{"value":80,"type":"percent"}},
             "unknown":{"key":None,"stat":{"value":"display only"}}}
    content = {"playerStats":{"11":{"id":11,"name":"One","teamId":1,"stats":[{"stats":stats}]}},
               "stats":{"Periods":{"All":{"stats":[{"key":"new_team_field","value":[1,2]}]}}}}
    detail = {"general":{"finished":True},"content":content}
    rows = extract_players(fixture, detail)
    expected = {"xa":.25,"assists":1,"passes_completed":24,"passes_attempted":30,
                "aerial_duels_won":0,"aerial_duels_total":4,"goals_prevented":-.35,
                "saves":None,"touches":None,"recoveries":None,"chances_created":None}
    typed = semantic_stats_payload("1", detail)
    check(len(METRICS) == 52 and len(rows) == 1 and rows[0]["player_schema"] == PLAYER_SCHEMA_VERSION
          and all(rows[0].get(k) == v for k,v in expected.items())
          and "unregistered_percentage" not in rows[0] and typed["players"]["11"]["stats"] == content["playerStats"]["11"]["stats"]
          and typed["team_stats"] == content["stats"],
          "players schema2: 11 specified xA/assist/fraction/negative/zero/unknown scalars preserve typed source groups and new/null keys; non-additive values never become totals")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); path = root/"test-2026.csv"
        second = {**rows[0],"match_id":"2","side":"away","xa":None,"assists":None}
        third = {**rows[0],"match_id":"3","xa":.5,"assists":2}
        def write(records):
            with path.open("w",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=PLAYER_FIELDS);writer.writeheader();writer.writerows(records)
        write([rows[0],second,third])
        master = pd.DataFrame([{**fixture,"home":"A","away":"B","played":True,"tbd":False,"home_goals":0,"away_goals":0},
            {**fixture,"match_id":"2","home":"A","away":"C","kickoff":"2026-09-02","played":True,"tbd":False,"home_goals":0,"away_goals":0},
            {**fixture,"match_id":"3","home":"A","away":"B","kickoff":"2026-09-03","played":True,"tbd":False,"home_goals":0,"away_goals":0}])
        pooled = build_players(master,2026,"2026-09-03",root)["competitions"]["Test"]
        p = pooled["players"][0]; a,c = p["by_team"]["A"],p["by_team"]["C"]
        check(p["matches"]==3 and p["xa"] is None and p["known"]["xa"]==2 and p["observed"]["xa"]==.75
              and a["xa"]==.75 and "xa" not in a["observed"] and a["known"]["xa"]==2
              and c["xa"] is None and "xa" not in c["observed"] and c["known"]["xa"]==0
              and pooled["teams"]["A"]["xa"] is None and pooled["teams"]["A"]["observed"]["xa"]==.75
              and pooled["teams"]["A"]["known"]["xa"]==2 and pooled["teams"]["A"]["known_appearances"]["xa"]==2
              and pooled["teams"]["A"]["appearances"]==2,
              "players schema2: 3 transferred appearances keep strict null, 0.75 observed xA and 2 known appearances distinct; team coverage counts complete games separately")
        errors=[]
        for corrupt in ({**rows[0],"player_schema":1}, {k:v for k,v in rows[0].items() if k!="player_schema"}):
            write([corrupt])
            try: validate_player_inputs(root,2026,master)
            except ValueError as e: errors.append(str(e))
        path.write_text("competition,season,match_id\nTest,2026,1\n")
        try: validate_player_inputs(root,2026,master)
        except ValueError as e: errors.append(str(e))
        check(len(errors)==3 and all("--players-only" in e and "schema 2" in e for e in errors),
              "players schema2: 3 stale header/row-marker cases reject with the cache-only rebuild command")


def check_fetch_storage() -> None:
    """Recover complete new source fields without another request or unsafe cache deletion."""
    import contextlib
    import hashlib
    import io
    from datetime import datetime
    from unittest.mock import patch, Mock
    from scripts import fetch_fotmob, ops_storage
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);cache=root/"matches";cache.mkdir();archives=root/"archives"
        with patch.object(fetch_fotmob,"DATA_DIR",root),patch.object(fetch_fotmob,"CACHE_DIR",cache),patch.object(ops_storage,"DEFAULT_ARCHIVE_ROOT",archives):
            data={"future":{"typed":[{"unit":"percent","value":81.2,"total":90},None],"new_key":{"text":"été"}},"matches":[1,2]}
            network=Mock(side_effect=AssertionError("retention must not request"))
            with patch.object(fetch_fotmob,"fetch_json",network):
                a=fetch_fotmob.retain_league_response("https://example.invalid/league?season=2026",data,2026)
                b=fetch_fotmob.retain_league_response("https://example.invalid/league?season=2027",data,2027)
            store=root/"league_responses";raw=gzip.decompress((store/a["file"]).read_bytes())
            observations=[json.loads(line) for line in (store/"observations.jsonl").read_text().splitlines()]
            source_ok=(not network.called and json.loads(raw)==data and a["sha256"]==hashlib.sha256(raw).hexdigest()
                  and a["file"]==b["file"] and len(list(store.glob("*.json.gz")))==1 and observations==[a,b]
                  and a["season"]==2026 and b["season"]==2027 and a["source_url"]!=b["source_url"]
                  and a["representation"]=="canonical_json" and a["decoded_bytes"]==len(raw)
                  and datetime.fromisoformat(a["observed_at"]).utcoffset().total_seconds()==0)
            statuses=[];gates_ok=True
            for fixtures_only in (False,True):
                for case in ("failed","empty","mixed"):
                    failed="English FA Cup";empty="Spanish Copa del Rey"
                    names=[failed] if case=="failed" else [empty] if case=="empty" else [failed,empty]
                    def enumerate_mock(name,*unused):
                        if name==failed:raise RuntimeError("injected enumeration failure")
                        return [] if case=="empty" else [{"competition":empty,"finished":False}]
                    fixture_writer=Mock(return_value=[]);player_writer=Mock();detail=Mock(side_effect=AssertionError("failed/empty source must not fetch detail"))
                    argv=["--season","2026",*(v for name in names for v in ("--competition",name)),*(["--fixtures-only"] if fixtures_only else [])]
                    output=io.StringIO()
                    with patch.object(fetch_fotmob,"list_fixtures",enumerate_mock),patch.object(fetch_fotmob,"write_competition_csvs",fixture_writer),patch.object(fetch_fotmob,"write_player_csv",player_writer),patch.object(fetch_fotmob,"fetch_match_detail",detail),contextlib.redirect_stdout(output):
                        status=fetch_fotmob.main(argv)
                    statuses.append(status)
                    gates_ok &= not detail.called
                    if case!="empty":gates_ok &= not fixture_writer.called and not player_writer.called and "FAILED" in output.getvalue()
            check(source_ok and gates_ok and statuses==[1,0,1,1,0,1],
                  "fetch retention/status:2 source observations share1 complete typed response;6 normal/fixtures-only cases return1 before any write/detail on failed or mixed enumeration, while valid empty cups return0",
                  f"source identity {source_ok}, safe gates {gates_ok}, return codes {statuses}")
            raw=b'{ "unchanged bytes": [1, 2] }\n'
            for mid in ("same","different","corrupt"):(cache/(mid+".json")).write_bytes(raw)
            same=gzip.compress(raw);different=gzip.compress(b'{"other":true}');corrupt=b"not gzip"
            for mid,body in (("same",same),("different",different),("corrupt",corrupt)):(cache/(mid+".json.gz")).write_bytes(body)
            output=io.StringIO()
            with contextlib.redirect_stdout(output):fetch_fotmob.compact_cache()
            archive_bytes=[p.read_bytes() for p in archives.rglob("*") if p.is_file()]
            check(not (cache/"same.json").exists() and gzip.decompress((cache/"same.json.gz").read_bytes())==raw and raw in archive_bytes
                  and all((cache/(mid+".json")).read_bytes()==raw for mid in ("different","corrupt"))
                  and (cache/"different.json.gz").read_bytes()==different and (cache/"corrupt.json.gz").read_bytes()==corrupt
                  and "2 plain files retained" in output.getvalue(),
                  "fetch compaction:1 byte-identical gzip permits archived plain removal;2 different/corrupt existing gzip files preserve both originals and report exceptions")


def check_fixture_ingestion() -> None:
    """Explicit phase names and result reasons survive missing match-detail statistics."""
    import csv
    from unittest.mock import patch
    from scripts import fetch_fotmob
    rounds=[({"round":1},1),({"round":"8"},"8"),
        ({"round":"League Stage - Round 1"},1),({"round":"League Phase - Round 8"},8),
        ({"round":"Group Stage - Round 6"},6),({"round":"League phase","roundName":2},2),
        ({"round":None,"roundName":"League Stage - Round 3"},3),
        *[({"round":f"{n}{suffix} Qualifying Round","roundName":n},f"{n}{suffix} Qualifying Round") for n,suffix in [(1,"st"),(2,"nd"),(3,"rd")]],
        ({"round":"Play-offs","roundName":"Play-offs"},"Play-offs"),({"round":"1/4","roundName":1},"1/4"),
        ({"round":"Round of 16","roundName":1},"Round of 16"),({"round":None,"roundName":1},None),
        ({"round":"1st Qualifying Round","roundName":"League Stage - Round 1"},"1st Qualifying Round")]
    base={"competition":"UEFA Champions League","season":2026,"match_id":"test","round":1,
          "utc_time":"2026-09-01T19:00:00Z","home":"Alpha","away":"Beta","home_id":1,"away_id":2,"score":"2 - 1","finished":True}
    def fixture(reason,**kw):
        return {**base,"status":{"reason":{"shortKey":reason}},**kw}
    cases=[(fixture("fulltime_short"),None,"fulltime",False),
           (fixture("fulltime_short"),{"error":True},"fulltime",False),
           (fixture("afterextratime_short"),None,"afterextratime",True),
           (fixture("afterextratime_short",status={"reason":{"shortKey":"afterextratime_short"},"halfs":{"firstExtraHalfStarted":False}}),None,"afterextratime",True),
           (fixture("penalties_short"),None,"penalties",None),
           (fixture("aborted_short",finished=False),None,"aborted",None),
           ({**base,"status":{}},None,None,None),
           (fixture("fulltime_short",finished=False),None,None,None),
           (fixture("fulltime_short",score=None),None,None,None),
           (fixture("fulltime_short"),{"header":{"status":{"reason":{"shortKey":"afterextratime_short"}}}},"afterextratime",True),
           (fixture("penalties_short",status={"reason":{"shortKey":"penalties_short"},"halfs":{"firstExtraHalfStarted":False}}),None,"penalties",False)]
    good=all(fetch_fotmob.fixture_round(raw)==want for raw,want in rounds)
    fixtures=[];stats={}
    for i,(f,detail,outcome,extra) in enumerate(cases):
        f={**f,"match_id":str(i)};fixtures.append(f);row=fetch_fotmob.extract_stats(f,detail);stats[str(i)]=row
        good &= row["outcome"]==outcome and row["went_to_extra_time"] is extra
        good &= all(row[side+"_xg"] is None for side in ("home","away"))
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(fetch_fotmob,"DATA_DIR",Path(tmp)):
            paths=fetch_fotmob.write_competition_csvs(2026,fixtures,stats)
            stored=list(csv.DictReader(paths[0].open()))
            for row,case in zip(stored,cases):
                good &= row["outcome"]==(case[2] or "") and row["Result"]==(case[0]["score"] or "") if case[0]["finished"] else row["outcome"]==(case[2] or "") and row["Result"]==""
                good &= row["home_xg"]==row["away_xg"]==""
            # Fixtures-only has no detail map, but the explicit source reason still owns the result.
            fresh={**fixtures[0],"competition":"UEFA Europa League"}
            path=fetch_fotmob.write_competition_csvs(2026,[fresh],{})[0]
            fallback=next(csv.DictReader(path.open()))
            good &= fallback["outcome"]=="fulltime" and fallback["Result"]=="2 - 1" and fallback["home_xg"]==""
    check(good,f"fixture ingestion: {len(rounds)} phase/qualifier/KO/missing round cases and {len(cases)} result-reason cases preserve explicit rounds, detail priority, ET/pens/aborted/unknown and null xG in full/fixtures-only CSV output")

    cache=ROOT/"data/fotmob/league_responses/b04af26f65ab892503a3c733104c4987b15d37fa9367aad83968b716a18764e9.json.gz"
    if not cache.exists():
        print("  skip    cached 234-row explicit UCL phase/qualifying regression fixture (retained league response absent)")
        return
    raw=json.loads(gzip.decompress(cache.read_bytes()));matches=raw["fixtures"]["allMatches"]
    with patch.object(fetch_fotmob,"resolve_season",return_value="2026/2027"),patch.object(fetch_fotmob,"fetch_json",return_value=raw),patch.object(fetch_fotmob,"retain_league_response"):
        rows=fetch_fotmob.list_fixtures("UEFA Champions League",42,2026)
    good=len(rows)==len(matches)==234;phase=qualifying=played=missing_xg=0;stats={}
    for source,f in zip(matches,rows):
        label=source.get("round")
        if str(label).startswith("League Stage - Round "):
            phase+=1;good &= f["round"]==int(label.rsplit(" ",1)[1])
        else:
            qualifying+=1;good &= f["round"]==label
        good &= f["status"]==source.get("status")
        if f["finished"]:
            record=fetch_fotmob.extract_stats(f,fetch_fotmob.read_cached(str(f["match_id"])));stats[f["match_id"]]=record
            played+=record["outcome"] in {"fulltime","afterextratime","penalties"}
            missing_xg+=record["home_xg"] is None and record["away_xg"] is None
    example=stats.get("1000022646",{})
    good &= example.get("outcome")=="fulltime" and example.get("home_goals")==1 and example.get("away_goals")==0 and example.get("home_xg") is None
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(fetch_fotmob,"DATA_DIR",Path(tmp)):
            path=fetch_fotmob.write_competition_csvs(2026,rows,stats)[0];stored=list(csv.DictReader(path.open()))
            good &= sum(row["Round Number"].isdigit() for row in stored)==144
            good &= sum(row["outcome"] in {"fulltime","afterextratime","penalties"} for row in stored)==144
    check(good and phase==144 and qualifying==90 and played==144 and missing_xg>0,
          f"fixture ingestion cache: all 234 source rows retain 144 numbered phase /90 qualifying labels; all {played} explicit finished results stay played, with {missing_xg} absent-xG results left unknown")


def check_source_refresh() -> None:
    """Forced provider reads retain revisions; ordinary runs cannot clobber forecast dates."""
    import argparse,contextlib,io,hashlib
    from unittest.mock import patch,Mock
    from scripts import fetch_fotmob as fotmob,fetch_opta as opta,fetch_clubelo as elo,nightly,ops_storage
    from scripts.source_retention import retain_response
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);archives=root/'archives';cache=root/'fotmob/matches'
        old={'general':{'matchId':'7'},'header':{'id':7},'unrecognised':{'value':17}}
        new={**old,'unrecognised':{'value':23},'new_provider_field':[1,{'x':2}]}
        with patch.object(ops_storage,'DEFAULT_ARCHIVE_ROOT',archives),patch.object(fotmob,'DATA_DIR',root/'fotmob'),patch.object(fotmob,'CACHE_DIR',cache),patch.object(fotmob,'fetch_json',return_value=old) as network:
            a=fotmob.fetch_match_detail('7');b=fotmob.fetch_match_detail('7')
            assert a==b==old and network.call_count==1
            network.return_value=new
            c=fotmob.fetch_match_detail('7',refresh=True)
            assert c==new and network.call_count==2 and fotmob.read_cached('7')==new
            retained=[json.loads(gzip.decompress(p.read_bytes())) for p in (root/'fotmob/match_responses').glob('*.gz')]
            assert old in retained and new in retained and len(retained)==2
            before=(cache/'7.json.gz').read_bytes();network.side_effect=OSError('deliberate failed refresh')
            try:fotmob.fetch_match_detail('7',refresh=True)
            except OSError:pass
            else:raise AssertionError('source failure accepted')
            assert (cache/'7.json.gz').read_bytes()==before
        check(True,'source refresh: normal match reads reuse cache; forced read makes a request, retains2 exact complete revisions, and a failed refresh preserves current evidence')
        with patch.object(ops_storage,'DEFAULT_ARCHIVE_ROOT',archives):
            for n in (90,91):
                bundle=json.dumps({'rank':1,'contestantId':'one','contestantName':'Alpha','currentRating':n,'lastWeekRating':89,'newRawField':[n]},separators=(',',':'))
                with patch.object(opta,'SNAPSHOT_DIR',root/'opta'),patch.object(opta,'OUT_FILE',root/'opta-current.csv'),patch.object(opta,'fetch_text',return_value=bundle),contextlib.redirect_stdout(io.StringIO()):opta.main()
            bodies=[gzip.decompress(p.read_bytes()).decode() for p in (root/'opta/responses').glob('*.gz')]
            assert len(bodies)==2 and all('newRawField' in b for b in bodies)
            observations=[json.loads(x) for x in (root/'opta/responses/observations.jsonl').read_text().splitlines()]
            assert len(observations)==2 and observations[0]['sha256']!=observations[1]['sha256']
            assert any(p.name.endswith('.csv') for p in archives.rglob('*'))
            # Corrupt retained bytes must never pass as the response identified by their filename.
            bad=root/'fault';r=retain_response(bad,'test:source',b'valid');(bad/r['file']).write_bytes(gzip.compress(b'wrong'))
            try:retain_response(bad,'test:source',b'valid')
            except ValueError:pass
            else:raise AssertionError('deliberate provider hash fault escaped')
        check(True,'rating retention:2 same-day Opta revisions preserve the full feed and retrieval hashes, archive replaced CSVs; deliberately corrupted response is rejected')
        from unittest.mock import MagicMock
        with patch.object(ops_storage,'DEFAULT_ARCHIVE_ROOT',archives),patch.object(elo,'OUT_FILE',root/'elo.csv'):
            for value in (1500,1510):
                response=MagicMock();response.__enter__.return_value.read.return_value=f'date,club,country,elo\n2026-08-01,Alpha,ENG,{value}\n'.encode()
                with patch.object(elo,'urlopen',return_value=response),contextlib.redirect_stdout(io.StringIO()):elo.main()
            assert len(list((root/'elo_responses').glob('*.gz')))==2
            previous=(root/'elo.csv').read_bytes();response.__enter__.return_value.read.return_value=b'date,club,country,elo\n2026-08-01,Alpha,ENG,NaN\n'
            with patch.object(elo,'urlopen',return_value=response):
                try:elo.main()
                except RuntimeError:pass
                else:raise AssertionError('Nonfinite Elo observation published')
            assert (root/'elo.csv').read_bytes()==previous and len(list((root/'elo_responses').glob('*.gz')))==3
        check(True,'Elo refresh:2 full history revisions retained; a deliberately nonfinite third response is retained as evidence and cannot replace usable ratings')

        snap=root/'snapshots';(snap/'2026-08-03').mkdir(parents=True);(snap/'2026-08-01').mkdir()
        for day in ('01','03'):(snap/('2026-08-'+day)/'projection.json').write_text(json.dumps({'params':{'season':2026},'as_of':'2026-08-'+day,'worlds':1}))
        original=(snap/'2026-08-03/projection.json').read_bytes();(snap/'2026-08-03/pipeline.log').write_text('keep report')
        args=argparse.Namespace(date='2026-08-03',only=None,skip=None,dry_run=False,season=2026,max_catch_up=0,keep=180,as_of=None,worlds=1,seed=1,processes=1)
        def catch_up(run):
            assert nightly.missing_days(0,run.day)==['2026-08-02']
            d=snap/'2026-08-02';d.mkdir();(d/'projection.json').write_text('{}');run.record('catch_up','ok','one missing date')
        with patch.multiple(nightly,ROOT=root,SNAP_DIR=snap,ARCHIVE_ROOT=archives),patch.object(nightly,'PIPELINE',[('catch_up',catch_up),('project',nightly.step_project)]),patch.object(nightly,'Engine',side_effect=AssertionError('existing projection must not simulate')),contextlib.redirect_stdout(io.StringIO()):
            assert nightly.run_nightly(args)==0
            assert (snap/'2026-08-03/projection.json').read_bytes()==original and (snap/'2026-08-03/pipeline.log').read_text()=='keep report'
            with patch.object(nightly,'PIPELINE',[('unexpected',lambda run:(_ for _ in ()).throw(AssertionError('existing day rerun'))) ]):assert nightly.run_nightly(args)==0
        check(True,'normal nightly: fills an interior missing date, skips existing projection before model work, preserves its report; repeated complete history is a no-op')
        # Explicit source failures stop a brute-force run before any projection can publish.
        args.date='2026-08-04';args.overwrite_snapshot=True;args.require_fresh_sources=True
        calls=[]
        def fail(run):run.record('fotmob','failed','deliberate source fault')
        with patch.multiple(nightly,ROOT=root,SNAP_DIR=snap,ARCHIVE_ROOT=archives),patch.object(nightly,'PIPELINE',[('fotmob',fail),('project',lambda r:calls.append('published'))]),contextlib.redirect_stdout(io.StringIO()):
            assert nightly.run_nightly(args)==1 and calls==[]
        check(True,'brute-force source failure: deliberately failed collection returns1 and stops before projection/publication')


def check_nightly_backfill() -> None:
    """Backfill repeats the shared normal job for stored metadata; no live phase runs here."""
    import argparse
    import contextlib
    import io
    from datetime import date
    from unittest.mock import patch, Mock
    from scripts import nightly, ops_storage

    class Today(date):
        @classmethod
        def today(cls): return cls(2026, 9, 7)

    def tree(root):
        return {str(p.relative_to(root)):(p.is_dir(),None if p.is_dir() else p.read_bytes(),p.stat().st_mtime_ns)
                for p in root.rglob("*")}

    def args():
        return argparse.Namespace(backfill=True,date="2026-09-07",worlds=17,seed=23,processes=4,
            dry_run=False,season=None,as_of=None,only=None,skip=None,refresh_players=False,
            keep=180,max_catch_up=14,stored_only=True,backfill_start=None)

    # Independently read the real folder metadata, without assuming an index entry or filling gaps.
    stored=[]
    for folder in nightly.SNAP_DIR.iterdir():
        try:
            if date.fromisoformat(folder.name).isoformat()!=folder.name or folder.name>date.today().isoformat():continue
            payload=json.loads((folder/"projection.json").read_text())
            stored.append((folder.name,payload["as_of"],int(payload["params"]["season"])))
        except (ValueError,OSError,KeyError,TypeError):continue
    stored.sort();actual=nightly.backfill_plan()
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);snap=root/"data/snapshots";snap.mkdir(parents=True);archives=root/"archives"
        (root/"data/master.csv").write_text("original master bytes\n")
        expected=[("2026-09-01","2026-08-30",2025),("2026-09-03","2026-09-02",2025),("2026-09-05","2026-09-04",2026)]
        for day,cutoff,season in expected:
            folder=snap/day;folder.mkdir()
            (folder/"projection.json").write_text(json.dumps({"params":{"season":season},"as_of":cutoff,"worlds":1}))
        (snap/"index.json").write_text("[]")
        invalid=snap/".snapshot-stage-ignore";invalid.mkdir();(invalid/"projection.json").write_text('{}')
        with patch.multiple(nightly,ROOT=root,SNAP_DIR=snap,ARCHIVE_ROOT=archives,date=Today),patch.object(ops_storage,"DEFAULT_ARCHIVE_ROOT",archives):
            before=tree(root)
            check(len(stored)>0 and actual==stored and nightly.backfill_plan()==expected
                  and nightly.backfill_plan("2026-09-07")==expected and nightly.backfill_plan("2026-09-04")==expected[:2] and tree(root)==before,
                  f"backfill plan: all {len(stored)} real stored date/cutoff/season records equal disk; 3 synthetic records stay exact across 2 seasons, ignoring gaps/new dates/stale index/staging folders")
            extended=nightly.backfill_plan("2026-09-07",start="2026-08-01")
            expected_days=[date.fromordinal(day).isoformat() for day in range(date(2026,8,1).toordinal(),date(2026,9,7).toordinal()+1)]
            recorded={day:(day,cutoff,season) for day,cutoff,season in expected}
            check(len(extended)==38 and [r[0] for r in extended]==expected_days
                  and all(r==recorded[r[0]] if r[0] in recorded else r[1]==r[0] for r in extended)
                  and extended[0]==('2026-08-01','2026-08-01',2025) and tree(root)==before,
                  "backfill calendar extension: all38 exact dates from1Aug through7Sep, no holes/duplicates,3 stored season/cutoff records preserved, new dates use their own cutoff; read-only")
            broken=extended[1:]
            check([r[0] for r in broken]!=expected_days,"backfill extension fault: removing1Aug is independently detected")
            invalid_cases=0
            for end in ("not-a-date","2026-08-31","2026-09-08"):
                try:nightly.backfill_plan(end)
                except ValueError:invalid_cases+=1
            empty=root/"empty";empty.mkdir()
            with patch.object(nightly,"SNAP_DIR",empty):
                try:nightly.backfill_plan("2026-09-07")
                except ValueError:invalid_cases+=1
            projection=snap/"2026-09-03/projection.json";previous=projection.read_bytes()
            for cutoff in ("invalid","2026-09-04"):
                projection.write_text(json.dumps({"params":{"season":2025},"worlds":1,"as_of":cutoff}))
                try:nightly.backfill_plan("2026-09-07")
                except ValueError:invalid_cases+=1
            projection.write_bytes(previous)
            check(invalid_cases==6,"backfill plan: 6 malformed/future/before-history end and empty-history/invalid-recorded-cutoff cases reject before publication")

            process=Mock(side_effect=AssertionError("backfill must use the shared runner, never subprocess orchestration"))
            archive=Mock(side_effect=AssertionError("dry-run must not archive"));engine=Mock(side_effect=AssertionError("mocked phases must not load model"))
            before=tree(root);output=io.StringIO()
            with patch.object(nightly.subprocess,"run",process),patch.object(nightly,"archive_paths",archive),patch.object(nightly,"Engine",engine),patch.object(nightly,"run_nightly",side_effect=AssertionError("dry-run must not run phases")),patch.object(sys,"argv",["nightly.py","--backfill","--stored-only","--date","2026-09-07","--dry-run"]),contextlib.redirect_stdout(output):
                dry_rc=nightly.main()
            check(dry_rc==0 and not process.called and not archive.called and not engine.called and tree(root)==before
                  and all(day in output.getvalue() for day,cutoff,season in expected) and "2026-09-06" not in output.getvalue(),
                  "backfill dry-run: actual CLI lists only 3 stored records and changes no file/directory/mtime, archive, persistent log, subprocess, shared runner or model")
            output=io.StringIO()
            with patch.object(nightly,"archive_paths",archive),patch.object(nightly,"Engine",engine),patch.object(nightly,"run_nightly",side_effect=AssertionError("calendar dry-run must not execute")),patch.object(sys,"argv",["nightly.py","--backfill","--date","2026-09-07","--dry-run"]),contextlib.redirect_stdout(output):
                calendar_rc=nightly.main()
            listing=output.getvalue()
            check(calendar_rc==0 and "38 calendar dates: 2026-08-01 to 2026-09-07" in listing
                  and all(day in listing for day in expected_days) and tree(root)==before
                  and not archive.called and not engine.called,
                  "backfill default CLI: starts1August, lists all38 days including missing dates, and executes no archive/model/job/filesystem writes")
            conflicts=0;before=tree(root)
            with patch.object(nightly,"run_backfill",side_effect=AssertionError("invalid flags must not reach driver")):
                for flags in (["--as-of","2026-09-01"],["--only","project"],["--skip","prune"],["--refresh-players"],["--season","2026"],["--worlds","0"],["--worlds","2000001"],["--processes","0"]):
                    with patch.object(sys,"argv",["nightly.py","--backfill","--date","2026-09-07",*flags]),contextlib.redirect_stderr(io.StringIO()):
                        try:nightly.main()
                        except SystemExit as error:conflicts+=error.code==2
            check(conflicts==8 and tree(root)==before,
                  "backfill CLI: 5 conflicting rewind/selection/player-refresh/season flags and 3 invalid world/process bounds reject before driver or filesystem changes")

            phases=[name for name,_ in nightly.PIPELINE];events=[];order=[];archives_seen=[];real_archive=nightly.archive_paths
            def capture_archive(paths,*pos,**kw):
                order.append("archive");result=real_archive(paths,*pos,**kw);archives_seen.append(result);return result
            def pipeline(fail_day=None):
                def phase(name):
                    def execute(run):
                        order.append("phase");a=run.args
                        events.append((run.day,a.as_of,a.season,name,a.only,a.skip,a.worlds,a.seed,a.processes))
                        print(f"PHASEMARK {run.day} {name}")
                        print(f"STDERRMARK {run.day} {name}",file=sys.stderr)
                        if name=="freshness":run.record(name,"failed","INJECTED nonfatal freshness warning")
                        elif name=="project" and run.day==fail_day:run.record(name,"failed","INJECTED fatal projection failure")
                        else:run.record(name,"ok","mocked normal phase")
                    return execute
                return [(name,phase(name)) for name in phases]
            output=io.StringIO();errors=io.StringIO();original_args=args()
            with patch.object(nightly,"archive_paths",capture_archive),patch.object(nightly,"PIPELINE",pipeline()),patch.object(nightly.subprocess,"run",process),patch.object(nightly,"Engine",engine),contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):
                rc=nightly.run_backfill(original_args)
            logs=list((root/"data").glob("backfill*.log"));text=logs[0].read_text() if len(logs)==1 else ""
            archived_files=[p.read_bytes() for p in archives.rglob("*") if p.is_file()]
            want=[(day,cutoff,season,name,None,None,17,23,4) for day,cutoff,season in expected for name in phases]
            summaries=[json.loads((snap/day/"pipeline.json").read_text()) for day,_,_ in expected]
            valid=(rc==0 and len(phases)>0 and events==want and order[0]=="archive" and len(archives_seen)==1
                   and b"original master bytes\n" in archived_files and not process.called and not engine.called
                   and original_args.date=="2026-09-07" and original_args.as_of is None
                   and len(logs)==1 and text.count("PHASEMARK")==len(want) and text.count("STDERRMARK")==len(want)
                   and all(s["failed"]==1 and [r["step"] for r in s["steps"]]==phases for s in summaries)
                   and all(next(r for r in s["steps"] if r["step"]=="freshness")["status"]=="failed" for s in summaries)
                   and all(next(r for r in s["steps"] if r["step"]=="project")["status"]=="ok" and next(r for r in s["steps"] if r["step"]=="track")["status"]=="ok" for s in summaries))
            check(valid,f"backfill execution: archives all data first, repeats the same {len(phases)} normal phases for each of 3 stored dates ({len(want)} phase calls); freshness failures remain reported while project/Track continue, with exact metadata/options and persistent stdout/stderr",
                  f"rc {rc}, {len(events)} phase calls, {len(logs)} logs, subprocess calls {process.call_count}")
            events.clear();failure_output=io.StringIO()
            with patch.object(nightly,"PIPELINE",pipeline("2026-09-03")),patch.object(nightly.subprocess,"run",process),patch.object(nightly,"Engine",engine),contextlib.redirect_stdout(failure_output),contextlib.redirect_stderr(io.StringIO()):
                fail_rc=nightly.run_backfill(args())
            failure_ok=fail_rc==1 and events==want[:2*len(phases)] and "INJECTED fatal projection failure" in failure_output.getvalue()
            before=tree(root);runner=Mock(side_effect=AssertionError("archive failure must prevent normal job"))
            with patch.object(nightly,"archive_paths",side_effect=OSError("INJECTED archive failure")),patch.object(nightly,"run_nightly",runner),contextlib.redirect_stdout(io.StringIO()):
                archive_rc=nightly.run_backfill(args())
            failure_ok &= archive_rc==1 and not runner.called and tree(root)==before
            with patch.object(nightly,"run_nightly",side_effect=KeyboardInterrupt()),contextlib.redirect_stdout(io.StringIO()):
                interrupt_rc=nightly.run_backfill(args())
            check(failure_ok and interrupt_rc==130 and not process.called and not engine.called,
                  "backfill failure: a normal projection failure stops before the third stored job; archive failure makes zero jobs/log writes, interruption returns 130, and no custom subprocess/model work runs")


def check_nightly_safety() -> None:
    """Keep expensive compute and destructive housekeeping behind tested read/write guards."""
    import argparse
    import contextlib
    import io
    from unittest.mock import patch, Mock
    from scripts import nightly
    from scripts.player_metrics import PLAYER_SCHEMA_VERSION
    from scripts.serve import Snapshots
    def files(root):
        return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);snap=root/"snapshots";snap.mkdir();archives=root/"archives"
        for i,season in enumerate([2025,2025,2025,2026,2026,2026,2026],1):
            d=snap/f"2026-09-{i:02d}";d.mkdir()
            (d/"projection.json").write_text(json.dumps({"params":{"season":season},"worlds":1,"as_of":"2026-09-01"}))
        for name in (".snapshot-stage-abcd","not-a-date","2026-09-99"):
            (snap/name).mkdir();(snap/name/"projection.json").write_text('{}')
        (snap/"index.json").write_text('[{"sentinel":true}]')
        expected=[snap/f"2026-09-{i:02d}" for i in (3,2,1)]
        args=argparse.Namespace(date="2026-09-08",only=["prune"],skip=None,dry_run=False,keep=2,season=2026)
        with patch.multiple(nightly,SNAP_DIR=snap,ARCHIVE_ROOT=archives,ROOT=root):
            good=nightly.retention_candidates(snap,2,2026)==expected and nightly.retention_candidates(snap,6,2026)==expected[2:]
            before=files(snap)
            for steps in ([],[{"step":"project","status":"failed"}],[{"step":"project","status":"ok"},{"step":"project:old","status":"failed"}]):
                run=nightly.Run(args);run.steps=steps.copy();nightly.step_prune(run)
                good &= files(snap)==before and run.steps[-1]["status"]=="skipped"
            run=nightly.Run(args);run.steps=[{"step":"project","status":"ok"}];nightly.step_prune(run)
            archive_bytes=list(files(archives).values())
            good &= all(not p.exists() for p in expected) and all((snap/f"2026-09-{i:02d}").exists() for i in (4,5,6,7))
            good &= sum(raw in archive_bytes for name,raw in before.items() if name.endswith("projection.json") and name[:10] in [p.name for p in expected])==3
            check(good,"nightly: 7 dated snapshots retain the whole 4-snapshot active season; 3 invalid names ignored; 3 failed/missing-project guards prevent pruning; eligible old bundles archived")
            dry_before=files(root)
            with patch.object(sys,"argv",["nightly.py","--dry-run","--date","2026-09-09","--season","2026"]), contextlib.redirect_stdout(io.StringIO()):
                rc=nightly.main()
            dry_ok=rc==0 and files(root)==dry_before
            # Rewind without --only must select project, avoiding source/master rewrites.
            calls=[]
            with patch.object(sys,"argv",["nightly.py","--dry-run","--as-of","2026-09-01"]), patch.object(nightly,"PIPELINE",[("probe",lambda r:calls.append(r.args.only))]),contextlib.redirect_stdout(io.StringIO()):
                rewind_rc=nightly.main()
            rewind_ok=rewind_rc==0 and calls==[["project"]] and files(root)==dry_before
            failing_track=lambda r:r.record("track","failed","injected selected track failure")
            with patch.object(sys,"argv",["nightly.py","--only","track","--date","2026-09-09"]),patch.object(nightly,"PIPELINE",[("track",failing_track)]),contextlib.redirect_stdout(io.StringIO()):
                failed_selected_rc=nightly.main()
            check(dry_ok and rewind_ok and failed_selected_rc==1,
                  "nightly: full dry-run leaves snapshot/index/log/archive bytes unchanged; --as-of selects project only; an explicitly selected failed track step returns1")
            # Missing player inputs must fail before either serial or parallel expensive runner.
            master=pd.DataFrame([{"season":2026,"played":True,"tbd":False}])
            engine=Mock(master=master);serial=Mock(side_effect=AssertionError("compute must not start"));parallel=Mock(side_effect=AssertionError("compute must not start"))
            args=argparse.Namespace(date="2026-09-08",only=["project"],skip=None,dry_run=False,worlds=1,season=2026,seed=1,as_of=None,processes=4)
            run=nightly.Run(args);before=files(root)
            with patch.object(nightly,"Engine",return_value=engine),patch.object(nightly,"run_projection",serial),patch.object(nightly,"run_projection_parallel",parallel):
                nightly.step_project(run)
            check(not serial.called and not parallel.called and files(root)==before and run.steps[-1]["status"]=="failed"
                  and "--players-only" in run.steps[-1]["detail"],
                  "nightly: obsolete/missing player extraction fails before serial/parallel simulation and preserves every existing bundle byte")
            stage=root/"stage";stage.mkdir()
            projection={"params":{"season":2026},"as_of":"2026-09-01"}
            (stage/"projection.json").write_text(json.dumps(projection));(stage/"matches.json").write_text('{"fixtures":[]}')
            for stem in ("gw","paths"):(stage/f"{stem}.json.gz").write_bytes(gzip.compress(b'{}'))
            players={"schema":PLAYER_SCHEMA_VERSION,"season":2026,"as_of":"2026-09-01","competitions":{}}
            (stage/"players.json").write_text('{"stale":true}')
            nightly.write_players_snapshot(stage,players);nightly.validate_snapshot_bundle(stage)
            packed=(stage/"players.json.gz").read_bytes()
            valid_ok=not (stage/"players.json").exists() and json.loads(gzip.decompress(packed))==players
            bad=0
            for body in (b"invalid gzip",gzip.compress(json.dumps({**players,"as_of":"2099-01-01"}).encode()),gzip.compress(json.dumps({**players,"schema":1}).encode())):
                (stage/"players.json.gz").write_bytes(body)
                try:nightly.validate_snapshot_bundle(stage)
                except (ValueError,OSError,EOFError):bad+=1
            (stage/"players.json.gz").write_bytes(packed)
            d=snap/"2026-09-10";stage.rename(d);(snap/"index.json").write_text('[{"date":"2026-09-10"}]')
            snapshots=Snapshots(snap)
            (d/"players.json").write_text('{"stale":true}')
            compressed=snapshots.players_bytes("2026-09-10",compressed=True)
            valid_ok &= snapshots.players("2026-09-10")==players and compressed==packed
            (d/"players.json.gz").unlink();(d/"players.json").write_text(json.dumps(players))
            valid_ok &= Snapshots(snap).players("2026-09-10")==players
            check(valid_ok and bad==3,
                  "nightly: schema2 player gzip publishes/archive-removes plain; 3 corrupt/cutoff/schema bundles reject; accessor prefers exact gzip over stale plain and retains plain fallback")


def check_ops_storage() -> None:
    """Independent byte identities for archive-first replacement and failure rollback."""
    from unittest.mock import patch
    from scripts import ops_storage

    def files(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()} if root.exists() else {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); work = root / "work"; work.mkdir(); archive_root = root / "archives"
        csv, pkl = work / "master.csv", work / "master.pkl"
        old = {csv: b"old csv\n1,2\n", pkl: b"old pickle bytes"}
        for path, raw in old.items(): path.write_bytes(raw)
        new = {csv: b"new csv\n3,4\n", pkl: b"new pickle bytes"}
        archive = ops_storage.atomic_write_files(new, archive_root=archive_root)
        copied = list(files(archive).values()) if archive else []
        first_ok = all(path.read_bytes() == raw for path, raw in new.items()) and all(raw in copied for raw in old.values())
        before = files(archive_root)
        unchanged = ops_storage.atomic_write_files(new, archive_root=archive_root)
        check(first_ok and unchanged is None and files(archive_root) == before,
              "storage: 2 master-like files publish together and preserve exact old bytes externally; identical rerun creates no write/archive")

        real_replace = ops_storage.os.replace
        refused = False
        def fail_second(source, destination):
            nonlocal refused
            if Path(destination) == pkl and Path(source).name.startswith(".write-") and not refused:
                refused = True
                raise OSError("injected second-file publication failure")
            return real_replace(source, destination)
        caught = False
        try:
            with patch.object(ops_storage.os, "replace", fail_second):
                ops_storage.atomic_write_files({csv:b"bad partial csv",pkl:b"bad partial pickle"}, archive_root=archive_root)
        except OSError as error:
            caught = str(error) == "injected second-file publication failure"
        check(caught and refused and all(path.read_bytes() == raw for path, raw in new.items())
              and not list(work.glob(".write-*")) and not list(work.glob(".restore-*")),
              "storage: injected second-file failure restores both exact prior master files and cleans staged/restore files")

        destination = root / "snapshots" / "2026-10-22"; destination.mkdir(parents=True)
        previous = {"projection.json":b'{"worlds":2}',"matches.json":b'{"fixtures":["old"]}',"players.json.gz":b"old players bytes"}
        for name, raw in previous.items(): (destination / name).write_bytes(raw)
        stage = root / "snapshots" / ".stage"; stage.mkdir()
        replacement = {"projection.json":b'{"worlds":3}',"matches.json":b'{"fixtures":["new"]}',"players.json.gz":b"new players bytes"}
        for name, raw in replacement.items(): (stage / name).write_bytes(raw)
        def fail_promote(source, target):
            raise OSError("injected snapshot promotion failure")
        caught = False
        try:
            ops_storage.publish_snapshot(stage, destination, archive_root=archive_root, promote=fail_promote)
        except OSError as error:
            caught = str(error) == "injected snapshot promotion failure"
        rollback_ok = caught and files(destination) == previous and files(stage) == replacement
        archive = ops_storage.publish_snapshot(stage, destination, archive_root=archive_root)
        copied = list(files(archive).values()) if archive else []
        check(rollback_ok and files(destination) == replacement and not stage.exists()
              and all(raw in copied for raw in previous.values())
              and not list(destination.parent.glob(".snapshot-rollback-*")),
              "storage: 3-file snapshot promotion failure restores the exact old bundle; successful retry publishes complete new bundle and external archive")


def check_europe_cases() -> None:
    """Specified Article-3 cases: cup cascades differ from consumed titleholder slots."""
    from scripts.europe_places import qualification_policies, seat_world

    specs = [("English Premier League", "EN", "English FA Cup", "English League Cup", 1),
             ("Spanish La Liga", "ES", "Spanish Copa del Rey", None, 1),
             ("Italian Serie A", "IT", "Italian Coppa Italia", None, 0),
             ("French Ligue 1", "FR", "French Coupe de France", None, 0),
             ("German Bundesliga", "DE", "German DFB Pokal", None, 0)]
    orders = {comp: [f"{code}{n}" for n in range(1, 21)] for comp, code, *_ in specs}
    policies = {comp: {"ucl": 4, "uel": 2, "uecl": 1, "eps": eps, "cup": cup,
                       "league_cup": efl, "ucl_direct": 3 if code == "FR" else 4}
                for comp, code, cup, efl, eps in specs}
    associations = {team: comp for comp, teams in orders.items() for team in teams}
    for comp, code, *_ in specs:
        associations[f"{code}-cup-only"] = comp
    defaults = {cup: f"{code}1" for _, code, cup, _, _ in specs}
    defaults["English League Cup"] = "EN2"
    CL, EL, CO = "UEFA Champions League", "UEFA Europa League", "UEFA Conference League"
    FR, EN = "French Ligue 1", "English Premier League"
    cases = []
    def case(name, comp, edits, ucl, uel, uecl):
        winners = {**defaults, **edits}
        cases.append((name, comp, winners, {"ucl": set(ucl), "uel": set(uel), "uecl": set(uecl)}))
    f = lambda *n: [f"FR{i}" for i in n]
    e = lambda *n: [f"EN{i}" for i in n]
    case("cup winner already UCL", FR, {"French Coupe de France": "FR3"}, f(1,2,3,4), f(5,6), f(7))
    case("cup winner already league UEL", FR, {"French Coupe de France": "FR5"}, f(1,2,3,4), f(5,6), f(7))
    case("cup winner at league UECL", FR, {"French Coupe de France": "FR7"}, f(1,2,3,4), f(5,7), f(6))
    case("cup winner below Europe", FR, {"French Coupe de France": "FR12"}, f(1,2,3,4), f(5,12), f(6))
    case("relegated cup winner", FR, {"French Coupe de France": "FR18"}, f(1,2,3,4), f(5,18), f(6))
    case("lower-division cup winner", FR, {"French Coupe de France": "FR-cup-only"}, f(1,2,3,4), ["FR5","FR-cup-only"], f(6))
    case("EFL winner already UCL", EN, {"English League Cup": "EN1"}, e(1,2,3,4,5), e(6,7), e(8))
    case("both English cups same outsider", EN, {"English FA Cup": "EN8", "English League Cup": "EN8"}, e(1,2,3,4,5), e(6,8), e(7))
    case("English cups distinct outsiders", EN, {"English FA Cup": "EN8", "English League Cup": "EN9"}, e(1,2,3,4,5), e(6,8), e(9))
    case("CL title consumes base UEL", FR, {CL: "FR5"}, f(1,2,3,4,5), f(6), f(7))
    case("EL title consumes base UECL", FR, {EL: "FR7"}, f(1,2,3,4,7), f(5,6), [])
    case("CL title outside domestic seats", FR, {CL: "FR12"}, f(1,2,3,4,12), f(5,6), f(7))
    case("CL title already UCL", FR, {CL: "FR2"}, f(1,2,3,4), f(5,6), f(7))
    case("cup-only CL title consumes cup UEL", FR, {"French Coupe de France": "FR-cup-only", CL: "FR-cup-only"}, [*f(1,2,3,4),"FR-cup-only"], f(5), f(6))
    case("Conference title within base UEL", FR, {CO: "FR6"}, f(1,2,3,4), f(5,6), f(7))
    case("Conference title consumes base UECL", FR, {CO: "FR7"}, f(1,2,3,4), f(5,6,7), [])
    case("Conference title outside domestic seats", FR, {CO: "FR12"}, f(1,2,3,4), f(5,6,12), f(7))
    case("Conference title already UCL", FR, {CO: "FR2"}, f(1,2,3,4), f(5,6), f(7))
    case("EPS outranks Conference title route", EN, {CO: "EN5"}, e(1,2,3,4,5), e(6,7), e(8))
    case("EPS then Conference base-UEL reservation", EN, {CO: "EN6"}, e(1,2,3,4,5), e(6,7), e(8))
    case("EPS then Conference base-UECL promotion", EN, {CO: "EN7"}, e(1,2,3,4,5), e(6,7,8), [])
    case("two UEL-consuming titles then EPS UECL cascade", EN, {CL: "EN5", EL: "EN6"}, e(1,2,3,4,5,6,7), [], e(8))
    case("title then EPS Conference winner", EN, {CL: "EN5", CO: "EN6"}, e(1,2,3,4,5,6), e(7), e(8))
    case("UEL and UECL titles consumed before EPS", EN, {CL: "EN5", EL: "EN7"}, e(1,2,3,4,5,6,7), e(8), [])
    case("three outside titleholders plus EPS", EN, {CL: "EN12", EL: "EN13", CO: "EN14"}, e(1,2,3,4,5,12,13), e(6,7,14), e(8))
    case("foreign titleholders do not steal domestic seats", FR, {CL: "Foreign CL", EL: "Foreign EL", CO: "Foreign CO"}, f(1,2,3,4), f(5,6), f(7))
    off = []; audited = 0
    for name, comp, winners, expected in cases:
        actual = seat_world(orders, winners, policies, associations)
        if actual.get(comp) != expected:
            off.append(f"{name}: {actual.get(comp)} != {expected}")
        for league, groups in actual.items():
            rows = [t for k in ("ucl", "uel", "uecl") for t in groups[k]]
            audited += len(rows)
            if len(rows) != len(set(rows)) or any(associations.get(t) != league for t in rows):
                off.append(f"{name}: overlapping/wrong-association seats in {league}")
    check(len(cases) == 26 and audited > 0 and not off,
          f"European entry: {len(cases)} independent cup/titleholder/EPS cases, {audited} seats, no overlap; relegated/lower-division winners and consumed lower quotas retained",
          "; ".join(off[:3]))
    live = qualification_policies(2026)
    bad = [comp for comp, code, cup, efl, eps in specs
           if comp not in live or any(live[comp].get(k) != v for k, v in
                                      {"ucl":4,"uel":2,"uecl":1,"eps":eps,"cup":cup,"league_cup":efl}.items())]
    check(len(live) == 5 and not bad and live[FR].get("ucl_direct") == 3,
          "European entry: all 5 associations start with4 UCL entries /2 UEL /1 UECL; France includes qualifying, and England/Spain EPS assumptions are explicit",
          ", ".join(bad))


def check_europe_counts(acc, payload: dict, expected: dict) -> None:
    """Count seats from every independently reconstructed final world, including outsiders."""
    keys = ("ucl", "uel", "uecl")
    off = []; cells = 0
    counts = acc.europe_counts
    if set(t for t, v in counts.items() if np.any(v)) != set(expected):
        off.append("positive raw team coverage differs")
    for team, values in counts.items():
        if values.dtype != np.int32 or values.shape != (3,) or not np.array_equal(values, expected.get(team, np.zeros(3, np.int32))):
            off.append(f"{team}: wrong per-world integer counts")
        if values.sum() > acc.worlds or np.any(values < 0):
            off.append(f"{team}: overlapping/negative exclusive entries")
        cells += 3
    europe = payload.get("europe", {})
    rows = europe.get("teams", [])
    by_team = {r["team"]: r for r in rows}
    if (len(rows) != len(by_team) or [r["team"] for r in rows] != sorted(expected)
            or europe.get("mode") != "per_world" or europe.get("scope") != "five_leagues_and_titleholders"
            or europe.get("season") != payload["params"]["season"] + 1 or europe.get("eps_policy") != "previous_allocation"):
        off.append("global scope/order/season/route metadata differs")
    for team, values in expected.items():
        row = by_team.get(team, {})
        if row.get("association") != acc.europe_associations.get(team) or any(row.get("p_" + key) != round(int(values[k]) / acc.worlds, 4) for k, key in enumerate(keys)):
            off.append(f"{team}: global entry probability/association differs")
    outsiders = foreign = league_cells = 0
    all_topflight = {t for block in acc.leagues.values() for t in block["teams"]}
    for row in rows:
        outsiders += row["team"] not in all_topflight
        foreign += row["association"] is None
    for league in payload["leagues"]:
        comp = league["competition"]
        policy, wire = acc.europe_policy[comp], league.get("qualification", {})
        if (wire.get("mode") != "per_world" or wire.get("scope") != "competition_entry"
                or wire.get("season") != payload["params"]["season"] + 1
                or wire.get("base") != {key: policy[key] for key in keys}
                or wire.get("eps_policy") != "previous_allocation"):
            off.append(f"{comp}: qualification policy metadata differs")
        for row in league["teams"]:
            values = expected.get(row["team"], np.zeros(3, np.int32))
            for k, key in enumerate(keys):
                league_cells += 1
                if row.get("p_" + key) != round(int(values[k]) / acc.worlds, 4):
                    off.append(f"{comp} {row['team']}: p_{key} differs from world entry")
        for k, key in enumerate(keys):
            top_count = sum(int(expected.get(t, np.zeros(3, np.int32))[k]) for t in acc.leagues[comp]["teams"])
            association_count = sum(int(v[k]) for t, v in expected.items() if acc.europe_associations.get(t) == comp)
            if (wire.get("mean", {}).get(key) != round(top_count / acc.worlds, 4)
                    or wire.get("association_mean", {}).get(key) != round(association_count / acc.worlds, 4)
                    or int(acc.europe_association_totals[comp][k]) != association_count
                    or acc.europe_association_totals[comp].dtype != np.int64):
                off.append(f"{comp}/{key}: top-flight/association means differ from exact seats")
    check(len(expected) > 0 and cells > 0 and league_cells > 0 and outsiders > 0 and foreign > 0 and not off,
          f"European entry: {len(expected)} clubs / {cells} integer cells equal every world's final tables and winners; {league_cells} league probabilities, 5 top-flight/association means, {outsiders} outsiders ({foreign} foreign title routes) serialize exactly",
          "; ".join(off[:4]) or f"outsiders={outsiders}, foreign={foreign}")


def collect_cup_world(acc, sim: pd.DataFrame, expected: dict, stats: dict) -> None:
    """Independent cup memberships and 90-minute result partitions, before Accumulator.add."""
    from scripts.projection import MAXG
    attrs, sim.attrs = sim.attrs, {}
    try:
        reports = {comp: rep for (comp, _), rep in attrs.get("cups", {}).items()}
        score90 = np.asarray(attrs.get("score90", []))
        if score90.shape != (len(sim), 2):
            stats["missing90"] = stats.get("missing90", 0) + 1
            return
        stats["late_reports"] = stats.get("late_reports", 0) + sum(bool(r.get("late")) for r in reports.values())
        for at, row in enumerate(sim.itertuples(index=False)):
            if row.sampled and row.phase == "knockout" and row.fixture_id < 0 and (row.competition, row.stage) in acc.track_stages:
                h, a = score90[at]
                if not np.isfinite([h, a]).all():
                    stats["missing90"] = stats.get("missing90", 0) + 1
                else:
                    key = (row.competition, row.stage, row.home, row.away)
                    grid = stats.setdefault("_ko_scores", {}).setdefault(key, np.zeros((MAXG, MAXG), np.int32))
                    grid[min(int(h), MAXG - 1), min(int(a), MAXG - 1)] += 1
            report = reports.get(row.competition)
            if report is None or not row.sampled:
                continue
            original = score90[at]
            if not np.isfinite(original).all():
                stats["missing90"] = stats.get("missing90", 0) + 1
                continue
            changed = tuple(original) != (row.home_goals, row.away_goals)
            stats["extra_changes"] = stats.get("extra_changes", 0) + changed
            stats["two_leg_rows"] = stats.get("two_leg_rows", 0) + (row.leg == 2)
            stats["decisive90_extra_returns"] = stats.get("decisive90_extra_returns", 0) + (row.leg == 2 and changed and original[0] != original[1])
            i = acc.fx_index.get(int(row.fixture_id))
            if i is None or acc.fx_meta[i]["kind"] != "cup":
                continue
            meta = acc.fx_meta[i]
            entry = expected.setdefault(i, {"score": np.zeros((MAXG, MAXG), np.int32), "excluded": False})
            h, a = map(int, original)
            entry["score"][min(h, MAXG - 1), min(a, MAXG - 1)] += 1
            stats["tracked_changes"] = stats.get("tracked_changes", 0) + changed
            if changed and "first_tracked_extra" not in stats:
                stats["first_tracked_extra"] = (i, h, a, int(row.home_goals), int(row.away_goals))
            if (row.home, row.away) != (meta["home"], meta["away"]):
                entry["excluded"] = True
                continue
            labels = list(report["reached"])
            if row.stage not in labels:
                stats["bad_stage"] = stats.get("bad_stage", 0) + 1
                continue
            later = labels[labels.index(row.stage) + 1:]
            keys = [s.lower() for s in later] + ["win"]
            if "keys" not in entry:
                entry.update(keys=keys, labels=later, counts=np.zeros((3, 2, len(keys)), np.int32))
            elif entry["keys"] != keys:
                stats["bad_stage"] = stats.get("bad_stage", 0) + 1
            outcome = 0 if h > a else 1 if h == a else 2
            for side, team in enumerate((row.home, row.away)):
                entry["counts"][outcome, side] += [int(team in report["reached"][s]) for s in later] + [int(team == report["champion"])]
            stats.setdefault("stages", set()).add(row.stage)
    finally:
        sim.attrs = attrs


def check_cup_stakes(acc, payload: dict, expected: dict, stats: dict) -> None:
    from scripts.projection import _projected_extras
    errors = []; fates = values = fixtures = placeholders = partials = raw_fates = 0; worst = 0.0
    match_by_id = {f["fixture_id"]: f for f in payload["matches"]["fixtures"] if f.get("kind") == "cup"}
    for i, source in expected.items():
        meta = acc.fx_meta[i]
        if not np.array_equal(source["score"], acc.fx_counts[i]):
            errors.append(f"{meta['competition']} {meta['home']}–{meta['away']}: score table is not90minutes")
        if source["excluded"]:
            placeholders += 1
            if i in acc.fx_cup_stakes or i in acc.fx_cup_keys:
                errors.append(f"{meta['competition']} placeholder has named-side stakes")
            continue
        fixtures += 1
        keys, tally = source["keys"], source["counts"]
        raw_fates += 2 * len(keys)
        if acc.fx_cup_keys.get(i) != keys or not np.array_equal(acc.fx_cup_stakes.get(i), tally):
            errors.append(f"{meta['competition']} {meta['home']}–{meta['away']}: raw later-round/result tally differs")
        if tally.dtype != np.int32 or tally.shape != (3, 2, len(keys)) or len(keys) != len(set(keys)) or keys[-1] != "win":
            errors.append(f"{meta['competition']}: fate shape/order/dtype")
        cup = acc.cups[meta["competition"]]
        by = np.array([np.tril(source["score"], -1).sum(), np.trace(source["score"]), np.triu(source["score"], 1).sum()])
        wire = _projected_extras(acc, i)
        actual_match = match_by_id.get(meta["fixture_id"])
        if wire.get("score_basis") != "90min" or wire.get("p_occurs") != round(int(by.sum()) / acc.worlds, 4):
            errors.append(f"{meta['competition']}: missing90-minute basis/occurrence probability")
        if int(by.sum()) != acc.worlds:
            partials += 1
            if (wire.get("stakes_unavailable") != "conditional_fixture" or "stakes" in wire or "stakes_of" in wire
                    or meta["next"] and (actual_match is None or actual_match.get("stakes_unavailable") != "conditional_fixture" or "stakes" in actual_match)):
                errors.append(f"{meta['competition']}: partial occurrence incorrectly claims unconditional stakes")
            continue
        if wire.get("stakes_of") != keys:
            errors.append(f"{meta['competition']}: missing per-fixture keys")
        if meta["next"] and (actual_match is None or any(actual_match.get(k) != wire[k] for k in ("stakes", "stakes_of", "score_basis"))):
            errors.append(f"{meta['competition']}: serialized matches stakes differ")
        for side, team in enumerate((meta["home"], meta["away"])):
            r = cup["teams"][team]
            counts = [r["reach"].get(label, 0) for label in source["labels"]] + [r["win"]]
            for k, count in enumerate(counts):
                fates += 1
                if int(tally[:, side, k].sum()) != int(count):
                    errors.append(f"{meta['competition']} {team}/{keys[k]}: weighted exact count not unconditional")
                raw = wire["stakes"][side][k]; row = raw if isinstance(raw, list) else [raw] * 3
                for result in range(3):
                    values += 1
                    want = round(int(tally[result, side, k]) / int(by[result]), 3) if by[result] else None
                    if row[result] != want:
                        errors.append(f"{meta['competition']} {team}/{keys[k]}: conditional/null not source count")
                weighted = sum(int(by[o]) / acc.worlds * (row[o] or 0) for o in range(3))
                worst = max(worst, abs(weighted - int(count) / acc.worlds))
    ko_scores = stats.get("_ko_scores", {})
    if set(ko_scores) != set(acc.matchups) or any(not np.array_equal(v, acc.matchups.get(k)) for k, v in ko_scores.items()):
        errors.append("drawn knockout score tables differ from independent90-minute scores")
    brief = {k: v for k, v in stats.items() if not k.startswith("_")}
    check(fixtures > 0 and fates > 0 and not errors and not stats.get("bad_stage") and not stats.get("missing90"),
          f"cup stakes: {fixtures} raw named fixtures / {raw_fates} side-fates equal world reports; {fates} unconditional fates / {values} values serialized exactly; {partials} conditional fixtures and {placeholders} placeholders withheld; {len(ko_scores)} drawnKO grids use90minutes",
          "; ".join(errors[:4]) or str(brief))
    if not ko_scores:
        print("  skip    drawn-knockout90-minute score-grid identity (no tracked pending knockout inside this fresh run's horizon; named cup grids checked)")
    check(fixtures > 0 and worst <= .0005 + 1e-9 and stats.get("tracked_changes", 0) > 0
          and stats.get("two_leg_rows", 0) > 0 and stats.get("decisive90_extra_returns", 0) > 0 and stats.get("late_reports", 0) > 0,
          f"cup stakes: weighted probabilities recover every fate (max{worst:.6f}); {stats.get('tracked_changes', 0)} tracked AET score changes, {stats.get('two_leg_rows', 0)} two-leg returns ({stats.get('decisive90_extra_returns', 0)} decisive90 AET returns) and {stats.get('late_reports', 0)} late-entry reports retain actual90 minutes",
          str(brief))
    # An unseen result is unknown even when the same fate is zero in every observed world.
    import copy
    i = next(i for i, s in expected.items() if not s["excluded"] and int(s["score"].sum()) == acc.worlds)
    probe = copy.copy(acc); probe.fx_counts = acc.fx_counts.copy()
    probe.worlds = 1
    probe.fx_cup_stakes = {k: v.copy() for k, v in acc.fx_cup_stakes.items()}
    probe.fx_counts[i].fill(0); probe.fx_counts[i, 1, 0] = 1
    probe.fx_cup_stakes[i].fill(0)
    wire = _projected_extras(probe, i)
    nulls = sum(isinstance(v, list) and v == [0.0, None, None] for side in wire.get("stakes", []) for v in side)
    probe.fx_meta = [dict(m) for m in acc.fx_meta]
    probe.fx_meta[i].update(kind="uefa", round=None)
    knockout = _projected_extras(probe, i)
    check(nulls == 2 * len(acc.fx_cup_keys[i]) and nulls > 0 and knockout.get("score_basis") == "90min"
          and "stakes_of" not in knockout and "p_occurs" not in knockout,
          f"cup stakes: {nulls} all-zero fates distinguish unseen outcomes as null; known UEFA knockout metadata also names90-minute odds without cup fates")


def check_score_counts(acc, payload) -> None:
    """Full retained score counts reproduce the independent fixed-point accumulator exactly."""
    import copy
    by_id={m['fixture_id']:i for i,m in enumerate(acc.fx_meta)}
    rows=payload['matches']['fixtures'];errors=[];cells=0
    for f in rows:
        source=acc.fx_counts[by_id[f['fixture_id']]];grid=np.asarray(f.get('score_counts',[]));cells+=source.size
        if grid.shape!=source.shape or not np.array_equal(grid,source) or grid.dtype.kind not in 'iu' or grid.sum()!=f['n'] or f.get('score_cap')!=source.shape[0]-1:
            errors.append(str(f['fixture_id']))
    check(bool(rows) and cells>0 and not errors,
          f"score counts:{len(rows)} fixture grids/{cells} integer cells equal raw accumulator; n and overflow cap exact",str(errors[:4]))
    damaged=copy.deepcopy(rows[0]);damaged['score_counts'][0][0]+=1
    check(sum(map(sum,damaged['score_counts']))!=damaged['n'],
          'score counts:1 deliberate extra world fails the exact n accounting identity')


def check_dashboard_store() -> None:
    """The extracted read service works in a fresh process that refuses model imports."""
    probe = r'''
import builtins, csv, gzip, hashlib, importlib.util, json, sys, tempfile
from pathlib import Path
original_import = builtins.__import__
def no_model(name, *args, **kwargs):
    if name.split('.')[0] in {'numpy','pandas'} or name.startswith(('scripts.projection','scripts.simulate_season','scripts.attack_defence_qt')):
        raise AssertionError('read service imported model dependency: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = no_model
spec = importlib.util.spec_from_file_location('standalone_dashboard_store', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); days = ['2026-09-01','2026-09-03']
    (root/'index.json').write_text(json.dumps([{'date': day} for day in days]))
    for day in days:
        folder=root/day;folder.mkdir()
        projection={'params':{'season':2026},'as_of':day,'worlds':1,'leagues':[],'uefa':[]}
        (folder/'projection.json').write_text(json.dumps(projection))
        (folder/'matches.json').write_text(json.dumps({'fixtures':[{'name':'stored future match'}]}))
        for name,payload in [('players',{'season':2026,'as_of':day,'competitions':{}}),('gw',{'leagues':{'L':{'teams':['Alpha','Beta']}}}),('paths',{'rounds':['R16']})]:
            (folder/(name+'.json.gz')).write_bytes(gzip.compress(json.dumps(payload).encode(),mtime=0))
    columns=['season','competition','kind','home','away','kickoff','played','tbd','home_goals','away_goals','home_xg','away_xg']
    entries=[dict(zip(columns,[season,'Cup','cup','Alpha','Beta',day+' 15:00:00',played,tbd,2,1,1.2,0.8])) for season,day,played,tbd in [(2026,'2026-09-01','true','false'),(2026,'2026-09-02','true','false'),(2025,'2026-09-01','true','false'),(2026,'2026-09-01','false','false'),(2026,'2026-09-01','true','true')]]
    csv_path=root/'fixtures.csv'
    with csv_path.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();writer.writerows(entries)
    store=module.Snapshots(root,csv_path)
    loaded=store.load(days[0]);raw=(root/days[0]/'projection.json').read_bytes()
    assert loaded['source']['projection_sha256']==hashlib.sha256(raw).hexdigest()
    assert store.matches(days[0])=={'fixtures':[{'name':'stored future match'}]}
    assert store.players(days[0])=={'season':2026,'as_of':days[0],'competitions':{}}
    assert store.gw(days[0])=={'leagues':{'L':{'teams':['Alpha','Beta']}}}
    assert store.paths(days[0])=={'rounds':['R16']}
    assert store.history(2026)['dates']==days
    early=store.team_fixtures('Alpha',days[0])['fixtures'];late=store.team_fixtures('Alpha',days[1])['fixtures']
    assert len(early)==1 and len(late)==2 and early[0]['result']==[2,1] and early[0]['xg']==[1.2,0.8], (early,late)
    print('7 read services,2 cutoffs,5 source fixture cases; no model dependencies')
from scripts.performance_studio import PerformanceStudio
from scripts.dashboard_store import Snapshots
live=Snapshots();p=live.load();evidence=PerformanceStudio(live).read(p['source']['date'],p['source']['projection_sha256'])
assert evidence['coverage']['fixtures']>0 and evidence['coverage']['forecasts']>0
print('Performance Studio retained source read: no numerical/model imports')
from scripts.time_machine import TimeMachine
machine=TimeMachine(live);catalog=machine.catalog(p['source']['date'],p['source']['projection_sha256']);a=catalog['dates'][0];b=catalog['dates'][-1]
comparison=machine.compare(p['source']['date'],p['source']['projection_sha256'],a['date'],a['projection_sha256'],b['date'],b['projection_sha256'],b['competitions'][0])
assert comparison['rows'] and all(row['bridge'] for row in comparison['rows']) and comparison['ledger'] is not None
print('Time Machine stored-only read: no numerical/model imports')
from scripts.forecast_lab import ForecastLab
lab=ForecastLab(live).read(p['source']['date'],p['source']['projection_sha256'])
assert lab['fixtures'] and lab['coverage']['evaluated']+lab['coverage']['excluded']==lab['coverage']['played']
print('Forecast Lab source-pinned evaluation: no numerical/model imports')
from scripts.explore_visuals import ExploreVisuals
schedule=ExploreVisuals(live).read(p['source']['date'],p['source']['projection_sha256'])
assert schedule['fixtures'] and schedule['coverage']['fixed_fixture_records']==len(schedule['fixtures'])
print('Explore fixed schedule: no numerical/model imports')
'''
    result = subprocess.run([sys.executable, '-c', probe, str(ROOT / 'scripts/dashboard_store.py')],
                            cwd=ROOT, text=True, capture_output=True, timeout=30)
    check(result.returncode == 0 and '7 read services,2 cutoffs,5 source fixture cases' in result.stdout,
          'dashboard read services:7 stored reads,2 cutoffs and5 fixture cases run with numpy/pandas/model imports blocked',
          result.stderr.strip() or result.stdout.strip())


def main() -> int:
    from scripts.projection import (Engine, coerce_params, run_projection, run_projection_parallel,
                                    world_kwargs)
    from scripts.serve import Snapshots
    from scripts.simulate_season import simulate, uefa_handovers
    from scripts.uefa_bracket import _selfcheck_draw, _selfcheck_handover, verify_bracket

    print("scenario isolation")
    from analysis.scenario_audit import exact_reference, request_cases
    from analysis.scenario_lifecycle import verify as verify_scenario_jobs
    from scripts.scenario_store import catalog as scenario_catalog
    exact_reference()
    check(True, "Scenario Lab: exact evolving latent-state conditional law, paired SE reference and deliberate faults")
    check(bool(verify_scenario_jobs()), "Scenario Lab: validation, cancellation, source replacement, parameter retention and memory-only lifecycle")

    print("stored time machine")
    from analysis.time_machine_audit import cases as time_cases, real_reference as time_reference
    check(bool(time_cases()), "Time Machine:exact decimal/reverse/same-date bridge;stored-only revision/model/generation/scale and corrupt-source guards")
    with tempfile.TemporaryDirectory(prefix="time-machine-smoke-") as directory:
        evidence_path=Path(directory)/"time.json";counts=time_reference(evidence_path)
        check(counts['bridges']>0 and counts['fixture_club_totals']==2*counts['bridges'] and counts['known_invalid_coppa']==12,
              "Time Machine:all five leagues reconcile stored points/fixture totals, probability changes and reversal;12 historical Coppa cells remain invalid")
        if shutil.which("node"):
            proof=subprocess.run(["node","analysis/time_machine_audit.mjs",str(evidence_path)],cwd=ROOT,capture_output=True,text=True,timeout=30)
            check(proof.returncode==0,"Time Machine:pure timeline selectors reconcile raw stored points/probabilities/strength scales and retained fixture identities;A season retired",proof.stderr.strip())
        else:print("  skip    Time Machine selector checks (node not on PATH)")

    print("forecast evaluation")
    from analysis.forecast_lab_audit import cases as forecast_cases, real_reference as forecast_reference
    check(bool(forecast_cases()),"Forecast Lab: timing/fit/cutoff boundaries, stale source, duplicate, zero support, exact90 return legs and deliberate H/A fault")
    with tempfile.TemporaryDirectory(prefix="forecast-lab-smoke-") as directory:
        evidence_path=Path(directory)/"lab.json";counts=forecast_reference(evidence_path)
        check(counts['fixtures']==490 and counts['exclusions']==98 and counts['independent_checks']>0 and counts['historical_invalid_coppa']==12,
              "Forecast Lab:490 forecasts reconcile Track/raw sources and independent log/Brier/RPS;98 exclusions;historical Coppa unchanged")
        if shutil.which("node"):
            proof=subprocess.run(["node","analysis/forecast_lab_audit.mjs",str(evidence_path)],cwd=ROOT,capture_output=True,text=True,timeout=30)
            check(proof.returncode==0,"Forecast Lab:pure selectors reconcile paired scores,weekly SE,calibration bins,cohorts and cumulative exact fixture populations",proof.stderr.strip())
        else:print("  skip    Forecast Lab selector checks (node not on PATH)")

    print("cross-competition visualisations")
    from analysis.explore_visuals_audit import cases as explore_cases, real_reference as explore_reference
    check(bool(explore_cases()),"Explore charts:stored-only source pins,conditional/duplicate/conflicting schedules,hash replacement and missing sidecars")
    with tempfile.TemporaryDirectory(prefix="explore-smoke-") as directory:
        evidence_path=Path(directory)/"explore.json";counts=explore_reference(evidence_path)
        check(counts['fixed_records']>0 and counts['club_appearances']>0 and counts['rank_cells']==4*counts['clubs'] and counts['title_cells']==counts['clubs'],
              "Explore charts:independent raw source ranks,title probabilities and28-day fixture/club ledger")
        if shutil.which("node"):
            proof=subprocess.run(["node","analysis/explore_visuals_audit.mjs",str(evidence_path)],cwd=ROOT,capture_output=True,text=True,timeout=30)
            check(proof.returncode==0,"Explore charts:rank/scales,total-order title curves,exact cells/kickoff gaps and DST/UK boundary faults",proof.stderr.strip())
        else:print("  skip    Explore chart selector checks (node not on PATH)")

    print("performance evidence")
    from analysis.performance_audit import fixtures_case, real_reference
    check(bool(fixtures_case()), "Performance Studio: exact source/cutoff identities, missing/invalid forecast handling, hash replacement and revision/duplicate guards")
    with tempfile.TemporaryDirectory(prefix="performance-smoke-") as directory:
        evidence_path=Path(directory)/"evidence.json";counts=real_reference(evidence_path)
        check(counts['fixtures']>0 and counts['appearances']==2*counts['fixtures'] and counts['forecasts']>0,
              "Performance Studio: independent CSV/source expectations reconcile every retained league fixture and both club appearances")
        if shutil.which("node"):
            proof=subprocess.run(["node","analysis/performance_audit.mjs",str(evidence_path)],cwd=ROOT,capture_output=True,text=True,timeout=30)
            check(proof.returncode==0,"Performance Studio: all club totals and chart-point fixture populations equal the independent ledger; away/coverage/normalizer faults caught",proof.stderr.strip())
        else:print("  skip    Performance Studio selector checks (node not on PATH)")

    print("bracket")
    master = pd.read_pickle(ROOT / "data/master_fixtures.pkl").sort_values(
        "kickoff").reset_index(drop=True)
    n, fails = verify_bracket(master)
    check(n == 6 and not fails, f"{n} real 36-team knockouts satisfy every derived constraint",
          "; ".join(fails[:2]))
    d = _selfcheck_draw(500)
    check(not d, "500 drawn brackets satisfy the same constraints", "; ".join(d[:2]))
    h = _selfcheck_handover(master)
    check(not h, "30 handover cut points reproduce the real ties", "; ".join(h[:2]))

    from scripts.cup_bracket import CUP_RULES as _CR, verify as verify_cups
    cf = verify_cups(master)
    n_cup = sum(1 for (c, _), _ in master[master.kind == "cup"].groupby(["competition", "season"])
                if c in _CR)
    check(not cf, f"every finished cup replays to its final, and {len(_CR)} draws obey their rules"
                  f" ({n_cup} cup-seasons)", "; ".join(cf[:2]))

    # Penalty goals (version 10), off each match's shot map: never more than the side scored,
    # nor more than the penalties it took -- which FotMob's xG minus npxG counts independently,
    # in steps of 0.785 -- and known for nearly every played match of the live season.
    if "home_pen_goals" in master:
        live = master[(master.season == master.season.max()) & master.played
                      & master.home_goals.notna()]
        known = live[live.home_pen_goals.notna() & live.away_pen_goals.notna()]
        bad_pg = []
        for side in ("home", "away"):
            pg, gl = known[f"{side}_pen_goals"], known[f"{side}_goals"]
            taken = ((known[f"{side}_xg"] - known[f"{side}_npxg"]) / 0.785).round()
            bad_pg += list(known.index[(pg < 0) | (pg > gl) | (taken.notna() & (pg > taken))])
        tot = int(known.home_pen_goals.sum() + known.away_pen_goals.sum())
        check(len(known) >= 0.95 * len(live) and not bad_pg,
              f"penalty goals: {tot} in {len(known)} of {len(live)} played matches this season, none"
              f" more than the side scored or the penalties it took", f"{len(bad_pg)} impossible")
    else:
        print("  skip    penalty goals (a master table before the column)")

    print("\nsimulator")
    engine = Engine()
    check(engine.live_season() == int(master[master.played].season.max()),
          f"live season is {engine.live_season()}")
    # Every league side plays every other twice: 2(n-1) fixtures a season, which is the identity a
    # stale abandonment breaks. Fotmob files a replay as a NEW fixture and leaves the original
    # `aborted`, and until master_fixtures dropped replayed originals seven sides carried a phantom
    # match -- Marseille two of them, 40 in 2021. Numbered rounds only: a relegation play-off
    # (Spezia v Verona, 2023) has no round, and is a real 39th match.
    off = []
    for (c, s), g in master[(master.kind == "league") & master["round"].notna()].groupby(
            ["competition", "season"]):
        n = pd.concat([g.home, g.away]).value_counts()
        off += [f"{c} {s} {t}: {k}" for t, k in n.items() if k != 2 * (len(n) - 1)]
    check(not off, "every league side has exactly 2(n-1) fixtures in every season",
          f"{len(off)} off, e.g. " + ", ".join(off[:3]))
    prep = engine.prepare(2025)
    fx25 = prep["fixtures"]
    sim = simulate(fx25, prep["model"], prep["calib"], prep["elo0"],
                   np.random.default_rng(1), master=master,
                   **world_kwargs(prep, coerce_params({}, 2025)))
    real = fx25[fx25.played]
    mg = sim.merge(real, on=["competition", "season", "kickoff", "home", "away"],
                   suffixes=("_s", "_r"))
    bad = mg[(mg.home_goals_s != mg.home_goals_r.astype(int))
             | (mg.away_goals_s != mg.away_goals_r.astype(int))]
    check(len(mg) == len(real) and bad.empty,
          f"a finished season replays exactly ({len(mg)} rows, {len(bad)} mismatches)")
    check(not uefa_handovers(fx25, master, np.random.default_rng(0)),
          "a finished season needs no bracket built")

    print("\nprojection")
    check_europe_cases()
    params = coerce_params({"worlds": 60, "as_of": "2026-09-11", "seed": 3}, 2026)
    # Keep the already-required serial run's raw counts for the all-team what-if identity.
    # Restore the constructor before multiprocessing so worker import/pickling stays untouched.
    from scripts.projection import Accumulator
    captured = []
    captured_init = []
    sampled_worlds = {}
    sampled_sims = {}
    europe_expected = {}
    cup_expected, cup_stats = {}, {}
    original_init = Accumulator.__init__
    original_add = Accumulator.add
    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured.append(self)
        captured_init.append((args, kwargs))
    def capture_add(self, sim, *args, **kwargs):
        collect_cup_world(self, sim, cup_expected, cup_stats)
        world_index = kwargs.get("world_index", args[0] if args else self.worlds)
        world = sample_from_world(self, sim, world_index)
        for k, key in enumerate(("ucl", "uel", "uecl")):
            for team in world.get("europe", {}).get(key, []):
                europe_expected.setdefault(team, np.zeros(3, np.int32))[k] += 1
        if world_index is not None and 0 <= world_index < 10:
            sampled_sims[world_index] = sim
            sampled_worlds[world_index] = world
        return original_add(self, sim, *args, **kwargs)
    Accumulator.__init__ = capture_init
    Accumulator.add = capture_add
    try:
        a = run_projection(engine, params)
    finally:
        Accumulator.__init__ = original_init
        Accumulator.add = original_add
    check_score_counts(captured[-1], a)
    check_europe_counts(captured[-1], a, europe_expected)
    check_whatif(captured[-1], a)
    check_cup_stakes(captured[-1], a, cup_expected, cup_stats)
    expected_samples = [sampled_worlds[i] for i in range(5)]
    check_samples(a, expected_samples)
    check_sample_merge(*captured_init[-1], sampled_sims, expected_samples)
    check_rivals(*captured_init[-1], sampled_sims)
    sampled_sims.clear()
    # the live season's fixture list as it stands today, for the checks the rewind cannot see
    live_fx = engine.prepare(engine.live_season())["fixtures"]
    b = run_projection_parallel(params, 4, engine=engine)
    diffs = []
    for A, B in zip(a["leagues"], b["leagues"]):
        for x, y in zip(A["teams"], B["teams"]):
            for k in ("mean_pts", "p10", "p50", "p90", "p_win", "p_top4", "p_ucl", "p_uel", "p_uecl", "p_releg", "mean_pos"):
                if x[k] != y[k]:
                    diffs.append((x["team"], k))
    for U, V in zip(a["uefa"], b["uefa"]):
        for x, y in zip(U["teams"], V["teams"]):
            for k in ("p_top8", "p_mid", "p_out", "p_r16", "p_qf", "p_win", "mean_pts", "now"):
                if x.get(k) != y.get(k):
                    diffs.append((x["team"], k))
    check(not diffs and a["gw"] == b["gw"] and a["paths"] == b["paths"]
          and a["ratings"] == b["ratings"] and a["matches"] == b["matches"] and a.get("samples") == b.get("samples") and a.get("model") == b.get("model")
          and [L.get("rivals") for L in a["leagues"]] == [L.get("rivals") for L in b["leagues"]]
          and [L.get("entry_routes") for L in a["leagues"]] == [L.get("entry_routes") for L in b["leagues"]]
          and a.get("europe") == b.get("europe") and [L.get("qualification") for L in a["leagues"]] == [L.get("qualification") for L in b["leagues"]],
          "4 processes give the identical answer to 1, gameweek tables, their per-round ratings,"
          " match stakes, head-to-head, five indexed sample worlds, model stamp and UEFA paths included",
          f"{len(diffs)} differences" + ("" if a["gw"] == b["gw"] else "; gw payload differs")
          + ("" if a["matches"] == b["matches"] else "; matches differ")
          + ("" if a["paths"] == b["paths"] else "; paths differ")
          + ("" if a["ratings"] == b["ratings"] else "; ratings differ")
          + ("" if a.get("samples") == b.get("samples") else "; samples differ"))
    check_projection_head_to_head(a, master)
    # Stakes (version 10): each side's fates by a match's result. Every world produces one
    # result, so weighting P(fate | result) by the results' own chances gives back P(fate) -- the
    # projection's own TITLE, UCL, Europe, REL, top 8, top 24, R16 and Win -- for every side of
    # every projected league and league-phase fixture. A stake counted for the wrong side, the
    # wrong result or the wrong world's table breaks it.
    fate_of = {"title": lambda T: T["p_win"], "ucl": lambda T: T["p_ucl"],
               "euro": lambda T: T["p_ucl"] + T["p_uel"] + T["p_uecl"],
               "down": lambda T: T["p_releg"], "top8": lambda T: T["p_top8"],
               "top24": lambda T: 1 - T["p_out"], "r16": lambda T: T["p_r16"],
               "win": lambda T: T["p_win"]}
    rows_of = {B["competition"]: {t["team"]: t for t in B["teams"]} for B in a["leagues"] + a["uefa"]}
    st_worst, st_n, st_at = 0.0, 0, ""
    for comp, g in {**a["gw"]["leagues"], **a["gw"]["phases"]}.items():
        for f in g["fixtures"]:
            if f.get("result") or "stakes" not in f:
                continue
            po = [f["ladder"]["h1"], f["ladder"]["d"], f["ladder"]["a1"]]
            for side, team in enumerate((f["home"], f["away"])):
                for k, key in enumerate(g["stakes_of"]):
                    v = f["stakes"][side][k]
                    v = v if isinstance(v, list) else [v] * 3
                    off = abs(sum(po[o] * (v[o] or 0) for o in range(3))
                              - fate_of[key](rows_of[comp][team]))
                    st_n += 1
                    if off > st_worst:
                        st_worst, st_at = off, f"{comp} {f['home']} v {f['away']} {team} {key}"
    # four-place results, three-place stakes, four-place fates
    check(st_n > 1000 and st_worst < 2e-3,
          f"stakes: over {st_n} side-fates of every projected fixture, Σ P(result) P(fate | result)"
          f" = P(fate) (worst {st_worst:.4f})", st_at)
    # Ratings. ATT and DEF are read against the average side of the five leagues, which by
    # construction makes what it concedes: over the league sides their geometric means agree.
    # The history behind the Gameweek view refits each past round as the run fits today -- at the
    # run's own cutoff it must BE the run's fit -- and a round counts as real exactly when it
    # started by the cutoff, carrying that day's fit.
    from scripts.projection import fit_through, prepare_for, rating_history
    rl = [r for r in a["ratings"]["teams"] if r["league"]]
    gm = {k: float(np.exp(np.mean(np.log([r[k] for r in rl])))) for k in ("att", "def")}
    pa = prepare_for(engine, params)
    m2, _, _ = fit_through(engine, pa, pa["cutoff"], until=pd.Timestamp(params["as_of"]))
    dq = max(abs(m2["Q"][t] - pa["model"]["Q"][t]) for t in pa["model"]["Q"])
    hist = rating_history(engine, params)
    hist_off, n_real = [], 0
    for comp, g in {**a["gw"]["leagues"], **a["gw"]["phases"]}.items():
        days = hist["days"][comp]
        for at, d in enumerate(days):
            if (d <= hist["cutoff"]) != g["rating_real"][at]:
                hist_off.append(f"{comp} {at}")
            elif g["rating_real"][at]:
                n_real += 1
                hist_off += [f"{comp} {at} {t}" for i, t in enumerate(g["teams"])
                             if abs(g["elo"][i][at] - round(hist["fits"][d][t][0], 1)) > 1e-9]
    # the change windows (a week, a month ... back from the cutoff): a side with no match inside
    # one, and no Opta path to move it, must show exactly no Elo change over it -- and the rest,
    # which played, must mostly show some
    anchored = set(pa["unseen"].anchors) if pa.get("unseen") is not None else set()
    fxp, now_fit = pa["fixtures"], hist["fits"][hist["cutoff"]]
    still, wrong_w, played_w, moved_w, revised_w = 0, [], 0, 0, 0
    for k, _, day in hist["windows"]:
        # A newly eligible Opta observation can refit the movement calibration and hence
        # revise an earlier opponent's Elo. Separate that estimate revision from match moves.
        from scripts.opta_ratings import Unseen
        from scripts.simulate_season import elo_walk
        revised_unseen = Unseen(pa["opta"], day-pd.Timedelta(days=1), fxp.kickoff.max()) if pa.get("opta") else None
        revised_walk, _ = elo_walk(fxp, pa["elo_start"], day, revised_unseen)
        inside = fxp[fxp.played & (fxp.kickoff >= day) & (fxp.kickoff < hist["cutoff"])]
        active = set(inside.home) | set(inside.away)
        for t in hist["teams"]:
            d = now_fit[t][0] - hist["fits"][day][t][0]
            if t in active:
                played_w += 1
                moved_w += abs(d) > 1e-9
            elif t not in anchored:
                reference = revised_walk.get(t)
                if reference is None or abs(now_fit[t][0] - reference) > 1e-9:
                    wrong_w.append(f"{k} {t} {d:+.6f}")
                elif abs(d) > 1e-9:
                    revised_w += 1
                else:
                    still += 1
    check(hist["windows"] and still > 0 and not wrong_w and moved_w > 0.9 * played_w,
          f"rating windows ({', '.join(k for k, _, _ in hist['windows'])}): {still} side-windows"
          f" with no match keep their Elo exactly; {revised_w} reflect independent calibration revisions; "
          f"{moved_w} of {played_w} that played moved",
          f"{len(wrong_w)} moved without a match, e.g. {wrong_w[:3]}")
    # Each competition's own views read ATT and DEF against ITS average side (`comp_shift`): its
    # sides balance at every real round, and the payload carries every competition's factors
    own_off, n_own = 0.0, 0
    for comp, g in {**a["gw"]["leagues"], **a["gw"]["phases"]}.items():
        if g.get("rating_scale") != "competition":
            own_off = 1.0
            continue
        for at, real in enumerate(g["rating_real"]):
            if real:
                n_own += 1
                ga_ = float(np.exp(np.mean(np.log([r[at] for r in g["att"]]))))
                gd_ = float(np.exp(np.mean(np.log([r[at] for r in g["def"]]))))
                own_off = max(own_off, abs(ga_ / gd_ - 1))
    # goals against xG: every match counted for both sides, so a competition's totals balance,
    # and a league side's goals are its real table's
    g_off, g_n, g_tab = 0.0, 0, []
    for blk in a["leagues"] + a["uefa"]:
        rr = [t["real"] for t in blk["teams"] if t.get("real")]
        if not rr:
            continue
        g_n += 1
        for x, y in (("gf", "ga"), ("xg", "xga"), ("xgot", "xgota"), ("pens", "pens_a")):
            g_off = max(g_off, abs(sum(r[x] for r in rr) - sum(r[y] for r in rr)))
        if blk in a["leagues"]:
            g_tab += [t["team"] for t in blk["teams"] if t.get("real") and t["real"]["pl"] == t["now"]["pl"]
                      and (t["real"]["gf"], t["real"]["ga"]) != (t["now"]["gf"], t["now"]["ga"])]
    # every competition that has played a match by the cutoff carries them (6 of 8 at 11 Sep)
    g_want = sum(1 for blk in a["leagues"] + a["uefa"]
                 if any((t.get("now") or {}).get("pl") for t in blk["teams"]))
    check(g_n == g_want and g_n > 0 and g_off < 0.2 and not g_tab,
          f"goals v xG: in all {g_n} competitions played so far goals for = against, xG = xGA, xGOT = xGOTA and"
          f" penalties taken = faced (worst {g_off:.2f}); league goals are the table's",
          f"worst {g_off:.2f}; {len(g_tab)} sides differ from the table")
    # xG by round: xG for = xG against at every round over a block, and at the last round played
    # in full each side's run totals are its played matches' own xG and xG points
    x_bal, x_real, x_n = 0.0, 0.0, 0
    for comp, gb in {**a["gw"]["leagues"], **a["gw"]["phases"]}.items():
        if "xgf" not in gb:
            continue
        x_n += 1
        for at in range(gb["rounds"] + 1):
            x_bal = max(x_bal, abs(sum(r[at] for r in gb["xgf"]) - sum(r[at] for r in gb["xga"])))
        full = 0
        for rr in range(1, gb["rounds"] + 1):
            fr = [f for f in gb["fixtures"] if f["round"] == rr]
            if fr and all(f.get("result") for f in fr):
                full = rr
            else:
                break
        for i, team in enumerate(gb["teams"]):
            mine = [f for f in gb["fixtures"] if f.get("xpts") and f["round"] <= full and team in (f["home"], f["away"])]
            sp = sum(f["xpts"][0] if f["home"] == team else f["xpts"][1] for f in mine)
            x_real = max(x_real, abs(sp - gb["xgpts"][i][full]))
    check(x_n >= 6 and x_bal < 0.2 and x_real < 0.06,
          f"xG by round: in {x_n} blocks xG for = against at every round (worst {x_bal:.2f}); real rounds"
          f" carry their matches' xG points (worst {x_real:.3f})", f"blocks {x_n}")
    rel_ok = set(a["ratings"].get("rel", {})) == (set(a["gw"]["leagues"]) | set(a["gw"]["phases"])
              | set(pa["fixtures"].loc[pa["fixtures"].kind == "cup", "competition"]))
    check(n_own > 0 and own_off < 2e-3 and rel_ok,
          f"own scale: at {n_own} real rounds every competition's sides balance against its own"
          f" average side (worst {own_off:.1e}); every competition carries its factors",
          f"worst {own_off:.2e}, factors for every competition {rel_ok}")
    check(len(rl) >= 90 and abs(gm["att"] / gm["def"] - 1) < 2e-3 and dq < 1e-9 and n_real > 0
          and not hist_off,
          f"ratings: the average side makes what it concedes (ATT {gm['att']:.3f}, DEF"
          f" {gm['def']:.3f}); the history's refit at the cutoff is the run's fit (|dQ| {dq:.0e});"
          f" {n_real} real rounds carry their day's fit",
          f"{len(hist_off)} rounds off, e.g. {hist_off[:3]}")
    check(all(abs(sum(t["dist"]) - 1) < 2e-3 for L in a["leagues"] for t in L["teams"]),
          "every position distribution sums to 1")
    # each round has a fixed number of entrants, so the reach probabilities must sum to it. This
    # is what caught a shared nested dict handing every team the same `reach` counter.
    want = {"p_po": 16, "p_r16": 16, "p_qf": 8, "p_sf": 4, "p_f": 2, "p_win": 1}
    off = [f"{u['competition'].split()[1]} {k}={sum(t[k] for t in u['teams']):.3f} want {v}"
           for u in a["uefa"] for k, v in want.items()
           if abs(sum(t[k] for t in u["teams"]) - v) > 0.01 * max(v, 1)]
    check(not off, "every UEFA round's reach probabilities sum to its number of entrants",
          "; ".join(off[:4]))
    # The league phase splits every side's finish three ways, and in every world exactly 8 / 16
    # / 12 sides land in each part. The knockout path is two counts per opponent, so over a
    # round's opponents P(meet) x P(through | met) is exactly the chance of going through it --
    # the next round's reach, less P(top 8) for the play-off the top eight skip.
    nxt = {"PO": "p_r16", "R16": "p_qf", "QF": "p_sf", "SF": "p_f", "F": "p_win"}
    zone_off, path_off, n_path = [], 0.0, 0
    for u in a["uefa"]:
        zs = [sum(t[k] for t in u["teams"]) for k in ("p_top8", "p_mid", "p_out")]
        if max(abs(zs[0] - 8), abs(zs[1] - 16), abs(zs[2] - (len(u["teams"]) - 24))) > 0.01:
            zone_off.append(f"{u['competition']} {[round(z, 2) for z in zs]}")
        teams = a["paths"]["competitions"][u["competition"]]["teams"]
        for t in u["teams"]:
            for stage, blk in teams.get(t["team"], {}).items():
                got = sum(m * q for _, m, q in blk["top"]) + (
                    blk["other"][0] * blk["other"][1] if blk["other"] else 0.0)
                want = t[nxt[stage]] - (t["p_top8"] if stage == "PO" else 0.0)
                path_off = max(path_off, abs(got - want))
                n_path += 1
    check(not zone_off and n_path > 0 and path_off < 2e-3,
          f"UEFA league phases split 8 / 16 / 12, and every knockout path accounts for its"
          f" round ({n_path} side-rounds, worst {path_off:.4f})",
          "; ".join(zone_off) or f"path identity off by {path_off:.4f}")
    # One champion per competition per world, so the expected hauls sum to the number decided --
    # exact, whatever the model does. And every league and league phase says what it takes.
    tro = a["trophies"]
    decided = len(a["leagues"]) + len(a["uefa"]) + len(a["cups"])
    t_sum = sum(t["mean"] for t in tro["teams"]) + tro.get("others", {}).get("mean", 0.0)
    lines_ok = (all(len(b.get("lines", [])) >= 3 for b in a["leagues"])
                and all(len(b.get("lines", [])) == 2 for b in a["uefa"]))
    check(abs(tro["per_world"] - decided) < 1e-9 and abs(t_sum - decided) < 0.01 and lines_ok,
          f"trophies: expected hauls sum to {t_sum:.3f}, the {decided} competitions decided;"
          f" every table carries its points lines",
          f"per_world {tro['per_world']}, sum {t_sum:.3f}, lines {lines_ok}")
    ph = a["gw"].get("phases", {})
    ph_off = [c for c, g in ph.items()
              if abs(sum(r[-1] for r in g["w"]) - sum(r[-1] for r in g["l"])) > 0.5
              or abs(sum(r[-1] for r in g["gf"]) - sum(r[-1] for r in g["ga"])) > 0.5]
    check(len(ph) == len(a["uefa"]) and not ph_off,
          f"every UEFA league phase has a matchday table that balances ({len(ph)})",
          f"phases {sorted(ph)}; off {ph_off}")
    # Domestic cups. The same identity as UEFA, but the round sizes are not a fixed list: a cup's
    # calendar decides them, and a preliminary round is a side door into the round it feeds rather
    # than double its size. So each round is checked against HALF the one before it, and the last
    # against 2 -- a final has two teams in it, whatever the cup.
    cup_off = []
    for c in a["cups"]:
        sums = [sum(t[f"p_{r.lower()}"] for t in c["teams"]) for r in c["rounds"]]
        name = c["competition"]
        if abs(sums[-1] - 2) > 0.01:
            cup_off.append(f"{name} final={sums[-1]:.2f} want 2")
        if abs(sum(t["p_win"] for t in c["teams"]) - 1) > 0.005:
            cup_off.append(f"{name} win={sum(t['p_win'] for t in c['teams']):.3f} want 1")
        for i in range(1, len(sums)):
            if c["rounds"][i - 1].startswith("PR"):
                continue
            if abs(sums[i - 1] - 2 * sums[i]) > 0.02 * max(sums[i - 1], 1):
                cup_off.append(f"{name} {c['rounds'][i-1]}={sums[i-1]:.2f} "
                               f"want 2x{sums[i]:.2f}")
    check(a["cups"] and not cup_off,
          f"every cup round's reach probabilities sum to its number of entrants "
          f"({len(a['cups'])} cups)", "; ".join(cup_off[:4]))
    # A cup we hold rules for either ran or said why not. Silence is what let three hand-made
    # fixture files stand in for competitions that had not been drawn.
    from scripts.cup_bracket import CUP_RULES
    accounted = ({c["competition"] for c in a["cups"]}
                 | {c["competition"] for c in a["cups_pending"]})
    check(accounted == set(CUP_RULES),
          f"all {len(CUP_RULES)} cups are either projected or explained",
          f"unaccounted: {sorted(set(CUP_RULES) - accounted)}")
    # The strongest check available on the cup engine: for a cup with NO extra time, a team's
    # chance of reaching the next round is exactly its chance of winning the tie, and the tie is
    # decided by 90 minutes plus a coin. So
    #
    #     P(reach next round)  ==  P(win in 90)  +  P(draw) / 2
    #
    # where the left side comes from the tournament simulation and the right from the per-match
    # scoreline table. Those are separate code paths over the same worlds -- the ladder is a
    # histogram of sampled scorelines, the reach count is who the bracket runner advanced -- so
    # agreement to Monte-Carlo error means the draw, the shootout and the accumulation all line up.
    # Extra time breaks the identity (it is 30 more minutes for the better side, not a coin), so
    # only the cups measured as going straight to penalties are checked.
    # each team's EARLIEST tie: that is the one deciding its next round. When the round after is
    # already drawn, both ties are in the payload, and keying on whichever came last compared a
    # side's chance of reaching round four with its round-four tie (Aston Villa, 2026-10-21).
    side = {}
    for f in sorted(a["matches"]["fixtures"], key=lambda f: str(f.get("kickoff", ""))):
        L = f["ladder"]
        side.setdefault((f["competition"], f["home"]), (L["h1"], L["d"]))
        side.setdefault((f["competition"], f["away"]), (L["a1"], L["d"]))
    devs, worst = [], ("", 0.0)
    for c in a["cups"]:
        if _CR[c["competition"]].extra_time:
            continue
        for t in c["teams"]:
            got = side.get((c["competition"], t["team"]))
            if got is None:
                continue                       # next tie not drawn, or outside the match window
            # the round this team's next tie DECIDES: the first one it has neither already reached
            # nor been knocked out of. Keying on rounds[0] instead made this check VACUOUS -- that
            # round is the one being played, which every surviving team has p=1 for, so nothing
            # was ever compared and it passed on an empty set.
            nxt = next((f"p_{r.lower()}" for r in c["rounds"] if 0 < t[f"p_{r.lower()}"] < 1), None)
            if nxt is None:
                continue
            d = t[nxt] - (got[0] + got[1] / 2)
            devs.append(d)
            if abs(d) > abs(worst[1]):
                worst = (f"{c['competition']} {t['team']} {nxt}={t[nxt]:.3f} "
                         f"vs W+D/2={got[0] + got[1] / 2:.3f}", d)
    # Both sides are estimates from the same finite set of worlds, so they agree only to
    # Monte-Carlo error -- and smoke runs 60 worlds, where one standard error is 0.065. A fixed
    # tolerance is therefore either useless here or false at 10,000 worlds. The test is on the
    # MEAN deviation instead, whose standard error shrinks with the number of teams as well: a
    # systematic fault (dropping the D/2, say, which is worth ~0.12) shows up in the mean, while
    # per-team noise cancels. The per-team bound stays as a loose sanity rail.
    #
    # Measured detection power, by injecting the fault and re-running the arithmetic:
    #   shootout dropped entirely (mean -0.1221)   caught at 60 worlds AND at 10,000
    #   shootout given a 0.6 home edge (+0.0244)   caught at 10,000, invisible at 60
    # So smoke catches a broken shootout; catching a merely biased one needs a nightly run.
    se = (0.25 / max(a["worlds"], 1)) ** 0.5
    n_t = len(devs)
    mean_dev = sum(devs) / n_t if n_t else 0.0
    ok_mean = n_t and abs(mean_dev) <= max(4 * se / (n_t ** 0.5), 0.002)
    ok_each = all(abs(d) <= 6 * se for d in devs)
    check(n_t >= 10 and ok_mean and ok_each,
          f"P(reach the next round) == P(win in 90) + P(draw)/2 over {n_t} teams whose level tie"
          f" is a coin (mean {mean_dev:+.4f}, 1se {se:.4f})",
          f"only {n_t} teams" if n_t < 10 else f"mean {mean_dev:+.4f}; worst {worst[0]}")

    # No bracket slot ever reaches a team list. "Winner EF1" once did, and played a match in
    # every world at the 5th-percentile default rating -- and so, until 20 Oct 2026, did eleven
    # FA Cup places like "Harrogate Town/Bury", which a prefix test could not see.
    from scripts.cup_bracket import is_slot
    slots = [t["team"] for c in a["cups"] for t in c["teams"] if is_slot(t["team"])]
    check(not slots, "no bracket slot is being treated as a club", ", ".join(slots[:4]))
    # A club in a country's top flight that has not played in that country's cup yet is still in
    # it, so it must be in the projection. The FA Cup ran for a day with none of the twenty
    # Premier League sides, who enter at the third round and were in no fixture yet.
    absent = []
    for c in a["cups"]:
        country = c["competition"].split()[0] + " "
        lg = live_fx[(live_fx.kind == "league") & live_fx.competition.str.startswith(country)]
        cup = live_fx[(live_fx.competition == c["competition"]) & live_fx.played]
        named = {t["team"] for t in c["teams"]}
        absent += [f"{c['competition']}: {t}" for t in sorted(set(lg.home) | set(lg.away))
                   if t not in set(cup.home) | set(cup.away) and t not in named]
    check(not absent, "every top-flight club still to play its cup is in that cup's projection",
          f"{len(absent)} missing, e.g. " + ", ".join(absent[:3]))

    mp = a["matches"]
    # 3e-4, not 1e-9: the ladder is stored rounded to four places, so three of them can only sum
    # to 1 within 1.5e-4. Tightening this past the stored precision fails on world counts whose
    # reciprocal does not round exactly, which is most of them.
    lad_ok = all(abs(f["ladder"]["h1"] + f["ladder"]["d"] + f["ladder"]["a1"] - 1) < 3e-4
                 for f in mp["fixtures"])
    # A league or UEFA fixture is played in every world. A cup tie in a later round is played only
    # in the worlds where both its sides get there -- rewound to September, "Fleetwood Town v
    # Arsenal" in the EFL Cup's round of 16 waits on a third round not yet played -- so it must be
    # counted in at least one world and at most all, and its ladder is conditional on it happening.
    n_ok = all(f["n"] == a["worlds"] if f.get("kind") != "cup" else 0 < f["n"] <= a["worlds"]
               for f in mp["fixtures"])
    check(lad_ok and mp["fixtures"] and n_ok,
          f"per-match ladders sum to 1 across {len(mp['fixtures'])} next-round fixtures")
    # A clean sheet is the other side scoring nothing, so it needs a win or a draw, and with BTTS
    # the two give P(0-0) exactly -- cs_h + cs_a + btts - 1 -- which is itself a draw. Swapping
    # cs_h and cs_a, or reading both off the same margin of the table, breaks the first two on any
    # lopsided fixture. Same 3e-4 as above: three values each rounded to four places.
    cs_off = [f"{f['home']} v {f['away']}" for f in mp["fixtures"]
              if not (f["cs_h"] <= f["ladder"]["h1"] + f["ladder"]["d"] + 3e-4
                      and f["cs_a"] <= f["ladder"]["a1"] + f["ladder"]["d"] + 3e-4
                      and -3e-4 <= f["cs_h"] + f["cs_a"] + f["btts"] - 1
                      <= f["ladder"]["d"] + 3e-4)]
    check(not cs_off, f"clean sheets agree with the ladder and BTTS across "
                      f"{len(mp['fixtures'])} fixtures",
          f"{len(cs_off)} off, e.g. " + ", ".join(cs_off[:3]))
    comps = {f["competition"] for f in mp["fixtures"]}
    # Every league side must have an upcoming fixture in its OWN competition, or the dashboard's
    # Next Opp. column reads "no fixture" for it. A part-played round is the case that breaks this:
    # the next round is the round of the earliest unplayed fixture, so it holds only that round's
    # leftovers and every side already through it drops out. At MATCH_ROUNDS=1 on a part-played
    # Sunday this covered 6 of 20 Premier League teams while the page still rendered perfectly.
    nxt = pd.DataFrame(mp["fixtures"])
    uncovered = []
    for L in a["leagues"]:
        c = nxt[nxt.competition == L["competition"]] if len(nxt) else nxt
        have = set(c.home) | set(c.away) if len(c) else set()
        uncovered += [f"{L['competition']}:{t['team']}" for t in L["teams"]
                      if t["team"] not in have]
    check(not uncovered, "every league team has a next fixture in its own competition",
          f"{len(uncovered)} without one, e.g. " + ", ".join(uncovered[:4]))
    # ...but that run is rewound to September, so it never sees what the live season is doing. On
    # 20 Oct 2026 a postponed round-6 game and the abandoned round-8 one were La Liga's two lowest
    # rounds, and 17 of 20 sides had no next fixture on the live page while this passed. So: the
    # same shape, built by hand, and the live fixture list itself, which needs no simulation.
    from scripts.projection import match_horizon, next_round_fixtures, upcoming
    syn = pd.DataFrame({"competition": "L", "played": False, "outcome": None, "tbd": False,
                        "round": [6, 8, 10, 10, 10],
                        "kickoff": pd.to_datetime(["2026-10-21", "2026-10-10", "2026-10-24",
                                                   "2026-10-24", "2026-10-25"]),
                        "home": ["A", "C", "A", "B", "D"], "away": ["B", "D", "C", "E", "F"]})
    syn.loc[1, "outcome"] = "aborted"
    kept = sorted(next_round_fixtures(syn))
    check(kept == [0, 2, 3, 4] and match_horizon(syn) == pd.Timestamp("2026-11-11"),
          "a postponed game and an abandoned one do not stand in for the next round",
          f"kept rows {kept}, horizon {match_horizon(syn):%Y-%m-%d}")
    tracked = live_fx.loc[next_round_fixtures(live_fx)]
    gaps = []
    for comp, g in live_fx[(live_fx.kind == "league") & upcoming(live_fx)].groupby("competition"):
        t = tracked[tracked.competition == comp]
        gaps += [f"{comp}:{s}" for s in sorted(set(g.home) | set(g.away))
                 if s not in set(t.home) | set(t.away)]
    check(not gaps, "on today's fixtures, every league side with a match left has a next one",
          f"{len(gaps)} without, e.g. " + ", ".join(gaps[:4]))
    # The bound is for the whole season leaking in (~2,000 fixtures), not for a big cup round:
    # 400 dated from before three cups were drawn, and the Coupe de France's sixth round alone is
    # 143 ties, so with every cup under way the next rounds hold ~470.
    check(len(comps) >= 5 and len(mp["fixtures"]) < 800,
          f"per-match detail covers {len(comps)} competitions and stays small "
          f"({len(mp['fixtures'])} fixtures)")
    # ---- the sides we do not see every match of (scripts/opta_ratings.py). Every league or UEFA
    # side outside the five leagues must be on an Opta path, or it stands still between its
    # appearances again; and beta, which turns Opta's movement into our walk's, must rest on
    # enough sides seen both ways to mean something.
    import scripts.simulate_season as ss_mod
    from scripts.cup_bracket import is_slot as _slot
    from scripts.projection import unseen_for
    art = engine.prepare(engine.live_season())["opta"]
    five = live_fx[live_fx.competition.isin(["English Premier League", "Spanish La Liga",
                                             "Italian Serie A", "German Bundesliga",
                                             "French Ligue 1"])]
    watched = set(five.home) | set(five.away)
    elsewhere = {t for t in set(live_fx[live_fx.kind != "cup"].home)
                 | set(live_fx[live_fx.kind != "cup"].away) if t not in watched and not _slot(t)}
    off_path = sorted(elsewhere - set((art or {}).get("teams", {})))
    check(art is not None and not off_path and art["beta_fit"]["clubs"] >= 50
          and art["beta_fit"]["corr"] >= 0.5,
          f"every league/UEFA side outside the five leagues is on an Opta path "
          f"({len(elsewhere)}); beta {art and art['beta']} on {art and art['beta_fit']['clubs']} "
          f"clubs, corr {art and art['beta_fit']['corr']}",
          "no artefact -- run scripts/opta_ratings.py" if art is None else
          f"off path: {off_path[:4]}; fit {art['beta_fit']}")
    # The past is history. A world starts at the data cutoff from the fit through it and the Elo
    # walk to it, so two worlds over the played matches end exactly where they began, Opta paths
    # and all -- and the walk must be what the in-world replay rule gives, or the start each world
    # is handed and the fit's prior would describe a different past from the one it records.
    worlds = []
    _init = ss_mod._World.__init__

    def grab(self, *a, **k):
        _init(self, *a, **k)
        worlds.append(self)
    ss_mod._World.__init__ = grab
    try:
        lp = engine.prepare(engine.live_season())
        lparams = coerce_params({}, engine.live_season())
        u = unseen_for(lp, live_fx, lparams)
        played = live_fx[live_fx.played]
        for s in (1, 2):
            ss_mod.simulate(played, lp["model"], lp["calib"], lp["elo0"], np.random.default_rng(s),
                            master=master, unseen=u, build_knockouts=False,
                            **world_kwargs(lp, lparams))
        moved = sorted(u.anchors)
        same = all(w.elo == lp["elo0"] and not any(w.q_shift.values()) and not w.t_shift
                   for w in worlds[:2])
        # the legacy path: a world from the season start that replays every played result
        worlds.clear()
        ss_mod.simulate(played, lp["model"], lp["calib"], lp["elo_start"],
                        np.random.default_rng(0), master=master, build_knockouts=False)
        walk, _ = ss_mod.elo_walk(live_fx, lp["elo_start"], lp["cutoff"], None)
        diff = [t for t in walk if abs(worlds[0].elo.get(t, np.nan) - walk[t]) > 1e-9]
        rows = [len(ss_mod.simulate(live_fx, lp["model"], lp["calib"], lp["elo0"],
                                    np.random.default_rng(3), master=master, unseen=x,
                                    **world_kwargs(lp, lparams)))
                for x in (u, None)]
    finally:
        ss_mod._World.__init__ = _init
    check(same, f"every world reaches the cutoff with the walk's ratings and nothing accrued "
                f"({len(moved)} sides on Opta paths)")
    check(not diff and len(walk) > 300,
          f"the Elo walk is the in-world replay rule ({len(walk)} sides, {len(diff)} differ)",
          ", ".join(diff[:4]))
    mdl = lp["model"]
    pri = [t for t in mdl["teams"] if t in lp["elo0"] and abs(
        mdl["q_prior"][t] - mdl["slope"] * (lp["elo0"][t] - mdl["elo_mean"]) / 200.0) > 1e-9]
    check(not pri, f"the fit's prior is the walk's rating at the cutoff ({lp['cutoff']:%Y-%m-%d})",
          ", ".join(pri[:4]))
    check(rows[0] == rows[1], f"unseen matches move sides but add no rows ({rows[0]} either way)",
          f"{rows[0]} with, {rows[1]} without")

    # What a match moves. The same 0-1 home defeat, once while winning the npxG 2.5-0.5 and once
    # while losing it 0.5-2.5: the rating falls identically (results only), strength falls far
    # less -- or rises -- in the first, and an open game tilts both sides towards attack.
    w = ss_mod._World(mdl, lp["calib"], lp["elo0"], np.random.default_rng(0), drift_per_day=0.0,
                      feedback=True, npxg_feedback=True, npxg_gain=lparams["npxg_gain"], rho=-0.10,
                      goals=lp["goals"], live_from=lp["live_from"], seed_elo=lp["seed_elo"])
    lg = live_fx[live_fx.competition == "English Premier League"]
    top = max(set(lg.home), key=lambda t: mdl["Q"].get(t, -9))
    low = min(set(lg.home), key=lambda t: mdl["Q"].get(t, 9))
    rates = w.rates("English Premier League", top, low)
    out = {}
    for label, npxg in (("won npxG", (2.5, 0.5)), ("outplayed", (0.5, 2.5)), ("open", None)):
        w.q_shift, w.t_shift, w.elo = {}, {}, dict(lp["elo0"])
        if npxg is None:
            npxg = (rates[0] + 1.0, rates[1] + 1.0)
        w._feedback("English Premier League", top, low, 0, 1, rates, npxg=npxg, neutral=False,
                    uefa=False)
        out[label] = (w.elo[top] - lp["elo0"][top], w.q_shift.get(top, 0.0),
                      w.t_shift.get(top, 0.0), w.t_shift.get(low, 0.0))
    won, beaten, op = out["won npxG"], out["outplayed"], out["open"]
    check(abs(won[0] - beaten[0]) < 1e-12 and won[0] < 0 and won[1] > beaten[1] + 0.05
          and op[2] > 0 and op[3] > 0,
          f"{top} 0-1 {low}: rating {won[0]:+.1f} either way; strength {won[1]:+.3f} winning the "
          f"npxG vs {beaten[1]:+.3f} outplayed; an open game tilts both to attack",
          f"won {won}, outplayed {beaten}, open {op}")
    # A side the fit does not rate takes its strength from its rating ONCE, when the world takes
    # over; a later rating move reaches it only through the shift. It used to be re-read off the
    # live rating while the same move was also added to the shift -- every Elo step twice.
    w._touch("Nowhere Athletic")
    q0 = w._state("Nowhere Athletic")[0]
    w.elo["Nowhere Athletic"] = w.elo.get("Nowhere Athletic", w.seed_elo) + 100.0
    check(w._state("Nowhere Athletic")[0] == q0,
          "an unrated side's strength is fixed at takeover, not re-read off its rating")
    # And no drift: under the world's own draw every surprise averages zero, so a re-simulated
    # season must not systematically strengthen its favourites. The log-ratio surprise did: a
    # slope of +0.23 of end-of-season shift on starting Q, Arsenal +0.17 against a world SD 0.20.
    p25 = engine.prepare(2025, from_start=True)
    epl = p25["fixtures"][p25["fixtures"].competition == "English Premier League"]
    fitted = sorted(t for t in set(epl.home) if t in p25["model"]["Q"])
    shifts = []
    ss_mod._World.__init__ = grab
    try:
        worlds.clear()
        for s in range(80):
            ss_mod.simulate(epl, p25["model"], p25["calib"], p25["elo0"],
                            np.random.default_rng(s), replay_played=False, build_knockouts=False,
                            npxg_gain=lparams["npxg_gain"], goals=p25["goals"],
                            q_half_life=lparams["q_half_life"])
        shifts = np.array([[x.q_shift.get(t, 0.0) for t in fitted] for x in worlds])
    finally:
        ss_mod._World.__init__ = _init
    q0s = np.array([p25["model"]["Q"][t] for t in fitted])
    slope = float(np.polyfit(q0s - q0s.mean(), shifts.mean(0), 1)[0])
    check(abs(slope) < 0.06, f"no favourite drift: end-of-season shift on starting Q, slope "
                             f"{slope:+.3f} over 80 re-simulated EPL 2025s")
    # The result channel's expected points come off a precomputed grid; it must be the
    # Dixon-Coles computation it replaces, or the channel stops averaging zero.
    from scripts.backtest_qt import score_matrix
    g = np.random.default_rng(0).uniform(0.05, 4.5, (500, 2))
    ep_err = max(abs(ss_mod.expected_points(h, a_) - float(
        np.tril(M, -1).sum() + 0.5 * np.trace(M)))
        for (h, a_), M in zip(g, score_matrix(g[:, 0], g[:, 1], ss_mod.GOAL_RHO)))
    check(ep_err < 5e-4, f"the expected-points grid is the direct computation (max err {ep_err:.1e})")
    # The two-stage match: a world's goals are drawn from its npxG
    sim_live = ss_mod.simulate(live_fx, lp["model"], lp["calib"], lp["elo0"],
                               np.random.default_rng(5), master=master, unseen=u,
                               **world_kwargs(lp, lparams))
    smp = sim_live[sim_live.sampled]
    rgx = float(np.corrcoef(np.r_[smp.home_goals, smp.away_goals],
                            np.r_[smp.home_npxg, smp.away_npxg])[0, 1])
    check(len(smp) > 500 and rgx > 0.45,
          f"drawn goals follow drawn npxG (corr {rgx:.2f} over {len(smp)} matches)")
    # A world's ratings leave it beside its rows (`attrs["state"]`) and must be the world's own:
    # NaN exactly on the replayed rows; every simulated match moving Elo and Q by equal and
    # opposite amounts and T by the same for both sides; and a side starting each match exactly
    # where it finished the last -- moves stick, asserted, not assumed.
    st = sim_live.attrs["state"]
    samp = sim_live.sampled.to_numpy(bool)
    S = st[samp]
    nan_ok = st.shape == (len(sim_live), 12) and bool(np.array_equal(np.isnan(st[:, 0]), ~samp))
    zero_sum = max(float(np.abs((S[:, 6] - S[:, 0]) + (S[:, 9] - S[:, 3])).max()),
                   float(np.abs((S[:, 7] - S[:, 1]) + (S[:, 10] - S[:, 4])).max()),
                   float(np.abs((S[:, 8] - S[:, 2]) - (S[:, 11] - S[:, 5])).max()))
    five = set(live_fx[live_fx.kind == "league"].home)
    last, pairs, carry = {}, 0, 0.0
    for row, x in zip(sim_live[samp].itertuples(), S):
        for team, pre, post in ((row.home, x[0:2], x[6:8]), (row.away, x[3:5], x[9:11])):
            if team in five and team in last:
                carry = max(carry, float(np.abs(pre - last[team]).max()))
                pairs += 1
            last[team] = post
    check(nan_ok and zero_sum < 1e-9 and pairs > 1000 and carry < 1e-9,
          f"a world's recorded ratings are its own: each match moves Elo and Q equal and opposite"
          f" and T alike (worst {zero_sum:.0e}); over {pairs} consecutive matches a side starts"
          f" where it finished (worst {carry:.0e})",
          f"nan pattern {nan_ok}, zero-sum {zero_sum:.2e}, carry {carry:.2e}")
    rewound = run_projection(engine, coerce_params({"worlds": 20, "as_of": "2026-08-18"}, 2026))
    check(rewound["as_of"] < a["as_of"],
          f"the as-of rewind moves the data cutoff ({rewound['as_of']} vs {a['as_of']})")

    print("\nsnapshots")
    check_dashboard_store()
    centre_check = subprocess.run([sys.executable, 'scripts/check_match_centre.py'], cwd=ROOT,
                                  text=True, capture_output=True, timeout=120)
    print(centre_check.stdout.strip())
    check(centre_check.returncode == 0, 'Match Centre: independent source identities/xG/xA/assists/scores,4 deliberate faults and6 cutoff/identity cases; model imports blocked', centre_check.stderr.strip())
    atlas_check=subprocess.run([sys.executable,'scripts/check_atlas.py'],cwd=ROOT,text=True,capture_output=True,timeout=120)
    print(atlas_check.stdout.strip())
    check(atlas_check.returncode==0,'Atlas:6 clubs,exact cutoff/source shot identities and geometry,3 deliberate faults,3 cutoff/club guards',atlas_check.stderr.strip())
    with tempfile.TemporaryDirectory() as tmp:
        day = "2026-09-11"

        (Path(tmp) / day).mkdir()
        (Path(tmp) / day / "projection.json").write_text(json.dumps(a))
        (Path(tmp) / "index.json").write_text(json.dumps([{"date": day}]))
        s = Snapshots(Path(tmp))
        back = s.load()
        check(back is not None and back["worlds"] == a["worlds"], "a snapshot round-trips")
        hist = s.history(2026)
        check(hist["dates"] == [day] and hist["competitions"], "history reads a snapshot")
        source_bytes = (Path(tmp) / day / "projection.json").read_bytes()
        check(back["source"]["projection_sha256"] == hashlib.sha256(source_bytes).hexdigest(),
              "workspace evidence: forecast fingerprint equals exact stored projection bytes; no bundle-manifest claim")
        # every metric the dashboard charts over time must actually be in the series, for each
        # KIND of tab -- a missing key draws an empty panel, not an error. UEFA has no
        # league-phase points table, so mean_pts is a league metric only; a cup has neither a
        # table nor a points total, so its only series is the one thing it has, P(win it).
        cup_names = {c["competition"] for c in a["cups"]}
        want = {"mean_pos": ("league", "uefa"), "mean_pts": ("league",),
                "p_win": ("league", "uefa", "cup")}
        missing = [f"{c}:{team}:{k}"
                   for c, teams in hist["competitions"].items()
                   for kind in ["cup" if c in cup_names
                                else ("uefa" if c.startswith("UEFA") else "league")]
                   for k, kinds in want.items() if kind in kinds
                   for team, t in teams.items()
                   if not any(v is not None for v in t.get(k, []))]
        check(not missing, f"all {len(want)} charted history metrics are in every team's series",
              f"{len(missing)} gaps, e.g. " + ", ".join(missing[:4]))
    # All four league fate histories must equal the stored probabilities, including null gaps.
    live_fates = Snapshots()
    fate_history = live_fates.history(2026)
    fate_cells = 0
    fate_equal = True
    for i, date in enumerate(fate_history["dates"]):
        source = live_fates.load(date)
        for block in source["leagues"]:
            for team in block["teams"]:
                series = fate_history["competitions"][block["competition"]][team["team"]]
                for metric in ("p_ucl", "p_uel", "p_uecl", "p_releg"):
                    expected = team.get(metric, team.get("p_top4") if metric == "p_ucl" else None)
                    fate_equal &= series.get(metric, [])[i:i+1] == [expected]
                    fate_cells += 1
    check(fate_equal and fate_cells > 0,
          f"qualification history: {fate_cells} UCL/UEL/UECL/REL values across {len(fate_history['dates'])} snapshots equal source files exactly")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        days = ["2026-08-22", "2026-08-23", "2026-08-24"]
        for i, date in enumerate(days):
            teams = [{"team": "Alpha", "p_win": .2, "p_releg": 0, "mean_pts": 50, "mean_pos": 5}]
            if i != 1:
                teams[0].update(p_uel=[0, None, .3][i], p_uecl=[.1, None, 0][i])
            if i:
                teams.append({"team": "Beta", "p_win": 0, "p_releg": .2, "mean_pts": 20, "mean_pos": 10, "p_uecl": None if i == 1 else 0})
            p = {"worlds": 2, "params": {"season": 2026}, "leagues": [{"competition": "Test League", "teams": teams}], "uefa": [], "cups": []}
            (root / date).mkdir()
            (root / date / "projection.json").write_text(json.dumps(p))
        (root / "index.json").write_text(json.dumps([{"date": d} for d in days]))
        history = Snapshots(root).history(2026)["competitions"]["Test League"]
        expected = {"Alpha": {"p_uel": [0, None, .3], "p_uecl": [.1, None, 0]},
                    "Beta": {"p_uel": [None, None, None], "p_uecl": [None, None, 0]}}
        check(all(history[t][k] == values for t, metrics in expected.items() for k, values in metrics.items()),
              "qualification history gaps: 12 UEL/UECL slots preserve leading/middle missing fields and explicit zero probabilities for2 clubs/3 dates")
    check_track_record()
    check_team_data()
    check_gw_compression()
    check_head_to_head()
    check_cup_reference()
    check_player_data()
    check_ops_storage()
    check_player_schema()
    check_fetch_storage()
    check_source_refresh()
    from analysis.rating_cutoff_audit import verify as verify_rating_cutoffs
    cutoff_result = verify_rating_cutoffs()
    check(True, "cutoff-safe ratings and founded assumed starts", cutoff_result["checks"])
    check_fixture_ingestion()
    check_nightly_safety()
    check_nightly_backfill()
    check_player_sources(master)
    # Render the page's tables and charts headlessly and assert on the HTML. This is the only
    # check that sees what a reader sees: every serious defect in this app so far rendered
    # perfectly, so a header/cell-count identity is worth more here than any amount of reading.
    # Optional by design -- node is not part of this project's stack, and the Python side stays
    # numpy/pandas-only, so a machine without node reports "skipped", never a failure.
    if shutil.which("node"):
        with tempfile.TemporaryDirectory() as tmp:
            live0 = Snapshots()
            hp = Path(tmp) / "history.json"
            pp, mp2 = Path(tmp) / "projection.json", Path(tmp) / "matches.json"
            payload = live0.load()
            hp.write_text(json.dumps(live0.history(payload["params"]["season"])))
            pp.write_text(json.dumps(payload))
            mp2.write_text(json.dumps(live0.matches()))
            gw = live0.gw()
            gp = Path(tmp) / "gw.json"
            if gw:
                gp.write_text(json.dumps(gw))
            paths = live0.paths()
            pa = Path(tmp) / "paths.json"
            if paths:
                pa.write_text(json.dumps(paths))
            track = live0.track(payload["params"]["season"])
            tp = Path(tmp) / "track.json"
            if track:
                tp.write_text(json.dumps(track))
            players = live0.players(payload["source"]["date"])
            player_path = Path(tmp) / "players.json"
            if players:
                player_path.write_text(json.dumps(players))
            league_sides = {t["team"] for b in payload["leagues"] for t in b["teams"]}
            uefa_sides = {t["team"] for b in payload["uefa"] for t in b["teams"]}
            uefa_only = next((t for t in sorted(uefa_sides - league_sides)), None)
            cup_only = next((t for t in sorted({t["team"] for b in payload.get("cups", []) for t in b["teams"]}
                                             - league_sides - uefa_sides)
                             if live0.team_fixtures(t, payload["source"]["date"])["fixtures"]), None)
            team_names = list(dict.fromkeys(t for t in ["Arsenal", payload["leagues"][1]["teams"][0]["team"], uefa_only, cup_only] if t))
            if live0.team_fixtures("Waldhof Mannheim", payload["source"]["date"])["fixtures"]:
                team_names.append("Waldhof Mannheim")
            teams = {t: live0.team_fixtures(t, payload["source"]["date"])["fixtures"] for t in team_names}
            team_path = Path(tmp) / "team-fixtures.json"
            team_path.write_text(json.dumps(teams))
            from scripts.match_centre import MatchCentre
            centre = MatchCentre(live0);day=payload['source']['date'];agenda=centre.agenda(day)
            selected=[]
            for mid in ['5840306','5840303','5750700']:
                item=next((f for f in agenda['fixtures'] if f.get('match_id')==mid),None)
                if item:selected.append(item)
            preview=next((f for f in agenda['fixtures'] if not f.get('result') and f.get('ladder') and f['kickoff'][:10]>payload['as_of']),None)
            recent=next((f for f in reversed(agenda['fixtures']) if f.get('result') and f.get('match_id')),None)
            selected.extend(f for f in [preview,recent] if f)
            import csv
            independent=[]
            with (ROOT/'data/master_fixtures.csv').open() as source:
                for row in csv.DictReader(source):
                    if str(row['season'])!=str(payload['params']['season']) or row['played'].lower()!='true' or row.get('tbd','').lower()=='true' or row['kickoff'][:10]>payload['as_of']:continue
                    independent.append({**{k:row[k] for k in ['competition','home','away','kickoff']},'result':[int(float(row[s+'_goals'])) for s in ['home','away']]})
            club_source_path=Path(tmp)/'club-master.json';club_source_path.write_text(json.dumps(independent))
            centre_path=Path(tmp)/'match-centre.json'
            centre_path.write_text(json.dumps({'agenda':agenda,'centres':[centre.detail(day,f['competition'],f['home'],f['away'],f['kickoff'][:10]) for f in selected],'atlases':[centre.atlas(day,t) for t in ['Arsenal','Chelsea','Cardiff City']]}))
            r = subprocess.run(["node", "scripts/webapp/render_check.mjs", str(pp), str(mp2),
                                str(hp), str(gp) if gw else "-", str(pa) if paths else "-",
                                str(tp) if track else "-", str(team_path), str(player_path) if players else "-", str(centre_path), str(club_source_path)],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
            for ln in (r.stdout or "").splitlines():
                if ln.strip():
                    print("  " + ln.strip() if not ln.startswith("  ") else ln)
            check(r.returncode == 0, "the rendered page passes its own checks",
                  (r.stderr or r.stdout or "").strip().splitlines()[-1:] and
                  (r.stderr or r.stdout).strip().splitlines()[-1] or "see above")
    else:
        print("  skip    render checks (node not on PATH)")

    # badges: optional (a side without one is a dot), but an index must never point at a missing
    # or non-PNG file, and two sides sharing one file would mean the name join went wrong
    bdir = ROOT / "data/badges"
    if (bdir / "index.json").exists():
        bix = json.loads((bdir / "index.json").read_text())
        bad_b = [t for t, f in bix.items()
                 if not (bdir / f).exists() or (bdir / f).read_bytes()[:4] != b"\x89PNG"]
        sides = {t["team"] for L in a["leagues"] for t in L["teams"]}
        check(bix and not bad_b and len(set(bix.values())) == len(bix),
              f"{len(bix)} badges on disk, each its own PNG; {sum(t in bix for t in sides)} of"
              f" {len(sides)} league sides have one", ", ".join(bad_b[:4]))
    else:
        print("  skip    badges (none fetched: scripts/fetch_badges.py)")

    live = Snapshots()
    check(bool(live.list()), f"{len(live.list())} snapshot(s) on disk",
          "none — run scripts/nightly.py")

    print("\npipeline and app")
    p = subprocess.run([sys.executable, "scripts/nightly.py", "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True)
    # one progress line per step -- "  4/8  master     skipped" -- then the closing "done in"
    from scripts.nightly import STEPS as NIGHTLY_STEPS
    lines = p.stdout.strip().splitlines()
    walked = [s for s in NIGHTLY_STEPS if any(ln.split()[1:2] == [s] for ln in lines)]
    skipped_existing=any("snapshot exists; --backfill rebuilds existing dates" in line for line in lines)
    check(p.returncode == 0 and (skipped_existing or walked == NIGHTLY_STEPS and lines[-1].startswith("done in")),
          f"nightly --dry-run: existing complete date skips, otherwise walks every step ({len(walked)} of {len(NIGHTLY_STEPS)})",
          (p.stderr or p.stdout).strip().splitlines()[-1:] and
          (p.stderr or p.stdout).strip().splitlines()[-1] or "no output")
    port = 8799
    srv = subprocess.Popen([sys.executable, "scripts/serve.py", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import urllib.request
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                meta = json.load(urllib.request.urlopen(base + "/api/meta"))
                break
            except Exception:                                       # noqa: BLE001
                time.sleep(0.5)
        else:
            meta = None
        check(meta is not None, "the dashboard serves")
        if meta:
            check(meta["model_loaded"] is False,
                  "viewing a snapshot does not load the model — the point of the split")
            page = urllib.request.urlopen(base + "/").read()
            check(b"<title>Season simulator</title>" in page and len(page) > 8000,
                  f"the page is served ({len(page)} bytes)")
            with urllib.request.urlopen(base + "/assets/workspace.mjs") as response:
                module = response.read()
                module_type = response.headers.get("Content-Type", "")
            traversal_blocked = False
            try:
                urllib.request.urlopen(base + "/assets/%2e%2e/serve.py")
            except urllib.error.HTTPError as error:
                traversal_blocked = error.code == 404
            check(module == (ROOT / "scripts/webapp/workspace.mjs").read_bytes()
                  and module_type.startswith("text/javascript") and traversal_blocked
                  and json.load(urllib.request.urlopen(base + "/api/meta"))["model_loaded"] is False,
                  "workspace module: exact local JavaScript bytes,1 traversal rejected, model remains unloaded")
            from urllib.parse import urlencode
            day=meta['snapshots'][-1]['date'];agenda=json.load(urllib.request.urlopen(base+'/api/agenda?date='+day))
            scenario_payload=live.load(day)
            scenario_query=urlencode({'date':day,'pr':scenario_payload['source']['projection_sha256']})
            scenario_cat=json.load(urllib.request.urlopen(base+'/api/scenario/catalog?'+scenario_query))
            if scenario_cat['available']:
                request_cases(scenario_cat)
                scenario_ready = bool(scenario_cat['fixtures'])
            else:
                from scripts.scenario_store import MODEL as SCENARIO_MODEL
                latest_result = str(master.loc[(master.season==scenario_payload['params']['season'])
                                               & master.played, 'kickoff'].max().date())
                scenario_ready = (not scenario_cat['fixtures'] and bool(scenario_cat.get('reason'))
                                  and (scenario_payload.get('model')!=SCENARIO_MODEL
                                       or latest_result!=scenario_payload['as_of']))
            scenario_fixture = scenario_cat['fixtures'][0]['id'] if scenario_cat['fixtures'] else 'unavailable'
            bad_scenario={'date':day,'revision':scenario_payload['source']['projection_sha256'],
                'input_revision':scenario_cat.get('input_revision'),'competition':scenario_cat['competitions'][0],
                'conditions':[{'fixture':scenario_fixture,'outcome':'home'},
                              {'fixture':scenario_fixture,'outcome':'draw'}]}
            rejected=False
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/scenario/run',data=json.dumps(bad_scenario).encode(),headers={'Content-Type':'application/json'}))
            except urllib.error.HTTPError as exc:rejected=exc.code==400
            scenario_asset=urllib.request.urlopen(base+'/assets/scenario-lab.mjs').read()
            check(scenario_ready and rejected
                  and scenario_asset==(ROOT/'scripts/webapp/scenario-lab.mjs').read_bytes()
                  and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  'Scenario Lab HTTP: current catalogue or explicit generation/cutoff refusal; invalid requests reject before model work; module served; model remains unloaded')
            perf=json.load(urllib.request.urlopen(base+'/api/performance?'+scenario_query))
            perf_module=urllib.request.urlopen(base+'/assets/performance-studio.mjs').read()
            perf_rejected=[]
            for query in ['','date='+day+'&pr=changed','date=1900-01-01&pr=changed']:
                try:urllib.request.urlopen(base+'/api/performance?'+query);perf_rejected.append(False)
                except urllib.error.HTTPError as error:perf_rejected.append(error.code in (400,404,409))
            check(perf['coverage']['fixtures']>0 and perf['coverage']['forecasts']>0 and all(perf_rejected)
                  and perf_module==(ROOT/'scripts/webapp/performance-studio.mjs').read_bytes()
                  and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  'Performance Studio HTTP: nonempty source-pinned evidence,3 invalid/revised reads rejected, exact module bytes; model remains unloaded')
            tmcat=json.load(urllib.request.urlopen(base+'/api/time-machine/catalog?'+scenario_query));ta=tmcat['dates'][0];tb=tmcat['dates'][-1]
            tmquery={'date':day,'pr':scenario_payload['source']['projection_sha256'],'a':ta['date'],'ap':ta['projection_sha256'],'b':tb['date'],'bp':tb['projection_sha256'],'competition':tb['competitions'][0]}
            comparison=json.load(urllib.request.urlopen(base+'/api/time-machine?'+urlencode(tmquery)))
            tm_module=urllib.request.urlopen(base+'/assets/time-machine.mjs').read();refused=[]
            for query in [{},{**tmquery,'ap':'changed'},{**tmquery,'competition':'unsupported'},{**tmquery,'b':'1900-01-01'}]:
                try:urllib.request.urlopen(base+'/api/time-machine?'+urlencode(query));refused.append(False)
                except urllib.error.HTTPError as error:refused.append(error.code in (400,404,409))
            check(comparison['rows'] and comparison['ledger'] is not None and all(refused)
                  and tm_module==(ROOT/'scripts/webapp/time-machine.mjs').read_bytes()
                  and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  'Time Machine HTTP:nonempty source-pinned catalogue/comparison,4 invalid reads rejected,exact module;model remains unloaded')
            labquery={'date':day,'pr':scenario_payload['source']['projection_sha256']}
            lab=json.load(urllib.request.urlopen(base+'/api/forecast-lab?'+urlencode(labquery)));labrefused=[]
            for query in [{},{**labquery,'pr':'changed'},{**labquery,'ir':'stale'},{**labquery,'date':'1900-01-01'}]:
                try:urllib.request.urlopen(base+'/api/forecast-lab?'+urlencode(query));labrefused.append(False)
                except urllib.error.HTTPError as error:labrefused.append(error.code in (400,404,409))
            check(lab['fixtures'] and lab['coverage']['played']==lab['coverage']['evaluated']+lab['coverage']['excluded'] and all(labrefused)
                  and urllib.request.urlopen(base+'/assets/forecast-lab.mjs').read()==(ROOT/'scripts/webapp/forecast-lab.mjs').read_bytes()
                  and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  'Forecast Lab HTTP:nonempty pinned evaluation,4 invalid/stale reads refused,exact module;model remains unloaded')
            exquery={'date':day,'pr':scenario_payload['source']['projection_sha256']}
            schedule=json.load(urllib.request.urlopen(base+'/api/explore-visuals?'+urlencode(exquery)));exrefused=[]
            for query in [{},{**exquery,'pr':'changed'},{**exquery,'ir':'stale'},{**exquery,'date':'1900-01-01'}]:
                try:urllib.request.urlopen(base+'/api/explore-visuals?'+urlencode(query));exrefused.append(False)
                except urllib.error.HTTPError as error:exrefused.append(error.code in (400,404,409))
            check(schedule['fixtures'] and schedule['coverage']['fixed_fixture_records']==len(schedule['fixtures']) and all(exrefused)
                  and urllib.request.urlopen(base+'/assets/explore-visuals.mjs').read()==(ROOT/'scripts/webapp/explore-visuals.mjs').read_bytes()
                  and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  'Explore charts HTTP:nonempty pinned fixed schedule,4 invalid/stale reads refused,exact module;model remains unloaded')
            upcoming=next(f for f in agenda['fixtures'] if not f.get('result') and f['kickoff'][:10]>agenda['as_of'])
            played=next(f for f in reversed(agenda['fixtures']) if f.get('result') and f.get('match_id'))
            def match_request(f):
                return json.load(urllib.request.urlopen(base+'/api/match-centre?'+urlencode({'date':day,'competition':f['competition'],'home':f['home'],'away':f['away'],'day':f['kickoff'][:10]})))
            before,after=match_request(upcoming),match_request(played)
            rejected=[]
            for path in ['/api/agenda','/api/agenda?date=1900-01-01','/api/match-centre?date='+day,'/api/agenda?date='+day+'&pr=changed']:
                try:urllib.request.urlopen(base+path);rejected.append(False)
                except urllib.error.HTTPError as error:rejected.append(error.code in [400,404,409])
            with urllib.request.urlopen(base+'/assets/match-centre.mjs') as response:centre_module=response.read()
            check(len(agenda['fixtures'])>0 and len({f['id'] for f in agenda['fixtures']})==len(agenda['fixtures'])
                  and before['facts'] is None and after['facts']['coverage']['goals_reconcile'] and all(rejected)
                  and centre_module==(ROOT/'scripts/webapp/match-centre.mjs').read_bytes()
                  and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  f"Match Centre HTTP:{len(agenda['fixtures'])} unique pinned fixtures,2 preview/played responses,4 invalid/revised requests rejected; module exact and model unloaded")
            from scripts.match_centre import MatchCentre
            atlas=json.load(urllib.request.urlopen(base+'/api/atlas?'+urlencode({'date':day,'team':'Arsenal'})))
            invalid_atlas=[]
            for query in [{'team':'Arsenal'},{'date':day,'team':'unknown'},{'date':day,'team':'Arsenal','pr':'changed'}]:
                try:urllib.request.urlopen(base+'/api/atlas?'+urlencode(query));invalid_atlas.append(False)
                except urllib.error.HTTPError as error:invalid_atlas.append(error.code in [400,404,409])
            check(atlas==MatchCentre(live).atlas(day,'Arsenal') and atlas['matches'] and all(invalid_atlas) and json.load(urllib.request.urlopen(base+'/api/meta'))['model_loaded'] is False,
                  f"Atlas HTTP:{len(atlas['matches'])} exact Arsenal matches,3 malformed/club/revision requests rejected;model unloaded")
            track = live.track()
            if track:
                served = json.load(urllib.request.urlopen(base + "/api/track"))
                check(served == track and served["matches"] and
                      json.load(urllib.request.urlopen(base + "/api/meta"))["model_loaded"] is False,
                      f"track record: /api/track equals the file ({len(served['matches'])} matches) without loading the model")
            else:
                print("  skip    track record endpoint (no track.json: run scripts/nightly.py --only track)")
            day = meta["snapshots"][-1]["date"]
            snapshot = live.load(day)
            check_gw_http(base, live, day)
            check_players_http(base, live, day)
            cutoff = pd.Timestamp(snapshot["as_of"]) + pd.Timedelta(days=1)
            eligible = master[(master.season == snapshot["params"]["season"]) & master.played
                              & (master.kickoff < cutoff) & master.home_goals.notna() & master.away_goals.notna()]
            if "tbd" in eligible:
                eligible = eligible[~eligible.tbd.fillna(False)]
            cups = eligible[eligible.kind == "cup"]
            fixture_key = lambda r: (r["competition"], r["home"], r["away"], str(r["kickoff"])[:10])
            counts = {fixture_key(r): 0 for r in cups.to_dict("records")}
            unexpected = []
            for team in sorted(set(cups.home) | set(cups.away)):
                report = live.team_fixtures(team, day)
                for f in report["fixtures"] if report else []:
                    if f["kind"] != "cup":
                        continue
                    key = fixture_key(f)
                    if key in counts:
                        counts[key] += 1
                    else:
                        unexpected.append(key)
            arsenal = json.load(urllib.request.urlopen(base + "/api/team-fixtures?team=Arsenal&date=" + day))
            want_arsenal = eligible[(eligible.home == "Arsenal") | (eligible.away == "Arsenal")]
            wanted = {fixture_key(r) for r in want_arsenal.to_dict("records")}
            got = {fixture_key(r) for r in arsenal["fixtures"]}
            check(len(counts) > 0 and all(n == 2 for n in counts.values()) and not unexpected
                  and len(wanted) > 0 and got == wanted and len(arsenal["fixtures"]) == len(wanted)
                  and arsenal == live.team_fixtures("Arsenal", day),
                  f"team page: {len(counts)} played cup fixtures appear on both sides ({sum(counts.values())} rows); Arsenal's endpoint includes all {len(wanted)} played matches",
                  f"cup omissions/duplicates {sum(n != 2 for n in counts.values())}, unexpected {len(unexpected)}, Arsenal {len(got)}/{len(wanted)}")
            bix = json.load(urllib.request.urlopen(base + "/api/badges"))
            if bix:
                one = urllib.request.urlopen(base + "/badges/" + next(iter(bix.values())))
                ok_one = one.status == 200 and one.headers.get("Content-Type") == "image/png"
                try:
                    urllib.request.urlopen(base + "/badges/..%2F..%2FREADME.md")
                    escaped = True
                except urllib.error.HTTPError as e:
                    escaped = e.code != 404
                check(ok_one and not escaped, "badges are served, and only badges",
                      f"badge ok {ok_one}, traversal escaped {escaped}")
            # The three time-series charts are declared as specs and read by one drawHistory.
            # Asserted on the target AND on the negative: the old positional signature took
            # (comp, metric, invert, size) and a half-applied edit leaves both forms in place,
            # which parses, renders, and silently charts the wrong metric.
            specs = [b"HIST_POS", b"HIST_PTS", b"HIST_WIN"]
            stale = [b"drawHistory(comp, metric, invert, size)",
                     b'drawHistory(comp, isPos ? "mean_pos" : "mean_pts", isPos, size)',
                     b'const title = metric === "mean_pos"']
            check(all(k in page for k in specs) and not any(k in page for k in stale),
                  "the three history charts are specs, and the old signature is gone",
                  f"missing {[k for k in specs if k not in page]}, "
                  f"stale {[k for k in stale if k in page]}")
            # The page names an older snapshot by its version against the newest it reads. Left
            # behind on a payload bump, the last version but one reads as current and its missing
            # views go unexplained -- which is how it sat at 8 under payload 9.
            from scripts.projection import PAYLOAD_VERSION
            pv = re.search(rb"const PAGE_VERSION = (\d+);", page)
            check(bool(pv) and int(pv.group(1)) == PAYLOAD_VERSION,
                  f"the page reads up to payload version {PAYLOAD_VERSION}",
                  f"PAGE_VERSION {pv.group(1).decode() if pv else 'missing'}")
    finally:
        srv.terminate()
        srv.wait(timeout=10)

    bad_n = results.count(False)
    print(f"\n{len(results) - bad_n}/{len(results)} checks passed")
    return 1 if bad_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
