"""Structural generation surface for whole-composition TRAIN rounds.

The direct channel freezes a scalar value domain before authorizing its one
generation call; this module is the structural analog.  The frozen object is
an operation domain: which typed operations are admissible, which phase kinds
they may write, how large the target program may grow (phase count and
compiled step count — PROBE reservations are sized for bounded programs), and
which compiled execution images are already registered (a textual change the
compiler elides back to a known image is an honest degenerate, not a probe).

Leakage law: the rendered prompt contains ONLY the source program structure,
the operation vocabulary, and the frozen bounds.  No benchmark case content,
no answers, no case identifiers ever enter this surface.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.mas.phase_program import PhaseProgram
from exp_graph.mas.phase_structural_ops import (
    StructuralNoOpError,
    parse_structural_operation,
)

STRUCTURAL_GENERATION_POLICY_VERSION = "sft-v5-structural-generation-v1"

_ALL_OP_KINDS = (
    "insert_phase",
    "delete_phase",
    "move_phase",
    "replace_phase",
    "fresh_skeleton",
)
_ALL_PHASE_KINDS = ("gather", "broadcast", "pairwise_exchange", "consensus")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class FrozenStructuralDomainV1(BaseModel):
    """The operation domain frozen before the generation call is authorized."""

    model_config = {"extra": "forbid", "frozen": True}

    policy_version: str = STRUCTURAL_GENERATION_POLICY_VERSION
    allowed_op_kinds: tuple[str, ...] = _ALL_OP_KINDS
    allowed_phase_kinds: tuple[str, ...] = _ALL_PHASE_KINDS
    max_phases: int = Field(default=6, ge=1, le=12)
    max_compiled_steps: int = Field(default=96, ge=1)
    excluded_image_commitments: tuple[str, ...] = ()
    source_program_json: str

    @property
    def digest(self) -> str:
        return _sha(self.model_dump(mode="json"))


def frozen_structural_domain(
    source_program: PhaseProgram,
    *,
    excluded_image_commitments: tuple[str, ...],
    max_phases: int = 6,
    max_compiled_steps: int = 96,
    allowed_op_kinds: tuple[str, ...] = _ALL_OP_KINDS,
) -> FrozenStructuralDomainV1:
    return FrozenStructuralDomainV1(
        allowed_op_kinds=tuple(allowed_op_kinds),
        max_phases=max_phases,
        max_compiled_steps=max_compiled_steps,
        excluded_image_commitments=tuple(sorted(set(excluded_image_commitments))),
        source_program_json=_canonical_json(
            source_program.model_dump(mode="json")
        ),
    )


_OP_VOCABULARY_TEXT = """\
Exactly ONE operation, as JSON. The admissible shapes are:
- {"op_kind": "insert_phase", "index": <0..len(phases)>, "phase": <PHASE>}
- {"op_kind": "delete_phase", "index": <0..len(phases)-1>}
- {"op_kind": "move_phase", "index": <i>, "to_index": <j>}   (i != j)
- {"op_kind": "replace_phase", "index": <i>, "phase": <PHASE>}
- {"op_kind": "fresh_skeleton", "phases": [<PHASE>, ...]}    (full new list)

