"""Agent config and state schemas."""
# ============================================================
# 【模块导读】agent 配置与状态的数据结构。
# Silo 的协议执行路径会把每个 agent 的局部数据、当前信念、收件箱和发件箱都装进这些模型。
# ============================================================

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from exp_graph.messaging.messages import OutboxMessage


# 【职责】信念状态的三种阶段：未知、候选答案、最终答案。
class BeliefStatus(str, Enum):
    """Allowed belief state statuses."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    FINAL = "final"


# 【职责】单个 agent 的唯一内部真相：自然语言解释、共识键、结构化答案与置信度都在这里。
class BeliefState(BaseModel):
    """The only internal source of truth for an agent."""

    status: BeliefStatus = BeliefStatus.UNKNOWN
    proposal: str = ""
    consensus_key: str | None = "UNKNOWN"
    support: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    open_questions: list[str] = Field(default_factory=list)
    private_notes: str = ""
    confidence: float | None = None
    structured_state: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None

    @field_validator("support", "open_questions", mode="before")
    @classmethod
    # 【职责】把 support/open_questions 容错归一为字符串列表，方便 LLM JSON 输出不稳定时继续运行。
    def _coerce_string_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    @field_validator("confidence")
    @classmethod
    # 【职责】把置信度裁剪到 [0,1]；缺省 None 表示模型没有可靠自评。
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.0, min(1.0, float(value)))


# 【职责】单个 agent 的静态配置：角色、模型、提示词模板、重试与温度。
class AgentConfig(BaseModel):
    """Static configuration for one agent."""

    agent_id: int
    role: str = "solver"
    model_name: str
    prompt_template_name: str = "solver_v1"
    json_retry_attempts: int = 2
    temperature: float = 0.0


# 【职责】单个 agent 的运行时可变状态：本地观测、当前信念、收件箱和最新发件箱。
class AgentState(BaseModel):
    """Mutable state for one agent."""

    local_observation: dict[str, Any]
    belief_state: BeliefState
    inbox: list[OutboxMessage] = Field(default_factory=list)
    outbox: OutboxMessage | None = None


# 【职责】创建初始 AgentState，并立即由初始信念派生第一条 outbox 消息。
def make_initial_agent_state(
    local_observation: dict[str, Any],
    belief_state: BeliefState,
    agent_id: int,
    round_idx: int,
) -> AgentState:
    """Create an agent state and derive its initial outbox."""
    outbox = OutboxMessage.from_belief_state(
        agent_id=agent_id,
        round_idx=round_idx,
        belief_state=belief_state,
    )
    return AgentState(
        local_observation=local_observation,
        belief_state=belief_state,
        inbox=[],
        outbox=outbox,
    )
