import masbench  # noqa: F401  (bootstraps exp_graph path)
from masbench.core.instance import BenchmarkInstance
from masbench.core.task_bridge import BenchmarkTaskAdapter, canonical_answer


def _instance():
    return BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[1, 5, 3], [9, 2]], ground_truth=9,
        task_prompt="Find the global maximum. You are agent {agent_id}.",
        meta={"output_type": "distributed"},
    )


def test_canonical_answer_scalar_and_json():
    assert canonical_answer(9) == "9"
    assert canonical_answer("9") == "9"           # numeric string normalizes
    assert canonical_answer("  9 ") == "9"
    assert canonical_answer([3, 1, 2]) == "[3,1,2]"
    assert canonical_answer("[3, 1, 2]") == "[3,1,2]"
    assert canonical_answer({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_answer(None) == "UNKNOWN"
    assert canonical_answer("unknown") == "UNKNOWN"
    assert canonical_answer("hello world") == "hello world"  # non-JSON string kept


def test_build_global_task_and_adjudication_hides_truth():
    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    assert gt["answer_key"] == "9"
    assert gt["n_agents"] == 2
    # Ground truth and raw shards must not leak into adjudication context.
    context = adapter.format_adjudication_context(gt)
    assert "answer_key" not in context
    assert "shards" not in context


def test_split_gives_each_agent_only_its_shard():
    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, 2)
    assert len(obs) == 2
    assert obs[0]["input_shard"] == [1, 5, 3]
    assert obs[1]["input_shard"] == [9, 2]
    assert obs[0]["agent_id"] == 0


def test_evaluate_final_answer_matches_canonical():
    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    assert adapter.evaluate_final_answer(gt, "9") is True
    assert adapter.evaluate_final_answer(gt, "7") is False
    assert adapter.evaluate_final_answer(gt, None) is False


def test_initial_local_solve_is_valid_belief_dict():
    from exp_graph.agents.schemas import BeliefState

    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, 2)
    raw = adapter.initial_local_solve(obs[0])
    belief = BeliefState(**raw)  # must construct without error
    assert belief.consensus_key == "UNKNOWN"


def test_canonical_answer_booleans():
    assert canonical_answer(True) == "true"
    assert canonical_answer("True") == "true"
    assert canonical_answer("false") == "false"


def test_split_rejects_wrong_agent_count():
    import pytest

    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    with pytest.raises(ValueError, match="cannot be re-split"):
        adapter.split_into_local_observations(gt, 3)


def test_prompt_does_not_double_embed_shard():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[1, 5, 3], [9, 2]], ground_truth=9,
        task_prompt="Max. You are agent {agent_id} holding {input_shard}.",
    )
    adapter = BenchmarkTaskAdapter(inst)
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, 2)
    prompt = adapter.format_task_prompt_context(gt, obs[0])
    assert prompt.count("[1, 5, 3]") == 1


def test_evaluate_handles_python_bool_strings():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-03", case_name="Distributed Vote",
        n_agents=2, shards=[[1], [0]], ground_truth=True,
    )
    adapter = BenchmarkTaskAdapter(inst)
    gt = adapter.build_global_task()
    assert adapter.evaluate_final_answer(gt, "True") is True
    assert adapter.evaluate_final_answer(gt, "true") is True
    assert adapter.evaluate_final_answer(gt, "False") is False
