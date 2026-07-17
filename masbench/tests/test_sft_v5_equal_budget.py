"""Stage 10 closure tests: control-arm backends + equal all-in budgets.

Every arm gets a real, exclusive, policy-gated backend adapter; no arm can
write another arm's backend or escalate past its closed capability law; and
the equal-budget verifier rejects any per-dimension divergence between arms.
"""

from __future__ import annotations

import hashlib

import pytest

from masbench.sft_pilot.controls import (
    EctTransactionBankV1,
    PilotMethodBackendGateway,
    WholeArtifactBankV1,
    build_control_gateways,
    verify_equal_all_in_budgets,
)

from sft_v5_fixtures import V5Harness


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


ALL_ARMS = (
    "current",
    "whole_artifact_receipt",
    "ect_whole_transaction",
    "sft_unified",
    "sft_shadow",
    "sft_shuffled_edge",
    "sft_uniform_target",
    "sft_no_failure_memory",
    "sft_no_diversity_eviction",
)


@pytest.fixture
def harness(tmp_path):
    built = V5Harness(tmp_path)
    yield built
    built.close()


def test_every_arm_gets_an_exclusive_policy_gated_backend(harness) -> None:
    key = hashlib.sha256(b"control-backend-key").digest()
    gateways = build_control_gateways(
        method_arms=ALL_ARMS,
        factor_bank=harness.bank,
        backend_key=key,
    )
    assert set(gateways) == set(ALL_ARMS)

    # Non-factor controls own real chained ledgers of their own.
    ect = gateways["ect_whole_transaction"].writer(
        "create_action", phase="TRAIN_UPDATE"
    )
    assert isinstance(ect, EctTransactionBankV1)
    row = ect.record(
        operation="create_action",
        subject_sha256=_sha("ect-whole-transaction"),
        outcome_sha256=_sha("ect-outcome"),
    )
    assert row.backend == "ect_transaction_bank_v1"
    assert ect.evidence_root_sha256 != WholeArtifactBankV1(
        backend_key=key
    ).evidence_root_sha256

    # The factor arm writes the FactorBankV2 instance itself.
    assert (
        gateways["sft_unified"].writer("commit_probe", phase="PROBE")
        is harness.bank
    )

    # Shadow observes the same Factor representation but can never write.
    with pytest.raises(PermissionError):
        gateways["sft_shadow"].writer("commit_probe", phase="PROBE")
    assert (
        gateways["sft_shadow"].reader().scientific_state_sha256
        == harness.bank.scientific_state_sha256
    )

    # FINAL_VAL can write no backend on any arm.
    for method_arm in ALL_ARMS:
        with pytest.raises(PermissionError):
            gateways[method_arm].writer("commit_probe", phase="FINAL_VAL")

    # The no-failure-memory ablation removed exactly record_failure.
    with pytest.raises(PermissionError):
        gateways["sft_no_failure_memory"].writer(
            "record_failure", phase="TRAIN_UPDATE"
        )
    gateways["sft_no_diversity_eviction"].writer(
        "record_failure", phase="TRAIN_UPDATE"
    )


def test_cross_backend_instances_fail_closed(harness) -> None:
    key = hashlib.sha256(b"control-backend-key").digest()
    with pytest.raises(TypeError, match="closed backend law"):
        PilotMethodBackendGateway(
            method_arm="sft_unified",
            backend=WholeArtifactBankV1(backend_key=key),
        )
    with pytest.raises(TypeError, match="closed backend law"):
        PilotMethodBackendGateway(
            method_arm="ect_whole_transaction",
            backend=harness.bank,
        )
    with pytest.raises(TypeError, match="read-only Factor facade"):
        PilotMethodBackendGateway(
            method_arm="sft_shadow",
            backend=harness.bank,
        )


def test_equal_all_in_budget_verifier(harness) -> None:
    report = verify_equal_all_in_budgets(
        (harness.experiment.protocol, harness.experiment.control_protocol)
    )
    assert report["equal_all_in"]
    assert report["totals"]["call_slots"] == 15

    skewed_budgets = tuple(
        budget.model_copy(update={"input_tokens": budget.input_tokens + 1})
        if budget.phase == "PROBE"
        else budget
        for budget in harness.experiment.control_protocol.phase_budgets
    )
    skewed = harness.experiment.control_protocol.model_copy(
        update={"phase_budgets": skewed_budgets}
    )
    with pytest.raises(ValueError, match="equal all-in budgets"):
        verify_equal_all_in_budgets((harness.experiment.protocol, skewed))
