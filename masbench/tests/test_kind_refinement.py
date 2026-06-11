"""M6: contradiction-triggered trust refinement to agg-kind granularity.

Dev-1 gen evidence: `staged_aggregate_to_sink` scored 1.00 (n=5) on I-03
(vote) and 0.17 (n=6) on I-05 (count) -- the bucket mean (0.55) earned it
of-bucket trust and it then deterministically failed the count-kind val case
every round, so the gate nuked the whole bank three times. Trust must live
at the coarsest granularity CONSISTENT with the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank
from masbench.task_features import agg_kind
from masbench.transfer import (
    build_transfer_ledger,
    deployment_view,
    skill_trusted_for,
)

BENCH_DIR = Path(__file__).resolve().parents[1] / "third_party" / "acl26-silo-bench" / "benchmarks"

# Hand-checked from the task statements (text-derived, no benchmark labels).
EXPECTED_KINDS = {
    "I-01": "max", "I-02": "count", "I-03": "vote", "I-04": "any",
    "I-05": "count", "I-06": "xor", "I-07": "mean", "I-08": "count",
    "I-09": "topk", "I-10": "stats",
    "II-11": "seq", "II-12": "seq", "II-13": "seq", "II-14": "seq",
    "II-15": "seq", "II-16": "seq", "II-17": "seq", "II-18": "seq",
    "II-19": "set", "II-20": "seq",
}


@pytest.mark.skipif(not BENCH_DIR.exists(), reason="silo benchmark data not present")
def test_agg_kind_extraction_on_real_cases():
    for case_id, expected in EXPECTED_KINDS.items():
        text = json.loads((BENCH_DIR / f"{case_id}_n5.json").read_text())["task_description"]
        if not isinstance(text, str):
            text = json.dumps(text)
        assert agg_kind(text) == expected, (case_id, agg_kind(text))


def _row(topology: str, bucket: str, kind: str, em: float) -> dict:
    return {
        "Topology": topology, "task_features_key": bucket,
        "task_agg_kind": kind, "ExactMatchRate": em,
    }


def _skill_with_ledger(ledger: dict) -> SkillCard:
    return SkillCard(
        skill_id="s", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy={
            "topology_name": "t",
            "protocol_spec": {
                "name": "t", "n_agents": 5,
                "steps": [{"transmissions": [[0, 1]], "description": "x", "operator": "replay"}],
                "metadata": {},
            },
            "transfer_evidence": ledger,
        },
        expected_tradeoff={"mean_primary_loss": 0.2},
        tags=["mas", "silo"],
    )


def test_ledger_writes_kind_subslots():
    rows = [
        _row("t", "of", "vote", 1.0), _row("t", "of", "vote", 1.0),
        _row("t", "of", "count", 0.0), _row("t", "of", "count", 0.0),
    ]
    ledger = build_transfer_ledger(rows)["t"]
    assert ledger["of"] == {"n": 4, "em_sum": 2.0}
    assert ledger["of#vote"] == {"n": 2, "em_sum": 2.0}
    assert ledger["of#count"] == {"n": 2, "em_sum": 0.0}


def test_contradiction_restricts_trust_to_winning_kinds():
    # The dev-1 gen signature: vote perfect, count fatal, bucket mean passes.
    skill = _skill_with_ledger({
        "of": {"n": 11, "em_sum": 6.0},
        "of#vote": {"n": 5, "em_sum": 5.0},
        "of#count": {"n": 6, "em_sum": 1.0},
    })
    assert skill_trusted_for(skill, "of", "vote") is True
    assert skill_trusted_for(skill, "of", "count") is False
    # A kind with no dedicated evidence inherits NOTHING once contradicted.
    assert skill_trusted_for(skill, "of", "max") is False


def test_uniform_evidence_keeps_bucket_trust():
    # one_peer_exponential's dev-1 profile: sparse but consistent os success.
    skill = _skill_with_ledger({
        "os": {"n": 3, "em_sum": 2.4},
        "os#seq": {"n": 3, "em_sum": 2.4},
    })
    # No contradiction -> bucket-level trust covers kinds without evidence
    # (this is what preserved the II-15 +44pp win in dev round 1).
    assert skill_trusted_for(skill, "os", "seq") is True
    assert skill_trusted_for(skill, "os", "set") is True


def test_single_lowstat_kind_does_not_trigger_contradiction():
    skill = _skill_with_ledger({
        "of": {"n": 3, "em_sum": 3.0},
        "of#max": {"n": 2, "em_sum": 2.0},
        "of#count": {"n": 1, "em_sum": 0.0},  # below MIN_TRUST_ROWS
    })
    assert skill_trusted_for(skill, "of", "count") is True  # bucket trust holds


def test_deployment_view_kind_aware():
    contradicted = _skill_with_ledger({
        "of": {"n": 11, "em_sum": 6.0},
        "of#vote": {"n": 5, "em_sum": 5.0},
        "of#count": {"n": 6, "em_sum": 1.0},
    })
    bank = SkillBank(skills=[contradicted])
    view, _, abstained = deployment_view(bank, None, "of", kind="count")
    assert abstained is True and len(view) == 0
    view, _, abstained = deployment_view(bank, None, "of", kind="vote")
    assert abstained is False and len(view) == 1
