# Stage 10 — Control arms & equal-budget driver surface

- Date: 2026-07-17 · Start HEAD: `ed07b60a` · Zero paid calls.

## Changed files

- `masbench/src/masbench/sft_pilot/controls.py` (new):
  `PilotMethodBackendGateway` — the only surface between one method arm and
  its backend; construction validates the backend *instance type* against
  the closed policy law (factor arms → the live `FactorBankV2`; shadow →
  only the read-only facade; current/whole/ECT → their own chained,
  key-attested evidence ledgers `QueenBeeSkillBankBackendV1`,
  `WholeArtifactBankV1`, `EctTransactionBankV1`); `writer()` enforces the
  operation+phase law and the FINAL_VAL write ban.
  `build_control_gateways` mints one exclusive gateway per arm.
  `verify_equal_all_in_budgets` requires identical per-phase and total
  execution/call/token budgets across every arm's frozen protocol.
- `masbench/tests/test_sft_v5_equal_budget.py` (new, 3 tests): all nine
  arms build policy-gated backends; ECT records real chained rows in its own
  ledger; the factor arm writes the Bank itself; shadow reads the same
  representation but can never write; FINAL_VAL writes fail on every arm;
  the no-failure-memory ablation removes exactly `record_failure`;
  cross-backend instances fail closed in both directions; equal-budget
  verification passes for the sealed sibling protocols and rejects a
  one-token skew.

## Scope note

The multi-arm *driver* that executes control arms end-to-end belongs to the
real-pilot phase (their probe flows are method-specific); what Stage 10
closes is the plan's gate: real per-arm backends, method-policy authority on
every operation, no cross-backend writes, and equal all-in budgets with a
comparable report root. The SFT probe cost accounting shares the same frozen
protocol budgets (probes draw from the arm's own PROBE budget, verified
equal across arms).

## Exit Gate

- [x] Every arm passes method-policy authority checks (writer path).
- [x] No arm can write another backend (typed gateway + policy).
- [x] Arms share the same cases/seeds/model/runtime via the single sealed
      schedule and namespace (Stage 2 seal law).
- [x] Budget divergence fails the replicate (verifier).
- [x] Comparable report root emitted (`budget_root_sha256`).

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
