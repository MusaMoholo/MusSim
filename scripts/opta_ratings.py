#!/usr/bin/env python3
"""Opta's ratings as the per-match updater for sides whose matches we do not see.

    .venv/bin/python scripts/opta_ratings.py          # rebuild data/external/opta_path.json

THE GAP. A world's strength state moves only on matches in our fourteen competitions. A side in
one of our five leagues plays all its competitive football there, so that is its whole season.
Every other side -- a UEFA club from a league we do not track, a Championship club in the FA Cup
-- plays most of its matches where we cannot see them, and between its appearances in our data
its state stood still: PSV were the PSV of 1 August whatever they did in the Eredivisie. Opta
rates ~10,000 sides every couple of days on all of their matches, which is exactly what those
sides were missing.

Rebuilt in memory at each forecast cutoff from eligible dated observations only. Alignment,
level conversion, movement regression and opponent populations cannot see later snapshots.
With one observation movement is zero; with none the forecast uses founded preseason priors.
Opta levels first observed later may initialise a current-cutoff rating, never an August start.
The five tracked leagues move through their observed results and npxG, not Opta updates.

"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from football_common import canonical_elo_team_name, canonical_team_name  # noqa: E402
from scripts.cup_bracket import is_slot  # noqa: E402
from scripts.elo_engine import expected_home  # noqa: E402
from scripts.simulate_season import HOME_ADV, K_ELO, UEFA_HOME_ADV  # noqa: E402

OPTA_DIR = ROOT / "data/team_rankings_history"
ELO_CSV = ROOT / "data/external/elo_ratings.csv"
MASTER = ROOT / "data/master_fixtures.pkl"
OUT = ROOT / "data/external/opta_path.json"
FULLY_SEEN = ("English Premier League", "Spanish La Liga", "Italian Serie A",
              "German Bundesliga", "French Ligue 1")

# When a side's league is not playing. Spring-to-autumn leagues stop for the northern winter; the
# rest of Europe takes a short break around new year, England excepted. Keyed on Opta's `country`.
CALENDAR_YEAR = {"Norway", "Sweden", "Finland", "Iceland", "Republic of Ireland", "Ireland",
                 "Lithuania", "Latvia", "Estonia", "Faroe Islands", "Kazakhstan", "Belarus",
                 "Georgia"}
NO_BREAK = {"England", "Wales", "Scotland", "Northern Ireland"}


# Our name -> Opta's, where neither the canonical map nor the folded spelling reaches it. "NEC" is
# also the name of a Ugandan side, which is why a country check sits behind every match below.
OPTA_ALIASES = {"NEC Nijmegen": "NEC", "St.Truiden": "Sint-Truiden"}
# the country a domestic competition's sides play in, as Opta spells it
COUNTRY = {"English": "England", "Spanish": "Spain", "Italian": "Italy", "German": "Germany",
           "French": "France"}


def _key(name: Any) -> str:
    return canonical_elo_team_name(canonical_team_name(name))


def _fold(name: Any) -> str:
    """Letters and digits only, accents dropped: "Hapoel Be'er Sheva" is "Hapoel Beer Sheva"."""
    import unicodedata
    text = unicodedata.normalize("NFKD", str(name).lower())
    return "".join(ch for ch in text if ch.isalnum() and not unicodedata.combining(ch))


# --------------------------------------------------------------------------- the snapshots
def load_snapshots(directory: Path = OPTA_DIR, before: Optional[pd.Timestamp] = None) -> Dict[pd.Timestamp, pd.DataFrame]:
    """Snapshot date -> (id, names, rating, country, league), whichever layout the file has.

    Four layouts so far: the first file has no contestant ids at all and is skipped; the league
    column was `domesticLeagueName` until 2026-10-06 and `league` from 2026-10-12.
    """
    out: Dict[pd.Timestamp, pd.DataFrame] = {}
    for f in sorted(directory.glob("team_rankings-*.csv")):
        when = pd.Timestamp(re.search(r"(\d{4}-\d{2}-\d{2})", f.name).group(1))
        if before is not None and when >= before:
            continue
        d = pd.read_csv(f)
        if not {"contestantId", "currentRating"} <= set(d.columns):
            if set(d.columns) == {"rank", "team", "rating", "ranking_change_7d"}:
                continue  # retained legacy names-only layout
            raise ValueError(f"invalid Opta snapshot schema: {f}")
        if d.empty or d.contestantId.isna().any() or d.contestantId.duplicated().any():
            raise ValueError(f"empty or ambiguous Opta identities: {f}")
        if not np.isfinite(pd.to_numeric(d.currentRating, errors="coerce")).all():
            raise ValueError(f"invalid Opta rating: {f}")
        league = "league" if "league" in d else "domesticLeagueName"
        when = pd.Timestamp(re.search(r"(\d{4}-\d{2}-\d{2})", f.name).group(1))
        out[when] = pd.DataFrame({
            "id": d["contestantId"], "rank": d["rank"], "rating": d["currentRating"],
            "name": d["contestantName"], "club": d.get("contestantClubName"),
            "short": d.get("contestantShortName"), "country": d.get("country"),
            "league": d.get(league)}).drop_duplicates("id").set_index("id")
    return out


def aligned(snaps: Dict[pd.Timestamp, pd.DataFrame]) -> pd.DataFrame:
    """Ratings by side and snapshot, every snapshot rescaled onto the first one's scale."""
    dates = sorted(snaps)
    ref = snaps[dates[0]].rating
    cols = {}
    for d in dates:
        x = snaps[d].rating
        j = pd.concat([ref.rename("r"), x.rename("x")], axis=1, join="inner")
        a, b = np.polyfit(j.r, j.x, 1)
        cols[d] = (x - b) / a
    return pd.DataFrame(cols)


