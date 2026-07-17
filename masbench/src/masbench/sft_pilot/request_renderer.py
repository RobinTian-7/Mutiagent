"""Sealed proposal-context request renderer for the v5 generation call.

The renderer is the only component allowed to turn a sealed
``ProposalGenerationContextV1`` + ``ProposalGenerationRequestV1`` pair into
provider-facing text.  It never sees a benchmark task, an answer, a raw
transcript, or another candidate's outcome: the prompt is built from a fixed
template over the exact locus, the typed value domain, the (mutate-only) safe
source scalar, and one bounded safe failure code.

Two commitments with different lifetimes come out of a render:

- ``request_envelope_sha256`` is derivable from *frozen* facts only (template,
  schema, policy, locus, scalar type, budget), so the experiment's execution
  schedule can pin it before any outcome exists.  The single-writer store
  enforces this pin at call reservation.
- ``prompt_sha256`` commits the exact runtime prompt bytes; it is recorded in
  the durable start-operation payload, never persisted as text.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Literal

from exp_graph.mas.factor_bank_v2 import (
    ProposalGenerationContextV1,
    ProposalGenerationRequestV1,
)

from masbench.sft_pilot.schema import canonical_sha256


REQUEST_RENDERER_VERSION = "sft_pilot_request_renderer_v1"

ScalarType = Literal["null", "bool", "int", "string"]

_MAX_SOURCE_SCALAR_BYTES = 512
_MAX_DOMAIN_DESCRIPTION_BYTES = 1_024
_MAX_RESPONSE_BYTES = 4_096
_MAX_GENERATED_STRING_BYTES = 256

# The fixed template is part of the frozen method; changing a single byte
# changes PROMPT_TEMPLATE_SHA256 and therefore every sealed schedule.
PROMPT_TEMPLATE_V1 = """You are configuring one field of a communication program.
Field path: {locator_path}
Field type: {scalar_type}
Legal domain: {value_domain}
{branch_block}
The previous configuration failed with code: {safe_failure_code}.
Propose one new value for exactly this field.
Reply with strict JSON of the form {{"value": <{scalar_type} value>}} and nothing else.
"""

_MUTATE_BLOCK = "Current value: {source_value_json}\n"
_FRESH_BLOCK = ""

PROMPT_TEMPLATE_SHA256 = hashlib.sha256(
    PROMPT_TEMPLATE_V1.encode("utf-8")
).hexdigest()

SCALAR_OUTPUT_SCHEMA_V1 = json.dumps(
    {
        "type": "object",
        "properties": {"value": {"type": ["null", "boolean", "integer", "string"]}},
        "required": ["value"],
        "additionalProperties": False,
    },
    sort_keys=True,
    separators=(",", ":"),
)

SCALAR_OUTPUT_SCHEMA_SHA256 = hashlib.sha256(
    SCALAR_OUTPUT_SCHEMA_V1.encode("utf-8")
).hexdigest()

GENERATION_POLICY_SHA256 = canonical_sha256(
    {
        "domain": "sft-pilot-generation-policy-v1",
        "renderer_version": REQUEST_RENDERER_VERSION,
        "prompt_template_sha256": PROMPT_TEMPLATE_SHA256,
        "scalar_output_schema_sha256": SCALAR_OUTPUT_SCHEMA_SHA256,
        "max_source_scalar_bytes": _MAX_SOURCE_SCALAR_BYTES,
        "max_domain_description_bytes": _MAX_DOMAIN_DESCRIPTION_BYTES,
        "max_response_bytes": _MAX_RESPONSE_BYTES,
        "max_generated_string_bytes": _MAX_GENERATED_STRING_BYTES,
    }
)

# Schedule pin for the renderer surface (code bytes are pinned separately by
# the runtime authority's code sources).
RENDERER_POLICY_SHA256 = canonical_sha256(
    {
        "domain": "sft-pilot-request-renderer-policy-v1",
        "renderer_version": REQUEST_RENDERER_VERSION,
        "generation_policy_sha256": GENERATION_POLICY_SHA256,
    }
)


class GeneratedScalarInvalid(ValueError):
    """The provider text is not one schema-valid typed scalar."""


@dataclass(frozen=True)
class SafeSourceScalar:
    """Host-resolved, answer-free source scalar surface (mutate branch only)."""

    scalar_type: ScalarType
    value: Any

    def __post_init__(self) -> None:
        _require_typed_scalar(self.value, scalar_type=self.scalar_type)


@dataclass(frozen=True)
class RenderedGenerationRequest:
    """Ephemeral render result; the prompt text is never persisted."""

    prompt_text: str
    prompt_sha256: str
    request_envelope_sha256: str
    prompt_template_sha256: str
    scalar_output_schema_sha256: str
    scalar_type: ScalarType
    json_mode: bool = True


def _require_typed_scalar(value: Any, *, scalar_type: str) -> Any:
    if scalar_type == "null":
        if value is not None:
            raise GeneratedScalarInvalid("null-typed slot requires null")
    elif scalar_type == "bool":
        if not isinstance(value, bool):
            raise GeneratedScalarInvalid("bool-typed slot requires a boolean")
    elif scalar_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise GeneratedScalarInvalid("int-typed slot requires an integer")
        if not math.isfinite(value):
            raise GeneratedScalarInvalid("int-typed slot requires a finite value")
    elif scalar_type == "string":
        if not isinstance(value, str):
            raise GeneratedScalarInvalid("string-typed slot requires a string")
        if len(value.encode("utf-8")) > _MAX_GENERATED_STRING_BYTES:
            raise GeneratedScalarInvalid("string scalar exceeds the frozen byte cap")
    else:
        raise GeneratedScalarInvalid(f"unknown scalar type {scalar_type!r}")
    return value


def generation_request_envelope_sha256(
    *,
    locator_path: str,
    scalar_type: str,
    generation_policy_sha256: str,
    prompt_template_sha256: str,
    scalar_output_schema_sha256: str,
    budget_sha256: str,
) -> str:
    """Outcome-before envelope over frozen request-shape facts only.

    Branch, failure code, and the (mutate) source value change the prompt
    bytes but deliberately not this envelope: the store pins the frozen shape
    at reservation while the Bank lease pins the exact full request digest.
    """

    return canonical_sha256(
        {
            "domain": "sft-pilot-rendered-generation-request-v1",
            "renderer_version": REQUEST_RENDERER_VERSION,
            "locator_path": locator_path,
            "scalar_type": scalar_type,
            "generation_policy_sha256": generation_policy_sha256,
            "prompt_template_sha256": prompt_template_sha256,
            "scalar_output_schema_sha256": scalar_output_schema_sha256,
            "budget_sha256": budget_sha256,
        }
    )


def render_generation_request(
    *,
    context: ProposalGenerationContextV1,
    request: ProposalGenerationRequestV1,
    scalar_type: ScalarType,
    value_domain_description: str,
    source_scalar: SafeSourceScalar | None,
) -> RenderedGenerationRequest:
    """Render the single admitted prompt for one sealed mutate/fresh request."""

    context = ProposalGenerationContextV1.model_validate(
        context.model_dump(mode="python")
    )
    request = ProposalGenerationRequestV1.model_validate(
        request.model_dump(mode="python")
    )
    if request.generation_context_sha256 != context.digest:
        raise ValueError("generation request does not bind the sealed context")
    if context.prompt_template_sha256 != PROMPT_TEMPLATE_SHA256:
        raise ValueError("sealed context names a foreign prompt template")
    if context.scalar_output_schema_sha256 != SCALAR_OUTPUT_SCHEMA_SHA256:
        raise ValueError("sealed context names a foreign output schema")
    if context.generation_policy_sha256 != GENERATION_POLICY_SHA256:
        raise ValueError("sealed context names a foreign generation policy")
    if request.branch == "fresh":
        if source_scalar is not None:
            raise ValueError("fresh generation must not see the source scalar")
    elif source_scalar is None:
        raise ValueError("mutate generation requires the safe source scalar")
    domain_bytes = value_domain_description.encode("utf-8")
    if not domain_bytes or len(domain_bytes) > _MAX_DOMAIN_DESCRIPTION_BYTES:
        raise ValueError("value domain description exceeds the frozen byte cap")
    if source_scalar is None:
        branch_block = _FRESH_BLOCK
    else:
        source_value_json = json.dumps(
            source_scalar.value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(source_value_json.encode("utf-8")) > _MAX_SOURCE_SCALAR_BYTES:
            raise ValueError("source scalar exceeds the frozen byte cap")
        branch_block = _MUTATE_BLOCK.format(source_value_json=source_value_json)
    prompt_text = PROMPT_TEMPLATE_V1.format(
        locator_path=request.locator_path,
        scalar_type=scalar_type,
        value_domain=value_domain_description,
        branch_block=branch_block,
        safe_failure_code=request.safe_failure_code,
    )
    envelope = generation_request_envelope_sha256(
        locator_path=request.locator_path,
        scalar_type=scalar_type,
        generation_policy_sha256=context.generation_policy_sha256,
        prompt_template_sha256=context.prompt_template_sha256,
        scalar_output_schema_sha256=context.scalar_output_schema_sha256,
        budget_sha256=context.budget_sha256,
    )
    return RenderedGenerationRequest(
        prompt_text=prompt_text,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        request_envelope_sha256=envelope,
        prompt_template_sha256=context.prompt_template_sha256,
        scalar_output_schema_sha256=context.scalar_output_schema_sha256,
        scalar_type=scalar_type,
    )


def parse_generated_scalar(text: str, *, scalar_type: ScalarType) -> Any:
    """Parse one strict ``{"value": ...}`` reply into a typed scalar.

    Any deviation raises :class:`GeneratedScalarInvalid`, which the caller
    must convert into an honest abort — never into a fabricated target.
    """

    if not isinstance(text, str) or not text.strip():
        raise GeneratedScalarInvalid("generation reply is empty")
    if len(text.encode("utf-8")) > _MAX_RESPONSE_BYTES:
        raise GeneratedScalarInvalid("generation reply exceeds the frozen byte cap")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeneratedScalarInvalid("generation reply is not strict JSON") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"value"}:
        raise GeneratedScalarInvalid(
            'generation reply must be exactly {"value": ...}'
        )
    return _require_typed_scalar(decoded["value"], scalar_type=scalar_type)


__all__ = [
    "GENERATION_POLICY_SHA256",
    "GeneratedScalarInvalid",
    "PROMPT_TEMPLATE_SHA256",
    "PROMPT_TEMPLATE_V1",
    "RENDERER_POLICY_SHA256",
    "REQUEST_RENDERER_VERSION",
    "RenderedGenerationRequest",
    "SCALAR_OUTPUT_SCHEMA_SHA256",
    "SCALAR_OUTPUT_SCHEMA_V1",
    "SafeSourceScalar",
    "generation_request_envelope_sha256",
    "parse_generated_scalar",
    "render_generation_request",
]
