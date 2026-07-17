from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from masbench.sft_pilot.anchor_freeze import (
    ANCHOR_FREEZE_APPLICATION_ID,
    ANCHOR_FREEZE_DATABASE_FILENAME,
    ANCHOR_FREEZE_LOCK_FILENAME,
    ANCHOR_FREEZE_USER_VERSION,
    EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST,
    AnchorFreezeBusyError,
    AnchorFreezeIntegrityError,
    AnchorFreezeLedger,
    AnchorFreezeStateError,
    AnchorNativeWitnessRequired,
    _mint_verified_anchor_native_witness,
)
from masbench.sft_pilot.bootstrap_authority import BootstrapAuthorityBundle
from test_sft_bootstrap_authority import (
    AuthorityFixture,
    make_authority_fixture,
    mint_source,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider(
    authority: BootstrapAuthorityBundle,
    *,
    anchor_root: str | None = None,
    recount_root: str | None = None,
):
    expected_anchor = _sha("anchor-root") if anchor_root is None else anchor_root
    expected_recount = _sha("native-recount") if recount_root is None else recount_root

    def provide(request):
        return _mint_verified_anchor_native_witness(
            authority,
            request,
            phase_envelope_sha256=_file_sha(request.phase_envelope_path),
            factor_envelope_sha256=_file_sha(request.factor_envelope_path),
            anchor_root_sha256=expected_anchor,
            native_recount_sha256=expected_recount,
        )

    return provide


def _write_both(paths, *, suffix: str = "one") -> None:
    paths.phase_envelope_path.write_bytes(f"phase:{suffix}".encode("ascii"))
    paths.factor_envelope_path.write_bytes(f"factor:{suffix}".encode("ascii"))
    os.chmod(paths.phase_envelope_path, 0o600)
    os.chmod(paths.factor_envelope_path, 0o600)


def _open_fixture(tmp_path: Path, *, label: str = "freeze"):
    fixture = make_authority_fixture(tmp_path, label=label)
    authority, _, source = mint_source(fixture)
    ledger = AnchorFreezeLedger.open(fixture.root, authority=authority)
    return fixture, authority, source, ledger


def _freeze_one(
    tmp_path: Path,
    *,
    label: str = "frozen",
    plan_sha: str | None = None,
):
    fixture, authority, source, ledger = _open_fixture(tmp_path, label=label)
    exact_plan = _sha(f"plan:{label}") if plan_sha is None else plan_sha
    permit = ledger.reserve(
        source_capability=source,
        anchor_plan_sha256=exact_plan,
    )
    with ledger._native_build_scope(permit) as paths:
        _write_both(paths, suffix=label)
    request = ledger._native_witness_request(permit.freeze_key)
    receipt = ledger._finalize_with_native_witness(
        permit, _provider(authority)(request)
    )
    return fixture, authority, source, ledger, permit, receipt, paths


def test_reservation_precedes_one_build_and_frozen_reopen_requires_witness(
    tmp_path: Path,
) -> None:
    fixture, authority, source, ledger = _open_fixture(tmp_path)
    plan_sha = _sha("anchor-plan")
    permit = ledger.reserve(
        source_capability=source,
        anchor_plan_sha256=plan_sha,
    )

    # The reservation is durably visible before the private build scope exists.
    reader = sqlite3.connect(fixture.root / ANCHOR_FREEZE_DATABASE_FILENAME)
    try:
        row = reader.execute(
            "SELECT event_kind,event_ordinal,event_sha256,build_ticket_sha256 "
            "FROM anchor_freeze_event"
        ).fetchone()
    finally:
        reader.close()
    assert row == ("reserved", 1, permit.build_ticket_sha256, permit.build_ticket_sha256)
    assert ledger.state(permit.freeze_key) == "reserved"

    with ledger._native_build_scope(permit) as paths:
        _write_both(paths)
    with pytest.raises(AnchorFreezeStateError, match="already been consumed"):
        with ledger._native_build_scope(permit):
            pass
    request = ledger._native_witness_request(permit.freeze_key)
    receipt = ledger._finalize_with_native_witness(
        permit, _provider(authority)(request)
    )
    assert ledger.state(permit.freeze_key) == "frozen"
    assert receipt.build_ticket_sha256 == permit.build_ticket_sha256
    assert receipt.phase_envelope_sha256 == _file_sha(paths.phase_envelope_path)
    assert receipt.factor_envelope_sha256 == _file_sha(paths.factor_envelope_path)
    assert receipt.anchor_plan_sha256 == plan_sha
    with pytest.raises(AnchorFreezeStateError, match="already attempted"):
        ledger.reserve(source_capability=source, anchor_plan_sha256=plan_sha)
    ledger.close()

    with pytest.raises(AnchorNativeWitnessRequired, match="fresh private"):
        AnchorFreezeLedger.open(fixture.root, authority=authority)
    reopened = AnchorFreezeLedger.open(
        fixture.root,
        authority=authority,
        _native_witness_provider=_provider(authority),
    )
    assert reopened.frozen_receipt(permit.freeze_key) == receipt
    assert EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST == reopened._connection.execute(
        "SELECT schema_digest FROM schema_meta"
    ).fetchone()[0]
    assert (
        reopened._connection.execute("PRAGMA application_id").fetchone()[0]
        == ANCHOR_FREEZE_APPLICATION_ID
    )
    assert (
        reopened._connection.execute("PRAGMA user_version").fetchone()[0]
        == ANCHOR_FREEZE_USER_VERSION
    )
    assert (fixture.root.stat().st_mode & 0o777) == 0o700
    assert (reopened.lock_path.stat().st_mode & 0o777) == 0o600
    assert (reopened.database_path.stat().st_mode & 0o777) == 0o600
    assert (paths.native_dir.stat().st_mode & 0o777) == 0o700
    assert (paths.phase_envelope_path.stat().st_mode & 0o777) == 0o600
    reopened.close()


def test_crash_with_no_native_files_is_permanently_failed_closed(tmp_path: Path) -> None:
    fixture, authority, source, ledger = _open_fixture(tmp_path, label="no-files")
    plan = _sha("no-file-plan")
    permit = ledger.reserve(source_capability=source, anchor_plan_sha256=plan)
    ledger.close()

    recovered = AnchorFreezeLedger.open(fixture.root, authority=authority)
    assert recovered.state(permit.freeze_key) == "failed_closed"
    terminal = recovered._terminal_row(permit.freeze_key)
    assert terminal is not None
    assert terminal["safe_failure_code"] == "no_native_root"
    assert terminal["anchor_root_sha256"] is None
    with pytest.raises(AnchorFreezeStateError, match="already attempted"):
        recovered.reserve(source_capability=source, anchor_plan_sha256=plan)
    recovered.close()


def test_crash_with_one_native_file_is_permanently_failed_closed(tmp_path: Path) -> None:
    fixture, authority, source, ledger = _open_fixture(tmp_path, label="partial")
    permit = ledger.reserve(
        source_capability=source,
        anchor_plan_sha256=_sha("partial-plan"),
    )
    with ledger._native_build_scope(permit) as paths:
        paths.phase_envelope_path.write_bytes(b"phase-only")
        os.chmod(paths.phase_envelope_path, 0o600)
    ledger.close()

    recovered = AnchorFreezeLedger.open(fixture.root, authority=authority)
    assert recovered.state(permit.freeze_key) == "failed_closed"
    terminal = recovered._terminal_row(permit.freeze_key)
    assert terminal is not None
    assert terminal["safe_failure_code"] == "partial_native_root"
    assert paths.phase_envelope_path.exists()
    assert not paths.factor_envelope_path.exists()
    recovered.close()


def test_crash_with_both_files_needs_private_witness_then_freezes_same_bytes(
    tmp_path: Path,
) -> None:
    fixture, authority, source, ledger = _open_fixture(tmp_path, label="both")
    permit = ledger.reserve(
        source_capability=source,
        anchor_plan_sha256=_sha("both-plan"),
    )
    with ledger._native_build_scope(permit) as paths:
        _write_both(paths, suffix="crash")
    phase_sha = _file_sha(paths.phase_envelope_path)
    factor_sha = _file_sha(paths.factor_envelope_path)
    ledger.close()

    with pytest.raises(AnchorNativeWitnessRequired):
        AnchorFreezeLedger.open(fixture.root, authority=authority)
    raw = sqlite3.connect(fixture.root / ANCHOR_FREEZE_DATABASE_FILENAME)
    try:
        assert raw.execute(
            "SELECT COUNT(*) FROM anchor_freeze_event WHERE event_ordinal=2"
        ).fetchone()[0] == 0
    finally:
        raw.close()

    recovered = AnchorFreezeLedger.open(
        fixture.root,
        authority=authority,
        _native_witness_provider=_provider(authority),
    )
    receipt = recovered.frozen_receipt(permit.freeze_key)
    assert receipt.phase_envelope_sha256 == phase_sha
    assert receipt.factor_envelope_sha256 == factor_sha
    assert recovered.state(permit.freeze_key) == "frozen"
    recovered.close()


def test_extra_or_insecure_native_file_fails_closed_without_root(tmp_path: Path) -> None:
    fixture, authority, source, ledger = _open_fixture(tmp_path, label="invalid")
    permit = ledger.reserve(
        source_capability=source,
        anchor_plan_sha256=_sha("invalid-plan"),
    )
    with ledger._native_build_scope(permit) as paths:
        _write_both(paths)
        (paths.native_dir / "unregistered.tmp").write_bytes(b"not-authorized")
    ledger.close()

    recovered = AnchorFreezeLedger.open(fixture.root, authority=authority)
    terminal = recovered._terminal_row(permit.freeze_key)
    assert terminal is not None
    assert terminal["event_kind"] == "failed_closed"
    assert terminal["safe_failure_code"] == "invalid_native_root"
    assert terminal["phase_envelope_sha256"] is None
    assert terminal["factor_envelope_sha256"] is None
    recovered.close()


def test_frozen_file_tamper_or_inode_replacement_is_rejected(tmp_path: Path) -> None:
    fixture, authority, _, ledger, _, _, paths = _freeze_one(
        tmp_path, label="tamper"
    )
    ledger.close()
    paths.phase_envelope_path.write_bytes(b"changed-but-mode-remains")
    os.chmod(paths.phase_envelope_path, 0o600)
    with pytest.raises(AnchorFreezeIntegrityError, match="identity mismatch"):
        AnchorFreezeLedger.open(
            fixture.root,
            authority=authority,
            _native_witness_provider=_provider(authority),
        )

    fixture2, authority2, _, ledger2, _, _, paths2 = _freeze_one(
        tmp_path, label="inode"
    )
    ledger2.close()
    original = paths2.factor_envelope_path.read_bytes()
    replacement = paths2.native_dir / "replacement"
    replacement.write_bytes(original)
    os.chmod(replacement, 0o600)
    os.replace(replacement, paths2.factor_envelope_path)
    with pytest.raises(AnchorFreezeIntegrityError, match="identity mismatch"):
        AnchorFreezeLedger.open(
            fixture2.root,
            authority=authority2,
            _native_witness_provider=_provider(authority2),
        )


def test_stable_lock_database_and_event_chain_tamper_are_rejected(tmp_path: Path) -> None:
    fixture, authority, _, ledger = _open_fixture(tmp_path, label="stable")
    with pytest.raises(AnchorFreezeBusyError):
        AnchorFreezeLedger.open(fixture.root, authority=authority)
    ledger.close()

    lock_path = fixture.root / ANCHOR_FREEZE_LOCK_FILENAME
    lock_path.unlink()
    lock_path.write_bytes(b"replacement")
    os.chmod(lock_path, 0o600)
    with pytest.raises(AnchorFreezeIntegrityError, match="stable_lock"):
        AnchorFreezeLedger.open(fixture.root, authority=authority)

    fixture2, authority2, _, ledger2 = _open_fixture(tmp_path, label="database")
    ledger2.close()
    database = fixture2.root / ANCHOR_FREEZE_DATABASE_FILENAME
    copy = fixture2.root / "database-copy"
    shutil.copyfile(database, copy)
    os.chmod(copy, 0o600)
    database.unlink()
    os.replace(copy, database)
    with pytest.raises(AnchorFreezeIntegrityError, match="stable_database"):
        AnchorFreezeLedger.open(fixture2.root, authority=authority2)

    fixture3, authority3, source3, ledger3 = _open_fixture(tmp_path, label="event")
    permit = ledger3.reserve(
        source_capability=source3,
        anchor_plan_sha256=_sha("event-plan"),
    )
    ledger3.close()
    raw = sqlite3.connect(fixture3.root / ANCHOR_FREEZE_DATABASE_FILENAME)
    try:
        raw.execute("DROP TRIGGER anchor_freeze_event_no_update")
        raw.execute(
            "UPDATE anchor_freeze_event SET anchor_plan_sha256=? WHERE freeze_key=?",
            (_sha("tampered-plan"), permit.freeze_key),
        )
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(AnchorFreezeIntegrityError, match="freeze key mismatch"):
        AnchorFreezeLedger.open(fixture3.root, authority=authority3)


def test_wrong_application_version_symlinks_and_root_commitment_fail_closed(
    tmp_path: Path,
) -> None:
    fixture, authority, _, ledger = _open_fixture(tmp_path, label="pragma")
    ledger.close()
    raw = sqlite3.connect(fixture.root / ANCHOR_FREEZE_DATABASE_FILENAME)
    try:
        raw.execute("PRAGMA user_version=99")
    finally:
        raw.close()
    with pytest.raises(AnchorFreezeIntegrityError, match="user_version"):
        AnchorFreezeLedger.open(fixture.root, authority=authority)

    fixture2 = make_authority_fixture(tmp_path, label="symlink")
    fixture2.root.mkdir(mode=0o700)
    target = fixture2.root / "lock-target"
    target.write_bytes(b"")
    (fixture2.root / ANCHOR_FREEZE_LOCK_FILENAME).symlink_to(target)
    authority2 = fixture2.load()
    with pytest.raises(AnchorFreezeIntegrityError, match="lock cannot be opened"):
        AnchorFreezeLedger.open(fixture2.root, authority=authority2)

    wrong_root = tmp_path / "wrong-authority-root"
    with pytest.raises(AnchorFreezeIntegrityError, match="commitment mismatch"):
        AnchorFreezeLedger.open(wrong_root, authority=authority2)


def test_ledger_persists_only_hashes_and_safe_failure_codes(tmp_path: Path) -> None:
    fixture, authority, source, ledger = _open_fixture(tmp_path, label="privacy")
    permit = ledger.reserve(
        source_capability=source,
        anchor_plan_sha256=_sha("privacy-plan"),
    )
    ledger.close()
    recovered = AnchorFreezeLedger.open(fixture.root, authority=authority)
    assert recovered.state(permit.freeze_key) == "failed_closed"
    recovered.close()

    database_bytes = (fixture.root / ANCHOR_FREEZE_DATABASE_FILENAME).read_bytes().lower()
    for forbidden in (
        b"unique-private-prompt-marker",
        b"unique-answer-marker",
        b"expected_output",
        b"ground_truth",
        b"final_val_case_row",
    ):
        assert forbidden not in database_bytes
