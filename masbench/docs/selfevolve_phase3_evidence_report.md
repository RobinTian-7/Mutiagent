# Phase 3 evidence report: stable self-evolution vs cold baseline

Living document; the frozen judge is `scripts/verify_evolve_stable.py`
(PASS = last 2 of 3 accumulating rounds each beat the same-pipeline cold
baseline by >=5pp mean with win-margin >=2 on a disjoint held-out case x
seed grid). Prereg: `selfevolve_phase3_preregistration.md`.

## Verdict (to be filled at confirmatory)

- Confirmatory attempts used: 0/3.

## Dev round 1 (split: TRAIN {I-01..06, II-13} / TEST {II-15,16,19}, seeds 11-18)

Code: commit 9991fcd (M1 transfer gate, M2 ratchet, M3 chain portfolio).

- **select_then_refine: PASS** — baseline 20.8%; r1 20.8 (gate false-reject,
  see below); r2 41.7* (+20.8pp, 8:3); r3 37.5* (+16.7pp, 8:4).
  Report: `lab_records/round_01/stable_select_then_refine_n5.json`.
- **graph_generate: FAIL** — the gate rejected the learned bank in ALL
  THREE rounds (j 0.0 -> 0.333 each; skills=0 every round; curve 8/12/21% is
  pure cold-eval noise). Report:
  `lab_records/round_01/stable_graph_generate_n5.json`.

Mechanism findings (diag `runs/p3_dev1/`):

1. **Transfer trust works and beats paradigm bans.** The deployed
   organization `one_peer_exponential_dag_star` earned os-bucket trust from
   II-13 train evidence; replayed onto held-out II-15 it scored 88% vs cold
   44%, and onto II-16 25% vs 6% — the SAME case where P2's case-blind
   replay of `tree_reduce_to_sink` scored 0/8. Evidence-conditioned trust
   (does THIS org succeed on feature-matched tasks?) generalizes where a
   paradigm-label ban would have forfeited the win.
2. **3-sample binary gate = coin flip** (both modes, round 1): cold 3/3 vs
   deployed 2/3 on val {I-02,I-04,I-06} x seed 3 nuked genuinely-good banks.
   Fixed in round 2 (M5). REFINED by the complete gen-mode data: the gen
   misses were NOT noise — `staged_aggregate_to_sink` failed the count-kind
   val case I-02 deterministically every round while its TRAIN ledger
   already showed kind bimodality (vote 1.00 n=5, count 0.17 n=6; bucket
   mean 0.55 cleared the trust bar). Bucket-mean trust hides intra-bucket
   contradictions -> M6 (round 3): contradiction-triggered refinement of
   trust to agg-kind granularity ("trust at the coarsest granularity
   consistent with the evidence"); uniform-evidence skills keep bucket
   trust, which is what preserved the II-15 win. Gate rejection was
   *symptomatically right but structurally wrong*: it nuked 10 skills
   (including the os-bucket winners) to stop one kind-mismatched replay.
3. **Champion flip by 1-row lucky org** (refine r3): a fresh explore org
   displaced the proven champion in raw-mean retrieval order; II-15 dropped
   88 -> 62. Fixed in round 2 (M4 LCB retrieval + LCB motif prior).
4. **Eval-noise calibration** (gen r1, free byproduct): the IDENTICAL cold
   policy measured twice on the 24-pair grid scored 20.8% vs 8.3% with
   wins 2 / losses 5 — per-pair binary flip noise is large; the judge's
   stability demand is doing real work, and true effects of refine's size
   (+17-21pp) are what clears it.
5. Cost texture: replayed organizations are message-heavy (II-19 38k vs
   16.7k tokens/run). The judge scores accuracy only; cost-parity is a
   known open item (champion validation for cheaper generated orgs is
   deferred work).

## Dev round 2 (split: TRAIN {I-01,02,04,05,07,08,II-12} / TEST {II-13,16,20}, seeds 21-28)

Code: commit cb32a26 (M4a/M4b LCB, M5 gate seeds x3 + one-miss floor,
parallel gate). Registered before gen-mode dev-1 results.

- select_then_refine: r1 4.2% vs baseline 29.2% (rest pending at writing).
- graph_generate: (pending)

Round-1 forensics (the -25pp is NOT a method regression):

1. **M1+M5 behaved exactly as designed.** No organization earned os trust
   (every org scored 0/2 on the only os train case II-12 — even chain), so
   the evolved arm abstained on ALL 24 test pairs; its generated DAGs are
   hash-identical to the cold arm's (same selected_primary, same
   messages/calls/tokens). M5's expanded gate accepted the (of-only) bank.
