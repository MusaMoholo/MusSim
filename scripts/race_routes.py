"""Payload14 exclusive provenance for existing entry allocations; never changes who qualifies.

A route is the first sufficient right in the allocator's order. A club with overlapping rights
is counted once: ordinary league UCL, UCL/UEL holder, EPS; then domestic cup, Conference holder
(if it was outside ordinary UEL), league. This is allocation provenance, not a causal effect.
"""
from __future__ import annotations
import numpy as np
from scripts.europe_places import _domestic_base, UCL, UEL, UECL

ROUTES = ('league', 'cup', 'league_cup', 'ucl_holder', 'uel_holder', 'uecl_holder', 'eps')
ENTRIES = ('ucl', 'uel', 'uecl')


def exclusive_routes(order, policy, champions, seats):
    """Label the final disjoint sets using the unchanged allocator's precedence."""
    base = _domestic_base(order, policy, champions)
    labelled = {}
    for entry in ENTRIES:
        for team in sorted(seats[entry]):
            if team in labelled:
                raise ValueError('Entry sets overlap')
            if entry == 'ucl':
                if team in base['ucl']: route = 'league'
                elif team == champions.get(UCL): route = 'ucl_holder'
                elif team == champions.get(UEL): route = 'uel_holder'
                elif policy.get('eps') and team in order: route = 'eps'
                else: raise ValueError('UCL entry has no supported route')
            elif entry == 'uel':
                if team == champions.get(policy.get('cup')): route = 'cup'
                elif team == champions.get(UECL) and team not in base['uel']: route = 'uecl_holder'
                elif team in order: route = 'league'
                else: raise ValueError('UEL entry has no supported route')
            else:
                if team == champions.get(policy.get('league_cup')): route = 'league_cup'
                elif team in order: route = 'league'
                else: raise ValueError('UECL entry has no supported route')
            labelled[team] = (entry, route)
    return labelled


class RouteTally:
    def __init__(self, teams):
        self.teams = tuple(teams)
        self.worlds = 0
        self.counts = {t: np.zeros((3, len(ROUTES)), np.int64) for t in teams}

    def add(self, order, policy, champions, seats):
        routes = exclusive_routes(order, policy, champions, seats)
        for team, (entry, route) in routes.items():
            self.counts.setdefault(team, np.zeros((3, len(ROUTES)), np.int64))[
                ENTRIES.index(entry), ROUTES.index(route)] += 1
        self.worlds += 1

    def merge(self, other):
        if self.teams != other.teams:
            raise ValueError('Route team identities/order differ')
        for team, counts in other.counts.items():
            self.counts.setdefault(team, np.zeros((3, len(ROUTES)), np.int64))[:] += counts
        self.worlds += other.worlds
        return self

    def validate(self, marginals=None):
        if self.worlds < 1:
            raise ValueError('Routes need nonempty full-world evidence')
        for team, counts in self.counts.items():
            if (counts.shape != (3, len(ROUTES)) or counts.dtype != np.int64 or
                    (counts < 0).any() or counts.sum() > self.worlds):
                raise ValueError('Invalid exclusive route counts')
            if marginals is not None and not np.array_equal(counts.sum(axis=1), marginals.get(team, np.zeros(3, int))):
                raise ValueError('Exclusive routes do not reconcile to entry marginals')

    def payload(self, marginals=None):
        self.validate(marginals)
        return dict(schema=1, worlds=self.worlds, routes=list(ROUTES), entries=list(ENTRIES),
                    priority='first sufficient right under the existing allocation order',
                    teams={t: c.tolist() for t,c in sorted(self.counts.items())},
                    entry_counts={t: (marginals[t] if marginals is not None and t in marginals else c.sum(axis=1)).tolist() for t,c in sorted(self.counts.items())},
                    scope='selected association; foreign domestic rights unknown')
