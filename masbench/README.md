# masbench

Clean multi-agent-system benchmark pipeline. Reuses the `exp_graph` engine; adds
a normalized benchmark interface, a Silo-Bench adapter, and a CLI.

## Layout
- `src/masbench/core` — instance, config, scoring, the `BenchmarkTaskAdapter` bridge
- `src/masbench/adapters/silo_bench.py` — Silo-Bench loader
- `src/masbench/adapters/silo_protocol.py` — Silo-Bench behind the QueenBee protocol engine
- `src/masbench/engine.py` — runs an instance through `SynchronousRunner` (planner-OFF) or the QueenBee planner (`--planner`)
- `src/masbench/evolve.py` — the gated QueenBee self-evolution loop (`run_evolution`)
- `src/masbench/bench.py` — the paper-grade arm-comparison harness (`run_benchmark`)
- `src/masbench/cli.py` — `run`, `run-suite`, `report`, `evolve`, `bench`

## Setup
```bash
git submodule update --init masbench/third_party/acl26-silo-bench   # Silo-Bench data
cd masbench
uv run --extra dev python -m pytest -v                             # offline tests, no API keys
```

## Offline smoke (no API keys, no cost)
```bash
cd masbench
uv run python -m masbench.cli run-suite --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels I --topology mesh --llm fake --out runs/smoke
uv run python -m masbench.cli report --run-dir runs/smoke
```
The fake client only solves associative-reduce cases (e.g. I-01 Global Max);
other tasks run end-to-end but score 0 offline. Use a real LLM for those.

## Real LLM run (uses your provider keys)
```bash
cd masbench
export DASHSCOPE_API_KEY=...    # or DEEPSEEK_API_KEY, etc.
uv run python -m masbench.cli run-suite --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels I --agent-counts 2 --topology one_peer_exponential \
  --llm dashscope --model-name qwen-flash --api-key-env DASHSCOPE_API_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --out runs/silo_real
uv run python -m masbench.cli report --run-dir runs/silo_real
```

## Planner (QueenBee on Silo)
`--planner` routes an instance through the QueenBee planner + the generalized
`ProtocolRunner` instead of the planner-OFF `SynchronousRunner`. `--planner-mode`
picks how the communication structure is chosen:

- `topology_select` (default): the emperor picks a named topology (skill-bank
  fallback `default_topology_for_objective`). Unchanged Plan-3 behavior.
- `graph_generate`: the **FULL QueenBee** — the emperor LLM invents a bespoke
  *temporal communication DAG* from scratch (`plan_free_graph`), and its
  generated `protocol_spec` drives the runner. Each `ScoreResult.extra` records
  `planner_mode` and (for `graph_generate`) `generated_steps`.
- `program_generate`: an independent restricted planner. The emperor emits only
  typed `phase_program_v1` stages; a deterministic compiler expands edges,
  enforces coverage/budgets, and performs bounded counterexample repair. The
  original `graph_generate` path remains available and unchanged.
- `python_generate`: a third independent generated path. The architect emits a
  complete `program.py` that calls the existing `create_llm_client` /
  `LLMClient.complete` API directly. A fail-closed AST/API/taint validator,
  fake-canary dry run, metered child process, and stdout/accounting checks run
  before scoring. It does not compile to `ProtocolGraphSpec` and does not reuse
  either generated graph DSL.

Offline (`--llm fake`) all three generated modes emit deterministic honest smoke
candidates. Invalid real-model output is recorded as generation failure rather
than silently replaced by a named topology:
```bash
cd masbench
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 \
  --planner --planner-mode graph_generate --llm fake --objective accuracy_first
```

PythonGen offline demo and one-instance smoke:
```bash
cd masbench
uv run python scripts/demo_python_generate.py
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 --max-rounds 2 \
  --planner --planner-mode python_generate --llm fake --model-name fake
```
The fake workers deliberately return no solution; this validates execution,
state retention, delayed delivery, no-send, metering, and artifacts only. See
[`docs/python_generate.md`](docs/python_generate.md) for the contract and the
static/runtime isolation boundary.

Real DAG generation needs a real LLM (the emperor designs the topology, soldiers
execute it):
```bash
cd masbench
export OPENAI_API_KEY=...
uv run python -m masbench.cli run-suite --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels I --agent-counts 2 \
  --planner --planner-mode graph_generate \
  --llm openai --model-name gpt-4o-mini --api-key-env OPENAI_API_KEY \
  --objective accuracy_first --out runs/silo_graphgen
uv run python -m masbench.cli report --run-dir runs/silo_graphgen
```

