# Plan deviations & adaptations

Only entries that change previously frozen code semantics or adapt plan
pseudocode to the repository's actual shapes. No entry weakens a closed
schema, authority, split, pairing, budget, gate, or TEST-freeze law.

## 1. Experiment seal realized as a new root object (Stage 2)

- Plan sketch: a `PilotExperimentManifestV1` carrying authority/protocol
  roots. The repo already had a validated `PilotExperimentManifestV1`
  (multi-arm children) and `PilotRuntimeAuthorityManifestV1` (git commit,
  bootstrap digest, runner/schedule/method-policy roots).
- Adaptation: `PilotExperimentSealV1` embeds the existing manifests and pins
  the remaining plan-listed facts (authority digests, TEST/report
  commitments, split roots, anchor genesis). All plan-listed facts are
  sealed; existing schemas untouched.

## 2. Factor authority operates on the probe arm subset (Stage 4)

- Pre-existing code required a protocol's `authorized_logical_arms` to be
  exactly the twelve probe arms; a v5 protocol also authorizes generation
  and FINAL_VAL arms (plan 9.1 explicitly schedules this adaptation).
- The exact six-pair/twelve-arm law is preserved over the probe subset;
  protocols with only probe arms behave byte-identically.

## 3. Store-derived schedules pin outcome-before call envelopes (Stage 4)

- The metered client derived its call identity from prompt bytes, which is
  circular under a frozen schedule (the schedule digest lives inside the
  protocol, which would live inside the envelope). The client now reserves
  under the schedule's frozen envelope while the exact prompt-byte
  commitment is recorded in the durable reserve/start operation payloads,
  and the Bank generation lease still pins the full request digest.

## 4. probe_terminal settlement law conditioned on attempt state (Stage 6)

- Pre-existing store law required a completed second-arm crossing for every
  `probe_terminal` checkpoint, which made the plan's half-pair cancellation
  law unrepresentable (a crashed pair could never publish its settlement and
  the saga wedged).
- New law: `complete` → completed second arm (unchanged);
  `incomplete`/`quarantine` → completed or permanently indeterminate;
  `cancelled` → additionally `reserved`/`failed_before_start` (terminal for
  that logical arm under no-retry + global arm uniqueness). This enables the
  plan's cancellation semantics; it does not admit any new evidence path
  (commit still requires completed crossings for complete pairs).

## 5. Honest linear-order skip for settled plans (Stage 8)

- The frozen execution schedule is strictly linear, but a probe plan may
  settle before its reserve units run. New store API
  `abandon_reserved_execution` terminalizes a never-started reserved lease
  as `failed_before_start` with a receipted reason;
  `skip_settled_probe_blocks` reserves-and-abandons the unused blocks in
  frozen order. No call can ever exist for an abandoned lease and the
  logical arms stay globally consumed.

## 6. FINAL_VAL quiescence law (Stage 8)

- Pre-existing store law required a *promoted* bundle before any FINAL_VAL
  crossing, but promotion requires the settled gate checkpoint, and the gate
  receipt requires FINAL_VAL evidence — a three-way deadlock that made the
  gate unreachable. New law: FINAL_VAL crossings run against the promoted
  head OR an unpromoted head whose latest checkpoint is a settled
  `probe_terminal` (no TRAIN provider stage in flight). Open TRAIN stages
  still block FINAL_VAL.

## 7. Gate receipt closure over the Bank's own strict summary (Stage 8)

- `FactorBankV2.apply_gate` closes `aggregate_summary_sha256` over the
  settled TRAIN strict summary, and the factor authority pins
  `gate_config_sha256` to the sealed plan's aggregate policy. The external
  FINAL_VAL report therefore binds the receipt via `decision_id` (and the
  Stage-9 result ledger), and the strict parameters are read from the frozen
  plan policy — never from caller arguments.
