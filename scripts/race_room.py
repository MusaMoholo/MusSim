"""Opt-in full-world rival accounting. No providers, model, or snapshot publication.

Schema 1 is carried by forecast payload 13 and later, after explicit publication approval.
Positive gap means the row club finishes above the column club.
"""
from __future__ import annotations

import numpy as np


class RivalTally:
    def __init__(self, teams):
        self.teams = tuple(str(t) for t in teams)
        if len(self.teams) < 2 or len(set(self.teams)) != len(self.teams):
            raise ValueError("Rivals need at least two unique teams")
        n = len(self.teams)
        self.worlds = 0
        self.gaps = np.zeros((n, n, 2 * n - 1), np.int64)
        self.positions = np.zeros((n, n), np.int64)
        self._row, self._col = np.indices((n, n))

    def add(self, positions):
        p = np.asarray(positions)
        n = len(self.teams)
        if p.shape != (n,) or not np.array_equal(np.sort(p), np.arange(1, n + 1)):
            raise ValueError("Rivals require a complete final order, places 1..n")
        p = p.astype(np.int64)
        self.gaps[self._row, self._col, p[None, :] - p[:, None] + n - 1] += 1
        self.positions[np.arange(n), p - 1] += 1
        self.worlds += 1

    def merge(self, other):
        if self.teams != other.teams:
            raise ValueError("Cannot merge rivals with different team identities/order")
        self.gaps += other.gaps
        self.positions += other.positions
        self.worlds += other.worlds
        return self

    def validate(self):
        n, w = len(self.teams), self.worlds
        above = self.gaps[:, :, n:].sum(axis=2)
        checks = [w > 0, self.gaps.dtype == np.int64, self.positions.dtype == np.int64,
                  bool((self.gaps >= 0).all()),
                  bool((self.positions >= 0).all()),
                  bool((self.gaps.sum(axis=2) == w).all()),
                  bool((self.positions.sum(axis=1) == w).all()),
                  bool((self.positions.sum(axis=0) == w).all()),
                  np.array_equal(self.gaps, self.gaps.transpose(1, 0, 2)[:, :, ::-1]),
                  np.array_equal(above + above.T, (1 - np.eye(n, dtype=np.int64)) * w),
                  np.array_equal(above.sum(axis=1), self.positions @ np.arange(n - 1, -1, -1))]
        # A club cannot finish level with another club in a complete final order.
        checks.append(np.array_equal(self.gaps[:, :, n - 1], np.eye(n, dtype=np.int64) * w))
        if not all(checks):
            raise ValueError("Invalid rival counts: sample, complement, gap or expected-rank identity")

    def payload(self):
        self.validate()
        return {"schema": 1, "worlds": self.worlds, "teams": list(self.teams),
                "order": "points, goal difference, goals for, team name",
                "gap_offset": 1 - len(self.teams), "gap_counts": self.gaps.tolist(),
                "position_counts": self.positions.tolist()}
