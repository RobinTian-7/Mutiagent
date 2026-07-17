from __future__ import annotations

import hashlib
import hmac
import threading
from pathlib import Path
from typing import Any

import pytest

from exp_graph.mas.factor_bank import DenseOutcome, ExecutionNamespace
from exp_graph.mas.factor_bank_v2 import FactorBankV2
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    SourceManifest,
)
from exp_graph.mas.phase_factor_binding_v2 import (
    make_phase_v2_binding_verifier,
    register_phase_materialization_v2,
)
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgram,
    PhaseProgramLimits,
)
from exp_graph.mas.sft_journal import (
    CheckpointProviderSnapshotV2,
    CheckpointUpdateClaimV2,
    JournalCheckpointV2,
    JournalScopeV2,
    PreparePayloadV2,
    SFTRunnerJournal,
    journal_canonical_sha256_v2,
    journal_fixed_hmac_sha256_v2,
)
from exp_graph.mas.sft_journal_snapshot import (
    ScopeManifestVerificationV1,
    SnapshotTrustPolicyV1,
    journal_key_commitment_v1,
    journal_locator_commitment_v1,
    load_verified_snapshot,
)

from masbench.engine import (
    ExactRegisteredPhaseExecution,
    exact_phase_arm_commitment_v1,
    register_exact_phase_execution_result,
)
from masbench.sft_pilot.execution_attestation import (
    PilotExecutionAttestationV1,
    PilotExecutionAttestor,
    PilotExecutionCapabilityBodyV1,
    PilotFinalValOutcomeReceiptV1,
    PilotOutcomeScorer,
    PilotTrainUpdateOutcomeReceiptV1,
    factor_arm_evidence_from_receipts,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotCapacityPreflightV1,
    PilotExecutionLeaseRequestV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
    canonical_sha256,
)
from masbench.sft_pilot.store import SingleWriterPilotStore


ENGINE_KEY = hashlib.sha256(b"exact-phase-engine-key").digest()
SCORER_KEY = hashlib.sha256(b"isolated-scalar-scorer-key").digest()
STORE_KEY = hashlib.sha256(b"execution-attestation-store-key").digest()
REGISTRY_KEY = hashlib.sha256(b"execution-attestation-registry-key").digest()
FACTOR_KEY = hashlib.sha256(b"execution-attestation-factor-key").digest()
JOURNAL_KEY = hashlib.sha256(b"execution-attestation-journal-key").digest()
READER_KEY = hashlib.sha256(b"execution-attestation-reader-key").digest()
MANIFEST_KEY = hashlib.sha256(b"execution-attestation-manifest-key").digest()
PROVIDER_EPOCH = hashlib.sha256(b"execution-provider-epoch").hexdigest()
MANIFEST_EPOCH = hashlib.sha256(b"execution-manifest-epoch").hexdigest()
READER_POLICY = hashlib.sha256(b"execution-reader-policy").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _host_id(prefix: str, label: str) -> str:
    return f"{prefix}:{_sha(label)[:24]}"


def _namespace(*, information_goal: str = "sink") -> ExecutionNamespace:
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
        runtime_version="exact-phase-runner-v1",
        binder_version=PHASE_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _arms() -> tuple[PilotLogicalArmCoordinatesV1, ...]:
    result: list[PilotLogicalArmCoordinatesV1] = []
    for arm in ("source", "target"):
        result.append(
            PilotLogicalArmCoordinatesV1(
                pair_id="pair-train",
                pair_arm=arm,
                case_commitment_sha256=_sha("case:TRAIN_UPDATE"),
                unit_commitment="unit-train-update",
                split="TRAIN_UPDATE",
                operation_kind=(
                    "source_probe" if arm == "source" else "target_probe"
                ),
                execution_ordinal=0,
            )
        )
    result.append(
        PilotLogicalArmCoordinatesV1(
            pair_id="pair-final",
            pair_arm="control",
            case_commitment_sha256=_sha("case:FINAL_VAL"),
            unit_commitment="unit-final-val",
            split="FINAL_VAL",
            operation_kind="final_val",
            execution_ordinal=0,
        )
    )
    return tuple(result)


