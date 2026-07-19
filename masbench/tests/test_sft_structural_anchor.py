from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    phase_mutable_factor_paths_v3,
)
from exp_graph.mas.phase_program import PHASE_PROGRAM_COMPILER_VERSION
from masbench.sft_pilot.components import phase_factor_capabilities
from masbench.sft_pilot.structural_anchor import (
    STRUCTURAL_ANCHOR_LOCATOR,
    StructuralAnchorPlanV1,
    build_structural_anchor_v1,
    load_structural_anchor_v1,
)


SOURCE_KEY = hashlib.sha256(b"structural-anchor-source-authority").digest()
PHASE_KEY = hashlib.sha256(b"structural-anchor-phase-registry").digest()
FACTOR_KEY = hashlib.sha256(b"structural-anchor-factor-bank").digest()


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace(goal: str = "sink", *, n_agents: int = 4) -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_anchor",
        objective="balanced",
        information_goal=goal,
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=n_agents,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="anchor-runtime-v1",
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _plan(goal: str = "sink", *, n_agents: int = 4) -> StructuralAnchorPlanV1:
    return StructuralAnchorPlanV1(
        namespace=_namespace(goal, n_agents=n_agents),
        source_catalog_sha256=_h(f"anchor-catalog:{goal}"),
        source_policy_sha256=_h(f"anchor-source-policy:{goal}"),
    )


def _build(tmp_path: Path, *, goal: str = "sink", name: str = "anchor"):
    return build_structural_anchor_v1(
        (tmp_path / name).resolve(),
        plan=_plan(goal),
        source_authority_key=SOURCE_KEY,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
    )


