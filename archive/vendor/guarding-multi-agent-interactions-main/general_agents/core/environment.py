from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List, Optional, Set, Tuple

from .agent import Agent
from .dig import InteractionLog, InteractionEvent, InteractionMode
from ..problems.problem_base import Problem
from ..policies.agent_policy import AgentPolicy
from ..analysis.error_detection.error_detection import detect_and_report_errors, detect_orphaned_events, detect_excessive_rerouting, detect_repeated_efforts, detect_dependency_warning
from ..analysis.error_detection.intervention import check_and_apply_intervention, handle_no_progress_intervention, handle_orphaned_events_intervention, handle_excessive_rerouting_intervention, handle_repeated_efforts_intervention, handle_dependency_warning_intervention
from ..analysis.error_detection.llm_judge import LLMJudge, check_llm_judge


class MultiAgentEnvironment:
    def __init__(
        self,
        problem: Problem,
        agents: Dict[str, AgentPolicy],
        enable_intervention: bool = False,
        realtime_dig_viz=None,
        llm_judge: Optional[LLMJudge] = None,
    ):
        self.problem = problem
        self.agents = {
            name: Agent(name, policy)
            for name, policy in agents.items()
        }
        self.enable_intervention = enable_intervention
        self.realtime_dig_viz = realtime_dig_viz
        self.llm_judge = llm_judge
        self.detected_errors: Set[str] = set()  # Track reported errors
        self.blocked_submissions: List[InteractionEvent] = []  # Track blocked submissions for intervention case

    async def run(
        self,
        timeout_seconds: Optional[float] = None,
    ) -> Tuple[InteractionLog, Optional[InteractionEvent], int, bool]:
        start_time = time.time()
        # Prefix all runtime logs with elapsed time since start of run
        import builtins
        if not getattr(builtins.print, "_is_ts_print", False):
            original_print = builtins.print

            def _ts_print(*args, **kwargs):
                elapsed = time.time() - start_time
                original_print(f"[{elapsed:7.2f}s]", *args, **kwargs)

            _ts_print._is_ts_print = True  # type: ignore[attr-defined]
            builtins.print = _ts_print
        timed_out = False

        dig = InteractionLog()
        agent_names = list(self.agents.keys())

        stop_event = asyncio.Event()
        dig_lock = asyncio.Lock()
        winning_event: Optional[InteractionEvent] = None
        last_submit_event: Optional[InteractionEvent] = None
        
        # Reset blocked submissions for this run
        self.blocked_submissions = []

        # Initialize problem with initial events
        initial_events = self.problem.initial_events(dig, agent_names)
        for ev in initial_events:
            for recipient in ev.recipients:
                if recipient in self.agents:
                    await self.agents[recipient].add_to_buffer(ev)

        num_activations = 0
        running_tasks: Set[asyncio.Task] = set()
        
        print(f"[ENV] Started environment with agents: {agent_names}")

        async def handle_agent_activation(agent: Agent):
            """Handle a single agent activation independently"""
            nonlocal num_activations, winning_event, last_submit_event
            
            # Update DIG viz at start of activation
            if self.realtime_dig_viz is not None:
                try:
                    self.realtime_dig_viz.update_from_dig(dig)
                except Exception:
                    pass  # Ignore visualization errors
            
            # Dependency warning detection
            if self.enable_intervention and len(agent.buffer) >= 2:
                try:
                    should_intervene, lineage_info = detect_dependency_warning(
                        agent.buffer, agent.name, dig
                    )
                    if should_intervene and lineage_info:
                        handle_dependency_warning_intervention(lineage_info, agent.name, dig)
                except Exception as e:
                    print(f"[DEPENDENCY_WARNING] Error during detection: {e}")
            
            result = await agent.activate(self.problem, dig, agent_names, stop_event)
            
            if result is None:
                return
            
            # Process the result (solution checking and event delivery)
            async with dig_lock:
                num_activations += 1
                
                # Update real-time DIG visualization after activation completes and events generated
                if self.realtime_dig_viz is not None:
                    try:
                        self.realtime_dig_viz.update_from_dig(dig)
                    except Exception:
                        pass  # Ignore visualization errors

                # Run error detection and intervention check
                # Detection always runs, intervention only when enabled
                intervention_applied = False
                try:
                    intervention_applied = await check_and_apply_intervention(
                        dig, agent, result, apply_intervention=self.enable_intervention
                    )
                    
                    if intervention_applied:
                        # Update visualization to show system intervention
                        if self.realtime_dig_viz is not None:
                            try:
                                self.realtime_dig_viz.update_from_dig(dig)
                            except Exception:
                                pass  # Ignore visualization errors
                except Exception as e:
                    print(f"[INTERVENTION] Error during intervention check: {e}")
                
                # Handle SUBMIT mode
                if result.mode is InteractionMode.SUBMIT:
                    # Extra visualization update to ensure submission is visible
                    if self.realtime_dig_viz is not None:
                        try:
                            self.realtime_dig_viz.update_from_dig(dig)
                        except Exception:
                            pass  # Ignore visualization errors

                    if result.new_events:
                        last_submit_event = result.new_events[-1]
                    
                    # If intervention was applied (incomplete coverage), track blocked submission
                    if intervention_applied:
                        # Store the blocked submission events for later evaluation
                        for ev in result.new_events:
                            self.blocked_submissions.append(ev)
                            print(f"[ENV] Tracked blocked submission event {ev.id} from {agent.name}")
                        # If the intervention rerouted events back, retrigger the agent
                        if agent.should_trigger():
                            task = asyncio.create_task(handle_agent_activation(agent))
                            running_tasks.add(task)
                            task.add_done_callback(running_tasks.discard)
                        return
                    
                    # Otherwise, stop on first Submit (valid submission with full coverage or intervention disabled)
                    reference = self.problem.reference_solution()
                    status = self.problem.goal_status(dig)
                    
                    if status.done:
                        winning_event = status.winning_event
                        print(f"[{agent.name}] Submitted CORRECT solution! Stopping system.")
                        print(f"[{agent.name}] Reference solution: {reference}")
                    else:
                        print(f"[{agent.name}] Submitted INCORRECT solution. Stopping system.")
                        print(f"[{agent.name}] Reference solution: {reference}")
                    
                    stop_event.set()
                    
                    # Cancel all running tasks immediately
                    for task in list(running_tasks):
                        if not task.done():
                            task.cancel()
                    
                    return

                if result.mode is InteractionMode.TERMINATE:
                    print(f"[{agent.name}] Terminating")
                    return
                
                # Handle per-edge reroute actions: deliver rerouted events to new recipients
                # This replaces the old mode-based REROUTE handling
                if result.reroute_events and result.activation:
                    for ev_id, recipients in result.reroute_events.items():
                        ev = dig.events.get(ev_id)
                        if ev:
                            for recipient in recipients:
                                if recipient in self.agents:
                                    await self.agents[recipient].add_to_buffer(ev)
                                    print(f"[ENV] Delivered rerouted event {ev.id} to {recipient}")
                                    # Trigger recipient if it's not already active
                                    recipient_agent = self.agents[recipient]
                                    if recipient_agent.should_trigger():
                                        task = asyncio.create_task(handle_agent_activation(recipient_agent))
                                        running_tasks.add(task)
                                        task.add_done_callback(running_tasks.discard)
                                else:
                                    print(f"[ENV] WARNING: Reroute recipient {recipient} not in agents!")
                
                # Deliver new events to recipients (triggering them independently)
                for ev in result.new_events:
                    valid_recipients = [r for r in ev.recipients if r in self.agents]
                    
                    # Repeated efforts detection and intervention
                    if self.enable_intervention:
                        agent_buffers = {name: len(agent.buffer) for name, agent in self.agents.items()}
                        should_intervene, designated_handler = detect_repeated_efforts(
                            ev, valid_recipients, agent_buffers
                        )
                        if should_intervene and designated_handler:
                            handle_repeated_efforts_intervention(ev, designated_handler, dig)
                    
                    for r in valid_recipients:
                        await self.agents[r].add_to_buffer(ev)
                        print(f"[ENV] Delivered event {ev.id} to {r}")
                        
                        # Run error detection after event delivery
                        try:
                            self.detected_errors = detect_and_report_errors(dig, self.detected_errors)
                        except Exception as e:
                            print(f"[ERROR DETECTION] Error after event delivery: {e}")
                        
                        # Trigger recipient if it's not already active
                        recipient_agent = self.agents[r]
                        if recipient_agent.should_trigger():
                            task = asyncio.create_task(handle_agent_activation(recipient_agent))
                            running_tasks.add(task)
                            task.add_done_callback(running_tasks.discard)
                
                # Run error detection after activation completion
                try:
                    self.detected_errors = detect_and_report_errors(dig, self.detected_errors)
                except Exception as e:
                    print(f"[ERROR DETECTION] Error after activation completion: {e}")
                
                # Check LLM judge if enabled
                if self.llm_judge:
                    try:
                        await check_llm_judge(dig, self.llm_judge, self.agents)
                    except Exception as e:
                        print(f"[LLM-JUDGE] Error during LLM judge check: {e}")
                        import traceback
                        traceback.print_exc()

                # Check for orphaned events immediately after DISCARD actions
                if result.activation and result.activation.input_actions:
                    discarded_event_ids = [
                        ev_id for ev_id, action in result.activation.input_actions.items()
                        if action == "discard"
                    ]
                    
                    rerouted_event_ids = [
                        ev_id for ev_id, action in result.activation.input_actions.items()
                        if action == "reroute"
                    ]

                    if discarded_event_ids:
                        print(f"[ENV] Checking {len(discarded_event_ids)} discarded events for orphaning")
                        try:
                            # Check if any discarded events became orphaned
                            orphaned_event_ids = detect_orphaned_events(
                                dig,
                                self.detected_errors,
                                valid_agent_names=set(self.agents.keys()),
                                orphan_timeout=0.0  # Check immediately, no timeout
                            )

                            if orphaned_event_ids:
                                for event_id in orphaned_event_ids:
                                    dig.record_detection("orphaned_event")
                                    print(f"[ENV] Detected orphaned event immediately after discard: {event_id}")

                                if self.enable_intervention:
                                    await handle_orphaned_events_intervention(dig, list(orphaned_event_ids), list(self.agents.keys()))

                                    # Deliver rerouted orphaned events back to their source agents
                                    for event_id in orphaned_event_ids:
                                        event = dig.events.get(event_id)
                                        if event and event.info.get("intervention_type") == "orphaned_event":
                                            # Event has been rerouted back to source agent
                                            for agent_name in event.recipients:
                                                if agent_name in self.agents:
                                                    await self.agents[agent_name].add_to_buffer(event)
                                                    print(f"[ENV] Delivered orphaned event {event_id} back to source agent {agent_name}")

                                                    # Trigger agent if not already active
                                                    orphan_agent = self.agents[agent_name]
                                                    if orphan_agent.should_trigger():
                                                        task = asyncio.create_task(handle_agent_activation(orphan_agent))
                                                        running_tasks.add(task)
                                                        task.add_done_callback(running_tasks.discard)

                                    # Update visualization to show orphaned event intervention
                                    if self.realtime_dig_viz is not None:
                                        try:
                                            self.realtime_dig_viz.update_from_dig(dig)
                                        except Exception:
                                            pass  # Ignore visualization errors
                        except Exception as e:
                            print(f"[ERROR] Orphaned event detection after discard failed: {e}")
                    
                    # Check for excessive rerouting after REROUTE actions
                    if rerouted_event_ids:
                        try:
                            excessive_reroutes = detect_excessive_rerouting(
                                dig,
                                self.detected_errors,
                                max_reroutes=2
                            )
                            
                            if excessive_reroutes:
                                for event_id, count in excessive_reroutes.items():
                                    dig.record_detection("excessive_rerouting")
                                    print(f"[ENV] Detected excessive rerouting: event {event_id} rerouted {count} times")
                                
                                if self.enable_intervention:
                                    await handle_excessive_rerouting_intervention(dig, excessive_reroutes, list(self.agents.keys()))
                                    
                                    # Update visualization
                                    if self.realtime_dig_viz is not None:
                                        try:
                                            self.realtime_dig_viz.update_from_dig(dig)
                                        except Exception:
                                            pass  # Ignore visualization errors
                        except Exception as e:
                            print(f"[ERROR] Excessive rerouting detection failed: {e}")

                # Check if the agent that just finished should retrigger immediately
                # (in case new events arrived in its buffer during activation)
                if agent.should_trigger():
                    print(f"[ENV] Agent {agent.name} buffer changed during activation, retriggering immediately")
                    task = asyncio.create_task(handle_agent_activation(agent))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)

        try:
            # Start with initial agents that have events
            for agent in self.agents.values():
                if agent.should_trigger():
                    task = asyncio.create_task(handle_agent_activation(agent))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)
            
            # Monitor loop
            empty_count = 0
            while not stop_event.is_set():
                # Check timeout FIRST before anything else
                if timeout_seconds is not None and (time.time() - start_time) >= timeout_seconds:
                    print(f"[ENV] Timeout reached ({timeout_seconds}s), stopping")
                    timed_out = True
                    
                    # Create system termination event
                    system_activation = dig.record_activation(
                        agent_name="system",
                        mode=InteractionMode.TERMINATE,
                        input_events=[],
                        output_events=[],
                        started_at=time.time(),
                        ended_at=time.time()
                    )
                    print(f"[SYSTEM] Timeout - created system termination activation {system_activation.id}")
                    
                    # Send termination event to all agents
                    termination_event = dig.new_event(
                        payload={
                            "type": "system_termination",
                            "reason": "timeout",
                            "timeout_seconds": timeout_seconds
                        },
                        source_activation_id=system_activation.id,
                        recipients=list(self.agents.keys()),
                    )
                    
                    for agent_name in self.agents.keys():
                        await self.agents[agent_name].add_to_buffer(termination_event)
                        print(f"[ENV] Delivered termination event {termination_event.id} to {agent_name}")
                    
                    stop_event.set()
                    # Cancel all running tasks immediately so we don't wait for long LLM calls
                    for task in list(running_tasks):
                        if not task.done():
                            task.cancel()
                    break
                
                # Wait a bit for tasks to complete
                await asyncio.sleep(0.1)
                
                # Check if any tasks are still running or any agents are ready
                if running_tasks:
                    empty_count = 0
                    continue
                
                # Check if any agents are ready to activate
                ready_agents = [agent for agent in self.agents.values() if agent.should_trigger()]
                if ready_agents:
                    empty_count = 0
                    for agent in ready_agents:
                        task = asyncio.create_task(handle_agent_activation(agent))
                        running_tasks.add(task)
                        task.add_done_callback(running_tasks.discard)
                else:
                    # No agents ready to activate
                    empty_count += 1

                    # Backup check for orphaned events every 50 cycles (5 seconds)
                    # This catches orphans not detected immediately after discard
                    if empty_count % 50 == 0:
                        try:
                            orphaned_event_ids = detect_orphaned_events(
                                dig,
                                self.detected_errors,
                                valid_agent_names=set(self.agents.keys()),
                                orphan_timeout=5.0
                            )
                            if orphaned_event_ids:
                                for event_id in orphaned_event_ids:
                                    dig.record_detection("orphaned_event")
                                    print(f"[ENV] Detected orphaned event: {event_id}")

                                if self.enable_intervention:
                                    await handle_orphaned_events_intervention(dig, list(orphaned_event_ids), list(self.agents.keys()))

                                    # Deliver rerouted orphaned events back to their source agents
                                    for event_id in orphaned_event_ids:
                                        event = dig.events.get(event_id)
                                        if event and event.info.get("intervention_type") == "orphaned_event":
                                            # Event has been rerouted back to source agent
                                            for agent_name in event.recipients:
                                                if agent_name in self.agents:
                                                    await self.agents[agent_name].add_to_buffer(event)
                                                    print(f"[ENV] Delivered orphaned event {event_id} back to source agent {agent_name}")

                                                    # Trigger agent if not already active
                                                    agent = self.agents[agent_name]
                                                    if agent.should_trigger():
                                                        task = asyncio.create_task(handle_agent_activation(agent))
                                                        running_tasks.add(task)
                                                        task.add_done_callback(running_tasks.discard)

                                    if self.realtime_dig_viz is not None:
                                        try:
                                            self.realtime_dig_viz.update_from_dig(dig)
                                        except Exception:
                                            pass  # Ignore visualization errors
                        except Exception as e:
                            print(f"[ERROR] Orphaned event detection failed: {e}")

                    if empty_count > 80:  # 8 seconds of no activity
                        dig.record_detection("deadlock_error")
                        print("[ENV] Detected deadlock, broadcasting intervention")

                        if self.enable_intervention:
                            await handle_no_progress_intervention(dig, list(self.agents.keys()))

                            latest_event = list(dig.events.values())[-1]
                            for agent_name in self.agents.keys():
                                await self.agents[agent_name].add_to_buffer(latest_event)
                                print(f"[ENV] Delivered deadlock intervention to {agent_name}")

                            if self.realtime_dig_viz is not None:
                                try:
                                    self.realtime_dig_viz.update_from_dig(dig)
                                except Exception:
                                    pass  # Ignore visualization errors

                            for agent_name in self.agents.keys():
                                agent = self.agents[agent_name]
                                if agent.should_trigger():
                                    task = asyncio.create_task(handle_agent_activation(agent))
                                    running_tasks.add(task)
                                    task.add_done_callback(running_tasks.discard)

                            empty_count = 0
                            continue
                        else:
                            empty_count = 0
                            continue
            
            # Wait for all running tasks to complete
            if running_tasks:
                await asyncio.gather(*running_tasks, return_exceptions=True)

        except KeyboardInterrupt:
            print("\n[ENV] Interrupted by user")
            stop_event.set()
            # Cancel all running tasks
            for task in running_tasks:
                task.cancel()
            if running_tasks:
                await asyncio.gather(*running_tasks, return_exceptions=True)

        # If no winning event, use the latest submit event (even if intervention blocked)
        if winning_event is None and last_submit_event is not None:
            winning_event = last_submit_event
            print(f"[ENV] Using latest submit event {winning_event.id} for evaluation")
        # Fallback: if no submit event tracked but we have blocked submissions, use last blocked
        if winning_event is None and self.blocked_submissions:
            winning_event = self.blocked_submissions[-1]
            print(f"[ENV] Using last blocked submission {winning_event.id} for evaluation")

        # Display aggregate LLM usage statistics
        if getattr(dig, "llm_usage", None) and dig.llm_usage.get("calls", 0) > 0:
            print(
                "[LLM USAGE] "
                f"calls={dig.llm_usage.get('calls', 0)} "
                f"prompt_tokens={dig.llm_usage.get('prompt_tokens', 0)} "
                f"completion_tokens={dig.llm_usage.get('completion_tokens', 0)} "
                f"total_tokens={dig.llm_usage.get('total_tokens', 0)}"
            )
            model_name = os.getenv("AZURE_OPENAI_MODEL", "").strip()
            if model_name == "gpt-5-chat":
                prompt_tokens = dig.llm_usage.get("prompt_tokens", 0)
                completion_tokens = dig.llm_usage.get("completion_tokens", 0)
                input_cost = (prompt_tokens / 1_000_000) * 1.25
                output_cost = (completion_tokens / 1_000_000) * 10.0
                total_cost = input_cost + output_cost
                print(
                    "[LLM COST] "
                    f"model={model_name} "
                    f"estimated_cost_usd=${total_cost:.6f} "
                    f"(input=${input_cost:.6f}, output=${output_cost:.6f})"
                )

        return dig, winning_event, num_activations, timed_out
