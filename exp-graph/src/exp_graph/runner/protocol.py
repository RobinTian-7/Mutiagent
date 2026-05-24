"""Protocol runner that preserves AgentState while changing communication schedule."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from exp_graph.agents.schemas import AgentState, BeliefState, make_initial_agent_state
from exp_graph.aggregator.cf_final import CFProtocolFinalResult, run_cf_final_aggregation
from exp_graph.configs.runtime import ExperimentConfig
from exp_graph.llm.base import LLMClient, LLMResponse, combine_usage
from exp_graph.llm.factory import create_llm_client
from exp_graph.llm.parser import parse_belief_state
from exp_graph.llm.retry import build_json_retry_prompt
from exp_graph.messaging import OutboxMessage
from exp_graph.metrics.cf_protocol import (
    CFAgentStepMetric,
    CFGlobalStepMetric,
    build_cf_step_metrics,
)
from exp_graph.protocols import (
    CommunicationStep,
    ProtocolGraphSpec,
    build_protocol_schedule,
    build_protocol_schedule_from_spec,
)
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter
from exp_graph.tracing import AgentStepTrace, append_traces_jsonl, reset_trace_jsonl


@dataclass
class _MergeOutcome:
    belief_state: BeliefState
    llm_response: LLMResponse | None = None
    prompt: str = ""
    parse_error: str | None = None
    fallback_applied: bool = False


class ProtocolRunnerConfig(BaseModel):
    """Runtime config for finite communication-protocol experiments."""

    topology_name: str = "chain"
    n_agents: int = 8
    seed: int = 0
    model_name: str = "deterministic"
    merge_mode: Literal[
        "deterministic",
        "llm_belief_merge",
        "llm_full_merge",
    ] = "deterministic"
    init_mode: Literal["deterministic", "llm_local_solve"] = "deterministic"
    llm_provider: str = "auto"
    temperature: float = 0.0
    json_retry_attempts: int = 2
    allow_deterministic_repair: bool = True
    max_parallel_agents: int = 1
    trace_enabled: bool = False
    save_prompts: bool = True
    retain_traces: bool = False
    trace_dir: str | None = None
    star_center: int = 0
    include_star_broadcast: bool = False
    average_include_min_coverage: float = 1.0
    selected_primary: Literal["topology_default", "vote", "average"] = "topology_default"
    verbose_events: bool = False
    run_id: str | None = None
    protocol_spec: ProtocolGraphSpec | None = None
    llm_role_summary: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_experiment_config(
        cls,
        config: ExperimentConfig,
        **overrides,
    ) -> "ProtocolRunnerConfig":
        data = {
            "topology_name": config.topology_name,
            "n_agents": config.n_agents,
            "seed": config.seed,
            "model_name": config.model_name,
            "init_mode": getattr(config, "init_mode", "deterministic"),
            "llm_provider": config.llm_provider,
            "temperature": config.temperature,
            "json_retry_attempts": config.json_retry_attempts,
            "trace_enabled": config.trace_enabled,
            "save_prompts": config.save_prompts,
            "retain_traces": config.retain_traces,
            "trace_dir": config.trace_dir,
            "run_id": config.run_id,
            "verbose_events": getattr(config, "verbose_events", False),
        }
        data.update(overrides)
        return cls(**data)


class ProtocolStepLog(BaseModel):
    """One protocol communication step."""

    step_idx: int
    description: str
    transmissions: list[tuple[int, int]] = Field(default_factory=list)
    sent_messages: int
    active_senders: list[int] = Field(default_factory=list)
    active_receivers: list[int] = Field(default_factory=list)


class ProtocolExperimentResult(BaseModel):
    """Full result of one finite protocol run."""

    run_id: str
    config: ProtocolRunnerConfig
    global_task: dict
    schedule: list[CommunicationStep] = Field(default_factory=list)
    step_logs: list[ProtocolStepLog] = Field(default_factory=list)
    agent_step_metrics: list[CFAgentStepMetric] = Field(default_factory=list)
    global_step_metrics: list[CFGlobalStepMetric] = Field(default_factory=list)
    final_agent_states: list[AgentState] = Field(default_factory=list)
    final_result: CFProtocolFinalResult
    total_steps: int
    total_messages: int
    total_model_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_retry_attempts: int = 0
    total_deterministic_fallbacks: int = 0
    agent_step_traces: list[AgentStepTrace] = Field(default_factory=list)
    trace_path: str | None = None

    def to_summary_dict(self) -> dict:
        return {
            "Task": "count_frequency_protocol",
            "Topology": self.config.topology_name,
            "Agents": self.config.n_agents,
            "ArraySize": int(self.global_task["array_length"]),
            "ValueMin": int(self.global_task["value_min"]),
            "ValueMax": int(self.global_task["value_max"]),
            "Seed": self.config.seed,
            "MergeMode": self.config.merge_mode,
            "InitMode": self.config.init_mode,
            "TotalSteps": self.total_steps,
            "TotalMessages": self.total_messages,
            "TotalModelCalls": self.total_model_calls,
            "TotalPromptTokens": self.total_prompt_tokens,
            "TotalCompletionTokens": self.total_completion_tokens,
            "TotalRetryAttempts": self.total_retry_attempts,
            "TotalDeterministicFallbacks": self.total_deterministic_fallbacks,
            "AggregationMethod": self.final_result.aggregation_method,
            "SelectedPrimary": self.final_result.selected_primary,
            "FinalRMSE": self.final_result.rmse,
            "FinalNormalizedL1Error": self.final_result.normalized_l1_error,
            "FinalExactMatch": self.final_result.exact_match,
            "VoteRMSE": self.final_result.vote.rmse,
            "VoteNormalizedL1Error": self.final_result.vote.normalized_l1_error,
            "VoteTopRatio": self.final_result.vote.top_ratio,
            "AverageRMSE": (
                self.final_result.average.rmse
                if self.final_result.average is not None
                else None
            ),
            "AverageNormalizedL1Error": (
                self.final_result.average.normalized_l1_error
                if self.final_result.average is not None
                else None
            ),
            "AverageIncludedAgents": (
                len(self.final_result.average.included_agents)
                if self.final_result.average is not None
                else 0
            ),
            "AnswerAgentIds": self.final_result.answer_agent_ids,
            "VoteAverageDisagreementRMSE": (
                self.final_result.vote_average_disagreement_rmse
            ),
            "FinalKey": self.final_result.final_key,
        }


class ProtocolRunner:
    """Run topology protocol schedules over existing agent states."""

    def __init__(
        self,
        *,
        config: ProtocolRunnerConfig,
        task_adapter: CountFrequencyTaskAdapter,
        global_task: dict,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.global_task = global_task
        self.llm_client = llm_client
        if self._needs_llm() and self.llm_client is None:
            self.llm_client = create_llm_client(self.config.llm_provider)

    def run(self) -> ProtocolExperimentResult:
        run_id = self._make_run_id()
        if self.config.protocol_spec is not None:
            schedule = build_protocol_schedule_from_spec(self.config.protocol_spec)
        else:
            schedule = build_protocol_schedule(
                self.config.topology_name,
                self.config.n_agents,
                star_center=self.config.star_center,
                include_star_broadcast=self.config.include_star_broadcast,
                random_seed=self.config.seed,
            )
        step_logs: list[ProtocolStepLog] = []
        agent_step_metrics: list[CFAgentStepMetric] = []
        global_step_metrics: list[CFGlobalStepMetric] = []
        total_messages = 0
        total_model_calls = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_retry_attempts = 0
        total_deterministic_fallbacks = 0
        agent_step_traces: list[AgentStepTrace] = []
        trace_path = None
        if self.config.trace_enabled and self.config.trace_dir:
            trace_path = reset_trace_jsonl(
                Path(self.config.trace_dir) / f"{run_id}.jsonl"
            )
        self._log_event(
            "run-start",
            (
                f"run={run_id} topology={self.config.topology_name} "
                f"agents={self.config.n_agents} init_mode={self.config.init_mode} "
                f"merge_mode={self.config.merge_mode} "
                f"steps={len(schedule)}"
            ),
        )
        (
            agent_states,
            init_traces,
            init_model_calls,
            init_prompt_tokens,
            init_completion_tokens,
            init_retry_attempts,
            init_deterministic_fallbacks,
        ) = self._initialize_agent_states(run_id=run_id)
        total_model_calls += init_model_calls
        total_prompt_tokens += init_prompt_tokens
        total_completion_tokens += init_completion_tokens
        total_retry_attempts += init_retry_attempts
        total_deterministic_fallbacks += init_deterministic_fallbacks
        if init_traces:
            if self.config.retain_traces:
                agent_step_traces.extend(init_traces)
            if trace_path is not None:
                append_traces_jsonl(init_traces, trace_path)

        initial_agent_metrics, initial_global_metric = self._record_metrics(
            agent_states=agent_states,
            step_idx=-1,
            phase="initial",
            send_counts=Counter(),
            receive_counts=Counter(),
        )
        agent_step_metrics.extend(initial_agent_metrics)
        global_step_metrics.append(initial_global_metric)

        for step in schedule:
            self._log_event(
                "step",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"description={step.description} "
                    f"scheduled_transmissions={len(step.transmissions)}"
                ),
            )
            previous_outboxes = {
                agent_id: state.outbox
                for agent_id, state in enumerate(agent_states)
            }
            inbox_by_receiver: dict[int, list[OutboxMessage]] = defaultdict(list)
            send_counts: Counter[int] = Counter()
            receive_counts: Counter[int] = Counter()
            for src, dst in step.transmissions:
                outbox = previous_outboxes.get(src)
                if outbox is None:
                    self._log_event(
                        "message-skip",
                        (
                            f"run={run_id} step={step.step_idx} "
                            f"round={step.step_idx + 1} {src} -> {dst} "
                            "skipped=no_outbox"
                        ),
                    )
                    continue
                inbox_by_receiver[dst].append(outbox)
                send_counts[src] += 1
                receive_counts[dst] += 1
                self._log_event(
                    "message",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} {src} -> {dst}"
                    ),
                )

            total_messages += sum(send_counts.values())
            next_states = list(agent_states)
            round_traces: list[AgentStepTrace] = []
            outcomes = self._process_receivers(
                agent_states=agent_states,
                inbox_by_receiver=inbox_by_receiver,
                step=step,
                run_id=run_id,
            )
            for receiver_id, outcome in outcomes.items():
                old_state = agent_states[receiver_id]
                new_belief = outcome.belief_state
                new_outbox = OutboxMessage.from_belief_state(
                    agent_id=receiver_id,
                    round_idx=step.step_idx,
                    belief_state=new_belief,
                )
                next_states[receiver_id] = old_state.model_copy(
                    update={
                        "belief_state": new_belief,
                        "inbox": [],
                        "outbox": new_outbox,
                    }
                )
                if outcome.llm_response is not None:
                    usage = outcome.llm_response.usage
                    total_model_calls += int(usage.model_calls)
                    total_prompt_tokens += int(usage.prompt_tokens)
                    total_completion_tokens += int(usage.completion_tokens)
                    total_retry_attempts += max(0, int(usage.model_calls) - 1)
                    if outcome.fallback_applied:
                        total_deterministic_fallbacks += 1
                    if self.config.trace_enabled:
                        trace = self._build_trace(
                            run_id=run_id,
                            step=step,
                            receiver_id=receiver_id,
                            inbox=inbox_by_receiver[receiver_id],
                            outcome=outcome,
                            outbox=new_outbox,
                        )
                        if self.config.retain_traces:
                            agent_step_traces.append(trace)
                        if trace_path is not None:
                            round_traces.append(trace)

            agent_states = next_states
            if trace_path is not None and round_traces:
                append_traces_jsonl(round_traces, trace_path)
            self._log_event(
                "step-done",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"delivered_messages={sum(send_counts.values())} "
                    f"active_senders={sorted(send_counts)} "
                    f"active_receivers={sorted(receive_counts)}"
                ),
            )
            step_logs.append(
                ProtocolStepLog(
                    step_idx=step.step_idx,
                    description=step.description,
                    transmissions=step.transmissions,
                    sent_messages=sum(send_counts.values()),
                    active_senders=sorted(send_counts),
                    active_receivers=sorted(receive_counts),
                )
            )
            step_agent_metrics, step_global_metric = self._record_metrics(
                agent_states=agent_states,
                step_idx=step.step_idx,
                phase="after_step",
                send_counts=send_counts,
                receive_counts=receive_counts,
            )
            agent_step_metrics.extend(step_agent_metrics)
            global_step_metrics.append(step_global_metric)

        final_result = run_cf_final_aggregation(
            agent_states=agent_states,
            global_task=self.global_task,
            task_adapter=self.task_adapter,
            topology_name=self.config.topology_name,
            star_center=self.config.star_center,
            average_include_min_coverage=self.config.average_include_min_coverage,
            selected_primary=self.config.selected_primary,
            answer_agent_ids_override=self._metadata_answer_agent_ids(),
        )
        self._log_event(
            "run-done",
            (
                f"run={run_id} steps={len(schedule)} messages={total_messages} "
                f"model_calls={total_model_calls} retries={total_retry_attempts} "
                f"deterministic_fallbacks={total_deterministic_fallbacks} "
                f"final_rmse={final_result.rmse:.6f} exact={final_result.exact_match}"
            ),
        )
        return ProtocolExperimentResult(
            run_id=run_id,
            config=self.config,
            global_task=self._compact_global_task(),
            schedule=schedule,
            step_logs=step_logs,
            agent_step_metrics=agent_step_metrics,
            global_step_metrics=global_step_metrics,
            final_agent_states=agent_states,
            final_result=final_result,
            total_steps=len(schedule),
            total_messages=total_messages,
            total_model_calls=total_model_calls,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_retry_attempts=total_retry_attempts,
            total_deterministic_fallbacks=total_deterministic_fallbacks,
            agent_step_traces=agent_step_traces,
            trace_path=trace_path,
        )

    def _initialize_agent_states(
        self,
        *,
        run_id: str,
    ) -> tuple[
        list[AgentState],
        list[AgentStepTrace],
        int,
        int,
        int,
        int,
        int,
    ]:
        observations = self.task_adapter.split_into_local_observations(
            self.global_task,
            self.config.n_agents,
        )
        if self.config.init_mode == "deterministic":
            states = []
            for agent_id, observation in enumerate(observations):
                belief = self.task_adapter.initial_protocol_belief(observation)
                states.append(
                    make_initial_agent_state(
                        local_observation=observation,
                        belief_state=belief,
                        agent_id=agent_id,
                        round_idx=0,
                    )
                )
            return states, [], 0, 0, 0, 0, 0

        if self.config.init_mode != "llm_local_solve":
            raise ValueError(f"unsupported init_mode: {self.config.init_mode}")
        if self.llm_client is None:
            raise RuntimeError("llm_client is required for llm_local_solve init")

        states: list[AgentState | None] = [None] * len(observations)
        traces: list[AgentStepTrace] = []
        total_model_calls = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_retry_attempts = 0
        total_deterministic_fallbacks = 0
        init_step = CommunicationStep(
            step_idx=-1,
            transmissions=[],
            description="llm_local_solve initialization",
        )

        outcomes: dict[int, _MergeOutcome] = {}
        max_workers = min(
            max(1, int(self.config.max_parallel_agents)),
            max(1, len(observations)),
        )
        if max_workers <= 1 or len(observations) <= 1:
            outcomes = {
                agent_id: self._initialize_agent_belief_with_llm(
                    observation=observation,
                    run_id=run_id,
                )
                for agent_id, observation in enumerate(observations)
            }
        else:
            self._log_event(
                "init-parallel",
                (
                    f"run={run_id} agents={len(observations)} "
                    f"max_parallel_agents={max_workers}"
                ),
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._initialize_agent_belief_with_llm,
                        observation=observation,
                        run_id=run_id,
                    ): agent_id
                    for agent_id, observation in enumerate(observations)
                }
                for future in as_completed(futures):
                    outcomes[futures[future]] = future.result()

        for agent_id, observation in enumerate(observations):
            outcome = outcomes[agent_id]
            new_outbox = OutboxMessage.from_belief_state(
                agent_id=agent_id,
                round_idx=0,
                belief_state=outcome.belief_state,
            )
            states[agent_id] = AgentState(
                local_observation=observation,
                belief_state=outcome.belief_state,
                inbox=[],
                outbox=new_outbox,
            )
            if outcome.llm_response is not None:
                usage = outcome.llm_response.usage
                total_model_calls += int(usage.model_calls)
                total_prompt_tokens += int(usage.prompt_tokens)
                total_completion_tokens += int(usage.completion_tokens)
                total_retry_attempts += max(0, int(usage.model_calls) - 1)
                if outcome.fallback_applied:
                    total_deterministic_fallbacks += 1
                if self.config.trace_enabled:
                    traces.append(
                        self._build_trace(
                            run_id=run_id,
                            step=init_step,
                            receiver_id=agent_id,
                            inbox=[],
                            outcome=outcome,
                            outbox=new_outbox,
                        )
                    )

        return (
            [state for state in states if state is not None],
            traces,
            total_model_calls,
            total_prompt_tokens,
            total_completion_tokens,
            total_retry_attempts,
            total_deterministic_fallbacks,
        )

    def _initialize_agent_belief_with_llm(
        self,
        *,
        observation: dict,
        run_id: str,
    ) -> _MergeOutcome:
        if self.llm_client is None:
            raise RuntimeError("llm_client is required for llm_local_solve init")

        deterministic_belief = self.task_adapter.initial_protocol_belief(observation)
        prompt = self.task_adapter.format_protocol_init_prompt(
            global_task=self.global_task,
            local_observation=observation,
        )
        current_prompt = prompt
        responses: list[LLMResponse] = []
        call_prompts: list[str] = []
        last_error: Exception | None = None
        agent_id = int(observation.get("agent_id", -1))

        for attempt_idx in range(self.config.json_retry_attempts + 1):
            call_prompts.append(current_prompt)
            self._log_event(
                "llm-init-call",
                (
                    f"run={run_id} agent={agent_id} "
                    f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1}"
                ),
            )
            try:
                response = self.llm_client.complete(
                    current_prompt,
                    model_name=self.config.model_name,
                    temperature=self.config.temperature,
                )
            except Exception as exc:
                self._log_event(
                    "llm-init-error",
                    (
                        f"run={run_id} agent={agent_id} "
                        f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1} "
                        f"provider_call_failed={type(exc).__name__}: {exc}"
                    ),
                )
                raise
            responses.append(response)
            try:
                llm_belief = parse_belief_state(response.text)
                belief = self.task_adapter.validate_protocol_initial_belief_state(
                    belief_state=llm_belief,
                    local_observation=observation,
                    global_task=self.global_task,
                )
                combined = self._combine_responses(responses, call_prompts)
                self._log_event(
                    "llm-init-success",
                    (
                        f"run={run_id} agent={agent_id} "
                        f"calls={combined.usage.model_calls} "
                        f"retries={max(0, combined.usage.model_calls - 1)} "
                        f"prompt_tokens={combined.usage.prompt_tokens} "
                        f"completion_tokens={combined.usage.completion_tokens}"
                    ),
                )
                return _MergeOutcome(
                    belief_state=belief,
                    llm_response=combined,
                    prompt=prompt,
                )
            except (ValueError, TypeError, ValidationError) as exc:
                last_error = exc
                if attempt_idx >= self.config.json_retry_attempts:
                    if self.config.allow_deterministic_repair:
                        self._log_event(
                            "init-retry-failed",
                            (
                                f"run={run_id} agent={agent_id} "
                                f"attempts={attempt_idx + 1} "
                                "deterministic_repair=applied "
                                f"last_error={exc}"
                            ),
                        )
                        return _MergeOutcome(
                            belief_state=deterministic_belief,
                            llm_response=self._combine_responses(responses, call_prompts),
                            prompt=prompt,
                            parse_error=str(exc),
                            fallback_applied=True,
                        )
                    self._log_event(
                        "init-retry-failed",
                        (
                            f"run={run_id} agent={agent_id} "
                            f"attempts={attempt_idx + 1} "
                            "deterministic_repair=disabled "
                            f"last_error={exc}"
                        ),
                    )
                    raise ValueError(
                        "LLM failed to return a valid CF local init belief_state "
                        f"after {attempt_idx + 1} call(s). Last error: {exc}"
                    ) from exc
                self._log_event(
                    "init-retry",
                    (
                        f"run={run_id} agent={agent_id} "
                        f"failed_attempt={attempt_idx + 1}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"next_attempt={attempt_idx + 2}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"error={exc}"
                    ),
                )
                current_prompt = build_json_retry_prompt(
                    original_prompt=prompt,
                    invalid_response=response.text,
                    error_message=str(exc),
                    attempt_idx=attempt_idx + 1,
                )

        if self.config.allow_deterministic_repair:
            self._log_event(
                "init-retry-failed",
                (
                    f"run={run_id} agent={agent_id} "
                    "deterministic_repair=applied "
                    f"last_error={last_error}"
                ),
            )
            return _MergeOutcome(
                belief_state=deterministic_belief,
                llm_response=self._combine_responses(responses, call_prompts),
                prompt=prompt,
                parse_error=str(last_error) if last_error else None,
                fallback_applied=True,
            )
        raise ValueError(f"LLM local init failed: {last_error}")

    def _merge_receiver_belief(self, state: AgentState) -> BeliefState:
        return self.task_adapter.merge_protocol_inbox(
            old_belief_state=state.belief_state,
            inbox=state.inbox,
            global_task=self.global_task,
        )

    def _process_receivers(
        self,
        *,
        agent_states: list[AgentState],
        inbox_by_receiver: dict[int, list[OutboxMessage]],
        step: CommunicationStep,
        run_id: str,
    ) -> dict[int, _MergeOutcome]:
        if self.config.merge_mode == "deterministic":
            return {
                receiver_id: _MergeOutcome(
                    belief_state=self._merge_receiver_belief(
                        agent_states[receiver_id].model_copy(update={"inbox": inbox})
                    )
                )
                for receiver_id, inbox in inbox_by_receiver.items()
            }

        max_workers = min(
            max(1, int(self.config.max_parallel_agents)),
            max(1, len(inbox_by_receiver)),
        )
        if max_workers <= 1 or len(inbox_by_receiver) <= 1:
            return {
                receiver_id: self._merge_receiver_belief_with_llm(
                    state=agent_states[receiver_id].model_copy(update={"inbox": inbox}),
                    step=step,
                    run_id=run_id,
                )
                for receiver_id, inbox in inbox_by_receiver.items()
            }

        outcomes: dict[int, _MergeOutcome] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._merge_receiver_belief_with_llm,
                    state=agent_states[receiver_id].model_copy(update={"inbox": inbox}),
                    step=step,
                    run_id=run_id,
                ): receiver_id
                for receiver_id, inbox in inbox_by_receiver.items()
            }
            for future in as_completed(futures):
                outcomes[futures[future]] = future.result()
        return outcomes

    def _merge_receiver_belief_with_llm(
        self,
        *,
        state: AgentState,
        step: CommunicationStep,
        run_id: str,
    ) -> _MergeOutcome:
        if self.llm_client is None:
            raise RuntimeError("llm_client is required for LLM protocol merge modes")

        verified_belief = self._merge_receiver_belief(state)
        prompt = self.task_adapter.format_protocol_merge_prompt(
            merge_mode=self.config.merge_mode,
            global_task=self.global_task,
            local_observation=state.local_observation,
            old_belief_state=state.belief_state,
            inbox=state.inbox,
            deterministic_belief=verified_belief,
        )
        current_prompt = prompt
        responses: list[LLMResponse] = []
        call_prompts: list[str] = []
        last_error: Exception | None = None

        for attempt_idx in range(self.config.json_retry_attempts + 1):
            call_prompts.append(current_prompt)
            self._log_event(
                "llm-call",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"receiver={state.local_observation.get('agent_id')} "
                    f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1} "
                    f"inbox_from={[message.agent_id for message in state.inbox]}"
                ),
            )
            try:
                response = self.llm_client.complete(
                    current_prompt,
                    model_name=self.config.model_name,
                    temperature=self.config.temperature,
                )
            except Exception as exc:
                self._log_event(
                    "llm-error",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} "
                        f"receiver={state.local_observation.get('agent_id')} "
                        f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1} "
                        f"provider_call_failed={type(exc).__name__}: {exc}"
                    ),
                )
                raise
            responses.append(response)
            try:
                llm_belief = parse_belief_state(response.text)
                if self.config.merge_mode == "llm_belief_merge":
                    belief = self.task_adapter.apply_verified_protocol_merge(
                        llm_belief_state=llm_belief,
                        verified_belief_state=verified_belief,
                    )
                elif self.config.merge_mode == "llm_full_merge":
                    belief = self.task_adapter.validate_protocol_belief_state(
                        belief_state=llm_belief,
                        global_task=self.global_task,
                        n_agents=self.config.n_agents,
                        transport_belief_state=verified_belief,
                    )
                else:
                    raise ValueError(f"unsupported merge_mode: {self.config.merge_mode}")
                combined = self._combine_responses(responses, call_prompts)
                self._log_event(
                    "llm-success",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} "
                        f"receiver={state.local_observation.get('agent_id')} "
                        f"calls={combined.usage.model_calls} "
                        f"retries={max(0, combined.usage.model_calls - 1)} "
                        f"prompt_tokens={combined.usage.prompt_tokens} "
                        f"completion_tokens={combined.usage.completion_tokens}"
                    ),
                )
                return _MergeOutcome(
                    belief_state=belief,
                    llm_response=combined,
                    prompt=prompt,
                )
            except (ValueError, TypeError, ValidationError) as exc:
                last_error = exc
                if attempt_idx >= self.config.json_retry_attempts:
                    if self.config.allow_deterministic_repair:
                        self._log_event(
                            "retry-failed",
                            (
                                f"run={run_id} step={step.step_idx} "
                                f"round={step.step_idx + 1} "
                                f"receiver={state.local_observation.get('agent_id')} "
                                f"attempts={attempt_idx + 1} "
                                "deterministic_repair=applied "
                                f"last_error={exc}"
                            ),
                        )
                        return _MergeOutcome(
                            belief_state=verified_belief,
                            llm_response=self._combine_responses(responses, call_prompts),
                            prompt=prompt,
                            parse_error=str(exc),
                            fallback_applied=True,
                        )
                    self._log_event(
                        "retry-failed",
                        (
                            f"run={run_id} step={step.step_idx} "
                            f"round={step.step_idx + 1} "
                            f"receiver={state.local_observation.get('agent_id')} "
                            f"attempts={attempt_idx + 1} "
                            "deterministic_repair=disabled "
                            f"last_error={exc}"
                        ),
                    )
                    raise ValueError(
                        "LLM failed to return a valid CF protocol belief_state "
                        f"after {attempt_idx + 1} call(s). Last error: {exc}"
                    ) from exc
                self._log_event(
                    "retry",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} "
                        f"receiver={state.local_observation.get('agent_id')} "
                        f"failed_attempt={attempt_idx + 1}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"next_attempt={attempt_idx + 2}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"error={exc}"
                    ),
                )
                current_prompt = build_json_retry_prompt(
                    original_prompt=prompt,
                    invalid_response=response.text,
                    error_message=str(exc),
                    attempt_idx=attempt_idx + 1,
                )

        if self.config.allow_deterministic_repair:
            self._log_event(
                "retry-failed",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"receiver={state.local_observation.get('agent_id')} "
                    "deterministic_repair=applied "
                    f"last_error={last_error}"
                ),
            )
            return _MergeOutcome(
                belief_state=verified_belief,
                llm_response=self._combine_responses(responses, call_prompts),
                prompt=prompt,
                parse_error=str(last_error) if last_error else None,
                fallback_applied=True,
            )
        raise ValueError(f"LLM protocol merge failed: {last_error}")

    def _log_event(self, event_type: str, message: str) -> None:
        if self.config.verbose_events:
            print(f"[{event_type}] {message}", flush=True)

    def _needs_llm(self) -> bool:
        return (
            self.config.init_mode == "llm_local_solve"
            or self.config.merge_mode != "deterministic"
        )

    def _combine_responses(
        self,
        responses: list[LLMResponse],
        call_prompts: list[str],
    ) -> LLMResponse:
        if not responses:
            return LLMResponse(text="{}")
        return LLMResponse(
            text=responses[-1].text,
            usage=combine_usage([response.usage for response in responses]),
            raw_responses=[response.text for response in responses],
            raw_prompts=call_prompts,
        )

    def _build_trace(
        self,
        *,
        run_id: str,
        step: CommunicationStep,
        receiver_id: int,
        inbox: list[OutboxMessage],
        outcome: _MergeOutcome,
        outbox: OutboxMessage,
    ) -> AgentStepTrace:
        response = outcome.llm_response or LLMResponse(text="")
        raw_responses = response.raw_responses or ([response.text] if response.text else [])
        raw_prompts = response.raw_prompts or ([outcome.prompt] if outcome.prompt else [])
        trace_prompts = raw_prompts if self.config.save_prompts else [""] * len(raw_prompts)
        return AgentStepTrace(
            run_id=run_id,
            round_idx=step.step_idx,
            communication_round=step.step_idx + 1,
            agent_id=receiver_id,
            topology_name=self.config.topology_name,
            neighbors=[message.agent_id for message in inbox],
            inbox=[message.model_dump() for message in inbox],
            prompt=outcome.prompt if self.config.save_prompts else "",
            raw_response=response.text,
            raw_responses=raw_responses,
            raw_prompts=trace_prompts,
            llm_calls=[
                {
                    "call_idx": idx,
                    "prompt": trace_prompts[idx] if idx < len(trace_prompts) else "",
                    "raw_response": raw_responses[idx] if idx < len(raw_responses) else "",
                }
                for idx in range(max(len(trace_prompts), len(raw_responses)))
            ],
            parsed_belief_state=outcome.belief_state.model_dump(mode="json"),
            outbox=outbox.model_dump(),
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model_calls=response.usage.model_calls,
            retry_attempts=max(0, response.usage.model_calls - 1),
            parse_error=outcome.parse_error,
        )

    def _record_metrics(
        self,
        *,
        agent_states: list[AgentState],
        step_idx: int,
        phase: str,
        send_counts: Counter[int],
        receive_counts: Counter[int],
    ) -> tuple[list[CFAgentStepMetric], CFGlobalStepMetric]:
        return build_cf_step_metrics(
            agent_states=agent_states,
            global_task=self.global_task,
            task_adapter=self.task_adapter,
            topology_name=self.config.topology_name,
            step_idx=step_idx,
            phase=phase,
            send_counts=send_counts,
            receive_counts=receive_counts,
            average_include_min_coverage=self.config.average_include_min_coverage,
        )

    def _compact_global_task(self) -> dict:
        compact = {
            key: value
            for key, value in self.global_task.items()
            if key not in {"array"}
        }
        compact["array_length"] = int(self.global_task["array_length"])
        return compact

    def _metadata_answer_agent_ids(self) -> list[int] | None:
        spec = self.config.protocol_spec
        if spec is None:
            return None
        selected_primary = spec.metadata.get("selected_primary")
        if selected_primary is None:
            return None
        try:
            agent_id = int(selected_primary)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "protocol_spec.metadata.selected_primary must be an integer agent id"
            ) from exc
        if agent_id < 0 or agent_id >= self.config.n_agents:
            raise ValueError(
                "protocol_spec.metadata.selected_primary is outside valid "
                f"range 0..{self.config.n_agents - 1}: {agent_id}"
            )
        return [agent_id]

    def _make_run_id(self) -> str:
        if self.config.run_id:
            return self.config.run_id
        return (
            f"protocol_{self.config.topology_name}_n{self.config.n_agents}_"
            f"seed{self.config.seed}_{time_ns()}"
        )
