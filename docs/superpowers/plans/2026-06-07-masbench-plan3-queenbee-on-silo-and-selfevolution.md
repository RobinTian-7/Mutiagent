# masbench Plan 3: QueenBee on Silo-Bench + self-evolution overhaul

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. All subagents on **Opus 4.8**. Guardrail every task: exp_graph **200 passed, 1 skipped** + masbench **27 passed** must not regress (run `uv run --directory exp-graph --extra dev python -m pytest -q` and `uv run --directory masbench --extra dev python -m pytest -q`).

**Goal:** Run the full QueenBee architecture (temporal-DAG planner + protocol execution + self-evolving skills) on Silo-Bench, and implement the agreed self-evolution improvements (validation gate, uncertainty-aware/veto/floor selection, motif-level credit, insight falsification).

**Builds on:** Plan 2 (done) — `ProtocolTaskAdapter`, generic vote aggregation, generic step metrics, generic evidence keys (`PrimaryMetric`/`PrimaryMetricName`). The temporal-DAG generator (`plan_free_graph`) + `ProtocolGraphSpec` are already task-agnostic.

**Critique driving this plan** (see prior turn): the paper's "accept-only-if-J_val-improves" validation gate is NOT in the code (`consolidate_skill_updates` applies patches unconditionally); evidence is tiny-sample/uncertainty-blind; selection is relative-only with unused risk signals + non-enforced counterexamples; mean-optimization is worst-case-blind; credit is whole-topology (no transfer); LLM insights are weakly verified; the reward is RMSE-shaped.

---

## Part A — `SiloProtocolAdapter` (masbench) — the keystone for "run Silo with QueenBee"

**File:** `masbench/src/masbench/adapters/silo_protocol.py`; **Test:** `masbench/tests/test_silo_protocol_adapter.py`.

`SiloProtocolAdapter(exp_graph.tasks.protocol_adapter.ProtocolTaskAdapter)` wrapping a `BenchmarkInstance`. Implements:
- The 6 base `TaskAdapter` methods (reuse `masbench.core.task_bridge` logic: `canonical_answer`, GROUND_TRUTH_KEY hiding, per-agent shard split, prompt rendering).
- The 7 protocol belief methods for **generic structured answers**: belief carries the agent's current candidate answer in `structured_state={"task_name":"silo","case_id":..,"answer":<canonical>}` + `consensus_key=canonical_answer(answer)`. `initial_protocol_belief` → "UNKNOWN" (agent only holds a shard; can't know the global answer alone) OR a deterministic local reduce for associative-reduce cases (reuse the reduce registry from `masbench/llm/fake.py`). `merge_protocol_inbox` (deterministic path) → for reduce-style cases, reduce over self+inbox answers; otherwise keep "UNKNOWN" (LLM does the real merge). `format_protocol_init_prompt`/`format_protocol_merge_prompt` → instruct the LLM to produce/merge a global answer for THIS Silo task (render `task_prompt` + neighbor answer artifacts), answer in `structured_state.answer`. `validate_protocol_*` → normalize the answer via `canonical_answer`, set consensus_key. `apply_verified_protocol_merge` → keep LLM wording, verified answer.
- `extract_protocol_answer` → the canonical answer; `protocol_answer_key` → `canonical_answer(answer)`; `score_protocol_answer` → `{"primary_metric": 1.0 if success else partial, "exact_match": success}` where success = canonical(answer)==canonical(ground_truth) and partial = the partial-correctness scorer (Part C-partial; start with success-only, partial=success).
- `compute_protocol_agent_metrics` → `{"coverage_ratio":..,"primary_metric":1.0 if agent answer==truth else 0.0,"exact_match":..}`.

**Acceptance:** an offline deterministic smoke (reduce-style case e.g. Global Max) runs through `ProtocolRunner` with the Silo adapter → final answer correct; a non-reduce case runs without crashing (UNKNOWN offline). Guardrail green.

## Part B — Wire `--planner` in masbench engine → QueenBee on Silo

**File:** `masbench/src/masbench/engine.py` (extend `run_instance`); CLI `--planner` already exists.

When `cfg.use_planner` is True: build `SiloProtocolAdapter`, build global_task, run via the QueenBee path:
- Minimal/offline: `EmperorPlanner(skill_bank).plan(PlannerRequest(task_family="silo", n_agents, objective))` → topology_name (+ optional protocol_spec) → `ProtocolRunner(ProtocolRunnerConfig(topology_name/protocol_spec, merge_mode, init_mode), SiloProtocolAdapter, global_task)` → `ProtocolFinalResult` → `ScoreResult`. (Remove the Plan-1 `NotImplementedError`.)
- Real-LLM: `merge_mode="llm_full_merge"`, `init_mode="llm_local_solve"`, optional `planner_policy="free_graph"` (graph_generate via `plan_free_graph`) for true temporal-DAG QueenBee.
- `--evolve` flag → after the run, build an evidence row (`summary_to_aggregate_row`, now generic) and run the minister/consolidation loop (Part C–H).

