from __future__ import annotations

import hashlib
import hmac
import json
import threading

import pytest
from pydantic import ValidationError

import exp_graph.mas.phase_artifact_registry as phase_registry_module
from exp_graph.mas.factor_bank import ExecutionBudget, ExecutionNamespace, ExecutionUsage
from exp_graph.mas.phase_artifact_registry import (
    LegacyPhaseArtifactRegistryRejected,
    PHASE_ARTIFACT_REGISTRY_VERSION,
    PHASE_FACTOR_BINDER_VERSION,
    PHASE_MATERIALIZATION_EVENT_DIGEST_VERSION,
    NoOpMaterialization,
    PhaseArtifactRegistry,
    PhaseArtifactRegistryState,
    PhaseBindingProofHandle,
    PhaseGenerationTerminalV1,
    RegistryCapacity,
    SourceManifest,
    phase_generated_scalar_sha256,
    phase_materialization_event_sha256_v1,
)
from exp_graph.mas.phase_program import PhaseProgram, PhaseProgramLimits


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _budget() -> ExecutionBudget:
    return ExecutionBudget(
        max_messages=1,
        max_model_calls=1,
        max_input_tokens=1024,
        max_output_tokens=64,
        max_wall_time_ms=30_000,
        max_cost_microusd=1_000,
    )


def _usage() -> ExecutionUsage:
    return ExecutionUsage(
        messages=1,
        model_calls=1,
        input_tokens=100,
        output_tokens=8,
        wall_time_ms=500,
        cost_microusd=20,
    )


def _generation_terminal(
    *,
    action_id: str,
    intent_sha256: str,
    branch: str,
    value,
    tag: str,
    budget: ExecutionBudget | None = None,
    usage: ExecutionUsage | None = None,
) -> PhaseGenerationTerminalV1:
    sealed_budget = budget or _budget()
    return PhaseGenerationTerminalV1(
        terminal_id=f"terminal:{tag}",
        action_transaction_id=action_id,
        action_intent_sha256=intent_sha256,
        branch=branch,
        generation_request_id=f"request:{tag}",
        generation_request_sha256=_h(f"request:{tag}"),
        generation_lease_id=f"lease:{tag}",
        generation_lease_sha256=_h(f"lease:{tag}"),
        runner_lease_token_sha256=_h(f"lease-token:{tag}"),
        generation_lease_started_sequence=10,
        runtime_version="openai-runtime-v1",
        budget=sealed_budget,
        budget_sha256=sealed_budget.digest,
        usage=usage or _usage(),
        generated_scalar_sha256=phase_generated_scalar_sha256(value),
        response_envelope_sha256=_h(f"response-envelope:{tag}"),
        terminal_event_id=f"generation-event:{tag}",
        terminal_event_sequence=11,
        verifier_epoch="generation-host:v1",
        attestation_sha256=_h(f"generation-attestation:{tag}"),
    )


def _generation_roots(
    terminal: PhaseGenerationTerminalV1,
    intent_sha256: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                intent_sha256,
                _h("bank-generation-context"),
                terminal.generation_request_sha256,
                terminal.generation_lease_sha256,
                terminal.digest,
            }
        )
    )


class _ObservedRLock:
    """Test-only RLock that exposes when one named thread attempts entry."""

    def __init__(self, *, observed_thread_name: str, attempted: threading.Event):
        self._lock = threading.RLock()
        self._observed_thread_name = observed_thread_name
        self._attempted = attempted

    def __enter__(self):
        if threading.current_thread().name == self._observed_thread_name:
            self._attempted.set()
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        return self._lock.__exit__(exc_type, exc_value, traceback)


def _generated_action_kwargs(
    registry,
    *,
    source,
    source_factor,
    ingress,
    action_id: str,
    value,
    tag: str,
    branch: str = "mutate",
):
    intent_sha256 = _h(f"intent:{tag}")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch=branch,
        value=value,
        tag=tag,
    )
    return {
        "action_transaction_id": action_id,
        "action_intent_sha256": intent_sha256,
        "branch": branch,
        "source_artifact": source,
        "locator": "/phases/0/instruction",
        "dependency_factor": source_factor.factor if branch == "mutate" else None,
        "exact_additional_input_root_commitments": _generation_roots(
            terminal, intent_sha256
        ),
        "producer_epoch": "sft-action-host:round58",
        "attestation_sha256": _h(f"action-attestation:{tag}"),
        "generation_terminal": terminal,
        "generated_value": value,
        "ingress": ingress,
    }


def _namespace(
    *,
    goal: str = "sink",
    runtime: str = "shadow-runtime-v2",
    n_agents: int = 4,
) -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_count",
        objective="balanced",
        information_goal=goal,
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=n_agents,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version=runtime,
        binder_version=PHASE_FACTOR_BINDER_VERSION,
        compiler_version="1",
    )


def _program(
    *,
    instruction: str | None = "collect",
    pattern: str = "tree",
    n_agents: int = 4,
) -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": [
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": pattern,
                    "instruction": instruction,
                }
            ],
        }
    )


def _registry(
    *,
    key: bytes = b"registry-test-key" * 2,
    n_agents: int = 4,
    capacity: RegistryCapacity | None = None,
    branch_receipt_verifier=lambda _receipt: True,
):
    manifest = SourceManifest(
        manifest_sha256=_h("train-manifest"),
        split="TRAIN_UPDATE",
        source_catalog_sha256=_h("catalog"),
        policy_sha256=_h("policy"),
        producer_version="test-host-v1",
    )
    registry = PhaseArtifactRegistry(
        registry_key=key,
        manifests=(manifest,),
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=branch_receipt_verifier,
        capacity=capacity,
    )
    namespace = _namespace(n_agents=n_agents)
    profile = registry.register_runtime_profile(
        namespace=namespace,
        limits=PhaseProgramLimits(),
    )
    ingress = registry.issue_ingress(manifest.manifest_sha256)
    return registry, manifest, namespace, profile, ingress


def _branch_receipt(
    registry,
    *,
    branch: str,
    source_artifact,
    locator: str,
    tag: str,
    retrieved_target_factor=None,
    mutation_parent_factor=None,
):
    return registry.register_branch_receipt(
        branch=branch,
        source_artifact=source_artifact,
        locator=locator,
        retrieved_target_factor=retrieved_target_factor,
        mutation_parent_factor=mutation_parent_factor,
        additional_input_root_commitments=(_h(f"input-root:{tag}"),),
        producer_epoch="branch-host:test-v1",
        attestation_sha256=_h(f"branch-attestation:{tag}"),
    )


def _mutate_instruction(registry, profile, ingress, *, target: str = "dedupe"):
    source = registry.ingest_program(
        _program(),
        runtime_profile=profile,
        ingress=ingress,
    )
    extracted = registry.extract_factor(source, locator="/phases/0/instruction")
    branch_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag=f"mutate:{target}:{registry.to_state().sequence}",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    generated = registry.register_generated_value(
        target,
        operation_seal=seal,
        ingress=ingress,
    )
    proof = registry.materialize(
        operation_seal=seal,
        target_factor=generated.factor,
    )
    assert isinstance(proof, PhaseBindingProofHandle)
    return source, extracted, generated, proof


def _mutate_artifact_instruction(
    registry,
    source,
    ingress,
    *,
    target: str,
    tag: str,
):
    extracted = registry.extract_factor(
        source,
        locator="/phases/0/instruction",
    )
    receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag=tag,
    )
    seal = registry.seal_operation(branch_receipt=receipt)
    generated = registry.register_generated_value(
        target,
        operation_seal=seal,
        ingress=ingress,
    )
    proof = registry.materialize(
        operation_seal=seal,
        target_factor=generated.factor,
    )
    assert isinstance(proof, PhaseBindingProofHandle)
    return registry.resolve_proof(proof).target_artifact, generated.factor, proof


