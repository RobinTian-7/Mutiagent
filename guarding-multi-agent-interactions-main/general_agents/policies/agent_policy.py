"""
agent_policy.py

Abstract base class and LLM-based implementation for agent policies in multi-agent interactions.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel, Field

load_dotenv()

from ..core.dig import InteractionLog, InteractionEvent, InteractionMode, build_observation
from ..problems.problem_base import Problem


class EventSpec(BaseModel):
    """Specification for an event to be created."""
    event_type: Literal["problem", "solution"] = Field(
        description="problem or solution."
    )
    problem_id: str = Field(
        description="Problem ID (e.g., P, P_1)."
    )
    payload_json: str = Field(
        default="{}",
        description="Event payload JSON string."
    )
    recipients: List[str] = Field(
        default_factory=list,
        description="Recipient agent names (non-empty)."
    )


class ChunkAssignment(BaseModel):
    """Assignment for a single chunk of a split problem."""
    instruction: str = Field(description="Instruction for this chunk.")
    recipients: List[str] = Field(
        description="Recipient agent names (non-empty)."
    )


class SplitAndSendToRecipients(BaseModel):
    """Split a problem into sub-problems and send each sub-problem to corresponding recipients."""
    tool: Literal["split_and_send"] = Field(default="split_and_send", description="Tool identifier")
    problem_id: str = Field(description="Problem ID.")
    num_chunks: int = Field(description="Number of sub-problems.")
    assignments: List[ChunkAssignment] = Field(
        description="One assignment per sub-problem; length == num_chunks."
    )


class SendProblemDataToRecipients(BaseModel):
    """Send problem data to recipient agents for processing."""
    tool: Literal["send_problem_data"] = Field(default="send_problem_data", description="Tool identifier")
    problem_id: str = Field(description="Problem ID.")
    instruction: str = Field(description="Instruction for recipients.")
    recipients: List[str] = Field(description="Recipient agent names.")


# Union type for tool requests
ToolRequest = Union[SplitAndSendToRecipients, SendProblemDataToRecipients]


class InputEventAction(BaseModel):
    """Action to take on a specific input event. You MUST specify an action for each input event."""
    event_id: str = Field(description="Input event ID.")
    action: Literal["consume", "reroute", "discard", "wait"] = Field(
        description="consume, reroute, discard, or wait."
    )
    reroute_to: Optional[List[str]] = Field(
        default=None,
        description="Required when action='reroute'."
    )


class AgentDecisionOutput(BaseModel):
    """Agent decision output structure."""
    input_actions: List[InputEventAction] = Field(
        default_factory=list,
        description="Action for each input event."
    )
    is_final_answer: bool = Field(
        default=False,
        description="True only for final submission."
    )
    tool_requests: Optional[List[ToolRequest]] = Field(
        default=None,
        description="Tool calls (if any).",
    )
    out_events: List[EventSpec] = Field(
        default_factory=list,
        description="Output events for consumed inputs."
    )
    reasoning: str = Field(description="Compact reasoning.")


@dataclass
class InteractionMessage:
    payload: Dict[str, Any]
    recipients: List[str]


@dataclass
class AgentDecision:
    mode: InteractionMode  # Derived from input_actions
    new_events: List[InteractionMessage]
    input_actions: List[InputEventAction]  # Per-event actions (consume/reroute/discard/wait)
    is_final_answer: bool = False
    tool_requests: Optional[List[ToolRequest]] = None
    reasoning: Optional[str] = None


class AgentPolicy(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def act(
        self,
        problem: Problem,
        dig: InteractionLog,
        pending_events: List[InteractionEvent],
        agent_names: Optional[List[str]] = None,
    ) -> AgentDecision:
        raise NotImplementedError


AGENT_INSTRUCTIONS_TEMPLATE = """
You are {agent_name}, an autonomous agent in a cooperative multiagent problem-solving system.

GOAL: Work with your collaborators to solve the problem in the SHORTEST TIME possible. Coordinate efficiently and avoid redundant work.

PROBLEM CONTEXT

{problem_spec}

AVAILABLE AGENTS: {all_agents}

INPUT EVENT ACTIONS

For each pending event, specify ONE action:

  "consume"  - Process this event. MUST produce output event(s) OR use a tool.
               - If you consume, you MUST generate something (event or tool call).
               - If you're not ready to process it, use "wait" instead.
               - If you don't want it, use "discard" instead.
  "reroute"  - Forward to other agents. MUST specify reroute_to recipients.
  "discard"  - Drop permanently (for duplicates/irrelevant events).
  "wait"     - Keep in buffer for later (need more data first).

