#!/usr/bin/env python3
"""Walk-forward backtest and hyperparameter selection for scripts/attack_defence_qt.py.

Two rules this harness exists to enforce, both learned the hard way:

1. TRAINING IS STRICTLY CAUSAL. Every refit sees only fixtures that kicked off before the
   prediction window opens, pooled across seasons AND competitions. Restarting the window each
   season starves every early-season origin and makes a decay sweep fight a cold-start problem
   instead of a recency question (HANDOFF.md records exactly that bug).

2. HYPERPARAMETERS ARE CHOSEN LEAVE-ONE-SEASON-OUT. Predictions are causal, so a config may be
   selected on the OTHER test seasons and scored on the held-out one. Selecting on the same
   season you report is how a tuned number turns into an optimistic one -- on 2023-25 the gap
   between the LOSO figure (0.9821) and the single best config (0.9814) was 0.0007.

Significance uses PAIRED per-match log-loss differences. Nested models share most of their
prediction, so comparing two mean log-losses unpaired is far less powerful -- it is why an earlier
"0.9871 vs 0.9870, statistically identical" verdict on time decay was not informative either way.

    .venv/bin/python scripts/backtest_qt.py --test-from 2022-08-01
    .venv/bin/python scripts/backtest_qt.py --hl-q none 280 200 140 --hl-t none 1460
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.attack_defence_qt import (  # noqa: E402
    apply_goal_calibration, fit, fit_goal_calibration, predict_npxg,
)

MASTER = Path("data/master_fixtures.pkl")
MAXG = 12
_LOGFACT = np.array([float(np.sum(np.log(np.arange(1, i + 1)))) for i in range(MAXG + 1)])


def score_matrix(lam_h, lam_a, rho: float = 0.0):
    """Independent Poisson with the Dixon-Coles low-score dependence correction."""
    g = np.arange(MAXG + 1)
    ph = np.exp(-lam_h[:, None] + g * np.log(lam_h)[:, None] - _LOGFACT)
    pa = np.exp(-lam_a[:, None] + g * np.log(lam_a)[:, None] - _LOGFACT)
    M = ph[:, :, None] * pa[:, None, :]
    if rho != 0.0:
        tau = np.ones((len(lam_h), MAXG + 1, MAXG + 1))
        tau[:, 0, 0] = 1.0 - lam_h * lam_a * rho
        tau[:, 0, 1] = 1.0 + lam_h * rho
        tau[:, 1, 0] = 1.0 + lam_a * rho
        tau[:, 1, 1] = 1.0 - rho
        M = M * np.clip(tau, 1e-9, None)
    return M / M.sum(axis=(1, 2), keepdims=True)


def outcome_probs(lam_h, lam_a, rho: float = 0.0):
    M = score_matrix(lam_h, lam_a, rho)
    iu = np.triu_indices(MAXG + 1, 1)
    p_away = M[:, iu[0], iu[1]].sum(1)
    p_draw = np.einsum("ijj->i", M)
    return np.clip(np.column_stack([1.0 - p_away - p_draw, p_draw, p_away]), 1e-12, 1.0)


def log_loss(pred: pd.DataFrame, rho: float = 0.0) -> np.ndarray:
    P = outcome_probs(pred.lam_h.to_numpy(), pred.lam_a.to_numpy(), rho)
    P = P / P.sum(1, keepdims=True)
    return -np.log(P[np.arange(len(pred)), pred.result.to_numpy()])


def load_master(path: Path = MASTER) -> pd.DataFrame:
    m = pd.read_pickle(path) if path.suffix == ".pkl" else pd.read_csv(path, parse_dates=["kickoff"])
    m = m[m.played & m.has_npxg].copy()
    m["result"] = np.where(m.home_goals > m.away_goals, 0,
                           np.where(m.home_goals == m.away_goals, 1, 2))
    return m.sort_values("kickoff").reset_index(drop=True)


def walk_forward(m: pd.DataFrame, test_from: pd.Timestamp, *, xi_q, xi_t, lam_q, lam_t,
                 xi_level: float = 0.0, refit_days: int = 14, min_train: int = 300,
                 score_kinds: Sequence[str] = ("league",)) -> pd.DataFrame:
    """Refit every `refit_days`, predict that window. Scored only on `score_kinds` so the number
    stays comparable across runs, while TRAINING always uses every competition available."""
    target = m[(m.kickoff >= test_from) & m.kind.isin(score_kinds)]
    if target.empty:
        raise RuntimeError("backtest_qt: no fixtures in the test window")
    edges = pd.date_range(target.kickoff.min().normalize(),
                          target.kickoff.max().normalize() + pd.Timedelta(days=refit_days),
                          freq=f"{refit_days}D")
    chunks = []
    for start, end in zip(edges[:-1], edges[1:]):
        window = m[(m.kickoff >= start) & (m.kickoff < end) & m.kind.isin(score_kinds)]
        if window.empty:
            continue
        train = m[m.kickoff < start]
        if len(train) < min_train:
            continue
        model = fit(train, start, xi_q=xi_q, xi_t=xi_t, lam_q=lam_q, lam_t=lam_t,
                    xi_level=xi_level)
        tr_h, tr_a = predict_npxg(train, model)
        calib = fit_goal_calibration(train, tr_h, tr_a)
        mu_h, mu_a = predict_npxg(window, model)
        lam_h, lam_a = apply_goal_calibration(window, mu_h, mu_a, calib)
        chunks.append(pd.DataFrame({
            "season": window.season.to_numpy(), "competition": window.competition.to_numpy(),
            "kickoff": window.kickoff.to_numpy(), "result": window.result.to_numpy(),
            "lam_h": lam_h, "lam_a": lam_a,
            "home_goals": window.home_goals.to_numpy(), "away_goals": window.away_goals.to_numpy(),
        }))
    return pd.concat(chunks, ignore_index=True)


def leave_one_season_out(losses: Dict[tuple, np.ndarray], seasons: Dict[tuple, np.ndarray],
                         test_seasons: Sequence[int]):
    """For each held-out season, pick the config minimising pooled loss on the OTHERS."""
    picks, held = [], []
    for out in test_seasons:
        best, key = None, None
        for k, v in losses.items():
            s = float(v[seasons[k] != out].mean())
            if best is None or s < best:
                best, key = s, k
        mask = seasons[key] == out
        picks.append((out, key, float(losses[key][mask].mean()), int(mask.sum())))
        held.append(losses[key][mask])
    return picks, np.concatenate(held)


def paired(a: np.ndarray, b: np.ndarray) -> Tuple[float, float, float]:
    d = a - b
    se = float(d.std(ddof=1) / np.sqrt(len(d)))
    return float(d.mean()), se, (float(d.mean() / se) if se > 0 else float("nan"))


def _hl(values: List[str]) -> List[Optional[int]]:
    return [None if v.lower() == "none" else int(v) for v in values]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", type=Path, default=MASTER)
    ap.add_argument("--test-from", default="2022-08-01")
    ap.add_argument("--hl-q", nargs="+", default=["none", "500", "280", "200", "140", "100"],
                   help="Q half-lives in days ('none' = no decay)")
    ap.add_argument("--hl-t", nargs="+", default=["none", "1460"])
    ap.add_argument("--lam-q", nargs="+", type=float, default=[20, 12, 8, 5, 3])
    ap.add_argument("--lam-t", nargs="+", type=float, default=[10, 5, 3])
    ap.add_argument("--rho", nargs="+", type=float,
                   default=[0.0, -0.04, -0.08, -0.10, -0.13])
    ap.add_argument("--refit-days", type=int, default=14)
    ap.add_argument("--train-kinds", nargs="+", default=["league", "uefa", "cup"])
    args = ap.parse_args()

    m = load_master(args.master)
    m = m[m.kind.isin(args.train_kinds)]
    test_from = pd.Timestamp(args.test_from)
    test_seasons = sorted(m[(m.kickoff >= test_from) & (m.kind == "league")].season.unique())
    print(f"{len(m)} fixtures; test seasons {test_seasons}; refit every {args.refit_days}d")
    print(f"training kinds: {sorted(m.kind.unique())}")

    losses, seasons, preds = {}, {}, {}
    grid = list(itertools.product(_hl(args.hl_q), _hl(args.hl_t), args.lam_q, args.lam_t))
    for i, (hq, ht, lq, lt) in enumerate(grid, 1):
        pred = walk_forward(m, test_from,
                            xi_q=0.0 if hq is None else np.log(2) / hq,
                            xi_t=0.0 if ht is None else np.log(2) / ht,
                            lam_q=lq, lam_t=lt, refit_days=args.refit_days)
        key = (hq, ht, lq, lt)
        losses[key] = log_loss(pred)
        seasons[key] = pred.season.to_numpy()
        preds[key] = pred
        if i % 10 == 0 or i == len(grid):
            print(f"  {i}/{len(grid)} configs", flush=True)

    picks, selected = leave_one_season_out(losses, seasons, test_seasons)
    print("\n== leave-one-season-out ==")
    for out, key, score, n in picks:
        print(f"  held out {out}: hl_Q={key[0]} hl_T={key[1]} lam_q={key[2]:g} lam_t={key[3]:g}"
              f"  -> {score:.4f} (n={n})")
    print(f"  LOSO pooled log-loss: {selected.mean():.4f}  (n={len(selected)})")
    best = min(losses, key=lambda k: losses[k].mean())
    print(f"  single best config (optimistically biased): {best} -> {losses[best].mean():.4f}")

    print("\n== Dixon-Coles rho, on the best config ==")
    for rho in args.rho:
        v = log_loss(preds[best], rho)
        print(f"  rho={rho:+.3f}  pooled {v.mean():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
