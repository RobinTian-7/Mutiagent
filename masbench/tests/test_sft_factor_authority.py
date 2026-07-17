from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exp_graph.mas.factor_bank import DenseOutcome, ExecutionNamespace, ExecutionUsage
from exp_graph.mas.factor_bank_v2 import (
    AttemptCancellationReceiptV3,
    BaseSnapshotReceiptV2,
    FactorBankV2,
    GateReceiptV2,
    RollbackTriggerV2,
    cancellation_event_root_v3,
    runner_schedule_commitment_v1,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    SourceManifest,
)
from exp_graph.mas.phase_factor_binding_v2 import register_phase_materialization_v2
from exp_graph.mas.phase_factor_binding_v3 import register_phase_materialization_v3
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgram,
    PhaseProgramLimits,
)

from masbench.sft_pilot.factor_authority import (
    SFTPilotFactorAuthority,
    UNSIGNED_ATTESTATION_SHA256,
    pilot_factor_assignment_schedule_sha256,
    pilot_factor_pair_manifest_sha256,
)
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
    PilotRunnerManifestV1,
    validate_experiment_children,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
    canonical_sha256,
)


ATTESTATION_KEY = hashlib.sha256(b"pilot-factor-attestation-key").digest()
FACTOR_STATE_KEY = hashlib.sha256(b"pilot-factor-state-key").digest()
REGISTRY_KEY = hashlib.sha256(b"pilot-phase-registry-key").digest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _opaque(prefix: str, value: object) -> str:
    return f"{prefix}:{canonical_sha256(value)[:24]}"


def _namespace(
    *,
    information_goal: str = "sink",
    binder_version: str = PHASE_FACTOR_BINDER_VERSION,
) -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_count",
        objective="balanced",
        information_goal=information_goal,
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=4,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="pilot-runtime-v1",
        binder_version=binder_version,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _arms() -> tuple[PilotLogicalArmCoordinatesV1, ...]:
    result = []
    for ordinal in range(6):
        for arm, operation in (
            ("source", "source_probe"),
            ("target", "target_probe"),
        ):
            result.append(
                PilotLogicalArmCoordinatesV1(
                    pair_id=f"pair-{ordinal}",
                    pair_arm=arm,
                    case_commitment_sha256=_sha(f"case-{ordinal}"),
                    unit_commitment=f"unit-{ordinal}",
                    split="TRAIN_UPDATE",
                    operation_kind=operation,
                    execution_ordinal=ordinal,
                )
            )
    return tuple(result)


def _case_manifest() -> PilotCaseManifestV1:
    return PilotCaseManifestV1(
        cases=tuple(
            PilotCaseEntryV1(
                case_id=f"case-{ordinal}",
                split="TRAIN_UPDATE",
                unit_commitment=f"unit-{ordinal}",
                input_commitment_sha256=_sha(f"case-{ordinal}"),
            )
            for ordinal in range(6)
        )
    )


def _pair_manifest() -> PilotPairManifestV1:
    return PilotPairManifestV1(
        pairs=tuple(
            PilotPairEntryV1(
                pair_id=f"pair-{ordinal}",
                case_id=f"case-{ordinal}",
                unit_commitment=f"unit-{ordinal}",
                case_commitment_sha256=_sha(f"case-{ordinal}"),
                arm_order="AB" if ordinal % 2 == 0 else "BA",
                execution_ordinal=ordinal,
            )
            for ordinal in range(6)
        )
    )


def _legacy_factor_pair_manifest_sha256() -> str:
    """Reproduce the removed v1 internal root for a fail-closed regression."""

    arms = _arms()
    grouped = {
        pair_id: {
            arm.pair_arm: arm
            for arm in arms
            if arm.pair_id == pair_id
        }
        for pair_id in (f"pair-{ordinal}" for ordinal in range(6))
    }
    pairs = []
    for ordinal in range(6):
        pair_id = f"pair-{ordinal}"
        source = grouped[pair_id]["source"]
        target = grouped[pair_id]["target"]
        unit_sha256 = canonical_sha256(
            {
                "domain": "sft-pilot-factor-unit-v1",
                "ordinal": ordinal,
                "pair_id": pair_id,
                "source": source,
                "target": target,
            }
        )
        pairs.append(
            {
                "ordinal": ordinal,
                "pair_id": pair_id,
                "source": source,
                "target": target,
                "unit_commitment_sha256": unit_sha256,
                "arm_order": "AB" if ordinal % 2 == 0 else "BA",
            }
        )
    return canonical_sha256(
        {
            "domain": "sft-pilot-factor-pair-manifest-v1",
            "pairs": tuple(pairs),
        }
    )


