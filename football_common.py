"""Helpers shared by simulation.ipynb and parameter_calibration.ipynb.

Both notebooks used to define these five functions and the alias map independently, and the copies
drifted. Four of the five differed textually, and two of those differences were real:

  * the calibration copy of `canonical_team_name` was not NaN-safe, so an undrawn placeholder row
    became the string "nan" instead of staying missing;
  * the calibration copy of `load_team_rankings` never coerced `rank` to numeric, and `rank` is what
    the duplicate-name tie-break sorts on. Harmless while the feed emits clean integers, but one
    non-numeric value flips the column to object dtype and the sort becomes lexicographic
    ("10040" before "2"), silently resolving a shared name to the wrong club in calibration only.

That class of drift has already cost one real bug: the UEFA aliases lived in only one notebook, so
200 of 531 UEFA matches were dropped from a fit, and because the unrated clubs were systematically
the weakest the fitted rating slope moved from 4.09 to 4.88. One definition removes the hazard.

The alias map stays a Python dict rather than data/team_aliases.json so the comments explaining WHY
each group exists survive — in particular the rule that names are resolved by rank plausibility and
never by fuzzy matching. Nothing outside these notebooks consumes it.
"""

import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Resolved against the repo, not the working directory, so an import works from anywhere.
DATA_DIR = Path(__file__).resolve().parent / "data"
TEAM_RANKINGS_FILE = DATA_DIR / "team_rankings.csv"

# `canonical_team_name` is applied to the ranking feed as well as to fixtures, so this is a
# two-sided normaliser: both sides converge on the same string and the canonical name need not
# match either. The feed now says "Manchester City" while the canonical name is "Man City".

