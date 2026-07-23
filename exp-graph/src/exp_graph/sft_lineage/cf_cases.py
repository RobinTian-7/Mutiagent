"""Tiered Count Frequency case bank for verified-lineage training.

SiloBench gives the SFTBank pipeline a fixed benchmark tree with difficulty
tiers baked into the case ids (``I-…``/``II-…``/``III-…``).  CF has no such
tree — instances are generated — so this module IS the benchmark: a
deterministic bank of cases whose ids carry the same tier prefix contract the
law layer keys on (``mint_task_sequence``, ``envelope_cases``,
``review_cases`` all split on ``case_id.split("-")[0]``).

Difficulty scales along the CF axes that actually stress an LLM merge
operator: array length (how much evidence must survive aggregation) and
value range (how many distinct keys the frequency table carries).  A case is
only a parameter bundle; the concrete array is drawn from
``content_seed_base + run_seed``, so train duels (``CARD_SEED_BASE``) and
the one-shot TEST (``TEST_SEED_BASE``) never see the same array even when
they share a case.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# array_size, value_min, value_max per tier.  Tier III matches the repo's
# main CF experiment profile (5000 values in 1..1000).
DEFAULT_TIER_SPECS: dict[str, tuple[int, int, int]] = {
    "I": (400, 1, 40),
    "II": (2000, 1, 300),
    "III": (5000, 1, 1000),
}


@dataclass(frozen=True)
class CFCase:
    """One frozen CF benchmark case (parameters only, no data)."""

    case_id: str
    tier: str
    array_size: int
    value_min: int
    value_max: int
    content_seed_base: int

    def task_kwargs(self, run_seed: int) -> dict[str, Any]:
        """Kwargs for ``CountFrequencyTaskAdapter.build_global_task``."""

        return {
            "array_size": self.array_size,
            "value_min": self.value_min,
            "value_max": self.value_max,
            "seed": self.content_seed_base + int(run_seed),
        }


def _content_seed_base(case_id: str) -> int:
    digest = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    # Leave the full run-seed range clear below the per-case offset so
    # (case, run_seed) pairs can never collide across cases.
    return int(digest[:8], 16) * 1_000_000


def parse_tier_specs(raw: str | None) -> dict[str, tuple[int, int, int]]:
    """Parse a ``--tier-spec`` JSON override into tier parameter bundles."""

    if not raw:
        return dict(DEFAULT_TIER_SPECS)
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not payload:
        raise ValueError("--tier-spec must be a non-empty JSON object")
    specs: dict[str, tuple[int, int, int]] = {}
    for tier, params in payload.items():
        if not isinstance(params, list) or len(params) != 3:
            raise ValueError(
                "--tier-spec values must be [array_size, value_min, value_max]"
            )
        array_size, value_min, value_max = (int(item) for item in params)
        if array_size < 1 or value_max < value_min:
            raise ValueError(f"--tier-spec tier {tier!r} is not satisfiable")
        specs[str(tier)] = (array_size, value_min, value_max)
    return specs


def build_case_bank(
    *,
    cases_per_tier: int = 6,
    tier_specs: dict[str, tuple[int, int, int]] | None = None,
) -> dict[str, CFCase]:
    """Deterministic case bank, insertion-ordered I.. then II.. then III.."""

    if cases_per_tier < 1:
        raise ValueError("cases_per_tier must be positive")
    specs = tier_specs or DEFAULT_TIER_SPECS
    bank: dict[str, CFCase] = {}
    for tier in sorted(specs, key=lambda name: (len(name), name)):
        array_size, value_min, value_max = specs[tier]
        for index in range(cases_per_tier):
            case_id = f"{tier}-cf{index:02d}"
            bank[case_id] = CFCase(
                case_id=case_id,
                tier=tier,
                array_size=array_size,
                value_min=value_min,
                value_max=value_max,
                content_seed_base=_content_seed_base(case_id),
            )
    return bank


def split_case_bank(
    bank: dict[str, CFCase], *, test_count: int
) -> tuple[list[str], tuple[str, ...]]:
    """Deterministic train/TEST split, TEST drawn tier-balanced from the end.

    Mirrors the pilot's ``split_cases`` contract: the TEST holdout is frozen
    up front and the training pool is everything else, so no case can drift
    between roles across resumes.
    """

    by_tier: dict[str, list[str]] = {}
    for case_id, case in bank.items():
        by_tier.setdefault(case.tier, []).append(case_id)
    tiers = sorted(by_tier, key=lambda name: (len(name), name))
    test: list[str] = []
    depth = 1
    while len(test) < test_count and any(
        depth <= len(by_tier[tier]) for tier in tiers
    ):
        for tier in tiers:
            if len(test) >= test_count:
                break
            cases = by_tier[tier]
            if depth <= len(cases) - 1:  # never drain a tier's training pool
                test.append(cases[-depth])
        depth += 1
    test_ids = tuple(sorted(test))
    train = [case_id for case_id in bank if case_id not in set(test_ids)]
    return train, test_ids


def group_by_tier(
    bank: dict[str, CFCase], train_pool: list[str]
) -> tuple[dict[str, list[str]], list[str]]:
    """Training pool grouped by tier, in first-seen tier order."""

    by_tier: dict[str, list[str]] = {}
    tier_order: list[str] = []
    for case_id in train_pool:
        tier = bank[case_id].tier
        if tier not in by_tier:
            by_tier[tier] = []
            tier_order.append(tier)
        by_tier[tier].append(case_id)
    return by_tier, tier_order


def task_statement(case: CFCase, *, n_agents: int, goal: str) -> str:
    """The sanitized statement both the planner and the agents may see.

    Parameters only — never the array, the shards, or the answer table.
    """

    if goal == "sink":
        goal_line = (
            f"The team must end with ONE designated sink agent (agent "
            f"{n_agents - 1}, the highest id) holding the exact global "
            "frequency table; only the sink's final table is scored."
        )
    else:
        goal_line = (
            "Every agent must end holding the exact global frequency table."
        )
    return (
        "Count the frequency of every distinct integer in a hidden global "
        f"array of length {case.array_size} with values in "
        f"[{case.value_min}, {case.value_max}]. The array is split into "
        f"{n_agents} disjoint shards and each agent privately holds exactly "
        f"one shard. {goal_line}"
    )


def task_view(case: CFCase, *, n_agents: int, goal: str) -> dict[str, Any]:
    """The planner-visible slice of one TRAIN case.

    Structurally answer-free: the statement is built from case parameters,
    so the planner cannot leak shard contents or the answer table — it never
    sees them.
    """

    return {
        "tier": case.tier,
        "n_agents": n_agents,
        "shard_count": n_agents,
        "task_statement": task_statement(case, n_agents=n_agents, goal=goal),
    }
