"""Task-agnostic protocol adapter interface for ProtocolRunner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from typing import TYPE_CHECKING, Any

from exp_graph.agents.schemas import AgentState, BeliefState
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.base import TaskAdapter

# Imported lazily inside the default methods to avoid an import cycle:
# count_frequency -> protocol_adapter -> aggregator/metrics __init__ -> cf_* -> count_frequency.
if TYPE_CHECKING:
    from exp_graph.aggregator.protocol_final import ProtocolFinalResult
    from exp_graph.metrics.protocol import (
        ProtocolAgentStepMetric,
        ProtocolGlobalStepMetric,
    )


class ProtocolTaskAdapter(TaskAdapter, ABC):
    """Adapter that ProtocolRunner drives. CF and generic tasks both implement this.

    The 7 belief methods below carry the per-agent protocol semantics; the
    finalize/step-metric/answer methods let the runner stay task-agnostic.
    """

    # --- per-agent protocol belief lifecycle (already on CountFrequencyTaskAdapter) ---
    @abstractmethod
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState: ...

    @abstractmethod
    def format_protocol_init_prompt(
        self, *, global_task: dict[str, Any], local_observation: dict[str, Any]
    ) -> str: ...

    @abstractmethod
    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState: ...

    @abstractmethod
    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState: ...

    @abstractmethod
    def format_protocol_merge_prompt(
        self,
        *,
        merge_mode: str,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        deterministic_belief: BeliefState | None = None,
    ) -> str: ...

    @abstractmethod
    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState: ...

    @abstractmethod
    def validate_protocol_belief_state(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> BeliefState: ...

    # --- answer extraction / scoring (used by generic aggregation + metrics) ---
    @abstractmethod
    def extract_protocol_answer(self, belief_state: BeliefState) -> Any: ...

    @abstractmethod
    def protocol_answer_key(self, answer: Any) -> str: ...

    @abstractmethod
    def score_protocol_answer(
        self, answer: Any, global_task: dict[str, Any]
    ) -> dict[str, Any]:
        """Return at least {'primary_metric': float, 'exact_match': bool}."""
        ...

    @abstractmethod
    def compute_protocol_agent_metrics(
        self, *, belief_state: BeliefState, global_task: dict[str, Any], n_agents: int
    ) -> dict[str, Any]:
        """Return at least {'coverage_ratio': float, 'primary_metric': float, 'exact_match': bool}."""
        ...

    # --- holder selection + finalize/metrics: generic defaults (CF overrides finalize/step) ---
    def answer_holders(
        self, *, topology_name: str, n_agents: int, star_center: int
    ) -> list[int]:
        return list(range(n_agents))

    def finalize_protocol(
        self,
        *,
        agent_states: list[AgentState],
        global_task: dict[str, Any],
        topology_name: str,
        star_center: int = 0,
        average_include_min_coverage: float = 1.0,
        selected_primary: str = "topology_default",
        answer_agent_ids_override: list[int] | None = None,
    ) -> ProtocolFinalResult:
        from exp_graph.aggregator.protocol_final import run_protocol_vote_aggregation

        ids = answer_agent_ids_override or self.answer_holders(
            topology_name=topology_name,
            n_agents=len(agent_states),
            star_center=star_center,
        )
        return run_protocol_vote_aggregation(
            agent_states=agent_states,
            global_task=global_task,
            task_adapter=self,
            answer_agent_ids=ids,
        )

    def build_protocol_step_metrics(
        self,
        *,
        agent_states: list[AgentState],
        global_task: dict[str, Any],
        topology_name: str,
        step_idx: int,
        phase: str,
        send_counts: Counter[int],
        receive_counts: Counter[int],
        average_include_min_coverage: float = 1.0,
    ) -> tuple[list[ProtocolAgentStepMetric], ProtocolGlobalStepMetric]:
        from exp_graph.metrics.protocol import (
            build_protocol_step_metrics as _build_protocol_step_metrics,
        )

        return _build_protocol_step_metrics(
            agent_states=agent_states,
            global_task=global_task,
            task_adapter=self,
            topology_name=topology_name,
            step_idx=step_idx,
            phase=phase,
            send_counts=send_counts,
            receive_counts=receive_counts,
        )
