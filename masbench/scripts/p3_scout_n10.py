"""Phase-3 n=10 dynamic-range scout (power design, both-arm symmetric).

Measures BASELINE-side properties only -- no evolution, no tuning: for each
case, (a) cold graph-generation EM and (b) a fixed lossless organization
(one_peer_exponential_dag_star) EM, 3 seeds each. Distinguishes
organization floors (cold 0 but a good org scores) from model-capability
floors (0 under both). Explicitly allowed by the operator brief
("level II 找动态范围"); results feed the confirmatory pool geometry, never
parameter selection on arm comparisons.

Usage: uv run --extra openai python scripts/p3_scout_n10.py
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.curve import _bounded
from masbench.engine import _build_llm_client
from masbench.evolve import (
    _run_fixed_one,
    _run_one,
    evolution_objective_spec,
)

CASES = ["II-13", "II-14", "II-17", "II-18", "II-20"]
SEEDS = [101, 102, 103]
ORG = "one_peer_exponential_dag_star"


def main() -> int:
    cfg = RunConfig(
        benchmark="silo_bench", objective="accuracy_first",
        merge_mode="llm_full_merge", init_mode="llm_local_solve",
        llm_provider="openai", model_name="gpt-4o-mini",
        request_timeout=120.0, n_agents=10, planner_mode="graph_generate",
        num_graph_candidates=3,
    )
    adapter = SiloBenchAdapter("third_party/acl26-silo-bench/benchmarks")
    instances = {
        inst.case_id: inst
        for inst in adapter.iter_instances(levels=["II"], agent_counts=[10], cases=CASES)
    }
    client = _bounded(_build_llm_client(cfg), 8)
    objective = evolution_objective_spec(cfg)

    tasks = []
    for case in CASES:
        inst = instances[case]
        for seed in SEEDS:
            tasks.append(("coldgen", inst, seed))
            tasks.append((ORG, inst, seed))

    def one(task):
        arm, inst, seed = task
        try:
            if arm == "coldgen":
                row = _run_one(
                    inst, cfg, objective=objective, skill_bank=SkillBank(),
                    seed=seed, llm_client=client,
                )
            else:
                row = _run_fixed_one(
                    inst, cfg, topology=ORG, seed=seed, llm_client=client,
                )
            return arm, inst.case_id, float(row.get("ExactMatchRate", 0.0)), None
        except Exception as exc:  # noqa: BLE001 - scout must report, not die
            return arm, inst.case_id, 0.0, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, tasks))

    table: dict = {}
    for arm, case, em, err in results:
        table.setdefault(case, {}).setdefault(arm, []).append(em)
        if err:
            print(f"  [scout] {case} {arm} FAILED: {err}", flush=True)
    print("\ncase      coldgen        " + ORG)
    out = {}
    for case in CASES:
        c = table.get(case, {}).get("coldgen", [])
        f = table.get(case, {}).get(ORG, [])
        cm = sum(c) / len(c) if c else float("nan")
        fm = sum(f) / len(f) if f else float("nan")
        out[case] = {"coldgen": c, ORG: f}
        print(f"{case}   {cm:.2f} {c}   {fm:.2f} {f}")
    with open("runs/p3_scout_n10.json", "w") as fh:
        json.dump(out, fh, indent=1)
    print("\nreport: runs/p3_scout_n10.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
