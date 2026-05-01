"""JSON retry prompts for structured belief-state outputs."""

from __future__ import annotations


BELIEF_STATE_SCHEMA_HINT = """{
  "analysis": {
    "reasoning": "step-by-step reasoning leading to this belief",
    "key_observations": ["short observation"]
  },
  "status": "unknown | candidate | final",
  "proposal": "short answer proposal",
  "consensus_key": "task-specific grouping key | UNKNOWN | null",
  "support": ["short evidence item"],
  "uncertainty": "short uncertainty statement",
  "open_questions": ["short question"],
  "private_notes": "optional short private note",
  "structured_state": {}
}"""


def build_json_retry_prompt(
    *,
    original_prompt: str,
    invalid_response: str,
    error_message: str,
    attempt_idx: int,
) -> str:
    """Build a compact retry prompt after JSON parsing or validation fails."""
    return (
        "Your previous response could not be parsed as a valid belief_state JSON object.\n"
        f"Retry attempt: {attempt_idx}\n"
        "Return exactly one JSON object and nothing outside it. No markdown "
        "fences, no prose before or after. Reasoning belongs inside the "
        "`analysis` field of the JSON, not outside.\n"
        "Required schema:\n"
        f"{BELIEF_STATE_SCHEMA_HINT}\n"
        "Validation error:\n"
        f"{_truncate(error_message, 1200)}\n"
        "Invalid previous response:\n"
        f"{_truncate(invalid_response, 2000)}\n"
        "Original task prompt follows. Use it as the source of truth and regenerate "
        "a valid belief_state JSON object.\n"
        "ORIGINAL_PROMPT:\n"
        f"{original_prompt}"
    )


def _truncate(value: str, max_chars: int) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
