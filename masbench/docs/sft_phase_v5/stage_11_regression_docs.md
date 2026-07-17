# Stage 11 — Full offline regression, docs & cleanup

- Date: 2026-07-17 · Start HEAD: `28b1c997` · Zero paid calls.

## Full suites (clean, serial, no concurrent edits)

- `cd masbench && uv run --extra dev python -m pytest -q` →
  **677 passed in 249.59s** (0 failed, 0 skipped after submodule init).
- `cd exp-graph && uv run --extra dev python -m pytest -q` →
  **783 passed, 2 skipped, 1 pre-existing warning in 76.22s** — identical to
  the Stage 0 baseline: no exp-graph source change was required anywhere in
  Stages 1–10.
- `git diff --check` → clean. No lint/type tooling is configured in this
  repo (AGENTS.md), so none is claimed.

## Fixed during this stage

- A suite-order class-identity split: the v5 off-path characterization test
  popped every `masbench.sft_*` module and left later files to re-import
  fresh class objects while shared fixtures held the originals (visible only
  in the full run). The test now restores the exact popped modules; the
  isolation assertion is unchanged.

## Covered suites within the full run

v5 targeted (profile/experiment/engine/generation/pair/probe/train
loop/final_val/result ledger/equal budget: 68 tests), fake end-to-end chains
(generation → probe → gate → promotion), crash injection (probe mid-plan,
post-cancellation, post-promotion reopen), authority adversarial (forged
HMACs, cross-split, cross-version, foreign keys, capability constructors),
off-path characterization (including off+v5-fields), capacity stress
(budget preflight/pre-call rejection), replay determinism (idempotent
provision, pair replay, reconcile replay).

## Docs updated

- `masbench/docs/sft_phase_v5_executable.md` (new profile doc incl. pilot
  command template + paid-call protection).
- `masbench/README.md` (SFT profile pointer; v3/v4 mechanics-only + v5
  no-efficacy language).
- `masbench/docs/sft_phase_v5/` stage reports 00–11 + `plan_deviations.md`.
- `archive/` untouched.

## Exit Gate

- [x] Both package suites pass (no pre-existing failures remain).
- [x] Off path has no behavioral regression.
- [x] Docs match the actual CLI surface.
- [x] Zero paid calls.
- [x] `git diff --check` clean; no secrets/run outputs committed.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
