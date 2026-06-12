"""M11: structural identity for the trust ledger + family merge (M13c).

dev-5 gen forensics: generated organizations carry per-run NAMES, so a
name-keyed ledger split one structure's successes into n=1 fragments that
never reached the n>=2 trust bar, and the bank grew linearly (9->13->15)
with same-structure duplicates.
"""

from __future__ import annotations

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

from masbench.transfer import (
    TRANSFER_EVIDENCE_KEY,
    build_transfer_ledger,
    inject_transfer_evidence,
    merge_structural_duplicates,
    skill_identity,
    spec_struct_hash,
)

_SPEC = {
    "name": "anything",
    "n_agents": 3,
    "steps": [
        {"transmissions": [[0, 2], [1, 2]], "description": "gather", "operator": "replay"},
    ],
    "metadata": {"graph_type": "temporal_dag", "selected_primary": 2},
}


def _spec(name: str) -> dict:
    return {**_SPEC, "name": name}


def _row(topology: str, spec: dict | None, lossless: bool, em: float) -> dict:
    return {
        "Topology": topology, "protocol_spec": spec,
        "task_features_key": "os", "task_needs_lossless": lossless,
        "ExactMatchRate": em,
    }


def _skill(skill_id: str, topology: str, spec: dict | None, ledger: dict | None = None) -> SkillCard:
    policy: dict = {"topology_name": topology, "protocol_spec": spec}
    if ledger:
        policy[TRANSFER_EVIDENCE_KEY] = ledger
    return SkillCard(
        skill_id=skill_id, objective="balanced", task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy=policy,
        expected_tradeoff={"mean_primary_loss": 0.3},
        tags=["mas", "silo"],
    )


def test_same_structure_different_names_share_one_ledger_row_pool():
    rows = [
        _row("generated:staged_pair_gather", _spec("staged_pair_gather"), True, 1.0),
        _row("generated:pairwise_merge_sink", _spec("pairwise_merge_sink"), True, 1.0),
    ]
    ledger = build_transfer_ledger(rows)
    # M22 adds a reserved "__pool__" baseline entry; identity pooling is
    # asserted over the non-reserved keys.
    identities = {k: v for k, v in ledger.items() if k != "__pool__"}
    assert len(identities) == 1, "structurally identical rows must pool"
    (identity, slots), = identities.items()
    assert identity == spec_struct_hash(_SPEC)
    assert slots["os"]["n"] == 2 and slots["os"]["em_sum"] == 2.0
    assert slots["os#lossless-scalar"]["n"] == 2
    assert slots["os#lossless-scalar"]["em_sum"] == 2.0


def test_rows_without_spec_fall_back_to_name():
    rows = [_row("chain", None, True, 1.0)]
    assert "chain" in build_transfer_ledger(rows)


def test_inject_matches_skill_by_structure_not_name():
    skill = _skill("silo__x__differently_named", "generated:other_label", _spec("other_label"))
    bank = SkillBank(skills=[skill])
    rows = [
        _row("generated:staged_pair_gather", _spec("staged_pair_gather"), True, 1.0),
        _row("generated:pairwise_merge_sink", _spec("pairwise_merge_sink"), True, 1.0),
    ]
    inject_transfer_evidence(bank, rows)
    ledger = skill.organization_policy[TRANSFER_EVIDENCE_KEY]
    assert ledger["os#lossless-scalar"] == {"n": 2, "em_sum": 2.0}


def test_merge_structural_duplicates_keeps_veteran_and_combines():
    veteran = _skill(
        "vet", "generated:a", _spec("a"),
        {"os": {"n": 4, "em_sum": 3.0}, "os#lossless-scalar": {"n": 4, "em_sum": 3.0}},
    )
    newcomer = _skill(
        "new", "generated:b", _spec("b"),
        {"os": {"n": 1, "em_sum": 1.0}, "os#lossless-scalar": {"n": 1, "em_sum": 1.0}},
    )
    other = _skill("other", "chain", None, {"os": {"n": 2, "em_sum": 1.0}})
    bank = SkillBank(skills=[veteran, newcomer, other])
    removed = merge_structural_duplicates(bank)
    assert removed == 1
    ids = sorted(s.skill_id for s in bank)
    assert ids == ["other", "vet"]
    merged = veteran.organization_policy[TRANSFER_EVIDENCE_KEY]
    assert merged["os"] == {"n": 5, "em_sum": 4.0}
    assert veteran.organization_policy["absorbed_skill_ids"] == ["new"]
    assert skill_identity(veteran) == spec_struct_hash(_SPEC)


def test_rule_actions_stamped():
    from masbench.transfer import stamp_rule_actions
    from exp_graph.mas.schemas import SkillCard

    avoid = SkillCard(
        skill_id="cf_avoid_x", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"}, organization_policy={"topology_name": "x"},
        tags=["counterexample"],
    )
    spec_card = _skill("s_spec", "t", _spec("t"))
    prose = SkillCard(
        skill_id="prose", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"}, organization_policy={"topology_name": "y"},
        tags=["mas"],
    )
    bank = SkillBank(skills=[avoid, spec_card, prose])
    stamp_rule_actions(bank)
    assert avoid.organization_policy["rule_action"] == "avoid"
    assert spec_card.organization_policy["rule_action"] == "preserve"
    assert prose.organization_policy["rule_action"] == "context"
