"""Safe, block-scoped mutation primitives for PythonGen parent skills."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from statistics import fmean
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from exp_graph.llm.parser import extract_json_object
from exp_graph.mas.python_code import python_source_sha256
from exp_graph.mas.schemas import SkillCard


PYTHON_MUTATION_PATCH_FORMAT = "python_mutation_patch_v1"
_START_RE = re.compile(
    r"^(?P<indent>[ \t]*)# EVOLVE-BLOCK-START: (?P<block>[A-Za-z0-9_-]+)[ \t]*$"
)
_END_RE = re.compile(
    r"^(?P<indent>[ \t]*)# EVOLVE-BLOCK-END: (?P<block>[A-Za-z0-9_-]+)[ \t]*$"
)
_FORBIDDEN_CONTEXT_KEYS = {
    "answer",
    "answers",
    "final_answer",
    "ground_truth",
    "expected_output",
    "expected_outputs",
    "expected_answer",
    "expected_answers",
    "prompt",
    "task_prompt",
    "agent_prompt",
    "local_prompt",
    "private_prompt",
    "private_data",
    "communication_prompt",
    "submit_prompt",
    "source_code",
    "python_source",
    "protocol_spec",
    "compiled_protocol_spec",
    "phase_program",
    "topology_program",
    "structure_code",
    "code",
    "steps",
    "edges",
    "mode_payload",
    "shard",
    "shards",
}


class PythonMutationError(RuntimeError):
    """A malformed or policy-violating mutation patch."""


class PythonMutationSkipped(RuntimeError):
    """Mutation is unavailable (for example, no same-contract Python parent)."""


class PythonMutationPatch(BaseModel):
    """One host-applied replacement inside an existing EVOLVE-BLOCK."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["python_mutation_patch_v1"] = PYTHON_MUTATION_PATCH_FORMAT
    parent_program_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    block_id: str = Field(min_length=1, max_length=80)
    replacement: str = Field(max_length=20_000)
    used_insight_ids: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("used_insight_ids")
    @classmethod
    def unique_insight_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class PythonEvolveBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    start_line: int
    end_line: int
    indent: str
    content: str


class AppliedPythonMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(exclude=True)
    block_id: str
    parent_program_sha256: str
    mutated_program_sha256: str
    diff_sha256: str
    diff: str
    used_insight_ids: tuple[str, ...]


def extract_evolve_blocks(source: str) -> dict[str, PythonEvolveBlock]:
    """Parse balanced, uniquely named EVOLVE-BLOCK regions."""
    lines = source.splitlines(keepends=True)
    blocks: dict[str, PythonEvolveBlock] = {}
    active: tuple[str, int, str] | None = None
    for index, line in enumerate(lines):
        plain = line.rstrip("\r\n")
        start = _START_RE.match(plain)
        end = _END_RE.match(plain)
        if start:
            if active is not None:
                raise PythonMutationError("nested EVOLVE-BLOCK markers are forbidden")
            block_id = start.group("block")
            if block_id in blocks:
                raise PythonMutationError(f"duplicate EVOLVE-BLOCK {block_id!r}")
            active = (block_id, index, start.group("indent"))
            continue
        if end:
            if active is None or end.group("block") != active[0]:
                raise PythonMutationError("unbalanced EVOLVE-BLOCK end marker")
            block_id, start_index, indent = active
            blocks[block_id] = PythonEvolveBlock(
                block_id=block_id,
                start_line=start_index + 1,
                end_line=index + 1,
                indent=indent,
                content="".join(lines[start_index + 1:index]),
            )
            active = None
    if active is not None:
        raise PythonMutationError(f"missing end marker for EVOLVE-BLOCK {active[0]!r}")
    if not blocks:
        raise PythonMutationError("parent source contains no EVOLVE-BLOCK regions")
    return blocks


def parse_python_mutation_patch(text: str) -> PythonMutationPatch:
    try:
        payload = extract_json_object(text)
        return PythonMutationPatch.model_validate(payload)
    except Exception as exc:
        raise PythonMutationError(f"invalid python_mutation_patch_v1: {exc}") from exc


def apply_python_mutation_patch(
    parent_source: str,
    patch: PythonMutationPatch,
    *,
    allowed_insight_ids: Iterable[str] | None = None,
) -> AppliedPythonMutation:
    """Validate parent hash/whitelist and replace exactly one block body."""
    parent_hash = python_source_sha256(parent_source)
    if patch.parent_program_sha256 != parent_hash:
        raise PythonMutationError("parent_program_sha256 does not match parent source")
    if allowed_insight_ids is not None:
        allowed = {str(item) for item in allowed_insight_ids}
        unknown = sorted(set(patch.used_insight_ids) - allowed)
        if unknown:
            raise PythonMutationError(
                f"used_insight_ids contains unexposed IDs: {unknown}"
            )
    if "EVOLVE-BLOCK-START" in patch.replacement or "EVOLVE-BLOCK-END" in patch.replacement:
        raise PythonMutationError("replacement may not add or remove EVOLVE-BLOCK markers")
    blocks = extract_evolve_blocks(parent_source)
    block = blocks.get(patch.block_id)
    if block is None:
        raise PythonMutationError(
            f"block_id {patch.block_id!r} is not in the parent whitelist"
        )
    lines = parent_source.splitlines(keepends=True)
    replacement = patch.replacement
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    mutated = "".join(
        [*lines[: block.start_line], replacement, *lines[block.end_line - 1 :]]
    )
    # Applying a patch must not change the marker set or any non-selected block.
    mutated_blocks = extract_evolve_blocks(mutated)
    if set(mutated_blocks) != set(blocks):
        raise PythonMutationError("mutation changed the EVOLVE-BLOCK whitelist")
    for block_id in blocks:
        if block_id != patch.block_id and mutated_blocks[block_id].content != blocks[block_id].content:
            raise PythonMutationError("mutation changed a non-selected EVOLVE-BLOCK")
    diff = "".join(
        difflib.unified_diff(
            parent_source.splitlines(keepends=True),
            mutated.splitlines(keepends=True),
            fromfile="parent.py",
            tofile="mutated.py",
        )
    )
    return AppliedPythonMutation(
        source=mutated,
        block_id=patch.block_id,
        parent_program_sha256=parent_hash,
        mutated_program_sha256=python_source_sha256(mutated),
        diff_sha256=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        diff=diff,
        used_insight_ids=tuple(patch.used_insight_ids),
    )


