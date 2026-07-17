from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.sft_journal import (
    CheckpointProviderSnapshotV2,
    CheckpointUpdateClaimV2,
    JournalCheckpointV2,
    JournalScopeV2,
    LegacyRunnerJournalRejected,
    MAX_JOURNAL_EVENTS,
    PreparePayloadV2,
    SFTRunnerJournal,
    derive_host_opaque_id_v2,
)


KEY = hashlib.sha256(b"sft-runner-journal-v2-test-key").digest()
PROVIDER_EPOCH = hashlib.sha256(b"checkpoint-provider-v1").hexdigest()


def _h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_h(label)[:24]}"


class InMemoryCheckpointProvider:
    """Linearizable test authority; ``ack`` represents an external owner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, JournalCheckpointV2] = {}
        self._pending: dict[str, CheckpointUpdateClaimV2] = {}

    def bootstrap(self, checkpoint: JournalCheckpointV2) -> None:
        with self._lock:
            if checkpoint.journal_id in self._latest:
                raise RuntimeError("checkpoint already bootstrapped")
            self._latest[checkpoint.journal_id] = checkpoint

    def inspect(self, journal_id: str) -> CheckpointProviderSnapshotV2:
        with self._lock:
            return CheckpointProviderSnapshotV2(
                journal_id=journal_id,
                provider_epoch_sha256=PROVIDER_EPOCH,
                latest_checkpoint=self._latest.get(journal_id),
                pending_claim=self._pending.get(journal_id),
            )

    def claim_update(
        self,
        *,
        journal_id: str,
        expected_checkpoint: JournalCheckpointV2,
        proposed_checkpoint: JournalCheckpointV2,
    ) -> CheckpointUpdateClaimV2:
        with self._lock:
            if journal_id in self._pending:
                raise RuntimeError("another update is pending")
            if self._latest.get(journal_id) != expected_checkpoint:
                raise RuntimeError("latest checkpoint compare-and-swap failed")
            claim = CheckpointUpdateClaimV2(
                claim_token_sha256=_h(
                    expected_checkpoint.digest + proposed_checkpoint.digest
                ),
                journal_id=journal_id,
                expected_checkpoint=expected_checkpoint,
                proposed_checkpoint=proposed_checkpoint,
                provider_epoch_sha256=PROVIDER_EPOCH,
            )
            self._pending[journal_id] = claim
            return claim

    def ack(self, journal_id: str, expected: JournalCheckpointV2) -> None:
        """External owner calls this only after verifying the published file."""

        with self._lock:
            claim = self._pending.get(journal_id)
            if claim is None or claim.proposed_checkpoint != expected:
                raise RuntimeError("no exact proposed checkpoint to acknowledge")
            self._latest[journal_id] = claim.proposed_checkpoint
            del self._pending[journal_id]

    def pending(self, journal_id: str) -> CheckpointUpdateClaimV2 | None:
        with self._lock:
            return self._pending.get(journal_id)


class ManifestVerifier:
    def __init__(self, allowed_manifest_sha256: str) -> None:
        self.allowed_manifest_sha256 = allowed_manifest_sha256
        self.calls = 0

    def __call__(self, scope: JournalScopeV2) -> bool:
        self.calls += 1
        return bool(
            scope.mode_payload_source in {"PUBLIC", "TRAIN_UPDATE"}
            and scope.mode_payload_manifest_sha256
            == self.allowed_manifest_sha256
        )


def _namespace(
    *,
    goal: str = "sink",
    mode: str = "program_generate",
) -> ExecutionNamespace:
    payload = (
        "phase_program_skill_v1"
        if mode == "program_generate"
        else "graph_skill_v1"
    )
    return ExecutionNamespace(
        task_family="silo",
        objective="balanced",
        information_goal=goal,
        planner_mode=mode,
        payload_format=payload,
        worker_contract="not_applicable",
        n_agents=4,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="runner-v2",
        binder_version="phase-binder-v2",
        compiler_version="phase-compiler-v1",
    )


def _scope(
    *,
    goal: str = "sink",
    mode: str = "program_generate",
    manifest_sha256: str | None = None,
) -> JournalScopeV2:
    namespace = _namespace(goal=goal, mode=mode)
    return JournalScopeV2(
        namespace=namespace,
        namespace_sha256=namespace.digest,
        planner_mode=namespace.planner_mode,
        information_goal=namespace.information_goal,
        worker_contract=namespace.worker_contract,
        mode_payload_sha256=_h("public-phase-program"),
        mode_payload_source="TRAIN_UPDATE",
        mode_payload_manifest_sha256=manifest_sha256 or _h("safe-train-manifest"),
        runner_policy_sha256=_h("non-overlap-pair-runner-v2"),
    )


def _intent(tag: str = "one", *, order: str = "AB") -> PreparePayloadV2:
    return PreparePayloadV2(
        attempt_id=_id("at", f"attempt:{tag}"),
        plan_id=_id("pp", f"plan:{tag}"),
        ordinal=0,
        assignment_receipt_sha256=_h(f"assignment:{tag}"),
        expected_open_attempt_sha256=_h(f"open:{tag}"),
        scheduled_arm_order=order,
        runner_session_id=_id("rs", "runner-session"),
        runner_lease_token_sha256=_h(f"lease:{tag}"),
        verifier_epoch_sha256=_h("journal-verifier-v2"),
        source_arm_commitment_sha256=_h(f"source-input:{tag}"),
        target_arm_commitment_sha256=_h(f"target-input:{tag}"),
    )


def _create_unbound(
    *,
    provider: InMemoryCheckpointProvider | None = None,
    verifier: ManifestVerifier | None = None,
    scope: JournalScopeV2 | None = None,
) -> tuple[SFTRunnerJournal, InMemoryCheckpointProvider, ManifestVerifier]:
    provider = provider or InMemoryCheckpointProvider()
    verifier = verifier or ManifestVerifier(_h("safe-train-manifest"))
    journal = SFTRunnerJournal(
        journal_key=KEY,
        journal_id=_id("jr", "pilot-journal"),
        scope=scope or _scope(),
        checkpoint_provider=provider,
        scope_manifest_verifier=verifier,
    )
    return journal, provider, verifier


def _persist_empty(
    tmp_path: Path,
    *,
    provider: InMemoryCheckpointProvider | None = None,
    verifier: ManifestVerifier | None = None,
    scope: JournalScopeV2 | None = None,
) -> tuple[SFTRunnerJournal, InMemoryCheckpointProvider, ManifestVerifier, Path]:
    journal, provider, verifier = _create_unbound(
        provider=provider,
        verifier=verifier,
        scope=scope,
    )
    provider.bootstrap(journal.checkpoint())
    path = tmp_path / "journal.json"
    journal.save(path)
    return journal, provider, verifier, path


def _ack(journal: SFTRunnerJournal, provider: InMemoryCheckpointProvider) -> None:
    provider.ack(journal.state.journal_id, journal.checkpoint())


def _append_and_ack(journal, provider, operation):
    event = operation()
    _ack(journal, provider)
    return event


def _complete_pair(
    journal: SFTRunnerJournal,
    provider: InMemoryCheckpointProvider,
    intent: PreparePayloadV2 | None = None,
) -> tuple:
    intent = intent or _intent()
    first, second = (
        ("source", "target")
        if intent.scheduled_arm_order == "AB"
        else ("target", "source")
    )
    events = [
        _append_and_ack(journal, provider, lambda: journal.prepare_attempt(intent)),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.start_arm(
                intent.attempt_id,
                arm=first,
                physical_root_id=_h(f"{first}-root"),
            ),
        ),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.finish_arm(intent.attempt_id, arm=first),
        ),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.start_arm(
                intent.attempt_id,
                arm=second,
                physical_root_id=_h(f"{second}-root"),
            ),
        ),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.finish_arm(intent.attempt_id, arm=second),
        ),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.complete_pair(intent.attempt_id),
        ),
    ]
    return tuple(events)


def test_single_attempt_complete_pair_is_generation_one_and_six_events(
    tmp_path: Path,
) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    events = _complete_pair(journal, provider)

    assert journal.state.sequence == MAX_JOURNAL_EVENTS == 6
    assert journal.state.fencing_generation == 1
    assert all(item.fencing_generation == 1 for item in events)
    assert tuple(item.sequence for item in events) == tuple(range(1, 7))
    assert events[2].sequence < events[3].sequence  # first finish before second start
    assert events[-1].payload.prepare == events[0].ref
    with pytest.raises(ValueError, match="one journal"):
        journal.prepare_attempt(_intent("second"))


@pytest.mark.parametrize("order,wrong_first", [("AB", "target"), ("BA", "source")])
def test_start_arm_enforces_scheduled_prefix_immediately(
    tmp_path: Path,
    order: str,
    wrong_first: str,
) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    intent = _intent(order=order)
    _append_and_ack(journal, provider, lambda: journal.prepare_attempt(intent))

    before = journal.scientific_state_sha256
    with pytest.raises(ValueError, match="scheduled prefix"):
        journal.start_arm(
            intent.attempt_id,
            arm=wrong_first,
            physical_root_id=_h("wrong-root"),
        )
    assert journal.scientific_state_sha256 == before
    assert provider.pending(journal.state.journal_id) is None


def test_second_arm_cannot_overlap_first(tmp_path: Path) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    intent = _intent(order="AB")
    _append_and_ack(journal, provider, lambda: journal.prepare_attempt(intent))
    _append_and_ack(
        journal,
        provider,
        lambda: journal.start_arm(
            intent.attempt_id,
            arm="source",
            physical_root_id=_h("source-root"),
        ),
    )

    with pytest.raises(ValueError, match="before the first arm finishes"):
        journal.start_arm(
            intent.attempt_id,
            arm="target",
            physical_root_id=_h("target-root"),
        )
    _append_and_ack(
        journal,
        provider,
        lambda: journal.finish_arm(intent.attempt_id, arm="source"),
    )
    target = _append_and_ack(
        journal,
        provider,
        lambda: journal.start_arm(
            intent.attempt_id,
            arm="target",
            physical_root_id=_h("target-root"),
        ),
    )
    assert target.sequence == 4


def test_idempotent_arm_lookup_never_crosses_attempt_identity(tmp_path: Path) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    intent = _intent()
    _append_and_ack(journal, provider, lambda: journal.prepare_attempt(intent))
    _append_and_ack(
        journal,
        provider,
        lambda: journal.start_arm(
            intent.attempt_id,
            arm="source",
            physical_root_id=_h("source-root"),
        ),
    )
    _append_and_ack(
        journal,
        provider,
        lambda: journal.finish_arm(intent.attempt_id, arm="source"),
    )
    other_attempt = _id("at", "other-attempt")

    with pytest.raises(ValueError, match="start idempotence crossed"):
        journal.start_arm(
            other_attempt,
            arm="source",
            physical_root_id=_h("source-root"),
        )
    with pytest.raises(ValueError, match="finish idempotence crossed"):
        journal.finish_arm(other_attempt, arm="source")


@pytest.mark.parametrize("order", ["AB", "BA"])
@pytest.mark.parametrize("prefix_events", [0, 1, 2, 3, 4])
def test_cancel_accepts_only_exact_scheduled_nonoverlap_prefix(
    tmp_path: Path,
    order: str,
    prefix_events: int,
) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    intent = _intent(order=order)
    _append_and_ack(journal, provider, lambda: journal.prepare_attempt(intent))
    first, second = (
        ("source", "target") if order == "AB" else ("target", "source")
    )
    operations = (
        lambda: journal.start_arm(
            intent.attempt_id, arm=first, physical_root_id=_h(f"{first}-root")
        ),
        lambda: journal.finish_arm(intent.attempt_id, arm=first),
        lambda: journal.start_arm(
            intent.attempt_id, arm=second, physical_root_id=_h(f"{second}-root")
        ),
        lambda: journal.finish_arm(intent.attempt_id, arm=second),
    )
    for operation in operations[:prefix_events]:
        _append_and_ack(journal, provider, operation)
    terminal = _append_and_ack(
        journal,
        provider,
        lambda: journal.cancel_attempt(
            intent.attempt_id,
            safe_failure_code="runner_crash",
        ),
    )

    assert terminal.payload.kind == "attempt_cancelled"
    assert journal.state.sequence == prefix_events + 2
    assert journal.state.sequence <= MAX_JOURNAL_EVENTS
    started_arms = [
        journal.get_event(item.event_id).payload.arm for item in terminal.payload.started
    ]
    assert tuple(started_arms) == (first, second)[: len(started_arms)]


def test_unpersisted_journal_cannot_grant_execution_authority(tmp_path: Path) -> None:
    journal, provider, _verifier = _create_unbound()
    provider.bootstrap(journal.checkpoint())
    with pytest.raises(RuntimeError, match="persist its empty checkpoint"):
        journal.prepare_attempt(_intent())
    journal.save(tmp_path / "journal.json")
    event = journal.prepare_attempt(_intent())
    assert event.sequence == 1


def test_external_ack_barrier_blocks_every_followup_mutation_and_save(
    tmp_path: Path,
) -> None:
    journal, provider, _verifier, path = _persist_empty(tmp_path)
    intent = _intent()
    prepared = journal.prepare_attempt(intent)
    assert provider.pending(journal.state.journal_id) is not None
    # Exact recovery is read/idempotence, not a second mutation.
    assert journal.prepare_attempt(intent) == prepared
    with pytest.raises(RuntimeError, match="awaits owner acknowledgement"):
        journal.start_arm(
            intent.attempt_id,
            arm="source",
            physical_root_id=_h("source-root"),
        )
    with pytest.raises(RuntimeError, match="awaits owner acknowledgement"):
        journal.save(path)
    _ack(journal, provider)
    started = journal.start_arm(
        intent.attempt_id,
        arm="source",
        physical_root_id=_h("source-root"),
    )
    assert started.sequence == 2


def test_reload_replays_manifest_verifier_and_requires_exact_scope_provider(
    tmp_path: Path,
) -> None:
    verifier = ManifestVerifier(_h("safe-train-manifest"))
    journal, provider, verifier, path = _persist_empty(
        tmp_path,
        verifier=verifier,
    )
    creation_and_save_calls = verifier.calls
    load_verifier = ManifestVerifier(_h("safe-train-manifest"))
    loaded = SFTRunnerJournal.load(
        path,
        journal_key=KEY,
        expected_scope=_scope(),
        checkpoint_provider=provider,
        scope_manifest_verifier=load_verifier,
    )
    assert loaded.state == journal.state
    assert creation_and_save_calls >= 2
    assert load_verifier.calls == 1

    with pytest.raises(ValueError, match="persisted scope"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(goal="all_agents"),
            checkpoint_provider=provider,
            scope_manifest_verifier=load_verifier,
        )
    with pytest.raises(TypeError):
        SFTRunnerJournal.load(  # type: ignore[call-arg]
            path,
            journal_key=KEY,
            checkpoint_provider=provider,
            scope_manifest_verifier=load_verifier,
        )


def test_manifest_capability_rejects_opaque_digest_from_unapproved_split() -> None:
    verifier = ManifestVerifier(_h("safe-train-manifest"))
    with pytest.raises(ValueError, match="manifest was rejected"):
        _create_unbound(
            verifier=verifier,
            scope=_scope(manifest_sha256=_h("hashed-test-manifest")),
        )
    with pytest.raises(ValueError, match="scope manifest verifier"):
        SFTRunnerJournal(
            journal_key=KEY,
            journal_id=_id("jr", "missing-verifier"),
            scope=_scope(),
            checkpoint_provider=InMemoryCheckpointProvider(),
            scope_manifest_verifier=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "field,alias",
    [
        ("attempt_id", "gold:choice_A"),
        ("plan_id", "heldout:secret_42"),
        ("runner_session_id", "oracle:label_B"),
    ],
)
def test_semantic_identifier_aliases_are_rejected(field: str, alias: str) -> None:
    raw = _intent().model_dump(mode="python")
    raw[field] = alias
    with pytest.raises(ValidationError, match="host-derived"):
        PreparePayloadV2.model_validate(raw)
    derived = derive_host_opaque_id_v2("at", _h("verified-public-attempt"))
    assert derived.startswith("at:") and len(derived) == 27


def test_schema_is_answer_free_and_rejects_extra_result_fields(tmp_path: Path) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    _complete_pair(journal, provider)
    text = json.dumps(journal.state.model_dump(mode="json"), sort_keys=True).casefold()
    for forbidden in (
        "answer",
        "ground_truth",
        "expected_output",
        "private_prompt",
        "test_case",
        "eval_seed",
        "score",
        "prompt_text",
    ):
        assert forbidden not in text
    raw = _intent().model_dump(mode="python")
    raw["reference_answer"] = "secret"
    with pytest.raises(ValidationError, match="Extra inputs"):
        PreparePayloadV2.model_validate(raw)


def test_v1_state_is_rejected_before_it_can_gain_v2_authority(tmp_path: Path) -> None:
    journal, _provider, _verifier, path = _persist_empty(tmp_path)
    raw = json.loads(path.read_text())
    raw["state"]["schema_version"] = "sft_runner_journal_v1"
    path.write_text(json.dumps(raw))
    with pytest.raises(LegacyRunnerJournalRejected, match="v1"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=InMemoryCheckpointProvider(),
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )
    assert journal.state.schema_version == "sft_runner_journal_v2"


def test_event_tamper_reorder_and_public_truncation_fail_closed(tmp_path: Path) -> None:
    journal, provider, _verifier, path = _persist_empty(tmp_path)
    _complete_pair(journal, provider)
    valid = json.loads(path.read_text())

    tampered = json.loads(json.dumps(valid))
    tampered["state"]["events"][1]["payload"]["physical_root_id"] = _h("forged")
    path.write_text(json.dumps(tampered))
    with pytest.raises((ValidationError, ValueError), match="digest|HMAC"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )

    reordered = json.loads(json.dumps(valid))
    reordered["state"]["events"][1], reordered["state"]["events"][2] = (
        reordered["state"]["events"][2],
        reordered["state"]["events"][1],
    )
    path.write_text(json.dumps(reordered))
    with pytest.raises((ValidationError, ValueError), match="sequence|chain|digest"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )

    truncated = json.loads(json.dumps(valid))
    truncated["state"]["events"].pop()
    truncated["state"]["sequence"] -= 1
    truncated["state"]["head_event_sha256"] = _h("attacker-public-head")
    truncated["state_sha256"] = _h("attacker-public-state")
    path.write_text(json.dumps(truncated))
    with pytest.raises((ValidationError, ValueError), match="head|digest|HMAC"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )


def test_valid_old_file_is_rejected_by_mandatory_provider_checkpoint(
    tmp_path: Path,
) -> None:
    journal, provider, _verifier, path = _persist_empty(tmp_path)
    old_file = path.read_bytes()
    _append_and_ack(journal, provider, lambda: journal.prepare_attempt(_intent()))
    path.write_bytes(old_file)

    with pytest.raises(RuntimeError, match="latest checkpoint differs"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )


def test_stale_writer_cannot_ABA_write_after_valid_file_rollback(tmp_path: Path) -> None:
    journal, provider, _verifier, path = _persist_empty(tmp_path)
    old_file = path.read_bytes()
    writer_one = SFTRunnerJournal.load(
        path,
        journal_key=KEY,
        expected_scope=_scope(),
        checkpoint_provider=provider,
        scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
    )
    writer_two = SFTRunnerJournal.load(
        path,
        journal_key=KEY,
        expected_scope=_scope(),
        checkpoint_provider=provider,
        scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
    )
    writer_one.prepare_attempt(_intent())
    _ack(writer_one, provider)
    path.write_bytes(old_file)
    stale_before = writer_two.scientific_state_sha256

    with pytest.raises(RuntimeError, match="latest checkpoint differs"):
        writer_two.prepare_attempt(_intent("fork"))
    assert writer_two.scientific_state_sha256 == stale_before
    assert path.read_bytes() == old_file
    assert provider.inspect(journal.state.journal_id).latest_checkpoint == (
        writer_one.checkpoint()
    )


def test_two_loaded_writers_are_linearized_by_provider_claim(tmp_path: Path) -> None:
    _journal, provider, _verifier, path = _persist_empty(tmp_path)
    writers = [
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )
        for _index in range(2)
    ]
    intent = _intent()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(writer.prepare_attempt, intent) for writer in writers]
    results = []
    failures = []
    for future in futures:
        try:
            results.append(future.result())
        except RuntimeError as exc:
            failures.append(exc)
    assert len(results) == 1
    assert len(failures) == 1
    assert provider.pending(writers[0].state.journal_id) is not None


def test_same_instance_duplicate_prepare_remains_concurrently_idempotent(
    tmp_path: Path,
) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    intent = _intent()
    with ThreadPoolExecutor(max_workers=2) as executor:
        events = tuple(executor.map(lambda _index: journal.prepare_attempt(intent), range(2)))
    assert events[0] == events[1]
    assert journal.state.sequence == 1
    assert journal.state.fencing_generation == 1
    assert provider.pending(journal.state.journal_id) is not None


def test_complete_cancel_race_leaves_one_terminal(tmp_path: Path) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    intent = _intent()
    _complete_pair_without_terminal = (
        _append_and_ack(journal, provider, lambda: journal.prepare_attempt(intent)),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.start_arm(
                intent.attempt_id, arm="source", physical_root_id=_h("source-root")
            ),
        ),
        _append_and_ack(
            journal, provider, lambda: journal.finish_arm(intent.attempt_id, arm="source")
        ),
        _append_and_ack(
            journal,
            provider,
            lambda: journal.start_arm(
                intent.attempt_id, arm="target", physical_root_id=_h("target-root")
            ),
        ),
        _append_and_ack(
            journal, provider, lambda: journal.finish_arm(intent.attempt_id, arm="target")
        ),
    )
    assert len(_complete_pair_without_terminal) == 5
    with ThreadPoolExecutor(max_workers=2) as executor:
        complete = executor.submit(journal.complete_pair, intent.attempt_id)
        cancel = executor.submit(
            journal.cancel_attempt,
            intent.attempt_id,
            safe_failure_code="runner_crash",
        )
    outcomes = []
    for future in (complete, cancel):
        try:
            outcomes.append(future.result().payload.kind)
        except ValueError:
            outcomes.append("rejected")
    assert outcomes.count("rejected") == 1
    assert journal.state.sequence == 6
    assert journal.terminal_for_attempt(intent.attempt_id) is not None


def test_failed_file_publication_leaves_provider_claim_pending_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, provider, _verifier, _path = _persist_empty(tmp_path)
    before = journal.scientific_state_sha256

    def fail_save(_target: Path) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr(journal, "_save_owned_state", fail_save)
    with pytest.raises(OSError, match="publication failure"):
        journal.prepare_attempt(_intent())
    assert journal.scientific_state_sha256 == before
    pending = provider.pending(journal.state.journal_id)
    assert pending is not None
    assert pending.expected_checkpoint == journal.checkpoint()
    with pytest.raises(RuntimeError, match="awaits owner acknowledgement"):
        journal.prepare_attempt(_intent())


def test_wrong_key_and_pending_provider_block_load(tmp_path: Path) -> None:
    journal, provider, _verifier, path = _persist_empty(tmp_path)
    with pytest.raises(ValueError, match="state HMAC"):
        SFTRunnerJournal.load(
            path,
            journal_key=b"x" * 32,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )
    journal.prepare_attempt(_intent())
    with pytest.raises(RuntimeError, match="awaits owner acknowledgement"):
        SFTRunnerJournal.load(
            path,
            journal_key=KEY,
            expected_scope=_scope(),
            checkpoint_provider=provider,
            scope_manifest_verifier=ManifestVerifier(_h("safe-train-manifest")),
        )


def test_atomic_save_and_schema_bound_leave_no_growth_surface(tmp_path: Path) -> None:
    journal, provider, _verifier, path = _persist_empty(tmp_path)
    _complete_pair(journal, provider)
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert (tmp_path / "journal.json.lock").exists()
    assert len(journal.state.events) == MAX_JOURNAL_EVENTS
    assert len(path.read_bytes()) < 40_000