def test_host_materializer_mints_recomputable_one_factor_proof() -> None:
    registry, _manifest, namespace, profile, ingress = _registry()
    source, extracted, generated, proof = _mutate_instruction(
        registry, profile, ingress
    )

    verified = registry.verify_phase_materialization_proof(
        proof,
        expected_namespace=namespace,
        expected_source_artifact_id=source.handle_id,
    )
    proof_record = verified.proof

    assert proof_record.source_factor == extracted.factor
    assert proof_record.target_factor == generated.factor
    assert proof_record.source_artifact.handle_id == source.handle_id
    assert proof_record.target_artifact.handle_id != source.handle_id
    assert proof_record.source_execution_image_commitment != (
        proof_record.target_execution_image_commitment
    )
    assert proof_record.target_activation.mode == "trusted_trace_event"
    assert proof_record.target_activation.activation_kind == "phase_step_executed"
    assert "acceptable_token_ids" not in proof_record.target_activation.model_dump()
    assert not hasattr(registry, "verify_activation")


def test_a_to_b_to_c_reuses_b_content_identity() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    _source, _a, b, proof_ab = _mutate_instruction(
        registry, profile, ingress, target="dedupe"
    )
    record_ab = registry.resolve_proof(proof_ab)
    b_from_complete_artifact = registry.extract_factor(
        record_ab.target_artifact,
        locator="/phases/0/instruction",
    )
    assert b_from_complete_artifact.factor == b.factor

    receipt_bc = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=record_ab.target_artifact,
        locator="/phases/0/instruction",
        mutation_parent_factor=b.factor,
        tag="mutate:bc",
    )
    seal_bc = registry.seal_operation(branch_receipt=receipt_bc)
    c = registry.register_generated_value(
        "dedupe-and-check",
        operation_seal=seal_bc,
        ingress=ingress,
    )
    proof_bc = registry.materialize(
        operation_seal=seal_bc,
        target_factor=c.factor,
    )
    assert isinstance(proof_bc, PhaseBindingProofHandle)
    assert registry.resolve_proof(proof_bc).source_factor == b.factor


@pytest.mark.parametrize("missing_record", ["seal", "event", "proof"])
def test_downstream_proof_requires_complete_upstream_derivation_lineage(
    missing_record: str,
) -> None:
    registry, manifest, _namespace_value, profile, ingress = _registry()
    _source, _a, b, proof_ab = _mutate_instruction(
        registry, profile, ingress, target="lineage-b"
    )
    record_ab = registry.resolve_proof(proof_ab)
    receipt_bc = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=record_ab.target_artifact,
        locator="/phases/0/instruction",
        mutation_parent_factor=b.factor,
        tag=f"lineage-bc:{missing_record}",
    )
    seal_bc = registry.seal_operation(branch_receipt=receipt_bc)
    c = registry.register_generated_value(
        "lineage-c",
        operation_seal=seal_bc,
        ingress=ingress,
    )
    proof_bc = registry.materialize(
        operation_seal=seal_bc,
        target_factor=c.factor,
    )
    assert isinstance(proof_bc, PhaseBindingProofHandle)

    if missing_record == "seal":
        registry._seals.pop(record_ab.operation_seal.handle_id)
    elif missing_record == "event":
        registry._events.pop(record_ab.event.handle_id)
    else:
        registry._proofs.pop(proof_ab.handle_id)

    with pytest.raises(ValueError, match="derivation|closure|seal"):
        registry.verify_phase_materialization_proof(proof_bc)


def test_reuse_proof_requires_its_distinct_donor_artifact() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(pattern="tree"), runtime_profile=profile, ingress=ingress
    )
    donor = registry.ingest_program(
        _program(instruction="donor-value", pattern="star"),
        runtime_profile=profile,
        ingress=ingress,
    )
    donor_factor = registry.extract_factor(
        donor, locator="/phases/0/instruction"
    )
    receipt = _branch_receipt(
        registry,
        branch="reuse",
        source_artifact=source,
        locator="/phases/0/instruction",
        retrieved_target_factor=donor_factor.factor,
        tag="reuse:distinct-donor",
    )
    seal = registry.seal_operation(branch_receipt=receipt)
    proof = registry.materialize(operation_seal=seal)
    assert isinstance(proof, PhaseBindingProofHandle)
    target = registry.resolve_proof(proof).target_artifact
    assert target != donor
    target_factor = registry.extract_factor(
        target, locator="/phases/0/instruction"
    )
    downstream_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=target,
        locator="/phases/0/instruction",
        mutation_parent_factor=target_factor.factor,
        tag="mutate:downstream-of-reuse",
    )
    downstream_seal = registry.seal_operation(
        branch_receipt=downstream_receipt
    )
    downstream_value = registry.register_generated_value(
        "after-donor-value",
        operation_seal=downstream_seal,
        ingress=ingress,
    )
    downstream_proof = registry.materialize(
        operation_seal=downstream_seal,
        target_factor=downstream_value.factor,
    )
    assert isinstance(downstream_proof, PhaseBindingProofHandle)

    registry._artifacts.pop(donor.handle_id)

    with pytest.raises(ValueError, match="source artifact is missing"):
        registry.verify_phase_materialization_proof(proof)
    with pytest.raises(ValueError, match="source artifact is missing"):
        registry.verify_phase_materialization_proof(downstream_proof)


def test_reuse_requires_preexisting_sealed_target() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source, _a, b, _proof_ab = _mutate_instruction(registry, profile, ingress)

    branch_receipt = _branch_receipt(
        registry,
        branch="reuse",
        source_artifact=source,
        locator="/phases/0/instruction",
        retrieved_target_factor=b.factor,
        tag="reuse:b",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    proof = registry.materialize(operation_seal=seal)
    assert isinstance(proof, PhaseBindingProofHandle)
    assert registry.resolve_proof(proof).branch == "reuse"


def test_generated_duplicate_cannot_claim_mutate_credit() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source, extracted, _b, _proof = _mutate_instruction(registry, profile, ingress)
    branch_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag="mutate:duplicate",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    with pytest.raises(ValueError, match="already existed"):
        registry.register_generated_value(
            "dedupe",
            operation_seal=seal,
            ingress=ingress,
        )


def test_operational_noop_cannot_mint_binding_proof() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        n_agents=2
    )
    source = registry.ingest_program(
        _program(pattern="tree", n_agents=2),
        runtime_profile=profile,
        ingress=ingress,
    )
    star = registry.ingest_program(
        _program(pattern="star", n_agents=2),
        runtime_profile=profile,
        ingress=ingress,
    )
    star_factor = registry.extract_factor(star, locator="/phases/0/pattern")
    branch_receipt = _branch_receipt(
        registry,
        branch="reuse",
        source_artifact=source,
        locator="/phases/0/pattern",
        retrieved_target_factor=star_factor.factor,
        tag="reuse:pattern",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)

    result = registry.materialize(operation_seal=seal)

    assert isinstance(result, NoOpMaterialization)
    assert result.reason == "same_execution_image"


def test_send_mode_without_runner_behavior_delta_is_operational_noop() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    target_program = _program()
    target_phase = target_program.phases[0].model_copy(update={"send_mode": "full_state"})
    target_program = target_program.model_copy(update={"phases": [target_phase]})
    target_artifact = registry.ingest_program(
        target_program, runtime_profile=profile, ingress=ingress
    )
    target_factor = registry.extract_factor(
        target_artifact, locator="/phases/0/send_mode"
    )
    branch_receipt = _branch_receipt(
        registry,
        branch="reuse",
        source_artifact=source,
        locator="/phases/0/send_mode",
        retrieved_target_factor=target_factor.factor,
        tag="reuse:send-mode",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)

    result = registry.materialize(operation_seal=seal)

    assert isinstance(result, NoOpMaterialization)
    assert result.reason == "same_execution_image"


def test_submit_when_is_locked_until_the_runner_has_a_consumer() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    with pytest.raises(ValueError, match="structural|allowlisted"):
        registry.extract_factor(source, locator="/submit_when")


def test_branch_receipt_is_host_attested_and_single_use() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    extracted = registry.extract_factor(source, locator="/phases/0/instruction")
    receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag="single-use",
    )
    registry.seal_operation(branch_receipt=receipt)
    before = registry.to_state()

    with pytest.raises(ValueError, match="already been consumed"):
        registry.seal_operation(branch_receipt=receipt)

    assert registry.to_state() == before


