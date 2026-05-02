"""Synchronous multi-round experiment runner."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import time_ns
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.agents import (
    AgentConfig,
    AgentState,
    BeliefState,
    SolverAgent,
    make_initial_agent_state,
)
from exp_graph.aggregator.final_reducer import FinalResult, run_final_reducer
from exp_graph.aggregator.runtime_consensus import (
    RuntimeConsensusResult,
    collect_runtime_keys,
    count_keys,
    detect_runtime_consensus,
)
from exp_graph.configs.runtime import ExperimentConfig
from exp_graph.hierarchy import HierarchyPlan, build_hierarchy_local_observations
from exp_graph.hierarchy.dispatch import DispatchTree
from exp_graph.llm.base import LLMClient, LLMResponse
from exp_graph.llm.factory import create_llm_client
from exp_graph.metrics.logger import MetricsSummary, build_metrics_summary
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.base import TaskAdapter
from exp_graph.topology import Topology, create_topology
from exp_graph.tracing import AgentStepTrace, append_traces_jsonl, reset_trace_jsonl


def _truncate_key(value: str | None, *, limit: int = 64) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class RoundLog(BaseModel):
    """Structured log for one synchronous round."""

    round_idx: int
    neighbors: dict[int, list[int]]
    consensus: RuntimeConsensusResult
    model_calls: int
    prompt_tokens: int
    completion_tokens: int


class ExperimentResult(BaseModel):
    """Full result of one experiment run."""

    run_id: str
    config: ExperimentConfig
    global_task: dict[str, Any]
    final_result: FinalResult
    metrics: MetricsSummary
    round_logs: list[RoundLog] = Field(default_factory=list)
    final_agent_states: list[AgentState] = Field(default_factory=list)
    agent_step_traces: list[AgentStepTrace] = Field(default_factory=list)
    trace_path: str | None = None
    stop_reason: str


class SynchronousRunner:
    """Synchronous runner with commit barriers between rounds."""

    def __init__(
        self,
        *,
        config: ExperimentConfig,
        task_adapter: TaskAdapter,
        global_task: dict[str, Any],
        llm_client: LLMClient | None = None,
        topology: Topology | None = None,
        hierarchy_plan: HierarchyPlan | None = None,
        hierarchy_dispatch: DispatchTree | None = None,
    ) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.global_task = global_task
        self.hierarchy_plan = hierarchy_plan
        self.hierarchy_dispatch = hierarchy_dispatch
        if topology is not None:
            self.topology = topology
        else:
            self.topology = create_topology(config.topology_name)
        if hierarchy_plan is not None:
            if hierarchy_plan.n_total != self.config.n_agents:
                raise ValueError(
                    "ExperimentConfig.n_agents="
                    f"{self.config.n_agents} does not match "
                    f"HierarchyPlan.n_total={hierarchy_plan.n_total}; "
                    "the runner expects them to be equal so agent ids align."
                )
        self.llm_client = llm_client or create_llm_client(config.llm_provider)

    def run(self) -> ExperimentResult:
        """Run the experiment to consensus or max_rounds."""
        run_id = self._make_run_id()
        agent_states = self._initialize_agent_states()
        agents = self._initialize_agents()
        round_logs: list[RoundLog] = []
        agent_step_traces: list[AgentStepTrace] = []
        trace_path = None
        if self.config.trace_enabled and self.config.trace_dir:
            trace_path = reset_trace_jsonl(
                Path(self.config.trace_dir) / f"{run_id}.jsonl"
            )
        stopped_by_runtime_consensus = False
        last_consensus = self._detect_consensus(agent_states)

        if self.config.verbose_events:
            self._log(
                "runner.start",
                f"run_id={run_id} n_agents={self.config.n_agents} "
                f"max_rounds={self.config.max_rounds} "
                f"max_parallel={self._max_parallel_agents()} "
                f"topology={self.config.topology_name}",
            )

        for round_idx in range(self.config.max_rounds):
            previous_outboxes = {
                agent_id: state.outbox for agent_id, state in enumerate(agent_states)
            }
            neighbors_by_agent = {
                agent_id: self.topology.get_neighbors(
                    agent_id=agent_id,
                    round_idx=round_idx,
                    n_agents=self.config.n_agents,
                )
                for agent_id in range(self.config.n_agents)
            }

            staged: list[tuple[BeliefState, OutboxMessage] | None] = [
                None for _ in range(self.config.n_agents)
            ]
            prompt_tokens = 0
            completion_tokens = 0
            model_calls = 0
            round_traces: list[AgentStepTrace] = []

            if self.config.verbose_events:
                self._log(
                    "round.start",
                    f"round={round_idx + 1}/{self.config.max_rounds} "
                    f"agents={self.config.n_agents}",
                )

            def process_agent(agent_id, state, current_round_idx):
                inbox = [
                    previous_outboxes[neighbor_id]
                    for neighbor_id in neighbors_by_agent[agent_id]
                    if previous_outboxes[neighbor_id] is not None
                ]
                staged_state = state.model_copy(update={"inbox": inbox})
                if self.config.trace_enabled:
                    (
                        new_belief,
                        new_outbox,
                        llm_response,
                        trace,
                    ) = agents[agent_id].step_with_trace(
                        global_task=self.global_task,
                        state=staged_state,
                        round_idx=current_round_idx,
                        run_id=run_id,
                        topology_name=self.config.topology_name,
                        neighbors=neighbors_by_agent[agent_id],
                        include_prompt=self.config.save_prompts,
                    )
                else:
                    new_belief, new_outbox, llm_response = agents[agent_id].step(
                        global_task=self.global_task,
                        state=staged_state,
                        round_idx=current_round_idx,
                    )
                    trace = None
                return agent_id, new_belief, new_outbox, llm_response, trace, len(inbox)

            with ThreadPoolExecutor(max_workers=self._max_parallel_agents()) as executor:
                futures = [
                    executor.submit(process_agent, i, s, round_idx)
                    for i, s in enumerate(agent_states)
                ]
                for future in as_completed(futures):
                    (
                        agent_id,
                        new_belief,
                        new_outbox,
                        llm_response,
                        trace,
                        inbox_size,
                    ) = future.result()
                    staged[agent_id] = (new_belief, new_outbox)
                    if trace is not None:
                        if self.config.retain_traces:
                            agent_step_traces.append(trace)
                        if trace_path is not None:
                            round_traces.append(trace)
                    model_calls += llm_response.usage.model_calls
                    prompt_tokens += llm_response.usage.prompt_tokens
                    completion_tokens += llm_response.usage.completion_tokens
                    if self.config.verbose_events:
                        self._log_agent_step(
                            round_idx=round_idx,
                            agent_id=agent_id,
                            agent_states=agent_states,
                            inbox_size=inbox_size,
                            new_belief=new_belief,
                            llm_response=llm_response,
                        )

            if trace_path is not None and round_traces:
                append_traces_jsonl(round_traces, trace_path)

            committed_states = []
            for agent_id, state in enumerate(agent_states):
                staged_update = staged[agent_id]
                if staged_update is None:
                    raise RuntimeError(f"agent {agent_id} did not produce a staged update")
                new_belief, new_outbox = staged_update
                committed_states.append(
                    state.model_copy(
                        update={
                            "belief_state": new_belief,
                            "outbox": new_outbox,
                            "inbox": [],
                        }
                    )
                )
            agent_states = committed_states

            last_consensus = self._detect_consensus(agent_states)
            if self.config.verbose_events:
                self._log(
                    "round.end",
                    f"round={round_idx + 1}/{self.config.max_rounds} "
                    f"top_key={_truncate_key(last_consensus.top_key)} "
                    f"top_ratio={last_consensus.top_ratio:.2f} "
                    f"reached={last_consensus.consensus_reached} "
                    f"prompt_tokens={prompt_tokens} "
                    f"completion_tokens={completion_tokens}",
                )
            round_logs.append(
                RoundLog(
                    round_idx=round_idx,
                    neighbors=neighbors_by_agent,
                    consensus=last_consensus,
                    model_calls=model_calls,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )

            if last_consensus.consensus_reached:
                stopped_by_runtime_consensus = True
                break

        stop_reason = (
            "runtime_consensus"
            if stopped_by_runtime_consensus
            else "max_rounds"
            if round_logs
            else "no_rounds"
        )
        final_result = run_final_reducer(
            agent_states=agent_states,
            global_task=self.global_task,
            task_adapter=self.task_adapter,
            runtime_consensus=last_consensus,
            round_idx=round_logs[-1].round_idx if round_logs else -1,
            stopped_by_runtime_consensus=stopped_by_runtime_consensus,
            config=self.config,
            llm_client=self.llm_client,
        )
        metrics = build_metrics_summary(
            config=self.config,
            global_task=self.global_task,
            task_adapter=self.task_adapter,
            final_result=final_result,
            round_logs=round_logs,
            stop_reason=stop_reason,
        )
        return ExperimentResult(
            run_id=run_id,
            config=self.config,
            global_task=self.global_task,
            final_result=final_result,
            metrics=metrics,
            round_logs=round_logs,
            final_agent_states=agent_states,
            agent_step_traces=agent_step_traces,
            trace_path=trace_path,
            stop_reason=stop_reason,
        )

    def _initialize_agent_states(self) -> list[AgentState]:
        if self.hierarchy_plan is not None:
            observations = build_hierarchy_local_observations(
                plan=self.hierarchy_plan,
                task_adapter=self.task_adapter,
                global_task=self.global_task,
                dispatch=self.hierarchy_dispatch,
            )
        else:
            observations = self.task_adapter.split_into_local_observations(
                global_task=self.global_task,
                n_agents=self.config.n_agents,
            )
        states = []
        for agent_id, observation in enumerate(observations):
            raw_belief = self.task_adapter.initial_local_solve(observation)
            belief = BeliefState(**raw_belief)
            belief.consensus_key = self.task_adapter.normalize_consensus_key(
                belief.consensus_key or belief.proposal
            )
            states.append(
                make_initial_agent_state(
                    local_observation=observation,
                    belief_state=belief,
                    agent_id=agent_id,
                    round_idx=0,
                )
            )
        return states

    def _initialize_agents(self) -> list[SolverAgent]:
        return [
            SolverAgent(
                config=AgentConfig(
                    agent_id=agent_id,
                    role="solver",
                    model_name=self.config.model_name,
                    prompt_template_name=self.config.prompt_template_name,
                    json_retry_attempts=self.config.json_retry_attempts,
                    temperature=self.config.temperature,
                ),
                task_adapter=self.task_adapter,
                llm_client=self.llm_client,
            )
            for agent_id in range(self.config.n_agents)
        ]

    def _detect_consensus(self, agent_states: list[AgentState]) -> RuntimeConsensusResult:
        keys = collect_runtime_keys(agent_states)
        key_counts = count_keys(keys)
        return detect_runtime_consensus(
            key_counts=key_counts,
            num_agents=self.config.n_agents,
            threshold=self.config.consensus_threshold,
        )

    def _max_parallel_agents(self) -> int:
        configured = self.config.max_parallel_agents
        if configured is None:
            return self.config.n_agents
        if configured < 1:
            raise ValueError("max_parallel_agents must be positive when set")
        return min(self.config.n_agents, configured)

    def _log(self, event_type: str, message: str) -> None:
        print(f"[{event_type}] {message}", flush=True)

    def _log_agent_step(
        self,
        *,
        round_idx: int,
        agent_id: int,
        agent_states: list[AgentState],
        inbox_size: int,
        new_belief: BeliefState,
        llm_response: LLMResponse,
    ) -> None:
        observation = agent_states[agent_id].local_observation
        role = str(observation.get("role") or "agent")
        status = (
            new_belief.status.value
            if hasattr(new_belief.status, "value")
            else str(new_belief.status)
        )
        usage = llm_response.usage
        self._log(
            "agent.step",
            f"round={round_idx + 1} agent={agent_id} role={role} "
            f"inbox={inbox_size} prompt_tokens={usage.prompt_tokens} "
            f"completion_tokens={usage.completion_tokens} "
            f"calls={usage.model_calls} "
            f"-> status={status} "
            f"key={_truncate_key(new_belief.consensus_key)}",
        )

    def _make_run_id(self) -> str:
        if self.config.run_id:
            return self.config.run_id
        return (
            f"{self.config.topology_name}_"
            f"n{self.config.n_agents}_"
            f"r{self.config.max_rounds}_"
            f"seed{self.config.seed}_"
            f"{time_ns()}"
        )