2. **Provider time-drift, not pipeline difference, produced the delta**:
   on II-13 the IDENTICAL deterministic DAG with the same seeds scored 5/8
   in the cold arm (~02:40) and 0/8 in the evolved arm (~03:05) —
   p≈4e-4 under independence. gpt-4o-mini at temp 0 is bistable on some
   cases and the flips are time/batch-correlated. Consequence for power:
   adding eval SEEDS does not help (all seeds flip together per case);
   adding TEST CASES does. Confirmatory power must come from more cases.
3. **The split itself is structurally unwinnable**: all-os test with an
   unlearnable sole os train case means the best possible evolved behavior
   is tie-by-abstention plus drift noise. Split-design lesson recorded for
   the confirmatory procedure (lexicographic tails make mixed pools II-heavy;
   a winnable pool needs either k_II < n_test — mixed test, of-winnable —
   or a learnable os case in train).

## Dev round 3 (10I+2II pilot, seeds 31-38) — both modes FAIL

1. **M6 inverted epistemics** (fixed by M8): one-kind generated orgs kept
   bucket trust ("no contradiction" out of ignorance) and deployed onto
   foreign kinds (I-09 evo 0.67 vs cold 0.88) while only well-measured
   veterans were contradiction-demoted.
2. **Kind disjointness**: lexicographic level-I tails put topk/stats kinds
   in TEST that never occur in TRAIN (max/count/vote/...) — of-side
   exact-kind transfer is impossible by construction on this benchmark.
   The demonstrated transfer carrier is seq-kind II→II (dev-1).
3. **3rd and largest same-policy drift**: identical cold grid 21.9%
   (02:56) → 0.0% (03:24).
4. Hygiene: M7 landed mid-driver → the two modes ran different code (each
   internally consistent). Rule since: no commits while a driver runs.

## Dev round 4 (seq trust vs UNTUNED floors; TRAIN {I-01..06,II-13},
TEST {II-17,II-18,II-20}, seeds 41-48, code 34da9ea) — the decision datum

- Baseline (cold gen): 0.0% on all 24 pairs (floors confirmed).
- Refine: banks built and deployed exactly as designed (11→15 skills,
  gates accepted, gate j improved 0.111→0.0 on val), and scored **0.0%
  in all 3 rounds — 0 wins in 72 evolved evaluations**.
- Conclusion: organizational memory cannot create capability the executor
  lacks. II-17/18/20 at n=5 are model-capability floors, not organization
  floors. With kind-disjoint of-tails and floor-bound seq-tails, **no
  untouched n=5 split is honestly winnable unless its test contains
  headroom seq cases (II-15/16) — which are dev-burned.**
- M7 classifier live validation: 10/10 cases classified by the LLM, ~80%
  agreement with hand labels; disagreements push toward abstention (safe).
- gen mode crashed at its baseline on one sporadic 120s timeout (no
  isolation in the frozen eval pool) → retry layer now gives timeouts one
  bounded retry.

## n=10 dynamic-range scout — ALL ZERO

Cold-gen AND one_peer_exponential scored 0.00 on II-13/14/17/18/20 at
n=10 (3 seeds each; even II-13, winnable at n=5). n=10 deepens the
capability floor; not a power lever.

## Dev round 5 (method-final validation, dev-1 split, fresh seeds 51-58)

