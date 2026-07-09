"""
error_detection.py

Error detection for multi-agent DIG analysis.
Checks for coverage issues and reports errors.
"""

from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from ...core.dig import InteractionEvent

from ...core.dig import InteractionLog
from ...core.dig import build_activation_event_graph
from .coverage import compute_rule_coverage


def activation_coverage_summary(dig: InteractionLog, activation_id: str) -> Dict[str, Any]:
    """
    Check if an activation has complete coverage of initial problem events.
    
    Returns:
      {
        "fully_covered": bool,
        "uncovered_initial_events": [event_ids],
        "uncovered_agents": [agent_names],
      }
    
    Checks if the backward traversal from this activation reaches all initial problem events.
    """
    nodes, edges, activation_inputs, activation_outputs, event_source = build_activation_event_graph(dig)
    cov = compute_rule_coverage(nodes, edges, activation_inputs, activation_outputs, event_source)

    # Find all initial problem events (events with no source activation)
    initial_events: Set[str] = set()
    for event_id, event in dig.events.items():
        if event.source_activation_id is None:
            initial_events.add(event_id)
    
    # Get covered edges from the activation
    covered_edges = set(cov.get(activation_id, {}).get("direct", [])) | set(cov.get(activation_id, {}).get("soft", []))
    
    # Check which initial events are reachable (their outgoing edges are covered)
    covered_initial_events: Set[str] = set()
    uncovered_initial_events: Set[str] = set()
    
    for event_id in initial_events:
        # Find outgoing edges from this initial event
        has_covered_outgoing = False
        for e in edges:
            if e.src == event_id and e.id in covered_edges:
                has_covered_outgoing = True
                covered_initial_events.add(event_id)
                break
        
        if not has_covered_outgoing:
            uncovered_initial_events.add(event_id)
    
    # For uncovered initial events, identify which agents would have received them
    uncovered_agents: Set[str] = set()
    for event_id in uncovered_initial_events:
        event = dig.events.get(event_id)
        if event:
            uncovered_agents.update(event.recipients)

    return {
        "fully_covered": len(uncovered_initial_events) == 0,
        "uncovered_initial_events": sorted(uncovered_initial_events),
        "uncovered_agents": sorted(uncovered_agents),
    }


def detect_and_report_errors(dig: InteractionLog, detected_errors: Set[str]) -> Set[str]:
    """
    Detect coverage errors in the DIG.
    
    Note: This function only tracks errors silently. Actual intervention messages
    are handled by intervention.py when agents try to submit with incomplete coverage.
    
    Args:
        dig: The DIG to analyze
        detected_errors: Set of already detected error IDs to avoid duplicate reporting
        
    Returns:
        Updated set of detected error IDs
    """
    # Check each activation for coverage issues
    for activation_id, activation in dig.activations.items():
        error_key = f"coverage_{activation_id}"
        
        # Skip if already reported
        if error_key in detected_errors:
            continue
        
        # Check coverage
        coverage_info = activation_coverage_summary(dig, activation_id)
        
        # Track if there are uncovered initial events (but don't print - intervention.py handles messaging)
        if not coverage_info['fully_covered']:
            detected_errors.add(error_key)
    
    return detected_errors


