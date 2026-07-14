# Paper-grade experiments (`masbench bench`)

This is the experiment guide for `masbench bench` — the harness
(`masbench/src/masbench/bench.py`, `run_benchmark`) that produces the Table-1
comparison of communication-structure policies ("arms") on Silo-Bench. It
orchestrates the *existing* engine/evolve building blocks; it does not invent any
new run semantics. Every arm routes through the same
`exp_graph.runner.protocol.ProtocolRunner` and the same masbench scorer
(`engine._score_protocol_result`), so the metrics are directly comparable. The
harness only decides *which structure each arm uses* and then aggregates over a
grid of conditions `(case_id, n_agents)` × seeds.

## The four arms

| arm | what it is | how it is run |
| --- | --- | --- |
| **fixed** | planner-OFF baselines: each named topology is forced through the protocol runner | `engine.run_fixed_protocol(..., topology=t)` for every `t` in `--fixed-topologies`, every seed; `use_planner=False` |
| **select** | QueenBee picks a *named* topology | `run_instance` with `use_planner=True`, `planner_mode="topology_select"` |
| **graphgen** | the FULL QueenBee: the emperor LLM invents a bespoke *temporal communication DAG* | `run_instance` with `use_planner=True`, `planner_mode="graph_generate"`, `num_graph_candidates=--graphgen-candidates` |
| **evolved** | the gated self-evolution loop, then its post-evolution selection evaluated on held-out seeds | `evolve.run_evolution(...)` run ONCE per agent-count on the train seeds; the resulting topology is then run via `run_fixed_protocol` on the test seed |

Notes:

- **fixed** runs via the *protocol* path (not the legacy `SynchronousRunner`)
  deliberately: the paper's fixed baselines are *protocol-schedule* topology names
  (`tree`, `mesh_star`, `one_peer_exponential_dag_star`, `chain`) that only
  `build_protocol_schedule` understands, and routing them through the protocol
  runner makes the whole comparison apples-to-apples (one runner, one scorer, one
  message/model-call/token accounting). See `engine.run_fixed_protocol`'s
  docstring for the full rationale.
- **graphgen** feeds accumulated *motif evidence* from earlier conditions back
  into later graphgen runs (via `exp_graph.mas.motifs.aggregate_motif_losses` →
  `motif_stats`) so the structural-motif credit prior is *active*, not merely set.
- **evolved** is heavy, so it is run once per `n_agents` over the whole case set
  and cached; its train/test seed split holds out the LAST seed as test, the rest
  train. The gate decision (`accepted`, `J_before`, `J_after`) and the
  pre/post held-out success are attached to every condition the evolve run
  covered.

The default arm set (when `--arms` is omitted) is `fixed select graphgen`; add
`evolved` explicitly for the full four-arm comparison.

## Metrics

For each arm, per condition, the harness reports the **mean±std** (population std,
0 for a single sample) over the grid's seeds of:

| metric | meaning |
| --- | --- |
| `success` | strict exact-match success rate (the boolean `ScoreResult.success`, averaged) |
| `partial` | graded partial-correctness in [0,1] (numeric near-miss / list / set / dict, per output type; segmented = mean per-agent quality) |
| `n_messages` | inter-agent messages delivered by the protocol runner (`result.total_messages`) |
| `n_model_calls` | LLM calls made (`result.total_model_calls`) — 0 under `--llm fake` |
| `tokens` | prompt + completion tokens (`result.total_*_tokens`) — 0 under `--llm fake` |

`success` is always strict exact-match; `partial` is the graded signal computed in
masbench (exp_graph stays untouched). The CSV carries `<metric>_mean` and
`<metric>_std` for each.

## The grid

A run sweeps the cross-product of:

- **conditions** — Silo cases selected by `--levels` (e.g. `I II`) and/or
  `--cases` (e.g. `I-01 III-21`), each at every `--agent-counts` value (e.g.
  `2 5 10`). Each `(case_id, n_agents)` pair is one condition.
