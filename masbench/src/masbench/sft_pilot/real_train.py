"""Real TRAIN → FINAL_VAL → TEST driver for one sealed v5 replicate.

This module is the Stage-12 arming layer: it replaces the fixture harness's
planted outcomes with REAL whole-program executions (``real_runner``) while
keeping every trust boundary production-shaped — real derived journal keys, a
linearizable in-process checkpoint provider, store call receipts carrying the
provider-authoritative token sums, engine attestation over a genuinely
persisted pair journal, and the native FactorBank reducers untouched.

Honesty laws implemented here:

- One probe arm = one whole ProtocolRunner run, metered as ONE aggregate store
  call receipt (see ``docs/sft_phase_v5/plan_deviations.md`` §8) whose token
  counts are the runner's provider-authoritative sums.  The driver asserts the
  arm-receipt ``ExecutionUsage`` equals those store sums — three views of one
  run may never diverge.
- Both arms of a unit run on the same case and seed, in the sealed AB/BA
  physical order, bracketed by a real ``SFTRunnerJournal`` pair journal.
- A raising arm run is never retried: the store call is marked indeterminate,
  the journal attempt is cancelled, and the Bank settles the half pair through
  the authority-fenced cancellation path.  No partial-pair evidence survives.
- FINAL_VAL runs candidate and incumbent on the same frozen cases and seeds,
  read-only; TEST evaluates only the deployed head and must leave every
  scientific root byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from exp_graph.mas.factor_bank import DenseOutcome, ExecutionUsage
from exp_graph.mas.factor_bank_v2 import (
    AttemptCancellationReceiptV3,
    FailureObservationV2,
    ProposalCursorV1,
    ProposalRequestV1,
    SFTProposalInputV1,
    cancellation_event_root_v3,
    proposal_counter_state_sha256,
    runner_schedule_commitment_v1,
)
from exp_graph.mas.phase_artifact_registry import (
    PhaseGenerationTerminalV1,
    phase_generated_scalar_sha256,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    register_phase_materialization_v3,
    reconcile_phase_proposal_action_v3,
)
from exp_graph.mas.phase_program import PhaseProgram
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
from exp_graph.mas.sft_proposal import (
    ExactFactorLocusV1,
    ExactProposalCellV1,
    select_exact_edge_proposal,
)

from masbench.engine import (
    exact_phase_arm_commitment_v1,
    register_exact_phase_execution_result,
    register_exact_phase_whole_execution_result,
)
from masbench.sft_phase_pilot import _derive_key
from masbench.sft_pilot.components import PilotComponentCoordinator
from masbench.sft_pilot.execution_attestation import (
    PilotExecutionAttestor,
    PilotOutcomeScorer,
)
from masbench.sft_pilot.factor_authority import SFTPilotFactorAuthority
from masbench.sft_pilot.final_val import (
    FinalValCaseSample,
    run_final_val_gate,
)
from masbench.sft_pilot.llm_meter import (
    FakeDeterministicPilotTransport,
    OpenAIPilotTransport,
)
from masbench.sft_pilot.pair_adapter import (
    make_phase_v3_factor_arm_receipt,
    make_phase_whole_arm_receipt,
)
from exp_graph.mas.phase_structural_ops import (
    PhaseStructuralOperationProofV1,
    RegisteredPhaseWholeCompositionEdgeV1,
    StructuralNoOpError,
    prove_structural_operation,
    register_phase_whole_materialization_v1,
)
from masbench.sft_pilot.structural_generation import (
    frozen_structural_domain,
    parse_generated_operation,
    render_structural_generation_request,
    validate_structural_bounds,
)
from masbench.sft_pilot.pair_consumer import consume_phase_v3_pair_once
from masbench.sft_pilot.real_eval import (
    CaseEvalRow,
    aggregate_eval_rows,
    evaluate_program_on_cases,
)
from masbench.sft_pilot.real_experiment import (
    GENERATION_OUTPUT_TOKENS_RESERVED,
    RealV5Experiment,
)
from masbench.sft_pilot.real_runner import ArmRunResult, run_phase_program_arm
from masbench.sft_pilot.request_renderer import (
    GENERATION_POLICY_SHA256,
    PROMPT_TEMPLATE_SHA256,
    SCALAR_OUTPUT_SCHEMA_SHA256,
    SafeSourceScalar,
    parse_generated_scalar,
    render_generation_request,
)
from masbench.sft_pilot.result_ledger import PilotResultLedger
from masbench.sft_pilot.schema import canonical_sha256
from masbench.sft_pilot.scientific_runner import (
    V5BranchReceiptAuthority,
    execute_metered_generation_call,
    reserve_scheduled_execution,
    run_frozen_test_readonly,
    skip_settled_probe_blocks,
    v5_factor_capabilities_factory,
)
from masbench.sft_pilot.store import SingleWriterPilotStore


PROBE_SEED_BASE = 100
FINAL_VAL_SEED_BASE = 500
TEST_SEED_BASE = 1_000

_JOURNAL_KEY_DOMAIN = b"journal-v5"
_READER_KEY_DOMAIN = b"journal-reader-v5"
_MANIFEST_KEY_DOMAIN = b"journal-manifest-v5"


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host_id(prefix: str, label: str) -> str:
    return f"{prefix}:{_sha(label)[:24]}"


class _LinearizableCheckpointProvider:
    """In-process linearizable CAS checkpoint authority for one journal.

    The single-process pilot host IS the external authority here: the CAS is
    guarded by one lock, a pending claim blocks further mutation until the
    runner acknowledges, and the epoch commitment is pinned in the snapshot
    trust policy so a swapped provider fails verification.
    """

    def __init__(self, *, provider_epoch_sha256: str) -> None:
        self._lock = threading.Lock()
        self.provider_epoch_sha256 = provider_epoch_sha256
        self.latest: JournalCheckpointV2 | None = None
        self.pending: CheckpointUpdateClaimV2 | None = None

    def bootstrap(self, checkpoint: JournalCheckpointV2) -> None:
        with self._lock:
            if self.latest is not None:
                raise RuntimeError("checkpoint provider already bootstrapped")
            self.latest = checkpoint

    def inspect(self, journal_id: str) -> CheckpointProviderSnapshotV2:
        with self._lock:
            return CheckpointProviderSnapshotV2(
                journal_id=journal_id,
                provider_epoch_sha256=self.provider_epoch_sha256,
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
                provider_epoch_sha256=self.provider_epoch_sha256,
            )
            return self.pending

    def acknowledge(self, checkpoint: JournalCheckpointV2) -> None:
        with self._lock:
            if self.pending is None or (
                self.pending.proposed_checkpoint != checkpoint
            ):
                raise RuntimeError("acknowledge does not match the pending claim")
            self.latest = checkpoint
            self.pending = None


class _ExactScopeVerifier:
    def __init__(self, expected: JournalScopeV2) -> None:
        self._expected = expected

    def __call__(self, candidate: JournalScopeV2) -> bool:
        return candidate == self._expected


class _JournalTrustHost:
    """Real-key journal trust anchors for one probe unit's pair journal."""

    def __init__(
        self,
        *,
        master: bytes,
        path: Path,
        locator_id: str,
        journal_id: str,
        manifest_sha256: str,
        provider_epoch_sha256: str,
        manifest_epoch_sha256: str,
        reader_policy_sha256: str,
    ) -> None:
        import hashlib

        self.journal_key = _derive_key(master, _JOURNAL_KEY_DOMAIN)
        self.reader_key = _derive_key(master, _READER_KEY_DOMAIN)
        self.manifest_key = _derive_key(master, _MANIFEST_KEY_DOMAIN)
        self.path = path.resolve()
        self.locator_id = locator_id
        self.journal_id = journal_id
        self.manifest_sha256 = manifest_sha256
        self.manifest_epoch_sha256 = manifest_epoch_sha256
        self._reader_policy_sha256 = reader_policy_sha256
        self._manifest_key_sha256 = hashlib.sha256(self.manifest_key).hexdigest()
        self.locator_sha256 = journal_locator_commitment_v1(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
            resolved_path=self.path,
        )
        del provider_epoch_sha256  # pinned in the trust policy by the caller

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
        return self.journal_key

    def resolve_reader_hmac_key(self, **kwargs: str) -> bytes:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return self.reader_key

    def pinned_journal_key_commitment_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return journal_key_commitment_v1(role="journal", key=self.journal_key)

    def pinned_reader_key_commitment_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return journal_key_commitment_v1(role="reader", key=self.reader_key)

    def reader_policy_sha256(self, **kwargs: str) -> str:
        self._check(kwargs["journal_locator_id"], kwargs["expected_journal_id"])
        return self._reader_policy_sha256

    def verifier_policy_sha256(self) -> str:
        return journal_canonical_sha256_v2(
            {
                "domain": "sft-v5-real-manifest-verifier-v1",
                "epoch": self.manifest_epoch_sha256,
                "key_sha256": self._manifest_key_sha256,
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
            "verifier_epoch_sha256": self.manifest_epoch_sha256,
        }
        return ScopeManifestVerificationV1(
            **body,
            verifier_attestation_sha256=journal_fixed_hmac_sha256_v2(
                self.manifest_key,
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
        import hmac as _hmac

        expected = journal_fixed_hmac_sha256_v2(
            self.manifest_key,
            domain="sft-scope-manifest-verification-v1",
            value=verification.model_dump(
                mode="python", exclude={"verifier_attestation_sha256"}
            ),
        )
        if not (
            verification.manifest_sha256 == self.manifest_sha256
            and verification.scope_sha256 == scope.digest
            and _hmac.compare_digest(
                verification.verifier_attestation_sha256, expected
            )
        ):
            raise ValueError("scope manifest verification failed")


@dataclass
class ProbeUnitOutcome:
    """Safe per-unit record for the external replicate report."""

    ordinal: int
    case_id: str
    seed: int
    arm_order: str
    status: str  # consumed | cancelled
    source: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    cancel_reason: str | None = None


def _arm_report(result: ArmRunResult) -> dict[str, Any]:
    dense = result.dense_outcome
    return {
        "execution_class": result.execution_class,
        "success": result.success,
        "partial": result.partial,
        "V": dense.V,
        "K": dense.K,
        "U": dense.U,
        "P": dense.P,
        "S": dense.S,
        "stage_score": dense.stage_score,
        "C": dense.C,
        "D": dense.D,
        "model_calls": result.model_calls,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "messages": result.messages,
    }



_PATTERN_DOMAINS = {
    "consensus": ("all_to_all", "rotating", "exponential"),
    "pairwise_exchange": ("ring", "bidirectional_ring", "rotating", "exponential"),
    "gather": ("star", "tree"),
    "broadcast": ("star", "tree"),
}


def anchor_generation_surface(plan: Any, n_agents: int) -> tuple[Any, str]:
    """Per-base (source scalar value, legal-domain description) for mutate.

    The description states the closed legal domain MINUS already-registered
    content (source + host anchor target) — Bank-structural facts only, so a
    generated duplicate cannot silently no-op the sealed single action.
    """

    payload = plan.source_program.model_dump(mode="python")
    phase_index = int(plan.anchor_locus.split("/")[2])
    phase = payload["phases"][phase_index]
    source_value = phase[plan.anchor_field_name]
    target_value = plan.anchor_target_value
    if plan.anchor_field_name == "hub":
        description = (
            f"an integer agent index in [0, {n_agents}) different from the "
            f"already-registered values {source_value} and {target_value}"
        )
    elif plan.anchor_field_name == "max_rounds":
        # Rounds at/above the coverage point compile to the source image
        # (registry no-op), so the honest legal domain is below the source.
        description = (
            f"an integer round count in [1, {int(source_value) - 1}] "
            f"different from the already-registered values {source_value} "
            f"and {target_value}"
        )
    elif plan.anchor_field_name == "instruction":
        description = (
            "a single English imperative instruction of at most 400 "
            "characters for a receiving agent, stating how to merge the "
            "incoming contributions toward the task's single global answer; "
            "plain text only (no code, no JSON, no topology or agent names); "
            "must differ from the already-registered instructions"
        )
    else:
        legal = _PATTERN_DOMAINS[str(phase["kind"])]
        free = [v for v in legal if v not in {source_value, target_value}]
        description = (
            f"one of {list(legal)} different from the already-registered "
            f"values {source_value!r} and {target_value!r} "
            f"(so effectively one of {free})"
        )
    return source_value, description


class RealReplicateHost:
    """One coordinator-restored real replicate with production authorities."""

    def __init__(
        self,
        experiment: RealV5Experiment,
        *,
        instances_by_case: dict[str, Any],
        llm_provider: str,
        arm_llm_client: Any,
        generation_transport: Any | None = None,
        max_parallel_agents: int = 5,
        strengthen_submission_merge: bool = False,
        log: Callable[[str], None] = print,
    ) -> None:
        self.experiment = experiment
        self.instances_by_case = instances_by_case
        self.llm_provider = llm_provider
        self.arm_llm_client = arm_llm_client
        self.max_parallel_agents = max_parallel_agents
        self.strengthen_submission_merge = strengthen_submission_merge
        self.log = log
        self.generation_transport = generation_transport
        # The offline rehearsal uses the repo's canonical deterministic agent
        # modes (the fake client does not speak the protocol init template);
        # a real provider run exercises the genuine LLM merge/init path.
        if llm_provider == "fake":
            self.merge_mode = "deterministic"
            self.init_mode = "deterministic"
        else:
            self.merge_mode = "llm_belief_merge"
            self.init_mode = "llm_local_solve"
        # All-agents LLM runs enforce the per-agent final submission barrier
        # (deterministic rehearsal beliefs already carry explicit answers).
        self.require_all_submissions = bool(
            experiment.spec.information_goal == "all_agents"
            and self.merge_mode != "deterministic"
        )
        spec = experiment.spec
        self.authority = SFTPilotFactorAuthority(
            experiment.protocol,
            pair_manifest=experiment.seal.pair_manifest,
            attestation_key=experiment.runtime_role_key("factor_pair_adapter"),
        )
        # The one owner kind and the structural-proof store must be installed
        # BEFORE the coordinator builds/loads the Bank: verify_plan and the
        # whole-operation verifier close over the authority's live attributes.
        self.authority.expected_owner_kind = (
            "whole_composition"
            if getattr(spec, "search_layer", "direct_factor")
            == "whole_composition"
            else "direct_factor"
        )
        self._structural_proofs: dict[str, PhaseStructuralOperationProofV1] = {}
        self._structural_proofs_path = (
            Path(spec.root) / "structural_proofs.json"
        ).resolve()
        self._load_structural_proofs()
        self.authority.structural_proof_resolver = self._structural_proofs.get
        anchor = experiment.seal.structural_anchor
        self.branch_authority = V5BranchReceiptAuthority(
            anchor_source_manifest_sha256=anchor.source_manifest_sha256,
        )
        self.store = SingleWriterPilotStore.open(
            experiment.state_dir,
            protocol=experiment.protocol,
            hmac_key=experiment.component_keys["store"],
            execution_schedule=experiment.seal.execution_schedule,
        )
        self.coordinator = PilotComponentCoordinator(
            store=self.store,
            phase_registry_key=experiment.component_keys["phase_registry"],
            factor_bank_key=experiment.component_keys["factor_bank"],
            manifest_verifier=self._verify_manifest,
            factor_capabilities_factory=v5_factor_capabilities_factory(
                authority=self.authority,
                seal=experiment.seal,
            ),
            branch_receipt_verifier=self.branch_authority,
        )
        self.loaded = self.coordinator.restore_recovery_head()
        self.checkpoint_ordinal = 0
        self.journal_dir = (Path(spec.root) / "journals").resolve()
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = PilotResultLedger(
            experiment.result_dir / "results.jsonl",
            ledger_key=experiment.runtime_role_key("result_ledger"),
        )
        self.attestor = PilotExecutionAttestor(
            experiment.protocol,
            engine_key=experiment.runtime_role_key("exact_phase_engine"),
        )
        self.scorer = PilotOutcomeScorer(
            experiment.protocol,
            scorer_key=experiment.runtime_role_key("train_scorer"),
            execution_attestor=self.attestor,
            scorer_id="sft-v5-real-train-scorer",
            scorer_version_sha256=_sha("sft-v5-real-train-scorer-code"),
        )

    def _verify_manifest(self, manifest: Any) -> bool:
        anchor = self.experiment.seal.structural_anchor
        return bool(
            manifest.manifest_sha256 == anchor.source_manifest_sha256
            and manifest.split == "TRAIN_UPDATE"
        )

    def close(self) -> None:
        self.store.close()

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
            operation_id=f"v5-real-checkpoint-{self.checkpoint_ordinal}",
            operation_request_sha256=_sha(
                f"v5-real-checkpoint:{self.experiment.spec.experiment_id}:"
                f"{self.checkpoint_ordinal}"
            ),
        )
        return self.loaded

    def _load_structural_proofs(self) -> None:
        if not self._structural_proofs_path.exists():
            return
        payload = json.loads(self._structural_proofs_path.read_text())
        for key, value in payload.items():
            self._structural_proofs[key] = (
                PhaseStructuralOperationProofV1.model_validate(value)
            )

    def _save_structural_proofs(self) -> None:
        self._structural_proofs_path.write_text(
            json.dumps(
                {
                    key: value.model_dump(mode="json")
                    for key, value in self._structural_proofs.items()
                },
                indent=2,
                sort_keys=True,
            )
        )

    def anchor_edge(self):
        proofs = self.registry.to_state().proofs
        return register_phase_materialization_v3(
            registry=self.registry,
            bank=self.bank,
            proof=proofs[0].handle,
        )

    # ------------------------------------------------------------------
    # TRAIN: real mutate generation
    # ------------------------------------------------------------------

    def commit_real_mutate_edge(self) -> tuple[Any, str, int]:
        """Run the sealed mutate slice with the real (or fake) transport.

        Returns ``(registered_edge, action_id, generated_value)``.
        """

        spec = self.experiment.spec
        tag = f"{spec.experiment_id}-mutate"
        edge = self.anchor_edge()
        observation = FailureObservationV2(
            failure_id=f"failure:v5-real:{tag}",
            failure_class="algorithm",
            failed_stage="execute",
            safe_failure_code="algorithm_failure",
            composition_id=edge.source_composition.composition_id,
            artifact_sha256=edge.source_composition.artifact_sha256,
            created_seq=self.bank.to_state().event_seq + 1,
        )
        opportunity = self.bank.record_failure(
            observation, feasible_branches=("mutate",)
        )
        if opportunity is None:
            raise RuntimeError("bootstrap repair opportunity was not created")
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
        _decision, assignment, action = self.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch=self.authority.assignment_producer_epoch,
            attestation_sha256=self.authority.proposal_action_attestation(
                opportunity_id=opportunity.opportunity_id,
                proposal_receipt_sha256=proposal.digest,
            ),
            generation_context=context,
        )
        if assignment is None or action is None or assignment.branch != "mutate":
            raise RuntimeError("mutate branch assignment was not allocated")

        generation_arm = next(
            item
            for item in self.experiment.protocol.authorized_logical_arms
            if item.operation_kind == "proposal_generation"
        )
        generation_key = f"v5-real-generation:{spec.experiment_id}"
        reserve_scheduled_execution(
            self.store,
            schedule=self.experiment.seal.execution_schedule,
            logical_arm=generation_arm,
            logical_execution_key=generation_key,
            action_id=action.action_id,
        )
        self.checkpoint()
        lease = self.authority.make_generation_lease(
            action=action,
            runner_session_id=f"v5-real-generation-runner:{tag}",
            runner_lease_token_sha256=_sha(f"gen-token:{tag}"),
            journal_anchor_sha256=_sha(f"gen-journal:{tag}"),
        )
        executing = self.bank.begin_proposal_generation(action.action_id, lease)
        self.checkpoint()
        plan_model = self.experiment.seal.structural_anchor_plan
        source_value, domain_description = anchor_generation_surface(
            plan_model, spec.n_agents
        )
        rendered = render_generation_request(
            context=context,
            request=executing.generation_request,
            scalar_type=plan_model.anchor_scalar_type,
            value_domain_description=domain_description,
            source_scalar=SafeSourceScalar(
                scalar_type=plan_model.anchor_scalar_type, value=source_value
            ),
        )
        transport = self.generation_transport
        if transport is None:
            if self.llm_provider == "openai":
                transport = OpenAIPilotTransport(
                    max_completion_tokens=GENERATION_OUTPUT_TOKENS_RESERVED,
                    expected_model=self.experiment.protocol.model_name,
                    reasoning_effort=spec.reasoning_effort,
                )
            else:
                transport = FakeDeterministicPilotTransport(
                    reply_factory=lambda _digest: json.dumps({"value": 2}),
                    expected_model=self.experiment.protocol.model_name,
                )
        started = time.monotonic()
        response = execute_metered_generation_call(
            store=self.store,
            schedule=self.experiment.seal.execution_schedule,
            logical_arm=generation_arm,
            logical_execution_key=generation_key,
            rendered=rendered,
            transport=transport,
            expected_component_recovery_root_sha256=(
                self.loaded.snapshot.recovery_root_sha256
            ),
        )
        wall_ms = max(1, int((time.monotonic() - started) * 1000))
        value = parse_generated_scalar(
            response.text, scalar_type=plan_model.anchor_scalar_type
        )
        self.log(
            f"[{spec.experiment_id}] generation produced hub value {value} "
            f"({response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens)"
        )
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
                wall_time_ms=wall_ms,
                cost_microusd=(
                    response.usage.prompt_tokens * 10
                    + response.usage.completion_tokens * 40
                ),
            ),
            generated_scalar_sha256=phase_generated_scalar_sha256(value),
            response_envelope_sha256=_sha(f"generation-response:{tag}"),
            terminal_event_id=f"generation-event:{tag}",
            terminal_event_sequence=generation_lease.started_seq + 1,
            verifier_epoch=f"v5-generation-terminal:{tag}",
            attestation_sha256=_sha(f"generation-terminal:{tag}"),
        )
        result = reconcile_phase_proposal_action_v3(
            registry=self.registry,
            bank=self.bank,
            action_id=executing.action_id,
            generation_terminal=terminal,
            generated_value=value,
            ingress=ingress,
        )
        from exp_graph.mas.phase_artifact_registry import (
            NoOpMaterialization,
            phase_materialization_event_sha256_v1,
        )

        if isinstance(result, NoOpMaterialization):
            # The generated scalar duplicates registered content, so no new
            # transition may exist (plan §5.2 duplicate/no-op law).  The
            # action aborts honestly with its Phase terminal joined; the
            # checkpoint saga is gate-delimited, so an aborted single-action
            # experiment has no further TRAIN work — the replicate ends
            # degenerate and the report says so.
            terminal_event = self.registry.resolve_event(result.event)
            abort = self.authority.make_abort_receipt(
                action=executing,
                reason="phase_noop",
                safe_failure_code="phase_noop",
                phase_terminal_sha256=phase_materialization_event_sha256_v1(
                    terminal_event
                ),
            )
            self.bank.abort_proposal_action(executing.action_id, abort)
            raise RuntimeError(
                f"generation duplicated registered content (value {value}); "
                "the sealed single-action experiment aborts with no probe "
                "evidence (degenerate no-op replicate)"
            )
        action_id = next(
            item.action_id
            for item in self.bank.to_state().proposal_actions
            if item.state == "committed"
        )
        return result, action_id, value

    # ------------------------------------------------------------------
    # TRAIN: real structural (whole-composition) generation
    # ------------------------------------------------------------------

    def commit_real_structural_edge(self, tag: str):
        """Generate, prove, and register one whole-composition edge.

        The structural analog of ``commit_real_mutate_edge``.  No Bank
        proposal action exists on this chain: the whole edge is an ordinary
        transition, the frozen operation domain plays the committed-intent
        role, and the saga's first checkpoint is the registered edge itself
        (``whole_edge_registered``).  Honest degenerates (no-op text, an
        already-registered compiled image, a scalar-only delta, a frozen
        bound violation) abort the sealed single-transition experiment with
        no probe evidence.
        """

        from masbench.sft_pilot.factor_authority import (
            derive_generation_budget,
        )

        spec = self.experiment.spec
        state = self.registry.to_state()
        genesis_proof = state.proofs[0]
        source_handle = genesis_proof.source_artifact
        source_artifact = self.registry.resolve_artifact(source_handle)
        source_program = PhaseProgram.model_validate(
            source_artifact.program.model_dump(mode="python")
        )
        excluded = tuple(
            sorted({item.execution_image_commitment for item in state.artifacts})
        )
        domain = frozen_structural_domain(
            source_program,
            excluded_image_commitments=excluded,
        )
        generation_arm = next(
            item
            for item in self.experiment.protocol.authorized_logical_arms
            if item.operation_kind == "proposal_generation"
        )
        generation_key = f"v5-real-generation:{spec.experiment_id}"
        reserve_scheduled_execution(
            self.store,
            schedule=self.experiment.seal.execution_schedule,
            logical_arm=generation_arm,
            logical_execution_key=generation_key,
            action_id=None,
        )
        budget = derive_generation_budget(
            self.experiment.protocol.phase_budgets[0]
        )
        rendered = render_structural_generation_request(
            domain=domain,
            n_agents=spec.n_agents,
            budget_sha256=budget.digest,
        )
        transport = self.generation_transport
        if transport is None:
            if self.llm_provider == "openai":
                transport = OpenAIPilotTransport(
                    max_completion_tokens=GENERATION_OUTPUT_TOKENS_RESERVED,
                    expected_model=self.experiment.protocol.model_name,
                    reasoning_effort=spec.reasoning_effort,
                )
            else:
                transport = FakeDeterministicPilotTransport(
                    reply_factory=lambda _digest: json.dumps(
                        {
                            "operation": {
                                "op_kind": "insert_phase",
                                "index": 1,
                                "phase": {
                                    "kind": "pairwise_exchange",
                                    "pattern": "rotating",
                                    "max_rounds": 2,
                                },
                            }
                        }
                    ),
                    expected_model=self.experiment.protocol.model_name,
                )
        response = execute_metered_generation_call(
            store=self.store,
            schedule=self.experiment.seal.execution_schedule,
            logical_arm=generation_arm,
            logical_execution_key=generation_key,
            rendered=rendered,
            transport=transport,
            expected_component_recovery_root_sha256=(
                self.loaded.snapshot.recovery_root_sha256
            ),
        )
        operation = parse_generated_operation(response.text)
        origin_branch = (
            "fresh" if operation.op_kind == "fresh_skeleton" else "mutate"
        )
        self.log(
            f"[{spec.experiment_id}] structural generation proposed "
            f"{operation.op_kind} "
            f"({response.usage.prompt_tokens}+"
            f"{response.usage.completion_tokens} tokens)"
        )
        ingress = self.registry.issue_ingress(
            self.experiment.seal.structural_anchor.source_manifest_sha256
        )
        try:
            proof = prove_structural_operation(
                self.registry,
                source_artifact=source_handle,
                operation=operation,
                origin_branch=origin_branch,
                ingress=ingress,
            )
            target_artifact = self.registry.resolve_artifact(
                proof.target_artifact
            )
            validate_structural_bounds(
                domain,
                operation,
                target_program=PhaseProgram.model_validate(
                    target_artifact.program.model_dump(mode="python")
                ),
                target_compiled_steps=len(
                    target_artifact.execution_image.steps
                ),
                target_image_commitment=(
                    target_artifact.execution_image_commitment
                ),
            )
        except (StructuralNoOpError, ValueError) as exc:
            # Honest degenerate: the sealed single-transition experiment has
            # no probe work; the replicate ends and the report says so.  The
            # spent generation call stays metered in the store.
            raise RuntimeError(
                f"structural generation degenerated honestly ({exc}); the "
                "sealed single-transition experiment aborts with no probe "
                "evidence"
            ) from exc
        self._structural_proofs[proof.receipt_sha256] = proof
        self._save_structural_proofs()
        edge = register_phase_whole_materialization_v1(
            registry=self.registry,
            bank=self.bank,
            proof=proof,
        )
        self.checkpoint()
        if (
            self.loaded.snapshot.checkpoint.checkpoint_kind
            != "whole_edge_registered"
        ):
            raise RuntimeError(
                "structural edge did not checkpoint as whole_edge_registered"
            )
        self.log(
            f"[{spec.experiment_id}] whole edge registered "
            f"{edge.transition.transition_id} "
            f"(changed slots: {len(edge.transition.changed_slot_ids)})"
        )
        return edge, operation

    # ------------------------------------------------------------------
    # TRAIN: real six-unit probe
    # ------------------------------------------------------------------

    def seal_plan_for(self, transition):
        return self.bank.seal_probe_plan(
            transition_id=transition.transition_id,
            owner_kind=self.authority.expected_owner_kind,
            epoch_id=self.authority.epoch_id_for(
                transition_id=transition.transition_id
            ),
            unit_commitments=self.authority.unit_commitments,
            arm_orders=self.authority.arm_orders,
            assignment_manifest_sha256=self.authority.assignment_manifest_sha256,
            runner_version=self.authority.runner_version,
            budget=self.authority.plan_budget,
        )

    def _probe_arm_coordinates(self, ordinal: int):
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

    def _case_for_commitment(self, case_commitment_sha256: str) -> Any:
        entry = next(
            item
            for item in self.experiment.seal.case_manifest.cases
            if item.input_commitment_sha256 == case_commitment_sha256
        )
        return entry.case_id, self.instances_by_case[entry.case_id]

    def _run_real_arm(
        self,
        *,
        program: PhaseProgram,
        instance: Any,
        seed: int,
    ) -> tuple[ArmRunResult, int]:
        spec = self.experiment.spec
        started = time.monotonic()
        result = run_phase_program_arm(
            program=program,
            instance=instance,
            n_agents=spec.n_agents,
            information_goal=spec.information_goal,
            seed=seed,
            model_name=self.experiment.protocol.model_name,
            temperature=self.experiment.protocol.temperature,
            llm_provider=self.llm_provider,
            llm_client=self.arm_llm_client,
            merge_mode=self.merge_mode,
            init_mode=self.init_mode,
            max_parallel_agents=self.max_parallel_agents,
            require_all_submissions=self.require_all_submissions,
            strengthen_submission_merge=self.strengthen_submission_merge,
        )
        wall_ms = max(1, int((time.monotonic() - started) * 1000))
        # Metering-consistency law (plan_deviations §8): the ArmRunResult token
        # totals are the store/ArmReceipt metering truth.  In sink mode the
        # paper C metric equals them exactly; in all_agents mode the official
        # C law counts the submission barrier differently (completion-only),
        # so C may lawfully be at most the metered total, never more.
        metered = float(result.prompt_tokens + result.completion_tokens)
        dense_c = float(result.dense_outcome.C)
        consistent = (
            dense_c == metered
            if self.experiment.spec.information_goal == "sink"
            else dense_c <= metered
        )
        if not consistent:
            raise RuntimeError(
                "run usage diverged from its DenseOutcome C metric: "
                f"C={dense_c} vs metered tokens={metered}"
            )
        return result, wall_ms

    def _store_whole_arm_receipt(
        self,
        *,
        arm_coords: Any,
        key: str,
        result_input_tokens: int,
        result_output_tokens: int,
        recovery_root: str,
    ) -> str:
        """Record one aggregate call receipt carrying the real token sums."""

        schedule = self.experiment.seal.execution_schedule
        scheduled_call = schedule.entry_for(arm_coords).calls[0]
        call_key = f"call-{key}"
        self.store.reserve_call(
            operation_id=f"reserve-{call_key}",
            operation_request_sha256=_sha(f"reserve:{call_key}"),
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
            operation_request_sha256=_sha(f"start:{call_key}"),
            call_request_sha256=scheduled_call.request_envelope_sha256,
            expected_component_recovery_root_sha256=recovery_root,
        )
        if not authorization.may_invoke_sdk:
            raise RuntimeError(f"store refused call authorization for {key}")
        self.store.complete_call(
            call_key,
            operation_id=f"complete-{call_key}",
            operation_request_sha256=_sha(f"complete:{call_key}"),
            call_request_sha256=scheduled_call.request_envelope_sha256,
            output_envelope_sha256=_sha(f"output:{call_key}"),
            provider_usage_known=True,
            input_tokens_used=result_input_tokens,
            output_tokens_used=result_output_tokens,
        )
        self.store.complete_execution(
            key,
            operation_id=f"complete-{key}",
            operation_request_sha256=_sha(f"complete:{key}"),
        )
        return call_key

    def _physical_root(
        self, *, attempt_id: str, arm: str, artifact_sha256: str, seed: int, key: str
    ) -> str:
        return canonical_sha256(
            {
                "domain": "sft-v5-real-arm-physical-root-v1",
                "attempt_id": attempt_id,
                "arm": arm,
                "artifact_sha256": artifact_sha256,
                "seed": seed,
                "logical_execution_key": key,
            }
        )

    def execute_real_probe_unit(
        self,
        *,
        edge: Any,
        plan: Any,
        action_id: str,
        ordinal: int,
    ) -> ProbeUnitOutcome:
        """Run one unit end-to-end with real arms; cancel on any failure."""

        spec = self.experiment.spec
        tag = f"{spec.experiment_id}-probe-{ordinal}"
        assignment = self.authority.make_assignment(plan, ordinal=ordinal)
        journal_id = _host_id("jr", f"journal:{tag}")
        locator_id = _host_id("jl", f"locator:{tag}")
        runner_lease = self.authority.make_runner_lease(
            plan=plan,
            assignment=assignment,
            runner_session_id=f"v5-real-probe-runner:{tag}",
            runner_lease_token_sha256=_sha(f"probe-token:{tag}"),
            journal_anchor_sha256=canonical_sha256(
                {
                    "domain": "sft-v5-real-journal-anchor-v1",
                    "journal_id": journal_id,
                    "journal_locator_id": locator_id,
                }
            ),
        )
        attempt = self.bank.open_next_attempt(
            plan.plan_id, assignment, runner_lease
        )
        source_arm, target_arm = self._probe_arm_coordinates(ordinal)
        source_key = f"probe-{tag}-source"
        target_key = f"probe-{tag}-target"
        for arm_coords, key in (
            (source_arm, source_key),
            (target_arm, target_key),
        ):
            reserve_scheduled_execution(
                self.store,
                schedule=self.experiment.seal.execution_schedule,
                logical_arm=arm_coords,
                logical_execution_key=key,
                action_id=action_id,
            )
        self.checkpoint()
        if (
            self.loaded.snapshot.checkpoint.checkpoint_kind
            != "probe_attempt_open"
        ):
            raise RuntimeError("probe unit did not open as probe_attempt_open")
        recovery_root = self.loaded.snapshot.recovery_root_sha256

        is_whole = isinstance(edge, RegisteredPhaseWholeCompositionEdgeV1)
        if is_whole:
            proof_id = edge.proof.proof_id
            proof_sha256 = edge.proof.receipt_sha256
            source_artifact = self.registry.resolve_artifact(
                edge.proof.source_artifact
            )
            target_artifact = self.registry.resolve_artifact(
                edge.proof.target_artifact
            )
            payload_manifest_sha256 = source_artifact.source_manifest_sha256
        else:
            proof = self.registry.resolve_proof(edge.proof)
            proof_id = proof.handle.handle_id
            proof_sha256 = proof.handle.proof_sha256
            source_artifact = self.registry.resolve_artifact(
                proof.source_artifact
            )
            target_artifact = self.registry.resolve_artifact(
                proof.target_artifact
            )
            payload_manifest_sha256 = proof.source_manifest_sha256
        source_program = PhaseProgram.model_validate(
            source_artifact.program.model_dump(mode="python")
        )
        target_program = PhaseProgram.model_validate(
            target_artifact.program.model_dump(mode="python")
        )
        case_id, instance = self._case_for_commitment(
            source_arm.case_commitment_sha256
        )
        seed = PROBE_SEED_BASE + ordinal
        arm_order = plan.units[ordinal].arm_order

        roots = {
            "source": self._physical_root(
                attempt_id=attempt.attempt_id,
                arm="source",
                artifact_sha256=source_artifact.execution_image_commitment,
                seed=seed,
                key=source_key,
            ),
            "target": self._physical_root(
                attempt_id=attempt.attempt_id,
                arm="target",
                artifact_sha256=target_artifact.execution_image_commitment,
                seed=seed,
                key=target_key,
            ),
        }

        # --- Real pair journal around the two real runs.
        scope = JournalScopeV2(
            namespace=self.experiment.protocol.namespace,
            namespace_sha256=self.experiment.protocol.namespace.digest,
            planner_mode=self.experiment.protocol.namespace.planner_mode,
            information_goal=(
                self.experiment.protocol.namespace.information_goal
            ),
            worker_contract=self.experiment.protocol.namespace.worker_contract,
            mode_payload_sha256=source_artifact.execution_image_commitment,
            mode_payload_source="TRAIN_UPDATE",
            mode_payload_manifest_sha256=payload_manifest_sha256,
            runner_policy_sha256=_sha("sft-v5-real-nonoverlap-policy-v1"),
        )
        provider_epoch = _sha(f"sft-v5-real-provider-epoch:{spec.experiment_id}")
        manifest_epoch = _sha(f"sft-v5-real-manifest-epoch:{spec.experiment_id}")
        reader_policy = _sha("sft-v5-real-reader-policy-v1")
        provider = _LinearizableCheckpointProvider(
            provider_epoch_sha256=provider_epoch
        )
        journal = SFTRunnerJournal(
            journal_key=_derive_key(spec.master_key, _JOURNAL_KEY_DOMAIN),
            journal_id=journal_id,
            scope=scope,
            checkpoint_provider=provider,
            scope_manifest_verifier=_ExactScopeVerifier(scope),
        )
        provider.bootstrap(journal.checkpoint())
        journal_path = self.journal_dir / f"journal-{tag}.json"
        journal.save(journal_path)
        intent = PreparePayloadV2(
            attempt_id=attempt.attempt_id,
            plan_id=plan.plan_id,
            ordinal=ordinal,
            assignment_receipt_sha256=canonical_sha256(attempt.assignment),
            expected_open_attempt_sha256=canonical_sha256(attempt),
            scheduled_arm_order=arm_order,
            runner_session_id=_host_id(
                "rs", attempt.runner_lease.runner_session_id
            ),
            runner_lease_token_sha256=(
                attempt.runner_lease.runner_lease_token_sha256
            ),
            verifier_epoch_sha256=_sha("sft-v5-real-journal-verifier-v1"),
            source_arm_commitment_sha256=exact_phase_arm_commitment_v1(
                self.experiment.protocol,
                source_arm,
                proof_id=proof_id,
                proof_sha256=proof_sha256,
                artifact_sha256=source_artifact.execution_image_commitment,
            ),
            target_arm_commitment_sha256=exact_phase_arm_commitment_v1(
                self.experiment.protocol,
                target_arm,
                proof_id=proof_id,
                proof_sha256=proof_sha256,
                artifact_sha256=target_artifact.execution_image_commitment,
            ),
        )
        journal.prepare_attempt(intent)
        provider.acknowledge(journal.checkpoint())

        ordered_arms = (
            ("source", "target") if arm_order == "AB" else ("target", "source")
        )
        programs = {"source": source_program, "target": target_program}
        keys = {"source": source_key, "target": target_key}
        arm_coords_by_name = {"source": source_arm, "target": target_arm}
        results: dict[str, ArmRunResult] = {}
        wall_ms: dict[str, int] = {}
        started_arms: list[dict] = []
        failure: tuple[str, str] | None = None

        for arm_name in ordered_arms:
            journal.start_arm(
                attempt.attempt_id,
                arm=arm_name,
                physical_root_id=roots[arm_name],
            )
            provider.acknowledge(journal.checkpoint())
            started_arms.append(
                {"arm": arm_name, "root": roots[arm_name], "finished": False}
            )
            try:
                results[arm_name], wall_ms[arm_name] = self._run_real_arm(
                    program=programs[arm_name],
                    instance=instance,
                    seed=seed,
                )
            except Exception as exc:  # noqa: BLE001 - honest infra settlement
                failure = (arm_name, f"{type(exc).__name__}: {exc}")
                self.log(
                    f"[{spec.experiment_id}] unit {ordinal} {arm_name} arm "
                    f"infrastructure failure: {failure[1]}"
                )
                break
            journal.finish_arm(attempt.attempt_id, arm=arm_name)
            provider.acknowledge(journal.checkpoint())
            started_arms[-1]["finished"] = True
            self._store_whole_arm_receipt(
                arm_coords=arm_coords_by_name[arm_name],
                key=keys[arm_name],
                result_input_tokens=results[arm_name].prompt_tokens,
                result_output_tokens=results[arm_name].completion_tokens,
                recovery_root=recovery_root,
            )

        if failure is not None:
            # The journal's cancellation enum is runner-scoped
            # (runner_timeout/...), distinct from the Bank's provider_timeout.
            journal.cancel_attempt(
                attempt.attempt_id, safe_failure_code="runner_timeout"
            )
            provider.acknowledge(journal.checkpoint())
            from exp_graph.mas.factor_bank_v2 import (
                StartedArmJournalWitnessV2,
            )

            witnesses = []
            for index, item in enumerate(started_arms):
                start_seq = 1 + 2 * index
                witnesses.append(
                    StartedArmJournalWitnessV2(
                        arm=item["arm"],
                        root_id=item["root"],
                        start_event_id=_host_id(
                            "se", f"start:{tag}:{item['arm']}"
                        ),
                        start_event_seq=start_seq,
                        finish_event_id=(
                            _host_id("se", f"finish:{tag}:{item['arm']}")
                            if item["finished"]
                            else None
                        ),
                        finish_event_seq=(
                            start_seq + 1 if item["finished"] else None
                        ),
                    )
                )
            self._cancel_open_attempt(
                plan=plan,
                attempt=attempt,
                started_arm_roots=tuple(witnesses),
                tag=tag,
            )
            return ProbeUnitOutcome(
                ordinal=ordinal,
                case_id=case_id,
                seed=seed,
                arm_order=arm_order,
                status="cancelled",
                cancel_reason=failure[1],
            )

        journal.complete_pair(attempt.attempt_id)
        provider.acknowledge(journal.checkpoint())

        trust_host = _JournalTrustHost(
            master=spec.master_key,
            path=journal_path,
            locator_id=locator_id,
            journal_id=journal_id,
            manifest_sha256=payload_manifest_sha256,
            provider_epoch_sha256=provider_epoch,
            manifest_epoch_sha256=manifest_epoch,
            reader_policy_sha256=reader_policy,
        )
        trust = SnapshotTrustPolicyV1(
            journal_locator_id=locator_id,
            journal_id=journal_id,
            scope_sha256=scope.digest,
            journal_locator_sha256=trust_host.locator_sha256,
            journal_key_commitment_sha256=journal_key_commitment_v1(
                role="journal", key=trust_host.journal_key
            ),
            reader_key_commitment_sha256=journal_key_commitment_v1(
                role="reader", key=trust_host.reader_key
            ),
            reader_policy_sha256=reader_policy,
            provider_epoch_sha256=provider_epoch,
            manifest_verifier_epoch_sha256=manifest_epoch,
            manifest_verifier_policy_sha256=trust_host.verifier_policy_sha256(),
        )
        snapshot = load_verified_snapshot(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
            expected_scope=scope,
            expected_trust_policy=trust,
            journal_key_resolver=trust_host,
            journal_locator_resolver=trust_host,
            checkpoint_provider=provider,
            scope_manifest_verifier=trust_host,
        )

        # --- Pair execution receipt: seqs mirror the journal event order.
        if arm_order == "AB":
            seqs = {"source": (2, 3), "target": (4, 5)}
        else:
            seqs = {"target": (2, 3), "source": (4, 5)}
        pair_receipt = self.authority.make_pair_execution(
            plan=plan,
            attempt=attempt,
            source_root_id=roots["source"],
            target_root_id=roots["target"],
            source_started_seq=seqs["source"][0],
            source_finished_seq=seqs["source"][1],
            target_started_seq=seqs["target"][0],
            target_finished_seq=seqs["target"][1],
        )

        receipts: dict[str, Any] = {}
        for arm_name in ("source", "target"):
            result = results[arm_name]
            if is_whole:
                capability = register_exact_phase_whole_execution_result(
                    protocol=self.experiment.protocol,
                    logical_arm=arm_coords_by_name[arm_name],
                    registry=self.registry,
                    registered_edge=edge,
                    store=self.store,
                    logical_execution_key=keys[arm_name],
                    call_keys=(f"call-{keys[arm_name]}",),
                    journal_snapshot=snapshot,
                    engine_key=self.experiment.runtime_role_key(
                        "exact_phase_engine"
                    ),
                )
            else:
                capability = register_exact_phase_execution_result(
                    protocol=self.experiment.protocol,
                    logical_arm=arm_coords_by_name[arm_name],
                    registry=self.registry,
                    registered_edge=edge,
                    store=self.store,
                    logical_execution_key=keys[arm_name],
                    call_keys=(f"call-{keys[arm_name]}",),
                    journal_snapshot=snapshot,
                    engine_key=self.experiment.runtime_role_key(
                        "exact_phase_engine"
                    ),
                    step_execution_witness=results[arm_name].total_steps,
                )
            attestation = self.attestor.issue(capability)
            outcome_receipt = self.scorer.score_train_update(
                attestation,
                result.dense_outcome,
                terminal_class=result.execution_class,
            )
            usage = ExecutionUsage(
                messages=result.messages,
                model_calls=result.model_calls,
                input_tokens=result.prompt_tokens,
                output_tokens=result.completion_tokens,
                wall_time_ms=wall_ms[arm_name],
                cost_microusd=(
                    result.prompt_tokens * 10 + result.completion_tokens * 40
                ),
            )
            receipt_maker = (
                make_phase_whole_arm_receipt
                if is_whole
                else make_phase_v3_factor_arm_receipt
            )
            receipts[arm_name] = receipt_maker(
                authority=self.authority,
                registry=self.registry,
                registered=edge,
                plan=plan,
                attempt=attempt,
                pair_execution_receipt=pair_receipt,
                execution=attestation,
                outcome_receipt=outcome_receipt,
                execution_attestor=self.attestor,
                scorer=self.scorer,
                usage=usage,
                safe_failure_code=result.safe_failure_code,
                failed_stage_rank=result.failed_stage_rank,
            )
        consumed = consume_phase_v3_pair_once(
            loaded=self.loaded,
            coordinator=self.coordinator,
            attempt_id=attempt.attempt_id,
            source_receipt=receipts["source"],
            target_receipt=receipts["target"],
            pair_execution_receipt=pair_receipt,
            operation_id=f"consume-{tag}",
            operation_request_sha256=_sha(f"consume:{tag}"),
        )
        self.loaded = consumed.loaded
        return ProbeUnitOutcome(
            ordinal=ordinal,
            case_id=case_id,
            seed=seed,
            arm_order=arm_order,
            status="consumed",
            source=_arm_report(results["source"]),
            target=_arm_report(results["target"]),
        )

    def _cancel_open_attempt(
        self,
        *,
        plan: Any,
        attempt: Any,
        started_arm_roots: tuple[str, ...],
        tag: str,
        safe_failure_code: str = "provider_timeout",
    ) -> None:
        """Settle a half pair through the authority-fenced cancellation law."""

        from masbench.sft_pilot.factor_authority import (
            UNSIGNED_ATTESTATION_SHA256,
        )

        assignment_sha256 = canonical_sha256(attempt.assignment)
        open_attempt_sha256 = canonical_sha256(attempt)
        schedule_event_id = f"schedule:{tag}"
        abort_event_id = f"abort:{tag}"
        abort_seq = 1 + max(
            [0]
            + [
                (
                    item.finish_event_seq
                    if item.finish_event_seq is not None
                    else item.start_event_seq
                )
                for item in started_arm_roots
            ]
        )
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
            abort_event_seq=abort_seq,
            cancel_kind="infrastructure",
            safe_failure_code=safe_failure_code,
            terminate_scope=bool(started_arm_roots),
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
            abort_event_seq=abort_seq,
            runner_event_root_sha256=event_root,
            cancel_kind="infrastructure",
            safe_failure_code=safe_failure_code,
            terminate_scope=bool(started_arm_roots),
            started_arm_roots=started_arm_roots,
            verifier_epoch=self.authority.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
        )
        cancellation = self.authority.attest_cancellation(
            unsigned, attempt=attempt, plan=plan
        )
        self.bank.cancel_open_attempt(attempt.attempt_id, cancellation)
        self.checkpoint()
        if self.loaded.snapshot.checkpoint.checkpoint_kind != "probe_terminal":
            raise RuntimeError("cancellation did not settle as probe_terminal")


    # ------------------------------------------------------------------
    # FINAL_VAL: real read-only gate executions
    # ------------------------------------------------------------------

    def run_real_final_val_gate(
        self,
        *,
        edge: Any,
    ) -> tuple[Any, dict[str, Any]]:
        """Run candidate vs incumbent on the frozen FINAL_VAL cases for real.

        Both programs run on BOTH frozen cases with identical seeds (paired
        keys are required by the strict predicate).  Each frozen FINAL_VAL
        arm's aggregate store receipt carries its role's real token sums.
        """

        spec = self.experiment.spec
        if isinstance(edge, RegisteredPhaseWholeCompositionEdgeV1):
            source_artifact = self.registry.resolve_artifact(
                edge.proof.source_artifact
            )
            target_artifact = self.registry.resolve_artifact(
                edge.proof.target_artifact
            )
        else:
            proof = self.registry.resolve_proof(edge.proof)
            source_artifact = self.registry.resolve_artifact(
                proof.source_artifact
            )
            target_artifact = self.registry.resolve_artifact(
                proof.target_artifact
            )
        programs = {
            "incumbent": PhaseProgram.model_validate(
                source_artifact.program.model_dump(mode="python")
            ),
            "candidate": PhaseProgram.model_validate(
                target_artifact.program.model_dump(mode="python")
            ),
        }
        incumbent_samples: list[FinalValCaseSample] = []
        candidate_samples: list[FinalValCaseSample] = []
        samples_by_role = {
            "incumbent": incumbent_samples,
            "candidate": candidate_samples,
        }
        fv_rows: dict[str, list[dict[str, Any]]] = {
            "incumbent": [],
            "candidate": [],
        }

        def execute_final_val_arm(arm: Any, role: str) -> None:
            key = f"final-val-{spec.experiment_id}-{role}"
            reserve_scheduled_execution(
                self.store,
                schedule=self.experiment.seal.execution_schedule,
                logical_arm=arm,
                logical_execution_key=key,
            )
            recovery_root = self.loaded.snapshot.recovery_root_sha256
            input_sum = 0
            output_sum = 0
            for offset, case_id in enumerate(spec.final_val_case_ids):
                instance = self.instances_by_case[case_id]
                seed = FINAL_VAL_SEED_BASE + offset
                result, _wall = self._run_real_arm(
                    program=programs[role],
                    instance=instance,
                    seed=seed,
                )
                input_sum += result.prompt_tokens
                output_sum += result.completion_tokens
                samples_by_role[role].append(
                    FinalValCaseSample(
                        case_id=case_id,
                        seed=seed,
                        metrics=result.dense_outcome,
                        algorithm_failure=(
                            result.execution_class == "algorithm_failure"
                        ),
                    )
                )
                fv_rows[role].append(
                    {"case_id": case_id, "seed": seed}
                    | _arm_report(result)
                )
                self.log(
                    f"[{spec.experiment_id}] FINAL_VAL {role} {case_id} "
                    f"S={result.dense_outcome.S:.3f} "
                    f"class={result.execution_class}"
                )
            self._store_whole_arm_receipt(
                arm_coords=arm,
                key=key,
                result_input_tokens=input_sum,
                result_output_tokens=output_sum,
                recovery_root=recovery_root,
            )

        outcome, promoted = run_final_val_gate(
            loaded=self.loaded,
            coordinator=self.coordinator,
            store=self.store,
            schedule=self.experiment.seal.execution_schedule,
            authority=self.authority,
            protocol=self.experiment.protocol,
            incumbent_samples=incumbent_samples,
            candidate_samples=candidate_samples,
            # The promoted scientific commit is owned by the TRAIN_UPDATE
            # proposal's terminal generation execution, not a FINAL_VAL lease.
            owner_logical_execution_key=(
                f"v5-real-generation:{spec.experiment_id}"
            ),
            execute_final_val_arm=execute_final_val_arm,
            operation_id=f"final-val-gate-{spec.experiment_id}",
        )
        self.loaded = promoted
        self.ledger.append(
            row_kind="final_val_gate",
            experiment_seal_sha256=self.experiment.seal.digest,
            protocol_sha256=self.experiment.protocol.digest,
            report_sha256=outcome.report_sha256,
            accepted=outcome.accepted,
            metrics=tuple(
                sorted(
                    {
                        "accepted": 1.0 if outcome.accepted else 0.0,
                        "incumbent_mean_S": (
                            sum(s.metrics.S for s in incumbent_samples)
                            / max(1, len(incumbent_samples))
                        ),
                        "candidate_mean_S": (
                            sum(s.metrics.S for s in candidate_samples)
                            / max(1, len(candidate_samples))
                        ),
                    }.items()
                )
            ),
        )
        return outcome, {
            "accepted": outcome.accepted,
            "report_sha256": outcome.report_sha256,
            "strict_result": outcome.strict_result,
            "incumbent_rows": fv_rows["incumbent"],
            "candidate_rows": fv_rows["candidate"],
        }

    # ------------------------------------------------------------------
    # TEST: frozen read-only deployed evaluation
    # ------------------------------------------------------------------

    def deployed_program(self, edge: Any) -> tuple[str, PhaseProgram]:
        """Resolve the deployed head's exact program via the registry."""

        if isinstance(edge, RegisteredPhaseWholeCompositionEdgeV1):
            handle_owner = edge.proof
        else:
            handle_owner = self.registry.resolve_proof(edge.proof)
        head = next(iter(self.bank.deployment_heads.values()))
        state = self.bank.to_state()
        composition = next(
            item
            for item in state.compositions
            if item.composition_id == head.active_composition_id
        )
        for handle_name in ("source_artifact", "target_artifact"):
            artifact = self.registry.resolve_artifact(
                getattr(handle_owner, handle_name)
            )
            if (
                artifact.execution_image_commitment
                == composition.artifact_sha256
            ):
                label = (
                    "anchor_source"
                    if handle_name == "source_artifact"
                    else "gated_target"
                )
                return label, PhaseProgram.model_validate(
                    artifact.program.model_dump(mode="python")
                )
        raise RuntimeError(
            "deployed composition does not match any registered artifact"
        )

    def run_real_frozen_test(
        self,
        *,
        edge: Any,
        max_parallel_cases: int = 3,
    ) -> dict[str, Any]:
        """Evaluate the deployed head on the frozen TEST cases, read-only."""

        spec = self.experiment.spec
        deployed_label, program = self.deployed_program(edge)
        instances = tuple(
            self.instances_by_case[case_id] for case_id in spec.test_case_ids
        )
        seeds = tuple(
            TEST_SEED_BASE + index for index in range(len(instances))
        )
        captured: dict[str, Any] = {}

        def test_executor(
            manifest: Any, snapshot: Any, deployment_view: Any
        ) -> tuple[str, tuple[tuple[str, float], ...]]:
            del snapshot
            rows = evaluate_program_on_cases(
                program=program,
                instances=instances,
                seeds=seeds,
                arm_label="sft_deployed",
                n_agents=spec.n_agents,
                information_goal=spec.information_goal,
                model_name=self.experiment.protocol.model_name,
                temperature=self.experiment.protocol.temperature,
                llm_provider=self.llm_provider,
                llm_client=self.arm_llm_client,
                merge_mode=self.merge_mode,
                init_mode=self.init_mode,
                max_parallel_cases=max_parallel_cases,
                max_parallel_agents=self.max_parallel_agents,
                require_all_submissions=self.require_all_submissions,
                strengthen_submission_merge=self.strengthen_submission_merge,
                progress=lambda row: self.log(
                    f"[{spec.experiment_id}] TEST {row.case_id} done"
                ),
            )
            aggregate = aggregate_eval_rows(rows)
            safe_rows = tuple(
                {
                    "case_id": row.case_id,
                    "seed": row.seed,
                    "infrastructure_error": row.infrastructure_error,
                }
                | (_arm_report(row.result) if row.result is not None else {})
                for row in rows
            )
            captured["rows"] = safe_rows
            captured["aggregate"] = aggregate
            report_sha256 = canonical_sha256(
                {
                    "domain": "sft-v5-real-test-report-v1",
                    "test_manifest_sha256": manifest.digest,
                    "deployment_view": deployment_view,
                    "deployed_label": deployed_label,
                    "rows": safe_rows,
                }
            )
            return report_sha256, tuple(
                sorted(
                    (name, float(value))
                    for name, value in aggregate.items()
                )
            )

        self.log(
            f"[{spec.experiment_id}] TEST evaluating deployed program "
            f"({deployed_label}) on {len(instances)} cases"
        )
        row = run_frozen_test_readonly(
            store=self.store,
            loaded=self.loaded,
            seal=self.experiment.seal,
            protocol=self.experiment.protocol,
            test_manifest=self.experiment.test_manifest,
            ledger=self.ledger,
            test_executor=test_executor,
        )
        return {
            "deployed_label": deployed_label,
            "ledger_row_sha256": row.digest,
            "aggregate": captured["aggregate"],
            "rows": captured["rows"],
        }


