# Stage 3 — full-factor-v3 exact execution closure

- Date: 2026-07-17
- Start HEAD: `02806a16`
- Scope: the exact engine boundary accepts `RegisteredPhaseFactorEdgeV3` under
  a full-factor-v3 protocol, replays the complete canonical bundle, and keeps
  the image-loaded-only activation law. No scientific Bank update; zero model
  calls.

## Changed files

- `masbench/src/masbench/engine.py` — `register_exact_phase_execution_result`
  now dispatches on the frozen protocol's `namespace.binder_version`:
  - `facts-phase-leaf-v2` → v2 edge model + v2 verifier + single background
    factor (byte-identical prior behaviour);
  - `facts-phase-full-v3` → `RegisteredPhaseFactorEdgeV3` (re-parsed from a
    dump, so v2/v3 objects can never impersonate each other — each closed
    model forbids the other's fields), `make_phase_v3_binding_verifier`
    (which re-verifies the registry proof, rebuilds the full-factor bundle,
    and requires exactly one scalar-leaf delta over an identical scalar
    domain), background = locked structural skeleton + every unchanged
    scalar factor;
  - any other binder → fail closed.
  All downstream laws unchanged: sanitized source authority, image/activation
  exactness, `image_loaded`-only, six-event journal pair, SQLite lease/call
  closure, HMAC'd opaque capability. Docstring updated.
- `masbench/tests/test_sft_v5_engine_v3.py` (new, 7 tests): v3 happy path
  (activated set == exactly the changed source factor; retrieved set == both
  changed revisions; selected==loaded artifact; attestor round-trip); v2 edge
  under v3 protocol and v3 edge under v2 protocol both rejected; unknown
  binder rejected; background-drop / source-target-swap / wrong-slot tampers
  rejected via the canonical-bundle replay; step-activation locus
  (`/phases/0/instruction`, `trusted_trace_event`) fails closed at execution
  while keeping structural identity; cross-namespace proof rejected; forged
  capability constructor rejected.

## Invariants established

- Exact-one-factor and full-composition closure are host-proven (registry
  proof + canonical v3 bundle replay), never claimed by the caller.
- v5's initial activation support domain is `image_loaded` only; instruction
  and submission loci retain structural identity but cannot enter scientific
  execution.
- v2/v3 alias mixing fails closed in both directions.

## Tests

- `tests/test_sft_v5_engine_v3.py` → **7 passed**.
- Regression: v2 boundary suite + v5 experiment suite + engine suites
  (`test_sft_execution_attestation.py`, `test_sft_v5_experiment.py`,
  `test_engine_fake.py`, `test_engine_planner.py`,
  `test_engine_skill_bank.py`) → **28 passed**.
- exp-graph `tests/test_phase_factor_binding_v3.py` → **10 passed** (verifier
  semantics unchanged).

## Notes

- The plan's optional exp-graph helpers (v5 image-load eligibility predicate,
  reverse-verification helper) are deferred to the stage that first consumes
  them (retrieval, Stage 7) to avoid speculative API surface; the engine-side
  closure needed none of them.

## Exit Gate

- [x] v3 exact execution attestation can be minted (fake fixtures, no model).
- [x] Only supported (image_loaded) loci pass.
- [x] Raw results/caller dicts cannot mint receipts (model re-parse + opaque
      capability token, tested).
- [x] No scientific Bank update anywhere in the boundary.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