- **seeds** — `--seeds` (e.g. `1 2 3 4 5`); each arm runs once per seed per
  condition (fixed also × each topology in `--fixed-topologies`).
- **arms** — `--arms` (subset of `fixed select graphgen evolved`).

So the per-condition sample size is `len(seeds)` for select/graphgen,
`len(seeds) × len(fixed_topologies)` for the fixed *breakdown* (the oracle-fixed
line collapses that to the single best topology), and one test-seed eval for
evolved.

## How to read `report.md`

`report.md` (rendered by `bench.render_report`) has:

1. A top line: **overall success (mean±std over all runs)** per arm.
2. One section per condition, headed `## <case_id> (n=<k>)  \`<case>|n<k>\``, with
   a table `| arm | success | partial | msgs | calls | tokens |`.
   - **The best arm per condition is bolded** — highest mean success, tie-broken
     by *lower* mean tokens.
   - `success` / `partial` are shown as percentages (`mean±std%`); `msgs` /
     `calls` / `tokens` as raw `mean±std`.
3. Under each table:
   - `_oracle fixed: \`<topology>\` success <m±s>%_` — the best fixed topology for
     that condition (highest mean success, tie-break lower tokens), i.e. the
     strongest hand-picked baseline the adaptive arms must beat. The full
     per-topology breakdown lives in `results.json` (`fixed_by_topology`).
   - `_evolved gate: accepted=<bool> J_before=<x> J_after=<y>_` — when the evolved
     arm ran, the held-out validation-gate decision (lower `J` is better; the gate
     commits the skill batch only if `J_after <= J_before - epsilon`).

The reading you want for the paper: per condition, does **select** / **graphgen**
/ **evolved** match or beat the **oracle fixed** line, and at what message/token
cost? And did the **evolved** gate *accept* (i.e. the self-evolution found a
held-out improvement)?

## Recommended paper-grade config

Levels I+II, agent-counts 2/5/10, seeds 1–5, all four arms, gpt-4o-mini, with the
LLM merge/init modes that make the arms actually differ. Install the `openai`
extra and export the key first:

```bash
cd masbench
export OPENAI_API_KEY=...
uv run --extra openai python -m masbench.cli bench --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels I II --agent-counts 2 5 10 --seeds 1 2 3 4 5 \
  --arms fixed select graphgen evolved \
  --fixed-topologies tree mesh_star one_peer_exponential_dag_star chain \
  --graphgen-candidates 4 \
  --llm openai --model-name gpt-4o-mini \
  --merge-mode llm_full_merge --init-mode llm_local_solve \
  --objective accuracy_first --out runs/paper
```

`--llm openai` reads `OPENAI_API_KEY` from the environment (the `openai` platform
has no default `--api-key-env`/`--base-url`, so the OpenAI SDK's standard
`OPENAI_API_KEY` + `api.openai.com` are used). Outputs land in `runs/paper/`:
`results.json`, `results.csv`, `report.md`.

For paired self-evolution verification, `scripts/verify_beats_baselines.py`
also writes an auditable `skill_banks/` tree under `--out`. Its
`manifest.json` indexes the shared empty control banks, every round's `before`,
pre-gate `candidate`, and post-gate `deployed` banks, plus the exact final bank
used for paired evaluation. Each non-empty snapshot is available both as one
`bank.json` and as one YAML file per skill. A rejected candidate is therefore
preserved for diagnosis without being mistaken for the deployed policy.
Cross-level evaluations can use explicit, disjoint `--train-cases` and
`--test-cases`; both lists are recorded with `split_mode: explicit` in the
report, avoiding any dependence on the default lexicographic holdout rule.

Offline smoke (wiring check only, no keys, no cost — see the caveats below for why
the offline numbers are not discriminative):

```bash
cd masbench
uv run python -m masbench.cli bench --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --cases I-01 --agent-counts 2 --seeds 0 \
  --arms fixed select graphgen --fixed-topologies tree chain \
  --llm fake --objective accuracy_first --out runs/bench_smoke
```

