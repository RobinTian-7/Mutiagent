"""Benchmark-aware deterministic fake LLM for offline smoke runs.

Unlike exp_graph's FakeLLMClient (hardwired to CF / array-search), this client
never crashes on arbitrary benchmark tasks. For associative-reduce cases it
computes the reduced answer from the local shard plus neighbor consensus keys so
that offline runs can converge; for everything else it returns a valid
"unknown" belief (the pipeline still runs end-to-end, just without a correct
answer offline).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import masbench  # noqa: F401
from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens

# case_id -> reducer over a flat list of numbers
_REDUCERS: dict[str, Callable[[list[float]], Any]] = {
    "I-01": max,  # Global Max
}


class BenchmarkFakeLLMClient:
    """Deterministic, task-tolerant fake client."""

    def complete(
        self, prompt: str, model_name: str, temperature: float | None = None
    ) -> LLMResponse:
        local = _block(prompt, "LOCAL_OBSERVATION_JSON:", "OLD_BELIEF_STATE_JSON:")
        old = _block(prompt, "OLD_BELIEF_STATE_JSON:", "INBOX_JSON:")
        inbox = _block(prompt, "INBOX_JSON:", None)
        belief = _solve(str(local.get("case_id", "")), local, old, inbox)
        text = json.dumps(belief)
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
            ),
        )


def _block(prompt: str, start: str, end: str | None) -> Any:
    begin = prompt.index(start) + len(start)
    raw = prompt[begin:].strip() if end is None else prompt[begin : prompt.index(end, begin)].strip()
    return json.loads(raw)


def _as_number(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_numbers(local: dict, old: dict, inbox: list) -> list[float]:
    numbers: list[float] = []
    shard = local.get("input_shard")
    if isinstance(shard, list):
        numbers += [n for n in (_as_number(v) for v in shard) if n is not None]
    for source in [old, *inbox]:
        if isinstance(source, dict):
            key = source.get("consensus_key")
            n = _as_number(key)
            if n is not None:
                numbers.append(n)
    return numbers


def _solve(case_id: str, local: dict, old: dict, inbox: list) -> dict:
    reducer = _REDUCERS.get(case_id)
    if reducer is not None:
        numbers = _candidate_numbers(local, old, inbox)
        if numbers:
            result = reducer(numbers)
            if float(result).is_integer():
                result = int(result)
            return {
                "status": "candidate",
                "proposal": f"Reduced answer over visible data is {result}.",
                "consensus_key": str(result),
                "support": [f"reduced {len(numbers)} visible values"],
                "uncertainty": "",
                "open_questions": [],
                "private_notes": "deterministic reduce over local shard + neighbor keys",
            }
    return {
        "status": "unknown",
        "proposal": "Offline fake client cannot solve this task type.",
        "consensus_key": "UNKNOWN",
        "support": [f"case_id={case_id}"],
        "uncertainty": "No deterministic offline solver for this task.",
        "open_questions": ["Use a real LLM provider to attempt this task."],
        "private_notes": "fake fallback",
    }
