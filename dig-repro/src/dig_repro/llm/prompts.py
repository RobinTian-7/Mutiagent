"""Prompt builders for DIG planners and judge."""

from __future__ import annotations

import json
from typing import Any

from dig_repro.events.models import Event


def build_agent_prompt(
    *,
    agent_name: str,
    problem_spec: str,
    all_agents: list[int],
    pending_events: list[Event],
) -> str:
    event_examples = [
        {
            "event_id": event.event_id,
            "type": event.event_type.value,
            "coverage_ids": event.coverage_ids[:20],
            "payload": event.payload,
            "lineage_id": event.lineage_id,
            "parent_event_ids": event.parent_event_ids,
            "final_answer": event.final_answer,
        }
        for event in pending_events
    ]
    return f"""You are {agent_name}, an autonomous agent in a cooperative multiagent problem-solving system.

GOAL: Work with your collaborators to solve the problem in the SHORTEST TIME possible. Coordinate efficiently and avoid redundant work.

PROBLEM CONTEXT
{problem_spec}

AVAILABLE AGENTS: {all_agents}

INPUT EVENTS JSON:
{json.dumps(event_examples, ensure_ascii=True)}

For each pending event, specify exactly one action: consume, reroute, discard, or wait.
If you consume a problem event without raw data, use one tool request: split_problem or get_raw_data.
If you consume raw_data or solution events, produce out_events directly.
If you submit, set final_answer=true on the produced solution event.
Prioritize aggregation when multiple solution events are available.
Stay focused on one task type per activation.

Return only JSON with this schema:
{{
  "input_actions": [{{"event_id": "...", "action": "consume|reroute|discard|wait", "reroute_to": [0,1]}}],
  "tool_calls": [{{"name": "split_problem|get_raw_data", "event_id": "...", "args": {{...}}}}],
  "out_events": [
    {{
      "event_type": "solution",
      "problem_id": "P",
      "payload": {{...}},
      "coverage_ids": [1,2],
      "recipient_ids": [0,1],
      "parent_event_ids": ["..."],
      "lineage_id": "...",
      "final_answer": false,
      "system_tags": []
    }}
  ],
  "is_final_answer": false,
  "reasoning": {{"observation": "...", "thought": "...", "action": "..."}}
}}
"""


def build_judge_prompt(
    *,
    dig_log: dict[str, Any],
    taxonomy_text: str,
) -> str:
    return f"""You are an expert system monitor for cooperative multi-agent systems.
Your role is to analyze the Dynamic Interaction Graph (DIG) and detect structural errors based solely on observable interaction patterns.
You do not have access to agent internals, reasoning traces, task semantics, or predefined workflows.
All judgments must be derived from DIG topology, event lineage, and interaction primitives (CONSUME, WAIT, REROUTE, DISCARD, SUBMIT).

ERROR TAXONOMY:
{taxonomy_text}

DIG LOG JSON:
{json.dumps(dig_log, ensure_ascii=True)}

Return only JSON:
{{
  "errors": [
    {{"kind": "ET|MC|OE|DL|ER|CLA|RSP", "severity": "critical|high|medium|low", "message": "...", "event_ids": ["..."], "activation_ids": ["..."]}}
  ],
  "interventions": [
    {{"kind": "inject_and_reroute|create_system_event", "target_event_ids": ["..."], "recipient_ids": [0], "message": "..."}}
  ]
}}
"""