def _schedule() -> PilotExecutionScheduleV1:
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
                        request_envelope_sha256=_sha(f"request-{index}"),
                        request_renderer_sha256=_sha("renderer"),
                        prompt_template_sha256=_sha(f"template-{index}"),
                        json_mode=True,
                        artifact_role=(
                            "source_artifact"
                            if arm.pair_arm == "source"
                            else "target_artifact"
                        ),
                    ),
                ),
            )
            for index, arm in enumerate(_arms())
        )
    )


def _candidate_manifest() -> PilotCandidateManifestV1:
    return PilotCandidateManifestV1(
        candidates=(
            PilotCandidateEntryV1(
                cell_sha256=_sha("candidate-cell"),
                target_factor_key_sha256=_sha("candidate-key"),
                target_content_sha256=_sha("candidate-content"),
            ),
        )
    )


def _runner_manifest() -> PilotRunnerManifestV1:
    return PilotRunnerManifestV1(
        fixed_git_commit="8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a",
        exact_artifact_runner_version="exact-runner-v1",
        runtime_version="pilot-runtime-v1",
        binder_version=PHASE_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
        code_sources=(
            PilotCodeSourceV1(
                source_id="factor-authority",
                sha256=_sha("factor-authority-source"),
            ),
        ),
        failure_owners=(
            PilotFailureOwnerV1(
                safe_failure_code="factor-failure",
                owner="factor_algorithm",
            ),
        ),
    )


def _protocol(
    *,
    namespace: ExecutionNamespace | None = None,
    arms: tuple[PilotLogicalArmCoordinatesV1, ...] | None = None,
    pair_manifest: PilotPairManifestV1 | None = None,
    method_arm: str = "sft_unified",
    case_manifest: PilotCaseManifestV1 | None = None,
    candidate_manifest: PilotCandidateManifestV1 | None = None,
    runner_manifest: PilotRunnerManifestV1 | None = None,
    execution_schedule: PilotExecutionScheduleV1 | None = None,
) -> PilotProtocolV1:
    namespace = namespace or _namespace()
    arms = arms or _arms()
    pair_manifest = pair_manifest or _pair_manifest()
    return PilotProtocolV1(
        protocol_id=f"factor-authority-{method_arm}",
        method_arm=method_arm,
        namespace=namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=(
                case_manifest.digest if case_manifest is not None else _sha("catalog")
            ),
            source_policy_sha256=_sha("source-policy"),
        ),
        source_authority_sha256=_sha("source-authority"),
        dataset_split_policy_sha256=_sha("split-policy"),
        candidate_pool_manifest_sha256=(
            candidate_manifest.digest
            if candidate_manifest is not None
            else _sha("candidate-pool")
        ),
        runner_config_sha256=(
            runner_manifest.digest
            if runner_manifest is not None
            else _sha("runner-config")
        ),
        model_config_sha256=_sha("model-config"),
        pair_manifest_sha256=pair_manifest.digest,
        genesis_state_sha256=_sha(f"genesis-{method_arm}"),
        component_bundle_required=(method_arm == "sft_unified"),
        execution_schedule_sha256=(
            execution_schedule.digest if execution_schedule is not None else None
        ),
        store_derived_schedule_required=(execution_schedule is not None),
        authorized_logical_arms=arms,
        phase_budgets=(
            AuthorizedPhaseBudgetV1(
                phase="TRAIN_UPDATE",
                method_arm=method_arm,
                executions=1,
                call_slots=1,
                input_tokens=1_000,
                output_tokens=200,
            ),
            AuthorizedPhaseBudgetV1(
                phase="PROBE",
                method_arm=method_arm,
                executions=12,
                call_slots=24,
                input_tokens=12_000,
                output_tokens=2_400,
            ),
            AuthorizedPhaseBudgetV1(
                phase="FINAL_VAL",
                method_arm=method_arm,
                executions=1,
                call_slots=1,
                input_tokens=1_000,
                output_tokens=200,
            ),
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=16,
            max_execution_leases=64,
            max_call_receipts=128,
            max_call_slots_per_execution=4,
            max_input_tokens_per_call=2_000,
            max_output_tokens_per_call=400,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=1024 * 1024,
            max_total_stored_scalar_bytes=8 * 1024 * 1024,
        ),
    )


def _program(instruction: str) -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": [
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": instruction,
                }
            ],
        }
    )


