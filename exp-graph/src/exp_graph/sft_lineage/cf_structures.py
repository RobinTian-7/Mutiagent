"""CF structure vocabulary: phase programs that compile to protocol specs.

The SFTBank structure lineage duels FROZEN artifacts written in a small
phase vocabulary.  This is that vocabulary's CF dialect, oriented at the
sink information goal: dissemination phases are optional pre-mixing
(redundancy against an imperfect LLM merge operator), and at least one
reduction phase must make every shard reachable at the sink.

Deliberate deviations from the SiloBench vocabulary, kept minimal:

- No ``broadcast``/``consensus`` kinds: propagating the merged table back
  out is pure waste under the sink goal.
- No per-phase ``instruction`` strings: this repository's protocol runner
  has no per-step prompt plumbing, so the search space is structure-only.
  ``structure_diff`` tolerates the absent field.

Compilation reuses the repository's schedule builders wherever one exists
(tree reduce, balanced layers, static exponential), so a lineage structure
and the named-topology baselines are literally the same steps.
"""

from __future__ import annotations

import math
from typing import Any

from exp_graph.protocols.schedules import (
    CommunicationStep,
    _build_balanced_log_layer_schedule,
    _build_binary_reduce_tree_schedule,
    _build_static_exponential_propagation,
)
from exp_graph.protocols.spec import ProtocolGraphSpec, ProtocolStepSpec

from exp_graph.sft_lineage.law import sha_of

CF_PROGRAM_FORMAT = "cf_phase_program_v1"
MAX_PHASES = 6
MAX_COMPILED_STEPS = 96
MAX_PREMIX_ROUNDS = 12

PREMIX_PATTERNS = ("one_peer_exponential", "static_exponential", "ring")
GATHER_PATTERNS = ("star", "tree", "chain", "balanced_layers")

CF_PHASE_VOCABULARY = """\
A <PHASE> object is one of:
- {"kind": "premix", "pattern": "one_peer_exponential"|"static_exponential"|\
"ring", "max_rounds": <int 1..12>}
  (peer dissemination BEFORE reduction: each round every agent forwards its
  merged table to one or more peers — redundancy that lets errors be
  corrected downstream, at extra message cost)
- {"kind": "gather", "pattern": "star"|"tree"|"chain"|"balanced_layers"}
  (reduction INTO the sink agent, the highest id: star = everyone sends to
  the sink in one step; tree = log-depth binary reduce; chain = serial
  relay; balanced_layers = log-depth dense layers)"""


def _tau(n_agents: int) -> int:
    return max(1, math.ceil(math.log2(max(2, n_agents))))


def _premix_steps(
    pattern: str, max_rounds: int, n_agents: int
) -> list[tuple[list[tuple[int, int]], str]]:
    tau = _tau(n_agents)
    steps: list[tuple[list[tuple[int, int]], str]] = []
    if pattern == "one_peer_exponential":
        for round_idx in range(max_rounds):
            distance = 2 ** (round_idx % tau)
            edges = _dedupe(
                (src, (src + distance) % n_agents) for src in range(n_agents)
            )
            steps.append(
                (edges, f"premix one_peer_exponential: distance {distance}")
            )
    elif pattern == "static_exponential":
        template = _build_static_exponential_propagation(n_agents)
        edges = list(template[0].transmissions) if template else []
        for _round_idx in range(max_rounds):
            steps.append(
                (list(edges), "premix static_exponential: fixed edges")
            )
    elif pattern == "ring":
        edges = _dedupe((src, (src + 1) % n_agents) for src in range(n_agents))
        for _round_idx in range(max_rounds):
            steps.append((list(edges), "premix ring: forward neighbour"))
    else:
        raise ValueError(f"unknown premix pattern {pattern!r}")
    return steps


def _gather_steps(
    pattern: str, n_agents: int
) -> list[tuple[list[tuple[int, int]], str]]:
    sink = n_agents - 1
    if pattern == "star":
        edges = [(src, sink) for src in range(n_agents) if src != sink]
        return [(edges, f"gather star: all agents send to sink {sink}")]
    if pattern == "chain":
        return [
            ([(src, src + 1)], f"gather chain: agent {src} relays forward")
            for src in range(n_agents - 1)
        ]
    if pattern == "tree":
        schedule = _build_binary_reduce_tree_schedule(n_agents)
    elif pattern == "balanced_layers":
        schedule = _build_balanced_log_layer_schedule(n_agents)
    else:
        raise ValueError(f"unknown gather pattern {pattern!r}")
    return [
        (list(step.transmissions), step.description) for step in schedule
    ]


