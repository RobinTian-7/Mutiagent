"""Shared state for the LangGraph multi-agent workflow.

Paper reference (Sec 3.1):
  "Agents execute over the task tree by iteratively selecting, decomposing,
   and solving tasks while communicating over the active topology."

The state is designed for LangGraph's state-passing architecture.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from src.schemas.claims import Claim
from src.schemas.events import Event
from src.schemas.subtasks import Subtask


def _append_list(a: list, b: list) -> list:
    """Reducer that appends new items to existing list."""
    return a + b


class AgentSystemState(BaseModel):
    """Global mutable state passed through the LangGraph workflow.

    Uses append-only semantics for events and claims, consistent with
    the paper's trace-based approach.
    """

    # Append-only coordination traces
    events: Annotated[list[Event], _append_list] = Field(default_factory=list)
    claims: Annotated[list[Claim], _append_list] = Field(default_factory=list)
    subtasks: Annotated[list[Subtask], _append_list] = Field(default_factory=list)

    # Coordination activity counts per claim (x_i(t) in paper Eq. 3)
    claim_activity: dict[str, int] = Field(default_factory=dict)

    # Current execution round
    current_round: int = 0
    max_rounds: int = 20  # Paper: "20 execution steps per run"

    # Run metadata
    run_id: str = "run_0"
    topology_name: str = "chain"
    task_domain: str = "reasoning"
    num_agents: int = 8

    # DTI state per cascade: root_claim_id -> (t_r, M_r)
    dti_state: dict[str, tuple[int, int]] = Field(default_factory=dict)
    dti_enabled: bool = False