## Evolve (QueenBee self-evolution on Silo)
`masbench evolve` runs the improved QueenBee self-evolution loop end-to-end on
Silo-Bench: it splits the selected instances into TRAIN/HELD-OUT, runs each
through the planner + `ProtocolRunner`, turns every run into an aggregate row
(`summary_to_aggregate_row`), has the ResultAnalyst minister propose skill
patches, and applies them through the **held-out validation gate** — committing
the batch only if it does not regress the held-out objective `J_val`. The planner
requests carry the Plan-3 improvement knobs (uncertainty-aware selection +
counterexample veto + risk floor), so the loop exercises improvements D+E+F. See
`docs/self_evolution_changes.md` for how each of the five improvements maps to its
`exp_graph` module and how it differs from the paper.

### Offline (no API keys, no cost)
```bash
cd masbench
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --cases I-01 III-21 --agent-counts 2 \
  --objective accuracy_first --llm fake --out runs/evolve
```
Prints the real gate decision and the before/after held-out objective, e.g.:
```
gate accepted=True J_before=1.000000 J_after=0.500000 epsilon=0.000000
train=['I-01'] (rows=3, success=1.000) | val=['III-21'] (rows=3, success=0.000)
knobs={'uncertainty_weight': 1.0, 'min_seeds': 1, 'enforce_avoid_veto': True, 'risk_weight': 0.5, 'max_acceptable_loss': 0.99} | skill_bank 1->4 mutated=True
```
The full result (gate `j_before`/`j_after`, accept/reject, per-set success
rates, the activated knobs, and the resulting skill ids) is written to
`runs/evolve/summary.json`. Because Silo's deterministic offline path is
*topology-invariant on success* (a fake-LLM run of a case solves it or not, the
same way for every topology), the offline command injects a small synthetic
multi-topology held-out set so the gate's accept/reject is a real, non-degenerate
decision; the gate arithmetic itself is real. Pass `--no-synthetic-held-out` to
score the gate purely on the real held-out Silo runs (intended for the real-LLM
path below).

Evolution can optionally warm-start from measured fixed/paper protocols and run
paired reuse plus fresh-creation branches for every TRAIN pair:

```bash
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels II III --agent-counts 5 --train-seeds 1 2 --val-seeds 3 \
  --silo-eval-mode all_agents --planner-mode graph_generate \
  --hot-start --hot-start-protocols auto --hot-start-topologies auto \
  --hot-start-innovation-mode graph_generate --llm fake --out runs/hot-start
```

This mode is deliberately **not clean GraphGen** because structural references
are supplied. Its separate cost, seed cards, parent selections, and innovation
outputs are recorded under `summary.json["hot_start"]`; see
`docs/experiments.md` for exact semantics and the contamination boundary.
In `all_agents` mode, `auto` creates the five-Skill portfolio
`p2p,broadcast,sfs,one_peer_exponential_dag,static_exponential`; sink mode uses
the separate gather/star/chain/tree/layer fixed portfolio. Every seeded card
stores a mode-specific typed executable payload, structured insights, and
measured evidence. Graph, phase DSL, Python source, fixed topology, and paper
transport payloads use distinct schemas; Python cards preserve full source.

### Real LLM (uses your provider keys)
```bash
cd masbench
export DASHSCOPE_API_KEY=...
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels I --agent-counts 2 \
  --objective accuracy_first \
  --merge-mode llm_full_merge --init-mode llm_local_solve \
  --llm dashscope --model-name qwen-flash --api-key-env DASHSCOPE_API_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --no-synthetic-held-out --out runs/evolve_real
```
With a real LLM the held-out Silo runs differ by topology, so the gate can decide
on real evidence alone (`--no-synthetic-held-out`).

## Paper-grade experiments (masbench bench)
`masbench bench` is the paper-grade harness: it compares **communication-structure
policies ("arms")** over a grid of Silo-Bench conditions `(case_id, n_agents)` ×
seeds and emits a Table-1-style comparison. Every arm routes through the SAME
`ProtocolRunner` + the same masbench scorer, so the metrics are directly
comparable; the harness only decides *which structure each arm uses* and then
aggregates. The arms:

- **fixed** — planner-OFF baselines: each topology in `--fixed-topologies` is
  forced through the protocol runner. The per-condition *best* fixed topology is
  reported as the **oracle fixed** baseline (the rest are kept as a breakdown).
- **select** — QueenBee `topology_select` (`--planner`, picks a named topology).
- **graphgen** — QueenBee `graph_generate` (the emperor LLM invents a temporal
  DAG). `--graphgen-candidates` is >1 by default so the structural-motif prior
  can matter; motif evidence accumulated from earlier conditions is fed back in.
- **programgen** — independent QueenBee `program_generate`; the emperor composes
  restricted phases and the compiler creates the executable schedule.
- **pycodegen** — non-default independent `python_generate`; the architect emits
  validated full Python and a Python-only subprocess executes it with an
  authoritative Worker-call ledger.
- **evolved** — the gated self-evolution loop (`masbench evolve`) run ONCE per
  agent-count on the train seeds, then its post-evolution topology selection is
  evaluated on the held-out/test seeds (the gate decision is attached).