def detect_orphaned_events(
    dig: InteractionLog,
    detected_errors: Set[str],
    valid_agent_names: Set[str],
    orphan_timeout: float = 5.0
) -> Set[str]:
    """
    Detect events that become unreachable before any activation can consume them.

    An event is orphaned ONLY if:
    1. It has been discarded (all edges deleted/discarded)
    2. AND it has no recipients (empty recipients list)
    
    If a recipient consumes an event (uses it as input), that recipient becomes permanent
    and the event cannot be orphaned even if later discarded.

    Args:
        dig: The DIG to analyze
        detected_errors: Set of already detected error IDs to avoid duplicate reporting
        valid_agent_names: Set of valid agent names in the system
        orphan_timeout: Minimum age in seconds before an event can be considered orphaned

    Returns:
        Set of orphaned event IDs detected in this call
    """
    current_time = time.time()
    orphaned_event_ids: Set[str] = set()

    # Build graph to check active edges
    nodes, edges, activation_inputs, activation_outputs, event_source = build_activation_event_graph(dig)

    # Build set of consumed events (events that have been used as input to any activation)
    consumed_event_ids: Set[str] = set()
    for activation in dig.activations.values():
        consumed_event_ids.update(activation.input_event_ids)

    for event_id, event in dig.events.items():
        # Skip if already detected
        error_key = f"orphaned_{event_id}"
        if error_key in detected_errors:
            continue

        # Skip system events (from system activations)
        if event.source_activation_id:
            src_act = dig.activations.get(event.source_activation_id)
            if src_act and src_act.agent_name == "system":
                continue

        # Check if event is old enough
        event_age = current_time - event.generated_at
        if event_age < orphan_timeout:
            continue

        # If event was consumed, it has permanent recipients - cannot be orphaned
        if event_id in consumed_event_ids:
            continue

        # An event is orphaned ONLY if:
        # 1. It is discarded (all edges deleted/discarded)
        # 2. AND it has no recipients

        # Check if event has no recipients
        if not event.recipients:
            # Find all outgoing edges from this event
            outgoing_edges = [e for e in edges if e.src == event_id]

            # Check if event has been discarded (all edges deleted/discarded)
            if outgoing_edges:
                # Check if all outgoing edges are deleted/discarded
                all_discarded = True
                for edge in outgoing_edges:
                    # An edge is active if it's not deleted and not marked as deleted in metadata
                    is_deleted = edge.meta.get("deleted", False)
                    is_discard = edge.meta.get("line_color") == "red"  # Red = discard

                    if not is_deleted and not is_discard:
                        all_discarded = False
                        break

                if all_discarded:
                    # Event has no recipients AND all edges are discarded - it's orphaned
                    detected_errors.add(error_key)
                    orphaned_event_ids.add(event_id)
                    print(f"[ORPHAN] Event {event_id} has no recipients and all edges are discarded")
            elif event_age >= orphan_timeout:
                # Event has no recipients and no edges at all (after timeout) - it's orphaned
                detected_errors.add(error_key)
                orphaned_event_ids.add(event_id)
                print(f"[ORPHAN] Event {event_id} has no recipients and no edges")

    return orphaned_event_ids


def detect_excessive_rerouting(
    dig: InteractionLog,
    detected_errors: Set[str],
    max_reroutes: int = 3
) -> Dict[str, int]:
    """
    Detect events that have been rerouted more than max_reroutes times.
    
    Args:
        dig: The DIG to analyze
        detected_errors: Set of already detected error IDs to avoid duplicate reporting
        max_reroutes: Maximum number of reroutes before intervention (default: 3)
        
    Returns:
        Dictionary mapping event_id to reroute count for events exceeding threshold
    """
    excessive_reroutes: Dict[str, int] = {}
    
    for event_id, event in dig.events.items():
        # Count how many times this event has been rerouted
        # Check all activations that had this event as input with "reroute" action
        reroute_count = 0
        
        for activation in dig.activations.values():
            if event_id in activation.input_event_ids:
                action = activation.input_actions.get(event_id)
                if action == "reroute":
                    reroute_count += 1
        
        # Check if exceeds threshold
        if reroute_count > max_reroutes:
            error_key = f"excessive_reroute_{event_id}"
            if error_key not in detected_errors:
                detected_errors.add(error_key)
                excessive_reroutes[event_id] = reroute_count
                print(f"[EXCESSIVE_REROUTE] Event {event_id} has been rerouted {reroute_count} times (threshold: {max_reroutes})")
    
    return excessive_reroutes


