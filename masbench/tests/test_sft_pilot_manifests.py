from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from masbench.sft_pilot.manifests import (
    PilotBlockedArmOrderV1,
    PilotCallScheduleEntryV1,
    PilotCandidateEntryV1,
    PilotCandidateManifestV1,
    PilotCaseEntryV1,
    PilotCaseManifestV1,
    PilotCodeSourceV1,
    PilotExecutionScheduleEntryV1,
    PilotExecutionScheduleV1,
    PilotExperimentArmV1,
    PilotExperimentManifestV1,
    PilotFailureOwnerV1,
    PilotPairEntryV1,
    PilotPairManifestV1,
    PilotProposalPermutationEntryV1,
    PilotProposalPermutationV1,
    PilotRunnerManifestV1,
    load_frozen_manifest,
    published_manifest_bytes,
    validate_experiment_children,
    validate_schedule_against_protocol,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace() -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=2,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="runtime-v1",
        binder_version="binder-v1",
        compiler_version="compiler-v1",
    )


def _arms() -> tuple[PilotLogicalArmCoordinatesV1, ...]:
    common = {
        "pair_id": "pair-1",
        "case_commitment_sha256": _h("case"),
        "unit_commitment": "unit-1",
        "split": "TRAIN_UPDATE",
        "execution_ordinal": 0,
    }
    return (
        PilotLogicalArmCoordinatesV1(
            **common, pair_arm="source", operation_kind="source_probe"
        ),
        PilotLogicalArmCoordinatesV1(
            **common, pair_arm="target", operation_kind="target_probe"
        ),
    )


def _schedule(arms=None) -> PilotExecutionScheduleV1:
    arms = _arms() if arms is None else arms
    return PilotExecutionScheduleV1(
        entries=tuple(
            PilotExecutionScheduleEntryV1(
                logical_arm=arm,
                physical_block_ordinal=index,
                calls=(
                    PilotCallScheduleEntryV1(
                        call_slot=0,
                        input_tokens_reserved=512,
                        output_tokens_reserved=128,
                        request_envelope_sha256=_h(f"request-{index}"),
                        request_renderer_sha256=_h("renderer-v1"),
                        prompt_template_sha256=_h(f"template-{index}"),
                        json_mode=True,
                        artifact_role=(
                            "source_artifact"
                            if arm.operation_kind == "source_probe"
                            else "target_artifact"
                        ),
                    ),
                ),
            )
            for index, arm in enumerate(arms)
        )
    )


def _case_manifest() -> PilotCaseManifestV1:
    return PilotCaseManifestV1(
        cases=(
            PilotCaseEntryV1(
                case_id="case-1",
                split="TRAIN_UPDATE",
                unit_commitment="unit-1",
                input_commitment_sha256=_h("case"),
            ),
        )
    )


def _pair_manifest() -> PilotPairManifestV1:
    return PilotPairManifestV1(
        pairs=(
            PilotPairEntryV1(
                pair_id="pair-1",
                case_id="case-1",
                unit_commitment="unit-1",
                case_commitment_sha256=_h("case"),
                arm_order="AB",
                execution_ordinal=0,
            ),
        )
    )


def _candidate_manifest() -> PilotCandidateManifestV1:
    return PilotCandidateManifestV1(
        candidates=(
            PilotCandidateEntryV1(
                cell_sha256=_h("cell"),
                target_factor_key_sha256=_h("target-key"),
                target_content_sha256=_h("target-content"),
            ),
        )
    )


def _runner_manifest() -> PilotRunnerManifestV1:
    return PilotRunnerManifestV1(
        fixed_git_commit="8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a",
        exact_artifact_runner_version="exact-runner-v1",
        runtime_version="runtime-v1",
        binder_version="binder-v1",
        compiler_version="compiler-v1",
        code_sources=(PilotCodeSourceV1(source_id="engine", sha256=_h("engine")),),
        failure_owners=(
            PilotFailureOwnerV1(
                safe_failure_code="algorithm_failure",
                owner="factor_algorithm",
            ),
        ),
    )


