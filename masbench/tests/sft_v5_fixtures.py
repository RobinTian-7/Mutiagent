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


def v5_namespace(*, n_agents: int = 3) -> ExecutionNamespace:
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

# The anchor's sole mutable locus is an int-typed hub slot; the generation
# schedule entry pins the real renderer envelope over that frozen shape.
ANCHOR_LOCATOR = "/phases/1/hub"
ANCHOR_SCALAR_TYPE = "int"


def _generation_envelope() -> tuple[str, str]:
    from masbench.sft_pilot.factor_authority import derive_generation_budget
    from masbench.sft_pilot.request_renderer import (
        GENERATION_POLICY_SHA256,
        PROMPT_TEMPLATE_SHA256,
        RENDERER_POLICY_SHA256,
        SCALAR_OUTPUT_SCHEMA_SHA256,
        generation_request_envelope_sha256,
    )

    budget = derive_generation_budget(_phase_budgets("sft_unified")[0])
    return (
        generation_request_envelope_sha256(
            locator_path=ANCHOR_LOCATOR,
            scalar_type=ANCHOR_SCALAR_TYPE,
            generation_policy_sha256=GENERATION_POLICY_SHA256,
            prompt_template_sha256=PROMPT_TEMPLATE_SHA256,
            scalar_output_schema_sha256=SCALAR_OUTPUT_SCHEMA_SHA256,
            budget_sha256=budget.digest,
        ),
        RENDERER_POLICY_SHA256,
    )


