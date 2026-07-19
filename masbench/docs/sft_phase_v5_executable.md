# phase_v5_executable_sft — the executable Sealed Factor–Transition profile

Status: **mechanics_ready is the ceiling of this document.** Nothing here is
an efficacy claim. The fake path proves mechanics only; a real pilot needs
explicit human authorization, a frozen budget, and credentials that this
repository never reads implicitly.

## What v5 is

`phase_v5_executable_sft` extends the mechanics-only v3/v4 profiles into a
recoverable, auditable, falsifiable execution loop:

```
proposal → exact materialization → sealed paired execution
→ split-specific scalar receipt → v3 ArmReceipt → single-use pair consumption
→ FactorBank native assessment → FINAL_VAL whole-snapshot gate → frozen TEST
```

Single facts, single owners: `PhaseArtifactRegistry` (artifacts/proofs),
`FactorBankV2` (scientific transition state), `SingleWriterPilotStore`
(protocol/leases/calls/component bytes/recovery), the external result ledger
(FINAL_VAL/TEST reports, no TRAIN write authority).

## Configuration surface

All required, absolute; frozen inputs must be stable non-symlink files:

```
--sft-profile phase_v5_executable_sft
--sft-state-dir            (provisioned single-writer store; default OUT/sft)
--sft-protocol             (frozen PilotProtocolV1 of this run's arm)
--sft-experiment-manifest  (sealed PilotExperimentSealV1 root)
--sft-runtime-authority    (frozen PilotRuntimeAuthorityManifestV1)
--sft-bootstrap-authority  (frozen PilotBootstrapAuthorityManifestV1)
--sft-result-dir           (external ledger dir; default OUT/sft-results)
```

Plus `MASBENCH_SFT_STATE_KEY` (≥32-byte hex/base64 host master key).
The model surface is frozen: `fake`, or official-endpoint `gpt-4o-mini`,
temperature 0, zero retries, workers=1.

## Provisioning (no model calls)

`masbench.sft_pilot.experiment.provision_phase_v5_experiment` verifies the
full seal graph (authority cross-pins, schedule/case/pair closure, anchor
genesis) and idempotently records generation zero from the frozen structural
anchor. Re-provisioning identical bytes is a no-op; any byte difference
fails closed. v4/v3 databases are never upgraded in place.

## Paid-call protection

The v5 entry raises `PAID_CALLS_NOT_AUTHORIZED` for `--llm openai` unless
`MASBENCH_SFT_PAID_PILOT_AUTHORIZED=yes-i-authorize-paid-gpt-4o-mini-calls`
is set externally. `masbench.sft_pilot.experiment.preview_experiment_budget`
prints the worst-case calls/tokens/cost upper bound for the frozen schedule
so the budget can be frozen before any authorization.

## Real pilot driver (Stage 12)

The armed Stage-12 path is the standalone replicated driver
`masbench.sft_pilot.run_real_pilot` (the `evolve` profile entry stays
fail-closed; arming lives beside the driver, not in the default CLI path):

```bash
# Offline mechanics rehearsal (zero cost, deterministic agents):
uv run python -m masbench.sft_pilot.run_real_pilot --llm fake --replicates 1

# Real pilot — explicit human authorization only:
MASBENCH_SFT_PAID_PILOT_AUTHORIZED=yes-i-authorize-paid-gpt-4o-mini-calls \
uv run python -m masbench.sft_pilot.run_real_pilot --llm openai \
  --replicates 3 --test-cases 12 --agents 5 \
  --parallel-tests 3 --max-parallel-agents 5 --max-concurrent 15
```

Per replicate the driver authors and provisions one sealed experiment over
real Silo n-agent cases (`real_experiment.py`; case commitments are SHA-256
of the raw benchmark file bytes), then drives mutate generation → six-unit
real probe loop (whole-arm runs via `real_runner.py`, real pair journals,
aggregate store metering per `plan_deviations.md` §8) → FINAL_VAL strict
gate → frozen read-only TEST → external result ledger, and finally evaluates
the anchor baseline on the same TEST cases and seeds.  Replicates run
concurrently; a process-wide admission gate (§9) bounds total in-flight
provider calls (default 15 = 3 concurrent tests × 5 parallel sub-agents).
Outputs land under the pilot root: per-replicate `replicate-report.json`,
chained `results/results.jsonl` ledgers, `pilot_report.json`, and
`effect_table.md`.

## Honesty invariants (enforced, tested)

- `sft_profile=off` never imports SFT modules, reads keys, or creates files.
- v3/v4 stay mechanics-only; their results and formats are unchanged.
- Factors/Compositions carry no efficacy; sealed direct transitions own all
  local effect; whole-composition evidence is never split.
- Retrieved-but-not-activated factors earn zero credit; infrastructure never
  updates efficacy; algorithm failure keeps its cost; harness/integrity
  failures invalidate the replicate loudly.
- One pair, one consumption; byte-identical replay is idempotent.
- FINAL_VAL has its own receipt types and cannot write TRAIN evidence; the
  gate selects whole snapshots only; TEST has no writer capability and all
  scientific roots must be byte-identical before/after.
- No raw prompts/answers/shards are persisted anywhere in pilot state.
- Fake transports generate schema-valid scalars from prompt digests only —
  they cannot read answers and never guarantee improvement.

See `docs/sft_phase_v5/` for per-stage reports and `plan_deviations.md` for
the documented store-law completions (half-pair settlement, honest schedule
skip, FINAL_VAL quiescence).
