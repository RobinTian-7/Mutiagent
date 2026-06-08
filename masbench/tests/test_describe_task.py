from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.instance import BenchmarkInstance


def test_describe_task_brief_strips_placeholders():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[1], [2]], ground_truth=2,
        task_prompt="Find the GLOBAL MAXIMUM. You are Agent {agent_id} holding {input_shard}.",
    )
    brief = SiloProtocolAdapter(inst).describe_task()
    assert brief.startswith("Global Max:")
    assert "{agent_id}" not in brief and "{input_shard}" not in brief
    assert "GLOBAL MAXIMUM" in brief
    assert len(brief) <= 400
