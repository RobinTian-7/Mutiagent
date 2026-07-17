from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from exp_graph.mas.factor_bank import (
    CompositionRevision,
    DenseOutcome,
    ExecutionBudget,
    ExecutionNamespace,
    ExecutionUsage,
    FactorBank,
    FactorLocator,
    FactorRevision,
    FailureObservation,
    GateDecision,
    SlotBinding,
    make_receipt,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace(
    *,
    goal: str = "sink",
    payload: str = "phase_program_skill_v1",
    mode: str = "program_generate",
    worker_contract: str = "not_applicable",
) -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_count",
        objective="balanced",
        information_goal=goal,
        planner_mode=mode,
        payload_format=payload,
        worker_contract=worker_contract,
        n_agents=4,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="shadow-runtime-v1",
        binder_version="facts-phase-v1",
        compiler_version="1",
    )


def _factor(
    revision_id: str,
    *,
    logical_id: str,
    content: str,
    namespace: ExecutionNamespace,
    carrier: str = "phase_program",
    surface: str = "phase_field",
    path: str = "/phases/0/instruction",
    status: str = "proven_factorized",
    parent: str | None = None,
    branch: str = "mutate",
) -> FactorRevision:
    return FactorRevision(
        revision_id=revision_id,
        logical_factor_id=logical_id,
        namespace=namespace,
        carrier=carrier,
        locator=FactorLocator(
            surface=surface,
            path=path,
            locator_version="v1",
        ),
        binding_status=status,
        content_sha256=_h(content),
        parent_revision_id=parent,
        origin_branch=branch,
    )


def _composition(
    composition_id: str,
    *,
    namespace: ExecutionNamespace,
    instruction_factor: str,
    policy_factor: str,
    artifact: str,
    parent: str | None = None,
    branch: str = "mutate",
) -> CompositionRevision:
    return CompositionRevision(
        composition_id=composition_id,
        namespace=namespace,
        carrier="phase_program",
        artifact_revision_id=f"artifact:{composition_id}",
        artifact_sha256=_h(artifact),
        bindings=(
            SlotBinding(
                slot_id="phase0_instruction",
                factor_revision_id=instruction_factor,
            ),
            SlotBinding(slot_id="reasoning_policy", factor_revision_id=policy_factor),
        ),
        origin_branch=branch,
        parent_composition_id=parent,
    )


def _budget() -> ExecutionBudget:
    return ExecutionBudget(
        max_messages=16,
        max_model_calls=8,
        max_input_tokens=8_000,
        max_output_tokens=2_000,
        max_wall_time_ms=60_000,
        max_cost_microusd=50_000,
    )


def _usage() -> ExecutionUsage:
    return ExecutionUsage(
        messages=4,
        model_calls=2,
        input_tokens=1_000,
        output_tokens=200,
        wall_time_ms=2_000,
        cost_microusd=2_000,
    )


def _outcome(
    stage: float,
    *,
    V: float = 1.0,
    K: float = 1.0,
    U: float = 1.0,
    P: float = 1.0,
    S: float = 1.0,
    C: float = 10.0,
    D: float = 1.0,
) -> DenseOutcome:
    return DenseOutcome(V=V, K=K, U=U, P=P, S=S, stage_score=stage, C=C, D=D)


def _direct_bank() -> tuple[
    FactorBank,
    str,
    CompositionRevision,
    CompositionRevision,
]:
    namespace = _namespace()
    bank = FactorBank(
        gate_verifier=lambda _decision, _state: True,
        binding_verifier=lambda *_args: True,
        execution_receipt_verifier=lambda *_args: True,
    )
    old = _factor(
        "instruction:v1",
        logical_id="instruction",
        content="preserve",
        namespace=namespace,
        branch="migration",
    )
    new = _factor(
        "instruction:v2",
        logical_id="instruction",
        content="preserve-and-dedupe",
        namespace=namespace,
        parent=old.revision_id,
    )
    policy = _factor(
        "policy:v1",
        logical_id="policy",
        content="cite-sources",
        namespace=namespace,
        carrier="reasoning_policy",
        surface="reasoning_policy_field",
        path="/reasoning_policy/synthesis",
        branch="migration",
    )
    bank.add_factor(old)
    bank.add_factor(new)
    bank.add_factor(policy)
    source = _composition(
        "composition:v1",
        namespace=namespace,
        instruction_factor=old.revision_id,
        policy_factor=policy.revision_id,
        artifact="source-program",
        branch="migration",
    )
    target = _composition(
        "composition:v2",
        namespace=namespace,
        instruction_factor=new.revision_id,
        policy_factor=policy.revision_id,
        artifact="target-program",
        parent=source.composition_id,
    )
    bank.add_composition(source)
    bank.add_composition(target)
    transition = bank.register_transition(
        source_composition_id=source.composition_id,
        target_composition_id=target.composition_id,
        slot_id="phase0_instruction",
        binding_proof_id="proof:direct",
        binding_proof_sha256=_h("direct-binding-proof"),
        masked_background_sha256=_h("direct-masked-background"),
        origin_branch="mutate",
    )
    return bank, transition.transition_id, source, target


