"""External append-only result ledger (v5 Stage 9).

FINAL_VAL gate reports and frozen TEST reports live here — outside every
scientific state owner.  Rows are closed models carrying safe scalars and
commitments only, hash-chained, and HMAC'd under the ``result_ledger``
runtime role key.  The ledger can verify itself byte-exactly; it exposes no
API that any selection, retrieval, failure, or Bank code path consumes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    canonical_json,
    canonical_sha256,
    pilot_hmac_sha256,
    require_opaque_id,
    require_sha256,
)


RESULT_LEDGER_VERSION = "sft_pilot_result_ledger_v1"
TEST_MANIFEST_VERSION = "sft_pilot_test_manifest_v1"
_ROW_DOMAIN = "sft-result-ledger-row-v1"
_ZERO = "0" * 64


class PilotTestManifestV1(ClosedPilotModel):
    """Frozen TEST identity: commitments only, sealed before TRAIN ends."""

    manifest_version: Literal[TEST_MANIFEST_VERSION] = TEST_MANIFEST_VERSION
    test_id: str
    experiment_id: str
    case_commitments: tuple[str, ...]
    scoring_policy_sha256: str

    @field_validator("test_id", "experiment_id")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("scoring_policy_sha256")
    @classmethod
    def validate_policy(cls, value: str) -> str:
        return require_sha256(value, field_name="scoring_policy_sha256")

    @field_validator("case_commitments")
    @classmethod
    def validate_cases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or tuple(sorted(set(value))) != value:
            raise ValueError("TEST case commitments must be canonical and unique")
        for item in value:
            require_sha256(item, field_name="case_commitments")
        return value

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotResultRowV1(ClosedPilotModel):
    """One immutable external result row (safe scalars + commitments only)."""

    row_version: Literal[RESULT_LEDGER_VERSION] = RESULT_LEDGER_VERSION
    row_ordinal: int = Field(ge=0)
    row_kind: Literal["final_val_gate", "test_report"]
    experiment_seal_sha256: str
    protocol_sha256: str
    report_sha256: str
    accepted: bool | None = None
    metrics: tuple[tuple[str, float], ...] = ()
    previous_row_sha256: str
    row_attestation_sha256: str

    @field_validator(
        "experiment_seal_sha256",
        "protocol_sha256",
        "report_sha256",
        "previous_row_sha256",
        "row_attestation_sha256",
    )
    @classmethod
    def validate_sha(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_metrics(self) -> "PilotResultRowV1":
        names = tuple(name for name, _value in self.metrics)
        if names != tuple(sorted(set(names))):
            raise ValueError("result metrics must be canonical and unique")
        for name, value in self.metrics:
            require_opaque_id(name, field_name="metrics")
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("result metrics must be finite")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotResultLedger:
    """Append-only, chained, key-attested JSONL ledger."""

    def __init__(self, path: str | Path, *, ledger_key: bytes) -> None:
        if not isinstance(ledger_key, bytes) or len(ledger_key) < 32:
            raise ValueError("result ledger key must contain at least 32 bytes")
        self._path = Path(path)
        if not self._path.is_absolute():
            raise ValueError("result ledger path must be absolute")
        self._key = bytes(ledger_key)

    def rows(self) -> tuple[PilotResultRowV1, ...]:
        """Read and fully verify the chain; any tamper fails loudly."""

        if not self._path.exists():
            return ()
        rows: list[PilotResultRowV1] = []
        previous = _ZERO
        payload = self._path.read_bytes().decode("utf-8")
        for ordinal, line in enumerate(
            item for item in payload.split("\n") if item
        ):
            try:
                row = PilotResultRowV1.model_validate_json(line)
            except (TypeError, ValueError) as exc:
                raise ValueError("result ledger row is not a closed row") from exc
            if canonical_json(row) != line:
                raise ValueError("result ledger row is not canonical exact JSON")
            if row.row_ordinal != ordinal:
                raise ValueError("result ledger rows are reordered or truncated")
            if row.previous_row_sha256 != previous:
                raise ValueError("result ledger chain is broken")
            expected = pilot_hmac_sha256(
                self._key,
                domain=_ROW_DOMAIN,
                value=row.model_dump(
                    mode="python", exclude={"row_attestation_sha256"}
                ),
            )
            if row.row_attestation_sha256 != expected:
                raise ValueError("result ledger row attestation mismatch")
            previous = row.digest
            rows.append(row)
        return tuple(rows)

    def append(
        self,
        *,
        row_kind: Literal["final_val_gate", "test_report"],
        experiment_seal_sha256: str,
        protocol_sha256: str,
        report_sha256: str,
        accepted: bool | None = None,
        metrics: tuple[tuple[str, float], ...] = (),
    ) -> PilotResultRowV1:
        existing = self.rows()
        previous = existing[-1].digest if existing else _ZERO
        body = {
            "row_version": RESULT_LEDGER_VERSION,
            "row_ordinal": len(existing),
            "row_kind": row_kind,
            "experiment_seal_sha256": experiment_seal_sha256,
            "protocol_sha256": protocol_sha256,
            "report_sha256": report_sha256,
            "accepted": accepted,
            "metrics": tuple(sorted(metrics)),
            "previous_row_sha256": previous,
        }
        attestation = pilot_hmac_sha256(
            self._key, domain=_ROW_DOMAIN, value=body
        )
        row = PilotResultRowV1(**body, row_attestation_sha256=attestation)
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row


__all__ = [
    "PilotResultLedger",
    "PilotResultRowV1",
    "PilotTestManifestV1",
    "RESULT_LEDGER_VERSION",
    "TEST_MANIFEST_VERSION",
]
