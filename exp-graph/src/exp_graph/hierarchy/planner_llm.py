"""LLM-driven hierarchy planner (M3).

This is the "皇帝是 LLM" entry point. It runs once before the synchronous
runner starts, asks an LLM to choose ``fanout_schedule`` and (optionally) an
explicit dispatch tree, validates the output against bounds, falls back to a
static plan when validation fails, and returns a ``HierarchyPlan`` enriched
with planner metadata + a ``DispatchTree``.

Design choices:

- The LLM only chooses ``fanout_schedule`` (and optionally per-agent dispatch
  text). It does **not** choose ``max_depth`` or ``max_n_agents``: those are
  experiment-level controls. The emperor is autonomous within those bounds.
- ``rationale`` is captured for trace auditing but never fed back into runner
  logic.
- ``dispatch_tree`` is always built (mechanical fallback) so downstream agents
  always have an assignment string to read in their prompt.
- This module performs exactly one LLM call. The runner's per-round LLM
  budget remains separate.
"""

from __future__ import annotations

import json
from math import prod
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.hierarchy.dispatch import (
    DispatchTree,
    SubordinateDispatchDecision,
    apply_subordinate_decision,
    attach_dispatch_to_plan,
    build_static_dispatch_tree,
    mechanical_equal_split_children,
    parse_llm_dispatch,
    parse_subordinate_dispatch,
)
from exp_graph.hierarchy.plan import HierarchyPlan, Role
from exp_graph.hierarchy.planner_static import build_static_hierarchy_plan
from exp_graph.llm.base import LLMClient, LLMResponse, LLMUsage, combine_usage
from exp_graph.llm.parser import extract_json_object


EMPEROR_PROMPT_MARKER = "EMPEROR_PLANNING_PROMPT_V1"
SUBORDINATE_PROMPT_MARKER = "SUBORDINATE_DISPATCH_PROMPT_V1"


class M3PlannerConfig(BaseModel):
    """Bounds the user sets on the emperor's autonomy."""

    max_depth: int = 4
    max_n_agents: int = 64
    max_fanout_per_layer: int = 32
    min_n_soldiers: int = 1
    fallback_fanout_schedule: list[int] = Field(default_factory=lambda: [8])
    model_name: str = "fake-model"
    temperature: float = 0.0
    allowed_split_strategies: list[str] = Field(
        default_factory=lambda: ["equal_shard_by_index"]
    )
    recursive_dispatch: bool = False
    verbose: bool = False
    plan_retry_attempts: int = 2
    include_constraint_examples: bool = True


class SubordinateDispatchCall(BaseModel):
    """Bookkeeping for one parent's recursive dispatch LLM call (M3-full)."""

    agent_id: int
    role: str
    layer: int
    parent_slice: tuple[int, int]
    children_ids: list[int]
    used_llm: bool
    fallback_used: bool
    fallback_reason: str = ""
    rationale: str = ""
    raw_response_text: str = ""
    raw_prompt: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)


class PlannerRetryRecord(BaseModel):
    """One emperor planning attempt, kept for trace audit."""

    attempt_idx: int
    proposed_fanout_schedule: list[int] = Field(default_factory=list)
    rationale: str = ""
    reason: str = ""
    accepted: bool
    raw_response_text: str = ""
    raw_prompt: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)


class LLMPlanResult(BaseModel):
    """Output of one LLM planning call, with bookkeeping for trace and metrics."""

    plan: HierarchyPlan
    dispatch: DispatchTree
    used_llm: bool
    fallback_used: bool
    fallback_reason: str = ""
    rationale: str = ""
    chosen_fanout_schedule: list[int] = Field(default_factory=list)
    chosen_split_strategy: str = ""
    raw_response_text: str = ""
    raw_prompt: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    subordinate_calls: list[SubordinateDispatchCall] = Field(default_factory=list)
    recursive_dispatch_used: bool = False
    planner_retry_attempts: int = 0
    planner_retry_records: list[PlannerRetryRecord] = Field(default_factory=list)

    @property
    def total_planner_usage(self) -> LLMUsage:
        return combine_usage(
            [self.usage] + [call.usage for call in self.subordinate_calls]
        )