def name_index(snap: pd.DataFrame) -> Dict[str, List[str]]:
    """Name key -> contestant ids, highest-ranked first. Two exact keys per name -- the canonical
    one and the folded spelling -- and nothing fuzzy."""
    out: Dict[str, List[str]] = {}
    for col in ("name", "club", "short"):
        for cid, v in snap.sort_values("rank")[col].dropna().items():
            for k in (_key(v), _fold(v)):
                ids = out.setdefault(k, [])
                if cid not in ids:
                    ids.append(cid)
    return out


def match_ids(teams: List[str], snap: pd.DataFrame,
              country: Dict[str, str]) -> Dict[str, str]:
    """Our side -> contestant id. Where our data says which country a side plays in, the match
    must be from it; otherwise the highest-ranked namesake wins."""
    index = name_index(snap)
    out: Dict[str, str] = {}
    for t in teams:
        name = OPTA_ALIASES.get(t, t)
        for k in (_key(name), _fold(name)):
            hit = next((cid for cid in index.get(k, [])
                        if country.get(t) is None or snap.country.get(cid) == country[t]), None)
            if hit is not None:
                out[t] = hit
                break
    return out


# --------------------------------------------------------------------------- our own walk
def elo_walk(fixtures: pd.DataFrame, elo0: Dict[str, float],
             at: List[pd.Timestamp]) -> pd.DataFrame:
    """Every side's Elo at each date in `at`, walked through the played fixtures exactly as a
    world's replay walks it (`simulate_season._World._feedback`)."""
    elo = dict(elo0)
    seed = float(np.percentile(list(elo0.values()), 5)) if elo0 else 1400.0
    played = fixtures[fixtures.played & fixtures.home_goals.notna()].sort_values("kickoff")
    out, k = {}, 0
    stops = sorted(at)
    for r in played.itertuples():
        while k < len(stops) and r.kickoff >= stops[k]:
            out[stops[k]] = dict(elo)
            k += 1
        eh, ea = elo.get(r.home, seed), elo.get(r.away, seed)
        ha = UEFA_HOME_ADV if r.kind == "uefa" else HOME_ADV
        e = float(expected_home(np.array([eh]), np.array([ea]), ha)[0])
        s = 1.0 if r.home_goals > r.away_goals else (0.5 if r.home_goals == r.away_goals else 0.0)
        elo[r.home], elo[r.away] = eh + K_ELO * (s - e), ea - K_ELO * (s - e)
    for t in stops[k:]:
        out[t] = dict(elo)
    return pd.DataFrame(out)


def draw_rate(master: pd.DataFrame) -> float:
    """P(draw) in an even league match, counted: the scale of an unseen match's draw chance."""
    g = master[master.played & master.elo_ok & (master.kind == "league")]
    e = expected_home(g.home_elo.to_numpy(float), g.away_elo.to_numpy(float), HOME_ADV)
    even = (e >= 0.4) & (e < 0.6)
    return float((g.home_goals == g.away_goals).to_numpy()[even].mean()) if even.any() else 0.25