def _complete_positive_block(
    bank: FactorBank,
    transition_id: str,
    source: CompositionRevision,
    target: CompositionRevision,
):
    block = bank.seal_direct_block(
        transition_id,
        unit_commitment=_h("synthetic-unit"),
        arm_order="AB",
        budget=_budget(),
        randomized_common_origin_set=True,
    )
    source_receipt = make_receipt(
        block=block,
        composition=source,
        arm="source",
        root_id=_h("source-root"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.5),
    )
    target_receipt = make_receipt(
        block=block,
        composition=target,
        arm="target",
        root_id=_h("target-root"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.7, C=8.0),
    )
    return block, source_receipt, target_receipt


def _gate_decision(
    *,
    bank: FactorBank,
    composition_id: str,
    transition_id: str,
    accepted: bool,
) -> GateDecision:
    return GateDecision(
        decision_id="gate:one",
        composition_id=composition_id,
        transition_id=transition_id,
        accepted=accepted,
        incumbent_snapshot_sha256=_h("incumbent"),
        candidate_snapshot_sha256=bank.scientific_state_sha256,
        gate_config_sha256=_h("strict-dense-v2"),
        verification_receipt_sha256=_h("strict-dense-v2-receipt"),
    )


def test_positive_complete_block_is_the_only_factor_credit_owner() -> None:
    bank, transition_id, source, target = _direct_bank()
    bank.record_exposure("retrieved-unused")
    bank.record_exposure("fresh-insight-only")
    block, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )

    completed = bank.commit_complete_block(
        block.block_id,
        source_receipt,
        target_receipt,
    )

    assert completed is not None
    assert completed.delta.stage_score == pytest.approx(0.2)
    assert bank.transitions[transition_id].state == "candidate"
    assert len(bank.transitions[transition_id].evidence_blocks) == 1
    assert bank.compositions[target.composition_id].state == "probation"
    assert bank.factors["instruction:v2"].state == "probation"
    assert not hasattr(bank.factors["instruction:v2"], "evidence_blocks")
    assert bank.exposures == {
        "retrieved-unused": 1,
        "fresh-insight-only": 1,
    }


def test_whole_bank_gate_is_required_before_active_retrieval() -> None:
    bank, transition_id, source, target = _direct_bank()
    block, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )
    bank.commit_complete_block(block.block_id, source_receipt, target_receipt)

    assert bank.retrieve(source.namespace) == []
    bank.apply_gate(
        _gate_decision(
            bank=bank,
            composition_id=target.composition_id,
            transition_id=transition_id,
            accepted=True,
        )
    )

    assert [item.composition_id for item in bank.retrieve(source.namespace)] == [
        target.composition_id
    ]
    assert bank.transitions[transition_id].state == "active"
    assert bank.factors["instruction:v2"].state == "active"


def test_gate_rejection_archives_candidate_without_deploying_it() -> None:
    bank, transition_id, source, target = _direct_bank()
    block, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )
    bank.commit_complete_block(block.block_id, source_receipt, target_receipt)
    bank.apply_gate(
        _gate_decision(
            bank=bank,
            composition_id=target.composition_id,
            transition_id=transition_id,
            accepted=False,
        )
    )

    assert bank.retrieve(source.namespace) == []
    assert bank.compositions[target.composition_id].state == "archived"
    assert bank.transitions[transition_id].state == "refuted"