Operator amendments in force: budget $60, explore-until-success, wins must
flow evolved-skills→planner→organization (provenance audit below).

- refine half: first attempt crashed on an APIConnectionError burst
  (network outage ~04:46) through the frozen no-isolation eval pool →
  connection retries deepened to 5×5s linear (~75s coverage); rerun in
  progress at writing.
- gen half (code 2ceb76f): FAIL — baseline 8.3%, rounds 12.5/8.3/8.3
  (skills=8 deployed every round: **M5/M8 verifiably fixed dev-1's gate
  triple-rejection**). Provenance audit: the evolved arm ABSTAINED on all
  72 test evals — the round numbers are cold-policy drift, no
  skills-driven wins to claim.

Two further mechanism findings from the abstention forensics:

4. **Trust starvation by name-splitting (→ M11)**: generated evidence orgs
   carry per-run names, so the ledger (keyed by topology NAME) splits one
   structure's successes into n=1 fragments that never reach the n≥2 trust
   bar. Fix: ledger/minister identity = topology-equivalence structural
   hash (mechanism already in the repo for retrieval dedupe).
5. **Trust keys too brittle (→ M12)**: the LLM read II-13 "length of the
   longest palindrome" as kind=max while II-15/16/19 read seq → chain's
   II-13-earned trust (1/2 successes, exactly at the bar) sat in os#max,
   unreachable from the seq test cases; II-15/16 additionally fell back to
   heuristics on unparseable replies (mixed-source labels). The 14-way
   statistic taxonomy is the wrong key. Replace with the mechanistic
   binary it proxied: **needs_lossless** (can local data be safely
   summarized before sharing, or must raw data reach the computing agent)
   — robust to classify, benchmark-agnostic, and it cleanly separates both
   measured failure modes (count-vs-vote bimodality; palindrome↔subsequence
   trust flow).

Queued method round: M9 (instruction-carrying replay) + M11 (structural
identity) + M12 (lossless-need trust key), then floor screen + known-signal
screen; M10 (train-time verified recipe search) behind them.

## Rounds 8-9: the breakthrough chain (M9-M12 + recipes)

Round-8 screens (seeds 61-63): all-abstain again — but now CORRECTLY:
M12 had aligned classifications (II-13/15/16/19 all os+lossless) and the
ledgers were right; at those seeds simply nothing cleared the trust bar on
the lone os anchor (chain 0/2, explore 1/1). Diagnosis moved from routing
to ANCHOR-EVIDENCE SCARCITY → M10.

Round-9 screens (seeds 71-73, M10 + M9 active):

- **A (known-signal cases, refine): exit 0, +33.3pp (3:0)** — evolved
  33.3% vs cold 0.0%.
- **B (floor cases, refine): exit 0, +22.2pp (2:0)** — II-17 and II-18,
  0/72 under dev-4's verbatim replay, each cracked by
  one_peer_exponential replay WITH M9-rewritten per-step instructions
  (instr=True on every deployed row; II-20 os-seg correctly abstained).
  The "capability floor" boundary is REVISED: structure + task-adapted
  role instructions creates capability that verbatim structure replay
  cannot.
- A (gen): M10's loop verified 3 recipes into the bank (II-13's on the
  2nd attempt after procedural feedback), but minister-card trigger
  specificity pushed recipe cards out of the top-3 seeded slots → 0%.
  After trigger-parity fix: +11.1pp (1:0) — recipes deploy and win, gen
  mode remains the thinner mode.

Provenance audits (operator requirement): every win traces to a bank
skill (replayed structure + architect-written instructions); zero
non-skill-driven wins claimed.

## Dev rounds 6-10c: stability, the fixed-best bar, and the shape axis

Split for all of these: TRAIN {I-01,02,04,06,07,08,II-13} / TEST
{II-15,II-17,II-19}; seeds dev-6 81-88, dev-7 91-98, dev-8 101-108,
dev-9 111-118, dev-10/b/c 121-128. Two frozen judges: verify_evolve_stable
(vs same-pipeline cold) and verify_beats_baselines (4-arm: select /
coldgen / fixed_best_on_train; PASS = ≥5pp AND win-margin ≥2 vs EACH).

