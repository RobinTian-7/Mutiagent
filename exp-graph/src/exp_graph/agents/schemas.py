"""Agent config and state schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from exp_graph.messaging.messages import OutboxMessage


class BeliefStatus(str, Enum):
    """Allowed belief state statuses."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    FINAL = "final"


class BeliefState(BaseModel):
    """The only internal source of truth for an agent."""

    status: BeliefStatus = BeliefStatus.UNKNOWN
    proposal: str = ""
    consensus_key: str | None = "UNKNOWN"
    support: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    open_questions: list[str] = Field(default_factory=list)
    private_notes: str = ""
    confidence: float | None = None
    structured_state: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None

    @field_validator("support", "open_questions", mode="before")
    @classmethod
    def _coerce_string_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.0, min(1.0, float(value)))


class AgentConfig(BaseModel):
    """Static configuration for one agent."""

    agent_id: int
    role: str = "solver"
    model_name: str
    prompt_template_name: str = "solver_v1"
    json_retry_attempts: int = 2
    temperature: float = 0.0


class AgentState(BaseModel):
    """Mutable state for one agent."""

    local_observation: dict[str, Any]
    belief_state: BeliefState
    inbox: list[OutboxMessage] = Field(default_factory=list)
    outbox: OutboxMessage | None = None


def make_initial_agent_state(
    local_observation: dict[str, Any],
    belief_state: BeliefState,
    agent_id: int,
    round_idx: int,
) -> AgentState:
    """Create an agent state and derive its initial outbox."""
    outbox = OutboxMessage.from_belief_state(
        agent_id=agent_id,
        round_idx=round_idx,
        belief_state=belief_state,
    )
    return AgentState(
        local_observation=local_observation,
        belief_state=belief_state,
        inbox=[],
        outbox=outbox,
    )