class Harness:
    def __init__(self, *, binder_version: str = PHASE_FACTOR_BINDER_VERSION) -> None:
        self.pair_manifest = _pair_manifest()
        self.protocol = _protocol(
            namespace=_namespace(binder_version=binder_version),
            pair_manifest=self.pair_manifest,
        )
        self.authority = SFTPilotFactorAuthority(
            self.protocol,
            pair_manifest=self.pair_manifest,
            attestation_key=ATTESTATION_KEY,
        )
        self.manifest = SourceManifest(
            manifest_sha256=_sha("phase-manifest"),
            split="TRAIN_UPDATE",
            source_catalog_sha256=self.protocol.source_manifest.source_catalog_sha256,
            policy_sha256=self.protocol.source_manifest.source_policy_sha256,
            producer_version="pilot-host-v1",
        )
        self.registry = PhaseArtifactRegistry(
            registry_key=REGISTRY_KEY,
            manifests=(self.manifest,),
            manifest_verifier=lambda candidate: candidate == self.manifest,
            branch_receipt_verifier=lambda receipt: (
                receipt.producer_epoch == "branch-host:factor-authority"
            ),
        )
        profile = self.registry.register_runtime_profile(
            namespace=self.protocol.namespace,
            limits=PhaseProgramLimits(),
        )
        ingress = self.registry.issue_ingress(self.manifest.manifest_sha256)
        source_artifact = self.registry.ingest_program(
            _program("gather concise evidence"),
            runtime_profile=profile,
            ingress=ingress,
        )
        source_factor = self.registry.extract_factor(
            source_artifact,
            locator="/phases/0/instruction",
        )
        branch_receipt = self.registry.register_branch_receipt(
            branch="mutate",
            source_artifact=source_artifact,
            locator="/phases/0/instruction",
            mutation_parent_factor=source_factor.factor,
            additional_input_root_commitments=(_sha("public-input"),),
            producer_epoch="branch-host:factor-authority",
            attestation_sha256=_sha("branch-attestation"),
        )
        operation_seal = self.registry.seal_operation(
            branch_receipt=branch_receipt
        )
        generated = self.registry.register_generated_value(
            "gather evidence and verify each claim",
            operation_seal=operation_seal,
            ingress=ingress,
        )
        proof = self.registry.materialize(
            operation_seal=operation_seal,
            target_factor=generated.factor,
        )
        assert isinstance(proof, PhaseBindingProofHandle)
        self.bank = FactorBankV2(
            state_key=FACTOR_STATE_KEY,
            **self.authority.capabilities(self.registry),
        )
        if binder_version == PHASE_FULL_FACTOR_BINDER_VERSION:
            self.edge = register_phase_materialization_v3(
                registry=self.registry,
                bank=self.bank,
                proof=proof,
            )
        else:
            self.edge = register_phase_materialization_v2(
                registry=self.registry,
                bank=self.bank,
                proof=proof,
            )
        unsigned_base = BaseSnapshotReceiptV2(
            receipt_id="base:factor-authority",
            deployment_slot_id=self.bank.deployment_slot_id(self.protocol.namespace),
            namespace_digest=self.protocol.namespace.digest,
            composition_id=self.edge.source_composition.composition_id,
            loaded_artifact_sha256=self.edge.source_composition.artifact_sha256,
            binding_map_sha256=canonical_sha256(
                sorted(self.edge.source_composition.binding_map.items())
            ),
            runtime_version=self.protocol.namespace.runtime_version,
            verifier_epoch=self.authority.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
            emitted_seq=self.bank.to_state().event_seq + 1,
        )
        self.bank.register_base_snapshot(
            self.authority.attest_base_snapshot(unsigned_base)
        )
        self.plan = self.bank.seal_probe_plan(
            transition_id=self.edge.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id=self.authority.epoch_id_for(
                transition_id=self.edge.transition.transition_id
            ),
            unit_commitments=self.authority.unit_commitments,
            arm_orders=self.authority.arm_orders,
            assignment_manifest_sha256=(
                self.authority.assignment_manifest_sha256
            ),
            runner_version=self.authority.runner_version,
            budget=self.authority.plan_budget,
            aggregate_policy=self.authority.aggregate_policy,
        )

    def open_attempt(self, ordinal: int):
        assignment = self.authority.make_assignment(self.plan, ordinal=ordinal)
        lease = self.authority.make_runner_lease(
            plan=self.plan,
            assignment=assignment,
            runner_session_id=f"runner-session:{ordinal}",
            runner_lease_token_sha256=_sha(f"lease-token-{ordinal}"),
            journal_anchor_sha256=_sha(f"journal-anchor-{ordinal}"),
        )
        return self.bank.open_next_attempt(self.plan.plan_id, assignment, lease)

    def complete_benefit(self, ordinal: int) -> None:
        attempt = self.open_attempt(ordinal)
        if attempt.assignment.arm_order == "AB":
            source_started, source_finished = 1, 2
            target_started, target_finished = 3, 4
        else:
            target_started, target_finished = 1, 2
            source_started, source_finished = 3, 4
        source_root = _sha(f"source-root-{ordinal}")
        target_root = _sha(f"target-root-{ordinal}")
        pair = self.authority.make_pair_execution(
            plan=self.plan,
            attempt=attempt,
            source_root_id=source_root,
            target_root_id=target_root,
            source_started_seq=source_started,
            source_finished_seq=source_finished,
            target_started_seq=target_started,
            target_finished_seq=target_finished,
        )
        usage = ExecutionUsage(
            messages=4,
            model_calls=2,
            input_tokens=900,
            output_tokens=180,
            wall_time_ms=2_000,
            cost_microusd=1_000,
        )
        source_outcome = DenseOutcome(
            V=0.50,
            K=0.8,
            U=0.8,
            P=0.8,
            S=0.8,
            stage_score=0.50,
            C=10.0,
            D=1.0,
        )
        target_outcome = source_outcome.model_copy(
            update={"V": 0.60, "stage_score": 0.60, "C": 9.0}
        )
        source_receipt = self.authority.make_phase_arm_receipt(
            registry=self.registry,
            registered=self.edge,
            plan=self.plan,
            attempt=attempt,
            arm="source",
            root_id=source_root,
            paired_arm_root_id=target_root,
            pair_execution_receipt=pair,
            activation_trace_root=_sha(f"activation-{ordinal}-source"),
            usage=usage,
            execution_class="completed",
            outcome=source_outcome,
        )
        target_receipt = self.authority.make_phase_arm_receipt(
            registry=self.registry,
            registered=self.edge,
            plan=self.plan,
            attempt=attempt,
            arm="target",
            root_id=target_root,
            paired_arm_root_id=source_root,
            pair_execution_receipt=pair,
            activation_trace_root=_sha(f"activation-{ordinal}-target"),
            usage=usage,
            execution_class="completed",
            outcome=target_outcome,
        )
        completed = self.bank.commit_attempt(
            attempt.attempt_id,
            source_receipt,
            target_receipt,
            pair,
        )
        assert completed.state == "complete"

    def apply_gate_and_rollback(self) -> None:
        opportunity = next(
            item
            for item in self.bank.to_state().gate_opportunities
            if item.plan_id == self.plan.plan_id and item.state == "pending"
        )
        assessment = self.bank.assessments[self.plan.plan_id]
        head = self.bank.deployment_heads[opportunity.deployment_slot_id]
        incumbent = next(
            item
            for item in self.bank.to_state().deployment_snapshots
            if item.snapshot_id == head.active_snapshot_id
        )
        unsigned_gate = GateReceiptV2(
            decision_id="gate:factor-authority",
            opportunity_id=opportunity.opportunity_id,
            deployment_slot_id=opportunity.deployment_slot_id,
            accepted=True,
            incumbent_snapshot_sha256=canonical_sha256(incumbent),
            candidate_snapshot_sha256=opportunity.candidate_snapshot_sha256,
            settled_assessment_sha256=assessment.digest,
            gate_config_sha256=(
                self.plan.aggregate_policy.strict_gate_config_sha256
            ),
            aggregate_summary_sha256=canonical_sha256(
                assessment.strict_summary
            ),
            verifier_epoch=self.authority.verifier_epoch,
            verification_attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
            emitted_seq=self.bank.to_state().event_seq + 1,
        )
        promoted = self.bank.apply_gate(self.authority.attest_gate(unsigned_gate))
        assert promoted is not None
        unsigned_rollback = RollbackTriggerV2(
            trigger_id="rollback:factor-authority",
            kind="train_monitor_harm",
            deployment_slot_id=promoted.deployment_slot_id,
            expected_head_generation=promoted.generation,
            active_snapshot_id=promoted.active_snapshot_id,
            safe_failure_code="monitor_harm",
            evidence_or_support_sha256=_sha("monitor-evidence"),
            verifier_epoch=self.authority.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
            emitted_seq=self.bank.to_state().event_seq + 1,
        )
        rollback = self.bank.apply_rollback(
            self.authority.attest_rollback(unsigned_rollback)
        )
        assert rollback.disposition == "restored_predecessor"


