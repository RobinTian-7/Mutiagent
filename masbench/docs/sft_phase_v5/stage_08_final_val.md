# Stage 8 — FINAL_VAL whole-snapshot gate

- Date: 2026-07-17
- Start HEAD: `2f550776`
- Scope: the only candidate→deployment path. Zero paid calls.

## Changed files

- `masbench/src/masbench/sft_pilot/final_val.py` (new):
  `FinalValCaseSample` (safe scalars only), `frozen_final_val_arms` (exactly
  two frozen FINAL_VAL logical arms in schedule order), `run_final_val_gate`:
  requires exactly one pending gate opportunity backed by a still-candidate
  assessment; freezes incumbent/candidate snapshots; spends both frozen
  FINAL_VAL executions read-only through a host executor (store control
  receipts only — no Bank state crosses that boundary); runs the real
  `evaluate_strict_dense_gate` with parameters read from the sealed plan's
  aggregate policy; signs one `GateReceiptV2` via the authority gate domain
  (the Bank additionally closes the receipt over its own strict summary and
  the exact incumbent/candidate snapshots); `apply_gate`; `gate_terminal`
  checkpoint + promotion to the next scientific generation; returns the
  external report root (`decision_id` binds it) and the promoted components.
- `masbench/src/masbench/sft_pilot/store.py` — `abandon_reserved_execution`
  (receipted skip of a never-started lease) and the FINAL_VAL quiescence law
  (see plan_deviations §5–6).
- `masbench/src/masbench/sft_pilot/scientific_runner.py` —
  `skip_settled_probe_blocks`.
- `masbench/tests/test_sft_v5_final_val.py` (new, 3 tests): accept swaps the
  whole snapshot, promotes generation 1, survives crash/restart, and leaves
  every TRAIN transition and the settled assessment digest unchanged; reject
  keeps the incumbent, marks the opportunity rejected, and does not relabel
  the transition; unpaired FINAL_VAL keys fail closed; a closure-valid gate
  receipt signed by a foreign key is rejected by the Bank's installed gate
  verifier. (FINAL_VAL receipts already cannot enter the TRAIN adapter —
  pinned in Stage 5.)

## Exit Gate

- [x] Accept/reject both select complete snapshots (head swap vs incumbent).
- [x] FINAL_VAL receipts cannot convert into ArmReceipts (Stage-5 test).
- [x] Post-gate recovery is exact (promotion survives reopen).
- [x] Incumbent/candidate roots auditable via the receipt + report root.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