def _protocol(
    *,
    information_goal: str = "sink",
    method_arm: str = "sft_unified",
) -> PilotProtocolV1:
    arms = _arms()
    return PilotProtocolV1(
        protocol_id=f"execution-boundary-{information_goal}-{method_arm}",
        method_arm=method_arm,
        namespace=_namespace(information_goal=information_goal),
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("source-catalog"),
            source_policy_sha256=_sha("source-policy"),
        ),
        source_authority_sha256=_sha("source-authority"),
        dataset_split_policy_sha256=_sha("split-policy"),
        candidate_pool_manifest_sha256=_sha("candidate-pool"),
        runner_config_sha256=_sha("runner-config"),
        model_config_sha256=_sha("model-config"),
        pair_manifest_sha256=canonical_sha256(arms),
        genesis_state_sha256=_sha("genesis"),
        authorized_logical_arms=arms,
        phase_budgets=tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm=method_arm,
                executions=4,
                call_slots=4,
                input_tokens=4_000,
                output_tokens=800,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=8,
            max_execution_leases=8,
            max_call_receipts=8,
            max_call_slots_per_execution=1,
            max_input_tokens_per_call=1_000,
            max_output_tokens_per_call=200,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=4 * 1024 * 1024,
        ),
    )


class _BranchVerifier:
    def __call__(self, receipt: Any) -> bool:
        return bool(
            receipt.producer_epoch == "branch-host:execution-boundary"
            and receipt.attestation_sha256 == _sha("branch-attestation")
        )


class _ExactManifestVerifier:
    def __init__(self, expected: Any) -> None:
        self._expected = expected

    def __call__(self, candidate: Any) -> bool:
        return candidate == self._expected


def _program(hub: int) -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": [
                {
                    "kind": "gather",
                    "hub": hub,
                    "pattern": "tree",
                    "instruction": "gather concise evidence",
                }
            ],
        }
    )


def _registry_edge(protocol: PilotProtocolV1):
    manifest = SourceManifest(
        manifest_sha256=_sha("phase-source-manifest"),
        split="TRAIN_UPDATE",
        source_catalog_sha256=protocol.source_manifest.source_catalog_sha256,
        policy_sha256=protocol.source_manifest.source_policy_sha256,
        producer_version="exact-phase-host-v1",
    )
    registry = PhaseArtifactRegistry(
        registry_key=REGISTRY_KEY,
        manifests=(manifest,),
        manifest_verifier=_ExactManifestVerifier(manifest),
        branch_receipt_verifier=_BranchVerifier(),
    )
    profile = registry.register_runtime_profile(
        namespace=protocol.namespace,
        limits=PhaseProgramLimits(),
    )
    ingress = registry.issue_ingress(manifest.manifest_sha256)
    source_artifact = registry.ingest_program(
        _program(0), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source_artifact, locator="/phases/0/hub"
    )
    branch = registry.register_branch_receipt(
        branch="mutate",
        source_artifact=source_artifact,
        locator="/phases/0/hub",
        mutation_parent_factor=source_factor.factor,
        additional_input_root_commitments=(_sha("sanitized-train-input"),),
        producer_epoch="branch-host:execution-boundary",
        attestation_sha256=_sha("branch-attestation"),
    )
    seal = registry.seal_operation(branch_receipt=branch)
    generated = registry.register_generated_value(1, operation_seal=seal, ingress=ingress)
    proof = registry.materialize(operation_seal=seal, target_factor=generated.factor)
    assert isinstance(proof, PhaseBindingProofHandle)
    bank = FactorBankV2(
        state_key=FACTOR_KEY,
        direct_binding_verifier=make_phase_v2_binding_verifier(registry),
    )
    edge = register_phase_materialization_v2(
        registry=registry, bank=bank, proof=proof
    )
    return registry, edge