def _clean_context_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _clean_context_value(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _FORBIDDEN_CONTEXT_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_clean_context_value(item) for item in value[:32]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _mean(rows: list[dict[str, object]], key: str) -> float:
    values: list[float] = []
    for row in rows:
        try:
            value = float(row.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if value == value and value not in (float("inf"), float("-inf")):
            values.append(value)
    return fmean(values) if values else 0.0


def sanitize_python_skill_context(
    skill: SkillCard,
    *,
    max_chars: int = 6_000,
) -> dict[str, Any]:
    """Build an allowlisted parent summary with no executable/private payload."""
    evidence = [dict(row) for row in skill.evidence if isinstance(row, dict)]
    context = {
        "parent_skill_id": skill.skill_id,
        "reasoning_policy": _clean_context_value(skill.reasoning_policy),
        "design_insights": _clean_context_value(skill.design_insights),
        "failure_modes": _clean_context_value(skill.failure_modes),
        "counterexamples": _clean_context_value(skill.counterexamples),
        "dense_metrics": {
            "n": len(evidence),
            "V": _mean(evidence, "program_validity"),
            "K": _mean(evidence, "structural_coverage"),
            "U": _mean(evidence, "submission_rate"),
            "P": _mean(evidence, "evolution_partial"),
            "S": _mean(evidence, "evolution_success"),
            "stage_score": _mean(evidence, "evolution_stage_score"),
        },
        "cost_metrics": {
            "C": _mean(evidence, "paper_C"),
            "D": _mean(evidence, "paper_D"),
            "tokens": _mean(evidence, "MeanTokenCost"),
            "messages": _mean(evidence, "MeanTotalMessages"),
        },
    }
    encoded = json.dumps(context, ensure_ascii=True, sort_keys=True)
    if len(encoded) <= max_chars:
        return context
    # Keep identity and measured summaries; shrink prose deterministically until
    # the serialized object truly obeys the configured cap.
    context["design_insights"] = list(context["design_insights"] or [])[:2]
    context["failure_modes"] = list(context["failure_modes"] or [])[:2]
    context["counterexamples"] = list(context["counterexamples"] or [])[:2]
    context["reasoning_policy"] = {"truncated": True}
    for key in ("counterexamples", "failure_modes", "design_insights"):
        values = context[key]
        assert isinstance(values, list)
        while values and len(
            json.dumps(context, ensure_ascii=True, sort_keys=True)
        ) > max_chars:
            values.pop()
    if len(json.dumps(context, ensure_ascii=True, sort_keys=True)) > max_chars:
        context.update(
            {
                "reasoning_policy": {},
                "design_insights": [],
                "failure_modes": [],
                "counterexamples": [],
            }
        )
    return context


def insight_ids_from_context(context: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    items = context.get("design_insights", [])
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping) and item.get("insight_id"):
                result.append(str(item["insight_id"]))
    return list(dict.fromkeys(result))


def split_python_skill_context(
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    positive = {
        key: value
        for key, value in context.items()
        if key not in {"failure_modes", "counterexamples"}
    }
    negative = [
        {
            "parent_skill_id": context.get("parent_skill_id"),
            "failure_modes": context.get("failure_modes", []),
            "counterexamples": context.get("counterexamples", []),
        }
    ]
    return positive, negative


def build_python_mutation_prompt(
    *,
    parent_source: str,
    parent_skill_id: str,
    positive_context: Mapping[str, Any],
    negative_context: list[dict[str, Any]],
    failure: Mapping[str, Any] | None = None,
) -> str:
    blocks = extract_evolve_blocks(parent_source)
    payload = {
        "format": PYTHON_MUTATION_PATCH_FORMAT,
        "parent_skill_id": parent_skill_id,
        "parent_program_sha256": python_source_sha256(parent_source),
        "editable_blocks": {
            block_id: block.content for block_id, block in sorted(blocks.items())
        },
        "positive_skill_context": _clean_context_value(positive_context),
        "negative_failure_context": _clean_context_value(negative_context),
        "latest_validation_failure": _clean_context_value(dict(failure or {})),
        "output_schema": {
            "format": PYTHON_MUTATION_PATCH_FORMAT,
            "parent_program_sha256": "copy exact hash above",
            "block_id": "one key from editable_blocks",
            "replacement": "complete replacement body for that block only",
            "used_insight_ids": ["only IDs actually used"],
        },
    }
    return (
        "PYTHON LOCAL MUTATION CONTRACT\n"
        "Improve one existing Python planner program. Return exactly one JSON "
        "object and no prose. You may replace exactly one listed EVOLVE-BLOCK. "
        "Do not rewrite the complete program, add markers, or invent an insight ID.\n\n"
        + json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    )