TEAM_ALIASES: Dict[str, str] = {
    "Alavés": "Deportivo Alavés",
    "Atleti": "Atlético de Madrid",
    "Atlético Madrid": "Atlético de Madrid",
    "Barcelona": "FC Barcelona",
    "Bayern München": "FC Bayern München",
    "FC Bayern": "FC Bayern München",  # fixturedownload.com's 2021 Bundesliga season file only
    "B. Dortmund": "Borussia Dortmund",
    "Brighton & Hove Albion": "Brighton",
    "Celta de Vigo": "Celta",
    "Coventry City": "Coventry",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "Frankfurt": "Eintracht Frankfurt",
    "Freiburg": "Sport-Club Freiburg",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Köln": "1. FC Köln",
    "Union Berlin": "1. FC Union Berlin",
    "Auxerre": "AJ Auxerre",
    "Angers": "Angers SCO",
    "Borussia M'gladbach": "Borussia Mönchengladbach",
    "Osasuna": "CA Osasuna",
    "Elche": "Elche CF",
    "Troyes": "Estac Troyes",
    "ESTAC Troyes": "Estac Troyes",  # fixturedownload.com's 2021-2022 Ligue 1 season files
    "Augsburg": "FC Augsburg",
    "Lorient": "FC Lorient",
    "Schalke 04": "FC Schalke 04",
    "Getafe": "Getafe CF",
    "Le Havre": "Havre Athletic Club",
    "Havre AC": "Havre Athletic Club",  # fixturedownload.com's 2023 Ligue 1 season file
    "Le Mans": "Le Mans FC",
    "Levante": "Levante UD",
    "Málaga": "Málaga CF",
    "Racing de Santander": "R. Racing Club",
    "Deportivo de A Coruña": "RC Deportivo",
    "Strasbourg": "RC Strasbourg Alsace",
    "Espanyol": "RCD Espanyol de Barcelona",
    "Paderborn": "SC Paderborn 07",
    "Elversberg": "SV Elversberg",
    "Werder Bremen": "SV Werder Bremen",
    "Sevilla": "Sevilla FC",
    "Brest": "Stade Brestois 29",
    "Rennes": "Stade Rennais FC",
    "Hoffenheim": "TSG Hoffenheim",
    "Toulouse": "Toulouse FC",
    "Valencia": "Valencia CF",
    "Inter": "Internazionale",
    "Leeds United": "Leeds",
    "Leverkusen": "Bayer 04 Leverkusen",
    "Lens": "RC Lens",
    "Lille": "LOSC Lille",
    "Lyon": "Olympique Lyonnais",
    "Mainz": "1. FSV Mainz 05",
    "Mainz 05": "1. FSV Mainz 05",
    "Manchester City": "Man City",
    "Milton Keynes Dons": "MK Dons",
    "Manchester United": "Man Utd",
    "Man United": "Man Utd",
    "Marseille": "Olympique de Marseille",
    "Monaco": "AS Monaco",
    "Newcastle United": "Newcastle",
    "Nice": "OGC Nice",
    "Nottingham Forest": "Nott'm Forest",
    "Olympique Marseille": "Olympique de Marseille",
    "Paris": "Paris Saint-Germain",
    "PSG": "Paris Saint-Germain",
    "Stuttgart": "VfB Stuttgart",
    "Tottenham": "Spurs",
    "Tottenham Hotspur": "Spurs",
    "Villarreal": "Villarreal CF",
    # UEFA Champions League entrants whose fixture spelling differs from the ranking feed.
    "Kairat Almaty": "Kairat",
    "Qarabag": "Qarabağ",
    "Union SG": "Union Saint-Gilloise",
    "Bodø/Glimt": "Bodø / Glimt",
    "Copenhagen": "København",
    "Olympiacos": "Olympiakos Piraeus",
    # UEFA entrants (Champions / Europa / Conference) whose fixture spelling differs from the
    # ranking feed. Resolved against the feed by rank plausibility, never by fuzzy matching:
    # fuzzy matching proposed reserve sides ("Jagiellonia II", "Ludogorets II") and wrong clubs
    # ("Braga" -> "Fraga").
    "AZ Alkmaar": "AZ",
    "Braga": "Sporting Braga",
    "Breiðablik": "Breidablik",
    "Crvena Zvezda": "Crvena zvezda",
    "GNK Dinamo": "Dinamo Zagreb",
    "Jagiellonia": "Jagiellonia Białystok",
    "KuPS Kuopio": "KuPS",
    "L. Red Imps": "Lincoln Red Imps",
    "Lech Poznan": "Lech Poznań",
    "Ludogorets": "Ludogorets Razgrad",
    "M. Tel-Aviv": "MTK",
    "Malmö": "Malmö FF",
    "Omonoia": "Omonia Nicosia",
    "Raków": "Raków Częstochowa",
    "S. Bratislava": "Slovan Bratislava",
    "SK Rapid": "Rapid",
    "Shakhtar": "Shakhtar Donetsk",
    "Shkëndija": "Shkendija",
    "U. Craiova": "Universitatea Craiova",
    # fixturedownload.com's spellings for UEFA entrants. These MUST be aliases, not edits to the
    # CSVs: scripts/update_team_rankings.py re-downloads those seven files, so a fix written into
    # the file is silently reverted on the next scrape. Resolved by substring plus rank
    # plausibility, never by fuzzy matching — RB Leipzig is rank 33 against Lokomotive Leipzig's
    # 1820, Omonia Nicosia rank 65 against Omonia 29is Maiou's 963, NEC/OFI are unique at the top.
    "Besiktas": "Beşiktaş",
    "H. Beer-Sheva": "Hapoel Be'er Sheva",
    "Leipzig": "RB Leipzig",
    "N.E.C.": "NEC",
    "OFI Crete": "OFI",
    "Omonia": "Omonia Nicosia",
    # Present in earlier-season league files; these lived only in parameter_calibration.ipynb
    # before and are merged here so both notebooks resolve names identically.
    "Heidenheim": "1. FC Heidenheim 1846",
    "Saint-Étienne": "AS Saint-Étienne",
    "Leganés": "CD Leganés",
    "Metz": "FC Metz",
    "Nantes": "FC Nantes",
    "St. Pauli": "FC St. Pauli",
    "Girona": "Girona FC",
    "Leicester City": "Leicester",
    "Montpellier": "Montpellier Hérault SC",
    "RC Celta": "Celta",
    "Mallorca": "RCD Mallorca",
    "Real Valladolid": "Real Valladolid CF",
    "SC Freiburg": "Sport-Club Freiburg",
    "Stade DE Reims": "Reims",
    "Stade de Reims": "Reims",
    "UD Las Palmas": "Las Palmas",
    "VfL Bochum 1848": "Bochum",
    "VfL Wolfsburg": "Wolfsburg",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    # Found while building Phase 3's ClubElo fits (PLAN.md), which needed every 2021-2025 team, not
    # just the 96 currently modelled: these were wrongly assumed absent from Opta's feed by
    # `scripts/backtest.py`'s `resolvable_seasons()` — they are present, just under a shorter name
    # than fixturedownload.com's historical files use. Confirmed by rank plausibility (172-1727,
    # consistent with a relegated European club still tracked, never a reserve side): Cádiz CF
    # (rank 789), Granada CF (438), Norwich (172), Luton (504), Sheffield Utd (244), UD Almería
    # (325), Girondins de Bordeaux (1727), Clermont Foot 63 (1039), SpVgg Greuther Fürth (730),
    # SV Darmstadt 98 (620). Real fix, not a workaround — see PLAN.md Phase 0.1 / 3.1.
    "Cádiz CF": "Cádiz",
    "Granada CF": "Granada",
    "Norwich": "Norwich City",
    "Luton": "Luton Town",
    "Sheffield Utd": "Sheffield United",
    "UD Almería": "Almería",
    "Girondins de Bordeaux": "Bordeaux",
    "Clermont Foot 63": "Clermont",
    "SpVgg Greuther Fürth": "Greuther Fürth",
    "SV Darmstadt 98": "Darmstadt 98",
    # Domestic cup files spell several clubs differently again. Resolved by rank plausibility
    # against the feed: a cup quarter-finalist is a well-ranked club, never a reserve side.
    "1. FC Kaiserslautern": "Kaiserslautern",
    "1. FC Magdeburg": "Magdeburg",
    "AC Milan": "Milan",
    "Athletic Bilbao": "Athletic Club",
    "Bayer Leverkusen": "Bayer 04 Leverkusen",
    "Bayern Munich": "FC Bayern München",
    "Deportivo La Coruña": "RC Deportivo",
    "Inter Milan": "Internazionale",
    "Racing Santander": "R. Racing Club",
    "VfL Bochum": "Bochum",
    "Viktoria Plzen": "Viktoria Plzeň",
}


