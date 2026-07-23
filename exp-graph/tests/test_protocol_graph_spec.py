import pytest

from exp_graph.protocols import (
    ProtocolGraphSpec,
    ProtocolStepSpec,
    build_protocol_schedule_from_spec,
)


def test_protocol_graph_spec_compiles_to_communication_steps() -> None:
    spec = ProtocolGraphSpec(
        name="custom_peer_star",
        n_agents=3,
        steps=[
            ProtocolStepSpec(
                transmissions=[(0, 1), (0, 1), (1, 2)],
                description="peer propagation",
                operator="peer_propagate",
            ),
            ProtocolStepSpec(
                transmissions=[(0, 2)],
                description="sink gather",
                operator="star_sink",
            ),
        ],
        operators=["local_solve", "peer_propagate", "star_sink"],
    )

    schedule = build_protocol_schedule_from_spec(spec)

    assert [step.step_idx for step in schedule] == [0, 1]
    assert schedule[0].transmissions == [(0, 1), (1, 2)]
    assert schedule[1].description == "sink gather"


def test_protocol_graph_spec_rejects_self_loop() -> None:
    with pytest.raises(ValueError, match="self-loops"):
        ProtocolStepSpec(transmissions=[(0, 0)])


def test_protocol_graph_spec_rejects_invalid_agent_id() -> None:
    with pytest.raises(ValueError, match="valid agent ids"):
        ProtocolGraphSpec(
            name="bad_ids",
            n_agents=2,
            steps=[ProtocolStepSpec(transmissions=[(0, 2)])],
        )


def test_protocol_graph_spec_rejects_budget_overflow() -> None:
    with pytest.raises(ValueError, match="max_messages"):
        ProtocolGraphSpec(
            name="too_many_messages",
            n_agents=3,
            steps=[
                ProtocolStepSpec(transmissions=[(0, 1), (1, 2)]),
                ProtocolStepSpec(transmissions=[(0, 2)]),
            ],
            metadata={"max_messages": 2},
        )
