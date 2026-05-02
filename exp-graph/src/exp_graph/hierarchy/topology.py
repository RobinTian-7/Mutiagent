"""Plan-driven hierarchy topology.

Each agent's neighbor set is the union of its plan parent and direct children.
This generalises the M1 emperor/soldier star into a strict tree:

- Emperor (root): only sees its layer-1 children (ministers or soldiers).
- Middle layer (minister / sub-manager): sees its parent and its own children.
- Soldier (leaf): only sees its parent.

The runner reads neighbours' previous-round outboxes into an agent's inbox, so
this routing pattern produces the expected upward "report" path and downward
"broadcast" path through the tree.

The topology is intentionally not registered in the global topology factory:
it requires a ``HierarchyPlan`` and is constructed by hierarchy-aware code
paths (planner + sweep script) and injected into the runner directly.
"""

from __future__ import annotations

from exp_graph.hierarchy.plan import HierarchyPlan
from exp_graph.topology.base import Topology, validate_agent_id


class HierarchyTopology(Topology):
    """Communication topology derived from a ``HierarchyPlan``."""

    name = "hierarchy"

    def __init__(self, plan: HierarchyPlan) -> None:
        self.plan = plan

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        if n_agents != self.plan.n_total:
            raise ValueError(
                f"HierarchyTopology built for n_total={self.plan.n_total} "
                f"but runner reported n_agents={n_agents}"
            )
        node = self.plan.node(agent_id)
        neighbors = list(node.children_ids)
        if node.parent_id is not None:
            neighbors.append(node.parent_id)
        return neighbors
