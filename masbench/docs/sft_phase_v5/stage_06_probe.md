# Stage 6 — Six-unit probe execution & recovery

- Date: 2026-07-17
- Start HEAD: `47e313d7`
- Scope: execute the existing `ProbePlanV2` through real assessments with the
  native reducer, crash recovery, half-pair cancellation, and infrastructure
  semantics. Zero paid calls (fake outcomes; provider crossings simulated via
  the real store law).

## Changed files

- `masbench/src/masbench/sft_pilot/store.py` — the `probe_terminal`
  settlement law is now conditioned on the semantic witness's attempt state:
  a `complete` pair still requires a completed second-arm crossing
  (unchanged); an `incomplete`/`quarantine` pair may carry a permanently
  indeterminate crossing; a `cancelled` pair may settle before its second
  crossing ever started (`reserved`/`failed_before_start` are terminal for
  that logical arm because the no-retry law and global arm uniqueness make
  them permanent). Previously a crashed half-pair could never publish its
  settlement checkpoint, so the saga would wedge — the plan's half-pair
  cancellation law was unrepresentable. Recorded in `plan_deviations.md`.
- `masbench/tests/sft_v5_fixtures.py` — `V5ProbeMixin`/`V5ProbeHarness`:
  `seal_plan_for` (authority-frozen six units), `open_probe_unit`
  (assignment/lease/open + scheduled executions + `probe_attempt_open`
  checkpoint), `execute_probe_unit` (per arm: store lease/calls under the
  frozen schedule with the saga fence → engine attestation → isolated scorer
  → adapter receipt; infrastructure arms complete their provider crossing
  but carry no outcome; consumer settles + `probe_terminal`),
  `cancel_probe_unit` (authority-fenced zero-start cancellation),
  `reopen` (crash/restart simulation), and `ArmPlan` scenario shapes.
- `masbench/tests/test_sft_v5_probe.py` (new, 9 scenarios):
  1. four benefit units → `candidate`, counterbalanced, plan settled (no
     seventh attempt), with a crash/restart mid-plan restoring exact bank +
     registry roots;
  2. three benefit + one null → native reducer output pinned (`candidate`
     under the 3/4 quorum with strict acceptance);
  3. source-complete/target-catastrophic → `catastrophic_harm`, label
     `harmful`, terminal (harmful transition refuses another epoch);
  4. all-zero stream → never candidate;
  5. six infrastructure units → `infrastructure_exhausted`, zero
     benefit/harm/null votes (cost retained, no efficacy);
  6. incomplete primary → reserve unit (ordinal 4) is the only admissible
     continuation → candidate;
  7. physical-order violation → attempt `quarantine`
     (`physical_arm_order_violation`), zero complete votes;
  8. half-pair (zero-start) cancellation → attempt `cancelled`, no
     survivor-bias evidence, recovery stable, next unit continues;
  9. duplicate unit cannot open twice.

## Invariants established

- Assessment labels come exclusively from `FactorBankV2.recompute_assessment`
  (tests pin its outputs; the harness never computes a second label).
- Infrastructure never updates efficacy; algorithm failure keeps cost and
  enters matched evidence; quarantine consumes roots without votes.
- Every unit is bracketed by `probe_attempt_open`/`probe_terminal` component
  checkpoints; crash/restart restores byte-exact component roots mid-plan
  and mid-lifecycle.

## Tests

- `tests/test_sft_v5_probe.py` → **9 passed** (about 2 minutes; every unit
  drives the full store/journal/engine/scorer chain).
- Regression batch (probe + pair-consumer + generation + saga + store +
  store-derived schedule suites) — run after the store-law change; see
  STATUS row for the recorded result.

## Exit Gate

- [x] Assessments equal the native reducer's expectations for all ten
      plan-listed scenario families (mapped onto the nine tests above).
- [x] No orchestrator-side relabeling exists.
- [x] Crash/restart yields stable state roots (mid-plan and post-cancel).
- [x] Zero paid model calls.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
