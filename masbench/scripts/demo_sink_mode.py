"""Offline demo: the SINK evaluation mode (single sinkpoint, full coverage).

No OpenAI, no keys: fake/deterministic clients and a synthetic instance only.
Shows (1) the structural knowledge propagation reaching ONE designated sink,
(2) the engine grading ONLY that sink (sink_exact/sink_information_coverage),
and (3) the end-to-end fixed + graphgen arms running in sink mode.

Run:  cd masbench && uv run python scripts/demo_sink_mode.py
"""
from __future__ import annotations

import json

import masbench  # noqa: F401
from exp_graph.mas.information_flow import (
    coverage_by_agent,
    propagate_knowledge,
    sink_covered,
)

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.engine import run_fixed_protocol, run_instance


def synthetic_instance(n: int = 5) -> BenchmarkInstance:
    shards = [[i * 10 + 1, i * 10 + 5] for i in range(n)]
    global_max = max(v for shard in shards for v in shard)
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",  # associative-reduce case: offline solvable
        case_name="Global Max (synthetic demo)",
        n_agents=n,
        shards=shards,
        ground_truth=global_max,
        task_prompt=(
            "Find the GLOBAL maximum across all agents' shards. "
            "You are agent {agent_id}; your shard: {input_shard}."
        ),
        meta={
            "num_agents": n,
            "output_type": "scalar",
            "is_segmented": False,
            "expected_outputs": [global_max] * n,
        },
    )


def main() -> int:
    print("=" * 66)
    print("DEMO: sink evaluation mode (single sinkpoint, offline/fake LLM)")
    print("=" * 66)

    # 1. Structural view: a gather-only star gives the sink full coverage.
    n = 5
    star = [[(i, 0) for i in range(1, n)]]
    knowledge = propagate_knowledge(n, star)
    print("\n[1] structural propagation over a gather-only star (edges -> sink 0):")
    print(f"    knowledge sets: {[sorted(k) for k in knowledge]}")
    print(f"    coverage by agent: {coverage_by_agent(knowledge)}")
    print(f"    sink_covered(sink=0) = {sink_covered(knowledge, 0)}  <- sink mode PASSES")

    # 2. End-to-end fixed chain arm in sink mode.
    inst = synthetic_instance(n)
    cfg = RunConfig(llm_provider="fake", n_agents=n, silo_eval_mode="sink")
    fixed = run_fixed_protocol(inst, cfg, topology="chain")
    print("\n[2] fixed chain arm (sink mode):")
    print(
        f"    success={fixed.success} sink_id={fixed.extra['sink_id']} "
        f"sink_exact={fixed.extra['sink_exact']} "
        f"sink_information_coverage={fixed.extra['sink_information_coverage']}"
    )
    print(f"    messages={fixed.n_messages} provenance={fixed.extra['provenance']}")

    # 3. End-to-end clean GraphGen arm in sink mode (fake architect).
    gg_cfg = RunConfig(
        llm_provider="fake",
        use_planner=True,
        planner_mode="graph_generate",
        n_agents=n,
        silo_eval_mode="sink",
    )
    gg = run_instance(inst, gg_cfg)
    print("\n[3] graphgen arm (sink mode, fake architect):")
    print(
        f"    success={gg.success} topology={gg.extra['topology']} "
        f"generated_steps={gg.extra['generated_steps']}"
    )
    print(
        f"    sink_id={gg.extra['sink_id']} "
        f"sink_information_coverage={gg.extra['sink_information_coverage']} "
        f"provenance={gg.extra['provenance']}"
    )
    print(f"    architect audit dir: {gg.extra['graph_artifacts_dir']}")

    summary = {
        "mode": "sink",
        "structural_star_sink_covered": sink_covered(knowledge, 0),
        "fixed_chain_success": fixed.success,
        "graphgen_success": gg.success,
        "graphgen_sink_coverage": gg.extra["sink_information_coverage"],
    }
    print("\nsummary:", json.dumps(summary))
    ok = (
        summary["structural_star_sink_covered"]
        and fixed.extra["sink_information_coverage"] == 1.0
        and gg.extra["sink_information_coverage"] == 1.0
    )
    print("DEMO RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
