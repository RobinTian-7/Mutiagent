import json
from pathlib import Path

import pytest

from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphValidationOptions,
    compile_generated_graph,
)
from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.runner import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks import CountFrequencyTaskAdapter


def _global_task():
    adapter = CountFrequencyTaskAdapter()
    return adapter, adapter.build_global_task(array=[1, 2, 1, 3, 2, 3, 3, 1])


def test_protocol_runner_chain_uses_last_agent_as_answer_holder() -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(topology_name="chain", n_agents=4),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_steps == 3
    assert result.total_messages == 3
    assert result.final_result.answer_agent_ids == [3]
    assert result.final_result.exact_match is True
    assert result.final_agent_states[3].belief_state.structured_state["known_sources"] == [
        0,
        1,
        2,
        3,
    ]


@pytest.mark.parametrize(
    ("topology_name", "expected_steps", "expected_messages"),
    [
        ("tree", 3, 7),
        ("dag_mesh", 7, 28),
        ("random", 7, 12),
        ("static_exponential_dag", 7, 17),
        ("two_stage_layer", 2, 15),
        ("balanced_log_layer", 3, 12),
        ("one_peer_exponential_dag_tree", 6, 31),
        ("one_peer_exponential_dag_star", 4, 31),
        ("one_peer_exponential_dag_static", 10, 41),
        ("static_exponential_star", 4, 79),
        ("mesh_star", 2, 63),
    ],
)
def test_protocol_runner_dag_style_topologies_use_last_agent_as_answer_holder(
    topology_name: str,
    expected_steps: int,
    expected_messages: int,
) -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(topology_name=topology_name, n_agents=8),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_steps == expected_steps
    assert result.total_messages == expected_messages
    assert result.final_result.answer_agent_ids == [7]
    assert result.final_result.exact_match is True
    assert result.final_agent_states[7].belief_state.structured_state["known_sources"] == [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]


def test_protocol_runner_generated_graph_uses_selected_primary_answer_holder() -> None:
    adapter, global_task = _global_task()
    graph = GeneratedGraphPlan(
        candidate_id="g1",
        name="balanced_tree_flow",
        n_agents=4,
        selected_primary=3,
        steps=[
            GeneratedGraphStep(edges=[(0, 1), (2, 3)]),
            GeneratedGraphStep(edges=[(1, 3)]),
        ],
    )
    spec = compile_generated_graph(graph, GraphValidationOptions(n_agents=4))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="generated:balanced_tree_flow",
            n_agents=4,
            protocol_spec=spec,
        ),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_steps == 2
    assert result.total_messages == 3
    assert result.final_result.answer_agent_ids == [3]
    assert result.final_result.exact_match is True
    assert result.final_result.vote.top_ratio == 1.0


def test_protocol_runner_one_peer_dag_vote_uses_all_agents_as_answer_holders() -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="one_peer_exponential_dag_vote",
            n_agents=4,
        ),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_steps == 2
    assert result.total_messages == 8
    assert result.final_result.answer_agent_ids == [0, 1, 2, 3]
    assert result.final_result.exact_match is True


def test_protocol_runner_mesh_records_vote_and_average_heads() -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(topology_name="mesh", n_agents=4),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_steps == 1
    assert result.final_result.vote.exact_match is True
    assert result.final_result.average is not None
    assert result.final_result.average.exact_match is True
    assert result.final_result.vote_average_disagreement_rmse == 0.0


def test_protocol_runner_one_peer_reaches_full_coverage_in_log_steps() -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(topology_name="one_peer_exponential", n_agents=4),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_steps == 2
    assert all(
        state.belief_state.structured_state["known_sources"] == [0, 1, 2, 3]
        for state in result.final_agent_states
    )
    assert result.final_result.exact_match is True


def test_protocol_runner_records_local_agent_error_curve() -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(topology_name="chain", n_agents=4),
        task_adapter=adapter,
        global_task=global_task,
    ).run()
    initial_agent_zero = next(
        row for row in result.agent_step_metrics if row.step_idx == -1 and row.agent_id == 0
    )
    final_agent_three = next(
        row for row in result.agent_step_metrics if row.step_idx == 2 and row.agent_id == 3
    )

    assert initial_agent_zero.coverage_ratio == 0.25
    assert initial_agent_zero.exact_match is True
    assert initial_agent_zero.local_exact_match is True
    assert initial_agent_zero.global_exact_match is False
    assert initial_agent_zero.rmse == 0.0
    assert initial_agent_zero.local_rmse == 0.0
    assert initial_agent_zero.global_rmse > 0.0
    assert final_agent_three.coverage_ratio == 1.0
    assert final_agent_three.normalized_l1_error == 0.0
    assert final_agent_three.global_normalized_l1_error == 0.0
    assert final_agent_three.rmse == 0.0
    assert final_agent_three.global_rmse == 0.0


