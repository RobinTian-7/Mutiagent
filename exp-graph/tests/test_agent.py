from exp_graph.agents import BeliefState
from exp_graph.messaging import OutboxMessage


def test_build_outbox_is_derived_from_belief_state() -> None:
    belief = BeliefState(
        status="candidate",
        proposal="Target appears to be at index 4.",
        consensus_key="FOUND:4",
        support=["a", "b", "c", "d"],
        uncertainty="low",
        open_questions=["confirm shard 4", "anything else?"],
        private_notes="do not send",
    )

    outbox = OutboxMessage.from_belief_state(
        agent_id=2,
        round_idx=5,
        belief_state=belief,
    )

    assert outbox.agent_id == 2
    assert outbox.round_idx == 5
    assert outbox.status == "candidate"
    assert outbox.consensus_key == "FOUND:4"
    assert outbox.support == ["a", "b", "c"]
    assert outbox.request == "confirm shard 4"
    assert "private_notes" not in outbox.model_dump()