## Optional evolution hot start

`run_evolution` remains cold-start by default. `--hot-start` adds a measured
pretraining stage and a paired improve/expand stage:

1. Pretraining executes supplied fixed topologies on TRAIN. In `all_agents`
   mode it can also execute the paper's dynamic `p2p`, `broadcast`, and `sfs`
   transports. Fixed cards retain an executable `protocol_spec`; dynamic cards
   are tagged `reference-only`, so they can inform generation but can never be
   selected as a static topology.
2. Every `(case, seed)` runs a pinned `reuse` branch plus an `innovation`
   branch. Python innovation can additionally run a local `mutate` branch, so
   `mutate_and_fresh` has at most three paid runs: reuse, mutate, and fresh
   innovation. Generic `evolve_explore` is skipped while this paired branch is
   active, avoiding a duplicate novelty run.
3. Pretraining is paid once. Later rounds detect persisted `hot-start` tags and
   reuse the seed bank, while still rerunning both per-task branches. A gate
   rejection rolls back to the warm bank, not to an empty bank.

Goal-aware `auto` defaults are intentionally different:

- `all_agents` starts from exactly five primary Skills: dynamic `p2p`,
  `broadcast`, and `sfs`, plus `one_peer_exponential_dag` (the propagation
  phases without a final star sink) and `static_exponential`. Both fixed graphs
  have statically verified all-agent source coverage.
- `sink` uses gathering organizations instead: `one_peer_exponential_dag_star`,
  `mesh_star`, `star`, `chain`, `tree`, `two_stage_layer`, and
  `balanced_log_layer`; paper transports are not auto-added.

Explicit paper transports in sink mode fail fast. Hot-start portfolio members
also retain their protocol-family identity during structural deduplication: two
programs that happen to expand to the same graph at `n=2` are not the same
scaling Skill.

Each hot-start Skill stores all three learning layers:

- **code:** the canonical executable artifact lives in the discriminated
  `mode_payload`. Fixed graphs use `named_topology_skill_v1`; paper transports
  use `paper_transport_skill_v1` and their dedicated dynamic runner instead of
  pretending to be a static graph. `organization_policy` is only a legacy/index
  mirror during migration.
- **insight:** `design_insights` records an observed design principle and its
  evidence summary; `reasoning_policy` records transport/merge/submission rules.
- **evidence:** `evidence` retains per-case/per-seed observations, while
  `expected_dynamics.hot_start_evidence_summary` summarizes V/K/U/P/S. The
  dynamic paper cards remain `reference-only` for the normal static planner but
are directly executable by the hot-start reuse branch.

### Mode-specific Skill payloads and iterative updates

The SkillBank keeps one common audit envelope for evidence, insights, failures,
triggers, tradeoffs, and revision history, but executable formats are not
shared:

| planner family | canonical payload format | executable source |
| --- | --- | --- |
| fixed named topology | `named_topology_skill_v1` | named constructor + compiled `ProtocolGraphSpec` |
| SILO paper transport | `paper_transport_skill_v1` | dynamic runner descriptor |
| GraphGen | `graph_skill_v1` | free topology program when present + compiled spec |
| PhaseProgram | `phase_program_skill_v1` | complete `phase_program_v1` + compiled spec |
| PythonGenerate | `python_skill_v1` | complete Python `source_code`, SHA-256, AST/runner contract |

The discriminator prevents a Graph candidate from being merged into a Phase or
Python card even if display names coincide. Legacy cards are adapted on read;
new cards and subsequent snapshots persist the typed payload.

Both direct `SkillBank.apply_patch` and batch consolidation iteratively update
the full learning surface: executable payload, organization compatibility
index, reasoning policy, trigger, tradeoff/dynamics, insight, evidence,
counterexamples, failures/risks, hypotheses, fallback, confidence, validation
plan, tags, and update rule. Nested dictionaries merge without deleting sibling
knowledge. An executable or reasoning change bumps the minor version and writes
before/after payload and program hashes to `revision_history`; round snapshots
retain the complete prior source. Explicit `patch.update` fields take precedence
over the candidate snapshot.

