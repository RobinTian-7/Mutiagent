from __future__ import annotations

import json
from pathlib import Path

import pytest

from exp_graph.mas.python_code import python_source_sha256
from exp_graph.mas.python_code_generation import (
    build_python_architect_scaffold,
    plan_and_execute_python,
)
from exp_graph.mas.python_mutation import (
    PythonMutationError,
    PythonMutationPatch,
    apply_python_mutation_patch,
    extract_evolve_blocks,
    sanitize_python_skill_context,
)
from exp_graph.mas.schemas import (
    MASRuntimeConfig,
    ObjectiveSpec,
    PlannerRequest,
    PythonSkillPayload,
    SkillCard,
)
from exp_graph.mas.skill_bank import SkillBank


@pytest.mark.parametrize(
    "worker_contract",
    ["action_json_v1", "message_only_v1", "message_only_v2"],
)
def test_mutation_patch_changes_only_an_existing_contract_block(
    worker_contract: str,
) -> None:
    parent = build_python_architect_scaffold(worker_contract)
    blocks = extract_evolve_blocks(parent)
    block = next(iter(blocks.values()))
    patch = PythonMutationPatch(
        parent_program_sha256=python_source_sha256(parent),
        block_id=block.block_id,
        replacement=block.content.rstrip("\n") + "\n# local mutation",
        used_insight_ids=["insight_1", "insight_1"],
    )

    applied = apply_python_mutation_patch(parent, patch)

    assert applied.parent_program_sha256 == python_source_sha256(parent)
    assert applied.mutated_program_sha256 == python_source_sha256(applied.source)
    assert applied.used_insight_ids == ("insight_1",)
    assert "# local mutation" in applied.source
    assert set(extract_evolve_blocks(applied.source)) == set(blocks)


def test_mutation_patch_rejects_wrong_hash_unknown_block_and_new_markers() -> None:
    parent = build_python_architect_scaffold("message_only_v2")
    block_id = next(iter(extract_evolve_blocks(parent)))
    values = {
        "parent_program_sha256": python_source_sha256(parent),
        "block_id": block_id,
        "replacement": "    return 0",
    }
    with pytest.raises(PythonMutationError, match="does not match"):
        apply_python_mutation_patch(
            parent,
            PythonMutationPatch(**{**values, "parent_program_sha256": "0" * 64}),
        )
    with pytest.raises(PythonMutationError, match="whitelist"):
        apply_python_mutation_patch(
            parent,
            PythonMutationPatch(**{**values, "block_id": "not_present"}),
        )
    with pytest.raises(PythonMutationError, match="markers"):
        apply_python_mutation_patch(
            parent,
            PythonMutationPatch(
                **{
                    **values,
                    "replacement": "# EVOLVE-BLOCK-START: injected",
                }
            ),
        )
    with pytest.raises(PythonMutationError, match="unexposed"):
        apply_python_mutation_patch(
            parent,
            PythonMutationPatch(
                **{**values, "used_insight_ids": ["invented_insight"]}
            ),
            allowed_insight_ids=["known_insight"],
        )


def test_parent_context_is_summary_only_and_drops_leak_fields() -> None:
    source = build_python_architect_scaffold()
    skill = SkillCard(
        skill_id="python_parent",
        task_family="silo",
        mode_payload=PythonSkillPayload(
            source_code=source,
            ast_policy_version="python_ast_v1",
            execution_contract_version="python_mas_v1",
        ),
        organization_policy={
            "source_code": "DO_NOT_EXPOSE",
            "protocol_spec": {"secret": True},
        },
        reasoning_policy={
            "merge": "deduplicate source ids",
            "local_prompt": "PRIVATE_PROMPT",
        },
        design_insights=[
            {
                "insight_id": "i1",
                "lesson": "exchange deltas" + ("x" * 10_000),
                "ground_truth": 7,
            }
        ],
        failure_modes=[{"error_type": "coverage", "answer": "SECRET"}],
        evidence=[
            {
                "program_validity": 1.0,
                "structural_coverage": 0.8,
                "submission_rate": 1.0,
                "evolution_partial": 0.5,
                "evolution_success": 0.0,
                "evolution_stage_score": 0.65,
                "paper_C": 12.0,
                "paper_D": 0.2,
                "final_answer": "SECRET",
            }
        ],
    )

    context = sanitize_python_skill_context(skill)
    encoded = json.dumps(context, sort_keys=True)

    assert context["parent_skill_id"] == "python_parent"
    assert context["dense_metrics"]["K"] == pytest.approx(0.8)
    assert "DO_NOT_EXPOSE" not in encoded
    assert "PRIVATE_PROMPT" not in encoded
    assert "SECRET" not in encoded
    assert "source_code" not in encoded
    assert "ground_truth" not in encoded
    assert len(encoded) <= 6_000


class _TaskAdapter:
    @staticmethod
    def describe_task() -> str:
        return "Synthetic task."


def test_fake_mutation_runs_full_validation_and_persists_provenance(
    tmp_path: Path,
) -> None:
    source = build_python_architect_scaffold()
    parent = SkillCard(
        skill_id="python_parent",
        task_family="silo",
        trigger={"planner_mode": "python_generate", "information_goal": "all_agents"},
        provenance="llm_generated_python",
        information_goal="all_agents",
        mode_payload=PythonSkillPayload(
            source_code=source,
            ast_policy_version="python_ast_v1",
            execution_contract_version="python_mas_v1",
        ),
    )
    request = PlannerRequest(
        task_family="silo",
        n_agents=2,
        objective=ObjectiveSpec.from_name("balanced"),
        planner_mode="python_generate",
        information_goal="all_agents",
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        python_max_rounds=2,
        python_innovation_branch="mutate",
        python_parent_skill_id=parent.skill_id,
        python_architect_context_enabled=True,
        information_goal="all_agents",
    )
    payload = {
        "execution_contract_version": "python_mas_v1",
        "worker_contract": "action_json_v1",
        "task_description": "Synthetic task.",
        "information_goal": "all_agents",
        "selected_primary": 0,
        "n_agents": 2,
        "max_rounds": 2,
        "budgets": {
            "max_model_calls": 8,
            "max_completion_tokens": 4000,
            "max_messages": 8,
        },
        "worker_llm": {
            "provider": "fake",
            "model_name": "fake",
            "base_url": None,
            "api_key_env": None,
            "temperature": 0.0,
        },
        "agents": [
            {"agent_id": agent_id, "local_prompt": f"PRIVATE_{agent_id}"}
            for agent_id in range(2)
        ],
    }

    result = plan_and_execute_python(
        request=request,
        runtime=runtime,
        skill_bank=SkillBank(skills=[parent]),
        task_adapter=_TaskAdapter(),
        execution_payload=payload,
        output_dir=tmp_path,
    )

    assert result.execution.runtime_success
    assert result.innovation_metadata["strategy"] == "mutate"
    assert result.innovation_metadata["parent_skill_id"] == "python_parent"
    assert len(result.innovation_metadata["patches"]) == 1
    assert (tmp_path / "mutation_patch_00.json").exists()
    assert (tmp_path / "mutation_diff_00.patch").exists()
    persisted = json.loads((tmp_path / "innovation_provenance.json").read_text())
    assert persisted["parent_program_sha256"] == python_source_sha256(source)