def test_loaded_hash_mismatch_quarantines_and_consumes_roots_without_credit() -> None:
    bank, transition_id, source, target = _direct_bank()
    block, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )
    target_receipt = target_receipt.model_copy(
        update={"loaded_artifact_sha256": _h("wrong-loaded-artifact")}
    )

    assert (
        bank.commit_complete_block(block.block_id, source_receipt, target_receipt)
        is None
    )
    assert bank.blocks[block.block_id].state == "quarantine"
    assert bank.blocks[block.block_id].disposition_reason == "loaded_hash_mismatch"
    assert bank.transitions[transition_id].evidence_blocks == ()
    assert bank.used_roots == {
        source_receipt.root_id: block.block_id,
        target_receipt.root_id: block.block_id,
    }


def test_duplicate_physical_roots_cannot_amplify_evidence() -> None:
    bank, transition_id, source, target = _direct_bank()
    first, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )
    bank.commit_complete_block(first.block_id, source_receipt, target_receipt)
    second = bank.seal_direct_block(
        transition_id,
        unit_commitment=_h("second-unit"),
        arm_order="BA",
        budget=_budget(),
    )
    second_source = make_receipt(
        block=second,
        composition=source,
        arm="source",
        root_id=source_receipt.root_id,
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.5),
    )
    second_target = make_receipt(
        block=second,
        composition=target,
        arm="target",
        root_id=_h("new-target-root"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.8),
    )

    assert bank.commit_complete_block(second.block_id, second_source, second_target) is None
    assert bank.blocks[second.block_id].disposition_reason == "reused_physical_root"
    assert len(bank.transitions[transition_id].evidence_blocks) == 1


def test_algorithm_failure_is_negative_but_infrastructure_is_incomplete() -> None:
    bank, transition_id, source, target = _direct_bank()
    block = bank.seal_direct_block(
        transition_id,
        unit_commitment=_h("algorithm-failure-unit"),
        arm_order="AB",
        budget=_budget(),
        randomized_common_origin_set=True,
    )
    source_receipt = make_receipt(
        block=block,
        composition=source,
        arm="source",
        root_id=_h("algorithm-source"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.5),
    )
    target_receipt = make_receipt(
        block=block,
        composition=target,
        arm="target",
        root_id=_h("algorithm-target"),
        usage=_usage(),
        execution_class="algorithm_failure",
        outcome=_outcome(0.0, V=0.0, K=0.0, U=0.0, P=0.0, S=0.0),
    )
    assert bank.commit_complete_block(block.block_id, source_receipt, target_receipt)
    assert bank.transitions[transition_id].state == "refuted"
    assert len(bank.transitions[transition_id].evidence_blocks) == 1

    bank2, transition2, source2, target2 = _direct_bank()
    block2 = bank2.seal_direct_block(
        transition2,
        unit_commitment=_h("infrastructure-unit"),
        arm_order="BA",
        budget=_budget(),
    )
    source2_receipt = make_receipt(
        block=block2,
        composition=source2,
        arm="source",
        root_id=_h("infra-source"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.5),
    )
    target2_receipt = make_receipt(
        block=block2,
        composition=target2,
        arm="target",
        root_id=_h("infra-target"),
        usage=_usage(),
        execution_class="infrastructure_failure",
        outcome=None,
    )
    assert (
        bank2.commit_complete_block(
            block2.block_id,
            source2_receipt,
            target2_receipt,
        )
        is None
    )
    assert bank2.blocks[block2.block_id].state == "incomplete"
    assert bank2.transitions[transition2].evidence_blocks == ()


def test_all_zero_quality_cannot_win_by_being_cheaper() -> None:
    bank, transition_id, source, target = _direct_bank()
    block = bank.seal_direct_block(
        transition_id,
        unit_commitment=_h("all-zero-unit"),
        arm_order="AB",
        budget=_budget(),
    )
    source_receipt = make_receipt(
        block=block,
        composition=source,
        arm="source",
        root_id=_h("zero-source"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.0, V=0.0, K=0.0, U=0.0, P=0.0, S=0.0, C=10.0),
    )
    target_receipt = make_receipt(
        block=block,
        composition=target,
        arm="target",
        root_id=_h("zero-target"),
        usage=_usage(),
        execution_class="completed",
        outcome=_outcome(0.0, V=0.0, K=0.0, U=0.0, P=0.0, S=0.0, C=1.0),
    )
    bank.commit_complete_block(block.block_id, source_receipt, target_receipt)

    assert bank.transitions[transition_id].state == "probed"
    assert bank.compositions[target.composition_id].state == "shadow"


