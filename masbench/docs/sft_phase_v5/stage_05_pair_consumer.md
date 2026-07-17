# Stage 5 — TRAIN arm adapter & single-use pair consumer

- Date: 2026-07-17
- Start HEAD: `d8c71fe2`
- Scope: trusted execution/scorer receipts become the only admissible
  FactorBank arm/pair evidence. Zero paid calls.

## Changed files

- `masbench/src/masbench/sft_pilot/pair_adapter.py` —
  `make_phase_v3_factor_arm_receipt`: exact-type gates (execution
  attestation, TRAIN outcome receipt, v3 edge); re-runs both authority
  verifications through the existing `factor_arm_evidence_from_receipts`
  (raw `DenseOutcome`, caller dicts, FINAL_VAL subclasses are impossible;
  method policy + retrieved/activated law enforced there); joins the
  attested execution to the exact registered edge (proof id/sha, composition,
  artifact, namespace, attempt ordinal); **re-derives the engine's composite
  physical execution root from the journal arm root**, binding the Bank
  receipt to the physically executed artifact; requires failure annotations
  exactly when the terminal class is `algorithm_failure`; emits the
  authority-signed `ArmReceiptV2`.
- `masbench/src/masbench/sft_pilot/pair_consumer.py` —
  `consume_phase_v3_pair_once`: loud pre-consumption join checks (one
  source + one target, same plan/attempt/unit/budget, journal roots equal
  the pair receipt's, order agreement, pair receipt binds the attempt);
  byte-identical replay of a settled attempt is idempotent
  (`replayed=True`), different bytes are a conflict; commits atomically via
  `FactorBankV2.commit_attempt` (whose single-use root/receipt registries
  provide the permanent consumption) and immediately checkpoints
  `probe_terminal` through the component coordinator (returns the new
  loaded components).
- `masbench/tests/sft_v5_fixtures.py` — the Stage-4 harness is promoted to
  the shared `V5Harness` (real authority verifiers, saga checkpoints,
  `prepare_action`, `commit_mutate_edge`); the generation tests now import
  it.
- `masbench/tests/test_sft_v5_pair_consumer.py` (new, 3 tests around one
  fully executed probe pair): the pair runs with **real engine attestations**
  (store leases + saga-fenced calls under the frozen schedule, verified
  journal pair snapshot, v3 canonical-bundle replay) and real
  isolated-scorer receipts over the freshly generated edge from
  `commit_mutate_edge`.

## End-to-end evidence

- One complete pair → `commit_attempt` → attempt `complete`, assessment
  `n_complete == 1`, `n_benefit == 1` (exactly one vote; label owned by the
  native reducer). `probe_terminal` checkpoint settles the saga stage.
- Byte-identical replay: `replayed=True`, scientific state digest unchanged.
- Conflicting replay (tampered receipt for a settled attempt) fails.
- Swapped arms fail before anything is consumed; the true pair still
  commits afterward.
- Adapter negative matrix: FINAL_VAL alias → `TypeError`; forged execution
  attestation HMAC → rejected; swapped transition endpoints → the expected
  factor is retrieved-but-not-activated → zero credit, loudly; foreign
  journal roots → not the attested physical execution root.

## Tests

- `tests/test_sft_v5_pair_consumer.py` → **3 passed**.
- All SFT targeted + v5 suites → **228 passed in 33.23s**.
- exp-graph `tests/test_factor_bank_v2.py` → **181 passed** (no Bank
  changes were needed in this stage).

## Exit Gate

- [x] A complete fake pair enters FactorBankV2 (real attestation chain).
- [x] The transition gains exactly one vote.
- [x] Both composition reliability observations derive from the same raw
      receipts (source and target receipts committed on the attempt).
- [x] Repeat consumption does not increase counts (digest-stable replay).
- [x] Conflicting replay fails.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