def test_replayed_or_rejected_branch_attestation_writes_nothing() -> None:
    registry, manifest, namespace, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    extracted = registry.extract_factor(source, locator="/phases/0/instruction")
    first = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag="replayed-attestation",
    )
    assert first.handle_id
    before_replay = registry.to_state()
    with pytest.raises(ValueError, match="already been registered"):
        registry.register_branch_receipt(
            branch="mutate",
            source_artifact=source,
            locator="/phases/0/instruction",
            mutation_parent_factor=extracted.factor,
            additional_input_root_commitments=(_h("different-input-root"),),
            producer_epoch="branch-host:test-v1",
            attestation_sha256=_h("branch-attestation:replayed-attestation"),
        )
    assert registry.to_state() == before_replay

    rejecting = PhaseArtifactRegistry(
        registry_key=b"rejecting-branch-registry-key" * 2,
        manifests=(manifest,),
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: False,
    )
    rejecting_profile = rejecting.register_runtime_profile(
        namespace=namespace,
        limits=PhaseProgramLimits(),
    )
    rejecting_ingress = rejecting.issue_ingress(manifest.manifest_sha256)
    rejecting_source = rejecting.ingest_program(
        _program(),
        runtime_profile=rejecting_profile,
        ingress=rejecting_ingress,
    )
    before_reject = rejecting.to_state()
    with pytest.raises(ValueError, match="rejected the receipt"):
        rejecting.register_branch_receipt(
            branch="fresh",
            source_artifact=rejecting_source,
            locator="/phases/0/instruction",
            additional_input_root_commitments=(_h("safe-generation-context"),),
            producer_epoch="branch-host:rejecting",
            attestation_sha256=_h("rejected-attestation"),
        )
    assert rejecting.to_state() == before_reject


def test_reuse_action_transaction_is_atomic_idempotent_and_persistent(
    tmp_path,
) -> None:
    key = b"registry-action-transaction-key" * 2
    registry, manifest, _namespace_value, profile, ingress = _registry(key=key)
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    target_artifact = registry.ingest_program(
        _program(instruction="dedupe"),
        runtime_profile=profile,
        ingress=ingress,
    )
    target = registry.extract_factor(
        target_artifact, locator="/phases/0/instruction"
    )
    transaction_id = "action:reuse:one"
    intent_sha256 = _h("prepared-bank-reuse-intent")
    roots = tuple(sorted((intent_sha256, _h("bank-assignment-root"))))
    kwargs = {
        "action_transaction_id": transaction_id,
        "action_intent_sha256": intent_sha256,
        "source_artifact": source,
        "locator": "/phases/0/instruction",
        "retrieved_target_factor": target.factor,
        "exact_additional_input_root_commitments": roots,
        "producer_epoch": "sft-action-host:v1",
        "attestation_sha256": _h("sft-action-attestation:one"),
    }

    first = registry.materialize_reuse_idempotent(**kwargs)
    assert isinstance(first, PhaseBindingProofHandle)
    after_first = registry.to_state()
    replay = registry.materialize_reuse_idempotent(**kwargs)
    assert replay == first
    assert registry.to_state() == after_first

    with pytest.raises(ValueError, match="different intent"):
        registry.materialize_reuse_idempotent(
            **{
                **kwargs,
                "exact_additional_input_root_commitments": tuple(
                    sorted((intent_sha256, _h("different-bank-assignment-root")))
                ),
            }
        )
    assert registry.to_state() == after_first

    path = tmp_path / "action-registry.json"
    registry.save(path)
    loaded = PhaseArtifactRegistry.load(
        path,
        registry_key=key,
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: True,
    )
    loaded_before = loaded.to_state()
    assert loaded.materialize_reuse_idempotent(**kwargs) == first
    assert loaded.to_state() == loaded_before


def test_rejected_reuse_action_transaction_rolls_back_every_record() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        branch_receipt_verifier=lambda receipt: (
            receipt.action_transaction_id is None
        )
    )
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    target_artifact = registry.ingest_program(
        _program(instruction="dedupe"),
        runtime_profile=profile,
        ingress=ingress,
    )
    target = registry.extract_factor(
        target_artifact, locator="/phases/0/instruction"
    )
    intent_sha256 = _h("rejected-action-intent")
    before = registry.to_state()

    with pytest.raises(ValueError, match="rejected the receipt"):
        registry.materialize_reuse_idempotent(
            action_transaction_id="action:reuse:rejected",
            action_intent_sha256=intent_sha256,
            source_artifact=source,
            locator="/phases/0/instruction",
            retrieved_target_factor=target.factor,
            exact_additional_input_root_commitments=(intent_sha256,),
            producer_epoch="sft-action-host:v1",
            attestation_sha256=_h("sft-action-attestation:rejected"),
        )

    assert registry.to_state() == before


@pytest.mark.parametrize("branch", ["mutate", "fresh"])
def test_generated_action_transaction_is_atomic_idempotent_and_exact(
    branch: str,
    tmp_path,
) -> None:
    registry, manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = f"action:{branch}:one"
    intent_sha256 = _h(f"prepared-bank-{branch}-intent")
    generated_value = f"generated-{branch}-value"
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch=branch,
        value=generated_value,
        tag=f"{branch}-one",
    )
    kwargs = {
        "action_transaction_id": action_id,
        "action_intent_sha256": intent_sha256,
        "branch": branch,
        "source_artifact": source,
        "locator": "/phases/0/instruction",
        "dependency_factor": source_factor.factor if branch == "mutate" else None,
        "exact_additional_input_root_commitments": _generation_roots(
            terminal, intent_sha256
        ),
        "producer_epoch": "sft-action-host:v2",
        "attestation_sha256": _h(f"sft-action-attestation:{branch}"),
        "generation_terminal": terminal,
        "generated_value": generated_value,
        "ingress": ingress,
    }

    first = registry.materialize_action_idempotent(**kwargs)
    assert isinstance(first, PhaseBindingProofHandle)
    proof = registry.resolve_proof(first)
    assert proof.branch == branch
    assert proof.source_factor == source_factor.factor
    receipt = next(
        item
        for item in registry.to_state().branch_receipts
        if item.body.action_transaction_id == action_id
    )
    assert receipt.body.generation_terminal == terminal
    if branch == "mutate":
        assert receipt.body.mutation_parent_factor == source_factor.factor
        assert receipt.body.dependency_factor_ids == (source_factor.factor.handle_id,)
    else:
        assert receipt.body.mutation_parent_factor is None
        assert receipt.body.dependency_factor_ids == ()

    after_first = registry.to_state()
    assert registry.materialize_action_idempotent(**kwargs) == first
    assert registry.to_state() == after_first

    different_terminal = terminal.model_copy(
        update={"response_envelope_sha256": _h(f"different:{branch}")}
    )
    with pytest.raises(ValueError, match="different intent"):
        registry.materialize_action_idempotent(
            **{
                **kwargs,
                "generation_terminal": different_terminal,
                "exact_additional_input_root_commitments": _generation_roots(
                    different_terminal, intent_sha256
                ),
            }
        )
    assert registry.to_state() == after_first

    path = tmp_path / f"generated-action-{branch}.json"
    registry.save(path)
    loaded = PhaseArtifactRegistry.load(
        path,
        registry_key=b"registry-test-key" * 2,
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: True,
    )
    loaded_ingress = loaded.issue_ingress(
        registry.to_state().manifests[0].manifest_sha256
    )
    loaded_before = loaded.to_state()
    assert loaded.materialize_action_idempotent(
        **{**kwargs, "ingress": loaded_ingress}
    ) == first
    assert loaded.to_state() == loaded_before


