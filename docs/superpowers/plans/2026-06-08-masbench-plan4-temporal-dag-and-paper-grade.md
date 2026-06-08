# masbench Plan 4: temporal-DAG QueenBee on Silo + paper-grade experiment data

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. All subagents on **Opus 4.8**. Guardrails every task (must not regress): exp_graph `uv run --directory exp-graph --extra dev python -m pytest -q` = **237 passed, 1 skipped**; masbench `uv run --directory masbench --extra dev python -m pytest -q` = **37 passed**. New exp_graph behavior stays opt-in/default-off so CF is byte-identical.

**Goal:** Let the user run the FULL temporal-DAG QueenBee (LLM-generated communication DAG) on Silo-Bench and produce paper-grade comparison data. Implements follow-ups #1,2,3,5,6,7 + a paper-grade experiment harness.

**Builds on:** Plans 1–3 (done, committed). Engine is task-agnostic (`ProtocolTaskAdapter`, generic aggregation/metrics); `SiloProtocolAdapter` + masbench `--planner` (currently topology_select only); self-evolution overhaul (gate D, uncertainty E, veto/floor F, motif G, insight-falsify H), `masbench evolve`. The LLM DAG generator `exp_graph.mas.graph_generation.plan_free_graph(*, request, runtime: MASRuntimeConfig, skill_bank, seed, task_adapter, output_dir, llm_client=None) -> FreeGraphPlanningResult` (returns a MASPlan carrying the generated `protocol_spec`) already exists and is task-agnostic; it just isn't wired into masbench.

**Tech:** Python 3.11+, uv. Real-LLM via OpenAI: `--llm openai --model-name gpt-4o-mini` (masbench now has an `openai` extra; run with `uv run --extra openai ...` or `--with openai`). OpenAI client reads `OPENAI_API_KEY`.

---

## Task 1 (#1): Wire the graph-generating planner into masbench `--planner`

**Files:** `masbench/src/masbench/engine.py`, `masbench/src/masbench/core/config.py`, `masbench/src/masbench/cli.py`; test `masbench/tests/test_planner_graphgen.py`.

- Add `RunConfig.planner_mode: str = "topology_select"` (values: `topology_select` | `graph_generate`). Add CLI `--planner-mode`.
- In `engine._run_planner`: when `planner_mode == "graph_generate"`, build a `MASRuntimeConfig` (llm_provider/model from cfg; `num_graph_candidates`, `graph_max_steps`, `graph_max_messages`, `graph_max_receiver_fan_in` from sensible defaults / new RunConfig fields) and call `plan_free_graph(request=..., runtime=..., skill_bank=SkillBank(), seed=cfg.seed, task_adapter=SiloProtocolAdapter(instance), output_dir=<tmp/out>, llm_client=client)` to get a `MASPlan` with a generated `protocol_spec`; feed that spec into `ProtocolRunnerConfig(protocol_spec=..., merge_mode, init_mode, ...)` → `ProtocolRunner` (same as today). `topology_select` path unchanged.
- The DAG generation needs a real LLM. With `--llm fake` the generator won't produce valid graph JSON → it must FALL BACK gracefully (plan_free_graph already validates/repairs/falls back to a fixed topology); the offline test asserts the path runs + returns a `ProtocolFinalResult` (success not required offline). The real DAG-gen is exercised with gpt-4o-mini.
- `extra["planner_mode"]` recorded in ScoreResult.
- **Test:** `test_graphgen_offline_falls_back_runs` (fake LLM, `--planner --planner-mode graph_generate` on I-01 n2 → returns ScoreResult, extra.planner_mode=="graph_generate", no crash). `test_topology_select_unchanged` (default planner_mode still works as Plan 3 B).
- **Acceptance:** masbench suite green + 2 new; document the real-LLM graphgen command in README.

## Task 2 (#3): Partial-correctness scoring (Silo official metrics)

**Files:** `masbench/src/masbench/adapters/silo_protocol.py` (+ `silo_bench.py` if needed); test `masbench/tests/test_silo_partial.py`.

- In `SiloProtocolAdapter.score_protocol_answer`, compute a real `partial` in [0,1] (currently primary_metric is 1.0/0.0 exact only). Strategy: try to import Silo's official scorers from the submodule (`third_party/acl26-silo-bench/src/utils/metrics.py` / `src/{broadcast,msg,sfs}/evaluate.py`); if importable + applicable, use them. Else a robust per-output-type fallback keyed by `meta.output_type`/case: numeric scalar → 1.0 if exact else `max(0, 1 - |a-truth|/max(1,|truth|))`; list (e.g. sort) → fraction of positions correct / Kendall-ish; set → Jaccard; dict → key-overlap. Keep `success`/`exact_match` as the strict gate; `partial` is the graded signal.
- `score_protocol_answer` returns `{"primary_metric": <success 1/0 OR keep as success>, "exact_match": bool, "partial": float}`. Make `ScoreResult.partial` carry the graded value (engine already maps `partial=getattr(final,"primary_metric",None)` — adjust so partial = graded, primary_metric used for evolution as before; or add a `partial` field to ProtocolFinalResult). Keep CF untouched.
- **Test:** numeric near-miss gets partial∈(0,1); exact gets 1.0; a sorted-list near-miss gets a sensible partial; success still strict.
- **Acceptance:** masbench green + new tests; if official scorers aren't importable, document the fallback used.

## Task 3 (#7): Segmented Silo tasks (per-agent answers)

