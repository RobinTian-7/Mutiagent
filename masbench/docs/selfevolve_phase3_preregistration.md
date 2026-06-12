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

## OPERATOR BAR RAISE (2026-06-11, before any confirmatory attempt)

The acceptance bar is raised: self-evolve must UNCONDITIONALLY beat the
BEST single topology in the baseline pool (fixed_best_on_train), not the
mean / cold start. Instrument: the FROZEN phase-2 judge
`scripts/verify_beats_baselines.py` (4-arm paired; PASS needs >=5pp AND
win-margin >=2 vs EACH of select / graphgen / fixed_best). Confirmatory now
requires BOTH frozen judges to exit 0 on both modes (stable curve judge +
beats-baselines judge). Priority AMENDED by operator
(2026-06-11, superseding the earlier refine-priority): when gen and
refine conflict, GEN has priority, and gen gets a longer evolution
runway (hypothesis: ~5 rounds needed for its advantage to emerge;
testable now that round-12 gave gen per-round exploration). Mechanical consequence registered: abstention is
neutral vs the cold baseline but LOSES vs fixed-best -> deployment gains a
tiered fallback (kind-trusted replay -> strong-bucket-trusted best skill ->
cold) so uncovered cases hold parity instead of bleeding pairs.

## Confirmatory procedure (fixed before confirmatory; dev results may refine
ONLY the power parameters below, never after a confirmatory attempt starts)

1. Case pool shape (AMENDED 2026-06-12, SHAPE v3, before any phase-3
   confirmatory attempt; supersedes the 10I+2II shape, which dev-3
   piloted and FAILED structurally — lexicographic level-I tail kinds
   are disjoint from train kinds, so the shape has no power for ANY
   method). Pool = 7 level-I cases drawn by recorded RNG from
   {I-01..I-10} + the fixed II quartet {II-13, II-15, II-17, II-19}.
   Lexicographic 30% then yields TEST = {II-15, II-17, II-19} and TRAIN
   = {7 I cases + II-13}. Rationale, all dev-evidenced: (a) II-13 is the
   benchmark's only os anchor that is learnable in train at n=5 and must
   sort OUT of the test tail (a 4th II case after II-13 achieves this);
   (b) the winnable-geometry enumeration (dev-2/3/4 + n=10 scout) shows
   the only II cases with dynamic range at n=5 are II-13/15/16/19 (+
   II-17 marginal via instruction rewrite); every other shape is floor
   or kind-disjoint; (c) provider time-drift makes per-CASE diversity
   the power lever. HONEST LIMITATION (recorded): at n=5 this benchmark
   has NO untouched live II cases left — the II quartet appeared in dev
   splits (registry above). "Untouched split" is therefore satisfied at
   the PARTITION level (the RNG-drawn 7-I subset must induce a split
   not in the dev registry and not equal to any P1/P2 split — the dev
   rounds used a 6-I pool, so any 7-I draw differs) plus never-used
   eval seeds; the operator may veto this interpretation before the
   first attempt.
2. Eval seeds: K=8 fresh random integers (range 10000-99999) drawn on the
   spot by recorded RNG, disjoint from train/val seeds.
3. Run both modes with the same case list + seeds; BOTH frozen judges
   (stable + beats-baselines) per the bar raise above. All four exit 0 =
   PASS.
4. Budget guard before each attempt; honest-failure clause: "no stable
   detectable effect at this scale" is a legitimate final report.
5. Cache hygiene (added 2026-06-12 with M18): confirmatory attempts run
   with FRESH EMPTY caches (no cross-run evcache/feature/evalcache
   seeding) so every confirmatory number is a fresh measurement; the M18
   resume layer may only replay rows the SAME attempt already paid for
   (mid-attempt crash recovery), never rows from dev runs or earlier
   attempts.

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
- Round-8/9 screens (cheap judge, seeds 61-63 / 71-73): case sets = dev-1's
  and dev-4's; outcomes in lab_records/round_09.
- Dev round 6 (registered 2026-06-11, stable judge, code 37c64ea): pool =
  I-01 I-02 I-04 I-06 I-07 I-08 + II-13 + II-15 II-17 II-19 -> TRAIN
  {I-01,I-02,I-04,I-06,I-07,I-08,II-13} TEST {II-15,II-17,II-19}; eval
  seeds 81-88; both modes. Mixes a known-range case, a cracked floor, and
  a near-floor.
- Dev round 8 (registered 2026-06-11, code 5928fcb round-12: tiered
  fallback + gen exploration): dev-7's split, fresh seeds 101-108. Three
  runs: (a) gen STABLE --rounds 5 --stable-rounds 2 (operator 5-round
  hypothesis, now mechanistically meaningful); (b) 4-arm
  verify_beats_baselines gen --rounds 5; (c) 4-arm refine --rounds 3.
  First direct measurement of the fixed-best bar.