def test_authenticated_lifecycle_round_trips_through_native_bank_load(
    tmp_path: Path,
) -> None:
    harness = Harness()
    for ordinal in range(4):
        harness.complete_benefit(ordinal)
    assert harness.bank.assessments[harness.plan.plan_id].label == "candidate"
    harness.apply_gate_and_rollback()

    state_path = tmp_path / "factor-bank.json"
    harness.bank.save(state_path)
    reloaded = FactorBankV2.load(
        state_path,
        state_key=FACTOR_STATE_KEY,
        **harness.authority.capabilities(harness.registry),
    )
    assert reloaded.to_state() == harness.bank.to_state()
    assert set(harness.authority.uncovered_capabilities) == {
        "proposal_generation_context_verifier",
        "proposal_generation_lease_verifier",
        "proposal_abort_verifier",
    }
    persisted = state_path.read_text(encoding="utf-8").casefold()
    for forbidden in ('"prompt"', '"answer"', '"ground_truth"', '"expected_output"'):
        assert forbidden not in persisted


def test_plan_reconstruction_rejects_unit_order_model_and_cross_mode() -> None:
    harness = Harness()
    units = list(harness.plan.units)
    units[0] = units[0].model_copy(
        update={"unit_commitment": _sha("wrong-unit")}
    )
    assert not harness.authority.verify_plan(
        harness.plan.model_copy(update={"units": tuple(units)})
    )

    units = list(harness.plan.units)
    first_order, second_order = units[0].arm_order, units[1].arm_order
    units[0] = units[0].model_copy(update={"arm_order": second_order})
    units[1] = units[1].model_copy(update={"arm_order": first_order})
    assert not harness.authority.verify_plan(
        harness.plan.model_copy(update={"units": tuple(units)})
    )
    assert not harness.authority.verify_plan(
        harness.plan.model_copy(update={"model_name": "gpt-4o"})
    )

    all_agents_authority = SFTPilotFactorAuthority(
        _protocol(namespace=_namespace(information_goal="all_agents")),
        pair_manifest=_pair_manifest(),
        attestation_key=ATTESTATION_KEY,
    )
    assert not all_agents_authority.verify_plan(harness.plan)


