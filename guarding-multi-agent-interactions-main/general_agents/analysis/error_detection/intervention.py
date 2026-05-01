"""
intervention.py

Unified intervention logic for multi-agent systems.
Provides two core intervention primitives:
1. inject_system_message: Add message to existing event and optionally reroute
2. create_system_event: Create new system intervention event
"""

from typing import Any, Dict, List, Tuple, Optional
import time

from ...core.dig import InteractionLog, InteractionMode, InteractionEvent, AgentActivation
from .error_detection import activation_coverage_summary


# ============================================================================
# Core Intervention Primitives
# ============================================================================

def inject_system_message(
    event: InteractionEvent,
    message: str,
    intervention_type: str,
    metadata: Optional[Dict[str, Any]] = None,
    reroute_to: Optional[List[str]] = None,
    system_activation_id: Optional[str] = None,
) -> None:
    """
    Inject a system message into an existing event.

    Args:
        event: The event to modify
        message: The system intervention message
        intervention_type: Type of intervention (for tracking)
        metadata: Optional metadata to add to event.info
        reroute_to: Optional list of recipients to reroute to
        system_activation_id: Optional system activation ID for rerouting tracking
    """
    # Add intervention message to event payload (visible to agent)
    event.payload["_system_message"] = message
    
    # Add intervention type to event.info for detection
    event.info["intervention_type"] = intervention_type

    # Add system annotation for dashed line visualization (system -> event)
    if system_activation_id:
        event.system_annotation = {
            "intervention_type": intervention_type,
            "system_activation_id": system_activation_id,
            "message": message,
        }

    # Optionally reroute (solid line from event -> new recipient)
    if reroute_to and system_activation_id:
        event.recipients = reroute_to
        for recipient in reroute_to:
            event.rerouted_recipients[recipient] = system_activation_id
            event.recipient_edge_type[recipient] = 'rerouted_delivery'


def create_system_event(
    dig: InteractionLog,
    message: str,
    intervention_type: str,
    recipients: List[str],
    metadata: Optional[Dict[str, Any]] = None,
    input_events: Optional[List[InteractionEvent]] = None,
) -> Tuple[AgentActivation, InteractionEvent]:
    """
    Create a new system intervention event.

    Args:
        dig: The DIG instance
        message: The intervention message
        intervention_type: Type of intervention
        recipients: List of agent names to send to
        metadata: Optional metadata for event.info
        input_events: Optional events consumed by this intervention

    Returns:
        Tuple of (system_activation, intervention_event)
    """
    current_time = time.time()

    # Create system intervention activation
    system_activation = dig.record_activation(
        agent_name="system",
        mode=intervention_type,
        input_events=input_events or [],
        output_events=[],  # Will append event after creation
        started_at=current_time,
        ended_at=current_time + 0.001,
        intervention_type=intervention_type,
    )

    # Create intervention event
    event_info = {
        "type": "system_intervention",
        "intervention_type": intervention_type,
        "message": message,
    }
    if metadata:
        event_info.update(metadata)

    intervention_event = dig.new_event(
        payload={},
        source_activation_id=system_activation.id,
        recipients=recipients,
        info=event_info,
    )

    # Link event to activation
    system_activation.output_event_ids.append(intervention_event.id)

    return system_activation, intervention_event


# ============================================================================
# Specific Intervention Handlers
# ============================================================================


async def check_and_apply_intervention(
    dig: InteractionLog,
    agent,
    result,
    apply_intervention: bool = True,
) -> bool:
    """
    Unified intervention check that evaluates all intervention conditions.
    Always records detections, but only applies interventions if apply_intervention=True.
    
    Checks performed:
    1. Incomplete coverage on SUBMIT: Block submission if not all initial events are covered
    2. Full coverage without submit: Nudge agent to submit when they have complete coverage
    
    Args:
        dig: The DIG instance (current graph state)
        agent: The agent whose activation just completed
        result: The activation result with new events
        apply_intervention: If True, apply intervention. If False, only record detection.
        
    Returns:
        True if any intervention was applied, False otherwise
    """
    # Get coverage information for this activation
    try:
        coverage_info = activation_coverage_summary(dig, result.activation.id)
    except Exception as e:
        print(f"[INTERVENTION] Error computing coverage: {e}")
        return False
    
    # Check 1: Incomplete coverage on SUBMIT
    if result.mode is InteractionMode.SUBMIT and not coverage_info["fully_covered"]:
        # Always record the detection
        dig.record_detection("early_termination_error")
        # Only intervene up to 3 times; on 4th attempt, let submission through
        current_count = dig.intervention_stats.get("early_termination_error", 0)
        if apply_intervention and current_count < 3:
            return await _handle_incomplete_submission(dig, agent, result, coverage_info)
        return False

    # Check 2: Full coverage but no submit (on non-SUBMIT/TERMINATE modes)
    if result.mode not in [InteractionMode.SUBMIT, InteractionMode.TERMINATE] and coverage_info["fully_covered"]:
        # Always record the detection
        dig.record_detection("missing_completion_error")
        if apply_intervention:
            return await _handle_full_coverage_no_submit(dig, agent, result)
        return False
    
    return False


