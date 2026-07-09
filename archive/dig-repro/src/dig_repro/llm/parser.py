"""JSON parsing helpers."""

from __future__ import annotations

import json


def extract_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("No JSON object found.")
    return json.loads(text[start : end + 1])

