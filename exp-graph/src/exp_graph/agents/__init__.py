"""Agent configs, state schemas, and agent runtime."""

from typing import TYPE_CHECKING

from exp_graph.agents.schemas import (
    AgentConfig,
    AgentState,
    BeliefState,
    BeliefStatus,
    make_initial_agent_state,
)

if TYPE_CHECKING:
    from exp_graph.agents.agent import SolverAgent

__all__ = [
    "SolverAgent",
    "AgentConfig",
    "AgentState",
    "BeliefState",
    "BeliefStatus",
    "make_initial_agent_state",
]


def __getattr__(name: str):
    if name == "SolverAgent":
        from exp_graph.agents.agent import SolverAgent

        return SolverAgent
    raise AttributeError(name)