Every evolution summary exposes
`skill_payload_audit.{candidate,deployed}` with counts by payload format,
payload-less generated-card violations, persisted Python source lengths/hashes,
the iterative field list, and the deliberately immutable identity fields.

```bash
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels II III --agent-counts 5 --train-seeds 1 2 --val-seeds 3 \
  --silo-eval-mode all_agents --planner-mode graph_generate \
  --hot-start --hot-start-protocols auto --hot-start-topologies auto \
  --hot-start-seed-count 1 --hot-start-innovation-mode graph_generate \
  --llm openai --model-name gpt-4o-mini --out runs/hot_start
```

Audit data is under `summary.json["hot_start"]`: resolved settings, seed Skill
ids, pretraining and branch V/K/U/P/S signals, branch outputs, calls,
tokens/messages, innovation candidate ids, and deployed innovation ids. The same
flags are available in `scripts/verify_beats_baselines.py`; its budget guard
includes the extra runs and its snapshots preserve the warm seed.

## Self-evolution v2 policies

The v2 behavior is opt-in. Historical commands retain `legacy_drop` and
`legacy_non_regression`, so existing preregistered results are not reinterpreted.

### Honest failure policy

`--failure-policy honest_v2` uses one typed classification in train, explore,
hot-start, gate, and the frozen baseline verifier:

- `algorithm_failure`: invalid generation/parse/action, coverage, budget, or
  submit-contract failure. The run remains in evidence with V/S/P zero and
  already incurred C/D/call/token cost.
- `infrastructure_failure`: provider timeout, connection timeout, or explicit
  transient network exception. Only this class may symmetrically drop a whole
  paired validation/evaluation unit.
- `harness_error`: assertion, configuration, schema/plumbing, or unknown
  exception. It aborts immediately rather than becoming experimental data.

Persisted `FailureRecord` objects contain run identity, mode/goal/worker
contract, parent/program identity, stage/type, missing Agent/source ids,
per-Agent partial values, structural signature, and artifact reference. They
forbid extra fields, so answers, ground truth, and expected outputs cannot be
stored. Stable clusters are scoped by mode + goal + worker contract + stage +
type + structural signature, deduplicated, written to the round summary, and
merged into matching Skill failure/counterexample fields. Under `honest_v2`,
GraphGen and PhaseProgram receive a bounded, answer-free
`negative_failure_context` separated from positive Skill evidence; Python hot
innovation receives the same separation through its sanitized parent context.

The frozen verifier report separately records
`algorithm_failures_by_arm`, `infrastructure_failures_by_arm`,
`harness_errors`, `dropped_infrastructure_pairs`, and
`zero_scored_algorithm_runs`.

### Strict dense ratchet

`--evolution-gate-policy strict_dense_v2` evaluates incumbent and candidate on
the exact same validation `(case, seed)` keys and persists each paired
V/K/U/P/S/stage-score/C/D sample. A candidate is accepted only when algorithm
failure rate, mean V, minimum K, mean U, and tolerated P do not regress; S or
mean dense stage score improves; and the paired stage-score bootstrap interval
does not show regression. Equal quality can pass only when at least one of C/D
falls and neither rises. Equal quality/equal cost reports
`accepted=false`, `accepted_no_change=false`, `reason=no_change`.

Infrastructure pairs are dropped symmetrically. Harness errors abort. A
rejected round exports the byte-equivalent `before` bank while retaining the
full `candidate` snapshot and failure audit. The strict controls are
`--strict-gate-min-dense-delta`, `--strict-gate-partial-tolerance`,
`--strict-gate-bootstrap-samples`, and `--strict-gate-bootstrap-seed`.

### Conservative insight association

