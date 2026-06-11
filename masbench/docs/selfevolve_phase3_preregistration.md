# Phase 3 pre-registration: stable self-evolution vs cold baseline

Registered 2026-06-10, BEFORE any phase-3 real-LLM run.

## Goal

`bash masbench/scripts/verify_evolve_stable.sh` exits 0 for BOTH
`--evolved-mode select_then_refine` AND `--evolved-mode graph_generate` on a
confirmatory configuration whose eval seeds were never used in development
(drawn randomly on the spot and recorded) and whose TRAIN/TEST case split was
never touched in development. Max 3 confirmatory attempts; a failed attempt
forces method work before the next.

The judge (`verify_evolve_stable.py`, FROZEN — red line, as are
`verify_evolve.{py,sh}`) requires, for every one of the last `--stable-rounds`
(default 2) of `--rounds` (default 3) accumulating evolution rounds:
`mean_em >= baseline + 0.05` AND `wins - losses >= 2` on the held-out
(test case × eval seed) grid, where baseline = the SAME planner pipeline with
empty bank and no motif prior. The judge imports protocol helpers from
`masbench.curve` (`_split_cases`, `_merge_motif`, `_bank_and_motif`,
`_evolved_planner_mode`, `_bounded`); these are treated as frozen protocol:
no behavior changes.

## Confirmatory procedure (fixed before confirmatory; dev results may refine
ONLY the power parameters below, never after a confirmatory attempt starts)

