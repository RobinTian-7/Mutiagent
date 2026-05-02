from exp_graph.hierarchy import (
    build_static_dispatch_tree,
    build_static_hierarchy_plan,
    parse_llm_dispatch,
)


def test_static_dispatch_assigns_each_soldier_a_disjoint_shard() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)
    dispatch = build_static_dispatch_tree(plan, array_length=8)

    soldier_shards = []
    for soldier in plan.soldier_nodes:
        entry = dispatch.for_agent(soldier.agent_id)
        assert entry is not None
        assert entry.shard_indices is not None
        soldier_shards.append(entry.shard_indices)

    cursor = 0
    for start, end in soldier_shards:
        assert start == cursor
        cursor = end
    assert cursor == 8


def test_static_dispatch_aggregated_slices_match_subtree() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=20)
    dispatch = build_static_dispatch_tree(plan, array_length=20)

    minister_1 = dispatch.for_agent(1)
    minister_2 = dispatch.for_agent(2)
    emperor = dispatch.for_agent(0)

    assert minister_1 is not None and minister_1.aggregated_slice is not None
    assert minister_2 is not None and minister_2.aggregated_slice is not None
    assert emperor is not None and emperor.aggregated_slice is not None
    assert minister_1.aggregated_slice == (0, 12)
    assert minister_2.aggregated_slice == (12, 20)
    assert emperor.aggregated_slice == (0, 20)


def test_static_dispatch_aggregated_slices_split_evenly_when_divisible() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=16)
    dispatch = build_static_dispatch_tree(plan, array_length=16)

    assert dispatch.for_agent(1).aggregated_slice == (0, 8)
    assert dispatch.for_agent(2).aggregated_slice == (8, 16)
    assert dispatch.for_agent(0).aggregated_slice == (0, 16)


def test_static_dispatch_instructions_mention_role() -> None:
    plan = build_static_hierarchy_plan([4], array_length=8)
    dispatch = build_static_dispatch_tree(plan, array_length=8)

    assert "publish" in dispatch.for_agent(0).instruction.lower()
    for soldier in plan.soldier_nodes:
        instr = dispatch.for_agent(soldier.agent_id).instruction
        assert "count" in instr.lower()


def test_parse_llm_dispatch_overrides_only_specified_agents() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)

    raw = {
        "agent_3": {
            "instruction": "Carefully count array[0:1) for value 5",
            "shard": [0, 1],
        },
        "agent_0": "Aggregate everything yourself.",
    }

    dispatch = parse_llm_dispatch(plan, raw, array_length=8, rationale="test")
    assert dispatch is not None
    assert dispatch.source == "llm"

    soldier_3 = dispatch.for_agent(3)
    assert soldier_3.instruction == "Carefully count array[0:1) for value 5"
    assert soldier_3.source == "llm"

    emperor = dispatch.for_agent(0)
    assert emperor.instruction == "Aggregate everything yourself."

    soldier_4 = dispatch.for_agent(4)
    assert soldier_4.source == "static"


def test_parse_llm_dispatch_returns_none_for_empty_or_invalid_input() -> None:
    plan = build_static_hierarchy_plan([2])
    assert parse_llm_dispatch(plan, None, array_length=2) is None
    assert parse_llm_dispatch(plan, "not a dict", array_length=2) is None
    assert parse_llm_dispatch(plan, {"unknown_agent": {}}, array_length=2) is None
