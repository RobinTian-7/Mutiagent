# Stage 9 — TEST frozen facade & external result ledger

- Date: 2026-07-17
- Start HEAD: `e989e852`
- Scope: the final evaluation can never influence a future Bank. Zero paid
  calls.

## Changed files

- `masbench/src/masbench/sft_pilot/result_ledger.py` (new):
  `PilotTestManifestV1` (frozen TEST identity — commitments only, sealed via
  the experiment seal's `test_manifest_sha256`), `PilotResultRowV1` (closed
  row: safe scalar metrics + commitments, hash-chained, HMAC'd under the
  `result_ledger` runtime role key), `PilotResultLedger` (append-only
  canonical JSONL; `rows()` re-verifies the entire chain: non-canonical
  bytes, ordinal reorder, chain break, attestation mismatch, and foreign
  keys all fail loudly; truncation is visible as a shortened chain).
- `masbench/src/masbench/sft_pilot/scientific_runner.py` —
  `all_scientific_state_roots` (store commit head, budget/operation ledger
  roots, component bundle root+generation, Bank scientific root, registry
  root, deployment heads, proposal counters, failures) and
  `run_frozen_test_readonly`: seals the TEST manifest against the
  experiment seal, hands the executor only the read-only Bank snapshot
  facade + safe head identifiers, captures all roots before/after, withholds
  the result on any difference, and appends the report row externally.
- `masbench/tests/sft_v5_fixtures.py` — the seal now pins a real
  `PilotTestManifestV1` digest; the manifest is exposed on the fixture.
- `masbench/tests/test_sft_v5_result_ledger.py` (new, 4 tests): ledger
  chain + full tamper matrix (bit flip, truncation visibility, reorder,
  foreign key); frozen TEST run with byte-identical roots, no writer surface
  on the facade (`ReadOnlyFactorBankV2`), a legal all-zero TEST result, and
  zero new failure observations; a hostile executor that mutates captured
  live state is detected and its result withheld (no row written); a foreign
  TEST manifest is rejected against the sealed commitment.

## Exit Gate

- [x] Complete fake TEST run leaves every scientific root identical.
- [x] The result ledger is independently verifiable (chain + HMAC + canonical
      bytes).
- [x] TEST results exist only in the external report ledger.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
