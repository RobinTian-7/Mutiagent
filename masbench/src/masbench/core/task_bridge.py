"""Generic bridge: a BenchmarkInstance -> an exp_graph TaskAdapter."""
# ============================================================
# 【模块导读】通用桥接：把一个 BenchmarkInstance 适配成 exp_graph 的 TaskAdapter
# （6 方法接口），并提供答案规范化 canonical_answer 与 GROUND_TRUTH_KEY 键。
# ============================================================

from __future__ import annotations

import json
from typing import Any

import masbench  # noqa: F401  (ensures exp_graph is importable)
from exp_graph.tasks.base import TaskAdapter

from masbench.core.instance import BenchmarkInstance
from masbench.core.task_view import (
    PRIVATE_SCORING_KEY,
    private_scoring_payload,
    public_task_view,
    task_ref,
)

# 中文：private scoring payload 里存放规范化 ground_truth（全局答案）的键。
#   自泄漏修复起，它只存在于 global_task[PRIVATE_SCORING_KEY] 之下，评分器经
#   private_answer_key/private_expected_outputs 读取；模型可见渲染一律走
#   public_task_view（显式白名单），物理上接触不到该载荷。
# Key for the canonical ground truth INSIDE the private scoring payload. Since
# the leakage fix it lives only under global_task[PRIVATE_SCORING_KEY]; scorers
# read it via private_answer_key/private_expected_outputs, and every
# model-visible rendering goes through public_task_view (explicit allowlist).
GROUND_TRUTH_KEY = "answer_key"


# 【职责】评分器读取规范化全局答案键（私有载荷缺失时返回 None）。
def private_answer_key(global_task: dict[str, Any]) -> Any:
    return private_scoring_payload(global_task).get(GROUND_TRUTH_KEY)


# 【职责】评分器读取逐 agent 期望输出（分段任务用；缺失返回空列表）。
def private_expected_outputs(global_task: dict[str, Any]) -> list[Any]:
    value = private_scoring_payload(global_task).get("expected_outputs")
    return list(value) if isinstance(value, list) else []


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _public_output_requirement(global_task: dict[str, Any]) -> str:
    """Extract the public Output section without consulting scoring data."""
    task_prompt = str(global_task.get("task_prompt") or "")
    collected: list[str] = []
    in_output = False
    for line in task_prompt.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not in_output:
            marker = "**output:**"
            if lowered.startswith(marker):
                in_output = True
                remainder = stripped[len(marker) :].strip()
                if remainder:
                    collected.append(remainder)
            elif lowered.startswith("output:"):
                in_output = True
                remainder = stripped[len("output:") :].strip()
                if remainder:
                    collected.append(remainder)
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            break
        if stripped:
            collected.append(stripped)
    if collected:
        return " ".join(collected)
    output_type = public_task_view(global_task).get("output_type", "unspecified")
    return (
        "Follow the answer shape requested by the public task statement. "
        f"The benchmark's public output_type is {_dumps(output_type)}."
    )


# 【职责】把答案规范化为用于分组与精确匹配的规范字符串形式。
# - 数字/列表/字典经规范 JSON 归一化；看起来是数字或 JSON 的字符串先解析，使 "9" 与 9、
#   "[3, 1]" 与 [3, 1] 比较相等。
# - Python 风格布尔（"True"/"False"）折叠为 JSON 布尔；空值/未知哨兵统一塌缩为 UNKNOWN。
def canonical_answer(value: Any) -> str:
    """Canonical string form of an answer for grouping and exact-match.

    Numbers, lists, and dicts are normalized via canonical JSON. Numeric or
    JSON-looking strings are parsed first so that "9" and 9, or "[3, 1]" and
    [3, 1], compare equal. Python-style booleans ("True"/"False") are folded to
    JSON booleans ("true"/"false"). Empty/unknown sentinels collapse to ``UNKNOWN``.
    """
    if value is None:
        return "UNKNOWN"
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() in {"UNKNOWN", "NONE", "NULL"}:
            return "UNKNOWN"
        if text.lower() in {"true", "false"}:
            return _dumps(text.lower() == "true")
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
        return _dumps(parsed)
    return _dumps(value)


