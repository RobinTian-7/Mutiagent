"""Author, seal, and provision one REAL v5 experiment over Silo n-agent cases.

This is the production counterpart of the test fixture author
(``masbench/tests/sft_v5_fixtures.py``): same closed schemas, same seal graph,
same provisioning entry — but every dataset commitment derives from real
Silo-Bench case bytes instead of synthetic hashes, and the schedule's token
reservations are sized for whole-arm aggregate metering (one store call
receipt per probe/FINAL_VAL arm covering a full multi-agent program run; a
completed call receipt fails closed when real usage exceeds its reservation,
so reservations here are deliberate upper bounds, not estimates).

Case commitment law (author-defined, frozen here): ``input_commitment_sha256``
is the SHA-256 of the raw benchmark JSON file bytes
(``{case_id}_n{n_agents}.json``), so any external auditor can re-derive every
case commitment from the pinned dataset directory without trusting this
module.  ``unit_commitment`` is ``unit-{case_id}`` (one evaluation unit per
case in this pilot).  One experiment is structurally one sealed transition:
1 generation + 6 probe pairs + 2 FINAL_VAL arms; scale comes from authoring
several independent replicate experiments.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.phase_artifact_registry import PHASE_FULL_FACTOR_BINDER_VERSION
from exp_graph.mas.phase_program import PHASE_PROGRAM_COMPILER_VERSION

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
from masbench.sft_pilot.result_ledger import PilotTestManifestV1
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
from masbench.sft_pilot.store import (
    component_genesis_sha256_from_envelope_digests,
)
from masbench.sft_pilot.structural_anchor import (
    StructuralAnchorPlanV1,
    StructuralAnchorRuntimeV1,
    build_structural_anchor_v1,
)


REAL_RUNTIME_VERSION = "sft-v5-real-runtime-v1"
PROBE_CASE_COUNT = 6
FINAL_VAL_CASE_COUNT = 2

# Whole-arm aggregate reservations (upper bounds, not estimates): one probe or
# FINAL_VAL "call" receipt covers an entire n-agent program run including the
# runner's bounded JSON-retry calls. gpt-4o-mini n=5 runs observed in bringup
# use well under a tenth of these; a completed receipt fails closed above them.
PROBE_INPUT_TOKENS_RESERVED = 400_000
# Reasoning-effort workers count hidden reasoning inside completion
# usage, so the whole-arm output bound is far above visible text.
PROBE_OUTPUT_TOKENS_RESERVED = 250_000
GENERATION_INPUT_TOKENS_RESERVED = 4_096
# Reasoning models spend hidden reasoning tokens inside the completion
# cap, so the sealed generation call reserves far above the visible JSON.
GENERATION_OUTPUT_TOKENS_RESERVED = 8_192

# The factor authority derives the per-arm plan budget by dividing the PROBE
# phase budget by its twelve executions (max_model_calls = call_slots // 12,
# max_wall_time_ms = 60s x that).  A real whole arm makes dozens of internal
# provider calls, so the phase call-slot pool must authorize the true per-arm
# ceiling even though the schedule still records ONE aggregate store call per
# arm (schedule call sums are bounded by, not equal to, the phase pool).
PROBE_MODEL_CALLS_PER_ARM = 64


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def case_file_path(benchmarks_dir: Path, case_id: str, n_agents: int) -> Path:
    return Path(benchmarks_dir) / f"{case_id}_n{n_agents}.json"


def case_input_commitment(
    benchmarks_dir: Path, case_id: str, n_agents: int
) -> str:
    """SHA-256 of the raw benchmark file bytes — externally re-derivable."""

    payload = case_file_path(benchmarks_dir, case_id, n_agents).read_bytes()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RealExperimentSpec:
    """Frozen author inputs for one real replicate experiment."""

    experiment_id: str
    root: Path
    benchmarks_dir: Path
    fixed_git_commit: str
    master_key: bytes
    n_agents: int
    probe_case_ids: tuple[str, ...]
    generation_case_id: str
    final_val_case_ids: tuple[str, ...]
    test_case_ids: tuple[str, ...]
    information_goal: str = "sink"
    base_structure: str = "gather_broadcast"
    source_value_override: int | str | None = None
    target_value_override: int | str | None = None
    model_name: str = "gpt-4o-mini"
    reasoning_effort: str | None = None
    # Which scientific channel this experiment's one transition uses.  Frozen
    # at authoring: the generation schedule entry, the plan owner kind, and
    # the probe/attestation path all follow it.
    search_layer: str = "direct_factor"
    # Anchorize (S4): anchor this round at a gate-accepted whole composition
    # (a validated PhaseProgram JSON dump) instead of the hand base program.
    source_program_override: dict | None = None

    def __post_init__(self) -> None:
        if self.search_layer not in {"direct_factor", "whole_composition"}:
            raise ValueError("search_layer must be direct_factor or whole_composition")
        if len(self.probe_case_ids) != PROBE_CASE_COUNT:
            raise ValueError(
                f"exactly {PROBE_CASE_COUNT} probe cases are required"
            )
        if len(self.final_val_case_ids) != FINAL_VAL_CASE_COUNT:
            raise ValueError(
                f"exactly {FINAL_VAL_CASE_COUNT} FINAL_VAL cases are required"
            )
        train_side = set(self.probe_case_ids) | {self.generation_case_id}
        overlap = (
            (train_side & set(self.final_val_case_ids))
            | (train_side & set(self.test_case_ids))
            | (set(self.final_val_case_ids) & set(self.test_case_ids))
        )
        if overlap:
            raise ValueError(f"case splits must be disjoint; overlap: {overlap}")
        if not self.test_case_ids:
            raise ValueError("at least one TEST case is required")


@dataclass(frozen=True)
class RealV5Experiment:
    """One fully authored, sealed, and provisioned real experiment."""

    spec: RealExperimentSpec
    state_dir: Path
    anchor_dir: Path
    result_dir: Path
    seal: PilotExperimentSealV1
    seal_path: Path
    protocol: PilotProtocolV1
    protocol_path: Path
    runtime_authority: PilotRuntimeAuthorityManifestV1
    runtime_authority_path: Path
    bootstrap_authority: PilotBootstrapAuthorityManifestV1
    bootstrap_authority_path: Path
    anchor_runtime: StructuralAnchorRuntimeV1
    provision_receipt: PilotExperimentProvisionReceipt
    component_keys: dict[str, bytes]
    test_manifest: PilotTestManifestV1

    def runtime_role_key(self, role: str) -> bytes:
        return derive_v5_runtime_role_key(self.spec.master_key, role)


def _namespace(spec: RealExperimentSpec) -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="silo_bench",
        objective="balanced",
        information_goal=spec.information_goal,
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=spec.n_agents,
        array_size_bucket=f"silo_n{spec.n_agents}",
        budget_level="normal",
        model_name=spec.model_name,
        runtime_version=REAL_RUNTIME_VERSION,
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _case_manifest(spec: RealExperimentSpec) -> PilotCaseManifestV1:
    entries = []
    for case_id in spec.probe_case_ids + (spec.generation_case_id,):
        entries.append(
            PilotCaseEntryV1(
                case_id=case_id,
                split="TRAIN_UPDATE",
                unit_commitment=f"unit-{case_id}",
                input_commitment_sha256=case_input_commitment(
                    spec.benchmarks_dir, case_id, spec.n_agents
                ),
            )
        )
    for case_id in spec.final_val_case_ids:
        entries.append(
            PilotCaseEntryV1(
                case_id=case_id,
                split="FINAL_VAL",
                unit_commitment=f"unit-{case_id}",
                input_commitment_sha256=case_input_commitment(
                    spec.benchmarks_dir, case_id, spec.n_agents
                ),
            )
        )
    return PilotCaseManifestV1(
        cases=tuple(sorted(entries, key=lambda item: item.case_id))
    )


def _pair_manifest(
    spec: RealExperimentSpec, cases: PilotCaseManifestV1
) -> PilotPairManifestV1:
    by_id = {item.case_id: item for item in cases.cases}
    probe_orders = ("AB", "BA", "AB", "BA", "AB", "BA")
    pairs = []
    for index, case_id in enumerate(spec.probe_case_ids):
        case = by_id[case_id]
        pairs.append(
            PilotPairEntryV1(
                pair_id=f"pair-probe-{index}",
                case_id=case.case_id,
                unit_commitment=case.unit_commitment,
                case_commitment_sha256=case.input_commitment_sha256,
                arm_order=probe_orders[index],
                execution_ordinal=index,
            )
        )
    gen_case = by_id[spec.generation_case_id]
    pairs.append(
        PilotPairEntryV1(
            pair_id="pair-generation",
            case_id=gen_case.case_id,
            unit_commitment=gen_case.unit_commitment,
            case_commitment_sha256=gen_case.input_commitment_sha256,
            arm_order="BA",
            execution_ordinal=PROBE_CASE_COUNT,
        )
    )
    for offset, case_id in enumerate(spec.final_val_case_ids):
        case = by_id[case_id]
        pairs.append(
            PilotPairEntryV1(
                pair_id=f"pair-final-val-{offset}",
                case_id=case.case_id,
                unit_commitment=case.unit_commitment,
                case_commitment_sha256=case.input_commitment_sha256,
                arm_order="AB" if offset == 0 else "BA",
                execution_ordinal=PROBE_CASE_COUNT + 1 + offset,
            )
        )
    return PilotPairManifestV1(pairs=tuple(pairs))


def _candidate_manifest(spec: RealExperimentSpec) -> PilotCandidateManifestV1:
    # The mutate branch generates a fresh scalar, so the frozen candidate
    # universe only needs stable identity commitments for the slate law.
    identities = sorted(
        (
            _h(f"{spec.experiment_id}-cell-{index}"),
            _h(f"{spec.experiment_id}-target-key-{index}"),
            _h(f"{spec.experiment_id}-target-{index}"),
        )
        for index in range(3)
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


def _runner_manifest(spec: RealExperimentSpec) -> PilotRunnerManifestV1:
    sources = tuple(
        PilotCodeSourceV1(source_id=source_id, sha256=stable_file_sha256(path))
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
        fixed_git_commit=spec.fixed_git_commit,
        exact_artifact_runner_version="sft-v5-real-exact-runner-v1",
        runtime_version=REAL_RUNTIME_VERSION,
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
    gen = by_id["pair-generation"]
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
    for index in range(PROBE_CASE_COUNT):
        pair = by_id[f"pair-probe-{index}"]
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
    for offset in range(FINAL_VAL_CASE_COUNT):
        pair = by_id[f"pair-final-val-{offset}"]
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

# Legacy single-base constants; the authored locus/type now come from the
# plan's base_structure law (structural_anchor._ANCHOR_BASE_LOCI).
ANCHOR_LOCATOR = "/phases/1/hub"
ANCHOR_SCALAR_TYPE = "int"


def _phase_budgets(method_arm: str) -> tuple[AuthorizedPhaseBudgetV1, ...]:
    return (
        AuthorizedPhaseBudgetV1(
            phase="TRAIN_UPDATE",
            method_arm=method_arm,
            executions=1,
            call_slots=1,
            input_tokens=GENERATION_INPUT_TOKENS_RESERVED,
            output_tokens=GENERATION_OUTPUT_TOKENS_RESERVED,
        ),
        AuthorizedPhaseBudgetV1(
            phase="PROBE",
            method_arm=method_arm,
            executions=12,
            call_slots=12 * PROBE_MODEL_CALLS_PER_ARM,
            input_tokens=12 * PROBE_INPUT_TOKENS_RESERVED,
            output_tokens=12 * PROBE_OUTPUT_TOKENS_RESERVED,
        ),
        AuthorizedPhaseBudgetV1(
            phase="FINAL_VAL",
            method_arm=method_arm,
            executions=2,
            call_slots=2,
            input_tokens=2 * PROBE_INPUT_TOKENS_RESERVED,
            output_tokens=2 * PROBE_OUTPUT_TOKENS_RESERVED,
        ),
    )


def _generation_envelope(
    locator_path: str = ANCHOR_LOCATOR,
    scalar_type: str = ANCHOR_SCALAR_TYPE,
    *,
    search_layer: str = "direct_factor",
) -> tuple[str, str, str]:
    from masbench.sft_pilot.factor_authority import derive_generation_budget
    from masbench.sft_pilot.request_renderer import (
        GENERATION_POLICY_SHA256,
        PROMPT_TEMPLATE_SHA256,
        RENDERER_POLICY_SHA256,
        SCALAR_OUTPUT_SCHEMA_SHA256,
        generation_request_envelope_sha256,
    )

    budget = derive_generation_budget(_phase_budgets("sft_unified")[0])
    if search_layer == "whole_composition":
        from masbench.sft_pilot.structural_generation import (
            STRUCTURAL_OUTPUT_SCHEMA_SHA256,
            STRUCTURAL_PROMPT_TEMPLATE_SHA256,
        )

        return (
            generation_request_envelope_sha256(
                locator_path="/phases",
                scalar_type="string",
                generation_policy_sha256=GENERATION_POLICY_SHA256,
                prompt_template_sha256=STRUCTURAL_PROMPT_TEMPLATE_SHA256,
                scalar_output_schema_sha256=STRUCTURAL_OUTPUT_SCHEMA_SHA256,
                budget_sha256=budget.digest,
            ),
            RENDERER_POLICY_SHA256,
            STRUCTURAL_PROMPT_TEMPLATE_SHA256,
        )
    return (
        generation_request_envelope_sha256(
            locator_path=locator_path,
            scalar_type=scalar_type,
            generation_policy_sha256=GENERATION_POLICY_SHA256,
            prompt_template_sha256=PROMPT_TEMPLATE_SHA256,
            scalar_output_schema_sha256=SCALAR_OUTPUT_SCHEMA_SHA256,
            budget_sha256=budget.digest,
        ),
        RENDERER_POLICY_SHA256,
        PROMPT_TEMPLATE_SHA256,
    )


def _execution_schedule(
    spec: RealExperimentSpec,
    arms: tuple[PilotLogicalArmCoordinatesV1, ...],
    *,
    locator_path: str,
    scalar_type: str,
) -> PilotExecutionScheduleV1:
    generation_envelope, renderer_policy, template_sha = _generation_envelope(
        locator_path, scalar_type, search_layer=spec.search_layer
    )
    entries = []
    for index, arm in enumerate(arms):
        if arm.operation_kind == "proposal_generation":
            envelope = generation_envelope
            renderer_sha = renderer_policy
            template = template_sha
            input_reserved = GENERATION_INPUT_TOKENS_RESERVED
            output_reserved = GENERATION_OUTPUT_TOKENS_RESERVED
        else:
            # Whole-arm aggregate call: the envelope commits to the exact arm
            # coordinates; the renderer/template commitments name the shared
            # whole-program runner rather than a prompt template (the arm's
            # prompts are produced case-side by the protocol runner).
            envelope = canonical_sha256(
                {
                    "domain": "sft-v5-real-whole-arm-request-v1",
                    "experiment_id": spec.experiment_id,
                    "pair_id": arm.pair_id,
                    "pair_arm": arm.pair_arm,
                    "operation_kind": arm.operation_kind,
                    "case_commitment_sha256": arm.case_commitment_sha256,
                }
            )
            renderer_sha = _h("sft-v5-real-whole-arm-runner")
            template = _h(f"sft-v5-real-whole-arm-{arm.operation_kind}")
            input_reserved = PROBE_INPUT_TOKENS_RESERVED
            output_reserved = PROBE_OUTPUT_TOKENS_RESERVED
        entries.append(
            PilotExecutionScheduleEntryV1(
                logical_arm=arm,
                physical_block_ordinal=index,
                calls=(
                    PilotCallScheduleEntryV1(
                        call_slot=0,
                        input_tokens_reserved=input_reserved,
                        output_tokens_reserved=output_reserved,
                        request_envelope_sha256=envelope,
                        request_renderer_sha256=renderer_sha,
                        prompt_template_sha256=template,
                        json_mode=True,
                        artifact_role=_ARM_ROLE[arm.operation_kind],
                    ),
                ),
            )
        )
    return PilotExecutionScheduleV1(entries=tuple(entries))


def _capacity_policy() -> PilotCapacityPolicyV1:
    return PilotCapacityPolicyV1(
        max_scientific_commits=64,
        max_execution_leases=32,
        max_call_receipts=64,
        max_component_checkpoints=64,
        max_call_slots_per_execution=1,
        max_input_tokens_per_call=PROBE_INPUT_TOKENS_RESERVED,
        max_output_tokens_per_call=PROBE_OUTPUT_TOKENS_RESERVED,
        max_active_db_bytes=256 * 1024 * 1024,
        max_archive_bytes=4 * 1024 * 1024,
        max_total_stored_scalar_bytes=32 * 1024 * 1024,
    )


def _protocol(
    *,
    spec: RealExperimentSpec,
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
        model_name=spec.model_name,
        namespace=namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=cases.digest,
            source_policy_sha256=_h(f"{spec.experiment_id}-source-policy"),
        ),
        source_authority_sha256=anchor_source_authority_sha256,
        dataset_split_policy_sha256=_h(f"{spec.experiment_id}-split-policy"),
        candidate_pool_manifest_sha256=candidates.digest,
        runner_config_sha256=runner.digest,
        model_config_sha256=_h(f"{spec.experiment_id}-model-config"),
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


def author_real_v5_experiment(spec: RealExperimentSpec) -> RealV5Experiment:
    """Author, seal, and provision one real replicate experiment.

    Zero model calls by construction (authoring + provisioning are
    execution-free); the returned object carries every frozen path the
    runner needs.
    """

    root = Path(spec.root)
    state_dir = (root / "state").resolve()
    anchor_dir = state_dir / ANCHOR_DIRNAME
    result_dir = (root / "results").resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    runtime_authority_root = (root / "runtime-authority-root").resolve()
    runtime_authority_root.mkdir(parents=True, exist_ok=True)

    keys = derive_v5_component_keys(spec.master_key)
    namespace = _namespace(spec)
    cases = _case_manifest(spec)
    plan = StructuralAnchorPlanV1(
        namespace=namespace,
        source_catalog_sha256=cases.digest,
        source_policy_sha256=_h(f"{spec.experiment_id}-source-policy"),
        base_structure=spec.base_structure,
        source_value_override=spec.source_value_override,
        target_value_override=spec.target_value_override,
        source_program_override=spec.source_program_override,
    )
    anchor_runtime = build_structural_anchor_v1(
        anchor_dir,
        plan=plan,
        source_authority_key=keys["source_authority"],
        phase_registry_key=keys["phase_registry"],
        factor_bank_key=keys["factor_bank"],
    )
    anchor = anchor_runtime.bundle

    pairs = _pair_manifest(spec, cases)
    candidates = _candidate_manifest(spec)
    runner = _runner_manifest(spec)
    arms = _logical_arms(pairs)
    schedule = _execution_schedule(
        spec,
        arms,
        locator_path=plan.anchor_locus,
        scalar_type=plan.anchor_scalar_type,
    )

    genesis = component_genesis_sha256_from_envelope_digests(
        phase_registry_envelope_sha256=anchor.phase_registry_envelope_sha256,
        factor_bank_envelope_sha256=anchor.factor_bank_envelope_sha256,
    )
    protocol = _protocol(
        spec=spec,
        protocol_id=f"{spec.experiment_id}-sft-unified",
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
        spec=spec,
        protocol_id=f"{spec.experiment_id}-ect-control",
        method_arm="ect_whole_transaction",
        genesis_state_sha256=_h(f"{spec.experiment_id}-ect-genesis"),
        namespace=namespace,
        anchor_source_authority_sha256=anchor.source_authority_sha256,
        cases=cases,
        pairs=pairs,
        candidates=candidates,
        runner=runner,
        schedule=schedule,
        arms=arms,
    )

    test_manifest = PilotTestManifestV1(
        test_id=f"{spec.experiment_id}-frozen-test",
        experiment_id=spec.experiment_id,
        case_commitments=tuple(
            sorted(
                case_input_commitment(
                    spec.benchmarks_dir, case_id, spec.n_agents
                )
                for case_id in spec.test_case_ids
            )
        ),
        scoring_policy_sha256=_h(
            "sft-v5-real-test-scoring:deployed-program-official-dense-v1"
        ),
    )

    method_arms = ("sft_unified", "ect_whole_transaction")
    experiment = PilotExperimentManifestV1(
        experiment_id=spec.experiment_id,
        case_manifest_sha256=cases.digest,
        pair_manifest_sha256=pairs.digest,
        candidate_manifest_sha256=candidates.digest,
        runner_manifest_sha256=runner.digest,
        model_config_sha256=_h(f"{spec.experiment_id}-model-config"),
        execution_schedule_sha256=schedule.digest,
        arms=(
            PilotExperimentArmV1(
                method_arm="sft_unified",
                child_protocol_sha256=protocol.digest,
                implementation_sha256=_h(f"{spec.experiment_id}-impl-sft"),
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
                implementation_sha256=_h(f"{spec.experiment_id}-impl-ect"),
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
                    method_arms
                    if index % 2 == 0
                    else tuple(reversed(method_arms))
                ),
            )
            for index, pair in enumerate(pairs.pairs)
        ),
    )

    # Dataset commitments derive from the same real case rows the manifests
    # freeze, so an auditor can re-derive them from the benchmark directory.
    dataset_release_rows = tuple(
        {
            "case_id": item.case_id,
            "unit_commitment": item.unit_commitment,
            "input_commitment_sha256": item.input_commitment_sha256,
        }
        for item in cases.cases
    )
    dataset_split_rows = tuple(
        {"case_id": item.case_id, "split": item.split} for item in cases.cases
    )
    bootstrap_authority = PilotBootstrapAuthorityManifestV1(
        authority_kind="host_pinned",
        bootstrap_id=f"{spec.experiment_id}-bootstrap",
        fixed_git_commit=spec.fixed_git_commit,
        dataset_release_manifest_sha256=canonical_sha256(
            {
                "domain": "sft-v5-real-dataset-release-v1",
                "benchmarks_dirname": Path(spec.benchmarks_dir).name,
                "n_agents": spec.n_agents,
                "rows": dataset_release_rows,
            }
        ),
        dataset_split_manifest_sha256=canonical_sha256(
            {
                "domain": "sft-v5-real-dataset-split-v1",
                "rows": dataset_split_rows,
            }
        ),
        train_loader_policy_sha256=_h(f"{spec.experiment_id}-source-policy"),
        namespace_template_sha256=canonical_sha256(namespace),
        anchor_freeze_dir_commitment_sha256=authority_root_commitment(
            anchor_dir
        ),
        authority_code_sources=tuple(
            PilotCodeSourceV1(
                source_id=source_id,
                sha256=stable_file_sha256(path),
            )
            for source_id, path in sorted(
                bootstrap_code_source_paths().items()
            )
        ),
        authority_key_commitments=tuple(
            PilotAuthorityKeyCommitmentV1(
                role=role,
                key_commitment_sha256=authority_key_commitment(
                    role=role,
                    key=derive_v5_bootstrap_role_key(spec.master_key, role),
                ),
            )
            for role in AUTHORITY_KEY_ROLES
        ),
    )

    runtime_authority = PilotRuntimeAuthorityManifestV1(
        authority_kind="host_pinned",
        runtime_authority_id=f"{spec.experiment_id}-runtime-authority",
        fixed_git_commit=spec.fixed_git_commit,
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
                    key=derive_v5_runtime_role_key(spec.master_key, role),
                ),
            )
            for role in RUNTIME_AUTHORITY_ROLES
        ),
    )

    seal = PilotExperimentSealV1(
        experiment_id=spec.experiment_id,
        fixed_git_commit=spec.fixed_git_commit,
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
        test_manifest_sha256=test_manifest.digest,
        report_manifest_sha256=_h(
            f"{spec.experiment_id}-report-manifest-commitment"
        ),
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
    test_manifest_path = (root / "test-manifest.json").resolve()
    test_manifest_path.write_text(
        canonical_json(test_manifest), encoding="utf-8"
    )

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

    return RealV5Experiment(
        spec=spec,
        state_dir=state_dir,
        anchor_dir=anchor_dir,
        result_dir=result_dir,
        seal=seal,
        seal_path=seal_path,
        protocol=protocol,
        protocol_path=protocol_path,
        runtime_authority=runtime_authority,
        runtime_authority_path=runtime_authority_path,
        bootstrap_authority=bootstrap_authority,
        bootstrap_authority_path=bootstrap_authority_path,
        anchor_runtime=anchor_runtime,
        provision_receipt=receipt,
        component_keys=keys,
        test_manifest=test_manifest,
    )


__all__ = [
    "ANCHOR_LOCATOR",
    "ANCHOR_SCALAR_TYPE",
    "FINAL_VAL_CASE_COUNT",
    "GENERATION_INPUT_TOKENS_RESERVED",
    "GENERATION_OUTPUT_TOKENS_RESERVED",
    "PROBE_CASE_COUNT",
    "PROBE_INPUT_TOKENS_RESERVED",
    "PROBE_OUTPUT_TOKENS_RESERVED",
    "REAL_RUNTIME_VERSION",
    "RealExperimentSpec",
    "RealV5Experiment",
    "author_real_v5_experiment",
    "case_file_path",
    "case_input_commitment",
]
