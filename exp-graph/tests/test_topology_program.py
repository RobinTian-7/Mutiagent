import json
from pathlib import Path

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GraphValidationOptions,
    _validate_and_compile_candidates,
    build_free_graph_prompt,
    plan_free_graph,
)
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.topology_program import (
    TopologyProgram,
    TopologyProgramError,
    TopologyProgramLimits,
    compile_topology_program,
)
from exp_graph.runner import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks import CountFrequencyTaskAdapter


def _chain_program() -> TopologyProgram:
    return TopologyProgram.model_validate(
        {
            "format": "topology_program_v1",
            "selected_primary": "n_agents - 1",
            "body": [
                {
                    "op": "repeat",
                    "var": "i",
                    "range": {"start": 0, "stop": "n_agents - 1"},
                    "body": [
                        {
                            "op": "step",
                            "description": "forward accumulated state",
                            "edges": [{"src": "i", "dst": "i + 1"}],
                        }
                    ],
                }
            ],
        }
    )


def test_repeat_program_expands_to_finite_chain() -> None:
    compiled = compile_topology_program(_chain_program(), n_agents=4)

    assert compiled.selected_primary == 3
    assert [step.edges for step in compiled.steps] == [
        [(0, 1)],
        [(1, 2)],
        [(2, 3)],
    ]
    assert compiled.expanded_messages == 3