# 【职责】把一个 BenchmarkInstance 包在 exp_graph 的 6 方法 TaskAdapter 接口后面。
class BenchmarkTaskAdapter(TaskAdapter):
    """Wrap one BenchmarkInstance behind the exp_graph 6-method interface."""

    def __init__(
        self,
        instance: BenchmarkInstance,
        *,
        information_goal: str = "sink",
    ) -> None:
        self.instance = instance
        self.task_name = f"benchmark::{instance.benchmark}::{instance.case_id}"
        # 中文：评测信息目标（sink/all_agents）：决定协议适配器选哪套提示词模板，
        #   并随评分/技能卡记录。默认 sink 与既有调用兼容。
        # Evaluation information goal (sink/all_agents): selects the protocol
        # adapter's prompt template set and rides along into scoring/skills.
        self.information_goal = information_goal

    # 【职责】把实例摊平为“全局任务”字典（交给引擎/规划器）。
    # - 答案类字段（answer_key/expected_outputs）只放进 PRIVATE_SCORING_KEY 私有载荷，
    #   与模型上下文物理隔离：模型可见渲染一律经 public_task_view 白名单。
    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        # 中文：接受 kwargs 只为匹配基类签名；Plan 1 中未使用。
        # kwargs are accepted to satisfy the base signature; unused in Plan 1.
        inst = self.instance
        # 中文：meta 进入运行侧任务字典前先剥掉答案与最优拓扑类字段——它们要么进
        #   私有载荷（expected_outputs），要么根本不该被携带（optimal_*）。
        # Strip answer/optimal-topology fields from meta before it enters the
        # run-side task dict: answers go to the private payload, optimal_* is
        # never carried at all.
        meta = {
            key: value
            for key, value in inst.meta.items()
            if key
            not in {
                "expected_outputs",
                "expected_output",
                "optimal_topology",
                "optimal_message_count",
                "theoretical_complexity",
            }
        }
        return {
            "task_name": self.task_name,
            "task_family": inst.benchmark,
            "benchmark": inst.benchmark,
            "case_id": inst.case_id,
            "task_ref": task_ref(inst.case_id),
            "case_name": inst.case_name,
            "n_agents": inst.n_agents,
            "shards": list(inst.shards),
            "task_prompt": inst.task_prompt,
            "meta": meta,
            "output_type": inst.meta.get("output_type", "scalar"),
            # 中文：区分分段任务（每 agent 各有答案）与单一共享答案任务；引擎据此决定
            #   按每个 agent 打分还是按投票答案打分。
            # Per-agent (segmented) vs single-shared-answer task. The engine reads
            # this to decide whether to grade per agent or by the voted answer.
            "segmented": inst.segmented,
            PRIVATE_SCORING_KEY: {
                GROUND_TRUTH_KEY: canonical_answer(inst.ground_truth),
                "expected_outputs": list(inst.meta.get("expected_outputs") or []),
                "output_type": inst.meta.get("output_type", "scalar"),
            },
        }

    # 【职责】把全局任务按 shard 切成每个 agent 的本地观测。
    # - benchmark 实例已预先分片，n_agents 必须等于 shards 数，否则报错（不可再切分）。
    def split_into_local_observations(
        self, global_task: dict[str, Any], n_agents: int
    ) -> list[dict[str, Any]]:
        shards = global_task["shards"]
        if n_agents != len(shards):
            raise ValueError(
                f"benchmark instance has {len(shards)} shards but n_agents={n_agents}; "
                "benchmark instances are pre-sharded and cannot be re-split"
            )
        # 中文：本地观测是模型可见的（进 LOCAL_OBSERVATION_JSON），故不携带可查表的
        #   case_id/含 case_id 的 task_name——用不可逆的 task_ref 代替。
        # Local observations are model-visible (LOCAL_OBSERVATION_JSON), so they
        # carry the opaque task_ref instead of the lookupable case_id (and a
        # task_name stripped of the case id).
        return [
            {
                "task_name": f"benchmark::{global_task['benchmark']}",
                "benchmark": global_task["benchmark"],
                "task_ref": global_task.get("task_ref")
                or task_ref(str(global_task.get("case_id", ""))),
                "agent_id": agent_id,
                "n_agents": n_agents,
                "input_shard": shards[agent_id],
            }
            for agent_id in range(n_agents)
        ]

    # 【职责】每个 agent 的初始本地求解：只有本地 shard、全局答案尚未可知。
    # - 返回一个合法的 “unknown” 信念状态（consensus_key=UNKNOWN）。
    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        agent_id = int(local_observation["agent_id"])
        shard = local_observation["input_shard"]
        size = len(shard) if isinstance(shard, (list, tuple, str, dict)) else 1
        return {
            "status": "unknown",
            "proposal": (
                f"Agent {agent_id} holds a private shard (size {size}). "
                "The global answer is not yet known."
            ),
            "consensus_key": "UNKNOWN",
            "support": [f"agent {agent_id} local shard size={size}"],
            "uncertainty": "Need information from other agents for the global answer.",
            "open_questions": ["What do other agents' shards contribute?"],
            "private_notes": "local shard only",
        }

    # 【职责】把共识键/提案规范化（复用 canonical_answer）。
    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        return canonical_answer(key_or_proposal)

    # 【职责】判定最终答案是否正确：规范化后与 ground_truth 精确匹配。
    # - ground truth 只从私有评分载荷读取（模型上下文物理隔离）。
    def evaluate_final_answer(
        self, global_task: dict[str, Any], final_key: str | None
    ) -> bool:
        return self.normalize_consensus_key(final_key) == private_answer_key(global_task)

    # 【职责】为某个 agent 渲染任务提示上下文（填入 agent_id 与其私有 shard）。
    # - 模板含 {input_shard} 占位则替换；否则在末尾附上该 agent 的私有 shard。
    def format_task_prompt_context(
        self, global_task: dict[str, Any], local_observation: dict[str, Any]
    ) -> str:
        agent_id = local_observation["agent_id"]
        shard_json = json.dumps(local_observation["input_shard"], ensure_ascii=True)
        template = global_task["task_prompt"] or f"Task: {global_task['case_name']}"
        had_shard_token = "{input_shard}" in template
        rendered = template.replace("{agent_id}", str(agent_id)).replace(
            "{input_shard}", shard_json
        )
        lines = [rendered, f"Total agents: {local_observation['n_agents']}"]
        if had_shard_token:
            lines.append(f"You are agent {agent_id}.")
        else:
            lines.append(f"You are agent {agent_id}. Your private shard: {shard_json}")
        return "\n".join(lines) + "\n"

    # PythonGen message_only_v2 deliberately uses two model-visible contexts.
    # Neither contains the legacy belief-state/action schema: communication
    # asks for content, while the runtime appends an immutable output contract
    # after the submit context.
    def format_python_communication_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        task_context = self.format_task_prompt_context(
            global_task, local_observation
        ).rstrip()
        return (
            "TASK_AND_PRIVATE_DATA:\n"
            f"{task_context}\n\n"
            "COMMUNICATION_PURPOSE:\n"
            "Preserve the task facts needed by another Agent or by your later "
            "final-answer call."
        )

    def format_python_submit_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        task_context = self.format_task_prompt_context(
            global_task, local_observation
        ).rstrip()
        requirement = _public_output_requirement(global_task)
        return (
            "TASK_AND_PRIVATE_DATA:\n"
            f"{task_context}\n\n"
            "PUBLIC_ANSWER_REQUIREMENT:\n"
            f"{requirement}"
        )

    # 【职责】给出把当前最佳全局答案写入 consensus_key 的规范化指令（返回提示串）。
    def format_consensus_key_instructions(self) -> str:
        return (
            "Put your current best GLOBAL answer in consensus_key as a compact "
            "canonical value (a JSON number, string, list, or object). Use "
            "UNKNOWN if you cannot yet determine the global answer."
        )

    # 【职责】给图生成规划器（皇帝）的简短任务简介。
    # - 提供真实任务语义（如“Global Max: ...”），取代 exp_graph 硬编码的 count_frequency
    #   说明；去占位符、压缩并截断以保持提示紧凑；plan_free_graph 以鸭子类型方式取用。
    def describe_task(self) -> str:
        """Short task brief for the graph-generating planner.

        Gives the emperor the ACTUAL task semantics (e.g. "Global Max: find the
        global maximum...") instead of exp_graph's hardcoded count_frequency
        notes. Placeholders are stripped and the text collapsed/truncated to keep
        the prompt compact. ``plan_free_graph`` picks this up duck-typed.
        """
        inst = self.instance
        prompt = (inst.task_prompt or "").replace("{agent_id}", "<id>").replace(
            "{input_shard}", "<shard>"
        )
        prompt = " ".join(prompt.split())
        brief = f"{inst.case_name}: {prompt}" if prompt else inst.case_name
        return brief[:400]

    # 【职责】构造裁决/提示词上下文：改用显式白名单的 public task view。
    # - 旧实现是"基类黑名单 + 去 shards"，嵌套字段（meta.expected_outputs）可绕过；
    #   白名单让新增字段默认私有，case_id 换成不可查表的 task_ref。
    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        """Allowlisted public view (nested-safe); replaces the old denylist."""
        return public_task_view(global_task)
