from exp_graph.tasks import ArraySearchTaskAdapter


def test_array_shard_splitting_correctness() -> None:
    adapter = ArraySearchTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(10)), target=7)

    observations = adapter.split_into_local_observations(global_task, n_agents=3)

    assert [obs["array_shard"] for obs in observations] == [
        [0, 1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]
    assert [obs["global_offset"] for obs in observations] == [0, 4, 7]


def test_initial_local_solve_pipeline_found_and_unknown() -> None:
    adapter = ArraySearchTaskAdapter()
    global_task = adapter.build_global_task(array=[5, 7, 9, 11], target=9)
    observations = adapter.split_into_local_observations(global_task, n_agents=2)

    left = adapter.initial_local_solve(observations[0])
    right = adapter.initial_local_solve(observations[1])

    assert left["consensus_key"] == "UNKNOWN"
    assert left["status"] == "unknown"
    assert right["consensus_key"] == "FOUND:2"
    assert right["status"] == "final"


def test_array_search_consensus_key_normalization() -> None:
    adapter = ArraySearchTaskAdapter()

    assert adapter.normalize_consensus_key("found:003") == "FOUND:3"
    assert adapter.normalize_consensus_key("Target at global index 12") == "FOUND:12"
    assert adapter.normalize_consensus_key("not found") == "NOT_FOUND"
    assert adapter.normalize_consensus_key(None) == "UNKNOWN"
