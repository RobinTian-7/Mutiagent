from exp_graph.aggregator.final_reducer import AgentFinalState, group_candidates, rule_based_select, summarize_group
from exp_graph.configs import ExperimentConfig
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
