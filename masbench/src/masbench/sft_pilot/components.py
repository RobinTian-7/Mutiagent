"""Exact Phase/Factor recovery adapter for the single-writer SFT pilot.

SQLite owns the committed bytes.  The two JSON files in the state directory
are replaceable working mirrors used only because the component libraries
currently expose authenticated path-based loaders.  Every operation restores
them from SQLite before loading, and publishes a new pair only through the
store's atomic component-scientific commit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any

from exp_graph.mas.factor_bank_v2 import FactorBankV2
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    SourceManifest,
)
from exp_graph.mas.phase_factor_binding_v2 import (
    make_phase_v2_binding_verifier,
    make_phase_v2_proposal_action_terminal_verifier,
    make_phase_v2_repair_opportunity_verifier,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    make_phase_v3_binding_verifier,
    make_phase_v3_proposal_action_terminal_verifier,
    make_phase_v3_repair_opportunity_verifier,
)

from masbench.sft_pilot.schema import (
    PilotComponentBundleSnapshotV1,
    PilotComponentRecoverySnapshotV1,
    PilotCheckpointSemanticWitnessV1,
    PilotProtocolV1,
    canonical_sha256,
)
from masbench.sft_pilot.store import (
    PilotStateTransitionError,
    SingleWriterPilotStore,
)


PHASE_WORKING_FILENAME = "phase_registry.v8.json"
FACTOR_WORKING_FILENAME = "factor_bank.current.json"

FactorCapabilitiesFactory = Callable[
    [PhaseArtifactRegistry], Mapping[str, Any]
]


def _indexed(items: Sequence[Any], attribute: str) -> dict[str, Any]:
    return {str(getattr(item, attribute)): item for item in items}


def _one(items: Sequence[Any], message: str) -> Any:
    if len(items) != 1:
        raise PilotStateTransitionError(message)
    return items[0]


def _action_by_id(state: Any, action_id: str) -> Any:
    action = _indexed(state.proposal_actions, "action_id").get(action_id)
    if action is None:
        raise PilotStateTransitionError(
            "checkpoint action is absent from exact Factor state"
        )
    return action


def _terminal_attempt_receipt_sha256(attempt: Any) -> str:
    receipt = attempt.pair_execution_receipt or attempt.cancellation_receipt
    if receipt is None:
        raise PilotStateTransitionError(
            "terminal probe checkpoint lacks pair/cancellation evidence"
        )
    return canonical_sha256(receipt)


def _probe_stage_coordinates(
    protocol: PilotProtocolV1,
    attempt: Any,
    *,
    terminal: bool,
) -> tuple[str, str, str, str, str]:
    first = "source" if attempt.assignment.arm_order == "AB" else "target"
    pair_arm = (
        ("target" if first == "source" else "source") if terminal else first
    )
    candidates = tuple(
        arm
        for arm in protocol.authorized_logical_arms
        if (
            arm.execution_ordinal == attempt.ordinal
            and arm.pair_arm in {"source", "target"}
            and arm.operation_kind == f"{arm.pair_arm}_probe"
        )
    )
    grouped: dict[str, dict[str, Any]] = {}
    for arm in candidates:
        grouped.setdefault(arm.pair_id, {})[arm.pair_arm] = arm
    complete = tuple(
        (pair_id, arms)
        for pair_id, arms in grouped.items()
        if set(arms) == {"source", "target"}
    )
    pair_id, arms = _one(
        complete,
        "Factor attempt ordinal does not map to one frozen logical pair",
    )
    return (
        pair_arm,
        f"{pair_arm}_probe",
        pair_id,
        arms["source"].derive_logical_arm_key(protocol),
        arms["target"].derive_logical_arm_key(protocol),
    )


def derive_checkpoint_semantic_witness(
    *,
    protocol: PilotProtocolV1,
    phase_before: Any,
    phase_after: Any,
    factor_before: Any,
    factor_after: Any,
    prior: PilotCheckpointSemanticWitnessV1 | None,
) -> PilotCheckpointSemanticWitnessV1:
    """Uniquely derive the next checkpoint kind from native component states.

    The caller supplies no kind, action, owner, or arm.  Each predecessor has
    one admitted Factor lifecycle delta, and every probe/gate delta is joined
    back to the same committed proposal action and edge epoch.
    """

    if factor_after.event_seq <= factor_before.event_seq:
        raise PilotStateTransitionError(
            "component checkpoint requires a new Factor lifecycle event"
        )
    common = {
        "protocol_sha256": protocol.digest,
        "phase_state_before_sha256": canonical_sha256(phase_before),
        "phase_state_after_sha256": canonical_sha256(phase_after),
        "phase_sequence_before": phase_before.sequence,
        "phase_sequence_after": phase_after.sequence,
        "factor_state_before_sha256": factor_before.digest,
        "factor_state_after_sha256": factor_after.digest,
        "factor_event_seq_before": factor_before.event_seq,
        "factor_event_seq_after": factor_after.event_seq,
    }

    if prior is None:
        before_ids = {item.action_id for item in factor_before.proposal_actions}
        new_actions = tuple(
            item
            for item in factor_after.proposal_actions
            if item.action_id not in before_ids
        )
        action = _one(
            new_actions,
            "first checkpoint must add exactly one Factor ProposalAction",
        )
        if action.state != "prepared" or action.namespace_digest != (
            protocol.namespace.digest
        ):
            raise PilotStateTransitionError(
                "first checkpoint lacks one prepared action in the frozen namespace"
            )
        return PilotCheckpointSemanticWitnessV1(
            checkpoint_kind="action_prepared",
            action_id=action.action_id,
            action_branch=action.branch,
            action_producer_epoch=action.producer_epoch,
            action_intent_sha256=action.action_intent_sha256,
            proposal_action_after_sha256=canonical_sha256(action),
            proposal_action_after_state=action.state,
            expected_stage_operation_kind="proposal_generation",
            **common,
        )

    if prior.protocol_sha256 != protocol.digest:
        raise PilotStateTransitionError("prior checkpoint belongs to another protocol")
    action_before = _action_by_id(factor_before, prior.action_id)
    action_after = _action_by_id(factor_after, prior.action_id)
    if not (
        canonical_sha256(action_before) == prior.proposal_action_after_sha256
        and action_before.action_intent_sha256 == prior.action_intent_sha256
        and action_after.action_intent_sha256 == prior.action_intent_sha256
        and action_after.producer_epoch == prior.action_producer_epoch
        and action_after.branch == prior.action_branch
        and action_after.namespace_digest == protocol.namespace.digest
    ):
        raise PilotStateTransitionError(
            "checkpoint action/epoch does not continue its exact predecessor"
        )
    action_values = {
        "action_id": action_after.action_id,
        "action_branch": action_after.branch,
        "action_producer_epoch": action_after.producer_epoch,
        "action_intent_sha256": action_after.action_intent_sha256,
        "proposal_action_before_sha256": canonical_sha256(action_before),
        "proposal_action_after_sha256": canonical_sha256(action_after),
        "proposal_action_before_state": action_before.state,
        "proposal_action_after_state": action_after.state,
    }

    if prior.checkpoint_kind == "action_prepared":
        if action_before.state != "prepared":
            raise PilotStateTransitionError(
                "generation checkpoint predecessor is not prepared"
            )
        if action_after.branch in {"mutate", "fresh"}:
            lease = action_after.generation_lease
            if action_after.state != "executing" or lease is None:
                raise PilotStateTransitionError(
                    "generated action checkpoint lacks one started generation lease"
                )
            lease_sha = canonical_sha256(lease)
        else:
            if (
                action_after.state != "committed"
                or action_after.generation_lease is not None
                or action_after.transition_id is None
            ):
                raise PilotStateTransitionError(
                    "reuse action checkpoint lacks its committed transition"
                )
            lease_sha = None
        return PilotCheckpointSemanticWitnessV1(
            checkpoint_kind="generation_start_authorized",
            proposal_generation_lease_sha256=lease_sha,
            expected_stage_operation_kind="proposal_generation",
            **action_values,
            **common,
        )

    if prior.checkpoint_kind in {
        "generation_start_authorized", "probe_terminal"
    }:
        before_gate_ids = {
            item.decision_id for item in factor_before.gate_receipts
        }
        new_gates = tuple(
            item
            for item in factor_after.gate_receipts
            if item.decision_id not in before_gate_ids
        )
        if new_gates:
            if prior.checkpoint_kind != "probe_terminal":
                raise PilotStateTransitionError(
                    "gate cannot precede a terminal probe checkpoint"
                )
            receipt = _one(
                new_gates,
                "gate checkpoint must consume exactly one GateReceipt",
            )
            if action_before.state != "committed" or action_after.state != "committed":
                raise PilotStateTransitionError(
                    "gate checkpoint requires a committed proposal action"
                )
            opportunity = _indexed(
                factor_after.gate_opportunities, "opportunity_id"
            ).get(receipt.opportunity_id)
            if opportunity is None or not (
                opportunity.decision_id == receipt.decision_id
                and opportunity.state in {"consumed", "rejected", "capacity_rejected"}
            ):
                raise PilotStateTransitionError(
                    "GateReceipt lacks one terminal GateOpportunity"
                )
            assessment = _indexed(
                factor_after.assessments, "plan_id"
            ).get(opportunity.plan_id)
            plan = _indexed(factor_after.plans, "plan_id").get(
                opportunity.plan_id
            )
            if assessment is None or plan is None or not (
                assessment.settled
                and assessment.digest == receipt.settled_assessment_sha256
                and assessment.digest == opportunity.settled_assessment_sha256
                and plan.transition_id == action_after.transition_id
                and plan.epoch_id == prior.plan_epoch_id
                and plan.plan_id == prior.plan_id
            ):
                raise PilotStateTransitionError(
                    "gate checkpoint does not join its settled assessment/action epoch"
                )
            attempt = _indexed(factor_after.attempts, "attempt_id").get(
                prior.attempt_id
            )
            if attempt is None or attempt.state == "open":
                raise PilotStateTransitionError(
                    "gate checkpoint predecessor attempt is not terminal"
                )
            (
                _pair_arm,
                _operation_kind,
                probe_pair_id,
                probe_source_arm_key,
                probe_target_arm_key,
            ) = _probe_stage_coordinates(protocol, attempt, terminal=True)
            return PilotCheckpointSemanticWitnessV1(
                checkpoint_kind="gate_terminal",
                proposal_generation_lease_sha256=(
                    canonical_sha256(action_after.generation_lease)
                    if action_after.generation_lease is not None
                    else None
                ),
                plan_id=plan.plan_id,
                plan_sha256=plan.digest,
                plan_epoch_id=plan.epoch_id,
                attempt_id=attempt.attempt_id,
                attempt_sha256=canonical_sha256(attempt),
                attempt_state=attempt.state,
                attempt_ordinal=attempt.ordinal,
                probe_pair_id=probe_pair_id,
                probe_source_logical_arm_key=probe_source_arm_key,
                probe_target_logical_arm_key=probe_target_arm_key,
                terminal_execution_receipt_sha256=(
                    _terminal_attempt_receipt_sha256(attempt)
                ),
                assessment_id=assessment.assessment_id,
                assessment_sha256=assessment.digest,
                gate_opportunity_id=opportunity.opportunity_id,
                gate_opportunity_sha256=canonical_sha256(opportunity),
                gate_receipt_id=receipt.decision_id,
                gate_receipt_sha256=canonical_sha256(receipt),
                expected_stage_operation_kind="proposal_generation",
                **action_values,
                **common,
            )

        before_attempt_ids = {item.attempt_id for item in factor_before.attempts}
        new_attempts = tuple(
            item
            for item in factor_after.attempts
            if item.attempt_id not in before_attempt_ids
        )
        attempt = _one(
            new_attempts,
            "probe-open checkpoint must add exactly one Factor attempt",
        )
        plan = _indexed(factor_after.plans, "plan_id").get(attempt.plan_id)
        if action_after.state != "committed" or plan is None or not (
            attempt.state == "open"
            and action_after.transition_id is not None
            and plan.transition_id == action_after.transition_id
        ):
            raise PilotStateTransitionError(
                "probe-open checkpoint does not join its committed action edge"
            )
        if prior.plan_id is not None and prior.plan_id != plan.plan_id:
            raise PilotStateTransitionError(
                "probe retry changed the action-owned probe plan"
            )
        (
            pair_arm,
            operation_kind,
            probe_pair_id,
            probe_source_arm_key,
            probe_target_arm_key,
        ) = _probe_stage_coordinates(protocol, attempt, terminal=False)
        return PilotCheckpointSemanticWitnessV1(
            checkpoint_kind="probe_attempt_open",
            proposal_generation_lease_sha256=(
                canonical_sha256(action_after.generation_lease)
                if action_after.generation_lease is not None
                else None
            ),
            plan_id=plan.plan_id,
            plan_sha256=plan.digest,
            plan_epoch_id=plan.epoch_id,
            attempt_id=attempt.attempt_id,
            attempt_sha256=canonical_sha256(attempt),
            attempt_state=attempt.state,
            attempt_ordinal=attempt.ordinal,
            probe_pair_id=probe_pair_id,
            probe_source_logical_arm_key=probe_source_arm_key,
            probe_target_logical_arm_key=probe_target_arm_key,
            expected_stage_operation_kind=operation_kind,
            expected_stage_pair_arm=pair_arm,
            expected_stage_execution_ordinal=attempt.ordinal,
            **action_values,
            **common,
        )

    if prior.checkpoint_kind == "probe_attempt_open":
        attempt_before = _indexed(factor_before.attempts, "attempt_id").get(
            prior.attempt_id
        )
        attempt_after = _indexed(factor_after.attempts, "attempt_id").get(
            prior.attempt_id
        )
        plan = _indexed(factor_after.plans, "plan_id").get(prior.plan_id)
        if (
            attempt_before is None
            or attempt_after is None
            or plan is None
            or canonical_sha256(attempt_before) != prior.attempt_sha256
            or attempt_before.state != "open"
            or attempt_after.state
            not in {"complete", "incomplete", "quarantine", "cancelled"}
            or action_before.state != "committed"
            or action_after.state != "committed"
            or plan.transition_id != action_after.transition_id
            or plan.epoch_id != prior.plan_epoch_id
        ):
            raise PilotStateTransitionError(
                "probe-terminal checkpoint lacks the exact open attempt transition"
            )
        (
            pair_arm,
            operation_kind,
            probe_pair_id,
            probe_source_arm_key,
            probe_target_arm_key,
        ) = _probe_stage_coordinates(protocol, attempt_after, terminal=True)
        assessment = _indexed(factor_after.assessments, "plan_id").get(
            plan.plan_id
        )
        return PilotCheckpointSemanticWitnessV1(
            checkpoint_kind="probe_terminal",
            proposal_generation_lease_sha256=(
                canonical_sha256(action_after.generation_lease)
                if action_after.generation_lease is not None
                else None
            ),
            plan_id=plan.plan_id,
            plan_sha256=plan.digest,
            plan_epoch_id=plan.epoch_id,
            attempt_id=attempt_after.attempt_id,
            attempt_sha256=canonical_sha256(attempt_after),
            attempt_state=attempt_after.state,
            attempt_ordinal=attempt_after.ordinal,
            probe_pair_id=probe_pair_id,
            probe_source_logical_arm_key=probe_source_arm_key,
            probe_target_logical_arm_key=probe_target_arm_key,
            terminal_execution_receipt_sha256=(
                _terminal_attempt_receipt_sha256(attempt_after)
            ),
            assessment_id=(assessment.assessment_id if assessment else None),
            assessment_sha256=(assessment.digest if assessment else None),
            expected_stage_operation_kind=operation_kind,
            expected_stage_pair_arm=pair_arm,
            expected_stage_execution_ordinal=attempt_after.ordinal,
            **action_values,
            **common,
        )

    raise PilotStateTransitionError(
        "settled checkpoint must be promoted before another semantic transition"
    )


def phase_factor_capabilities(
    registry: PhaseArtifactRegistry,
) -> dict[str, Any]:
    """Dispatch exact capabilities by the proof's frozen binder profile."""

    direct_v2 = make_phase_v2_binding_verifier(registry)
    direct_v3 = make_phase_v3_binding_verifier(registry)
    terminal_v2 = make_phase_v2_proposal_action_terminal_verifier(registry)
    terminal_v3 = make_phase_v3_proposal_action_terminal_verifier(registry)
    repair_v2 = make_phase_v2_repair_opportunity_verifier(registry)
    repair_v3 = make_phase_v3_repair_opportunity_verifier(registry)

    def direct_binding_verifier(*args: Any) -> bool:
        if not args:
            return False
        binder = args[0].namespace.binder_version
        if binder == PHASE_FACTOR_BINDER_VERSION:
            return bool(direct_v2(*args))
        if binder == PHASE_FULL_FACTOR_BINDER_VERSION:
            return bool(direct_v3(*args))
        return False

    def repair_opportunity_verifier(*args: Any) -> bool:
        if len(args) != 3:
            return False
        binder = args[2].namespace.binder_version
        if binder == PHASE_FACTOR_BINDER_VERSION:
            return bool(repair_v2(*args))
        if binder == PHASE_FULL_FACTOR_BINDER_VERSION:
            return bool(repair_v3(*args))
        return False

    def proposal_action_terminal_verifier(*args: Any) -> bool:
        if len(args) != 3:
            return False
        binder = args[1].namespace.binder_version
        if binder == PHASE_FACTOR_BINDER_VERSION:
            return bool(terminal_v2(*args))
        if binder == PHASE_FULL_FACTOR_BINDER_VERSION:
            return bool(terminal_v3(*args))
        return False

    return {
        "direct_binding_verifier": direct_binding_verifier,
        "proposal_action_terminal_verifier": proposal_action_terminal_verifier,
        "repair_opportunity_verifier": repair_opportunity_verifier,
    }


