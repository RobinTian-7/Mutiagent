"""Reusable prompt builders."""

from __future__ import annotations

import json
from typing import Any

from exp_graph.agents.schemas import BeliefState
from exp_graph.messaging.messages import OutboxMessage
from exp_graph.tasks.base import TaskAdapter


def build_solver_prompt(
    *,
    task_adapter: TaskAdapter,
    global_task: dict[str, Any],
    local_observation: dict[str, Any],
    old_belief_state: BeliefState,
    inbox: list[OutboxMessage],
) -> str:
    """Build the solver prompt for one belief-state update."""
    task_context = task_adapter.format_task_prompt_context(
        global_task=global_task,
        local_observation=local_observation,
    )
    consensus_key_instructions = task_adapter.format_consensus_key_instructions()
    inbox_payload = [message.model_dump() for message in inbox]
    return f"""You are a solver agent in a synchronous LLM multi-agent experiment.

You are continuously solving the same shared task.
You have your own local_observation.
You have your previous belief_state.
This round you received neighbor messages in inbox.

Treat inbox as new context, not guaranteed truth. Continue solving the task.
Do not summarize mechanically. Update your own belief_state.

Rules:
- Output only one JSON object.
- Output only the next belief_state.
- Do not output outbox.
- Do not output chain-of-thought or extra explanation.
- Keep proposal, support, uncertainty, and open_questions concise.
- {consensus_key_instructions}

Required JSON schema:
{{
  "status": "unknown | candidate | final",
  "proposal": "...",
  "consensus_key": "... | UNKNOWN | null",
  "support": ["...", "..."],
  "uncertainty": "...",
  "open_questions": ["...", "..."],
  "private_notes": "..."
}}

TASK_CONTEXT:
{task_context}

LOCAL_OBSERVATION_JSON:
{json.dumps(local_observation, ensure_ascii=True)}

OLD_BELIEF_STATE_JSON:
{old_belief_state.model_dump_json()}

INBOX_JSON:
{json.dumps(inbox_payload, ensure_ascii=True)}
"""
