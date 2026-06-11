# Phase 2 pre-registration — "stably beats ALL baselines after R rounds"

Written 2026-06-10, before any phase-2 real-LLM run. Binding, same rules as
phase 1 (`docs/selfevolve_preregistration.md`); changes only via the changelog.

## Frozen judge

`masbench/scripts/verify_beats_baselines.py` is FROZEN as of 2026-06-10
(suite: tests/test_verify_beats_baselines.py, 5 tests incl. the offline
machinery smoke; masbench 154 / exp-graph 262 green). Judgment logic:
- paired 4 arms on identical (case, seed): evolved (R-round accumulated bank,
  deployed mode) vs select(empty) vs graphgen(empty) vs fixed_best_on_train
  (argmax train-mean over {tree, mesh_star, one_peer_exponential_dag_star,
  chain}, lexicographic tiebreak);
- PASS iff vs EACH baseline: delta >= 5pp AND discordant margin >= 2;
- rounds stability (last 3 rounds of a `masbench curve` rounds_curve all above
  every baseline in that file) is reported separately (`stable_rounds_ok`).
Fixes go into the pipeline, never into this script. verify_evolve.py (phase 1)
also stays frozen.

## Difficulty scout (exploration, NOT evaluation — pre-registered here)

Purpose: pick phase-2 CONFIRMATORY reserved conditions among condition
candidates that were never used in phase 1 (phase 1 burned: I-01..I-06, I-09,
II-13, II-14, II-15, II-19, all @ n=5).

- Scout seeds: **[9874, 616]** (drawn 2026-06-10 before this file was final).
- Scout grid A (level III, unexplored): cases III-21..III-25 @ n=5,
  arms {select, graphgen}, 2 seeds.
- Scout grid B (n=10 re-probe of paper-era signals): cases I-02, I-04, II-13,
  II-15, II-16, II-19 @ n=10, arms {select, graphgen}, 2 seeds.
- Budget: <= $2 (estimated ~$0.4); budget_guard must pass before launch.

## Reservation rule (declared BEFORE seeing scout results)

From scout (+ phase-1 paper-grid priors), reserve 2-3 confirmatory conditions
(case, n) that satisfy ALL of:
1. never used in any phase-1 or phase-2 dev round (as train or test);
2. the BEST baseline of {select, graphgen} lands in [20%, 70%] (headroom above
   the strongest baseline; floors and ceilings carry no information);
3. prefer conditions where select and graphgen disagree (organization-
   sensitive), and prefer condition diversity (not all the same n / level).
The reserved set is written into this file's changelog immediately after the
scout is read, BEFORE any evolved/dev measurement on those conditions.
Constraint: within any verify run, train and test share the same n_agents
(executable-spec replay requires matching n).

## Confirmatory protocol (frozen)

`verify_beats_baselines.py` on the reserved conditions: cases list chosen so
the sorted tail = reserved cases; R >= 3 rounds; both evolved modes
(select_then_refine primary, graph_generate reported); seeds drawn fresh at
confirmatory time (2 train + 1 val + 10 eval) and recorded into the protocol
JSON before launch. Goal B additionally requires `masbench curve` stability
(last >= 3 rounds above all curve baselines) on the SAME reserved conditions —
the curve run's seeds are drawn and recorded the same way.
Max 3 attempts, 2 PASSes required; PASS = the frozen script's exit 0 on
select_then_refine. No checkpoint/parameter selection on confirmatory results.

## Budget

Cumulative (continuing phase 1's ledger) <= $40; per round <= $2 unless the
protocol JSON documents why; `scripts/budget_guard.py --planned-usd X` must
pass before every real launch.

## Changelog

- 2026-06-10: initial version; judge frozen; scout not yet run.
- 2026-06-10 (scout read; BEFORE any evolved/dev measurement on these
  conditions): **reserved confirmatory conditions = II-13 @ n=10 and
  II-16 @ n=10.** Scout (seeds [9874,616], 2/arm): II-13@n10 select 0% /
  graphgen 50%; II-16@n10 select 50% / graphgen 0% — both satisfy rule 2
  (best baseline in [20,70]) and rule 3 (organization-sensitive), and their
  directions are OPPOSITE, so no constant policy can pass on both; III@n5 had
  no dynamic range (4 floors, 1 ceiling), I-02/I-04/II-15@n10 are
  best-baseline ceilings, II-19@n10 a floor. Both reserved conditions are
  level II at n=10 (diversity preference yields to rule-2 eligibility — no
  other candidates qualified). Scout cost $0.45 (ledger).
- 2026-06-10 (efficiency changes, judgment untouched; landed AFTER confirmatory
  attempt 1 was launched, so attempt 1 runs without them): (1) opt-in evidence
  cache (`MASBENCH_EVIDENCE_CACHE`) for bank-INDEPENDENT runs only — named-
  topology evidence rows (fresh empty bank by construction) and the generation
  gate's round-invariant j_before; explore, j_after, and ALL paired-eval runs
  are never cached. At temperature 0 a cached row is the same measurement
  reused, not a lost sample. (2) refine-mode evolution no longer collects val
  evidence rows (the selection gate — their only consumer — is inactive in the
  single-gate architecture; pure spend removal). (3) `scripts/dev_screen.py`,
  an explicitly-labeled 2-arm SCREENER for dev direction checks (~$0.2);
  verify_beats_baselines.py remains the only verdict authority. Frozen judges
  unedited; suites green (masbench 168 / exp-graph 262).
- 2026-06-10 CLOSE-OUT: confirmatory attempts 1 and 2 both FAILED (failure
  analyses in the evidence report; two scoring inversions root-fixed along the
  way). With 2 PASSes required of 3 attempts, the goal became arithmetically
  unreachable; **attempt 3 left unconsumed** — both candidate configurations
  failed cheap screens (probe route -20pp/-60pp vs select) and the attempt-2
  configuration was already measured at 0%, so spending it could not change
  the overall verdict and would have violated the no-number-chasing clause.
  Final verdict: phase-2 goal NOT MET; boundary finding (in-paradigm transfer
  works at cost parity, cross-paradigm replay fails representationally)
  documented in `docs/selfevolve_evidence_report.md`. Total spend $12.16/$40.
