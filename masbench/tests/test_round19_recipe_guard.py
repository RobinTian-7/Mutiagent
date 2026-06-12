"""M19 (dev-11 forensics): single-case skills must not hijack deployment.

dev-11: a recipe verified 2x on ONE train case (II-13) earned kind-wide
trust, won retrieval, shape-extrapolated onto composite slots, and zeroed
the whole curve. The epistemic line: evidence from ONE case may decide its
OWN slot (direct trust -- the dev-1 one_peer lineage depends on it), but it
may never EXTRAPOLATE (M16b shape-sibling, M8 breadth) nor outrank
multi-case incumbents on equal terms.
"""

from __future__ import annotations

from exp_graph.mas.schemas import SkillCard
from masbench.transfer import (
    build_transfer_ledger,
    combine_bucket_stats,
    inject_transfer_evidence,
    skill_trusted_for,
    slot_case_diversity,
)
from exp_graph.mas.skill_bank import SkillBank


def _row(case_id: str, kind: str, em: float = 1.0, lossless=True, composite=False):
    return {
        "Topology": "generated:test_org",
        "task_features_key": "os",
        "task_needs_lossless": lossless,
        "task_answer_composite": composite,
        "case_id": case_id,
        "ExactMatchRate": em,
    }


def test_ledger_tracks_distinct_cases():
    rows = [_row("II-13", "x"), _row("II-13", "x"), _row("II-15", "x")]
    ledger = build_transfer_ledger(rows)
    slots = ledger["generated:test_org"]
    assert slots["os"]["n"] == 3
    assert sorted(slots["os"]["cases"]) == ["II-13", "II-15"]
    assert slot_case_diversity(slots["os"]) == 2
    assert slot_case_diversity(slots["os#lossless-scalar"]) == 2


def test_combine_merges_cases():
    a = {"os": {"n": 2, "em_sum": 2.0, "cases": ["II-13"]}}
    b = {"os": {"n": 1, "em_sum": 1.0, "cases": ["II-15"]}}
    out = combine_bucket_stats(a, b)
    assert out["os"]["n"] == 3
    assert sorted(out["os"]["cases"]) == ["II-13", "II-15"]


def test_legacy_slot_without_cases_counts_as_single_case():
    # recipe cards pre-seed {n, em_sum} dicts; conservatively diversity=1
    assert slot_case_diversity({"n": 2, "em_sum": 2.0}) == 1
    assert slot_case_diversity({"n": 0, "em_sum": 0.0}) == 0


def _skill(evidence):
    return SkillCard(
        skill_id="s1",
        objective="balanced",
        task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy={
            "planner_mode": "graph_generate",
            "topology_name": "generated:test_org",
            "transfer_evidence": evidence,
        },
        expected_tradeoff={"mean_primary_loss": 0.0},
        confidence={},
        tags=["mas"],
    )


def test_single_case_skill_does_not_shape_extrapolate():
    # the dev-11 repro: a card whose ENTIRE evidence is one case (the recipe)
    # must not ride the shape-sibling hop onto composite slots
    sk = _skill({
        "os": {"n": 2, "em_sum": 2.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 2, "em_sum": 2.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(sk, "os", "lossless-scalar") is True  # direct kept
    assert not skill_trusted_for(sk, "os", "lossless-composite")  # no sibling hop


def test_globally_diverse_skill_keeps_shape_extrapolation():
    # the dev-10c winning path: one_peer's os scalar slot is single-case BY
    # GEOMETRY (II-13 is the only os anchor), but the artifact is exercised
    # across many 'of' cases -- the global robustness prior authorizes the
    # sibling hop (action stays auto-Modify downstream)
    sk = _skill({
        "of": {"n": 12, "em_sum": 8.0, "cases": ["I-01", "I-02", "I-06", "I-08"]},
        "of#lossy-scalar": {"n": 12, "em_sum": 8.0, "cases": ["I-01", "I-02", "I-06", "I-08"]},
        "os": {"n": 8, "em_sum": 5.0, "cases": ["II-13"]},
        "os#lossless-scalar": {"n": 8, "em_sum": 5.0, "cases": ["II-13"]},
    })
    assert skill_trusted_for(sk, "os", "lossless-composite") is True


def test_failing_sibling_blocks_at_any_diversity():
    sk = _skill({
        "of": {"n": 12, "em_sum": 8.0, "cases": ["I-01", "I-02", "I-06"]},
        "os": {"n": 8, "em_sum": 5.0, "cases": ["II-13", "II-14"]},
        "os#lossless-scalar": {"n": 8, "em_sum": 1.0, "cases": ["II-13", "II-14"]},
    })
    assert not skill_trusted_for(sk, "os", "lossless-composite")


def test_legacy_ledger_without_case_tracking_keeps_old_semantics():
    # snapshots that predate M19 carry no cases lists; the sibling hop keeps
    # its dev-10c behavior for them (recipes always carry provenance now)
    sk = _skill({
        "os": {"n": 8, "em_sum": 5.0},
        "os#lossless-scalar": {"n": 8, "em_sum": 5.0},
    })
    assert skill_trusted_for(sk, "os", "lossless-composite") is True


def test_inject_stamps_evidence_case_count():
    sk = _skill({})
    bank = SkillBank(skills=[sk])
    rows = [_row("II-13", "x"), _row("II-15", "x"), _row("I-01", "x")]
    inject_transfer_evidence(bank, rows)
    assert sk.expected_tradeoff["evidence_case_count"] == 3


def test_recipe_card_seeds_single_case_evidence():
    import json
    from masbench.recipes import parse_recipe, recipe_skill_card

    spec = parse_recipe(json.dumps({
        "name": "r", "selected_primary": 1,
        "steps": [{"edges": [[0, 1]], "instruction": "i"}],
    }), n_agents=2, max_steps=4)
    card = recipe_skill_card(
        spec, task_family="silo", bucket="os", lossless_slot="lossless-scalar",
        n_agents=2, verify_count=2, source_case_id="II-13",
    )
    ev = card.organization_policy["transfer_evidence"]
    assert ev["os"]["cases"] == ["II-13"]
    assert card.expected_tradeoff["evidence_case_count"] == 1
    # direct slot trusted, composite sibling NOT (the dev-11 hijack)
    assert skill_trusted_for(card, "os", "lossless-scalar") is True
    assert not skill_trusted_for(card, "os", "lossless-composite")
