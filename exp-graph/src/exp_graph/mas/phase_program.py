"""Restricted phase DSL for independently generated MAS communication programs.

``phase_program_v1`` deliberately does not expose edge expressions.  An LLM can
only compose a small set of typed phases and bounded parameters; the compiler
owns every concrete edge, loop expansion, budget check, and structural stop
condition.  The existing free-form ``graph_generate`` and
``topology_program_v1`` paths remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.mas.schemas import InformationGoal
from exp_graph.protocols import ProtocolGraphSpec, ProtocolStepSpec
from exp_graph.protocols.schedules import build_protocol_schedule


PHASE_PROGRAM_FORMAT = "phase_program_v1"
PHASE_PROGRAM_COMPILER_VERSION = "1"

StopCondition = Literal[
    "fixed_rounds",
    "sink_full_information",
    "all_agents_full_information",
]


class PhaseProgramError(ValueError):
    """A phase program is invalid or cannot fit its bounded execution budget."""


class _PhaseBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str | None = Field(default=None, max_length=500)
    send_mode: Literal["full_state", "delta_or_no_send"] = "delta_or_no_send"


class GatherPhase(_PhaseBase):
    """Move every agent's accumulated state into one hub."""

    kind: Literal["gather"] = "gather"
    hub: int = 0
    pattern: Literal["star", "tree"] = "tree"


class BroadcastPhase(_PhaseBase):
    """Disseminate one hub's accumulated state to every agent."""

    kind: Literal["broadcast"] = "broadcast"
    hub: int = 0
    pattern: Literal["star", "tree"] = "tree"


class PairwiseExchangePhase(_PhaseBase):
    """Bounded peer exchange with no model-authored endpoint expressions."""

    kind: Literal["pairwise_exchange"] = "pairwise_exchange"
    pattern: Literal["ring", "bidirectional_ring", "rotating"] = "rotating"
    max_rounds: int = Field(default=4, ge=1, le=64)
    stop_when: StopCondition = "fixed_rounds"


class ConsensusPhase(_PhaseBase):
    """A full-dissemination phase using a dense or rotating construction."""

    kind: Literal["consensus"] = "consensus"
    pattern: Literal["all_to_all", "rotating"] = "rotating"
    max_rounds: int = Field(default=8, ge=1, le=64)
    stop_when: StopCondition = "all_agents_full_information"


PhaseStatement: TypeAlias = Annotated[
    GatherPhase | BroadcastPhase | PairwiseExchangePhase | ConsensusPhase,
    Field(discriminator="kind"),
]


class PhaseProgram(BaseModel):
    """Versioned source program composed only from typed communication phases."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["phase_program_v1"] = PHASE_PROGRAM_FORMAT
    information_goal: InformationGoal = "sink"
    selected_primary: int = 0
    state_retention: Literal["keep"] = "keep"
    allow_no_send: Literal[True] = True
    submit_when: Literal["coverage_complete", "program_complete"] = (
        "coverage_complete"
    )
    phases: list[PhaseStatement] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_goal_shape(self) -> "PhaseProgram":
        if self.information_goal == "all_agents" and self.submit_when != "coverage_complete":
            raise ValueError(
                "all_agents phase programs must submit only after coverage_complete"
            )
        return self


class PhaseProgramLimits(BaseModel):
    """Finite expansion limits shared with the generated-graph runner."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=16, ge=1)
    max_messages: int = Field(default=128, ge=0)
    max_receiver_fan_in: int = Field(default=4, ge=1)


class CompiledPhaseStep(BaseModel):
    """One simultaneous communication step emitted by a typed phase."""

    phase_index: int
    phase_kind: str
    description: str
    instruction: str | None = None
    send_mode: str = "delta_or_no_send"
    transmissions: list[tuple[int, int]] = Field(default_factory=list)


