# masbench

Clean multi-agent-system benchmark pipeline. Reuses the `exp_graph` engine; adds
a normalized benchmark interface, a Silo-Bench adapter, and a CLI.

## Layout
- `src/masbench/core` — instance, config, scoring, the `BenchmarkTaskAdapter` bridge
- `src/masbench/adapters/silo_bench.py` — Silo-Bench loader
- `src/masbench/engine.py` — runs an instance through `SynchronousRunner` (planner-OFF)
- `src/masbench/cli.py` — `run`, `run-suite`, `report`

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

## Status
- Plan 1 (this): planner-OFF, exact-match success rate.
- Plan 2: generic protocol runner (temporal-DAG execution on any benchmark).
- Plan 3: full QueenBee planner + skill-evolution on Silo-Bench; official partial-correctness scorers.
