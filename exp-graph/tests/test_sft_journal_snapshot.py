from __future__ import annotations

import hashlib
import hmac
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from exp_graph.mas.factor_bank import ExecutionNamespace
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
    VerifiedJournalSnapshot,
    journal_key_commitment_v1,
    journal_locator_commitment_v1,
    load_verified_snapshot,
)


JOURNAL_KEY = hashlib.sha256(b"snapshot-journal-key").digest()
READER_KEY = hashlib.sha256(b"snapshot-reader-key").digest()
MANIFEST_KEY = hashlib.sha256(b"snapshot-manifest-key").digest()
PROVIDER_EPOCH = hashlib.sha256(b"snapshot-provider-epoch").hexdigest()
MANIFEST_EPOCH = hashlib.sha256(b"snapshot-manifest-epoch").hexdigest()
READER_POLICY = hashlib.sha256(b"snapshot-reader-policy-v1").hexdigest()


def _h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_h(label)[:24]}"


def _namespace(*, goal: str = "sink") -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="silo",
        objective="balanced",
        information_goal=goal,
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=4,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="runner-v2",
        binder_version="phase-binder-v2",
        compiler_version="phase-compiler-v1",
    )


def _scope(*, goal: str = "sink") -> JournalScopeV2:
    namespace = _namespace(goal=goal)
    return JournalScopeV2(
        namespace=namespace,
        namespace_sha256=namespace.digest,
        planner_mode=namespace.planner_mode,
        information_goal=namespace.information_goal,
        worker_contract=namespace.worker_contract,
        mode_payload_sha256=_h("public-phase-program"),
        mode_payload_source="TRAIN_UPDATE",
        mode_payload_manifest_sha256=_h("safe-train-manifest"),
        runner_policy_sha256=_h("non-overlap-pair-runner-v2"),
    )


def _intent(tag: str) -> PreparePayloadV2:
    return PreparePayloadV2(
        attempt_id=_id("at", f"attempt:{tag}"),
        plan_id=_id("pp", f"plan:{tag}"),
        ordinal=0,
        assignment_receipt_sha256=_h(f"assignment:{tag}"),
        expected_open_attempt_sha256=_h(f"open:{tag}"),
        scheduled_arm_order="AB",
        runner_session_id=_id("rs", "snapshot-session"),
        runner_lease_token_sha256=_h(f"lease:{tag}"),
        verifier_epoch_sha256=_h("journal-verifier-v2"),
        source_arm_commitment_sha256=_h(f"source:{tag}"),
        target_arm_commitment_sha256=_h(f"target:{tag}"),
    )


class WriterManifestVerifier:
    """Concrete writer-side verifier used only to produce authenticated files."""

    def __init__(self, manifest_sha256: str) -> None:
        self._manifest_sha256 = manifest_sha256

    def __call__(self, scope: JournalScopeV2) -> bool:
        return bool(
            scope.mode_payload_source in {"PUBLIC", "TRAIN_UPDATE"}
            and scope.mode_payload_manifest_sha256 == self._manifest_sha256
        )


class LinearCheckpointProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.latest: dict[str, JournalCheckpointV2] = {}
        self.pending: dict[str, CheckpointUpdateClaimV2] = {}
        self.inspect_calls = 0
        self.inspect_hook: FileReplaceOnInspect | None = None
        self.return_journal_id: str | None = None
        self.provider_epoch_sha256 = PROVIDER_EPOCH
        self.snapshot_inspect_barrier: SnapshotInspectBarrier | None = None
        self.claim_observed = threading.Event()

    def bootstrap(self, checkpoint: JournalCheckpointV2) -> None:
        self.latest[checkpoint.journal_id] = checkpoint

    def inspect(self, journal_id: str) -> CheckpointProviderSnapshotV2:
        with self._lock:
            self.inspect_calls += 1
            hook = self.inspect_hook
            self.inspect_hook = None
            snapshot = CheckpointProviderSnapshotV2(
                journal_id=self.return_journal_id or journal_id,
                provider_epoch_sha256=self.provider_epoch_sha256,
                latest_checkpoint=(
                    None
                    if self.return_journal_id is not None
                    else self.latest.get(journal_id)
                ),
                pending_claim=self.pending.get(journal_id),
            )
            barrier = self.snapshot_inspect_barrier
            should_pause = bool(barrier is not None and barrier.claim_reader_slot())
        if should_pause:
            assert barrier is not None
            barrier.observed.set()
            if not barrier.resume.wait(timeout=5):
                raise RuntimeError("snapshot inspect barrier timed out")
        if hook is not None:
            hook.replace()
        return snapshot

    def claim_update(
        self,
        *,
        journal_id: str,
        expected_checkpoint: JournalCheckpointV2,
        proposed_checkpoint: JournalCheckpointV2,
    ) -> CheckpointUpdateClaimV2:
        with self._lock:
            if self.latest.get(journal_id) != expected_checkpoint:
                raise RuntimeError("checkpoint CAS failed")
            if journal_id in self.pending:
                raise RuntimeError("checkpoint update already pending")
            claim = CheckpointUpdateClaimV2(
                claim_token_sha256=_h(
                    expected_checkpoint.digest + proposed_checkpoint.digest
                ),
                journal_id=journal_id,
                expected_checkpoint=expected_checkpoint,
                proposed_checkpoint=proposed_checkpoint,
                provider_epoch_sha256=self.provider_epoch_sha256,
            )
            self.pending[journal_id] = claim
            self.claim_observed.set()
            return claim

    def ack(self, journal_id: str, checkpoint: JournalCheckpointV2) -> None:
        with self._lock:
            claim = self.pending[journal_id]
            if claim.proposed_checkpoint != checkpoint:
                raise RuntimeError("wrong checkpoint acknowledgement")
            self.latest[journal_id] = checkpoint
            del self.pending[journal_id]

    def force_latest(
        self,
        journal_id: str,
        checkpoint: JournalCheckpointV2,
        *,
        clear_pending: bool = True,
    ) -> None:
        with self._lock:
            self.latest[journal_id] = checkpoint
            if clear_pending:
                self.pending.pop(journal_id, None)


