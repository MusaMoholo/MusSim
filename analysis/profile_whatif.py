"""Paired accumulator cost on identical worlds, against an archived pre-what-if module.

    .venv/bin/python analysis/profile_whatif.py --baseline /path/to/pre-whatif/projection.py

Worlds are generated once and offered to both accumulators. Their order alternates to balance
cache/scheduling effects; only each complete add() is timed. Neither the profiler nor the new
tally reads columns through the world's state/knockout attrs. Simulation and fitting are outside
the add timings. --candidate can point at an archived completed implementation for later replay.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT / "scripts/projection.py")
    parser.add_argument("--worlds", type=int, default=100)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--as-of", default="2026-10-20")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.worlds < 2:
        raise ValueError("at least two worlds are needed to alternate the timing order")
    baseline = load_module(args.baseline.resolve(), "projection_whatif_baseline")
    candidate = load_module(args.candidate.resolve(), "projection_whatif_candidate")
    params = candidate.coerce_params({"season": args.season, "worlds": args.worlds,
                                     "seed": args.seed, "as_of": args.as_of}, args.season,
                                    max_worlds=2_000_000)
    engine = candidate.Engine()
    prep = candidate.prepare_for(engine, params)
    fx = prep["fixtures"]
    hands, _ = candidate.build_handovers(engine, fx, params)
    cups = candidate.cup_handovers(fx, engine.master, np.random.default_rng(params["seed"]))
    unseen = candidate.unseen_for(prep, fx, params)
    track, nxt = candidate.tracked_fixtures(fx, params["match_rounds"])
    stages = candidate.first_pending_stages(hands, candidate.match_horizon(fx))
    kwargs = {"places": prep["places"], "scale": prep["scale"], "pen_xg": prep["pen_xg"]}
    old = baseline.Accumulator(fx, track, stages, nxt, **kwargs)
    new = candidate.Accumulator(fx, track, stages, nxt, **kwargs)
    elapsed = {"baseline": [], "candidate": []}
    simulation_seconds = 0.0
    print(f"Baseline: {args.baseline.resolve()}")
    print(f"Candidate: {args.candidate.resolve()}")
    print(f"Season {args.season}, as_of {args.as_of}, seed {args.seed}, {args.worlds} identical worlds")
    kinds = Counter(meta["kind"] for i, meta in enumerate(new.fx_meta) if new.whatif_pos[i] >= 0)
    print(f"Eligible contexts: {sum(kinds.values())}, by kind {dict(sorted(kinds.items()))}")
    print(f"What-if array: shape {new.fx_whatif.shape}, dtype {new.fx_whatif.dtype}, "
          f"{new.fx_whatif.nbytes} bytes ({new.fx_whatif.nbytes / 1024:.3f} KiB)")
    for i in range(args.worlds):
        start = time.perf_counter()
        world = candidate.simulate(fx, prep["model"], prep["calib"], prep["elo0"],
                                   np.random.default_rng(params["seed"] * 1_000_003 + i),
                                   **candidate.world_kwargs(prep, params), master=engine.master,
                                   handovers=hands, cups=cups, unseen=unseen)
        simulation_seconds += time.perf_counter() - start
        order = [("baseline", old), ("candidate", new)]
        if i % 2:
            order.reverse()
        for label, acc in order:
            start = time.perf_counter()
            acc.add(world)
            elapsed[label].append(time.perf_counter() - start)
        if (i + 1) % max(1, args.worlds // 10) == 0 or i + 1 == args.worlds:
            print(f"  worlds {i + 1}/{args.worlds}", flush=True)
    assert old.result() == new.result(), "what-if changed an existing aggregate value"
    old_matches, new_matches = baseline.match_payload(old), candidate.match_payload(new)
    for fixture in new_matches["fixtures"]:
        fixture.pop("whatif", None)
    assert old_matches == new_matches, "what-if changed an existing match value"
    old_seconds, new_seconds = sum(elapsed["baseline"]), sum(elapsed["candidate"])
    delta = new_seconds - old_seconds
    paired = np.asarray(elapsed["candidate"]) - np.asarray(elapsed["baseline"])
    print(f"Baseline complete add(): {old_seconds:.6f}s")
    print(f"Candidate complete add(): {new_seconds:.6f}s")
    print(f"Increment: {delta:+.6f}s ({100 * delta / old_seconds:+.3f}%) "
          f"over {args.worlds} worlds; {1000 * delta / args.worlds:+.6f}ms/world")
    print(f"Paired median increment: {1000 * float(np.median(paired)):+.6f}ms/world")
    print(f"Simulation only, excluded from add timings: {simulation_seconds:.6f}s")
    print("PASS: identical existing aggregates and match payload after removing only whatif")


if __name__ == "__main__":
    main()