def test_pair_manifest_rejects_control_final_val_and_protocol_substitution() -> None:
    pair_manifest = _pair_manifest()
    arms = list(_arms())
    arms[0] = arms[0].model_copy(
        update={"pair_arm": "control", "operation_kind": "control_execution"}
    )
    with pytest.raises(ValueError, match="source_probe/target_probe"):
        pilot_factor_assignment_schedule_sha256(
            tuple(arms), pair_manifest=pair_manifest
        )

    arms = list(_arms())
    arms[0] = arms[0].model_copy(
        update={"split": "FINAL_VAL", "operation_kind": "final_val"}
    )
    with pytest.raises(ValueError, match="FINAL_VAL"):
        pilot_factor_assignment_schedule_sha256(
            tuple(arms), pair_manifest=pair_manifest
        )

    with pytest.raises(ValueError, match="removed"):
        pilot_factor_pair_manifest_sha256(_arms())

    private_alias = _arms()[0].model_dump(mode="python")
    private_alias["split"] = "TEST"
    with pytest.raises(ValueError):
        PilotLogicalArmCoordinatesV1.model_validate(private_alias)

    protocol = _protocol(pair_manifest=pair_manifest)
    substituted = protocol.model_copy(
        update={"pair_manifest_sha256": _sha("substituted-pair-manifest")}
    )
    with pytest.raises(ValueError, match="pair manifest"):
        SFTPilotFactorAuthority(
            substituted,
            pair_manifest=pair_manifest,
            attestation_key=ATTESTATION_KEY,
        )

    changed_orders = list(pair_manifest.pairs)
    changed_orders[0] = changed_orders[0].model_copy(update={"arm_order": "BA"})
    changed_orders[1] = changed_orders[1].model_copy(update={"arm_order": "AB"})
    altered_order_manifest = PilotPairManifestV1(pairs=tuple(changed_orders))
    with pytest.raises(ValueError, match="exact typed manifest"):
        SFTPilotFactorAuthority(
            protocol,
            pair_manifest=altered_order_manifest,
            attestation_key=ATTESTATION_KEY,
        )

    changed_pairs = list(pair_manifest.pairs)
    changed_pairs[0] = changed_pairs[0].model_copy(update={"pair_id": "pair-other"})
    altered_pair_manifest = PilotPairManifestV1(pairs=tuple(changed_pairs))
    with pytest.raises(ValueError, match="exact typed manifest"):
        SFTPilotFactorAuthority(
            protocol,
            pair_manifest=altered_pair_manifest,
            attestation_key=ATTESTATION_KEY,
        )

    for updates in (
        {"pair_id": "pair-other"},
        {"case_commitment_sha256": _sha("other")},
        {"unit_commitment": "unit-other"},
        {"execution_ordinal": 5},
    ):
        arms = list(_arms())
        arms[0] = arms[0].model_copy(update=updates)
        arms[1] = arms[1].model_copy(update=updates)
        altered_arm_protocol = protocol.model_copy(
            update={"authorized_logical_arms": tuple(arms)}
        )
        with pytest.raises(
            ValueError,
            match="typed pair|logical pairs|ordinals|execution ordinal",
        ):
            SFTPilotFactorAuthority(
                altered_arm_protocol,
                pair_manifest=pair_manifest,
                attestation_key=ATTESTATION_KEY,
            )

    legacy_internal_root = _legacy_factor_pair_manifest_sha256()
    assert legacy_internal_root != pair_manifest.digest
    legacy_protocol = protocol.model_copy(
        update={"pair_manifest_sha256": legacy_internal_root}
    )
    with pytest.raises(ValueError, match="exact typed manifest"):
        SFTPilotFactorAuthority(
            legacy_protocol,
            pair_manifest=pair_manifest,
            attestation_key=ATTESTATION_KEY,
        )


