"""Judges for the MAS+LLM Judge baseline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from dig_repro.detectors.models import DetectionRecord
from dig_repro.llm.base import LLMClient, UsageStats
from dig_repro.llm.parser import extract_json_object
from dig_repro.llm.prompts import build_judge_prompt


TAXONOMY_TEXT = """ET: early termination. MC: missing termination. OE: orphaned event.
DL: deadlock. ER: excessive rerouting. CLA: cross-lineage aggregation. RSP: repeated subproblem solving."""


class JudgeIntervention(BaseModel):
    kind: str
    target_event_ids: list[str] = Field(default_factory=list)
    recipient_ids: list[int] = Field(default_factory=list)
    message: str = ""


class JudgeOutput(BaseModel):
    errors: list[DetectionRecord] = Field(default_factory=list)
    interventions: list[JudgeIntervention] = Field(default_factory=list)
    usage: UsageStats = UsageStats()


class Judge(ABC):
    @abstractmethod
    def evaluate(self, *, dig_log: dict[str, Any]) -> JudgeOutput:
        ...


class RuleJudge(Judge):
    """Simple periodic judge used for tests."""

    def evaluate(self, *, dig_log: dict[str, Any]) -> JudgeOutput:
        interventions: list[JudgeIntervention] = []
        errors = []
        if dig_log.get("coverage_complete_without_submit"):
            interventions.append(
                JudgeIntervention(
                    kind="create_system_event",
                    recipient_ids=dig_log.get("all_agents", [])[:2],
                    message="Current evidence appears complete. Merge and submit a final answer.",
                )
            )
        stalled_events = dig_log.get("reroute_hotspots", [])
        if stalled_events:
            errors.append(
                DetectionRecord(
                    kind="ER",
                    severity="medium",
                    message="Repeated rerouting detected by periodic judge.",
                    event_ids=[stalled_events[0]],
                )
            )
            interventions.append(
                JudgeIntervention(
                    kind="inject_and_reroute",
                    target_event_ids=[stalled_events[0]],
                    recipient_ids=dig_log.get("all_agents", [])[:2],
                    message="Stop rerouting. Fetch raw data or aggregate directly.",
                )
            )
        pending_non_solution = dig_log.get("pending_non_solution_events", [])
        if pending_non_solution:
            interventions.append(
                JudgeIntervention(
                    kind="inject_and_reroute",
                    target_event_ids=pending_non_solution[:1],
                    recipient_ids=dig_log.get("all_agents", [])[:2],
                    message="Resolve this pending shard before more aggregation.",
                )
            )
        return JudgeOutput(errors=errors, interventions=interventions, usage=UsageStats(model_calls=1))


class LLMJudge(Judge):
    def __init__(self, llm_client: LLMClient, *, model_name: str, temperature: float) -> None:
        self.llm_client = llm_client
        self.model_name = model_name
        self.temperature = temperature

    def evaluate(self, *, dig_log: dict[str, Any]) -> JudgeOutput:
        prompt = build_judge_prompt(dig_log=dig_log, taxonomy_text=TAXONOMY_TEXT)
        response = self.llm_client.complete(
            prompt,
            model_name=self.model_name,
            temperature=self.temperature,
        )
        raw = extract_json_object(response.text)
        return JudgeOutput(
            errors=[DetectionRecord(**item) for item in raw.get("errors", [])],
            interventions=[JudgeIntervention(**item) for item in raw.get("interventions", [])],
            usage=response.usage,
        )
