# Stage 12/13 preparation (execution NOT RUN)

```
Stage 12 execution: NOT RUN
Reason: paid model calls are outside this task's authorization
Prepared: yes
```

- Frozen manifest schemas: PilotExperimentSealV1 + embedded children +
  authority manifests (Stage 2).
- Provisioning CLI surface: `provision_phase_v5_experiment` (idempotent,
  fail-closed).
- Experiment controls: per-arm policy-gated backends + equal all-in budget
  verifier (Stage 10).
- No-retry metering: PilotMeteredLLMClient (+ scheduled envelopes, saga
  fence); OpenAIPilotTransport constructed only explicitly.
- Report/analysis surface: external chained result ledger + gate report
  roots; TEST manifest sealed by commitment.
- Protocol validity: seal graph validation + store chain verification on
  every open.
- Dry-run rehearsal: the full fake end-to-end suite (Stages 4–9 tests).
- Real pilot command template + worst-case budget preview
  (`preview_experiment_budget`): see `docs/sft_phase_v5_executable.md`.
- PAID_CALLS_NOT_AUTHORIZED guard: `--llm openai` raises unless the external
  `MASBENCH_SFT_PAID_PILOT_AUTHORIZED` marker is set (tested).
- Additionally, this build keeps the v5 scientific loop fail-closed at the
  profile entry until a real pilot is explicitly armed.

Remaining pre-pilot hardening (documented, not blocking mechanics):
FINAL_VAL deployment-execution attestation variant of the engine boundary;
two-phase signed archive eviction; multi-round protocols beyond the
single-transition confirmatory scope.