class _CheckpointProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.latest: JournalCheckpointV2 | None = None
        self.pending: CheckpointUpdateClaimV2 | None = None

    def bootstrap(self, checkpoint: JournalCheckpointV2) -> None:
        self.latest = checkpoint

    def inspect(self, journal_id: str) -> CheckpointProviderSnapshotV2:
        with self._lock:
            return CheckpointProviderSnapshotV2(
                journal_id=journal_id,
                provider_epoch_sha256=PROVIDER_EPOCH,
                latest_checkpoint=self.latest,
                pending_claim=self.pending,
            )

    def claim_update(
        self,
        *,
        journal_id: str,
        expected_checkpoint: JournalCheckpointV2,
        proposed_checkpoint: JournalCheckpointV2,
    ) -> CheckpointUpdateClaimV2:
        with self._lock:
            if self.latest != expected_checkpoint or self.pending is not None:
                raise RuntimeError("checkpoint CAS failed")
            self.pending = CheckpointUpdateClaimV2(
                claim_token_sha256=_sha(
                    expected_checkpoint.digest + proposed_checkpoint.digest
                ),
                journal_id=journal_id,
                expected_checkpoint=expected_checkpoint,
                proposed_checkpoint=proposed_checkpoint,
                provider_epoch_sha256=PROVIDER_EPOCH,
            )
            return self.pending

    def acknowledge(self, checkpoint: JournalCheckpointV2) -> None:
        with self._lock:
            assert self.pending is not None
            assert self.pending.proposed_checkpoint == checkpoint
            self.latest = checkpoint
            self.pending = None


class _JournalAuthorities:
    def __init__(
        self,
        *,
        path: Path,
        locator_id: str,
        journal_id: str,
        manifest_sha256: str,
    ) -> None:
        self.path = path.resolve()
        self.locator_id = locator_id
        self.journal_id = journal_id
        self.manifest_sha256 = manifest_sha256
        self.locator_sha256 = journal_locator_commitment_v1(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
            resolved_path=self.path,
        )

    def _check(self, journal_locator_id: str, expected_journal_id: str) -> None:
        if (journal_locator_id, expected_journal_id) != (
            self.locator_id,
            self.journal_id,
        ):
            raise KeyError("unknown journal authority tuple")

    def resolve_journal_path(self, **kwargs: str) -> Path:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return self.path

    def pinned_locator_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return self.locator_sha256

    def resolve_journal_hmac_key(self, **kwargs: str) -> bytes:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return JOURNAL_KEY

    def resolve_reader_hmac_key(self, **kwargs: str) -> bytes:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return READER_KEY

    def pinned_journal_key_commitment_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return journal_key_commitment_v1(role="journal", key=JOURNAL_KEY)

    def pinned_reader_key_commitment_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return journal_key_commitment_v1(role="reader", key=READER_KEY)

    def reader_policy_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return READER_POLICY

    def verifier_policy_sha256(self) -> str:
        return journal_canonical_sha256_v2(
            {
                "domain": "execution-test-manifest-verifier-v1",
                "epoch": MANIFEST_EPOCH,
                "key_sha256": hashlib.sha256(MANIFEST_KEY).hexdigest(),
            }
        )

    def verify_scope_manifest(
        self, scope: JournalScopeV2
    ) -> ScopeManifestVerificationV1:
        body = {
            "verification_version": "sft_scope_manifest_verification_v1",
            "manifest_sha256": self.manifest_sha256,
            "source": scope.mode_payload_source,
            "scope_sha256": scope.digest,
            "verifier_epoch_sha256": MANIFEST_EPOCH,
        }
        return ScopeManifestVerificationV1(
            **body,
            verifier_attestation_sha256=journal_fixed_hmac_sha256_v2(
                MANIFEST_KEY,
                domain="sft-scope-manifest-verification-v1",
                value=body,
            ),
        )

    def validate_scope_manifest_verification(
        self,
        *,
        scope: JournalScopeV2,
        verification: ScopeManifestVerificationV1,
    ) -> None:
        expected = journal_fixed_hmac_sha256_v2(
            MANIFEST_KEY,
            domain="sft-scope-manifest-verification-v1",
            value=verification.model_dump(
                mode="python", exclude={"verifier_attestation_sha256"}
            ),
        )
        if not (
            verification.manifest_sha256 == self.manifest_sha256
            and verification.scope_sha256 == scope.digest
            and hmac.compare_digest(
                verification.verifier_attestation_sha256, expected
            )
        ):
            raise ValueError("scope manifest verification failed")