class CompiledPhaseProgram(BaseModel):
    """Auditable finite expansion of ``phase_program_v1``."""

    format: Literal["phase_program_v1"] = PHASE_PROGRAM_FORMAT
    compiler_version: str = PHASE_PROGRAM_COMPILER_VERSION
    source_hash: str
    selected_primary: int
    steps: list[CompiledPhaseStep] = Field(default_factory=list)
    expanded_messages: int = 0
    final_knowledge: list[list[int]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def phase_program_digest(program: PhaseProgram) -> str:
    payload = json.dumps(
        program.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compile_phase_program(
    program: PhaseProgram,
    *,
    n_agents: int,
    limits: PhaseProgramLimits | None = None,
) -> CompiledPhaseProgram:
    """Expand a restricted phase program into a finite temporal schedule."""
    compiler = _PhaseProgramCompiler(
        program=program,
        n_agents=n_agents,
        limits=limits or PhaseProgramLimits(),
    )
    return compiler.compile()


def compile_phase_program_spec(
    program: PhaseProgram,
    *,
    n_agents: int,
    limits: PhaseProgramLimits | None = None,
    name: str = "generated_phase_program",
) -> tuple[ProtocolGraphSpec, CompiledPhaseProgram]:
    """Compile directly to the existing ``ProtocolGraphSpec`` runner contract."""
    compiled = compile_phase_program(program, n_agents=n_agents, limits=limits)
    spec = ProtocolGraphSpec(
        name=name,
        n_agents=n_agents,
        steps=[
            ProtocolStepSpec(
                transmissions=step.transmissions,
                description=step.description,
                operator=f"phase:{step.phase_kind}",
                instruction=step.instruction,
            )
            for step in compiled.steps
        ],
        operators=[f"phase:{phase.kind}" for phase in program.phases],
        metadata={
            "graph_type": "temporal_dag",
            "generated_graph": True,
            "generated_program": True,
            "program_mode": "program_generate",
            "selected_primary": compiled.selected_primary,
            "information_goal": program.information_goal,
            "state_retention": program.state_retention,
            "allow_no_send": program.allow_no_send,
            "submit_when": program.submit_when,
            "phase_program": program.model_dump(mode="json"),
            "phase_program_compilation": compiled.model_dump(mode="json"),
        },
    )
    return spec, compiled


class _PhaseProgramCompiler:
    def __init__(
        self,
        *,
        program: PhaseProgram,
        n_agents: int,
        limits: PhaseProgramLimits,
    ) -> None:
        if n_agents < 1:
            raise PhaseProgramError("n_agents must be positive")
        if not 0 <= program.selected_primary < n_agents:
            raise PhaseProgramError(
                f"selected_primary={program.selected_primary} is outside agent range"
            )
        self.program = program
        self.n_agents = n_agents
        self.limits = limits
        self.steps: list[CompiledPhaseStep] = []
        self.messages = 0
        self.knowledge = [{agent_id} for agent_id in range(n_agents)]
        self.warnings: list[str] = []

    def compile(self) -> CompiledPhaseProgram:
        for phase_index, phase in enumerate(self.program.phases):
            before = [set(items) for items in self.knowledge]
            if isinstance(phase, GatherPhase):
                self._compile_gather(phase_index, phase)
            elif isinstance(phase, BroadcastPhase):
                self._compile_broadcast(phase_index, phase)
            elif isinstance(phase, PairwiseExchangePhase):
                self._compile_exchange(phase_index, phase)
            else:
                self._compile_consensus(phase_index, phase)
            if before == self.knowledge:
                self.warnings.append(
                    f"phase[{phase_index}] {phase.kind} added no structural information"
                )
        if not self.steps and self.n_agents > 1:
            raise PhaseProgramError("phase program produced no communication steps")
        return CompiledPhaseProgram(
            source_hash=phase_program_digest(self.program),
            selected_primary=self.program.selected_primary,
            steps=self.steps,
            expanded_messages=self.messages,
            final_knowledge=[sorted(items) for items in self.knowledge],
            warnings=self.warnings,
        )

    def _compile_gather(self, phase_index: int, phase: GatherPhase) -> None:
        self._validate_hub(phase.hub, phase_index)
        if phase.pattern == "star":
            steps = [[
                (agent_id, phase.hub)
                for agent_id in range(self.n_agents)
                if agent_id != phase.hub
            ]]
        else:
            steps = self._tree_steps(phase.hub)
        self._append_phase_steps(phase_index, phase, steps)

    def _compile_broadcast(self, phase_index: int, phase: BroadcastPhase) -> None:
        self._validate_hub(phase.hub, phase_index)
        if phase.pattern == "star":
            steps = [[
                (phase.hub, agent_id)
                for agent_id in range(self.n_agents)
                if agent_id != phase.hub
            ]]
        else:
            steps = [
                [(dst, src) for src, dst in edges]
                for edges in reversed(self._tree_steps(phase.hub))
            ]
        self._append_phase_steps(phase_index, phase, steps)

    def _compile_exchange(
        self,
        phase_index: int,
        phase: PairwiseExchangePhase,
    ) -> None:
        for round_idx in range(phase.max_rounds):
            if self._stop_reached(phase.stop_when):
                break
            if phase.pattern == "ring":
                edges = self._offset_edges(1)
            elif phase.pattern == "bidirectional_ring":
                edges = [*self._offset_edges(1), *self._offset_edges(-1)]
            else:
                offset = (round_idx % max(1, self.n_agents - 1)) + 1
                edges = self._offset_edges(offset)
            self._append_step(
                phase_index,
                phase.kind,
                edges,
                instruction=phase.instruction,
                send_mode=phase.send_mode,
                suffix=f"round {round_idx + 1}/{phase.max_rounds}",
            )
            if self._stop_reached(phase.stop_when):
                break

    def _compile_consensus(self, phase_index: int, phase: ConsensusPhase) -> None:
        for round_idx in range(phase.max_rounds):
            if self._stop_reached(phase.stop_when):
                break
            if phase.pattern == "all_to_all":
                edges = [
                    (src, dst)
                    for src in range(self.n_agents)
                    for dst in range(self.n_agents)
                    if src != dst
                ]
            else:
                offset = (round_idx % max(1, self.n_agents - 1)) + 1
                edges = self._offset_edges(offset)
            self._append_step(
                phase_index,
                phase.kind,
                edges,
                instruction=phase.instruction,
                send_mode=phase.send_mode,
                suffix=f"round {round_idx + 1}/{phase.max_rounds}",
            )
            if self._stop_reached(phase.stop_when):
                break

    def _append_phase_steps(
        self,
        phase_index: int,
        phase: GatherPhase | BroadcastPhase,
        steps: list[list[tuple[int, int]]],
    ) -> None:
        for step_idx, edges in enumerate(steps):
            self._append_step(
                phase_index,
                phase.kind,
                edges,
                instruction=phase.instruction,
                send_mode=phase.send_mode,
                suffix=f"stage {step_idx + 1}/{len(steps)}",
            )

    def _append_step(
        self,
        phase_index: int,
        phase_kind: str,
        edges: list[tuple[int, int]],
        *,
        instruction: str | None,
        send_mode: str,
        suffix: str,
    ) -> None:
        deduped: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        fan_in: Counter[int] = Counter()
        skipped_no_delta = 0
        for src, dst in edges:
            edge = (int(src), int(dst))
            if src == dst or edge in seen:
                continue
            if not (0 <= src < self.n_agents and 0 <= dst < self.n_agents):
                raise PhaseProgramError(
                    f"phase[{phase_index}] generated invalid edge {edge}"
                )
            # ``delta_or_no_send`` has executable semantics: when the sender's
            # structurally known sources are already a subset of the receiver's,
            # this transfer cannot add information and is omitted. Agents still
            # retain their prior state because the runner updates only receivers.
            if (
                send_mode == "delta_or_no_send"
                and self.knowledge[src] <= self.knowledge[dst]
            ):
                skipped_no_delta += 1
                continue
            fan_in[dst] += 1
            if fan_in[dst] > self.limits.max_receiver_fan_in:
                raise PhaseProgramError(
                    f"phase[{phase_index}] exceeds max_receiver_fan_in="
                    f"{self.limits.max_receiver_fan_in} at agent {dst}"
                )
            seen.add(edge)
            deduped.append(edge)
        if not deduped:
            if skipped_no_delta:
                self.warnings.append(
                    f"phase[{phase_index}] omitted {skipped_no_delta} no-delta sends"
                )
            return
        if skipped_no_delta:
            self.warnings.append(
                f"phase[{phase_index}] omitted {skipped_no_delta} no-delta sends"
            )
        if len(self.steps) >= self.limits.max_steps:
            raise PhaseProgramError(
                f"phase program exceeds max_steps={self.limits.max_steps}"
            )
        if self.messages + len(deduped) > self.limits.max_messages:
            raise PhaseProgramError(
                f"phase program exceeds max_messages={self.limits.max_messages}"
            )
        self.steps.append(
            CompiledPhaseStep(
                phase_index=phase_index,
                phase_kind=phase_kind,
                description=f"{phase_kind}: {suffix}",
                instruction=instruction,
                send_mode=send_mode,
                transmissions=deduped,
            )
        )
        self.messages += len(deduped)
        previous = [set(items) for items in self.knowledge]
        updated = [set(items) for items in previous]
        for src, dst in deduped:
            updated[dst].update(previous[src])
        self.knowledge = updated

    def _tree_steps(self, hub: int) -> list[list[tuple[int, int]]]:
        logical_agents = [
            agent_id for agent_id in range(self.n_agents) if agent_id != hub
        ] + [hub]
        return [
            [
                (logical_agents[src], logical_agents[dst])
                for src, dst in step.transmissions
            ]
            for step in build_protocol_schedule("tree", self.n_agents)
        ]

    def _offset_edges(self, offset: int) -> list[tuple[int, int]]:
        if self.n_agents <= 1:
            return []
        return [
            (src, (src + offset) % self.n_agents)
            for src in range(self.n_agents)
        ]

    def _stop_reached(self, condition: StopCondition) -> bool:
        target = set(range(self.n_agents))
        if condition == "fixed_rounds":
            return False
        if condition == "sink_full_information":
            return self.knowledge[self.program.selected_primary] >= target
        return all(items >= target for items in self.knowledge)

    def _validate_hub(self, hub: int, phase_index: int) -> None:
        if not 0 <= hub < self.n_agents:
            raise PhaseProgramError(
                f"phase[{phase_index}] hub={hub} is outside agent range"
            )
