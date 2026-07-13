from __future__ import annotations

import json

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage

from masbench.adapters.silo_paper_protocols import run_silo_paper_protocol
from masbench.bench import run_benchmark
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance


class _ScriptedPaperClient:
    def __init__(self, protocol: str) -> None:
        self.protocol = protocol
        self.prompts: dict[tuple[int, int], str] = {}

    def complete(self, prompt: str, model_name: str, temperature: float | None = None):
        raw_state = prompt.split("ROUND_STATE_JSON:\n", 1)[1].split(
            "\n\nSILO_PROTOCOL_ACTION_JSON:", 1
        )[0]
        state = json.loads(raw_state)
        agent_id = int(state["agent_id"])
        round_idx = int(state["round"])
        self.prompts[(agent_id, round_idx)] = prompt
        other = 1 - agent_id

        if round_idx == 1 and self.protocol == "p2p":
            actions = [
                {
                    "tool": "send_message",
                    "parameters": {
                        "target_id": other,
                        "content": f"payload-from-{agent_id}",
                    },
                },
                {"tool": "wait", "parameters": {}},
            ]
        elif round_idx == 1 and self.protocol == "broadcast":
            actions = [
                {
                    "tool": "broadcast_message",
                    "parameters": {"content": f"payload-from-{agent_id}"},
                },
                {"tool": "wait", "parameters": {}},
            ]
        elif round_idx == 1 and self.protocol == "sfs":
            actions = [
                {
                    "tool": "write_file",
                    "parameters": {
                        "path": f"agent_{agent_id}",
                        "content": f"payload-from-{agent_id}",
                    },
                },
                {"tool": "wait", "parameters": {}},
            ]
        elif round_idx == 2 and self.protocol in {"p2p", "broadcast"}:
            actions = [
                {"tool": "receive_messages", "parameters": {}},
                {"tool": "wait", "parameters": {}},
            ]
        elif round_idx == 2:
            actions = [
                {"tool": "read_file", "parameters": {"path": f"agent_{other}"}},
                {"tool": "wait", "parameters": {}},
            ]
        else:
            actions = [
                {
                    "tool": "submit_result",
                    "parameters": {"answer": [agent_id + 1]},
                }
            ]

        text = json.dumps({"actions": actions})
        return LLMResponse(
            text=text,
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10),
        )


def _instance() -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="II-99",
        case_name="Synthetic Segments",
        n_agents=2,
        shards=[[10], [20]],
        ground_truth=[1],
        task_prompt="Return your assigned segment.\nYour data: {input_shard}\n",
        meta={
            "num_agents": 2,
            "is_segmented": True,
            "output_type": "distributed",
            "expected_outputs": [[1], [2]],
        },
    )


@pytest.mark.parametrize("protocol", ["p2p", "broadcast", "sfs"])
def test_paper_protocols_run_with_delayed_visibility_and_per_agent_scores(
    protocol: str,
) -> None:
    client = _ScriptedPaperClient(protocol)
    cfg = RunConfig(
        silo_eval_mode="all_agents",
        max_rounds=3,
        model_name="scripted",
    )
    score = run_silo_paper_protocol(
        _instance(), cfg, protocol=protocol, llm_client=client
    )

    assert score.success is True
    assert score.extra["paper_S"] == 1.0
    assert score.extra["paper_P"] == 1.0
    assert score.extra["paper_C"] == 20.0
    assert score.extra["paper_D"] == 1.0
    assert score.n_messages == 2
    assert score.n_model_calls == 6
    assert score.extra["information_coverage_by_agent"] == [1.0, 1.0]
    assert score.extra["min_information_coverage"] == 1.0
    assert score.extra["all_agents_full_information"] is True
    assert [row["answer"] for row in score.extra["per_agent_submissions"]] == [
        [1],
        [2],
    ]

    # Round 2 can request the transfer but cannot see its result until round 3.
    assert "payload-from-1" not in client.prompts[(0, 2)]
    assert "payload-from-1" in client.prompts[(0, 3)]


def test_paper_protocols_require_all_agents_mode() -> None:
    with pytest.raises(ValueError, match="all_agents"):
        run_silo_paper_protocol(
            _instance(),
            RunConfig(silo_eval_mode="sink", max_rounds=1),
            protocol="p2p",
            llm_client=_ScriptedPaperClient("p2p"),
        )


def test_bench_exposes_all_three_paper_arms_in_parallel() -> None:
    class _Adapter:
        def iter_instances(self, **filters):
            yield _instance()

    results = run_benchmark(
        _Adapter(),  # type: ignore[arg-type]
        seeds=[0],
        arms=["p2p", "broadcast", "sfs"],
        cfg_base=RunConfig(
            llm_provider="fake",
            model_name="fake",
            silo_eval_mode="all_agents",
            max_rounds=1,
        ),
        workers=2,
        progress=False,
    )
    assert {run["arm"] for run in results["runs"]} == {
        "p2p",
        "broadcast",
        "sfs",
    }
    assert all("per_agent_submissions" in run for run in results["runs"])
    assert all("paper_D" in run for run in results["runs"])
