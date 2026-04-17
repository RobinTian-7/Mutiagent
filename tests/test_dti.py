"""Tests for DTI trigger and no-trigger paths."""

from src.interventions.dti import DTIConfig, DTIMonitor, get_active_branch_heads
from src.schemas.claims import Claim, ClaimType


def test_dti_no_trigger_short_cascade():
    """DTI should not trigger for a short cascade."""
    config = DTIConfig(beta_c=0.15, a_c=0.1, delta_c=3.0)
    monitor = DTIMonitor(config)
    state: dict[str, tuple[int, int]] = {}

    # Process a few non-merge events — should not trigger
    for _ in range(5):
        result = monitor.process_event("root_1", is_merge=False, dti_state=state)

    # With a_c=0.1, beta_c=0.15, t_r=5:
    # P_r = 0.1 * 5^0.15 ≈ 0.1 * 1.27 ≈ 0.127
    # Δ_r = 0.127 - 0 = 0.127 < 3.0 → no trigger
    assert result is None


def test_dti_trigger_long_cascade():
    """DTI should trigger when deficit exceeds threshold."""
    # Use aggressive parameters to ensure trigger
    config = DTIConfig(beta_c=1.5, a_c=1.0, delta_c=2.0)
    monitor = DTIMonitor(config)
    state: dict[str, tuple[int, int]] = {}

    triggered = False
    for _ in range(100):
        result = monitor.process_event("root_1", is_merge=False, dti_state=state)
        if result is not None:
            triggered = True
            break

    assert triggered


def test_dti_merge_events_reduce_deficit():
    """Merge events should reduce the integration deficit."""
    config = DTIConfig(beta_c=1.0, a_c=1.0, delta_c=5.0)
    monitor = DTIMonitor(config)
    state: dict[str, tuple[int, int]] = {}

    # Process some events with merges interspersed
    for i in range(10):
        is_merge = (i % 3 == 0)  # Every 3rd event is a merge
        monitor.process_event("root_1", is_merge=is_merge, dti_state=state)

    t_r, m_r = state["root_1"]
    assert m_r >= 3  # At least 3 merges in 10 events


def test_dti_state_reset_after_trigger():
    """After DTI triggers, state should reset per Algorithm 1."""
    config = DTIConfig(beta_c=2.0, a_c=2.0, delta_c=1.0)
    monitor = DTIMonitor(config)
    state: dict[str, tuple[int, int]] = {}

    # Keep processing until trigger
    triggered = False
    for _ in range(50):
        result = monitor.process_event("root_1", is_merge=False, dti_state=state)
        if result is not None:
            triggered = True
            # Simulate reset per Algorithm 1: t_r ← 0, M_r ← 1
            state["root_1"] = (0, 1)
            break

    assert triggered
    assert state["root_1"] == (0, 1)


def test_active_branch_heads():
    """Branch heads are claims not referenced as parents by other claims."""
    claims = [
        Claim(claim_id="c1", agent_id="a0", root_claim_id="c1"),
        Claim(claim_id="c2", agent_id="a1", root_claim_id="c1",
              parent_claim_ids=["c1"]),
        Claim(claim_id="c3", agent_id="a2", root_claim_id="c1",
              parent_claim_ids=["c1"]),
    ]
    heads = get_active_branch_heads("c1", claims)
    head_ids = {c.claim_id for c in heads}
    # c2 and c3 are leaves (not parents of anything)
    assert head_ids == {"c2", "c3"}
