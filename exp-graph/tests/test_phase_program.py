import json
from pathlib import Path

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.phase_program import (
    PhaseProgram,
    PhaseProgramError,
    PhaseProgramLimits,
    compile_phase_program,
    compile_phase_program_spec,
)
from exp_graph.mas.phase_program_generation import (
    build_phase_program_prompt,
    plan_phase_program,
)
from exp_graph.mas.evolution import make_skill_card
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest, SkillCard
from exp_graph.mas.skill_bank import SkillBank, is_selectable_skill
from exp_graph.protocols import ProtocolGraphSpec, ProtocolStepSpec


def test_gather_broadcast_compiles_to_full_all_agent_coverage() -> None:
    program = PhaseProgram.model_validate(
        {
            "information_goal": "all_agents",
            "selected_primary": 0,
            "phases": [
                {"kind": "gather", "hub": 0, "pattern": "tree"},
                {"kind": "broadcast", "hub": 0, "pattern": "tree"},
            ],
        }
    )

    spec, compiled = compile_phase_program_spec(
        program,
        n_agents=5,
        limits=PhaseProgramLimits(
            max_steps=8,
            max_messages=16,
            max_receiver_fan_in=4,
        ),
    )

    assert all(known == [0, 1, 2, 3, 4] for known in compiled.final_knowledge)
    assert spec.metadata["program_mode"] == "program_generate"
    assert spec.metadata["state_retention"] == "keep"
    assert spec.metadata["allow_no_send"] is True


def test_delta_or_no_send_omits_redundant_rounds() -> None:
    program = PhaseProgram.model_validate(
        {
            "information_goal": "all_agents",
            "phases": [
                {
                    "kind": "pairwise_exchange",
                    "pattern": "ring",
                    "max_rounds": 3,
                    "stop_when": "fixed_rounds",
                    "send_mode": "delta_or_no_send",
                }
            ],
        }
    )

    compiled = compile_phase_program(program, n_agents=2)

    assert len(compiled.steps) == 1
    assert compiled.expanded_messages == 2
    assert any("no-delta sends" in warning for warning in compiled.warnings)


def test_phase_compiler_enforces_receiver_fan_in_budget() -> None:
    program = PhaseProgram.model_validate(
        {
            "phases": [
                {"kind": "gather", "hub": 0, "pattern": "star"},
            ]
        }
    )

    with pytest.raises(PhaseProgramError, match="max_receiver_fan_in"):
        compile_phase_program(
            program,
            n_agents=5,
            limits=PhaseProgramLimits(max_receiver_fan_in=2),
        )


def test_architect_prompt_exposes_stages_but_not_edge_programming() -> None:
    prompt = build_phase_program_prompt(
        request=PlannerRequest(
            n_agents=5,
            planner_mode="program_generate",
            information_goal="all_agents",
        ),
        skills=[],
        avoid_skills=[],
        max_steps=8,
        max_messages=32,
        max_receiver_fan_in=4,
        num_candidates=1,
        task_brief="Combine private inputs.",
    )

    assert '"format": "phase_program_v1"' in prompt
    assert '"pairwise_exchange"' in prompt
    assert '"program_generate"' in prompt
    assert '"steps"' not in prompt
    assert '"edges"' not in prompt


def test_skill_replay_is_namespaced_from_free_graphgen() -> None:
    program = PhaseProgram.model_validate(
        {"phases": [{"kind": "gather", "hub": 0, "pattern": "tree"}]}
    )
    program_spec, _ = compile_phase_program_spec(program, n_agents=2)
    graph_spec = ProtocolGraphSpec(
        name="free_graph",
        n_agents=2,
        steps=[ProtocolStepSpec(transmissions=[(0, 1)])],
        metadata={"generated_graph": True},
    )
    bank = SkillBank(
        [
            SkillCard(
                skill_id="program_replay",
                task_family="test",
                provenance="skill_replay",
                organization_policy={
                    "protocol_spec": program_spec.model_dump(mode="json")
                },
            ),
            SkillCard(
                skill_id="graph_replay",
                task_family="test",
                provenance="skill_replay",
                organization_policy={
                    "protocol_spec": graph_spec.model_dump(mode="json")
                },
            ),
        ]
    )

    program_matches = bank.retrieve(
        PlannerRequest(
            task_family="test",
            n_agents=2,
            planner_mode="program_generate",
            provenance_allowlist=["program_generated", "skill_replay"],
        )
    )
    graph_matches = bank.retrieve(
        PlannerRequest(
            task_family="test",
            n_agents=2,
            planner_mode="graph_generate",
            provenance_allowlist=["llm_generated", "skill_replay"],
        )
    )

    assert [skill.skill_id for skill in program_matches] == ["program_replay"]
    assert [skill.skill_id for skill in graph_matches] == ["graph_replay"]


