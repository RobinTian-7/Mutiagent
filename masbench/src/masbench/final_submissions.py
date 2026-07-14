"""Runtime-owned final-answer barrier for strict all-agent experiments."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from exp_graph.llm.base import LLMClient
from exp_graph.runner.protocol import ProtocolActionError


@dataclass(frozen=True)
class FinalSubmissionBatch:
    """Parsed answers and metering for one synchronized submission barrier."""

    answers: dict[int, Any]
    attempts_by_agent: dict[int, int]
    answer_sha256_by_agent: dict[int, str]
    model_calls: int
    prompt_tokens: int
    completion_tokens: int

    def audit_dict(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "agent_ids": sorted(self.answers),
            "all_submitted": True,
            "attempts_by_agent": {
                str(key): value
                for key, value in sorted(self.attempts_by_agent.items())
            },
            "answer_sha256_by_agent": {
                str(key): value
                for key, value in sorted(self.answer_sha256_by_agent.items())
            },
            "model_calls": self.model_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "parser": "json.loads_whole_response",
        }


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


def is_valid_submission_answer(answer: Any) -> bool:
    """Return whether an already-parsed value counts as a real submission."""

    if answer is None:
        return False
    if isinstance(answer, str) and answer.strip().lower() in {
        "",
        "null",
        "none",
        "unknown",
    }:
        return False
    return True


def _parse_nonempty_json(text: str) -> Any:
    answer = json.loads(text.strip(), parse_constant=_reject_nonfinite)
    if not is_valid_submission_answer(answer):
        raise ValueError("empty or unknown text is not a submitted answer")
    return answer


def _answer_sha256(answer: Any) -> str:
    payload = json.dumps(
        answer,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_final_submission_barrier(
    *,
    prompts: dict[int, str],
    llm_client: LLMClient,
    model_name: str,
    temperature: float | None,
    max_parallel_agents: int,
    retries: int,
) -> FinalSubmissionBatch:
    """Require every listed agent to return one non-empty JSON answer.

    The barrier never invents or repairs an answer on the host. A malformed or
    empty response receives a bounded format-only retry; exhausting that budget
    is an algorithm failure. Provider exceptions propagate unchanged.
    """

    if not prompts:
        return FinalSubmissionBatch({}, {}, {}, 0, 0, 0)
    max_attempts = max(1, int(retries) + 1)

    def submit(agent_id: int, prompt: str) -> tuple[int, Any, int, int, int, int]:
        prompt_tokens = 0
        completion_tokens = 0
        model_calls = 0
        current_prompt = prompt
        last_error = "unknown format error"
        for attempt in range(1, max_attempts + 1):
            response = llm_client.complete(
                current_prompt,
                model_name=model_name,
                temperature=temperature,
                json_mode=False,
            )
            prompt_tokens += int(response.usage.prompt_tokens)
            completion_tokens += int(response.usage.completion_tokens)
            model_calls += int(response.usage.model_calls)
            try:
                answer = _parse_nonempty_json(response.text)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                current_prompt = (
                    prompt
                    + "\n\nFORMAT_RETRY:\n"
                    + "Your prior response was not one complete non-empty JSON "
                    + f"value ({last_error}). Return only the answer JSON value."
                )
                continue
            return (
                agent_id,
                answer,
                attempt,
                model_calls,
                prompt_tokens,
                completion_tokens,
            )
        raise ProtocolActionError(
            f"agent {agent_id} failed the required final submission barrier "
            f"after {max_attempts} attempt(s): {last_error}"
        )

    answers: dict[int, Any] = {}
    attempts: dict[int, int] = {}
    model_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    workers = min(max(1, int(max_parallel_agents)), len(prompts))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(submit, agent_id, prompt): agent_id
            for agent_id, prompt in sorted(prompts.items())
        }
        for future in as_completed(futures):
            (
                agent_id,
                answer,
                attempt_count,
                calls,
                prompt_count,
                completion_count,
            ) = future.result()
            answers[agent_id] = answer
            attempts[agent_id] = attempt_count
            model_calls += calls
            prompt_tokens += prompt_count
            completion_tokens += completion_count

    expected_ids = sorted(prompts)
    if sorted(answers) != expected_ids:
        raise ProtocolActionError(
            "required final submission barrier did not return every agent"
        )
    return FinalSubmissionBatch(
        answers=answers,
        attempts_by_agent=attempts,
        answer_sha256_by_agent={
            agent_id: _answer_sha256(answer)
            for agent_id, answer in answers.items()
        },
        model_calls=model_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