- **dev-6 (37c64ea): gen-mode first-ever stable PASS** (4.2/29.2*/37.5*
  rising, zero losses); II-13 train-verified recipe replayed onto II-15 =
  15/16. refine FAILED by an r3 deployment reshuffle → round-10
  deployment-stability fixes (replay_first, sticky motif margin,
  instruction-keeping dedupe).
- **dev-7 (764bcb0): BOTH modes stable PASS** (refine 45.8/45.8/62.5* vs
  16.7; gen 25.0*×3 vs 8.3) — first simultaneous PASS.
- **dev-8: first 4-arm battles** — refine -8.3pp vs fixed (unconditional
  Modify added noise where bare structure worked) → M14
  evidence-conditioned Preserve/Modify; gen 0.0pp all-abstain (no named
  aggregators in gen evidence) → M15 portfolio parity.
- **dev-9 (cfc768c): stable_gen 5-round PASS, ALL 5 dominate** (+25.0/
  +12.5/+16.7/+20.8/+20.8); gen vs fixed closed -33.3→+0.0; refine
  -4.2pp. All 48 deployments preserve-verbatim → floors II-17/19 stayed
  0 — M14 had traded screen-B's Modify-cracked floors for II-15
  protection. Distinguisher identified: ANSWER SHAPE → M16 slot key
  bucket#(lossy|lossless)-(scalar|composite).
- **dev-10 INVALID (infra)**: httpx cookie-jar accumulation → 431s
  poisoned all arms; fixed by _NoCookieHTTPClient (66c10b3).
- **dev-10b: M16-as-shipped NET NEGATIVE** (all-scalar train pool starves
  composite slots; 16/24 abstentions; stable_gen fell to FAIL) → **M16b**:
  the shape axis EXTRAPOLATES via the sibling-shape verdict with action
  auto-Modify; the losslessness axis never does.
- **dev-10c (M16b + M18 resume layer): the validation round.**
  - stable_gen PASS exit 0 — strongest curve to date: base 12.5%, rounds
    +16.7(6:2)/+37.5(9:0)/+25.0(6:0)/+50.0(12:0)/+45.8(11:0), 5/5
    dominate, zero losses after r1, bank 14→24 all gates accepted.
  - **beats_refine PASS exit 0 — FIRST-EVER 4-arm unconditional win**:
    evolved 58.3% vs select 41.7 (+16.7, 4:0), coldgen 8.3 (+50.0, 12:0),
    fixed_best=one_peer_exponential 45.8 (+12.5, 4:1); 24 pairs, 0
    dropped. Margin carried by II-19: evolved 0.75 vs fixed 0.38 vs
    select 0.25 — the M16b Modify path (extrapolated lossless-composite
    trust, 4 rewritten step instructions on every deployed row). II-15 =
    shared ceiling (1.00 evolved/select/fixed), II-17 = shared floor
    (0.00 all four arms at these seeds).
  - beats_gen FAIL — but only on the select arm and only by noise width:
    vs fixed +37.5pp (10:1, PASS), vs coldgen +29.2 (8:1, PASS), vs
    select +4.2pp 4:3 (needs ≥5pp & margin 2). The two lost II-15 pairs
    are seeds where evolved and select deployed the SAME verbatim
    one_peer policy (instr0, identical family) — same-policy provider
    drift, the ~4pp arm-noise measured in dev-9. II-19 evolved 0.50 vs
    select 0.12 (4 Modify wins). Mechanically gen now clears the
    operator-named bar (beat the best fixed topology) on this split; the
    frozen judge's select-arm criterion remains unmet at this power.
  - Deployment forensics (all three runs): composite cases II-17/II-19
    deploy with extrapolated trust + 4 instruction-carrying steps
    (Modify); scalar II-15 deploys preserve-verbatim (instr0); ZERO
    evolved-row abstentions (dev-10b's 16/24 starvation eliminated).
  - M18 resume layer validated live (operator directive: every test
    resumable): dev-10c was SIGTERM-killed at 5 min, relaunched, and
    replayed the killed leg's finished rows at 0.0s (beats_gen 20/32,
    beats_refine 8/8 portfolio) before purchasing new work.
    POLICY: dev runs may seed caches across same-split runs;
    CONFIRMATORY attempts run with fresh empty caches (no cross-run
    seeding, fresh MASBENCH_EVAL_CACHE) so every confirmatory number is
    a fresh measurement.

