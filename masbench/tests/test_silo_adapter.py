from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter

DATA = Path(__file__).parent / "data"


def test_loads_instance_from_json():
    adapter = SiloBenchAdapter(DATA)
    instances = {inst.case_id: inst for inst in adapter.iter_instances()}
    assert set(instances) == {"I-01", "III-21"}
    gmax = instances["I-01"]
    assert gmax.n_agents == 2
    assert gmax.shards == [[3, 1, 9, 2], [5, 8, 4]]
    assert gmax.ground_truth == 9
    assert gmax.case_name == "Global Max"
    assert "{agent_id}" in gmax.task_prompt


def test_filters_by_case():
    adapter = SiloBenchAdapter(DATA)
    only = list(adapter.iter_instances(cases=["I-01"]))
    assert len(only) == 1
    assert only[0].case_id == "I-01"


def test_filters_by_level():
    adapter = SiloBenchAdapter(DATA)
    level_iii = list(adapter.iter_instances(levels=["III"]))
    assert [inst.case_id for inst in level_iii] == ["III-21"]
