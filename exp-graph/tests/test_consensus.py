from exp_graph.aggregator.runtime_consensus import count_keys, detect_runtime_consensus


def test_runtime_consensus_detection_reaches_on_non_unknown_top_key() -> None:
    key_counts = count_keys(["FOUND:2", "FOUND:2", "FOUND:2", "UNKNOWN"])

    result = detect_runtime_consensus(
        key_counts=key_counts,
        num_agents=4,
        threshold=0.75,
    )

    assert result.consensus_reached is True
    assert result.top_key == "FOUND:2"
    assert result.top_ratio == 0.75


def test_runtime_consensus_unknown_and_ties_do_not_reach() -> None:
    unknown_result = detect_runtime_consensus(
        key_counts=count_keys(["UNKNOWN", "UNKNOWN", "UNKNOWN"]),
        num_agents=3,
        threshold=0.8,
    )
    tie_result = detect_runtime_consensus(
        key_counts=count_keys(["FOUND:1", "FOUND:2"]),
        num_agents=2,
        threshold=0.5,
    )

    assert unknown_result.consensus_reached is False
    assert unknown_result.top_key == "UNKNOWN"
    assert tie_result.consensus_reached is False
    assert tie_result.top_key is None