def test_generated_mutate_rejects_wrong_parent_without_writes() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    registry.extract_factor(source, locator="/phases/0/instruction")
    donor = registry.ingest_program(
        _program(instruction="unrelated-parent"),
        runtime_profile=profile,
        ingress=ingress,
    )
    wrong_parent = registry.extract_factor(
        donor, locator="/phases/0/instruction"
    )
    action_id = "action:mutate:wrong-parent"
    intent_sha256 = _h("mutate-wrong-parent-intent")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value="wrong-parent-output",
        tag="wrong-parent",
    )
    before = registry.to_state()

    with pytest.raises(ValueError, match="exact source factor"):
        registry.materialize_action_idempotent(
            action_transaction_id=action_id,
            action_intent_sha256=intent_sha256,
            branch="mutate",
            source_artifact=source,
            locator="/phases/0/instruction",
            dependency_factor=wrong_parent.factor,
            exact_additional_input_root_commitments=_generation_roots(
                terminal, intent_sha256
            ),
            producer_epoch="sft-action-host:v2",
            attestation_sha256=_h("wrong-parent-action-attestation"),
            generation_terminal=terminal,
            generated_value="wrong-parent-output",
            ingress=ingress,
        )

    assert registry.to_state() == before


def test_generated_fresh_rejects_any_bank_dependency_without_writes() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = "action:fresh:dependency"
    intent_sha256 = _h("fresh-dependency-intent")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="fresh",
        value="fresh-output",
        tag="fresh-dependency",
    )
    before = registry.to_state()

    with pytest.raises(ValueError, match="empty dependency"):
        registry.materialize_action_idempotent(
            action_transaction_id=action_id,
            action_intent_sha256=intent_sha256,
            branch="fresh",
            source_artifact=source,
            locator="/phases/0/instruction",
            dependency_factor=source_factor.factor,
            exact_additional_input_root_commitments=_generation_roots(
                terminal, intent_sha256
            ),
            producer_epoch="sft-action-host:v2",
            attestation_sha256=_h("fresh-dependency-action-attestation"),
            generation_terminal=terminal,
            generated_value="fresh-output",
            ingress=ingress,
        )

    assert registry.to_state() == before


def test_generated_action_late_capacity_failure_rolls_back_complete_transaction() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        capacity=RegistryCapacity(max_proofs=1)
    )
    _source, _a, _b, first_proof = _mutate_instruction(
        registry, profile, ingress, target="first-proof-value"
    )
    source = registry.resolve_proof(first_proof).target_artifact
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = "action:mutate:late-rollback"
    intent_sha256 = _h("late-rollback-intent")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value="late-rollback-output",
        tag="late-rollback",
    )
    before = registry.to_state()

    with pytest.raises(RuntimeError, match="proof capacity"):
        registry.materialize_action_idempotent(
            action_transaction_id=action_id,
            action_intent_sha256=intent_sha256,
            branch="mutate",
            source_artifact=source,
            locator="/phases/0/instruction",
            dependency_factor=source_factor.factor,
            exact_additional_input_root_commitments=_generation_roots(
                terminal, intent_sha256
            ),
            producer_epoch="sft-action-host:v2",
            attestation_sha256=_h("late-rollback-action-attestation"),
            generation_terminal=terminal,
            generated_value="late-rollback-output",
            ingress=ingress,
        )

    assert registry.to_state() == before