def test_for_each_when_omits_non_senders() -> None:
    program = TopologyProgram.model_validate(
        {
            "body": [
                {
                    "op": "step",
                    "description": "only even agents send",
                    "edges": [
                        {
                            "src": "i",
                            "dst": "i + 1",
                            "when": "not (i % 2 == 1)",
                            "for_each": [
                                {
                                    "var": "i",
                                    "range": {"stop": "n_agents - 1"},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )

    compiled = compile_topology_program(program, n_agents=6)

    assert compiled.steps[0].edges == [(0, 1), (2, 3), (4, 5)]


def test_repeat_and_for_each_expand_butterfly_exchange() -> None:
    program = TopologyProgram.model_validate(
        {
            "selected_primary": "n_agents - 1",
            "body": [
                {
                    "op": "repeat",
                    "var": "r",
                    "range": {"stop": "ceil_log2(n_agents)"},
                    "body": [
                        {
                            "op": "step",
                            "edges": [
                                {
                                    "src": "i",
                                    "dst": "i ^ pow2(r)",
                                    "for_each": [
                                        {
                                            "var": "i",
                                            "range": {"stop": "n_agents"},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    compiled = compile_topology_program(program, n_agents=4)

    assert [step.edges for step in compiled.steps] == [
        [(0, 1), (1, 0), (2, 3), (3, 2)],
        [(0, 2), (1, 3), (2, 0), (3, 1)],
    ]


def test_program_rejects_arbitrary_python_calls() -> None:
    program = TopologyProgram.model_validate(
        {
            "body": [
                {
                    "op": "step",
                    "edges": [
                        {
                            "src": "__import__('os').system('true')",
                            "dst": 1,
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(TopologyProgramError, match="function call is not allowed"):
        compile_topology_program(program, n_agents=2)


def test_program_rejects_unbounded_expansion_before_materializing() -> None:
    program = TopologyProgram.model_validate(
        {
            "body": [
                {
                    "op": "repeat",
                    "var": "r",
                    "range": {"stop": 100_000},
                    "body": [
                        {
                            "op": "step",
                            "edges": [{"src": 0, "dst": 1}],
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(TopologyProgramError, match="loop has 100000 iterations"):
        compile_topology_program(
            program,
            n_agents=2,
            limits=TopologyProgramLimits(
                max_steps=8,
                max_messages=8,
                max_loop_iterations=16,
            ),
        )


def test_program_candidate_uses_existing_validation_and_protocol_compiler() -> None:
    graph = GeneratedGraphPlan(
        candidate_id="program_chain",
        name="program_chain",
        n_agents=4,
        program=_chain_program(),
    )

    state = _validate_and_compile_candidates(
        [graph],
        GraphValidationOptions(n_agents=4, max_steps=4, max_messages=8),
    )[0]

    assert state.record.status == "valid"
    assert state.spec is not None
    assert [step.transmissions for step in state.spec.steps] == [
        [(0, 1)],
        [(1, 2)],
        [(2, 3)],
    ]
    compilation = state.spec.metadata["program_compilation"]
    assert compilation["expanded_steps"] == 3
    assert compilation["expanded_messages"] == 3
    assert state.spec.metadata["topology_program"]["format"] == (
        "topology_program_v1"
    )

    adapter = CountFrequencyTaskAdapter()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="generated:program_chain",
            n_agents=4,
            protocol_spec=state.spec,
        ),
        task_adapter=adapter,
        global_task=adapter.build_global_task(
            array=[1, 2, 1, 3, 2, 3, 3, 1]
        ),
    ).run()
    assert result.final_result.exact_match is True
    assert result.final_agent_states[3].belief_state.structured_state[
        "known_sources"
    ] == [0, 1, 2, 3]


def test_invalid_program_does_not_poison_other_candidates() -> None:
    invalid = GeneratedGraphPlan(
        candidate_id="bad_program",
        n_agents=2,
        program=TopologyProgram.model_validate(
            {
                "body": [
                    {
                        "op": "step",
                        "edges": [{"src": "unknown_agent", "dst": 1}],
                    }
                ]
            }
        ),
    )
    valid = GeneratedGraphPlan(
        candidate_id="good_program",
        n_agents=2,
        program=TopologyProgram.model_validate(
            {
                "selected_primary": 1,
                "body": [
                    {
                        "op": "step",
                        "edges": [{"src": 0, "dst": 1}],
                    }
                ],
            }
        ),
    )

    states = _validate_and_compile_candidates(
        [invalid, valid],
        GraphValidationOptions(n_agents=2),
    )

    assert states[0].record.status == "rejected"
    assert "unknown name" in states[0].record.validation_errors[0]
    assert states[1].record.status == "valid"


class _ProgramGraphClient:
    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        payload = {
            "candidates": [
                {
                    "candidate_id": "llm_program",
                    "name": "llm_program_chain",
                    "n_agents": 4,
                    "program": _chain_program().model_dump(mode="json"),
                    "program_compilation": {"source_hash": "forged"},
                    "rationale": "Use a compact sequential relay.",
                }
            ]
        }
        return LLMResponse(
            text=json.dumps(payload),
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        )


def test_llm_planner_compiles_program_and_runs_existing_plan_path(
    tmp_path: Path,
) -> None:
    result = plan_free_graph(
        request=PlannerRequest.from_names(
            n_agents=4,
            array_size=8,
            planner_mode="graph_generate",
        ),
        runtime=MASRuntimeConfig(
            llm_provider="openai",
            model_name="planner-test",
            graph_max_steps=4,
            graph_max_messages=8,
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
        llm_client=_ProgramGraphClient(),
    )

    assert result.fallback_reason is None
    assert result.selected_candidate_id == "llm_program"
    assert [step.transmissions for step in result.plan.protocol_spec.steps] == [
        [(0, 1)],
        [(1, 2)],
        [(2, 3)],
    ]
    assert result.plan.protocol_spec.metadata["program_compilation"][
        "source_hash"
    ] != "forged"
    saved = json.loads((tmp_path / "selected_graph_plan.json").read_text())
    assert saved["graph_plan"]["program"]["format"] == "topology_program_v1"


def test_free_graph_prompt_teaches_program_and_state_semantics() -> None:
    prompt = build_free_graph_prompt(
        request=PlannerRequest.from_names(
            n_agents=4,
            planner_mode="graph_generate",
        ),
        skills=[],
        options=GraphValidationOptions(n_agents=4),
        num_candidates=1,
    )
    payload = json.loads(prompt)

    assert payload["topology_program_language"]["format"] == (
        "topology_program_v1"
    )
    assert "keeps its previous state" in payload["edge_semantics"][
        "state_retention"
    ]
    assert payload["required_json_shape"]["candidates"][0]["program"][
        "format"
    ] == "topology_program_v1"