def _execution_schedule(
    arms: tuple[PilotLogicalArmCoordinatesV1, ...],
) -> PilotExecutionScheduleV1:
    generation_envelope, renderer_policy = _generation_envelope()
    from masbench.sft_pilot.request_renderer import PROMPT_TEMPLATE_SHA256

    entries = []
    for index, arm in enumerate(arms):
        if arm.operation_kind == "proposal_generation":
            envelope = generation_envelope
            renderer_sha = renderer_policy
            template_sha = PROMPT_TEMPLATE_SHA256
        else:
            envelope = _h(
                f"request-envelope-{index}-{arm.pair_id}-{arm.pair_arm}"
            )
            renderer_sha = _h("sft-v5-request-renderer")
            template_sha = _h(f"prompt-template-{arm.operation_kind}")
        entries.append(
            PilotExecutionScheduleEntryV1(
                logical_arm=arm,
                physical_block_ordinal=index,
                calls=(
                    PilotCallScheduleEntryV1(
                        call_slot=0,
                        input_tokens_reserved=1_024,
                        output_tokens_reserved=256,
                        request_envelope_sha256=envelope,
                        request_renderer_sha256=renderer_sha,
                        prompt_template_sha256=template_sha,
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


class V5Harness:
    """One coordinator-restored v5 experiment with real authority verifiers.

    Shared by the generation/probe/pair test layers so every stage exercises
    the same production wiring: real registry, real Bank verifiers, real saga
    checkpoints, real store schedule, fake transport only.
    """

    def __init__(self, tmp_path: Path) -> None:
        import hashlib as _hashlib

        from masbench.sft_pilot.factor_authority import SFTPilotFactorAuthority
        from masbench.sft_pilot.components import PilotComponentCoordinator
        from masbench.sft_pilot.scientific_runner import (
            V5BranchReceiptAuthority,
            v5_factor_capabilities_factory,
        )
        from masbench.sft_pilot.store import SingleWriterPilotStore

        self._sha = lambda value: _hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()
        self.experiment = build_v5_experiment(tmp_path)
        self.authority = SFTPilotFactorAuthority(
            self.experiment.protocol,
            pair_manifest=self.experiment.seal.pair_manifest,
            attestation_key=self.experiment.runtime_role_key(
                "factor_pair_adapter"
            ),
        )
        anchor = self.experiment.seal.structural_anchor
        self.branch_authority = V5BranchReceiptAuthority(
            anchor_source_manifest_sha256=anchor.source_manifest_sha256,
        )
        self.store = SingleWriterPilotStore.open(
            self.experiment.state_dir,
            protocol=self.experiment.protocol,
            hmac_key=self.experiment.component_keys["store"],
            execution_schedule=self.experiment.seal.execution_schedule,
        )
        self.coordinator = PilotComponentCoordinator(
            store=self.store,
            phase_registry_key=self.experiment.component_keys["phase_registry"],
            factor_bank_key=self.experiment.component_keys["factor_bank"],
            manifest_verifier=self._verify_manifest,
            factor_capabilities_factory=v5_factor_capabilities_factory(
                authority=self.authority,
                seal=self.experiment.seal,
            ),
            branch_receipt_verifier=self.branch_authority,
        )
        self.loaded = self.coordinator.restore_recovery_head()
        self.checkpoint_ordinal = 0

    def _verify_manifest(self, manifest: object) -> bool:
        anchor = self.experiment.seal.structural_anchor
        return bool(
            manifest.manifest_sha256 == anchor.source_manifest_sha256
            and manifest.split == "TRAIN_UPDATE"
        )

    def close(self) -> None:
        self.store.close()

    def reopen(self):
        """Simulate a process crash/restart: reopen and restore the head."""

        from masbench.sft_pilot.components import PilotComponentCoordinator
        from masbench.sft_pilot.scientific_runner import (
            v5_factor_capabilities_factory,
        )
        from masbench.sft_pilot.store import SingleWriterPilotStore

        self.store.close()
        self.store = SingleWriterPilotStore.open(
            self.experiment.state_dir,
            protocol=self.experiment.protocol,
            hmac_key=self.experiment.component_keys["store"],
            execution_schedule=self.experiment.seal.execution_schedule,
        )
        self.coordinator = PilotComponentCoordinator(
            store=self.store,
            phase_registry_key=self.experiment.component_keys["phase_registry"],
            factor_bank_key=self.experiment.component_keys["factor_bank"],
            manifest_verifier=self._verify_manifest,
            factor_capabilities_factory=v5_factor_capabilities_factory(
                authority=self.authority,
                seal=self.experiment.seal,
            ),
            branch_receipt_verifier=self.branch_authority,
        )
        self.loaded = self.coordinator.restore_recovery_head()
        return self.loaded

    @property
    def bank(self):
        return self.loaded.bank

    @property
    def registry(self):
        return self.loaded.registry

    def checkpoint(self):
        self.checkpoint_ordinal += 1
        self.loaded = self.coordinator.checkpoint_loaded(
            self.loaded,
            operation_id=f"v5-checkpoint-{self.checkpoint_ordinal}",
            operation_request_sha256=self._sha(
                f"v5-checkpoint:{self.checkpoint_ordinal}"
            ),
        )
        return self.loaded

    def anchor_edge(self):
        from exp_graph.mas.phase_factor_binding_v3 import (
            register_phase_materialization_v3,
        )

        proofs = self.registry.to_state().proofs
        return register_phase_materialization_v3(
            registry=self.registry,
            bank=self.bank,
            proof=proofs[0].handle,
        )

    def prepare_action(self, branch: str, *, tag: str):
        from exp_graph.mas.factor_bank_v2 import (
            FailureObservationV2,
            ProposalCursorV1,
            ProposalRequestV1,
            SFTProposalInputV1,
            proposal_counter_state_sha256,
        )
        from exp_graph.mas.sft_proposal import (
            ExactFactorLocusV1,
            ExactProposalCellV1,
            select_exact_edge_proposal,
        )
        from masbench.sft_pilot.request_renderer import (
            GENERATION_POLICY_SHA256,
            PROMPT_TEMPLATE_SHA256,
            SCALAR_OUTPUT_SCHEMA_SHA256,
        )

        edge = self.anchor_edge()
        observation = FailureObservationV2(
            failure_id=f"failure:v5:{tag}",
            failure_class="algorithm",
            failed_stage="execute",
            safe_failure_code="algorithm_failure",
            composition_id=edge.source_composition.composition_id,
            artifact_sha256=edge.source_composition.artifact_sha256,
            created_seq=self.bank.to_state().event_seq + 1,
        )
        opportunity = self.bank.record_failure(
            observation, feasible_branches=(branch,)
        )
        assert opportunity is not None
        locus = ExactFactorLocusV1(
            carrier="phase_program",
            slot_id=edge.transition.slot_id,
            logical_factor_id=edge.source_factor.logical_factor_id,
            locator_surface="phase_field",
            locator_path=edge.source_factor.locator.path,
            locator_version=edge.source_factor.locator.locator_version,
        )
        cell = ExactProposalCellV1(
            namespace=self.experiment.protocol.namespace,
            locus=locus,
            from_revision_id=edge.source_factor.revision_id,
            canonical_from_factor_key_sha256=(
                self.bank._factor_carrier_key_sha256(edge.source_factor)
            ),
            canonical_background_sha256=(
                self.bank._canonical_direct_background_sha256(
                    self.bank.to_state(),
                    source=edge.source_composition,
                    source_factor=edge.source_factor,
                    slot_id=locus.slot_id,
                )
            ),
        )
        candidates, _root, _count = self.bank._proposal_candidate_slate(
            opportunity=opportunity,
            source_factor=edge.source_factor,
            slot_id=locus.slot_id,
        )
        state = self.bank.to_state()
        proposal = select_exact_edge_proposal(
            SFTProposalInputV1(
                request=ProposalRequestV1(
                    opportunity_id=opportunity.opportunity_id,
                    cell=cell,
                ),
                cursor=ProposalCursorV1.empty(cell),
                candidates=candidates,
                proposal_counter_state_sha256=proposal_counter_state_sha256(
                    tuple(
                        item.witness
                        for item in state.proposal_lifetime_counters
                        if item.cell_sha256 == cell.scheduler_key_sha256
                    )
                ),
                candidate_counter_witnesses=(
                    self.bank._proposal_counter_witnesses(
                        state,
                        cell_sha256=cell.scheduler_key_sha256,
                        candidates=candidates,
                    )
                ),
            )
        )
        context = None
        if branch in {"mutate", "fresh"}:
            context = self.authority.make_generation_context(
                opportunity=opportunity,
                failure=observation,
                proposal_receipt=proposal,
                source=edge.source_composition,
                source_factor=edge.source_factor,
                source_manifest_sha256=(
                    self.experiment.seal.structural_anchor.source_manifest_sha256
                ),
                generation_policy_sha256=GENERATION_POLICY_SHA256,
                prompt_template_sha256=PROMPT_TEMPLATE_SHA256,
                scalar_output_schema_sha256=SCALAR_OUTPUT_SCHEMA_SHA256,
            )
        decision, assignment, action = self.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch=self.authority.assignment_producer_epoch,
            attestation_sha256=self.authority.proposal_action_attestation(
                opportunity_id=opportunity.opportunity_id,
                proposal_receipt_sha256=proposal.digest,
            ),
            generation_context=context,
        )
        assert assignment is not None and action is not None
        assert assignment.branch == branch
        return edge, opportunity, observation, proposal, context, action

    def commit_mutate_edge(self, *, tag: str, generated_value: int = 2):
        """Run the complete Stage-4 mutate slice and return the new edge."""

        import json as _json

        from exp_graph.mas.factor_bank import ExecutionUsage
        from exp_graph.mas.phase_artifact_registry import (
            PhaseGenerationTerminalV1,
            phase_generated_scalar_sha256,
        )
        from exp_graph.mas.phase_factor_binding_v3 import (
            reconcile_phase_proposal_action_v3,
        )
        from masbench.sft_pilot.llm_meter import FakeDeterministicPilotTransport
        from masbench.sft_pilot.request_renderer import (
            SafeSourceScalar,
            parse_generated_scalar,
            render_generation_request,
        )
        from masbench.sft_pilot.scientific_runner import (
            execute_metered_generation_call,
            reserve_scheduled_execution,
        )

        edge, _opp, _obs, _prop, context, action = self.prepare_action(
            "mutate", tag=tag
        )
        arm = next(
            item
            for item in self.experiment.protocol.authorized_logical_arms
            if item.operation_kind == "proposal_generation"
        )
        reserve_scheduled_execution(
            self.store,
            schedule=self.experiment.seal.execution_schedule,
            logical_arm=arm,
            logical_execution_key=f"v5-generation-owner-{tag}",
            action_id=action.action_id,
        )
        self.checkpoint()
        lease = self.authority.make_generation_lease(
            action=action,
            runner_session_id=f"v5-generation-runner:{tag}",
            runner_lease_token_sha256=self._sha(f"gen-token:{tag}"),
            journal_anchor_sha256=self._sha(f"gen-journal:{tag}"),
        )
        executing = self.bank.begin_proposal_generation(action.action_id, lease)
        self.checkpoint()
        rendered = render_generation_request(
            context=context,
            request=executing.generation_request,
            scalar_type="int",
            value_domain_description="an integer agent index in [0, 3)",
            source_scalar=SafeSourceScalar(scalar_type="int", value=0),
        )
        response = execute_metered_generation_call(
            store=self.store,
            schedule=self.experiment.seal.execution_schedule,
            logical_arm=arm,
            logical_execution_key=f"v5-generation-owner-{tag}",
            rendered=rendered,
            transport=FakeDeterministicPilotTransport(
                reply_factory=lambda _digest: _json.dumps(
                    {"value": generated_value}
                ),
            ),
            expected_component_recovery_root_sha256=(
                self.loaded.snapshot.recovery_root_sha256
            ),
        )
        value = parse_generated_scalar(response.text, scalar_type="int")
        self.branch_authority.authorize_action(executing)
        ingress = self.registry.issue_ingress(
            self.experiment.seal.structural_anchor.source_manifest_sha256
        )
        request = executing.generation_request
        generation_lease = executing.generation_lease
        terminal = PhaseGenerationTerminalV1(
            terminal_id=f"terminal:{tag}",
            action_transaction_id=executing.action_id,
            action_intent_sha256=executing.action_intent_sha256,
            branch=executing.branch,
            generation_request_id=request.request_id,
            generation_request_sha256=request.digest,
            generation_lease_id=generation_lease.lease_id,
            generation_lease_sha256=generation_lease.digest,
            runner_lease_token_sha256=generation_lease.runner_lease_token_sha256,
            generation_lease_started_sequence=generation_lease.started_seq,
            runtime_version=request.runtime_version,
            budget=request.budget,
            budget_sha256=request.budget_sha256,
            usage=ExecutionUsage(
                messages=1,
                model_calls=1,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                wall_time_ms=500,
                cost_microusd=(
                    response.usage.prompt_tokens * 10
                    + response.usage.completion_tokens * 40
                ),
            ),
            generated_scalar_sha256=phase_generated_scalar_sha256(value),
            response_envelope_sha256=self._sha(f"generation-response:{tag}"),
            terminal_event_id=f"generation-event:{tag}",
            terminal_event_sequence=generation_lease.started_seq + 1,
            verifier_epoch=f"v5-generation-terminal:{tag}",
            attestation_sha256=self._sha(f"generation-terminal:{tag}"),
        )
        result = reconcile_phase_proposal_action_v3(
            registry=self.registry,
            bank=self.bank,
            action_id=executing.action_id,
            generation_terminal=terminal,
            generated_value=value,
            ingress=ingress,
        )
        return result


@dataclass(frozen=True)
class ArmPlan:
    """Host-declared fake outcome for one probe arm (mechanics only)."""

    terminal: str = "completed"  # completed | algorithm_failure | infrastructure_failure
    v: float = 0.5
    c: float = 25.0
    safe_failure_code: str | None = None
    failed_stage_rank: int | None = None


def benefit_pair() -> tuple[ArmPlan, ArmPlan]:
    return ArmPlan(v=0.5, c=25.0), ArmPlan(v=0.7, c=9.0)


def null_pair() -> tuple[ArmPlan, ArmPlan]:
    return ArmPlan(v=0.5, c=25.0), ArmPlan(v=0.5, c=25.0)


def harm_pair() -> tuple[ArmPlan, ArmPlan]:
    return ArmPlan(v=0.7, c=9.0), ArmPlan(v=0.4, c=30.0)


class V5ProbeMixin:
    """Six-unit probe execution over the shared v5 harness."""

    def seal_plan_for(self, transition):
        return self.bank.seal_probe_plan(
            transition_id=transition.transition_id,
            owner_kind="direct_factor",
            epoch_id=self.authority.epoch_id_for(
                transition_id=transition.transition_id
            ),
            unit_commitments=self.authority.unit_commitments,
            arm_orders=self.authority.arm_orders,
            assignment_manifest_sha256=self.authority.assignment_manifest_sha256,
            runner_version=self.authority.runner_version,
            budget=self.authority.plan_budget,
        )

    def probe_arm_coordinates(self, ordinal: int):
        protocol = self.experiment.protocol
        source = next(
            item
            for item in protocol.authorized_logical_arms
            if item.operation_kind == "source_probe"
            and item.execution_ordinal == ordinal
        )
        target = next(
            item
            for item in protocol.authorized_logical_arms
            if item.operation_kind == "target_probe"
            and item.execution_ordinal == ordinal
        )
        return source, target

    def open_probe_unit(self, plan, *, ordinal: int, tag: str, action_id: str):
        assignment = self.authority.make_assignment(plan, ordinal=ordinal)
        runner_lease = self.authority.make_runner_lease(
            plan=plan,
            assignment=assignment,
            runner_session_id=f"v5-probe-runner:{tag}:{ordinal}",
            runner_lease_token_sha256=self._sha(f"probe-token:{tag}:{ordinal}"),
            journal_anchor_sha256=self._sha(f"probe-journal:{tag}:{ordinal}"),
        )
        attempt = self.bank.open_next_attempt(
            plan.plan_id, assignment, runner_lease
        )
        source_arm, target_arm = self.probe_arm_coordinates(ordinal)
        from masbench.sft_pilot.scientific_runner import (
            reserve_scheduled_execution,
        )

        for arm in (source_arm, target_arm):
            reserve_scheduled_execution(
                self.store,
                schedule=self.experiment.seal.execution_schedule,
                logical_arm=arm,
                logical_execution_key=f"probe-{tag}-{ordinal}-{arm.pair_arm}",
                action_id=action_id,
            )
        self.checkpoint()
        assert (
            self.loaded.snapshot.checkpoint.checkpoint_kind
            == "probe_attempt_open"
        )
        return attempt, source_arm, target_arm

    def _complete_probe_store_execution(
        self, *, arm, key: str, tag: str, recovery_root: str
    ) -> str:
        schedule = self.experiment.seal.execution_schedule
        scheduled_call = schedule.entry_for(arm).calls[0]
        call_key = f"call-{key}"
        self.store.reserve_call(
            operation_id=f"reserve-{call_key}",
            operation_request_sha256=self._sha(f"reserve:{call_key}"),
            call_key=call_key,
            logical_execution_key=key,
            call_slot=0,
            call_request_sha256=scheduled_call.request_envelope_sha256,
            input_tokens_reserved=scheduled_call.input_tokens_reserved,
            output_tokens_reserved=scheduled_call.output_tokens_reserved,
            expected_component_recovery_root_sha256=recovery_root,
        )
        authorization = self.store.start_call(
            call_key,
            operation_id=f"start-{call_key}",
            operation_request_sha256=self._sha(f"start:{call_key}"),
            call_request_sha256=scheduled_call.request_envelope_sha256,
            expected_component_recovery_root_sha256=recovery_root,
        )
        assert authorization.may_invoke_sdk
        self.store.complete_call(
            call_key,
            operation_id=f"complete-{call_key}",
            operation_request_sha256=self._sha(f"complete:{call_key}"),
            call_request_sha256=scheduled_call.request_envelope_sha256,
            output_envelope_sha256=self._sha(f"output:{call_key}"),
            provider_usage_known=True,
            input_tokens_used=20,
            output_tokens_used=5,
        )
        self.store.complete_execution(
            key,
            operation_id=f"complete-{key}",
            operation_request_sha256=self._sha(f"complete:{key}"),
        )
        return call_key

    def execute_probe_unit(
        self,
        *,
        edge,
        plan,
        action_id: str,
        ordinal: int,
        tag: str,
        source: ArmPlan,
        target: ArmPlan,
        physical_order: str | None = None,
    ):
        """Run one unit end-to-end and consume its pair (or settle it)."""

        from exp_graph.mas.factor_bank import DenseOutcome, ExecutionUsage
        from masbench.engine import register_exact_phase_execution_result
        from masbench.sft_pilot.execution_attestation import (
            PilotExecutionAttestor,
            PilotOutcomeScorer,
        )
        from masbench.sft_pilot.pair_adapter import (
            make_phase_v3_factor_arm_receipt,
        )
        from masbench.sft_pilot.pair_consumer import consume_phase_v3_pair_once

        import test_sft_execution_attestation as base

        attempt, source_arm, target_arm = self.open_probe_unit(
            plan, ordinal=ordinal, tag=tag, action_id=action_id
        )
        recovery_root = self.loaded.snapshot.recovery_root_sha256
        unit_tag = f"{tag}-{ordinal}"
        snapshot = base._verified_pair_snapshot(
            self.experiment.root,
            protocol=self.experiment.protocol,
            registry=self.registry,
            edge=edge,
            pair_arm=source_arm,
            tag=unit_tag,
        )
        attestor = PilotExecutionAttestor(
            self.experiment.protocol,
            engine_key=self.experiment.runtime_role_key("exact_phase_engine"),
        )
        scorer = PilotOutcomeScorer(
            self.experiment.protocol,
            scorer_key=self.experiment.runtime_role_key("train_scorer"),
            execution_attestor=attestor,
            scorer_id="sft-v5-train-scorer",
            scorer_version_sha256=self._sha("sft-v5-train-scorer-code"),
        )
        scheduled_order = plan.units[ordinal].arm_order
        observed_order = physical_order or scheduled_order
        if observed_order == "AB":
            seqs = {"source": (1, 2), "target": (3, 4)}
        else:
            seqs = {"target": (1, 2), "source": (3, 4)}
        pair_receipt = self.authority.make_pair_execution(
            plan=plan,
            attempt=attempt,
            source_root_id=self._sha(f"physical:{unit_tag}:source"),
            target_root_id=self._sha(f"physical:{unit_tag}:target"),
            source_started_seq=seqs["source"][0],
            source_finished_seq=seqs["source"][1],
            target_started_seq=seqs["target"][0],
            target_finished_seq=seqs["target"][1],
        )
        usage = ExecutionUsage(
            messages=1,
            model_calls=1,
            input_tokens=20,
            output_tokens=5,
            wall_time_ms=100,
            cost_microusd=400,
        )
        receipts = {}
        for arm_name, arm_coords, arm_plan in (
            ("source", source_arm, source),
            ("target", target_arm, target),
        ):
            key = f"probe-{tag}-{ordinal}-{arm_name}"
            if arm_plan.terminal == "infrastructure_failure":
                # The provider crossing itself completed (usage retained);
                # a downstream runner-infrastructure failure prevented a
                # scoreable execution, so the host records the arm directly
                # with retained cost and no outcome.
                self._complete_probe_store_execution(
                    arm=arm_coords,
                    key=key,
                    tag=unit_tag,
                    recovery_root=recovery_root,
                )
                receipts[arm_name] = self.authority.make_phase_arm_receipt(
                    registry=self.registry,
                    registered=edge,
                    plan=plan,
                    attempt=attempt,
                    arm=arm_name,
                    root_id=(
                        pair_receipt.source_root_id
                        if arm_name == "source"
                        else pair_receipt.target_root_id
                    ),
                    paired_arm_root_id=(
                        pair_receipt.target_root_id
                        if arm_name == "source"
                        else pair_receipt.source_root_id
                    ),
                    pair_execution_receipt=pair_receipt,
                    activation_trace_root=self._sha(
                        f"infra-activation:{unit_tag}:{arm_name}"
                    ),
                    usage=usage,
                    execution_class="infrastructure_failure",
                    outcome=None,
                    safe_failure_code=(
                        arm_plan.safe_failure_code or "provider_timeout"
                    ),
                    failed_stage_rank=None,
                )
                continue
            call_key = self._complete_probe_store_execution(
                arm=arm_coords,
                key=key,
                tag=unit_tag,
                recovery_root=recovery_root,
            )
            capability = register_exact_phase_execution_result(
                protocol=self.experiment.protocol,
                logical_arm=arm_coords,
                registry=self.registry,
                registered_edge=edge,
                store=self.store,
                logical_execution_key=key,
                call_keys=(call_key,),
                journal_snapshot=snapshot,
                engine_key=self.experiment.runtime_role_key(
                    "exact_phase_engine"
                ),
            )
            attestation = attestor.issue(capability)
            metrics = DenseOutcome(
                V=arm_plan.v,
                K=arm_plan.v,
                U=arm_plan.v,
                P=arm_plan.v,
                S=arm_plan.v,
                stage_score=arm_plan.v,
                C=arm_plan.c,
                D=2.0,
            )
            outcome_receipt = scorer.score_train_update(
                attestation,
                metrics,
                terminal_class=(
                    "completed"
                    if arm_plan.terminal == "completed"
                    else "algorithm_failure"
                ),
            )
            receipts[arm_name] = make_phase_v3_factor_arm_receipt(
                authority=self.authority,
                registry=self.registry,
                registered=edge,
                plan=plan,
                attempt=attempt,
                pair_execution_receipt=pair_receipt,
                execution=attestation,
                outcome_receipt=outcome_receipt,
                execution_attestor=attestor,
                scorer=scorer,
                usage=usage,
                safe_failure_code=arm_plan.safe_failure_code,
                failed_stage_rank=arm_plan.failed_stage_rank,
            )
        consumed = consume_phase_v3_pair_once(
            loaded=self.loaded,
            coordinator=self.coordinator,
            attempt_id=attempt.attempt_id,
            source_receipt=receipts["source"],
            target_receipt=receipts["target"],
            pair_execution_receipt=pair_receipt,
            operation_id=f"consume-{unit_tag}",
            operation_request_sha256=self._sha(f"consume:{unit_tag}"),
        )
        self.loaded = consumed.loaded
        return consumed


    def cancel_probe_unit(
        self,
        *,
        plan,
        action_id: str,
        ordinal: int,
        tag: str,
        started_arm_roots: tuple[str, ...] = (),
        safe_failure_code: str = "provider_timeout",
    ):
        """Settle one half-pair by authority-fenced cancellation.

        The second provider crossing may never have started; the store's
        settlement law admits that terminal lease state for a cancelled
        attempt (no-retry makes it permanent).
        """

        from exp_graph.mas.factor_bank_v2 import (
            AttemptCancellationReceiptV3,
            cancellation_event_root_v3,
            runner_schedule_commitment_v1,
        )
        from masbench.sft_pilot.factor_authority import (
            UNSIGNED_ATTESTATION_SHA256,
        )
        from masbench.sft_pilot.schema import canonical_sha256

        attempt, _source_arm, _target_arm = self.open_probe_unit(
            plan, ordinal=ordinal, tag=tag, action_id=action_id
        )
        assignment_sha256 = canonical_sha256(attempt.assignment)
        open_attempt_sha256 = canonical_sha256(attempt)
        unit_tag = f"{tag}-{ordinal}"
        schedule_event_id = f"schedule:{unit_tag}"
        abort_event_id = f"abort:{unit_tag}"
        schedule = runner_schedule_commitment_v1(
            expected_open_attempt_sha256=open_attempt_sha256,
            assignment_receipt_sha256=assignment_sha256,
            plan_id=plan.plan_id,
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
            started_arm_roots=started_arm_roots,
            abort_event_id=abort_event_id,
            abort_event_seq=1 + len(started_arm_roots),
            cancel_kind="infrastructure",
            safe_failure_code=safe_failure_code,
            terminate_scope=False,
            runner_lease_token_sha256=(
                attempt.runner_lease.runner_lease_token_sha256
            ),
            fencing_generation=1,
            next_fencing_generation=2,
        )
        unsigned = AttemptCancellationReceiptV3(
            cancellation_id=(
                "ac:"
                + canonical_sha256(
                    {
                        "attempt": open_attempt_sha256,
                        "runner_lease": attempt.runner_lease.digest,
                        "terminal_event_root": event_root,
                    }
                )[:24]
            ),
            attempt_id=attempt.attempt_id,
            plan_id=plan.plan_id,
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
            abort_event_seq=1 + len(started_arm_roots),
            runner_event_root_sha256=event_root,
            cancel_kind="infrastructure",
            safe_failure_code=safe_failure_code,
            terminate_scope=False,
            started_arm_roots=started_arm_roots,
            verifier_epoch=self.authority.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
        )
        cancellation = self.authority.attest_cancellation(
            unsigned, attempt=attempt, plan=plan
        )
        cancelled = self.bank.cancel_open_attempt(
            attempt.attempt_id, cancellation
        )
        self.checkpoint()
        assert (
            self.loaded.snapshot.checkpoint.checkpoint_kind == "probe_terminal"
        )
        return cancelled


class V5ProbeHarness(V5ProbeMixin, V5Harness):
    """Harness with the probe-unit execution surface enabled."""


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
