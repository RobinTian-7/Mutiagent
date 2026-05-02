from exp_graph.hierarchy import (
    Role,
    build_emperor_soldiers_plan,
    build_hierarchy_local_observations,
    build_static_hierarchy_plan,
)
from exp_graph.tasks import CountFrequencyTaskAdapter
from exp_graph.tasks.count_frequency import extract_cf_structured_state


def test_assignment_gives_emperor_empty_shard_and_role_tag() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 1, 3, 4, 5])
    plan = build_emperor_soldiers_plan(n_soldiers=3, array_length=6)

    observations = build_hierarchy_local_observations(
        plan=plan,
        task_adapter=adapter,
        global_task=global_task,
    )

    assert len(observations) == plan.n_total
    emperor_obs = observations[0]
    assert emperor_obs["role"] == Role.EMPEROR.value
    assert emperor_obs["array_shard"] == []
    assert emperor_obs["agent_id"] == 0
    assert emperor_obs["n_agents"] == plan.n_soldiers


def test_emperor_initial_belief_has_no_empty_source_partial() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 1, 3])
    plan = build_emperor_soldiers_plan(n_soldiers=2, array_length=4)
    observations = build_hierarchy_local_observations(
        plan=plan,
        task_adapter=adapter,
        global_task=global_task,
    )

    initial = adapter.initial_local_solve(observations[plan.emperor_id])
    structured = extract_cf_structured_state(initial["structured_state"])

    assert structured is not None
    assert structured["known_sources"] == []
    assert structured["partials"] == {}


def test_assignment_keeps_soldier_shards_disjoint_and_complete() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(12)))
    plan = build_emperor_soldiers_plan(n_soldiers=4, array_length=12)

    observations = build_hierarchy_local_observations(
        plan=plan,
        task_adapter=adapter,
        global_task=global_task,
    )
    soldier_observations = [observations[soldier_id] for soldier_id in plan.soldier_ids]

    seen_indices: list[int] = []
    for soldier_obs, plan_node in zip(soldier_observations, plan.soldier_nodes, strict=True):
        assert soldier_obs["role"] == Role.SOLDIER.value
        assert soldier_obs["agent_id"] == plan_node.agent_id
        assert soldier_obs["soldier_index"] == plan_node.soldier_index
        assert soldier_obs["n_agents"] == plan.n_soldiers
        start = soldier_obs["shard_start"]
        end = soldier_obs["shard_end_exclusive"]
        seen_indices.extend(range(start, end))

    assert sorted(seen_indices) == list(range(12))


def test_assignment_re_keys_partials_under_runner_agent_id() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[5, 5, 6, 6])
    plan = build_emperor_soldiers_plan(n_soldiers=2, array_length=4)

    observations = build_hierarchy_local_observations(
        plan=plan,
        task_adapter=adapter,
        global_task=global_task,
    )
    first_soldier = observations[plan.soldier_ids[0]]

    initial = adapter.initial_local_solve(first_soldier)

    assert initial["structured_state"]["partials"].keys() == {
        str(plan.soldier_ids[0])
    }


def test_three_layer_assignment_tags_minister_observations() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(8)))
    plan = build_static_hierarchy_plan([2, 4], array_length=8)

    observations = build_hierarchy_local_observations(
        plan=plan,
        task_adapter=adapter,
        global_task=global_task,
    )

    assert observations[0]["role"] == Role.EMPEROR.value
    for minister_id in (1, 2):
        minister_obs = observations[minister_id]
        assert minister_obs["role"] == Role.MINISTER.value
        assert minister_obs["array_shard"] == []
        assert minister_obs["n_agents"] == plan.n_soldiers
        assert minister_obs["hierarchy_layer"] == 1
        assert minister_obs["hierarchy_parent_id"] == 0
        children = minister_obs["hierarchy_children_ids"]
        assert all(plan.node(child).role == Role.SOLDIER for child in children)


def test_three_layer_soldier_observations_carry_runner_agent_ids() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(12)))
    plan = build_static_hierarchy_plan([2, 4], array_length=12)

    observations = build_hierarchy_local_observations(
        plan=plan,
        task_adapter=adapter,
        global_task=global_task,
    )
    seen_indices: list[int] = []

    for node in plan.soldier_nodes:
        observation = observations[node.agent_id]
        assert observation["role"] == Role.SOLDIER.value
        assert observation["agent_id"] == node.agent_id
        assert observation["soldier_index"] == node.soldier_index
        assert observation["n_agents"] == plan.n_soldiers
        seen_indices.extend(
            range(observation["shard_start"], observation["shard_end_exclusive"])
        )

    assert sorted(seen_indices) == list(range(12))
