"""Claim schema — atomic unit of reasoning in the coordination system.

Paper reference (Sec 3.2, Appendix B.2):
  A claim c_i = (a(c_i), t(c_i), P(c_i), τ(c_i)) where:
    a = producing agent, t = associated task,
    P = set of parent claims, τ = claim type.

Claim types (Appendix Table 6):
  proposed, revised, contradictory, merged.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ClaimType(str, enum.Enum):
    """Paper Table 6: Types of claims observed in coordination traces."""

    PROPOSED = "proposed"
    REVISED = "revised"
    CONTRADICTORY = "contradictory"
    MERGED = "merged"


class ClaimStatus(str, enum.Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INTEGRATED = "integrated"


class Claim(BaseModel):
    """A structured unit of reasoning produced by an agent.

    Paper (Appendix Table 8): claim_id, parent_claim_ids, root_claim_id,
    claim_depth, claim_status.
    """

    claim_id: str
    agent_id: str
    subtask_id: Optional[str] = None
    content: str = ""
    claim_type: ClaimType = ClaimType.PROPOSED
    parent_claim_ids: list[str] = Field(default_factory=list)
    root_claim_id: str = ""  # Inherited from earliest ancestor; self if root
    claim_depth: int = 0
    claim_status: ClaimStatus = ClaimStatus.ACTIVE
    timestamp: datetime = Field(default_factory=datetime.now)

    def model_post_init(self, __context: object) -> None:
        if not self.root_claim_id:
            if not self.parent_claim_ids:
                self.root_claim_id = self.claim_id
            # If parents exist, root must be set by the caller / trace processor