def test_generated_same_value_is_a_durable_noncreditable_action_terminal() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = "action:mutate:same-value"
    intent_sha256 = _h("same-value-intent")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value="collect",
        tag="same-value",
    )
    kwargs = {
        "action_transaction_id": action_id,
        "action_intent_sha256": intent_sha256,
        "branch": "mutate",
        "source_artifact": source,
        "locator": "/phases/0/instruction",
        "dependency_factor": source_factor.factor,
        "exact_additional_input_root_commitments": _generation_roots(
            terminal, intent_sha256
        ),
        "producer_epoch": "sft-action-host:v2",
        "attestation_sha256": _h("same-value-action-attestation"),
        "generation_terminal": terminal,
        "generated_value": "collect",
        "ingress": ingress,
    }
    before = registry.to_state()
    result = registry.materialize_action_idempotent(**kwargs)

    assert isinstance(result, NoOpMaterialization)
    assert result.reason == "same_value"
    after = registry.to_state()
    event = registry.resolve_materialization_event(result.event)
    seal = next(item for item in after.seals if item.handle == event.operation_seal)
    receipt = next(
        item for item in after.branch_receipts
        if item.handle == seal.branch_receipt
    )
    target_attestation = next(
        item for item in after.attestations
        if item.handle == event.target_attestation
    )
    assert event.status == "same_value_noop"
    assert event.reason_code == "same_value"
    assert event.target_artifact is None
    assert event.target_factor == source_factor.factor
    assert target_attestation.operation_seal_id == seal.handle.handle_id
    assert target_attestation.source_artifact_id is None
    assert target_attestation.handle != source_factor.attestation
    assert receipt.body.generation_terminal == terminal
    assert receipt.body.mutation_parent_factor == source_factor.factor
    assert receipt.body.dependency_factor_ids == (source_factor.factor.handle_id,)
    assert not after.proofs
    assert len(after.values) == len(before.values)
    assert len(after.factors) == len(before.factors)
    terminal_digest = phase_materialization_event_sha256_v1(event)
    assert terminal_digest == phase_materialization_event_sha256_v1(
        registry.resolve_event(result.event)
    )
    assert terminal_digest != hashlib.sha256(
        json.dumps(event.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert registry.resolve_materialization_event(result.event) is not event

    replay_before = registry.to_state()
    assert registry.materialize_action_idempotent(**kwargs) == result
    assert registry.to_state() == replay_before


@pytest.mark.parametrize("branch", ["mutate", "fresh"])
def test_action_generated_preexisting_value_is_durable_duplicate_noop(
    branch: str,
) -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    existing_artifact = registry.ingest_program(
        _program(instruction="preexisting-target"),
        runtime_profile=profile,
        ingress=ingress,
    )
    existing_factor = registry.extract_factor(
        existing_artifact, locator="/phases/0/instruction"
    )
    kwargs = _generated_action_kwargs(
        registry,
        source=source,
        source_factor=source_factor,
        ingress=ingress,
        action_id=f"action:{branch}:preexisting",
        value="preexisting-target",
        tag=f"{branch}-preexisting",
        branch=branch,
    )
    before = registry.to_state()

    result = registry.materialize_action_idempotent(**kwargs)

    assert isinstance(result, NoOpMaterialization)
    assert result.reason == "duplicate_existing"
    after = registry.to_state()
    event = registry.resolve_materialization_event(result.event)
    seal = next(item for item in after.seals if item.handle == event.operation_seal)
    receipt = next(
        item for item in after.branch_receipts
        if item.handle == seal.branch_receipt
    )
    attestation = next(
        item for item in after.attestations
        if item.handle == event.target_attestation
    )
    assert event.status == "duplicate_existing"
    assert event.reason_code == "duplicate_existing"
    assert event.target_artifact is None
    assert event.target_factor == existing_factor.factor
    assert attestation.operation_seal_id == seal.handle.handle_id
    assert attestation.source_artifact_id is None
    assert receipt.body.generation_terminal == kwargs["generation_terminal"]
    assert receipt.body.dependency_factor_ids == (
        (source_factor.factor.handle_id,) if branch == "mutate" else ()
    )
    assert len(after.values) == len(before.values)
    assert len(after.factors) == len(before.factors)
    assert len(after.artifacts) == len(before.artifacts)
    assert len(after.proofs) == len(before.proofs)

    replay_before = registry.to_state()
    assert registry.materialize_action_idempotent(**kwargs) == result
    assert registry.to_state() == replay_before


def test_generated_duplicate_noop_is_concurrent_singleton_and_persistent(
    tmp_path,
) -> None:
    key = b"registry-v8-noop-replay-key" * 2
    registry, manifest, _namespace_value, profile, ingress = _registry(key=key)
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    donor = registry.ingest_program(
        _program(instruction="durable-preexisting"),
        runtime_profile=profile,
        ingress=ingress,
    )
    registry.extract_factor(donor, locator="/phases/0/instruction")
    kwargs = _generated_action_kwargs(
        registry,
        source=source,
        source_factor=source_factor,
        ingress=ingress,
        action_id="action:mutate:concurrent-duplicate",
        value="durable-preexisting",
        tag="concurrent-duplicate",
    )
    start = threading.Event()
    results = {}
    errors = {}

    def materialize(index: int) -> None:
        start.wait(timeout=5)
        try:
            results[index] = registry.materialize_action_idempotent(**kwargs)
        except Exception as exc:
            errors[index] = exc

    threads = [
        threading.Thread(target=materialize, args=(index,))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == {}
    assert results[0] == results[1]
    terminal = results[0]
    assert isinstance(terminal, NoOpMaterialization)
    assert terminal.reason == "duplicate_existing"
    state = registry.to_state()
    receipts = [
        item
        for item in state.branch_receipts
        if item.body.action_transaction_id
        == "action:mutate:concurrent-duplicate"
    ]
    assert len(receipts) == 1
    seals = [item for item in state.seals if item.branch_receipt == receipts[0].handle]
    assert len(seals) == 1
    events = [item for item in state.events if item.operation_seal == seals[0].handle]
    assert len(events) == 1
    assert events[0].handle == terminal.event
    assert events[0].status == "duplicate_existing"
    assert not [item for item in state.proofs if item.event == terminal.event]

    path = tmp_path / "durable-generated-noop.json"
    registry.save(path)
    loaded = PhaseArtifactRegistry.load(
        path,
        registry_key=key,
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: True,
    )
    loaded_ingress = loaded.issue_ingress(manifest.manifest_sha256)
    loaded_before = loaded.to_state()
    assert loaded.materialize_action_idempotent(
        **{**kwargs, "ingress": loaded_ingress}
    ) == terminal
    assert loaded.to_state() == loaded_before
    assert loaded.resolve_materialization_event(terminal.event).status == (
        "duplicate_existing"
    )


def test_action_generated_fresh_same_value_is_durable_same_value_noop() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    kwargs = _generated_action_kwargs(
        registry,
        source=source,
        source_factor=source_factor,
        ingress=ingress,
        action_id="action:fresh:same-value",
        value="collect",
        tag="fresh-same-value",
        branch="fresh",
    )

    result = registry.materialize_action_idempotent(**kwargs)

    assert isinstance(result, NoOpMaterialization)
    assert result.reason == "same_value"
    event = registry.resolve_materialization_event(result.event)
    state = registry.to_state()
    seal = next(item for item in state.seals if item.handle == event.operation_seal)
    receipt = next(
        item for item in state.branch_receipts if item.handle == seal.branch_receipt
    )
    assert event.status == "same_value_noop"
    assert event.target_factor == source_factor.factor
    assert receipt.body.dependency_factor_ids == ()
    assert receipt.body.mutation_parent_factor is None
    assert not state.proofs


def test_unified_reuse_action_preserves_idempotent_operational_noop() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry(n_agents=2)
    source = registry.ingest_program(
        _program(pattern="tree", n_agents=2),
        runtime_profile=profile,
        ingress=ingress,
    )
    target_artifact = registry.ingest_program(
        _program(pattern="star", n_agents=2),
        runtime_profile=profile,
        ingress=ingress,
    )
    target = registry.extract_factor(target_artifact, locator="/phases/0/pattern")
    action_id = "action:reuse:operational-noop"
    intent_sha256 = _h("reuse-operational-noop-intent")
    roots = tuple(sorted((intent_sha256, _h("noop-assignment-root"))))
    kwargs = {
        "action_transaction_id": action_id,
        "action_intent_sha256": intent_sha256,
        "branch": "reuse",
        "source_artifact": source,
        "locator": "/phases/0/pattern",
        "dependency_factor": target.factor,
        "exact_additional_input_root_commitments": roots,
        "producer_epoch": "sft-action-host:v2",
        "attestation_sha256": _h("reuse-operational-noop-attestation"),
    }

    result = registry.materialize_action_idempotent(**kwargs)
    assert isinstance(result, NoOpMaterialization)
    assert result.reason == "same_execution_image"
    after = registry.to_state()
    assert registry.materialize_action_idempotent(**kwargs) == result
    assert registry.to_state() == after


@pytest.mark.parametrize(
    "locator",
    [
        "/format",
        "/information_goal",
        "/phases",
        "/phases/0/kind",
        "/phases/0/unknown",
    ],
)
def test_structural_and_unknown_fields_remain_locked_atomic(locator: str) -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    artifact = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    with pytest.raises(ValueError, match="structural|allowlisted"):
        registry.extract_factor(artifact, locator=locator)


def test_typed_slot_rejects_bool_as_int_and_cross_enum_value() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    hub = registry.extract_factor(source, locator="/phases/0/hub")
    branch_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/hub",
        mutation_parent_factor=hub.factor,
        tag="mutate:hub",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    with pytest.raises(ValueError, match="scalar type"):
        registry.register_generated_value(
            True, operation_seal=seal, ingress=ingress
        )


def test_round_trip_rejects_model_copy_program_and_limits_bypass() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    invalid_phase = _program().phases[0].model_copy(update={"pattern": "oracle"})
    invalid_program = _program().model_copy(update={"phases": [invalid_phase]})
    with pytest.raises(ValidationError):
        registry.ingest_program(
            invalid_program, runtime_profile=profile, ingress=ingress
        )

    invalid_limits = PhaseProgramLimits().model_copy(
        update={"max_receiver_fan_in": 0}
    )
    with pytest.raises(ValidationError):
        registry.register_runtime_profile(
            namespace=_namespace(), limits=invalid_limits
        )


def test_untrusted_manifest_and_cross_registry_capability_fail_closed() -> None:
    registry, manifest, _namespace_value, profile, ingress = _registry()
    other, _manifest2, _namespace2, _profile2, other_ingress = _registry(
        key=b"another-registry-key" * 2
    )
    with pytest.raises(ValueError, match="not owned"):
        registry.ingest_program(
            _program(), runtime_profile=profile, ingress=other_ingress
        )
    with pytest.raises(ValueError, match="not registered"):
        other.resolve_artifact(
            registry.ingest_program(
                _program(), runtime_profile=profile, ingress=ingress
            )
        )
    assert manifest.split == "TRAIN_UPDATE"


def test_test_split_has_no_registry_schema_value() -> None:
    with pytest.raises(ValidationError):
        SourceManifest(
            manifest_sha256=_h("test"),
            split="TEST",  # type: ignore[arg-type]
            source_catalog_sha256=_h("catalog"),
            policy_sha256=_h("policy"),
            producer_version="bad",
        )


def test_generation_terminal_rejects_budget_usage_and_test_private_fields() -> None:
    action_id = "action:mutate:terminal-validation"
    intent_sha256 = _h("terminal-validation-intent")
    valid = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value="valid-output",
        tag="terminal-validation",
    )

    with pytest.raises(ValidationError, match="budget commitment"):
        PhaseGenerationTerminalV1.model_validate(
            {
                **valid.model_dump(mode="python"),
                "budget_sha256": _h("forged-budget"),
            }
        )
    with pytest.raises(ValidationError, match="exactly one model call"):
        PhaseGenerationTerminalV1.model_validate(
            {
                **valid.model_dump(mode="python"),
                "usage": {**_usage().model_dump(), "model_calls": 0},
            }
        )
    over_budget = ExecutionUsage(
        **{**_usage().model_dump(), "output_tokens": valid.budget.max_output_tokens + 1}
    )
    with pytest.raises(ValidationError, match="exceeds its sealed budget"):
        PhaseGenerationTerminalV1.model_validate(
            {**valid.model_dump(mode="python"), "usage": over_budget}
        )
    with pytest.raises(ValidationError, match="TRAIN_UPDATE|literal"):
        PhaseGenerationTerminalV1.model_validate(
            {**valid.model_dump(mode="python"), "split": "TEST"}
        )
    for forbidden, marker in (
        ("expected_output", "secret answer"),
        ("private_prompt", "private instructions"),
        ("ground_truth", "gold"),
        ("test_case", "held-out input"),
    ):
        with pytest.raises(ValidationError, match="extra"):
            PhaseGenerationTerminalV1.model_validate(
                {**valid.model_dump(mode="python"), forbidden: marker}
            )


def test_generated_action_revalidates_terminal_and_scalar_before_writing() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = "action:mutate:terminal-tamper"
    intent_sha256 = _h("terminal-tamper-intent")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value="expected-generated-output",
        tag="terminal-tamper",
    )
    before = registry.to_state()

    bypassed = terminal.model_copy(update={"budget_sha256": _h("wrong-budget")})
    with pytest.raises(ValidationError, match="budget commitment"):
        registry.materialize_action_idempotent(
            action_transaction_id=action_id,
            action_intent_sha256=intent_sha256,
            branch="mutate",
            source_artifact=source,
            locator="/phases/0/instruction",
            dependency_factor=source_factor.factor,
            exact_additional_input_root_commitments=_generation_roots(
                bypassed, intent_sha256
            ),
            producer_epoch="sft-action-host:v2",
            attestation_sha256=_h("terminal-tamper-action-attestation"),
            generation_terminal=bypassed,
            generated_value="expected-generated-output",
            ingress=ingress,
        )
    assert registry.to_state() == before

    with pytest.raises(ValueError, match="scalar commitment"):
        registry.materialize_action_idempotent(
            action_transaction_id=action_id,
            action_intent_sha256=intent_sha256,
            branch="mutate",
            source_artifact=source,
            locator="/phases/0/instruction",
            dependency_factor=source_factor.factor,
            exact_additional_input_root_commitments=_generation_roots(
                terminal, intent_sha256
            ),
            producer_epoch="sft-action-host:v2",
            attestation_sha256=_h("terminal-tamper-action-attestation"),
            generation_terminal=terminal,
            generated_value="different-generated-output",
            ingress=ingress,
        )
    assert registry.to_state() == before


def test_low_entropy_value_uses_keyed_commitment_not_naked_hash() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    _source, _a, generated, _proof = _mutate_instruction(
        registry, profile, ingress, target="42"
    )
    factor = registry.resolve_factor(generated.factor)
    state_dump = registry.to_state().model_dump(mode="json")
    naked = hashlib.sha256(json.dumps("42").encode("utf-8")).hexdigest()

    def scalar_strings(value):
        if isinstance(value, dict):
            return [item for child in value.values() for item in scalar_strings(child)]
        if isinstance(value, list):
            return [item for child in value for item in scalar_strings(child)]
        return [value] if isinstance(value, str) else []

    assert factor.factor_content_commitment != naked
    # Raw scalar is confined to the host registry; scientific FactorBank-facing
    # handles/commitments do not expose it or its dictionary-attackable SHA.
    assert "42" not in scalar_strings(factor.model_dump(mode="json"))
    assert naked not in json.dumps(state_dump)


def test_persistence_is_keyed_and_tamper_evident(tmp_path) -> None:
    key = b"registry-test-key" * 2
    registry, manifest, namespace, profile, ingress = _registry(key=key)
    _mutate_instruction(registry, profile, ingress)
    path = tmp_path / "phase-registry.json"
    registry.save(path)

    loaded = PhaseArtifactRegistry.load(
        path,
        registry_key=key,
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: True,
    )
    assert loaded.scientific_state_sha256 == registry.scientific_state_sha256
    with pytest.raises(ValueError, match="state MAC"):
        PhaseArtifactRegistry.load(
            path,
            registry_key=b"wrong-registry-key" * 2,
            manifest_verifier=lambda candidate: candidate == manifest,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["profiles"][0]["namespace"]["information_goal"] = "all_agents"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="state MAC"):
        PhaseArtifactRegistry.load(
            path,
            registry_key=key,
            manifest_verifier=lambda candidate: candidate == manifest,
        )


def test_generated_terminal_record_tamper_fails_even_with_recomputed_state_mac(
    tmp_path,
) -> None:
    key = b"registry-generated-tamper-key" * 2
    registry, manifest, _namespace_value, profile, ingress = _registry(key=key)
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = "action:mutate:persisted-terminal-tamper"
    intent_sha256 = _h("persisted-terminal-tamper-intent")
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value="persisted-generated-output",
        tag="persisted-terminal-tamper",
    )
    registry.materialize_action_idempotent(
        action_transaction_id=action_id,
        action_intent_sha256=intent_sha256,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        dependency_factor=source_factor.factor,
        exact_additional_input_root_commitments=_generation_roots(
            terminal, intent_sha256
        ),
        producer_epoch="sft-action-host:v2",
        attestation_sha256=_h("persisted-terminal-action-attestation"),
        generation_terminal=terminal,
        generated_value="persisted-generated-output",
        ingress=ingress,
    )
    path = tmp_path / "generated-terminal-tamper.json"
    registry.save(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["branch_receipts"][0]["body"]["generation_terminal"][
        "response_envelope_sha256"
    ] = _h("tampered-envelope")
    canonical_state = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_hmac_sha256"] = hmac.new(
        key,
        b"registry-state\0" + canonical_state,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="terminal commitments|record MAC|provenance closure",
    ):
        PhaseArtifactRegistry.load(
            path,
            registry_key=key,
            manifest_verifier=lambda candidate: candidate == manifest,
            branch_receipt_verifier=lambda _receipt: True,
        )


