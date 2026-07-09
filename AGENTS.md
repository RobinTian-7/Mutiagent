# Repository Guidelines

## Project Structure & Module Organization

Two Python 3.11 packages, both `src/`-layout, living side by side at the repo
root (this sibling relationship is load-bearing — see README "invariants"):

- `exp-graph/` — the `exp_graph` engine: protocol runner, QueenBee planner and
  free-graph generation, skill bank + self-evolution machinery, LLM clients,
  task adapters. Tests in `exp-graph/tests/`.
- `masbench/` — the `masbench` benchmark framework on top of `exp_graph`:
  benchmark adapters (Silo-Bench via the `masbench/third_party/acl26-silo-bench`
  submodule, JSSP), the run/evolve/bench/curve harnesses and the CLI. Tests in
  `masbench/tests/`.
- `docs/superpowers/` — cross-package design plans/specs (masbench plans 1–5).
- `archive/` — frozen history (legacy prototype, vendored references, lab
  records). Never import from it, never "fix" code inside it.

## Build, Test, and Development Commands

Each package manages its own environment with `uv` (editable cross-dependency
`masbench -> ../exp-graph` is declared in `masbench/pyproject.toml`):

```bash
git submodule update --init masbench/third_party/acl26-silo-bench
cd masbench   && uv run --extra dev python -m pytest -q
cd exp-graph  && uv run --extra dev python -m pytest -q
```

masbench commands run from `masbench/` (default `--benchmarks-dir` is relative
to it); see README for the offline Silo smoke commands. Everything must stay
runnable with `--llm fake` (offline, deterministic, no keys) — keep that path
green when changing the engine or adapters.

## Coding Style & Naming Conventions

4-space indentation, type hints, Pydantic models for shared shapes
(`exp_graph.mas.schemas`, `exp_graph.agents.schemas`). Descriptive snake_case
names. Docstrings in this codebase explain *why* (design rationale, honesty
caveats) — keep that habit. No formatter/linter is configured; match the
surrounding code.

## Testing Guidelines

`pytest` per package, `test_*.py` / `test_*` naming. The suites are
offline-only (no API keys, no network): fake-LLM clients and synthetic
fixtures. Cover new planner/runner/adapter/evolution behavior with focused
unit tests, and extend the offline smoke path when adding a CLI surface.

## Commit & Pull Request Guidelines

Short imperative commit subjects (`Add ...`, `Fix ...`), body explaining the
observable change and any measurement it is based on. PRs: summary, tests run,
config/data assumptions. Never commit run outputs — `runs/` and `*_results/`
are gitignored; experiment artifacts belong outside the repo (or, for frozen
scientific ledgers, under `archive/` by explicit decision).

## Agent-Specific Instructions

Do not move `exp-graph/` or `masbench/`, rename their packages, or relocate
the Silo submodule path — imports and file-relative lookups depend on them.
Respect the offline-honesty design: deterministic fake-LLM paths must not be
made to fabricate success. When changing self-evolution behavior, update the
relevant doc in `masbench/docs/` (the reports there are preregistered — do not
rewrite conclusions casually).
