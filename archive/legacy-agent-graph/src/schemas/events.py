"""Event schema — a single coordination step in the reasoning process.

Paper reference (Sec 3.2, Table 1, Appendix B.2):
  Event types: delegate_subtask, revise_claim, contradict_claim, merge_claims.
  Each event transforms or relates one or more claims.

Paper (Appendix Table 9): Event-level fields.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EventType(str, enum.Enum):
    """Paper Table 1 + Appendix Table 10: coordination event types."""

    PROPOSE_CLAIM = "propose_claim"
    REVISE_CLAIM = "revise_claim"
    CONTRADICT_CLAIM = "contradict_claim"
    MERGE_CLAIMS = "merge_claims"
    DELEGATE_SUBTASK = "delegate_subtask"


class Event(BaseModel):
    """A single coordination step recorded in the interaction trace.

    Paper (Appendix Table 9): run_id, step_id, agent_id, event_type,
    target_claim_id, target_subtask_id, timestamp, message_length.
    """

    event_id: str
    run_id: str = ""
    step_id: int = 0
    agent_id: str
    event_type: EventType
    # The claim produced by this event
    claim_id: str = ""
    # Referenced existing claim(s)
    target_claim_id: Optional[str] = None
    target_subtask_id: Optional[str] = None
    # For merge events — the parent claims being merged
    parent_claim_ids: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
    message_length: int = 0
    # Cascade association
    root_claim_id: str = ""