def canonical_team_name(team: Any) -> str:
    if pd.isna(team):
        return team  # undrawn placeholder rows keep their missing teams
    name = str(team).strip()
    return TEAM_ALIASES.get(name, name)


# Fotmob's own spellings, where they differ from both TEAM_ALIASES's targets and fixturedownload's
# conventions. Scoped to PLAN.md Phase 1.2: the 5 domestic leagues, the 3 UEFA competitions (all
# rounds — all 36 teams are modelled), and the 6 domestic cups from their Ro16-equivalent round
# onward (early qualifying rounds bring in amateur sides genuinely absent from Opta's feed — see
# PLAN.md Part II, "not an aliasing problem"). Measured against the full 2025 Fotmob cache with
# canonical_team_name (TEAM_ALIASES) already applied first, so these are names TEAM_ALIASES could
# not already resolve. Same rules as TEAM_ALIASES: exact match only, resolved by rank plausibility
# against the Opta feed, never fuzzy (HANDOFF.md: fuzzy matching proposes reserve sides and wrong
# clubs — "Braga" -> "Fraga").
FOTMOB_ALIASES: Dict[str, str] = {
    "AFC Bournemouth": "Bournemouth",
    "Celta Vigo": "Celta",
    "FC Heidenheim": "1. FC Heidenheim 1846",
    "Darmstadt": "Darmstadt 98",
    "Clermont Foot": "Clermont",  # Fotmob's 2023 Ligue 1 spelling (fixturedownload's is "Clermont Foot 63")
    "Burgos CF": "Burgos",
    "Deportivo A Coruña": "RC Deportivo",
    # UEFA (Champions / Europa / Conference League) entrants.
    "FC København": "København",
    "PSV Eindhoven": "PSV",
    "Pafos FC": "Pafos",
    "Qarabağ FK": "Qarabağ",
    "Slavia Prague": "Slavia Praha",
    "Union St.Gilloise": "Union Saint-Gilloise",
    "FC Midtjylland": "Midtjylland",
    "FC Porto": "Porto",
    "FC Utrecht": "Utrecht",
    "FK Crvena Zvezda": "Crvena zvezda",
    "PAOK Thessaloniki": "PAOK",
    "FC Noah": "Noah",
    "KF Shkendija": "Shkendija",
    "Lausanne": "Lausanne-Sport",
    "Lincoln Red Imps FC": "Lincoln Red Imps",
    "NK Celje": "Celje",
    "Rapid Wien": "Rapid",
    "Sparta Prague": "Sparta Praha",
    "Zrinjski Mostar": "Zrinjski",
}