def test_v8_loader_explicitly_rejects_v7_state_without_migration(tmp_path) -> None:
    key = b"registry-v7-rejection-key" * 2
    registry, manifest, _namespace_value, _profile, _ingress = _registry(key=key)
    path = tmp_path / "claimed-v7-registry.json"
    registry.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["schema_version"] = "phase-artifact-registry-v7"
    canonical_state = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_hmac_sha256"] = hmac.new(
        key,
        b"registry-state\0" + canonical_state,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        LegacyPhaseArtifactRegistryRejected,
        match="legacy.*explicit migration",
    ):
        PhaseArtifactRegistry.load(
            path,
            registry_key=key,
            manifest_verifier=lambda candidate: candidate == manifest,
            branch_receipt_verifier=lambda _receipt: True,
        )


def test_capacity_is_finite_and_fail_closed() -> None:
    capacity = RegistryCapacity(max_artifacts=1)
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        capacity=capacity
    )
    registry.ingest_program(_program(), runtime_profile=profile, ingress=ingress)
    with pytest.raises(RuntimeError, match="capacity"):
        registry.ingest_program(
            _program(instruction="different"),
            runtime_profile=profile,
            ingress=ingress,
        )


@pytest.mark.parametrize("branch", ["mutate", "fresh"])
def test_lineage_depth_max_is_valid_and_max_plus_one_rejects_at_branch_admission(
    branch: str,
) -> None:
    capacity = RegistryCapacity(max_lineage_depth=2)
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        capacity=capacity
    )
    current = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    current, _factor_b, _proof_b = _mutate_artifact_instruction(
        registry,
        current,
        ingress,
        target=f"depth-one-{branch}",
        tag=f"depth-one:{branch}",
    )
    current, factor_at_max, proof_at_max = _mutate_artifact_instruction(
        registry,
        current,
        ingress,
        target=f"depth-two-{branch}",
        tag=f"depth-two:{branch}",
    )

    # A child at exactly max_lineage_depth is legal and fully verifiable.
    assert registry.resolve_proof(proof_at_max).target_artifact == current
    artifacts = {
        item.handle.handle_id: item for item in registry.to_state().artifacts
    }
    cursor = artifacts[current.handle_id]
    depth = 0
    while cursor.parent_artifact_id is not None:
        depth += 1
        cursor = artifacts[cursor.parent_artifact_id]
    assert depth == capacity.max_lineage_depth

    before = registry.to_state()
    before_bytes = before.model_dump_json()
    kwargs = (
        {"mutation_parent_factor": factor_at_max}
        if branch == "mutate"
        else {}
    )
    for attempt in range(3):
        # register_branch_receipt is the early rejection API.  In particular,
        # its implicit extract_factor has not yet created a value,
        # attestation, factor, receipt, or seal.
        with pytest.raises(ValueError, match="lineage depth preflight"):
            _branch_receipt(
                registry,
                branch=branch,
                source_artifact=current,
                locator="/phases/0/instruction",
                tag=f"over-cap:{branch}:{attempt}",
                **kwargs,
            )
        assert registry.to_state() == before
        assert registry.to_state().model_dump_json() == before_bytes