def _verified_pair_snapshot(
    tmp_path: Path,
    *,
    protocol: PilotProtocolV1,
    registry: PhaseArtifactRegistry,
    edge: Any,
    pair_arm: PilotLogicalArmCoordinatesV1,
    tag: str,
):
    proof = registry.resolve_proof(edge.proof)
    source_artifact = registry.resolve_artifact(proof.source_artifact)
    target_artifact = registry.resolve_artifact(proof.target_artifact)
    pair = [
        item
        for item in protocol.authorized_logical_arms
        if item.pair_id == pair_arm.pair_id and item.split == pair_arm.split
    ]
    source = next(item for item in pair if item.pair_arm == "source")
    target = next(item for item in pair if item.pair_arm == "target")
    scope = JournalScopeV2(
        namespace=protocol.namespace,
        namespace_sha256=protocol.namespace.digest,
        planner_mode=protocol.namespace.planner_mode,
        information_goal=protocol.namespace.information_goal,
        worker_contract=protocol.namespace.worker_contract,
        mode_payload_sha256=source_artifact.execution_image_commitment,
        mode_payload_source="TRAIN_UPDATE",
        mode_payload_manifest_sha256=proof.source_manifest_sha256,
        runner_policy_sha256=_sha("exact-nonoverlap-policy-v1"),
    )
    provider = _CheckpointProvider()
    journal_id = _host_id("jr", f"journal:{tag}")
    locator_id = _host_id("jl", f"locator:{tag}")
    journal = SFTRunnerJournal(
        journal_key=JOURNAL_KEY,
        journal_id=journal_id,
        scope=scope,
        checkpoint_provider=provider,
        scope_manifest_verifier=_ExactManifestVerifier(scope),
    )
    provider.bootstrap(journal.checkpoint())
    path = tmp_path / f"journal-{tag}.json"
    journal.save(path)
    intent = PreparePayloadV2(
        attempt_id=_host_id("at", f"attempt:{tag}"),
        plan_id=_host_id("pp", f"plan:{tag}"),
        ordinal=pair_arm.execution_ordinal,
        assignment_receipt_sha256=_sha(f"assignment:{tag}"),
        expected_open_attempt_sha256=_sha(f"open:{tag}"),
        scheduled_arm_order="AB",
        runner_session_id=_host_id("rs", f"session:{tag}"),
        runner_lease_token_sha256=_sha(f"lease:{tag}"),
        verifier_epoch_sha256=_sha("journal-verifier-v2"),
        source_arm_commitment_sha256=exact_phase_arm_commitment_v1(
            protocol,
            source,
            proof_id=proof.handle.handle_id,
            proof_sha256=proof.handle.proof_sha256,
            artifact_sha256=source_artifact.execution_image_commitment,
        ),
        target_arm_commitment_sha256=exact_phase_arm_commitment_v1(
            protocol,
            target,
            proof_id=proof.handle.handle_id,
            proof_sha256=proof.handle.proof_sha256,
            artifact_sha256=target_artifact.execution_image_commitment,
        ),
    )
    journal.prepare_attempt(intent)
    provider.acknowledge(journal.checkpoint())
    for arm in ("source", "target"):
        journal.start_arm(
            intent.attempt_id,
            arm=arm,
            physical_root_id=_sha(f"physical:{tag}:{arm}"),
        )
        provider.acknowledge(journal.checkpoint())
        journal.finish_arm(intent.attempt_id, arm=arm)
        provider.acknowledge(journal.checkpoint())
    journal.complete_pair(intent.attempt_id)
    provider.acknowledge(journal.checkpoint())
    authorities = _JournalAuthorities(
        path=path,
        locator_id=locator_id,
        journal_id=journal_id,
        manifest_sha256=proof.source_manifest_sha256,
    )
    trust = SnapshotTrustPolicyV1(
        journal_locator_id=locator_id,
        journal_id=journal_id,
        scope_sha256=scope.digest,
        journal_locator_sha256=authorities.locator_sha256,
        journal_key_commitment_sha256=journal_key_commitment_v1(
            role="journal", key=JOURNAL_KEY
        ),
        reader_key_commitment_sha256=journal_key_commitment_v1(
            role="reader", key=READER_KEY
        ),
        reader_policy_sha256=READER_POLICY,
        provider_epoch_sha256=PROVIDER_EPOCH,
        manifest_verifier_epoch_sha256=MANIFEST_EPOCH,
        manifest_verifier_policy_sha256=authorities.verifier_policy_sha256(),
    )
    return load_verified_snapshot(
        journal_locator_id=locator_id,
        expected_journal_id=journal_id,
        expected_scope=scope,
        expected_trust_policy=trust,
        journal_key_resolver=authorities,
        journal_locator_resolver=authorities,
        checkpoint_provider=provider,
        scope_manifest_verifier=authorities,
    )