## Dev-11 (DIAGNOSTIC) and round 19: the recipe-hijack triad

dev-11 ran the last unmeasured cell (stable_refine on round-18 code, same
split/seeds as dev-10c) and FAILED hard: 4.2/0.0/4.2 vs base 8.3 — on the
same seeds where beats_refine's evolved arm had scored 58.3% an hour
earlier. Forensics found a single deployment hijack with three stacked
defects:

1. **Trust**: `silo__recipe_longest_palindrome_cross_boundary` (M10
   recipe, verified 2x on the ONE train case II-13) earned kind trust for
   os#lossless-scalar from its own verification rows, and M16b
   shape-extrapolated it onto the composite slots — it deployed on ALL
   three test cases, every round, every seed (70/72 evolved rows),
   displacing one_peer.
2. **Ranking**: retrieval LCB rewards low-n perfection — recipe
   0+0.5/sqrt(2)=0.354 outranked the multi-case generalist (~0.45+).
   Winner-take-all refine replay has no per-case competition to recover.
3. **Fidelity (the deepest one)**: the card stores 5 instruction-bearing
   steps (verified 2/2 at train time as such), but deploy compiled under
   max_messages=32: repair trimmed the 5th step (the global-answer step)
   AND rebuilt the kept steps without their `instruction` field. The
   deployed artifact (4 bare steps, 32 msgs — exactly the budget) was NOT
   the verified artifact. beats_refine's instr4 rows came from the
   REWRITE path on one_peer; stored instructions never survived repair.

Validity note (honest): dev-11 is recorded as DIAGNOSTIC — my cross-run
evalcache seeding transplanted stable_gen's stochastic recipe-search
SUCCESS into the refine run (recipe| keys are split-deterministic), and
3/24 baseline rows replayed from the gen run's measurements. The hijack
mechanism itself is run-independent: any refine run whose own recipe
search verifies would reproduce it.

Round-19 fixes (M19a–d, all offline-tested, suites 277/271 green, CF
byte-identical):

- **M19c**: repair preserves instructions; skill-replay candidates are
  admitted under budgets widened to the stored artifact's exact size
  (budgets bind synthesis, not replay); fresh candidates stay bound.
- **M19a**: ledger slots record distinct evidenced cases; skills carry
  global `evidence_case_count`; retrieval adds 0.25/case_count — the
  7-case generalist (0.498) now outranks the 1-case perfect recipe
  (0.604).
- **M19b**: positive shape-sibling extrapolation requires GLOBAL case
  diversity >= 2 (one_peer keeps the dev-10c winning hop via its
  multi-case of-evidence; single-case recipes do not hop); measured
  failures block at any diversity. Per-slot diversity was deliberately
  NOT required — II-13 is the only learnable os anchor, so per-slot
  diversity is impossible by geometry and would have killed the working
  mechanism (the 3 prior-round tests that pin the winning semantics
  caught exactly this in TDD).
- **M19d (tooling)**: evalcache is never seeded across runs; M18 resume
  = same-run-dir relaunch only. Confirmatory cache hygiene unchanged
  (fresh empty caches).

## Dev-12/12b: the full four-cell sweep (M19 code, seeds 131-138)

The milestone the campaign has driven toward: BOTH modes x BOTH frozen
judges PASS at a single fresh seed draw, on one code state (round 19).

