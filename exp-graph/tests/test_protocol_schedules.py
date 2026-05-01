from exp_graph.protocols import build_protocol_schedule


def test_chain_schedule_is_serial_forwarding() -> None:
    schedule = build_protocol_schedule("chain", n_agents=4)

    assert [step.transmissions for step in schedule] == [
        [(0, 1)],
        [(1, 2)],
        [(2, 3)],
    ]


def test_tree_schedule_is_binary_reduction_to_last_agent() -> None:
    schedule = build_protocol_schedule("tree", n_agents=8)

    assert [step.transmissions for step in schedule] == [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(3, 7)],
    ]


def test_tree_schedule_handles_non_power_of_two_agents() -> None:
    schedule = build_protocol_schedule("tree", n_agents=6)

    assert [step.transmissions for step in schedule] == [
        [(0, 1), (2, 3), (4, 5)],
        [(1, 3)],
        [(3, 5)],
    ]


def test_star_schedule_gathers_to_center_by_default() -> None:
    schedule = build_protocol_schedule("star", n_agents=4, star_center=0)

    assert len(schedule) == 1
    assert schedule[0].transmissions == [(1, 0), (2, 0), (3, 0)]


def test_star_schedule_can_broadcast_after_gather() -> None:
    schedule = build_protocol_schedule(
        "star",
        n_agents=4,
        star_center=0,
        include_star_broadcast=True,
    )

    assert schedule[0].transmissions == [(1, 0), (2, 0), (3, 0)]
    assert schedule[1].transmissions == [(0, 1), (0, 2), (0, 3)]


def test_mesh_schedule_is_one_all_to_all_step() -> None:
    schedule = build_protocol_schedule("mesh", n_agents=4)

    assert len(schedule) == 1
    assert len(schedule[0].transmissions) == 12
    assert (0, 1) in schedule[0].transmissions
    assert (1, 0) in schedule[0].transmissions


def test_dag_mesh_schedule_sweeps_destinations_in_topological_order() -> None:
    schedule = build_protocol_schedule("dag_mesh", n_agents=4)

    assert [step.transmissions for step in schedule] == [
        [(0, 1)],
        [(0, 2), (1, 2)],
        [(0, 3), (1, 3), (2, 3)],
    ]


def test_two_stage_layer_schedule_uses_hidden_aggregation_layer() -> None:
    schedule = build_protocol_schedule("two_stage_layer", n_agents=8)

    assert len(schedule) == 2
    assert schedule[0].transmissions == [
        (src, dst)
        for src in [0, 1, 2, 3]
        for dst in [4, 5, 6]
    ]
    assert schedule[1].transmissions == [(4, 7), (5, 7), (6, 7)]


def test_two_stage_layer_schedule_degrades_to_direct_edge_for_two_agents() -> None:
    schedule = build_protocol_schedule("two_stage_layer", n_agents=2)

    assert [step.transmissions for step in schedule] == [[(0, 1)]]


def test_balanced_log_layer_schedule_balances_non_sink_agents() -> None:
    schedule = build_protocol_schedule("balanced_log_layer", n_agents=8)

    assert [step.transmissions for step in schedule] == [
        [(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)],
        [(3, 5), (3, 6), (4, 5), (4, 6)],
        [(5, 7), (6, 7)],
    ]


def test_balance_log_alias_matches_balanced_log_layer() -> None:
    assert build_protocol_schedule(
        "balance_log",
        n_agents=8,
    ) == build_protocol_schedule("balanced_log_layer", n_agents=8)


def test_static_exponential_repeats_fixed_edges_for_log_steps() -> None:
    schedule = build_protocol_schedule("static_exponential", n_agents=8)

    assert len(schedule) == 3
    assert schedule[0].transmissions == schedule[1].transmissions
    assert schedule[1].transmissions == schedule[2].transmissions
    assert (0, 1) in schedule[0].transmissions
    assert (0, 2) in schedule[0].transmissions
    assert (0, 4) in schedule[0].transmissions


def test_one_peer_exponential_uses_global_distance_phases() -> None:
    schedule = build_protocol_schedule("one_peer_exponential", n_agents=8)

    assert len(schedule) == 3
    assert schedule[0].transmissions[0] == (0, 1)
    assert schedule[1].transmissions[0] == (0, 2)
    assert schedule[2].transmissions[0] == (0, 4)