class RegistryLocatorResolver:
    """Concrete registry with an immutable pin and independently mutable result."""

    def __init__(
        self,
        *,
        locator_id: str,
        journal_id: str,
        registered_path: Path,
    ) -> None:
        self.locator_id = locator_id
        self.journal_id = journal_id
        self.registered_path = registered_path.resolve()
        self.resolved_path = self.registered_path
        self._pinned = journal_locator_commitment_v1(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
            resolved_path=self.registered_path,
        )

    def _check(self, journal_locator_id: str, expected_journal_id: str) -> None:
        if (journal_locator_id, expected_journal_id) != (
            self.locator_id,
            self.journal_id,
        ):
            raise KeyError("unknown journal locator tuple")

    def resolve_journal_path(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> Path:
        self._check(journal_locator_id, expected_journal_id)
        return self.resolved_path

    def pinned_locator_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        self._check(journal_locator_id, expected_journal_id)
        return self._pinned


class RegistryKeyResolver:
    """Concrete registry: returned bytes can be faulted without changing pins."""

    def __init__(self, *, locator_id: str, journal_id: str) -> None:
        self.locator_id = locator_id
        self.journal_id = journal_id
        self.journal_key = JOURNAL_KEY
        self.reader_key = READER_KEY
        self._journal_pin = journal_key_commitment_v1(
            role="journal", key=JOURNAL_KEY
        )
        self._reader_pin = journal_key_commitment_v1(role="reader", key=READER_KEY)

    def _check(self, journal_locator_id: str, expected_journal_id: str) -> None:
        if (journal_locator_id, expected_journal_id) != (
            self.locator_id,
            self.journal_id,
        ):
            raise KeyError("unknown journal key tuple")

    def resolve_journal_hmac_key(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> bytes:
        self._check(journal_locator_id, expected_journal_id)
        return self.journal_key

    def resolve_reader_hmac_key(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> bytes:
        self._check(journal_locator_id, expected_journal_id)
        return self.reader_key

    def pinned_journal_key_commitment_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        self._check(journal_locator_id, expected_journal_id)
        return self._journal_pin

    def pinned_reader_key_commitment_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        self._check(journal_locator_id, expected_journal_id)
        return self._reader_pin

    def reader_policy_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        self._check(journal_locator_id, expected_journal_id)
        return READER_POLICY


class HMACScopeManifestVerifier:
    def __init__(self) -> None:
        self.manifest_sha256 = _h("safe-train-manifest")
        self.tamper_attestation = False
        self.raw_source: str | None = None
        self.calls = 0
        self.verifier_key = MANIFEST_KEY
        self.verifier_epoch_sha256 = MANIFEST_EPOCH

    def _body(self, scope: JournalScopeV2) -> dict[str, Any]:
        return {
            "verification_version": "sft_scope_manifest_verification_v1",
            "manifest_sha256": self.manifest_sha256,
            "source": self.raw_source or scope.mode_payload_source,
            "scope_sha256": scope.digest,
            "verifier_epoch_sha256": self.verifier_epoch_sha256,
        }

    def verify_scope_manifest(
        self,
        scope: JournalScopeV2,
    ) -> ScopeManifestVerificationV1 | dict[str, Any]:
        self.calls += 1
        body = self._body(scope)
        attestation = journal_fixed_hmac_sha256_v2(
            self.verifier_key,
            domain="sft-scope-manifest-verification-v1",
            value=body,
        )
        if self.tamper_attestation:
            attestation = _h("tampered-manifest-attestation")
        raw = {**body, "verifier_attestation_sha256": attestation}
        if self.raw_source is not None:
            return raw
        return ScopeManifestVerificationV1(**raw)

    def validate_scope_manifest_verification(
        self,
        *,
        scope: JournalScopeV2,
        verification: ScopeManifestVerificationV1,
    ) -> None:
        body = verification.model_dump(
            mode="python", exclude={"verifier_attestation_sha256"}
        )
        expected = journal_fixed_hmac_sha256_v2(
            self.verifier_key,
            domain="sft-scope-manifest-verification-v1",
            value=body,
        )
        if not hmac.compare_digest(
            verification.verifier_attestation_sha256,
            expected,
        ):
            raise ValueError("manifest verifier HMAC mismatch")
        if verification.scope_sha256 != scope.digest:
            raise ValueError("manifest verification scope mismatch")

    def verifier_policy_sha256(self) -> str:
        return journal_canonical_sha256_v2(
            {
                "policy_version": "test_scope_manifest_verifier_policy_v1",
                "verifier_epoch_sha256": self.verifier_epoch_sha256,
                "verifier_key_sha256": hashlib.sha256(
                    self.verifier_key
                ).hexdigest(),
            }
        )


class FileReplaceOnInspect:
    def __init__(self, path: Path, replacement: bytes) -> None:
        self.path = path
        self.replacement = replacement

    def replace(self) -> None:
        self.path.write_bytes(self.replacement)


class SnapshotInspectBarrier:
    """Pause exactly the first provider read after the barrier is installed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed = False
        self.observed = threading.Event()
        self.resume = threading.Event()

    def claim_reader_slot(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True


@dataclass
class SnapshotFixture:
    journal: SFTRunnerJournal
    provider: LinearCheckpointProvider
    path: Path
    locator_id: str
    journal_id: str
    scope: JournalScopeV2
    locator: RegistryLocatorResolver
    keys: RegistryKeyResolver
    manifest: HMACScopeManifestVerifier
    trust_policy: SnapshotTrustPolicyV1


def _persist_empty(
    tmp_path: Path,
    *,
    name: str = "main",
    journal_id: str | None = None,
    provider: LinearCheckpointProvider | None = None,
) -> SnapshotFixture:
    scope = _scope()
    journal_id = journal_id or _id("jr", f"journal:{name}")
    locator_id = _id("jl", f"locator:{name}")
    provider = provider or LinearCheckpointProvider()
    journal = SFTRunnerJournal(
        journal_key=JOURNAL_KEY,
        journal_id=journal_id,
        scope=scope,
        checkpoint_provider=provider,
        scope_manifest_verifier=WriterManifestVerifier(
            scope.mode_payload_manifest_sha256
        ),
    )
    provider.bootstrap(journal.checkpoint())
    path = tmp_path / f"{name}.json"
    journal.save(path)
    locator = RegistryLocatorResolver(
        locator_id=locator_id,
        journal_id=journal_id,
        registered_path=path,
    )
    keys = RegistryKeyResolver(locator_id=locator_id, journal_id=journal_id)
    manifest = HMACScopeManifestVerifier()
    trust_policy = SnapshotTrustPolicyV1(
        journal_locator_id=locator_id,
        journal_id=journal_id,
        scope_sha256=scope.digest,
        journal_locator_sha256=locator.pinned_locator_sha256(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
        ),
        journal_key_commitment_sha256=keys.pinned_journal_key_commitment_sha256(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
        ),
        reader_key_commitment_sha256=keys.pinned_reader_key_commitment_sha256(
            journal_locator_id=locator_id,
            expected_journal_id=journal_id,
        ),
        reader_policy_sha256=READER_POLICY,
        provider_epoch_sha256=PROVIDER_EPOCH,
        manifest_verifier_epoch_sha256=MANIFEST_EPOCH,
        manifest_verifier_policy_sha256=manifest.verifier_policy_sha256(),
    )
    return SnapshotFixture(
        journal=journal,
        provider=provider,
        path=path,
        locator_id=locator_id,
        journal_id=journal_id,
        scope=scope,
        locator=locator,
        keys=keys,
        manifest=manifest,
        trust_policy=trust_policy,
    )


def _load(fixture: SnapshotFixture, *, expected_scope: JournalScopeV2 | None = None):
    return load_verified_snapshot(
        journal_locator_id=fixture.locator_id,
        expected_journal_id=fixture.journal_id,
        expected_scope=expected_scope or fixture.scope,
        expected_trust_policy=fixture.trust_policy,
        journal_key_resolver=fixture.keys,
        journal_locator_resolver=fixture.locator,
        checkpoint_provider=fixture.provider,
        scope_manifest_verifier=fixture.manifest,
    )


def test_canonical_digest_and_fixed_domain_hmac_have_fixed_vectors() -> None:
    value = {"b": [2, 1], "a": "x"}
    key = hashlib.sha256(b"fixed-reader-key").digest()
    assert journal_canonical_sha256_v2(value) == (
        "1bb141b0beaf4ebf42280d226d19296aa9bcde08525419393fa8c706e6a57148"
    )
    assert journal_fixed_hmac_sha256_v2(
        key,
        domain="sft-journal-snapshot-reader-v1",
        value=value,
    ) == "3d7aa7d20f6ba716853e3399e29bea518a496637a15c64a7b9f7d7601440bf32"
    with pytest.raises(ValueError, match="unreviewed"):
        journal_fixed_hmac_sha256_v2(
            key,
            domain="arbitrary-domain",  # type: ignore[arg-type]
            value=value,
        )


def test_fresh_snapshot_commits_exact_envelope_provider_manifest_and_policy(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    snapshot = _load(fixture)
    receipt = snapshot.receipt

    assert receipt.state == fixture.journal.state
    assert receipt.checkpoint == fixture.journal.checkpoint()
    assert receipt.envelope_sha256 == hashlib.sha256(
        fixture.path.read_bytes()
    ).hexdigest()
    assert receipt.provider_pending is False
    assert receipt.authority_scope == snapshot.authority_scope == "observation_only"
    assert receipt.trust_policy_sha256 == fixture.trust_policy.digest
    assert receipt.provider_epoch_sha256 == PROVIDER_EPOCH
    assert receipt.reader_policy_sha256 == READER_POLICY
    assert receipt.scope_verification.manifest_sha256 == (
        fixture.scope.mode_payload_manifest_sha256
    )
    assert receipt.journal_locator_sha256 == journal_locator_commitment_v1(
        journal_locator_id=fixture.locator_id,
        expected_journal_id=fixture.journal_id,
        resolved_path=fixture.path,
    )
    assert receipt.reader_attestation_sha256 == journal_fixed_hmac_sha256_v2(
        READER_KEY,
        domain="sft-journal-snapshot-reader-v1",
        value=receipt.attestation_body,
    )
    text = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    assert str(fixture.path) not in text
    assert JOURNAL_KEY.hex() not in text and READER_KEY.hex() not in text


def test_every_load_reinspects_provider_and_reverifies_manifest(tmp_path: Path) -> None:
    fixture = _persist_empty(tmp_path)
    before_inspect = fixture.provider.inspect_calls
    _load(fixture)
    _load(fixture)
    assert fixture.provider.inspect_calls == before_inspect + 2
    assert fixture.manifest.calls == 2


def test_pending_claim_and_old_idempotent_event_never_grant_snapshot_authority(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    intent = _intent("pending")
    old_event = fixture.journal.prepare_attempt(intent)
    assert fixture.journal.prepare_attempt(intent) == old_event
    with pytest.raises(RuntimeError, match="awaits owner acknowledgement"):
        _load(fixture)


def test_provider_stale_ahead_and_same_sequence_fork_all_fail(tmp_path: Path) -> None:
    stale = _persist_empty(tmp_path, name="stale")
    empty_checkpoint = stale.journal.checkpoint()
    stale.journal.prepare_attempt(_intent("stale"))
    stale.provider.force_latest(stale.journal_id, empty_checkpoint)
    with pytest.raises(RuntimeError, match="latest checkpoint differs"):
        _load(stale)

    ahead = _persist_empty(tmp_path, name="ahead")
    empty_bytes = ahead.path.read_bytes()
    ahead.journal.prepare_attempt(_intent("ahead"))
    ahead.provider.ack(ahead.journal_id, ahead.journal.checkpoint())
    ahead.path.write_bytes(empty_bytes)
    with pytest.raises(RuntimeError, match="latest checkpoint differs"):
        _load(ahead)

    shared_journal_id = _id("jr", "forked-journal")
    branch_a = _persist_empty(tmp_path, name="fork-a", journal_id=shared_journal_id)
    branch_b = _persist_empty(tmp_path, name="fork-b", journal_id=shared_journal_id)
    branch_a.journal.prepare_attempt(_intent("branch-a"))
    branch_a.provider.ack(shared_journal_id, branch_a.journal.checkpoint())
    branch_b.journal.prepare_attempt(_intent("branch-b"))
    branch_b.provider.ack(shared_journal_id, branch_b.journal.checkpoint())
    branch_b.provider = branch_a.provider
    with pytest.raises(RuntimeError, match="latest checkpoint differs"):
        _load(branch_b)


def test_locator_path_and_both_key_substitutions_fail_closed(tmp_path: Path) -> None:
    fixture = _persist_empty(tmp_path, name="locator-main")
    other = _persist_empty(tmp_path, name="locator-other")
    fixture.locator.resolved_path = other.path
    with pytest.raises(ValueError, match="pinned locator"):
        _load(fixture)

    fixture.locator.resolved_path = fixture.path
    fixture.keys.journal_key = hashlib.sha256(b"wrong-journal-key").digest()
    with pytest.raises(ValueError, match="journal key differs"):
        _load(fixture)

    fixture.keys.journal_key = JOURNAL_KEY
    fixture.keys.reader_key = hashlib.sha256(b"wrong-reader-key").digest()
    with pytest.raises(ValueError, match="reader key differs"):
        _load(fixture)


def test_wrong_scope_manifest_attestation_and_test_label_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    with pytest.raises(ValueError, match="trust policy differs|persisted scope"):
        _load(fixture, expected_scope=_scope(goal="all_agents"))

    fixture.manifest.manifest_sha256 = _h("unapproved-manifest")
    with pytest.raises(ValueError, match="differs from expected scope"):
        _load(fixture)

    fixture.manifest.manifest_sha256 = _h("safe-train-manifest")
    fixture.manifest.tamper_attestation = True
    with pytest.raises(RuntimeError, match="attestation was rejected"):
        _load(fixture)

    fixture.manifest.tamper_attestation = False
    fixture.manifest.raw_source = "TEST"
    with pytest.raises(ValidationError, match="PUBLIC|TRAIN_UPDATE"):
        _load(fixture)


def test_host_trust_policy_rejects_substitute_provider_and_manifest_verifier(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    fixture.provider.provider_epoch_sha256 = _h("substitute-provider-epoch")
    with pytest.raises(ValueError, match="provider epoch differs"):
        _load(fixture)

    fixture.provider.provider_epoch_sha256 = PROVIDER_EPOCH
    fixture.manifest.verifier_key = hashlib.sha256(
        b"self-validating-substitute-manifest-key"
    ).digest()
    # The substitute issues and validates its own internally consistent HMAC,
    # but its independently pinned host policy identity is different.
    with pytest.raises(ValueError, match="verifier policy differs"):
        _load(fixture)


def test_envelope_tamper_and_v1_schema_never_gain_snapshot_authority(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    raw = json.loads(fixture.path.read_text())
    raw["state"]["head_event_sha256"] = _h("tampered-head")
    fixture.path.write_text(json.dumps(raw))
    with pytest.raises((ValidationError, ValueError), match="head|digest|HMAC"):
        _load(fixture)

    fixture = _persist_empty(tmp_path, name="legacy")
    raw = json.loads(fixture.path.read_text())
    raw["state"]["schema_version"] = "sft_runner_journal_v1"
    fixture.path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="v1"):
        _load(fixture)


def test_duplicate_json_object_keys_are_rejected_before_authentication(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    raw = json.loads(fixture.path.read_text())
    duplicate = (
        "{\n"
        f'  "state_sha256": "{raw["state_sha256"]}",\n'
        + fixture.path.read_text().lstrip()[2:]
    )
    fixture.path.write_text(duplicate)
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        _load(fixture)


def test_wrong_provider_identity_and_file_replace_race_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    fixture.provider.return_journal_id = _id("jr", "wrong-provider-journal")
    with pytest.raises((ValidationError, ValueError), match="wrong journal|crosses"):
        _load(fixture)

    fixture.provider.return_journal_id = None
    fixture.provider.inspect_hook = FileReplaceOnInspect(fixture.path, b"{}\n")
    with pytest.raises(RuntimeError, match="changed during"):
        _load(fixture)


def test_snapshot_has_no_writer_or_provider_ack_surface_and_no_public_constructor(
    tmp_path: Path,
) -> None:
    fixture = _persist_empty(tmp_path)
    snapshot = _load(fixture)
    for forbidden in (
        "save",
        "prepare_attempt",
        "start_arm",
        "finish_arm",
        "complete_pair",
        "cancel_attempt",
        "claim_update",
        "ack",
        "authorize_execution",
        "release_execution",
        "consume",
    ):
        assert not hasattr(snapshot, forbidden)
    with pytest.raises(ValueError, match="fresh authenticated load"):
        VerifiedJournalSnapshot(snapshot.receipt)

    lock_path = fixture.path.with_suffix(fixture.path.suffix + ".lock")
    lock_path.unlink()
    with pytest.raises(FileNotFoundError):
        _load(fixture)
    assert not lock_path.exists()  # a reader never recreates writer state


def test_claim_before_file_lock_can_expire_observation_but_never_authorize_execution(
    tmp_path: Path,
) -> None:
    provider = LinearCheckpointProvider()
    fixture = _persist_empty(tmp_path, name="claim-race", provider=provider)
    barrier = SnapshotInspectBarrier()
    provider.snapshot_inspect_barrier = barrier

    with ThreadPoolExecutor(max_workers=2) as executor:
        snapshot_future = executor.submit(_load, fixture)
        assert barrier.observed.wait(timeout=5)
        writer_future = executor.submit(
            fixture.journal.prepare_attempt,
            _intent("claim-race"),
        )
        assert provider.claim_observed.wait(timeout=5)
        # Writer has claimed provider C(A)->C(B) and is blocked by the
        # reader's shared file lock before publishing B.
        barrier.resume.set()
        observation = snapshot_future.result(timeout=5)
        writer_future.result(timeout=5)

    live = provider.inspect(fixture.journal_id)
    assert observation.receipt.provider_pending is False  # historical cut
    assert live.pending_claim is not None  # it expired before caller use
    assert observation.authority_scope == "observation_only"
    assert not hasattr(observation, "authorize_execution")


def test_snapshot_receipts_reject_extra_oracle_and_test_fields(tmp_path: Path) -> None:
    receipt = _load(_persist_empty(tmp_path)).receipt
    raw = receipt.model_dump(mode="python")
    raw["expected_output"] = "secret"
    with pytest.raises(ValidationError, match="Extra inputs"):
        type(receipt).model_validate(raw)

    manifest = receipt.scope_verification.model_dump(mode="python")
    manifest["source"] = "TEST"
    with pytest.raises(ValidationError, match="PUBLIC|TRAIN_UPDATE"):
        ScopeManifestVerificationV1.model_validate(manifest)