def _completed_store_execution(
    store: SingleWriterPilotStore,
    *,
    arm: PilotLogicalArmCoordinatesV1,
    tag: str,
) -> tuple[str, tuple[str, ...]]:
    execution_key = f"execution-{tag}"
    call_key = f"call-{tag}"
    request_sha = _sha(f"request:{tag}")
    store.reserve_execution(
        PilotExecutionLeaseRequestV1(
            logical_execution_key=execution_key,
            operation_kind=arm.operation_kind,
            request_sha256=request_sha,
            namespace_sha256=store.protocol.namespace.digest,
            split=arm.split,
            unit_commitment=arm.unit_commitment,
            call_slots_reserved=1,
            input_tokens_reserved=1_000,
            output_tokens_reserved=200,
        ),
        logical_arm=arm,
        operation_id=f"reserve-execution-{tag}",
        operation_request_sha256=_sha(f"reserve-execution:{tag}"),
    )
    store.reserve_call(
        operation_id=f"reserve-call-{tag}",
        operation_request_sha256=_sha(f"reserve-call:{tag}"),
        call_key=call_key,
        logical_execution_key=execution_key,
        call_slot=0,
        call_request_sha256=request_sha,
        input_tokens_reserved=1_000,
        output_tokens_reserved=200,
    )
    authorization = store.start_call(
        call_key,
        operation_id=f"start-call-{tag}",
        operation_request_sha256=_sha(f"start-call:{tag}"),
        call_request_sha256=request_sha,
    )
    assert authorization.may_invoke_sdk
    store.complete_call(
        call_key,
        operation_id=f"complete-call-{tag}",
        operation_request_sha256=_sha(f"complete-call:{tag}"),
        call_request_sha256=request_sha,
        output_envelope_sha256=_sha(f"envelope:{tag}"),
        provider_usage_known=True,
        input_tokens_used=20,
        output_tokens_used=5,
    )
    store.complete_execution(
        execution_key,
        operation_id=f"complete-execution-{tag}",
        operation_request_sha256=_sha(f"complete-execution:{tag}"),
    )
    return execution_key, (call_key,)