**Acceptance:** `masbench run --benchmark silo_bench --case I-01 --n-agents 2 --planner --llm fake` runs end-to-end and scores; a fake-LLM smoke test asserts a `ScoreResult` with the QueenBee path. Document the real-LLM `--planner` command in README.

## Part C — Generalize the evolution objective to success+partial

Ministers consume aggregate rows; Plan 2 added `MeanPrimaryMetric`/`PrimaryMetricName`. Make `ingest.aggregate_rows_to_evidence` + `scoring.score_skill` + `evolution` use `MeanPrimaryMetric` with a `primary_metric_name`-aware direction (RMSE lower-better; success higher-better → store as "regret" = 1 - success so lower-better is uniform, OR add a `higher_is_better` flag threaded through `score_skill`'s min-max invert). Add `task_family="silo"` support to `PlannerRequest`/`SkillCard` defaults (currently hardwired "count_frequency"). Guardrail: CF evolution tests stay green.

## Part D — Validation gate (the keystone self-evolution fix)

**File:** `exp_graph/mas/consolidation.py` (+ a new `validation.py`).
Implement the paper's missing gate: given a candidate bank `S' = S ⊕ ΔS`, evaluate `J_val` on a held-out validation set (re-run selection+execution, or score skills against held-out evidence) and **accept ΔS only if `J_val(S') ≤ J_val(S) − ε`** (ε default 0); else archive the patch as unverified. Add `consolidate_skill_updates(..., validation_evidence=..., epsilon=0.0, accept_if_improves=True)`. Default OFF (so existing CF tests unchanged) and ON in the masbench QueenBee `--evolve` path. Test: a regressing patch is rejected; an improving patch is accepted.

## Part E — Uncertainty-aware selection + min-sample gating

**File:** `exp_graph/mas/scoring.py` + `skill_bank.retrieve`.
Add a lower-confidence-bound selection: `score = mean_score − κ·std/sqrt(n)` (κ default ~1.0) so high-variance/low-n skills don't win on a lucky mean; gate skills below `min_seeds` (default 2) out of `is_selectable_skill` (or down-weight). Keep CF defaults so existing tests pass (κ=0 / min_seeds=1 preserves current behavior unless configured). Test: a 1-seed lucky skill loses to a many-seed stable skill under the LCB.

## Part F — Counterexample hard veto + absolute floors

**File:** `exp_graph/mas/planner.py` + `scoring.py`.
In `TopologySelectPlanner.plan`, exclude any topology matched by a retrieved avoid-skill (hard veto via `skill_bank.retrieve_avoid`); apply an absolute floor (don't select a skill whose `expected_tradeoff` violates a configured floor / is dominated by the safe fixed-topology baseline). Subtract `confidence.risk_penalty` from the selection score (currently computed but unused). Test: a vetoed topology is never selected even if top-scored.

## Part G — Motif/operator credit attribution

**File:** `exp_graph/mas/evidence.py` + `evolution.py` + `skill_bank.py`.
Attribute each run's evidence to structural motifs (fan-in profile bucket, sink placement, audit-edge presence, reduction depth — derivable from `ProtocolGraphSpec`/`topology_equivalence`), not just `topology_name`. Add motif-level evidence rows + a motif score the planner consults when scoring a *generated* DAG (so knowledge transfers to novel DAGs). Test: a generated DAG sharing a winning motif scores higher than one without it.

## Part H — LLM insight falsification verification

**File:** `exp_graph/mas/insights.py`.
Require each `MASInsight` to carry a falsifiable prediction (`falsification_test` already exists as a field) and verify it against held-out evidence before `insight_report_to_patches` is allowed to influence the planner; unverified insights stay `claim_status="hypothesis"` and are ignored by selection. Test: an insight contradicted by held-out evidence does not produce an accepted patch.

## Part I — Final verification + docs

Full exp_graph + masbench suites green; a documented real-LLM `--planner --evolve` command; README + spec updated; a short `docs/` note on the self-evolution changes vs the paper.

---

## Self-Review (author)
- Part A+B deliver the user's primary need ("run Silo with QueenBee") and are independent of D–H — do them first. C is small plumbing on Plan 2's generic keys. D is the highest-leverage self-evolution fix; E–H are the remaining agreed improvements.
- Guardrail discipline: every exp_graph change keeps CF defaults (gates default OFF / κ=0 / min_seeds=1) so the 200-test baseline holds; new behavior is opt-in via the masbench QueenBee `--evolve` path and covered by new tests.
- Risk: D–H touch the subtlest evolution code; each is a separate task with its own test + the full-suite guardrail. Sequence: A → B → C → D → E → F → G → H → I.
