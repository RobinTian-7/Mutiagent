"""Structured trace records for agent LLM calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AgentStepTrace(BaseModel):
    """Auditable record for one agent update in one communication round."""

    run_id: str
    round_idx: int
    communication_round: int
    agent_id: int
    topology_name: str
    neighbors: list[int] = Field(default_factory=list)
    inbox: list[dict[str, Any]] = Field(default_factory=list)
    prompt: str = ""
    raw_response: str = ""
    raw_responses: list[str] = Field(default_factory=list)
    raw_prompts: list[str] = Field(default_factory=list)
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    parsed_belief_state: dict[str, Any] = Field(default_factory=dict)
    outbox: dict[str, Any] = Field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 0
    retry_attempts: int = 0
    parse_error: str | None = None


def write_traces_jsonl(traces: list[AgentStepTrace], path: str | Path) -> str:
    """Write traces as one JSON object per line and return the path string."""
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_traces = sorted(
        traces,
        key=lambda trace: (trace.round_idx, trace.agent_id),
    )
    with trace_path.open("w", encoding="utf-8") as handle:
        for trace in sorted_traces:
            handle.write(json.dumps(trace.model_dump(), sort_keys=True))
            handle.write("\n")
    return str(trace_path)


def reset_trace_jsonl(path: str | Path) -> str:
    """Create or truncate a trace JSONL file and return the path string."""
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")
    return str(trace_path)


def append_traces_jsonl(traces: list[AgentStepTrace], path: str | Path) -> str:
    """Append traces to a JSONL file and return the path string."""
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_traces = sorted(
        traces,
        key=lambda trace: (trace.round_idx, trace.agent_id),
    )
    with trace_path.open("a", encoding="utf-8") as handle:
        for trace in sorted_traces:
            handle.write(json.dumps(trace.model_dump(), sort_keys=True))
            handle.write("\n")
    return str(trace_path)
