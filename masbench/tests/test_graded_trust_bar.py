"""M22: currency-aware comparative trust bar (jssp-v3 forensics).

JSSP v3 abstained on every deployment across all rounds: no schedule org
ever averaged the absolute 0.5 bar designed for binary EM, even orgs
clearly better than cold (0.3 vs 0.05). Binary slots keep MIN_TRUST_EM
byte-identically (all Silo rows are binary); graded slots pass by beating
the bucket's pooled all-org mean by GRADED_TRUST_MARGIN above an absolute
floor.
"""

from __future__ import annotations

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank
from masbench.transfer import (
    _slot_passes,
    build_transfer_ledger,
    inject_transfer_evidence,
    skill_trusted_for,
)


def test_binary_slots_keep_absolute_bar():
    assert _slot_passes({"n": 4, "em_sum": 2.0}) is True          # mean .5
    assert _slot_passes({"n": 4, "em_sum": 1.0}) is False         # mean .25
    # even with a terrible pool, binary stays absolute
    assert _slot_passes({"n": 4, "em_sum": 1.0}, {"n": 8, "em_sum": 0.0}) is False


def test_graded_slot_passes_comparatively():
    graded = {"n": 4, "em_sum": 1.4, "graded": True}              # mean .35
    weak_pool = {"n": 12, "em_sum": 1.2, "graded": True}          # mean .10
    strong_pool = {"n": 12, "em_sum": 3.6, "graded": True}        # mean .30
    assert _slot_passes(graded, weak_pool) is True                # .35 >= .10+.15
    assert _slot_passes(graded, strong_pool) is False             # .35 < .30+.15
    assert _slot_passes(graded, None) is False                    # no pool, no pass
    # floor: better than pool but absurdly low absolute quality
    low = {"n": 4, "em_sum": 0.6, "graded": True}                 # mean .15
    zero_pool = {"n": 8, "em_sum": 0.0, "graded": True}
    assert _slot_passes(low, zero_pool) is False                  # below 0.2 floor
    # graded slot that clears the absolute bar needs no pool
    assert _slot_passes({"n": 4, "em_sum": 2.4, "graded": True}) is True


def _row(case, value, topo="generated:org"):
    return {"Topology": topo, "task_features_key": "of",
            "task_needs_lossless": True, "task_answer_composite": True,
            "case_id": case, "ExactMatchRate": 0.0, "MeanPrimaryMetric": value}


def test_pool_accumulates_and_flows_to_cards():
    rows = [
        _row("synA", 0.4), _row("synB", 0.5),                     # our org: mean .45
        _row("synA", 0.05, topo="generated:other"),               # the field: weak
        _row("synB", 0.05, topo="generated:other"),
    ]
    ledger = build_transfer_ledger(rows)
    pool = ledger["__pool__"]["of"]
    assert pool["n"] == 4 and abs(pool["em_sum"] - 1.0) < 1e-9 and pool["graded"]

    card = SkillCard(
        skill_id="s1", objective="balanced", task_family="jssp",
        trigger={"task_family": "jssp"},
        organization_policy={"planner_mode": "graph_generate",
                             "topology_name": "generated:org"},
        expected_tradeoff={"mean_primary_loss": 0.0}, confidence={}, tags=["mas"],
    )
    bank = SkillBank(skills=[card])
    inject_transfer_evidence(bank, rows)
    ev = card.organization_policy["transfer_evidence"]
    assert "__pool__:of" in ev
    # graded comparative trust on the DIRECT slot: org mean .45 vs
    # pool .25 + margin .15 = .40 -> trusted
    assert skill_trusted_for(card, "of", "lossless-composite") is True


def test_weak_graded_org_stays_untrusted():
    rows = [
        _row("synA", 0.10), _row("synB", 0.12),                   # our org ~ pool
        _row("synA", 0.10, topo="generated:other"),
        _row("synB", 0.10, topo="generated:other"),
    ]
    card = SkillCard(
        skill_id="s1", objective="balanced", task_family="jssp",
        trigger={"task_family": "jssp"},
        organization_policy={"planner_mode": "graph_generate",
                             "topology_name": "generated:org"},
        expected_tradeoff={"mean_primary_loss": 0.0}, confidence={}, tags=["mas"],
    )
    inject_transfer_evidence(SkillBank(skills=[card]), rows)
    assert skill_trusted_for(card, "of", "lossless-composite") is False