def _dedupe(edges: Any) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    cleaned: list[tuple[int, int]] = []
    for src, dst in edges:
        edge = (int(src), int(dst))
        if edge[0] == edge[1] or edge in seen:
            continue
        seen.add(edge)
        cleaned.append(edge)
    return cleaned


def simulate_information_flow(
    steps: list[list[tuple[int, int]]], n_agents: int
) -> list[set[int]]:
    """Final source coverage per agent under simultaneous-step semantics.

    Within one step every transmission reads the SENDER's pre-step
    knowledge, matching the runner's merge-inbox-after-step behaviour.
    """

    knowledge = [{agent_id} for agent_id in range(n_agents)]
    for transmissions in steps:
        snapshot = [set(known) for known in knowledge]
        for src, dst in transmissions:
            knowledge[dst] |= snapshot[src]
    return knowledge


def validate_cf_design(
    phases: Any, *, information_goal: str, n_agents: int
) -> dict[str, Any]:
    """Planner output -> compile-checked CF program (bounds enforced).

    The returned program is the frozen artifact the lineage archives; it
    fails loudly on any phase outside the vocabulary, on compiled schedules
    beyond the step bound, and on schedules whose information flow cannot
    satisfy the goal even with a perfect merge operator.
    """

    if information_goal not in ("sink", "all_agents"):
        raise ValueError(f"unknown information goal {information_goal!r}")
    if not isinstance(phases, list) or not 1 <= len(phases) <= MAX_PHASES:
        raise ValueError(f"design must contain 1..{MAX_PHASES} phases")
    normalized: list[dict[str, Any]] = []
    for phase in phases:
        if not isinstance(phase, dict):
            raise ValueError("each phase must be a JSON object")
        kind = str(phase.get("kind") or "")
        if kind == "premix":
            pattern = str(phase.get("pattern") or "")
            if pattern not in PREMIX_PATTERNS:
                raise ValueError(f"unknown premix pattern {pattern!r}")
            max_rounds = int(phase.get("max_rounds") or 0)
            if not 1 <= max_rounds <= MAX_PREMIX_ROUNDS:
                raise ValueError(
                    f"premix max_rounds must be 1..{MAX_PREMIX_ROUNDS}"
                )
            normalized.append(
                {"kind": kind, "pattern": pattern, "max_rounds": max_rounds}
            )
        elif kind == "gather":
            pattern = str(phase.get("pattern") or "")
            if pattern not in GATHER_PATTERNS:
                raise ValueError(f"unknown gather pattern {pattern!r}")
            normalized.append({"kind": kind, "pattern": pattern})
        else:
            raise ValueError(f"unknown phase kind {kind!r}")
    program = {
        "format": CF_PROGRAM_FORMAT,
        "information_goal": information_goal,
        "phases": normalized,
    }
    compile_cf_program(program, n_agents=n_agents)
    return program