| cell | verdict | numbers |
|---|---|---|
| stable_refine | PASS exit 0 | base 8.3; 45.8*/62.5*/45.8*; r3 9:0 |
| stable_gen | PASS exit 0 | base 8.3; 50.0*/45.8*/54.2*/54.2*/45.8*; losses <= 1 |
| beats_refine | PASS exit 0 | evolved 45.8 vs select 37.5 (+8.3, 2:0), coldgen 8.3 (+37.5, 11:2), fixed=one_peer 37.5 (+8.3, 5:3) |
| beats_gen | **PASS exit 0 (first ever)** | evolved 50.0 vs select 37.5 (+12.5, 6:3), coldgen 8.3 (+41.7, 11:1), fixed=one_peer 41.7 (+8.3, 4:2) |

Notes that matter:

- Both 4-arm runs drew fixed_best = one_peer_exponential (the genuinely
  strongest fixed topology) on their train measurement -- unlike
  round-18's beats_gen where drift had picked chain. The "beats the best
  fixed topology" claim now stands against the strong arm in both modes.
- beats_gen's select-arm gap (+4.2pp 4:3 at seeds 121-128) closed to
  +12.5pp 6:3 at this draw, consistent with the drift-width reading of
  the earlier near-miss.
- Provenance (operator requirement): 100% of evolved deployments are
  bank skills -- one_peer on all three test cases; II-15
  preserve-verbatim (instr0), II-17/II-19 Modify with 4 rewritten step
  instructions each (the M16b/M19b extrapolation path). Zero
  abstentions, zero recipe hijacks (no recipe verified live at these
  seeds; the M19a/c guards stay offline-validated). II-19 is the
  margin-maker in both 4-arm runs (evolved 0.62-0.75 vs others
  0.12-0.38); II-17 remains a floor for every arm; II-15 is
  ceiling-adjacent for the strong arms.
- Cost: dev-12 $1.29 + dev-12b $3.94. Total spend $52.89/$100.

Remaining gate: confirmatory per the amended procedure (SHAPE v3, fresh
recorded RNG seeds, fresh empty caches, both modes x both judges, <= 3
attempts) -- pending operator sign-off on the SHAPE v3 untouched-split
interpretation.

## Thesis alignment (operator's ultimate framing)

The system IS the thesis: frozen workers (soldier prompts never learned);
an LLM architect (emperor) designs the temporal communication DAG (steps =
rounds, transmissions = who→whom, selected_primary = answer emitter)
conditioned on a memory of design rules (SkillBank) distilled from past
runs; rules are evidence-conditioned (trust ledger: bucket#lossless slots,
n≥2, mean≥0.5, LCB) and motif-attached (bucket-namespaced motif credit +
structural-hash families). Action vocabulary: Preserve = trusted replay;
Modify = refine + per-step instruction rewrite; Avoid = avoid cards +
withdrawn trust. Definitional line: per-step instructions are part of the
DESIGN ARTIFACT (the architect decides what each edge carries and what
receivers do with it, at design time); worker solving prompts stay frozen.
Remaining schema work: make the Preserve/Modify/Avoid action an explicit
card field (M13 finishing move).

## Borrowed designs

- SkillLens (arXiv:2605.08386): verifier SKIP route -> M1 abstention to the
  exact cold path.
- SkillGraph (arXiv:2605.12039): task/structure-conditioned retrieval -> M1
  feature-bucketed trust ledger.
- SAGE (arXiv:2512.17102): skill-quality jointly tracked with task outcome
  -> per-bucket success ledger on skill cards.
- Voyager / AWM (bib): task-conditioned skill retrieval precedent.
- LCB/champion-challenger (standard bandit practice): M4 retrieval/motif
  pessimism, M2 ratchet gate.

## Operational notes

- Harness background-task notifications were unreliable this session
  (phantom round lines, false completion reports); all experiment state is
  read from artifacts only (stable_*.json, diag eval_runs.jsonl, evcache).
  Long runs are launched detached (python os.setsid) with FS watchers.
