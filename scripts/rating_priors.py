"""Assumed preseason ratings for clubs without a dated Elo observation.

These are population assumptions, never observations assigned to an earlier date. Cup-only
entrants use pooled historical results against rated opposition; top-flight entrants use their
league's lower quartile. Existing model posterior uncertainty is retained.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from football_common import canonical_elo_team_name
from scripts.cup_bracket import is_slot
from scripts.opta_ratings import FULLY_SEEN, COUNTRY
from scripts.simulate_season import HOME_ADV


def starting_ratings(master, fixtures, wide, before):
    """Return dated ratings, explicit assumed starts, and their reproducible evidence."""
    eligible = wide[wide.index < before]
    if eligible.empty:
        raise ValueError(f'No Elo observations before {before.date()}')
    row = eligible.ffill().iloc[-1].dropna()
    look = {canonical_elo_team_name(t): float(v) for t, v in row.items()}
    teams = sorted(t for t in set(fixtures.home) | set(fixtures.away) if not is_slot(t))
    rated = {t: look[canonical_elo_team_name(t)] for t in teams if canonical_elo_team_name(t) in look}
    history = master[(master.kickoff < before) & master.played & master.home_goals.notna()
                     & (master.kickoff >= before - pd.Timedelta(days=5*366))]
    leagues = fixtures[fixtures.competition.isin(FULLY_SEEN)]
    membership = {t: c for c, g in leagues.groupby('competition') for t in set(g.home) | set(g.away)}
    domestic = fixtures[fixtures.kind != 'uefa']
    country = {t: c.split()[0] for c, g in domestic.groupby('competition')
               if c.split()[0] in COUNTRY for t in set(g.home) | set(g.away)}
    # Historical non-top-flight cup entrants. Membership is decided in that historical season,
    # so a relegation/promotion after the cutoff cannot change this reference population.
    top = {(int(season), t) for season, g in history[history.competition.isin(FULLY_SEEN)].groupby('season')
           for t in set(g.home) | set(g.away)}
    samples = {}
    for r in history[history.kind == 'cup'].itertuples():
        key = str(r.competition).split()[0]
        for team, opponent, opp_elo, result, advantage in [
            (r.home, r.away, r.away_elo, float(r.home_goals > r.away_goals)+.5*(r.home_goals == r.away_goals), HOME_ADV),
            (r.away, r.home, r.home_elo, float(r.away_goals > r.home_goals)+.5*(r.home_goals == r.away_goals), -HOME_ADV)]:
            if (int(r.season), team) not in top and (int(r.season), opponent) in top and np.isfinite(opp_elo):
                samples.setdefault(key, []).append((float(opp_elo), result, advantage))
    pooled = [r for k in sorted(samples) for r in samples[k]]
    priors, evidence = {}, {}
    for team in teams:
        if team in rated:
            continue
        if team in membership:
            comp = membership[team]
            peers = sorted(t for t, c in membership.items() if c == comp and t in rated)
            if not peers:
                raise ValueError(f'No dated top-flight peers for {team}')
            value = float(np.percentile([rated[t] for t in peers], 25))
            detail = {'basis': 'assumed league lower quartile', 'competition': comp, 'peers': len(peers)}
        elif team in country:
            rows = samples.get(country[team], [])
            local = len(rows) >= 20
            rows = rows if local else pooled
            if not rows:
                # Older seasons can predate retained cups entirely. Use an explicit lower-tail
                # prior from dated ratings rather than inventing retrospective cup evidence.
                priors[team] = round(float(np.percentile(list(look.values()), 5)), 1)
                evidence[team] = {'basis': 'assumed dated Elo lower-tail fallback', 'percentile': 5,
                                  'peers': len(look), 'elo': priors[team],
                                  'evidence_before': str(before.date())}
                continue
            opp, scores, ha = np.asarray(rows).T
            # Solve for one pooled rating matching the observed result score, venue included.
            # A half-result pseudo-observation prevents finite-sample all-win/loss extremes.
            target = (float(scores.sum()) + .5) / (len(scores) + 1)
            lo, hi = 400., 2400.
            for _ in range(60):
                mid = (lo + hi) / 2
                expected = np.mean(1 / (1 + 10 ** (-(mid - opp + ha) / 400)))
                if expected < target:lo = mid
                else:hi = mid
            value = (lo + hi) / 2
            detail = {'basis': 'assumed historical lower-tier cup entrants',
                      'population': country[team] if local else 'pooled countries', 'matches': len(rows)}
        else:
            comps = sorted(set(fixtures.loc[(fixtures.home == team) | (fixtures.away == team), 'competition']))
            past = history[history.competition.isin(comps)]
            values = pd.concat([past.home_elo, past.away_elo]).dropna()
            if values.empty:
                raise ValueError(f'No dated competition peers for {team}')
            value = float(values.median())
            detail = {'basis': 'assumed historical competition median', 'competitions': comps, 'appearances': len(values)}
        priors[team] = round(value, 1)
        evidence[team] = {**detail, 'elo': priors[team], 'evidence_before': str(before.date())}
    return rated, priors, {'elo_date': str(eligible.index[-1].date()), 'assumed': evidence}
