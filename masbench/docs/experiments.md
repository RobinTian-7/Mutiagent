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
| `--request-timeout S` | `90.0` | Hard per-request wall-clock guard (`masbench.llm.timeout.TimeoutLLMClient`, a daemon-thread `join(timeout)` that abandons a hung call). A stalled call raises `LLMTimeoutError`, recorded as a failed run, and the grid continues. Also applies to `run`/`run-suite`/`evolve`. |
| `--resume` | off | `bench` appends every finished run to `runs/<out>/runs.jsonl` immediately. Re-running the SAME command with `--resume` loads that log, skips completed run-keys, and finishes the rest — so a crash/Ctrl-C loses nothing. |

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

Recommended real-LLM invocation: add `--workers 8 --request-timeout 90` to the
paper command; if it dies, re-run the identical command with `--resume`.

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
