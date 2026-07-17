# Stage 1 — v5 profile & configuration closure

- Date: 2026-07-17
- Start HEAD: `fb2c52e7` (Stage 0 report commit)
- Scope: add `phase_v5_executable_sft` as a fully fail-closed profile. No
  runner, no provisioning, no scientific call, no state creation.

## Changed files

- `masbench/src/masbench/core/config.py` — four new RunConfig fields:
  `sft_experiment_manifest_path`, `sft_runtime_authority_path`,
  `sft_bootstrap_authority_path`, `sft_result_dir` (all default `None`).
- `masbench/src/masbench/evolve.py` —
  - profile enum accepts `phase_v5_executable_sft`;
  - new v5 validation branch: all five paths required + absolute; provider
    closed to `fake` or official-endpoint `gpt-4o-mini`; planner model frozen;
    `temperature == 0.0` required;
  - non-v5 active profiles reject the v5-only path fields;
  - the `workers=1` single-writer requirement now covers v5;
  - `sft_protocol_path` error message covers v4/v5.
- `masbench/src/masbench/cli.py` — `--sft-profile` gains the v5 choice; new
  flags `--sft-experiment-manifest`, `--sft-runtime-authority`,
  `--sft-bootstrap-authority`, `--sft-result-dir`; `_cmd_evolve` resolves them
  to absolute paths (result dir defaults to `OUT/sft-results` for v5 only).
- `masbench/src/masbench/sft_phase_pilot.py` — `_V5_PROFILE` constant; the
  dispatcher routes v5 to a lazily imported
  `masbench.sft_pilot.scientific_runner.run_phase_v5_executable_sft` and
  rejects synthetic held-out rows / initial skills on direct entry. v3/v4
  branches untouched.
- `masbench/src/masbench/sft_pilot/scientific_runner.py` — new module. Stage 1
  scope only: master-key gate, physical closure of all four frozen inputs
  (absolute, O_NOFOLLOW, stable dev/ino, non-symlink regular file, bounded
  bytes), protocol parse + v5 namespace closure (shared v4 law plus
  `component_checkpoint_saga_required` and `store_derived_schedule_required`),
  pre-provisioned store requirement, then an explicit fail-closed error — this
  build cannot authorize scientific execution.
- `masbench/tests/test_sft_v5_profile.py` — new (13 tests, most parametrized;
  34 cases): CLI surface, happy config validation, 24 fail-closed config
  variants, workers>1, missing key before state creation, missing frozen
  inputs before state creation, symlinked experiment manifest rejection,
  legacy scientific input rejection (both entries), off-path laziness with v5
  fields populated.

## Invariants established

- `sft_profile="off"` with populated v5 paths still never imports any
  `masbench.sft_*` module, reads no key, creates no file (tested).
- v5 cannot run: every path ends in a raise; zero model calls by construction.
- Missing/relative/symlinked authority fails before any state or result
  directory exists.
- v3/v4 result shapes and validation semantics unchanged.

## Tests

- `uv run --extra dev python -m pytest -q tests/test_sft_v5_profile.py
  tests/test_sft_phase_pilot.py tests/test_sft_phase_v4_profile.py
  tests/test_cli.py` → **62 passed**.
- Full masbench suite after the change → **631 passed, 0 failed** (the seven
  Stage 0 skips now run because the Silo submodule is initialized; the count
  additionally grew by the 34 new v5 cases).
- Fixed during development: the evolve-entry legacy-input test initially
  omitted the env key (the key gate fires first); the test now sets the key
  and additionally covers direct entry, mirroring the v4 convention.

## Exit Gate

- [x] Off-path results/calls/files identical to Stage 0 (characterization
      tests green, including the new off+v5-fields case).
- [x] v5 performs config validation only; no success path exists.
- [x] Zero scientific calls (no client construction anywhere in the branch).
- [x] All related tests pass.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
