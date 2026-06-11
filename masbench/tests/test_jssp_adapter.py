"""Tests for JSSPBenchAdapter: OR-library *.jssp files -> BenchmarkInstance."""

from __future__ import annotations

from pathlib import Path

import pytest

from masbench.adapters.jssp_bench import JSSPBenchAdapter

DATA = Path(__file__).parent / "data" / "jssp"

FT06_JOBS = [
    [[2, 1], [0, 3], [1, 6], [3, 7], [5, 3], [4, 6]],
    [[1, 8], [2, 5], [4, 10], [5, 10], [0, 10], [3, 4]],
    [[2, 5], [3, 4], [5, 8], [0, 9], [1, 1], [4, 7]],
    [[1, 5], [0, 5], [2, 5], [3, 3], [4, 8], [5, 9]],
    [[2, 9], [1, 3], [4, 5], [5, 4], [0, 3], [3, 1]],
    [[1, 3], [3, 3], [5, 9], [0, 10], [4, 4], [2, 1]],
]


def test_parses_ft06():
    adapter = JSSPBenchAdapter(DATA)
    instances = {inst.case_id: inst for inst in adapter.iter_instances()}
    assert set(instances) == {"ft06", "tiny2x2"}

    ft06 = instances["ft06"]
    assert ft06.benchmark == "jssp"
    assert ft06.case_name == "JSSP 6x6"
    assert ft06.n_agents == 6
    assert ft06.meta["n_machines"] == 6
    # `# ub: 55` carries the known optimal makespan.
    assert ft06.ground_truth == 55
    assert ft06.meta["upper_bound"] == 55
    assert ft06.meta["output_type"] == "json"
    assert ft06.meta["is_segmented"] is False
    assert ft06.segmented is False
    # shards[i] is job i's ordered [machine, duration] operation list.
    assert ft06.shards == FT06_JOBS


def test_parses_tiny2x2():
    adapter = JSSPBenchAdapter(DATA)
    (inst,) = list(adapter.iter_instances(cases=["tiny2x2"]))
    assert inst.case_id == "tiny2x2"
    assert inst.case_name == "JSSP 2x2"
    assert inst.n_agents == 2
    assert inst.meta["n_machines"] == 2
    assert inst.shards == [[[0, 2], [1, 2]], [[1, 3], [0, 2]]]
    # Hand-derived optimum (see tiny2x2.jssp comments): machine 1 must carry
    # job1 op0 (3) + job0 op1 (2), so makespan >= 5; 5 is achievable -> ub = 5.
    assert inst.ground_truth == 5
    assert inst.meta["upper_bound"] == 5


def test_agent_counts_filter():
    adapter = JSSPBenchAdapter(DATA)
    only_n2 = [inst.case_id for inst in adapter.iter_instances(agent_counts=[2])]
    assert only_n2 == ["tiny2x2"]
    only_n6 = [inst.case_id for inst in adapter.iter_instances(agent_counts=[6])]
    assert only_n6 == ["ft06"]
    assert list(adapter.iter_instances(agent_counts=[3])) == []


def test_cases_filter_and_levels_ignored():
    adapter = JSSPBenchAdapter(DATA)
    only = [inst.case_id for inst in adapter.iter_instances(cases=["ft06"])]
    assert only == ["ft06"]
    # JSSP has no level taxonomy: the levels filter is accepted and ignored.
    all_ids = [inst.case_id for inst in adapter.iter_instances(levels=["I", "III"])]
    assert all_ids == ["ft06", "tiny2x2"]
    # cases + agent_counts compose (mismatched count -> empty).
    assert list(adapter.iter_instances(cases=["ft06"], agent_counts=[2])) == []


def test_task_prompt_has_placeholders_and_answer_schema():
    adapter = JSSPBenchAdapter(DATA)
    (inst,) = list(adapter.iter_instances(cases=["tiny2x2"]))
    prompt = inst.task_prompt
    assert "{agent_id}" in prompt
    assert "{input_shard}" in prompt
    # The JSON answer schema is spelled out for the agents.
    assert '"makespan"' in prompt
    assert '"schedule"' in prompt
    assert '"job"' in prompt and '"op"' in prompt and '"machine"' in prompt
    assert '"start"' in prompt and '"end"' in prompt
    assert "makespan" in prompt.lower()


def test_naive_bound_when_ub_comment_absent(tmp_path):
    # Without `# ub:`, ground truth falls back to the naive feasible bound
    # (sum of all durations: run every operation back to back).
    (tmp_path / "noub.jssp").write_text("2 2\n0 2 1 2\n1 3 0 2\n")
    adapter = JSSPBenchAdapter(tmp_path)
    (inst,) = list(adapter.iter_instances())
    assert inst.ground_truth == 2 + 2 + 3 + 2
    assert inst.meta["upper_bound"] == 9


def test_missing_dir_raises():
    adapter = JSSPBenchAdapter(DATA / "does_not_exist")
    with pytest.raises(FileNotFoundError):
        list(adapter.iter_instances())
