"""Asynchronous event-driven runner for DIG reproduction."""

from __future__ import annotations

import json
import random
from pathlib import Path
from time import perf_counter
from typing import Any

from dig_repro.agents.general_agent import LLMPlanner, RuleBasedPlanner
from dig_repro.agents.judge import LLMJudge, RuleJudge
from dig_repro.baselines.systems import SystemKind
from dig_repro.detectors.rules import detect_errors
from dig_repro.dig.graph import build_dig_graph
from dig_repro.events.models import Event, EventType
from dig_repro.healing.engine import propose_interventions
from dig_repro.llm.openai_client import OpenAIClient
from dig_repro.metrics.eval import count_detections
from dig_repro.runtime.models import (
    ActivationRecord,
    AgentRuntimeState,
    DeliveryRecord,
    DeliveryStatus,
    EventDraft,
    ExperimentConfig,
    ExperimentMetrics,
    ExperimentResult,
    InterventionRecord,
    ToolName,
)
from dig_repro.tasks.base import TaskAdapter


class _RuntimeState:
    def __init__(self, *, all_agent_ids: list[int]) -> None:
        self.events: dict[str, Event] = {}
        self.deliveries: dict[str, DeliveryRecord] = {}
        self.agents: dict[int, AgentRuntimeState] = {
            agent_id: AgentRuntimeState(agent_id=agent_id) for agent_id in all_agent_ids
        }
        self.activations: list[ActivationRecord] = []
        self.interventions: list[InterventionRecord] = []
        self.logical_time = 0
        self.next_event_counter = 0
        self.next_delivery_counter = 0
        self.all_agent_ids = all_agent_ids
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.model_calls = 0