def run_real_replicate(
    experiment: RealV5Experiment,
    *,
    instances_by_case: dict[str, Any],
    llm_provider: str,
    arm_llm_client: Any,
    generation_transport: Any | None = None,
    max_parallel_agents: int = 5,
    test_parallel_cases: int = 3,
    strengthen_submission_merge: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Drive one sealed replicate end-to-end: mutate → probe → gate → TEST."""

    spec = experiment.spec
    host = RealReplicateHost(
        experiment,
        instances_by_case=instances_by_case,
        llm_provider=llm_provider,
        arm_llm_client=arm_llm_client,
        generation_transport=generation_transport,
        max_parallel_agents=max_parallel_agents,
        strengthen_submission_merge=strengthen_submission_merge,
        log=log,
    )
    report: dict[str, Any] = {
        "experiment_id": spec.experiment_id,
        "seal_sha256": experiment.seal.digest,
        "protocol_sha256": experiment.protocol.digest,
        "probe_case_ids": list(spec.probe_case_ids),
        "final_val_case_ids": list(spec.final_val_case_ids),
        "test_case_ids": list(spec.test_case_ids),
        "units": [],
    }
    try:
        if getattr(spec, "search_layer", "direct_factor") == "whole_composition":
            edge, operation = host.commit_real_structural_edge(
                spec.experiment_id
            )
            # The whole transition is the chain's owner: probe leases join
            # the saga through its id (the direct chain uses the Bank
            # proposal-action id here).
            action_id = edge.transition.transition_id
            report["generated_operation"] = operation.model_dump(mode="json")
            report["target_program"] = host.registry.resolve_artifact(
                edge.proof.target_artifact
            ).program.model_dump(mode="json")
        else:
            edge, action_id, generated_value = host.commit_real_mutate_edge()
            report["generated_hub_value"] = generated_value
        report["transition_id"] = edge.transition.transition_id
        plan = host.seal_plan_for(edge.transition)
        report["plan_id"] = plan.plan_id

        used_ordinals: list[int] = []
        for ordinal in range(6):
            outcome = host.execute_real_probe_unit(
                edge=edge,
                plan=plan,
                action_id=action_id,
                ordinal=ordinal,
            )
            used_ordinals.append(ordinal)
            report["units"].append(outcome.__dict__)
            assessment = host.bank.assessments.get(plan.plan_id)
            label = getattr(assessment, "label", None)
            settled = bool(getattr(assessment, "settled", False))
            log(
                f"[{spec.experiment_id}] unit {ordinal} {outcome.status}; "
                f"assessment label={label} settled={settled}"
            )
            if settled and label != "probing":
                break

        assessment = host.bank.assessments.get(plan.plan_id)
        label = getattr(assessment, "label", None)
        report["assessment_label"] = label
        report["assessment_settled"] = bool(
            getattr(assessment, "settled", False)
        )

        unused = tuple(
            ordinal for ordinal in range(6) if ordinal not in used_ordinals
        )
        if label == "candidate":
            if unused:
                skipped = skip_settled_probe_blocks(
                    host.store,
                    schedule=experiment.seal.execution_schedule,
                    ordinals=unused,
                    action_id=action_id,
                )
                report["skipped_probe_blocks"] = list(skipped)
            _outcome, gate_report = host.run_real_final_val_gate(edge=edge)
            report["gate"] = gate_report
        else:
            report["gate"] = {
                "accepted": False,
                "skipped": True,
                "reason": f"assessment label is {label!r}, not candidate",
            }

        report["test"] = host.run_real_frozen_test(
            edge=edge, max_parallel_cases=test_parallel_cases
        )
        report["ledger_rows"] = len(host.ledger.rows())
        report["scientific_state_sha256"] = host.bank.scientific_state_sha256
        report["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 - replicate-level honest failure
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        import traceback

        report["traceback"] = traceback.format_exc()
        raise
    finally:
        host.close()
        report_path = Path(spec.root) / "replicate-report.json"
        report_path.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
    return report


__all__ = [
    "FINAL_VAL_SEED_BASE",
    "PROBE_SEED_BASE",
    "ProbeUnitOutcome",
    "RealReplicateHost",
    "TEST_SEED_BASE",
    "run_real_replicate",
]
