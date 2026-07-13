"""Structured messages exchanged between neighbors."""
# ============================================================
# 【模块导读】agent 邻居之间交换的结构化消息。
# ProtocolRunner 不直接搬运完整 BeliefState，而是通过 OutboxMessage 暴露可传播的短摘要。
# ============================================================

from __future__ import annotations

from pydantic import BaseModel, Field


# 【职责】从 agent 信念状态抽出的外部视图：用于跨边传输候选答案、共识键与少量解释。
class OutboxMessage(BaseModel):
    """External view derived from an agent belief state."""

    agent_id: int
    round_idx: int
    status: str
    proposal: str
    consensus_key: str | None = "UNKNOWN"
    support: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    request: str = ""
    structured_payload: dict = Field(default_factory=dict)

    @classmethod
    # 【职责】从 BeliefState 和运行时元数据派生精简 outbox；只带邻居需要看的字段。
    def from_belief_state(
        cls,
        agent_id: int,
        round_idx: int,
        belief_state: object,
    ) -> "OutboxMessage":
        """Derive a short outbox from a belief state and runtime metadata."""
        open_questions = list(getattr(belief_state, "open_questions", []) or [])
        request = open_questions[0] if open_questions else ""
        return cls(
            agent_id=agent_id,
            round_idx=round_idx,
            status=str(getattr(belief_state, "status", "unknown").value)
            if hasattr(getattr(belief_state, "status", None), "value")
            else str(getattr(belief_state, "status", "unknown")),
            proposal=str(getattr(belief_state, "proposal", "")),
            consensus_key=getattr(belief_state, "consensus_key", "UNKNOWN"),
            support=[str(item) for item in getattr(belief_state, "support", [])[:3]],
            uncertainty=str(getattr(belief_state, "uncertainty", "")),
            request=str(request),
            structured_payload=dict(getattr(belief_state, "structured_state", {}) or {}),
        )