async def _handle_incomplete_submission(
    dig: InteractionLog,
    agent,
    result,
    coverage_info: Dict[str, Any]
) -> bool:
    """
    Handle a submission with incomplete coverage by rerouting events back to submitter.
    Uses: inject_system_message primitive

    Args:
        dig: The DIG instance
        agent: The agent that submitted
        result: The activation result with new events
        coverage_info: Coverage information from activation_coverage_summary

    Returns:
        True if intervention was applied, False otherwise
    """
    print(f"[{agent.name}] Intervention: submission blocked (incomplete coverage)")
    print(f"[{agent.name}] Uncovered initial events: {len(coverage_info['uncovered_initial_events'])}")
    print(f"[{agent.name}] Uncovered agents: {coverage_info['uncovered_agents']}")

    # Create system intervention activation
    system_activation = dig.record_activation(
        agent_name="system",
        mode="early_termination_error",
        input_events=result.new_events,
        output_events=result.new_events,
        started_at=result.activation.ended_at,
        ended_at=result.activation.ended_at + 0.001,
        intervention_type="early_termination_error",
    )

    # Build intervention message
    message = (
        f"SYSTEM: Submission blocked - {len(coverage_info['uncovered_initial_events'])} initial events uncovered. "
        f"Broadcast your current solution to ALL other agents and ask them to finish it up."
    )

    # Inject message and reroute each event back to submitter
    for ev in result.new_events:
        inject_system_message(
            event=ev,
            message=message,
            intervention_type="early-termination-detected",
            metadata={
                "original_type": ev.payload.get("type", "solution"),
                "uncovered_initial_events": len(coverage_info['uncovered_initial_events']),
                "uncovered_agents": coverage_info['uncovered_agents'],
            },
            reroute_to=[agent.name],
            system_activation_id=system_activation.id,
        )

        await agent.add_to_buffer(ev)
        print(f"[SYSTEM] Rerouted early-termination event {ev.id[:8]}... back to {agent.name}")

    return True


