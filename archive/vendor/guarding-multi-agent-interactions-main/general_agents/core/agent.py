"""
agent.py

Agent class that encapsulates agent state, buffer, and activation logic.
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional
from dataclasses import dataclass

from .dig import InteractionLog, InteractionEvent, InteractionMode, AgentActivation
from ..policies.agent_policy import AgentPolicy
from ..problems.problem_base import Problem


@dataclass
class ActivationResult:
    """Result of an agent activation."""
    mode: InteractionMode
    new_events: List[InteractionEvent]
    activation: AgentActivation
    reroute_events: dict = None  # event_id -> list of recipients for rerouted events
    

class Agent:
    """
    An agent in the multiagent system with its own event buffer and activation logic.
    """
    
    def __init__(self, name: str, policy: AgentPolicy):
        self.name = name
        self.policy = policy
        self.buffer: List[InteractionEvent] = []
        self.is_active = False
        self.buffer_lock = asyncio.Lock()
        self.buffer_changed = False  # Track if buffer has new events since last activation
        
    async def add_to_buffer(self, event: InteractionEvent):
        """Add event to buffer and mark as changed."""
        async with self.buffer_lock:
            event.received_at[self.name] = time.time()
            self.buffer.append(event)
            self.buffer_changed = True  # New event arrived
            print(f"[{self.name}] Added event {event.id} to buffer, buffer size: {len(self.buffer)}")
    
    def should_trigger(self) -> bool:
        """Decide if agent should activate based on buffer state."""
        return self.buffer_changed and not self.is_active
    
    async def activate(
        self,
        problem: Problem,
        dig: InteractionLog,
        agent_names: List[str],
        stop_event: asyncio.Event,
    ) -> Optional[ActivationResult]:
        """
        Process buffered events and generate decision.
        Returns ActivationResult if successful, None otherwise.
        """
        # Check if system should stop
        if stop_event.is_set():
            print(f"[{self.name}] Stop event detected, skipping activation")
            return None

        async with self.buffer_lock:
            if not self.buffer:
                return None
                
            self.is_active = True
            self.buffer_changed = False  # Clear the flag since we're processing now
            pending = self.buffer.copy()
            self.buffer.clear()
        
        # Show what we're processing
        print(f"[{self.name}] Activating with {len(pending)} event(s)")
        
        llm_start_time = time.time()
        
        # Track activation start
        activation_id = dig.start_activation(self.name, pending)
        
        try:
            decision = await self.policy.act(
                problem,
                dig,
                pending,
                agent_names=agent_names,
            )
            llm_end_time = time.time()
            
            # Remove from in-progress tracking
            dig.finish_activation(activation_id)
            
            # Process the decision
            mode = decision.mode
            messages = decision.new_events
            tool_requests = decision.tool_requests
            
            # ALL pending events are input to the activation
            input_events = pending
            
            # Check if any tool is being used
            has_tool = tool_requests is not None and len(tool_requests) > 0
            
            # Determine consumed/unconsumed based on per-edge input_actions
            # consume, discard, reroute = remove from buffer
            # wait = keep in buffer
            input_actions = decision.input_actions or []
            consumed_ids = set()
            reroute_events = {}  # event_id -> list of recipients
            
            for ia in input_actions:
                if ia.action in ("consume", "discard", "reroute"):
                    consumed_ids.add(ia.event_id)
                    if ia.action == "reroute" and ia.reroute_to:
                        reroute_events[ia.event_id] = ia.reroute_to
                # "wait" action: event stays in buffer (not added to consumed_ids)
            
            # If waiting with no input_actions, put events back in buffer (not consumed)
            if mode is InteractionMode.WAIT and not messages and not has_tool:
                unconsumed = pending  # Keep all events
            else:
                unconsumed = [e for e in pending if e.id not in consumed_ids]
            
            # Skip recording activation if agent waited with no input events
            if mode == InteractionMode.WAIT and not input_events and not messages and not has_tool:
                print(f"[{self.name}] Empty wait (no input), not recording activation")
                await self.return_to_buffer(unconsumed)
                return None
            
            # Execute tool request - creates events automatically
            tool_generated_events: List[InteractionEvent] = []
            
            # Block tool calls if agent is in Wait mode
            if has_tool and mode == InteractionMode.WAIT:
                print(f"[{self.name}] ERROR: Tool calls not allowed in Wait mode. Ignoring.")
                tool_requests = None
                has_tool = False
            
            # Import tool types for isinstance checks
            from ..policies.agent_policy import SplitAndSendToRecipients, SendProblemDataToRecipients
            
            # Execute tools based on type
            if tool_requests:
                for tool_request in tool_requests:
                    if isinstance(tool_request, SplitAndSendToRecipients):
                        try:
                            if not tool_request.assignments:
                                print(f"[{self.name}] WARNING: split_and_send called without assignments")
                            else:
                                print(f"[{self.name}] Executing split_and_send: {tool_request.num_chunks} sub-problems")
                                events = problem.split_problem_at_high_level(
                                    problem_id=tool_request.problem_id,
                                    splits=tool_request.assignments,
                                    dig=dig,
                                )
                                tool_generated_events.extend(events)
                                print(f"[{self.name}] split_and_send created {len(events)} event(s)")
                        except Exception as e:
                            print(f"[{self.name}] ERROR executing split_and_send: {e}")
                            import traceback
                            traceback.print_exc()
                    
                    elif isinstance(tool_request, SendProblemDataToRecipients):
                        try:
                            print(f"[{self.name}] Executing send_problem_data: problem={tool_request.problem_id}")
                            event = problem.get_raw_data_of_problem(
                                problem_id=tool_request.problem_id,
                                message=tool_request.instruction,
                                recipients=tool_request.recipients,
                                dig=dig,
                            )
                            tool_generated_events.append(event)
                            print(f"[{self.name}] send_problem_data created 1 event")
                        except Exception as e:
                            print(f"[{self.name}] ERROR executing send_problem_data: {e}")
                            import traceback
                            traceback.print_exc()
            
            # Create new events from messages (unless it's REROUTE or DISCARD)
            new_events: List[InteractionEvent] = []
            
            if mode == InteractionMode.REROUTE:
                # For REROUTE, don't create new events - just specify new recipients
                # The DIG will add these recipients to the original input events
                for spec in messages:
                    # Store the reroute info but don't create actual events
                    # The recipients in spec will be added to input events by record_activation
                    print(f"[{self.name}] Rerouting to: {spec.recipients}")
            elif mode == InteractionMode.DISCARD:
                # For DISCARD, no new events are created
                print(f"[{self.name}] Discarding {len(input_events)} event(s)")
            else:
                # For other modes, create events normally
                for spec in messages:
                    payload = dict(spec.payload)

                    ev = dig.new_event(
                        payload=payload,
                        source_activation_id=None,  # Will be set after activation is recorded
                        recipients=spec.recipients,
                    )
                    new_events.append(ev)
                    print(f"[{self.name}] Created event {ev.id} for recipients: {spec.recipients}")

            # Combine tool-generated events with manually created events
            all_output_events = tool_generated_events + new_events

            # Build tool_calls list for recording
            tool_calls = []
            if tool_requests:
                for tool_request in tool_requests:
                    if isinstance(tool_request, SplitAndSendToRecipients):
                        tool_calls.append({
                            "tool": "split_and_send",
                            "problem_id": tool_request.problem_id,
                            "num_chunks": tool_request.num_chunks,
                            "assignments": [{
                                "instruction": a.instruction,
                                "recipients": a.recipients
                            } for a in tool_request.assignments],
                        })
                    elif isinstance(tool_request, SendProblemDataToRecipients):
                        tool_calls.append({
                            "tool": "send_problem_data",
                            "problem_id": tool_request.problem_id,
                            "instruction": tool_request.instruction,
                            "recipients": tool_request.recipients,
                        })

            # Build input_actions dict from decision.input_actions list
            input_actions_dict = {}
            if decision.input_actions:
                for ia in decision.input_actions:
                    input_actions_dict[ia.event_id] = ia.action
            
            # Record activation in DIG with per-event reroute map and input actions
            activation = dig.record_activation(
                agent_name=self.name,
                mode=mode,
                input_events=input_events,
                output_events=all_output_events,
                started_at=llm_start_time,
                ended_at=llm_end_time,
                reroute_map=reroute_events if reroute_events else None,  # Built from input_actions
                unconsumed_events=unconsumed,
                reasoning=decision.reasoning,
                tool_calls=tool_calls,
                input_actions=input_actions_dict,  # Per-edge actions
            )
            
            # For SUBMIT, do not deliver events to any recipients; mark for evaluation only
            if mode == InteractionMode.SUBMIT:
                for ev in all_output_events:
                    ev.recipients = []
                    ev.info["submission_only"] = True

            # Link events to activation (for non-REROUTE/DISCARD modes)
            if mode not in (InteractionMode.REROUTE, InteractionMode.DISCARD):
                for ev in all_output_events:
                    ev.source_activation_id = activation.id

            # Return unconsumed events to buffer
            await self.return_to_buffer(unconsumed)
            
            print(f"[{self.name}] Completed activation")
            
            return ActivationResult(
                mode=mode,
                new_events=all_output_events,
                activation=activation,
                reroute_events=reroute_events,  # Per-event reroute targets
            )
        
        except asyncio.CancelledError:
            # Task was cancelled - record as TERMINATE
            activation_end_time = time.time()
            print(f"[{self.name}] Activation cancelled, recording as TERMINATE")
            
            activation = dig.record_activation(
                agent_name=self.name,
                mode=InteractionMode.TERMINATE,
                input_events=pending,
                output_events=[],
                started_at=llm_start_time,
                ended_at=activation_end_time,
                reasoning="Agent activation was cancelled",
            )
            
            dig.finish_activation(activation_id)
            
            # Re-raise to properly handle cancellation
            raise
            
        except Exception as e:
            print(f"[{self.name}] ERROR in policy.act: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            # Remove from in-progress tracking on error
            dig.finish_activation(activation_id)
            return None
            
        finally:
            async with self.buffer_lock:
                self.is_active = False
    
    async def return_to_buffer(self, events: List[InteractionEvent]):
        """Put unconsumed events back in buffer (does NOT mark as changed)."""
        if events:
            async with self.buffer_lock:
                self.buffer.extend(events)
                # Do NOT set buffer_changed = True here!
                # These are old events, not new triggers
                print(f"[{self.name}] Returned {len(events)} event(s) to buffer")
    
    def get_buffer_size(self) -> int:
        """Get current buffer size (non-blocking read)."""
        return len(self.buffer)
