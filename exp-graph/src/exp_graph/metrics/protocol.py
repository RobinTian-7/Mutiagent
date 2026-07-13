"""Generic, task-agnostic per-step protocol metrics."""
# ============================================================
# 【模块导读】协议执行的任务无关逐步指标。
# ProtocolRunner 每个阶段都会调用这里，把各 agent 的信念质量汇总成全局曲线。
# ============================================================

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Protocol

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState


# 【职责】单个 agent 在一个协议阶段的指标行：是否活跃、覆盖率、主指标、消息计数等。
class ProtocolAgentStepMetric(BaseModel):
    step_idx: int
    phase: str
    topology: str
    agent_id: int
    active_sender: bool
    active_receiver: bool
    coverage_ratio: float
    primary_metric: float
    exact_match: bool
    sent_count: int = 0
    received_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


# 【职责】一个协议阶段的全局汇总指标：覆盖率范围、平均主指标、投票集中度等。
class ProtocolGlobalStepMetric(BaseModel):
    step_idx: int
    phase: str
    topology: str
    mean_coverage: float
    min_coverage: float
    max_coverage: float
    mean_primary_metric: float
    best_primary_metric: float
    worst_primary_metric: float
    exact_match_agents: int
    full_coverage_agents: int
    vote_top_ratio: float


# 【职责】逐步指标构建器需要的最小适配器协议：算单 agent 指标并抽取答案键。
class _MetricAdapter(Protocol):
    def compute_protocol_agent_metrics(self, *, belief_state: Any, global_task: dict[str, Any], n_agents: int) -> dict[str, Any]: ...
    def extract_protocol_answer(self, belief_state: Any) -> Any: ...
    def protocol_answer_key(self, answer: Any) -> str: ...


# 【职责】从所有 agent 当前状态构建逐 agent 指标和全局汇总指标。
def build_protocol_step_metrics(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: _MetricAdapter,
    topology_name: str,
    step_idx: int,
    phase: str,
    send_counts: Counter[int],
    receive_counts: Counter[int],
) -> tuple[list[ProtocolAgentStepMetric], ProtocolGlobalStepMetric]:
    rows: list[ProtocolAgentStepMetric] = []
    for agent_id, state in enumerate(agent_states):
        # 中文：任务适配器负责定义“覆盖率/主指标/精确匹配”的任务语义。
        m = task_adapter.compute_protocol_agent_metrics(
            belief_state=state.belief_state, global_task=global_task, n_agents=len(agent_states),
        )
        sent = int(send_counts.get(agent_id, 0))
        recv = int(receive_counts.get(agent_id, 0))
        rows.append(ProtocolAgentStepMetric(
            step_idx=step_idx, phase=phase, topology=topology_name, agent_id=agent_id,
            active_sender=sent > 0, active_receiver=recv > 0,
            coverage_ratio=float(m.get("coverage_ratio", 0.0)),
            primary_metric=float(m.get("primary_metric", 0.0)),
            exact_match=bool(m.get("exact_match", False)),
            sent_count=sent, received_count=recv, extra=dict(m),
        ))
    # 中文：投票集中度只看规范答案键；它衡量本阶段 agent 之间是否已经收敛。
    keys = [task_adapter.protocol_answer_key(task_adapter.extract_protocol_answer(s.belief_state)) for s in agent_states]
    top = max(Counter(keys).values()) / max(1, len(keys)) if keys else 0.0
    g = ProtocolGlobalStepMetric(
        step_idx=step_idx, phase=phase, topology=topology_name,
        mean_coverage=statistics.fmean(r.coverage_ratio for r in rows),
        min_coverage=min(r.coverage_ratio for r in rows),
        max_coverage=max(r.coverage_ratio for r in rows),
        mean_primary_metric=statistics.fmean(r.primary_metric for r in rows),
        best_primary_metric=max(r.primary_metric for r in rows),
        worst_primary_metric=min(r.primary_metric for r in rows),
        exact_match_agents=sum(1 for r in rows if r.exact_match),
        full_coverage_agents=sum(1 for r in rows if r.coverage_ratio >= 1.0),
        vote_top_ratio=top,
    )
    return rows, g
