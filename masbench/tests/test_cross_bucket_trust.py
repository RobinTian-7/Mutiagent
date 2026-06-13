"""M28 (DISABLED -- recorded negative result): cross-bucket generalist trust.

M28 tried to keep one_peer trusted when its single os anchor (II-13) drifts
to failure. The same-window A/B + draw2 forensics DISPROVED it: it ballooned
os-trusted candidates 2->9 (rescuing of-overfit staged_* on 2 cases),
diluting retrieval so an of-overfit org beat the os-direct-trusted one_peer
and gen crashed to 4.2%. It ships DISABLED (flag default False). These tests
pin (a) that it ships disabled and (b) what the rescue logic did when on, so
the negative result is documented and re-checkable.
"""

from __future__ import annotations

import pytest

from exp_graph.mas.schemas import SkillCard
import masbench.transfer as T
from masbench.transfer import skill_trusted_for


@pytest.fixture
def enable_m28(monkeypatch):
    monkeypatch.setattr(T, "_M28_CROSS_BUCKET_RESCUE", True)


def _card(evidence):
    return SkillCard(
        skill_id="s", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy={"planner_mode": "graph_generate",
                             "topology_name": "generated:org",
                             "transfer_evidence": evidence},
        expected_tradeoff={"mean_primary_loss": 0.0}, confidence={}, tags=["mas"],
    )


def test_m28_ships_disabled():
    assert T._M28_CROSS_BUCKET_RESCUE is False, "M28 must ship disabled (harmful)"


def test_disabled_does_not_rescue():
    # default behavior: single-anchor os failure DOES veto, even a generalist
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is False


def test_generalist_rescued_when_enabled(enable_m28):
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "of#lossless-scalar": {"n": 20, "em_sum": 10.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is True


def test_non_generalist_not_rescued_even_when_enabled(enable_m28):
    card = _card({
        "of": {"n": 1, "em_sum": 0.0, "cases": ["I-07"]},
        "of#lossless-scalar": {"n": 1, "em_sum": 0.0, "cases": ["I-07"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is False


def test_os_direct_pass_unaffected_by_flag():
    # os directly passes -> trusted regardless of the flag (the real path)
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 8, "em_sum": 8.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 8, "em_sum": 8.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is True
