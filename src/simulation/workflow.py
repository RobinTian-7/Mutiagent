"""LangGraph-based multi-agent orchestration workflow.

Paper reference (Sec 3.1):
  "The system is implemented using LangGraph, which enforces the specified
   topology and manages message routing."

  "Agents execute over the task tree by iteratively selecting, decomposing,
   and solving tasks while communicating over the active topology."

This module implements the core simulation loop as a LangGraph StateGraph.
Each round, every agent:
  1. Sees claims filtered by topology
  2. Selects a claim via reinforced routing
  3. Performs a coordination action (propose/revise/contradict/merge/delegate)
  4. The event and claim are appended to the trace

ASSUMPTION (A7): 20 global rounds. In each round, every agent acts once.
ASSUMPTION (A11): One "step" = one agent performing one coordination action.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from src.agents.mock_agent import mock_agent_action
from src.interventions.dti import DTIMonitor
from src.routing.claim_router import ClaimRouter, ReinforcedRouter
from src.routing.topology_filter import get_visible_claims
from src.schemas.events import EventType
from src.topology.base import Topology


def _build_state_dict(
    events: list,
    claims: list,
    claim_activity: dict,
    current_round: int,
    dti_state: dict,
    **kwargs: Any,
) -> dict:
    """Build a state dict for LangGraph."""
    return {
        "events": events,
        "claims": claims,
        "claim_activity": claim_activity,
        "current_round": current_round,
        "dti_state": dti_state,
        **kwargs,
    }


def create_workflow(
    agent_ids: list[str],
    topology: Topology,
    router: ClaimRouter | None = None,
    max_rounds: int = 20,
    dti_enabled: bool = False,
    dti_monitor: DTIMonitor | None = None,
) -> StateGraph:
    """Create a LangGraph StateGraph for multi-agent coordination.

    The graph has a single node that processes one full round of agent actions,
    then loops until max_rounds is reached.
    """
    if router is None:
        router = ReinforcedRouter(beta=0.15)

    if dti_enabled and dti_monitor is None:
        dti_monitor = DTIMonitor()

    def agent_round(state: dict) -> dict:
        """Execute one round: each agent acts once."""
        events = list(state.get("events", []))
        claims = list(state.get("claims", []))
        claim_activity = dict(state.get("claim_activity", {}))
        dti_state = dict(state.get("dti_state", {}))
        current_round = state.get("current_round", 0)

        new_events = []
        new_claims = []
        step_counter = current_round * len(agent_ids)

        for agent_id in agent_ids:
            # 1. Filter visible claims by topology
            visible = get_visible_claims(agent_id, claims, topology)

            # 2. Select claim via reinforced routing
            selected = None
            if visible:
                selected = router.select_claim(visible, claim_activity)

            # 3. Agent acts
            event, claim = mock_agent_action(
                agent_id=agent_id,
                visible_claims=visible,
                selected_claim=selected,
            )
            event.step_id = step_counter
            step_counter += 1

            # 4. Update activity counts
            # Paper: x_i(t) = number of downstream events referencing c_i
            for parent_id in event.parent_claim_ids:
                claim_activity[parent_id] = claim_activity.get(parent_id, 0) + 1
            if event.target_claim_id:
                claim_activity[event.target_claim_id] = (
                    claim_activity.get(event.target_claim_id, 0) + 1
                )

            new_events.append(event)
            new_claims.append(claim)
            claims.append(claim)

            # 5. DTI check (if enabled)
            if dti_enabled and dti_monitor is not None:
                root_id = event.root_claim_id
                if root_id:
                    is_merge = event.event_type == EventType.MERGE_CLAIMS
                    dti_event = dti_monitor.process_event(
                        root_claim_id=root_id,
                        is_merge=is_merge,
                        dti_state=dti_state,
                    )
                    if dti_event is not None:
                        # DTI triggered — create a merge event
                        from src.interventions.dti import create_dti_merge_event

                        merge_evt, merge_claim = create_dti_merge_event(
                            root_claim_id=root_id,
                            claims=claims,
                            agent_id=agent_id,
                            step_id=step_counter,
                        )
                        step_counter += 1
                        new_events.append(merge_evt)
                        new_claims.append(merge_claim)
                        claims.append(merge_claim)

                        # Update DTI state with reset
                        dti_state[root_id] = (0, 1)

                        # Update activity for merge parents
                        for pid in merge_evt.parent_claim_ids:
                            claim_activity[pid] = claim_activity.get(pid, 0) + 1

        return {
            "events": events + new_events,
            "claims": claims,
            "claim_activity": claim_activity,
            "current_round": current_round + 1,
            "dti_state": dti_state,
        }

    def should_continue(state: dict) -> str:
        """Check if simulation should continue."""
        if state.get("current_round", 0) >= max_rounds:
            return "end"
        return "continue"

    # Build graph
    graph = StateGraph(dict)
    graph.add_node("agent_round", agent_round)
    graph.set_entry_point("agent_round")
    graph.add_conditional_edges(
        "agent_round",
        should_continue,
        {"continue": "agent_round", "end": END},
    )

    return graph


def run_simulation(
    agent_ids: list[str],
    topology: Topology,
    router: ClaimRouter | None = None,
    max_rounds: int = 20,
    dti_enabled: bool = False,
    dti_monitor: DTIMonitor | None = None,
) -> dict:
    """Convenience function to create and run the workflow."""
    graph = create_workflow(
        agent_ids=agent_ids,
        topology=topology,
        router=router,
        max_rounds=max_rounds,
        dti_enabled=dti_enabled,
        dti_monitor=dti_monitor,
    )

    app = graph.compile()

    initial_state = {
        "events": [],
        "claims": [],
        "claim_activity": {},
        "current_round": 0,
        "dti_state": {},
    }

    result = app.invoke(initial_state)
    return result