def test_compound_change_and_locked_atomic_factor_fail_closed() -> None:
    bank, _transition_id, source, target = _direct_bank()
    namespace = source.namespace
    new_policy = _factor(
        "policy:v2",
        logical_id="policy",
        content="different-policy",
        namespace=namespace,
        carrier="reasoning_policy",
        surface="reasoning_policy_field",
        path="/reasoning_policy/synthesis",
        parent="policy:v1",
    )
    bank.add_factor(new_policy)
    compound = _composition(
        "composition:compound",
        namespace=namespace,
        instruction_factor="instruction:v2",
        policy_factor=new_policy.revision_id,
        artifact="compound-program",
        parent=source.composition_id,
    )
    bank.add_composition(compound)
    with pytest.raises(ValueError, match="exactly one slot"):
        bank.register_transition(
            source_composition_id=source.composition_id,
            target_composition_id=compound.composition_id,
            slot_id="phase0_instruction",
            binding_proof_id="proof:compound",
            binding_proof_sha256=_h("compound-binding-proof"),
            masked_background_sha256=_h("compound-masked-background"),
            origin_branch="mutate",
        )

    atomic = _factor(
        "atomic:v1",
        logical_id="atomic",
        content="whole-artifact",
        namespace=namespace,
        surface="atomic_artifact",
        path="/artifact",
        status="locked_atomic",
    )
    atomic2 = atomic.model_copy(
        update={
            "revision_id": "atomic:v2",
            "content_sha256": _h("whole-artifact-2"),
            "parent_revision_id": atomic.revision_id,
        }
    )
    bank.add_factor(atomic)
    bank.add_factor(atomic2)
    atomic_source = CompositionRevision(
        composition_id="atomic-composition:v1",
        namespace=namespace,
        carrier="phase_program",
        artifact_revision_id="atomic-artifact:v1",
        artifact_sha256=_h("atomic-1"),
        bindings=(SlotBinding(slot_id="atomic", factor_revision_id=atomic.revision_id),),
        origin_branch="migration",
    )
    atomic_target = CompositionRevision(
        composition_id="atomic-composition:v2",
        namespace=namespace,
        carrier="phase_program",
        artifact_revision_id="atomic-artifact:v2",
        artifact_sha256=_h("atomic-2"),
        bindings=(SlotBinding(slot_id="atomic", factor_revision_id=atomic2.revision_id),),
        origin_branch="mutate",
        parent_composition_id=atomic_source.composition_id,
    )
    bank.add_composition(atomic_source)
    bank.add_composition(atomic_target)
    with pytest.raises(ValueError, match="cannot mint factor credit"):
        bank.register_transition(
            source_composition_id=atomic_source.composition_id,
            target_composition_id=atomic_target.composition_id,
            slot_id="atomic",
            binding_proof_id="proof:atomic",
            binding_proof_sha256=_h("atomic-binding-proof"),
            masked_background_sha256=_h("atomic-masked-background"),
            origin_branch="mutate",
        )


def test_namespace_and_policy_identity_never_merge() -> None:
    bank, transition_id, source, target = _direct_bank()
    block, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )
    bank.commit_complete_block(block.block_id, source_receipt, target_receipt)
    bank.apply_gate(
        _gate_decision(
            bank=bank,
            composition_id=target.composition_id,
            transition_id=transition_id,
            accepted=True,
        )
    )

    other_goal = _namespace(goal="all_agents")
    assert bank.retrieve(other_goal) == []
    assert source.artifact_sha256 != target.artifact_sha256
    assert source.binding_map["reasoning_policy"] == target.binding_map["reasoning_policy"]


