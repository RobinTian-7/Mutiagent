"""M12: lossless-need trust slots + M8 breadth over them.

History: M6 used a 14-way agg-kind taxonomy as the trust key; dev-5 showed
its boundaries fracture trust ("longest palindrome length" read as max while
its target cases read seq -> 72/72 abstentions in both modes). M12 replaces
the key with the mechanistic binary the taxonomy proxied: does correctness
survive local summarization (lossy-safe) or must raw data reach the
computing agent (lossless)? The dev-1 gen failure maps cleanly: vote
successes = of#lossy passing, count failures = of#lossless failing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank
from masbench.task_classify import classify_task
from masbench.transfer import (
    build_transfer_ledger,
    deployment_view,
    skill_trusted_for,
)

BENCH_DIR = Path(__file__).resolve().parents[1] / "third_party" / "acl26-silo-bench" / "benchmarks"

# Hand-derived from the statements: can shards be reduced to small local
# summaries (max/sum/vote compose) or must raw data reach the computer?
EXPECTED_LOSSLESS = {
    "I-01": False, "I-03": False, "I-04": False, "I-06": False, "I-07": False,
    "I-02": True,   # word-frequency count needs full (word,count) info
    "I-05": True, "I-08": True, "I-09": True, "I-10": True,
    "II-13": True, "II-15": True, "II-16": True, "II-19": True,
}


@pytest.mark.skipif(not BENCH_DIR.exists(), reason="silo benchmark data not present")
def test_heuristic_fallback_lossless_bits():
    for case_id, expected in EXPECTED_LOSSLESS.items():
        text = json.loads((BENCH_DIR / f"{case_id}_n5.json").read_text())["task_description"]
        if not isinstance(text, str):
            text = json.dumps(text)
        out = classify_task(text, llm_client=None, model_name="fake", llm_provider="fake")
        assert out["needs_lossless"] == expected, (case_id, out)


def _row(topology: str, bucket: str, lossless: bool, em: float) -> dict:
    return {
        "Topology": topology, "task_features_key": bucket,
        "task_needs_lossless": lossless, "task_agg_kind": "diag-only",
        "ExactMatchRate": em,
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


def test_ledger_writes_lossless_subslots():
    rows = [
        _row("t", "of", False, 1.0), _row("t", "of", False, 1.0),
        _row("t", "of", True, 0.0), _row("t", "of", True, 0.0),
    ]
    ledger = build_transfer_ledger(rows)["t"]
    assert ledger["of"] == {"n": 4, "em_sum": 2.0}
    assert ledger["of#lossy-scalar"] == {"n": 2, "em_sum": 2.0}
    assert ledger["of#lossless-scalar"] == {"n": 2, "em_sum": 0.0}


def test_lossy_safe_success_does_not_authorize_lossless_cases():
    # dev-1 gen signature in M12 terms: vote (lossy) perfect, count
    # (lossless) fatal; bucket mean passes.
    skill = _skill_with_ledger({
        "of": {"n": 11, "em_sum": 6.0},
        "of#lossy-scalar": {"n": 5, "em_sum": 5.0},
        "of#lossless-scalar": {"n": 6, "em_sum": 1.0},
    })
    assert skill_trusted_for(skill, "of", "lossy-scalar") is True
    assert skill_trusted_for(skill, "of", "lossless-scalar") is False


def test_anchor_trust_reaches_same_slot_targets():
    # dev-5's broken flow, repaired: II-13 (lossless) earned trust must be
    # reachable from II-15/16/19 (lossless) -- same slot, direct evidence.
    skill = _skill_with_ledger({
        "os": {"n": 2, "em_sum": 1.0},
        "os#lossless-scalar": {"n": 2, "em_sum": 1.0},
    })
    assert skill_trusted_for(skill, "os", "lossless-scalar") is True
    # ...but a lossless anchor says nothing about the lossy slot alone;
    # narrow evidence never extrapolates (M8).
    assert skill_trusted_for(skill, "os", "lossy-scalar") is False


def test_breadth_requires_both_bits():
    both = _skill_with_ledger({
        "of": {"n": 6, "em_sum": 5.0},
        "of#lossy-scalar": {"n": 3, "em_sum": 3.0},
        "of#lossless-scalar": {"n": 3, "em_sum": 2.0},
    })
    # both bits measured and passing -> trusted on either slot
    assert skill_trusted_for(both, "of", "lossy-scalar") is True
    assert skill_trusted_for(both, "of", "lossless-scalar") is True


def test_single_lowstat_slot_means_no_extrapolation():
    skill = _skill_with_ledger({
        "of": {"n": 3, "em_sum": 3.0},
        "of#lossy-scalar": {"n": 2, "em_sum": 2.0},
        "of#lossless-scalar": {"n": 1, "em_sum": 0.0},  # below MIN_TRUST_ROWS
    })
    assert skill_trusted_for(skill, "of", "lossy-scalar") is True
    assert skill_trusted_for(skill, "of", "lossless-scalar") is False


def test_legacy_ledger_without_subslots_keeps_bucket_semantics():
    skill = _skill_with_ledger({"of": {"n": 4, "em_sum": 4.0}})
    assert skill_trusted_for(skill, "of", "lossy-scalar") is True


def test_deployment_view_slot_aware():
    contradicted = _skill_with_ledger({
        "of": {"n": 11, "em_sum": 6.0},
        "of#lossy-scalar": {"n": 5, "em_sum": 5.0},
        "of#lossless-scalar": {"n": 6, "em_sum": 1.0},
    })
    bank = SkillBank(skills=[contradicted])
    view, _, abstained, _tier = deployment_view(bank, None, "of", kind="lossless-scalar")
    assert abstained is True and len(view) == 0
    view, _, abstained, _tier = deployment_view(bank, None, "of", kind="lossy-scalar")
    assert abstained is False and len(view) == 1


def test_m16_shape_routes_preserve_vs_modify():
    """dev-9 forensics: II-13 (scalar) direct evidence marked II-17
    (composite) 'preserve' -> bare structure 0.00 where Modify had cracked
    it. With the shape bit: scalar slot keeps preserve; composite slot has
    no direct evidence and routes through breadth extrapolation -> modify."""
    from masbench.transfer import deployment_view

    veteran = _skill_with_ledger({
        "os": {"n": 6, "em_sum": 4.0},
        "os#lossless-scalar": {"n": 3, "em_sum": 2.5},
        "os#lossy-scalar": {"n": 3, "em_sum": 1.5},
    })
    bank = SkillBank(skills=[veteran])
    # II-15-like: scalar slot, direct evidence -> preserve
    view, _, _, _ = deployment_view(
        bank, None, "os", kind="lossless-scalar", fallback_tier=True,
    )
    assert next(iter(view)).organization_policy["deploy_action"] == "preserve"
    # II-17-like: composite slot, no direct evidence; breadth (2 slots pass,
    # none fail) extrapolates trust -> deploy as MODIFY (rewrite for task)
    view2, _, abstained2, _ = deployment_view(
        bank, None, "os", kind="lossless-composite", fallback_tier=True,
    )
    assert abstained2 is False
    assert next(iter(view2)).organization_policy["deploy_action"] == "modify"
