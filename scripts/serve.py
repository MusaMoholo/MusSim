#!/usr/bin/env python3
"""A localhost dashboard for the season simulator. Stdlib only -- no Flask, no build step.

    .venv/bin/python scripts/serve.py            # then open http://127.0.0.1:8765

It reads what `scripts/nightly.py` wrote. The heavy work -- scrape, rebuild, re-walk Elo,
re-simulate -- happens once a night, so opening the page is a file read rather than a minute of
compute. The dashboard can still run a live projection on demand when you want to move a knob and
see what happens, but that is the exception, not the normal path.

The reason to prefer snapshots is not only speed. A projection of the live season is the same
answer for everyone who asks it that day, and running it nightly accumulates a HISTORY: the
`/api/history` endpoint turns the snapshot directory into per-team time series, so you can see
when a title probability moved rather than only where it stands. No single interactive run shows
that.

Endpoints:
    GET  /                      the page
    GET  /api/meta              seasons, defaults, snapshot list, last pipeline run
    GET  /api/snapshot?date=    one stored projection (date omitted -> the newest)
    GET  /api/history?season=   per-team probability and Elo/ATT/DEF series across snapshots
    GET  /api/team-fixtures?team=&date=  played league, UEFA and cup matches through a cutoff
    GET  /api/track?season=     stored pre-kickoff match forecasts against 90-minute results
    GET  /api/matches?date=     next round's scoreline distributions, per fixture
    GET  /api/players?date=     stored player totals and coverage for one snapshot
    GET  /api/gw?date=          per-league tables after every round, and every league fixture
    GET  /api/paths?date=       each UEFA side's knockout path: likeliest opponents per round
    GET  /api/badges            team -> badge file, for the Visualisations view
    GET  /badges/<id>.png       one badge (scripts/fetch_badges.py keeps them in data/badges)
    GET  /api/pipeline?date=    that night's step-by-step report
    GET  /api/time-machine/catalog?date=&pr=  pinned stored-history date catalogue
    GET  /api/time-machine?date=&pr=&a=&ap=&b=&bp=&competition=  stored-only two-date comparison
    GET  /api/explore-visuals?date=&pr=&ir=  stored fixed-calendar evidence for Explore charts
    GET  /api/forecast-lab?date=&pr=&ir=  source-pinned evaluation and historical validity
    GET  /api/performance?date=&pr=  retained league results and source-pinned pre-match expectations
    GET  /api/scenario/catalog?date=&pr=  source-pinned future league fixtures; no simulation
    POST /api/scenario/run      explicit isolated conditional experiment; never publishes
    GET  /api/scenario/job?id=  in-memory progress/result
    POST /api/scenario/cancel   cancel only the named experiment
    POST /api/run               start a live projection (one at a time)
    GET  /api/job?id=           progress, then the result
    POST /api/cancel            stop the running job
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.projection import (  # noqa: E402
    DEFAULTS, Engine, coerce_params, run_projection, run_projection_parallel,
)

# A live run above this many worlds goes parallel. Below it, spawning ten processes costs more in
# start-up than it saves, as the 200-world case showed: 3.1x rather than the ~8x at 10,000.
PARALLEL_ABOVE = 400

WEBAPP = Path(__file__).resolve().parent / "webapp"
SNAP_DIR = ROOT / "data/snapshots"
BADGE_DIR = ROOT / "data/badges"


def accepts_gzip(value: str) -> bool:
    """Accept an explicit gzip preference while respecting a zero quality value."""
    for entry in value.lower().split(","):
        name, *parameters = [part.strip() for part in entry.split(";")]
        if name != "gzip":
            continue
        quality = 1.0
        for parameter in parameters:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        return quality > 0
    return False


# Read services have no dependency on the optional live runner. Keep the public alias.
from scripts.dashboard_store import Snapshots  # noqa: E402
from scripts.match_centre import MatchCentre  # noqa: E402
from scripts.performance_studio import PerformanceStudio, PerformanceError  # noqa: E402
from scripts.time_machine import TimeMachine, TimeMachineError  # noqa: E402
from scripts.forecast_lab import ForecastLab, ForecastError  # noqa: E402
from scripts.explore_visuals import ExploreVisuals, ExploreError  # noqa: E402
from scripts.scenario_store import ScenarioManager, ScenarioError, catalog as scenario_catalog  # noqa: E402


# --------------------------------------------------------------------------- live jobs
class Runner:
    def __init__(self, engine: Engine, processes: Optional[int] = None):
        self.engine = engine
        self.processes = processes or max(1, (os.cpu_count() or 4) - 4)
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start(self, params: Dict[str, Any]) -> str:
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise RuntimeError("a run is already in progress")
            job_id = uuid.uuid4().hex[:12]
            self.jobs[job_id] = {"status": "running", "done": 0, "total": params["worlds"],
                                 "started": time.time(), "stage": "fitting", "params": params}
        threading.Thread(target=self._run, args=(job_id, params), daemon=True).start()
        return job_id

    def _run(self, job_id: str, params: Dict[str, Any]) -> None:
        job = self.jobs[job_id]

        def progress(done: int, total: int, stage: str) -> None:
            job["done"], job["total"], job["stage"] = done, total, stage
            if job.get("cancel"):
                raise KeyboardInterrupt("cancelled")

        try:
            procs = self.processes if params["worlds"] > PARALLEL_ABOVE else 1
            out = (run_projection_parallel(params, procs, progress, self.engine) if procs > 1
                   else run_projection(self.engine, params, progress))
            out["source"] = {"kind": "live"}
            job["matches"] = out.pop("matches", None)
            job["gw"] = out.pop("gw", None)
            job["paths"] = out.pop("paths", None)
            job["result"] = out
            job["status"] = "done"
        except KeyboardInterrupt:
            job["status"] = "cancelled"
        except Exception as exc:                                    # noqa: BLE001
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["traceback"] = traceback.format_exc()


# --------------------------------------------------------------------------- HTTP
class Lazy:
    """Holds the model side of the app, built on FIRST USE rather than at startup.

    The point of the nightly job is that viewing results needs no model: a snapshot is JSON on
    disk. So the dashboard starts instantly and stays useful even if the fixture table is
    mid-rebuild. Only a live projection -- or the season metadata its controls need -- pays for
    loading the master table and fitting.
    """

    def __init__(self, processes: Optional[int] = None) -> None:
        self._engine: Optional[Engine] = None
        self._runner: Optional[Runner] = None
        self.processes = processes
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    @property
    def engine(self) -> Engine:
        with self._lock:
            if self._engine is None:
                t0 = time.time()
                self._engine = Engine()
                sys.stderr.write(f"  loaded the model in {time.time() - t0:.1f}s "
                                 f"(first live request)\n")
            return self._engine

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.engine)
        return self._runner


class Handler(BaseHTTPRequestHandler):
    lazy: Lazy
    snaps: Snapshots
    server_version = "FootballSim/2.0"

    @property
    def engine(self) -> Engine:
        return self.lazy.engine

    @property
    def runner(self) -> Runner:
        return self.lazy.runner

    @property
    def time_machine(self) -> TimeMachine:
        with self.lazy._lock:
            if not hasattr(self.server,"time_machine_store"):
                self.server.time_machine_store=TimeMachine(self.snaps)
            return self.server.time_machine_store

    @property
    def explore_visuals(self) -> ExploreVisuals:
        with self.lazy._lock:
            if not hasattr(self.server,"explore_visuals_store"):
                self.server.explore_visuals_store=ExploreVisuals(self.snaps)
            return self.server.explore_visuals_store

    @property
    def forecast_lab(self) -> ForecastLab:
        with self.lazy._lock:
            if not hasattr(self.server,"forecast_lab_store"):
                self.server.forecast_lab_store=ForecastLab(self.snaps)
            return self.server.forecast_lab_store

    @property
    def performance(self) -> PerformanceStudio:
        with self.lazy._lock:
            if not hasattr(self.server,"performance_store"):
                self.server.performance_store=PerformanceStudio(self.snaps)
            return self.server.performance_store

    @property
    def scenarios(self) -> ScenarioManager:
        with self.lazy._lock:
            if not hasattr(self.server, 'scenario_manager'):
                self.server.scenario_manager = ScenarioManager(self.snaps,self.lazy.processes or 4)
            return self.server.scenario_manager

    def log_message(self, fmt: str, *args: Any) -> None:
        if "/api/job" not in self.path and "/api/scenario/job" not in self.path:
            sys.stderr.write(f"  {self.command} {self.path}\n")

    def _send(self, code: int, body: bytes, ctype: str, encoding: Optional[str] = None,
              vary: Optional[str] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
        if vary:
            self.send_header("Vary", vary)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:                                       # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                f = WEBAPP / "index.html"
                if not f.exists():
                    return self._json({"error": f"missing {f}"}, 500)
                return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            if url.path in {"/assets/workspace.mjs", "/assets/match-centre.mjs", "/assets/scenario-lab.mjs", "/assets/performance-studio.mjs", "/assets/competition-evidence.mjs", "/assets/time-machine.mjs", "/assets/forecast-lab.mjs", "/assets/explore-visuals.mjs"}:
                return self._send(200, (WEBAPP / url.path.rsplit("/", 1)[-1]).read_bytes(),
                                  "text/javascript; charset=utf-8")
            if url.path == "/api/meta":
                # deliberately model-free: everything here comes off disk
                return self._json({"defaults": DEFAULTS, "snapshots": self.snaps.list(),
                                   "pipeline": self.snaps.pipeline(),
                                   "model_loaded": self.lazy.loaded})
            if url.path == "/api/time-machine/catalog":
                return self._json(self.time_machine.catalog(q.get("date",[None])[0],q.get("pr",[""])[0]))
            if url.path == "/api/time-machine":
                get=lambda key:q.get(key,[""])[0]
                return self._json(self.time_machine.compare(get("date"),get("pr"),get("a"),get("ap"),get("b"),get("bp"),get("competition")))
            if url.path == "/api/explore-visuals":
                return self._json(self.explore_visuals.read(q.get("date",[None])[0],q.get("pr",[""])[0],q.get("ir",[""])[0]))
            if url.path == "/api/forecast-lab":
                return self._json(self.forecast_lab.read(q.get("date",[None])[0],q.get("pr",[""])[0],q.get("ir",[""])[0]))
            if url.path == "/api/performance":
                return self._json(self.performance.read(q.get("date",[None])[0],q.get("pr",[""])[0],all_competitions=q.get("scope",[""])[0]=="all"))
            if url.path == "/api/scenario/catalog":
                return self._json(scenario_catalog(self.snaps,q.get('date',[None])[0],q.get('pr',[''])[0]))
            if url.path == "/api/scenario/job":
                return self._json(self.scenarios.get(q.get('id',[''])[0]))
            if url.path == "/api/seasons":
                # loads the model; the page asks only when the live-run panel is opened
                seasons = self.engine.seasons()
                return self._json({"seasons": seasons, "live_season": self.engine.live_season(),
                                   "meta": {str(s): self.engine.season_meta(s) for s in seasons}})
            if url.path == "/api/snapshot":
                p = self.snaps.load(q.get("date", [None])[0])
                return self._json(p) if p else self._json({"error": "no snapshot"}, 404)
            if url.path in {"/api/agenda", "/api/match-centre", "/api/atlas"}:
                day = q.get("date", [None])[0]
                if not day:
                    return self._json({"error": "a pinned snapshot date is required"}, 400)
                if not hasattr(self.server, "match_centre"):
                    self.server.match_centre = MatchCentre(self.snaps)
                centre = self.server.match_centre
                payload = centre.atlas(day, q.get("team", [""])[0]) if url.path == "/api/atlas" else centre.agenda(day) if url.path == "/api/agenda" else centre.detail(day,
                    q.get("competition", [""])[0], q.get("home", [""])[0], q.get("away", [""])[0], q.get("day", [""])[0])
                if payload is not None and q.get('pr', [''])[0] and payload['source']['projection_sha256'] != q['pr'][0]:
                    return self._json({'error':'This forecast revision changed. Reload the selected snapshot to use its current evidence.'},409)
                return self._json(payload) if payload is not None else self._json({"error": "fixture/snapshot unavailable"}, 404)
            if url.path == "/api/matches":
                p = self.snaps.matches(q.get("date", [None])[0])
                return self._json(p) if p else self._json({"error": "no match detail"}, 404)
            if url.path == "/api/players":
                compressed = accepts_gzip(self.headers.get("Accept-Encoding", ""))
                body = self.snaps.players_bytes(q.get("date", [None])[0], compressed)
                if body is None:
                    return self._json({"error": "no player detail for this snapshot"}, 404)
                return self._send(200, body, "application/json; charset=utf-8",
                                  "gzip" if compressed else None, "Accept-Encoding")
            if url.path == "/api/gw":
                stored = self.snaps.gw_bytes(q.get("date", [None])[0])
                if stored is None:
                    return self._json({"error": "no gameweek detail"}, 404)
                body, encoding = stored
                return self._send(200, body, "application/json; charset=utf-8", encoding)
            if url.path == "/api/paths":
                p = self.snaps.paths(q.get("date", [None])[0])
                return self._json(p) if p else self._json({"error": "no knockout paths"}, 404)
            if url.path == "/api/team-fixtures":
                team = q.get("team", [""])[0].strip()
                if not team:
                    return self._json({"error": "team is required"}, 400)
                p = self.snaps.team_fixtures(team, q.get("date", [None])[0])
                return self._json(p) if p else self._json({"error": "no snapshot"}, 404)
            if url.path == "/api/track":
                season = q.get("season", [None])[0]
                p = self.snaps.track(int(season) if season else None)
                return self._json(p) if p else self._json({"error": "no track record for this season"}, 404)
            if url.path == "/api/badges":
                f = BADGE_DIR / "index.json"
                return self._json(json.loads(f.read_text()) if f.exists() else {})
            if url.path.startswith("/badges/"):
                # a file name and nothing else: digits then .png, so no path can leave the folder
                name = url.path[len("/badges/"):]
                f = BADGE_DIR / name
                if not (name[:-4].isdigit() and name.endswith(".png")) or not f.exists():
                    return self._json({"error": "no such badge"}, 404)
                return self._send(200, f.read_bytes(), "image/png")
            if url.path == "/api/pipeline":
                p = self.snaps.pipeline(q.get("date", [None])[0])
                return self._json(p) if p else self._json({"error": "no pipeline run"}, 404)
            if url.path == "/api/history":
                s = q.get("season", [None])[0]
                return self._json(self.snaps.history(int(s) if s else None))
            if url.path == "/api/job":
                job = self.runner.jobs.get(q.get("id", [""])[0])
                if job is None:
                    return self._json({"error": "unknown job"}, 404)
                out = {k: job[k] for k in ("status", "done", "total", "stage") if k in job}
                out["elapsed"] = round(time.time() - job["started"], 1)
                for k in ("error", "traceback", "result", "matches", "gw", "paths"):
                    if k in job:
                        out[k] = job[k]
                return self._json(out)
            self._json({"error": "not found"}, 404)
        except (ScenarioError, PerformanceError, TimeMachineError, ForecastError, ExploreError) as exc:
            self._json({"error":str(exc)},exc.status)
        except Exception as exc:                                    # noqa: BLE001
            self._json({"error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc()}, 500)

    def do_POST(self) -> None:                                      # noqa: N802
        url = urlparse(self.path)
        if url.path in {'/api/scenario/run','/api/scenario/cancel'}:
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:raise ScenarioError('Invalid or oversized scenario request.')
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):raise ScenarioError('Scenario request must be an object.')
                if url.path.endswith('/cancel'):return self._json(self.scenarios.cancel(body.get('job','')))
                job,definition=self.scenarios.start(body)
                return self._json({'job':job,'definition':definition},202)
            except ScenarioError as exc:return self._json({'error':str(exc)},exc.status)
            except (ValueError,TypeError) as exc:return self._json({'error':str(exc)},400)
        if url.path == "/api/cancel":
            for job in self.runner.jobs.values():
                if job["status"] == "running":
                    job["cancel"] = True
            return self._json({"ok": True})
        if url.path != "/api/run":
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            params = coerce_params(body, self.engine.live_season())
            return self._json({"job": self.runner.start(params), "params": params})
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 409)
        except Exception as exc:                                    # noqa: BLE001
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--snapshots", type=Path, default=SNAP_DIR,
                    help="snapshot directory to serve (default data/snapshots) -- point it at a "
                         "copy to try a page change against a projection without touching history")
    ap.add_argument("--processes", type=int, default=None,
                    help="processes for a live run (default: cores - 4). The result is identical "
                         "whatever this is; only the wait changes.")
    args = ap.parse_args()

    Handler.lazy = Lazy(args.processes)
    Handler.snaps = Snapshots(args.snapshots)
    snaps = Handler.snaps.list()
    print(f"{len(snaps)} snapshot(s)"
          + (f", newest {snaps[-1]['date']} ({snaps[-1].get('worlds')} worlds, data as of "
             f"{snaps[-1].get('as_of')})" if snaps
             else " — run scripts/nightly.py to make one")
          + "\nthe model loads on the first live run, not now")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"\n  ->  http://{args.host}:{args.port}\n\nctrl-c to stop", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
