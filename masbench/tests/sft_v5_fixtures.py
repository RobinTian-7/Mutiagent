"""Shared authoring factory for a complete, provisioned v5 experiment fixture.

Tests are the experiment *author* here: they build the structural anchor,
freeze every manifest byte, seal the experiment, and provision the store —
exactly the artifacts a real Stage-12 authoring pass would freeze, but with
synthetic dataset commitments and test-only keys.  Nothing in this module
bypasses production validation; every object goes through the same closed
schemas and the same provisioning entry the real pilot will use.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.phase_artifact_registry import PHASE_FULL_FACTOR_BINDER_VERSION
from exp_graph.mas.phase_program import PHASE_PROGRAM_COMPILER_VERSION

from masbench.core.config import RunConfig
from masbench.sft_phase_pilot import _derive_key
from masbench.sft_pilot.bootstrap_authority import (
    AUTHORITY_KEY_ROLES,
    PilotAuthorityKeyCommitmentV1,
    PilotBootstrapAuthorityManifestV1,
    authority_key_commitment,
    authority_root_commitment,
)
from masbench.sft_pilot.experiment import (
    ANCHOR_DIRNAME,
    PilotExperimentProvisionReceipt,
    PilotExperimentSealV1,
    bootstrap_code_source_paths,
    derive_method_policy_sha256,
    provision_phase_v5_experiment,
    runtime_code_source_paths,
    split_case_manifest_sha256,
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
    published_manifest_bytes,
)
from masbench.sft_pilot.runtime_authority import (
    RUNTIME_AUTHORITY_ROLES,
    RUNTIME_ROLE_DOMAINS,
    PilotRuntimeAuthorityManifestV1,
    PilotRuntimeRoleCommitmentV1,
    runtime_authority_key_commitment,
    runtime_authority_root_commitment,
)
from masbench.sft_pilot.runtime_authority import (
    _stable_file_sha256 as stable_file_sha256,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
    canonical_json,
    canonical_sha256,
)
from masbench.sft_pilot.scientific_runner import (
    derive_v5_bootstrap_role_key,
    derive_v5_component_keys,
    derive_v5_runtime_role_key,
)
from masbench.sft_pilot.structural_anchor import (
    StructuralAnchorPlanV1,
    StructuralAnchorRuntimeV1,
    build_structural_anchor_v1,
)


DEFAULT_MASTER = hashlib.sha256(b"sft-v5-experiment-fixture-master").digest()
FIXED_GIT_COMMIT = "3c6380d0b57e5872527a65153b310d601e7d50a8"
RUNTIME_VERSION = "sft-v5-runtime-v1"


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def v5_namespace(*, n_agents: int = 2) -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="silo_bench",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=n_agents,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version=RUNTIME_VERSION,
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _case_manifest() -> PilotCaseManifestV1:
    entries = []
    for index in range(6):
        entries.append(
            PilotCaseEntryV1(
                case_id=f"case-t{index}",
                split="TRAIN_UPDATE",
                unit_commitment=f"unit-t{index}",
                input_commitment_sha256=_h(f"case-input-t{index}"),
            )
        )
    entries.append(
        PilotCaseEntryV1(
            case_id="case-tgen",
            split="TRAIN_UPDATE",
            unit_commitment="unit-tgen",
            input_commitment_sha256=_h("case-input-tgen"),
        )
    )
    for label in ("va", "vb"):
        entries.append(
            PilotCaseEntryV1(
                case_id=f"case-v{label}",
                split="FINAL_VAL",
                unit_commitment=f"unit-v{label}",
                input_commitment_sha256=_h(f"case-input-v{label}"),
            )
        )
    ordered = tuple(sorted(entries, key=lambda item: item.case_id))
    return PilotCaseManifestV1(cases=ordered)


def _pair_manifest(cases: PilotCaseManifestV1) -> PilotPairManifestV1:
    by_id = {item.case_id: item for item in cases.cases}
    pairs = []
    probe_orders = ("AB", "BA", "AB", "BA", "AB", "BA")
    for index in range(6):
        case = by_id[f"case-t{index}"]
        pairs.append(
            PilotPairEntryV1(
                pair_id=f"pair-p{index}",
                case_id=case.case_id,
                unit_commitment=case.unit_commitment,
                case_commitment_sha256=case.input_commitment_sha256,
                arm_order=probe_orders[index],
                execution_ordinal=index,
            )
        )
    gen_case = by_id["case-tgen"]
    pairs.append(
        PilotPairEntryV1(
            pair_id="pair-gen",
            case_id=gen_case.case_id,
            unit_commitment=gen_case.unit_commitment,
            case_commitment_sha256=gen_case.input_commitment_sha256,
            arm_order="BA",
            execution_ordinal=6,
        )
    )
    for offset, label in enumerate(("va", "vb")):
        case = by_id[f"case-v{label}"]
        pairs.append(
            PilotPairEntryV1(
                pair_id=f"pair-fv-{label}",
                case_id=case.case_id,
                unit_commitment=case.unit_commitment,
                case_commitment_sha256=case.input_commitment_sha256,
                arm_order="AB" if offset == 0 else "BA",
                execution_ordinal=7 + offset,
            )
        )
    return PilotPairManifestV1(pairs=tuple(pairs))


def _candidate_manifest() -> PilotCandidateManifestV1:
    identities = sorted(
        (
            (_h(f"cell-{index}"), _h(f"target-key-{index}"), _h(f"target-{index}"))
            for index in range(3)
        )
    )
    return PilotCandidateManifestV1(
        candidates=tuple(
            PilotCandidateEntryV1(
                cell_sha256=cell,
                target_factor_key_sha256=key,
                target_content_sha256=content,
            )
            for cell, key, content in identities
        )
    )


def _runner_manifest() -> PilotRunnerManifestV1:
    sources = tuple(
        PilotCodeSourceV1(
            source_id=source_id,
            sha256=stable_file_sha256(path),
        )
        for source_id, path in sorted(runtime_code_source_paths().items())
    )
    owners = tuple(
        PilotFailureOwnerV1(safe_failure_code=code, owner=owner)
        for code, owner in sorted(
            {
                "algorithm_failure": "factor_algorithm",
                "final_val_external": "external_final_val",
                "harness_stop": "harness_stop",
                "provider_timeout": "store_indeterminate",
            }.items()
        )
    )
    return PilotRunnerManifestV1(
        fixed_git_commit=FIXED_GIT_COMMIT,
        exact_artifact_runner_version="sft-v5-exact-runner-v1",
        runtime_version=RUNTIME_VERSION,
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
        code_sources=sources,
        failure_owners=owners,
    )


def _logical_arms(
    pairs: PilotPairManifestV1,
) -> tuple[PilotLogicalArmCoordinatesV1, ...]:
    by_id = {item.pair_id: item for item in pairs.pairs}
    arms: list[PilotLogicalArmCoordinatesV1] = []
    gen = by_id["pair-gen"]
    arms.append(
        PilotLogicalArmCoordinatesV1(
            pair_id=gen.pair_id,
            pair_arm="control",
            case_commitment_sha256=gen.case_commitment_sha256,
            unit_commitment=gen.unit_commitment,
            split="TRAIN_UPDATE",
            operation_kind="proposal_generation",
            execution_ordinal=gen.execution_ordinal,
        )
    )
    for index in range(6):
        pair = by_id[f"pair-p{index}"]
        for pair_arm, operation in (
            ("source", "source_probe"),
            ("target", "target_probe"),
        ):
            arms.append(
                PilotLogicalArmCoordinatesV1(
                    pair_id=pair.pair_id,
                    pair_arm=pair_arm,
                    case_commitment_sha256=pair.case_commitment_sha256,
                    unit_commitment=pair.unit_commitment,
                    split="TRAIN_UPDATE",
                    operation_kind=operation,
                    execution_ordinal=pair.execution_ordinal,
                )
            )
    for label in ("va", "vb"):
        pair = by_id[f"pair-fv-{label}"]
        arms.append(
            PilotLogicalArmCoordinatesV1(
                pair_id=pair.pair_id,
                pair_arm="control",
                case_commitment_sha256=pair.case_commitment_sha256,
                unit_commitment=pair.unit_commitment,
                split="FINAL_VAL",
                operation_kind="final_val",
                execution_ordinal=pair.execution_ordinal,
            )
        )
    return tuple(arms)


_ARM_ROLE = {
    "proposal_generation": "proposal_generation",
    "source_probe": "source_artifact",
    "target_probe": "target_artifact",
    "final_val": "final_deployment",
}


def _execution_schedule(
    arms: tuple[PilotLogicalArmCoordinatesV1, ...],
) -> PilotExecutionScheduleV1:
    entries = []
    for index, arm in enumerate(arms):
        entries.append(
            PilotExecutionScheduleEntryV1(
                logical_arm=arm,
                physical_block_ordinal=index,
                calls=(
                    PilotCallScheduleEntryV1(
                        call_slot=0,
                        input_tokens_reserved=1_024,
                        output_tokens_reserved=256,
                        request_envelope_sha256=_h(
                            f"request-envelope-{index}-{arm.pair_id}-{arm.pair_arm}"
                        ),
                        request_renderer_sha256=_h("sft-v5-request-renderer"),
                        prompt_template_sha256=_h(
                            f"prompt-template-{arm.operation_kind}"
                        ),
                        json_mode=True,
                        artifact_role=_ARM_ROLE[arm.operation_kind],
                    ),
                ),
            )
        )
    return PilotExecutionScheduleV1(entries=tuple(entries))


def _phase_budgets(method_arm: str) -> tuple[AuthorizedPhaseBudgetV1, ...]:
    return (
        AuthorizedPhaseBudgetV1(
            phase="TRAIN_UPDATE",
            method_arm=method_arm,
            executions=1,
            call_slots=1,
            input_tokens=1_024,
            output_tokens=256,
        ),
        AuthorizedPhaseBudgetV1(
            phase="PROBE",
            method_arm=method_arm,
            executions=12,
            call_slots=12,
            input_tokens=12_288,
            output_tokens=3_072,
        ),
        AuthorizedPhaseBudgetV1(
            phase="FINAL_VAL",
            method_arm=method_arm,
            executions=2,
            call_slots=2,
            input_tokens=2_048,
            output_tokens=512,
        ),
    )


def _capacity_policy() -> PilotCapacityPolicyV1:
    return PilotCapacityPolicyV1(
        max_scientific_commits=64,
        max_execution_leases=32,
        max_call_receipts=64,
        max_component_checkpoints=64,
        max_call_slots_per_execution=1,
        max_input_tokens_per_call=2_048,
        max_output_tokens_per_call=512,
        max_active_db_bytes=256 * 1024 * 1024,
        max_archive_bytes=4 * 1024 * 1024,
        max_total_stored_scalar_bytes=32 * 1024 * 1024,
    )


def _protocol(
    *,
    protocol_id: str,
    method_arm: str,
    genesis_state_sha256: str,
    namespace: ExecutionNamespace,
    anchor_source_authority_sha256: str,
    cases: PilotCaseManifestV1,
    pairs: PilotPairManifestV1,
    candidates: PilotCandidateManifestV1,
    runner: PilotRunnerManifestV1,
    schedule: PilotExecutionScheduleV1,
    arms: tuple[PilotLogicalArmCoordinatesV1, ...],
) -> PilotProtocolV1:
    return PilotProtocolV1(
        protocol_id=protocol_id,
        method_arm=method_arm,
        namespace=namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=cases.digest,
            source_policy_sha256=_h("sft-v5-source-policy"),
        ),
        source_authority_sha256=anchor_source_authority_sha256,
        dataset_split_policy_sha256=_h("sft-v5-split-policy"),
        candidate_pool_manifest_sha256=candidates.digest,
        runner_config_sha256=runner.digest,
        model_config_sha256=_h("sft-v5-model-config"),
        pair_manifest_sha256=pairs.digest,
        genesis_state_sha256=genesis_state_sha256,
        component_bundle_required=True,
        component_checkpoint_saga_required=True,
        execution_schedule_sha256=schedule.digest,
        store_derived_schedule_required=True,
        authorized_logical_arms=arms,
        phase_budgets=_phase_budgets(method_arm),
        capacity_policy=_capacity_policy(),
    )


@dataclass(frozen=True)
class V5Experiment:
    """One fully authored, sealed, and provisioned v5 experiment."""

    master: bytes
    root: Path
    state_dir: Path
    anchor_dir: Path
    result_dir: Path
    runtime_authority_root: Path
    seal: PilotExperimentSealV1
    seal_path: Path
    protocol: PilotProtocolV1
    protocol_path: Path
    control_protocol: PilotProtocolV1
    runtime_authority: PilotRuntimeAuthorityManifestV1
    runtime_authority_path: Path
    bootstrap_authority: PilotBootstrapAuthorityManifestV1
    bootstrap_authority_path: Path
    anchor_runtime: StructuralAnchorRuntimeV1
    provision_receipt: PilotExperimentProvisionReceipt
    component_keys: dict[str, bytes]

    def run_config(self, **updates: object) -> RunConfig:
        values: dict[str, object] = {
            "benchmark": "silo_bench",
            "use_planner": True,
            "use_skill_evolution": True,
            "sft_profile": "phase_v5_executable_sft",
            "sft_state_dir": str(self.state_dir),
            "sft_protocol_path": str(self.protocol_path),
            "sft_experiment_manifest_path": str(self.seal_path),
            "sft_runtime_authority_path": str(self.runtime_authority_path),
            "sft_bootstrap_authority_path": str(self.bootstrap_authority_path),
            "sft_result_dir": str(self.result_dir),
            "planner_mode": "program_generate",
            "evolved_mode": "program_generate",
            "objective": "balanced",
            "silo_eval_mode": "sink",
            "failure_policy": "honest_v2",
            "evolution_gate_policy": "strict_dense_v2",
            "evolve_explore": 0,
            "evidence_portfolio": "",
            "recipe_search_budget": 0,
            "exemplar_search_budget": 0,
            "use_llm_insights": False,
            "hot_start_enabled": False,
            "llm_provider": "fake",
            "model_name": "fake",
            "temperature": 0.0,
        }
        values.update(updates)
        return RunConfig(**values)

    def runtime_role_key(self, role: str) -> bytes:
        return derive_v5_runtime_role_key(self.master, role)


def build_v5_experiment(
    tmp_path: Path,
    *,
    master: bytes = DEFAULT_MASTER,
    provision: bool = True,
) -> V5Experiment:
    """Author, seal, and (optionally) provision one complete v5 experiment."""

    root = Path(tmp_path)
    state_dir = (root / "state").resolve()
    anchor_dir = state_dir / ANCHOR_DIRNAME
    result_dir = (root / "results").resolve()
    runtime_authority_root = (root / "runtime-authority-root").resolve()
    runtime_authority_root.mkdir(parents=True, exist_ok=True)

    keys = derive_v5_component_keys(master)
    namespace = v5_namespace()
    plan = StructuralAnchorPlanV1(
        namespace=namespace,
        source_catalog_sha256=_case_manifest().digest,
        source_policy_sha256=_h("sft-v5-source-policy"),
    )
    anchor_runtime = build_structural_anchor_v1(
        anchor_dir,
        plan=plan,
        source_authority_key=keys["source_authority"],
        phase_registry_key=keys["phase_registry"],
        factor_bank_key=keys["factor_bank"],
    )
    anchor = anchor_runtime.bundle

    cases = _case_manifest()
    pairs = _pair_manifest(cases)
    candidates = _candidate_manifest()
    runner = _runner_manifest()
    arms = _logical_arms(pairs)
    schedule = _execution_schedule(arms)

    from masbench.sft_pilot.store import (
        component_genesis_sha256_from_envelope_digests,
    )

    genesis = component_genesis_sha256_from_envelope_digests(
        phase_registry_envelope_sha256=anchor.phase_registry_envelope_sha256,
        factor_bank_envelope_sha256=anchor.factor_bank_envelope_sha256,
    )
    protocol = _protocol(
        protocol_id="sft-v5-experiment-sft-unified",
        method_arm="sft_unified",
        genesis_state_sha256=genesis,
        namespace=namespace,
        anchor_source_authority_sha256=anchor.source_authority_sha256,
        cases=cases,
        pairs=pairs,
        candidates=candidates,
        runner=runner,
        schedule=schedule,
        arms=arms,
    )
    control_protocol = _protocol(
        protocol_id="sft-v5-experiment-ect-control",
        method_arm="ect_whole_transaction",
        genesis_state_sha256=_h("sft-v5-ect-genesis"),
        namespace=namespace,
        anchor_source_authority_sha256=anchor.source_authority_sha256,
        cases=cases,
        pairs=pairs,
        candidates=candidates,
        runner=runner,
        schedule=schedule,
        arms=arms,
    )

    method_arms = ("sft_unified", "ect_whole_transaction")
    experiment = PilotExperimentManifestV1(
        experiment_id="sft-v5-experiment",
        case_manifest_sha256=cases.digest,
        pair_manifest_sha256=pairs.digest,
        candidate_manifest_sha256=candidates.digest,
        runner_manifest_sha256=runner.digest,
        model_config_sha256=_h("sft-v5-model-config"),
        execution_schedule_sha256=schedule.digest,
        arms=(
            PilotExperimentArmV1(
                method_arm="sft_unified",
                child_protocol_sha256=protocol.digest,
                implementation_sha256=_h("sft-v5-impl-sft-unified"),
                state_dir_commitment_sha256=canonical_sha256(
                    {
                        "domain": "sft-v5-state-dir-commitment",
                        "arm": "sft_unified",
                        "path": str(state_dir),
                    }
                ),
                execution_schedule_sha256=schedule.digest,
            ),
            PilotExperimentArmV1(
                method_arm="ect_whole_transaction",
                child_protocol_sha256=control_protocol.digest,
                implementation_sha256=_h("sft-v5-impl-ect"),
                state_dir_commitment_sha256=canonical_sha256(
                    {
                        "domain": "sft-v5-state-dir-commitment",
                        "arm": "ect_whole_transaction",
                        "path": str(root / "ect-state"),
                    }
                ),
                execution_schedule_sha256=schedule.digest,
            ),
        ),
        blocked_arm_orders=tuple(
            PilotBlockedArmOrderV1(
                block_ordinal=index,
                unit_commitment=pair.unit_commitment,
                arm_order=(
                    method_arms if index % 2 == 0 else tuple(reversed(method_arms))
                ),
            )
            for index, pair in enumerate(pairs.pairs)
        ),
    )

    bootstrap_authority = PilotBootstrapAuthorityManifestV1(
        authority_kind="host_pinned",
        bootstrap_id="sft-v5-bootstrap",
        fixed_git_commit=FIXED_GIT_COMMIT,
        dataset_release_manifest_sha256=_h("sft-v5-dataset-release"),
        dataset_split_manifest_sha256=_h("sft-v5-dataset-split"),
        train_loader_policy_sha256=_h("sft-v5-train-loader-policy"),
        namespace_template_sha256=canonical_sha256(namespace),
        anchor_freeze_dir_commitment_sha256=authority_root_commitment(anchor_dir),
        authority_code_sources=tuple(
            PilotCodeSourceV1(
                source_id=source_id,
                sha256=stable_file_sha256(path),
            )
            for source_id, path in sorted(bootstrap_code_source_paths().items())
        ),
        authority_key_commitments=tuple(
            PilotAuthorityKeyCommitmentV1(
                role=role,
                key_commitment_sha256=authority_key_commitment(
                    role=role,
                    key=derive_v5_bootstrap_role_key(master, role),
                ),
            )
            for role in AUTHORITY_KEY_ROLES
        ),
    )

    runtime_authority = PilotRuntimeAuthorityManifestV1(
        authority_kind="host_pinned",
        runtime_authority_id="sft-v5-runtime-authority",
        fixed_git_commit=FIXED_GIT_COMMIT,
        bootstrap_authority_manifest_sha256=bootstrap_authority.digest,
        source_authority_manifest_sha256=anchor.source_manifest_sha256,
        runner_manifest_sha256=runner.digest,
        execution_schedule_sha256=schedule.digest,
        method_policy_sha256=derive_method_policy_sha256(method_arms),
        authority_root_commitment_sha256=runtime_authority_root_commitment(
            runtime_authority_root
        ),
        authority_code_sources=tuple(
            PilotCodeSourceV1(
                source_id=source_id,
                sha256=stable_file_sha256(path),
            )
            for source_id, path in sorted(runtime_code_source_paths().items())
        ),
        role_commitments=tuple(
            PilotRuntimeRoleCommitmentV1(
                role=role,
                allowed_domains=RUNTIME_ROLE_DOMAINS[role],
                key_commitment_sha256=runtime_authority_key_commitment(
                    role=role,
                    key=derive_v5_runtime_role_key(master, role),
                ),
            )
            for role in RUNTIME_AUTHORITY_ROLES
        ),
    )

    seal = PilotExperimentSealV1(
        experiment_id="sft-v5-experiment",
        fixed_git_commit=FIXED_GIT_COMMIT,
        runtime_authority_manifest_sha256=runtime_authority.digest,
        bootstrap_authority_manifest_sha256=bootstrap_authority.digest,
        method_policy_sha256=derive_method_policy_sha256(method_arms),
        experiment=experiment,
        case_manifest=cases,
        pair_manifest=pairs,
        candidate_manifest=candidates,
        runner_manifest=runner,
        execution_schedule=schedule,
        structural_anchor_plan=plan,
        structural_anchor=anchor,
        train_case_manifest_sha256=split_case_manifest_sha256(
            cases, split="TRAIN_UPDATE"
        ),
        final_val_case_manifest_sha256=split_case_manifest_sha256(
            cases, split="FINAL_VAL"
        ),
        test_manifest_sha256=_h("sft-v5-test-manifest-commitment"),
        report_manifest_sha256=_h("sft-v5-report-manifest-commitment"),
        state_genesis_sha256=genesis,
    )

    seal_path = (root / "experiment-seal.json").resolve()
    seal_path.write_bytes(published_manifest_bytes(seal))
    protocol_path = (root / "protocol.json").resolve()
    protocol_path.write_text(canonical_json(protocol), encoding="utf-8")
    runtime_authority_path = (root / "runtime-authority.json").resolve()
    runtime_authority_path.write_bytes(
        published_manifest_bytes(runtime_authority)
    )
    bootstrap_authority_path = (root / "bootstrap-authority.json").resolve()
    bootstrap_authority_path.write_bytes(
        published_manifest_bytes(bootstrap_authority)
    )

    if provision:
        receipt = provision_phase_v5_experiment(
            seal=seal,
            protocol=protocol,
            runtime_authority=runtime_authority,
            bootstrap_authority=bootstrap_authority,
            state_dir=state_dir,
            store_hmac_key=keys["store"],
            source_authority_key=keys["source_authority"],
            phase_registry_key=keys["phase_registry"],
            factor_bank_key=keys["factor_bank"],
        )
    else:
        receipt = PilotExperimentProvisionReceipt(
            seal_sha256=seal.digest,
            protocol_sha256=protocol.digest,
            genesis_state_sha256=genesis,
            preflight_sha256="0" * 64,
            schema_sha256="0" * 64,
            structural_anchor_root_sha256=anchor.anchor_root_sha256,
        )

    return V5Experiment(
        master=master,
        root=root,
        state_dir=state_dir,
        anchor_dir=anchor_dir,
        result_dir=result_dir,
        runtime_authority_root=runtime_authority_root,
        seal=seal,
        seal_path=seal_path,
        protocol=protocol,
        protocol_path=protocol_path,
        control_protocol=control_protocol,
        runtime_authority=runtime_authority,
        runtime_authority_path=runtime_authority_path,
        bootstrap_authority=bootstrap_authority,
        bootstrap_authority_path=bootstrap_authority_path,
        anchor_runtime=anchor_runtime,
        provision_receipt=receipt,
        component_keys=keys,
    )
