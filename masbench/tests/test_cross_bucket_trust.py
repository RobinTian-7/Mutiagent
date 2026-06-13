"""M28: cross-bucket generalist trust survives single-anchor failure.

hi-power forensics: at n=5 the os bucket has one training anchor (II-13);
its verdict swings 0..1.0 across drift windows. A single-anchor failure
must not veto a CROSS-BUCKET GENERALIST (e.g. one_peer holds of=0.67 over
3 cases every window). A non-generalist (staged_pair_gather: of single-case
em0) is NOT rescued -- the distinction is structural, not name-based.
"""

from __future__ import annotations

from exp_graph.mas.schemas import SkillCard
from masbench.transfer import skill_trusted_for


def _card(evidence):
    return SkillCard(
        skill_id="s", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy={"planner_mode": "graph_generate",
                             "topology_name": "generated:org",
                             "transfer_evidence": evidence},
        expected_tradeoff={"mean_primary_loss": 0.0}, confidence={}, tags=["mas"],
    )


def test_generalist_rescued_on_single_anchor_os_failure():
    # of: 3 cases, 0.67 (diverse-earn) ; os: single anchor II-13, failed 0/10
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "of#lossless-scalar": {"n": 20, "em_sum": 10.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
    })
    # os single-anchor failure does NOT veto the of-generalist
    assert skill_trusted_for(card, "os", "lossless-scalar") is True
    assert skill_trusted_for(card, "os", "lossless-composite") is True


def test_non_generalist_not_rescued():
    # of single case em0 -> NOT a generalist; os single anchor failed
    card = _card({
        "of": {"n": 1, "em_sum": 0.0, "cases": ["I-07"]},
        "of#lossless-scalar": {"n": 1, "em_sum": 0.0, "cases": ["I-07"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is False
    assert skill_trusted_for(card, "os", "lossless-composite") is False


def test_no_kind_no_rescue():
    # the rescue is kind-scoped (deployment slots); bare bucket query unaffected
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 10, "em_sum": 0.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(card, "os", None) is False


def test_multi_case_os_failure_still_vetoes():
    # if os itself were multi-anchor (not the n=5 reality) a real failure
    # there should still veto -- rescue is ONLY for single-anchor buckets
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 20, "em_sum": 2.0, "cases": ["II-13", "II-20"]},
        "os#lossless-scalar": {"n": 20, "em_sum": 2.0, "cases": ["II-13", "II-20"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is False


def test_generalist_with_passing_os_unchanged():
    # when os passes directly, behavior is the ordinary direct-trust path
    card = _card({
        "of": {"n": 30, "em_sum": 20.0, "cases": ["I-01", "I-04", "I-07"]},
        "os": {"n": 8, "em_sum": 8.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 8, "em_sum": 8.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(card, "os", "lossless-scalar") is True
