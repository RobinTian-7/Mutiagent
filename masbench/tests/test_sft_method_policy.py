from __future__ import annotations

import pytest

from masbench.sft_pilot.method_policy import (
    PilotMethodCapabilityPolicyV2,
    method_capability_policy,
)


METHOD_ARMS = [
    "current",
    "whole_artifact_receipt",
    "ect_whole_transaction",
    "sft_unified",
    "sft_shadow",
    "sft_shuffled_edge",
    "sft_uniform_target",
    "sft_no_failure_memory",
    "sft_no_diversity_eviction",
]


@pytest.mark.parametrize("method_arm", METHOD_ARMS)
def test_every_named_arm_has_one_closed_policy(method_arm: str) -> None:
    policy = method_capability_policy(method_arm)  # type: ignore[arg-type]
    assert policy.method_arm == method_arm
    assert not policy.final_val_bank_writable
    assert policy == PilotMethodCapabilityPolicyV2.model_validate_json(
        policy.model_dump_json()
    )


def test_current_is_native_mutable_and_not_shadow() -> None:
    current = method_capability_policy("current")
    shadow = method_capability_policy("sft_shadow")

    assert current.state_backend == "queenbee_skillbank_v1"
    assert current.state_write_mode == "native_update"
    assert current.state_writable
    assert current.proposal_law == "queenbee_native_reuse_mutate_fresh"
    assert current.allowed_operations != shadow.allowed_operations
    current.require_operation("create_action", phase="TRAIN_UPDATE")
    current.require_operation("apply_gate", phase="TRAIN_UPDATE")
    current.require_state_write(
        phase="TRAIN_UPDATE", backend="queenbee_skillbank_v1"
    )


def test_shadow_observes_factor_representation_but_cannot_mutate() -> None:
    policy = method_capability_policy("sft_shadow")
    assert policy.state_backend == "factor_bank_v2"
    assert policy.state_write_mode == "observe_only"
    assert not policy.state_writable
    assert not policy.factor_bank_writable
    policy.require_operation("observe_activation", phase="PROBE")
    with pytest.raises(PermissionError, match="observe-only"):
        policy.require_state_write(phase="PROBE", backend="factor_bank_v2")
    with pytest.raises(PermissionError, match="apply_gate"):
        policy.require_operation("apply_gate")
    with pytest.raises(PermissionError, match="record_failure"):
        policy.require_operation("record_failure")
    with pytest.raises(PermissionError, match="attribute_factor_evidence"):
        policy.require_operation("attribute_factor_evidence")


@pytest.mark.parametrize(
    "method_arm",
    ["current", "whole_artifact_receipt", "ect_whole_transaction", "sft_shadow"],
)
def test_non_sft_writers_and_shadow_cannot_import_factor_evidence(
    method_arm: str,
) -> None:
    policy = method_capability_policy(method_arm)  # type: ignore[arg-type]
    with pytest.raises(PermissionError, match="attribute_factor_evidence"):
        policy.require_operation("attribute_factor_evidence")
    assert not policy.factor_bank_writable


def test_whole_and_ect_have_distinct_non_factor_backends() -> None:
    whole = method_capability_policy("whole_artifact_receipt")
    ect = method_capability_policy("ect_whole_transaction")

    assert whole.state_backend == "whole_artifact_bank_v1"
    assert whole.state_write_mode == "whole_artifact_update"
    assert whole.proposal_law == "whole_artifact"
    assert ect.state_backend == "ect_transaction_bank_v1"
    assert ect.state_write_mode == "ect_transaction_update"
    assert ect.proposal_law == "ect_transaction"
    assert whole.backend_capability_sha256 != ect.backend_capability_sha256
    assert not whole.factor_bank_writable
    assert not ect.factor_bank_writable
    whole.require_state_write(
        phase="PROBE", backend="whole_artifact_bank_v1"
    )
    ect.require_state_write(
        phase="PROBE", backend="ect_transaction_bank_v1"
    )
    with pytest.raises(PermissionError, match="cannot write backend"):
        whole.require_state_write(
            phase="PROBE", backend="ect_transaction_bank_v1"
        )
    with pytest.raises(PermissionError, match="cannot write backend"):
        ect.require_state_write(phase="PROBE", backend="factor_bank_v2")


