"""Benchmark-aware deterministic fake LLM for offline smoke runs.

Unlike exp_graph's FakeLLMClient (hardwired to CF / array-search), this client
never crashes on arbitrary benchmark tasks. For associative-reduce cases it
computes the reduced answer from the local shard plus neighbor consensus keys so
that offline runs can converge; for everything else it returns a valid
"unknown" belief (the pipeline still runs end-to-end, just without a correct
answer offline).
"""
# ============================================================
# 【模块导读】面向 benchmark 的确定性 fake LLM，用于离线冒烟运行。
# 不同于 exp_graph 写死 CF/array-search 的 FakeLLMClient，本客户端对任意 benchmark
# 任务都不崩溃：可结合归约的 case 会从本地 shard + 邻居共识键算出归约答案（让离线运行
# 能收敛）；其余一律返回合法的 “unknown” 信念（流水线仍端到端跑通，只是离线无正确答案）。
# ============================================================

from __future__ import annotations

import json
from typing import Any, Callable

import masbench  # noqa: F401
from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens

from masbench.core.task_view import task_ref

# 中文：case_id -> 对一列扁平数字的归约函数（如 I-01 = Global Max，取最大值）。
# case_id -> reducer over a flat list of numbers
_REDUCERS: dict[str, Callable[[list[float]], Any]] = {
    "I-01": max,  # Global Max
}

# 中文：泄漏修复后模型可见上下文只带不可查表的 task_ref；fake 客户端是宿主侧的确定性
#   模拟器，按 task_ref 反查同一张归约表（与按 case_id 查表同一诚实度，不多知道任何答案）。
# After the leakage fix, model-visible context carries only the opaque
# task_ref. The fake client is a HOST-side deterministic simulator, so mapping
# task_ref back to the same reducer table adds no answer knowledge.
_REDUCERS_BY_REF: dict[str, Callable[[list[float]], Any]] = {
    task_ref(case_id): fn for case_id, fn in _REDUCERS.items()
}


# 【职责】确定性、对任务宽容的 fake 客户端。
class BenchmarkFakeLLMClient:
    """Deterministic, task-tolerant fake client."""

    # 【职责】解析提示中的 LOCAL/OLD_BELIEF/INBOX 三段，求解并返回信念状态 JSON。
    def complete(
        self, prompt: str, model_name: str, temperature: float | None = None
    ) -> LLMResponse:
        # 中文：论文 P2P/Broadcast/SFS 基线使用工具动作 JSON，而不是 BeliefState。
        # 离线 fake 只验证协议循环能完整运行：前几轮查询可见环境并等待，最后一轮
        # 提交 null（诚实失败），绝不伪造 benchmark 成功。
        # The paper P2P/Broadcast/SFS baselines use tool-action JSON rather than
        # BeliefState.  Offline fake only exercises that loop: inspect/wait on
        # earlier rounds and submit null on the final round (an honest failure).
        if "SILO_PROTOCOL_ACTION_JSON:" in prompt:
            text = _paper_protocol_action(prompt)
            return LLMResponse(
                text=text,
                usage=LLMUsage(
                    prompt_tokens=estimate_tokens(prompt),
                    completion_tokens=estimate_tokens(text),
                ),
            )
        local = _block(prompt, "LOCAL_OBSERVATION_JSON:", "OLD_BELIEF_STATE_JSON:")
        old = _block(prompt, "OLD_BELIEF_STATE_JSON:", "INBOX_JSON:")
        inbox = _block(prompt, "INBOX_JSON:", None)
        # 中文：模型可见上下文带 task_ref（不可查表摘要）；旧合成夹具可能仍传 case_id，
        #   两者都接受。
        # Model-visible context carries task_ref; legacy synthetic fixtures may
        # still pass case_id -- accept either.
        belief = _solve(
            str(local.get("case_id", "") or local.get("task_ref", "")),
            local,
            old,
            inbox,
        )
        text = json.dumps(belief)
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
            ),
        )


def _paper_protocol_action(prompt: str) -> str:
    """Deterministic, deliberately non-solving actions for offline paper smokes."""
    final_round = '"final_round": true' in prompt.lower()
    if final_round:
        actions = [{"tool": "submit_result", "parameters": {"answer": None}}]
    elif "PAPER_PROTOCOL_NAME: sfs" in prompt:
        actions = [
            {"tool": "list_files", "parameters": {}},
            {"tool": "wait", "parameters": {}},
        ]
    else:
        actions = [
            {"tool": "receive_messages", "parameters": {}},
            {"tool": "wait", "parameters": {}},
        ]
    return json.dumps({"actions": actions})


# 【职责】从提示里截取 start 与 end 标记之间的 JSON 片段并解析（end=None 取到末尾）。
def _block(prompt: str, start: str, end: str | None) -> Any:
    begin = prompt.index(start) + len(start)
    raw = prompt[begin:].strip() if end is None else prompt[begin : prompt.index(end, begin)].strip()
    return json.loads(raw)


# 【职责】尽力把值转为 float；布尔视为非数字返回 None（避免把 True 当作 1）。
def _as_number(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# 【职责】汇集可见的候选数字：本地 shard 里的数 + old/inbox 里各邻居的 consensus_key。
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


# 【职责】按 case_id 或 task_ref 选归约器求解：能归约则算出答案，否则返回 unknown 信念。
def _solve(case_id: str, local: dict, old: dict, inbox: list) -> dict:
    reducer = _REDUCERS.get(case_id) or _REDUCERS_BY_REF.get(case_id)
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