def _protocol(
    method_arm: str,
    *,
    cases: PilotCaseManifestV1,
    pairs: PilotPairManifestV1,
    candidates: PilotCandidateManifestV1,
    runner: PilotRunnerManifestV1,
) -> PilotProtocolV1:
    return PilotProtocolV1(
        protocol_id=f"protocol-{method_arm}",
        method_arm=method_arm,
        namespace=_namespace(),
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=cases.digest,
            source_policy_sha256=_h("source-policy"),
        ),
        source_authority_sha256=_h("source-authority"),
        dataset_split_policy_sha256=_h("split-policy"),
        candidate_pool_manifest_sha256=candidates.digest,
        runner_config_sha256=runner.digest,
        model_config_sha256=_h("model"),
        pair_manifest_sha256=pairs.digest,
        genesis_state_sha256=_h(f"genesis-{method_arm}"),
        component_bundle_required=(method_arm == "sft_unified"),
        execution_schedule_sha256=_schedule().digest,
        store_derived_schedule_required=True,
        authorized_logical_arms=_arms(),
        phase_budgets=tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm=method_arm,
                executions=2,
                call_slots=2,
                input_tokens=1_024,
                output_tokens=256,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=2,
            max_execution_leases=4,
            max_call_receipts=4,
            max_call_slots_per_execution=1,
            max_input_tokens_per_call=512,
            max_output_tokens_per_call=128,
            max_active_db_bytes=1_000_000,
            max_archive_bytes=64_000,
            max_total_stored_scalar_bytes=64_000,
        ),
    )


def test_schedule_is_exact_and_budget_closed() -> None:
    cases = _case_manifest()
    pairs = _pair_manifest()
    candidates = _candidate_manifest()
    runner = _runner_manifest()
    protocol = _protocol(
        "sft_unified",
        cases=cases,
        pairs=pairs,
        candidates=candidates,
        runner=runner,
    )
    schedule = _schedule()
    validate_schedule_against_protocol(schedule, protocol)
    assert schedule.entry_for(_arms()[0]).input_tokens_reserved == 512

    missing = PilotExecutionScheduleV1(entries=(schedule.entries[0],))
    with pytest.raises(ValueError, match="logical arms"):
        validate_schedule_against_protocol(missing, protocol)


def test_schedule_rejects_wrong_role_alias_and_overbudget() -> None:
    arm = _arms()[0]
    with pytest.raises(ValueError, match="artifact roles"):
        PilotExecutionScheduleEntryV1(
            logical_arm=arm,
            physical_block_ordinal=0,
            calls=(
                PilotCallScheduleEntryV1(
                    call_slot=0,
                    input_tokens_reserved=512,
                    output_tokens_reserved=128,
                    request_envelope_sha256=_h("request"),
                    request_renderer_sha256=_h("renderer-v1"),
                    prompt_template_sha256=_h("template"),
                    json_mode=True,
                    artifact_role="target_artifact",
                ),
            ),
        )

    cases, pairs = _case_manifest(), _pair_manifest()
    candidates, runner = _candidate_manifest(), _runner_manifest()
    protocol = _protocol(
        "sft_unified",
        cases=cases,
        pairs=pairs,
        candidates=candidates,
        runner=runner,
    )
    oversized = _schedule().model_copy(
        update={
            "entries": tuple(
                entry.model_copy(
                    update={
                        "calls": (
                            entry.calls[0].model_copy(
                                update={"input_tokens_reserved": 513}
                            ),
                        )
                    }
                )
                for entry in _schedule().entries
            )
        }
    )
    with pytest.raises(ValueError, match="exact execution schedule|per-call input"):
        validate_schedule_against_protocol(oversized, protocol)


def test_schedule_closes_exact_case_pair_split_and_operation() -> None:
    cases, pairs = _case_manifest(), _pair_manifest()
    candidates, runner = _candidate_manifest(), _runner_manifest()
    schedule = _schedule()
    protocol = _protocol(
        "sft_unified",
        cases=cases,
        pairs=pairs,
        candidates=candidates,
        runner=runner,
    )
    validate_schedule_against_protocol(
        schedule,
        protocol,
        case_manifest=cases,
        pair_manifest=pairs,
    )

    wrong_pairs = PilotPairManifestV1(
        pairs=(
            pairs.pairs[0].model_copy(
                update={"case_commitment_sha256": _h("another-case")}
            ),
        )
    )
    with pytest.raises(ValueError, match="exact case"):
        validate_schedule_against_protocol(
            schedule,
            protocol,
            case_manifest=cases,
            pair_manifest=wrong_pairs,
        )

    with pytest.raises(ValueError, match="TRAIN_UPDATE split"):
        PilotExecutionScheduleEntryV1(
            logical_arm=_arms()[0].model_copy(update={"split": "FINAL_VAL"}),
            physical_block_ordinal=0,
            calls=(schedule.entries[0].calls[0],),
        )


