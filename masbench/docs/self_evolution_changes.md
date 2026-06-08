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