class DIGExperimentRunner:
    def __init__(self, *, config: ExperimentConfig, task_adapter: TaskAdapter) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.rng = random.Random(config.seed)
        self.llm_client = OpenAIClient() if config.llm_provider == "openai" else None

    def run(self, **problem_kwargs: Any) -> ExperimentResult:
        started = perf_counter()
        problem = self.task_adapter.build_problem_instance(
            difficulty=self.config.difficulty,
            seed=self.config.seed,
            **problem_kwargs,
        )
        state = _RuntimeState(all_agent_ids=list(range(self.config.n_agents)))
        planner = self._create_planner()
        judge = self._create_judge()

        root_event = Event(
            event_id=self._next_event_id(state),
            event_type=EventType.PROBLEM,
            problem_id="P",
            root_problem_id="P",
            payload={"description": problem["description"]},
            coverage_ids=self.task_adapter.all_item_ids(problem),
            parent_event_ids=[],
            lineage_id="P",
            created_at=0,
        )
        self._register_event(state, root_event, recipient_ids=[0])

        while state.logical_time < self.config.max_activations:
            if perf_counter() - started > self.config.time_limit_s:
                break

            agent_id = self._sample_ready_agent(state)
            if agent_id is None:
                break

            pending_deliveries = [
                state.deliveries[delivery_id]
                for delivery_id in list(state.agents[agent_id].pending_delivery_ids)
                if state.deliveries[delivery_id].status == DeliveryStatus.PENDING
            ]
            pending_events = [state.events[delivery.event_id] for delivery in pending_deliveries]
            plan, usage = planner.plan(
                task_adapter=self.task_adapter,
                problem=problem,
                agent_id=agent_id,
                all_agent_ids=state.all_agent_ids,
                pending_events=pending_events,
                logical_time=state.logical_time,
            )
            state.prompt_tokens += usage.prompt_tokens
            state.completion_tokens += usage.completion_tokens
            state.model_calls += usage.model_calls

            activation = ActivationRecord(
                activation_id=f"act:{state.logical_time}:{agent_id}",
                agent_id=agent_id,
                logical_time=state.logical_time,
                tool_calls=plan.tool_calls,
                reasoning=plan.reasoning,
                planner_kind=planner.__class__.__name__,
                system_name=self.config.system_name,
            )
            decisions = {decision.event_id: decision for decision in plan.input_actions}
            for delivery in pending_deliveries:
                event = state.events[delivery.event_id]
                decision = decisions.get(event.event_id)
                if decision is None:
                    raise ValueError(f"Missing action for pending event {event.event_id}")
                if decision.action.value == "wait":
                    activation.waited_event_ids.append(event.event_id)
                    continue
                if decision.action.value == "discard":
                    delivery.status = DeliveryStatus.DISCARDED
                    delivery.updated_at = state.logical_time
                    delivery.activation_id = activation.activation_id
                    state.agents[agent_id].pending_delivery_ids.remove(delivery.delivery_id)
                    activation.discarded_event_ids.append(event.event_id)
                    continue
                if decision.action.value == "reroute":
                    delivery.status = DeliveryStatus.REROUTED
                    delivery.updated_at = state.logical_time
                    delivery.activation_id = activation.activation_id
                    state.agents[agent_id].pending_delivery_ids.remove(delivery.delivery_id)
                    event.reroute_count += 1
                    self._enqueue_existing_event(
                        state,
                        event.event_id,
                        recipient_ids=decision.reroute_to or self._pick_other_agents(state, agent_id),
                        source_delivery_id=delivery.delivery_id,
                    )
                    activation.rerouted_event_ids.append(event.event_id)
                    continue
                if decision.action.value == "consume":
                    delivery.status = DeliveryStatus.CONSUMED
                    delivery.updated_at = state.logical_time
                    delivery.activation_id = activation.activation_id
                    state.agents[agent_id].pending_delivery_ids.remove(delivery.delivery_id)
                    event.consumed_by_activation_ids.append(activation.activation_id)
                    activation.processed_event_ids.append(event.event_id)

            for tool_call in plan.tool_calls:
                produced = self._execute_tool(
                    state=state,
                    problem=problem,
                    tool_call=tool_call,
                    agent_id=agent_id,
                    activation_id=activation.activation_id,
                )
                activation.produced_event_ids.extend(produced)

            for draft in plan.out_events:
                event_id = self._materialize_event_draft(
                    state=state,
                    draft=draft,
                    agent_id=agent_id,
                    activation_id=activation.activation_id,
                )
                activation.produced_event_ids.append(event_id)
                if draft.final_answer:
                    activation.submitted_event_ids.append(event_id)

            state.activations.append(activation)
            state.logical_time += 1

            detections = detect_errors(state=state, config=self.config)
            if self.config.system_name == SystemKind.MAS_DIG.value:
                interventions = propose_interventions(
                    state=state,
                    detections=detections,
                    logical_time=state.logical_time,
                )
                self._apply_interventions(state, interventions, problem=problem)
            elif (
                self.config.system_name == SystemKind.MAS_LLM_JUDGE.value
                and judge is not None
                and state.logical_time % max(1, self.config.judge_interval) == 0
            ):
                dig_log = self._build_judge_log(state, detections)
                judge_output = judge.evaluate(dig_log=dig_log)
                state.prompt_tokens += judge_output.usage.prompt_tokens
                state.completion_tokens += judge_output.usage.completion_tokens
                state.model_calls += judge_output.usage.model_calls
                interventions = [
                    InterventionRecord(
                        intervention_id=f"judge:{state.logical_time}:{idx}",
                        logical_time=state.logical_time,
                        source="judge",
                        kind=item.kind,
                        target_event_ids=item.target_event_ids,
                        recipient_ids=item.recipient_ids,
                        message=item.message,
                        detector_kinds=[error.kind for error in judge_output.errors],
                    )
                    for idx, item in enumerate(judge_output.interventions)
                ]
                self._apply_interventions(state, interventions, problem=problem)

        final_event = self._select_final_event(state, problem)
        final_solution = (
            self.task_adapter.normalize_solution(problem, final_event.payload)
            if final_event is not None
            else None
        )
        detections = detect_errors(state=state, config=self.config)
        metrics = ExperimentMetrics(
            rmse=self.task_adapter.compute_rmse(problem, final_solution),
            runtime_seconds=perf_counter() - started,
            valid_output=bool(final_event and self.task_adapter.is_complete_solution(problem, final_solution)),
            final_solution=final_solution,
            final_event_id=final_event.event_id if final_event is not None else None,
            total_activations=len(state.activations),
            prompt_tokens=state.prompt_tokens,
            completion_tokens=state.completion_tokens,
            model_calls=state.model_calls,
            detected_error_counts=count_detections(detections),
        )
        graph = build_dig_graph(events=state.events, activations=state.activations)
        exports = self._export_artifacts(
            state=state,
            graph=graph,
            problem=problem,
            metrics=metrics,
        )
        return ExperimentResult(
            config=self.config,
            problem=problem,
            metrics=metrics,
            activations=state.activations,
            interventions=state.interventions,
            graph=graph,
            exports=exports,
        )

    def _create_planner(self):
        if self.config.llm_provider == "openai":
            return LLMPlanner(
                self.llm_client,
                model_name=self.config.model_name,
                temperature=self.config.temperature,
            )
        return RuleBasedPlanner(
            seed=self.config.seed,
            split_threshold=self.config.split_threshold,
            max_split_parts=self.config.max_split_parts,
        )

    def _create_judge(self):
        if self.config.system_name != SystemKind.MAS_LLM_JUDGE.value:
            return None
        if self.config.llm_provider == "openai":
            return LLMJudge(
                self.llm_client,
                model_name=self.config.model_name,
                temperature=self.config.temperature,
            )
        return RuleJudge()

    def _sample_ready_agent(self, state: _RuntimeState) -> int | None:
        ready = [
            agent_id
            for agent_id, agent_state in state.agents.items()
            if any(
                state.deliveries[delivery_id].status == DeliveryStatus.PENDING
                for delivery_id in agent_state.pending_delivery_ids
            )
        ]
        if not ready:
            return None
        prioritized = []
        for agent_id in ready:
            pending_event_types = {
                state.events[state.deliveries[delivery_id].event_id].event_type
                for delivery_id in state.agents[agent_id].pending_delivery_ids
                if state.deliveries[delivery_id].status == DeliveryStatus.PENDING
            }
            if EventType.RAW_DATA in pending_event_types or EventType.PROBLEM in pending_event_types:
                prioritized.append(agent_id)
        return self.rng.choice(prioritized or ready)

    def _execute_tool(
        self,
        *,
        state: _RuntimeState,
        problem: dict[str, Any],
        tool_call,
        agent_id: int,
        activation_id: str,
    ) -> list[str]:
        event = state.events[tool_call.event_id]
        produced_ids: list[str] = []
        if tool_call.name == ToolName.SPLIT_PROBLEM:
            parts = self.task_adapter.split_coverage(
                problem,
                event.coverage_ids,
                int(tool_call.args.get("n_parts", self.config.max_split_parts)),
            )
            recipients = list(tool_call.args.get("recipient_ids", self._pick_other_agents(state, agent_id)))
            for index, coverage in enumerate(parts):
                child = Event(
                    event_id=self._next_event_id(state),
                    event_type=EventType.PROBLEM,
                    problem_id=event.problem_id,
                    root_problem_id=event.root_problem_id,
                    payload={"parent_problem_id": event.event_id},
                    coverage_ids=coverage,
                    parent_event_ids=[event.event_id],
                    lineage_id=f"{event.event_id}:{index}",
                    created_by_agent_id=agent_id,
                    created_by_activation_id=activation_id,
                    created_at=state.logical_time,
                )
                recipient_id = recipients[min(index, len(recipients) - 1)]
                self._register_event(state, child, recipient_ids=[recipient_id])
                produced_ids.append(child.event_id)
        elif tool_call.name == ToolName.GET_RAW_DATA:
            raw_payload = self.task_adapter.fetch_raw_data(problem, event.coverage_ids)
            raw_event = Event(
                event_id=self._next_event_id(state),
                event_type=EventType.RAW_DATA,
                problem_id=event.problem_id,
                root_problem_id=event.root_problem_id,
                payload=raw_payload,
                coverage_ids=event.coverage_ids,
                parent_event_ids=[event.event_id],
                lineage_id=event.lineage_id,
                created_by_agent_id=agent_id,
                created_by_activation_id=activation_id,
                created_at=state.logical_time,
            )
            recipient_ids = list(tool_call.args.get("recipient_ids", [agent_id]))
            self._register_event(state, raw_event, recipient_ids=recipient_ids)
            produced_ids.append(raw_event.event_id)
        return produced_ids

    def _materialize_event_draft(
        self,
        *,
        state: _RuntimeState,
        draft: EventDraft,
        agent_id: int,
        activation_id: str,
    ) -> str:
        event = Event(
            event_id=self._next_event_id(state),
            event_type=EventType(draft.event_type),
            problem_id=draft.problem_id,
            root_problem_id="P",
            payload=draft.payload,
            coverage_ids=list(draft.coverage_ids),
            parent_event_ids=list(draft.parent_event_ids),
            lineage_id=draft.lineage_id or f"{draft.problem_id}:{activation_id}",
            created_by_agent_id=agent_id,
            created_by_activation_id=activation_id,
            created_at=state.logical_time,
            final_answer=draft.final_answer,
            system_tags=list(draft.system_tags),
        )
        self._register_event(state, event, recipient_ids=list(draft.recipient_ids))
        return event.event_id

    def _register_event(self, state: _RuntimeState, event: Event, recipient_ids: list[int]) -> None:
        state.events[event.event_id] = event
        self._enqueue_existing_event(state, event.event_id, recipient_ids=recipient_ids)

    def _enqueue_existing_event(
        self,
        state: _RuntimeState,
        event_id: str,
        *,
        recipient_ids: list[int],
        source_delivery_id: str | None = None,
    ) -> None:
        for recipient_id in recipient_ids:
            delivery = DeliveryRecord(
                delivery_id=self._next_delivery_id(state),
                event_id=event_id,
                agent_id=recipient_id,
                created_at=state.logical_time,
                updated_at=state.logical_time,
                source_delivery_id=source_delivery_id,
            )
            state.deliveries[delivery.delivery_id] = delivery
            state.agents[recipient_id].pending_delivery_ids.append(delivery.delivery_id)

    @staticmethod
    def _pick_other_agents(state: _RuntimeState, agent_id: int) -> list[int]:
        others = [candidate for candidate in state.all_agent_ids if candidate != agent_id]
        return others[:2] if others else [agent_id]

    def _apply_interventions(
        self,
        state: _RuntimeState,
        interventions: list[InterventionRecord],
        *,
        problem: dict[str, Any],
    ) -> None:
        for intervention in interventions:
            state.interventions.append(intervention)
            if intervention.kind == "inject_and_reroute":
                for event_id in intervention.target_event_ids:
                    event = state.events.get(event_id)
                    if event is None:
                        continue
                    event.system_tags.append(intervention.message)
                    event.reroute_count += 1
                    self._enqueue_existing_event(
                        state,
                        event_id,
                        recipient_ids=intervention.recipient_ids or state.all_agent_ids[:1],
                    )
            elif intervention.kind == "create_system_event":
                solution_payloads = [
                    event.payload
                    for event in state.events.values()
                    if event.event_type == EventType.SOLUTION
                ]
                if solution_payloads:
                    merged = self.task_adapter.merge_solution_payloads(
                        problem,
                        solution_payloads,
                    )
                    event = Event(
                        event_id=self._next_event_id(state),
                        event_type=EventType.SOLUTION,
                        problem_id="P",
                        root_problem_id="P",
                        payload=merged,
                        coverage_ids=list(merged.get("covered_ids", [])),
                        parent_event_ids=[],
                        lineage_id=f"system:{state.logical_time}",
                        created_at=state.logical_time,
                        final_answer=self.task_adapter.is_complete_solution(
                            problem,
                            merged,
                        ),
                        system_tags=["healing"],
                    )
                    self._register_event(
                        state,
                        event,
                        recipient_ids=intervention.recipient_ids or state.all_agent_ids[:1],
                    )
                    continue
                pending = [
                    delivery.event_id
                    for delivery in state.deliveries.values()
                    if delivery.status == DeliveryStatus.PENDING
                ]
                coverage_ids = state.events[pending[0]].coverage_ids if pending else []
                event = Event(
                    event_id=self._next_event_id(state),
                    event_type=EventType.PROBLEM,
                    problem_id="P",
                    root_problem_id="P",
                    payload={"message": intervention.message},
                    coverage_ids=coverage_ids,
                    parent_event_ids=[],
                    lineage_id=f"system:{state.logical_time}",
                    created_at=state.logical_time,
                    system_tags=["healing"],
                )
                self._register_event(
                    state,
                    event,
                    recipient_ids=intervention.recipient_ids or state.all_agent_ids[:1],
                )

    def _build_judge_log(self, state: _RuntimeState, detections: list) -> dict[str, Any]:
        root_coverages = [set(event.coverage_ids) for event in state.events.values() if event.parent_event_ids == []]
        root_coverage = max(root_coverages, key=len) if root_coverages else set()
        solution_coverages = [
            set(event.payload.get("covered_ids", []))
            for event in state.events.values()
            if event.event_type == EventType.SOLUTION
        ]
        union_solution_coverage = set().union(*solution_coverages) if solution_coverages else set()
        return {
            "logical_time": state.logical_time,
            "all_agents": state.all_agent_ids,
            "num_events": len(state.events),
            "num_activations": len(state.activations),
            "detected_errors": [item.model_dump() for item in detections],
            "reroute_hotspots": [event.event_id for event in state.events.values() if event.reroute_count > self.config.reroute_threshold],
            "pending_non_solution_events": [
                delivery.event_id
                for delivery in state.deliveries.values()
                if delivery.status == DeliveryStatus.PENDING
                and state.events[delivery.event_id].event_type != EventType.SOLUTION
            ],
            "coverage_complete_without_submit": bool(
                root_coverage
                and union_solution_coverage == root_coverage
                and not any(event.final_answer for event in state.events.values())
            ),
        }

    def _select_final_event(self, state: _RuntimeState, problem: dict[str, Any]) -> Event | None:
        final_events = [
            event
            for event in state.events.values()
            if event.final_answer
        ]
        if not final_events:
            complete_solutions = [
                event
                for event in state.events.values()
                if event.event_type == EventType.SOLUTION
                and self.task_adapter.is_complete_solution(problem, event.payload)
            ]
            return sorted(complete_solutions, key=lambda item: item.created_at)[-1] if complete_solutions else None
        return sorted(final_events, key=lambda item: item.created_at)[-1]

    def _export_artifacts(self, *, state: _RuntimeState, graph: dict[str, Any], problem: dict[str, Any], metrics) -> dict[str, str]:
        if self.config.export_dir is None:
            return {}
        export_dir = Path(self.config.export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{self.config.task_name}_{self.config.system_name}_{self.config.difficulty}_{self.config.n_agents}a_seed{self.config.seed}"
        graph_path = export_dir / f"{prefix}_dig.json"
        metrics_path = export_dir / f"{prefix}_metrics.json"
        trace_path = export_dir / f"{prefix}_trace.json"
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        metrics_path.write_text(json.dumps(metrics.model_dump(), indent=2), encoding="utf-8")
        trace_path.write_text(
            json.dumps(
                {
                    "problem": problem,
                    "activations": [item.model_dump() for item in state.activations],
                    "interventions": [item.model_dump() for item in state.interventions],
                    "events": {key: value.model_dump() for key, value in state.events.items()},
                    "deliveries": {key: value.model_dump() for key, value in state.deliveries.items()},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "graph": str(graph_path),
            "metrics": str(metrics_path),
            "trace": str(trace_path),
        }

    @staticmethod
    def _next_event_id(state: _RuntimeState) -> str:
        value = f"ev:{state.next_event_counter}"
        state.next_event_counter += 1
        return value

    @staticmethod
    def _next_delivery_id(state: _RuntimeState) -> str:
        value = f"dl:{state.next_delivery_counter}"
        state.next_delivery_counter += 1
        return value