class LLMHierarchyPlanner:
    """Run one LLM call to produce a hierarchy plan from a task description."""

    def __init__(
        self,
        *,
        config: M3PlannerConfig,
        llm_client: LLMClient,
    ) -> None:
        self.config = config
        self.llm_client = llm_client

    def plan(
        self,
        *,
        task_description: dict[str, Any],
    ) -> LLMPlanResult:
        """Build a plan for ``task_description``.

        Performs up to ``plan_retry_attempts + 1`` LLM calls (one initial call
        plus retries). After a rejected proposal, the next call sees the
        previous proposal and the validator's rejection reason and is asked
        to choose a strictly compliant fanout. Falls back to
        ``fallback_fanout_schedule`` only after all attempts are exhausted.
        """
        attempts: list[PlannerRetryRecord] = []
        responses: list[LLMResponse] = []
        prompts: list[str] = []

        last_proposed: list[int] = []
        last_reason = ""

        used_llm = False
        chosen_fanout: list[int] = []
        rationale = ""
        chosen_split = self.config.allowed_split_strategies[0]
        raw_dispatch: Any = None
        max_attempts = max(1, self.config.plan_retry_attempts + 1)

        for attempt_idx in range(max_attempts):
            if attempt_idx == 0:
                prompt = build_emperor_planning_prompt(
                    config=self.config,
                    task_description=task_description,
                )
            else:
                prompt = build_emperor_retry_prompt(
                    config=self.config,
                    task_description=task_description,
                    previous_fanout=last_proposed,
                    previous_reason=last_reason,
                    attempt_idx=attempt_idx,
                    max_attempts=max_attempts,
                )

            if self.config.verbose:
                event = "planner.emperor.call" if attempt_idx == 0 else "planner.emperor.retry"
                self._log(
                    event,
                    f"attempt={attempt_idx + 1}/{max_attempts} "
                    f"model={self.config.model_name} "
                    f"prev_proposal={last_proposed or None} "
                    f"prev_reason={last_reason!r}",
                )

            response = self.llm_client.complete(
                prompt,
                model_name=self.config.model_name,
                temperature=self.config.temperature,
            )
            responses.append(response)
            prompts.append(prompt)
            if self.config.verbose:
                self._log(
                    "planner.emperor.response",
                    f"attempt={attempt_idx + 1}/{max_attempts} "
                    f"prompt_tokens={response.usage.prompt_tokens} "
                    f"completion_tokens={response.usage.completion_tokens} "
                    f"raw={_truncate_text(response.text)}",
                )

            attempt_fanout: list[int] = []
            attempt_rationale = ""
            attempt_split = self.config.allowed_split_strategies[0]
            attempt_dispatch: Any = None
            parse_error = ""

            try:
                payload = extract_json_object(response.text)
            except (ValueError, TypeError) as exc:
                parse_error = f"failed to parse emperor response as JSON: {exc}"
                payload = {}

            if isinstance(payload, dict):
                attempt_fanout = _coerce_int_list(payload.get("fanout_schedule"))
                attempt_rationale = str(payload.get("rationale") or "").strip()
                split_value = str(
                    payload.get("split_strategy")
                    or self.config.allowed_split_strategies[0]
                ).strip()
                if split_value in self.config.allowed_split_strategies:
                    attempt_split = split_value
                attempt_dispatch = payload.get("dispatch")

            validation_error = validate_fanout(attempt_fanout, config=self.config)
            attempt_reason = parse_error or validation_error or ""
            attempt_accepted = bool(attempt_fanout) and not attempt_reason

            attempts.append(
                PlannerRetryRecord(
                    attempt_idx=attempt_idx,
                    proposed_fanout_schedule=attempt_fanout,
                    rationale=attempt_rationale,
                    reason=attempt_reason,
                    accepted=attempt_accepted,
                    raw_response_text=response.text,
                    raw_prompt=prompt,
                    usage=response.usage,
                )
            )
            if self.config.verbose:
                if attempt_accepted:
                    self._log(
                        "planner.emperor.accepted",
                        f"attempt={attempt_idx + 1}/{max_attempts} "
                        f"fanout={attempt_fanout} rationale={attempt_rationale!r}",
                    )
                else:
                    self._log(
                        "planner.emperor.rejected",
                        f"attempt={attempt_idx + 1}/{max_attempts} "
                        f"proposed={attempt_fanout} reason={attempt_reason!r} "
                        f"rationale={attempt_rationale!r}",
                    )

            if attempt_accepted:
                used_llm = True
                chosen_fanout = attempt_fanout
                rationale = attempt_rationale
                chosen_split = attempt_split
                raw_dispatch = attempt_dispatch
                break

            last_proposed = list(attempt_fanout)
            last_reason = attempt_reason
            chosen_fanout = attempt_fanout
            rationale = attempt_rationale

        fallback_used = not used_llm
        fallback_reason = ""
        if not used_llm:
            tail = attempts[-1] if attempts else None
            fallback_reason = (
                tail.reason
                if tail is not None
                else "no planner attempts produced a valid fanout"
            )

        combined_usage = combine_usage([r.usage for r in responses]) if responses else LLMUsage()
        last_response_text = responses[-1].text if responses else ""
        first_prompt = prompts[0] if prompts else ""

        if used_llm:
            final_fanout = list(chosen_fanout)
        else:
            final_fanout = list(self.config.fallback_fanout_schedule)

        array_length = _array_length_from_task(task_description)
        plan = build_static_hierarchy_plan(
            final_fanout,
            array_length=array_length,
        )
        plan.metadata["planner"] = "llm" if used_llm else "static_fallback"
        plan.metadata["planner_model_name"] = self.config.model_name
        plan.metadata["planner_temperature"] = self.config.temperature
        plan.metadata["llm_rationale"] = rationale
        plan.metadata["llm_chosen_fanout_schedule"] = chosen_fanout
        plan.metadata["llm_chosen_split_strategy"] = chosen_split
        plan.metadata["llm_fallback_used"] = fallback_used
        plan.metadata["llm_fallback_reason"] = fallback_reason
        plan.metadata["planner_retry_attempts"] = max(0, len(attempts) - 1)
        plan.metadata["planner_attempts_total"] = len(attempts)

        dispatch: DispatchTree | None = None
        if used_llm and raw_dispatch is not None:
            dispatch = parse_llm_dispatch(
                plan,
                raw_dispatch,
                array_length=array_length,
                rationale=rationale,
            )
        if dispatch is None:
            dispatch = build_static_dispatch_tree(
                plan,
                array_length=array_length,
                rationale=rationale,
            )

        subordinate_calls: list[SubordinateDispatchCall] = []
        recursive_used = False
        if self.config.recursive_dispatch:
            dispatch, subordinate_calls = self._run_recursive_dispatch(
                plan=plan,
                dispatch=dispatch,
            )
            recursive_used = bool(subordinate_calls)

        plan = attach_dispatch_to_plan(plan, dispatch)

        return LLMPlanResult(
            plan=plan,
            dispatch=dispatch,
            used_llm=used_llm,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            rationale=rationale,
            chosen_fanout_schedule=chosen_fanout,
            chosen_split_strategy=chosen_split,
            raw_response_text=last_response_text,
            raw_prompt=first_prompt,
            usage=combined_usage,
            subordinate_calls=subordinate_calls,
            recursive_dispatch_used=recursive_used,
            planner_retry_attempts=max(0, len(attempts) - 1),
            planner_retry_records=attempts,
        )

    def _run_recursive_dispatch(
        self,
        *,
        plan: HierarchyPlan,
        dispatch: DispatchTree,
    ) -> tuple[DispatchTree, list[SubordinateDispatchCall]]:
        """Walk non-leaf nodes top-down and ask each one how to split.

        Each parent's LLM call decides its own children's slices, independently
        of its siblings. A parent that fails validation falls back to a
        mechanical equal split for that sub-tree only; its sibling sub-trees
        keep whatever decisions their own LLM calls produced.
        """
        records: list[SubordinateDispatchCall] = []
        layers = sorted({node.layer for node in plan.nodes})
        for layer_idx in layers:
            for node in plan.nodes:
                if node.layer != layer_idx:
                    continue
                if node.role == Role.SOLDIER or not node.children_ids:
                    continue
                if node.role == Role.EMPEROR:
                    # The emperor's top-level planning call already chose
                    # ministers' slices via the dispatch tree; recursive
                    # dispatch only adds value at non-root managers.
                    continue
                entry = dispatch.for_agent(node.agent_id)
                if entry is None or entry.aggregated_slice is None:
                    continue
                children_nodes = [plan.node(child_id) for child_id in node.children_ids]
                prompt = build_subordinate_dispatch_prompt(
                    node=node,
                    parent_slice=entry.aggregated_slice,
                    children_nodes=children_nodes,
                )
                if self.config.verbose:
                    self._log(
                        "planner.subordinate.call",
                        f"agent={node.agent_id} role={node.role.value} "
                        f"layer={node.layer} parent_slice={entry.aggregated_slice} "
                        f"children={list(node.children_ids)}",
                    )
                response = self.llm_client.complete(
                    prompt,
                    model_name=self.config.model_name,
                    temperature=self.config.temperature,
                )

                payload: Any = None
                parse_error = ""
                try:
                    payload = extract_json_object(response.text)
                except (TypeError, ValueError) as exc:
                    parse_error = (
                        f"failed to parse subordinate dispatch JSON: {exc}"
                    )

                rationale = ""
                decision: SubordinateDispatchDecision | None = None
                if isinstance(payload, dict):
                    rationale = str(payload.get("rationale") or "").strip()
                    decision = parse_subordinate_dispatch(
                        parent_node=node,
                        parent_slice=entry.aggregated_slice,
                        children_nodes=children_nodes,
                        raw_payload=payload,
                        rationale=rationale,
                    )

                used_llm = decision is not None and not parse_error
                if decision is None:
                    decision = mechanical_equal_split_children(
                        parent_node=node,
                        parent_slice=entry.aggregated_slice,
                        children_nodes=children_nodes,
                    )
                fallback_reason = parse_error
                if not used_llm and not fallback_reason:
                    fallback_reason = (
                        "subordinate output failed partition validation"
                    )

                source_label = (
                    "llm_recursive" if used_llm else "recursive_fallback"
                )
                dispatch = apply_subordinate_decision(
                    dispatch,
                    decision,
                    decision_source_label=source_label,
                )
                if self.config.verbose:
                    if used_llm:
                        self._log(
                            "planner.subordinate.accepted",
                            f"agent={node.agent_id} "
                            f"prompt_tokens={response.usage.prompt_tokens} "
                            f"completion_tokens={response.usage.completion_tokens} "
                            f"rationale={rationale!r}",
                        )
                    else:
                        self._log(
                            "planner.subordinate.rejected",
                            f"agent={node.agent_id} reason={fallback_reason!r} "
                            f"falling back to equal split",
                        )

                records.append(
                    SubordinateDispatchCall(
                        agent_id=node.agent_id,
                        role=node.role.value,
                        layer=node.layer,
                        parent_slice=entry.aggregated_slice,
                        children_ids=list(node.children_ids),
                        used_llm=used_llm,
                        fallback_used=not used_llm,
                        fallback_reason=fallback_reason,
                        rationale=rationale,
                        raw_response_text=response.text,
                        raw_prompt=prompt,
                        usage=response.usage,
                    )
                )

        if records:
            dispatch = dispatch.model_copy(update={"source": "llm_recursive"})
        return dispatch, records

    def _log(self, event_type: str, message: str) -> None:
        print(f"[{event_type}] {message}", flush=True)


