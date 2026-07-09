"""Runtime schemas for asynchronous DIG experiments."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    DISCARDED = "discarded"
    REROUTED = "rerouted"


class AgentAction(str, Enum):
    CONSUME = "consume"
    REROUTE = "reroute"
    DISCARD = "discard"
    WAIT = "wait"


class ToolName(str, Enum):
    SPLIT_PROBLEM = "split_problem"
    GET_RAW_DATA = "get_raw_data"


class DeliveryRecord(BaseModel):
    delivery_id: str
    event_id: str
    agent_id: int
    created_at: int
    status: DeliveryStatus = DeliveryStatus.PENDING
    updated_at: int = 0
    source_delivery_id: str | None = None
    activation_id: str | None = None


class EventDecision(BaseModel):
    event_id: str
    action: AgentAction
    reroute_to: list[int] = Field(default_factory=list)


class ToolCall(BaseModel):
    name: ToolName
    event_id: str
    args: dict[str, Any] = Field(default_factory=dict)


class EventDraft(BaseModel):
    event_type: str
    problem_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    coverage_ids: list[int] = Field(default_factory=list)
    recipient_ids: list[int] = Field(default_factory=list)
    parent_event_ids: list[str] = Field(default_factory=list)
    lineage_id: str | None = None
    final_answer: bool = False
    system_tags: list[str] = Field(default_factory=list)


class ActivationPlan(BaseModel):
    input_actions: list[EventDecision]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    out_events: list[EventDraft] = Field(default_factory=list)
    is_final_answer: bool = False
    reasoning: dict[str, str] = Field(default_factory=dict)


class ActivationRecord(BaseModel):
    activation_id: str
    agent_id: int
    logical_time: int
    processed_event_ids: list[str] = Field(default_factory=list)
    waited_event_ids: list[str] = Field(default_factory=list)
    rerouted_event_ids: list[str] = Field(default_factory=list)
    discarded_event_ids: list[str] = Field(default_factory=list)
    produced_event_ids: list[str] = Field(default_factory=list)
    submitted_event_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning: dict[str, str] = Field(default_factory=dict)
    planner_kind: str = ""
    system_name: str = ""


class AgentRuntimeState(BaseModel):
    agent_id: int
    pending_delivery_ids: list[str] = Field(default_factory=list)
    seen_event_ids: list[str] = Field(default_factory=list)


class ExperimentConfig(BaseModel):
    task_name: str
    system_name: str
    n_agents: int
    difficulty: str
    seed: int = 0
    max_activations: int = 200
    judge_interval: int = 12
    time_limit_s: float = 120.0
    llm_provider: str = "rule"
    model_name: str = "gpt-4o"
    temperature: float = 0.0
    reroute_threshold: int = 3
    deadlock_window: int = 8
    missing_termination_window: int = 8
    split_threshold: int = 256
    max_split_parts: int = 2
    export_dir: str | None = None


class InterventionRecord(BaseModel):
    intervention_id: str
    logical_time: int
    source: str
    kind: str
    target_event_ids: list[str] = Field(default_factory=list)
    recipient_ids: list[int] = Field(default_factory=list)
    message: str = ""
    detector_kinds: list[str] = Field(default_factory=list)


class ExperimentMetrics(BaseModel):
    rmse: float | None = None
    runtime_seconds: float
    valid_output: bool
    final_solution: dict[str, Any] | None = None
    final_event_id: str | None = None
    total_activations: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 0
    detected_error_counts: dict[str, int] = Field(default_factory=dict)


class ExperimentResult(BaseModel):
    config: ExperimentConfig
    problem: dict[str, Any]
    metrics: ExperimentMetrics
    activations: list[ActivationRecord]
    interventions: list[InterventionRecord]
    graph: dict[str, Any]
    exports: dict[str, str] = Field(default_factory=dict)