You MUST specify an action for EVERY pending event.

HOW TO PICK ACTION FOR EACH EVENT

For PROBLEM events (without raw data):
  - CONSUME: you MUST use a tool (split_problem_at_high_level or get_raw_data_of_problem)
  - REROUTE: forward to another agent if you're busy
  - WAIT: keep for later if you have higher priority work

For RAW DATA events:
  - CONSUME: compute solution and output a solution event; share your solution to others to speed up the process
  - WAIT: if you need more data first

For SOLUTION events:
  - CONSUME: aggregate with other solutions you have
  - DISCARD: if it's a duplicate of information you already have
  - WAIT: if you're expecting more solutions to aggregate

AGGREGATION: When consuming multiple solution events, reduce redundancy and output ONE combined solution.

SUBMIT: Set is_final_answer=True when your solution is complete or good enough.

HANDLING MULTIPLE INPUTS: Prioritize aggregation if you have multiple solutions. Stay focused on one task type per activation.

EVENT TYPES

  "problem"  - A task to solve. Created by tools (split_problem_at_high_level, get_raw_data_of_problem).
               A problem is only solvable if it includes raw data; otherwise, you must call get_raw_data_of_problem first.
  "solution" - An answer. ONLY create when:
               1. Computing result from RAW DATA
               2. Aggregating multiple solutions
               If it solves root P, set is_final_answer=True.

{event_examples}

TOOLS

- If you consume a PROBLEM event without raw data, you MUST use a tool
  (split_problem_at_high_level or get_raw_data_of_problem). Tools generate events for that problem.
- Do NOT also create out_events for the same consumed PROBLEM.
- You MUST still create out_events for any other consumed inputs not handled by a tool
  (e.g., aggregated solution events).

{tools_description}

{capability_explain}

OUTPUT FORMAT

- input_actions: REQUIRED. {{event_id, action, reroute_to (if rerouting)}}
- is_final_answer: Set to True when you want to SUBMIT a final solution
  * If you have a reasonable answer, submit it!
