# masbench

Clean multi-agent-system benchmark pipeline. Reuses the `exp_graph` engine; adds
a normalized benchmark interface, a Silo-Bench adapter, and a CLI.

## Layout
- `src/masbench/core` — instance, config, scoring, the `BenchmarkTaskAdapter` bridge
- `src/masbench/adapters/silo_bench.py` — Silo-Bench loader
- `src/masbench/adapters/silo_protocol.py` — Silo-Bench behind the QueenBee protocol engine
- `src/masbench/engine.py` — runs an instance through `SynchronousRunner` (planner-OFF) or the QueenBee planner (`--planner`)
- `src/masbench/evolve.py` — the gated QueenBee self-evolution loop (`run_evolution`)
- `src/masbench/cli.py` — `run`, `run-suite`, `report`, `evolve`

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

Offline (`--llm fake`) the emperor still emits deterministic fake DAG candidates
that compile to valid specs; on junk it validates/repairs and ultimately falls
back to a fixed operator topology, so the run never crashes without an API key:
```bash
cd masbench
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 \
  --planner --planner-mode graph_generate --llm fake --objective accuracy_first
```

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
- Plan 4 Task 1 (done): `--planner-mode graph_generate` wires the LLM temporal-DAG-GENERATING
  planner (`plan_free_graph`) into the `--planner` path, so the FULL QueenBee (the emperor
  invents a bespoke communication DAG) runs on Silo-Bench. Offline-verifiable with `--llm fake`.
- Suites: exp_graph 237 passed, 1 skipped; masbench 40 passed.