Reuse, mutate, and fresh rows from the same pair update
`exposures/wins/losses/ties/mean_delta_stage_score` for the insight ids actually
associated with that branch. Fresh records exposure only; mutation records use
only ids explicitly returned by the accepted patch. These are labelled
`paired_association_not_causal`. Counts accumulate across rounds. After at
least three exposures, an insight with more losses than wins leaves positive
`design_insights` and becomes a `negative_constraint` risk note.

```bash
uv run python scripts/verify_beats_baselines.py \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels II III --n-agents 5 --rounds 5 \
  --train-seeds 1 2 --val-seeds 3 --eval-seeds 11 12 \
  --silo-eval-mode all_agents --evolved-mode python_generate \
  --hot-start --hot-start-protocols auto --hot-start-topologies auto \
  --hot-start-innovation-mode python_generate \
  --python-innovation-strategy mutate_and_fresh \
  --failure-policy honest_v2 --evolution-gate-policy strict_dense_v2 \
  --llm fake --model-name fake --out runs/v2_offline_smoke
```

This command is a wiring check only. A scientific comparison requires a real
model, disjoint II/III train/validation/test cases and seeds, and a preregistered
budget. The repository test/smoke path never calls a paid LLM.

For an explicit three-way scientific split, pass `--train-cases`, `--val-cases`,
and `--test-cases`. The verifier forwards the validation set separately so
`run_evolution` does not carve cases out of TRAIN internally. Omitting
`--val-cases` preserves the legacy automatic train/validation split.

**Contamination boundary:** hot start deliberately supplies fixed/paper
structural knowledge, so it is not clean GraphGen. The verifier writes
`clean_run=false`; generated records write `clean_graphgen=false` (or
`clean_programgen=false`). Structural reference names alone are narrowly allowed
by the prompt audit, while answer/expected-output/ground-truth tokens remain
forbidden. A hot-start result cannot support a claim that GraphGen discovered a
paper topology without prior structural information.

## Honest caveats

These are real limitations of the *current* harness; the paper write-up must
respect them.

1. **Offline determinism makes arm-success non-discriminative.** With `--llm
   fake` every run is deterministic and Silo's offline path is *topology-invariant
   on success* — a case is solved (loss 0) or not (loss 1) the same way for every
   topology. The offline table is well-formed and the math is real, but the arm
   comparison only becomes scientifically meaningful with a **real LLM** (or
   multi-seed runs that genuinely differ per topology). Use offline only to verify
   wiring.
2. **The fake LLM cannot run the LLM merge/init modes.** `--llm fake` supports
   only `--merge-mode deterministic` / `--init-mode deterministic`; the
   `llm_full_merge` / `llm_local_solve` modes emit prompts it cannot parse, so the
   harness **fails fast** with an actionable message (`bench.run_benchmark`'s
   guard). The paper-grade modes therefore require a real `--llm` provider.
3. **Segmented tasks need a real LLM for per-agent segments.** Segmented Silo
   cases give each agent its own `expected_output`; grading reads each agent's
   final belief. Offline the soldiers do not actually solve their distinct
   segments, so segmented conditions are only meaningful with a real LLM.
4. **The motif prior only fires with `--graphgen-candidates > 1`.** The
   structural-motif credit prior changes the graphgen pick only when more than one
   candidate DAG survives validation; with a single surviving candidate it is
   inert (selection unchanged). The default is 4; keep it >1 to exercise the
   prior. Offline, the fallback DAG is a fixed named topology, so the prior's
   effect on the *generated* structure is only observable with a real LLM that
   produces multiple valid candidates.
5. **The evolve gate uses a synthetic held-out set offline.** Because offline Silo
   rows are topology-invariant on success, `masbench evolve` / the evolved arm
   inject a small synthetic multi-topology held-out set + a baseline incumbent so
   the gate decision is real and non-degenerate (`evolve.accepting_held_out_rows`,
   `INCUMBENT_BASELINE_TOPOLOGY`). With a real LLM the held-out Silo runs differ by
   topology, so pass `--no-synthetic-held-out` to `masbench evolve` to score the
   gate purely on real evidence. (The `bench` harness's evolved arm auto-selects:
   synthetic offline, real-evidence when `--llm` is a real provider.)
