from __future__ import annotations

import json
import threading

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.runner.protocol import ProtocolActionError

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.engine import run_fixed_protocol
from masbench.final_submissions import (
    is_valid_submission_answer,
    run_final_submission_barrier,
)


class _SubmissionClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}

    def complete(self, prompt, model_name, temperature=None, json_mode=True):
        del model_name, temperature, json_mode
        key = "agent_0" if "agent_0" in prompt else "agent_1"
        with self._lock:
            self._calls[key] = self._calls.get(key, 0) + 1
            attempt = self._calls[key]
        if key == "agent_0":
            text = "3"
        else:
            text = "not json" if attempt == 1 else "[1,2]"
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=10,
                completion_tokens=2,
                model_calls=1,
            ),
        )


def test_final_submission_barrier_retries_format_and_requires_every_agent() -> None:
    result = run_final_submission_barrier(
        prompts={0: "agent_0", 1: "agent_1"},
        llm_client=_SubmissionClient(),
        model_name="fake",
        temperature=0.0,
        max_parallel_agents=2,
        retries=1,
    )

    assert result.answers == {0: 3, 1: [1, 2]}
    assert result.attempts_by_agent == {0: 1, 1: 2}
    assert result.model_calls == 3
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 6
    assert result.audit_dict()["all_submitted"] is True


class _NullClient:
    def complete(self, prompt, model_name, temperature=None, json_mode=True):
        del prompt, model_name, temperature, json_mode
        return LLMResponse(text="null", usage=LLMUsage())


def test_final_submission_barrier_never_accepts_null() -> None:
    with pytest.raises(ProtocolActionError, match="failed the required"):
        run_final_submission_barrier(
            prompts={0: "submit"},
            llm_client=_NullClient(),
            model_name="fake",
            temperature=0.0,
            max_parallel_agents=1,
            retries=1,
        )


@pytest.mark.parametrize("answer", [None, "", "null", "NONE", " unknown "])
def test_invalid_submission_answers_are_not_complete(answer) -> None:
    assert is_valid_submission_answer(answer) is False


@pytest.mark.parametrize("answer", [0, False, [], {}, "accepted"])
def test_json_values_are_valid_submission_answers(answer) -> None:
    assert is_valid_submission_answer(answer) is True


class _FixedSubmitClient:
    def complete(self, prompt, model_name, temperature=None, json_mode=True):
        del model_name, temperature, json_mode
        answer = [1] if "You are agent 0." in prompt else [2]
        return LLMResponse(
            text=json.dumps(answer),
            usage=LLMUsage(prompt_tokens=10, completion_tokens=2),
        )


def test_fixed_protocol_strict_mode_records_every_final_submission() -> None:
    instance = BenchmarkInstance(
        benchmark="silo_bench",
        case_id="II-99",
        case_name="Synthetic Segments",
        n_agents=2,
        shards=[[10], [20]],
        ground_truth=[1],
        task_prompt="Return your assigned segment.\nYour data: {input_shard}\n",
        meta={
            "num_agents": 2,
            "is_segmented": True,
            "output_type": "distributed",
            "expected_outputs": [[1], [2]],
        },
    )
    score = run_fixed_protocol(
        instance,
        RunConfig(
            silo_eval_mode="all_agents",
            n_agents=2,
            init_mode="deterministic",
            merge_mode="deterministic",
            model_name="scripted",
            require_all_submissions=True,
            max_parallel_agents=2,
        ),
        topology="chain",
        llm_client=_FixedSubmitClient(),
    )

    assert score.success is True
    assert score.extra["all_submitted"] is True
    assert score.extra["runtime_final_submission"]["agent_ids"] == [0, 1]
    assert [row["answer"] for row in score.extra["per_agent_submissions"]] == [
        [1],
        [2],
    ]
