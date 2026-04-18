"""JSON parsing helpers for belief-state outputs."""

from __future__ import annotations

import json
import re

from exp_graph.agents.schemas import BeliefState


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    return json.loads(stripped[start : end + 1])


def parse_belief_state(text: str) -> BeliefState:
    """Parse an LLM response into a BeliefState."""
    return BeliefState(**extract_json_object(text))
