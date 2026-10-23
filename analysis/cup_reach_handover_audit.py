#!/usr/bin/env python3
"""Read-only structural reproduction of the early Coppa reach defect, without fitting a model.

Uses real rewound round definitions and deterministic fixture results to show where
survivors are dropped and a named later slot can resurrect a club twice. Exit1 reports
the reproduced defect; this is diagnosis, not a correction or snapshot regeneration.
"""
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.cup_bracket import cup_handovers  # noqa: E402
from scripts.projection import as_of_fixtures  # noqa: E402
from scripts.simulate_season import _Cup, _run_cup_round  # noqa: E402


class DeterministicWorld:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.rho = 0

    def play(self, *args, **kwargs):
        return 1, 0, 1.3, 1.0

    def rates(self, *args, **kwargs):
        return 0, 0, 1.3, 1.0

    def replay(self, row):
        pass

    def add_extra_time(self, *args):
        pass


def main():
    master = pd.read_pickle(ROOT / "data/master_fixtures.pkl")
    fixtures = as_of_fixtures(master[master.season == 2026].copy(), "2026-08-21")
    hand = cup_handovers(fixtures, master, np.random.default_rng(1))[("Italian Coppa Italia", 2026)]
    rows = {(r.home, r.away): r for r in fixtures[fixtures.competition == hand.competition].itertuples()}
    duplicates = []
    lost = []
    for seed in range(8):
        cup = _Cup(hand.competition, hand.season, alive=list(hand.field))
        world = DeterministicWorld(seed)
        for rnd in hand.rounds:
            before = set(cup.alive)
            _run_cup_round(world, cup, rnd, 1, hand.rules, set(), rows, True)
            if rnd.two_leg:
                _run_cup_round(world, cup, rnd, 2, hand.rules, set(), rows, True)
            participants = {t for tie in cup.ties[rnd.label] for t in tie}
            skipped = before - participants - set(cup.byes[rnd.label])
            vanished = sorted(skipped - set(cup.alive))
            if vanished:
                lost.append((seed, rnd.label, vanished))
            repeated = {team: n for team, n in Counter(cup.reached[rnd.label]).items() if n > 1}
            if repeated:
                duplicates.append((seed, rnd.label, repeated))
    print(f"Audited {len(hand.rounds)} real Coppa round definitions × 8 deterministic structural worlds; no fit or source writes")
    print(f"Alive clubs absent from this round dropped (includes later entrants): {len(lost)} round transitions")
    for seed, label, names in lost[:3]:
        print(f"FAIL seed{seed} {label}: dropped {', '.join(names)}")
    print(f"Duplicate within-round reach: {len(duplicates)} rounds")
    for seed, label, teams in duplicates[:5]:
        print(f"FAIL seed{seed} {label}: {teams}")
    print("Observed mechanism: _run_cup_round replaces alive with this round's winners/byes; later missing slots consume unrelated spare clubs or invoke a feeder again.")
    return int(bool(lost or duplicates))


if __name__ == "__main__":
    raise SystemExit(main())