@pytest.mark.parametrize(
    "method_arm",
    [
        "sft_unified",
        "sft_shuffled_edge",
        "sft_uniform_target",
        "sft_no_failure_memory",
        "sft_no_diversity_eviction",
    ],
)
def test_only_mutating_sft_arms_write_factor_bank(method_arm: str) -> None:
    policy = method_capability_policy(method_arm)  # type: ignore[arg-type]
    assert policy.state_backend == "factor_bank_v2"
    assert policy.state_write_mode == "factor_update"
    assert policy.factor_bank_writable
    policy.require_operation("attribute_factor_evidence", phase="PROBE")
    policy.require_state_write(phase="PROBE", backend="factor_bank_v2")


def test_operation_phase_law_and_final_val_isolation() -> None:
    policy = method_capability_policy("sft_unified")

    policy.require_operation("select_proposal", phase="TRAIN_UPDATE")
    policy.require_operation("commit_probe", phase="PROBE")
    policy.require_operation("attribute_factor_evidence", phase="PROBE")
    policy.require_operation("final_val_result", phase="FINAL_VAL")
    policy.require_operation("retrieve", phase="FINAL_VAL")
    with pytest.raises(PermissionError, match="not legal in phase"):
        policy.require_operation("apply_gate", phase="PROBE")
    with pytest.raises(PermissionError, match="not legal in phase"):
        policy.require_operation("commit_probe", phase="TRAIN_UPDATE")
    with pytest.raises(PermissionError, match="not legal in phase"):
        policy.require_operation("final_val_result", phase="TRAIN_UPDATE")
    with pytest.raises(PermissionError, match="FINAL_VAL"):
        policy.require_state_write(phase="FINAL_VAL", backend="factor_bank_v2")

    for method_arm in METHOD_ARMS:
        arm = method_capability_policy(method_arm)  # type: ignore[arg-type]
        if arm.state_writable:
            with pytest.raises(PermissionError, match="FINAL_VAL"):
                arm.require_state_write(
                    phase="FINAL_VAL", backend=arm.state_backend
                )


def test_causal_controls_change_only_the_proposal_law() -> None:
    unified = method_capability_policy("sft_unified")
    shuffled = method_capability_policy("sft_shuffled_edge")
    uniform = method_capability_policy("sft_uniform_target")

    baseline = unified.model_dump(exclude={"method_arm", "proposal_law"})
    assert shuffled.model_dump(exclude={"method_arm", "proposal_law"}) == baseline
    assert uniform.model_dump(exclude={"method_arm", "proposal_law"}) == baseline
    assert shuffled.proposal_law == "sft_shuffled_sign"
    assert uniform.proposal_law == "sft_uniform_target"


def test_lifecycle_ablations_remove_only_declared_capability() -> None:
    unified = method_capability_policy("sft_unified")
    no_failure = method_capability_policy("sft_no_failure_memory")
    no_diversity = method_capability_policy("sft_no_diversity_eviction")

    assert set(unified.allowed_operations) - set(no_failure.allowed_operations) == {
        "record_failure"
    }
    assert no_failure.failure_law == "disabled"
    assert no_failure.model_dump(
        exclude={"method_arm", "allowed_operations", "failure_law"}
    ) == unified.model_dump(
        exclude={"method_arm", "allowed_operations", "failure_law"}
    )
    assert no_diversity.allowed_operations == unified.allowed_operations
    assert no_diversity.diversity_law == "eviction_disabled"
    assert no_diversity.model_dump(
        exclude={"method_arm", "diversity_law"}
    ) == unified.model_dump(exclude={"method_arm", "diversity_law"})


def test_closed_shape_rejects_backend_or_operation_escalation() -> None:
    unified = method_capability_policy("sft_unified")
    shadow_payload = method_capability_policy("sft_shadow").model_dump()
    shadow_payload["state_write_mode"] = "factor_update"
    shadow_payload["allowed_operations"] = unified.allowed_operations
    with pytest.raises(ValueError, match="closed arm law"):
        PilotMethodCapabilityPolicyV2.model_validate(shadow_payload)

    whole_payload = method_capability_policy("whole_artifact_receipt").model_dump()
    whole_payload["state_backend"] = "factor_bank_v2"
    whole_payload["state_write_mode"] = "factor_update"
    with pytest.raises(ValueError, match="closed arm law"):
        PilotMethodCapabilityPolicyV2.model_validate(whole_payload)

    current_payload = method_capability_policy("current").model_dump()
    current_payload["allowed_operations"] = tuple(
        sorted((*current_payload["allowed_operations"], "attribute_factor_evidence"))
    )
    with pytest.raises(ValueError, match="closed arm law"):
        PilotMethodCapabilityPolicyV2.model_validate(current_payload)