- tool_requests OR out_events (mutually exclusive)
- reasoning: {{observation, thought, action}}
- FINAL SUBMISSION payload must include: {{\"type\": \"solution\", \"problem_id\": \"P\", \"solution\": {{...}}}}
- NO EMPTY ACTIVATIONS: You MUST use tools OR generate output events (or both). You cannot do neither.

REASONING GUIDANCE

- Be compact.
- Include only important details needed to justify actions and help teammates.
"""


def _select_azure_config(agent_name: str, total_agents: int = None) -> Dict[str, str]:
    """Select Azure OpenAI config based on agent name, distributing evenly across available backends."""
    default = {
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "api_key": os.getenv("AZURE_OPENAI_API_KEY"),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
        "deployment": os.getenv("AZURE_OPENAI_MODEL"),
    }

    backup1 = {
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT_BACKUP1"),
        "api_key": os.getenv("AZURE_OPENAI_API_KEY_BACKUP1"),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION_BACKUP1") or default["api_version"],
        "deployment": os.getenv("AZURE_OPENAI_MODEL_BACKUP1") or default["deployment"],
    }

    backup2 = {
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT_BACKUP2"),
        "api_key": os.getenv("AZURE_OPENAI_API_KEY_BACKUP2"),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION_BACKUP2") or default["api_version"],
        "deployment": os.getenv("AZURE_OPENAI_MODEL_BACKUP2") or default["deployment"],
    }

    # Build list of available backends
    backends = [default]
    if all(backup1.values()):
        backends.append(backup1)
    if all(backup2.values()):
        backends.append(backup2)
    
    num_backends = len(backends)
    
    # Extract agent index from name (e.g., "Agent3" -> 3)
    digits = ""
    for ch in reversed(agent_name):
        if ch.isdigit():
            digits = ch + digits
        elif digits:
            break
    agent_idx = int(digits) if digits else 1
    
    # Distribute agents evenly: agent_idx % num_backends
    # Agent1 -> backend 0, Agent2 -> backend 1, Agent3 -> backend 2, Agent4 -> backend 0, etc.
    backend_idx = (agent_idx - 1) % num_backends
    
    print(f"[CONFIG] {agent_name}: idx={agent_idx}, backends={num_backends}, assigned=backend{backend_idx}")
    
    return backends[backend_idx]


def _make_llm(agent_name: str) -> AzureChatOpenAI:
    cfg = _select_azure_config(agent_name)
    # Debug: Print which endpoint this agent is using
    endpoint_short = cfg["endpoint"].split("//")[1].split(".")[0] if "//" in cfg["endpoint"] else cfg["endpoint"]
    print(f"[{agent_name}] Using LLM endpoint: {endpoint_short}")
    return AzureChatOpenAI(
        azure_endpoint=cfg["endpoint"],
        api_key=cfg["api_key"],
        api_version=cfg["api_version"],
        azure_deployment=cfg["deployment"],
        temperature=0.2,
        request_timeout=8.0,  # 8-second timeout for API calls
    )


# Global list to track LLM clients for cleanup
_llm_clients = []


def register_llm_client(client):
    """Register an LLM client for cleanup."""
    _llm_clients.append(client)


def _extract_usage(raw_response) -> Dict[str, int]:
    """Best-effort extraction of token usage from a LangChain response."""
    if raw_response is None:
        return {}
    usage = {}
    usage_meta = getattr(raw_response, "usage_metadata", None) or {}
    if usage_meta:
        usage["prompt_tokens"] = usage_meta.get("input_tokens") or usage_meta.get("prompt_tokens")
        usage["completion_tokens"] = usage_meta.get("output_tokens") or usage_meta.get("completion_tokens")
        usage["total_tokens"] = usage_meta.get("total_tokens")
    if not usage or all(v is None for v in usage.values()):
        resp_meta = getattr(raw_response, "response_metadata", None) or {}
        token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
        if token_usage:
            usage["prompt_tokens"] = token_usage.get("prompt_tokens")
            usage["completion_tokens"] = token_usage.get("completion_tokens")
            usage["total_tokens"] = token_usage.get("total_tokens")
    return {k: v for k, v in usage.items() if v is not None}


async def cleanup_llm_clients():
    """Cleanup all registered LLM clients."""
    for client in _llm_clients:
        try:
            if hasattr(client, 'client') and hasattr(client.client, 'aclose'):
                await client.client.aclose()
        except (RuntimeError, Exception):
            # Ignore cleanup errors - this is expected when system terminates early
            # due to solution submission or timeout
            pass
    _llm_clients.clear()


class LLMAgentPolicy(AgentPolicy):
    async def act(
        self,
        problem: Problem,
        dig: InteractionLog,
        pending_events: List[InteractionEvent],
        agent_names: Optional[List[str]] = None,
    ) -> AgentDecision:
        if not pending_events:
            return AgentDecision(
                mode=InteractionMode.WAIT,
                new_events=[],
                input_actions=[],
                is_final_answer=False,
                tool_requests=None,
                reasoning=None,
            )

        # Build observation (event_id included in pending_events)
        observation = build_observation(self.name, pending_events)

        # Problem specific context
        problem_spec = problem.problem_spec(context_limit=1000)

        # Agent list
        if agent_names is None:
            all_agents = sorted({act.agent_name for act in dig.activations.values()})
        else:
            all_agents = sorted(agent_names)
        agent_name_map = {a: a for a in all_agents}
        agent_name_norm_map = {a.replace(" ", "").lower(): a for a in all_agents}

        # System prompt with dynamic tools description
        system_prompt = AGENT_INSTRUCTIONS_TEMPLATE.format(
            problem_spec=problem_spec,
            agent_name=self.name,
            all_agents=", ".join(all_agents),
            tools_description=problem.tools_description(),
            capability_explain=problem.capability_explain(),
            event_examples=problem.event_examples(),
        )

        llm = _make_llm(self.name)
        register_llm_client(llm)

        # Use structured output (strict mode) and keep raw for usage tracking when supported
        try:
            llm_with_structured = llm.with_structured_output(AgentDecisionOutput, include_raw=True)
        except TypeError:
            llm_with_structured = llm.with_structured_output(AgentDecisionOutput)

        # Observation goes at the top level of the user payload
        user_payload = json.dumps(
            {
                "agent_name": self.name,
                "observation": observation,
            },
            ensure_ascii=False,
        )

        # Invoke with structured output
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload}
        ]

        print(f"[{self.name}] Calling LLM with {len(pending_events)} pending event(s)...")

        try:
            # Wrap in asyncio.wait_for to ensure timeout is enforced
            import asyncio
            response = await asyncio.wait_for(
                llm_with_structured.ainvoke(messages),
                timeout=10.0  # 10-second hard timeout
            )
        except asyncio.TimeoutError:
            print(f"[{self.name}] LLM TIMEOUT: Call exceeded 10 seconds")
            raise
        except Exception as e:
            print(f"[{self.name}] LLM ERROR: {type(e).__name__}: {e}")
            raise

        if isinstance(response, dict) and "parsed" in response:
            structured_output: AgentDecisionOutput = response.get("parsed")
            raw_response = response.get("raw")
        else:
            structured_output = response
            raw_response = None

        usage = _extract_usage(raw_response)
        dig.record_llm_usage(
            prompt_tokens=usage.get("prompt_tokens") if usage else None,
            completion_tokens=usage.get("completion_tokens") if usage else None,
            total_tokens=usage.get("total_tokens") if usage else None,
        )

        # Process input_actions to count action types for logging
        input_actions = structured_output.input_actions or []
        consume_count = 0
        reroute_count = 0
        discard_count = 0
        wait_count = 0
        
        for action in input_actions:
            if action.action == "consume":
                consume_count += 1
            elif action.action == "reroute":
                reroute_count += 1
            elif action.action == "discard":
                discard_count += 1
            elif action.action == "wait":
                wait_count += 1
        
        # Derive mode from actions (allow implicit submit when sending to system)
        is_final_answer = structured_output.is_final_answer

        if is_final_answer:
            mode = InteractionMode.SUBMIT
        elif not input_actions or all(a.action == "wait" for a in input_actions):
            mode = InteractionMode.WAIT  # No actions or all wait = wait
        elif all(a.action == "reroute" for a in input_actions if a.action != "wait"):
            mode = InteractionMode.REROUTE
        elif all(a.action == "discard" for a in input_actions if a.action != "wait"):
            mode = InteractionMode.DISCARD
        else:
            mode = InteractionMode.RESPOND

        messages_out: List[InteractionMessage] = []
        for spec in structured_output.out_events:
            # Normalize recipients (strip "(pending)" and map to known agent names)
            normalized_recipients: List[str] = []
            for r in (spec.recipients or []):
                cleaned = r.replace("(pending)", "").strip()
                if cleaned in agent_name_map:
                    normalized_recipients.append(cleaned)
                    continue
                key = cleaned.replace(" ", "").lower()
                normalized_recipients.append(agent_name_norm_map.get(key, cleaned))

            # Parse JSON string payload
            try:
                payload_dict = json.loads(spec.payload_json) if spec.payload_json and spec.payload_json != "{} " else {}
            except json.JSONDecodeError:
                print(f"[{self.name}] WARNING: Invalid payload JSON, using empty dict")
                payload_dict = {}
            
            # Add event metadata to payload
            payload_dict["type"] = spec.event_type
            payload_dict["problem_id"] = spec.problem_id
            
            messages_out.append(
                InteractionMessage(
                    payload=payload_dict,
                    recipients=normalized_recipients,
                )
            )

        reasoning = structured_output.reasoning
        tool_requests = structured_output.tool_requests

        # Log decision
        tool_info = "none"
        if tool_requests:
            tool_infos = []
            for tr in tool_requests:
                if isinstance(tr, SplitAndSendToRecipients):
                    tool_infos.append(f"split_and_send(sub_problems={tr.num_chunks})")
                elif isinstance(tr, SendProblemDataToRecipients):
                    tool_infos.append(f"send_problem_data(problem={tr.problem_id})")
            tool_info = ", ".join(tool_infos)
        
        print(
            f"[{self.name}] Decision mode={mode.value} "
            f"tools={tool_info} "
            f"out_events={len(messages_out)}"
        )
        print(f"  Input actions: {len(input_actions)} (consume={consume_count}, reroute={reroute_count}, discard={discard_count}, wait={wait_count})")
        print(f"  Reasoning: {reasoning}")
        if tool_requests:
            for tr in tool_requests:
                if isinstance(tr, SplitAndSendToRecipients):
                    print(
                        f"  SplitAndSend problem_id={tr.problem_id} "
                        f"num_sub_problems={tr.num_chunks} "
                        f"assignments={len(tr.assignments)}"
                    )
                elif isinstance(tr, SendProblemDataToRecipients):
                    print(
                        f"  SendProblemData problem_id={tr.problem_id} "
                        f"recipients={tr.recipients}"
                    )
        for i, msg in enumerate(messages_out):
            event_type = msg.payload.get("_event_type", "unknown")
            problem_id = msg.payload.get("_problem_id", "unknown")
            print(
                f"  Event {i} [{event_type}] problem_id={problem_id} "
                f"recipients={msg.recipients}"
            )

        return AgentDecision(
            mode=mode,
            new_events=messages_out,
            input_actions=input_actions,
            is_final_answer=is_final_answer,
            tool_requests=tool_requests,
            reasoning=reasoning,
        )