- Dev round 9 (registered 2026-06-11, code c78be6e round-15: M14
  Preserve/Modify + M15 gen portfolio parity): dev-8's split, fresh seeds
  111-118, THREE PARALLEL runs (stable gen 5r; 4-arm gen 5r; 4-arm refine
  3r). Operator priorities: stable gen evolution; beat fixed-best.
- Dev round 7 (registered 2026-06-11, code 764bcb0 round-10 stability
  fixes): SAME split as dev-6, fresh seeds 91-98, both modes -- the direct
  A/B for replay-first + sticky margin + instruction-keeping dedupe
  (dev-6: gen PASS, refine r3 reshuffle FAIL).
- Dev round 5 (registered 2026-06-11, method-final validation): dev-1's
  split (TRAIN {I-01..06,II-13} TEST {II-15,II-16,II-19}) with FRESH dev
  seeds 51-58 and the full current method (M1-M8, code 2ceb76f), both
  modes. Purpose: the positive half of the final report -- the dev-1 PASS
  used round-1 code; M4-M8 were never validated on the known-signal
  geometry (M5/M8 specifically target gen mode's dev-1 failure). Honest
  labeling: this is a DEV split; the result is a method-validation
  measurement, not a confirmatory attempt.
- Dev round 10 / 10b / 10c (registered 2026-06-11; recorded 2026-06-12):
  dev-9's split, fresh seeds 121-128, three parallel runs each (stable
  gen 5r; 4-arm gen 5r; 4-arm refine 3r). dev-10 = INVALID infra (httpx
  cookie-jar 431s poisoned all arms; measurements discarded, no method
  conclusions). dev-10b = M16 validation (code 9e7ad7b): NET NEGATIVE,
  composite-slot starvation. dev-10c = M16b + M18 validation (code
  bdf3ea8, killed at 5 min by operator pause then RESUMED from caches):
  stable_gen PASS 5/5 dominate; beats_refine PASS (first-ever 4-arm);
  beats_gen FAIL on the select arm only (+4.2pp 4:3 = same-policy drift
  width). Same seeds reused across 10/10b/10c deliberately: they rerun
  the SAME registered measurement after an infra fix and two method
  fixes, not new draws.
- Dev round 11 (registered 2026-06-12, code = round-18 state): stable
  judge, select_then_refine, dev-9's split, SAME seeds 121-128, --rounds
  3. Purpose: stable_refine has not run since M14/M15/M16/M16b landed
  (last stable_refine PASS was dev-7 on round-10 code); the confirmatory
  requires BOTH judges BOTH modes, so this is the last unmeasured
  judge x mode cell on current code. Caches seeded from dev-10c (same
  split+seeds; bank-independent rows + cold baseline replay).

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
  AMENDED AGAIN 2026-06-11 (operator): cap raised to $100
  (budget_guard --cap-usd 100); stable evolution (especially gen mode)
  added to the deliverables; other benchmarks may corroborate
  generalization; ultimate goal = evolve stably beats the BEST baseline.

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
- Rounds 6-9 (from dev-5 72/72-abstention forensics; one cohesive batch):
  M9 instruction-carrying replay (ProtocolStepSpec.instruction -> runner
  merge-prompt injection behind enable_step_instructions; deploy-time
  architect rewrite with parse-retry; CF byte-identical); M10 train-time
  verified recipe search (Reflexion/STaR-style propose->execute->verify
  on 2 seeds; shard-literal leakage scan; trigger parity so recipe cards
  reach seeded slots); M11 structural-identity ledger
  (topology_equivalence_hash keys the trust ledger; family merge); M12
  needs_lossless binary trust key (replaces the 14-way kind taxonomy
  that fractured trust); M13 explicit rule_action stamps.
- Round 10 (from dev-6 refine r3 reshuffle): deployment stability --
  instruction-keeping structural dedupe, replay_first candidate
  selection, motif_displacement_margin=0.1 sticky incumbent.
- Round 12 (from dev-8 abstention-bleeds-pairs vs fixed): tiered fallback
  (kind-trusted replay -> strong-bucket generalist -> cold) + gen-mode
  per-round exploration.
- Rounds 14-15 (from dev-8 4-arm forensics): M14 evidence-conditioned
  Preserve/Modify (direct slot evidence => preserve verbatim; otherwise
  Modify = instruction rewrite); M15 gen portfolio parity (named
  aggregators into gen-mode evidence).
- Rounds 16-16b (from dev-9/dev-10b): M16 answer-shape trust bit (slot =
  bucket#(lossy|lossless)-(scalar|composite)); M16b shape-sibling
  extrapolation (an unmeasured shape slot inherits the sibling-shape
  verdict with action auto-Modify; the losslessness axis NEVER
  extrapolates). Fixes M16-as-shipped composite starvation.
- Round 17 (operator directive, infra not method): M18 resume layer --
  MASBENCH_EVAL_CACHE replays deployment-phase rows keyed by
  (case,seed,cfg,planner_mode@bank_state_hash); recipe-result cache;
  env-unset = byte-identical behavior. Resume = relaunch the same
  driver. Confirmatory cache hygiene clause added to the procedure.

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