1. Case pool shape (AMENDED 2026-06-11 after dev-2 r1 forensics, before any
   confirmatory attempt): the case list is 10 level-I cases (all of I-01..
   I-10) plus exactly 2 level-II cases drawn by recorded RNG. The
   lexicographic 30% split then yields TEST = {last two I cases, the two II
   cases} and TRAIN = 8 level-I cases. Rationale (recorded in the evidence
   report): lexicographic tails make II-heavier pools structurally
   unwinnable (os-test cases with no learnable os train signal — dev round
   2's split demonstrated this), while provider time-drift makes per-CASE
   diversity, not per-seed diversity, the power lever. The induced split
   must not appear in the dev registry nor equal any P1/P2 split; redraw
   the II pair otherwise.
2. Eval seeds: K=8 fresh random integers (range 10000-99999) drawn on the
   spot by recorded RNG, disjoint from train/val seeds.
3. Run both modes with the same case list + seeds. Exit 0 both = PASS.
4. Budget guard before each attempt; honest-failure clause: "no stable
   detectable effect at this scale" is a legitimate final report.

## Dev split registry (every split used in development; updated per round)

- P1 (burned): TRAIN {I-01,I-02,I-03,I-06,I-09,II-13} TEST {II-15,II-19};
  rotations TEST {I-09,II-13,II-14} etc. (see phase-1 prereg).
- P2 (burned): TRAIN {I-01..I-06} TEST {I-09,II-16}; reserved-confirmatory
  TEST {II-13,II-16} @ n10.
- Dev round 1 (this phase): TRAIN {I-01..I-06, II-13} TEST {II-15,II-16,II-19}
  (pool = I-01..06 + II-13,15,16,19; n=5), eval seeds 11-18.
- Dev round 2 (registered 2026-06-11 before gen-mode dev-1 results): pool =
  I-01 I-02 I-04 I-05 I-07 I-08 II-12 II-13 II-16 II-20 -> TRAIN {I-01,I-02,
  I-04,I-05,I-07,I-08,II-12} TEST {II-13,II-16,II-20}; eval seeds 21-28.
- Dev round 3 (registered 2026-06-11, pilots the amended confirmatory shape):
  pool = I-01..I-10 + II-17 + II-19 -> TRAIN {I-01..I-08} TEST {I-09,I-10,
  II-17,II-19}; eval seeds 31-38. RESULT: both modes FAIL; shape abandoned
  (level-I tail kinds disjoint from train kinds; II-17/19 floors).
- Dev round 4 (registered 2026-06-11): pool = I-01..I-06 + II-13 + II-17 +
  II-18 + II-20 -> TRAIN {I-01..06, II-13} TEST {II-17,II-18,II-20}; eval
  seeds 41-48; code = single version M7+M8 (no mid-driver commits -- dev-3
  hygiene lesson). Question piloted: do II-13-earned seq replays crack
  UNTUNED seq floors? RESULT: NO -- 0 wins in 72 evolved evals; floors are
  model-capability floors. n=10 scout: all-zero (both arms, 5 cases).
- Dev round 5 (registered 2026-06-11, method-final validation): dev-1's
  split (TRAIN {I-01..06,II-13} TEST {II-15,II-16,II-19}) with FRESH dev
  seeds 51-58 and the full current method (M1-M8, code 2ceb76f), both
  modes. Purpose: the positive half of the final report -- the dev-1 PASS
  used round-1 code; M4-M8 were never validated on the known-signal
  geometry (M5/M8 specifically target gen mode's dev-1 failure). Honest
  labeling: this is a DEV split; the result is a method-validation
  measurement, not a confirmatory attempt.

## Method-change ground rules (from the operator brief)

- Anything in the learner may change (SkillCard schema, minister, motif
  credit, retrieval, gate, bank compression, prompts). CF (count_frequency)
  default paths stay byte-identical; full exp-graph + masbench suites green
  before any real run.
- Forbidden: editing `verify_evolve*.{py,sh}`, checkpoint/param selection on
  confirmatory results, hardcoding case IDs in the method, reading
  `masbench/.env`.
- The method must not read the benchmark's `paradigm` label at run time; task
  features may be derived only from `task_description` (text the agents see
  anyway). The `paradigm` label may be used OFFLINE as validation ground truth
  for the feature extractor's tests.
- Budget: cumulative real-LLM spend ≤ $40 (ledger `masbench/runs/COST_LEDGER.json`;
  $12.16 already spent by P1+P2). Reserve ≥ $9 for confirmatory attempts.
  AMENDED 2026-06-11 (operator): cap raised to $60; directive = keep
  exploring until SUCCESS (stable dominance, both modes) or budget
  exhaustion; the honest-failure report is reserved for true exhaustion.
  Mechanism-purity requirement (operator): every claimed win must flow
  through evolved skills -> planner -> deployed organization; round reports
  audit per-win provenance (deployed topology traced to a bank skill_id).
  budget_guard invocations now pass --cap-usd 60.

## Method changelog (applied symmetrically; baseline arm never executes
## learner-internal paths)

- Round 1 (commit 9991fcd): M1 transfer gate, M2 ratchet, M3 chain portfolio
  (details below). Run on dev split 1: refine PASS (r2 +20.8pp, r3 +16.7pp);
  round-1 gate falsely rejected a good bank (3-sample binary val).
- Round 2 (designed from refine-mode dev-1 diagnostics, before gen-mode
  results): M4a LCB retrieval ordering (kappa=0.5 over mean_primary_loss;
  CF skills byte-identical), M4b LCB motif prior
  (MASRuntimeConfig.motif_uncertainty_kappa, default 0 = old behavior;
  masbench sets 0.5), M5 gate seed expansion (gate_seed_factor=3, derived
  seeds s+1009k, val instances only -- never eval seeds) + one-miss noise
  floor (epsilon_eff = max(epsilon, 1/n_samples)). Perf: gate runs
  parallelized (measurement-identical).
- Round 3 (designed from COMPLETE gen-mode dev-1 data, while dev-2 runs
  cb32a26 untouched): M6 contradiction-triggered trust refinement -- rows
  carry a text-derived agg-kind (vote/count/max/.../seq); the ledger keeps
  bucket#kind sub-slots; when a skill's well-measured kinds DISAGREE inside
  a bucket (one >= trust bar, another < it), bucket trust is withdrawn and
  only the case's own kind evidence can authorize replay. Uniform-evidence
  skills keep bucket-level trust (preserves dev-1's II-15 mechanism).
  Trigger: staged_aggregate_to_sink (vote 1.00 n5 / count 0.17 n6, bucket
  mean 0.55) deterministically failed count-kind val every round and the
  gate nuked whole banks x3 in gen mode.
- Round 4 (operator directive: the method must generalize, not overfit
  Silo): M7 -- task features (bucket + agg kind) are produced by the run's
  own LLM answering benchmark-agnostic distributed-computation questions
  (order-sensitivity, answer locality, statistic family from a generic
  vocabulary), temp-0, cached per statement hash (MASBENCH_FEATURE_CACHE).
  The Silo-fitted regexes are demoted to offline fake-LLM fallback / test
  scaffolding (cfg.task_feature_source: llm|heuristic). Layering: the
  benchmark adapter contributes ONLY the task statement; classifier,
  ledger, trust, gates are benchmark-agnostic.
- Round 5 (from dev-3 forensics): M8 trust-breadth -- extrapolating trust
  to an UNMEASURED kind requires >= 2 distinct kinds passing and none
  failing; direct kind evidence always decides when present; narrow
  one-kind evidence earns only that kind (fixes M6's inverted epistemics:
  sparse generated orgs rode "no contradiction" onto foreign kinds while
  only well-measured veterans got demoted). Kind-equality still carries
  the seq-kind II->II transfer that won dev-1.

## Phase-3 round-1 planned method changes (registered before the run)

- M1 evidence-conditioned transfer gate + do-no-harm abstention: skills carry
  a per-task-feature success ledger; at deployment a skill's executable spec
  is replayable on a test case only if the ledger shows real success on a
  feature-matching case; if no skill qualifies, the evolved arm runs the
  EXACT cold path (empty bank, no motif prior). Features from task text only.
- M2 ratchet generation gate: when a round starts from an inherited bank,
  gate j_before is the INCUMBENT bank's held-out generation loss (not the
  empty-bank cold loss), so a round update must beat the previous round.
- M3 portfolio evidence: evidence collection measures a fixed paradigm-
  spanning set of named organizations (aggregation: peer-exponential/tree/
  mesh-star; sequential: chain) so order-sensitive champions can be learned
  when train contains level-II cases.
- M4 (optional) uncertainty-aware retrieval ordering for replay candidates
  (LCB on mean_primary_loss; CF skills unaffected — they never carry the key).