def test_nonempty_anchor_is_one_edge_one_base_and_zero_scientific_evidence(
    tmp_path: Path,
) -> None:
    runtime = _build(tmp_path)
    phase = runtime.registry.to_state()
    factor = runtime.bank.to_state()

    assert len(phase.manifests) == 1
    assert phase.manifests[0].split == "TRAIN_UPDATE"
    assert len(phase.proofs) == len(phase.events) == len(phase.seals) == 1
    assert phase.events[0].status == "verified_delta"
    expected_paths = set(phase_mutable_factor_paths_v3(phase.artifacts[0].program))
    assert {item.descriptor.locator.path for item in phase.factors} == expected_paths
    assert len(factor.factors) == len(expected_paths) + 2
    assert len(factor.compositions[0].bindings) == len(expected_paths) + 1
    edge = runtime.bank.direct_transitions[factor.direct_transitions[0].transition_id]
    source_composition = runtime.bank.compositions[edge.source_composition_id]
    target_composition = runtime.bank.compositions[edge.target_composition_id]
    background = tuple(
        runtime.bank.factors[revision_id]
        for slot, revision_id in sorted(source_composition.binding_map.items())
        if slot != edge.slot_id
    )
    capabilities = phase_factor_capabilities(runtime.registry)
    assert capabilities["direct_binding_verifier"](
        edge,
        source_composition,
        target_composition,
        runtime.bank.factors[edge.from_revision_id],
        runtime.bank.factors[edge.to_revision_id],
        background,
    )
    assert len(factor.direct_transitions) == 1
    assert len(factor.base_receipts) == 1
    assert len(factor.deployment_heads) == 1
    assert factor.direct_transitions[0].proposal_action_id is None
    assert factor.direct_transitions[0].proposal_action_intent_sha256 is None
    assert not factor.plans
    assert not factor.reservations
    assert not factor.attempts
    assert not factor.assessments
    assert not factor.gate_opportunities
    assert not factor.gate_receipts
    assert not factor.failures
    assert not factor.repair_opportunities
    assert not factor.proposal_actions
    assert not factor.exposures
    assert not factor.tombstones
    assert not factor.portable_evidence_leaves
    assert runtime.bundle.zero_evidence.outcomes == 0
    assert runtime.bundle.zero_evidence.positive_credit == 0
    assert runtime.bundle.zero_evidence.negative_credit == 0

    serialized = (
        runtime.phase_registry_envelope_bytes
        + runtime.factor_bank_envelope_bytes
    ).lower()
    for forbidden in (
        b'"test"',
        b"ground_truth",
        b"expected_output",
        b"private_prompt",
        b"raw_prompt",
        b"raw_response",
        b"answer_key",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("goal", ["sink", "all_agents"])
def test_native_reload_preserves_exact_contract_and_frozen_root(
    tmp_path: Path,
    goal: str,
) -> None:
    plan = _plan(goal)
    built = build_structural_anchor_v1(
        (tmp_path / goal).resolve(),
        plan=plan,
        source_authority_key=SOURCE_KEY,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
    )
    loaded = load_structural_anchor_v1(
        (tmp_path / goal).resolve(),
        plan=plan,
        expected_bundle=built.bundle,
        source_authority_key=SOURCE_KEY,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
    )

    assert loaded.bundle == built.bundle
    assert loaded.phase_registry_envelope_bytes == built.phase_registry_envelope_bytes
    assert loaded.factor_bank_envelope_bytes == built.factor_bank_envelope_bytes
    proof = loaded.registry.to_state().proofs[0]
    assert proof.namespace == plan.namespace
    assert proof.namespace.information_goal == goal
    assert proof.namespace.planner_mode == "program_generate"
    assert proof.namespace.worker_contract == "not_applicable"
    assert proof.descriptor.locator.path == STRUCTURAL_ANCHOR_LOCATOR
    assert proof.descriptor.activation_kind == "execution_image_load"
    assert proof.source_activation.mode == "image_loaded"
    assert proof.target_activation.mode == "image_loaded"
    assert built.bundle.exact_root_requires_one_time_freeze
    assert built.bundle.root_policy == "freeze_first_exact_native_envelopes"


def test_fresh_builds_require_one_time_root_freeze_because_seals_are_random(
    tmp_path: Path,
) -> None:
    first = _build(tmp_path, name="first")
    second = _build(tmp_path, name="second")

    assert first.registry.to_state().seals[0].nonce_commitment != (
        second.registry.to_state().seals[0].nonce_commitment
    )
    assert first.bundle.anchor_root_sha256 != second.bundle.anchor_root_sha256
    assert first.bundle.anchor_plan_sha256 == second.bundle.anchor_plan_sha256
    assert first.bundle.source_authority_sha256 == second.bundle.source_authority_sha256


@pytest.mark.parametrize("n_agents", [2, 5, 16, 17])
def test_anchor_image_load_edge_preserves_original_agent_domain(
    tmp_path: Path,
    n_agents: int,
) -> None:
    plan = _plan(n_agents=n_agents)
    runtime = build_structural_anchor_v1(
        (tmp_path / f"agents-{n_agents}").resolve(),
        plan=plan,
        source_authority_key=SOURCE_KEY,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
    )
    proof = runtime.registry.to_state().proofs[0]
    source = runtime.registry.resolve_artifact(proof.source_artifact)
    target = runtime.registry.resolve_artifact(proof.target_artifact)

    assert proof.descriptor.locator.path == STRUCTURAL_ANCHOR_LOCATOR
    assert proof.descriptor.activation_kind == "execution_image_load"
    assert source.execution_image != target.execution_image
    assert source.program.phases[0].kind == "gather"
    assert source.program.phases[1].kind == "broadcast"
    assert source.program.phases[1].hub == 0
    assert target.program.phases[1].hub == 1


@pytest.mark.parametrize(
    "forbidden_field",
    ["split", "test_case", "answer", "ground_truth", "raw_prompt", "private_prompt"],
)
def test_plan_has_no_test_private_or_raw_ingress(forbidden_field: str) -> None:
    payload = _plan().model_dump(mode="python")
    payload[forbidden_field] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuralAnchorPlanV1.model_validate(payload)


def test_contract_crossing_and_wrong_authority_fail_closed(tmp_path: Path) -> None:
    invalid_namespace = _namespace().model_copy(
        update={"model_name": "stronger-model"}
    )
    with pytest.raises(ValidationError, match="contract"):
        StructuralAnchorPlanV1(
            namespace=invalid_namespace,
            source_catalog_sha256=_h("catalog"),
            source_policy_sha256=_h("policy"),
        )

    built = _build(tmp_path)
    with pytest.raises((ValueError, RuntimeError), match="manifest|anchor|rejected"):
        load_structural_anchor_v1(
            (tmp_path / "anchor").resolve(),
            plan=_plan(),
            expected_bundle=built.bundle,
            source_authority_key=hashlib.sha256(b"wrong-source-authority").digest(),
            phase_registry_key=PHASE_KEY,
            factor_bank_key=FACTOR_KEY,
        )


def test_branch_verifier_does_not_expose_an_arbitrary_fact_signer(tmp_path: Path) -> None:
    runtime = _build(tmp_path)
    phase = runtime.registry.to_state()
    source = phase.proofs[0].source_artifact
    source_factor = phase.proofs[0].source_factor

    with pytest.raises(ValueError, match="trusted branch/provenance verifier rejected"):
        runtime.registry.register_branch_receipt(
            branch="mutate",
            source_artifact=source,
            locator=STRUCTURAL_ANCHOR_LOCATOR,
            mutation_parent_factor=source_factor,
            additional_input_root_commitments=(
                runtime.bundle.anchor_plan_sha256,
                runtime.bundle.source_authority_sha256,
            ),
            producer_epoch="sft-anchor-host:v2",
            attestation_sha256=_h("caller-invented-branch-fact"),
        )


def test_paths_and_exact_envelope_bytes_fail_closed(tmp_path: Path) -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="absolute"):
        build_structural_anchor_v1(
            Path("relative-anchor"),
            plan=plan,
            source_authority_key=SOURCE_KEY,
            phase_registry_key=PHASE_KEY,
            factor_bank_key=FACTOR_KEY,
        )

    built = _build(tmp_path)
    with pytest.raises(FileExistsError, match="already exists"):
        build_structural_anchor_v1(
            (tmp_path / "anchor").resolve(),
            plan=plan,
            source_authority_key=SOURCE_KEY,
            phase_registry_key=PHASE_KEY,
            factor_bank_key=FACTOR_KEY,
        )

    built.phase_registry_path.write_bytes(
        built.phase_registry_envelope_bytes + b"\n"
    )
    with pytest.raises(ValueError, match="exact envelope digest mismatch"):
        load_structural_anchor_v1(
            (tmp_path / "anchor").resolve(),
            plan=plan,
            expected_bundle=built.bundle,
            source_authority_key=SOURCE_KEY,
            phase_registry_key=PHASE_KEY,
            factor_bank_key=FACTOR_KEY,
        )

    changed = built.bundle.model_copy(
        update={"phase_registry_envelope_sha256": _h("changed-envelope")}
    )
    changed = changed.model_copy(
        update={
            "anchor_root_sha256": _h("temporarily-invalid-root")
        }
    )
    # The closed bundle itself refuses a caller-edited digest/root pair before
    # the loader can be tricked into treating changed bytes as authoritative.
    with pytest.raises(ValidationError, match="root is not reproducible"):
        type(built.bundle).model_validate(changed.model_dump(mode="python"))


