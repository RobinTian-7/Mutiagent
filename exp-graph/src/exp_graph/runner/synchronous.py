"""Synchronous multi-round experiment runner."""

from __future__ import annotations

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
from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import create_llm_client
from exp_graph.metrics.logger import MetricsSummary, build_metrics_summary
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.base import TaskAdapter
from exp_graph.topology import create_topology


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

    config: ExperimentConfig
    global_task: dict[str, Any]
    final_result: FinalResult
    metrics: MetricsSummary
    round_logs: list[RoundLog] = Field(default_factory=list)
    final_agent_states: list[AgentState] = Field(default_factory=list)


class SynchronousRunner:
    """Synchronous runner with commit barriers between rounds."""

    def __init__(
        self,
        *,
        config: ExperimentConfig,
        task_adapter: TaskAdapter,
        global_task: dict[str, Any],
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.global_task = global_task
        self.topology = create_topology(config.topology_name)
        self.llm_client = llm_client or create_llm_client(config.llm_provider)

    def run(self) -> ExperimentResult:
        """Run the experiment to consensus or max_rounds."""
        agent_states = self._initialize_agent_states()
        agents = self._initialize_agents()
        round_logs: list[RoundLog] = []
        stopped_by_runtime_consensus = False
        last_consensus = self._detect_consensus(agent_states)

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

            staged: list[tuple[BeliefState, OutboxMessage]] = []
            prompt_tokens = 0
            completion_tokens = 0
            model_calls = 0

            for agent_id, state in enumerate(agent_states):
                inbox = [
                    previous_outboxes[neighbor_id]
                    for neighbor_id in neighbors_by_agent[agent_id]
                    if previous_outboxes[neighbor_id] is not None
                ]
                staged_state = state.model_copy(update={"inbox": inbox})
                new_belief, new_outbox, llm_response = agents[agent_id].step(
                    global_task=self.global_task,
                    state=staged_state,
                    round_idx=round_idx,
                )
                staged.append((new_belief, new_outbox))
                model_calls += 1
                prompt_tokens += llm_response.usage.prompt_tokens
                completion_tokens += llm_response.usage.completion_tokens

            committed_states = []
            for agent_id, state in enumerate(agent_states):
                new_belief, new_outbox = staged[agent_id]
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
        )
        return ExperimentResult(
            config=self.config,
            global_task=self.global_task,
            final_result=final_result,
            metrics=metrics,
            round_logs=round_logs,
            final_agent_states=agent_states,
        )

    def _initialize_agent_states(self) -> list[AgentState]:
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
