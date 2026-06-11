# Self-evolve verification — pre-registration

Written 2026-06-09, BEFORE any real-LLM development round of this effort.
This document binds the experiment design. Changes to it after seeing dev
results are allowed only for *future* rounds and must be logged in the
changelog at the bottom; the confirmatory protocol below is frozen.

## Claim under test

Self-evolution (`run_evolution` -> gated skill bank -> `select_then_refine`
generation) improves held-out Silo-Bench exact-match over an empty bank, by a
mechanism: the bank carries evidence-backed organization knowledge (which
canonical topologies succeed on this task family + their executable protocol
specs + design insights), and generation that refines those references
produces better temporal DAGs than cold generation.

## Fixed configuration (all rounds, both arms, symmetric)

- model: gpt-4o-mini, temperature 0.0, request-timeout 120s, workers 8
- benchmark: Silo-Bench levels I+II, n_agents = 5
- merge_mode=llm_full_merge, init_mode=llm_local_solve, objective=accuracy_first
- primary mode: `select_then_refine`; secondary (reported, weaker prior): `graph_generate`
- graphgen-candidates 3, graph-validation-seeds 0, LLM-insights OFF
- judge: `masbench/scripts/verify_evolve.py` (frozen; never edited for judgment)
- PASS criteria (script defaults): paired delta >= +5pp AND
  (evolved-only wins - empty-only wins) >= 2

## Reserved confirmatory TEST cases (never used in any dev round)

**II-15 and II-19.**

Rationale (from pre-existing data only — the 2026-06-08 `runs/paper` grid,
gathered before this effort): at n=5 both cases are organization-sensitive
(select 60%/60% vs cold-generation 0%/0%), i.e. they have headroom for the
mechanism and are not model-capability floors (unlike I-07/I-08/I-10/II-11/
II-12/II-14/II-16/II-17/II-18/II-20, ~0% under every arm at n=5). Selection is
arm-symmetric: it uses only select-vs-graphgen baseline gaps, not any evolved
result. These two cases never appear in any dev round, neither as train nor as
test.

## Confirmatory protocol (frozen)

```
bash scripts/verify_evolve.sh \
  --cases I-01 I-02 I-03 I-06 I-09 II-13 II-15 II-19 \
  --holdout-frac 0.3 --n-agents 5 \
  --train-seeds <2 fresh> --val-seeds <1 fresh> --eval-seeds <10 fresh> \
  --evolved-mode select_then_refine   # and a second run: graph_generate
```

- Sorted case list puts II-15, II-19 last -> script's holdout = exactly the
  reserved cases (verified offline before running).
- Seeds: drawn at confirmatory time via
  `python3 -c "import random; print(random.sample(range(100,10000),13))"`
  (2 train + 1 val + 10 eval), recorded into the run JSON IMMEDIATELY, before
  the run starts. Both modes use the identical case list and seeds.
- TRAIN cases overlap dev training pools by design: the bank is rebuilt from
  scratch inside each confirmatory run (no state persists), so the held-out
  guarantee that matters is on TEST cases, which are dev-virgin. Stated here
  for honesty.
- Success = script PASS on select_then_refine. Reproduce: a second confirmatory
  run with freshly drawn seeds (same reserved cases). Goal B met iff 2
  confirmatory PASSes. Max 3 confirmatory attempts total, ever; a failure sends
  the effort back to development with a written failure analysis.
- No checkpoint/parameter selection on confirmatory outcomes; no re-rolling
  seeds; the first drawn seed set per attempt is the one used.

## Development protocol

- Dev rounds use `verify_evolve.py` with a ROTATED case split each round
  (different `--cases` subsets so the holdout tail varies) and FRESH
  `--eval-seeds` drawn per round from range(100,10000) and recorded.
  No identical (split, seeds) combination is ever re-run to chase a number.
- Known constraint (stated upfront): the script holds out the lexicographically
  last 30% of `--cases`, so early-sorting cases (I-01..I-06) can only appear in
  dev TEST tails when no later-sorting case is included; dev test rotation
  therefore draws mostly from {I-08, I-09, I-10, II-11..II-14, II-16..II-18,
  II-20}. The real anti-overfitting guard is the reserved confirmatory set.
- Method changes (minister, gate, retrieval, motif credit, generation prompts)
  are allowed between rounds, must pass offline (fake-LLM) tests with the CF
  suite green before any real-LLM spend, and must come with a mechanism story.
  Any change that improves numbers without an explicable mechanism is treated
  as overfitting and reverted.

## Deliverables (regardless of outcome)

1. Paired numbers + discordant-pair counts + reproduction count.
2. Learned skills list + per-skill mechanism explanation + before/after
   generated-DAG comparisons on held-out cases.
3. Ablation: same pipeline with the held-out acceptance gate disabled — does
   the bank drift / get worse?
4. Cost parity: evolved arm must not win by spending more tokens/calls on the
   paired eval (report mean tokens + calls per arm).

## Budget

Real-LLM spend cumulative <= $40 for this whole effort, tracked in
`masbench/runs/COST_LEDGER.json` (tokens x $0.2625/M blended gpt-4o-mini
estimate). Calibration: n=5 protocol run ~19.5k tokens ~= $0.005; a dev round
~70-90 runs ~= $0.4; a confirmatory attempt (2 modes) ~220 runs ~= $1.2.

## Red lines (restated)

- No hardcoding case answers/patterns; no editing verify_evolve.py judgment;
- no reading masbench/.env; no test-set-driven checkpoint or hyperparameter
  selection; "no detectable effect at gpt-4o-mini + level I/II scale" is an
  acceptable, reportable outcome.

## Changelog

- 2026-06-09: initial version (no real-LLM dev round run yet under this plan).
- 2026-06-09 (while round 1 was RUNNING, before seeing its results): implemented
  A2 "executable-spec transfer" — evidence rows now carry the executed schedule,
  so minister skills store executable protocol_specs and the documented
  select_then_refine replay/seed path actually fires (it was dead code: the
  vacuous `"protocol_spec" in organization_policy` test passed on a None value).
  Motivated purely by code reading; round 1 measures the PRE-A2 pipeline
  (prompt-context transfer only), round 2 will measure POST-A2. Also: the
  held-out gate now measures GENERATION (deployed mode) for select_then_refine,
  rejected updates export the pre-state, gate runs are per-run isolated, and a
  gate-off knob (MASBENCH_GATE_MODE=off) exists for the drift ablation.