def test_protocol_runner_llm_belief_merge_preserves_verified_cf_structure() -> None:
    adapter, global_task = _global_task()

    class WrongStructuredStateClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "LLM text can be wrong, but verified structure is guarded.",
                    "consensus_key": "FREQ_JSON:{\"999\":999}",
                    "support": ["unsupported hallucinated answer"],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "test",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "known_sources": [0],
                        "partials": {"0": {"999": 999}},
                        "merged_counts": {"999": 999},
                        "source_sizes": {"0": 1},
                        "n_agents": 4,
                    },
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_belief_merge",
            model_name="test-model",
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=WrongStructuredStateClient(),
    ).run()

    assert result.total_model_calls == 4
    assert result.total_deterministic_fallbacks == 0
    assert result.final_result.exact_match is True
    assert result.final_agent_states[0].belief_state.structured_state["known_sources"] == [
        0,
        1,
        2,
        3,
    ]


def test_protocol_runner_llm_full_merge_uses_llm_structured_state() -> None:
    adapter, global_task = _global_task()
    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_full_merge",
            llm_provider="fake",
            model_name="fake",
        ),
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.total_model_calls == 4
    assert result.total_deterministic_fallbacks == 0
    assert result.final_result.exact_match is True


def test_protocol_runner_llm_full_merge_does_not_recompute_answer_from_partials() -> None:
    adapter, global_task = _global_task()
    correct_partials = {
        "0": {"1": 1, "2": 1},
        "1": {"1": 1, "3": 1},
        "2": {"2": 1, "3": 1},
        "3": {"1": 1, "3": 1},
    }

    class WrongMergedCountsClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "The global counts are wrong on purpose.",
                    "consensus_key": "FREQ_JSON:{\"1\":1}",
                    "support": ["LLM produced merged_counts independently"],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "test",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "known_sources": [0, 1, 2, 3],
                        "partials": correct_partials,
                        "merged_counts": {"1": 1},
                        "source_sizes": {"0": 2, "1": 2, "2": 2, "3": 2},
                        "n_agents": 4,
                    },
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_full_merge",
            model_name="test-model",
            allow_deterministic_repair=False,
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=WrongMergedCountsClient(),
    ).run()

    assert result.total_deterministic_fallbacks == 0
    assert result.final_result.final_counts == {"1": 1}
    assert result.final_result.exact_match is False
    assert result.final_result.rmse > 0.0


def test_protocol_runner_llm_full_merge_accepts_compact_answer_without_partials() -> None:
    adapter, global_task = _global_task()

    class CompactWrongCountsClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "Compact answer without echoing transport partials.",
                    "consensus_key": "FREQ_JSON:{\"1\":1}",
                    "support": ["LLM merged counts directly"],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "test",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "merged_counts": {"1": 1},
                    },
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_full_merge",
            model_name="test-model",
            allow_deterministic_repair=False,
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=CompactWrongCountsClient(),
    ).run()

    assert result.total_deterministic_fallbacks == 0
    assert result.final_result.final_counts == {"1": 1}
    assert result.final_result.exact_match is False
    assert result.final_agent_states[0].belief_state.structured_state["known_sources"] == [
        0,
        1,
        2,
        3,
    ]


def test_protocol_runner_llm_full_merge_prompt_uses_answer_artifact_outbox() -> None:
    adapter, global_task = _global_task()

    class CapturePromptClient:
        def __init__(self) -> None:
            self.prompt = ""

        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            self.prompt = prompt
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "Merged from answer artifacts.",
                    "consensus_key": "FREQ_JSON:{\"1\":1}",
                    "support": ["artifact merge"],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "test",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "merged_counts": {"1": 1},
                    },
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    client = CapturePromptClient()
    ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="chain",
            n_agents=2,
            merge_mode="llm_full_merge",
            model_name="test-model",
            allow_deterministic_repair=False,
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=client,
    ).run()

    assert "cf-outbox-v1" in client.prompt
    assert '"message_type": "answer_artifact"' in client.prompt
    assert '"artifact"' in client.prompt
    assert '"answer"' in client.prompt
    assert '"provenance"' in client.prompt
    assert '"source_agent_ids"' in client.prompt
    assert '"consensus_key": "UNKNOWN"' in client.prompt
    assert "FREQ_JSON" not in client.prompt
    assert '"structured_payload"' not in client.prompt
    assert '"partials"' not in client.prompt
    assert '"source_sizes"' not in client.prompt


