"""Deterministic task-context features from the task TEXT (phase 3, M1).

The phase-2 boundary finding: executable-spec replay deploys one learned
organization onto every held-out case, and when the test case's information-
flow demands differ from every case the organization was earned on, blind
replay is a net harm (P2 dev round 3: ``generated:tree_reduce_to_sink``
replayed onto II-16 scored 0/8 while cold generation scored 1/8).

These features condition deployment on the TASK, using only the task
description text -- the same text the agents themselves receive. The
benchmark's internal ``paradigm`` label is never read at run time (it is used
only as offline ground truth in the tests).

Feature vocabulary (kept deliberately coarse so evidence per bucket
accumulates quickly):

* ``order_sensitive`` -- the task statement binds agents to positions in a
  sequence (segment ordering, neighbor exchange, pipeline). Silo level-II
  statements all carry explicit markers ("Agent Ordering", "CONSECUTIVE",
  "Position {agent_id}", a numbered chain); level-I statements never do.
* ``per_agent_output`` -- each agent must submit its OWN portion of the
  answer (segmented scoring) instead of one shared global answer. A
  sink-collect organization is structurally unable to put the right answer
  in every agent unless it redistributes.

``feature_key`` collapses the features into a small bucket id used by the
transfer-evidence ledger: ``of`` (order-free), ``os`` (order-sensitive,
shared answer), plus the ``-seg`` suffix when each agent answers for itself.

Borrowed designs (citations for the round report): task-conditioned skill
retrieval (Voyager's task-similarity retrieval; AWM's induced workflows
applied to matching task types; SkillGraph arXiv:2605.12039 argues retrieval
must be task/structure-conditioned, not similarity-only) and an explicit
SKIP/abstain route when nothing matches (SkillLens arXiv:2605.08386 routes
each skill unit to ACCEPT/DECOMPOSE/REWRITE/SKIP; our abstention is SKIP at
whole-organization granularity, falling back to the exact cold path).
"""

from __future__ import annotations

import re
from typing import Any

# Markers of position-bound agents. Case-sensitive on purpose where Silo
# shouts (CONSECUTIVE), case-insensitive for prose variants.
_ORDER_PATTERNS = (
    re.compile(r"agent ordering", re.IGNORECASE),
    re.compile(r"CONSECUTIVE"),
    re.compile(r"consecutive (segments?|parts?|elements?|blocks?)", re.IGNORECASE),
    re.compile(r"position \{agent_id\}", re.IGNORECASE),
    re.compile(r"sequential(ly| segments?)", re.IGNORECASE),
    re.compile(r"logical chain", re.IGNORECASE),
    re.compile(r"agent 0 (?:→|->|↔|<->) ?agent 1", re.IGNORECASE),
)

# Markers that every agent submits its OWN slice of the answer.
_PER_AGENT_PATTERNS = (
    re.compile(r"each agent submits? (their|its) (own |)?(portion|segment|part)", re.IGNORECASE),
    re.compile(r"submits? their own final segment", re.IGNORECASE),
)


def extract_task_features(task_text: str | None) -> dict[str, bool]:
    """Boolean task features from the statement text only."""
    text = task_text or ""
    return {
        "order_sensitive": any(p.search(text) for p in _ORDER_PATTERNS),
        "per_agent_output": any(p.search(text) for p in _PER_AGENT_PATTERNS),
    }


def feature_key(features: dict[str, Any]) -> str:
    """Canonical coarse bucket id for a feature dict."""
    base = "os" if features.get("order_sensitive") else "of"
    if features.get("per_agent_output"):
        return f"{base}-seg"
    return base


def instance_feature_key(instance: Any) -> str:
    """Feature bucket of a BenchmarkInstance (text-only; never reads labels)."""
    return feature_key(extract_task_features(getattr(instance, "task_prompt", "") or ""))