def compile_cf_program(
    program: dict[str, Any], *, n_agents: int
) -> ProtocolGraphSpec:
    """Compile a CF phase program into a runnable protocol graph spec."""

    if n_agents < 2:
        raise ValueError("CF structures need at least 2 agents")
    if program.get("format") != CF_PROGRAM_FORMAT:
        raise ValueError(f"unknown program format {program.get('format')!r}")
    goal = str(program.get("information_goal") or "sink")
    phases = program.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("program carries no phases")

    compiled: list[tuple[list[tuple[int, int]], str]] = []
    for phase in phases:
        kind = str(phase.get("kind"))
        if kind == "premix":
            compiled.extend(
                _premix_steps(
                    str(phase.get("pattern")),
                    int(phase.get("max_rounds") or 1),
                    n_agents,
                )
            )
        elif kind == "gather":
            compiled.extend(_gather_steps(str(phase.get("pattern")), n_agents))
        else:
            raise ValueError(f"unknown phase kind {kind!r}")
    compiled = [(edges, text) for edges, text in compiled if edges]
    if not compiled:
        raise ValueError("program compiles to an empty schedule")
    if len(compiled) > MAX_COMPILED_STEPS:
        raise ValueError(
            f"design compiles beyond the {MAX_COMPILED_STEPS}-step bound"
        )

    knowledge = simulate_information_flow(
        [edges for edges, _text in compiled], n_agents
    )
    everything = set(range(n_agents))
    sink = n_agents - 1
    if goal == "sink":
        if knowledge[sink] != everything:
            missing = sorted(everything - knowledge[sink])
            raise ValueError(
                f"sink agent {sink} can never see shards {missing}; add or "
                "extend a gather/premix phase"
            )
    elif goal == "all_agents":
        starved = [
            agent_id
            for agent_id in range(n_agents)
            if knowledge[agent_id] != everything
        ]
        if starved:
            raise ValueError(
                f"agents {starved} can never see every shard under goal "
                "'all_agents'"
            )
    else:
        raise ValueError(f"unknown information goal {goal!r}")

    metadata: dict[str, Any] = {
        "format": CF_PROGRAM_FORMAT,
        "information_goal": goal,
        "phases": phases,
        "max_steps": MAX_COMPILED_STEPS,
    }
    if goal == "sink":
        # The runner reads this as the answer-agent override: only the
        # sink's final table feeds FinalRMSE / FinalExactMatch.
        metadata["selected_primary"] = sink
    return ProtocolGraphSpec(
        name=f"cf_sft_{sha_of(phases)[:12]}",
        n_agents=n_agents,
        steps=[
            ProtocolStepSpec(transmissions=edges, description=text)
            for edges, text in compiled
        ],
        operators=["cf_phase_program"],
        metadata=metadata,
    )


def compiled_steps(program: dict[str, Any], *, n_agents: int) -> list[CommunicationStep]:
    """The runner-facing schedule for a program (for reports/inspection)."""

    spec = compile_cf_program(program, n_agents=n_agents)
    return [
        CommunicationStep(
            step_idx=index,
            transmissions=step.transmissions,
            description=step.description,
        )
        for index, step in enumerate(spec.steps)
    ]


# ---------------------------------------------------------------------------
# Seed structures and reference baselines

SEED_STRUCTURES: dict[str, str] = {
    "one_peer_star_sink": (
        "One-peer exponential pre-mix, then a single star gather into the "
        "sink — redundancy first, one aggregation pass to finish."
    ),
    "star_sink": "Single star gather: every agent sends to the sink once.",
    "tree_sink": "Binary reduce tree into the sink; fan-in 2, log depth.",
    "chain_sink": "Serial relay along the agent order into the sink.",
    "static_exponential_sink": (
        "Static exponential pre-mix, then a star gather into the sink."
    ),
    "balanced_log_layer_sink": (
        "Balanced log-depth layers reducing densely into the sink."
    ),
}


def seed_program(
    name: str, *, n_agents: int, information_goal: str = "sink"
) -> dict[str, Any]:
    """Build the seed phase program for a named start point."""

    wanted = str(name).strip().lower()
    tau = _tau(n_agents)
    phases_by_name: dict[str, list[dict[str, Any]]] = {
        "one_peer_star_sink": [
            {
                "kind": "premix",
                "pattern": "one_peer_exponential",
                "max_rounds": tau,
            },
            {"kind": "gather", "pattern": "star"},
        ],
        "star_sink": [{"kind": "gather", "pattern": "star"}],
        "tree_sink": [{"kind": "gather", "pattern": "tree"}],
        "chain_sink": [{"kind": "gather", "pattern": "chain"}],
        "static_exponential_sink": [
            {
                "kind": "premix",
                "pattern": "static_exponential",
                "max_rounds": tau,
            },
            {"kind": "gather", "pattern": "star"},
        ],
        "balanced_log_layer_sink": [
            {"kind": "gather", "pattern": "balanced_layers"}
        ],
    }
    if wanted not in phases_by_name:
        valid = ", ".join(sorted(phases_by_name))
        raise ValueError(f"unknown seed structure {name!r}; choose one of: {valid}")
    return validate_cf_design(
        phases_by_name[wanted],
        information_goal=information_goal,
        n_agents=n_agents,
    )


def fake_design(round_index: int, n_agents: int) -> list[dict[str, Any]]:
    """Deterministic offline designs; alternate two compilable shapes."""

    if round_index % 2 == 0:
        return [{"kind": "gather", "pattern": "star"}]
    return [
        {"kind": "premix", "pattern": "one_peer_exponential", "max_rounds": 2},
        {"kind": "gather", "pattern": "tree"},
    ]