def test_typed_experiment_and_factor_authority_share_one_pair_truth() -> None:
    cases = _case_manifest()
    pairs = _pair_manifest()
    candidates = _candidate_manifest()
    runner = _runner_manifest()
    schedule = _schedule()
    protocols = tuple(
        _protocol(
            method_arm=method,
            case_manifest=cases,
            pair_manifest=pairs,
            candidate_manifest=candidates,
            runner_manifest=runner,
            execution_schedule=schedule,
        )
        for method in ("current", "sft_unified")
    )
    experiment_arms = tuple(
        PilotExperimentArmV1(
            method_arm=protocol.method_arm,
            child_protocol_sha256=protocol.digest,
            implementation_sha256=_sha(f"implementation-{protocol.method_arm}"),
            state_dir_commitment_sha256=_sha(f"state-{protocol.method_arm}"),
            execution_schedule_sha256=schedule.digest,
        )
        for protocol in protocols
    )
    experiment = PilotExperimentManifestV1(
        experiment_id="factor-pair-truth-cross-test",
        case_manifest_sha256=cases.digest,
        pair_manifest_sha256=pairs.digest,
        candidate_manifest_sha256=candidates.digest,
        runner_manifest_sha256=runner.digest,
        model_config_sha256=_sha("model-config"),
        execution_schedule_sha256=schedule.digest,
        arms=experiment_arms,
        blocked_arm_orders=tuple(
            PilotBlockedArmOrderV1(
                block_ordinal=ordinal,
                unit_commitment=f"unit-{ordinal}",
                arm_order=(
                    ("current", "sft_unified")
                    if ordinal % 2 == 0
                    else ("sft_unified", "current")
                ),
            )
            for ordinal in range(6)
        ),
    )
    validate_experiment_children(
        experiment,
        protocols=protocols,
        case_manifest=cases,
        pair_manifest=pairs,
        candidate_manifest=candidates,
        runner_manifest=runner,
        execution_schedule=schedule,
    )
    authority = SFTPilotFactorAuthority(
        protocols[1],
        pair_manifest=pairs,
        attestation_key=ATTESTATION_KEY,
    )
    assert authority.protocol.pair_manifest_sha256 == pairs.digest
    assert authority.arm_orders == tuple(item.arm_order for item in pairs.pairs)
    assert authority.factor_assignment_schedule_sha256 != pairs.digest


@pytest.mark.parametrize(
    "binder_version",
    [PHASE_FACTOR_BINDER_VERSION, PHASE_FULL_FACTOR_BINDER_VERSION],
)
def test_phase_arm_requires_exact_registry_proof_and_runner_attestation(
    binder_version: str,
) -> None:
    harness = Harness(binder_version=binder_version)
    attempt = harness.open_attempt(0)
    pair = harness.authority.make_pair_execution(
        plan=harness.plan,
        attempt=attempt,
        source_root_id=_sha("proof-source-root"),
        target_root_id=_sha("proof-target-root"),
        source_started_seq=1,
        source_finished_seq=2,
        target_started_seq=3,
        target_finished_seq=4,
    )
    receipt = harness.authority.make_phase_arm_receipt(
        registry=harness.registry,
        registered=harness.edge,
        plan=harness.plan,
        attempt=attempt,
        arm="source",
        root_id=pair.source_root_id,
        paired_arm_root_id=pair.target_root_id,
        pair_execution_receipt=pair,
        activation_trace_root=_sha("proof-activation"),
        usage=ExecutionUsage(
            messages=1,
            model_calls=1,
            input_tokens=100,
            output_tokens=20,
            wall_time_ms=100,
            cost_microusd=100,
        ),
        execution_class="completed",
        outcome=DenseOutcome(
            V=0.5,
            K=0.8,
            U=0.8,
            P=0.8,
            S=0.8,
            stage_score=0.5,
            C=10.0,
            D=1.0,
        ),
    )
    verifier = harness.authority.capabilities(harness.registry)[
        "arm_receipt_verifier"
    ]
    assert verifier(receipt, harness.plan, attempt.assignment)
    assert receipt.composition_id == harness.edge.source_composition.composition_id
    assert receipt.activated_direct_factor_revision_ids == (
        harness.edge.source_factor.revision_id,
    )
    assert not verifier(
        receipt.model_copy(update={"binding_proof_id": "proof:substituted"}),
        harness.plan,
        attempt.assignment,
    )
    assert not verifier(
        receipt.model_copy(update={"attestation_sha256": _sha("wrong-arm-domain")}),
        harness.plan,
        attempt.assignment,
    )
    capability_names = harness.authority.capabilities(harness.registry)
    assert not set(harness.authority.uncovered_capabilities).intersection(
        capability_names
    )