# --------------------------------------------------------------------------- build
def build(master: pd.DataFrame, season: int, elo_csv: Path = ELO_CSV,
          directory: Path = OPTA_DIR, before: Optional[pd.Timestamp] = None) -> Optional[Dict[str, Any]]:
    fx = master[master.season == season]
    snaps = load_snapshots(directory, before)
    if not snaps:
        return None
    if before is not None:
        # Future results must not calibrate movement or the unseen-match draw model.
        master = master[master.kickoff < before]
        fx = fx.copy()
        fx.loc[fx.kickoff >= before, "played"] = False
    dates = sorted(snaps)
    al = aligned(snaps)
    first, last = dates[0], dates[-1]

    # Level map uses a dated Elo observation no later than the first eligible Opta snapshot.
    mirror = pd.read_csv(elo_csv, parse_dates=["date"])
    mirror = mirror[mirror.date < (before if before is not None else first + pd.Timedelta(days=1))]
    eligible = mirror[mirror.date <= first]
    if eligible.empty:
        return None
    near = eligible.date.max()
    clubelo = mirror[mirror.date == near].groupby("club").elo.last()
    idx0 = name_index(snaps[first])
    pairs = [(idx0[_key(c)][0], v) for c, v in clubelo.items() if _key(c) in idx0]
    pairs = [(cid, v) for cid, v in pairs if cid in al.index and np.isfinite(al.at[cid, first])]
    px = np.array([al.at[cid, first] for cid, _ in pairs])
    py = np.array([v for _, v in pairs])
    level = np.polyfit(px, py, 3)
    level_sd = float(np.std(py - np.polyval(level, px)))
    mapped = al.apply(lambda col: pd.Series(np.polyval(level, col), index=col.index))

    # which of our sides we see every match of, and the rest
    ours = sorted(t for t in set(fx.home) | set(fx.away) if not is_slot(t))
    seen = set(fx[fx.competition.isin(FULLY_SEEN)].home) | set(fx[fx.competition.isin(FULLY_SEEN)].away)
    domestic = fx[fx.kind != "uefa"]
    country = {t: COUNTRY[c.split()[0]] for c, g in domestic.groupby("competition")
               if c.split()[0] in COUNTRY for t in set(g.home) | set(g.away)}
    ids = match_ids(ours, snaps[last], country)

    # beta: our walk's movement against Opta's, first snapshot to last, over the fully seen sides
    start = fx.kickoff.min()
    pos = mirror[mirror.date < start].date.max()
    elo0 = {}
    look = {canonical_elo_team_name(c): float(v)
            for c, v in mirror[mirror.date == pos].groupby("club").elo.last().items()}
    for t in ours:
        if canonical_elo_team_name(t) in look:
            elo0[t] = look[canonical_elo_team_name(t)]
    walk = elo_walk(fx, elo0, sorted({first, last}))
    # only sides the walk starts from a real rating: a promoted side ClubElo never rated starts
    # at the default, and its first weeks are the walk catching up, not the side moving
    rows = [(walk.at[t, last] - walk.at[t, first], mapped.at[ids[t], last] - mapped.at[ids[t], first])
            for t in sorted(seen) if t in ids and t in elo0 and ids[t] in mapped.index
            and np.isfinite(mapped.at[ids[t], last]) and np.isfinite(mapped.at[ids[t], first])]
    dw, do = np.array(rows).T if rows else (np.array([]), np.array([]))
    enough = len(rows) > 10 and float(np.std(do)) > 1e-8 and float(np.std(dw)) > 1e-8
    beta = float(np.polyfit(do, dw, 1)[0]) if enough else 0.0
    corr = float(np.corrcoef(do, dw)[0, 1]) if enough else None

    # leagues: mean mapped strength over every side Opta places in them, at the latest snapshot
    snap = snaps[last]
    lg_mean = (pd.DataFrame({"league": snap.league, "elo": mapped[last].reindex(snap.index)})
               .dropna().groupby("league").elo.agg(["mean", "size"]))
    leagues = {lg: round(float(r["mean"]), 1) for lg, r in lg_mean.iterrows() if r["size"] >= 4}

    teams: Dict[str, Any] = {}
    for t in ours:
        if t in seen or t not in ids:
            continue
        cid = ids[t]
        series = (mapped.loc[cid] if cid in mapped.index else pd.Series(dtype=float)).dropna()
        if series.empty:
            continue
        # movement is measured from the side's own first appearance, which for most is the
        # first snapshot and for a side Opta began listing later is that later one
        base = float(series.iloc[0])
        path = [[d.strftime("%Y-%m-%d"), round(beta * float(v - base), 2)]
                for d, v in series.items()]
        teams[t] = {"id": cid, "league": snap.league.get(cid), "country": snap.country.get(cid),
                    "elo": round(float(base), 1), "path": path}
    unmatched = [t for t in ours if t not in seen and t not in teams]
    return {"season": season, "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "snapshots": [d.strftime("%Y-%m-%d") for d in dates],
            "level_map": {"coef": [float(c) for c in level], "clubelo_date": str(near.date()),
                          "clubs": len(pairs), "resid_sd": round(level_sd, 1)},
            "beta": round(beta, 4), "beta_fit": {"clubs": len(rows), "corr": round(corr, 3) if corr is not None else None},
            "draw0": round(draw_rate(master), 4), "k": K_ELO, "home_adv": HOME_ADV,
            "leagues": leagues, "start": {}, "teams": teams, "unmatched": unmatched}


