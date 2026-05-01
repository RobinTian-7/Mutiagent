from exp_graph.aggregator.final_reducer import (
    AgentFinalState,
    GroupSummary,
    group_candidates,
    maybe_run_llm_adjudicator,
    rule_based_select,
    summarize_group,
)
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMResponse
from exp_graph.tasks import ArraySearchTaskAdapter


def test_final_reducer_groups_and_selects_top_candidate() -> None:
    adapter = ArraySearchTaskAdapter()
    states = [
        AgentFinalState(
            agent_id=0,
            status="final",
            proposal="Target is at global index 3.",
            consensus_key="FOUND:3",
            support=["local evidence"],
        ),
        AgentFinalState(
            agent_id=1,
            status="final",
            proposal="Found at 3.",
            consensus_key="found:3",
            support=["neighbor evidence"],
        ),
        AgentFinalState(
            agent_id=2,
            status="unknown",
            proposal="No local hit.",
            consensus_key="UNKNOWN",
        ),
    ]

    grouped = group_candidates(states, adapter)
    summaries = [
        summarize_group(key, grouped_states, num_agents=3)
        for key, grouped_states in grouped.items()
    ]
    selection = rule_based_select(
        summaries,
        ExperimentConfig(final_accept_threshold=0.6, adjudication_margin=0.1),
    )

    assert set(grouped) == {"FOUND:3", "UNKNOWN"}
    assert selection.decision == "accept"
    assert selection.selected_group_key == "FOUND:3"


def test_final_reducer_returns_no_consensus_when_only_unknown() -> None:
    grouped = group_candidates(
        [
            AgentFinalState(
                agent_id=0,
                status="unknown",
                proposal="Need more context.",
                consensus_key="UNKNOWN",
            )
        ],
        ArraySearchTaskAdapter(),
    )
    summaries = [
        summarize_group(key, grouped_states, num_agents=1)
        for key, grouped_states in grouped.items()
    ]
    selection = rule_based_select(summaries, ExperimentConfig())

    assert selection.decision == "no_consensus"
    assert selection.selected_group_key is None


def test_group_score_ignores_optional_confidence_for_continuity() -> None:
    summary = summarize_group(
        "FOUND:4",
        [
            AgentFinalState(
                agent_id=0,
                status="final",
                proposal="Found at 4.",
                consensus_key="FOUND:4",
                confidence=0.0,
            )
        ],
        num_agents=4,
    )

    assert summary.size_ratio == 0.25
    assert summary.score == summary.size_ratio


def test_llm_adjudicator_context_does_not_leak_ground_truth() -> None:
    class CapturingLLMClient:
        def __init__(self) -> None:
            self.prompt = ""

        def complete(
            self,
            prompt: str,
            model_name: str,
            temperature: float | None = None,
        ) -> LLMResponse:
            self.prompt = prompt
            self.temperature = temperature
            return LLMResponse(
                text=(
                    '{"selected_group_key":"FOUND:2","decision":"accept",'
                    '"reason":"candidate support is stronger","confidence":0.8}'
                )
            )

    adapter = ArraySearchTaskAdapter()
    global_task = adapter.build_global_task(
        array=[0, 1, 2, 3, 4, 5, 6, 7],
        target=6,
    )
    llm_client = CapturingLLMClient()

    maybe_run_llm_adjudicator(
        top_groups=[
            GroupSummary(
                group_key="FOUND:2",
                member_agents=[0],
                size=1,
                size_ratio=0.5,
                status_distribution={"final": 1},
                representative_proposals=["candidate answer"],
                merged_support=["candidate support"],
                uncertainty_summary="",
                score=0.5,
            )
        ],
        global_task=global_task,
        config=ExperimentConfig(use_llm_adjudicator=True, temperature=0.4),
        llm_client=llm_client,
        task_adapter=adapter,
    )

    assert "answer_key" not in llm_client.prompt
    assert "answer_index" not in llm_client.prompt
    assert "FOUND:6" not in llm_client.prompt
    assert llm_client.temperature == 0.4
