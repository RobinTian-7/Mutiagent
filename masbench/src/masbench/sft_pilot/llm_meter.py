"""At-most-once, equal-budget model-call boundary for the SFT pilot.

This module is imported only by an explicitly enabled pilot profile.  It never
persists prompts or responses: the SQLite control store receives commitments,
provider-authoritative usage, and bounded state transitions only.  A call that
crossed the transport boundary is never retried, even when its response was
not durably recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.llm.openai_client import OpenAIChatClient

from masbench.sft_pilot.schema import canonical_sha256
from masbench.sft_pilot.store import (
    PilotStateTransitionError,
    SingleWriterPilotStore,
)


class PilotCallBoundaryError(RuntimeError):
    """The bounded pilot call could not produce a reusable response."""


class PilotCallReplayBlocked(PilotCallBoundaryError):
    """The logical call slot was already consumed and cannot cross the SDK again."""


class PilotCallIndeterminate(PilotCallBoundaryError):
    """A call crossed the SDK boundary but did not reach a durable completion."""


# A content token consumes at least one input byte.  The pilot admits one user
# message and no system message; 256 additional token units conservatively
# cover the chat envelope and response-format framing.  This deliberately
# over-reserves weak-model calls so the SDK is never entered on the strength of
# the usual len(text)/4 heuristic.
PILOT_CHAT_ENVELOPE_TOKEN_ALLOWANCE = 256


@dataclass(frozen=True)
class PilotCallBudget:
    """Outcome-before reservation for one sequential call slot."""

    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.input_tokens, bool)
            or not isinstance(self.input_tokens, int)
            or self.input_tokens < 0
        ):
            raise ValueError("input_tokens must be a non-negative integer")
        if (
            isinstance(self.output_tokens, bool)
            or not isinstance(self.output_tokens, int)
            or self.output_tokens < 1
        ):
            raise ValueError("output_tokens must be a positive integer")


@dataclass(frozen=True)
class PilotTransportResult:
    """Ephemeral provider result; ``text`` is returned but never stored."""

    text: str
    input_tokens: int
    output_tokens: int
    provider_usage_known: bool


class PilotBoundedTransport(Protocol):
    """Transport that exposes an explicit completion cap and usage provenance."""

    def complete_bounded(
        self,
        prompt: str,
        *,
        model_name: str,
        temperature: float,
        json_mode: bool,
        max_completion_tokens: int,
    ) -> PilotTransportResult:
        ...


class OpenAIPilotTransport:
    """Real ``gpt-4o-mini`` transport with SDK retry disabled.

    Construction is intentionally explicit and profile-local; the default and
    fake QueenBee paths never instantiate this class or read an API key.
    """

    def __init__(
        self,
        *,
        max_completion_tokens: int,
        api_key_env: str | None = None,
    ) -> None:
        if isinstance(max_completion_tokens, bool) or max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be a positive integer")
        self._max_completion_tokens = max_completion_tokens
        self._client = OpenAIChatClient(
            api_key_env=api_key_env,
            max_retries=0,
            max_completion_tokens=max_completion_tokens,
            require_provider_usage=True,
        )

    def complete_bounded(
        self,
        prompt: str,
        *,
        model_name: str,
        temperature: float,
        json_mode: bool,
        max_completion_tokens: int,
    ) -> PilotTransportResult:
        if model_name != "gpt-4o-mini":
            raise ValueError("SFT pilot transport is frozen to gpt-4o-mini")
        if temperature != 0.0:
            raise ValueError("SFT pilot transport requires temperature 0")
        if max_completion_tokens != self._max_completion_tokens:
            raise ValueError("call completion cap differs from the frozen transport")
        response = self._client.complete(
            prompt,
            model_name=model_name,
            temperature=temperature,
            json_mode=json_mode,
        )
        # ``require_provider_usage=True`` makes missing provider usage raise
        # inside OpenAIChatClient before a response can reach this boundary.
        return PilotTransportResult(
            text=response.text,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            provider_usage_known=True,
        )


def _sha256_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _opaque(prefix: str, value: object) -> str:
    return f"{prefix}:{canonical_sha256(value)[:32]}"


class PilotMeteredLLMClient:
    """Sequential LLM client whose every SDK crossing is durably fenced.

    One instance belongs to one already-reserved execution lease.  It is not a
    resumable conversation object: after any started-call failure, all later
    calls are rejected and the execution must be classified indeterminate.
    """

    def __init__(
        self,
        *,
        store: SingleWriterPilotStore,
        transport: PilotBoundedTransport,
        logical_execution_key: str,
        call_budgets: tuple[PilotCallBudget, ...],
    ) -> None:
        if not call_budgets:
            raise ValueError("metered execution requires at least one call budget")
        lease = store.get_execution(logical_execution_key)
        if lease.state != "reserved":
            raise PilotStateTransitionError(
                "metered client requires a newly reserved execution lease"
            )
        if len(call_budgets) > lease.call_slots_reserved:
            raise ValueError("call budget count exceeds the execution reservation")
        if sum(item.input_tokens for item in call_budgets) > lease.input_tokens_reserved:
            raise ValueError("input call budgets exceed the execution reservation")
        if sum(item.output_tokens for item in call_budgets) > lease.output_tokens_reserved:
            raise ValueError("output call budgets exceed the execution reservation")
        self._store = store
        self._transport = transport
        self._logical_execution_key = logical_execution_key
        self._call_budgets = call_budgets
        self._next_slot = 0
        self._terminal_failure = False
        self._finalized = False

    @property
    def call_slots_consumed(self) -> int:
        return self._next_slot

    def _mark_indeterminate(
        self,
        call_key: str,
        call_request_sha256: str,
        *,
        result: PilotTransportResult | None = None,
    ) -> None:
        usage_known = bool(result is not None and result.provider_usage_known)
        payload = {
            "domain": "sft-pilot-call-indeterminate-v1",
            "call_key": call_key,
            "call_request_sha256": call_request_sha256,
            "provider_usage_known": usage_known,
            "input_tokens_used": (
                result.input_tokens if usage_known and result is not None else None
            ),
            "output_tokens_used": (
                result.output_tokens if usage_known and result is not None else None
            ),
        }
        try:
            self._store.mark_call_indeterminate(
                call_key,
                operation_id=_opaque("op-indeterminate", payload),
                operation_request_sha256=canonical_sha256(payload),
                provider_usage_known=payload["provider_usage_known"],
                input_tokens_used=payload["input_tokens_used"],
                output_tokens_used=payload["output_tokens_used"],
            )
        except Exception:
            # The durable row remains request_started; opening the store again
            # converts it to indeterminate.  Never attempt the transport again.
            pass

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        if self._terminal_failure or self._finalized:
            raise PilotCallReplayBlocked(
                "this execution is terminal and cannot invoke another call"
            )
        if model_name != self._store.protocol.model_name:
            raise ValueError("model differs from the frozen pilot protocol")
        resolved_temperature = 0.0 if temperature is None else temperature
        if resolved_temperature != self._store.protocol.temperature:
            raise ValueError("temperature differs from the frozen pilot protocol")
        if not isinstance(json_mode, bool):
            raise TypeError("json_mode must be boolean")
        if self._next_slot >= len(self._call_budgets):
            raise PilotCallBoundaryError("execution exhausted its frozen call slots")

        slot = self._next_slot
        budget = self._call_budgets[slot]
        if (
            self._store.protocol.input_admission_policy
            != "utf8_bytes_plus_fixed_allowance_v1"
            or self._store.protocol.input_envelope_token_allowance
            != PILOT_CHAT_ENVELOPE_TOKEN_ALLOWANCE
        ):
            raise PilotCallBoundaryError(
                "protocol names an unsupported input admission policy"
            )
        prompt_upper_bound = len(prompt.encode("utf-8")) + (
            self._store.protocol.input_envelope_token_allowance
        )
        if prompt_upper_bound > budget.input_tokens:
            raise PilotCallBoundaryError(
                "prompt exceeds the conservative pre-transport input bound"
            )
        prompt_sha256 = _sha256_bytes(prompt)
        call_request = {
            "domain": "sft-pilot-model-call-v1",
            "protocol_sha256": self._store.protocol.digest,
            "logical_execution_key": self._logical_execution_key,
            "call_slot": slot,
            "prompt_sha256": prompt_sha256,
            "model_name": model_name,
            "temperature": resolved_temperature,
            "json_mode": json_mode,
            "input_tokens_reserved": budget.input_tokens,
            "max_completion_tokens": budget.output_tokens,
        }
        call_request_sha256 = canonical_sha256(call_request)
        call_key = _opaque(
            "call",
            {
                "protocol_sha256": self._store.protocol.digest,
                "logical_execution_key": self._logical_execution_key,
                "call_slot": slot,
                "call_request_sha256": call_request_sha256,
            },
        )
        reserve_payload = {
            "domain": "sft-pilot-reserve-call-v1",
            "call_key": call_key,
            "call_request_sha256": call_request_sha256,
        }
        self._store.reserve_call(
            operation_id=_opaque("op-reserve-call", reserve_payload),
            operation_request_sha256=canonical_sha256(reserve_payload),
            call_key=call_key,
            logical_execution_key=self._logical_execution_key,
            call_slot=slot,
            call_request_sha256=call_request_sha256,
            input_tokens_reserved=budget.input_tokens,
            output_tokens_reserved=budget.output_tokens,
        )
        start_payload = {
            "domain": "sft-pilot-start-call-v1",
            "call_key": call_key,
            "call_request_sha256": call_request_sha256,
        }
        authorization = self._store.start_call(
            call_key,
            operation_id=_opaque("op-start-call", start_payload),
            operation_request_sha256=canonical_sha256(start_payload),
            call_request_sha256=call_request_sha256,
        )
        if not authorization.may_invoke_sdk:
            self._terminal_failure = True
            raise PilotCallReplayBlocked(
                "logical call slot already crossed the transport boundary"
            )

        # Consume the in-memory slot before transport work.  Catching an error
        # in caller code cannot make this same object retry the logical call.
        self._next_slot += 1
        try:
            result = self._transport.complete_bounded(
                prompt,
                model_name=model_name,
                temperature=resolved_temperature,
                json_mode=json_mode,
                max_completion_tokens=budget.output_tokens,
            )
        except Exception as exc:
            self._terminal_failure = True
            self._mark_indeterminate(call_key, call_request_sha256)
            raise PilotCallIndeterminate(
                "model transport outcome is indeterminate and will not be retried"
            ) from exc

        output_envelope_sha256 = canonical_sha256(
            {
                "domain": "sft-pilot-output-envelope-v1",
                "call_request_sha256": call_request_sha256,
                "response_text_sha256": _sha256_bytes(result.text),
                "provider_usage_known": result.provider_usage_known,
                "input_tokens_used": result.input_tokens,
                "output_tokens_used": result.output_tokens,
            }
        )
        completion_payload = {
            "domain": "sft-pilot-complete-call-v1",
            "call_key": call_key,
            "call_request_sha256": call_request_sha256,
            "output_envelope_sha256": output_envelope_sha256,
            "provider_usage_known": result.provider_usage_known,
            "input_tokens_used": result.input_tokens,
            "output_tokens_used": result.output_tokens,
        }
        try:
            self._store.complete_call(
                call_key,
                operation_id=_opaque("op-complete-call", completion_payload),
                operation_request_sha256=canonical_sha256(completion_payload),
                call_request_sha256=call_request_sha256,
                output_envelope_sha256=output_envelope_sha256,
                provider_usage_known=result.provider_usage_known,
                input_tokens_used=result.input_tokens,
                output_tokens_used=result.output_tokens,
            )
        except Exception as exc:
            self._terminal_failure = True
            self._mark_indeterminate(
                call_key,
                call_request_sha256,
                result=result,
            )
            raise PilotCallIndeterminate(
                "provider response did not reach a valid durable completion"
            ) from exc

        return LLMResponse(
            text=result.text,
            usage=LLMUsage(
                prompt_tokens=result.input_tokens,
                completion_tokens=result.output_tokens,
                model_calls=1,
            ),
        )

    def finalize_execution(self) -> None:
        """Commit the execution only after every frozen slot completed exactly once."""

        if self._terminal_failure:
            raise PilotCallIndeterminate(
                "an execution with an indeterminate call cannot complete"
            )
        if self._finalized:
            return
        if self._next_slot != len(self._call_budgets):
            raise PilotCallBoundaryError(
                "execution cannot complete before every frozen call slot"
            )
        payload = {
            "domain": "sft-pilot-complete-execution-v1",
            "logical_execution_key": self._logical_execution_key,
            "completed_call_slots": self._next_slot,
        }
        self._store.complete_execution(
            self._logical_execution_key,
            operation_id=_opaque("op-complete-execution", payload),
            operation_request_sha256=canonical_sha256(payload),
        )
        self._finalized = True


__all__ = [
    "OpenAIPilotTransport",
    "PilotBoundedTransport",
    "PilotCallBoundaryError",
    "PilotCallBudget",
    "PilotCallIndeterminate",
    "PilotCallReplayBlocked",
    "PilotMeteredLLMClient",
    "PilotTransportResult",
]
