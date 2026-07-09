"""Deficit-Triggered Integration (DTI).

Paper reference (Sec 6, Appendix C, Algorithm 1):

DTI is a cascade-local intervention that monitors the imbalance between
exploration and integration and triggers integration when this imbalance
exceeds a condition-specific threshold.

Per-cascade state: (t_r, M_r) where
  t_r = coordination events elapsed in active cascade segment
  M_r = realized merge events in current cascade segment

Exploration pressure (Eq. A4):
  P_r(t_r) = a_c * t_r^{β̂_c}

Integration deficit (Eq. A5):
  Δ_r(t_r) = P_r(t_r) - M_r

Trigger condition (Eq. A6):
  Δ_r(t_r) > δ_c

On trigger:
  1. Collect active branch heads B_r = ActiveBranches(r)
  2. Invoke integration over B_r → merged claim
  3. Log as merge event
  4. Reset: t_r ← 0, M_r ← 1

ASSUMPTION (A9): β̂_c defaults to 0.15.
ASSUMPTION (A10): a_c defaults to 0.1, δ_c defaults to 3.0.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.schemas.claims import Claim, ClaimType
from src.schemas.events import Event, EventType


@dataclass
class DTIConfig:
    """Configuration for DTI intervention.

    Paper: "The parameters a_c and δ_c are estimated directly from baseline
    coordination traces for each condition class."

    ASSUMPTION (A10): Defaults are conservative estimates.
    """

    # Contradiction scaling exponent (β̂_c in paper)
    beta_c: float = 0.15
    # Normalization constant per condition class
    a_c: float = 0.1
    # Condition-specific deficit threshold
    # Paper: "δ_c = mean + 1σ of integration deficit at cascade termination"
    delta_c: float = 3.0


class DTIMonitor:
    """Per-cascade DTI state tracker.

    Paper Algorithm 1: "For each active root claim r, initialize local
    cascade state: t_r ← 0, M_r ← 0"

    Memory: O(|R|) where R = active cascades.
    Each event: constant-time updates to (t_r, M_r).
    """

    def __init__(self, config: DTIConfig | None = None):
        self.config = config or DTIConfig()

    def process_event(
        self,
        root_claim_id: str,
        is_merge: bool,
        dti_state: dict[str, tuple[int, int]],
    ) -> Optional[str]:
        """Process a single event and check DTI trigger.

        Paper Algorithm 1 lines 4-18.

        Args:
            root_claim_id: root claim of the cascade
            is_merge: whether the event is a merge event
            dti_state: mutable dict of root_id -> (t_r, M_r)

        Returns:
            root_claim_id if DTI triggered, None otherwise.
        """
        # Initialize cascade state if new
        t_r, m_r = dti_state.get(root_claim_id, (0, 0))

        # Update cascade length (Algorithm 1, line 6)
        t_r += 1

        # Update merge count if applicable (Algorithm 1, lines 7-8)
        if is_merge:
            m_r += 1

        dti_state[root_claim_id] = (t_r, m_r)

        # Compute exploration pressure (Algorithm 1, line 9; Eq. A4)
        p_r = self.config.a_c * (t_r ** self.config.beta_c)

        # Compute integration deficit (Algorithm 1, line 10; Eq. A5)
        delta_r = p_r - m_r

        # Check trigger condition (Algorithm 1, line 11; Eq. A6)
        if delta_r > self.config.delta_c:
            return root_claim_id

        return None


def get_active_branch_heads(
    root_claim_id: str,
    claims: list[Claim],
) -> list[Claim]:
    """Collect active branch heads for a cascade.

    Paper Algorithm 1, line 12:
    "B_r ← ActiveBranches(r): most recent branch-head outputs
     causally attached to root claim r"

    A branch head is a claim in the cascade that is not a parent of
    any other claim (i.e., a leaf in the claim DAG).
    """
    cascade_claims = [c for c in claims if c.root_claim_id == root_claim_id]
    if not cascade_claims:
        return []

    # Find claims that are not referenced as parents by other claims
    all_parent_ids = set()
    for c in cascade_claims:
        all_parent_ids.update(c.parent_claim_ids)

    branch_heads = [c for c in cascade_claims if c.claim_id not in all_parent_ids]
    return branch_heads if branch_heads else cascade_claims[-1:]


def create_dti_merge_event(
    root_claim_id: str,
    claims: list[Claim],
    agent_id: str,
    step_id: int = 0,
) -> tuple[Event, Claim]:
    """Create a DTI-triggered merge event.

    Paper Algorithm 1, lines 13-15:
    "Invoke integration over B_r to produce merged claim ẽ.
     Log ẽ as a merge event attached to root claim r.
     Broadcast ẽ as updated shared context."
    """
    branch_heads = get_active_branch_heads(root_claim_id, claims)
    parent_ids = [c.claim_id for c in branch_heads]

    if not parent_ids:
        # Fallback: use the root claim itself
        parent_ids = [root_claim_id]

    claim_id = f"claim_dti_{uuid.uuid4().hex[:8]}"
    event_id = f"evt_dti_{uuid.uuid4().hex[:8]}"

    max_depth = max((c.claim_depth for c in branch_heads), default=0)

    # ASSUMPTION (A8): merge prompt produces a synthesis of branch heads
    merge_claim = Claim(
        claim_id=claim_id,
        agent_id=agent_id,
        content=f"[DTI merge of {len(parent_ids)} branch heads for cascade {root_claim_id}]",
        claim_type=ClaimType.MERGED,
        parent_claim_ids=parent_ids,
        root_claim_id=root_claim_id,
        claim_depth=max_depth + 1,
    )

    merge_event = Event(
        event_id=event_id,
        agent_id=agent_id,
        event_type=EventType.MERGE_CLAIMS,
        claim_id=claim_id,
        parent_claim_ids=parent_ids,
        root_claim_id=root_claim_id,
        step_id=step_id,
    )

    return merge_event, merge_claim
