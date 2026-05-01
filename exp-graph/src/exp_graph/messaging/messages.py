"""Structured messages exchanged between neighbors."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OutboxMessage(BaseModel):
    """External view derived from an agent belief state."""

    agent_id: int
    round_idx: int
    status: str
    proposal: str
    consensus_key: str | None = "UNKNOWN"
    support: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    request: str = ""
    structured_payload: dict = Field(default_factory=dict)

    @classmethod
    def from_belief_state(
        cls,
        agent_id: int,
        round_idx: int,
        belief_state: object,
    ) -> "OutboxMessage":
        """Derive a short outbox from a belief state and runtime metadata."""
        open_questions = list(getattr(belief_state, "open_questions", []) or [])
        request = open_questions[0] if open_questions else ""
        return cls(
            agent_id=agent_id,
            round_idx=round_idx,
            status=str(getattr(belief_state, "status", "unknown").value)
            if hasattr(getattr(belief_state, "status", None), "value")
            else str(getattr(belief_state, "status", "unknown")),
            proposal=str(getattr(belief_state, "proposal", "")),
            consensus_key=getattr(belief_state, "consensus_key", "UNKNOWN"),
            support=[str(item) for item in getattr(belief_state, "support", [])[:3]],
            uncertainty=str(getattr(belief_state, "uncertainty", "")),
            request=str(request),
            structured_payload=dict(getattr(belief_state, "structured_state", {}) or {}),
        )
