"""LLM-backed solver agent."""

from __future__ import annotations

from typing import Any

from exp_graph.agents.schemas import AgentConfig, AgentState, BeliefState
from exp_graph.llm.base import LLMClient, LLMResponse
from exp_graph.llm.parser import parse_belief_state
from exp_graph.llm.prompts import build_solver_prompt
from exp_graph.messaging.messages import OutboxMessage
from exp_graph.tasks.base import TaskAdapter


class SolverAgent:
    """One synchronous solver agent."""

    def __init__(
        self,
        config: AgentConfig,
        task_adapter: TaskAdapter,
        llm_client: LLMClient,
    ) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.llm_client = llm_client

    def build_prompt(
        self,
        *,
        global_task: dict[str, Any],
        state: AgentState,
    ) -> str:
        return build_solver_prompt(
            task_adapter=self.task_adapter,
            global_task=global_task,
            local_observation=state.local_observation,
            old_belief_state=state.belief_state,
            inbox=state.inbox,
        )

    def update_belief_state(
        self,
        *,
        prompt: str,
    ) -> tuple[BeliefState, LLMResponse]:
        response = self.llm_client.complete(prompt, model_name=self.config.model_name)
        belief_state = parse_belief_state(response.text)
        normalized_key = self.task_adapter.normalize_consensus_key(
            belief_state.consensus_key or belief_state.proposal
        )
        belief_state.consensus_key = normalized_key
        return belief_state, response

    def build_outbox(
        self,
        *,
        belief_state: BeliefState,
        round_idx: int,
    ) -> OutboxMessage:
        return OutboxMessage.from_belief_state(
            agent_id=self.config.agent_id,
            round_idx=round_idx,
            belief_state=belief_state,
        )

    def step(
        self,
        *,
        global_task: dict[str, Any],
        state: AgentState,
        round_idx: int,
    ) -> tuple[BeliefState, OutboxMessage, LLMResponse]:
        """Run one update without mutating shared global state."""
        prompt = self.build_prompt(global_task=global_task, state=state)
        belief_state, response = self.update_belief_state(prompt=prompt)
        outbox = self.build_outbox(belief_state=belief_state, round_idx=round_idx)
        return belief_state, outbox, response