def test_protocol_runner_llm_full_merge_repairs_missing_counts_from_consensus_key() -> None:
    adapter, global_task = _global_task()

    class ConsensusKeyOnlyClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "Counts are carried in the consensus key.",
                    "consensus_key": "FREQ_JSON:{\"1\":1}",
                    "support": ["LLM supplied FREQ_JSON key"],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "test",
                    "structured_state": {"task_name": "count_frequency"},
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_full_merge",
            model_name="test-model",
            json_retry_attempts=0,
            allow_deterministic_repair=False,
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=ConsensusKeyOnlyClient(),
    ).run()

    assert result.total_retry_attempts == 0
    assert result.final_result.final_counts == {"1": 1}
    assert result.final_result.exact_match is False


def test_protocol_runner_llm_local_solve_initializes_agent_partials() -> None:
    adapter, global_task = _global_task()

    class WrongLocalCountClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "candidate",
                    "proposal": "Local LLM count.",
                    "consensus_key": "UNKNOWN",
                    "support": ["counted local shard"],
                    "uncertainty": "need neighbors",
                    "open_questions": ["share counts"],
                    "private_notes": "test",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "merged_counts": {"1": 1},
                    },
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="chain",
            n_agents=2,
            merge_mode="deterministic",
            init_mode="llm_local_solve",
            model_name="test-model",
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=WrongLocalCountClient(),
    ).run()

    assert result.total_model_calls == 2
    assert result.total_retry_attempts == 0
    assert result.final_result.final_counts == {"1": 2}
    assert result.final_result.exact_match is False


def test_protocol_runner_trace_records_llm_local_init(tmp_path) -> None:
    adapter, global_task = _global_task()

    class LocalCountClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "candidate",
                    "proposal": "Local LLM count.",
                    "consensus_key": "UNKNOWN",
                    "support": ["counted local shard"],
                    "uncertainty": "need neighbors",
                    "open_questions": ["share counts"],
                    "private_notes": "test",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "merged_counts": {"1": 1},
                    },
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="chain",
            n_agents=2,
            merge_mode="deterministic",
            init_mode="llm_local_solve",
            model_name="test-model",
            trace_enabled=True,
            trace_dir=str(tmp_path),
            run_id="llm-local-init-trace-test",
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=LocalCountClient(),
    ).run()

    assert result.trace_path is not None
    trace_lines = Path(result.trace_path).read_text(encoding="utf-8").splitlines()
    init_traces = [json.loads(line) for line in trace_lines if json.loads(line)["round_idx"] == -1]
    assert len(init_traces) == 2
    assert sorted(trace["agent_id"] for trace in init_traces) == [0, 1]
    assert all(trace["neighbors"] == [] for trace in init_traces)


def test_protocol_runner_llm_full_merge_json_repair_avoids_retry() -> None:
    adapter, global_task = _global_task()

    class MissingCommaClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = (
                '{"status":"final"'
                '"proposal":"JSON has a missing comma after status.",'
                '"consensus_key":"FREQ_JSON:{\\"1\\":1}",'
                '"support":["syntax repair should recover this"],'
                '"uncertainty":"",'
                '"open_questions":[],'
                '"private_notes":"test",'
                '"structured_state":{"task_name":"count_frequency","merged_counts":{"1":1}}}'
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="chain",
            n_agents=2,
            merge_mode="llm_full_merge",
            model_name="test-model",
            json_retry_attempts=0,
            allow_deterministic_repair=False,
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=MissingCommaClient(),
    ).run()

    assert result.total_model_calls == 1
    assert result.total_retry_attempts == 0
    assert result.total_deterministic_fallbacks == 0
    assert result.final_result.final_counts == {"1": 1}


def test_protocol_runner_llm_full_merge_can_fallback_to_deterministic_repair() -> None:
    adapter, global_task = _global_task()

    class InvalidStructuredStateClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "invalid",
                    "consensus_key": "UNKNOWN",
                    "support": [],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "",
                    "structured_state": {},
                }
            )
            return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_full_merge",
            model_name="test-model",
            json_retry_attempts=1,
            allow_deterministic_repair=True,
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=InvalidStructuredStateClient(),
    ).run()

    assert result.total_model_calls == 8
    assert result.total_retry_attempts == 4
    assert result.total_deterministic_fallbacks == 4
    assert result.final_result.exact_match is True


