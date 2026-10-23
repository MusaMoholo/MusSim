#!/usr/bin/env python3
"""The scheduled job: refresh the data, rebuild the fixture table, re-simulate, write a snapshot.

    .venv/bin/python scripts/nightly.py                                # the whole pipeline
    .venv/bin/python scripts/nightly.py --skip fotmob opta             # offline: reuse the data
    .venv/bin/python scripts/nightly.py --only project --worlds 1000
    .venv/bin/python scripts/nightly.py --dry-run
    .venv/bin/python scripts/nightly.py --backfill                    # normal nightly job from 1 August, including missing dates
    .venv/bin/python scripts/nightly.py --date 2026-10-21 --refresh-players

Why a job rather than doing it in the app. A projection of the live season is the same answer for
everyone who asks it that day, so computing it per page-load burns seconds for nothing and makes
the app feel slow. Run it once a night, write the payload to `data/snapshots/<date>/`, and the
dashboard becomes a file read. The side effect is the valuable part: a run a day accumulates a
HISTORY of projections, so "when did Arsenal's title probability move, and what moved it" becomes
answerable. No single interactive run can show that.

The terminal shows progress and nothing else: a line per step -- ok, FAILED or skipped, and how
long it took -- with the reason when one fails and a count when a script warned. Whatever a step
has to say beyond that goes to `pipeline.json` and `pipeline.log` beside the snapshot, which is
where the dashboard's health panel reads it. Commentary printed every night outlives the thing it
describes; a status does not. Reports that inform a modelling decision rather than the snapshot
are run by hand: `analysis/reconcile.py`, `scripts/elo_engine.py --walk-to today`.

Design rules this file follows, because it runs unattended:

  * Every step is isolated. A blocked scrape must not stop the re-simulation -- yesterday's
    fixtures are still on disk and a projection from them is still worth having. Each step records
    ok / failed / skipped with its output, and the run reports what it could not do.
  * The master table is built and validated in a temporary directory; changed previous files
    are archived before CSV/pickle publication. An implausible rebuild never replaces the master.
  * Player extraction schema is checked before simulation. Dated data is staged/validated as a
    complete bundle, with an external previous-bundle archive and rollback on publication failure.
  * The complete active season is retained. Older snapshots are archived before pruning, only
    after successful projection. Dry runs never write reports, indexes or data.
  * A line a script prints starting "!" is a warning, and is counted on its step's line. Only the
    tail of a script's output is kept, so a warning printed early would otherwise be lost -- which
    is what happened to the Fotmob fetch's notice that a competition had come back empty.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.projection import (  # noqa: E402
    Engine, coerce_params, run_projection, run_projection_parallel,
)

SNAP_DIR = ROOT / "data/snapshots"
# 10,000 worlds -> sqrt(p(1-p)/n) <= 0.005, i.e. every probability good to half a point. That is
# the whole reason to move the compute off the page: a number you can trust day-to-day.
NIGHTLY_WORLDS = 10_000
MASTER_CSV = ROOT / "data/master_fixtures.csv"
MASTER_PKL = ROOT / "data/master_fixtures.pkl"
# Override in isolated checks; production archives are unique directories outside the repo.
ARCHIVE_ROOT: Optional[Path] = Path.home() / "Football_archive_ops"
PY_BIN = str(ROOT / ".venv/bin/python")
from scripts.ops_storage import archive_paths, atomic_write_files, publish_snapshot  # noqa: E402


def _secs(s: float) -> str:
    return f"{s:.1f}s" if s < 60 else f"{int(s // 60)}m{int(s % 60):02d}s"


class Run:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.day = args.date or date.today().isoformat()
        self.dir = SNAP_DIR / self.day
        self.steps: List[Dict[str, Any]] = []
        self.started = time.time()
        self.log_lines: List[str] = []
        # live updates overwrite a line, which only makes sense on a terminal: under launchd the
        # output is a file, and gets each step's finished line and nothing else
        self.tty = sys.stdout.isatty()
        self.position, self.current = "", ""
        self.step_started = self.mark = time.time()
        self.last_output: List[str] = []
        self.last_warnings: List[str] = []

    def log(self, msg: str) -> None:
        """A line for pipeline.log. The terminal gets one line per step -- see `record`."""
        self.log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def begin(self, position: str, name: str) -> None:
        self.position, self.current = position, name
        self.step_started = self.mark = time.time()
        self.progress("running")

    def progress(self, text: str) -> None:
        """What the running step is doing, on a terminal only, overwritten as it goes."""
        if self.tty:
            sys.stdout.write(f"\r\033[K{self.position:>5}  {self.current:<12} {text}")
            sys.stdout.flush()

    def record(self, name: str, status: str, detail: str = "", **extra: Any) -> None:
        """Finish a step: one line on the terminal, the detail in pipeline.json and the log.

        A name other than the running step's is a sub-step -- a day the catch-up backfills --
        and is shown indented beneath it, timed from the line before.
        """
        warnings = extra.get("warnings") or []
        self.steps.append({"step": name, "status": status, "detail": detail, **extra})
        now = time.time()
        sub = name != self.current
        took = now - (self.mark if sub else self.step_started)
        self.mark = now
        word = {"ok": "ok", "failed": "FAILED", "skipped": "skipped"}[status]
        label = (f"{'':>5}  {'· ' + name.split(':', 1)[-1]:<12}" if sub
                 else f"{self.position:>5}  {name:<12}")
        line = f"{label} {word:<7} {_secs(took) if status != 'skipped' else '':>7}"
        if warnings:
            line += f"  {len(warnings)} warning{'s' if len(warnings) > 1 else ''}"
        if status == "failed" and detail:
            line += f"  {detail}"
        if self.tty:
            sys.stdout.write("\r\033[K")
        print(line.rstrip(), flush=True)
        self.log(f"{name}: {word}{(' — ' + detail) if detail else ''}")
        for w in warnings:
            self.log(f"  ! {w}")

    def wants(self, name: str) -> bool:
        if self.args.only:
            return name in self.args.only
        return name not in (self.args.skip or [])

    def shell(self, name: str, cmd: List[str], timeout: int = 1800, record: bool = True) -> bool:
        """Run a step as a subprocess so a crash or a hang is contained.

        With `record=False` a success is left to the caller, which has more to check before it
        can say what happened; `last_output` and `last_warnings` hold what it needs. A failure
        is always recorded here.
        """
        self.last_output, self.last_warnings = [], []
        if not self.wants(name):
            self.record(name, "skipped", "not selected")
            return False
        if self.args.dry_run:
            self.record(name, "skipped", "dry run: " + " ".join(cmd[1:]))
            return False
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.record(name, "failed", f"timed out after {timeout}s")
            return False
        tail = (p.stdout or p.stderr or "").strip().splitlines()
        self.log_lines += [f"    | {ln}" for ln in tail[-40:]]
        self.last_output = tail
        self.last_warnings = [ln.strip().lstrip("!").strip() for ln in tail
                              if ln.strip().startswith("!")]
        # prefer a line that says what happened over whatever the script printed last, which for
        # master_fixtures.py and elo_engine.py is the last row of a summary table
        headline = next((ln.strip() for ln in reversed(tail)
                         if ln.strip().lower().startswith(("wrote", "fetched", "updated"))), None)
        seconds = round(time.time() - self.step_started, 1)
        if p.returncode != 0:
            self.record(name, "failed", (tail[-1] if tail else f"exit {p.returncode}"),
                        seconds=seconds, warnings=self.last_warnings)
            return False
        if record:
            self.record(name, "ok", headline or (tail[-1] if tail else ""), seconds=seconds,
                        warnings=self.last_warnings)
        return True


# --------------------------------------------------------------------------- steps
def step_fotmob(run: Run) -> None:
    """Scrape the live season's fixtures and results.

    This step used to run `--compact`, which gzips leftover plain-JSON cache entries and EXITS
    without fetching anything; `--season` is what actually scrapes. So it reported `ok` every
    night while the fixture table stayed frozen at whenever someone last scraped by hand, and the
    dashboard went on naming an opponent the side had already played. It rendered perfectly --
    the projection was internally consistent, just answering a question about the wrong day.

    The cost is bounded, which is why this can run nightly: detail is fetched only for FINISHED
    matches and the match-detail cache is permanent, so a run pays the fixture enumeration plus
    that day's new results, not a re-scrape of the season.
    """
    if not run.wants("fotmob"):
        run.record("fotmob", "skipped", "not selected")
        return
    if run.args.dry_run:
        run.record("fotmob", "skipped", "dry run: scripts/fetch_fotmob.py --season <live>")
        return
    try:
        season = run.args.season or Engine().live_season()
    except Exception as error:                                      # noqa: BLE001
        run.record("fotmob", "failed", f"could not determine the live season: {error}")
        return
    command=[PY_BIN,"scripts/fetch_fotmob.py","--season",str(season)]
    if getattr(run.args,'refresh_details',False):command.append('--refresh-details')
    run.shell("fotmob",command,timeout=7200 if getattr(run.args,"refresh_details",False) else 2400)


def step_opta(run: Run) -> None:
    run.shell("opta", [PY_BIN, "scripts/fetch_opta.py"], timeout=600)


def step_ratings(run: Run) -> None:
    """Refresh the existing dated Elo source, then rebuild the Opta-derived updater."""
    if not run.wants('ratings'):
        run.record('ratings','skipped','not selected');return
    if run.args.dry_run:
        run.record('ratings','skipped','dry run: refresh retained Elo history and rebuild ratings');return
    if not run.shell('ratings',[PY_BIN,'scripts/fetch_clubelo.py'],timeout=120,record=False):return
    warnings=run.last_warnings.copy()
    if not run.shell('ratings',[PY_BIN,'scripts/opta_ratings.py'],timeout=600,record=False):return
    run.record('ratings','ok',run.last_output[-1] if run.last_output else 'rating sources refreshed',warnings=warnings+run.last_warnings)


def step_master(run: Run) -> None:
    """Build/validate a temporary CSV/pickle pair before publishing changed master bytes."""
    if not run.wants("master"):
        run.record("master", "skipped", "not selected")
        return
    if run.args.dry_run:
        run.record("master", "skipped", "dry run: would rebuild and validate master")
        return
    before = None
    if MASTER_PKL.exists():
        old = pd.read_pickle(MASTER_PKL)
        before = {"rows": len(old), "played": int(old.played.sum()),
                  "npxg": int(old.has_npxg.sum())}
    with tempfile.TemporaryDirectory(prefix="football-master-") as temporary:
        staged_csv = Path(temporary) / "master_fixtures.csv"
        staged_pkl = staged_csv.with_suffix(".pkl")
        if not run.shell("master", [PY_BIN, "scripts/master_fixtures.py", "--include-unplayed",
                                    "--out", str(staged_csv)], record=False):
            return
        try:
            new = pd.read_pickle(staged_pkl)
            bad = []
            if len(new) < 10_000:
                bad.append(f"only {len(new)} rows")
            if before and len(new) < before["rows"] * 0.95:
                bad.append(f"{len(new)} rows vs {before['rows']} before")
            if before and int(new.played.sum()) < before["played"] * 0.95:
                bad.append(f"{int(new.played.sum())} played vs {before['played']} before")
            missing = {"kickoff", "home", "away", "played", "has_npxg", "round", "kind"} - set(new.columns)
            if missing:
                bad.append(f"missing columns {sorted(missing)}")
            if bad:
                raise ValueError("; ".join(bad))
            atomic_write_files({MASTER_CSV: staged_csv.read_bytes(),
                                MASTER_PKL: staged_pkl.read_bytes()}, ARCHIVE_ROOT)
        except Exception as exc:
            run.record("master", "failed", f"rebuild rejected; previous master retained: {exc}",
                       warnings=run.last_warnings)
            return
    owed = int(new.outcome.eq("aborted").sum()) if "outcome" in new else 0
    delta = "" if not before else (f"{len(new) - before['rows']:+d} rows, "
                                  f"{int(new.played.sum()) - before['played']:+d} played, "
                                  f"{int(new.has_npxg.sum()) - before['npxg']:+d} with npxG")
    run.record("master", "ok",
               f"{len(new)} fixtures, {int(new.played.sum())} played"
               + (f", {owed} abandoned and owed" if owed else "")
               + (f" ({delta})" if delta else ""),
               delta=delta, warnings=run.last_warnings)


def step_badges(run: Run) -> None:
    """Each league and UEFA side's badge, for the Visualisations view. Fetches only the ones not
    on disk, so a normal night does nothing; a side left without one is drawn as a dot."""
    run.shell("badges", [PY_BIN, "scripts/fetch_badges.py"], timeout=600)


def step_freshness(run: Run) -> None:
    """Every fixture whose kickoff has passed should be marked played. Count the ones that aren't.

    An accounting identity, in the spirit of the others in this repo, and the check that would
    have caught the `--compact` bug on the first night rather than after a fortnight of snapshots
    built from a frozen table. A stale scrape does not stop the run -- yesterday's fixtures still
    make a projection worth having -- but it must be LOUD, because every downstream number looks
    entirely plausible while being a day or more behind.

    Scoped to the live season on purpose: older seasons keep a handful of fixtures that were
    never played and never will be, so counting across all seasons gives a permanent non-zero
    floor and the signal is lost in it. The 12-hour grace is for the gap between a final whistle
    and the result being published.

    An abandoned match is not the scrape being behind -- Fotmob has it, marked `aborted` -- so it
    is named rather than counted. Counting it failed this step every night from Rayo v Athletic
    (abandoned 10 Oct 2026) until a replay date was set, and a step that always fails is one
    nobody reads, which buries the very failure it exists to raise.
    """
    if not run.wants("freshness"):
        run.record("freshness", "skipped", "not selected")
        return
    if run.args.dry_run:
        run.record("freshness", "skipped", "dry run")
        return
    try:
        engine = Engine()
        season = run.args.season or engine.live_season()
        m = engine.master
        cutoff = pd.Timestamp.now() - pd.Timedelta(hours=12)
        late = m[(m.season == season) & (m.kickoff < cutoff) & ~m.played]
        abandoned = late[late.outcome.eq("aborted")]
        overdue = late.drop(index=abandoned.index)
    except Exception as error:                                      # noqa: BLE001
        run.record("freshness", "failed", f"could not check: {error}")
        return
    played_to = m[m.played].kickoff.max()
    owed = "" if abandoned.empty else (
        "; abandoned, awaiting a new date: " + ", ".join(
            f"{r.home} v {r.away} ({r.kickoff:%Y-%m-%d})" for r in abandoned.itertuples()))
    if overdue.empty:
        run.record("freshness", "ok", f"results complete to {played_to:%Y-%m-%d}{owed}",
                   overdue=0, abandoned=int(len(abandoned)))
        return
    first = overdue.kickoff.min()
    run.record("freshness", "failed",
               f"{len(overdue)} fixture(s) past kickoff still unplayed, oldest {first:%Y-%m-%d}; "
               f"results complete to {played_to:%Y-%m-%d}",
               overdue=int(len(overdue)), oldest=f"{first:%Y-%m-%d}",
               abandoned=int(len(abandoned)))


def _write_compressed_json(out_dir: Path, stem: str, payload: Any) -> Path:
    out_dir = Path(out_dir)
    raw = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode()
    packed = gzip.compress(raw, mtime=0)
    if gzip.decompress(packed) != raw:
        raise ValueError(f"compressed {stem} differs from source")
    destination, plain = out_dir / f"{stem}.json.gz", out_dir / f"{stem}.json"
    # Archive a plain predecessor before publishing/removing it, even if gzip is unchanged.
    if plain.exists():
        archive_paths([plain], ARCHIVE_ROOT)
    atomic_write_files({destination: packed}, ARCHIVE_ROOT)
    if plain.exists():
        plain.unlink()
    return destination


def write_gw_snapshot(out_dir: Path, gw: Dict[str, Any] | bytes) -> Path:
    """Deterministic gzip JSON with archived, verified migration from old plain files."""
    return _write_compressed_json(out_dir, "gw", gw)


def write_players_snapshot(out_dir: Path, players: Dict[str, Any]) -> Path:
    return _write_compressed_json(out_dir, "players", players)


def validate_snapshot_bundle(stage: Path) -> None:
    """Reject an incomplete/corrupt or mismatched staged bundle before old data moves."""
    from scripts.player_stats import PLAYER_SCHEMA_VERSION

    def load(name):
        path = stage / name
        raw = gzip.decompress(path.read_bytes()) if name.endswith(".gz") else path.read_bytes()
        return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    projection = load("projection.json")
    players = load("players.json.gz")
    for name in ("matches.json", "gw.json.gz", "paths.json.gz"):
        load(name)
    if (players.get("season") != projection["params"]["season"]
            or players.get("as_of") != projection.get("as_of")
            or players.get("schema") != PLAYER_SCHEMA_VERSION):
        raise ValueError("snapshot/player season, cutoff or schema mismatch")
    if list(stage.glob("*.partial")):
        raise ValueError("unfinished files in staged snapshot")


def refresh_players_snapshot(day: str, *, snapshot_root: Optional[Path] = None,
                             players_root: Optional[Path] = None, master=None) -> Path:
    """Refresh only the stored sidecar at its recorded cutoff; no worlds or pipeline writes."""
    from scripts.player_stats import build_players, validate_player_inputs
    root = Path(snapshot_root) if snapshot_root is not None else SNAP_DIR
    directory = root / day
    projection = json.loads((directory / "projection.json").read_text())
    season = int(projection["params"]["season"])
    inputs = Path(players_root) if players_root is not None else ROOT / "data/fotmob/players"
    if master is None:
        master = pd.read_pickle(MASTER_PKL)
    validate_player_inputs(inputs, season, master)
    players = build_players(master, season, projection.get("as_of"), inputs)
    # The dated bundle is archived before changing its independently derived sidecar.
    archive_paths([directory], ARCHIVE_ROOT)
    return write_players_snapshot(directory, players)


def step_project(run: Run, as_of: Optional[str] = None, day: Optional[str] = None) -> None:
    """The projection itself. `as_of`/`day` let the catch-up loop reuse this for a missed date."""
    name = "project" + (f":{day}" if day else "")
    if not run.wants("project"):
        run.record(name, "skipped", "not selected")
        return
    if run.args.dry_run:
        run.record(name, "skipped", f"dry run: would simulate {run.args.worlds} worlds")
        return
    as_of = as_of or run.args.as_of
    out_dir = (SNAP_DIR / day) if day else run.dir
    if (out_dir/"projection.json").is_file() and not getattr(run.args,"overwrite_snapshot",False):
        run.record(name,"skipped","snapshot already exists");return
    try:
        engine = Engine()
        season = run.args.season or engine.live_season()
        from scripts.player_stats import validate_player_inputs
        validate_player_inputs(ROOT / "data/fotmob/players", season, engine.master)
        params = coerce_params({"season": season, "worlds": run.args.worlds,
                                "seed": run.args.seed, "replay_played": True,
                                "as_of": as_of}, season, max_worlds=2_000_000)

        def progress(done: int, total: int, stage: str) -> None:
            run.progress(f"{done}/{total} worlds" if stage == "simulating" else stage)

        procs = run.args.processes
        payload = (run_projection_parallel(params, procs, progress, engine) if procs > 1
                   else run_projection(engine, params, progress))
        payload["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload["snapshot"] = day or run.day
        matches = payload.pop("matches")
        gw = payload.pop("gw")
        paths = payload.pop("paths")
        from scripts.player_stats import build_players
        players = build_players(engine.master, season, payload["as_of"], ROOT / "data/fotmob/players")
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".snapshot-stage-", dir=SNAP_DIR) as temporary:
            stage = Path(temporary)
            (stage / "projection.json").write_text(json.dumps(payload, allow_nan=False))
            (stage / "matches.json").write_text(json.dumps(matches, allow_nan=False))
            write_gw_snapshot(stage, gw)
            write_players_snapshot(stage, players)
            _write_compressed_json(stage, "paths", paths)
            # Keep the previous visible report until main writes this Run's final report.
            for report in ("pipeline.json", "pipeline.log"):
                if (out_dir / report).exists():
                    shutil.copy2(out_dir / report, stage / report)
            validate_snapshot_bundle(stage)
            archive = publish_snapshot(stage, out_dir, ARCHIVE_ROOT)
            if archive:
                run.log(f"previous snapshot archived: {archive}")
        payload["match_fixtures"] = len(matches["fixtures"])
        run.record(name, "ok",
                   f"season {season}, {payload['worlds']} worlds in {payload['elapsed']}s "
                   f"on {payload.get('processes', 1)} process(es), "
                   f"+-{payload['mc_se_pp']}pp; "
                   f"{payload.get('match_fixtures', 0)} fixtures with per-match detail; "
                   f"data as of {payload['as_of']}"
                   + (f" (rewound to {as_of})" if as_of else ""),
                   season=season, worlds=payload["worlds"], as_of=payload["as_of"])
    except Exception as exc:                                        # noqa: BLE001
        import traceback
        run.record(name, "failed", f"{type(exc).__name__}: {exc}")
        run.log_lines.append(traceback.format_exc())


def step_track(run: Run) -> None:
    """Evaluate the last pre-kickoff forecasts, independently of projection success."""
    if not run.wants("track"):
        run.record("track", "skipped", "not selected")
        return
    if run.args.dry_run:
        run.record("track", "skipped", "dry run: would score stored match forecasts")
        return
    try:
        from scripts.track_record import build_track, write_track

        master = pd.read_pickle(MASTER_PKL)
        master.attrs = {}
        season = run.args.season or int(master.season.max())
        payload = build_track(master, SNAP_DIR, season, run.args.as_of)
        write_track(payload, SNAP_DIR)
        covered = payload["coverage"]
        run.record("track", "ok",
                   f"{covered['forecast']}/{covered['played']} matches scored; "
                   f"{covered['missing']} without a pre-kickoff forecast; "
                   f"{payload['snapshots']['total']} snapshots read",
                   season=season, **covered)
    except Exception as exc:                                        # noqa: BLE001
        import traceback
        run.record("track", "failed", f"{type(exc).__name__}: {exc}")
        run.log_lines.append(traceback.format_exc())


def missing_days(window_days: int, upto: str) -> List[str]:
    """Every date with no snapshot, inside the window we are willing to rebuild.

    Looks for ANY hole, not just dates after the newest snapshot. A shut laptop leaves a gap at
    the end, but a single failed night leaves one in the middle, and that one would otherwise
    never be filled -- the history would keep a permanent notch. The lower bound is the earliest
    snapshot we hold, so this never tries to backfill before the history starts.
    """
    have=set()
    for directory in SNAP_DIR.iterdir() if SNAP_DIR.exists() else []:
        try:
            if directory.is_dir() and (directory/'projection.json').is_file() and date.fromisoformat(directory.name).isoformat()==directory.name:have.add(directory.name)
        except ValueError:continue
    if not have:
        return []                      # no baseline: inventing a start date would be guessing
    end = pd.Timestamp(upto)
    start = pd.Timestamp(min(have)) if window_days<=0 else max(pd.Timestamp(min(have)), end - pd.Timedelta(days=window_days))
    out, d = [], start
    while d <= end:
        if d.date().isoformat() not in have:
            out.append(d.date().isoformat())
        d += pd.Timedelta(days=1)
    return out


def step_catch_up(run: Run) -> None:
    """Backfill days the job did not run -- a shut laptop, a holiday.

    This is why `--as-of` exists. A projection is a function of the fixtures played by a date, and
    that set is reconstructible after the fact, so a missed Tuesday is recoverable exactly rather
    than left as a hole in the history. The only thing a backfilled night cannot reproduce is the
    Elo mirror as it stood then; that is taken at season start in either case, so it does not
    enter. Run daily and this does nothing.
    """
    if not run.wants("catch_up"):
        run.record("catch_up", "skipped", "not selected")
        return
    if getattr(run.args,"in_backfill",False):
        run.record("catch_up","skipped","dates controlled by backfill plan");return
    days = [d for d in missing_days(run.args.max_catch_up, run.day) if d != run.day]
    days = days[-run.args.max_catch_up:]
    if not days:
        run.record("catch_up", "ok", "no gaps")
        return
    if run.args.dry_run:
        run.record("catch_up", "skipped", f"dry run: would backfill {', '.join(days)}")
        return
    run.log(f"catch_up: backfilling {len(days)} missed day(s): {', '.join(days)}")
    for d in days:
        step_project(run, as_of=d, day=d)
    run.record("catch_up", "ok", f"backfilled {len(days)}: {', '.join(days)}")


def retention_candidates(root: Path, keep: int, active_season: int) -> List[Path]:
    """Keep the full active season plus the newest older snapshots within the keep budget."""
    active, older = [], []
    for directory in sorted(Path(root).iterdir(), reverse=True) if Path(root).exists() else []:
        try:
            if date.fromisoformat(directory.name).isoformat() != directory.name:
                continue
            projection = json.loads((directory / "projection.json").read_text())
            season = int(projection["params"]["season"])
        except (ValueError, OSError, KeyError, TypeError):
            continue
        (active if season >= active_season else older).append(directory)
    return older[max(0, keep - len(active)):]


def step_prune(run: Run) -> None:
    if not run.wants("prune"):
        run.record("prune", "skipped", "not selected")
        return
    projections = [s for s in run.steps if s["step"].startswith("project")]
    if not run.args.dry_run and (not any(s["status"] == "ok" for s in projections)
                                or any(s["status"] == "failed" for s in projections)):
        run.record("prune", "skipped", "requires successful projection with no failed projection")
        return
    seasons = []
    for row in write_index_rows():
        seasons.append(row["season"])
    active = max(seasons + [run.args.season or 0])
    dropped = retention_candidates(SNAP_DIR, run.args.keep, active)
    if run.args.dry_run:
        run.record("prune", "skipped", f"dry run: would archive {len(dropped)} older snapshots; active season retained")
        return
    for directory in dropped:
        archive, _ = archive_paths([directory], ARCHIVE_ROOT)
        shutil.rmtree(directory)
        run.log(f"pruned {directory.name}; archive {archive}")
    run.record("prune", "ok", f"active season {active} retained; {len(dropped)} older snapshots archived")


# in order: the fetches, the table and the ratings they feed, the check on the table, then the
# simulation and its upkeep
PIPELINE: List[Tuple[str, Callable[[Run], None]]] = [
    ("fotmob", step_fotmob), ("opta", step_opta), ("master", step_master),
    ("ratings", step_ratings), ("badges", step_badges), ("freshness", step_freshness),
    ("catch_up", step_catch_up),
    ("project", step_project), ("track", step_track), ("prune", step_prune)]
STEPS = [name for name, _ in PIPELINE]


def write_index_rows() -> List[Dict[str, Any]]:
    """Read the manifest population without changing any file."""
    rows = []
    if SNAP_DIR.exists():
        for d in sorted(SNAP_DIR.iterdir()):
            f = d / "projection.json"
            try:
                if (not d.is_dir() or date.fromisoformat(d.name).isoformat() != d.name
                        or not f.is_file()):
                    continue
                p = json.loads(f.read_text())
                row = {"date": d.name, "season": int(p["params"]["season"]),
                       "worlds": int(p["worlds"]), "as_of": p.get("as_of"),
                       "generated": p.get("generated"), "elapsed": p.get("elapsed"),
                       "bytes": f.stat().st_size}
            except (ValueError, OSError, KeyError, TypeError):
                continue
            rows.append(row)
    return rows


def write_index() -> List[Dict[str, Any]]:
    rows = write_index_rows()
    atomic_write_files({SNAP_DIR / "index.json": json.dumps(rows, indent=1).encode()}, ARCHIVE_ROOT)
    return rows


def backfill_plan(end: Optional[str] = None, start: Optional[str] = None) -> List[Tuple[str, str, int]]:
    """Recorded dates/cutoffs, optionally filling every calendar date from an explicit start.

    Existing bundles keep their exact cutoff/season. New dates use that date as their requested
    inclusive cutoff and the nearest earlier stored season (first stored season before history).
    Reading a plan never writes the index, fetches sources or prepares a model.
    """
    stop = date.fromisoformat(end) if end else date.today()
    if stop > date.today():
        raise ValueError("backfill end cannot be in the future")
    anchors = sorted(write_index_rows(), key=lambda row: row['date'])
    if not anchors:
        raise ValueError("no stored snapshots to establish the backfill season")
    rows = [row for row in anchors if row['date'] <= stop.isoformat()]
    if start is None and not rows:
        raise ValueError("no stored snapshots at or before the backfill end")
    recorded = {}
    for row in rows:
        day, cutoff = row['date'], row.get('as_of')
        if not cutoff or date.fromisoformat(cutoff).isoformat() != cutoff or cutoff > day:
            raise ValueError(f"invalid recorded as_of for {day}: {cutoff!r}")
        recorded[day] = (day, cutoff, row['season'])
    if start is None:
        return list(recorded.values())
    begin = date.fromisoformat(start)
    if begin > stop:
        raise ValueError("backfill start must be on or before its end")
    plan = []
    for ordinal in range(begin.toordinal(), stop.toordinal() + 1):
        day = date.fromordinal(ordinal).isoformat()
        if day in recorded:
            plan.append(recorded[day])
        else:
            anchor = next((row for row in reversed(anchors) if row['date'] <= day), anchors[0])
            plan.append((day, day, int(anchor['season'])))
    return plan


def run_backfill(args) -> int:
    """Repeat the normal nightly job for each stored date, with its recorded cutoff."""
    import contextlib
    start = getattr(args, 'backfill_start', None)
    if not getattr(args, 'stored_only', False) and start is None:
        anchors = sorted(write_index_rows(), key=lambda row: row['date'])
        eligible = [row for row in anchors if row['date'] <= (args.date or date.today().isoformat())]
        if not anchors:
            raise ValueError("no stored snapshots to establish the backfill season")
        season = int((eligible[-1] if eligible else anchors[0])['season'])
        start = f"{season}-08-01"
    plan = backfill_plan(args.date, start=None if getattr(args, 'stored_only', False) else start)
    print(f"backfill {len(plan)} calendar dates: {plan[0][0]} to {plan[-1][0]} · {args.worlds:,} worlds/date", flush=True)
    if args.dry_run:
        for day, cutoff, season in plan:
            print(f"  {day} · as_of {cutoff} · season {season} · normal nightly pipeline")
        return 0
    log_path = None
    try:
        archive, _ = archive_paths([ROOT / "data"], ARCHIVE_ROOT)
        if archive is None:
            raise ValueError("data directory missing; nothing was archived")
        log_path = ROOT / "data" / f"backfill_{time.time_ns()}.log"
        print(f"archive: {archive}\nlog: {log_path}", flush=True)
        with log_path.open("x", encoding="utf-8") as log:
            class Tee:
                def __init__(self, stream):
                    self.stream = stream
                def write(self, text):
                    self.stream.write(text)
                    log.write(text)
                    return len(text)
                def flush(self):
                    self.stream.flush()
                    log.flush()
                def isatty(self):
                    return False
            with contextlib.redirect_stdout(Tee(sys.stdout)), contextlib.redirect_stderr(Tee(sys.stderr)):
                refreshed_seasons=set()
                for i, (day, cutoff, season) in enumerate(plan, 1):
                    print(f"[{i}/{len(plan)}] nightly {day} · as_of {cutoff}", flush=True)
                    daily = argparse.Namespace(**vars(args))
                    daily.date, daily.as_of, daily.season = day, cutoff, season
                    daily.backfill, daily.only, daily.skip = False, None, None
                    daily.overwrite_snapshot=True
                    daily.in_backfill=True
                    daily.require_fresh_sources=True
                    daily.refresh_details=season not in refreshed_seasons
                    status = run_nightly(daily)
                    if status==0:refreshed_seasons.add(season)
                    if status:
                        print(f"backfill stopped at {day}; nightly exit {status}", flush=True)
                        return status
                    print(f"[{i}/{len(plan)}] complete", flush=True)
                print(f"DONE: {len(plan)} normal nightly runs finished; individual step failures are reported above.", flush=True)
        return 0
    except KeyboardInterrupt:
        print(f"backfill interrupted; log: {log_path}", flush=True)
        return 130
    except (OSError, ValueError) as error:
        print(f"backfill FAILED: {error}; log: {log_path}", flush=True)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worlds", type=int, default=NIGHTLY_WORLDS,
                    help="worlds for the nightly projection. 10,000 puts the Monte-Carlo error on "
                         "any probability at or below 0.5pp, so movement between two nights is "
                         "signal rather than sampling noise; at 300 it is +-2.9pp and a trend "
                         "line just jitters.")
    ap.add_argument("--season", type=int, default=None, help="default: the live season")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--keep", type=int, default=180,
                    help="recent snapshot budget; the complete active season is always retained")
    ap.add_argument("--backfill", action="store_true",
                    help="run every calendar date from 1 August of the stored season through today; preserve existing cutoffs; --date limits the end")
    ap.add_argument("--backfill-start", default=None, help="override the backfill start (YYYY-MM-DD); default 1 August of the stored season")
    ap.add_argument("--stored-only", action="store_true", help="with --backfill, rebuild existing dates only (the previous behaviour)")
    ap.add_argument("--refresh-players", action="store_true",
                    help="refresh only a dated snapshot's player sidecar at its recorded cutoff; no worlds")
    ap.add_argument("--date", default=None, help="label this run with a given date")
    ap.add_argument("--as-of", default=None,
                    help="rewind the season to what was known on this date (YYYY-MM-DD). Use with "
                         "--date to backfill the projection history; implies --only project")
    ap.add_argument("--only", nargs="+", choices=STEPS, default=None)
    ap.add_argument("--skip", nargs="+", choices=STEPS, default=None)
    ap.add_argument("--processes", type=int, default=max(1, (os.cpu_count() or 4) - 4),
                    help="processes for the projection. Worlds are independent and each one's "
                         "seed is a function of its index, so the result is identical whatever "
                         "this is set to -- verified, not assumed.")
    ap.add_argument("--max-catch-up", type=int, default=0,
                    help="limit normal catch-up days; default0 fills every missing date since history starts")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if (args.backfill_start or args.stored_only) and not args.backfill:
        ap.error("--backfill-start/--stored-only require --backfill")
    if args.backfill:
        if args.backfill_start and args.stored_only:
            ap.error("--backfill-start cannot be combined with --stored-only")
        if args.as_of or args.only or args.skip or args.refresh_players or args.season is not None:
            ap.error("--backfill uses recorded seasons/cutoffs and cannot use --as-of/--only/--skip/--refresh-players/--season")
        if not 1 <= args.worlds <= 2_000_000 or args.processes < 1:
            ap.error("--backfill requires 1..2000000 worlds and at least one process")
        try:
            return run_backfill(args)
        except (ValueError, TypeError) as error:
            ap.error(str(error))
    if args.refresh_players:
        if not args.date or args.as_of or args.only or args.skip:
            ap.error("--refresh-players requires --date and cannot use --as-of/--only/--skip")
        if args.dry_run:
            print(f"dry run: would refresh player sidecar for {args.date}")
        else:
            print(f"wrote {refresh_players_snapshot(args.date)}")
        return 0
    if args.as_of and args.only is None:
        args.only = ["project"]

    return run_nightly(args)


def run_nightly(args) -> int:
    """One normal nightly pipeline; shared by the CLI and historical repeats."""
    run = Run(args)
    existing=(run.dir/'projection.json').is_file() and not getattr(args,'overwrite_snapshot',False)
    if existing and not args.only and not [d for d in missing_days(args.max_catch_up,run.day) if d!=run.day]:
        print(f"nightly {run.day} · skipped (snapshot exists; --backfill rebuilds existing dates)",flush=True)
        return 0
    header = (f"nightly {run.day} · "
              + ("dry run" if args.dry_run else f"{args.worlds:,} worlds"))
    print(header, flush=True)
    run.log(header)
    for i, (name, step) in enumerate(PIPELINE, 1):
        run.begin(f"{i}/{len(PIPELINE)}", name)
        try:
            step(run)
            if getattr(args,'require_fresh_sources',False) and name in {'fotmob','opta','master','ratings'} and any(s['step']==name and s['status']=='failed' for s in run.steps):break
        except Exception as exc:                                    # noqa: BLE001
            import traceback
            run.record(name, "failed", f"{type(exc).__name__}: {exc}")
            run.log_lines.append(traceback.format_exc())
            if getattr(args,'require_fresh_sources',False) and name in {'fotmob','opta','master','ratings'}:break

    ok = [s for s in run.steps if s["status"] == "ok"]
    failed = [s for s in run.steps if s["status"] == "failed"]
    warned = sum(len(s.get("warnings") or []) for s in run.steps)
    summary = {"date": run.day, "seconds": round(time.time() - run.started, 1),
               "steps": run.steps, "ok": len(ok), "failed": len(failed),
               "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not args.dry_run:
        if not existing:
            atomic_write_files({run.dir / "pipeline.json": json.dumps(summary, indent=1).encode(),
                                run.dir / "pipeline.log": ("\n".join(run.log_lines) + "\n").encode()}, ARCHIVE_ROOT)
        write_index()
    parts = [f"{len(ok)} ok"]
    if failed:
        parts.append(f"{len(failed)} failed ({', '.join(s['step'] for s in failed)})")
    if warned:
        parts.append(f"{warned} warning{'s' if warned > 1 else ''}")
    if not args.dry_run and not existing:
        parts.append(f"details in {(run.dir / 'pipeline.log').relative_to(ROOT)}")
    print(f"done in {_secs(summary['seconds'])} · " + " · ".join(parts), flush=True)
    # A normal full nightly can still publish from yesterday's inputs after a fetch fails.
    # Explicit isolated work reports its selected step failures to the caller.
    project_failed = any(s["step"].startswith("project") for s in failed)
    selected_failed = bool(args.only) and any(s["step"].split(":", 1)[0] in args.only for s in failed)
    source_failed=getattr(args,'require_fresh_sources',False) and any(s['step'] in {'fotmob','opta','master','ratings'} for s in failed)
    return 1 if project_failed or selected_failed or source_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