def test_lineage_cap_reuse_allows_existing_artifact_but_rejects_novel_child() -> None:
    capacity = RegistryCapacity(max_lineage_depth=2)
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        capacity=capacity
    )
    existing = registry.ingest_program(
        _program(instruction="existing-reuse-target"),
        runtime_profile=profile,
        ingress=ingress,
    )
    existing_factor = registry.extract_factor(
        existing,
        locator="/phases/0/instruction",
    )
    novel_donor = registry.ingest_program(
        _program(instruction="novel-reuse-target", pattern="star"),
        runtime_profile=profile,
        ingress=ingress,
    )
    novel_factor = registry.extract_factor(
        novel_donor,
        locator="/phases/0/instruction",
    )
    current = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    current, _factor_b, _proof_b = _mutate_artifact_instruction(
        registry,
        current,
        ingress,
        target="reuse-depth-one",
        tag="reuse-depth-one",
    )
    current, _factor_c, _proof_c = _mutate_artifact_instruction(
        registry,
        current,
        ingress,
        target="reuse-depth-two",
        tag="reuse-depth-two",
    )

    artifact_count = len(registry.to_state().artifacts)
    receipt = _branch_receipt(
        registry,
        branch="reuse",
        source_artifact=current,
        locator="/phases/0/instruction",
        retrieved_target_factor=existing_factor.factor,
        tag="at-cap-existing-reuse",
    )
    seal = registry.seal_operation(branch_receipt=receipt)
    proof = registry.materialize(operation_seal=seal)
    assert isinstance(proof, PhaseBindingProofHandle)
    assert registry.resolve_proof(proof).target_artifact == existing
    assert len(registry.to_state().artifacts) == artifact_count

    before_novel = registry.to_state()
    before_novel_bytes = before_novel.model_dump_json()
    with pytest.raises(ValueError, match="over-cap artifact"):
        _branch_receipt(
            registry,
            branch="reuse",
            source_artifact=current,
            locator="/phases/0/instruction",
            retrieved_target_factor=novel_factor.factor,
            tag="at-cap-novel-reuse",
        )
    assert registry.to_state() == before_novel
    assert registry.to_state().model_dump_json() == before_novel_bytes


def test_generated_attestation_capacity_failure_is_byte_atomic() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        capacity=RegistryCapacity(max_attestations=1)
    )
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    extracted = registry.extract_factor(source, locator="/phases/0/instruction")
    branch_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag="mutate:atomic-attestation",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    before = registry.to_state()

    with pytest.raises(RuntimeError, match="attestation capacity"):
        registry.register_generated_value(
            "new-value", operation_seal=seal, ingress=ingress
        )

    assert registry.to_state() == before


def test_materialize_proof_capacity_failure_is_byte_atomic() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry(
        capacity=RegistryCapacity(max_proofs=1)
    )
    _source, _a, _b, first_proof = _mutate_instruction(
        registry, profile, ingress, target="b"
    )
    first = registry.resolve_proof(first_proof)
    source_factor = registry.extract_factor(
        first.target_artifact, locator="/phases/0/instruction"
    )
    branch_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=first.target_artifact,
        locator="/phases/0/instruction",
        mutation_parent_factor=source_factor.factor,
        tag="mutate:atomic-proof",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    target = registry.register_generated_value(
        "c", operation_seal=seal, ingress=ingress
    )
    before = registry.to_state()

    with pytest.raises(RuntimeError, match="proof capacity"):
        registry.materialize(operation_seal=seal, target_factor=target.factor)

    assert registry.to_state() == before


def test_noncanonical_pointer_fails_before_any_registry_write() -> None:
    registry, _manifest, _namespace_value, profile, ingress = _registry()
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    before = registry.to_state()

    with pytest.raises(ValueError, match="canonical"):
        registry.extract_factor(source, locator="/phases/00/instruction")

    assert registry.to_state() == before


def test_duplicate_persisted_record_ids_fail_before_dict_collapse() -> None:
    registry, manifest, _namespace_value, profile, ingress = _registry()
    artifact = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    assert artifact.handle_id
    state = registry.to_state()
    duplicate = PhaseArtifactRegistryState.model_validate(
        {
            **state.model_dump(mode="python"),
            "artifacts": (*state.artifacts, state.artifacts[0]),
        }
    )

    with pytest.raises(ValueError, match="duplicate persisted.*artifact"):
        PhaseArtifactRegistry(
            registry_key=b"registry-test-key" * 2,
            state=duplicate,
            manifest_verifier=lambda candidate: candidate == manifest,
        )


def test_state_export_has_no_nested_alias_and_detached_clone_is_rejected() -> None:
    registry, manifest, _namespace_value, profile, ingress = _registry()
    artifact = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    exported = registry.to_state()
    exported.artifacts[0].program.phases.clear()

    assert len(registry.resolve_artifact(artifact).program.phases) == 1
    with pytest.raises(ValueError, match="detached.*not authoritative"):
        PhaseArtifactRegistry(
            registry_key=b"registry-test-key" * 2,
            state=registry.to_state(),
            manifest_verifier=lambda candidate: candidate == manifest,
        )


