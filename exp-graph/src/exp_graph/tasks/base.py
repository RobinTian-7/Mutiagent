"""Task adapter interface.

Task-specific logic belongs behind this interface so the multi-agent runtime
can test communication topology effects without knowing task semantics.
"""
# ============================================================
# 【模块导读】任务适配器接口。
# 任务特有的逻辑都应封装在该接口之后，使多智能体运行时
# 无需了解任务语义即可检验通信拓扑的效应。
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# 【职责】可插拔的任务基接口（六方法）：建全局任务/切分片/本地初解/共识键归一化/终评/提示词上下文。
class TaskAdapter(ABC):
    """Pluggable task interface."""

    # 任务名标识
    task_name: str

    # 【职责】构建或规范化所有 agent 共享的全局任务。
    @abstractmethod
    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        """Build or normalize a global task shared by all agents."""
        ...

    # 【职责】把共享任务切分为每个 agent 的本地观测（即各自持有的数据分片）。
    @abstractmethod
    def split_into_local_observations(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> list[dict[str, Any]]:
        """Split the shared task into per-agent local observations."""
        ...

    # 【职责】仅凭本地观测得出初始信念状态（dict 形式）。
    @abstractmethod
    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        """Return an initial belief_state from only local observation."""
        ...

    # 【职责】规范化任务特定的答案键（共识键），用于分组与投票。
    @abstractmethod
    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        """Normalize task-specific answer keys for grouping and voting."""
        ...

    # 【职责】评估最终键是否解决了全局任务。
    @abstractmethod
    def evaluate_final_answer(
        self,
        global_task: dict[str, Any],
        final_key: str | None,
    ) -> bool:
        """Evaluate whether the final key solves the global task."""
        ...

    # 【职责】为 agent 提示词格式化任务上下文。
    @abstractmethod
    def format_task_prompt_context(
        self,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        """Format task context for an agent prompt."""
        ...

    # 【职责】返回求解提示词中的共识键填写指引（默认通用文案，任务可覆写）。
    def format_consensus_key_instructions(self) -> str:
        """Return task-specific consensus-key guidance for solver prompts."""
        return (
            "consensus_key should be a short task-specific key suitable for "
            "cheap grouping. Use UNKNOWN when the current evidence is insufficient."
        )

    # 【职责】返回允许进入最终 LLM 裁决的任务上下文。
    # - 该上下文绝不能包含标签或真值答案；默认按黑名单剔除常见答案字段。
    # - 任务字典含私有评测字段时，具体适配器应覆写本方法。
    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        """Return the task context allowed in final LLM adjudication.

        This context must not include labels or ground-truth answers. Concrete
        adapters should override this when the task dictionary contains private
        evaluation fields.
        """
        blocked_keys = {
            "answer",
            "answer_index",
            "answer_key",
            "expected_answer",
            "ground_truth",
            "label",
        }
        return {
            key: value
            for key, value in global_task.items()
            if key not in blocked_keys
        }
