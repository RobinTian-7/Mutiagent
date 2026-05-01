"""General-purpose agents and planners."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError

from dig_repro.events.models import Event, EventType
from dig_repro.llm.base import LLMClient, LLMResponse, UsageStats
from dig_repro.llm.parser import extract_json_object
from dig_repro.llm.prompts import build_agent_prompt
from dig_repro.runtime.models import (
    ActivationPlan,
    AgentAction,
    EventDecision,
    EventDraft,
    ToolCall,
    ToolName,
)
from dig_repro.tasks.base import TaskAdapter


class ActivationPlanner(ABC):
    @abstractmethod
    def plan(
        self,
        *,
        task_adapter: TaskAdapter,
        problem: dict[str, Any],
        agent_id: int,
        all_agent_ids: list[int],
        pending_events: list[Event],
        logical_time: int,
    ) -> tuple[ActivationPlan, UsageStats]:
        ...


class RuleBasedPlanner(ActivationPlanner):
    """Deterministic planner used in tests and offline regression."""

    def __init__(self, *, seed: int = 0, split_threshold: int = 256, max_split_parts: int = 2) -> None:
        self.rng = random.Random(seed)
        self.split_threshold = split_threshold
        self.max_split_parts = max_split_parts

    def plan(
        self,
        *,
        task_adapter: TaskAdapter,
        problem: dict[str, Any],
        agent_id: int,
        all_agent_ids: list[int],
        pending_events: list[Event],
        logical_time: int,
    ) -> tuple[ActivationPlan, UsageStats]:
        decisions = [EventDecision(event_id=event.event_id, action=AgentAction.WAIT) for event in pending_events]
        by_id = {event.event_id: event for event in pending_events}
        event_ids = [event.event_id for event in pending_events]

        def set_action(event_id: str, action: AgentAction, reroute_to: list[int] | None = None) -> None:
            idx = event_ids.index(event_id)
            decisions[idx] = EventDecision(
                event_id=event_id,
                action=action,
                reroute_to=list(reroute_to or []),
            )

        solution_events = [event for event in pending_events if event.event_type == EventType.SOLUTION]
        raw_events = [event for event in pending_events if event.event_type == EventType.RAW_DATA]
        problem_events = [event for event in pending_events if event.event_type == EventType.PROBLEM]

        if raw_events:
            event = raw_events[0]
            set_action(event.event_id, AgentAction.CONSUME)
            solved = task_adapter.solve_raw_data_payload(problem, event.payload)
            draft = EventDraft(
                event_type=EventType.SOLUTION.value,
                problem_id=event.problem_id,
                payload=solved,
                coverage_ids=solved.get("covered_ids", []),
                recipient_ids=list(all_agent_ids),
                parent_event_ids=[event.event_id],
                lineage_id=event.lineage_id,
                final_answer=task_adapter.is_complete_solution(problem, solved),
            )
            return (
                ActivationPlan(
                    input_actions=decisions,
                    out_events=[draft],
                    is_final_answer=draft.final_answer,
                    reasoning={
                        "observation": "Raw data available.",
                        "thought": "Compute local frequency table and share it.",
                        "action": "Solved raw data and broadcast partial solution.",
                    },
                ),
                UsageStats(model_calls=0),
            )

        if problem_events:
            event = problem_events[0]
            set_action(event.event_id, AgentAction.CONSUME)
            if len(event.coverage_ids) > max(1, self.split_threshold):
                recipients = self._pick_delegates(agent_id, all_agent_ids, self.max_split_parts)
                return (
                    ActivationPlan(
                        input_actions=decisions,
                        tool_calls=[
                            ToolCall(
                                name=ToolName.SPLIT_PROBLEM,
                                event_id=event.event_id,
                                args={
                                    "n_parts": self.max_split_parts,
                                    "recipient_ids": recipients,
                                },
                            )
                        ],
                        reasoning={
                            "observation": "Problem coverage is still large.",
                            "thought": "Split into smaller subproblems for parallel work.",
                            "action": "Requested split_problem.",
                        },
                    ),
                    UsageStats(model_calls=0),
                )
            return (
                ActivationPlan(
                    input_actions=decisions,
                    tool_calls=[
                        ToolCall(
                            name=ToolName.GET_RAW_DATA,
                            event_id=event.event_id,
                            args={"recipient_ids": [agent_id]},
                        )
                    ],
                    reasoning={
                        "observation": "Problem is small enough to inspect directly.",
                        "thought": "Fetch raw data to compute a partial answer.",
                        "action": "Requested get_raw_data.",
                    },
                ),
                UsageStats(model_calls=0),
            )

        if len(solution_events) >= 2:
            selected = solution_events[: min(3, len(solution_events))]
            for event in selected:
                set_action(event.event_id, AgentAction.CONSUME)
            merged = task_adapter.merge_solution_payloads(
                problem,
                [event.payload for event in selected],
            )
            complete = task_adapter.is_complete_solution(problem, merged)
            draft = EventDraft(
                event_type=EventType.SOLUTION.value,
                problem_id=selected[0].problem_id,
                payload=merged,
                coverage_ids=merged.get("covered_ids", []),
                recipient_ids=list(all_agent_ids),
                parent_event_ids=[event.event_id for event in selected],
                lineage_id=f"agg:{selected[0].problem_id}:{logical_time}:{agent_id}",
                final_answer=complete,
            )
            return (
                ActivationPlan(
                    input_actions=decisions,
                    out_events=[draft],
                    is_final_answer=complete,
                    reasoning={
                        "observation": "Multiple solution events available.",
                        "thought": "Aggregate partial solutions to reduce redundancy.",
                        "action": "Merged solution events.",
                    },
                ),
                UsageStats(model_calls=0),
            )

        if len(solution_events) == 1:
            event = solution_events[0]
            if task_adapter.is_complete_solution(problem, event.payload):
                set_action(event.event_id, AgentAction.CONSUME)
                draft = EventDraft(
                    event_type=EventType.SOLUTION.value,
                    problem_id=event.problem_id,
                    payload=event.payload,
                    coverage_ids=event.coverage_ids,
                    recipient_ids=[],
                    parent_event_ids=[event.event_id],
                    lineage_id=event.lineage_id,
                    final_answer=True,
                )
                return (
                    ActivationPlan(
                        input_actions=decisions,
                        out_events=[draft],
                        is_final_answer=True,
                        reasoning={
                            "observation": "A complete solution is already present.",
                            "thought": "Submit the completed answer.",
                            "action": "Submitted final solution.",
                        },
                    ),
                    UsageStats(model_calls=0),
                )

        return (
            ActivationPlan(
                input_actions=decisions,
                reasoning={
                    "observation": "No productive combination was available.",
                    "thought": "Keep events buffered for later progress.",
                    "action": "Waited on pending events.",
                },
            ),
            UsageStats(model_calls=0),
        )

    @staticmethod
    def _pick_delegates(agent_id: int, all_agent_ids: list[int], n_parts: int) -> list[int]:
        ordered = [candidate for candidate in all_agent_ids if candidate != agent_id] or [agent_id]
        recipients = []
        for offset in range(n_parts):
            recipients.append(ordered[offset % len(ordered)])
        return recipients


class LLMPlanner(ActivationPlanner):
    """LLM-backed planner that follows the paper-style general agent prompt."""

    def __init__(self, llm_client: LLMClient, *, model_name: str, temperature: float) -> None:
        self.llm_client = llm_client
        self.model_name = model_name
        self.temperature = temperature

    def plan(
        self,
        *,
        task_adapter: TaskAdapter,
        problem: dict[str, Any],
        agent_id: int,
        all_agent_ids: list[int],
        pending_events: list[Event],
        logical_time: int,
    ) -> tuple[ActivationPlan, UsageStats]:
        prompt = build_agent_prompt(
            agent_name=f"Agent {agent_id}",
            problem_spec=task_adapter.format_problem_spec(problem),
            all_agents=all_agent_ids,
            pending_events=pending_events,
        )
        response = self.llm_client.complete(
            prompt,
            model_name=self.model_name,
            temperature=self.temperature,
        )
        data = extract_json_object(response.text)
        try:
            plan = ActivationPlan(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid agent plan JSON: {exc}") from exc
        return plan, response.usage
