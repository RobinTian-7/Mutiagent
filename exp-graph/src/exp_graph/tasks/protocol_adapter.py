"""Task-agnostic protocol adapter interface for ProtocolRunner."""
# ============================================================
# 【模块导读】ProtocolRunner 使用的任务无关协议适配器接口。
# SiloProtocolAdapter 实现这里的钩子，让通用时序 DAG 执行器无需知道 Silo 任务细节。
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from typing import TYPE_CHECKING, Any

from exp_graph.agents.schemas import AgentState, BeliefState
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.base import TaskAdapter

# 中文：默认方法内部再懒加载这些类型，避免形成循环导入：
# count_frequency -> protocol_adapter -> aggregator/metrics __init__ -> cf_* -> count_frequency。
# Imported lazily inside the default methods to avoid an import cycle:
# count_frequency -> protocol_adapter -> aggregator/metrics __init__ -> cf_* -> count_frequency.
if TYPE_CHECKING:
    from exp_graph.aggregator.protocol_final import ProtocolFinalResult
    from exp_graph.metrics.protocol import (
        ProtocolAgentStepMetric,
        ProtocolGlobalStepMetric,
    )


# 【职责】协议执行器驱动的核心接口：把每个任务自己的信念生命周期、答案抽取、评分与指标暴露出来。
class ProtocolTaskAdapter(TaskAdapter, ABC):
    """Adapter that ProtocolRunner drives. CF and generic tasks both implement this.

    The 7 belief methods below carry the per-agent protocol semantics; the
    finalize/step-metric/answer methods let the runner stay task-agnostic.
    """

    # 中文：逐 agent 的协议信念生命周期（CountFrequencyTaskAdapter 原本已有这组方法）。
    # --- per-agent protocol belief lifecycle (already on CountFrequencyTaskAdapter) ---
    @abstractmethod
    # 【职责】用本地观测构造协议初始信念；Silo 中通常是局部候选或 UNKNOWN。
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState: ...

    @abstractmethod
    # 【职责】格式化 LLM 初始化提示词，让 agent 从本地分片生成初始信念。
    def format_protocol_init_prompt(
        self, *, global_task: dict[str, Any], local_observation: dict[str, Any]
    ) -> str: ...

    @abstractmethod
    # 【职责】校验并规范化 LLM 生成的初始信念，保证状态字段可被执行器继续使用。
    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState: ...

    @abstractmethod
    # 【职责】确定性地把收件箱信息合并进旧信念；LLM 合并模式也会用它作基准/兜底。
    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState: ...

    @abstractmethod
    # 【职责】格式化 LLM 合并提示词，把旧信念、邻居消息和确定性基准一起交给模型。
    def format_protocol_merge_prompt(
        self,
        *,
        merge_mode: str,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        deterministic_belief: BeliefState | None = None,
    ) -> str: ...

    @abstractmethod
    # 【职责】把 LLM 合并结果与经过验证的确定性结果合成最终落地信念。
    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState: ...

    @abstractmethod
    # 【职责】校验每轮合并后的信念，统一 consensus_key/status/structured_state 等任务字段。
    def validate_protocol_belief_state(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> BeliefState: ...

    # 中文：答案抽取与评分钩子（通用终局聚合和逐步指标会调用）。
    # --- answer extraction / scoring (used by generic aggregation + metrics) ---
    @abstractmethod
    # 【职责】从 BeliefState 取出任务答案对象。
    def extract_protocol_answer(self, belief_state: BeliefState) -> Any: ...

    @abstractmethod
    # 【职责】把答案规范化为可投票/分组的稳定字符串键。
    def protocol_answer_key(self, answer: Any) -> str: ...

    @abstractmethod
    # 【职责】评分单个最终答案，至少返回 primary_metric 与 exact_match。
    def score_protocol_answer(
        self, answer: Any, global_task: dict[str, Any]
    ) -> dict[str, Any]:
        """Return at least {'primary_metric': float, 'exact_match': bool}."""
        ...

    @abstractmethod
    # 【职责】计算单个 agent 当前信念的覆盖率、主指标与精确匹配等逐步指标。
    def compute_protocol_agent_metrics(
        self, *, belief_state: BeliefState, global_task: dict[str, Any], n_agents: int
    ) -> dict[str, Any]:
        """Return at least {'coverage_ratio': float, 'primary_metric': float, 'exact_match': bool}."""
        ...

    # 中文：答案持有者选择、终局聚合与逐步指标的通用默认实现（CF 可覆写 finalize/step）。
    # --- holder selection + finalize/metrics: generic defaults (CF overrides finalize/step) ---
    # 【职责】返回哪些 agent 的答案参与最终投票；默认全体参与。
    def answer_holders(
        self, *, topology_name: str, n_agents: int, star_center: int
    ) -> list[int]:
        return list(range(n_agents))

    # 【职责】默认终局聚合：取答案持有者，交给通用投票聚合器。
    def finalize_protocol(
        self,
        *,
        agent_states: list[AgentState],
        global_task: dict[str, Any],
        topology_name: str,
        star_center: int = 0,
        average_include_min_coverage: float = 1.0,
        selected_primary: str = "topology_default",
        answer_agent_ids_override: list[int] | None = None,
    ) -> ProtocolFinalResult:
        from exp_graph.aggregator.protocol_final import run_protocol_vote_aggregation

        ids = answer_agent_ids_override or self.answer_holders(
            topology_name=topology_name,
            n_agents=len(agent_states),
            star_center=star_center,
        )
        return run_protocol_vote_aggregation(
            agent_states=agent_states,
            global_task=global_task,
            task_adapter=self,
            answer_agent_ids=ids,
        )

    # 【职责】默认逐步指标：委托给任务无关指标构建器。
    def build_protocol_step_metrics(
        self,
        *,
        agent_states: list[AgentState],
        global_task: dict[str, Any],
        topology_name: str,
        step_idx: int,
        phase: str,
        send_counts: Counter[int],
        receive_counts: Counter[int],
        average_include_min_coverage: float = 1.0,
    ) -> tuple[list[ProtocolAgentStepMetric], ProtocolGlobalStepMetric]:
        from exp_graph.metrics.protocol import (
            build_protocol_step_metrics as _build_protocol_step_metrics,
        )

        return _build_protocol_step_metrics(
            agent_states=agent_states,
            global_task=global_task,
            task_adapter=self,
            topology_name=topology_name,
            step_idx=step_idx,
            phase=phase,
            send_counts=send_counts,
            receive_counts=receive_counts,
        )