def _require_component_key(value: bytes, name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 bytes")
    return bytes(value)


def _atomic_publish(path: Path, payload: bytes) -> None:
    """Replace one non-authoritative working mirror with exact committed bytes."""

    if type(payload) is not bytes or not payload:
        raise ValueError("component working payload must be non-empty exact bytes")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_empty_component_envelopes(
    state_dir: str | Path,
    *,
    phase_registry_key: bytes,
    factor_bank_key: bytes,
    manifests: Sequence[SourceManifest] = (),
    manifest_verifier: Callable[[SourceManifest], bool],
    factor_capabilities_factory: FactorCapabilitiesFactory = phase_factor_capabilities,
) -> tuple[bytes, bytes]:
    """Create exact empty/genesis envelopes before freezing ``PilotProtocolV1``.

    The returned bytes are suitable for ``component_bundle_state_sha256``.
    They contain only the explicitly supplied PUBLIC/TRAIN_UPDATE manifests;
    no benchmark row, prompt, response, answer, or scoring payload is accepted.
    """

    root = Path(state_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    phase_path = root / PHASE_WORKING_FILENAME
    factor_path = root / FACTOR_WORKING_FILENAME
    registry = PhaseArtifactRegistry(
        registry_key=_require_component_key(
            phase_registry_key, "phase_registry_key"
        ),
        manifests=tuple(manifests),
        manifest_verifier=manifest_verifier,
    )
    registry.save(phase_path)
    bank = FactorBankV2(
        state_key=_require_component_key(factor_bank_key, "factor_bank_key"),
        **dict(factor_capabilities_factory(registry)),
    )
    bank.save(factor_path)
    return phase_path.read_bytes(), factor_path.read_bytes()


@dataclass(frozen=True)
class PilotLoadedComponents:
    """One SQLite generation loaded through both native authenticated codecs."""

    snapshot: PilotComponentBundleSnapshotV1
    registry: PhaseArtifactRegistry
    bank: FactorBankV2


@dataclass(frozen=True)
class PilotLoadedRecoveryComponents:
    """One checkpoint/scientific recovery head loaded through native codecs."""

    snapshot: PilotComponentRecoverySnapshotV1
    registry: PhaseArtifactRegistry
    bank: FactorBankV2


class PilotComponentCoordinator:
    """Restore, mutate, verify, and atomically publish one component generation."""

    def __init__(
        self,
        *,
        store: SingleWriterPilotStore,
        phase_registry_key: bytes,
        factor_bank_key: bytes,
        manifest_verifier: Callable[[SourceManifest], bool],
        factor_capabilities_factory: FactorCapabilitiesFactory = phase_factor_capabilities,
        branch_receipt_verifier: Callable[[Any], bool] | None = None,
    ) -> None:
        if not store.protocol.component_bundle_required:
            raise PilotStateTransitionError(
                "component coordinator requires a bundle-authoritative protocol"
            )
        self._store = store
        self._phase_key = _require_component_key(
            phase_registry_key, "phase_registry_key"
        )
        self._factor_key = _require_component_key(
            factor_bank_key, "factor_bank_key"
        )
        self._manifest_verifier = manifest_verifier
        self._factor_capabilities_factory = factor_capabilities_factory
        # None keeps the registry read-only for branch receipts (mechanics
        # profiles); the executable profile installs a host verifier so
        # sealed generation actions can materialize.
        self._branch_receipt_verifier = branch_receipt_verifier
        self.phase_path = store.state_dir / PHASE_WORKING_FILENAME
        self.factor_path = store.state_dir / FACTOR_WORKING_FILENAME

    def _load_working_pair(
        self,
    ) -> tuple[PhaseArtifactRegistry, FactorBankV2]:
        registry = PhaseArtifactRegistry.load(
            self.phase_path,
            registry_key=self._phase_key,
            manifest_verifier=self._manifest_verifier,
            branch_receipt_verifier=self._branch_receipt_verifier,
        )
        bank = FactorBankV2.load(
            self.factor_path,
            state_key=self._factor_key,
            **dict(self._factor_capabilities_factory(registry)),
        )
        return registry, bank

    def _restore_snapshot_bytes(
        self,
        snapshot: PilotComponentBundleSnapshotV1 | PilotComponentRecoverySnapshotV1,
    ) -> None:
        _atomic_publish(
            self.phase_path,
            snapshot.phase_registry_envelope_bytes,
        )
        _atomic_publish(
            self.factor_path,
            snapshot.factor_bank_envelope_bytes,
        )

    def restore_latest(self) -> PilotLoadedComponents:
        """Discard sidecar drift and load the exact authoritative SQLite head."""

        if self._store.protocol.component_checkpoint_saga_required:
            raise PilotStateTransitionError(
                "checkpoint-saga protocols must restore the recovery head"
            )

        snapshot = self._store.latest_component_bundle()
        self._restore_snapshot_bytes(snapshot)
        registry, bank = self._load_working_pair()
        return PilotLoadedComponents(
            snapshot=snapshot,
            registry=registry,
            bank=bank,
        )

    def restore_recovery_head(self) -> PilotLoadedRecoveryComponents:
        """Restore an unpromoted checkpoint, else the promoted scientific head."""

        if not self._store.protocol.component_checkpoint_saga_required:
            raise PilotStateTransitionError(
                "protocol does not authorize component checkpoint recovery"
            )
        snapshot = self._store.latest_component_recovery_snapshot()
        self._restore_snapshot_bytes(snapshot)
        registry, bank = self._load_working_pair()
        return PilotLoadedRecoveryComponents(
            snapshot=snapshot,
            registry=registry,
            bank=bank,
        )

    def checkpoint_loaded(
        self,
        loaded: PilotLoadedRecoveryComponents,
        *,
        operation_id: str,
        operation_request_sha256: str,
    ) -> PilotLoadedRecoveryComponents:
        """Derive and publish one exact non-scientific recovery transition.

        Kind, action owner, and stage arm are deliberately absent from this
        API.  They are reconstructed from native component states and then
        independently joined to SQLite execution leases by the store.
        """

        if not self._store.protocol.component_checkpoint_saga_required:
            raise PilotStateTransitionError(
                "protocol does not authorize component checkpoints"
            )
        current = self._store.latest_component_recovery_snapshot()
        if current != loaded.snapshot:
            raise PilotStateTransitionError(
                "loaded components no longer match the exact recovery head"
            )
        try:
            phase_after_state = loaded.registry.to_state()
            factor_after_state = loaded.bank.to_state()
            loaded.registry.save(self.phase_path)
            loaded.bank.save(self.factor_path)
            phase_bytes = self.phase_path.read_bytes()
            factor_bytes = self.factor_path.read_bytes()
            # Reopen both native envelopes before they are eligible for the
            # SQLite outbox transaction.
            self._load_working_pair()

            # The loaded objects are the proposed after-state.  Restore and
            # open the exact authoritative before bytes separately so a
            # caller cannot relabel a Phase-only or stale Factor mutation.
            self._restore_snapshot_bytes(current)
            phase_before, factor_before = self._load_working_pair()
            witness = derive_checkpoint_semantic_witness(
                protocol=self._store.protocol,
                phase_before=phase_before.to_state(),
                phase_after=phase_after_state,
                factor_before=factor_before.to_state(),
                factor_after=factor_after_state,
                prior=(
                    current.checkpoint.semantic_witness
                    if current.checkpoint is not None
                    else None
                ),
            )
            _atomic_publish(self.phase_path, phase_bytes)
            _atomic_publish(self.factor_path, factor_bytes)
            self._load_working_pair()
            self._store._append_semantically_verified_component_checkpoint(
                operation_id=operation_id,
                operation_request_sha256=operation_request_sha256,
                semantic_witness=witness,
                previous_recovery_root_sha256=current.recovery_root_sha256,
                phase_registry_envelope_bytes=phase_bytes,
                factor_bank_envelope_bytes=factor_bytes,
            )
        except BaseException:
            self._restore_snapshot_bytes(current)
            raise
        return self.restore_recovery_head()

    def promote_settled_checkpoint(
        self,
        loaded: PilotLoadedRecoveryComponents,
        *,
        operation_id: str,
        owner_logical_execution_key: str,
        request_sha256: str,
    ) -> PilotLoadedComponents:
        """Atomically promote exact settled checkpoint bytes to science."""

        current = self._store.latest_component_recovery_snapshot()
        checkpoint = current.checkpoint
        if current != loaded.snapshot or checkpoint is None or not checkpoint.settled:
            raise PilotStateTransitionError(
                "scientific promotion requires the exact settled recovery head"
            )
        scientific_before = self._store.latest_component_bundle()
        try:
            self._store.append_component_scientific_commit(
                operation_id=operation_id,
                owner_logical_execution_key=owner_logical_execution_key,
                request_sha256=request_sha256,
                before_state_sha256=scientific_before.metadata.bundle_sha256,
                phase_registry_envelope_bytes=(
                    current.phase_registry_envelope_bytes
                ),
                factor_bank_envelope_bytes=current.factor_bank_envelope_bytes,
                settled_checkpoint_sha256=checkpoint.checkpoint_sha256,
            )
        except BaseException:
            self._restore_snapshot_bytes(current)
            raise
        scientific_after = self._store.latest_component_bundle()
        self._restore_snapshot_bytes(scientific_after)
        registry, bank = self._load_working_pair()
        return PilotLoadedComponents(
            snapshot=scientific_after,
            registry=registry,
            bank=bank,
        )

    def commit_loaded(
        self,
        loaded: PilotLoadedComponents,
        *,
        operation_id: str,
        owner_logical_execution_key: str,
        request_sha256: str,
    ) -> PilotLoadedComponents:
        """Publish a mutated pair or restore the prior committed bytes on failure."""

        if self._store.protocol.component_checkpoint_saga_required:
            raise PilotStateTransitionError(
                "checkpoint-saga protocols cannot bypass settled promotion"
            )

        current = self._store.latest_component_bundle()
        if current.metadata != loaded.snapshot.metadata:
            raise PilotStateTransitionError(
                "loaded components no longer match the authoritative generation"
            )
        try:
            loaded.registry.save(self.phase_path)
            loaded.bank.save(self.factor_path)
            phase_bytes = self.phase_path.read_bytes()
            factor_bytes = self.factor_path.read_bytes()
            if (
                phase_bytes == current.phase_registry_envelope_bytes
                and factor_bytes == current.factor_bank_envelope_bytes
            ):
                raise PilotStateTransitionError(
                    "scientific component commit cannot contain a semantic no-op"
                )
            # Native loaders own the inner HMAC and full-state validation.  Do
            # this before SQLite publication; a partially saved pair is never
            # allowed to become the recovery head.
            self._load_working_pair()
            self._store.append_component_scientific_commit(
                operation_id=operation_id,
                owner_logical_execution_key=owner_logical_execution_key,
                request_sha256=request_sha256,
                before_state_sha256=current.metadata.bundle_sha256,
                phase_registry_envelope_bytes=phase_bytes,
                factor_bank_envelope_bytes=factor_bytes,
            )
        except BaseException:
            self._restore_snapshot_bytes(current)
            raise
        return self.restore_latest()


__all__ = [
    "FACTOR_WORKING_FILENAME",
    "PHASE_WORKING_FILENAME",
    "FactorCapabilitiesFactory",
    "PilotComponentCoordinator",
    "PilotLoadedComponents",
    "PilotLoadedRecoveryComponents",
    "build_empty_component_envelopes",
    "derive_checkpoint_semantic_witness",
    "phase_factor_capabilities",
]
