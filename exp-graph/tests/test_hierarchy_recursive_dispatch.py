import json

from exp_graph.hierarchy import (
    LLMHierarchyPlanner,
    M3PlannerConfig,
    build_static_hierarchy_plan,
    mechanical_equal_split_children,
    parse_subordinate_dispatch,
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


def test_mechanical_equal_split_children_partitions_parent_slice() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=20)
    minister_1 = plan.node(1)
    children = [plan.node(child_id) for child_id in minister_1.children_ids]

    decision = mechanical_equal_split_children(
        parent_node=minister_1,
        parent_slice=(0, 12),
        children_nodes=children,
    )

    soldier_shards = [
        decision.children[child.agent_id].shard_indices for child in children
    ]
    assert soldier_shards == [(0, 3), (3, 6), (6, 9), (9, 12)]
    assert decision.source == "static"


def test_parse_subordinate_dispatch_accepts_valid_partition() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)
    minister_1 = plan.node(1)
    children = [plan.node(child_id) for child_id in minister_1.children_ids]

    payload = {
        "rationale": "even split",
        "children": {
            "agent_3": {"shard": [0, 1], "instruction": "count 0:1"},
            "agent_4": {"shard": [1, 2], "instruction": "count 1:2"},
            "agent_5": {"shard": [2, 3], "instruction": "count 2:3"},
            "agent_6": {"shard": [3, 4], "instruction": "count 3:4"},
        },
    }
    decision = parse_subordinate_dispatch(
        parent_node=minister_1,
        parent_slice=(0, 4),
        children_nodes=children,
        raw_payload=payload,
        rationale="even split",
    )

    assert decision is not None
    assert decision.source == "llm"
    assert {child_id for child_id in decision.children} == {3, 4, 5, 6}
    assert decision.children[3].instruction == "count 0:1"


def test_parse_subordinate_dispatch_rejects_overlapping_shards() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)
    minister_1 = plan.node(1)
    children = [plan.node(child_id) for child_id in minister_1.children_ids]

    payload = {
        "children": {
            "agent_3": {"shard": [0, 2]},
            "agent_4": {"shard": [1, 3]},
            "agent_5": {"shard": [3, 4]},
            "agent_6": {"shard": [4, 4]},
        },
    }

    decision = parse_subordinate_dispatch(
        parent_node=minister_1,
        parent_slice=(0, 4),
        children_nodes=children,
        raw_payload=payload,
    )
    assert decision is None


def test_parse_subordinate_dispatch_rejects_missing_children() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)
    minister_1 = plan.node(1)
    children = [plan.node(child_id) for child_id in minister_1.children_ids]

    payload = {
        "children": {
            "agent_3": {"shard": [0, 1]},
            "agent_4": {"shard": [1, 4]},
        },
    }

    decision = parse_subordinate_dispatch(
        parent_node=minister_1,
        parent_slice=(0, 4),
        children_nodes=children,
        raw_payload=payload,
    )
    assert decision is None


def test_recursive_planner_records_call_per_minister() -> None:
    planner = LLMHierarchyPlanner(
        config=M3PlannerConfig(
            max_depth=4,
            max_n_agents=64,
            max_fanout_per_layer=8,
            recursive_dispatch=True,
            fallback_fanout_schedule=[2, 4],
        ),
        llm_client=FakeLLMClient(),
    )

    plan_result = planner.plan(
        task_description={"task": "count_frequency", "array_length": 5000}
    )

    assert plan_result.recursive_dispatch_used is True
    assert plan_result.dispatch.source == "llm_recursive"
    minister_calls = [
        call for call in plan_result.subordinate_calls if call.role == "minister"
    ]
    assert len(minister_calls) == plan_result.plan.layers[1]
    for call in minister_calls:
        assert call.used_llm is True
        assert call.fallback_used is False
        assert call.usage.prompt_tokens > 0


def test_recursive_planner_per_node_fallback_when_minister_invalid() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)
    minister_1 = plan.node(1)
    children_1 = [plan.node(c) for c in minister_1.children_ids]
    minister_2 = plan.node(2)
    children_2 = [plan.node(c) for c in minister_2.children_ids]

    valid_payload_2 = {
        "rationale": "even",
        "children": {
            f"agent_{children_2[i].agent_id}": {
                "shard": [4 + i, 5 + i],
                "instruction": "ok",
            }
            for i in range(4)
        },
    }
    invalid_payload_1 = "garbled not json"

    responses = [
        json.dumps(
            {
                "fanout_schedule": [2, 4],
                "split_strategy": "equal_shard_by_index",
                "rationale": "fixed",
                "dispatch": None,
            }
        ),
        invalid_payload_1,
        json.dumps(valid_payload_2),
    ]

    planner = LLMHierarchyPlanner(
        config=M3PlannerConfig(
            max_depth=4,
            max_n_agents=64,
            max_fanout_per_layer=8,
            recursive_dispatch=True,
            fallback_fanout_schedule=[2, 4],
        ),
        llm_client=StubLLMClient(responses),
    )

    plan_result = planner.plan(
        task_description={"task": "count_frequency", "array_length": 8}
    )

    minister_records = {
        call.agent_id: call
        for call in plan_result.subordinate_calls
        if call.role == "minister"
    }

    assert minister_records[minister_1.agent_id].fallback_used is True
    assert minister_records[minister_2.agent_id].used_llm is True

    soldier_3 = plan_result.dispatch.for_agent(children_1[0].agent_id)
    soldier_7 = plan_result.dispatch.for_agent(children_2[0].agent_id)
    assert soldier_3.source == "recursive_fallback"
    assert soldier_7.source == "llm_recursive"
    assert soldier_3.shard_indices == (0, 1)
    assert soldier_7.shard_indices == (4, 5)
