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
