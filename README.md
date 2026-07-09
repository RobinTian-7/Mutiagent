# QueenBee lab — temporal-DAG planner, Silo-Bench, self-evolution

Clean mainline for the QueenBee experiments: an emperor LLM that *selects or
invents* the communication structure (a temporal DAG) for a multi-agent system,
evaluated on Silo-Bench (and JSSP), with a held-out-gated self-evolution loop.
Forked from the `selfevolve-lab` branch with the historical prototype and
committed experiment outputs moved out of the way (see `archive/` and the
restructure commit).

## Layout

| path | what it is |
| --- | --- |
| `exp-graph/` | The engine (`exp_graph` package): `runner/protocol.py` (generalized ProtocolRunner), `mas/` (EmperorPlanner, `graph_generation.plan_free_graph`, skill bank, evolution/consolidation/motifs), `protocols/` (schedules + graph specs), `llm/` (provider clients, fake client, retry/timeout), `tasks/` (Count-Frequency + generic protocol task adapters). Own tests/configs/scripts. |
| `masbench/` | The benchmark framework (`masbench` package) reusing the engine: `adapters/` (Silo-Bench, JSSP, protocol + scoring bridges), `engine.py` (run one instance: fixed / planner select / graph_generate), `evolve.py` (gated self-evolution loop), `bench.py` (paper-grade arm comparison), `curve.py` (learning curves), `cli.py` (`run`, `run-suite`, `report`, `evolve`, `bench`, `curve`), `scripts/full_cluster_eval.py` (cross-difficulty eval on a local OpenAI-compatible endpoint). |
| `masbench/third_party/acl26-silo-bench` | Git **submodule** with the Silo-Bench data + official metrics. Required for anything Silo. |
| `docs/superpowers/` | Cross-package design history: masbench plans 1–5 and the pipeline spec. |
| `archive/` | Frozen history (legacy prototype, reference repros, vendored code, lab records). Nothing imports from it; see `archive/README.md`. |

Two invariants the code relies on — keep `exp-graph/` and `masbench/` as
sibling directories at the repo root:

- `masbench/__init__.py` falls back to `<repo>/exp-graph/src` on `sys.path`,
  and `masbench/pyproject.toml` installs `exp-graph` editable from
  `../exp-graph`.
- `masbench/src/masbench/adapters/silo_scoring.py` locates Silo's official
  metrics at `masbench/third_party/acl26-silo-bench/` relative to the package.

## Setup

```bash
git submodule update --init masbench/third_party/acl26-silo-bench   # Silo data
cd masbench
uv run --extra dev python -m pytest -q        # offline, no API keys
cd ../exp-graph
uv run --extra dev python -m pytest -q
```

## Silo-Bench smoke (offline, no keys, no cost)

All masbench commands run from `masbench/` (the default `--benchmarks-dir` is
relative to it):

```bash
cd masbench
uv run python -m masbench.cli run-suite --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels I --topology mesh --llm fake --out runs/smoke
uv run python -m masbench.cli report --run-dir runs/smoke
```

Planner / evolution / paper-harness smokes (same offline caveats as
`masbench/README.md` — offline success is topology-invariant, use a real LLM
for discriminative comparisons):

```bash
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 --planner --planner-mode graph_generate --llm fake
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --cases I-01 III-21 --agent-counts 2 --objective accuracy_first \
  --llm fake --out runs/evolve
uv run python -m masbench.cli bench --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --cases I-01 --agent-counts 2 --seeds 0 \
  --arms fixed select graphgen --fixed-topologies tree chain \
  --llm fake --objective accuracy_first --out runs/bench_smoke
```

Real-LLM usage, the four-arm paper harness, robustness flags
(`--workers/--request-timeout/--resume`) and honest caveats:
`masbench/README.md` and `masbench/docs/experiments.md`. Evidence reports and
preregistrations for the self-evolution studies live in `masbench/docs/`
(their raw ledgers in `archive/lab_records/`).

Run outputs are never committed: `runs/` and `*_results/` are gitignored.