def canonical_fotmob_team_name(team: Any) -> str:
    """Fotmob names are aliased first (FOTMOB_ALIASES), then run through the same TEAM_ALIASES
    normalisation everything else uses — so a Fotmob spelling that happens to already match a
    fixturedownload/Opta spelling needs no entry here at all.
    """
    if pd.isna(team):
        return team
    name = FOTMOB_ALIASES.get(str(team).strip(), str(team).strip())
    return canonical_team_name(name)


# ClubElo (data/external/elo_ratings.csv, via scripts/fetch_clubelo.py) is the Phase 3 xG-free
# control variable — see PLAN.md Part II. Its own naming convention is much terser than Opta's or
# fixturedownload's ("Bayern Munich", "Dortmund", "Ath Madrid"), so it needs its own alias map, same
# rules as everywhere else: exact match only, resolved by rank/rating plausibility, never fuzzy.
# Scoped to the 96 teams the 5 domestic leagues currently carry (2025 season) — the only teams
# Phase 3's fits need. ClubElo has its own dirt (PLAN.md Part II: it lists ("Alanya", "RUS") for a
# club that is Turkish), so a country code is a hint here, never a key.
ELO_ALIASES: Dict[str, str] = {
    # Germany
    "1. FC Heidenheim 1846": "Heidenheim",
    "1. FC Köln": "FC Koln",
    "1. FC Union Berlin": "Union Berlin",
    "1. FSV Mainz 05": "Mainz",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund",
    # ClubElo carries a second, much shorter series under "M'gladbach" (41 rows, starting
    # 2025-01-01) alongside the real continuous one — this is "MGladbach" (618 rows back to
    # 2000-07-01). Picked the continuous series; the short one looks like a mirror artifact.
    "Borussia Mönchengladbach": "MGladbach",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "FC Augsburg": "Augsburg",
    "FC Bayern München": "Bayern Munich",
    "FC St. Pauli": "St Pauli",
    "Hamburger SV": "Hamburg",
    "SV Werder Bremen": "Werder Bremen",
    "Sport-Club Freiburg": "Freiburg",
    "TSG Hoffenheim": "Hoffenheim",
    "VfB Stuttgart": "Stuttgart",
    # Spain
    "Atlético de Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao",
    "CA Osasuna": "Osasuna",
    "Deportivo Alavés": "Alaves",
    "Elche CF": "Elche",
    "FC Barcelona": "Barcelona",
    "Getafe CF": "Getafe",
    "Girona FC": "Girona",
    "Levante UD": "Levante",
    "RCD Espanyol de Barcelona": "Espanol",
    "RCD Mallorca": "Mallorca",
    "Rayo Vallecano": "Vallecano",
    "Real Betis": "Betis",
    "Real Oviedo": "Oviedo",
    "Real Sociedad": "Sociedad",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Villarreal CF": "Villarreal",
    # Italy
    "Hellas Verona": "Verona",
    "Internazionale": "Inter",
    # France
    "AJ Auxerre": "Auxerre",
    "AS Monaco": "Monaco",
    "Angers SCO": "Angers",
    "FC Lorient": "Lorient",
    "FC Metz": "Metz",
    "FC Nantes": "Nantes",
    "Havre Athletic Club": "Le Havre",
    "LOSC Lille": "Lille",
    "OGC Nice": "Nice",
    "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille",
    "Paris Saint-Germain": "Paris SG",
    "RC Lens": "Lens",
    "RC Strasbourg Alsace": "Strasbourg",
    "Stade Brestois 29": "Brest",
    "Stade Rennais FC": "Rennes",
    "Toulouse FC": "Toulouse",
    # England
    "Man Utd": "Man United",
    "Spurs": "Tottenham",
    "Norwich City": "Norwich",
    "Luton Town": "Luton",
    # Teams present in the 2021-2024 (but not the current) domestic-league fixture files — needed
    # for Phase 3's point-in-time fits, which use several seasons, not just the currently-modelled
    # 96 teams. Keys are OUR canonical form (post `TEAM_ALIASES`) — note several of these teams
    # were briefly, wrongly, believed absent from Opta's feed entirely by `scripts/backtest.py`'s
    # `resolvable_seasons()`; they were only missing a `TEAM_ALIASES` entry (fixed there), and
    # ClubElo — results-only, no "top N" cutoff — carries all of them regardless.
    "AS Saint-Étienne": "St Etienne",
    "Arminia Bielefeld": "Bielefeld",
    "CD Leganés": "Leganes",
    "Cádiz": "Cadiz",
    "Estac Troyes": "Troyes",
    "FC Schalke 04": "Schalke 04",
    "Hertha BSC": "Hertha",
    "Montpellier Hérault SC": "Montpellier",
    "Real Valladolid CF": "Valladolid",
    "Darmstadt 98": "Darmstadt",
    "Greuther Fürth": "Greuther Furth",
    "Almería": "Almeria",
    # AC Ajaccio has no ClubElo entry at all — genuinely a different, much smaller club from
    # "Gazélec Ajaccio" (the only Ajaccio ClubElo carries), not an aliasing gap.
}