6. **Only Silo-Bench is integrated.** `--benchmark` currently supports
   `silo_bench` only. REALM-Bench and M-APPLE-OS are **not** integrated (a separate
   phase; tracked as follow-up #8).
7. **Per-seed loss variance (`std_primary_loss`) is not recorded** in the
   evolution evidence rows (follow-up #4, intentionally deferred); the uncertainty
   penalty therefore uses the within-condition std the gate can compute, not a
   per-seed std.

## Robust large runs (timeout / checkpoint / parallel)

A real-LLM paper grid (`--levels I II --agent-counts 2 5 10 --seeds 1..5 --arms
fixed select graphgen evolved`) is thousands of provider calls. Three flags make
it fast, crash-safe, and immune to a single hung call (the failure mode that once
froze a run for 90 min on one stalled socket):

| flag | default | what it does |
| --- | --- | --- |
| `--workers N` | `1` | Run independent grid units `(arm, case, n, seed[, topology])` concurrently via a `ThreadPoolExecutor`. LLM calls are I/O-bound (they release the GIL), so wall-clock drops ~linearly. `N=1` is the unchanged sequential path. |
| `--max-parallel-agents N` | `5` | Run independent Agent calls from the same logical round concurrently. Every round still reads one frozen prior-round snapshot and waits for the entire batch before advancing. ProtocolRunner, all three SILO paper transports, and Python `message_only_v2` preserve deterministic Agent-order commits and record the actual batch width. |
| `--request-timeout S` | `90.0` | Hard per-request wall-clock guard (`masbench.llm.timeout.TimeoutLLMClient`, a daemon-thread `join(timeout)` that abandons a hung call). A stalled call raises `LLMTimeoutError`, recorded as a failed run, and the grid continues. Also applies to `run`/`run-suite`/`evolve`. |
| `--llm-timeout-attempts N` | `2` | Bounded attempts for a request that reaches the wall-clock timeout. Each attempt has its own `--request-timeout`; raise this only for a deliberately patient science run. |
| `--require-complete-runs` | off | Abort at the last completed verifier checkpoint instead of dropping an infrastructure-failed TRAIN/gate/TEST unit. This prevents a reduced sample from being presented as the requested experiment. |
| `--python-execution-timeout S` | auto | Whole-child guard for PythonGenerate. Auto derives a budget from rounds, Agent waves, and `--request-timeout`; it is no longer the invalid 30-second fixed default. |
| `--resume` | off | `bench` appends every finished run to `runs/<out>/runs.jsonl` immediately. The paired verifier atomically writes `run_checkpoint.json` after every fully deployed evolution round and reloads the last deployed SkillBank/motif state. Re-running the SAME command with `--resume` skips completed training rounds; its frozen selection and TEST stages are deliberately recomputed. |
| `--require-all-submissions` | off | In `all_agents` verifier runs, require one non-null answer from every Agent. Python `message_only_v2` uses its synchronized runtime barrier; paper protocols recover only missing submitters after their normal rounds; fixed topologies explicitly query every Agent. `--final-submission-retries` permits format-only retries and never invents an answer. |

Semantics under concurrency (correctness preserved):
- **Per-run isolation:** every unit is wrapped; any exception (incl. a timeout)
  becomes a `success=False` record with `extra["error"]` and the grid never aborts.
  `KeyboardInterrupt`/`SystemExit` still propagate (finished units are on disk).
- **Checkpoint append is lock-guarded** → exactly one `runs.jsonl` line per unique
  run-key, no double-counting under `--workers > 1`.
- **`graphgen` motif prior:** under `--workers > 1` the cross-run motif evidence is
  snapshotted once before dispatch (the sequential incremental feed needs ordering);
  per-run correctness is unaffected — only the best-effort prior differs.
- **`evolved` arm:** the heavy `run_evolution` runs sequentially, once per
  `n_agents`, *before* the per-instance eval units are dispatched to the pool
  (never two evolutions at once).
- **Determinism:** aggregates are order-independent, so `--workers 1` and
  `--workers 8` produce identical per-condition/overall means.
- **Provider concurrency:** the approximate upper bound is `workers *
  max_parallel_agents`. Keep that product within the provider's rate-limit and
  connection budget; for n=5, `--workers 2 --max-parallel-agents 5` is a safer
  starting point than launching forty simultaneous requests.

Recommended real-LLM invocation: start with `--workers 2
--max-parallel-agents 5 --request-timeout 120`; increase outer workers only
after observing provider headroom. If it dies, re-run the identical command
with `--resume`.

For a long paired verifier run, keep the `--out` directory and every scientific
argument unchanged when resuming. `checkpoint_config.json` is the immutable
argument fingerprint, `run_checkpoint.json` names the last complete deployed
round, and `skill_banks/round_NN/{before,candidate,deployed}` preserves each
decision. A mismatched resume fails before any paid call. The checkpoint is not
permission to accept partial Agent output: with `--require-all-submissions`, a
missing or null answer is an explicit failed run.

## What is wired vs. activation-pending

- **Wired and exercised offline** (by `tests/test_bench.py`): the four arms, the
  per-condition mean±std aggregation, oracle-fixed selection, the
  fail-fast guard, the evolved-arm gate plumbing, and the `results.json` /
  `results.csv` / `report.md` writers. The offline smoke runs the whole harness
  end to end.
- **Wired, activation needs a real LLM** (offline runs it but the result is not
  discriminative): graphgen DAG *generation* (offline falls back to a fixed
  topology), the LLM merge/init belief modes, segmented per-agent solving, and the
  real-evidence (`--no-synthetic-held-out`) evolve gate.
- **Motif `motif_stats` feeding from prior runs.** Within a single `bench`
  invocation the graphgen arm accumulates motif evidence across conditions and
  feeds it forward, so the prior is *active* (not merely configured). It is keyed
  by the selected topology offline (the fallback is a named topology), so its
  effect on truly *generated* DAGs is an activation that surfaces with a real LLM.
- **Not wired:** additional benchmarks (REALM-Bench / M-APPLE-OS) and
  `std_primary_loss` evidence recording — see caveats 6 and 7.

## Contamination notice (2026-07-11): pre-leakage-fix results

> **热警告 / Contamination warning.** 本文件上方的既有结论与所有早于
> 2026-07-11 泄漏修复的实验产物（包括
> `runs/graphgen_vs_fixed_mixed_train.41DNFR` 及此前一切 bench/evolve/verify
> 运行）在以下已修复缺陷下产生，一律标记为 **contaminated**，不得用于新的
> 科学结论（保留仅供历史审计，不删除、不改写）：
>
> 1. **答案泄漏**：`meta.expected_outputs` 经 `TASK_CONTEXT_JSON` 进入模型可见
>    上下文（顶层黑名单挡不住嵌套字段）。
> 2. **拓扑泄漏**：Silo `task_description` 的 “Communication Protocol” 小节
>    （含标注拓扑）与 `metadata.optimal_topology/optimal_message_count/`
>    `theoretical_complexity` 均可达模型上下文。
> 3. **指数图注入**：graphgen 架构师提示词的 `required_json_shape` 示例含
>    `distance-doubling` / `pow2(r)` / `ceil_log2` 可复制公式。
> 4. **fallback 污染**：graphgen 失败会静默回退到具名拓扑
>    （accuracy_first 默认 `one_peer_exponential_dag_star`）并计入 graphgen 臂。
> 5. **审计缺失**：架构师调用产物写入 `TemporaryDirectory` 后即删除。
>
> 自本日期起，`results.json` / verify 报告携带 `silo_eval_mode` 与
> `clean_run` 字段；缺这两个字段的产物即属 contaminated 世代。旧 SkillBank
> 卡片缺 `provenance`，被 clean GraphGen 检索一律排除（文件保留）。
> 详见 `docs/leakage_and_eval_modes.md`。
