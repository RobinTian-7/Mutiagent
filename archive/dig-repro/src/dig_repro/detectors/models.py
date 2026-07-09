"""Detector result models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DetectionRecord(BaseModel):
    kind: str
    severity: str
    message: str
    event_ids: list[str] = Field(default_factory=list)
    activation_ids: list[str] = Field(default_factory=list)

