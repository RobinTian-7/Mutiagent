# Self-evolution changes (Plan 3)

The QueenBee self-evolution overhaul adds five improvements over the paper's
described loop. Each is implemented in `exp_graph` (all opt-in and default-off, so
the count-frequency pipeline stays byte-identical) and is *activated* by the
masbench `evolve` loop (`masbench/src/masbench/evolve.py`,
`masbench evolve ... --llm fake`). This note records, for each improvement, the
owning `exp_graph` module and how it differs from the paper.

The masbench loop wires them together: it runs real Silo-Bench instances through
the QueenBee planner + `ProtocolRunner`, turns each run into an aggregate row
(`exp_graph.mas.runner.summary_to_aggregate_row`), has the ResultAnalyst minister
propose patches (`exp_graph.mas.evolution.ResultAnalystMinister`), and applies
them through the validation gate with the E/F selection knobs active on the
planner requests.

## 1. Held-out validation gate (D)
- **Module:** `exp_graph.mas.consolidation.consolidate_skill_updates(..., validation_rows, epsilon, gate)` + `exp_graph.mas.validation.validation_objective`.
- **What it does:** before committing a patch batch, it measures a lower-is-better
  held-out objective `J_val` (for each held-out condition, which topology the
  planner would select and that topology's held-out loss), applies the batch to a
  *clone* of the bank, recomputes `J_val`, and commits to the real bank only if
  `j_after <= j_before - epsilon`. On rejection the bank is untouched and the
  rejection is reported (`counts['gated_out']`, a warning, and `gate_*` fields).
- **Difference from the paper:** the paper *describes* "accept a skill update only
  if it improves a held-out objective" but provides **no implemented gate** — skill
  updates were applied unconditionally. This is the missing acceptance rule, now
  implemented and run end-to-end (`masbench evolve` prints the real
  `J_before`/`J_after` and accept/reject).

## 2. Uncertainty-aware selection + min-sample gating (E)
- **Module:** `exp_graph.mas.scoring.score_skill` / `lcb_primary_loss` (the LCB
  accuracy penalty) and `exp_graph.mas.skill_bank.SkillBank.retrieve` /
  `is_selectable_skill` (the min-sample gate); knobs `ObjectiveSpec.uncertainty_weight`
  (kappa) and `ObjectiveSpec.min_seeds`.
- **What it does:** the accuracy term becomes a pessimistic loss
  `mean_loss + kappa * std / sqrt(max(1, n))`, so a high-variance / tiny-sample
  "lucky" skill is demoted relative to a stable one; skills backed by fewer than
  `min_seeds` independent observations are excluded from selection.
- **Difference from the paper:** the paper selects topologies on the **plain mean**
  metric with no variance penalty and no minimum-evidence requirement, so a single
  lucky seed could win. The loop sets `uncertainty_weight=1.0`, `min_seeds=1`.

## 3. Counterexample veto + absolute floor (F)
- **Module:** `exp_graph.mas.planner.TopologySelectPlanner.plan` (the veto, floor,
  and risk-penalty selection logic) reading `SkillBank.retrieve_avoid`; knobs
  `ObjectiveSpec.enforce_avoid_veto`, `ObjectiveSpec.max_acceptable_loss`,
  `ObjectiveSpec.risk_weight`.
- **What it does:** topologies flagged by matching avoid/counterexample skills are
  removed from the candidate set (hard veto, with a safe-default fallback if every
  candidate is vetoed); a candidate whose loss exceeds `max_acceptable_loss` is
  rejected in favor of a safe default; `risk_weight` subtracts a
  `confidence.risk_penalty` term from the selection score.
- **Difference from the paper:** the paper keeps counterexamples only as *retrieval
  hints* and has **no veto, no absolute no-worse-than-baseline floor, and no
  risk-aware score adjustment** — a dominated topology could still be selected.
  The loop sets `enforce_avoid_veto=True`, `risk_weight=0.5`,
  `max_acceptable_loss=0.99`.

## 4. Motif / operator credit attribution (G)
- **Module:** `exp_graph.mas.evolution.infer_topology_structure_features` +
  `default_operation_recommendations` (and `make_skill_card`, which stores
  `organization_policy.structure_features` / `operation_recommendations`).
- **What it does:** credit is attributed to explicit topology *motifs*
  (`hierarchical_reduce`, `single_sink`, `peer_broadcast`, ...) and operator-level
  recommendations, not just the opaque topology name, so lessons transfer across
  topologies that share structure.
- **Difference from the paper:** the paper attributes outcomes to the **whole-graph
  topology name**; structure-/operator-level credit that generalizes across graphs
  is new.

## 5. LLM insight falsification (H)
- **Module:** `exp_graph.mas.insights.falsify_insights(report, held_out_rows)` +
  `insight_report_to_patches(report, require_verified=True)`.
- **What it does:** each LLM-proposed design insight is turned into a checkable
  topology claim and tested against held-out aggregate rows (a claimed-good
  topology must have `<=` median loss in its condition; a claimed-bad topology
  `>=` median). Verified claims become `observed`; contradicted ones become
  `rejected` and are dropped; unverifiable ones stay `hypothesis`. With
  `require_verified=True` only verified insights can become skill patches.
- **Difference from the paper:** the paper lets the LLM's insights feed skill
  updates **without an empirical falsification step**, so a plausible-but-wrong
  insight could become an accepted skill. Falsification gates that path.

## What the offline `masbench evolve --llm fake` loop activates
- **D** — the gate runs (`consolidate_skill_updates(gate=True)`) and the CLI prints
  the real `J_before`/`J_after` + accept/reject.
- **E** — the planner requests set `uncertainty_weight=1.0` and `min_seeds=1`
  (`evolve.evolution_objective_spec`), so `score_skill` runs the LCB path and
  `retrieve` runs the min-sample gate during evidence collection.
- **F** — the same requests set `enforce_avoid_veto=True`, `risk_weight=0.5`, and
  `max_acceptable_loss=0.99`, so `TopologySelectPlanner.plan` runs the veto/floor/
  risk logic.

G and H are exercised by the exp_graph suite (`make_skill_card` structure features
and `falsify_insights`/`require_verified`); the masbench loop focuses on the D+E+F
selection/gate path, which is the part that "actually runs the improved
self-evolution end-to-end on Silo".

### Offline honesty caveat
Silo's deterministic offline path is *topology-invariant on success*: a fake-LLM
run of a case either solves it (loss 0) or not (loss 1), the same way for every
topology, so real offline Silo rows cannot, alone, make one topology look better
than another on the held-out loss the gate uses. To keep the offline gate decision
**real and non-degenerate**, `masbench evolve --llm fake` injects a small synthetic
multi-topology held-out set (`masbench.evolve.accepting_held_out_rows`); the gate
arithmetic (which topology the planner selects before vs. after the batch, and
whether `J_val` improves) is computed by the real gate. With a real LLM the
held-out Silo runs differ by topology, so `--no-synthetic-held-out` scores the gate
purely on real evidence.

## Self-evolution v2 additions

The original Plan-3 path above remains the compatibility default. The following
mechanisms are activated only by their v2 switches.

### Seed and artifact identity

`evolve._run_one` binds its explicit seed into an immutable per-run config before
generation, execution, cache-key construction, and audit output. GraphGen,
PhaseProgram, and PythonGen artifact leaves all include case, Agent count, seed,
information goal, PID, and a nanosecond timestamp. The frozen verifier roots all
three artifact families under its `--out` directory.

### Typed failure feedback

`--failure-policy honest_v2` distinguishes algorithm, infrastructure, and
harness failures. Algorithm failures remain as zero-scored dense evidence with
incurred cost; infrastructure failures alone permit symmetric pair removal;
harness/unknown errors abort. Strict answer-free Pydantic records are clustered
by mode/goal/worker/stage/type/structure and merged only into compatible Skills.
The next architect sees a bounded negative section separate from positive
evidence. `legacy_drop` remains the default.

### Python parent innovation

`--python-innovation-strategy fresh|mutate|mutate_and_fresh` controls the
hot-start Python branches. Local mutation uses `python_mutation_patch_v1` and can
replace exactly one pre-existing `EVOLVE-BLOCK`; parent hash, marker whitelist,
non-selected blocks, exposed insight ids, AST policy, dry run, sandbox, real
execution, stdout, and usage are all host-verified. Complete resulting source
and mutation provenance remain in the independent `python_skill_v1` payload.

### Dense ratchet and insight association

`--evolution-gate-policy strict_dense_v2` stores paired validation samples and
requires non-regression in algorithm failure rate, V, K, U, tolerated P, and
the paired stage-score interval. S or dense stage score must improve; only an
equal-quality C/D reduction can otherwise pass. Rejection deploys the exact
before snapshot while retaining the candidate audit. Paired branch/insight
statistics are explicitly association, not causal credit, accumulate over
rounds, and move repeatedly losing insights into negative constraints after
three exposures. `legacy_non_regression` remains the default.

### Strict final submissions and resumable verifier

The paired verifier has an opt-in `--require-all-submissions` contract for
`all_agents` experiments. Python `message_only_v2` retains its synchronized
runtime barrier. Paper transports keep their native communication semantics and
invoke a bounded barrier only for missing submitters; fixed topology arms query
all Agents explicitly from their final beliefs. Whole-response JSON parsing is
strict, null/empty answers fail, retries correct format only, and the host never
uses expected output to repair or synthesize an answer.

Long verifier runs atomically persist `run_checkpoint.json` after each deployed
evolution round, alongside the complete before/candidate/deployed SkillBank
snapshots. `--resume` requires an exact configuration match and reloads the last
deployed bank plus motif state. It skips only completed training rounds; frozen
selection and TEST evaluation rerun so a partial final table is never presented
as a complete experiment.

For patient real-provider runs, `--llm-timeout-attempts` raises the bounded retry
count while every attempt remains protected by `--request-timeout`.
`--require-complete-runs` converts any exhausted infrastructure failure into an
abort at the last complete checkpoint; it forbids the normal honest-v2 behavior
of symmetrically dropping that sample.