def build_intervention_message(dig: InteractionLog, coverage_info: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Build detailed intervention message from coverage information.
    
    Args:
        dig: The DIG instance
        coverage_info: Coverage information from activation_coverage_summary
        
    Returns:
        Tuple of (summary_string, uncovered_details_list)
    """
    uncovered_details = []
    
    try:
        # Build details about uncovered initial problem events
        for event_id in coverage_info['uncovered_initial_events'][:20]:  # Limit to 20 for readability
            event = dig.events.get(event_id)
            if event:
                uncovered_details.append({
                    "event_id": event.id,
                    "event_type": event.payload.get('type', 'unknown'),
                    "recipients": event.recipients,
                    "edge_type": "initial_problem_event"
                })
    except Exception as e:
        print(f"[INTERVENTION] Error building uncovered details: {e}")
    
    # Build human-readable summary
    summary_parts = [
        "Your submission was blocked because not all initial problem events are reachable.",
        f"Uncovered initial problem events: {len(coverage_info['uncovered_initial_events'])}",
        f"Agents with incomplete information flow: {', '.join(coverage_info['uncovered_agents']) if coverage_info['uncovered_agents'] else 'None'}",
    ]
    
    if uncovered_details:
        summary_parts.append("\nUncovered initial problem events:")
        for detail in uncovered_details[:10]:  # Show first 10 in summary
            if detail['edge_type'] == 'initial_problem_event':
                summary_parts.append(
                    f"  - Event '{detail['event_type']}' intended for {', '.join(detail['recipients'])}"
                )
    
    return "\n".join(summary_parts), uncovered_details


async def _handle_full_coverage_no_submit(
    dig: InteractionLog,
    agent,
    result,
) -> bool:
    """
    Handle case where agent has full coverage but hasn't submitted.
    Uses: inject_system_message (if events exist) or create_system_event (if no events)

    Only intervene if the parent activation is problem-reducing.

    Args:
        dig: The DIG instance
        agent: The agent that has full coverage
        result: The activation result with new events

    Returns:
        True if intervention was applied, False otherwise
    """
    # Check if parent activation is problem-reducing
    parent_act = result.activation
    num_input = len(parent_act.input_event_ids)
    num_output = len(parent_act.output_event_ids)
    is_problem_reducing = num_output <= num_input

    if not is_problem_reducing:
        print(f"[{agent.name}] Skipping full coverage intervention: parent is problem-generating")
        return False

    print(f"[{agent.name}] Intervention: full coverage detected, modifying event payloads")

    # Build intervention message
    message = (
        f"SYSTEM: You have full coverage of all initial problems. "
        f"If you have a complete solution, SUBMIT it now. "
        f"Otherwise, coordinate final results with other agents."
    )

    if result.new_events:
        # Create system activation for tracking
        system_activation = dig.record_activation(
            agent_name="system",
            mode="missing_completion_error",
            input_events=[],
            output_events=[],
            started_at=result.activation.ended_at,
            ended_at=result.activation.ended_at + 0.001,
            intervention_type="missing_completion_error",
        )

        # Inject message into existing events (no reroute)
        for event in result.new_events:
            inject_system_message(
                event=event,
                message=message,
                intervention_type="missing_completion_error",
                metadata={},
                reroute_to=None,  # Don't reroute, just annotate
                system_activation_id=system_activation.id,
            )
            system_activation.output_event_ids.append(event.id)
    else:
        # Create new intervention event
        system_activation, intervention_event = create_system_event(
            dig=dig,
            message=message,
            intervention_type="missing_completion_error",
            recipients=[agent.name],
            metadata={},
        )
        await agent.add_to_buffer(intervention_event)

    return True


def build_submission_prompt_message(agent_name: str) -> str:
    """
    Build message prompting an agent to submit when they have full coverage.
    
    Args:
        agent_name: Name of the agent who should submit
        
    Returns:
        Human-readable prompt message
    """
    return (
        f"SYSTEM NOTICE: Agent {agent_name}, you have achieved complete information coverage! "
        f"All communication paths are properly established and all agents' contributions are reachable. "
        f"You should now submit your solution using the submit_solution tool."
    )


async def handle_no_progress_intervention(
    dig: InteractionLog,
    waiting_agents: List[str],
) -> None:
    """
    Handle system intervention when all agents are in Wait mode with no progress.
    Uses: create_system_event primitive

    Args:
        dig: The DIG instance
        waiting_agents: List of agent names currently in Wait mode
    """
    if not waiting_agents:
        return

    print(f"[SYSTEM] No progress detected: All agents waiting ({', '.join(waiting_agents)})")

    # Build intervention message
    message = (
        f"SYSTEM: Deadlock detected - all agents waiting. "
        f"Process with what you have and send results to others, unless you truly need to wait."
    )

    # Create system intervention event
    system_activation, intervention_event = create_system_event(
        dig=dig,
        message=message,
        intervention_type="deadlock_error",
        recipients=waiting_agents,
        metadata={"waiting_agents": waiting_agents},
    )

    print(f"[SYSTEM] Created deadlock intervention event {intervention_event.id} for agents: {', '.join(waiting_agents)}")


async def handle_orphaned_events_intervention(
    dig: InteractionLog,
    orphaned_event_ids: List[str],
    all_agents: List[str],
) -> None:
    """
    Handle system intervention when events have lost all recipients.
    Uses: inject_system_message primitive to reroute events back to their source

    Args:
        dig: The DIG instance
        orphaned_event_ids: List of event IDs that have become orphaned
        all_agents: List of all agent names in the system
    """
    if not orphaned_event_ids:
        return

    current_time = time.time()

    # Collect orphaned events that will be rerouted
    events_to_reroute = []
    for event_id in orphaned_event_ids:
        event = dig.events.get(event_id)
        if event:
            events_to_reroute.append(event)

    # Create system intervention activation
    system_activation = dig.record_activation(
        agent_name="system",
        mode="orphaned_events",
        input_events=events_to_reroute,
        output_events=events_to_reroute,
        started_at=current_time,
        ended_at=current_time + 0.001,
        intervention_type="orphaned_events",
    )

    # For each orphaned event, route it back to the source agent
    for event_id in orphaned_event_ids:
        event = dig.events.get(event_id)
        if not event:
            continue

        event_type = event.payload.get("type", "unknown")
        event_age = current_time - event.generated_at
        original_recipients = event.recipients if event.recipients else []

        # Find the source agent (who generated this event)
        source_agent = None
        if event.source_activation_id:
            source_activation = dig.activations.get(event.source_activation_id)
            if source_activation and source_activation.agent_name != "system":
                source_agent = source_activation.agent_name

        # If no valid source agent, skip this event
        if not source_agent or source_agent not in all_agents:
            print(f"[SYSTEM] Cannot route orphaned event {event_id} - no valid source agent")
            continue

        print(f"[SYSTEM] Orphaned event detected: {event_id} (type={event_type}, age={event_age:.1f}s)")
        print(f"[SYSTEM] Original recipients: {', '.join(original_recipients)}")
        print(f"[SYSTEM] Routing back to source agent: {source_agent}")

        # Determine reason for orphaning
        invalid_recipients = [r for r in original_recipients if r not in all_agents]
        if invalid_recipients:
            reason = f"assigned invalid recipients: {', '.join(invalid_recipients)}"
        else:
            reason = "all recipients have discarded/rerouted it"

        # Build intervention message
        message = (
            f"SYSTEM: Your event {event_id[:8]} (type={event_type}) has been orphaned for {event_age:.1f}s. "
            f"Reason: {reason}. "
            f"Please review and decide: (1) reroute to valid recipients, (2) discard if no longer needed, "
            f"or (3) handle it yourself if you can process it."
        )

        # Inject message and reroute back to source agent
        inject_system_message(
            event=event,
            message=message,
            intervention_type="orphaned_event",
            metadata={
                "orphaned_at": current_time,
                "orphaned_age": event_age,
                "original_recipients": original_recipients,
                "invalid_recipients": invalid_recipients,
            },
            reroute_to=[source_agent],
            system_activation_id=system_activation.id,
        )

        print(f"[SYSTEM] Rerouted orphaned event {event_id} back to source agent: {source_agent}")


async def handle_excessive_rerouting_intervention(
    dig: InteractionLog,
    excessive_reroutes: Dict[str, int],
    all_agents: List[str],
) -> None:
    """
    Handle intervention for events that have been rerouted excessively.
    
    Args:
        dig: The DIG instance
        excessive_reroutes: Dictionary mapping event_id -> reroute_count
        all_agents: List of all valid agent names
    """
    if not excessive_reroutes:
        return
    
    current_time = time.time()
    
    # Create system activation for this intervention batch
    system_activation = dig.record_activation(
        agent_name="system",
        mode="excessive_rerouting",
        input_events=[],
        output_events=[],
        started_at=current_time,
        ended_at=current_time + 0.001,
        intervention_type="excessive_rerouting",
    )
    
    for event_id, reroute_count in excessive_reroutes.items():
        event = dig.events.get(event_id)
        if not event:
            continue
        
        # Find current recipients (who has this event now)
        current_recipients = event.recipients if event.recipients else []
        
        if not current_recipients:
            print(f"[SYSTEM] Event {event_id} has been rerouted {reroute_count} times but has no current recipients")
            continue
        
        event_type = event.payload.get("type", "unknown")
        problem_id = event.info.get("problem_id") or event.payload.get("problem_id", "unknown")
        
        print(f"[SYSTEM] Event {event_id} has been rerouted {reroute_count} times")
        print(f"[SYSTEM] Current recipients: {', '.join(current_recipients)}")
        
        # Build intervention message encouraging agents to process everything
        message = (
            f"SYSTEM NOTICE: This event (problem_id={problem_id}) has been rerouted {reroute_count} times. "
            f"DO NOT REROUTE this event again. "
            f"Try your best to solve it and share your result to everyone including yourself."
        )
        
        # Inject message to current recipients
        inject_system_message(
            event=event,
            message=message,
            intervention_type="excessive_rerouting",
            metadata={
                "reroute_count": reroute_count,
                "problem_id": problem_id,
                "intervention_at": current_time,
            },
            reroute_to=None,  # Don't reroute, just add message
            system_activation_id=system_activation.id,
        )
        
        print(f"[SYSTEM] Added system message to event {event_id} for recipients: {', '.join(current_recipients)}")


def handle_repeated_efforts_intervention(
    event: InteractionEvent,
    designated_handler: str,
    dig: InteractionLog,
) -> None:
    """
    Handle repeated efforts by injecting a designated handler notice into the event.
    
    When a solution event is broadcast to multiple agents, we designate the least busy
    agent to handle it and tell others to discard.
    
    Args:
        event: The event to inject the notice into
        designated_handler: Name of the agent designated to handle this event
        dig: The DIG instance for recording
    """
    current_time = time.time()
    
    # Record detection
    dig.record_detection("repeated_efforts")
    
    # Create system activation for tracking
    system_activation = dig.record_activation(
        agent_name="system",
        mode="repeated_efforts_prevention",
        input_events=[],
        output_events=[],
        started_at=current_time,
        ended_at=current_time + 0.001,
        intervention_type="repeated_efforts_prevention",
    )
    
    # Build intervention message
    message = (
        f"SYSTEM NOTICE: This event is designated for {designated_handler} to handle. "
        f"If you are not {designated_handler}, please DISCARD this event to avoid repeated efforts."
    )
    
    # Inject into event payload
    event.payload["_designated_handler"] = designated_handler
    event.payload["_handler_notice"] = message
    
    # Also inject as system message for tracking
    inject_system_message(
        event=event,
        message=message,
        intervention_type="repeated_efforts_prevention",
        metadata={
            "designated_handler": designated_handler,
            "intervention_at": current_time,
        },
        reroute_to=None,
        system_activation_id=system_activation.id,
    )
    
    # Record intervention
    dig.record_intervention("repeated_efforts_prevention")
    
    print(f"[SYSTEM] Designated {designated_handler} to handle event {event.id}")


def handle_dependency_warning_intervention(
    events_with_lineage: Dict[str, Dict],
    agent_name: str,
    dig: InteractionLog,
) -> None:
    """
    Handle dependency warning detection with informational message injection.
    
    Records when an agent receives events from different lineages and injects
    a message informing the agent about the event's generator.
    
    Args:
        events_with_lineage: Dict mapping event_id to lineage info (generator, level)
        agent_name: Name of the agent receiving the events
        dig: The DIG instance for recording
    """
    current_time = time.time()
    
    # Record detection
    dig.record_detection("dependency_warning")
    
    # Group events by their generator for logging
    events_by_generator = {}
    for ev_id, info in events_with_lineage.items():
        generator = info.get("generator")
        if generator not in events_by_generator:
            events_by_generator[generator] = []
        events_by_generator[generator].append(ev_id)
    
    print(f"[DEPENDENCY_WARNING] Detected for {agent_name}, generators: {list(events_by_generator.keys())}")
    
    # Create system activation for tracking
    system_activation = dig.record_activation(
        agent_name="system",
        mode="dependency_warning",
        input_events=[],
        output_events=[],
        started_at=current_time,
        ended_at=current_time + 0.001,
        intervention_type="dependency_warning",
    )
    
    # Inject informational message into each event
    for ev_id, info in events_with_lineage.items():
        generator = info.get("generator")
        event = dig.events.get(ev_id)
        if not event:
            continue
        
        message = (
            f"This question was generated by {generator}. "
            f"Prioritize working on questions from the same ancestor if there are multiple."
        )
        
        inject_system_message(
            event=event,
            message=message,
            intervention_type="dependency_warning",
            reroute_to=None,
            system_activation_id=system_activation.id,
        )
        print(f"[DEPENDENCY_WARNING] Injected message into event {ev_id[:8]}: generator={generator}")
    
    # Record intervention
    dig.record_intervention("dependency_warning")
