# Stage 12 — first real pilot (2026-07-17)

```
Status: pilot_usable
Authorization: explicit human request in-session; MASBENCH_SFT_PAID_PILOT_AUTHORIZED set externally
Model: official OpenAI gpt-4o-mini, temperature 0, SDK retries 0 (scientific arms un-retried)
Worktree: a1ee8941 + uncommitted Stage-12 arming (real_experiment/real_train/real_eval/
          run_real_pilot, llm concurrency gate, real_runner integration)
Driver: masbench.sft_pilot.run_real_pilot --llm openai --replicates 3 --test-cases 12
Output root: masbench/runs/sft_v5_real_run2/ (gitignored; ledgers+seals+journals inside)
```

## Design actually executed

- 3 independent sealed replicate experiments over real Silo-Bench n=5 cases
  (case commitments = SHA-256 of raw benchmark file bytes; per-replicate
  6 probe + 1 generation + 2 FINAL_VAL cases disjoint from a shared 12-case
  TEST holdout).
- Each replicate: metered mutate generation → six-unit real probe loop
  (whole-arm runs, real pair journals, aggregate store receipts per
  plan_deviations §8) → FactorBank native assessment → FINAL_VAL strict gate
  → frozen read-only TEST → chained external ledger.
- Baseline arm: the structural-anchor program (current QueenBee static
  deployment) on the same TEST cases/seeds, same runner/scorer/client stack.
- Concurrency: 3 replicates concurrent × max_parallel_agents=5, process-wide
  admission cap 15 (plan_deviations §9). Observed peak_in_flight = 15, never
  exceeded. Wall time 759 s for 1,542 provider calls.

## Outcomes (falsifiable, per the preregistered endpoints)

- Protocol validity: 12/12 probe pairs complete (no cancellations, no
  infrastructure failures, no budget violations); scientific roots identical
  before/after every frozen TEST; all ledgers re-verify.
- Generation: all replicates proposed hub value 2 (valid, non-duplicate).
- Paired TRAIN evidence (hub 0→2): target D=6 vs source D=8 messages in
  12/12 units; target cheaper in C in 10/12 units. Assessments: candidate
  (r1: 4/4 units), candidate (r3: 3/4), neutral (r2: 2/4) — the reducer
  discriminated, and the neutral replicate deployed nothing.
- Gates: both candidates accepted with reason `equal_quality_lower_cost`;
  deployment heads advanced to the gated target snapshots.
- TEST (12 held-out cases, paired vs baseline): quality is at floor in this
  configuration (S=P=success=0 for every arm — gpt-4o-mini under either
  program does not fully solve Silo at n=5), so quality endpoints are
  uninformative; V=1.0 everywhere. Cost endpoints moved: deployed programs
  used D=6 vs 8 and C −8.6 % (r1) / −12.3 % (r3) per case, against a
  same-program run-variance control of −1.8 % (r2, anchor vs anchor).
- All-in budget: 1,542 calls, 1.56 M input + 0.37 M output tokens,
  ≈ $0.45. SFT arms ≈ 430–450 calls each (search+gate+TEST) vs baseline 245
  (TEST only) — the deployment-level comparison is equal-budget per TEST
  case; the search spend is reported, not hidden.

## Second pilot: all_agents goal + per-agent submission barrier (2026-07-17)

Root cause of the first pilot's quality floor: the sink-mode init prompt
instructs non-sink agents to keep ``structured_state.answer = null`` unless
their shard alone determines the global answer, the merge answer channel then
relays only extracted answers (nulls), and sink mode has no submission
barrier — a null cascade by prompt design, not model refusal.

Fix (real_runner): under ``information_goal=all_agents`` every arm run now
appends the runtime-owned final submission barrier
(``run_final_submission_barrier``: per-agent submit prompt + final belief →
one non-empty JSON answer, bounded format-only retries), scored with
``all_agents_exact``; barrier usage is included in the arm's metering truth
(paper C counts it under its own law, so the §8 consistency assert is
``C <= metered`` for all_agents).

Rerun (``runs/sft_v5_real_aa``, ``--goal all_agents``, 3 replicates, 12 TEST
cases, 1,018 calls ≈ $0.20, 438 s, peak in-flight 15/15):

- Quality endpoints are now live: every agent submits a concrete answer;
  baseline solves I-04 with all five agents exactly (success 0.091), other
  failures are informative (agents submit LOCAL aggregates — incomplete
  propagation), II-14 hit an honest APITimeoutError infra row in 3/4 arms.
- All three replicates' generation again proposed hub 0→2; under all_agents
  this is a genuine structural mismatch (gather hub 0, broadcast hub 2 —
  the broadcaster holds no gathered state), and the native reducer settled
  ``harmful`` from just TWO real paired units per replicate (target K
  1.0→0.4, stage 0.5→0.08): no gate ran, nothing deployed, TEST stayed the
  anchor everywhere (paired deltas within ±3 tokens noise).
- Falsification working as designed: the same mutation the sink-mode gate
  accepted on cost is correctly REJECTED as harmful when every agent's
  answer matters. The anchor's single int locus is a dead-end search
  dimension under all_agents — motivating multi-base anchors over
  simultaneous-aggregation structures (consensus/pairwise/exponential) and
  paper-protocol control arms as the next design.

## Honest limits

- Single-transition confirmatory scope (one mutate per replicate — the
  sealed schedule law); "medium-large" scale came from replicates + TEST
  breadth, not multi-round search.
- Quality floor: no evidence about quality improvement is available from
  this configuration; the observed effect is cost/coordination-structural
  (C/D) under equal quality, exactly what the gate reason states.
- Control arms (`current`/`whole_artifact_receipt`/`ect_whole_transaction`)
  were sealed but not executed as live search loops; the baseline here is
  the anchor incumbent. Credit-law comparisons remain future work
  (Stage 13).
- A duplicate generated value aborts the sealed single-action experiment
  honestly (offline-tested); the real run did not hit this path.
