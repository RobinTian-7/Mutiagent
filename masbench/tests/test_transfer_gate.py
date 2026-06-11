"""M1 transfer gate: ledger, trust thresholds, deployment view, motif buckets."""

from __future__ import annotations

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

from masbench.transfer import (
    MIN_TRUST_ROWS,
    build_transfer_ledger,
    combine_bucket_stats,
    deployment_view,
    inject_transfer_evidence,
    motif_view,
    namespace_motif_keys,
    skill_trusted_for,
    snapshot_transfer_evidence,
)


def _row(topology: str, bucket: str, em: float) -> dict:
    return {"Topology": topology, "task_features_key": bucket, "ExactMatchRate": em}


def _skill(skill_id: str, topology: str, ledger: dict | None = None, spec: bool = True) -> SkillCard:
    policy: dict = {"topology_name": topology}
    if spec:
        policy["protocol_spec"] = {
            "name": topology,
            "n_agents": 5,
            "steps": [{"transmissions": [[0, 1]], "description": "x", "operator": "replay"}],
            "metadata": {},
        }
    if ledger is not None:
        policy["transfer_evidence"] = ledger
    return SkillCard(
        skill_id=skill_id,
        objective="balanced",
        task_family="silo",
        trigger={"task_family": "silo", "min_agents": 1, "max_agents": 999},
        organization_policy=policy,
        expected_tradeoff={"mean_primary_loss": 0.2, "active_evidence_count": 4},
        tags=["mas", "silo"],
    )


def test_ledger_aggregates_by_topology_and_bucket():
    rows = [
        _row("tree", "of", 1.0),
        _row("tree", "of", 0.0),
        _row("tree", "os", 0.0),
        _row("chain", "os", 1.0),
        {"Topology": "x"},  # no bucket -> ignored
    ]
    ledger = build_transfer_ledger(rows)
    assert ledger["tree"]["of"] == {"n": 2, "em_sum": 1.0}
    assert ledger["tree"]["os"] == {"n": 1, "em_sum": 0.0}
    assert ledger["chain"]["os"] == {"n": 1, "em_sum": 1.0}
    assert "x" not in ledger


def test_combine_bucket_stats_accumulates():
    a = {"of": {"n": 2, "em_sum": 1.0}}
    b = {"of": {"n": 1, "em_sum": 1.0}, "os": {"n": 2, "em_sum": 0.0}}
    out = combine_bucket_stats(a, b)
    assert out == {"of": {"n": 3, "em_sum": 2.0}, "os": {"n": 2, "em_sum": 0.0}}


def test_trust_thresholds():
    # One lucky row cannot earn deployment (phase-2 Bernoulli lesson).
    lucky = _skill("s1", "tree", {"of": {"n": 1, "em_sum": 1.0}})
    assert MIN_TRUST_ROWS >= 2
    assert not skill_trusted_for(lucky, "of")
    solid = _skill("s2", "tree", {"of": {"n": 2, "em_sum": 1.0}})
    assert skill_trusted_for(solid, "of")
    assert not skill_trusted_for(solid, "os")
    weak = _skill("s3", "tree", {"of": {"n": 4, "em_sum": 1.0}})  # mean 0.25
    assert not skill_trusted_for(weak, "of")


def test_inject_combines_with_prior_across_rounds():
    bank = SkillBank(skills=[_skill("tree_skill", "tree")])
    rows = [_row("tree", "of", 1.0), _row("tree", "of", 0.0)]
    inject_transfer_evidence(bank, rows)
    snap = snapshot_transfer_evidence(bank)
    assert snap["tree_skill"]["of"] == {"n": 2, "em_sum": 1.0}
    # Round 2: same skill identity, prior snapshot carries round-1 counts.
    rows2 = [_row("tree", "of", 1.0)]
    inject_transfer_evidence(bank, rows2, prior=snap)
    snap2 = snapshot_transfer_evidence(bank)
    assert snap2["tree_skill"]["of"] == {"n": 3, "em_sum": 2.0}


def test_deployment_view_abstains_to_exact_cold_inputs():
    bank = SkillBank(skills=[_skill("s", "tree", {"of": {"n": 4, "em_sum": 4.0}})])
    motif = {"of|fan_in:2": {"mean_loss": 0.1, "n": 4}}
    view, vmotif, abstained = deployment_view(bank, motif, "os")
    assert abstained is True
    assert len(view) == 0
    assert vmotif is None


def test_deployment_view_keeps_only_trusted_and_projects_motif():
    trusted = _skill("ok", "tree", {"os": {"n": 2, "em_sum": 2.0}})
    untrusted = _skill("nope", "mesh_star", {"of": {"n": 9, "em_sum": 9.0}})
    bank = SkillBank(skills=[trusted, untrusted])
    motif = {
        "os|fan_in:2": {"mean_loss": 0.1, "n": 4},
        "of|fan_in:9": {"mean_loss": 0.9, "n": 2},
    }
    view, vmotif, abstained = deployment_view(bank, motif, "os")
    assert abstained is False
    assert [s.skill_id for s in view] == ["ok"]
    assert vmotif == {"fan_in:2": {"mean_loss": 0.1, "n": 4}}


def test_deployment_view_off_mode_passthrough():
    bank = SkillBank(skills=[_skill("s", "tree", {"of": {"n": 1, "em_sum": 1.0}})])
    motif = {"raw_key": {"mean_loss": 0.5, "n": 1}}
    view, vmotif, abstained = deployment_view(bank, motif, "os", mode="off")
    assert abstained is False
    assert view is bank
    assert vmotif is motif


def test_motif_namespacing_roundtrip():
    keys = namespace_motif_keys(["a", "b"], "os")
    assert keys == ["os|a", "os|b"]
    stats = {"os|a": {"mean_loss": 0.0, "n": 1}, "of|a": {"mean_loss": 1.0, "n": 1}}
    assert motif_view(stats, "os") == {"a": {"mean_loss": 0.0, "n": 1}}
    assert motif_view(stats, "os-seg") is None  # nothing for the bucket
    assert motif_view(None, "os") is None