@pytest.fixture
def boundary(tmp_path: Path):
    protocol = _protocol()
    registry, edge = _registry_edge(protocol)
    store = SingleWriterPilotStore.open(
        tmp_path / "store", protocol=protocol, hmac_key=STORE_KEY
    )
    store.record_capacity_preflight(
        PilotCapacityPreflightV1(
            planned_scientific_commits=4,
            planned_execution_leases=4,
            planned_call_receipts=4,
            planned_max_calls_per_execution=1,
            planned_max_active_db_bytes=8 * 1024 * 1024,
            planned_archive_bytes=32 * 1024,
            planned_total_stored_scalar_bytes=2 * 1024 * 1024,
            planned_max_input_tokens_per_call=1_000,
            planned_max_output_tokens_per_call=200,
            quarantined_carriers_reserved=1,
            indeterminate_call_reserve=1,
        ),
        operation_id="capacity-preflight",
        request_sha256=_sha("capacity-preflight"),
    )
    receipts: dict[str, PilotExecutionAttestationV1] = {}
    registration_inputs: dict[str, dict[str, Any]] = {}
    attestor = PilotExecutionAttestor(protocol, engine_key=ENGINE_KEY)
    arm = next(
        item
        for item in protocol.authorized_logical_arms
        if item.split == "TRAIN_UPDATE" and item.pair_arm == "source"
    )
    execution_key, call_keys = _completed_store_execution(
        store, arm=arm, tag="train"
    )
    snapshot = _verified_pair_snapshot(
        tmp_path,
        protocol=protocol,
        registry=registry,
        edge=edge,
        pair_arm=arm,
        tag="train",
    )
    capability = register_exact_phase_execution_result(
        protocol=protocol,
        logical_arm=arm,
        registry=registry,
        registered_edge=edge,
        store=store,
        logical_execution_key=execution_key,
        call_keys=call_keys,
        journal_snapshot=snapshot,
        engine_key=ENGINE_KEY,
    )
    receipts["TRAIN_UPDATE"] = attestor.issue(capability)
    registration_inputs["TRAIN_UPDATE"] = {
        "arm": arm,
        "logical_execution_key": execution_key,
        "call_keys": call_keys,
        "journal_snapshot": snapshot,
    }
    scorer = PilotOutcomeScorer(
        protocol,
        scorer_key=SCORER_KEY,
        execution_attestor=attestor,
        scorer_id="scalar-scorer-v1",
        scorer_version_sha256=_sha("scalar-scorer-code-v1"),
    )
    yield (
        protocol,
        registry,
        edge,
        store,
        attestor,
        scorer,
        receipts,
        registration_inputs,
    )
    store.close()


def _metrics() -> DenseOutcome:
    return DenseOutcome(
        V=0.6,
        K=0.7,
        U=0.8,
        P=0.9,
        S=1.0,
        stage_score=0.6,
        C=25.0,
        D=2.0,
    )


def test_exact_capability_rejects_handwritten_models_and_tampered_roots(boundary) -> None:
    (
        protocol,
        registry,
        edge,
        store,
        attestor,
        _scorer,
        receipts,
        inputs,
    ) = boundary
    execution = receipts["TRAIN_UPDATE"]
    body = PilotExecutionCapabilityBodyV1.model_validate(
        execution.model_dump(
            mode="python",
            exclude={
                "attestation_version",
                "engine_key_commitment_sha256",
                "engine_capability_sha256",
                "execution_attestation_sha256",
            },
        )
    )
    with pytest.raises(TypeError, match="exact engine capability"):
        attestor.issue(body)
    with pytest.raises(ValueError, match="engine-owned"):
        ExactRegisteredPhaseExecution(body, _sha("handwritten"))

    wrong_call_root = execution.model_copy(
        update={"call_receipt_root_sha256": _sha("wrong-call-root")}
    )
    wrong_proof = execution.model_copy(
        update={"proof_sha256": _sha("wrong-proof")}
    )
    assert not attestor.verify(wrong_call_root)
    assert not attestor.verify(wrong_proof)
    assert attestor.verify(execution)
    assert execution.protocol_sha256 == protocol.digest
    persisted = canonical_sha256(execution)
    assert persisted and not hasattr(execution, "outcome")

    wrong_registered_proof = edge.model_copy(
        update={
            "proof": edge.proof.model_copy(
                update={"proof_sha256": _sha("wrong-registered-proof")}
            )
        }
    )
    train_inputs = inputs["TRAIN_UPDATE"]
    with pytest.raises(ValueError):
        register_exact_phase_execution_result(
            protocol=protocol,
            logical_arm=train_inputs["arm"],
            registry=registry,
            registered_edge=wrong_registered_proof,
            store=store,
            logical_execution_key=train_inputs["logical_execution_key"],
            call_keys=train_inputs["call_keys"],
            journal_snapshot=train_inputs["journal_snapshot"],
            engine_key=ENGINE_KEY,
        )


