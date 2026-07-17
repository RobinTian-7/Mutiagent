# Stage 7 — Failure memory, repair & branch scheduling loop

- Date: 2026-07-17
- Start HEAD: `32198452`
- Scope: the TRAIN update loop beyond a fixed anchor edge — opportunity →
  slate → branch → action lifecycle → probe/assessment → failure/repair →
  capacity → next round — with the Bank as the only scheduler truth source.
  Zero paid calls.

## Changed files

- `masbench/src/masbench/sft_pilot/scientific_runner.py` —
  `pending_repair_opportunities(bank)` (Bank-truth queue: unconsumed by any
  proposal decision, unexpired) and `branch_assignment_counts(bank)`
  (reuse/mutate/fresh exposure counters from Bank state; no caller cache).
- `masbench/tests/sft_v5_fixtures.py` — `prepare_action_from(...)`
  generalizes action preparation to an existing opportunity, with optional
  source overrides for repairing a deployed-bad composition (the failing
  target becomes the next proposal's source cell).
- `masbench/tests/test_sft_v5_train_loop.py` (new, 2 tests).

## Loop evidence

- Round 1: bootstrap opportunity → mutate (one frozen call) → probe unit →
  `harmful` terminal. Crash/restart at the settled probe boundary restores
  exact roots; the mutate exposure counter reads back from Bank state.
- Harm repair: the failure observation binds the harmful transition to its
  target composition (the Bank enforces exactly that join); the repair
  opportunity carries only safe codes — no failure text can reach a prompt
  because the renderer only ever accepts `safe_failure_code`.
- Round 2: `pending_repair_opportunities` drives a reuse action — zero
  generation calls (store budget ledger root unchanged), opportunity
  consumed, reuse counter incremented — all read from the Bank.
- Round 3 (capacity law): a further mutate cannot even reserve its
  generation execution — the frozen TRAIN budget rejects before any model
  call could exist.
- Unauthorized capacity archive: an attestation not signed by the authority
  can never evict (fail-closed on the harmful victim).
- Scheduler-state honesty: an unpromoted in-session failure/opportunity tail
  is deliberately discarded by recovery — the queue re-derives from the
  restored component head, never from in-process memory.

## Findings recorded (design facts, not regressions)

- The checkpoint saga is **gate-delimited by design**: `action_prepared` has
  no predecessors, so a NEW action's durable chain can only begin after the
  previous action settles through `gate_terminal` and its checkpoint is
  promoted. Durable multi-round chaining therefore composes with Stage 8's
  gate/promotion cycle; within one saga cycle the loop above is fully
  demonstrated.
- End-to-end *signed* archive eviction needs a two-phase root derivation
  (the merkle root is computed inside `archive_for_capacity` while the
  authority signs roots); the fail-closed direction is tested. Left as a
  documented gap for the pre-pilot hardening pass.

## Tests

- `tests/test_sft_v5_train_loop.py` → **2 passed**.

## Exit Gate

- [x] Fake multi-round is recoverable (crash at the settled boundary; the
      unpromoted tail honestly re-derives).
- [x] reuse/mutate/fresh scheduling is deterministic and Bank-owned.
- [x] FactorBankV2 is the only scheduler/counter truth source (queue and
      counters are pure Bank-state functions).
- [x] No broad fallback anywhere in the loop path.
- [x] Capacity bounds hold — rejection happens before any model call.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