**Files:** `masbench/src/masbench/adapters/silo_bench.py`, `silo_protocol.py`, `core/task_bridge.py`; test `masbench/tests/test_segmented.py`.

- Detect `metadata.is_segmented == true` (per-agent `expected_output` differs). Loader already keeps `meta["expected_outputs"]`. Add scoring that compares each agent's final answer to its OWN segment (success = all agents correct on their segment; partial = fraction of agents correct). Add a `segmented` flag to the instance/global_task; `evaluate_final_answer`/`score` branch on it.
- **Test:** a small segmented fixture (per-agent different expected_output) scores per-agent; a non-segmented one is unchanged.
- **Acceptance:** masbench green + new; vendored segmented fixture added under tests/data.

## Task 4 (#6): task_family threading (Silo first-class in evolution)

**Files:** `exp-graph/src/exp_graph/mas/evolution.py` (`make_skill_card`, `classify_topology`, minister patches), maybe `schemas.py`; test `exp-graph/tests/test_task_family_threading.py` + remove masbench's `_retag_patches_to_family` workaround if clean.

- Thread a `task_family` through `ResultAnalystMinister.analyze(..., task_family="count_frequency")` / `make_skill_card(..., task_family=...)` / patch construction so Silo skills are tagged `silo` natively (default stays `count_frequency` → CF byte-identical). Update masbench `evolve.py` to pass `task_family="silo"` and drop the re-tag shim if no longer needed.
- **Test:** minister with `task_family="silo"` emits skills/patches tagged `silo`; default emits `count_frequency` (CF unchanged).
- **Acceptance:** both suites green; CF evolution tests unchanged.

## Task 5 (#2): Activate motif credit in graph-candidate scoring

**Files:** `exp-graph/src/exp_graph/mas/graph_generation.py` (`_evaluate_candidates`), maybe `mas/motifs.py`; test `exp-graph/tests/test_motif_activation.py`.

- In `_evaluate_candidates`, add an OPT-IN motif prior: when enabled (a flag on `MASRuntimeConfig`/`GraphValidationOptions`, default OFF → CF/default selection unchanged), blend `score_spec_by_motifs(candidate_spec, motif_stats)` into the candidate ranking (motif_stats passed in from accumulated evidence). Default off keeps the 237 baseline green.
- masbench graph_generate path (Task 1) turns the flag ON and supplies motif_stats from the run's evidence so generated DAGs are scored with transfer.
- **Test:** with the flag on + motif_stats favoring a motif, a candidate sharing that motif is ranked above one without it; with flag off, ranking is unchanged.
- **Acceptance:** both suites green; CF candidate selection unchanged by default.

## Task 6 (#5 + harness): Paper-grade Silo experiment harness

**Files:** `masbench/src/masbench/bench.py`, `cli.py` (`bench` subcommand), `core/` as needed; test `masbench/tests/test_bench.py`.

- `run_benchmark(adapter, *, cases, agent_counts, seeds, arms, cfg) -> dict` running these ARMS per (case, n_agents, seed):
  - `fixed`: each topology in a configured set (e.g. tree, mesh_star, one_peer_exponential_dag_star, chain) via planner-OFF/fixed protocol → per-topology metrics; the per-condition best = "oracle fixed".
  - `select`: `--planner` topology_select.
  - `graphgen`: `--planner --planner-mode graph_generate` (LLM DAG).
  - `evolved`: `run_evolution` on train seeds (gate ON, real held-out via `--no-synthetic-held-out` when real LLM) → eval on test seeds.
- Aggregate per condition: mean±std of success, partial, messages, model_calls, tokens.
- Emit `results.json` + `results.csv` + `report.md` (a Table-1-style matrix: condition × arm → success / partial / msgs / tokens; mark the winning arm).
- CLI: `masbench bench --benchmark silo_bench --benchmarks-dir ... --levels I II --agent-counts 2 5 --seeds 1 2 3 --arms fixed select graphgen evolved --llm openai --model-name gpt-4o-mini --out runs/paper`.
- **Test (offline, fake):** a tiny grid (1–2 reduce cases, n=2, 1 seed, arms=fixed+select) runs end-to-end, writes results.json/report.md with the expected structure + per-condition aggregates. (graphgen/evolved arms covered by their own tests; bench just orchestrates.)
- **Acceptance:** masbench green + new; `report.md` renders a readable comparison table.

## Task 7: Docs + final verification + reproduce command

- Update `masbench/README.md`: a "Paper-grade experiments" section with the offline `bench` smoke AND the real-LLM `bench ... --llm openai --model-name gpt-4o-mini --extra openai` command; note `--planner-mode graph_generate` = the temporal-DAG QueenBee.
- `masbench/docs/experiments.md`: the experiment design (arms, metrics, grid, how to read report.md), and the honest caveats (offline determinism, partial-scorer fallback, motif activation).
- Run BOTH suites; report final counts.

---

## Self-review (author)
- Order: T1 (graphgen — the headline) → T2 (partial) → T3 (segmented) → T4 (task_family) → T5 (motif activation, depends on T1's graphgen path) → T6 (harness, depends on T1+T2) → T7 (docs/verify).
- Every exp_graph change (T4, T5) stays opt-in/default-off → the 237 baseline holds; masbench changes covered by new tests + the 37 baseline.
- Real DAG-gen + paper data require a real LLM (gpt-4o-mini); offline tests prove wiring + graceful fallback, not correctness.
- Known deferrals: std_primary_loss recording (#4) skipped per user; REALM-Bench/M-APPLE-OS (#8) separate phase.
