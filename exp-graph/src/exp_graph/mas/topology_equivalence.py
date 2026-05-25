"""Temporal topology equivalence helpers for generated MAS protocols."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from exp_graph.protocols import ProtocolGraphSpec

TemporalEdge = tuple[int, int, int]


@dataclass(frozen=True)
class TopologyFingerprint:
    """Stable hashes and canonical forms for one temporal topology."""

    topology_equivalence_hash: str
    exact_execution_hash: str
    canonical_temporal_edges: list[TemporalEdge]


def fingerprint_protocol_spec(
    spec: ProtocolGraphSpec,
) -> TopologyFingerprint:
    """Build exact and equivalence hashes from a protocol spec."""
    selected = _optional_int(spec.metadata.get("selected_primary"))
    return fingerprint_temporal_edges(
        n_agents=spec.n_agents,
        steps=[step.transmissions for step in spec.steps],
        selected_primary=selected,
    )


def fingerprint_temporal_edges(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    selected_primary: int | None = None,
) -> TopologyFingerprint:
    """Build exact and label-invariant hashes for temporal routes.

    Edges are interpreted as (step, src, dst).  Agent-level feedback is valid
    because time always advances between steps in the expanded execution graph.
    """
    normalized_steps = _normalize_steps(steps)
    exact_payload = {
        "n_agents": int(n_agents),
        "selected_primary": selected_primary,
        "steps": normalized_steps,
    }
    exact_hash = _digest(exact_payload)
    canonical = canonical_temporal_edges(
        n_agents=n_agents,
        steps=normalized_steps,
        selected_primary=selected_primary,
    )
    equivalence_payload = {
        "n_agents": int(n_agents),
        "canonical_temporal_edges": canonical,
    }
    return TopologyFingerprint(
        topology_equivalence_hash=_digest(equivalence_payload),
        exact_execution_hash=exact_hash,
        canonical_temporal_edges=canonical,
    )


def canonical_temporal_edges(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    selected_primary: int | None = None,
) -> list[TemporalEdge]:
    """Return the lexicographically minimal relabeled temporal edge list."""
    normalized_steps = _normalize_steps(steps)
    agents = tuple(range(int(n_agents)))
    initial_colors = _initial_agent_colors(
        n_agents=int(n_agents),
        steps=normalized_steps,
        selected_primary=selected_primary,
    )
    refined_colors = _refine_agent_colors(
        n_agents=int(n_agents),
        steps=normalized_steps,
        colors=initial_colors,
    )
    color_groups: dict[tuple[object, ...], list[int]] = {}
    for agent, color in refined_colors.items():
        color_groups.setdefault(color, []).append(agent)
    ordered_groups = [
        tuple(sorted(group))
        for _color, group in sorted(
            color_groups.items(),
            key=lambda item: (repr(item[0]), len(item[1]), tuple(sorted(item[1]))),
        )
    ]
    best: list[TemporalEdge] | None = None
    for ordered_agents in _candidate_orders(ordered_groups):
        mapping = {agent: idx for idx, agent in enumerate(ordered_agents)}
        relabeled = sorted(
            (step_idx, mapping[src], mapping[dst])
            for step_idx, edges in enumerate(normalized_steps)
            for src, dst in edges
        )
        if best is None or relabeled < best:
            best = relabeled
    if best is not None:
        return best
    return [(step_idx, agent, agent) for step_idx, agent in enumerate(agents[:0])]


def topology_hash_from_skill(skill: object) -> str | None:
    """Return or derive a topology equivalence hash for a SkillCard-like object."""
    organization_policy = getattr(skill, "organization_policy", {}) or {}
    stored = organization_policy.get("topology_equivalence_hash")
    if stored:
        return str(stored)
    spec_data = organization_policy.get("protocol_spec")
    if not isinstance(spec_data, dict):
        return None
    try:
        spec = ProtocolGraphSpec.model_validate(spec_data)
    except Exception:
        return None
    return fingerprint_protocol_spec(spec).topology_equivalence_hash


def protocol_metadata_with_fingerprint(
    spec: ProtocolGraphSpec,
) -> dict[str, object]:
    """Return protocol metadata containing current topology fingerprints."""
    fp = fingerprint_protocol_spec(spec)
    return {
        "topology_equivalence_hash": fp.topology_equivalence_hash,
        "exact_execution_hash": fp.exact_execution_hash,
        "canonical_temporal_edges": [list(edge) for edge in fp.canonical_temporal_edges],
    }


def _normalize_steps(
    steps: Sequence[Sequence[tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    normalized: list[list[tuple[int, int]]] = []
    for edges in steps:
        normalized.append(sorted({(int(src), int(dst)) for src, dst in edges}))
    return normalized


def _initial_agent_colors(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    selected_primary: int | None,
) -> dict[int, tuple[object, ...]]:
    colors: dict[int, tuple[object, ...]] = {}
    final_receivers = {dst for edges in steps for _src, dst in edges}
    sources = {src for edges in steps for src, _dst in edges}
    for agent in range(n_agents):
        timeline = []
        for edges in steps:
            out_count = sum(1 for src, _dst in edges if src == agent)
            in_count = sum(1 for _src, dst in edges if dst == agent)
            timeline.append((out_count, in_count))
        colors[agent] = (
            tuple(timeline),
            agent == selected_primary,
            agent in final_receivers and agent not in sources,
        )
    return colors


def _refine_agent_colors(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    colors: dict[int, tuple[object, ...]],
) -> dict[int, tuple[object, ...]]:
    current = dict(colors)
    for _ in range(max(1, n_agents * 2)):
        next_colors: dict[int, tuple[object, ...]] = {}
        for agent in range(n_agents):
            step_signature = []
            for edges in steps:
                outgoing = sorted(current[dst] for src, dst in edges if src == agent)
                incoming = sorted(current[src] for src, dst in edges if dst == agent)
                step_signature.append((tuple(outgoing), tuple(incoming)))
            next_colors[agent] = (current[agent], tuple(step_signature))
        compressed = _compress_colors(next_colors)
        if compressed == current:
            return compressed
        current = compressed
    return current


def _compress_colors(
    colors: dict[int, tuple[object, ...]],
) -> dict[int, tuple[object, ...]]:
    ranked = {
        color: idx
        for idx, color in enumerate(sorted(set(colors.values()), key=repr))
    }
    return {agent: (ranked[color],) for agent, color in colors.items()}


def _candidate_orders(groups: Sequence[Sequence[int]]) -> Iterable[tuple[int, ...]]:
    total = 1
    for group in groups:
        total *= _factorial(len(group))
    if total > 200_000:
        # Keep runtime bounded for larger, highly symmetric graphs.  The refined
        # color groups still give deterministic, stable labels for practical use.
        yield tuple(agent for group in groups for agent in sorted(group))
        return
    for pieces in itertools.product(*(itertools.permutations(group) for group in groups)):
        yield tuple(agent for piece in pieces for agent in piece)


def _factorial(value: int) -> int:
    result = 1
    for number in range(2, value + 1):
        result *= number
    return result


def _digest(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