def test_invalid_program_evidence_is_saved_as_counterexample_skill() -> None:
    card = make_skill_card(
        skill_id="invalid_program",
        topology_name="program:invalid",
        objective="balanced",
        operators=[],
        task_family="silo",
        expected_tradeoff={"mean_primary_loss": 1.0},
        evidence=[
            {
                "topology_name": "program:invalid",
                "n_agents": 5,
                "mean_primary_loss": 1.0,
                "program_validity": 0.0,
                "structural_coverage": 0.0,
                "submission_rate": 0.0,
                "evolution_partial": 0.0,
                "evolution_stage": "validity",
                "planner_mode": "program_generate",
                "information_goal": "all_agents",
                "provenance": "program_generated",
                "case_id": "II-01",
                "seed": 1,
            }
        ],
    )

    assert "counterexample" in card.tags
    assert not is_selectable_skill(card)
    assert card.failure_modes[0]["stage"] == "validity"
    assert card.counterexamples[0]["case_id"] == "II-01"


class _RepairClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        del model_name, temperature
        self.calls += 1
        phases = [
            {"kind": "gather", "hub": 0, "pattern": "tree"},
        ]
        if self.calls > 1:
            assert "missing_source_agents" in prompt
            phases.append(
                {"kind": "broadcast", "hub": 0, "pattern": "tree"}
            )
            payload = {
                "program": {
                    "format": "phase_program_v1",
                    "information_goal": "all_agents",
                    "selected_primary": 0,
                    "state_retention": "keep",
                    "allow_no_send": True,
                    "submit_when": "coverage_complete",
                    "phases": phases,
                },
                "rationale": "Disseminate the gathered state.",
            }
        else:
            payload = {
                "candidates": [
                    {
                        "candidate_id": "needs_repair",
                        "name": "gather_only",
                        "program": {
                            "format": "phase_program_v1",
                            "information_goal": "all_agents",
                            "selected_primary": 0,
                            "state_retention": "keep",
                            "allow_no_send": True,
                            "submit_when": "coverage_complete",
                            "phases": phases,
                        },
                    }
                ]
            }
        return LLMResponse(
            text=json.dumps(payload),
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        )


class _TaskAdapter:
    def describe_task(self) -> str:
        return "Combine private inputs into one answer."


def test_program_planner_repairs_from_coverage_counterexample(
    tmp_path: Path,
) -> None:
    client = _RepairClient()
    result = plan_phase_program(
        request=PlannerRequest(
            task_family="test",
            n_agents=4,
            planner_mode="program_generate",
            information_goal="all_agents",
            provenance_allowlist=["program_generated", "skill_replay"],
        ),
        runtime=MASRuntimeConfig(
            llm_provider="openai",
            model_name="planner-test",
            num_graph_candidates=1,
            graph_max_steps=8,
            graph_max_messages=16,
            graph_max_receiver_fan_in=4,
            program_repair_attempts=1,
            information_goal="all_agents",
        ),
        skill_bank=SkillBank(),
        seed=0,
        task_adapter=_TaskAdapter(),
        output_dir=tmp_path,
        llm_client=client,
    )

    assert client.calls == 2
    assert result.plan.planner_mode == "program_generate"
    assert result.plan.provenance == "program_generated"
    assert result.candidates[0].status == "selected"
    assert len(result.candidates[0].repair_attempts) == 1
    assert result.candidates[0].counterexamples == []
    assert (tmp_path / "program_architect_call.json").exists()
