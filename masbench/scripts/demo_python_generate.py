#!/usr/bin/env python3
"""Offline 3-agent demonstration of the independent PythonGen path."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import masbench  # noqa: F401  (bootstraps the sibling exp_graph package)
from exp_graph.mas.python_code_generation import plan_and_execute_python
from exp_graph.mas.schemas import MASRuntimeConfig, ObjectiveSpec, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank


class _DemoTaskAdapter:
    @staticmethod
    def describe_task() -> str:
        return "Combine private observations through explicit worker messages."


def _payload() -> dict:
    return {
        "execution_contract_version": "python_mas_v1",
        "task_description": "Synthetic wiring demonstration.",
        "information_goal": "all_agents",
        "selected_primary": 0,
        "n_agents": 3,
        "max_rounds": 2,
        "budgets": {
            "max_model_calls": 10,
            "max_completion_tokens": 4000,
            "max_messages": 10,
        },
        "worker_llm": {
            "provider": "fake",
            "model_name": "fake",
            "base_url": None,
            "api_key_env": None,
            "temperature": 0.0,
        },
        "agents": [
            {
                "agent_id": agent_id,
                "local_prompt": f"Synthetic private observation for agent {agent_id}.",
            }
            for agent_id in range(3)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=None,
        help="artifact directory (default: a retained temporary directory)",
    )
    args = parser.parse_args()
    output_dir = Path(args.out) if args.out else Path(
        tempfile.mkdtemp(prefix="queenbee-python-demo-")
    )
    request = PlannerRequest(
        task_family="silo",
        n_agents=3,
        objective=ObjectiveSpec.from_name("balanced"),
        planner_mode="python_generate",
        information_goal="all_agents",
        provenance_allowlist=["llm_generated_python", "skill_replay"],
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        information_goal="all_agents",
        python_max_rounds=2,
        python_max_model_calls=10,
        python_max_completion_tokens=4000,
        python_max_messages=10,
    )
    result = plan_and_execute_python(
        request=request,
        runtime=runtime,
        skill_bank=SkillBank(),
        task_adapter=_DemoTaskAdapter(),
        execution_payload=_payload(),
        output_dir=output_dir,
    )
    execution = result.execution
    assert execution.output is not None
    output = execution.output
    round_one_calls = [
        call for call in execution.ledger["calls"] if call["round"] == 1
    ]
    sent_round_zero = {
        message.src for message in output.messages if message.round_sent == 0
    }

    print("=== GENERATED program.py ===")
    print(result.source)
    print("=== VALIDATION / REPAIR ===")
    print(
        json.dumps(
            {
                "attempts": len(result.attempts),
                "repairs": result.repair_model_calls,
                "validation": result.attempts[-1]["validation"],
                "runtime_success": execution.runtime_success,
            },
            indent=2,
            sort_keys=True,
        )
    )
    print("=== EXECUTION SEMANTICS ===")
    print(
        json.dumps(
            {
                "rounds_executed": output.rounds_executed,
                "state_retained_in_round_1": all(
                    bool(call["previous_state_keys"]) for call in round_one_calls
                ),
                "round_0_senders": sorted(sent_round_zero),
                "agent_2_no_send_round_0": 2 not in sent_round_zero,
                "messages_visible_next_round_only": all(
                    message.round_delivered == message.round_sent + 1
                    for message in output.messages
                ),
                "submissions": [
                    submission.model_dump(mode="json")
                    for submission in output.submissions
                ],
                "authoritative_usage": execution.authoritative_usage.model_dump(
                    mode="json"
                ),
                "artifact_dir": str(output_dir.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(
        "NOTE: fake architect/workers validate wiring and accounting only; "
        "they deliberately do not solve the task."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
