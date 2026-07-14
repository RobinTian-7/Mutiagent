"""Independent architect, repair loop, execution and audit for PythonGen."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from exp_graph.llm.base import LLMClient
from exp_graph.mas.leakage_audit import assert_prompt_clean
from exp_graph.mas.python_code import (
    DEFAULT_MESSAGE_ONLY_PROGRAM,
    DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
    DEFAULT_PYTHON_PROGRAM,
    PYTHON_AST_POLICY_VERSION,
    PYTHON_EXECUTION_CONTRACT_VERSION,
    PYTHON_WORKER_CONTRACTS,
    PythonValidationReport,
    default_python_program,
    python_source_sha256,
    validate_python_source,
)
from exp_graph.mas.python_code_runner import (
    CodeProcessRunner,
    PythonExecutionLimits,
    PythonExecutionResult,
)
from exp_graph.mas.python_mutation import (
    PYTHON_MUTATION_PATCH_FORMAT,
    PythonMutationPatch,
    PythonMutationSkipped,
    apply_python_mutation_patch,
    build_python_mutation_prompt,
    extract_evolve_blocks,
    insight_ids_from_context,
    parse_python_mutation_patch,
    sanitize_python_skill_context,
    split_python_skill_context,
)
from exp_graph.mas.role_llm import create_role_llm_client, resolve_role_llm_config
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest, SkillCard
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.skill_payloads import (
    planner_mode_from_skill,
    python_source_from_skill,
    python_worker_contract_from_skill,
)


_PYTHON_SOURCE_KEYS = ("source_code", "python_source", "code", "main")
_PYTHON_FENCE_RE = re.compile(
    r"```(?:python|py)?[ \t]*\r?\n(?P<source>.*?)```",
    re.IGNORECASE | re.DOTALL,
)
PYTHON_SCAFFOLD_VERSION = "python_mas_scaffold_v1"
PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION = "python_mas_scaffold_message_only_v1"
PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION = (
    "python_mas_scaffold_message_only_v2_parallel_v1"
)


def python_scaffold_version(worker_contract: str) -> str:
    """Return the audited scaffold identity for one worker contract."""
    if worker_contract == "message_only_v1":
        return PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION
    if worker_contract == "message_only_v2":
        return PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION
    return PYTHON_SCAFFOLD_VERSION


class PythonGenerationError(RuntimeError):
    """Python generation failed honestly; callers must score it as validity=0."""

    def __init__(
        self,
        reason: str,
        *,
        error_type: str | None = None,
        artifacts_dir: Path | None = None,
        metrics: dict[str, Any] | None = None,
        program_sha256: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_type = error_type
        self.artifacts_dir = artifacts_dir
        self.metrics = dict(metrics or {})
        self.program_sha256 = program_sha256


class PythonCodePlanningResult:
    """Selected source, authoritative execution result and audit metadata."""

    def __init__(
        self,
        *,
        source: str,
        execution: PythonExecutionResult,
        artifacts_dir: Path,
        provenance: str,
        architect_prompt: str | None,
        attempts: list[dict[str, Any]],
        planner_model_calls: int,
        repair_model_calls: int,
        selected_skill_id: str | None = None,
        innovation_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.execution = execution
        self.artifacts_dir = artifacts_dir
        self.provenance = provenance
        self.architect_prompt = architect_prompt
        self.attempts = attempts
        self.planner_model_calls = planner_model_calls
        self.repair_model_calls = repair_model_calls
        self.selected_skill_id = selected_skill_id
        self.innovation_metadata = dict(innovation_metadata or {})


def build_python_architect_scaffold(
    worker_contract: str = "action_json_v1",
) -> str:
    """Return the known-valid program with narrow model-editable regions."""
    if worker_contract == "message_only_v1":
        return _build_message_only_scaffold()
    if worker_contract == "message_only_v2":
        return _build_message_only_v2_scaffold()
    if worker_contract != "action_json_v1":
        raise ValueError(f"unknown python worker contract {worker_contract!r}")
    scaffold = DEFAULT_PYTHON_PROGRAM.strip()
    replacements = {
        "                action_contract = (\n": (
            "                # EVOLVE-BLOCK-START: worker_instruction\n"
            "                action_contract = (\n"
        ),
        "                worker_prompt = action_contract + local_prompt\n": (
            "                worker_prompt = action_contract + local_prompt\n"
            "                # EVOLVE-BLOCK-END: worker_instruction\n"
        ),
        "                    if information_goal == \"sink\":\n": (
            "                    # EVOLVE-BLOCK-START: fallback_routing\n"
            "                    if information_goal == \"sink\":\n"
        ),
        (
            "                    if information_goal == \"all_agents\" and "
            "round_idx == 0 and agent_id == n_agents - 1:\n"
            "                        fallback_send = False\n"
        ): (
            "                    if information_goal == \"all_agents\" and "
            "round_idx == 0 and agent_id == n_agents - 1:\n"
            "                        fallback_send = False\n"
            "                    # EVOLVE-BLOCK-END: fallback_routing\n"
        ),
        '                        "submit": round_idx + 1 >= max_rounds,\n': (
            "                        # EVOLVE-BLOCK-START: submission_policy\n"
            '                        "submit": round_idx + 1 >= max_rounds,\n'
            "                        # EVOLVE-BLOCK-END: submission_policy\n"
        ),
    }
    for original, marked in replacements.items():
        if original not in scaffold:
            raise RuntimeError("default Python scaffold marker target is missing")
        scaffold = scaffold.replace(original, marked, 1)
    return scaffold


def _build_message_only_scaffold() -> str:
    """Mark the two Planner-owned plan_turn regions as model-editable.

    The worker instruction constants are deliberately NOT an editable region:
    the bootstrap wrapper enforces the canonical prompt byte-for-byte, so a
    rewritten instruction would fail closed at execution time.
    """
    scaffold = DEFAULT_MESSAGE_ONLY_PROGRAM.strip()
    replacements = {
        (
            '    if information_goal == "sink":\n'
            "        if agent_id == selected_primary and (\n"
        ): (
            "    # EVOLVE-BLOCK-START: submission_policy\n"
            '    if information_goal == "sink":\n'
            "        if agent_id == selected_primary and (\n"
        ),
        (
            "    if round_idx + 1 >= max_rounds:\n"
            '        return {"mode": "idle", "recipients": []}\n'
        ): (
            "    # EVOLVE-BLOCK-END: submission_policy\n"
            "    # EVOLVE-BLOCK-START: routing_policy\n"
            "    if round_idx + 1 >= max_rounds:\n"
            '        return {"mode": "idle", "recipients": []}\n'
        ),
        (
            '    return {"mode": "send", "recipients": [(agent_id + 1) % n_agents]}\n'
        ): (
            '    return {"mode": "send", "recipients": [(agent_id + 1) % n_agents]}\n'
            "    # EVOLVE-BLOCK-END: routing_policy\n"
        ),
    }
    for original, marked in replacements.items():
        if original not in scaffold:
            raise RuntimeError(
                "message_only Python scaffold marker target is missing"
            )
        scaffold = scaffold.replace(original, marked, 1)
    return scaffold


def _build_message_only_v2_scaffold() -> str:
    """Expose only the communication policy; the submit barrier is immutable."""
    scaffold = DEFAULT_MESSAGE_ONLY_V2_PROGRAM.strip()
    replacements = {
        "def plan_submit_round(n_agents, max_rounds, information_goal):\n"
        "    return max_rounds - 1\n": (
            "def plan_submit_round(n_agents, max_rounds, information_goal):\n"
            "    # EVOLVE-BLOCK-START: schedule_policy\n"
            "    return max_rounds - 1\n"
            "    # EVOLVE-BLOCK-END: schedule_policy\n"
        ),
        '    if information_goal == "sink":\n': (
            "    # EVOLVE-BLOCK-START: routing_policy\n"
            '    if information_goal == "sink":\n'
        ),
        '    return {"mode": "send", "recipients": recipients}\n': (
            '    return {"mode": "send", "recipients": recipients}\n'
            "    # EVOLVE-BLOCK-END: routing_policy\n"
        ),
    }
    for original, marked in replacements.items():
        if original not in scaffold:
            raise RuntimeError(
                "message_only_v2 Python scaffold marker target is missing"
            )
        scaffold = scaffold.replace(original, marked, 1)
    return scaffold


def build_python_architect_prompt(
    *,
    request: PlannerRequest,
    task_brief: str | None,
    runtime: MASRuntimeConfig,
) -> str:
    """Build genuinely different sink/all-agent code-generation contracts."""
    worker_contract = getattr(
        runtime, "python_worker_contract", "action_json_v1"
    )
    if worker_contract == "message_only_v1":
        return _append_python_architect_context(
            _build_message_only_architect_prompt(
                request=request,
                task_brief=task_brief,
                runtime=runtime,
            ),
            runtime,
        )
    if worker_contract == "message_only_v2":
        return _append_python_architect_context(
            _build_message_only_v2_architect_prompt(
                request=request,
                task_brief=task_brief,
                runtime=runtime,
            ),
            runtime,
        )
    common = {
        "role": "Write one complete executable Python program for a multi-agent task.",
        "planner_mode": "python_generate",
        "task_description": task_brief,
        "n_agents": request.n_agents,
        "budgets": {
            "max_rounds": runtime.python_max_rounds,
            "max_model_calls": runtime.python_max_model_calls,
            "max_completion_tokens": runtime.python_max_completion_tokens,
            "max_messages": runtime.python_max_messages,
        },
        "source_contract": {
            "read": "Use json.load(sys.stdin) exactly once.",
            "client": (
                "Import create_llm_client only from exp_graph.llm.factory; use "
                "worker_llm payload values unchanged; call client.complete directly."
            ),
            "write": "Use sys.stdout.write exactly once for one JSON object.",
            "imports": ["json", "sys", "exp_graph.llm.factory.create_llm_client"],
            "loops": "Only finite for/range loops bounded by payload values.",
            "worker_header": "Every worker prompt starts with PYTHON_AGENT_ID:<current id>.",
            "round_header": "Every worker prompt includes PYTHON_ROUND:<current round>.",
            "state_headers": (
                "Every worker prompt includes one-line PREVIOUS_STATE_JSON and "
                "DELIVERED_INBOX_JSON values, then LOCAL_PROMPT on its own line, "
                "for host semantic verification."
            ),
            "action_fields": [
                "state",
                "should_send",
                "recipients",
                "message",
                "source_ids",
                "submit",
                "answer",
            ],
            "state": "Retain the previous state unless the new action updates fields.",
            "delivery": "Messages sent in round r enter inbox only in round r+1.",
            "snapshot": "All agents in a round read the same previous-round snapshot.",
            "submitted": "Never call or send from an agent after it submits.",
        },
        "stdout_fields": [
            "submissions",
            "rounds_executed",
            "messages",
            "usage",
            "errors",
        ],
        "security": [
            "Do not parse, split, slice, aggregate, or copy local_prompt values.",
            "local_prompt for agent i may enter only agent i's worker prompt.",
            "Only worker outputs may be sent as messages to peers.",
            "No files, environment reads, reflection, network libraries, dynamic code, recursion, while loops, exceptions, or debug output.",
            "Never compute the task result in Python; workers produce every answer.",
            "Do not change provider, model, endpoint, temperature, or budgets.",
        ],
        "output_rule": "Return raw Python source only, with no Markdown fences or commentary.",
    }
    if request.information_goal == "all_agents":
        goal = {
            "information_goal": "all_agents",
            "mission": (
                "Design explicit peer information sharing so every agent independently "
                "submits. A gather-only execution is invalid."
            ),
            "submission_rule": (
                "Return one submission slot per agent and keep exchanging new worker "
                "outputs until every active agent can submit or a budget stops execution."
            ),
            "grading_warning": (
                "Each agent is graded separately; no vote or leader result can replace "
                "a missing individual submission."
            ),
        }
    else:
        goal = {
            "information_goal": "sink",
            "selected_primary": 0,
            "mission": (
                "Route only necessary worker-produced information toward selected_primary, "
                "which forms the final task answer."
            ),
            "submission_rule": (
                "Return one slot per agent; non-primary slots may remain null and should "
                "not trigger unnecessary dissemination."
            ),
            "grading_warning": "Only selected_primary is the required answer holder.",
        }
    contract = json.dumps(
        {"common": common, "goal_specific_contract": goal},
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    scaffold = build_python_architect_scaffold()
    return _append_python_architect_context((
        "PYTHON SOURCE GENERATION CONTRACT\n"
        "Output one complete executable Python source file.\n"
        "Your first non-whitespace token must be a Python token such as import or from.\n"
        "Do not return JSON. Do not return an agents array. Do not put source in a "
        "main/source_code/code field. Do not use Markdown fences or commentary.\n"
        "The JSON below is INPUT SPECIFICATION ONLY; never copy its outer shape.\n\n"
        "BEGIN_INPUT_SPECIFICATION_JSON\n"
        f"{contract}\n"
        "END_INPUT_SPECIFICATION_JSON\n\n"
        f"BEGIN_KNOWN_VALID_SCAFFOLD_{PYTHON_SCAFFOLD_VERSION}\n"
        f"{scaffold}\n"
        f"END_KNOWN_VALID_SCAFFOLD_{PYTHON_SCAFFOLD_VERSION}\n\n"
        "Copy the complete scaffold as your output. You may edit only the three "
        "EVOLVE-BLOCK regions to specialize Worker instructions, routing, and "
        "submission. Preserve every import, stdin/client/complete call, state and "
        "delivery loop, usage ledger, stdout field, and main() call. If no safe "
        "specialization is needed, return the scaffold unchanged.\n"
        "FINAL OUTPUT REMINDER: raw complete Python source only."
    ), runtime)


def _append_python_architect_context(
    prompt: str,
    runtime: MASRuntimeConfig,
) -> str:
    """Append bounded positive/negative sections only for opt-in innovation."""
    if not getattr(runtime, "python_architect_context_enabled", False):
        return prompt
    context = {
        "positive_skill_context": dict(runtime.python_positive_context),
        "negative_failure_context": list(runtime.python_negative_context),
        "exposed_insight_ids": list(runtime.python_exposed_insight_ids),
    }
    encoded = json.dumps(context, ensure_ascii=True, indent=2, sort_keys=True)
    if len(encoded) > runtime.python_context_max_chars:
        encoded = json.dumps(
            {
                "positive_skill_context": {
                    "parent_skill_id": runtime.python_parent_skill_id,
                    "truncated": True,
                },
                "negative_failure_context": [],
                "exposed_insight_ids": list(runtime.python_exposed_insight_ids)[:8],
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    return (
        prompt
        + "\n\nBEGIN_SANITIZED_EVOLUTION_CONTEXT_JSON\n"
        + encoded
        + "\nEND_SANITIZED_EVOLUTION_CONTEXT_JSON\n"
        + "Use this context only as design guidance. Do not copy it into stdout."
    )


def _build_message_only_architect_prompt(
    *,
    request: PlannerRequest,
    task_brief: str | None,
    runtime: MASRuntimeConfig,
) -> str:
    """Architect contract where the Planner routes and Workers only write text."""
    common = {
        "role": "Write one complete executable Python program for a multi-agent task.",
        "planner_mode": "python_generate",
        "worker_contract": "message_only_v1",
        "task_description": task_brief,
        "n_agents": request.n_agents,
        "budgets": {
            "max_rounds": runtime.python_max_rounds,
            "max_model_calls": runtime.python_max_model_calls,
            "max_completion_tokens": runtime.python_max_completion_tokens,
            "max_messages": runtime.python_max_messages,
        },
        "source_contract": {
            "read": "Use json.load(sys.stdin) exactly once.",
            "client": (
                "Import create_llm_client only from exp_graph.llm.factory; use "
                "worker_llm payload values unchanged; call client.complete "
                "directly with json_mode=False."
            ),
            "write": "Use sys.stdout.write exactly once for one JSON object.",
            "imports": ["json", "sys", "exp_graph.llm.factory.create_llm_client"],
            "loops": "Only finite for/range loops bounded by payload values.",
            "control_model": (
                "plan_turn returns one control object per agent per round: "
                "{'mode': 'send'|'reflect'|'submit'|'idle', 'recipients': "
                "[...]}. recipients must be empty unless mode is send."
            ),
            "planner_owns": [
                "the per-round control mode of every agent",
                "recipients and whether anything is sent",
                "when each agent submits",
            ],
            "runtime_owns": [
                "per-agent previous_output memory",
                "inbox construction with the one-round delivery delay",
                "source_ids provenance merging",
                "token, call and message budgets",
            ],
            "worker_owns": [
                "the message body text",
                "the final answer text",
            ],
            "worker_output": (
                "Workers return plain text only. The text becomes the agent's "
                "new previous_output and, on send, the message body; on "
                "submit, the final answer. Workers never author state, "
                "recipients, source_ids, or submit flags."
            ),
            "worker_header": (
                "Every worker prompt starts with "
                "PYTHON_WORKER_CONTRACT:message_only_v1."
            ),
            "canonical_prompt": (
                "Keep the exact canonical header block and the worker "
                "instruction constants from the scaffold; the host verifies "
                "every worker prompt byte-for-byte and any deviation fails "
                "the run."
            ),
            "dynamic_conditions": (
                "plan_turn may read only round_idx, agent_id, n_agents, "
                "max_rounds, information_goal, selected_primary, "
                "known_source_count and inbox_count; never message bodies or "
                "local prompts."
            ),
            "delivery": "Messages sent in round r enter inbox only in round r+1.",
            "snapshot": "All agents in a round read the same previous-round snapshot.",
            "submitted": "Never call or send from an agent after it submits.",
            "fail_closed": (
                "Invalid recipients (out of range, self, duplicate, or on a "
                "non-send mode) must raise an error; never substitute another "
                "route silently."
            ),
        },
        "stdout_fields": [
            "submissions",
            "rounds_executed",
            "messages",
            "usage",
            "errors",
        ],
        "security": [
            "Do not parse, split, slice, aggregate, or copy local_prompt values.",
            "local_prompt for agent i may enter only agent i's worker prompt.",
            "Only worker outputs may be sent as messages to peers.",
            "No files, environment reads, reflection, network libraries, dynamic code, recursion, while loops, exceptions, or debug output.",
            "Never compute the task result in Python; workers produce every answer.",
            "Do not change provider, model, endpoint, temperature, or budgets.",
        ],
        "output_rule": "Return raw Python source only, with no Markdown fences or commentary.",
    }
    if request.information_goal == "all_agents":
        goal = {
            "information_goal": "all_agents",
            "mission": (
                "Design explicit peer information sharing so every agent independently "
                "submits. A gather-only execution is invalid."
            ),
            "submission_rule": (
                "Return one submission slot per agent and keep exchanging new worker "
                "outputs until every active agent can submit or a budget stops execution."
            ),
            "grading_warning": (
                "Each agent is graded separately; no vote or leader result can replace "
                "a missing individual submission."
            ),
        }
    else:
        goal = {
            "information_goal": "sink",
            "selected_primary": 0,
            "mission": (
                "Route only necessary worker-produced information toward selected_primary, "
                "which forms the final task answer."
            ),
            "submission_rule": (
                "Return one slot per agent; non-primary slots may remain null and should "
                "not trigger unnecessary dissemination."
            ),
            "grading_warning": "Only selected_primary is the required answer holder.",
        }
    contract = json.dumps(
        {"common": common, "goal_specific_contract": goal},
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    scaffold = build_python_architect_scaffold("message_only_v1")
    return (
        "PYTHON SOURCE GENERATION CONTRACT\n"
        "Output one complete executable Python source file.\n"
        "Your first non-whitespace token must be a Python token such as import or from.\n"
        "Do not return JSON. Do not return an agents array. Do not put source in a "
        "main/source_code/code field. Do not use Markdown fences or commentary.\n"
        "The JSON below is INPUT SPECIFICATION ONLY; never copy its outer shape.\n\n"
        "BEGIN_INPUT_SPECIFICATION_JSON\n"
        f"{contract}\n"
        "END_INPUT_SPECIFICATION_JSON\n\n"
        f"BEGIN_KNOWN_VALID_SCAFFOLD_{PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION}\n"
        f"{scaffold}\n"
        f"END_KNOWN_VALID_SCAFFOLD_{PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION}\n\n"
        "Copy the complete scaffold as your output. You may edit only the two "
        "EVOLVE-BLOCK regions inside plan_turn (submission_policy and "
        "routing_policy). Keep the worker instruction constants, the canonical "
        "prompt header block, every import, stdin/client/complete call, the "
        "runtime state and delivery loops, the usage ledger, the stdout "
        "fields, and the main() call unchanged. If no safe specialization is "
        "needed, return the scaffold unchanged.\n"
        "FINAL OUTPUT REMINDER: raw complete Python source only."
    )


def _build_message_only_v2_architect_prompt(
    *,
    request: PlannerRequest,
    task_brief: str | None,
    runtime: MASRuntimeConfig,
) -> str:
    """Architect contract for communication-only planning plus a host barrier."""
    if request.information_goal == "all_agents":
        goal = {
            "information_goal": "all_agents",
            "mission": (
                "Design communication so useful information circulates among all "
                "agents before the final synchronized submit barrier."
            ),
            "required_submitters": "every agent, at the same final logical round",
            "grading": "Each parsed native JSON answer is scored per agent.",
        }
    else:
        goal = {
            "information_goal": "sink",
            "selected_primary": 0,
            "mission": (
                "Design communication that gathers useful information at the "
                "selected primary before the final submit barrier."
            ),
            "required_submitters": "selected_primary only, at the final logical round",
            "grading": "Only the selected primary's parsed native JSON answer is scored.",
        }
    common = {
        "role": "Write one complete executable Python communication program.",
        "planner_mode": "python_generate",
        "worker_contract": "message_only_v2",
        "task_description": task_brief,
        "n_agents": request.n_agents,
        "budgets": {
            "max_rounds": runtime.python_max_rounds,
            "max_model_calls": runtime.python_max_model_calls,
            "max_completion_tokens": runtime.python_max_completion_tokens,
            "max_messages": runtime.python_max_messages,
        },
        "round_semantics": (
            "max_rounds includes the final submit barrier. Communication may run "
            "only in rounds 0 through max_rounds-2. Messages sent in round r are "
            "delivered in r+1, including messages delivered at the barrier."
        ),
        "execution_parallelism": (
            "The immutable scaffold batches independent Worker calls from one "
            "logical round through client.complete_batch. The trusted runtime "
            "caps concurrency at max_parallel_agents, commits results in Agent "
            "order, and completes the whole batch before the next round."
        ),
        "planner_owns": [
            "one global submit_round selected within the max_rounds budget",
            "communication mode send, reflect, or idle",
            "send recipients",
            "the communication topology before the barrier",
        ],
        "runtime_owns": [
            "previous_output memory",
            "one-round-delayed inbox delivery",
            "source_ids provenance merging",
            "validation and enforcement of the Planner's global submit_round",
            "the immutable submitter set at that barrier",
            "a frozen final snapshot shared by every required submitter",
            "strict whole-response json.loads parsing",
            "budgets and the audit ledger",
            "bounded same-round Worker-call parallelism",
        ],
        "worker_owns": [
            "plain-text communication message bodies",
            "exactly one JSON value during its final submit call",
        ],
        "answer_contract": {
            "json_mode": False,
            "accepted": ["42", "[1,2]", "true", "null", "\"accepted\""],
            "forbidden": [
                "prose around the answer",
                "Markdown or code fences",
                "routing metadata",
                "a belief-state/status/proposal object",
                "an answer wrapper object",
                "NaN or Infinity",
            ],
            "parsing": (
                "The host parses the entire stripped response once with json.loads. "
                "There is no regex, answer extraction, judge model, or ground-truth "
                "repair."
            ),
        },
        "control_model": (
            "plan_submit_round returns one integer satisfying 0 <= submit_round "
            "< max_rounds. plan_communication_turn returns exactly {'mode': "
            "'send'|'reflect'|'idle', 'recipients': [...]}. It must never return "
            "submit. Recipients are legal only for send."
        ),
        "canonical_prompt": (
            "Preserve the exact worker instructions, all PYTHON_* headers, and "
            "the distinct COMMUNICATION_PROMPT/SUBMIT_PROMPT boundaries. The "
            "immutable instruction must remain last. The host reconstructs and "
            "verifies every prompt byte-for-byte."
        ),
        "security": [
            "Never inspect or transform communication_prompt or submit_prompt in Python.",
            "Only agent i's communication_prompt may enter its communication calls.",
            "Only agent i's submit_prompt may enter its final submit call.",
            "Never combine the two prompt types or prompts from different agents.",
            "Only Worker output may become a peer message or final answer.",
            "No files, environment access, reflection, network libraries, dynamic "
            "code, recursion, while loops, exception handlers, or debug output.",
            "Do not alter providers, models, endpoints, temperatures, or budgets.",
        ],
    }
    contract = json.dumps(
        {"common": common, "goal_specific_contract": goal},
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    scaffold = build_python_architect_scaffold("message_only_v2")
    return (
        "PYTHON SOURCE GENERATION CONTRACT\n"
        "Output one complete executable Python source file.\n"
        "Return raw Python only, with no JSON wrapper, Markdown, or commentary.\n"
        "The JSON below is input specification only.\n\n"
        "BEGIN_INPUT_SPECIFICATION_JSON\n"
        f"{contract}\n"
        "END_INPUT_SPECIFICATION_JSON\n\n"
        f"BEGIN_KNOWN_VALID_SCAFFOLD_{PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION}\n"
        f"{scaffold}\n"
        f"END_KNOWN_VALID_SCAFFOLD_{PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION}\n\n"
        "Copy the complete scaffold. You may edit only the schedule_policy and "
        "routing_policy EVOLVE-BLOCKs. Preserve the submit barrier, "
        "submitter selection, final frozen snapshots, strict JSON parser, canonical "
        "Worker prompts, same-round complete_batch calls, imports, I/O, budgets, "
        "ledger-compatible stdout fields, and main() call exactly. If no "
        "specialization is needed, return the "
        "scaffold unchanged.\n"
        "FINAL OUTPUT REMINDER: raw complete Python source only."
    )


def build_python_repair_prompt(
    *,
    source: str,
    failure: dict[str, Any],
    attempt: int,
    information_goal: str,
    worker_contract: str = "action_json_v1",
) -> str:
    observation_fields: dict[str, Any] = {
        "attempt": attempt,
        "information_goal": information_goal,
        "error_type": failure.get("error_type"),
        "message": failure.get("message"),
        "line": failure.get("line"),
        "column": failure.get("column"),
    }
    if worker_contract != "action_json_v1":
        # Keep the historical action_json_v1 repair prompt byte-identical;
        # only the new contract announces itself in the observation.
        observation_fields["worker_contract"] = worker_contract
    observation = json.dumps(
        observation_fields,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    scaffold_version = python_scaffold_version(worker_contract)
    scaffold = build_python_architect_scaffold(worker_contract)
    return (
        "PYTHON SOURCE REPAIR CONTRACT\n"
        "Replace the rejected program with one complete executable Python source file.\n"
        "Return raw Python only: no JSON wrapper, agents array, main/source_code/code "
        "field, Markdown fence, commentary, patch, or explanation.\n"
        "Do not change budgets, security rules, scorer, or planner mode.\n"
        "Do not include task answers, scores, benchmark results, or private data.\n"
        "Use only json, sys, create_llm_client, finite loops, and one stdout JSON.\n\n"
        "BEGIN_REJECTION_OBSERVATION_JSON\n"
        f"{observation}\n"
        "END_REJECTION_OBSERVATION_JSON\n\n"
        "BEGIN_REJECTED_PYTHON_SOURCE\n"
        f"{source}\n"
        "END_REJECTED_PYTHON_SOURCE\n\n"
        f"BEGIN_KNOWN_VALID_SCAFFOLD_{scaffold_version}\n"
        f"{scaffold}\n"
        f"END_KNOWN_VALID_SCAFFOLD_{scaffold_version}\n\n"
        "Use the complete known-valid scaffold as the replacement. Edit only its "
        "EVOLVE-BLOCK regions. If the rejected response was JSON rather than code, "
        "return the scaffold unchanged instead of emitting an output object.\n"
        "FINAL OUTPUT REMINDER: raw complete replacement Python source only."
    )


def extract_python_source(response_text: str) -> tuple[str, str]:
    """Normalize common LLM wrappers without weakening source validation.

    The returned source still passes through the existing AST, policy, data-flow,
    dry-run, and subprocess checks. Unsupported JSON shapes are returned intact
    so they fail honestly and can enter the repair loop.
    """
    raw = str(response_text or "").strip()
    if not raw:
        return raw, "empty"

    fenced = _single_python_fence(raw)
    if fenced is not None:
        return fenced, "markdown_fence"

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw, "raw_python"

    if isinstance(payload, str):
        candidate = _normalize_embedded_source(payload)
        if _looks_like_python_source(candidate):
            return candidate, "json_string"
        return raw, "unrecognized_json"
    if not isinstance(payload, dict):
        return raw, "unrecognized_json"
    for key in _PYTHON_SOURCE_KEYS:
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        candidate = _normalize_embedded_source(value)
        if _looks_like_python_source(candidate):
            return candidate, f"json:{key}"
    return raw, "unrecognized_json"


def _single_python_fence(text: str) -> str | None:
    matches = list(_PYTHON_FENCE_RE.finditer(text))
    if len(matches) != 1:
        return None
    source = matches[0].group("source").strip()
    return source if _looks_like_python_source(source) else None


def _normalize_embedded_source(value: str) -> str:
    candidate = value.strip()
    fenced = _single_python_fence(candidate)
    if fenced is not None:
        candidate = fenced
    # Do not decode a second layer of backslash escapes: layout ``\\n`` and a
    # legitimate Python string literal are indistinguishable at that point.
    # The unchanged candidate will fail AST validation and enter repair safely.
    return candidate.strip()


def _looks_like_python_source(value: str) -> bool:
    stripped = value.lstrip()
    return bool(stripped) and (
        stripped.startswith(("import ", "from ", "def ", "class ", "@", "#!"))
        or "\ndef " in stripped
        or "\nimport " in stripped
        or "\nfrom " in stripped
    )


def _eligible_python_parent_source(
    skill: SkillCard | None,
    runtime: MASRuntimeConfig,
) -> str | None:
    if skill is None or planner_mode_from_skill(skill) != "python_generate":
        return None
    payload = skill.mode_payload
    execution_contract = (
        payload.execution_contract_version
        if getattr(payload, "format", None) == "python_skill_v1"
        else skill.organization_policy.get("execution_contract_version")
    )
    ast_policy = (
        payload.ast_policy_version
        if getattr(payload, "format", None) == "python_skill_v1"
        else skill.organization_policy.get("ast_policy_version")
    )
    if execution_contract != runtime.python_execution_contract_version:
        return None
    if ast_policy != runtime.python_ast_policy_version:
        return None
    if python_worker_contract_from_skill(skill) != runtime.python_worker_contract:
        return None
    source = python_source_from_skill(skill)
    if not isinstance(source, str):
        return None
    if not validate_python_source(
        source,
        worker_contract=runtime.python_worker_contract,
    ).valid:
        return None
    return source


def _innovation_parent(
    skill_bank: SkillBank,
    runtime: MASRuntimeConfig,
) -> SkillCard | None:
    parent_id = getattr(runtime, "python_parent_skill_id", None)
    return skill_bank.get(parent_id) if parent_id else None


def _prepare_python_innovation_context(
    runtime: MASRuntimeConfig,
    parent: SkillCard | None,
) -> MASRuntimeConfig:
    if not runtime.python_architect_context_enabled or parent is None:
        return runtime
    sanitized = sanitize_python_skill_context(
        parent,
        max_chars=runtime.python_context_max_chars,
    )
    positive, negative = split_python_skill_context(sanitized)
    exposed = list(runtime.python_exposed_insight_ids)
    if not exposed:
        exposed = insight_ids_from_context(sanitized)
    return runtime.model_copy(
        update={
            "python_positive_context": positive,
            "python_negative_context": negative,
            "python_exposed_insight_ids": exposed,
        }
    )


def _record_applied_mutation(
    *,
    output_dir: Path,
    index: int,
    patch: PythonMutationPatch,
    applied: Any,
) -> dict[str, Any]:
    patch_path = output_dir / f"mutation_patch_{index:02d}.json"
    diff_path = output_dir / f"mutation_diff_{index:02d}.patch"
    patch_path.write_text(
        json.dumps(patch.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    diff_path.write_text(applied.diff, encoding="utf-8")
    return {
        "patch_index": index,
        "patch_file": patch_path.name,
        "diff_file": diff_path.name,
        "block_id": applied.block_id,
        "parent_program_sha256": applied.parent_program_sha256,
        "mutated_program_sha256": applied.mutated_program_sha256,
        "diff_sha256": applied.diff_sha256,
        "used_insight_ids": list(applied.used_insight_ids),
    }


def plan_and_execute_python(
    *,
    request: PlannerRequest,
    runtime: MASRuntimeConfig,
    skill_bank: SkillBank,
    task_adapter: Any,
    execution_payload: dict[str, Any],
    output_dir: Path,
    llm_client: LLMClient | None = None,
) -> PythonCodePlanningResult:
    """Generate/replay, validate, dry-run, execute, repair, and persist."""
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_contract = str(
        getattr(runtime, "python_worker_contract", "action_json_v1")
    )
    if worker_contract not in PYTHON_WORKER_CONTRACTS:
        raise ValueError(f"unknown python worker contract {worker_contract!r}")
    payload_contract = str(
        execution_payload.get("worker_contract") or "action_json_v1"
    )
    if payload_contract != worker_contract:
        # A runtime/payload disagreement is a host plumbing bug, not an honest
        # planner failure; refuse loudly instead of scoring validity=0.
        raise ValueError(
            "execution payload worker_contract "
            f"{payload_contract!r} does not match runtime configuration "
            f"{worker_contract!r}"
        )
    describe = getattr(task_adapter, "describe_task", None)
    task_brief = describe() if callable(describe) else None
    emperor = resolve_role_llm_config(runtime, "emperor")
    innovation_branch = getattr(runtime, "python_innovation_branch", None)
    parent_skill = _innovation_parent(skill_bank, runtime)
    runtime = _prepare_python_innovation_context(runtime, parent_skill)
    replay = (
        None
        if innovation_branch is not None
        else _replay_source(skill_bank.retrieve(request), runtime)
    )
    selected_skill_id = replay[0] if replay is not None else None
    architect_prompt: str | None = None
    planner_calls = 0
    repair_calls = 0
    response_trace: list[dict[str, Any]] = []
    provenance = "skill_replay" if replay is not None else "llm_generated_python"
    innovation_metadata: dict[str, Any] = {
        # Only the explicit hot-start branch is labelled ``fresh``/``mutate``.
        # A normal cold generation is neither branch; calling it ``fresh``
        # made evidence selection unable to distinguish the marked innovation
        # scaffold from the historical unmarked default program.
        "strategy": innovation_branch or ("reuse" if replay is not None else None),
        "parent_skill_id": (
            parent_skill.skill_id if parent_skill is not None else None
        ),
        "context_exposed": bool(
            runtime.python_architect_context_enabled and parent_skill is not None
        ),
        "exposed_insight_ids": list(runtime.python_exposed_insight_ids),
        "used_insight_ids": [],
        "patches": [],
    }
    client = llm_client
    if replay is not None:
        source = replay[1]
        source_format = "skill_replay"
    elif innovation_branch == "mutate":
        parent_source = _eligible_python_parent_source(parent_skill, runtime)
        if parent_source is None or parent_skill is None:
            raise PythonMutationSkipped(
                "no same-contract validated Python parent source is available"
            )
        selected_skill_id = parent_skill.skill_id
        positive = dict(runtime.python_positive_context)
        negative = list(runtime.python_negative_context)
        architect_prompt = build_python_mutation_prompt(
            parent_source=parent_source,
            parent_skill_id=parent_skill.skill_id,
            positive_context=positive,
            negative_context=negative,
        )
        if runtime.leakage_audit:
            assert_prompt_clean(
                architect_prompt,
                context="python mutation prompt",
                allowed_tokens=runtime.leakage_allowed_tokens,
            )
        if emperor.platform == "fake":
            first = next(iter(extract_evolve_blocks(parent_source).values()))
            patch = PythonMutationPatch(
                parent_program_sha256=python_source_sha256(parent_source),
                block_id=first.block_id,
                replacement=first.content.rstrip("\n"),
                used_insight_ids=[],
            )
        else:
            client = client or create_role_llm_client(runtime, "emperor")
            response = client.complete(
                architect_prompt,
                model_name=emperor.model_name,
                temperature=emperor.temperature,
                json_mode=True,
            )
            planner_calls += int(response.usage.model_calls)
            _write_raw_model_response(
                output_dir / "architect_response.raw.txt",
                response.text,
            )
            patch = parse_python_mutation_patch(response.text)
            response_trace.append(
                {
                    "role": "mutation_architect",
                    "response_format": PYTHON_MUTATION_PATCH_FORMAT,
                    "raw_response_sha256": hashlib.sha256(
                        response.text.encode("utf-8")
                    ).hexdigest(),
                    "raw_response_chars": len(response.text),
                }
            )
        applied = apply_python_mutation_patch(
            parent_source,
            patch,
            allowed_insight_ids=runtime.python_exposed_insight_ids,
        )
        source = applied.source
        source_format = PYTHON_MUTATION_PATCH_FORMAT
        mutation_record = _record_applied_mutation(
            output_dir=output_dir,
            index=0,
            patch=patch,
            applied=applied,
        )
        innovation_metadata["patches"].append(mutation_record)
        innovation_metadata["parent_program_sha256"] = python_source_sha256(
            parent_source
        )
        innovation_metadata["mutated_program_sha256"] = python_source_sha256(source)
        innovation_metadata["used_insight_ids"] = list(applied.used_insight_ids)
    elif emperor.platform == "fake":
        source = (
            build_python_architect_scaffold(worker_contract)
            if innovation_branch == "fresh"
            else default_python_program(worker_contract)
        )
        source_format = (
            "fake_scaffold_innovation"
            if innovation_branch == "fresh"
            else "fake_default"
        )
        provenance = "fake"
    else:
        architect_prompt = build_python_architect_prompt(
            request=request,
            task_brief=task_brief,
            runtime=runtime,
        )
        if runtime.leakage_audit:
            assert_prompt_clean(
                architect_prompt,
                context="python architect prompt",
                allowed_tokens=runtime.leakage_allowed_tokens,
            )
        client = client or create_role_llm_client(runtime, "emperor")
        response = client.complete(
            architect_prompt,
            model_name=emperor.model_name,
            temperature=emperor.temperature,
            json_mode=False,
        )
        planner_calls += int(response.usage.model_calls)
        raw_response = response.text
        source, source_format = extract_python_source(raw_response)
        _write_raw_model_response(
            output_dir / "architect_response.raw.txt",
            raw_response,
        )
        response_trace.append(
            _response_normalization_record(
                role="architect",
                response_format=source_format,
                raw_response=raw_response,
                source=source,
            )
        )

    runner = CodeProcessRunner(
        PythonExecutionLimits(
            timeout_seconds=runtime.python_execution_timeout,
            cpu_seconds=runtime.python_cpu_seconds,
            memory_mb=runtime.python_memory_mb,
            max_output_bytes=runtime.python_max_output_bytes,
        )
    )
    attempts: list[dict[str, Any]] = []
    repair_trace: list[dict[str, Any]] = []
    final_execution: PythonExecutionResult | None = None
    max_repairs = max(0, runtime.python_repair_attempts)
    for attempt_idx in range(max_repairs + 1):
        validation = validate_python_source(
            source,
            worker_contract=worker_contract,
        )
        attempt_record: dict[str, Any] = {
            "attempt": attempt_idx,
            "source_format": source_format,
            "source_sha256": python_source_sha256(source),
            "validation": validation.model_dump(mode="json"),
            "dry_run": None,
            "execution": None,
        }
        (output_dir / f"attempt_{attempt_idx:02d}.py").write_text(
            source,
            encoding="utf-8",
        )
        failure = _first_validation_failure(validation)
        if validation.valid:
            if runtime.python_dry_run:
                dry_result = runner.run(
                    source,
                    _dry_run_payload(request, runtime),
                    agent_canaries=_dry_run_canaries(request.n_agents),
                )
                attempt_record["dry_run"] = _execution_summary(dry_result)
            else:
                dry_result = PythonExecutionResult(runtime_success=True)
                attempt_record["dry_run"] = {
                    "runtime_success": None,
                    "skipped": True,
                }
            if not dry_result.runtime_success:
                failure = dry_result.failure or {
                    "error_type": "RuntimeError",
                    "message": "fake dry-run failed",
                }
            else:
                actual = runner.run(source, execution_payload)
                final_execution = actual
                attempt_record["execution"] = _execution_summary(actual)
                if actual.runtime_success:
                    attempts.append(attempt_record)
                    (
                        output_dir
                        / f"attempt_{attempt_idx:02d}_validation.json"
                    ).write_text(
                        json.dumps(attempt_record, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                    _write_python_artifacts(
                        output_dir,
                        request=request,
                        runtime=runtime,
                        source=source,
                        architect_prompt=architect_prompt,
                        attempts=attempts,
                        repair_trace=repair_trace,
                        response_trace=response_trace,
                        execution=actual,
                        payload=execution_payload,
                        provenance=provenance,
                        planner_calls=planner_calls,
                        repair_calls=repair_calls,
                        failure_category=None,
                        failure_reason=None,
                        innovation_metadata=innovation_metadata,
                    )
                    return PythonCodePlanningResult(
                        source=source,
                        execution=actual,
                        artifacts_dir=output_dir,
                        provenance=provenance,
                        architect_prompt=architect_prompt,
                        attempts=attempts,
                        planner_model_calls=planner_calls,
                        repair_model_calls=repair_calls,
                        selected_skill_id=selected_skill_id,
                        innovation_metadata=innovation_metadata,
                    )
                failure = actual.failure or {
                    "error_type": "RuntimeError",
                    "message": "generated program execution failed",
                }
        attempts.append(attempt_record)
        (output_dir / f"attempt_{attempt_idx:02d}_validation.json").write_text(
            json.dumps(attempt_record, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if attempt_idx >= max_repairs or emperor.platform == "fake" or client is None:
            reason = str((failure or {}).get("message") or "python generation failed")
            failure_category = str(
                (failure or {}).get("error_type") or "RuntimeError"
            )
            _write_python_artifacts(
                output_dir,
                request=request,
                runtime=runtime,
                source=source,
                architect_prompt=architect_prompt,
                attempts=attempts,
                repair_trace=repair_trace,
                response_trace=response_trace,
                execution=final_execution,
                payload=execution_payload,
                provenance=provenance,
                planner_calls=planner_calls,
                repair_calls=repair_calls,
                failure_category=failure_category,
                failure_reason=reason,
                innovation_metadata=innovation_metadata,
            )
            raise PythonGenerationError(
                reason,
                error_type=failure_category,
                artifacts_dir=output_dir,
                metrics=_failed_execution_metrics(
                    final_execution,
                    n_agents=request.n_agents,
                ),
                program_sha256=python_source_sha256(source),
            )
        if innovation_branch == "mutate" and parent_skill is not None:
            repair_prompt = build_python_mutation_prompt(
                parent_source=source,
                parent_skill_id=parent_skill.skill_id,
                positive_context=dict(runtime.python_positive_context),
                negative_context=list(runtime.python_negative_context),
                failure=failure or {},
            )
            repair_action = "mutation_patch"
            repair_json_mode = True
        else:
            repair_prompt = build_python_repair_prompt(
                source=source,
                failure=failure or {},
                attempt=attempt_idx + 1,
                information_goal=request.information_goal,
                worker_contract=worker_contract,
            )
            repair_action = "replace_code"
            repair_json_mode = False
        if runtime.leakage_audit:
            assert_prompt_clean(
                repair_prompt,
                context="python repair prompt",
                allowed_tokens=runtime.leakage_allowed_tokens,
            )
        response = client.complete(
            repair_prompt,
            model_name=emperor.model_name,
            temperature=emperor.temperature,
            json_mode=repair_json_mode,
        )
        repair_calls += int(response.usage.model_calls)
        repair_trace.append(
            {
                "attempt": attempt_idx + 1,
                "action": repair_action,
                "prompt_sha256": hashlib.sha256(
                    repair_prompt.encode("utf-8")
                ).hexdigest(),
                "observation": failure,
            }
        )
        raw_response = response.text
        _write_raw_model_response(
            output_dir / f"repair_response_{attempt_idx + 1:02d}.raw.txt",
            raw_response,
        )
        if innovation_branch == "mutate":
            patch = parse_python_mutation_patch(raw_response)
            applied = apply_python_mutation_patch(
                source,
                patch,
                allowed_insight_ids=runtime.python_exposed_insight_ids,
            )
            source = applied.source
            source_format = PYTHON_MUTATION_PATCH_FORMAT
            mutation_record = _record_applied_mutation(
                output_dir=output_dir,
                index=len(innovation_metadata["patches"]),
                patch=patch,
                applied=applied,
            )
            innovation_metadata["patches"].append(mutation_record)
            used_ids = [
                *innovation_metadata.get("used_insight_ids", []),
                *applied.used_insight_ids,
            ]
            innovation_metadata["used_insight_ids"] = list(dict.fromkeys(used_ids))
            innovation_metadata["mutated_program_sha256"] = python_source_sha256(source)
            response_trace.append(
                {
                    "role": f"mutation_repair_{attempt_idx + 1}",
                    "response_format": PYTHON_MUTATION_PATCH_FORMAT,
                    "raw_response_sha256": hashlib.sha256(
                        raw_response.encode("utf-8")
                    ).hexdigest(),
                    "raw_response_chars": len(raw_response),
                }
            )
        else:
            source, source_format = extract_python_source(raw_response)
            response_trace.append(
                _response_normalization_record(
                    role=f"repair_{attempt_idx + 1}",
                    response_format=source_format,
                    raw_response=raw_response,
                    source=source,
                )
            )
        repair_trace[-1]["response_format"] = source_format
        provenance = "llm_generated_python"
    raise AssertionError("unreachable python repair loop")


def _replay_source(
    skills: list[SkillCard],
    runtime: MASRuntimeConfig,
) -> tuple[str, str] | None:
    if not runtime.replay_first:
        return None
    worker_contract = str(
        getattr(runtime, "python_worker_contract", "action_json_v1")
    )
    for skill in skills:
        if planner_mode_from_skill(skill) != "python_generate":
            continue
        payload = skill.mode_payload
        execution_contract = (
            payload.execution_contract_version
            if getattr(payload, "format", None) == "python_skill_v1"
            else skill.organization_policy.get("execution_contract_version")
        )
        ast_policy = (
            payload.ast_policy_version
            if getattr(payload, "format", None) == "python_skill_v1"
            else skill.organization_policy.get("ast_policy_version")
        )
        if execution_contract != runtime.python_execution_contract_version:
            continue
        if ast_policy != runtime.python_ast_policy_version:
            continue
        # Worker contracts are separate archives: a card recorded under one
        # contract must never replay into a run configured for the other.
        if python_worker_contract_from_skill(skill) != worker_contract:
            continue
        source = python_source_from_skill(skill)
        if isinstance(source, str) and validate_python_source(
            source,
            worker_contract=worker_contract,
        ).valid:
            return skill.skill_id, source
    return None


def _dry_run_payload(
    request: PlannerRequest,
    runtime: MASRuntimeConfig,
) -> dict[str, Any]:
    canaries = _dry_run_canaries(request.n_agents)
    worker_contract = str(
        getattr(runtime, "python_worker_contract", "action_json_v1")
    )
    agents: list[dict[str, Any]] = []
    for agent_id in range(request.n_agents):
        private_text = (
            f"{canaries[str(agent_id)]}\n"
            f"Synthetic private prompt for agent {agent_id}."
        )
        if worker_contract == "message_only_v2":
            agents.append(
                {
                    "agent_id": agent_id,
                    "communication_prompt": private_text,
                    "submit_prompt": (
                        private_text
                        + "\nPUBLIC_ANSWER_REQUIREMENT:\n"
                        "Return one JSON string for this synthetic wiring check."
                    ),
                }
            )
        else:
            agents.append({"agent_id": agent_id, "local_prompt": private_text})
    return {
        "execution_contract_version": runtime.python_execution_contract_version,
        "worker_contract": worker_contract,
        "task_description": "Synthetic offline wiring check.",
        "information_goal": request.information_goal,
        "selected_primary": 0,
        "n_agents": request.n_agents,
        "max_rounds": min(2, runtime.python_max_rounds),
        "budgets": {
            "max_model_calls": max(1, request.n_agents * 2),
            "max_completion_tokens": max(1000, request.n_agents * 500),
            "max_messages": max(1, runtime.python_max_messages),
        },
        "worker_llm": {
            "provider": "fake",
            "model_name": "fake",
            "base_url": None,
            "api_key_env": None,
            "temperature": 0.0,
        },
        "agents": agents,
    }


def _dry_run_canaries(n_agents: int) -> dict[str, str]:
    return {
        str(agent_id): f"PYTHON_LOCAL_CANARY_{agent_id}_A91F"
        for agent_id in range(n_agents)
    }


def _first_validation_failure(report: PythonValidationReport) -> dict[str, Any] | None:
    return report.errors[0] if report.errors else None


def _execution_summary(result: PythonExecutionResult) -> dict[str, Any]:
    return {
        "runtime_success": result.runtime_success,
        "failure": result.failure,
        "return_code": result.return_code,
        "authoritative_usage": result.authoritative_usage.model_dump(mode="json"),
        "rounds": (
            result.output.rounds_executed if result.output is not None else 0
        ),
        "messages": len(result.output.messages) if result.output is not None else 0,
        "submit_barrier": result.ledger.get("submit_barrier"),
        "resource_limits": result.resource_limits,
    }


def _failed_execution_metrics(
    result: PythonExecutionResult | None,
    *,
    n_agents: int,
) -> dict[str, Any]:
    if result is None:
        return {}
    usage = result.authoritative_usage
    output = result.output
    rounds = int(output.rounds_executed) if output is not None else 0
    messages = len(output.messages) if output is not None else 0
    denominator = n_agents * (n_agents - 1)
    return {
        "messages": messages,
        "model_calls": int(usage.model_calls),
        "tokens": int(usage.prompt_tokens + usage.completion_tokens),
        "C": float(usage.completion_tokens) / max(1, rounds),
        "D": float(messages) / denominator if denominator > 0 else 0.0,
    }


def _response_normalization_record(
    *,
    role: str,
    response_format: str,
    raw_response: str,
    source: str,
) -> dict[str, Any]:
    return {
        "role": role,
        "response_format": response_format,
        "raw_response_sha256": hashlib.sha256(
            raw_response.encode("utf-8")
        ).hexdigest(),
        "source_sha256": python_source_sha256(source),
        "raw_response_chars": len(raw_response),
        "source_chars": len(source),
    }


def _write_raw_model_response(path: Path, response_text: str) -> None:
    path.write_text(_scrub(response_text), encoding="utf-8")


def _write_python_artifacts(
    output_dir: Path,
    *,
    request: PlannerRequest,
    runtime: MASRuntimeConfig,
    source: str,
    architect_prompt: str | None,
    attempts: list[dict[str, Any]],
    repair_trace: list[dict[str, Any]],
    response_trace: list[dict[str, Any]],
    execution: PythonExecutionResult | None,
    payload: dict[str, Any],
    provenance: str,
    planner_calls: int,
    repair_calls: int,
    failure_category: str | None,
    failure_reason: str | None,
    innovation_metadata: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "architect_prompt.txt").write_text(
        _scrub(architect_prompt or "[fake-or-replay: no architect prompt]"),
        encoding="utf-8",
    )
    (output_dir / "final_program.py").write_text(source, encoding="utf-8")
    (output_dir / "program_hash.txt").write_text(
        python_source_sha256(source) + "\n",
        encoding="utf-8",
    )
    (output_dir / "stdin_payload.redacted.json").write_text(
        json.dumps(_redacted_payload(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    redacted_stdout = _redacted_stdout(execution)
    (output_dir / "stdout.json").write_text(
        json.dumps(redacted_stdout, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "stderr.redacted.txt").write_text(
        _scrub(execution.stderr if execution is not None else ""),
        encoding="utf-8",
    )
    (output_dir / "repair_trace.json").write_text(
        json.dumps(repair_trace, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "response_normalization_trace.json").write_text(
        json.dumps(response_trace, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "innovation_provenance.json").write_text(
        json.dumps(innovation_metadata or {}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    usage = (
        execution.authoritative_usage
        if execution is not None
        else None
    )
    report = {
        "syntax_valid_at_1": bool(
            attempts and attempts[0]["validation"].get("syntax_valid")
        ),
        "repair_attempts": len(repair_trace),
        "policy_valid": bool(
            attempts and attempts[-1]["validation"].get("policy_valid")
        ),
        "data_flow_valid": bool(
            attempts and attempts[-1]["validation"].get("data_flow_valid")
        ),
        "compile_valid": bool(
            attempts and attempts[-1]["validation"].get("compile_valid")
        ),
        "dry_run_valid": bool(
            attempts
            and (attempts[-1].get("dry_run") or {}).get("runtime_success")
        ),
        "dry_run_enabled": bool(runtime.python_dry_run),
        "runtime_success": bool(execution and execution.runtime_success),
        "planner_model_calls": planner_calls,
        "repair_model_calls": repair_calls,
        "response_formats": [
            str(item.get("response_format")) for item in response_trace
        ],
        "worker_model_calls": int(usage.model_calls) if usage else 0,
        "prompt_tokens": int(usage.prompt_tokens) if usage else 0,
        "completion_tokens": int(usage.completion_tokens) if usage else 0,
        "messages": (
            len(execution.output.messages)
            if execution and execution.output is not None
            else 0
        ),
        "rounds": (
            execution.output.rounds_executed
            if execution and execution.output is not None
            else 0
        ),
        "information_goal": request.information_goal,
        "program_sha256": python_source_sha256(source),
        "ast_policy_version": runtime.python_ast_policy_version,
        "execution_contract_version": runtime.python_execution_contract_version,
        "worker_contract": str(
            getattr(runtime, "python_worker_contract", "action_json_v1")
        ),
        "execution_timeout_seconds": float(runtime.python_execution_timeout),
        "max_parallel_agents": int(runtime.max_parallel_agents),
        "parallelism": (
            execution.ledger.get("parallelism") if execution else None
        ),
        "submit_barrier": (
            execution.ledger.get("submit_barrier") if execution else None
        ),
        "provenance": provenance,
        "innovation": innovation_metadata or {},
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    (output_dir / "execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _redacted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = {key: item for key, item in payload.items() if key != "agents"}
    value["agents"] = [_redacted_agent_prompts(agent) for agent in payload.get("agents", [])]
    return value


def _redacted_agent_prompts(agent: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {"agent_id": agent.get("agent_id")}
    for field in ("local_prompt", "communication_prompt", "submit_prompt"):
        prompt = agent.get(field)
        if prompt is None:
            continue
        text = str(prompt)
        value[f"{field}_length"] = len(text)
        value[f"{field}_sha256"] = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
    return value


def _redacted_stdout(execution: PythonExecutionResult | None) -> dict[str, Any]:
    if execution is None or execution.output is None:
        return {"runtime_success": False}
    output = execution.output
    return {
        "runtime_success": execution.runtime_success,
        "submissions": [
            {
                "agent_id": item.agent_id,
                "answer": "[REDACTED]" if item.answer is not None else None,
                "submitted_round": item.submitted_round,
            }
            for item in output.submissions
        ],
        "rounds_executed": output.rounds_executed,
        "messages": [
            {
                "round_sent": item.round_sent,
                "round_delivered": item.round_delivered,
                "src": item.src,
                "dst": item.dst,
                "source_ids": item.source_ids,
                "body": "[REDACTED]" if item.body is not None else None,
            }
            for item in output.messages
        ],
        "usage": execution.authoritative_usage.model_dump(mode="json"),
        "errors": ["[REDACTED]" for _ in output.errors],
    }


def _scrub(text: str) -> str:
    scrubbed = text
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(
            marker in name.upper() for marker in ("API_KEY", "APIKEY", "SECRET", "TOKEN")
        ):
            scrubbed = scrubbed.replace(value, f"[REDACTED:{name}]")
    return scrubbed
