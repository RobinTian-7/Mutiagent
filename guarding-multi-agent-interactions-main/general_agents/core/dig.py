"""
dig.py

DIG data model and observation helper.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class InteractionMode(str, Enum):
    RESPOND = "Respond"
    REROUTE = "Reroute"
    WAIT = "Wait"
    DISCARD = "Discard"
    SUBMIT = "Submit"       # agent claims to submit a candidate solution
    TERMINATE = "Terminate" # agent opts out of further participation


@dataclass
class InteractionEvent:
    """
    Hyperedge in the DIG.
    """
    id: str
    payload: Dict[str, Any]  # Agent-editable content (may be manipulated)
    source_activation_id: Optional[str]
    recipients: List[str]
    generated_at: float
    received_at: Dict[str, float] = field(default_factory=dict)
    delivery_policy: Dict[str, Any] = field(default_factory=dict)
    deleted_recipients: List[str] = field(default_factory=list)  # Track recipients removed due to reroute
    rerouted_recipients: Dict[str, str] = field(default_factory=dict)  # new_recipient -> reroute_activation_id
    system_annotation: Optional[Dict[str, Any]] = None  # System intervention annotation (no solid edge, just dashed line)
    info: Dict[str, Any] = field(default_factory=dict)  # System/tool-generated info (trustworthy, not agent-editable)
    # Edge type for each recipient: recipient -> edge_type (normal, rerouted_delivery)
    recipient_edge_type: Dict[str, str] = field(default_factory=dict)



@dataclass
class AgentActivation:
    """
    Vertex in the DIG.
    """
    id: str
    agent_name: str
    mode: InteractionMode | str  # InteractionMode for agents, intervention_type string for system
    input_event_ids: List[str]
    output_event_ids: List[str]
    started_at: float
    ended_at: float
    unconsumed_event_ids: List[str] = field(default_factory=list)  # Events returned to buffer
    reasoning: Optional[str] = None  # Agent's reasoning for this decision
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # Track tool calls: [{"tool": "split", "include_data": True}, ...]
    intervention_type: Optional[str] = None  # Type of system intervention if this is a system activation
    # Per-edge actions: event_id -> action (consume/reroute/discard/wait)
    input_actions: Dict[str, str] = field(default_factory=dict)


@dataclass
class InteractionLog:
    """
    Event log for recording all interactions in a single run.
    """
    activations: Dict[str, AgentActivation] = field(default_factory=dict)
    events: Dict[str, InteractionEvent] = field(default_factory=dict)
    in_progress_activations: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # Track running activations
    deleted_edges: Dict[str, str] = field(default_factory=dict)  # event_id -> activation_id mapping for cancelled edges
    changelog: List[Dict[str, Any]] = field(default_factory=list)  # Timeline of DIG changes
    detection_stats: Dict[str, int] = field(default_factory=dict)  # Track detected errors by type (always counted)
    intervention_stats: Dict[str, int] = field(default_factory=dict)  # Track interventions applied by type
    llm_usage: Dict[str, int] = field(
        default_factory=lambda: {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )
    _event_counter: int = field(default=0, repr=False)  # Counter for short event IDs
    _activation_counter: int = field(default=0, repr=False)  # Counter for short activation IDs
    
    def record_detection(self, detection_type: str):
        """Record that an error was detected (whether or not intervention is applied)."""
        self.detection_stats[detection_type] = self.detection_stats.get(detection_type, 0) + 1
    
    def record_intervention(self, intervention_type: str):
        """Record that an intervention was applied."""
        self.intervention_stats[intervention_type] = self.intervention_stats.get(intervention_type, 0) + 1

    def record_llm_usage(
        self,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ):
        """Accumulate LLM usage stats."""
        self.llm_usage["calls"] += 1
        if prompt_tokens is not None:
            self.llm_usage["prompt_tokens"] += prompt_tokens
        if completion_tokens is not None:
            self.llm_usage["completion_tokens"] += completion_tokens
        if total_tokens is not None:
            self.llm_usage["total_tokens"] += total_tokens
        elif prompt_tokens is not None and completion_tokens is not None:
            self.llm_usage["total_tokens"] += prompt_tokens + completion_tokens

    def get_efficiency_metrics(self) -> Dict[str, float]:
        """Get efficiency metrics: total elapsed time and total activation time."""
        if not self.activations:
            return {"elapsed_time": 0.0, "activation_time": 0.0, "num_activations": 0}
        
        # Find reference time (earliest activation start)
        t0 = min(a.started_at for a in self.activations.values())
        
        total_elapsed = 0.0
        total_activation = 0.0
        
        for act in self.activations.values():
            end_time = act.ended_at - t0
            duration = act.ended_at - act.started_at
            total_elapsed = max(total_elapsed, end_time)
            total_activation += duration
        
        return {
            "elapsed_time": total_elapsed,
            "activation_time": total_activation,
            "num_activations": len(self.activations),
        }

    def get_solution_events(self) -> List[InteractionEvent]:
        """Get all events that look like solutions (type='solution' in payload or info)."""
        solution_events = []
        for ev in self.events.values():
            if ev.payload.get("type") == "solution" or ev.info.get("type") == "solution":
                solution_events.append(ev)
        return solution_events
    
    def get_submit_activation_inputs(self) -> List[InteractionEvent]:
        """Get all input events to SUBMIT activations."""
        input_events = []
        for act in self.activations.values():
            if act.mode == InteractionMode.SUBMIT:
                for ev_id in act.input_event_ids:
                    if ev_id in self.events:
                        input_events.append(self.events[ev_id])
        return input_events

    def new_event(
        self,
        payload: Dict[str, Any],
        source_activation_id: Optional[str],
        recipients: List[str],
        delivery_policy: Optional[Dict[str, Any]] = None,
        info: Optional[Dict[str, Any]] = None,
    ) -> InteractionEvent:
        self._event_counter += 1
        eid = f"e{self._event_counter}"
        timestamp = time.time()
        ev = InteractionEvent(
            id=eid,
            payload=payload,
            source_activation_id=source_activation_id,
            recipients=list(recipients),
            generated_at=timestamp,
            delivery_policy=delivery_policy or {},
            info=info or {},
        )
        self.events[eid] = ev
        
        # Log event creation
        self.changelog.append({
            "timestamp": timestamp,
            "type": "event_created",
            "event_id": eid,
            "source_activation_id": source_activation_id,
            "recipients": list(recipients),
            "payload_type": payload.get("type", "unknown")
        })
        
        return ev

    def record_activation(
        self,
        agent_name: str,
        mode: InteractionMode | str,  # InteractionMode for agents, intervention_type string for system
        input_events: List[InteractionEvent],
        output_events: List[InteractionEvent],
        started_at: Optional[float] = None,
        ended_at: Optional[float] = None,
        reroute_map: Optional[Dict[str, List[str]]] = None,  # Per-event reroute: event_id -> recipients
        unconsumed_events: Optional[List[InteractionEvent]] = None,
        reasoning: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        intervention_type: Optional[str] = None,
        input_actions: Optional[Dict[str, str]] = None,  # Per-edge actions: event_id -> action
    ) -> AgentActivation:
        self._activation_counter += 1
        aid = f"a{self._activation_counter}"
        now = time.time()
        act = AgentActivation(
            id=aid,
            agent_name=agent_name,
            mode=mode,
            input_event_ids=[e.id for e in input_events],
            output_event_ids=[e.id for e in output_events],
            started_at=started_at if started_at is not None else now,
            unconsumed_event_ids=[e.id for e in unconsumed_events] if unconsumed_events else [],
            ended_at=ended_at if ended_at is not None else now,
            reasoning=reasoning,
            tool_calls=tool_calls or [],
            intervention_type=intervention_type,
            input_actions=input_actions or {},
        )
        self.activations[aid] = act
        
        # Track intervention statistics
        if intervention_type:
            self.intervention_stats[intervention_type] = self.intervention_stats.get(intervention_type, 0) + 1
        
        # Log activation creation
        self.changelog.append({
            "timestamp": now,
            "type": "activation_recorded",
            "activation_id": aid,
            "agent_name": agent_name,
            "mode": mode.value if isinstance(mode, InteractionMode) else str(mode),
            "input_event_ids": [e.id for e in input_events],
            "output_event_ids": [e.id for e in output_events],
            "unconsumed_event_ids": [e.id for e in unconsumed_events] if unconsumed_events else [],
            "started_at": started_at if started_at is not None else now,
            "ended_at": ended_at if ended_at is not None else now
        })

        # Get consumed event IDs (input events that are NOT unconsumed)
        unconsumed_ids = set([e.id for e in unconsumed_events] if unconsumed_events else [])
        reroute_map = reroute_map or {}
        input_actions = input_actions or {}
        
        for e in input_events:
            if agent_name not in e.received_at:
                e.received_at[agent_name] = now
            
            # Check if this event was consumed (not in unconsumed list)
            is_consumed = e.id not in unconsumed_ids
            
            # Check if this specific event is being rerouted
            is_rerouted = e.id in reroute_map
            
            # Check if this specific event is being discarded (per-event action)
            is_discarded = input_actions.get(e.id) == "discard"
            
            # Check if this specific event is being waited (per-event action)
            is_waited = input_actions.get(e.id) == "wait"
            
            # Check if this event was previously rerouted to this agent
            was_rerouted_to_me = e.recipient_edge_type.get(agent_name) == 'rerouted_delivery'
            
            # For rerouted events: mark edge as deleted and add new recipients
            if is_rerouted and is_consumed:
                edge_key = f"{e.id}->{aid}"
                self.deleted_edges[edge_key] = agent_name
                e.deleted_recipients.append(agent_name)
                # Override edge type to 'deleted' if it was a rerouted delivery
                if was_rerouted_to_me:
                    e.recipient_edge_type[agent_name] = 'deleted'
                
                # Add new recipients from per-event reroute
                for recipient in reroute_map[e.id]:
                    if recipient not in e.recipients:
                        e.recipients.append(recipient)
                        e.rerouted_recipients[recipient] = aid
                        e.recipient_edge_type[recipient] = 'rerouted_delivery'
            
            # For discarded events (either by mode or per-event action): mark edges as deleted
            elif (mode == InteractionMode.DISCARD or is_discarded) and is_consumed and not is_rerouted:
                edge_key = f"{e.id}->{aid}"
                self.deleted_edges[edge_key] = agent_name
                e.deleted_recipients.append(agent_name)
                # Override edge type to 'deleted' if it was a rerouted delivery
                if was_rerouted_to_me:
                    e.recipient_edge_type[agent_name] = 'deleted'
            
            # For waited events: override edge type if it was a rerouted delivery
            elif is_waited and was_rerouted_to_me:
                e.recipient_edge_type[agent_name] = 'waited'

        return act

    def start_activation(self, agent_name: str, input_events: List[InteractionEvent]) -> str:
        """Record the start of an activation (before it completes)."""
        self._activation_counter += 1
        aid = f"a{self._activation_counter}"
        self.in_progress_activations[aid] = {
            "id": aid,
            "agent_name": agent_name,
            "input_event_ids": [e.id for e in input_events],
            "started_at": time.time(),
        }
        return aid
    
    def finish_activation(self, activation_id: str):
        """Remove an activation from in-progress tracking."""
        self.in_progress_activations.pop(activation_id, None)
    
    def save_changelog(self, filename: str):
        """Save the DIG changelog to a JSON file for replay."""
        import json
        from datetime import datetime
        
        changelog_data = {
            "metadata": {
                "total_changes": len(self.changelog),
                "total_activations": len(self.activations),
                "total_events": len(self.events),
                "saved_at": datetime.now().isoformat()
            },
            "changes": self.changelog
        }
        
        with open(filename, 'w') as f:
            json.dump(changelog_data, f, indent=2)


def build_observation(
    agent_name: str,
    pending_events: List[InteractionEvent],
) -> Dict[str, Any]:
    """
    Observation passed to an agent.
    Events include both info (system-generated, trustworthy) and payload (agent-generated).
    """
    return {
        "agent_name": agent_name,
        "pending_events": [
            {
                "event_id": e.id,
                # System/tool-generated info (trustworthy)
                "info": e.info,
                # Agent-generated payload
                "payload": {
                    k: v
                    for k, v in e.payload.items()
                    if k not in {"data"}  # Exclude large data arrays from summary
                },
            }
            for e in pending_events
        ],
    }


# Graph building and representation for DIG analysis
@dataclass
class GraphNode:
    id: str
    layer: str
    label: str
    meta: Dict


@dataclass
class GraphEdge:
    src: str
    dst: str
    id: str
    meta: Dict
    index: int = 0


def build_activation_event_graph(dig: InteractionLog) -> Tuple[List[GraphNode], List[GraphEdge], Dict[str, List[str]], Dict[str, List[str]], Dict[str, str]]:
    """
    Build an alternating activation-event graph from an InteractionLog.
    
    Returns:
        - nodes: List of all nodes (activations and events)
        - edges: List of all edges (activation->event, event->activation)
        - activation_inputs: Map of activation_id -> list of input event IDs
        - activation_outputs: Map of activation_id -> list of output event IDs
        - event_source: Map of event_id -> source activation_id (for events with sources)
    """
    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []

    # Activation nodes
    for aid, act in dig.activations.items():
        # Classify agent nodes: submitting, problem-expanding, or problem-reducing
        classification = None
        if act.agent_name != "system":
            mode_val = getattr(act.mode, "value", str(act.mode))
            if mode_val == "Submit":
                classification = "submitting"
            else:
                num_input = len(act.input_event_ids)
                num_output = len(act.output_event_ids)
                classification = "problem-expanding" if num_output > num_input else "problem-reducing"
        
        nodes.append(
            GraphNode(
                id=aid,
                layer="Activation",
                label=getattr(act.mode, "value", str(act.mode)),
                meta={
                    "type": "activation",
                    "mode": getattr(act.mode, "value", str(act.mode)),
                    "classification": classification
                },
            )
        )

    # Event nodes and edges
    idx = 0
    for ev in dig.events.values():
        nodes.append(GraphNode(id=ev.id, layer="Event", label=ev.payload.get("type", "event"), meta={"type": "event"}))
        
        # Check if this is a system event (from system activation)
        is_system_event = False
        if ev.source_activation_id:
            src_act = dig.activations.get(ev.source_activation_id)
            is_system_event = src_act and src_act.agent_name == "system"
        
        if ev.source_activation_id:
            # Style activation→event edges
            # System activation→event edges should be dashed
            if is_system_event:
                prod_line_style = 'dash'
                prod_line_color = 'light-gray'
            else:
                prod_line_style = 'solid'
                prod_line_color = 'gray'
            
            edges.append(GraphEdge(
                src=ev.source_activation_id, 
                dst=ev.id, 
                id=f"{ev.id}:prod", 
                meta={
                    "event_id": ev.id, 
                    "system_event": is_system_event,
                    "line_style": prod_line_style,
                    "line_color": prod_line_color,
                    "useful": not is_system_event
                }, 
                index=idx
            ))
            idx += 1
        for dst_id, act in dig.activations.items():
            if ev.id in getattr(act, "input_event_ids", []):
                edge_key = f"{ev.id}->{dst_id}"
                # Include ALL edges (even deleted ones) for visualization
                # Mark deleted edges in metadata so they can be styled differently
                is_deleted = edge_key in dig.deleted_edges
                is_unconsumed = ev.id in getattr(act, "unconsumed_event_ids", [])
                is_wait = act.mode.value == "Wait" if hasattr(act.mode, "value") else str(act.mode) == "Wait"
                
                # Determine if edge is useful (solid) or not useful (dashed)
                # Dashed (not useful): deleted, unconsumed, wait incoming, or system event
                # Solid (useful): normal consumed edges
                useful = not (is_deleted or is_unconsumed or is_wait or is_system_event)
                
                # Determine line style and color based on edge type
                if is_deleted:
                    if act.mode == InteractionMode.DISCARD or (hasattr(act.mode, 'value') and act.mode.value == 'Discard'):
                        line_style = 'dash'
                        line_color = 'red'  # Discard
                    elif act.mode == InteractionMode.REROUTE or (hasattr(act.mode, 'value') and act.mode.value == 'Reroute'):
                        line_style = 'dash'
                        line_color = 'purple'  # Reroute
                    else:
                        line_style = 'dash'
                        line_color = 'gray'
                elif is_unconsumed:
                    line_style = 'dash'
                    line_color = 'gold'  # Unconsumed/returned to buffer
                elif is_wait:
                    line_style = 'dash'
                    line_color = 'orange'  # Wait
                elif is_system_event:
                    line_style = 'dash'
                    line_color = 'light-gray'  # System event
                else:
                    # Check for rerouted delivery edges (using stored edge type)
                    edge_type = ev.recipient_edge_type.get(act.agent_name)
                    if edge_type == 'rerouted_delivery':
                        line_style = 'solid'
                        line_color = 'purple'  # Rerouted delivery
                    else:
                        line_style = 'solid'
                        line_color = 'gray'  # Normal
                
                edges.append(
                    GraphEdge(
                        src=ev.id,
                        dst=dst_id,
                        id=edge_key,
                        meta={
                            "event_id": ev.id,
                            "dst_agent": act.agent_name,
                            "deleted": is_deleted,
                            "unconsumed": is_unconsumed,
                            "wait": is_wait,
                            "system_event": is_system_event,
                            "useful": useful,
                            "line_style": line_style,
                            "line_color": line_color
                        },
                        index=idx,
                    )
                )
                idx += 1

    activation_inputs = {aid: list(getattr(act, "input_event_ids", [])) for aid, act in dig.activations.items()}
    activation_outputs = {aid: list(getattr(act, "output_event_ids", [])) for aid, act in dig.activations.items()}
    event_source = {ev.id: ev.source_activation_id for ev in dig.events.values() if ev.source_activation_id}

    return nodes, edges, activation_inputs, activation_outputs, event_source