def canonical_elo_team_name(team: Any) -> str:
    """Map OUR canonical name (post `canonical_team_name`) to ClubElo's own spelling. Unlike
    `canonical_fotmob_team_name`, this takes an already-canonicalised name as input — callers
    resolve a fixture's team through `canonical_team_name` first, same as every other loader,
    then look the result up here only when reading ClubElo.
    """
    if pd.isna(team):
        return team
    name = str(team).strip()
    return ELO_ALIASES.get(name, name)


def recover_mac_roman(raw: bytes) -> Tuple[str, Dict[str, int]]:
    """Decode a file that Excel for Mac has half-converted.

    Editing a fixture CSV in Excel on macOS writes MacRoman, and editing one that was already UTF-8
    leaves a file that is **both**: a real case had `Estádio` stored as UTF-8 (\\xc3\\xa1) and
    `Fenerbahçe` stored as MacRoman (\\x8d), so no single encoding could read it. `surrogateescape`
    parks each undecodable byte at U+DCxx, which lets valid UTF-8 sequences through untouched and
    leaves the stray bytes individually recoverable as MacRoman.

    This replaced a cp1252 fallback that was actively dangerous: cp1252 accepts most MacRoman bytes
    without raising, so `Estádio Malmö` came back as `Est‡dio Malmš` with no error at all. A loud
    warning here beats silent mojibake — mojibake only surfaces later as an unrated team, which is a
    confusing way to learn your file is mis-encoded.
    """
    text = raw.decode("utf-8", errors="surrogateescape")
    out: List[str] = []
    recovered: Dict[str, int] = {}
    for char in text:
        code = ord(char)
        if 0xDC80 <= code <= 0xDCFF:
            byte = bytes([code - 0xDC00])
            out.append(byte.decode("mac_roman"))
            recovered[byte.hex()] = recovered.get(byte.hex(), 0) + 1
        else:
            out.append(char)
    return "".join(out), recovered


