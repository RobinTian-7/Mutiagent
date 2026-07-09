"""Event models for DIG reproduction."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    PROBLEM = "problem"
    RAW_DATA = "raw_data"
    SOLUTION = "solution"


class Event(BaseModel):
    """Global event object tracked across deliveries."""

    event_id: str
    event_type: EventType
    problem_id: str
    root_problem_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    coverage_ids: list[int] = Field(default_factory=list)
    parent_event_ids: list[str] = Field(default_factory=list)
    lineage_id: str
    created_by_agent_id: int | None = None
    created_by_activation_id: str | None = None
    created_at: int = 0
    reroute_count: int = 0
    final_answer: bool = False
    system_tags: list[str] = Field(default_factory=list)
    consumed_by_activation_ids: list[str] = Field(default_factory=list)