def test_indeterminate_call_cannot_enter_completed_call_root(
    boundary, tmp_path: Path
) -> None:
    protocol, registry, edge, store, _attestor, _scorer, _receipts, _inputs = boundary
    arm = next(
        item
        for item in protocol.authorized_logical_arms
        if item.split == "TRAIN_UPDATE" and item.pair_arm == "target"
    )
    execution_key = "execution-indeterminate"
    call_key = "call-indeterminate"
    request_sha = _sha("request:indeterminate")
    store.reserve_execution(
        PilotExecutionLeaseRequestV1(
            logical_execution_key=execution_key,
            operation_kind=arm.operation_kind,
            request_sha256=request_sha,
            namespace_sha256=protocol.namespace.digest,
            split=arm.split,
            unit_commitment=arm.unit_commitment,
            call_slots_reserved=1,
            input_tokens_reserved=1_000,
            output_tokens_reserved=200,
        ),
        logical_arm=arm,
        operation_id="reserve-execution-indeterminate",
        operation_request_sha256=_sha("reserve-execution:indeterminate"),
    )
    store.reserve_call(
        operation_id="reserve-call-indeterminate",
        operation_request_sha256=_sha("reserve-call:indeterminate"),
        call_key=call_key,
        logical_execution_key=execution_key,
        call_slot=0,
        call_request_sha256=request_sha,
        input_tokens_reserved=1_000,
        output_tokens_reserved=200,
    )
    store.start_call(
        call_key,
        operation_id="start-call-indeterminate",
        operation_request_sha256=_sha("start-call:indeterminate"),
        call_request_sha256=request_sha,
    )
    store.mark_call_indeterminate(
        call_key,
        operation_id="terminal-call-indeterminate",
        operation_request_sha256=_sha("terminal-call:indeterminate"),
        provider_usage_known=True,
        input_tokens_used=20,
        output_tokens_used=5,
    )
    snapshot = _verified_pair_snapshot(
        tmp_path,
        protocol=protocol,
        registry=registry,
        edge=edge,
        pair_arm=arm,
        tag="indeterminate",
    )
    with pytest.raises(ValueError, match="SQLite execution lease"):
        register_exact_phase_execution_result(
            protocol=protocol,
            logical_arm=arm,
            registry=registry,
            registered_edge=edge,
            store=store,
            logical_execution_key=execution_key,
            call_keys=(call_key,),
            journal_snapshot=snapshot,
            engine_key=ENGINE_KEY,
        )


def test_split_keys_modes_and_workers_are_closed(boundary) -> None:
    protocol, registry, edge, store, attestor, scorer, receipts, inputs = boundary
    train_execution = receipts["TRAIN_UPDATE"]
    train_outcome = scorer.score_train_update(train_execution, _metrics())
    assert type(train_outcome) is PilotTrainUpdateOutcomeReceiptV1

    final_arm = next(
        item for item in protocol.authorized_logical_arms if item.split == "FINAL_VAL"
    )
    train_inputs = inputs["TRAIN_UPDATE"]
    with pytest.raises(ValueError, match="TRAIN_UPDATE probe arms only"):
        register_exact_phase_execution_result(
            protocol=protocol,
            logical_arm=final_arm,
            registry=registry,
            registered_edge=edge,
            store=store,
            logical_execution_key=train_inputs["logical_execution_key"],
            call_keys=train_inputs["call_keys"],
            journal_snapshot=train_inputs["journal_snapshot"],
            engine_key=ENGINE_KEY,
        )

    wrong_key_attestor = PilotExecutionAttestor(
        protocol, engine_key=hashlib.sha256(b"wrong-engine-key").digest()
    )
    assert not wrong_key_attestor.verify(train_execution)
    wrong_key_scorer = PilotOutcomeScorer(
        protocol,
        scorer_key=hashlib.sha256(b"wrong-scorer-key").digest(),
        execution_attestor=attestor,
        scorer_id="scalar-scorer-v1",
        scorer_version_sha256=_sha("scalar-scorer-code-v1"),
    )
    assert not wrong_key_scorer.verify(train_outcome, train_execution)

    cross_mode = _protocol(information_goal="all_agents")
    cross_attestor = PilotExecutionAttestor(cross_mode, engine_key=ENGINE_KEY)
    assert not cross_attestor.verify(train_execution)
    python_namespace = protocol.namespace.model_copy(
        update={
            "planner_mode": "python_generate",
            "payload_format": "python_skill_v1",
            "worker_contract": "message_only_v2",
        }
    )
    python_protocol_payload = protocol.model_dump(mode="python")
    python_protocol_payload["namespace"] = python_namespace
    with pytest.raises(ValueError, match="exact Phase mode"):
        PilotExecutionAttestor(
            PilotProtocolV1.model_validate(python_protocol_payload),
            engine_key=ENGINE_KEY,
        )