def _truncate_text(value: str, *, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def build_emperor_planning_prompt(
    *,
    config: M3PlannerConfig,
    task_description: dict[str, Any],
) -> str:
    """Render the emperor planning prompt."""
    examples_block = (
        _format_constraint_examples(config)
        if config.include_constraint_examples
        else ""
    )
    return (
        f"{EMPEROR_PROMPT_MARKER}\n"
        "You are the planning emperor in a hierarchical multi-agent system.\n"
        "You will dispatch a team to solve a task by choosing a fan-out\n"
        "schedule. You output ONE JSON object only.\n\n"
        "PLANNING_CONSTRAINTS_JSON:\n"
        f"{json.dumps(_planning_constraints(config), sort_keys=True)}\n\n"
        "TASK_DESCRIPTION_JSON:\n"
        f"{json.dumps(task_description, sort_keys=True)}\n\n"
        "IMPORTANT BUDGET CONTRACT:\n"
        "- The values in PLANNING_CONSTRAINTS_JSON are hard upper bounds, "
        "not suggestions.\n"
        "- Your fanout_schedule MUST fit inside max_depth, max_n_agents, "
        "and max_fanout_per_layer simultaneously.\n"
        "- If your output violates any max constraint, a validator will reject "
        "your plan and replace it with a fallback plan.\n"
        "- Treat max_n_agents as the total population budget including the "
        "emperor. For fanout [a,b,c], total agents are "
        "1 + a + a*b + a*b*c.\n"
        "- Before answering, MENTALLY COMPUTE the total agents for your "
        "candidate fanout and confirm it is <= max_n_agents.\n"
        f"{examples_block}"
        "Return only this JSON schema:\n"
        "{\n"
        '  "fanout_schedule": [int, ...],\n'
        '  "split_strategy": "equal_shard_by_index",\n'
        '  "rationale": "short reason",\n'
        '  "dispatch": null\n'
        "}\n\n"
        "Hard rules:\n"
        f"- len(fanout_schedule) <= {config.max_depth - 1} (depth = "
        f"len + 1, max_depth includes the emperor)\n"
        f"- 1 <= each fanout <= {config.max_fanout_per_layer}\n"
        "- total agents = 1 + sum of cumulative products <= "
        f"{config.max_n_agents}\n"
        f"- prod(fanout_schedule) >= {config.min_n_soldiers}\n"
        f"- split_strategy in {config.allowed_split_strategies}\n"
        "- If unsure, prefer fewer layers and balanced fan-out.\n"
        "- Only output the JSON object; no prose, no Markdown.\n"
    )


EMPEROR_RETRY_PROMPT_MARKER = "EMPEROR_PLANNING_RETRY_PROMPT_V1"


def build_emperor_retry_prompt(
    *,
    config: M3PlannerConfig,
    task_description: dict[str, Any],
    previous_fanout: list[int],
    previous_reason: str,
    attempt_idx: int,
    max_attempts: int,
) -> str:
    """Render the retry prompt after a previous proposal was rejected."""
    examples_block = (
        _format_constraint_examples(config)
        if config.include_constraint_examples
        else ""
    )
    previous_summary = {
        "fanout_schedule": list(previous_fanout) if previous_fanout else None,
        "rejection_reason": previous_reason or "unknown",
        "n_total_if_applied": _expected_total_for_fanout(previous_fanout),
    }
    return (
        f"{EMPEROR_RETRY_PROMPT_MARKER}\n"
        f"This is retry attempt {attempt_idx + 1} of {max_attempts}. "
        "Your previous fanout_schedule was REJECTED by the validator.\n\n"
        "PREVIOUS_REJECTED_PROPOSAL_JSON:\n"
        f"{json.dumps(previous_summary, sort_keys=True)}\n\n"
        "PLANNING_CONSTRAINTS_JSON:\n"
        f"{json.dumps(_planning_constraints(config), sort_keys=True)}\n\n"
        "TASK_DESCRIPTION_JSON:\n"
        f"{json.dumps(task_description, sort_keys=True)}\n\n"
        "Required: propose a NEW fanout_schedule that strictly satisfies all "
        "hard rules. Do not repeat the rejected proposal. Recompute the "
        "total agents with 1 + sum of cumulative products and verify it is "
        f"<= {config.max_n_agents} BEFORE answering.\n"
        f"{examples_block}"
        "Return only this JSON schema:\n"
        "{\n"
        '  "fanout_schedule": [int, ...],\n'
        '  "split_strategy": "equal_shard_by_index",\n'
        '  "rationale": "short reason",\n'
        '  "dispatch": null\n'
        "}\n\n"
        "Hard rules:\n"
        f"- len(fanout_schedule) <= {config.max_depth - 1}\n"
        f"- 1 <= each fanout <= {config.max_fanout_per_layer}\n"
        "- total agents = 1 + sum of cumulative products <= "
        f"{config.max_n_agents}\n"
        f"- prod(fanout_schedule) >= {config.min_n_soldiers}\n"
        f"- split_strategy in {config.allowed_split_strategies}\n"
        "- Only output the JSON object; no prose, no Markdown.\n"
    )


def _format_constraint_examples(config: M3PlannerConfig) -> str:
    """Build worked examples that thread the user's actual constraints."""
    examples = _build_concrete_examples(config)
    if not examples:
        return ""
    lines = ["WORKED EXAMPLES (using your actual constraints):"]
    for fanout, total, ok, reason in examples:
        marker = "OK" if ok else "REJECTED"
        breakdown = " + ".join(str(part) for part in _cumulative_breakdown(fanout))
        lines.append(
            f"  fanout={fanout} -> total = {breakdown} = {total}  [{marker}]"
            + (f" reason: {reason}" if reason else "")
        )
    return "\n".join(lines) + "\n\n"


def _build_concrete_examples(
    config: M3PlannerConfig,
) -> list[tuple[list[int], int, bool, str]]:
    """Pick a small, instructive set of fanout candidates anchored to ``config``."""
    cap = config.max_n_agents
    layer_cap = config.max_fanout_per_layer
    depth_cap = config.max_depth
    candidate_fanouts: list[list[int]] = []

    def _add(value: list[int]) -> None:
        if not value or any(v < 1 for v in value):
            return
        if len(value) + 1 > depth_cap:
            return
        if any(v > layer_cap for v in value):
            return
        if value not in candidate_fanouts:
            candidate_fanouts.append(value)

    _add([min(2, layer_cap)])
    _add([min(4, layer_cap)])
    _add([2, min(2, layer_cap)])
    _add([2, min(4, layer_cap)])
    _add([min(4, layer_cap), min(4, layer_cap)])
    _add([layer_cap, layer_cap])
    if depth_cap >= 4:
        _add([2, 2, 2])

    examples: list[tuple[list[int], int, bool, str]] = []
    for fanout in candidate_fanouts:
        total = _expected_total_for_fanout(fanout)
        ok = total <= cap and total > 0
        reason = "" if ok else f"total {total} exceeds max_n_agents={cap}"
        examples.append((fanout, total, ok, reason))
    has_ok = any(item[2] for item in examples)
    has_rejected = any(not item[2] for item in examples)
    if has_ok and has_rejected:
        return examples
    if has_ok and not has_rejected:
        return examples
    if not has_ok and has_rejected:
        return examples
    return examples


def _cumulative_breakdown(fanout: list[int]) -> list[int]:
    """Return [1, a, a*b, a*b*c, ...] for human-readable example output."""
    parts = [1]
    cumulative = 1
    for f in fanout:
        cumulative *= int(f)
        parts.append(cumulative)
    return parts


def _expected_total_for_fanout(fanout: list[int]) -> int:
    if not fanout:
        return 0
    sizes = [1]
    for f in fanout:
        sizes.append(sizes[-1] * int(f))
    return sum(sizes)


def build_subordinate_dispatch_prompt(
    *,
    node,
    parent_slice: tuple[int, int],
    children_nodes,
) -> str:
    """Render a recursive dispatch prompt for one minister or sub-manager."""
    children_descriptions = [
        {
            "agent_id": child.agent_id,
            "role": child.role.value,
            "layer": child.layer,
            "is_leaf": child.role == Role.SOLDIER,
            "grandchildren_ids": list(child.children_ids),
        }
        for child in children_nodes
    ]
    return (
        f"{SUBORDINATE_PROMPT_MARKER}\n"
        "You are a manager agent inside a hierarchical multi-agent system.\n"
        "Your parent already decided the team shape; you only decide how to\n"
        "subdivide your assigned slice among your direct subordinates.\n\n"
        "AGENT_SELF_JSON:\n"
        f"{json.dumps({'agent_id': node.agent_id, 'role': node.role.value, 'layer': node.layer}, sort_keys=True)}\n\n"
        "ASSIGNED_SLICE_JSON:\n"
        f"{json.dumps({'start': int(parent_slice[0]), 'end': int(parent_slice[1])}, sort_keys=True)}\n\n"
        "CHILDREN_JSON:\n"
        f"{json.dumps(children_descriptions, sort_keys=True)}\n\n"
        "Output ONLY this JSON object:\n"
        "{\n"
        '  "rationale": "short reason",\n'
        '  "children": {\n'
        '    "agent_<id>": {\n'
        '      "shard": [a, b],   // for soldier subordinates only\n'
        '      "slice": [a, b],   // for non-soldier subordinates only\n'
        '      "instruction": "short instruction"\n'
        "    },\n"
        "    ...\n"
        "  }\n"
        "}\n\n"
        "Hard rules:\n"
        "- The union of children shards/slices must equal your assigned slice.\n"
        "- No overlap. No gap.\n"
        "- Subordinate agent ids must match exactly the CHILDREN_JSON list.\n"
        "- Use 'shard' for soldier children, 'slice' for non-soldier children.\n"
        "- Output JSON only; no Markdown, no prose.\n"
    )


def _planning_constraints(config: M3PlannerConfig) -> dict[str, Any]:
    return {
        "max_depth": config.max_depth,
        "max_n_agents": config.max_n_agents,
        "max_fanout_per_layer": config.max_fanout_per_layer,
        "min_n_soldiers": config.min_n_soldiers,
        "allowed_split_strategies": list(config.allowed_split_strategies),
    }


def validate_fanout(
    fanout: list[int],
    *,
    config: M3PlannerConfig,
) -> str:
    """Return an error message if ``fanout`` violates ``config`` bounds, else empty."""
    if not fanout:
        return "fanout_schedule must be non-empty"
    if len(fanout) + 1 > config.max_depth:
        return (
            f"depth={len(fanout) + 1} exceeds max_depth={config.max_depth}"
        )
    for value in fanout:
        if value < 1:
            return f"fanout value {value} must be >= 1"
        if value > config.max_fanout_per_layer:
            return (
                f"fanout value {value} exceeds max_fanout_per_layer="
                f"{config.max_fanout_per_layer}"
            )
    if prod(fanout) < config.min_n_soldiers:
        return (
            f"prod(fanout)={prod(fanout)} below min_n_soldiers="
            f"{config.min_n_soldiers}"
        )
    layer_sizes = [1]
    for f in fanout:
        layer_sizes.append(layer_sizes[-1] * int(f))
    n_total = sum(layer_sizes)
    if n_total > config.max_n_agents:
        return (
            f"n_total={n_total} exceeds max_n_agents={config.max_n_agents}"
        )
    return ""


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    cleaned: list[int] = []
    for item in value:
        try:
            cleaned.append(int(item))
        except (TypeError, ValueError):
            return []
    return cleaned


def _array_length_from_task(task_description: dict[str, Any]) -> int | None:
    for key in ("array_length", "array_size", "n_items", "length"):
        if key in task_description:
            try:
                return int(task_description[key])
            except (TypeError, ValueError):
                continue
    array = task_description.get("array")
    if isinstance(array, list):
        return len(array)
    return None
