# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 package for multi-agent expressional graph experiments. Source code lives under `src/`, grouped by responsibility: `agents/`, `routing/`, `topology/`, `reconstruction/`, `simulation/`, `schemas/`, `analysis/`, `interventions/`, and `tracing/`. Tests live in `tests/` and mirror the main behavior areas, for example `tests/test_routing.py` and `tests/test_topology.py`. Configuration files belong in `configs/`, runnable examples in `examples/`, and longer design notes in `docs/`. The local `files/` directory is ignored and should be treated as private reference material or large assets.

## Build, Test, and Development Commands

Create and activate a local environment before development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the full test suite with:

```bash
pytest
```

Run example workflows with:

```bash
python examples/run_demo.py
python examples/compare_dti.py
```

Use `pip install -e ".[analysis]"` when working on plotting or numerical analysis tools.

## Coding Style & Naming Conventions

Use 4-space indentation, Python type hints, and small modules with clear data flow. Prefer descriptive snake_case for functions, variables, files, and test names. Keep Pydantic schema definitions in `src/schemas/` and avoid duplicating model shapes in feature modules. No formatter or linter is currently configured in `pyproject.toml`, so keep changes consistent with the surrounding code and run tests before committing.

## Testing Guidelines

The project uses `pytest`; async tests are supported through `pytest-asyncio` with `asyncio_mode = "auto"`. Add tests under `tests/` using the `test_*.py` filename pattern and `test_*` function names. Cover new routing, topology, reconstruction, schema, and intervention behavior with focused unit tests. For user-facing examples or workflows, add or update a smoke test when practical.

## Commit & Pull Request Guidelines

Current history uses short imperative commit subjects such as `Add gitignore`. Follow that style: keep the first line concise and describe the observable change. For pull requests, include a brief summary, the tests run, and any configuration or data assumptions. Link related issues when available. Do not include virtual environments, caches, `.env` files, `examples/output/`, or `files/` contents.

## Agent-Specific Instructions

Respect the existing module boundaries before adding abstractions. Keep generated outputs out of source control unless they are intentional fixtures. When modifying behavior tied to the paper reproduction, update `docs/paper_to_code_mapping.md` if the mapping changes.
