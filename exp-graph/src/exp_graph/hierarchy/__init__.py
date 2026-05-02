"""Hierarchy (emperor-soldier) topology and planning.

Public entry points used by the synchronous runner and sweep scripts:

- :class:`Role`, :class:`AgentNode`, :class:`HierarchyPlan` describe a static
  agent organization.
- :class:`HierarchyTopology` adapts a plan to the runner's neighbor interface.
- :func:`build_emperor_soldiers_plan` is the M1 static planner.
- :func:`build_hierarchy_local_observations` maps a plan onto per-agent
  observations using a task adapter.
"""

from exp_graph.hierarchy.assignment import build_hierarchy_local_observations
from exp_graph.hierarchy.dispatch import (
    ChildAssignment,
    DispatchEntry,
    DispatchTree,
    SubordinateDispatchDecision,
    apply_subordinate_decision,
    attach_dispatch_to_plan,
    build_static_dispatch_tree,
    mechanical_equal_split_children,
    parse_llm_dispatch,
    parse_subordinate_dispatch,
)
from exp_graph.hierarchy.plan import AgentNode, HierarchyPlan, Role
from exp_graph.hierarchy.planner_llm import (
    EMPEROR_PROMPT_MARKER,
    EMPEROR_RETRY_PROMPT_MARKER,
    SUBORDINATE_PROMPT_MARKER,
    LLMHierarchyPlanner,
    LLMPlanResult,
    M3PlannerConfig,
    PlannerRetryRecord,
    SubordinateDispatchCall,
    build_emperor_planning_prompt,
    build_emperor_retry_prompt,
    build_subordinate_dispatch_prompt,
    validate_fanout,
)
from exp_graph.hierarchy.planner_static import (
    build_emperor_soldiers_plan,
    build_static_hierarchy_plan,
    expected_n_soldiers,
    expected_total_agents,
    shape_label_for_fanout,
    shape_label_to_fanout,
)
from exp_graph.hierarchy.topology import HierarchyTopology

__all__ = [
    "AgentNode",
    "ChildAssignment",
    "DispatchEntry",
    "DispatchTree",
    "EMPEROR_PROMPT_MARKER",
    "EMPEROR_RETRY_PROMPT_MARKER",
    "HierarchyPlan",
    "HierarchyTopology",
    "LLMHierarchyPlanner",
    "LLMPlanResult",
    "M3PlannerConfig",
    "PlannerRetryRecord",
    "Role",
    "SUBORDINATE_PROMPT_MARKER",
    "SubordinateDispatchCall",
    "SubordinateDispatchDecision",
    "apply_subordinate_decision",
    "attach_dispatch_to_plan",
    "build_emperor_planning_prompt",
    "build_emperor_retry_prompt",
    "build_emperor_soldiers_plan",
    "build_hierarchy_local_observations",
    "build_static_dispatch_tree",
    "build_static_hierarchy_plan",
    "build_subordinate_dispatch_prompt",
    "expected_n_soldiers",
    "expected_total_agents",
    "mechanical_equal_split_children",
    "parse_llm_dispatch",
    "parse_subordinate_dispatch",
    "shape_label_for_fanout",
    "shape_label_to_fanout",
    "validate_fanout",
]