def test_factor_join_requires_train_activation_and_mutating_method(boundary) -> None:
    protocol, _registry, edge, _store, attestor, scorer, receipts, _inputs = boundary
    train_execution = receipts["TRAIN_UPDATE"]
    train_outcome = scorer.score_train_update(train_execution, _metrics())
    evidence = factor_arm_evidence_from_receipts(
        protocol=protocol,
        execution=train_execution,
        outcome_receipt=train_outcome,
        expected_activated_factor_revision_id=edge.source_factor.revision_id,
        execution_attestor=attestor,
        scorer=scorer,
    )
    assert evidence.metrics == _metrics()
    assert evidence.execution_root_sha256 == train_execution.root_sha256
    assert evidence.outcome_root_sha256 == train_outcome.root_sha256

    with pytest.raises(ValueError, match="retrieved-but-not-activated"):
        factor_arm_evidence_from_receipts(
            protocol=protocol,
            execution=train_execution,
            outcome_receipt=train_outcome,
            expected_activated_factor_revision_id=edge.target_factor.revision_id,
            execution_attestor=attestor,
            scorer=scorer,
        )
    final_outcome = PilotFinalValOutcomeReceiptV1(
        **train_outcome.model_dump(
            mode="python", exclude={"receipt_kind", "split"}
        ),
        receipt_kind="final_val",
        split="FINAL_VAL",
    )
    with pytest.raises(TypeError, match="TRAIN_UPDATE receipt type only"):
        factor_arm_evidence_from_receipts(
            protocol=protocol,
            execution=train_execution,
            outcome_receipt=final_outcome,  # type: ignore[arg-type]
            expected_activated_factor_revision_id=edge.source_factor.revision_id,
            execution_attestor=attestor,
            scorer=scorer,
        )

    shadow_protocol = _protocol(method_arm="sft_shadow")
    with pytest.raises(ValueError, match="no Factor-evidence capability"):
        factor_arm_evidence_from_receipts(
            protocol=shadow_protocol,
            execution=train_execution,
            outcome_receipt=train_outcome,
            expected_activated_factor_revision_id=edge.source_factor.revision_id,
            execution_attestor=attestor,
            scorer=scorer,
        )
    algorithm_failure = scorer.score_train_update(
        train_execution,
        _metrics(),
        terminal_class="algorithm_failure",
    )
    no_failure_protocol = _protocol(method_arm="sft_no_failure_memory")
    with pytest.raises(ValueError, match="forbids algorithm-failure memory"):
        factor_arm_evidence_from_receipts(
            protocol=no_failure_protocol,
            execution=train_execution,
            outcome_receipt=algorithm_failure,
            expected_activated_factor_revision_id=edge.source_factor.revision_id,
            execution_attestor=attestor,
            scorer=scorer,
        )


def test_scorer_receipt_cannot_be_handwritten_or_cross_execution(boundary) -> None:
    (
        _protocol_value,
        _registry,
        _edge,
        _store,
        _attestor,
        scorer,
        receipts,
        _inputs,
    ) = boundary
    train_execution = receipts["TRAIN_UPDATE"]
    train_outcome = scorer.score_train_update(train_execution, _metrics())
    assert scorer.verify(train_outcome, train_execution)
    cross_execution = train_execution.model_copy(
        update={"physical_execution_root_sha256": _sha("other-execution")}
    )
    assert not scorer.verify(train_outcome, cross_execution)

    tampered = train_outcome.model_copy(
        update={"metrics": _metrics().model_copy(update={"V": 0.99})}
    )
    assert not scorer.verify(tampered, train_execution)
    with pytest.raises(ValueError, match="abstract"):
        from masbench.sft_pilot.execution_attestation import PilotOutcomeReceiptV1

        PilotOutcomeReceiptV1(
            **train_outcome.model_dump(
                mode="python",
                exclude={"receipt_kind", "split"},
            ),
            receipt_kind="train_update",
            split="TRAIN_UPDATE",
        )