def test_all_required_carriers_persist_as_locked_atomic_revisions(tmp_path: Path) -> None:
    definitions = (
        ("named_topology", "named_topology_skill_v1", "topology_select", "not_applicable"),
        ("paper_transport", "paper_transport_skill_v1", "paper_protocol_runtime", "not_applicable"),
        ("graph", "graph_skill_v1", "graph_generate", "not_applicable"),
        ("phase_program", "phase_program_skill_v1", "program_generate", "not_applicable"),
        ("python_source", "python_skill_v1", "python_generate", "message_only_v2"),
    )
    bank = FactorBank()
    for index, (carrier, payload, mode, contract) in enumerate(definitions):
        namespace = _namespace(
            payload=payload,
            mode=mode,
            worker_contract=contract,
        )
        factor = _factor(
            f"atomic:{index}",
            logical_id=f"whole:{index}",
            content=f"artifact:{index}",
            namespace=namespace,
            carrier=carrier,
            surface="atomic_artifact",
            path="/artifact",
            status="locked_atomic",
            branch="migration",
        )
        bank.add_factor(factor)

    path = tmp_path / "pif_bank.json"
    bank.save(path)
    loaded = FactorBank.load(path)

    assert loaded.scientific_state_sha256 == bank.scientific_state_sha256
    assert {factor.carrier for factor in loaded.factors.values()} == {
        "named_topology",
        "paper_transport",
        "graph",
        "phase_program",
        "python_source",
    }


def test_read_only_snapshot_and_hash_detect_terminal_state_writes() -> None:
    bank, _transition_id, source, _target = _direct_bank()
    snapshot = bank.read_only_snapshot()
    before = snapshot.scientific_state_sha256

    assert not hasattr(snapshot, "commit_complete_block")
    assert snapshot.retrieve(source.namespace) == []
    bank.assert_scientific_state_unchanged(before)

    bank.record_exposure("post-test-write-canary")
    with pytest.raises(RuntimeError, match="scientific state changed"):
        bank.assert_scientific_state_unchanged(before)


def test_failure_information_is_typed_answer_free_and_hash_bound() -> None:
    bank, transition_id, _source, target = _direct_bank()
    failure = FailureObservation(
        failure_id="failure:one",
        failure_class="algorithm",
        stage="execution",
        failure_code="coverage_incomplete",
        composition_id=target.composition_id,
        transition_id=transition_id,
        artifact_sha256=target.artifact_sha256,
    )
    bank.record_failure(failure)
    assert bank.failures[failure.failure_id].failure_code == "coverage_incomplete"

    with pytest.raises(ValidationError, match="forbidden"):
        FailureObservation(
            failure_id="failure:oracle",
            failure_class="algorithm",
            stage="execution",
            failure_code="expected_output_leaked",
            composition_id=target.composition_id,
            transition_id=transition_id,
            artifact_sha256=target.artifact_sha256,
        )


def test_budget_violation_quarantines_without_evidence() -> None:
    bank, transition_id, source, target = _direct_bank()
    block, source_receipt, target_receipt = _complete_positive_block(
        bank, transition_id, source, target
    )
    target_receipt = target_receipt.model_copy(
        update={
            "usage": _usage().model_copy(update={"model_calls": block.budget.max_model_calls + 1})
        }
    )

    assert bank.commit_complete_block(block.block_id, source_receipt, target_receipt) is None
    assert bank.blocks[block.block_id].disposition_reason == "budget_violation"
    assert bank.transitions[transition_id].evidence_blocks == ()


def test_no_parent_mutation_is_infeasible_not_negative_branch_credit() -> None:
    assert FactorBank.choose_branch(1, {"fresh", "reuse"}) in {"fresh", "reuse"}
    assert FactorBank.choose_branch(1, {"fresh"}) == "fresh"
    with pytest.raises(ValueError, match="at least one"):
        FactorBank.choose_branch(1, set())


def test_invalid_mode_contract_and_extra_oracle_field_fail_schema() -> None:
    with pytest.raises(ValidationError, match="requires planner/runtime mode"):
        _namespace(payload="phase_program_skill_v1", mode="graph_generate")

    payload = _namespace().model_dump(mode="json")
    payload["expected_output"] = "secret"
    with pytest.raises(ValidationError):
        ExecutionNamespace.model_validate(payload)
