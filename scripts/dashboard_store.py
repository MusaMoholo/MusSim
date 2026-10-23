"""Read-only dashboard snapshot services. Standard library only; no model or runner imports.

Public aliases in serve.py preserve existing imports while HTTP and optional live execution
remain separate from disk reads. File bytes and cutoff semantics are unchanged.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data/snapshots"


# --------------------------------------------------------------------------- snapshots
class Snapshots:
    """Reads the nightly output. Caches on directory mtime so a fresh run is picked up."""

    def __init__(self, root: Path = SNAP_DIR,
                 master_csv: Path = ROOT / "data/master_fixtures.csv"):
        self.root = root
        self.master_csv = Path(master_csv)
        self._lock = threading.Lock()
        self._hist: Dict[str, Any] = {}
        self._hist_key: Optional[tuple] = None
        self._team_fixture_key: Optional[tuple] = None
        self._team_fixture_rows: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
        self._players_http_cache: Optional[Tuple[tuple, bytes]] = None

    def list(self) -> List[Dict[str, Any]]:
        idx = self.root / "index.json"
        if idx.exists():
            try:
                return json.loads(idx.read_text())
            except Exception:                                       # noqa: BLE001
                pass
        return [{"date": d.name} for d in sorted(self.root.glob("*/"))
                if (d / "projection.json").exists()]

    def load(self, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        rows = self.list()
        if not rows:
            return None
        day = day or rows[-1]["date"]
        f = self.root / day / "projection.json"
        if not f.exists():
            return None
        raw = f.read_bytes()
        out = json.loads(raw)
        out["source"] = {"kind": "snapshot", "date": day,
                         "projection_sha256": hashlib.sha256(raw).hexdigest()}
        return out

    def matches(self, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Per-match distributions for one snapshot, loaded only when the page asks."""
        rows = self.list()
        if not rows:
            return None
        day = day or rows[-1]["date"]
        f = self.root / day / "matches.json"
        return json.loads(f.read_text()) if f.exists() else None

    def players(self, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Stored cutoff-safe player totals; older snapshots deliberately have no file."""
        body = self.players_bytes(day)
        return json.loads(body) if body is not None else None

    def players_bytes(self, day: Optional[str] = None,
                      compressed: bool = False) -> Optional[bytes]:
        """Preserve file bytes; cache one gzip response by file revision for browser requests."""
        rows = self.list()
        if not rows:
            return None
        day = day or rows[-1]["date"]
        if not any(row["date"] == day for row in rows):
            return None
        packed, plain = self.root / day / "players.json.gz", self.root / day / "players.json"
        # Prefer the stored compressed sidecar; older snapshots retain their plain format.
        if packed.is_file():
            body = packed.read_bytes()
            return body if compressed else gzip.decompress(body)
        if not plain.is_file():
            return None
        if not compressed:
            return plain.read_bytes()
        stat = plain.stat()
        key = (str(plain), stat.st_mtime_ns, stat.st_size)
        cached = self._players_http_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        body = gzip.compress(plain.read_bytes(), compresslevel=6, mtime=0)
        self._players_http_cache = (key, body)
        return body

    def gw_bytes(self, day: Optional[str] = None) -> Optional[Tuple[bytes, Optional[str]]]:
        """Stored GW bytes and their encoding, with plain-JSON fallback for older snapshots."""
        rows = self.list()
        if not rows:
            return None
        day = day or rows[-1]["date"]
        compressed, plain = self.root / day / "gw.json.gz", self.root / day / "gw.json"
        if compressed.exists():
            return compressed.read_bytes(), "gzip"
        return (plain.read_bytes(), None) if plain.exists() else None

    def gw(self, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Decoded per-round tables and fixtures; HTTP serves gw_bytes without recompression."""
        stored = self.gw_bytes(day)
        if stored is None:
            return None
        body, encoding = stored
        return json.loads(gzip.decompress(body) if encoding == "gzip" else body)

    def _played_team_fixtures(self) -> Dict[int, Dict[str, List[Dict[str, Any]]]]:
        """Parse the master CSV once per file revision, indexed by season and participating side."""
        stat = self.master_csv.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if self._team_fixture_key == key:
                return self._team_fixture_rows

            def number(value: Optional[str]) -> Optional[float]:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return None
                return value if math.isfinite(value) else None

            def flag(value: Optional[str]) -> bool:
                return str(value or "").lower() in ("true", "1", "yes")

            seasons: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
            with self.master_csv.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    season = number(row.get("season"))
                    if season is None or not season.is_integer() or not flag(row.get("played")) \
                            or flag(row.get("tbd")):
                        continue
                    kickoff = row.get("kickoff", "")
                    if not kickoff:
                        continue
                    score = [number(row.get(k)) for k in ("home_goals", "away_goals")]
                    if any(v is None or v < 0 or not v.is_integer() for v in score):
                        continue
                    fixture = {"competition": row["competition"], "kind": row["kind"],
                               "home": row["home"], "away": row["away"], "kickoff": kickoff,
                               "result": [int(v) for v in score], "outcome": row.get("outcome") or None,
                               "minutes": number(row.get("minutes")), "round": number(row.get("round"))}
                    xg = [number(row.get(k)) for k in ("home_xg", "away_xg")]
                    if all(v is not None and v >= 0 for v in xg):
                        fixture["xg"] = xg
                    sides = seasons.setdefault(int(season), {})
                    for team in (fixture["home"], fixture["away"]):
                        sides.setdefault(team, []).append(fixture)
            for sides in seasons.values():
                for fixtures in sides.values():
                    fixtures.sort(key=lambda f: (f["kickoff"], f["competition"], f["home"], f["away"]))
            self._team_fixture_rows, self._team_fixture_key = seasons, key
            return seasons

    def team_fixtures(self, team: str, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Real matches in every competition through the selected snapshot, with no model load.

        Cups are not in gw.json's played fixtures. Read their existing master CSV with stdlib
        csv, then apply the snapshot's season/cutoff before emitting anything, including xG.
        Scores are the recorded final score; outcome/minutes identify extra time or penalties.
        """
        if not team or not team.strip():
            raise ValueError("team is required")
        if day is not None and day not in {r["date"] for r in self.list()}:
            return None
        projection = self.load(day)
        if projection is None:
            return None
        season, cutoff = projection["params"]["season"], projection.get("as_of")
        fixtures = [] if cutoff is None else [dict(f) for f in self._played_team_fixtures()
                     .get(season, {}).get(team, []) if f["kickoff"][:10] <= cutoff]
        return {"season": season, "as_of": cutoff, "team": team, "fixtures": fixtures}

    def track(self, season: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Nightly forecast evaluation; a missing report leaves older snapshots usable."""
        path = self.root / "track.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text())
        if season is not None and payload.get("season") != season:
            return None
        return payload

    def paths(self, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Each UEFA side's knockout path, loaded only when the Paths view opens."""
        rows = self.list()
        if not rows:
            return None
        day = day or rows[-1]["date"]
        gz, f = self.root / day / "paths.json.gz", self.root / day / "paths.json"
        if gz.exists():
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(f.read_text()) if f.exists() else None

    def pipeline(self, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
        rows = self.list()
        if not rows:
            return None
        day = day or rows[-1]["date"]
        f = self.root / day / "pipeline.json"
        return json.loads(f.read_text()) if f.exists() else None

    def _key(self) -> tuple:
        return tuple(sorted((d.name, (d / "projection.json").stat().st_mtime_ns)
                            for d in self.root.glob("*") if (d / "projection.json").exists()))

    def history(self, season: Optional[int] = None) -> Dict[str, Any]:
        """Per-team series across snapshots, for the few numbers worth watching move.

        Every series is padded to the snapshot index BEFORE its value is appended, so a team that
        first appears at snapshot k lands at position k rather than position 0. Getting that wrong
        plots a newcomer's line at the start of the season instead of where it belongs, and the
        chart looks plausible either way -- which is exactly why it is done explicitly here.
        """
        with self._lock:
            key = (self._key(), season)
            if self._hist_key == key:
                return self._hist
        dates: List[str] = []
        series: Dict[str, Dict[str, Dict[str, List[Optional[float]]]]] = {}
        meta: Dict[str, Any] = {}
        ratings: Dict[str, Dict[str, List[Optional[float]]]] = {}
        for row in self.list():
            p = self.load(row["date"])
            if p is None or (season is not None and p["params"]["season"] != season):
                continue
            i = len(dates)                     # this snapshot's index in the series
            dates.append(row["date"])
            meta[row["date"]] = {"worlds": p["worlds"], "as_of": p.get("as_of"),
                                 "version": p.get("version", 1), "model": p.get("model")}

            def put(comp_name: str, team: str, values: Dict[str, Optional[float]]) -> None:
                d = series.setdefault(comp_name, {}).setdefault(
                    team, {k: [] for k in values})
                for k, v in values.items():
                    col = d.setdefault(k, [])
                    while len(col) < i:
                        col.append(None)
                    col.append(v)

            for L in p["leagues"]:
                for t in L["teams"]:
                    put(L["competition"], t["team"],
                        {"p_win": t["p_win"], "p_ucl": t.get("p_ucl", t.get("p_top4")),
                         "p_uel": t.get("p_uel"), "p_uecl": t.get("p_uecl"),
                         "p_releg": t["p_releg"], "mean_pts": t["mean_pts"],
                         "mean_pos": t["mean_pos"]})
            for U in p["uefa"]:
                for t in U["teams"]:
                    put(U["competition"], t["team"],
                        {"p_win": t["p_win"], "p_sf": t.get("p_sf"),
                         "p_top8": t.get("p_top8"), "mean_pos": t.get("mean_seed"),
                         "mean_pts": t.get("mean_pts")})
            for C in p.get("cups", []):
                for t in C["teams"]:
                    put(C["competition"], t["team"], {"p_win": t["p_win"]})
            for rating in (p.get("ratings") or {}).get("teams", []):
                target = ratings.setdefault(rating["team"], {k: [] for k in ("elo", "att", "def")})
                for metric, col in target.items():
                    while len(col) < i:
                        col.append(None)
                    col.append(rating.get(metric))
            for target in ratings.values():
                for col in target.values():
                    while len(col) < i + 1:
                        col.append(None)
            # a team missing from this snapshot gets a hole, never a silent shift
            for comp in series.values():
                for d in comp.values():
                    for col in d.values():
                        while len(col) < i + 1:
                            col.append(None)
        out = {"dates": dates, "meta": meta,
               "competitions": {c: dict(sorted(v.items())) for c, v in sorted(series.items())},
               "ratings": dict(sorted(ratings.items()))}
        with self._lock:
            self._hist, self._hist_key = out, (self._key(), season)
        return out