def test_protocol_runner_trace_records_each_retry_call_input_and_output(tmp_path) -> None:
    adapter, global_task = _global_task()

    class InvalidThenValidClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            self.calls += 1
            if self.calls % 2 == 1:
                return LLMResponse(
                    text="not json",
                    usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
                )
            text = json.dumps(
                {
                    "status": "final",
                    "proposal": "Recovered after retry.",
                    "consensus_key": "FREQ_JSON:{\"1\":3,\"2\":2,\"3\":3}",
                    "support": ["retry success"],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "",
                    "structured_state": {
                        "task_name": "count_frequency",
                        "known_sources": [0, 1, 2, 3],
                        "partials": {
                            "0": {"1": 1, "2": 1},
                            "1": {"1": 1, "3": 1},
                            "2": {"2": 1, "3": 1},
                            "3": {"1": 1, "3": 1},
                        },
                        "merged_counts": {"1": 3, "2": 2, "3": 3},
                        "source_sizes": {"0": 2, "1": 2, "2": 2, "3": 2},
                        "n_agents": 4,
                    },
                }
            )
            return LLMResponse(
                text=text,
                usage=LLMUsage(prompt_tokens=2, completion_tokens=2),
            )

    result = ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="mesh",
            n_agents=4,
            merge_mode="llm_full_merge",
            model_name="test-model",
            json_retry_attempts=1,
            allow_deterministic_repair=False,
            trace_enabled=True,
            trace_dir=str(tmp_path),
            run_id="protocol-trace-test",
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=InvalidThenValidClient(),
    ).run()

    assert result.trace_path is not None
    trace_lines = Path(result.trace_path).read_text(encoding="utf-8").splitlines()
    first_trace = json.loads(trace_lines[0])
    assert len(first_trace["llm_calls"]) == 2
    assert first_trace["llm_calls"][0]["raw_response"] == "not json"
    assert "Retry attempt: 1" in first_trace["llm_calls"][1]["prompt"]
    assert "Recovered after retry" in first_trace["llm_calls"][1]["raw_response"]


def test_protocol_runner_verbose_events_prints_messages_and_retry_failures(capsys) -> None:
    adapter, global_task = _global_task()

    class InvalidStructuredStateClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            return LLMResponse(
                text=json.dumps(
                    {
                        "status": "final",
                        "proposal": "invalid",
                        "consensus_key": "UNKNOWN",
                        "support": [],
                        "uncertainty": "",
                        "open_questions": [],
                        "private_notes": "",
                        "structured_state": {},
                    }
                ),
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

    ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="chain",
            n_agents=2,
            merge_mode="llm_full_merge",
            model_name="test-model",
            json_retry_attempts=1,
            allow_deterministic_repair=True,
            verbose_events=True,
            run_id="verbose-events-test",
        ),
        task_adapter=adapter,
        global_task=global_task,
        llm_client=InvalidStructuredStateClient(),
    ).run()

    output = capsys.readouterr().out
    assert "[message]" in output
    assert "0 -> 1" in output
    assert "[llm-call]" in output
    assert "[retry]" in output
    assert "[retry-failed]" in output
    assert "deterministic_repair=applied" in output


def test_protocol_runner_llm_full_merge_can_fail_without_deterministic_repair() -> None:
    adapter, global_task = _global_task()

    class InvalidStructuredStateClient:
        def complete(self, prompt: str, model_name: str, temperature: float | None = None):
            return LLMResponse(
                text=json.dumps(
                    {
                        "status": "final",
                        "proposal": "invalid",
                        "consensus_key": "UNKNOWN",
                        "support": [],
                        "uncertainty": "",
                        "open_questions": [],
                        "private_notes": "",
                        "structured_state": {},
                    }
                ),
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

    with pytest.raises(ValueError):
        ProtocolRunner(
            config=ProtocolRunnerConfig(
                topology_name="mesh",
                n_agents=4,
                merge_mode="llm_full_merge",
                model_name="test-model",
                json_retry_attempts=0,
                allow_deterministic_repair=False,
            ),
            task_adapter=adapter,
            global_task=global_task,
            llm_client=InvalidStructuredStateClient(),
        ).run()
