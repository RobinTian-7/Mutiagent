"""Cascade schema — connected subgraph of claims sharing a root.

Paper reference (Sec 3.2):
  C_r = {c_i in C | root(c_i) = c_r}
  Cascades represent the propagation of reasoning initiated by a single claim.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Cascade(BaseModel):
    """A coordination cascade rooted at a single claim.

    Paper: "Cascades are connected subgraphs of G corresponding to the
    propagation of reasoning initiated by a single claim, forming the
    fundamental units for analyzing coordination dynamics."
    """

    root_claim_id: str
    claim_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)

    @property
    def size(self) -> int:
        """Cascade size = |C_r| (Paper Eq. 1)."""
        return len(self.claim_ids)

    @property
    def tce(self) -> int:
        """Total Cognitive Effort = number of events in cascade (Paper Eq. 2)."""
        return len(self.event_ids)
