"""JSON parsing helpers for belief-state outputs."""

from __future__ import annotations

import json
import re

from exp_graph.agents.schemas import BeliefState

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - exercised only without optional package
    repair_json = None


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        parsed = _loads_with_repair(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    candidate = stripped[start : end + 1]
    parsed = _loads_with_repair(candidate)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM response JSON root must be an object: {text[:200]}")
    return parsed


def _loads_with_repair(raw: str):
    """Parse JSON, using json-repair only after syntax parsing fails."""
    last_error: json.JSONDecodeError | None = None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        last_error = exc

    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        last_error = exc

    if repair_json is not None:
        try:
            return repair_json(raw, return_objects=True)
        except Exception:
            pass

    assert last_error is not None
    raise last_error


def parse_belief_state(text: str) -> BeliefState:
    """Parse an LLM response into a BeliefState."""
    return BeliefState(**extract_json_object(text))
