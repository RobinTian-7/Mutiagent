from exp_graph.hierarchy import (
    EMPEROR_RETRY_PROMPT_MARKER,
    LLMHierarchyPlanner,
    M3PlannerConfig,
    build_emperor_planning_prompt,
    validate_fanout,
)
from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.llm.fake import FakeLLMClient


class StubLLMClient:
    """Returns a queued sequence of LLM responses for testing."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def complete(self, prompt: str, model_name: str, temperature: float | None = None):
        self.calls.append(prompt)
        text = self._responses.pop(0) if self._responses else ""
        return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1))


def _build_planner(
    llm_client,
    *,
    max_depth: int = 4,
    max_n_agents: int = 64,
    max_fanout_per_layer: int = 32,
    fallback_fanout_schedule: list[int] | None = None,
    plan_retry_attempts: int = 0,
    include_constraint_examples: bool = True,
) -> LLMHierarchyPlanner:
    config = M3PlannerConfig(
        max_depth=max_depth,
        max_n_agents=max_n_agents,
        max_fanout_per_layer=max_fanout_per_layer,
        fallback_fanout_schedule=fallback_fanout_schedule or [4],
        plan_retry_attempts=plan_retry_attempts,
        include_constraint_examples=include_constraint_examples,
    )
    return LLMHierarchyPlanner(config=config, llm_client=llm_client)


def test_validate_fanout_rejects_excess_depth() -> None:
    config = M3PlannerConfig(max_depth=3, max_n_agents=64, max_fanout_per_layer=32)
    assert validate_fanout([2, 2, 2], config=config) != ""
    assert validate_fanout([2, 2], config=config) == ""


def test_validate_fanout_rejects_excess_total_agents() -> None:
    config = M3PlannerConfig(max_depth=4, max_n_agents=10, max_fanout_per_layer=32)
    assert validate_fanout([8, 8], config=config) != ""


def test_validate_fanout_rejects_excess_per_layer_fanout() -> None:
    config = M3PlannerConfig(
        max_depth=4, max_n_agents=64, max_fanout_per_layer=4
    )
    assert validate_fanout([8], config=config) != ""


def test_validate_fanout_rejects_empty_or_zero_values() -> None:
    config = M3PlannerConfig(max_depth=4, max_n_agents=64, max_fanout_per_layer=32)
    assert validate_fanout([], config=config) != ""
    assert validate_fanout([0, 4], config=config) != ""


def test_planner_accepts_valid_emperor_response() -> None:
    response = (
        '{"fanout_schedule": [2, 4], "split_strategy": "equal_shard_by_index", '
        '"rationale": "balanced shape", "dispatch": null}'
    )
    planner = _build_planner(StubLLMClient([response]))

    result = planner.plan(task_description={"task": "count_frequency", "array_length": 1024})

    assert result.used_llm is True
    assert result.fallback_used is False
    assert result.chosen_fanout_schedule == [2, 4]
    assert result.plan.fanout_schedule == [2, 4]
    assert result.plan.metadata["planner"] == "llm"
    assert result.plan.metadata["llm_rationale"] == "balanced shape"
    assert result.dispatch.source == "static"
    for entry in result.dispatch.entries.values():
        assert entry.instruction


def test_planner_falls_back_when_response_is_invalid_json() -> None:
    planner = _build_planner(
        StubLLMClient(["not valid JSON"]),
        fallback_fanout_schedule=[4],
    )

    result = planner.plan(task_description={"task": "count_frequency", "array_length": 16})

    assert result.used_llm is False
    assert result.fallback_used is True
    assert result.fallback_reason
    assert result.plan.fanout_schedule == [4]
    assert result.plan.metadata["planner"] == "static_fallback"


def test_planner_falls_back_when_response_violates_constraints() -> None:
    response = (
        '{"fanout_schedule": [16, 16, 16], '
        '"split_strategy": "equal_shard_by_index", "rationale": "too big"}'
    )
    planner = _build_planner(
        StubLLMClient([response]),
        max_depth=3,
        max_n_agents=20,
        fallback_fanout_schedule=[4],
    )

    result = planner.plan(task_description={"task": "count_frequency", "array_length": 16})

    assert result.fallback_used is True
    assert "exceed" in result.fallback_reason.lower() or "above" in result.fallback_reason.lower()
    assert result.plan.fanout_schedule == [4]


def test_planner_uses_llm_dispatch_when_provided() -> None:
    response = (
        '{"fanout_schedule": [2], "split_strategy": "equal_shard_by_index", '
        '"rationale": "small", "dispatch": {"agent_1": '
        '{"instruction": "Tiny shard"}}}'
    )
    planner = _build_planner(StubLLMClient([response]))

    result = planner.plan(task_description={"task": "count_frequency", "array_length": 4})

    assert result.dispatch.source == "llm"
    assert result.dispatch.for_agent(1).instruction == "Tiny shard"


def test_fake_llm_client_produces_planner_response_for_emperor_marker() -> None:
    planner = _build_planner(FakeLLMClient(), max_depth=4, max_n_agents=64)

    result = planner.plan(task_description={"task": "count_frequency", "array_length": 5000})

    assert result.used_llm is True
    assert result.fallback_used is False
    assert result.chosen_fanout_schedule
    assert result.plan.metadata["llm_rationale"]


def test_planning_prompt_includes_worked_examples_by_default() -> None:
    config = M3PlannerConfig(max_depth=4, max_n_agents=64, max_fanout_per_layer=8)
    prompt = build_emperor_planning_prompt(
        config=config, task_description={"task": "count_frequency", "array_length": 1000}
    )

    assert "WORKED EXAMPLES" in prompt
    assert "fanout=" in prompt
    assert "[OK]" in prompt or "[REJECTED]" in prompt


def test_planning_prompt_skips_examples_when_disabled() -> None:
    config = M3PlannerConfig(
        max_depth=4,
        max_n_agents=64,
        max_fanout_per_layer=8,
        include_constraint_examples=False,
    )
    prompt = build_emperor_planning_prompt(
        config=config, task_description={"task": "count_frequency", "array_length": 1000}
    )

    assert "WORKED EXAMPLES" not in prompt


def test_planner_retry_recovers_after_first_proposal_rejected() -> None:
    invalid_first = (
        '{"fanout_schedule": [16, 16], "split_strategy": "equal_shard_by_index", '
        '"rationale": "too big"}'
    )
    valid_second = (
        '{"fanout_schedule": [4, 4], "split_strategy": "equal_shard_by_index", '
        '"rationale": "fits budget"}'
    )
    client = StubLLMClient([invalid_first, valid_second])
    planner = _build_planner(
        client,
        max_depth=4,
        max_n_agents=32,
        max_fanout_per_layer=8,
        plan_retry_attempts=2,
    )

    result = planner.plan(
        task_description={"task": "count_frequency", "array_length": 1000}
    )

    assert result.used_llm is True
    assert result.fallback_used is False
    assert result.plan.fanout_schedule == [4, 4]
    assert result.planner_retry_attempts == 1
    assert len(result.planner_retry_records) == 2
    assert result.planner_retry_records[0].accepted is False
    assert result.planner_retry_records[1].accepted is True
    assert EMPEROR_RETRY_PROMPT_MARKER in client.calls[1]
    assert "[16, 16]" in client.calls[1] or "16, 16" in client.calls[1]
    # Accumulated usage should account for both calls.
    assert result.usage.model_calls == 2
    assert result.plan.metadata["planner_retry_attempts"] == 1


def test_planner_falls_back_after_retries_exhausted() -> None:
    bad_response = (
        '{"fanout_schedule": [32, 32], "split_strategy": "equal_shard_by_index", '
        '"rationale": "still too big"}'
    )
    client = StubLLMClient([bad_response, bad_response, bad_response])
    planner = _build_planner(
        client,
        max_depth=4,
        max_n_agents=20,
        max_fanout_per_layer=32,
        plan_retry_attempts=2,
        fallback_fanout_schedule=[4],
    )

    result = planner.plan(
        task_description={"task": "count_frequency", "array_length": 100}
    )

    assert result.used_llm is False
    assert result.fallback_used is True
    assert result.plan.fanout_schedule == [4]
    assert result.planner_retry_attempts == 2
    assert len(result.planner_retry_records) == 3
    assert all(record.accepted is False for record in result.planner_retry_records)
    assert result.usage.model_calls == 3


def test_planner_does_not_retry_when_attempts_zero() -> None:
    bad_response = (
        '{"fanout_schedule": [32, 32], "rationale": "out of budget"}'
    )
    client = StubLLMClient([bad_response, bad_response])
    planner = _build_planner(
        client,
        max_depth=4,
        max_n_agents=10,
        max_fanout_per_layer=32,
        plan_retry_attempts=0,
        fallback_fanout_schedule=[2],
    )

    result = planner.plan(
        task_description={"task": "count_frequency", "array_length": 100}
    )

    assert result.fallback_used is True
    assert result.planner_retry_attempts == 0
    assert len(result.planner_retry_records) == 1
    assert len(client.calls) == 1
