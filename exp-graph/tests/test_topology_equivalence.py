from exp_graph.mas.topology_equivalence import fingerprint_temporal_edges


def _hash(steps, selected_primary=None, n_agents=8):
    return fingerprint_temporal_edges(
        n_agents=n_agents,
        steps=steps,
        selected_primary=selected_primary,
    ).topology_equivalence_hash


def test_binary_tree_roots_are_equivalent_under_agent_relabeling() -> None:
    sink_7 = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(3, 7)],
    ]
    sink_3 = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(7, 3)],
    ]
    root_0 = [
        [(1, 0), (3, 2), (5, 4), (7, 6)],
        [(2, 0), (6, 4)],
        [(4, 0)],
    ]

    assert _hash(sink_7, selected_primary=7) == _hash(sink_3, selected_primary=3)
    assert _hash(sink_7, selected_primary=7) == _hash(root_0, selected_primary=0)


def test_agent_permutation_and_same_step_edge_order_do_not_change_hash() -> None:
    original = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(3, 7)],
    ]
    permuted = [
        [(4, 6), (0, 2), (5, 7), (1, 3)],
        [(6, 2), (7, 3)],
        [(2, 3)],
    ]

    assert _hash(original, selected_primary=7) == _hash(permuted, selected_primary=3)


def test_shifted_binary_tree_is_equivalent_to_standard_binary_tree() -> None:
    standard = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(3, 7)],
    ]
    shifted = [
        [(0, 1), (2, 4), (3, 5), (6, 7)],
        [(1, 4), (5, 7)],
        [(4, 7)],
    ]

    assert _hash(standard, selected_primary=7) == _hash(shifted, selected_primary=7)


def test_extra_edges_and_temporal_shape_changes_are_not_equivalent() -> None:
    tree = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(3, 7)],
    ]
    audit_tree = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 3), (5, 7)],
        [(3, 7), (3, 0)],
    ]
    two_step_star = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(1, 7), (3, 7), (5, 7)],
    ]

    assert _hash(tree, selected_primary=7) != _hash(audit_tree, selected_primary=7)
    assert _hash(tree, selected_primary=7) != _hash(two_step_star, selected_primary=7)


def test_step_order_is_part_of_equivalence() -> None:
    forward = [[(0, 1)], [(1, 2)]]
    reordered = [[(1, 2)], [(0, 1)]]

    assert _hash(forward, selected_primary=2, n_agents=3) != _hash(
        reordered,
        selected_primary=2,
        n_agents=3,
    )


def test_symmetric_ties_are_stable() -> None:
    symmetric = [
        [(0, 1), (1, 0), (2, 3), (3, 2)],
        [(0, 2), (1, 3)],
    ]

    hashes = {_hash(symmetric, selected_primary=3, n_agents=4) for _ in range(20)}

    assert len(hashes) == 1
