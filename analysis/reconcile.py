#!/usr/bin/env python3
"""Where the live season has no strength information, and whether Opta could supply it.

    .venv/bin/python analysis/reconcile.py

Run by hand: it informs an open modelling decision (FINDINGS 6.1, "Opta->Elo") and changes
nothing. It used to be a nightly step, printing the same lines every night until they no longer
described anything.

Reported, never converted. FINDINGS 6.1: converting Opta costs 0.149 in Q units against 0.021 for
ClubElo's staleness, and the extrapolation off ClubElo's countries has unmeasurable error.

The number that matters is NOT "teams without an Elo rating". Most of those have a fitted Q from
their own npxG, which is the primary driver -- the rating only centres the shrinkage. The blind
spots are teams with NEITHER, because they fall back to a 5th-percentile seed rating, i.e. "assume
bottom of the pile". That is fine for a Conference League minnow and wrong for a Hajduk Split.

Only league and UEFA sides are named. Cup-only clubs -- amateurs and lower divisions, for whom the
default is the right guess -- are counted, and bracket slots are not clubs at all. A blind spot
the Elo mirror carries under a similar name is a missing `ELO_ALIASES` entry, not a coverage gap,
so those are listed separately.

Names go through `canonical_team_name` and THEN `canonical_elo_team_name`, the two-step map
`analysis/opta_bridge2.py` uses. Skipping the first drops clubs as obvious as Bayern Munchen,
which makes a join bug look like a data gap.
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from football_common import canonical_elo_team_name, canonical_team_name  # noqa: E402
from scripts.cup_bracket import is_slot  # noqa: E402
from scripts.projection import Engine  # noqa: E402

ELO_MIRROR = ROOT / "data/external/elo_ratings.csv"
OPTA_CSV = ROOT / "data/team_rankings.csv"


def canon(x: str) -> str:
    return canonical_elo_team_name(canonical_team_name(x))


def similar_names(teams: List[str], clubs: "pd.Series") -> Dict[str, str]:
    """Team -> a mirror club whose name folds to the same letters, or one containing the other.

    A hint for a human, never a mapping: aliases stay exact. Containment only counts when the
    shorter name is most of the longer -- "nijmegen" is 8 of "necnijmegen"'s 11 letters, but
    "inter" is 5 of "interclubdescaldes"' 18, and that club is in Andorra.
    """
    stop = {"fc", "afc", "cf", "sc", "sk", "fk", "ac", "as", "if", "bk", "nk", "kv", "sv", "club"}

    def fold(name: str) -> str:
        text = unicodedata.normalize("NFKD", str(name).lower()).replace("ø", "o")
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        words = "".join(ch if ch.isalnum() else " " for ch in text).split()
        return "".join(w for w in words if w not in stop)

    keys = {fold(c): str(c) for c in clubs}
    out: Dict[str, str] = {}
    for t in teams:
        k = fold(t)
        hit = keys.get(k) or next((c for ck, c in keys.items() if (ck in k or k in ck)
                                   and min(len(ck), len(k)) >= 0.6 * max(len(ck), len(k))),
                                  None)
        if hit:
            out[t] = hit
    return out


def main() -> int:
    engine = Engine()
    season = engine.live_season()
    prep = engine.prepare(season)
    fx, model, elo0 = prep["fixtures"], prep["model"], prep["elo0"]
    named = set(fx.home) | set(fx.away)
    teams = sorted(t for t in named if not is_slot(t))
    rated = [t for t in teams if t in elo0]
    major = set(fx[fx.kind != "cup"].home) | set(fx[fx.kind != "cup"].away)
    unrated = [t for t in teams if t not in model["Q"] and t not in elo0]
    blind = [t for t in unrated if t in major]
    touched = int((fx.home.isin(blind) | fx.away.isin(blind)).sum())
    print(f"season {season}: {len(rated)}/{len(teams)} sides have a ClubElo rating "
          f"({len(named) - len(teams)} bracket slots aside)")
    print(f"  {len(blind)} league/UEFA sides with no fitted Q and no Elo, on {touched} fixtures "
          f"({100 * touched / max(len(fx), 1):.1f}%), and {len(unrated) - len(blind)} "
          f"cup-only clubs")
    if blind:
        print("  on the 5th-percentile default: " + ", ".join(blind))

    mirror = pd.read_csv(ELO_MIRROR)
    hints = similar_names(blind, mirror[mirror.date == mirror.date.max()].club)
    if hints:
        print("  the Elo mirror has a similar name (a missing ELO_ALIASES entry?): "
              + ", ".join(f"{t} ~ {c}" for t, c in hints.items()))

    if OPTA_CSV.exists():
        opta = pd.read_csv(OPTA_CSV)
        # setdefault, not a comprehension: the file is rank-ordered and 10,000 rows deep, so
        # canonical-name collisions are common and a comprehension would silently keep the
        # LAST -- mapping a big club onto some obscure namesake far down the list.
        by: Dict[str, tuple] = {}
        for r in opta.itertuples():
            by.setdefault(canon(r.team), (int(r.rank), float(r.rating)))
        covered = [t for t in blind if canon(t) in by]
        print(f"  Opta has {len(covered)} of the {len(blind)}"
              + (": " + ", ".join(f"{t} (#{by[canon(t)][0]})" for t in covered) if covered else ""))
        shared = [t for t in teams if t in elo0 and canon(t) in by]
        if len(shared) > 10:
            a = pd.Series([by[canon(t)][1] for t in shared]).rank()
            b = pd.Series([elo0[t] for t in shared]).rank()
            print(f"  Opta/ClubElo rank agreement {np.corrcoef(a, b)[0, 1]:.3f} "
                  f"on {len(shared)} shared sides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
