"""Deterministic, auditable stratified TRAIN/TEST split for the hot-start
PythonGenerate all_agents study (frozen before any paid call).

Selection rule (frozen):
  * Pool = every available n=5 case at the requested levels (default II, III).
  * For each level, deterministically shuffle the level's cases with a single
    ``random.Random(seed)`` drawn ONCE and consumed level-by-level in sorted
    level order, then take the first ``per_level_train`` for TRAIN and the next
    ``per_level_test`` for TEST. TRAIN and TEST are disjoint by construction.

The manifest records the exact RNG draws so the split can be reproduced and
audited; it must be written before the first paid model call and never changed
based on results.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter


def build_split(
    *,
    benchmarks_dir: str,
    levels: list[str],
    n_agents: int,
    seed: int,
    per_level_train: int,
    per_level_test: int,
) -> dict:
    adapter = SiloBenchAdapter(benchmarks_dir)
    instances = list(
        adapter.iter_instances(levels=levels, agent_counts=[n_agents])
    )
    by_level: dict[str, list[str]] = {}
    for inst in instances:
        by_level.setdefault(inst.case_id.split("-", 1)[0], []).append(inst.case_id)
    for level in by_level:
        by_level[level] = sorted(set(by_level[level]))

    rng = random.Random(seed)
    strata: list[dict] = []
    train_cases: list[str] = []
    test_cases: list[str] = []
    for level in sorted(by_level):  # deterministic level order: II before III
        pool = list(by_level[level])
        order = pool[:]
        rng.shuffle(order)  # single shared RNG, consumed in sorted level order
        need = per_level_train + per_level_test
        if len(order) < need:
            raise SystemExit(
                f"level {level}: need {need} cases but only {len(order)} available"
            )
        picked = order[:need]
        lvl_train = picked[:per_level_train]
        lvl_test = picked[per_level_train:need]
        train_cases.extend(lvl_train)
        test_cases.extend(lvl_test)
        strata.append(
            {
                "level": level,
                "pool_sorted": pool,
                "shuffled_order": order,
                "train": lvl_train,
                "test": lvl_test,
            }
        )

    overlap = sorted(set(train_cases) & set(test_cases))
    assert not overlap, f"TRAIN/TEST overlap: {overlap}"
    return {
        "seed": seed,
        "levels": levels,
        "n_agents": n_agents,
        "per_level_train": per_level_train,
        "per_level_test": per_level_test,
        "train_cases": sorted(train_cases),
        "test_cases": sorted(test_cases),
        "strata": strata,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--benchmarks-dir",
        default="third_party/acl26-silo-bench/benchmarks",
    )
    p.add_argument("--levels", nargs="+", default=["II", "III"])
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--seed", type=int, default=20260712)
    p.add_argument("--per-level-train", type=int, default=2)
    p.add_argument("--per-level-test", type=int, default=2)
    p.add_argument("--out", default=None, help="optional path to write the split JSON")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    split = build_split(
        benchmarks_dir=args.benchmarks_dir,
        levels=args.levels,
        n_agents=args.n_agents,
        seed=args.seed,
        per_level_train=args.per_level_train,
        per_level_test=args.per_level_test,
    )
    print(json.dumps(split, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(split, indent=2, sort_keys=True))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
