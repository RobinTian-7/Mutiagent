"""Serializable finite protocol graph specifications."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from exp_graph.protocols.schedules import CommunicationStep


class ProtocolStepSpec(BaseModel):
    """One finite simultaneous communication step requested by a planner."""

    transmissions: list[tuple[int, int]] = Field(default_factory=list)
    description: str = ""
    operator: str = "custom"
    # Optional receiver-facing role guidance for this step, injected into the
    # merge prompt when the runner enables step instructions (M9). Default
    # None -> no behavior change anywhere (CF specs never set it).
    instruction: str | None = None

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


class ProtocolGraphSpec(BaseModel):
    """A planner-generated finite protocol that compiles to CommunicationStep."""

    name: str
    n_agents: int
    steps: list[ProtocolStepSpec] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

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
