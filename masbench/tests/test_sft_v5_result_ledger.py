"""Stage 9 closure tests: TEST frozen facade + external result ledger.

The TEST run can never influence a future Bank: it sees only a read-only
snapshot facade and safe head identifiers, all scientific roots must be
byte-identical before and after, its report exists only in the external
chained ledger, and any tamper of that ledger is detected on read.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from masbench.sft_pilot.result_ledger import (
    PilotResultLedger,
    PilotTestManifestV1,
)
from masbench.sft_pilot.scientific_runner import (
    all_scientific_state_roots,
    run_frozen_test_readonly,
)

from sft_v5_fixtures import V5Harness


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def harness(tmp_path):
    built = V5Harness(tmp_path)
    yield built
    built.close()


def _ledger(harness) -> PilotResultLedger:
    return PilotResultLedger(
        harness.experiment.result_dir / "results.jsonl",
        ledger_key=harness.experiment.runtime_role_key("result_ledger"),
    )


def test_ledger_chains_and_detects_every_tamper(harness, tmp_path) -> None:
    ledger = _ledger(harness)
    first = ledger.append(
        row_kind="final_val_gate",
        experiment_seal_sha256=harness.experiment.seal.digest,
        protocol_sha256=harness.experiment.protocol.digest,
        report_sha256=_sha("gate-report"),
        accepted=True,
        metrics=(("stage_delta", 0.12),),
    )
    second = ledger.append(
        row_kind="test_report",
        experiment_seal_sha256=harness.experiment.seal.digest,
        protocol_sha256=harness.experiment.protocol.digest,
        report_sha256=_sha("test-report"),
        metrics=(("exact_success", 0.5),),
    )
    rows = ledger.rows()
    assert [row.row_ordinal for row in rows] == [0, 1]
    assert rows[1].previous_row_sha256 == first.digest
    assert second.row_kind == "test_report"

    path = harness.experiment.result_dir / "results.jsonl"
    original = path.read_bytes()

    # Bit flip inside a row.
    path.write_bytes(original.replace(b'"accepted":true', b'"accepted":false'))
    with pytest.raises(ValueError, match="attestation mismatch|closed row"):
        ledger.rows()

    # Truncation (drop the last row).
    path.write_bytes(b"".join(original.splitlines(keepends=True)[:1]))
    truncated_rows = ledger.rows()
    assert len(truncated_rows) == 1  # visible truncation: chain ends early
    # Reorder: swapping rows breaks both ordinal and chain.
    lines = original.splitlines(keepends=True)
    path.write_bytes(lines[1] + lines[0])
    with pytest.raises(ValueError, match="reordered|chain is broken"):
        ledger.rows()
    # A foreign key cannot mint acceptable rows.
    path.write_bytes(original)
    foreign = PilotResultLedger(
        harness.experiment.result_dir / "results.jsonl",
        ledger_key=hashlib.sha256(b"foreign-ledger-key").digest(),
    )
    with pytest.raises(ValueError, match="attestation mismatch"):
        foreign.rows()


def test_frozen_test_run_leaves_all_roots_identical(harness) -> None:
    ledger = _ledger(harness)
    seal = harness.experiment.seal
    manifest = harness.experiment.test_manifest
    before = all_scientific_state_roots(
        store=harness.store, loaded=harness.loaded
    )

    captured = {}

    def executor(test_manifest, snapshot, deployment_view):
        captured["manifest"] = test_manifest
        captured["snapshot_type"] = type(snapshot).__name__
        # The facade exposes no writer surface at all.
        for forbidden in (
            "commit_attempt",
            "record_failure",
            "apply_gate",
            "archive_for_capacity",
            "screen_and_allocate_branch",
            "save",
        ):
            assert not hasattr(snapshot, forbidden)
        assert deployment_view["heads"][0]["active_composition_id"]
        return _sha("frozen-test-report"), (("exact_success", 0.0),)

    row = run_frozen_test_readonly(
        store=harness.store,
        loaded=harness.loaded,
        seal=seal,
        protocol=harness.experiment.protocol,
        test_manifest=manifest,
        ledger=ledger,
        test_executor=executor,
    )
    after = all_scientific_state_roots(
        store=harness.store, loaded=harness.loaded
    )
    assert before == after
    assert captured["snapshot_type"] == "ReadOnlyFactorBankV2"
    assert row.row_kind == "test_report"
    assert ledger.rows()[-1] == row
    # A zero-quality TEST result is a legal, recorded outcome — and the Bank
    # holds no new failure observation from it.
    assert harness.bank.to_state().failures == ()


def test_mutating_test_executor_is_detected_and_result_withheld(
    harness,
) -> None:
    ledger = _ledger(harness)

    def hostile_executor(test_manifest, snapshot, deployment_view):
        # A hostile executor that captured the live bank out-of-band.
        from exp_graph.mas.factor_bank_v2 import FailureObservationV2

        edge = harness.anchor_edge()
        harness.bank.record_failure(
            FailureObservationV2(
                failure_id="failure:test-poison",
                failure_class="algorithm",
                failed_stage="execute",
                safe_failure_code="algorithm_failure",
                composition_id=edge.source_composition.composition_id,
                artifact_sha256=edge.source_composition.artifact_sha256,
                created_seq=harness.bank.to_state().event_seq + 1,
            ),
            feasible_branches=("reuse",),
        )
        return _sha("poisoned-report"), ()

    with pytest.raises(RuntimeError, match="mutated scientific state"):
        run_frozen_test_readonly(
            store=harness.store,
            loaded=harness.loaded,
            seal=harness.experiment.seal,
            protocol=harness.experiment.protocol,
            test_manifest=harness.experiment.test_manifest,
            ledger=ledger,
            test_executor=hostile_executor,
        )
    assert ledger.rows() == ()


def test_foreign_test_manifest_is_rejected(harness) -> None:
    foreign = PilotTestManifestV1(
        test_id="foreign-test",
        experiment_id="sft-v5-experiment",
        case_commitments=(_sha("foreign-case"),),
        scoring_policy_sha256=_sha("foreign-policy"),
    )
    with pytest.raises(ValueError, match="sealed commitment"):
        run_frozen_test_readonly(
            store=harness.store,
            loaded=harness.loaded,
            seal=harness.experiment.seal,
            protocol=harness.experiment.protocol,
            test_manifest=foreign,
            ledger=_ledger(harness),
            test_executor=lambda *_args: (_sha("x"), ()),
        )