def test_experiment_closes_children_and_block_order() -> None:
    cases, pairs = _case_manifest(), _pair_manifest()
    candidates, runner = _candidate_manifest(), _runner_manifest()
    schedule = _schedule()
    protocols = tuple(
        _protocol(
            method,
            cases=cases,
            pairs=pairs,
            candidates=candidates,
            runner=runner,
        )
        for method in ("current", "sft_unified")
    )
    arms = tuple(
        PilotExperimentArmV1(
            method_arm=protocol.method_arm,
            child_protocol_sha256=protocol.digest,
            implementation_sha256=_h(f"impl-{protocol.method_arm}"),
            state_dir_commitment_sha256=_h(f"state-{protocol.method_arm}"),
            execution_schedule_sha256=schedule.digest,
        )
        for protocol in protocols
    )
    manifest = PilotExperimentManifestV1(
        experiment_id="experiment-1",
        case_manifest_sha256=cases.digest,
        pair_manifest_sha256=pairs.digest,
        candidate_manifest_sha256=candidates.digest,
        runner_manifest_sha256=runner.digest,
        model_config_sha256=_h("model"),
        execution_schedule_sha256=schedule.digest,
        arms=arms,
        blocked_arm_orders=(
            PilotBlockedArmOrderV1(
                block_ordinal=0,
                unit_commitment="unit-1",
                arm_order=("current", "sft_unified"),
            ),
        ),
    )
    validate_experiment_children(
        manifest,
        protocols=protocols,
        case_manifest=cases,
        pair_manifest=pairs,
        candidate_manifest=candidates,
        runner_manifest=runner,
        execution_schedule=schedule,
    )

    changed = protocols[1].model_copy(update={"temperature": 0.1})
    with pytest.raises(ValueError, match="outside the explicit allowlist"):
        validate_experiment_children(
            manifest.model_copy(
                update={
                    "arms": (
                        arms[0],
                        arms[1].model_copy(
                            update={"child_protocol_sha256": changed.digest}
                        ),
                    )
                }
            ),
            protocols=(protocols[0], changed),
            case_manifest=cases,
            pair_manifest=pairs,
            candidate_manifest=candidates,
            runner_manifest=runner,
            execution_schedule=schedule,
        )


def test_shuffled_control_requires_real_frozen_permutation() -> None:
    schedule = _schedule()
    arm_methods = ("current", "sft_shuffled_edge")
    arms = tuple(
        PilotExperimentArmV1(
            method_arm=method,
            child_protocol_sha256=_h(f"protocol-{method}"),
            implementation_sha256=_h(f"impl-{method}"),
            state_dir_commitment_sha256=_h(f"state-{method}"),
            execution_schedule_sha256=schedule.digest,
        )
        for method in arm_methods
    )
    values = dict(
        experiment_id="experiment-shuffled",
        case_manifest_sha256=_h("cases"),
        pair_manifest_sha256=_h("pairs"),
        candidate_manifest_sha256=_h("candidates"),
        runner_manifest_sha256=_h("runner"),
        model_config_sha256=_h("model"),
        execution_schedule_sha256=schedule.digest,
        arms=arms,
        blocked_arm_orders=(
            PilotBlockedArmOrderV1(
                block_ordinal=0,
                unit_commitment="unit-1",
                arm_order=arm_methods,
            ),
        ),
    )
    with pytest.raises(ValueError, match="permutation"):
        PilotExperimentManifestV1(**values)

    permutation = PilotProposalPermutationV1(
        entries=(
            PilotProposalPermutationEntryV1(
                target_factor_key_sha256=_h("target-key"),
                permuted_rank=0,
            ),
        )
    )
    manifest = PilotExperimentManifestV1(
        **values,
        shuffled_proposal_permutation=permutation,
    )
    assert manifest.shuffled_proposal_permutation == permutation


def test_manifest_shapes_reject_private_or_outcome_fields() -> None:
    with pytest.raises(ValueError):
        PilotCaseEntryV1.model_validate(
            {
                "case_id": "case-1",
                "split": "TRAIN_UPDATE",
                "unit_commitment": "unit-1",
                "input_commitment_sha256": _h("case"),
                "ground_truth": "forbidden",
            }
        )


def test_frozen_manifest_loader_requires_exact_nofollow_bytes(tmp_path: Path) -> None:
    manifest = _case_manifest()
    path = (tmp_path / "cases.json").resolve()
    path.write_bytes(published_manifest_bytes(manifest))
    assert load_frozen_manifest(
        path,
        model_type=PilotCaseManifestV1,
        expected_sha256=manifest.digest,
    ) == manifest

    pretty = (tmp_path / "pretty.json").resolve()
    pretty.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="canonical exact JSON"):
        load_frozen_manifest(
            pretty,
            model_type=PilotCaseManifestV1,
            expected_sha256=manifest.digest,
        )

    symlink = tmp_path / "manifest-link.json"
    symlink.symlink_to(path)
    with pytest.raises(ValueError, match="cannot be opened|non-symlink"):
        load_frozen_manifest(
            symlink.absolute(),
            model_type=PilotCaseManifestV1,
            expected_sha256=manifest.digest,
        )
