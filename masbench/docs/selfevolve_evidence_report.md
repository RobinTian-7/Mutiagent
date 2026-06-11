# Self-evolve on Silo-Bench — evidence report (FINAL)

Pre-registration: `docs/selfevolve_preregistration.md`. Budget ledger:
`runs/COST_LEDGER.json`. Judge: frozen `scripts/verify_evolve.py` (never edited).

## VERDICT — goal met, with stated scope

**Self-evolution produces a real, reproducible, mechanistically-explained
held-out improvement on Silo-Bench at the gpt-4o-mini / level I+II / n=5
scale.** On the pre-registered reserved test cases {II-15 "Pattern Search",
II-19 "Merge Neighbors"} — never used in any development round — with seeds
drawn fresh and recorded before each run:

| confirmatory | mode | empty | evolved | delta | discordant | verdict |
|---|---|---|---|---|---|---|
| attempt 1 | select_then_refine | 15.0% | 50.0% | +35.0pp | 10:3 | PASS |
| attempt 1 | graph_generate | 10.0% | 50.0% | +40.0pp | 9:1 | PASS |
| attempt 2 | select_then_refine | 10.0% | 50.0% | +40.0pp | 10:2 | PASS |
| attempt 2 | graph_generate | 10.0% | 35.0% | +25.0pp | 7:2 | PASS |

Reproductions: **2/2 confirmatory attempts PASS in BOTH modes** (criteria:
paired delta >= +5pp AND discordant margin >= 2, frozen script). Dev-phase
record after the method fixes: 2/2 PASS under rotated splits (R2 +25.0pp,
R3A +11.1pp); the pre-fix baseline FAILED (R1 -16.7pp) and is reported below.

**Mechanism (one sentence):** evolution distills evidence into skills that
carry the EXECUTABLE schedule of organizations that actually solved the
training cases (canonical topologies in refine mode, self-generated DAGs in
graph_generate mode), and the deployed planner replays the best-evidenced
schedule instead of designing from a cold prompt — prose-only transfer of the
same knowledge measurably HURT (round 1, the cargo-cult failure).

**Honest scope limits (load-bearing, not boilerplate):**
- The confirmatory improvement is carried by II-15 (0-10% -> 70-80% in all
  four runs); II-19 stayed ~flat (20->20 / 20->30 / 20->0). Both cases were
  pre-registered; per-case texture reported as measured.
- The refine-mode win costs x1.7-2.2 tokens (the learned organization is
  communication-heavy); the graph_generate win is at ~cost parity (x1.1). See
  Cost parity — tokens alone demonstrably do not buy accuracy here.
- The gate is a guardrail (binding evidence: round-3C rejection; first strict
  non-tie accept in confirmatory-2 refine, j 0.333->0.0), not a fine
  discriminator at 3-6 val runs/arm.
- What was verified is evidence-grounded selection + executable replay through
  the generation interface — NOT free-form topology invention from abstract
  insights (that variant failed round 1). B2 insight-mining and motif priors
  stayed OFF: untested, not refuted.
- Cumulative real-LLM spend: $3.97 of the $40 budget.

## Prior state (before this effort)

- Previous curves (sibling worktree `runs/curve_*`): test split I-08/09/10 was
  mostly model-capability floor; rounds-curve reruns of an IDENTICAL bank
  swung 6.7% -> 26.7% (pure eval noise); select-mode gate j_before == j_after
  everywhere (3 binary val points, ties accepted) — no discriminative power.
