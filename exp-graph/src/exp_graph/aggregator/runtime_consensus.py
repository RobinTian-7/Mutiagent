"""Cheap O(N) runtime consensus detection."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field


class RuntimeConsensusResult(BaseModel):
    """Result of cheap per-round consensus detection."""

    consensus_reached: bool
    top_key: str | None = None
    top_ratio: float = 0.0
    key_counts: dict[str, int] = Field(default_factory=dict)
    active_keys: list[str] = Field(default_factory=list)


def collect_runtime_keys(agent_states: list) -> list[str | None]:
    """Collect consensus keys from current agent belief states."""
    keys = []
    for state in agent_states:
        belief = getattr(state, "belief_state", None)
        keys.append(getattr(belief, "consensus_key", None))
    return keys


def count_keys(keys: list[str | None]) -> dict[str, int]:
    """Count non-empty keys while preserving UNKNOWN as a valid counted key."""
    cleaned = []
    for key in keys:
        if key is None:
            continue
        key_text = str(key).strip()
        if not key_text:
            continue
        cleaned.append(key_text)
    return dict(Counter(cleaned))


def detect_runtime_consensus(
    key_counts: dict[str, int],
    num_agents: int,
    threshold: float,
) -> RuntimeConsensusResult:
    """Detect whether a cheap consensus threshold has been reached."""
    if num_agents <= 0:
        raise ValueError("num_agents must be positive")
    if not key_counts:
        return RuntimeConsensusResult(
            consensus_reached=False,
            top_key=None,
            top_ratio=0.0,
            key_counts={},
            active_keys=[],
        )

    max_count = max(key_counts.values())
    top_keys = sorted(key for key, count in key_counts.items() if count == max_count)
    active_keys = sorted(key_counts)
    top_key = top_keys[0] if len(top_keys) == 1 else None
    top_ratio = max_count / num_agents

    if top_key is None:
        return RuntimeConsensusResult(
            consensus_reached=False,
            top_key=None,
            top_ratio=top_ratio,
            key_counts=key_counts,
            active_keys=active_keys,
        )

    if top_key == "UNKNOWN":
        reached = False
    else:
        reached = top_ratio >= threshold

    return RuntimeConsensusResult(
        consensus_reached=reached,
        top_key=top_key,
        top_ratio=top_ratio,
        key_counts=key_counts,
        active_keys=active_keys,
    )
