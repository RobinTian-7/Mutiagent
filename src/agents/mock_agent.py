"""Mock agent for simulation without real LLM calls.

ASSUMPTION (A12): For simulation without real LLM calls, we provide a mock
agent that selects actions stochastically with biases matching paper's
observed distributions.

Paper evidence (Sec 5, Fig 6a):
  - Delegation and contradiction drive expansion
  - Merge is rarer and more constrained
  - Revision is intermediate
  - In larger cascades: delegation ~0.45, contradiction ~0.34, merge ~0.08
  - At median cascades: delegation ~0.30, contradiction ~0.21, merge ~0.19
"""

from __future__ import annotations

import random
import uuid

from src.schemas.claims import Claim, ClaimType
from src.schemas.events import Event, EventType


# ASSUMPTION (A12): action probabilities calibrated from paper Table in Appendix
# (tail anatomy, Table at App C.3). We use median-cascade proportions as default.
DEFAULT_ACTION_PROBS = {
    EventType.DELEGATE_SUBTASK: 0.25,
    EventType.REVISE_CLAIM: 0.25,
    EventType.CONTRADICT_CLAIM: 0.20,
    EventType.MERGE_CLAIMS: 0.15,
    EventType.PROPOSE_CLAIM: 0.15,
}


def mock_agent_action(
    agent_id: str,
    visible_claims: list[Claim],
    selected_claim: Claim | None,
    subtask_id: str | None = None,
    action_probs: dict[EventType, float] | None = None,
) -> tuple[Event, Claim]:
    """Generate a mock coordination action.

    Returns an (Event, Claim) pair representing the agent's action.
    """
    probs = action_probs or DEFAULT_ACTION_PROBS

    # If no visible claims, must propose
    if not visible_claims or selected_claim is None:
        action = EventType.PROPOSE_CLAIM
    else:
        # Merge requires at least 2 visible claims
        effective_probs = dict(probs)
        if len(visible_claims) < 2:
            merge_p = effective_probs.pop(EventType.MERGE_CLAIMS, 0)
            # Redistribute merge probability
            remaining = sum(effective_probs.values())
            if remaining > 0:
                for k in effective_probs:
                    effective_probs[k] += merge_p * (effective_probs[k] / remaining)

        actions = list(effective_probs.keys())
        weights = [effective_probs[a] for a in actions]
        action = random.choices(actions, weights=weights, k=1)[0]

    claim_id = f"claim_{uuid.uuid4().hex[:8]}"
    event_id = f"evt_{uuid.uuid4().hex[:8]}"

    # Build claim and event based on action type
    if action == EventType.PROPOSE_CLAIM:
        claim = Claim(
            claim_id=claim_id,
            agent_id=agent_id,
            subtask_id=subtask_id,
            content=f"[Proposed by {agent_id}]",
            claim_type=ClaimType.PROPOSED,
            parent_claim_ids=[],
            root_claim_id=claim_id,
            claim_depth=0,
        )
        event = Event(
            event_id=event_id,
            agent_id=agent_id,
            event_type=action,
            claim_id=claim_id,
            root_claim_id=claim_id,
        )

    elif action == EventType.REVISE_CLAIM:
        parent = selected_claim
        claim = Claim(
            claim_id=claim_id,
            agent_id=agent_id,
            subtask_id=subtask_id,
            content=f"[Revision of {parent.claim_id} by {agent_id}]",
            claim_type=ClaimType.REVISED,
            parent_claim_ids=[parent.claim_id],
            root_claim_id=parent.root_claim_id,
            claim_depth=parent.claim_depth + 1,
        )
        event = Event(
            event_id=event_id,
            agent_id=agent_id,
            event_type=action,
            claim_id=claim_id,
            target_claim_id=parent.claim_id,
            parent_claim_ids=[parent.claim_id],
            root_claim_id=parent.root_claim_id,
        )

    elif action == EventType.CONTRADICT_CLAIM:
        parent = selected_claim
        claim = Claim(
            claim_id=claim_id,
            agent_id=agent_id,
            subtask_id=subtask_id,
            content=f"[Contradiction of {parent.claim_id} by {agent_id}]",
            claim_type=ClaimType.CONTRADICTORY,
            parent_claim_ids=[parent.claim_id],
            root_claim_id=parent.root_claim_id,
            claim_depth=parent.claim_depth + 1,
        )
        event = Event(
            event_id=event_id,
            agent_id=agent_id,
            event_type=action,
            claim_id=claim_id,
            target_claim_id=parent.claim_id,
            parent_claim_ids=[parent.claim_id],
            root_claim_id=parent.root_claim_id,
        )

    elif action == EventType.MERGE_CLAIMS:
        # Select 2-3 claims to merge from visible claims
        n_merge = min(random.randint(2, 3), len(visible_claims))
        merge_parents = random.sample(visible_claims, n_merge)
        parent_ids = [c.claim_id for c in merge_parents]
        # Root is inherited from the first parent (conservative assumption)
        root_id = merge_parents[0].root_claim_id
        max_depth = max(c.claim_depth for c in merge_parents)
        claim = Claim(
            claim_id=claim_id,
            agent_id=agent_id,
            subtask_id=subtask_id,
            content=f"[Merge of {parent_ids} by {agent_id}]",
            claim_type=ClaimType.MERGED,
            parent_claim_ids=parent_ids,
            root_claim_id=root_id,
            claim_depth=max_depth + 1,
        )
        event = Event(
            event_id=event_id,
            agent_id=agent_id,
            event_type=action,
            claim_id=claim_id,
            parent_claim_ids=parent_ids,
            root_claim_id=root_id,
        )

    elif action == EventType.DELEGATE_SUBTASK:
        # Delegation creates a new claim in a new subtask context
        parent = selected_claim
        parent_ids = [parent.claim_id] if parent else []
        root_id = parent.root_claim_id if parent else claim_id
        depth = (parent.claim_depth + 1) if parent else 0
        claim = Claim(
            claim_id=claim_id,
            agent_id=agent_id,
            subtask_id=f"subtask_{uuid.uuid4().hex[:8]}",
            content=f"[Delegated from {parent.claim_id if parent else 'root'} by {agent_id}]",
            claim_type=ClaimType.PROPOSED,
            parent_claim_ids=parent_ids,
            root_claim_id=root_id,
            claim_depth=depth,
        )
        event = Event(
            event_id=event_id,
            agent_id=agent_id,
            event_type=action,
            claim_id=claim_id,
            target_claim_id=parent.claim_id if parent else None,
            target_subtask_id=claim.subtask_id,
            parent_claim_ids=parent_ids,
            root_claim_id=root_id,
        )
    else:
        raise ValueError(f"Unknown action type: {action}")

    return event, claim
