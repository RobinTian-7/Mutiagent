"""Hierarchy plan data structures.

The plan describes a role-tagged organization of agents. M1 supports the
"emperor + soldiers" two-tier shape only; later milestones extend it with
ministers, sub-managers, and dynamic fan-out without changing this schema.

Design rules:
- Plan is data, not behavior. Topology and runner consume it; agents do not
  branch on plan structure beyond reading their own role through
  ``local_observation``.
- ``agent_id`` values are 0-indexed and contiguous so they map directly onto
  the synchronous runner's ``enumerate``-based agent loop.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Role(str, Enum):
    """Hierarchical role labels.

    M1 uses EMPEROR and SOLDIER only. The other values are reserved for the
    multi-layer milestone (M2) and validated in plan invariants once enabled.
    """

    EMPEROR = "emperor"
    MINISTER = "minister"
    SUB_MANAGER = "sub_manager"
    SOLDIER = "soldier"


class AgentNode(BaseModel):
    """One agent's static role assignment inside a hierarchy plan."""

    agent_id: int
    role: Role
    layer: int
    parent_id: int | None = None
    children_ids: list[int] = Field(default_factory=list)
    soldier_index: int | None = None
    shard_indices: tuple[int, int] | None = None


class HierarchyPlan(BaseModel):
    """A complete agent organization for one experiment run."""

    n_total: int
    layers: list[int]
    nodes: list[AgentNode]
    fanout_schedule: list[int] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_invariants(self) -> "HierarchyPlan":
        if self.n_total < 2:
            raise ValueError("HierarchyPlan requires at least 2 agents (1 emperor + 1 soldier)")
        if len(self.nodes) != self.n_total:
            raise ValueError(
                f"nodes length {len(self.nodes)} does not match n_total {self.n_total}"
            )
        ids = [node.agent_id for node in self.nodes]
        if ids != list(range(self.n_total)):
            raise ValueError("agent ids must be 0..n_total-1 in order")
        if sum(self.layers) != self.n_total:
            raise ValueError(
                f"sum(layers)={sum(self.layers)} does not match n_total={self.n_total}"
            )
        emperors = [node for node in self.nodes if node.role == Role.EMPEROR]
        if len(emperors) != 1:
            raise ValueError("HierarchyPlan must contain exactly one emperor")
        if emperors[0].agent_id != 0:
            raise ValueError("emperor.agent_id must be 0 by convention")
        soldiers = [node for node in self.nodes if node.role == Role.SOLDIER]
        if len(soldiers) < 1:
            raise ValueError("HierarchyPlan must contain at least one soldier")
        return self

    @property
    def emperor(self) -> AgentNode:
        return self.nodes[0]

    @property
    def emperor_id(self) -> int:
        return self.emperor.agent_id

    @property
    def soldier_nodes(self) -> list[AgentNode]:
        return [node for node in self.nodes if node.role == Role.SOLDIER]

    @property
    def soldier_ids(self) -> list[int]:
        return [node.agent_id for node in self.soldier_nodes]

    @property
    def n_soldiers(self) -> int:
        return len(self.soldier_nodes)

    def node(self, agent_id: int) -> AgentNode:
        if agent_id < 0 or agent_id >= self.n_total:
            raise ValueError(f"agent_id {agent_id} out of range")
        return self.nodes[agent_id]

    def children_of(self, agent_id: int) -> list[int]:
        return list(self.node(agent_id).children_ids)

    def parent_of(self, agent_id: int) -> int | None:
        return self.node(agent_id).parent_id
