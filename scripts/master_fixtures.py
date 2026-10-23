#!/usr/bin/env python3
"""The master fixture table: one row per fixture, every competition, sorted by kickoff.

Shape follows fixturedownload.com's own convention -- a fixture is a ROW (home team, away team,
result), not two team-match rows -- extended with Fotmob's non-penalty xG and point-in-time
ClubElo for both sides. All 14 competitions live in ONE table ordered by kickoff timestamp, so a
congested week interleaves league, domestic cup and UEFA ties in true chronological order. That
ordering is what makes a walk-forward backtest honest (train on everything strictly before a
kickoff, whatever competition it was in) and it is the same table the simulator consumes.

    .venv/bin/python scripts/master_fixtures.py                       # played fixtures only
    .venv/bin/python scripts/master_fixtures.py --include-unplayed    # + scheduled, for the sim
    .venv/bin/python scripts/master_fixtures.py --seasons 2021 2022 2023 2024 2025

Writes data/master_fixtures.csv (and .pkl alongside, for speed).

Why point-in-time ClubElo and not Opta: Opta's feed history begins 2026-08-21, so using it for a
2023 match would reintroduce exactly the staleness bias PLAN.md Phase 3 diagnosed. ClubElo is
genuinely dated back to 2000. Its mirror covers 19 countries, so clubs outside them (Swiss, Czech,
Croatian, Ukrainian, Serbian, Hungarian sides in UEFA, and lower-league domestic cup entrants)
carry no rating -- those rows keep `elo_ok = False` and are NEVER dropped here. Dropping unrated
clubs is a known bias trap (HANDOFF.md: it moved a fitted slope 4.09 -> 4.88, because unrated
clubs are systematically the weakest); the model gives them a fallback prior instead.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from football_common import (  # noqa: E402
    canonical_elo_team_name, canonical_fotmob_team_name, parse_score,
)
from scripts.ops_storage import atomic_write_files  # noqa: E402

FOTMOB_DIR = Path("data/fotmob")
ELO_FILE = Path("data/external/elo_ratings.csv")
OUT_CSV = Path("data/master_fixtures.csv")

# competition -> (region, slug, kind).  `kind` separates the three tiers because baseline scoring
# level and home advantage differ by tier, while per-team attack/defence does not.
COMPETITIONS: Dict[str, Tuple[str, str, str]] = {
    "English Premier League":  ("England", "epl", "league"),
    "Spanish La Liga":         ("Spain", "la-liga", "league"),
    "German Bundesliga":       ("Germany", "bundesliga", "league"),
    "Italian Serie A":         ("Italy", "serie-a", "league"),
    "French Ligue 1":          ("France", "ligue-1", "league"),
    "UEFA Champions League":   ("UEFA", "champions-league", "uefa"),
    "UEFA Europa League":      ("UEFA", "europa-league", "uefa"),
    "UEFA Conference League":  ("UEFA", "conference-league", "uefa"),
    "English FA Cup":          ("England", "fa-cup", "cup"),
    "English League Cup":      ("England", "efl-cup", "cup"),
    "Spanish Copa del Rey":    ("Spain", "copa-del-rey", "cup"),
    "Italian Coppa Italia":    ("Italy", "coppa-italia", "cup"),
    "German DFB Pokal":        ("Germany", "dfb-pokal", "cup"),
    "French Coupe de France":  ("France", "coupe-de-france", "cup"),
}

NUMERIC = ["home_xg", "away_xg", "home_npxg", "away_npxg", "home_xgot", "away_xgot",
           "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
           "home_big_chances", "away_big_chances", "home_possession", "away_possession",
           "home_corners", "away_corners", "home_pen_goals", "away_pen_goals"]


# A cup whose bracket is fixed publishes the LATER rounds before the teams that fill them are
# known, using the slot's name in place of a club: the Coppa Italia calendar carries "Winner EF1",
# "Winner QF 1", "Winner SF 1", and -- for a round-of-16 tie whose feeder is still to be played --
# "Pisa/Fiorentina". Sixteen such rows were reaching the simulator as if they were clubs, picking
# up the 5th-percentile default rating and playing a match in every world.
#
# They are dropped here rather than downstream because they are not fixtures: no team is known, so
# there is nothing to play. What they DO carry -- the date and the shape of the round -- is
# recovered by `scripts/cup_bracket.py` from the previous season's calendar, the same way
# `uefa_bracket.stage_calendar` dates a UEFA stage that has not been drawn.
#
# Matched conservatively. "Bodo / Glimt" is a real club and must survive, so a bare slash is not
# enough: the name must either start with a slot word or be two known-looking halves with no
# spaces around the slash.
_SLOT_PREFIXES = ("winner ", "loser ", "sieger ", "verlierer ", "vainqueur ", "ganador ",
                  "vincente ", "perdente ", "tbd", "to be determined", "bye")


def is_placeholder_team(name: object) -> bool:
    """True for a bracket slot masquerading as a club name."""
    text = str(name).strip()
    low = text.lower()
    if low.startswith(_SLOT_PREFIXES):
        return True
    # "Pisa/Fiorentina" -- two names joined with no spaces. "Bodo / Glimt" has them, and is a club.
    return "/" in text and " / " not in text


def load_fixtures(seasons: Optional[List[int]], include_unplayed: bool) -> pd.DataFrame:
    frames = []
    for comp, (region, slug, kind) in COMPETITIONS.items():
        for path in sorted((FOTMOB_DIR / region / comp).glob(f"{slug}-*.csv")):
            season = int(re.search(r"-(\d{4})\.csv$", path.name).group(1))
            if seasons is not None and season not in seasons:
                continue
            raw = pd.read_csv(path)
            # An abandoned match still carries a plausible-looking score (PLAN.md Part II: Caen PTT
            # 0-0 Evreux), so `aborted` is never trusted. But `penalties` and `afterextratime` ARE
            # real completed matches: filtering to `fulltime` alone silently dropped 252 of them,
            # every one in a cup competition (the leagues have zero), which is why a ClubElo update
            # rule fitted on cup fortnights came out at corr 0.50 against 0.997 for league-only --
            # ClubElo counts those matches and we were not showing them to the fit.
            #   penalties      -> `Result` is the score when the shootout began, i.e. a DRAW
            #   afterextratime -> `Result` is the final extra-time score, i.e. decisive
            PLAYED = ("fulltime", "penalties", "afterextratime")
            played = (raw.get("outcome").isin(PLAYED) if "outcome" in raw
                      else pd.Series(False, index=raw.index))
            if not include_unplayed:
                raw = raw[played].copy()
                played = played[played.index.isin(raw.index)]
            scores = raw["Result"].map(parse_score) if "Result" in raw else [(None, None)] * len(raw)
            hg = [h for h, _ in scores]
            ag = [a for _, a in scores]
            out = pd.DataFrame({
                "season": season,
                "competition": comp,
                "kind": kind,
                "match_id": raw.get("match_id"),
                "kickoff": pd.to_datetime(raw["Date"], dayfirst=True, errors="coerce"),
                "round": pd.to_numeric(raw.get("Round Number"), errors="coerce"),
                # Preserve explicit qualifier/stage labels for competition-aware consumers;
                # numeric round remains unchanged for league/phase table calculations.
                "round_label": raw.get("Round Number", pd.Series(index=raw.index, dtype="object"))
                                  .astype("string"),
                "home": raw["Home Team"].map(canonical_fotmob_team_name),
                "away": raw["Away Team"].map(canonical_fotmob_team_name),
                "played": played.to_numpy(dtype=bool),
                "outcome": raw.get("outcome"),
                # xG accumulates over the minutes actually played, so a tie settled in extra time
                # carries 120 minutes of it. Downstream fits must scale by 90/minutes or the team
                # looks stronger for having drawn.
                "minutes": np.where(
                    raw.get("went_to_extra_time", pd.Series(False, index=raw.index))
                       .fillna(False).astype(bool), 120.0, 90.0),
                "home_goals": hg,
                "away_goals": ag,
            })
            for col in NUMERIC:
                # a season file written before a column existed (penalty goals, 2026-10-21)
                # loads it as unknown, never as zero
                out[col.replace("shots_on_target", "sot").replace("big_chances", "bigch")] = (
                    pd.to_numeric(raw[col], errors="coerce") if col in raw else np.nan)
            frames.append(out)
    if not frames:
        raise RuntimeError("master_fixtures: no competition files matched")
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["kickoff", "home", "away"])
    # NOT dropped -- flagged. See `is_placeholder_team`: these rows carry a real calendar and, in
    # a half-filled tie like "Napoli v Pisa/Fiorentina", a real participant too. Everything that
    # PLAYS a fixture must filter them out; `scripts/cup_bracket.py` is the one reader that wants
    # them, and it reads the slot names.
    df["tbd"] = (df.home.map(is_placeholder_team) | df.away.map(is_placeholder_team)).to_numpy()
    # goals are only meaningful on played fixtures
    df.loc[~df.played, ["home_goals", "away_goals"]] = np.nan
    # and so is npxG: an abandoned match carries the npxG of the minutes it lasted, which as a
    # match reads as two sides that created nothing (Rayo v Athletic, 2026: 0.02 v 0.06)
    df["has_npxg"] = df.played & df.home_npxg.notna() & df.away_npxg.notna()
    return drop_replayed_abandonments(df)


def drop_replayed_abandonments(df: pd.DataFrame) -> pd.DataFrame:
    """Drop an abandoned match once its replay is in the table.

    Fotmob gives a replay a NEW match_id and leaves the original `aborted` for good. Every
    abandonment in the window that was replayed went that way -- Nice v Marseille and Lyon v
    Marseille (2021), Montpellier v Clermont and Bournemouth v Luton (2023). Left in, the original
    is an unplayed fixture, so every simulated world plays it AS WELL AS the replay and both sides
    finish on 39 matches. An abandonment with no replay yet stays: that match is still owed, and
    without it the season is a fixture short.

    A replay is the same pairing the same way round in the same round, later. Requiring the round
    keeps a UEFA league-phase meeting from being taken for a knockout leg between the same clubs.
    """
    aborted = df[df.outcome.eq("aborted")]
    if aborted.empty:
        return df
    key = ["competition", "season", "home", "away"]
    pairs = aborted[key + ["round", "kickoff"]].reset_index().merge(
        df.loc[~df.outcome.eq("aborted"), key + ["round", "kickoff"]], on=key,
        suffixes=("", "_replay"))
    same_round = ((pairs["round"] == pairs["round_replay"])
                  | (pairs["round"].isna() & pairs["round_replay"].isna()))
    replayed = pairs.loc[same_round & (pairs.kickoff_replay > pairs.kickoff), "index"].unique()
    return df.drop(index=replayed)


def attach_elo(df: pd.DataFrame, elo_file: Path = ELO_FILE) -> pd.DataFrame:
    """Latest ClubElo snapshot STRICTLY BEFORE kickoff, per team. Clamped to each club's own
    earliest snapshot, never row 0 of the shared date index (a club promoted after 2000 has
    leading NaNs in the pivot, and .iloc[0] would silently return one of those)."""
    elo = pd.read_csv(elo_file)
    elo["date"] = pd.to_datetime(elo["date"])
    wide = elo.pivot_table(index="date", columns="club", values="elo", aggfunc="last").sort_index()

    def asof(names: pd.Series, when: pd.Series) -> np.ndarray:
        out = np.full(len(names), np.nan)
        for team, rows in pd.Series(np.arange(len(names)), index=names.to_numpy()).groupby(level=0):
            series = wide.get(team)
            if series is None:
                continue
            series = series.dropna()
            if series.empty:
                continue
            idx = rows.to_numpy()
            pos = series.index.searchsorted(when.iloc[idx], side="left") - 1
            out[idx] = np.where(pos >= 0, series.to_numpy()[np.clip(pos, 0, None)], np.nan)
        return out

    df = df.copy()
    df["home_elo"] = asof(df.home.map(canonical_elo_team_name), df.kickoff)
    df["away_elo"] = asof(df.away.map(canonical_elo_team_name), df.kickoff)
    df["elo_ok"] = df.home_elo.notna() & df.away_elo.notna()
    return df


def build(seasons: Optional[List[int]] = None, include_unplayed: bool = False) -> pd.DataFrame:
    df = attach_elo(load_fixtures(seasons, include_unplayed))
    return df.sort_values(["kickoff", "competition", "home"]).reset_index(drop=True)


def write_master_table(df: pd.DataFrame, path: Path, archive_root: Optional[Path] = None) -> None:
    """Serialize both representations before replacing either; archive changed old files."""
    buffer = io.BytesIO()
    df.to_pickle(buffer)
    atomic_write_files({Path(path): df.to_csv(index=False).encode(),
                        Path(path).with_suffix(".pkl"): buffer.getvalue()}, archive_root)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=None)
    ap.add_argument("--include-unplayed", action="store_true",
                    help="keep scheduled fixtures (no result yet) -- required by the simulator")
    ap.add_argument("--out", type=Path, default=OUT_CSV)
    args = ap.parse_args()

    df = build(args.seasons, args.include_unplayed)
    write_master_table(df, args.out)
    print(f"wrote {len(df)} fixtures -> {args.out} (+ .pkl)")
    print(f"  competitions {df.competition.nunique()}, "
          f"seasons {sorted(int(s) for s in df.season.unique())}")
    print(f"  played {int(df.played.sum())}, scheduled {int((~df.played).sum())}, "
          f"abandoned and still owed {int(df.outcome.eq('aborted').sum())}")
    print(f"  with npxG {int(df.has_npxg.sum())}, both teams Elo-rated {int(df.elo_ok.sum())}")
    print(df.groupby(["kind", "season"]).agg(n=("match_id", "size"), npxg=("has_npxg", "sum"),
                                             elo=("elo_ok", "sum")).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