def test_anchorize_source_program_override(tmp_path: Path) -> None:
    """S4: an accepted whole composition anchors the next round's genesis."""

    accepted = {
        "format": "phase_program_v1",
        "information_goal": "sink",
        "selected_primary": 0,
        "state_retention": "keep",
        "allow_no_send": True,
        "submit_when": "coverage_complete",
        "phases": [
            {"kind": "gather", "hub": 0, "pattern": "tree"},
            {
                "kind": "pairwise_exchange",
                "pattern": "rotating",
                "max_rounds": 2,
            },
            {"kind": "broadcast", "hub": 0, "pattern": "tree"},
        ],
    }
    plan = StructuralAnchorPlanV1(
        namespace=_namespace("sink"),
        source_catalog_sha256=_h("anchorize-catalog"),
        source_policy_sha256=_h("anchorize-policy"),
        base_structure="broadcast",
        source_program_override=accepted,
    )
    # Frozen genesis-locus rule: phase 0 pattern flip.
    assert plan.anchor_locus == "/phases/0/pattern"
    assert plan.anchor_field_name == "pattern"
    assert plan.anchor_scalar_type == "string"
    assert plan.anchor_target_value == "star"
    assert [item.kind for item in plan.source_program.phases] == [
        "gather",
        "pairwise_exchange",
        "broadcast",
    ]
    assert plan.target_program.phases[0].pattern == "star"
    assert plan.digest != StructuralAnchorPlanV1(
        namespace=_namespace("sink"),
        source_catalog_sha256=_h("anchorize-catalog"),
        source_policy_sha256=_h("anchorize-policy"),
        base_structure="broadcast",
    ).digest

    runtime = build_structural_anchor_v1(
        (tmp_path / "anchorized").resolve(),
        plan=plan,
        source_authority_key=SOURCE_KEY,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
    )
    edge = runtime.bundle
    assert edge is not None
    state = runtime.registry.to_state()
    programs = {
        tuple(item.kind for item in artifact.program.phases)
        for artifact in state.artifacts
    }
    assert ("gather", "pairwise_exchange", "broadcast") in programs
