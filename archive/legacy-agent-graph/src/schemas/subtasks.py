"""Subtask schema — hierarchical task decomposition.

Paper reference (Appendix B.1, Table 11):
  "Task → Subtask → Claim → Event"
  The subtask tree records task decomposition induced by delegation.
  Separate from the Claim DAG, which records reasoning evolution.
"""

from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


class SubtaskStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


class Subtask(BaseModel):
    """A decomposed work unit created via delegation.

    Paper (Appendix Table 11): subtask_id, parent_subtask_id,
    subtask_depth, assigned_agent, subtask_status.
    """

    subtask_id: str
    parent_subtask_id: Optional[str] = None
    subtask_depth: int = 0
    assigned_agent: Optional[str] = None
    subtask_status: SubtaskStatus = SubtaskStatus.PENDING
    description: str = ""
    # Claims produced within this subtask
    claim_ids: list[str] = Field(default_factory=list)