def detect_repeated_efforts(
    event: "InteractionEvent",
    recipients: list,
    agent_buffers: Dict[str, int],
) -> Tuple[bool, Optional[str]]:
    """
    Detect if an event with multiple recipients could cause repeated efforts.
    
    When a solution event is broadcast to multiple agents, they may all try to
    aggregate/process it redundantly. This detects such cases and identifies
    the least busy agent to designate as the handler.
    
    Args:
        event: The event being delivered
        recipients: List of valid recipient agent names
        agent_buffers: Dictionary mapping agent name to their buffer size
        
    Returns:
        Tuple of (should_intervene, designated_handler)
        - should_intervene: True if event has multiple recipients and is a solution
        - designated_handler: Name of the least busy agent to handle it
    """
    # Only intervene on solution events with multiple recipients
    if len(recipients) <= 1:
        return False, None
    
    event_type = event.payload.get("type")
    if event_type != "solution":
        return False, None
    
    # Find the agent with the fewest events in their buffer (least busy)
    buffer_sizes = {r: agent_buffers.get(r, 0) for r in recipients}
    least_busy_agent = min(buffer_sizes, key=buffer_sizes.get)
    
    print(f"[REPEATED_EFFORTS] Event {event.id} has {len(recipients)} recipients, designating {least_busy_agent} (buffer sizes: {buffer_sizes})")
    
    return True, least_busy_agent


def detect_dependency_warning(
    pending_events: List["InteractionEvent"],
    agent_name: str,
    dig: InteractionLog,
) -> Tuple[bool, Optional[Dict[str, str]]]:
    """
    Detect if an agent is trying to aggregate events from different lineages.
    
    Dependency warning triggers when an agent receives events that originate
    from different problem-generating activations at the same level (same number
    of steps back to their generator).
    
    Args:
        pending_events: List of events pending for this agent
        agent_name: Name of the agent receiving the events
        dig: The DIG to trace lineage
        
    Returns:
        Tuple of (should_intervene, lineage_info)
        - should_intervene: True if events come from different lineages
        - lineage_info: Dict mapping event_id to generator agent name
    """
    if len(pending_events) < 2:
        return False, None
    
    # Only check solution events (aggregation typically happens with solutions)
    solution_events = [
        ev for ev in pending_events
        if ev.payload.get("type") == "solution" or ev.info.get("type") == "solution"
    ]
    
    if len(solution_events) < 2:
        return False, None
    
    def find_generator(event: "InteractionEvent", max_depth: int = 10) -> Tuple[Optional[str], int]:
        """
        Find the closest problem-generating activation for an event.
        
        A problem-generating activation is one that used split_and_send or send_problem_data.
        
        Returns:
            Tuple of (generator_agent_name, steps_back)
        """
        current_act_id = event.source_activation_id
        steps = 0
        
        while current_act_id and steps < max_depth:
            activation = dig.activations.get(current_act_id)
            if not activation:
                break
            
            # Check if this is a problem-generating activation
            if activation.tool_calls:
                for tool_call in activation.tool_calls:
                    if tool_call.get("tool") in ["split_and_send", "send_problem_data"]:
                        return activation.agent_name, steps
            
            # Move to parent activation (via input events)
            if activation.input_event_ids:
                # Get the first input event and trace its source
                first_input = dig.events.get(activation.input_event_ids[0])
                if first_input:
                    current_act_id = first_input.source_activation_id
                    steps += 1
                else:
                    break
            else:
                break
        
        return None, steps
    
    # Find generators for all solution events
    lineage_info = {}
    generators_by_level = {}  # level -> set of generators
    
    for ev in solution_events:
        generator, level = find_generator(ev)
        lineage_info[ev.id] = {
            "generator": generator,
            "level": level,
            "event_id": ev.id,
        }
        
        if level not in generators_by_level:
            generators_by_level[level] = set()
        if generator:
            generators_by_level[level].add(generator)
    
    # Check if any level has multiple generators (dependency warning)
    for level, generators in generators_by_level.items():
        if len(generators) > 1:
            print(f"[DEPENDENCY_WARNING] Agent {agent_name} has events from different generators at level {level}: {generators}")
            return True, lineage_info
    
    return False, lineage_info


def _get_node_name(node_id: str, dig: InteractionLog) -> str:
    """Get a human-readable name for a node."""
    if node_id in dig.activations:
        act = dig.activations[node_id]
        return f"{act.agent_name} ({act.mode})"
    elif node_id in dig.events:
        evt = dig.events[node_id]
        return f"Event: {evt.payload.get('type', 'unknown')}"
    return node_id[:8]
