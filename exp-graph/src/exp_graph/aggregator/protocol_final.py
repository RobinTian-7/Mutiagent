"""Generic, task-agnostic final aggregation (vote-only) for protocol runs."""
# ============================================================
# 【模块导读】协议运行的任务无关终局投票聚合。
# Silo 的最终答案会先由适配器抽取/规范化，再在这里按多数共识键选出并评分。
# ============================================================

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState


# 【职责】保存最终投票结果：选中的答案键、真实答案对象、评分和支持它的 agent。
class ProtocolFinalResult(BaseModel):
    """Task-agnostic final aggregation result."""

    final_key: str
    final_answer: Any = None
    selected_primary: str = "vote"
    aggregation_method: str = "vote"
    # 中文：任务定义的主指标；对成功率类任务（如 Silo exact-match）越高越好。
    primary_metric: float = 0.0          # task-defined; higher-is-better for success-rate tasks
    exact_match: bool = False
    supporting_agents: list[int] = Field(default_factory=list)
    answer_agent_ids: list[int] = Field(default_factory=list)
    top_ratio: float | None = None


# 【职责】投票聚合器需要的最小适配器协议：抽答案、取规范键、给答案评分。
class _VoteAdapter(Protocol):
    def extract_protocol_answer(self, belief_state: Any) -> Any: ...
    def protocol_answer_key(self, answer: Any) -> str: ...
    def score_protocol_answer(self, answer: Any, global_task: dict[str, Any]) -> dict[str, Any]: ...


# 【职责】按规范答案键分组投票，选多数派答案并交回任务适配器评分。
def run_protocol_vote_aggregation(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: _VoteAdapter,
    answer_agent_ids: list[int],
) -> ProtocolFinalResult:
    """Group the holders' answers by canonical key, pick the majority, score it."""
    # 中文：先收集参与投票的 agent 答案，同一个规范键归到一组。
    groups: dict[str, list[int]] = defaultdict(list)
    answer_by_key: dict[str, Any] = {}
    for agent_id in answer_agent_ids:
        answer = task_adapter.extract_protocol_answer(agent_states[agent_id].belief_state)
        key = task_adapter.protocol_answer_key(answer)
        groups[key].append(agent_id)
        answer_by_key[key] = answer

    if not groups:
        # 中文：没有可投票者时显式评分 None，保证下游仍拿到完整 ProtocolFinalResult。
        scored = task_adapter.score_protocol_answer(None, global_task)
        return ProtocolFinalResult(
            final_key="UNKNOWN", final_answer=None, primary_metric=float(scored.get("primary_metric", 0.0)),
            exact_match=bool(scored.get("exact_match", False)),
            answer_agent_ids=list(answer_agent_ids), top_ratio=0.0,
        )

    # 中文：多数派优先；票数相同则按 key 稳定排序，避免非确定性。
    top_key, supporting = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
    answer = answer_by_key[top_key]
    scored = task_adapter.score_protocol_answer(answer, global_task)
    return ProtocolFinalResult(
        final_key=top_key,
        final_answer=answer,
        selected_primary="vote",
        aggregation_method="vote",
        primary_metric=float(scored.get("primary_metric", 0.0)),
        exact_match=bool(scored.get("exact_match", False)),
        supporting_agents=sorted(supporting),
        answer_agent_ids=list(answer_agent_ids),
        top_ratio=len(supporting) / max(1, len(answer_agent_ids)),
    )
