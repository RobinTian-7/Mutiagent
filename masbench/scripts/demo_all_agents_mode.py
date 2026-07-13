"""Offline demo: the ALL_AGENTS evaluation mode (everyone must know everything).

No OpenAI, no keys: fake/deterministic clients and synthetic structures only.
Shows (1) a gather-only star being REJECTED by the all_agents graph validator,
(2) the deterministic dissemination repair turning it into a passing
gather+broadcast structure, and (3) the engine's all_agents grading where one
wrong agent fails the whole run even though the majority is correct.

Run:  cd masbench && uv run python scripts/demo_all_agents_mode.py
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import masbench  # noqa: F401
from exp_graph.agents.schemas import AgentState, BeliefState, BeliefStatus
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphValidationOptions,
    repair_graph_plan,
    validate_graph_plan,
)
from exp_graph.mas.information_flow import (
    all_agents_covered,
    propagate_knowledge,
)
from exp_graph.protocols.schedules import CommunicationStep

from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.instance import BenchmarkInstance
from masbench.core.task_bridge import canonical_answer
from masbench.engine import _score_protocol_result


def synthetic_instance(n: int = 5) -> BenchmarkInstance:
    shards = [[i + 1] for i in range(n)]
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="DEMO-ALL",
        case_name="All-agents demo",
        n_agents=n,
        shards=shards,
        ground_truth=42,
        task_prompt="Everyone must end holding the global answer.",
        meta={
            "num_agents": n,
            "output_type": "scalar",
            "is_segmented": False,
            "expected_outputs": [42] * n,
        },
    )


def _belief(answer) -> BeliefState:
    key = canonical_answer(answer) if answer is not None else "UNKNOWN"
    return BeliefState(
        status=BeliefStatus.CANDIDATE, proposal="demo", consensus_key=key,
        support=[], uncertainty="", open_questions=[], private_notes="demo",
        structured_state={"task_name": "silo", "case_id": "DEMO-ALL", "answer": answer},
    )


def _result(schedule_edges, answers):
    states = [
        AgentState(local_observation={"agent_id": i}, belief_state=_belief(a))
        for i, a in enumerate(answers)
    ]
    schedule = [
        CommunicationStep(step_idx=i, transmissions=e, description=f"s{i}")
        for i, e in enumerate(schedule_edges)
    ]
    return SimpleNamespace(
        schedule=schedule, final_agent_states=states,
        total_messages=sum(len(e) for e in schedule_edges),
        total_steps=len(schedule_edges), total_model_calls=0,
        total_prompt_tokens=0, total_completion_tokens=0,
        config=SimpleNamespace(protocol_spec=None),
        final_result=SimpleNamespace(
            aggregation_method="vote", final_key="42", final_answer=42
        ),
    )


def main() -> int:
    n = 5
    print("=" * 66)
    print("DEMO: all_agents evaluation mode (offline, structural + scoring)")
    print("=" * 66)

    # 1. gather-only star is REJECTED by the all_agents validator.
    star = GeneratedGraphPlan(
        candidate_id="demo",
        name="gather_star",
        n_agents=n,
        steps=[GeneratedGraphStep(description="gather", edges=[(i, 0) for i in range(1, n)])],
        selected_primary=0,
    )
    all_opts = GraphValidationOptions(
        n_agents=n, require_full_sink_coverage=True,
        information_goal="all_agents", max_steps=6, max_messages=32,
    )
    verdict = validate_graph_plan(star, all_opts)
    print("\n[1] gather-only star under all_agents validation:")
    print(f"    valid={verdict.valid}")
    print(f"    errors={verdict.errors}")

    # 2. the dissemination repair adds a broadcast phase -> structure passes.
    repaired, notes = repair_graph_plan(star, all_opts)
    knowledge = propagate_knowledge(n, [s.edges for s in repaired.steps])
    reverdict = validate_graph_plan(repaired, all_opts)
    print("\n[2] deterministic all_agents repair (gather + broadcast):")
    print(f"    repair notes: {notes}")
    print(f"    steps now: {[s.edges for s in repaired.steps]}")
    print(f"    all_agents_covered={all_agents_covered(knowledge)} valid={reverdict.valid}")

    # 3. scoring: majority correct + one wrong agent MUST fail all_agents.
    inst = synthetic_instance(n)
    gt = SiloProtocolAdapter(inst).build_global_task()
    edges = [s.edges for s in repaired.steps]
    majority = _result(edges, answers=[42, 42, 42, 42, 7])  # agent4 is wrong
    score = _score_protocol_result(
        majority, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="all_agents",
    )
    print("\n[3] all_agents grading, majority correct but agent4 wrong:")
    print(f"    per_agent_correct={score.extra['per_agent_correct']}")
    print(f"    agent_success_rate={score.extra['agent_success_rate']}")
    print(f"    all_agents_exact={score.extra['all_agents_exact']}  -> success={score.success}")

    perfect = _result(edges, answers=[42] * n)
    score2 = _score_protocol_result(
        perfect, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="all_agents",
    )
    print("\n[4] all_agents grading, every agent correct:")
    print(
        f"    S={score2.extra['agent_success_rate']} "
        f"all_agents_exact={score2.extra['all_agents_exact']} "
        f"min_information_coverage={score2.extra['min_information_coverage']}"
    )

    summary = {
        "mode": "all_agents",
        "gather_only_rejected": not verdict.valid,
        "repaired_structure_passes": reverdict.valid,
        "one_wrong_agent_fails": not score.success,
        "all_correct_passes": score2.success,
    }
    print("\nsummary:", json.dumps(summary))
    ok = all(summary[k] for k in (
        "gather_only_rejected", "repaired_structure_passes",
        "one_wrong_agent_fails", "all_correct_passes",
    ))
    print("DEMO RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