def read_csv_flexible(path: Path) -> pd.DataFrame:
    # The happy path is left exactly as it was, so a valid UTF-8 file reads byte-for-byte the same.
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        text, recovered = recover_mac_roman(Path(path).read_bytes())
        detail = ", ".join(f"0x{h} x{n}" for h, n in sorted(recovered.items()))
        print(f"read_csv_flexible: {Path(path).name} is not valid UTF-8 — recovered "
              f"{sum(recovered.values())} byte(s) as MacRoman ({detail}). "
              "Re-save it as UTF-8; Excel for Mac does this.")
        return pd.read_csv(io.StringIO(text))


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={column: column.strip().lower().replace(" ", "_") for column in df.columns})


def parse_score(result_str: Any) -> Tuple[Optional[int], Optional[int]]:
    if pd.isna(result_str):
        return None, None
    result = str(result_str).split("(")[0].strip().replace("–", "-")  # drop shootout suffix e.g. "(3 - 4 pens)"
    parts = [part.strip() for part in result.split("-")]
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def load_team_rankings(path: Path = TEAM_RANKINGS_FILE) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"Missing required Opta team rankings file: {path}")

    rankings = normalize_columns(read_csv_flexible(path))
    rankings = rankings.rename(columns={
        "club": "team",
        "squad": "team",
        "score": "rating",
        "opta_rating": "rating",
        "power_rating": "rating",
        "currentrating": "rating",  # the raw field name in data/team_rankings_history/'s detailed
                                    # snapshots (normalize_columns already lowercased it)
        "contestantname": "team",  # ditto — the detailed snapshots say "contestantName", not "team"
        "7_day_change": "ranking_change_7d",
        "ranking_change": "ranking_change_7d",
    })

    required = ["team", "rating"]
    missing = [column for column in required if column not in rankings.columns]
    if missing:
        raise RuntimeError(f"{path.name} missing required team ranking columns: {missing}")

    rankings["team"] = rankings["team"].map(canonical_team_name)
    rankings["rating"] = pd.to_numeric(rankings["rating"], errors="coerce")
    if "rank" in rankings.columns:
        rankings["rank"] = pd.to_numeric(rankings["rank"], errors="coerce")
    if "ranking_change_7d" in rankings.columns:
        rankings["ranking_change_7d"] = pd.to_numeric(rankings["ranking_change_7d"], errors="coerce")

    rankings = rankings.dropna(subset=["team", "rating"])
    # 161 names in the feed are shared by different clubs (Al Ahli x4, MTK x2, ...). Resolve them
    # by the feed's own ordering - best rank wins - not by rating. The two disagree on 16 rows,
    # and for "MTK" (Maccabi Tel Aviv) picking by rating selects a different club entirely. Of the
    # 9 duplicated names that appear in fixtures, MTK is the only one where the choice matters.
    order = ["rank", "team"] if "rank" in rankings.columns else ["rating", "team"]
    ascending = [True, True] if "rank" in rankings.columns else [False, True]
    rankings = rankings.sort_values(order, ascending=ascending).drop_duplicates("team", keep="first")
    return rankings.reset_index(drop=True)
