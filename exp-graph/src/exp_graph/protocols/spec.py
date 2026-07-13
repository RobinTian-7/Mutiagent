"""Serializable finite protocol graph specifications."""
# ============================================================
# 【模块导读】可序列化的有限协议图规格。
# ProtocolStepSpec / ProtocolGraphSpec 是皇帝(规划 LLM)产出的
# 时序通信 DAG 数据结构；build_protocol_schedule_from_spec 把它
# 编译为执行器使用的 CommunicationStep 协议调度(逐步通信计划)。
# ============================================================

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from exp_graph.protocols.schedules import CommunicationStep


# 【职责】皇帝(规划 LLM)请求的一个有限同时通信步。
class ProtocolStepSpec(BaseModel):
    """One finite simultaneous communication step requested by a planner."""

    # 本步同时投递的有向边 (src, dst)：src 的发件箱送达 dst 的收件箱
    transmissions: list[tuple[int, int]] = Field(default_factory=list)
    # 人类可读的步骤描述
    description: str = ""
    # 产生该步的算子标签（默认 "custom"）
    operator: str = "custom"
    # 中文：本步可选的、面向接收方的角色指引；执行器启用步指令(M9)时注入合并提示词。
    #   默认 None -> 任何地方行为都不变（CF 规格从不设置它）。
    # Optional receiver-facing role guidance for this step, injected into the
    # merge prompt when the runner enables step instructions (M9). Default
    # None -> no behavior change anywhere (CF specs never set it).
    instruction: str | None = None

    # 【职责】清洗传输边：转 int、按首次出现去重；含自环 (src==dst) 直接抛错。
    @field_validator("transmissions")
    @classmethod
    def validate_transmissions(cls, transmissions: list[tuple[int, int]]):
        seen: set[tuple[int, int]] = set()
        cleaned: list[tuple[int, int]] = []
        for src, dst in transmissions:
            edge = (int(src), int(dst))
            if edge[0] == edge[1]:
                raise ValueError("protocol step transmissions cannot contain self-loops")
            if edge in seen:
                continue
            seen.add(edge)
            cleaned.append(edge)
        return cleaned


# 【职责】皇帝(规划 LLM)生成的有限协议，可编译为 CommunicationStep 调度。
class ProtocolGraphSpec(BaseModel):
    """A planner-generated finite protocol that compiles to CommunicationStep."""

    # 协议名（也用作步骤描述的兜底前缀）
    name: str
    # 参与 agent 数（用于校验边端点范围）
    n_agents: int
    # 时序通信 DAG 的逐通信步列表（按顺序执行）
    steps: list[ProtocolStepSpec] = Field(default_factory=list)
    # 该协议用到的算子名列表
    operators: list[str] = Field(default_factory=list)
    # 元数据：可含 max_steps / max_messages 预算上限与 selected_primary 等
    metadata: dict[str, object] = Field(default_factory=dict)

    # 【职责】整体校验：n_agents 为正、边端点为合法 agent 编号、
    # 步数与消息数不超过 metadata 的 max_steps / max_messages 预算。
    @model_validator(mode="after")
    def validate_spec(self) -> "ProtocolGraphSpec":
        if self.n_agents < 1:
            raise ValueError("n_agents must be positive")
        for step in self.steps:
            for src, dst in step.transmissions:
                if src < 0 or dst < 0 or src >= self.n_agents or dst >= self.n_agents:
                    raise ValueError(
                        "protocol step transmissions must reference valid agent ids"
                    )
        max_steps = self.metadata.get("max_steps")
        if max_steps is not None and len(self.steps) > int(max_steps):
            raise ValueError("protocol graph exceeds metadata.max_steps")
        max_messages = self.metadata.get("max_messages")
        if max_messages is not None:
            message_count = sum(len(step.transmissions) for step in self.steps)
            if message_count > int(max_messages):
                raise ValueError("protocol graph exceeds metadata.max_messages")
        return self


# 【职责】把有限协议规格编译为执行器的调度格式（CommunicationStep 列表）。
# - 顺序编号 step_idx；描述缺省用协议名+步号；instruction 原样透传。
def build_protocol_schedule_from_spec(
    spec: ProtocolGraphSpec,
) -> list[CommunicationStep]:
    """Compile a finite protocol spec into the runner schedule format."""
    return [
        CommunicationStep(
            step_idx=step_idx,
            transmissions=step.transmissions,
            description=step.description or f"{spec.name}: step {step_idx}",
            instruction=step.instruction,
        )
        for step_idx, step in enumerate(spec.steps)
    ]