# --------------------------------------------------------------------------- consumed by the sim
class Unseen:
    """What a world needs to keep the sides it cannot see moving: an Opta path up to the cutoff,
    and a calendar of unseen matches after it. Built once per run; a world only reads it."""

    def __init__(self, art: Dict[str, Any], until: Optional[pd.Timestamp],
                 horizon: pd.Timestamp):
        self.k, self.draw0, self.home_adv = art["k"], art["draw0"], art["home_adv"]
        self.start: Dict[str, float] = dict(art.get("start", {}))
        self.anchors: Dict[str, Tuple[List[pd.Timestamp], List[float]]] = {}
        self.calendar: Dict[str, List[pd.Timestamp]] = {}
        self.opponent: Dict[str, float] = {}
        for team, t in art["teams"].items():
            dated = [(pd.Timestamp(d), v) for d, v in t["path"]
                     if until is None or pd.Timestamp(d) <= until]
            if not dated:
                continue
            # a snapshot is pulled mid-afternoon and may already hold that day's early kickoffs,
            # so it counts from the next day -- never before a match it might contain
            self.anchors[team] = ([d + pd.Timedelta(days=1) for d, _ in dated],
                                  [v for _, v in dated])
            lg = art["leagues"].get(t.get("league"))
            if lg is None:
                continue
            self.opponent[team] = lg
            self.calendar[team] = schedule(self.anchors[team][0][-1], horizon, t.get("country"))

    def var(self, elo: float, opp: float) -> float:
        """Variance of one unseen match's Elo change: K^2 Var(S), averaged over the venue."""
        out = 0.0
        for ha in (self.home_adv, -self.home_adv):
            e = 1.0 / (1.0 + 10.0 ** (-(elo - opp + ha) / 400.0))
            d = self.draw0 * np.sqrt(max(1.0 - (2.0 * e - 1.0) ** 2, 0.0))
            out += e * (1.0 - e) - d / 4.0
        return self.k ** 2 * out / 2.0


def schedule(after: pd.Timestamp, until: pd.Timestamp, country: Optional[str]) -> List[pd.Timestamp]:
    """One unseen league match a week, skipping the side's league's break."""
    out, t = [], after + pd.Timedelta(days=7)
    while t <= until:
        m, dd = t.month, t.day
        if country in CALENDAR_YEAR:
            off = m in (12, 1, 2) or (m == 3 and dd < 15)
        elif country in NO_BREAK:
            off = False
        else:
            off = (m == 12 and dd >= 22) or (m == 1 and dd < 10)
        if not off:
            out.append(t)
        t += pd.Timedelta(days=7)
    return out


def load(season: int, path: Path = OUT) -> Optional[Dict[str, Any]]:
    """The artefact for `season`, or None -- no file, or built for another season."""
    if not path.exists():
        return None
    art = json.loads(path.read_text())
    return art if art.get("season") == season else None


def main() -> int:
    master = pd.read_pickle(MASTER)
    season = int(master[master.played].season.max())
    art = build(master, season)
    if art is None:
        raise RuntimeError("no eligible id-keyed Opta snapshots")
    from scripts.ops_storage import atomic_write_files
    atomic_write_files({OUT: json.dumps(art, allow_nan=False).encode()})
    print(f"wrote {OUT.relative_to(ROOT)}: {len(art['teams'])} sides on Opta paths over "
          f"{len(art['snapshots'])} snapshots, {len(art['unmatched'])} unmatched; beta "
          f"{art['beta']} (corr {art['beta_fit']['corr']} on {art['beta_fit']['clubs']} clubs); "
          f"level map {art['level_map']['resid_sd']} Elo on {art['level_map']['clubs']} clubs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