@pytest.mark.parametrize(
    ("authority_binder", "edge_binder"),
    [
        (PHASE_FACTOR_BINDER_VERSION, PHASE_FULL_FACTOR_BINDER_VERSION),
        (PHASE_FULL_FACTOR_BINDER_VERSION, PHASE_FACTOR_BINDER_VERSION),
    ],
)
def test_phase_arm_maker_rejects_cross_version_registered_edge(
    authority_binder: str,
    edge_binder: str,
) -> None:
    owner = Harness(binder_version=authority_binder)
    foreign = Harness(binder_version=edge_binder)
    attempt = owner.open_attempt(0)
    pair = owner.authority.make_pair_execution(
        plan=owner.plan,
        attempt=attempt,
        source_root_id=_sha(f"cross-source:{authority_binder}"),
        target_root_id=_sha(f"cross-target:{authority_binder}"),
        source_started_seq=1,
        source_finished_seq=2,
        target_started_seq=3,
        target_finished_seq=4,
    )
    with pytest.raises(ValueError, match="protocol rejects"):
        owner.authority.make_phase_arm_receipt(
            registry=foreign.registry,
            registered=foreign.edge,
            plan=owner.plan,
            attempt=attempt,
            arm="source",
            root_id=pair.source_root_id,
            paired_arm_root_id=pair.target_root_id,
            pair_execution_receipt=pair,
            activation_trace_root=_sha("cross-version-activation"),
            usage=ExecutionUsage(
                messages=1,
                model_calls=1,
                input_tokens=100,
                output_tokens=20,
                wall_time_ms=100,
                cost_microusd=100,
            ),
            execution_class="completed",
            outcome=DenseOutcome(
                V=0.5,
                K=0.8,
                U=0.8,
                P=0.8,
                S=0.8,
                stage_score=0.5,
                C=10.0,
                D=1.0,
            ),
        )


def test_full_v3_pair_receipts_name_only_changed_factor_and_full_compositions() -> None:
    harness = Harness(binder_version=PHASE_FULL_FACTOR_BINDER_VERSION)
    harness.complete_benefit(0)
    attempt = harness.bank.attempts[next(iter(harness.bank.attempts))]
    assert attempt.source_receipt is not None
    assert attempt.target_receipt is not None
    assert attempt.source_receipt.composition_id == (
        harness.edge.source_composition.composition_id
    )
    assert attempt.target_receipt.composition_id == (
        harness.edge.target_composition.composition_id
    )
    assert attempt.source_receipt.activated_direct_factor_revision_ids == (
        harness.edge.source_factor.revision_id,
    )
    assert attempt.target_receipt.activated_direct_factor_revision_ids == (
        harness.edge.target_factor.revision_id,
    )
    assert len(harness.edge.source_composition.bindings) > 2


def test_receipts_reject_wrong_attestation_domain_unit_order_and_key(
    tmp_path: Path,
) -> None:
    harness = Harness()
    assignment = harness.authority.make_assignment(harness.plan, ordinal=0)
    forged_attestation = assignment.model_copy(
        update={"attestation_sha256": _sha("wrong-domain")}
    )
    assert not harness.authority.verify_assignment(
        forged_attestation,
        harness.plan,
    )
    forged_unit = assignment.model_copy(
        update={"unit_commitment": harness.authority.unit_commitments[1]}
    )
    assert not harness.authority.verify_assignment(forged_unit, harness.plan)
    forged_order = assignment.model_copy(update={"arm_order": "BA"})
    assert not harness.authority.verify_assignment(forged_order, harness.plan)

    harness.complete_benefit(0)
    state_path = tmp_path / "wrong-key-factor-bank.json"
    harness.bank.save(state_path)
    wrong_key_authority = SFTPilotFactorAuthority(
        harness.protocol,
        pair_manifest=harness.pair_manifest,
        attestation_key=hashlib.sha256(b"different-factor-key").digest(),
    )
    with pytest.raises(ValueError, match="assignment|attempt"):
        FactorBankV2.load(
            state_path,
            state_key=FACTOR_STATE_KEY,
            **wrong_key_authority.capabilities(harness.registry),
        )