A <PHASE> object is one of:
- {"kind": "gather", "hub": <int>, "pattern": "star"|"tree"}
- {"kind": "broadcast", "hub": <int>, "pattern": "star"|"tree"}
- {"kind": "pairwise_exchange", "pattern": "ring"|"bidirectional_ring"|\
"rotating"|"exponential", "max_rounds": <int>=1..64>}
- {"kind": "consensus", "pattern": "all_to_all"|"rotating"|"exponential", \
"max_rounds": <int>=1..64>}
Optional on any phase: "instruction": <string<=500>, "send_mode": \
"full_state"|"delta_or_no_send"."""


def render_structural_generation_prompt(
    domain: FrozenStructuralDomainV1,
    *,
    n_agents: int,
) -> str:
    source = json.loads(domain.source_program_json)
    return (
        "You are proposing ONE structural edit to a multi-agent communication "
        "program. The program is a sequence of typed phases executed by "
        f"{n_agents} agents. You will see the current (source) program; "
        "propose exactly one structural operation from the frozen vocabulary "
        "below. The edit must change the phase-container structure — adding, "
        "removing, reordering, or replacing phases, or writing a fresh phase "
        "sequence. A proposal that leaves the program unchanged, that only "
        "retunes a single scalar field of an existing phase, or that compiles "
        "to an already-registered schedule is a degenerate no-op and aborts "
        "the experiment.\n\n"
        f"SOURCE_PROGRAM_JSON:\n{json.dumps(source, indent=2)}\n\n"
        f"OPERATION VOCABULARY (allowed op_kinds: "
        f"{', '.join(domain.allowed_op_kinds)}):\n{_OP_VOCABULARY_TEXT}\n\n"
        "FROZEN BOUNDS: the resulting program must have at most "
        f"{domain.max_phases} phases and compile to at most "
        f"{domain.max_compiled_steps} scheduled steps; allowed phase kinds: "
        f"{', '.join(domain.allowed_phase_kinds)}.\n\n"
        "Reply with EXACTLY one JSON object of the form "
        '{"operation": {...}} and nothing else.'
    )


STRUCTURAL_PROMPT_TEMPLATE_SHA256 = _sha(
    {
        "policy": STRUCTURAL_GENERATION_POLICY_VERSION,
        "vocabulary": _OP_VOCABULARY_TEXT,
    }
)

STRUCTURAL_OUTPUT_SCHEMA_SHA256 = _sha(
    {
        "schema_version": "sft-v5-structural-operation-output-v1",
        "shape": {"operation": "StructuralOperationV1"},
        "op_kinds": list(_ALL_OP_KINDS),
        "phase_kinds": list(_ALL_PHASE_KINDS),
    }
)


def render_structural_generation_request(
    *,
    domain: FrozenStructuralDomainV1,
    n_agents: int,
    budget_sha256: str,
) -> Any:
    """Render the single admitted structural prompt as a metered request.

    Mirrors the scalar renderer's output type so the frozen-schedule checks in
    ``execute_metered_generation_call`` (envelope + template digests) apply
    unchanged; the envelope derivation reuses the generic request-envelope
    domain with the structural template/schema commitments.
    """

    from masbench.sft_pilot.request_renderer import (
        GENERATION_POLICY_SHA256,
        RenderedGenerationRequest,
        generation_request_envelope_sha256,
    )

    prompt_text = render_structural_generation_prompt(
        domain, n_agents=n_agents
    )
    return RenderedGenerationRequest(
        prompt_text=prompt_text,
        prompt_sha256=hashlib.sha256(
            prompt_text.encode("utf-8")
        ).hexdigest(),
        request_envelope_sha256=generation_request_envelope_sha256(
            locator_path="/phases",
            scalar_type="string",
            generation_policy_sha256=GENERATION_POLICY_SHA256,
            prompt_template_sha256=STRUCTURAL_PROMPT_TEMPLATE_SHA256,
            scalar_output_schema_sha256=STRUCTURAL_OUTPUT_SCHEMA_SHA256,
            budget_sha256=budget_sha256,
        ),
        prompt_template_sha256=STRUCTURAL_PROMPT_TEMPLATE_SHA256,
        scalar_output_schema_sha256=STRUCTURAL_OUTPUT_SCHEMA_SHA256,
        scalar_type="string",
    )


def parse_generated_operation(text: str) -> Any:
    """Strictly parse one generated operation; no repair, no retry."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("generated structural reply carries no JSON object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict) or "operation" not in payload:
        raise ValueError("generated structural reply lacks an operation field")
    return parse_structural_operation(payload["operation"])


def validate_structural_bounds(
    domain: FrozenStructuralDomainV1,
    operation: Any,
    *,
    target_program: PhaseProgram,
    target_compiled_steps: int,
    target_image_commitment: str,
) -> None:
    """Enforce the frozen operation domain on the materialized target.

    ``StructuralNoOpError`` marks honest degenerates (already-registered
    compiled image); ``ValueError`` marks domain violations.  Both abort the
    sealed single-action experiment without probe evidence.
    """

    if operation.op_kind not in domain.allowed_op_kinds:
        raise ValueError(
            f"operation kind {operation.op_kind!r} is outside the frozen domain"
        )
    written_phases = []
    if operation.op_kind in {"insert_phase", "replace_phase"}:
        written_phases = [operation.phase]
    elif operation.op_kind == "fresh_skeleton":
        written_phases = list(operation.phases)
    for phase in written_phases:
        if phase.kind not in domain.allowed_phase_kinds:
            raise ValueError(
                f"phase kind {phase.kind!r} is outside the frozen domain"
            )
    if len(target_program.phases) > domain.max_phases:
        raise ValueError(
            "target program exceeds the frozen phase-count bound "
            f"({len(target_program.phases)} > {domain.max_phases})"
        )
    if target_compiled_steps > domain.max_compiled_steps:
        raise ValueError(
            "target program exceeds the frozen compiled-step bound "
            f"({target_compiled_steps} > {domain.max_compiled_steps})"
        )
    if target_image_commitment in domain.excluded_image_commitments:
        raise StructuralNoOpError(
            "generated structure compiled to an already-registered "
            "execution image"
        )


__all__ = [
    "STRUCTURAL_GENERATION_POLICY_VERSION",
    "STRUCTURAL_OUTPUT_SCHEMA_SHA256",
    "STRUCTURAL_PROMPT_TEMPLATE_SHA256",
    "FrozenStructuralDomainV1",
    "frozen_structural_domain",
    "parse_generated_operation",
    "render_structural_generation_prompt",
    "render_structural_generation_request",
    "validate_structural_bounds",
]
