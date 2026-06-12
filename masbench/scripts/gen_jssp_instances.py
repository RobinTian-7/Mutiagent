"""Deterministic synthetic JSSP instance generator (corroboration suite).

Writes OR-library-format ``*.jssp`` files with a ``# ub:`` bound computed by
a greedy non-delay list scheduler (shortest-processing-time tie-broken by
job id). The UB is therefore a REAL feasible makespan a decent heuristic
achieves: row exact_match (makespan <= ub) means "matched or beat the
heuristic", which has honest dynamic range for LLM teams, unlike known
optima (floor) or naive duration sums (ceiling).

Usage:
    python scripts/gen_jssp_instances.py --out runs/jssp_gen --count 6 \
        --jobs 5 --machines 3 --ops 3 --seed 7
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path


def make_instance(rng: random.Random, n_jobs: int, n_machines: int, n_ops: int):
    jobs = []
    for _ in range(n_jobs):
        machines = rng.sample(range(n_machines), k=min(n_ops, n_machines))
        while len(machines) < n_ops:
            machines.append(rng.randrange(n_machines))
        jobs.append([[m, rng.randint(2, 9)] for m in machines])
    return jobs


def greedy_ub(jobs: list[list[list[int]]], n_machines: int) -> int:
    """Non-delay greedy list schedule -> feasible makespan upper bound."""
    next_op = [0] * len(jobs)
    job_free = [0] * len(jobs)
    machine_free = [0] * n_machines
    makespan = 0
    remaining = sum(len(ops) for ops in jobs)
    while remaining:
        best = None
        for j, ops in enumerate(jobs):
            k = next_op[j]
            if k >= len(ops):
                continue
            machine, duration = ops[k]
            start = max(job_free[j], machine_free[machine])
            key = (start, duration, j)
            if best is None or key < best[0]:
                best = (key, j, machine, duration, start)
        _, j, machine, duration, start = best
        end = start + duration
        next_op[j] += 1
        job_free[j] = end
        machine_free[machine] = end
        makespan = max(makespan, end)
        remaining -= 1
    return makespan


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--jobs", type=int, default=5)
    p.add_argument("--machines", type=int, default=3)
    p.add_argument("--ops", type=int, default=3)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    for i in range(args.count):
        jobs = make_instance(rng, args.jobs, args.machines, args.ops)
        ub = greedy_ub(jobs, args.machines)
        lines = [
            f"# synthetic JSSP (gen_jssp_instances.py seed={args.seed} idx={i})",
            f"# ub: {ub}",
            f"{args.jobs} {args.machines}",
        ]
        for ops in jobs:
            lines.append(" ".join(f"{m} {d}" for m, d in ops))
        path = out / f"syn{i:02d}.jssp"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {path} (ub={ub})")


if __name__ == "__main__":
    main()