def test_loaded_registry_materialization_returns_only_after_file_cas(tmp_path) -> None:
    key = b"registry-test-key" * 2
    registry, manifest, _namespace_value, profile, ingress = _registry(key=key)
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    extracted = registry.extract_factor(source, locator="/phases/0/instruction")
    branch_receipt = _branch_receipt(
        registry,
        branch="mutate",
        source_artifact=source,
        locator="/phases/0/instruction",
        mutation_parent_factor=extracted.factor,
        tag="mutate:cas",
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    target = registry.register_generated_value(
        "cas-target", operation_seal=seal, ingress=ingress
    )
    path = tmp_path / "phase-registry-cas.json"
    registry.save(path)
    verifier = lambda candidate: candidate == manifest
    first = PhaseArtifactRegistry.load(
        path,
        registry_key=key,
        manifest_verifier=verifier,
        branch_receipt_verifier=lambda _receipt: True,
    )
    stale = PhaseArtifactRegistry.load(
        path,
        registry_key=key,
        manifest_verifier=verifier,
        branch_receipt_verifier=lambda _receipt: True,
    )
    stale_before = stale.to_state()

    assert isinstance(
        first.materialize(operation_seal=seal, target_factor=target.factor),
        PhaseBindingProofHandle,
    )
    with pytest.raises(RuntimeError, match="compare-and-swap"):
        stale.materialize(operation_seal=seal, target_factor=target.factor)

    assert stale.to_state() == stale_before


def test_same_instance_actions_are_linearized_before_outer_snapshot_rollback() -> None:
    action_a_waiting = threading.Event()
    release_action_a = threading.Event()
    action_b_at_lock = threading.Event()
    action_b_returned = threading.Event()

    def verifier(body):
        if body.action_transaction_id == "action:mutate:thread-a":
            action_a_waiting.set()
            if not release_action_a.wait(timeout=5):
                raise RuntimeError("timed out waiting to release action A")
            return False
        return True

    registry, _manifest, _namespace_value, profile, ingress = _registry(
        branch_receipt_verifier=verifier
    )
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    before = registry.to_state()
    kwargs_a = _generated_action_kwargs(
        registry,
        source=source,
        source_factor=source_factor,
        ingress=ingress,
        action_id="action:mutate:thread-a",
        value="thread-a-value",
        tag="thread-a",
    )
    kwargs_b = _generated_action_kwargs(
        registry,
        source=source,
        source_factor=source_factor,
        ingress=ingress,
        action_id="action:mutate:thread-b",
        value="thread-b-value",
        tag="thread-b",
    )
    registry._mutation_lock = _ObservedRLock(
        observed_thread_name="phase-action-b",
        attempted=action_b_at_lock,
    )
    results = {}
    errors = {}

    def run_a():
        try:
            results["a"] = registry.materialize_action_idempotent(**kwargs_a)
        except Exception as exc:
            errors["a"] = exc

    def run_b():
        try:
            results["b"] = registry.materialize_action_idempotent(**kwargs_b)
        except Exception as exc:
            errors["b"] = exc
        finally:
            action_b_returned.set()

    thread_a = threading.Thread(target=run_a, name="phase-action-a")
    thread_b = threading.Thread(target=run_b, name="phase-action-b")
    thread_a.start()
    try:
        assert action_a_waiting.wait(timeout=5)
        thread_b.start()
        assert action_b_at_lock.wait(timeout=5)
        # B has reached the registry lock, but cannot be misclassified as A's
        # nested transaction or return authority before A publishes/rolls back.
        assert not action_b_returned.wait(timeout=0.1)
    finally:
        release_action_a.set()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not thread_a.is_alive() and not thread_b.is_alive()
    assert isinstance(errors.get("a"), ValueError)
    assert "b" not in errors
    assert "a" not in results
    proof_b = results["b"]
    assert isinstance(proof_b, PhaseBindingProofHandle)
    assert registry.verify_phase_materialization_proof(proof_b).proof.handle == proof_b
    action_ids = {
        item.body.action_transaction_id
        for item in registry.to_state().branch_receipts
        if item.body.action_transaction_id is not None
    }
    assert action_ids == {"action:mutate:thread-b"}
    assert registry.to_state() != before


def test_public_verify_waits_for_failing_same_instance_transaction() -> None:
    mutation_waiting = threading.Event()
    release_mutation = threading.Event()
    reader_at_lock = threading.Event()
    reader_returned = threading.Event()

    def verifier(body):
        if body.action_transaction_id == "action:mutate:read-fence":
            mutation_waiting.set()
            if not release_mutation.wait(timeout=5):
                raise RuntimeError("timed out waiting to release mutation")
            return False
        return True

    registry, _manifest, _namespace_value, profile, ingress = _registry(
        branch_receipt_verifier=verifier
    )
    _source, _old, _new, stable_proof = _mutate_instruction(
        registry, profile, ingress, target="stable-proof-value"
    )
    stable = registry.resolve_proof(stable_proof)
    action_source = stable.target_artifact
    action_source_factor = registry.extract_factor(
        action_source, locator="/phases/0/instruction"
    )
    before = registry.to_state()
    kwargs = _generated_action_kwargs(
        registry,
        source=action_source,
        source_factor=action_source_factor,
        ingress=ingress,
        action_id="action:mutate:read-fence",
        value="rolled-back-value",
        tag="read-fence",
    )
    registry._mutation_lock = _ObservedRLock(
        observed_thread_name="phase-proof-reader",
        attempted=reader_at_lock,
    )
    results = {}
    errors = {}

    def mutate():
        try:
            registry.materialize_action_idempotent(**kwargs)
        except Exception as exc:
            errors["mutation"] = exc

    def read_proof():
        try:
            results["verified"] = registry.verify_phase_materialization_proof(
                stable_proof
            )
        except Exception as exc:
            errors["reader"] = exc
        finally:
            reader_returned.set()

    mutation_thread = threading.Thread(target=mutate, name="phase-failing-mutation")
    reader_thread = threading.Thread(target=read_proof, name="phase-proof-reader")
    mutation_thread.start()
    try:
        assert mutation_waiting.wait(timeout=5)
        reader_thread.start()
        assert reader_at_lock.wait(timeout=5)
        assert not reader_returned.wait(timeout=0.1)
    finally:
        release_mutation.set()
    mutation_thread.join(timeout=10)
    reader_thread.join(timeout=10)

    assert not mutation_thread.is_alive() and not reader_thread.is_alive()
    assert isinstance(errors.get("mutation"), ValueError)
    assert "reader" not in errors
    assert results["verified"].proof.handle == stable_proof
    assert registry.to_state() == before


def test_same_instance_save_waits_and_publishes_committed_mutation(tmp_path) -> None:
    mutation_waiting = threading.Event()
    release_mutation = threading.Event()
    save_at_lock = threading.Event()
    save_returned = threading.Event()

    def verifier(body):
        if body.action_transaction_id == "action:mutate:save-fence":
            mutation_waiting.set()
            if not release_mutation.wait(timeout=5):
                raise RuntimeError("timed out waiting to release mutation")
        return True

    key = b"registry-round58-save-key" * 2
    registry, manifest, _namespace_value, profile, ingress = _registry(
        key=key,
        branch_receipt_verifier=verifier,
    )
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    kwargs = _generated_action_kwargs(
        registry,
        source=source,
        source_factor=source_factor,
        ingress=ingress,
        action_id="action:mutate:save-fence",
        value="save-fence-value",
        tag="save-fence",
    )
    path = tmp_path / "same-instance-save.json"
    registry.save(path)
    registry._mutation_lock = _ObservedRLock(
        observed_thread_name="phase-save-thread",
        attempted=save_at_lock,
    )
    results = {}
    errors = {}

    def mutate():
        try:
            results["proof"] = registry.materialize_action_idempotent(**kwargs)
        except Exception as exc:
            errors["mutation"] = exc

    def save():
        try:
            registry.save(path)
        except Exception as exc:
            errors["save"] = exc
        finally:
            save_returned.set()

    mutation_thread = threading.Thread(target=mutate, name="phase-save-mutation")
    save_thread = threading.Thread(target=save, name="phase-save-thread")
    mutation_thread.start()
    try:
        assert mutation_waiting.wait(timeout=5)
        save_thread.start()
        assert save_at_lock.wait(timeout=5)
        assert not save_returned.wait(timeout=0.1)
    finally:
        release_mutation.set()
    mutation_thread.join(timeout=10)
    save_thread.join(timeout=10)

    assert not mutation_thread.is_alive() and not save_thread.is_alive()
    assert errors == {}
    proof = results["proof"]
    assert isinstance(proof, PhaseBindingProofHandle)
    loaded = PhaseArtifactRegistry.load(
        path,
        registry_key=key,
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: True,
    )
    assert loaded.resolve_proof(proof).handle == proof
    assert loaded.scientific_state_sha256 == registry.scientific_state_sha256


def test_load_recomputes_generated_terminal_scalar_from_exact_event_target(
    tmp_path,
    monkeypatch,
) -> None:
    key = b"registry-round58-scalar-load-key" * 2
    registry, manifest, _namespace_value, profile, ingress = _registry(key=key)
    source = registry.ingest_program(
        _program(), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(
        source, locator="/phases/0/instruction"
    )
    action_id = "action:mutate:scalar-load"
    intent_sha256 = _h("scalar-load-intent")
    claimed_value = "terminal-claimed-value"
    actual_value = "event-target-value"
    terminal = _generation_terminal(
        action_id=action_id,
        intent_sha256=intent_sha256,
        branch="mutate",
        value=claimed_value,
        tag="scalar-load",
    )
    kwargs = {
        "action_transaction_id": action_id,
        "action_intent_sha256": intent_sha256,
        "branch": "mutate",
        "source_artifact": source,
        "locator": "/phases/0/instruction",
        "dependency_factor": source_factor.factor,
        "exact_additional_input_root_commitments": _generation_roots(
            terminal, intent_sha256
        ),
        "producer_epoch": "sft-action-host:round58",
        "attestation_sha256": _h("scalar-load-action-attestation"),
        "generation_terminal": terminal,
        "generated_value": actual_value,
        "ingress": ingress,
    }
    path = tmp_path / "semantic-scalar-mismatch.json"

    # Construct an authenticated state that an older writer could accept if
    # its scalar join were faulty.  All record handles/MACs and the state HMAC
    # are produced by the registry itself; only the test-time join function is
    # held to the terminal's incorrect claim during write/publication.
    with monkeypatch.context() as patch:
        patch.setattr(
            phase_registry_module,
            "phase_generated_scalar_sha256",
            lambda _value: terminal.generated_scalar_sha256,
        )
        proof = registry.materialize_action_idempotent(**kwargs)
        assert isinstance(proof, PhaseBindingProofHandle)
        registry.save(path)

    with pytest.raises(ValueError, match="scalar commitment differs"):
        PhaseArtifactRegistry.load(
            path,
            registry_key=key,
            manifest_verifier=lambda candidate: candidate == manifest,
            branch_receipt_verifier=lambda _receipt: True,
        )