def test_zero_start_cancellation_is_authenticated_and_reloadable(
    tmp_path: Path,
) -> None:
    harness = Harness()
    attempt = harness.open_attempt(0)
    assignment_sha256 = canonical_sha256(attempt.assignment)
    open_attempt_sha256 = canonical_sha256(attempt)
    schedule_event_id = "schedule:cancellation"
    abort_event_id = "abort:cancellation"
    schedule = runner_schedule_commitment_v1(
        expected_open_attempt_sha256=open_attempt_sha256,
        assignment_receipt_sha256=assignment_sha256,
        plan_id=harness.plan.plan_id,
        ordinal=attempt.ordinal,
        scheduled_arm_order=attempt.assignment.arm_order,
        runner_session_id=attempt.runner_lease.runner_session_id,
        runner_lease_token_sha256=(
            attempt.runner_lease.runner_lease_token_sha256
        ),
        fencing_generation=attempt.runner_lease.fencing_generation,
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        prestart_schedule_event_id=schedule_event_id,
        prestart_schedule_event_seq=0,
    )
    event_root = cancellation_event_root_v3(
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        schedule_commitment_sha256=schedule,
        started_arm_roots=(),
        abort_event_id=abort_event_id,
        abort_event_seq=1,
        cancel_kind="infrastructure",
        safe_failure_code="runner_unavailable",
        terminate_scope=False,
        runner_lease_token_sha256=(
            attempt.runner_lease.runner_lease_token_sha256
        ),
        fencing_generation=1,
        next_fencing_generation=2,
    )
    unsigned = AttemptCancellationReceiptV3(
        cancellation_id=_opaque(
            "ac",
            {
                "attempt": open_attempt_sha256,
                "runner_lease": attempt.runner_lease.digest,
                "terminal_event_root": event_root,
            },
        ),
        attempt_id=attempt.attempt_id,
        plan_id=harness.plan.plan_id,
        ordinal=attempt.ordinal,
        assignment_receipt_sha256=assignment_sha256,
        expected_opened_seq=attempt.opened_seq,
        expected_open_attempt_sha256=open_attempt_sha256,
        scheduled_arm_order=attempt.assignment.arm_order,
        runner_lease_sha256=attempt.runner_lease.digest,
        runner_session_id=attempt.runner_lease.runner_session_id,
        runner_lease_token_sha256=(
            attempt.runner_lease.runner_lease_token_sha256
        ),
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        prestart_schedule_event_id=schedule_event_id,
        prestart_schedule_event_seq=0,
        schedule_commitment_sha256=schedule,
        abort_event_id=abort_event_id,
        abort_event_seq=1,
        runner_event_root_sha256=event_root,
        cancel_kind="infrastructure",
        safe_failure_code="runner_unavailable",
        terminate_scope=False,
        verifier_epoch=harness.authority.verifier_epoch,
        attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
    )
    cancellation = harness.authority.attest_cancellation(
        unsigned,
        attempt=attempt,
        plan=harness.plan,
    )
    assert harness.authority.verify_cancellation(
        cancellation,
        attempt,
        harness.plan,
    )
    assert not harness.authority.verify_cancellation(
        cancellation.model_copy(
            update={"attestation_sha256": _sha("cancellation-wrong-domain")}
        ),
        attempt,
        harness.plan,
    )
    cancelled = harness.bank.cancel_open_attempt(
        attempt.attempt_id,
        cancellation,
    )
    assert cancelled.state == "cancelled"
    state_path = tmp_path / "cancelled-factor-bank.json"
    harness.bank.save(state_path)
    assert FactorBankV2.load(
        state_path,
        state_key=FACTOR_STATE_KEY,
        **harness.authority.capabilities(harness.registry),
    ).attempts[attempt.attempt_id].state == "cancelled"


def test_archive_domain_is_protocol_and_key_separated() -> None:
    pair_manifest = _pair_manifest()
    authority = SFTPilotFactorAuthority(
        _protocol(pair_manifest=pair_manifest),
        pair_manifest=pair_manifest,
        attestation_key=ATTESTATION_KEY,
    )
    root = _sha("archive-root")
    attestation = authority.archive_attestation(root)
    assert authority.verify_archive(root, attestation)
    assert not authority.verify_archive(_sha("other-root"), attestation)
    assert not authority.verify_archive(
        root,
        authority.assignment_producer_epoch.ljust(64, "0")[:64],
    )
    other = SFTPilotFactorAuthority(
        _protocol(namespace=_namespace(information_goal="all_agents")),
        pair_manifest=_pair_manifest(),
        attestation_key=ATTESTATION_KEY,
    )
    assert not other.verify_archive(root, attestation)