**Outputs** (under `--out`): `results.json` (raw per-run records + per-condition
and overall aggregates), `results.csv` (one row per condition × arm with mean/std
columns), and `report.md` (a markdown table per condition — `arm | success |
partial | msgs | calls | tokens` — with the best arm bolded, an oracle-fixed
line, and a top overall-success summary). Metrics are success (exact-match rate),
partial ([0,1] graded), n_messages, n_model_calls, tokens, each as **mean±std**
per condition.

### Offline smoke (no API keys, no cost)
```bash
cd masbench
uv run python -m masbench.cli bench --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --cases I-01 --agent-counts 2 --seeds 0 \
  --arms graphgen programgen pycodegen \
  --llm fake --objective accuracy_first --out runs/bench_smoke
```
The fake LLM is deterministic and only supports `--merge-mode deterministic` /
`--init-mode deterministic` (it cannot run `llm_full_merge` / `llm_local_solve`
and the harness **fails fast** with an actionable message if you try). Silo's
offline path is also topology-invariant *on success*, so the offline table is
well-formed but the arm comparison is **not** discriminative — use a real LLM for
a scientifically meaningful comparison.

### Real-LLM reproduce (gpt-4o-mini)
Install the `openai` extra and export your key, then run all four arms with the
LLM merge/init modes (this is what makes the arms differ):
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
  --workers 8 --request-timeout 90 \
  --objective accuracy_first --out runs/paper
```
`--llm openai` reads `OPENAI_API_KEY` from the environment (no `--api-key-env` /
`--base-url` needed). See `docs/experiments.md` for the full experiment design,
the recommended paper-grade config, and the honest caveats.

**Robust large runs (timeout / checkpoint / parallel).** A real-LLM grid is big,
I/O-bound, and a single stalled provider call must not freeze or lose it. Three
flags make it safe + fast:
- `--workers N` — run the (independent) grid units concurrently (LLM calls are
  I/O-bound, so threads give near-linear speedup). `N=1` (default) is the original
  sequential path. Start with `--workers 8`.
- `--request-timeout S` — hard per-call wall-clock guard (default 90s); a hung
  request fails fast as a recorded failure instead of blocking everything (also
  applies to `run` / `run-suite` / `evolve`).
- `--resume` — `bench` writes every run to `runs/<out>/runs.jsonl` as it finishes,
  so a crash/Ctrl-C loses nothing; re-run the SAME command with `--resume` to skip
  completed `(arm,case,n,seed,topology)` units and finish the rest.

So if a run dies mid-way: just re-run with `--resume` added.

## Status
- Plan 1 (done): planner-OFF, exact-match success rate on Silo-Bench via `SynchronousRunner`.
- Plan 2 (done): exp_graph's protocol engine is now task-agnostic — `ProtocolTaskAdapter` +
  generic vote aggregation + generic step metrics. CF stays byte-identical (delegates to
  cf_final/cf_protocol); a non-CF `global_max` task runs end-to-end through `ProtocolRunner`.
- Plan 3 (done): `SiloProtocolAdapter` + `--planner` wire the QueenBee temporal-DAG pipeline
  onto Silo-Bench; the self-evolution overhaul is implemented and activated — held-out
  validation gate, uncertainty-aware/veto/floor selection, motif-level credit, and insight
  falsification — and `masbench evolve` runs the whole gated loop end-to-end (offline-verifiable
  with `--llm fake`). See `docs/self_evolution_changes.md`.
- Plan 4 (done): the FULL temporal-DAG QueenBee + the paper-grade experiment harness.
  - **T1** `--planner-mode graph_generate` wires the LLM temporal-DAG-GENERATING planner
    (`plan_free_graph`) into `--planner`, so the emperor invents a bespoke communication DAG
    on Silo-Bench (offline-verifiable with `--llm fake`, which validates/repairs/falls back).
  - **T2** graded partial-correctness scoring (`ScoreResult.partial` in [0,1] per output type:
    numeric / list / set / dict), with `success` kept strictly exact-match.
  - **T3** segmented Silo tasks scored per-agent (each agent vs. its own `expected_output`;
    success = all agents correct, partial = mean per-agent quality).
  - **T4** `task_family` threading so Silo skills are tagged `silo` natively in evolution
    (default `count_frequency` → CF byte-identical).
  - **T5** the structural-motif credit prior is activated in graph-candidate scoring
    (opt-in, default-off; only changes the pick when >1 candidate survives).
  - **T6** the `masbench bench` harness (arms fixed/select/graphgen/evolved →
    `results.json`/`results.csv` + `report.md`). See "Paper-grade experiments" above
    and `docs/experiments.md`.
- Suites: exp_graph 248 passed, 1 skipped; masbench 77 passed.
