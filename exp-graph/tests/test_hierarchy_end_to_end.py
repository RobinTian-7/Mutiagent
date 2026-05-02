from exp_graph.configs.runtime import ExperimentConfig
from exp_graph.hierarchy import (
    HierarchyTopology,
    LLMHierarchyPlanner,
    M3PlannerConfig,
    Role,
    build_emperor_soldiers_plan,
    build_static_hierarchy_plan,
)
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.runner.synchronous import SynchronousRunner
from exp_graph.tasks import CountFrequencyTaskAdapter


def _build_config(n_total: int, *, max_rounds: int = 4) -> ExperimentConfig:
    return ExperimentConfig(
        topology_name="hierarchy",
        n_agents=n_total,
        max_rounds=max_rounds,
        seed=0,
        model_name="fake-model",
        prompt_template_name="solver_v1",
        llm_provider="fake",
        consensus_threshold=0.8,
        final_accept_threshold=0.5,
        adjudication_margin=0.1,
        trace_enabled=False,
        save_prompts=False,
        retain_traces=False,
    )


def test_emperor_soldiers_recovers_exact_counts_with_fake_llm() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(
        array_size=200,
        seed=7,
        value_min=0,
        value_max=4,
    )
    n_soldiers = 4
    plan = build_emperor_soldiers_plan(
        n_soldiers=n_soldiers,
        array_length=int(global_task["array_length"]),
    )
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
    ).run()

    assert result.final_result.consensus_reached is True
    assert result.final_result.final_key == global_task["answer_key"]
    assert result.metrics.final_accuracy is True
    assert result.stop_reason == "runtime_consensus"


def test_emperor_belief_state_reaches_final_with_full_coverage() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 1, 3, 2, 1, 4, 5])
    plan = build_emperor_soldiers_plan(n_soldiers=4, array_length=8)
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
    ).run()
    emperor_state = result.final_agent_states[plan.emperor_id]

    assert emperor_state.belief_state.status.value == "final"
    assert emperor_state.belief_state.consensus_key == global_task["answer_key"]


def test_soldier_observations_carry_role_tags() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 3, 4])
    plan = build_emperor_soldiers_plan(n_soldiers=2, array_length=4)
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
    ).run()

    assert result.final_agent_states[0].local_observation["role"] == "emperor"
    for soldier_id in plan.soldier_ids:
        assert (
            result.final_agent_states[soldier_id].local_observation["role"]
            == "soldier"
        )


def test_three_layer_hierarchy_recovers_exact_counts() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(
        array_size=200,
        seed=11,
        value_min=0,
        value_max=4,
    )
    plan = build_static_hierarchy_plan(
        [2, 4],
        array_length=int(global_task["array_length"]),
    )
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total, max_rounds=8)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
    ).run()

    assert result.final_result.consensus_reached is True
    assert result.final_result.final_key == global_task["answer_key"]
    assert result.metrics.final_accuracy is True
    assert result.stop_reason == "runtime_consensus"


def test_three_layer_minister_belief_states_become_final() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(20)))
    plan = build_static_hierarchy_plan(
        [2, 4],
        array_length=20,
    )
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total, max_rounds=8)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
    ).run()

    minister_nodes = [node for node in plan.nodes if node.role == Role.MINISTER]
    for minister_node in minister_nodes:
        belief = result.final_agent_states[minister_node.agent_id].belief_state
        assert belief.status.value == "final"
        assert belief.consensus_key == global_task["answer_key"]


def test_four_layer_hierarchy_runs_to_consensus() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(64)))
    plan = build_static_hierarchy_plan(
        [2, 2, 2],
        array_length=64,
    )
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total, max_rounds=12)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
    ).run()

    assert result.final_result.consensus_reached is True
    assert result.final_result.final_key == global_task["answer_key"]


def test_llm_planner_drives_full_run_to_consensus() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(
        array_size=400,
        seed=23,
        value_min=0,
        value_max=4,
    )
    planner = LLMHierarchyPlanner(
        config=M3PlannerConfig(
            max_depth=4,
            max_n_agents=32,
            max_fanout_per_layer=8,
            fallback_fanout_schedule=[4],
        ),
        llm_client=FakeLLMClient(),
    )

    plan_result = planner.plan(
        task_description={
            "task": "count_frequency",
            "array_length": int(global_task["array_length"]),
            "value_min": int(global_task["value_min"]),
            "value_max": int(global_task["value_max"]),
        }
    )

    assert plan_result.used_llm is True
    assert plan_result.fallback_used is False
    assert plan_result.dispatch is not None
    plan = plan_result.plan
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total, max_rounds=12)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
        hierarchy_dispatch=plan_result.dispatch,
    ).run()

    assert result.final_result.consensus_reached is True
    assert result.final_result.final_key == global_task["answer_key"]
    assert result.metrics.final_accuracy is True

    soldier_id = plan.soldier_ids[0]
    soldier_obs = result.final_agent_states[soldier_id].local_observation
    assignment = soldier_obs.get("assignment")
    assert isinstance(assignment, dict)
    assert assignment.get("instruction")
    assert "shard_indices" in assignment


def test_recursive_dispatch_drives_run_to_consensus_and_logs_each_layer() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(
        array_size=5000,
        seed=29,
        value_min=0,
        value_max=4,
    )
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
        task_description={
            "task": "count_frequency",
            "array_length": int(global_task["array_length"]),
            "value_min": int(global_task["value_min"]),
            "value_max": int(global_task["value_max"]),
        }
    )

    assert plan_result.recursive_dispatch_used is True
    assert any(
        call.role == "minister" and call.used_llm
        for call in plan_result.subordinate_calls
    )

    plan = plan_result.plan
    topology = HierarchyTopology(plan)
    config = _build_config(n_total=plan.n_total, max_rounds=12)

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
        hierarchy_dispatch=plan_result.dispatch,
    ).run()

    assert result.final_result.consensus_reached is True
    assert result.final_result.final_key == global_task["answer_key"]
    assert result.metrics.final_accuracy is True

    soldier_id = plan.soldier_ids[0]
    soldier_obs = result.final_agent_states[soldier_id].local_observation
    assignment = soldier_obs.get("assignment")
    assert isinstance(assignment, dict)
    assert assignment.get("source") in {"llm_recursive", "recursive_fallback"}


def test_three_layer_takes_more_rounds_than_two_layer() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(40)))

    flat_plan = build_static_hierarchy_plan([8], array_length=40)
    flat_result = SynchronousRunner(
        config=_build_config(n_total=flat_plan.n_total, max_rounds=8),
        task_adapter=adapter,
        global_task=global_task,
        topology=HierarchyTopology(flat_plan),
        hierarchy_plan=flat_plan,
    ).run()

    deep_plan = build_static_hierarchy_plan([2, 4], array_length=40)
    deep_result = SynchronousRunner(
        config=_build_config(n_total=deep_plan.n_total, max_rounds=8),
        task_adapter=adapter,
        global_task=global_task,
        topology=HierarchyTopology(deep_plan),
        hierarchy_plan=deep_plan,
    ).run()

    assert flat_result.metrics.rounds_to_consensus is not None
    assert deep_result.metrics.rounds_to_consensus is not None
    assert (
        deep_result.metrics.rounds_to_consensus
        > flat_result.metrics.rounds_to_consensus
    ), (
        "Three-layer hierarchy should take more rounds to broadcast than two-"
        "layer star, but observed flat="
        f"{flat_result.metrics.rounds_to_consensus} vs deep="
        f"{deep_result.metrics.rounds_to_consensus}"
    )
