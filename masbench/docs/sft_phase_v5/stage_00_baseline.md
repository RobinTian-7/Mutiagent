# Stage 0 — Code & Test Baseline

- Date: 2026-07-17
- Start HEAD: `3c6380d0b57e5872527a65153b310d601e7d50a8` (== plan audit baseline)
- End HEAD: `3c6380d0b57e5872527a65153b310d601e7d50a8` (no code changes in Stage 0)
- Branch: `SFT-Bank`

## Scope

Record the true repo/test state before any v5 implementation work. No code
changes; the only worktree mutations are the untracked `plan.md` (pre-existing,
user-owned) and this report directory.

## Environment

| Item | Value |
|---|---|
| Platform | macOS (Darwin 25.4.0, arm64) |
| System Python | 3.9.6 (unused by packages) |
| Package Python (uv-managed) | 3.13.13 |
| uv | 0.11.12 |
| SQLite | 3.51.0 |
| CI | none available — all results below are local runs |

## Git baseline

```text
git status --short   -> ?? plan.md          (pre-existing, untracked, user-owned)
git rev-parse HEAD   -> 3c6380d0b57e5872527a65153b310d601e7d50a8
git diff --stat      -> (empty)
```

The Silo-Bench submodule (`masbench/third_party/acl26-silo-bench`) was NOT
initialized at session start. It was initialized during Stage 0 via the
AGENTS.md-documented command
`git submodule update --init masbench/third_party/acl26-silo-bench`
(checked out `e74127782ed1c42fff474249961f022c063d76f2`, matching the recorded
gitlink — no gitlink change).

## Test baseline

### Full suites (before submodule init)

- `cd masbench && uv run --extra dev python -m pytest -q`
  → **1 failed, 590 passed, 7 skipped in 33.56s**
  - Failure: `tests/test_silo_partial.py::test_official_lis_is_used_for_sequences`
    — environmental: `uses_official_lis()` falls back to the local copy while the
    Silo submodule is uninitialized.
- `cd exp-graph && uv run --extra dev python -m pytest -q`
  → **783 passed, 2 skipped, 1 warning in 77.38s**
  - Warning (pre-existing): Pydantic serializer warning in
    `tests/test_phase_artifact_registry.py::test_round_trip_rejects_model_copy_program_and_limits_bypass`.

### After submodule init

- `masbench tests/test_silo_partial.py tests/test_sft_phase_pilot.py tests/test_sft_phase_v4_profile.py`
  → **48 passed** (the sole failure above is resolved by submodule init; it was
  environmental, not a code regression).

### SFT targeted suites

- masbench (all 16 `test_sft_*` files) → **171 passed in 12.38s**
- exp-graph (`test_factor_bank*.py test_factory_timeout.py test_phase_*.py test_sft_*.py`)
  → **363 passed, 1 warning in 67.33s**

### `sft_profile=off` characterization (already present, re-verified green)

- `tests/test_sft_phase_pilot.py::test_run_config_and_cli_keep_sft_default_off`
- `tests/test_sft_phase_pilot.py::test_default_path_does_not_import_sft_or_read_key`
  (asserts the off path does not import `masbench.sft_phase_pilot` and never
  reads `MASBENCH_SFT_STATE_KEY` before reaching the legacy client builder)

## Pre-existing failures

- None after submodule initialization. The single full-suite failure was the
  documented environmental submodule condition described above.

## Current profile facts (audited)

- `RunConfig.sft_profile` default `"off"`; only
  `off | phase_v3_shadow_register | phase_v4_single_writer_preliminary` accepted
  (`evolve.py:236`).
- Off path returns from `_validate_v2_config` before any SFT check beyond the
  profile enum; dispatch to `masbench.sft_phase_pilot` is a lazy import guarded
  at `evolve.py:4258`.
- v4 result: `method_status="component_restore_only_no_efficacy_claim"`,
  `model_calls=0`, `total_tokens=0`.

## Exit Gate

- [x] Both suites' real results recorded.
- [x] Pre-existing failures listed (one, environmental, resolved by documented
      submodule init).
- [x] Dirty worktree untouched (`plan.md` untracked, preserved).
- [x] Zero paid model calls (all suites offline/fake).
- [x] `sft_profile=off` characterization has reproducible green results.

Local tests passed; no CI status was available/verified.

Paid model calls: 0.
Scientific status: mechanics-only baseline; no efficacy claim.
