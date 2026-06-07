import json

import masbench  # noqa: F401
from exp_graph.agents.schemas import BeliefState
from exp_graph.llm.parser import parse_belief_state
from exp_graph.llm.prompts import build_solver_prompt
from masbench.core.instance import BenchmarkInstance
from masbench.core.task_bridge import BenchmarkTaskAdapter
from masbench.llm.fake import BenchmarkFakeLLMClient


def _prompt_for(instance, agent_id, old_belief, inbox):
    adapter = BenchmarkTaskAdapter(instance)
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, instance.n_agents)
    return build_solver_prompt(
        task_adapter=adapter, global_task=gt,
        local_observation=obs[agent_id], old_belief_state=old_belief, inbox=inbox,
    )


def test_fake_returns_parseable_belief_for_unknown_case():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="III-21", case_name="Distributed Sort",
        n_agents=2, shards=[[3, 1], [4, 2]], ground_truth=[1, 2, 3, 4],
        task_prompt="Sort. Agent {agent_id}: {input_shard}",
    )
    prompt = _prompt_for(inst, 0, BeliefState(), [])
    resp = BenchmarkFakeLLMClient().complete(prompt, model_name="fake")
    belief = parse_belief_state(resp.text)  # must not raise
    assert isinstance(belief, BeliefState)
    assert resp.usage.completion_tokens > 0


def test_fake_reduces_global_max_from_local_shard():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[3, 1, 9, 2], [5, 8, 4]], ground_truth=9,
        task_prompt="Max. Agent {agent_id}: {input_shard}",
    )
    prompt = _prompt_for(inst, 0, BeliefState(), [])
    resp = BenchmarkFakeLLMClient().complete(prompt, model_name="fake")
    belief = json.loads(resp.text)
    assert belief["consensus_key"] == "9"  # local max of [3,1,9,2]


def test_fake_reduces_global_max_with_neighbor_key():
    # Agent 1's local max is 8, but a neighbor reports 9 -> should output 9.
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[3, 1, 9, 2], [5, 8, 4]], ground_truth=9,
        task_prompt="Max. Agent {agent_id}: {input_shard}",
    )
    from exp_graph.messaging.messages import OutboxMessage

    neighbor = OutboxMessage.from_belief_state(
        agent_id=0, round_idx=0,
        belief_state=BeliefState(status="candidate", consensus_key="9"),
    )
    prompt = _prompt_for(inst, 1, BeliefState(), [neighbor])
    resp = BenchmarkFakeLLMClient().complete(prompt, model_name="fake")
    belief = json.loads(resp.text)
    assert belief["consensus_key"] == "9"