- Mechanism audit: the documented select_then_refine mechanism ("skills carry
  working topologies' protocol_specs; eval refines them") was DEAD CODE —
  aggregate rows never carried specs; the test asserting it passed vacuously on
  a None value. The only live mechanism was prompt-context injection.

## Round 1 (2026-06-09) — pre-A2 baseline, FAIL (informative)

Protocol: `runs/dev_round1/protocol.json` (pre-declared; fresh eval seeds).
TRAIN I-01..I-06, TEST {I-09, II-13}, n=5, 24 pairs. Cost $0.31.

**Numbers:** empty 54.2%, evolved 37.5%, delta **-16.7pp**, discordant 5/9
(evolved-only/empty-only). Per case: I-09 75%->42%, II-13 33%->33%.

**Diagnosis (from `runs/dev_round1/diag/`):**
1. The bank advertised avoid skills for ALL THREE topologies simultaneously
   (engine dominance rule `loss > best*1.75` misfires on binary per-case rows:
   best=0 makes every miss "dominated") — contradictory context.
2. The three positive skills carried IDENTICAL mean loss (0.333): this train
   split has zero between-topology signal (I-01/I-03 solved by everything,
   I-05 by nothing).
3. Before/after DAG diff (I-09): empty arm designed `staged_pair_aggregation`
   (pair-merge tree -> sink, 4 msgs, 75%); evolved arm, prompted with the
   "peer propagation + star sink" lesson, designed `staged_peer_exchange` — a
   LINEAR chain + full-fan star (8 msgs, 42%): a cargo-cult imitation of
   peer_star's shape without the exponential-coverage property that makes it
   work. Prompt-context transfer distorts the executable knowledge.
4. The generation gate (new in this round) ran but with 3 runs/arm its j was
   quantized at 1/3 and tied -> tie-accepted a bank that cost -16.7pp held-out.

**Method changes adopted (each with mechanism, offline-tested, CF green):**
- A2 executable-spec transfer: evidence rows carry the EXECUTED schedule;
  minister skills store it; eval REPLAYS the top-retrieved spec instead of
  imitating prose (kills the cargo-cult failure mode).
- Avoid-patch dominance filter (`AVOID_MEAN_LOSS_GAP=0.25` absolute mean gap)
  (kills the all-topologies-avoid misfire).
- Gate val doubled (--val-seeds 3 4) for round 2.

## Round 2 (2026-06-09) — A2 replay + avoid filter, PASS

Protocol: `runs/dev_round2/protocol.json` (pre-declared, rotated split:
TRAIN I-01..I-05+I-09, TEST {II-13, II-14}, fresh eval seeds).
Mechanism prediction (written before results): evolved replays a real
named-topology schedule on II-13 (~select-arm level) vs cold generation;
II-14 is a floor case (expect 0-0).

**Numbers:** empty 12.5%, evolved 37.5%, delta **+25.0pp**, discordant 8/2.
Per case: II-13 25% -> **75%** (+50pp); II-14 0% -> 0% (floor, as predicted).
Cost $0.46 (cumulative $0.77).

**Mechanism evidence (`runs/dev_round2/diag/`):**
- Bank: exactly 3 positive skills, ALL carrying executable specs
  (peer_star 4 steps / mesh_star 2 / tree 3), ZERO avoid skills (filter worked).
- The evolved arm replayed `generated:one_peer_exponential_dag_star` in 24/24
  eval runs — the top-retrieved accuracy-first skill's exact schedule. The
  empty arm cold-designed `staged_boundary_exchange` / `staged_pair_gather`
  (the same cold repertoire as round 1) and got 25% on II-13.
- The prediction in protocol.json (written pre-run) matched in every part.

**Honest caveats:**
- Cost asymmetry: evolved 22.8k tok/run vs empty 13.2k (x1.7), 19 vs 10 msgs.
  The learned ORGANIZATION is more communication-heavy. Counter-evidence that
  tokens alone don't buy accuracy: round 1's evolved arm also spent more
  (11.1k vs 10.1k) and was 16.7pp WORSE.
- The delta rests on a single signal case (II-13) — known dev-pool limitation;
  the reserved confirmatory cases are the real test.
- The generation gate again tied (j 0.167 both arms; 6 runs/arm) — it accepted,
  but its protective power remains undemonstrated (see ablation).

## Round 3 (2026-06-09) — rotation reproduce + ablation + secondary mode

Protocol: `runs/dev_round3/protocol.json` (pre-declared; 3-case test
{I-09, II-13, II-14}, train I-01..I-06, fresh eval seeds; predictions written
before results). Paused by user after run A; B/C resumed later with the same
pre-registered seeds (the aborted B partial produced no peekable results and
was discarded, $0.18 logged).

**Run A (select_then_refine, gate auto): PASS.** empty 25.0%, evolved 36.1%,
delta **+11.1pp**, discordant 8/4. Per case: I-09 42%->42% (tie — cold
generation already matches replay there, as predicted), II-13 33%->**67%**
(mechanism reproduced), II-14 0/0 (floor). Evolved arm: 36/36 replays of
`one_peer_exponential_dag_star`; bank again 3 spec-carrying skills, 0 avoids.
Cost $0.63.

**Post-A2 dev record: 2/2 PASS under rotated splits + fresh seeds**
(R2 +25.0pp, R3A +11.1pp), both with the same explainable mechanism and the
delta concentrated exactly where the pre-run difficulty map predicted headroom.

**Run B (gate OFF ablation): FAIL -2.8pp — honest reading is subtler than
"drift".** empty 33.3%, evolved 30.6%, discordant 5/6. The un-gated bank
admitted a 4th skill (avoid_tree — legitimately earned: in B's own evidence
sample tree's mean loss was 0.667 vs 0.333 best, above the 0.25 gap), but the
DEPLOYED policy was unchanged (36/36 replays of peer_star, same as A). The A-vs-B
verdict swing (+11.1 vs -2.8) is dominated by EMPTY-arm rerun noise: on
identical seeds, cold generation scored I-09 at 42% (run A) vs 67% (run B) —
±25pp per-case rerun noise at 12 seeds. Conclusion: in refine mode, gate-off
did NOT cause behavioral drift on this data; the gate's binding protection is
demonstrated by run C instead. (Also a cautionary datum: single dev rounds at
24-36 pairs can flip verdicts on empty-arm noise alone.)

**Run C (graph_generate mode): the gate FIRED — its first real protective
event.** The generated-evidence bank (2 skills distilled from cold-generated
DAGs, train_success 0.39) made held-out GENERATION worse: j_before 0.0 vs
j_after 0.333 -> REJECTED -> pre-state (empty) exported, rejected ids recorded.
This is exactly the round-1-style harmful-bank scenario, now caught by the
aligned gate. The subsequent paired eval crashed at 32/72 runs on a single
`openai.APIConnectionError` (infra, not a verdict) — fixed by adding a bounded
transient-connection retry layer (`masbench/llm/retry.py`, TDD) under the
frozen verify script. Health conclusion: at this scale graph_generate-mode
learning HURTS generation and is correctly blocked; its confirmatory run is
expected to show ~zero delta (bank withheld), reported as-is.

## Confirmatory attempt 1 (2026-06-10) — BOTH MODES PASS

Reserved TEST cases {II-15, II-19} (never in any dev round). Seeds drawn and
recorded in `runs/confirmatory1/protocol.json` BEFORE launch (train [2549,3139],
val [5655], 10 eval seeds). Frozen verify_evolve.py is the sole judge.

| mode | empty | evolved | delta | discordant | II-15 | II-19 |
|---|---|---|---|---|---|---|
| select_then_refine | 15.0% | 50.0% | **+35.0pp** | 10:3 | 10->80% | 20->20% |
| graph_generate | 10.0% | 50.0% | **+40.0pp** | 9:1 | 0->70% | 20->30% |

**Mechanisms (from `runs/confirmatory1/diag_*`):**
- refine: this train mix has real between-topology signal (tree 0.5 vs
  peer/mesh 0.167); avoid_tree legitimately earned (gap 0.33 >= 0.25); evolved
  arm replayed peer_star 20/20. Cost x2.2 tokens vs empty (31.1k vs 14.2k) —
  the learned organization is communication-heavy.
- graph_generate: A2 made GENERATED evidence replayable too — the bank stored
  5 self-generated DAG specs (best: `staged_aggregate_to_sink`, train loss 0.0)
  and replayed it 20/20. **~Cost parity (x1.09 tokens, 15.7k vs 14.4k) and half
  the cost of the refine replay at the same 50% accuracy** — the self-designed
  organization beats the canonical one on cost. (Contrast round-3C, where a
  different train mix produced bad generated evidence and the gate rejected
  the bank: the gate is what separates these two outcomes.)
- Honest per-case note: the delta is carried mostly by II-15 in both modes;
  II-19 moved 0/+10pp. Both cases were pre-registered; reported as measured.

Per pre-registration: PASS #1 of the 2 required.

## Confirmatory attempt 2 (2026-06-10) — BOTH MODES PASS AGAIN

Fresh seeds (train [5577,9116], val [7668], 10 eval), recorded in
`runs/confirmatory2/protocol.json` before launch; code identical to attempt 1.
(One pause/rerun: the user paused the first attempt-2 launch during its
evidence phase — nothing was evaluated or peeked; the rerun used the same
recorded seeds. Discarded partial logged at $0.13.)

| mode | empty | evolved | delta | discordant | II-15 | II-19 |
|---|---|---|---|---|---|---|
| select_then_refine | 10.0% | 50.0% | **+40.0pp** | 10:2 | 0->80% | 20->20% |
| graph_generate | 10.0% | 35.0% | **+25.0pp** | 7:2 | 0->70% | 20->0% |

- refine: 20/20 peer_star replays again; bank = 3 positive spec-carrying
  skills (this train-seed draw produced no qualifying avoid). **First strict
  (non-tie) gate accept: j_before 0.333 -> j_after 0.0.**
- graph_generate: 20/20 replays of self-generated `staged_aggregate_to_sink`
  again (x1.12 tokens). II-19 regressed 20->0 this attempt (vs 20->30 in
  attempt 1) — the self-generated design is II-15-effective, II-19-weak;
  the overall PASS still clears both criteria.

## Cost parity (paired eval arms, per-run means from diag dumps)

| run | arm | exact | msgs | tokens | tokens ratio |
|---|---|---|---|---|---|
| R1 (pre-A2) | empty | 54.2% | 6.2 | 10.1k | — |
| R1 (pre-A2) | evolved | 37.5% | 7.1 | 11.1k | x1.10 (spent MORE, scored WORSE) |
| R2 | empty | 12.5% | 10.0 | 13.2k | — |
| R2 | evolved | 37.5% | 19.0 | 22.8k | x1.73 |
| R3A | empty | 25.0% | 8.4 | 12.3k | — |
| R3A | evolved | 36.1% | 19.0 | 23.4k | x1.90 |
| Conf1 refine | empty | 15.0% | 6.6 | 14.2k | — |
| Conf1 refine | evolved | 50.0% | 19.0 | 31.1k | x2.20 |
| Conf1 gen | empty | 10.0% | 6.5 | 14.4k | — |
| Conf1 gen | evolved | 50.0% | 12.0 | 15.7k | **x1.09 (~parity)** |

Reading: the refine-mode wins come with a 1.7-2.2x token cost — the learned
policy deploys a communication-heavy canonical organization (peer_star, 19
msgs). Two observations keep this honest rather than "winning by spending":
(1) round 1's evolved arm ALSO outspent its empty arm (x1.10) and scored
16.7pp WORSE — tokens alone do not buy exact-match; (2) the graph_generate
confirmatory arm reached the SAME 50% at ~cost parity (x1.09) by replaying a
SELF-GENERATED 12-msg DAG — the knowledge, not the budget, is what transfers.
Both arms always use the same model, temperature, and per-call limits.

## PHASE 2 — FINAL VERDICT: GOAL NOT MET (boundary established, honestly)

The pre-registered phase-2 goal (evolved beats EVERY baseline — select,
graphgen, fixed_best_on_train — by >=5pp with margin >=2 on reserved held-out
conditions, reproduced 2x within 3 confirmatory attempts) is **formally
unreachable**: attempts 1 and 2 both FAILED, so even a attempt-3 PASS would
yield 1 < 2 required. Attempt 3 was deliberately left unconsumed: the two
candidate configurations for it both failed cheap screens (probe-selection
route: -20pp then -60pp vs select), and re-running attempt-2's configuration
was already measured at 0%. Spending the last attempt would have been
number-chasing, which the honesty clauses forbid.

**What IS established (each with mechanism + artifacts):**
1. *In-paradigm self-evolution works and is cheap*: with the frozen 4-arm
   judge, 2/2 dev PASSes under rotated splits — R=2: evolved 62.5% vs
   select 25 / graphgen 18.8 / fixed 37.5 (cost x1.03 of select); R=3:
   evolved 37.5% vs 18.8x3, deploying a SELF-GENERATED design at 0.39x
   select's tokens. Plus phase 1's 4/4 confirmatory PASSes on reserved
   aggregation-paradigm cases.
2. *The boundary is paradigm transfer*: the reserved phase-2 conditions
   (II-13 palindrome, II-16 trapping-rain @ n=10) are sequential/chain tasks;
   the train pool is aggregation tasks; "replay the best-evidenced
   organization" cannot represent an organization absent from evidence, and
   eval-time fresh generation lacks a reliable selector (1-seed probe is a
   per-case Bernoulli gate — screens measured it harmful). fixed=chain (picked
   on train!) beating the generation arms on these tasks is itself evidence
   the failure is representational, not statistical.
3. *Three same-family scoring inversions found and root-fixed* (CF
   lower-is-better RMSE fields reused for higher-is-better generic success):
   retrieval sort key (confirmatory-1 collapse), probe-row objective score
   (bundle-screen collapse), both with regression tests; ingest bridge
   (phase 1, A2). Audit of remaining `mean_rmse` consumers: clean.
4. *The verification discipline did its job*: reserved conditions caught a
   collapse dev never saw; $0.19/$0.15 screens saved two confirmatory
   attempts from known-broken configurations; the gate fired twice for real.

Cumulative spend: $12.16 of $40. Suites: exp-graph 265 / masbench 172, green.

## PHASE 2 (2026-06-10 onward) — "stably beats ALL baselines after R rounds"

Pre-registration: `docs/selfevolve_phase2_preregistration.md`. Frozen judge:
`scripts/verify_beats_baselines.py` (4 arms paired; PASS needs delta>=5pp AND
margin>=2 vs EACH of select / graphgen / fixed_best_on_train). Reserved
confirmatory conditions (scout-selected by pre-declared rule, opposite-
direction org-sensitivity): **II-13@n10 (select 0/gen 50) and II-16@n10
(select 50/gen 0)** — no constant policy can pass both.

### P2 dev round 1 (aborted by network outage — no verdict, $0.47)
Salvaged mechanism data: explore (hot-bank graph_generate evidence runs)
added self-generated designs to the bank (9 skills incl. `staged_tree_
aggregation` loss 0). BUG found and fixed: an n=1 explored design at loss 0.0
anchored the dominance rule -> avoid skills for ALL named topologies incl. the
deployed winner. Fixes (TDD): `AVOID_CHAMPION_MIN_ROWS=3`; explore generation
HOT (0.7) / execution cold (diversity across rounds); env-tunable retry.

### P2 dev round 2 — first full 4-arm read: PASS vs ALL baselines
Protocol `runs/p2_dev_round2/protocol.json` (pre-declared; test {II-13,
II-16}@n5, R=2, fresh seeds). 16 pairs, 0 dropped. Cost $0.70.

| arm | exact | per-run tokens | II-13 | II-16 |
|---|---|---|---|---|
| **evolved (R=2)** | **62.5%** | 21.8k | 62% | 62% |
| select | 25.0% (+37.5pp, 7:1 PASS) | 21.3k | 25% | 25% |
| graphgen | 18.8% (+43.8pp, 8:1 PASS) | 12.2k | 38% | 0% |
| fixed=peer_star (train-picked) | 37.5% (+25.0pp, 6:2 PASS) | ~21k | 50% | 25% |

**Cost parity achieved**: evolved x1.03 tokens vs select (same 19-msg
peer_star-shaped organization) — unlike phase 1's x1.7-2.2.

**Gate fired again (2nd real rejection):** round-2's candidate bank regressed
held-out generation (j 0.0 -> 0.5) and was rejected wholesale; the deployed
bank is round-1's (3 named + 3 explored generated designs, zero avoids —
pollution fix verified). Hot explore produced 4 DISTINCT generated designs
across rounds (vote/xor/tree-reduce/aggregation variants), so the saturation
fix works mechanically; whether accepted growth continues across R>=3 is the
rounds-stability question.

**Mechanism of the win over same-topology baselines (resolved from runner
code):** the named-topology path (select/fixed) finalizes by VOTE OVER ALL
AGENTS (`answer_holders` = range(n)) — peer-star leaves holding partial views
dilute the sink's correct global answer; the replayed executable spec carries
`metadata.selected_primary` = the sink, so only the designated final holder
answers. The evolved edge = learned shape (vs graphgen's cold designs) +
learned explicit answer-holder designation (vs the baselines' vote dilution).
Both properties live in the bank's stored spec; nothing case-specific.

### P2 dev round 3 — R=3 reproduction under rotation: PASS vs ALL again

Protocol `runs/p2_dev_round3/protocol.json` (pre-declared; test {I-09,
II-16}@n5, R=3, fresh seeds, NO method change vs round 2). 16 pairs, 0
dropped. Cost $0.90.

| arm | exact | per-run tokens | I-09 | II-16 |
|---|---|---|---|---|
| **evolved (R=3)** | **37.5%** | **9.1k** | 75% | 0% |
| select | 18.8% (+18.8pp, 4:1 PASS) | 23.0k | 38% | 0% |
| graphgen | 18.8% (+18.8pp, 4:1 PASS) | ~12k | 25% | 12% |
| fixed=peer_star | 18.8% (+18.8pp, 4:1 PASS) | ~23k | 25% | 12% |

Two qualitatively new mechanism results:
1. **The deployed organization was SELF-GENERATED** — the evolved arm replayed
   `generated:tree_reduce_to_sink` 16/16 (an explored design that entered the
   bank in round 1), not a canonical named topology. The bank out-designed its
   own canonical repertoire on this split's evidence.
2. **The win came with a 61% token REDUCTION** (9.1k vs select's 23.0k per
   run): the learned design is both more accurate AND much cheaper — the
   strongest possible answer to "did it win by spending more?".
3. Bank growth was accepted in ALL THREE rounds (7 -> 8 -> 9 skills) — the
   saturation fix produces real multi-round accumulation.

Honest texture: the PASS is carried by I-09 (75% vs 25-38%); II-16@n5 was an
evolved-arm floor this round (0% vs 0-12%) — baselines took 1 discordant pair
each there. Dev record with the frozen 4-arm judge: **2/2 PASS under rotated
splits (R=2 and R=3)**.

### P2 confirmatory attempt 1 — FAIL (1 of 3 consumed); root cause found & fixed

Seeds pre-recorded in `runs/p2_confirmatory1/protocol.json`. Refine verdict on
the reserved conditions: **evolved 0.0%** vs select 17.6 / graphgen 17.6 /
fixed=chain 11.8 (17 pairs, 3 dropped) — total collapse, exactly what the
never-dev-touched reserved set exists to catch (all dev rounds were n=5; this
was the replay path's first n=10 outing). Curve/gen parts killed mid-flight
once the cause was known (measuring a known-broken config is waste; $1.42 +
~$1.10 logged).

**Failure analysis (forensic on the dumped bank, reproduced offline):** the
final bank contained THREE loss-0.0 self-generated designs, yet the evolved
arm replayed `staged_xor_aggregation` — stored train loss **1.0** — 20/20.
`SkillBank._retrieval_sort_key` sorts its second key (`mean_rmse`) ASCENDING
under CF semantics (RMSE: lower=better); generic Silo rows bridge SUCCESS
(higher=better) into that field, so retrieval returned **worst-first** and the
blind first-valid replay seeding deployed a known-always-fails design. The
observed retrieve order matched this theory exactly (incl. id tiebreaks).
Why n=5 dev rounds didn't catch it: the motif prior happened to demote the bad
first candidate there; at n=10 it didn't. The per-round gate (1 val seed, j
quantized at 1/3) tie-accepted past it.

**Fix (root layer, TDD):** `_skill_mean_rmse` now ranks by the uniform
lower-is-better `mean_primary_loss` when present (generic benchmarks); CF
skills never carry that key, so CF ordering is byte-identical. Regression
tests pin worst-first never recurs + CF unchanged (exp-graph 264 / masbench
168 green). Post-fix forensic replay on the EXACT failed bank: the three
loss-0 designs now rank first. Direction screen at n=10 (non-reserved I-04):
**evolved 100% vs select 0%** (4:0, $0.21) — fix verified live.

### P2 confirmatory attempt 2 — FAIL (2 of 3 consumed); the real boundary emerges

Fresh seeds pre-recorded (`runs/p2_confirmatory2/protocol.json`); retrieval
fix + evidence cache active. Refine: **evolved 0.0%** vs select 25.0 /
graphgen 18.8 / **fixed=chain 25.0** (16 pairs, 4 timeout-drops). Gen mode:
evolved 11.8 vs fixed=chain 23.5 (FAIL). The curve crashed on a single 120s
timeout (no per-run isolation in curve eval — pipeline-fixed + test).

**Failure analysis — this time the method's real limits, not a scoring bug:**
1. **Retrieval fix worked**: the evolved arm replayed its loss-best design
   (`staged_aggregation_tree`, train loss 0.0). Deployment did the right
   thing given its bank.
2. **Paradigm shift**: the reserved conditions are SEQUENTIAL tasks (II-13
   Longest Palindrome, II-16 Trapping Rain; optimal = chain with
   prefix/suffix or bidirectional passes; output distributed). The train pool
   (I-01..I-09) is all GLOBAL-AGGREGATION tasks. The bank cannot contain a
   chain-paradigm organization because none ever appears in its evidence —
   "replay what won on train" cannot represent the winning org for test.
3. **Expressiveness cap**: `graph_max_steps=4` made ~9-step chain schedules
   INEXPRESSIBLE at n=10 for every generation-based arm, while the named
   `chain` baseline compiles uncapped — fixed=chain (picked from train!) beat
   both generation arms on these tasks. Pipeline fix: cap now scales
   `max(4, n+2)` (task-agnostic, all arms symmetric).
4. A third same-family inversion found by the pre-attempt-3 screen ($0.19):
   `_probe_row` stuffed Silo SUCCESS into the `mean_rmse` (loss) field, so
   `_objective_score`'s success terms cancelled (`exact - "rmse"`) and probe
   selection degenerated to cheapest-wins (deployed a 1-step star, 0%).
   Root-fixed via the `primary_loss` bridge + regression test (exp-graph 265
   green). The screen saved the last confirmatory attempt from being burned
   on a known-broken probe.

## Appendix A — what the bank learns, and how it changes the deployed DAG

The minister distills per-topology skills from evidence rows; every claim
below is read directly from the dumped banks (`runs/*/diag*/evolution_*.json`).

**Confirmatory-1 refine bank (4 skills):**
- `silo__cf_accuracy_peer_star` — topology one_peer_exponential_dag_star,
  mean train loss 0.167, **executable 4-step spec** (3 exponential peer-
  propagation steps + star sink; 19 msgs at n=5). Evidence: it solved 5/6 of
  its train (case,seed) runs. THIS is the skill the eval retrieves first under
  accuracy_first and replays 20/20.
- `silo__cf_middle_ground_mesh_star` — mesh_star, loss 0.167, 2-step spec
  (mesh broadcast + star sink, 24 msgs). Retrieved second (balanced tag).
- `silo__cf_budget_tree` — tree, loss 0.5, 3-step spec (4 msgs). Excluded from
  accuracy_first retrieval (budget objective) — never replayed at eval.
- `silo__cf_avoid_tree` — counterexample skill, earned by a real mean-loss gap
  (0.5 vs 0.167 best >= 0.25 threshold), 6 counterexample rows attached.

**Confirmatory-1 graph_generate bank (6 skills):** five positive skills each
storing a SELF-GENERATED DAG spec with its measured train loss
(staged_aggregate_to_sink 0.0, staged_aggregation_to_sink 0.0,
staged_pair_gather 0.0, staged_tree_aggregation 0.167,
staged_pair_aggregation 0.4) plus one earned avoid (pair_aggregation, gap
0.4). Eval replayed the best (staged_aggregate_to_sink, 3 steps / 12 msgs).

**How the bank changes the deployed design (before/after, same case+seeds):**
- Confirmatory II-15, empty arm: cold-generated `staged_aggregation_to_sink` /
  `staged_pair_gather` variants -> 0-10% exact. Evolved arm (refine): replayed
  peer_star spec (full pairwise coverage via exponential doubling, then sink)
  -> 80%. Evolved arm (gen): replayed its own 12-msg staged_aggregate_to_sink
  -> 70%.
- Round-1 I-09 (the failure mode A2 removed): empty arm cold-designed
  `staged_pair_aggregation` (pair-merge tree, 4 msgs) -> 75%; the PRE-A2
  evolved arm, given the same knowledge as PROSE ("peer propagation followed
  by star sink is the accuracy-first policy"), designed `staged_peer_exchange`
  — a linear chain + full-fan star (8 msgs) -> 42%. The shape was imitated;
  the property that makes it work (every agent's information reaching the
  sink via exponential doubling) was not. Executable replay transfers the
  property, not the description.

**Honest scope statement:** at this scale (gpt-4o-mini, level I+II, n=5) the
verified mechanism is *evidence-grounded organization selection with
executable replay, deployed through the generation interface* — including
replay of self-GENERATED designs (graph_generate confirmatory arm). It is NOT
free-form novel-topology invention guided by abstract insights; pre-A2, that
prompt-context-only variant measurably HURT (round 1). LLM-insight mining (B2)
and motif priors stayed OFF throughout — they are untested here, not refuted.

## Ablation: held-out gate

Three pieces of evidence (full detail in the round sections):
1. **Gate binds where learning is harmful:** round-3C's graph_generate bank
   (distilled from poor generated evidence, train_success 0.39) regressed
   held-out generation (j 0.0 -> 0.333) and was REJECTED — the pre-state was
   exported and the rejected ids recorded. Round-1-style harmful banks are the
   scenario this catches.
2. **Gate-off does not instantly drift in refine mode at this scale:** run B
   (MASBENCH_GATE_MODE=off, same split/seeds as run A) admitted one extra,
   legitimately-earned avoid skill; the deployed policy was UNCHANGED (36/36
   peer_star replays). The A/B verdict gap (+11.1 vs -2.8pp) is empty-arm
   rerun noise (cold generation scored I-09 at 42% vs 67% on identical seeds).
3. **Known weakness, reported as-is:** with 3-6 val runs per arm the gate's J
   is quantized at 1/6-1/3 and every accept so far has been a TIE accept
   (epsilon=0). The reject path works (offline tests + round-3C), but at this
   budget the gate is a guardrail against gross regressions, not a fine
   discriminator. Round 1's harmful bank was tie-accepted: more val seeds per
   gate decision is the obvious next investment if this pipeline scales up.
