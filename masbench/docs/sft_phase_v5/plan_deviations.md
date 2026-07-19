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

## 8. Whole-arm aggregate model-call metering (Stage 12)

- The plan's metering sketch assumed one store call receipt per provider
  crossing. A real probe/FINAL_VAL arm is one whole `ProtocolRunner` run over
  a compiled Phase program (n-agent init + per-step merges + bounded JSON
  retries), whose internal call count and per-call prompts are produced
  case-side at run time — they cannot be enumerated in an outcome-before
  frozen schedule.
- New law (`real_runner.py` + `real_train.py`): one probe arm = ONE aggregate
  store call receipt. The scheduled request envelope commits to the exact arm
  coordinates (pair, arm, operation, case commitment); `complete_call`
  records the runner's provider-authoritative token sums; reservations are
  sized as deliberate whole-arm upper bounds
  (`PROBE_INPUT_TOKENS_RESERVED`/`PROBE_OUTPUT_TOKENS_RESERVED`) and a
  completed receipt still fails closed above them. The PROBE phase call-slot
  pool authorizes the true per-arm internal call ceiling
  (`PROBE_MODEL_CALLS_PER_ARM`, threaded through the factor authority's
  divide-by-twelve plan budget) while the schedule keeps exactly one
  aggregate slot per arm.
- The real per-call counts still travel in scientific evidence: the
  `ArmReceiptV2` `ExecutionUsage` and the `DenseOutcome` C/D carry the same
  runner sums the store receipt records, and the driver asserts the three
  views agree. Provider-crossing identity/recovery below arm granularity is
  deliberately given up; the no-retry law holds at arm granularity (a failed
  arm run marks its aggregate call indeterminate, cancels the pair journal,
  and settles the attempt through the authority-fenced cancellation path —
  no partial-pair evidence survives).

## 9. Process-wide LLM admission gate for concurrent harness layers (Stage 12)

- The plan froze `parallel_model_calls = 1` per writer. That law is intact
  per store (single writer, linear physical schedule), but the pilot runs
  several independent replicate experiments concurrently and each whole-arm
  run fans its sub-agents out (`max_parallel_agents`).
- New infrastructure (`exp_graph.llm.concurrency`): one process-wide
  admission semaphore caps total in-flight real-LLM calls (default off;
  explicit `configure_global_llm_concurrency(...)` or
  `EXP_GRAPH_LLM_MAX_CONCURRENCY`). It wraps every factory-built client and
  the pilot's metered generation transport, OUTSIDE the wall-clock guard so
  an abandoned hung call can never leak a slot, and INSIDE any retry wrapper
  so backoff sleeps never hold one. Peak in-flight is recorded in the pilot
  report as evidence the configured ceiling was respected.

## 10. Whole-composition (structural) channel: ordinary edges, surrogate saga lineage

The skeleton-search channel opens `WholeCompositionTransitionV2` end-to-end
(S1–S3, 2026-07-19). Four deliberate deviations from a literal reading of the
direct-chain plan, each preserving the underlying law:

- **Ordinary edges, no Bank proposal action.** The schema gives whole
  transitions no `proposal_action_*` closure, and `register_whole_transition`
  guards ordinary-owner laundering instead. The committed-intent role is
  played by the frozen structural operation domain
  (`FrozenStructuralDomainV1`: op vocabulary, phase kinds, phase-count and
  compiled-step bounds, already-registered-image exclusions) whose digest is
  the auditable intent, and by the content-complete
  `PhaseStructuralOperationProofV1` (deterministic replay: apply the typed
  operation, byte-compare the target program, recompute skeleton/image/receipt
  digests). The Bank re-runs this proof through its trusted whole-operation
  verifier at registration and audit; proofs persist in the run root
  (`structural_proofs.json`) and resolve through the factor authority.
- **Saga lineage by surrogate.** The checkpoint saga stays mandatory. Whole
  chains start at a new first kind `whole_edge_registered` (there is no
  pre-generation Bank record — the one metered call PRODUCES the edge) and
  thread the existing action fields with exact transition surrogates
  (`action_id` = transition id, branch = origin branch, intent =
  operation receipt sha, epoch = operation verifier epoch, after-sha =
  canonical transition), discriminated by the witness's new `owner_kind`.
  Downstream kinds join `plan.transition_id` to the carried transition id.
- **Provider-crossing exemption for the one structural generation.** The
  crossing law requires an open lifecycle checkpoint; the structural
  generation necessarily precedes its chain's first checkpoint. The store
  admits exactly this crossing — `proposal_generation` lease with
  `action_id IS NULL` (unreachable for direct chains) against the genesis
  recovery head with zero prior checkpoints. A crash between the call and
  the first checkpoint ends the experiment as an honest degenerate, the
  same terminal semantics as a direct chain crashing between generation and
  reconcile. Probe crossings keep the full open-checkpoint law (probe
  leases carry the transition id).
- **Whole-arm activation = the skeleton factor.** The execution capability
  schema requires a non-empty activated set; a whole arm activates the
  loaded composition's locked structural-skeleton factor (`psk:` revision)
  under image-load — the structural identity the image load genuinely
  activates. Bank receipts still carry an EMPTY activated direct-factor set
  and support id = transition id (`make_arm_receipt_v2`'s whole law), so no
  scalar can earn credit. The materialization event of a whole edge is the
  target artifact's registration, committed by its execution-image MAC.

Channel separation stays structural: an operation whose source and target
project to the same skeleton is rejected at proof time ("direct-factor
channel"), compiled-image aliasing (compiler elision) and unchanged programs
abort as honest no-ops, and structural chaining past one round is fenced
until Anchorize (S4) lands.
