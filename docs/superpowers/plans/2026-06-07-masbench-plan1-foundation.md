# masbench Plan 1: Foundation + Planner-OFF Silo-Bench Runnable Milestone

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a clean `masbench` package that runs the Silo-Bench benchmark end-to-end through the existing task-agnostic `SynchronousRunner` (planner-OFF), scored by exact-match success rate, with an offline fake-LLM smoke path and a documented real-LLM run command.

**Architecture:** `masbench` is a new top-level package that **reuses the `exp_graph` engine** (does not rewrite it). It defines a normalized `BenchmarkInstance`, a generic `BenchmarkTaskAdapter` implementing the 6-method `exp_graph.tasks.base.TaskAdapter` interface, a Silo-Bench loader, a benchmark-aware fake LLM client (the stock `FakeLLMClient` is hardwired to CF/array-search and crashes on other tasks), and a thin engine bridge that drives `SynchronousRunner`. Planner-ON (temporal-DAG QueenBee) is explicitly deferred to Plan 2/3 (it needs a generic protocol runner).

**Tech Stack:** Python 3.11+, pydantic v2, pytest, argparse, stdlib `json`. **Run everything through `uv`** (`uv 0.11` is installed; the system `/usr/bin/python3` is 3.9 and cannot import `exp_graph`, which needs 3.11+). `masbench/pyproject.toml` declares `exp-graph` as an **editable path dependency** (`[tool.uv.sources]`), so `uv` provisions a 3.11+ interpreter and installs `exp_graph` plus its transitive deps (`pydantic`, `json-repair`) into the masbench venv. A `sys.path` bootstrap in `masbench/__init__.py` is a harmless fallback for non-uv invocation.

**Environment note (verified):** `uv --version` → 0.11.12; `/usr/bin/python3` → 3.9.6 (no pytest, and `import exp_graph` fails under 3.9). The first `uv run` provisions Python 3.11+ and installs deps (needs network once). All run/test commands below use `uv run`.

**Scope note:** This is Plan 1 of 3. Plan 2 = generic protocol runner (generalize the CF-hardwired `ProtocolRunner` + final aggregation + step metrics). Plan 3 = full temporal-DAG QueenBee + skill-evolution on the generic protocol path. Plan 1 delivers the runnable "I can run tests" milestone. Spec: `docs/superpowers/specs/2026-06-07-masbench-pipeline-benchmarks-design.md`.

---

## File Structure

```
masbench/
├── pyproject.toml                    # pytest pythonpath = ["src", "../exp-graph/src"]
├── README.md                         # offline + real run commands; submodule setup
├── configs/smoke.yaml                # example suite config (documentation)
├── third_party/                      # acl26-silo-bench submodule (added in Task 9; not needed for tests)
├── src/masbench/
│   ├── __init__.py                   # sys.path bootstrap so `import exp_graph` works at runtime
│   ├── core/
│   │   ├── __init__.py
│   │   ├── instance.py               # BenchmarkInstance dataclass
│   │   ├── scoring.py                # ScoreResult dataclass
│   │   ├── config.py                 # RunConfig dataclass
│   │   ├── benchmark.py              # BenchmarkAdapter ABC
│   │   └── task_bridge.py            # canonical_answer() + BenchmarkTaskAdapter(TaskAdapter)
│   ├── adapters/
│   │   ├── __init__.py
│   │   └── silo_bench.py             # SiloBenchAdapter (loads benchmarks/*.json)
│   ├── llm/
│   │   ├── __init__.py
│   │   └── fake.py                   # BenchmarkFakeLLMClient (generic, never crashes)
│   ├── engine.py                     # run_instance(): planner-OFF via SynchronousRunner
│   └── cli.py                        # run / run-suite / report subcommands
└── tests/
    ├── conftest.py                   # path bootstrap for tests (belt-and-suspenders)
    ├── data/silo_I-01_n2.json        # tiny vendored Global-Max fixture (no network needed)
    ├── data/silo_III-21_n2.json      # tiny vendored "unknown to fake" fixture (Distributed Sort)
    ├── test_instance.py
    ├── test_task_bridge.py
    ├── test_silo_adapter.py
    ├── test_fake.py
    ├── test_engine_fake.py           # THE offline smoke (end-to-end)
    └── test_cli.py
```

---

## Task 1: Scaffold the `masbench` package and verify `exp_graph` imports

**Files:**
- Create: `masbench/pyproject.toml`
- Create: `masbench/src/masbench/__init__.py`
- Create: `masbench/src/masbench/core/__init__.py`
- Create: `masbench/src/masbench/adapters/__init__.py`
- Create: `masbench/src/masbench/llm/__init__.py`
- Create: `masbench/tests/conftest.py`
- Test: `masbench/tests/test_import.py`

> **Order note (uv):** Tests run via `uv run`, which needs `masbench/pyproject.toml` to build the venv. So create `pyproject.toml` and the empty package `__init__.py` files (Step 3 content) **first**, then write the test and run it. The first `uv run` provisions Python 3.11+ and installs `exp-graph` (editable) + deps — this can take a minute and needs network once. With `exp-graph` installed by uv, `import exp_graph` works via the install; the `sys.path` bootstrap in `masbench/__init__.py` is just a fallback. At Step 2 the test then fails only on the missing `masbench.__version__` / package modules, not on environment setup.

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_import.py`:

```python
def test_can_import_exp_graph_engine():
    # masbench must make the sibling exp_graph engine importable.
    import masbench  # noqa: F401  (triggers sys.path bootstrap)
    from exp_graph.runner import SynchronousRunner  # noqa: F401
    from exp_graph.tasks.base import TaskAdapter  # noqa: F401


def test_masbench_version_present():
    import masbench

    assert isinstance(masbench.__version__, str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_import.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench'` (package not created yet).

- [ ] **Step 3: Write minimal implementation**

Create `masbench/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "masbench"
version = "0.1.0"
description = "Clean MAS benchmark pipeline reusing the exp_graph engine"
requires-python = ">=3.11"
license = {text = "MIT"}
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "exp-graph",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

# exp-graph lives in the sibling directory; install it editable (with its deps,
# e.g. json-repair) into the masbench venv via uv.
[tool.uv.sources]
exp-graph = { path = "../exp-graph", editable = true }

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

> First run provisions the venv: `cd masbench && uv run --extra dev python -c "import exp_graph, masbench; print('env ok')"` (downloads Python 3.11+ and installs deps the first time). The `pythonpath=["src"]` keeps tests using the working-tree masbench source.

Create `masbench/src/masbench/__init__.py`:

```python
"""masbench: a clean MAS benchmark pipeline that reuses the exp_graph engine."""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"


def _ensure_exp_graph_importable() -> None:
    """Add the sibling exp-graph/src to sys.path (repo idiom; see run_cf_*.py)."""
    repo_root = Path(__file__).resolve().parents[3]
    exp_graph_src = repo_root / "exp-graph" / "src"
    candidate = str(exp_graph_src)
    if exp_graph_src.is_dir() and candidate not in sys.path:
        sys.path.insert(0, candidate)


_ensure_exp_graph_importable()
```

Create empty `masbench/src/masbench/core/__init__.py`, `masbench/src/masbench/adapters/__init__.py`, `masbench/src/masbench/llm/__init__.py` (each containing only a one-line module docstring, e.g. `"""masbench core package."""`).

Create `masbench/tests/conftest.py`:

```python
"""Ensure both masbench/src and exp-graph/src are importable during tests."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _rel in ("masbench/src", "exp-graph/src"):
    _path = str(_REPO_ROOT / _rel)
    if _path not in sys.path:
        sys.path.insert(0, _path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_import.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add masbench/pyproject.toml masbench/src/masbench/__init__.py masbench/src/masbench/core/__init__.py masbench/src/masbench/adapters/__init__.py masbench/src/masbench/llm/__init__.py masbench/tests/conftest.py masbench/tests/test_import.py
git commit -m "feat(masbench): scaffold package and bridge to exp_graph engine"
```

---

## Task 2: `BenchmarkInstance` normalized data model

**Files:**
- Create: `masbench/src/masbench/core/instance.py`
- Test: `masbench/tests/test_instance.py`

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_instance.py`:

```python
import pytest

from masbench.core.instance import BenchmarkInstance


def test_instance_happy_path():
    inst = BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",
        case_name="Global Max",
        n_agents=2,
        shards=[[1, 5, 3], [9, 2]],
        ground_truth=9,
        task_prompt="Find the global maximum.",
        meta={"output_type": "distributed"},
    )
    assert inst.n_agents == 2
    assert inst.shards[1] == [9, 2]
    assert inst.ground_truth == 9


def test_instance_rejects_shard_count_mismatch():
    with pytest.raises(ValueError, match="expected 3 shards"):
        BenchmarkInstance(
            benchmark="silo_bench",
            case_id="I-01",
            case_name="Global Max",
            n_agents=3,
            shards=[[1], [2]],
            ground_truth=2,
        )


def test_instance_rejects_nonpositive_agents():
    with pytest.raises(ValueError, match="n_agents must be positive"):
        BenchmarkInstance(
            benchmark="b", case_id="c", case_name="n",
            n_agents=0, shards=[], ground_truth=None,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_instance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.core.instance'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/core/instance.py`:

```python
"""Normalized cross-benchmark task instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchmarkInstance:
    """One benchmark task instance, normalized across benchmarks.

    ``shards[i]`` is the private data held by agent ``i``. ``ground_truth`` is the
    expected global answer (kept out of agent-visible context by the adapter).
    """

    benchmark: str
    case_id: str
    case_name: str
    n_agents: int
    shards: list[Any]
    ground_truth: Any
    task_prompt: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.n_agents < 1:
            raise ValueError("n_agents must be positive")
        if len(self.shards) != self.n_agents:
            raise ValueError(
                f"expected {self.n_agents} shards, got {len(self.shards)}"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_instance.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add masbench/src/masbench/core/instance.py masbench/tests/test_instance.py
git commit -m "feat(masbench): add BenchmarkInstance data model"
```

---

## Task 3: `ScoreResult` and `RunConfig`

**Files:**
- Create: `masbench/src/masbench/core/scoring.py`
- Create: `masbench/src/masbench/core/config.py`
- Test: `masbench/tests/test_config_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_config_scoring.py`:

```python
from masbench.core.config import RunConfig
from masbench.core.scoring import ScoreResult


def test_run_config_defaults():
    cfg = RunConfig()
    assert cfg.benchmark == "silo_bench"
    assert cfg.use_planner is False
    assert cfg.topology == "mesh"
    assert cfg.llm_provider == "fake"
    assert cfg.max_rounds == 4


def test_score_result_shape():
    score = ScoreResult(success=True, n_messages=4, n_model_calls=8, tokens=120)
    assert score.success is True
    assert score.partial is None
    assert score.n_messages == 4
    assert score.extra == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_config_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.core.scoring'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/core/scoring.py`:

```python
"""Generic, benchmark-agnostic score record (not RMSE-bound)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScoreResult:
    """Outcome of running one benchmark instance through the pipeline."""

    success: bool
    partial: float | None = None
    n_messages: int = 0
    n_model_calls: int = 0
    tokens: int = 0
    final_answer: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
```

Create `masbench/src/masbench/core/config.py`:

```python
"""Run configuration for one benchmark execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunConfig:
    """How to run one instance. ``use_planner`` is reserved for Plan 2/3."""

    benchmark: str = "silo_bench"
    use_planner: bool = False
    use_skill_evolution: bool = False
    topology: str = "mesh"
    objective: str = "balanced"
    n_agents: int | None = None
    max_rounds: int = 4
    llm_provider: str = "fake"
    model_name: str = "fake"
    base_url: str | None = None
    api_key_env: str | None = None
    thinking_enabled: bool | None = None
    seed: int = 0
    consensus_threshold: float = 0.8
    final_accept_threshold: float = 0.7
    temperature: float = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_config_scoring.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add masbench/src/masbench/core/scoring.py masbench/src/masbench/core/config.py masbench/tests/test_config_scoring.py
git commit -m "feat(masbench): add RunConfig and ScoreResult"
```

---

## Task 4: `canonical_answer` + `BenchmarkTaskAdapter` (the bridge to exp_graph)

**Files:**
- Create: `masbench/src/masbench/core/task_bridge.py`
- Test: `masbench/tests/test_task_bridge.py`

This implements the 6-method `exp_graph.tasks.base.TaskAdapter` interface (verified signatures: `build_global_task`, `split_into_local_observations`, `initial_local_solve`, `normalize_consensus_key`, `evaluate_final_answer`, `format_task_prompt_context`).

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_task_bridge.py`:

```python
import masbench  # noqa: F401  (bootstraps exp_graph path)
from masbench.core.instance import BenchmarkInstance
from masbench.core.task_bridge import BenchmarkTaskAdapter, canonical_answer


def _instance():
    return BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[1, 5, 3], [9, 2]], ground_truth=9,
        task_prompt="Find the global maximum. You are agent {agent_id}.",
        meta={"output_type": "distributed"},
    )


def test_canonical_answer_scalar_and_json():
    assert canonical_answer(9) == "9"
    assert canonical_answer("9") == "9"           # numeric string normalizes
    assert canonical_answer("  9 ") == "9"
    assert canonical_answer([3, 1, 2]) == "[3,1,2]"
    assert canonical_answer("[3, 1, 2]") == "[3,1,2]"
    assert canonical_answer({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_answer(None) == "UNKNOWN"
    assert canonical_answer("unknown") == "UNKNOWN"
    assert canonical_answer("hello world") == "hello world"  # non-JSON string kept


def test_build_global_task_and_adjudication_hides_truth():
    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    assert gt["answer_key"] == "9"
    assert gt["n_agents"] == 2
    # Ground truth and raw shards must not leak into adjudication context.
    context = adapter.format_adjudication_context(gt)
    assert "answer_key" not in context
    assert "shards" not in context


def test_split_gives_each_agent_only_its_shard():
    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, 2)
    assert len(obs) == 2
    assert obs[0]["input_shard"] == [1, 5, 3]
    assert obs[1]["input_shard"] == [9, 2]
    assert obs[0]["agent_id"] == 0


def test_evaluate_final_answer_matches_canonical():
    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    assert adapter.evaluate_final_answer(gt, "9") is True
    assert adapter.evaluate_final_answer(gt, "7") is False
    assert adapter.evaluate_final_answer(gt, None) is False


def test_initial_local_solve_is_valid_belief_dict():
    from exp_graph.agents.schemas import BeliefState

    adapter = BenchmarkTaskAdapter(_instance())
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, 2)
    raw = adapter.initial_local_solve(obs[0])
    belief = BeliefState(**raw)  # must construct without error
    assert belief.consensus_key == "UNKNOWN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_task_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.core.task_bridge'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/core/task_bridge.py`:

```python
"""Generic bridge: a BenchmarkInstance -> an exp_graph TaskAdapter."""

from __future__ import annotations

import json
from typing import Any

import masbench  # noqa: F401  (ensures exp_graph is importable)
from exp_graph.tasks.base import TaskAdapter

from masbench.core.instance import BenchmarkInstance

GROUND_TRUTH_KEY = "answer_key"  # blocked by format_adjudication_context


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_answer(value: Any) -> str:
    """Canonical string form of an answer for grouping and exact-match.

    Numbers, lists, and dicts are normalized via canonical JSON. Numeric or
    JSON-looking strings are parsed first so that "9" and 9, or "[3, 1]" and
    [3, 1], compare equal. Empty/unknown sentinels collapse to ``UNKNOWN``.
    """
    if value is None:
        return "UNKNOWN"
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() in {"UNKNOWN", "NONE", "NULL", "PARTIAL"}:
            return "UNKNOWN"
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
        return _dumps(parsed)
    return _dumps(value)


class BenchmarkTaskAdapter(TaskAdapter):
    """Wrap one BenchmarkInstance behind the exp_graph 6-method interface."""

    def __init__(self, instance: BenchmarkInstance) -> None:
        self.instance = instance
        self.task_name = f"benchmark::{instance.benchmark}::{instance.case_id}"

    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        inst = self.instance
        return {
            "task_name": self.task_name,
            "benchmark": inst.benchmark,
            "case_id": inst.case_id,
            "case_name": inst.case_name,
            "n_agents": inst.n_agents,
            "shards": list(inst.shards),
            "task_prompt": inst.task_prompt,
            "meta": dict(inst.meta),
            "output_type": inst.meta.get("output_type", "scalar"),
            GROUND_TRUTH_KEY: canonical_answer(inst.ground_truth),
        }

    def split_into_local_observations(
        self, global_task: dict[str, Any], n_agents: int
    ) -> list[dict[str, Any]]:
        shards = global_task["shards"]
        if n_agents != len(shards):
            raise ValueError(
                f"benchmark instance has {len(shards)} shards but n_agents={n_agents}; "
                "benchmark instances are pre-sharded and cannot be re-split"
            )
        return [
            {
                "task_name": global_task["task_name"],
                "benchmark": global_task["benchmark"],
                "case_id": global_task["case_id"],
                "agent_id": agent_id,
                "n_agents": n_agents,
                "input_shard": shards[agent_id],
            }
            for agent_id in range(n_agents)
        ]

    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        agent_id = int(local_observation["agent_id"])
        shard = local_observation["input_shard"]
        size = len(shard) if isinstance(shard, (list, tuple, str, dict)) else 1
        return {
            "status": "unknown",
            "proposal": (
                f"Agent {agent_id} holds a private shard (size {size}). "
                "The global answer is not yet known."
            ),
            "consensus_key": "UNKNOWN",
            "support": [f"agent {agent_id} local shard size={size}"],
            "uncertainty": "Need information from other agents for the global answer.",
            "open_questions": ["What do other agents' shards contribute?"],
            "private_notes": "local shard only",
        }

    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        return canonical_answer(key_or_proposal)

    def evaluate_final_answer(
        self, global_task: dict[str, Any], final_key: str | None
    ) -> bool:
        return self.normalize_consensus_key(final_key) == global_task[GROUND_TRUTH_KEY]

    def format_task_prompt_context(
        self, global_task: dict[str, Any], local_observation: dict[str, Any]
    ) -> str:
        agent_id = local_observation["agent_id"]
        shard_json = json.dumps(local_observation["input_shard"], ensure_ascii=True)
        template = global_task["task_prompt"] or f"Task: {global_task['case_name']}"
        rendered = template.replace("{agent_id}", str(agent_id)).replace(
            "{input_shard}", shard_json
        )
        return (
            f"{rendered}\n"
            f"Total agents: {local_observation['n_agents']}\n"
            f"You are agent {agent_id}. Your private shard: {shard_json}\n"
        )

    def format_consensus_key_instructions(self) -> str:
        return (
            "Put your current best GLOBAL answer in consensus_key as a compact "
            "canonical value (a JSON number, string, list, or object). Use "
            "UNKNOWN if you cannot yet determine the global answer."
        )

    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        blocked = {GROUND_TRUTH_KEY, "shards"}
        return {key: value for key, value in global_task.items() if key not in blocked}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_task_bridge.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add masbench/src/masbench/core/task_bridge.py masbench/tests/test_task_bridge.py
git commit -m "feat(masbench): add canonical_answer and generic BenchmarkTaskAdapter"
```

---

## Task 5: `BenchmarkAdapter` ABC + `SiloBenchAdapter` loader

**Files:**
- Create: `masbench/src/masbench/core/benchmark.py`
- Create: `masbench/src/masbench/adapters/silo_bench.py`
- Create: `masbench/tests/data/silo_I-01_n2.json`
- Create: `masbench/tests/data/silo_III-21_n2.json`
- Test: `masbench/tests/test_silo_adapter.py`

- [ ] **Step 1: Write the failing test**

Create the fixture `masbench/tests/data/silo_I-01_n2.json` (tiny Global-Max, mirrors the real schema):

```json
{
  "case_id": "I-01",
  "case_name": "Global Max",
  "paradigm": "Paradigm I",
  "metadata": {"num_agents": 2, "output_type": "distributed", "is_segmented": false,
               "theoretical_complexity": "O(N) - MapReduce/Aggregation"},
  "task_description": "Find the GLOBAL MAXIMUM across all agents' data. You are Agent {agent_id} and hold: {input_shard}",
  "agent_configs": [
    {"agent_id": 0, "input_shard": [3, 1, 9, 2], "expected_output": 9},
    {"agent_id": 1, "input_shard": [5, 8, 4], "expected_output": 9}
  ]
}
```

Create the fixture `masbench/tests/data/silo_III-21_n2.json` (Distributed Sort — the fake cannot solve this; used to prove graceful no-crash):

```json
{
  "case_id": "III-21",
  "case_name": "Distributed Sort",
  "paradigm": "Paradigm III",
  "metadata": {"num_agents": 2, "output_type": "distributed", "is_segmented": false,
               "theoretical_complexity": "O(N log N)"},
  "task_description": "Return the globally sorted ascending list of all agents' values. You are Agent {agent_id} and hold: {input_shard}",
  "agent_configs": [
    {"agent_id": 0, "input_shard": [3, 1], "expected_output": [1, 2, 3, 4]},
    {"agent_id": 1, "input_shard": [4, 2], "expected_output": [1, 2, 3, 4]}
  ]
}
```

Create `masbench/tests/test_silo_adapter.py`:

```python
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter

DATA = Path(__file__).parent / "data"


def test_loads_instance_from_json():
    adapter = SiloBenchAdapter(DATA)
    instances = {inst.case_id: inst for inst in adapter.iter_instances()}
    assert set(instances) == {"I-01", "III-21"}
    gmax = instances["I-01"]
    assert gmax.n_agents == 2
    assert gmax.shards == [[3, 1, 9, 2], [5, 8, 4]]
    assert gmax.ground_truth == 9
    assert gmax.case_name == "Global Max"
    assert "{agent_id}" in gmax.task_prompt


def test_filters_by_case():
    adapter = SiloBenchAdapter(DATA)
    only = list(adapter.iter_instances(cases=["I-01"]))
    assert len(only) == 1
    assert only[0].case_id == "I-01"


def test_filters_by_level():
    adapter = SiloBenchAdapter(DATA)
    level_iii = list(adapter.iter_instances(levels=["III"]))
    assert [inst.case_id for inst in level_iii] == ["III-21"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_silo_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.adapters.silo_bench'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/core/benchmark.py`:

```python
"""Benchmark adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from masbench.core.instance import BenchmarkInstance


class BenchmarkAdapter(ABC):
    """A source of normalized BenchmarkInstances for one benchmark."""

    name: str

    @abstractmethod
    def iter_instances(self, **filters: Any) -> Iterable[BenchmarkInstance]:
        """Yield instances, optionally narrowed by benchmark-specific filters."""
        ...
```

Create `masbench/src/masbench/adapters/silo_bench.py`:

```python
"""Silo-Bench loader: benchmarks/{Level}-{NN}_n{agents}.json -> BenchmarkInstance."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from masbench.core.benchmark import BenchmarkAdapter
from masbench.core.instance import BenchmarkInstance

_FILENAME_RE = re.compile(r"(?P<level>[IVX]+)-(?P<num>\d+)_n(?P<agents>\d+)\.json$")


class SiloBenchAdapter(BenchmarkAdapter):
    """Load Silo-Bench instances from a directory of benchmark JSON files."""

    name = "silo_bench"

    def __init__(self, benchmarks_dir: str | Path) -> None:
        self.benchmarks_dir = Path(benchmarks_dir)

    def iter_instances(
        self,
        *,
        levels: list[str] | None = None,
        agent_counts: list[int] | None = None,
        cases: list[str] | None = None,
    ) -> Iterable[BenchmarkInstance]:
        if not self.benchmarks_dir.is_dir():
            raise FileNotFoundError(
                f"Silo-Bench benchmarks dir not found: {self.benchmarks_dir}. "
                "Add the submodule or pass --benchmarks-dir (see masbench/README.md)."
            )
        for path in sorted(self.benchmarks_dir.glob("*.json")):
            match = _FILENAME_RE.search(path.name)
            if match is None:
                continue
            level = match.group("level")
            agents = int(match.group("agents"))
            if levels is not None and level not in set(levels):
                continue
            if agent_counts is not None and agents not in set(agent_counts):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if cases is not None and data.get("case_id") not in set(cases):
                continue
            yield self._to_instance(data)

    def _to_instance(self, data: dict) -> BenchmarkInstance:
        agent_configs = data["agent_configs"]
        shards = [ac["input_shard"] for ac in agent_configs]
        expected_outputs = [ac.get("expected_output") for ac in agent_configs]
        metadata = dict(data.get("metadata", {}))
        metadata["expected_outputs"] = expected_outputs
        return BenchmarkInstance(
            benchmark="silo_bench",
            case_id=data["case_id"],
            case_name=data.get("case_name", ""),
            n_agents=int(metadata.get("num_agents", len(agent_configs))),
            shards=shards,
            ground_truth=expected_outputs[0] if expected_outputs else None,
            task_prompt=data.get("task_description", ""),
            meta=metadata,
        )
```

> Note: `ground_truth = expected_outputs[0]` is correct for non-segmented "distributed" tasks where every agent submits the same global answer. Segmented tasks (`metadata.is_segmented == true`) have per-agent answers; they are out of scope for Plan 1 success-scoring and are handled in a later plan (the per-agent answers are preserved in `meta["expected_outputs"]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_silo_adapter.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add masbench/src/masbench/core/benchmark.py masbench/src/masbench/adapters/silo_bench.py masbench/tests/data/silo_I-01_n2.json masbench/tests/data/silo_III-21_n2.json masbench/tests/test_silo_adapter.py
git commit -m "feat(masbench): add BenchmarkAdapter ABC and Silo-Bench loader"
```

---

## Task 6: `BenchmarkFakeLLMClient` (offline, never crashes)

**Files:**
- Create: `masbench/src/masbench/llm/fake.py`
- Test: `masbench/tests/test_fake.py`

The stock `exp_graph.llm.fake.FakeLLMClient` dispatches on `task_name == "count_frequency"` else assumes array-search and calls `int(local_observation.get("target"))`, which raises on Silo tasks. We need a benchmark-aware fake that (a) always returns a parseable belief, and (b) for known associative-reduce cases (e.g. `I-01` Global Max) computes the reduced answer from the local shard plus neighbor consensus keys, so offline runs can actually converge.

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_fake.py`:

```python
import json

import masbench  # noqa: F401
from exp_graph.agents.schemas import BeliefState
from exp_graph.llm.parser import parse_belief_state
from exp_graph.llm.prompts import build_solver_prompt
from masbench.core.instance import BenchmarkInstance
from masbench.core.task_bridge import BenchmarkTaskAdapter
from masbench.llm.fake import BenchmarkFakeLLMClient


def _prompt_for(instance, agent_id, old_belief, inbox):
    adapter = BenchmarkTaskAdapter(instance)
    gt = adapter.build_global_task()
    obs = adapter.split_into_local_observations(gt, instance.n_agents)
    return build_solver_prompt(
        task_adapter=adapter, global_task=gt,
        local_observation=obs[agent_id], old_belief_state=old_belief, inbox=inbox,
    )


def test_fake_returns_parseable_belief_for_unknown_case():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="III-21", case_name="Distributed Sort",
        n_agents=2, shards=[[3, 1], [4, 2]], ground_truth=[1, 2, 3, 4],
        task_prompt="Sort. Agent {agent_id}: {input_shard}",
    )
    prompt = _prompt_for(inst, 0, BeliefState(), [])
    resp = BenchmarkFakeLLMClient().complete(prompt, model_name="fake")
    belief = parse_belief_state(resp.text)  # must not raise
    assert isinstance(belief, BeliefState)
    assert resp.usage.completion_tokens > 0


def test_fake_reduces_global_max_from_local_shard():
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[3, 1, 9, 2], [5, 8, 4]], ground_truth=9,
        task_prompt="Max. Agent {agent_id}: {input_shard}",
    )
    prompt = _prompt_for(inst, 0, BeliefState(), [])
    resp = BenchmarkFakeLLMClient().complete(prompt, model_name="fake")
    belief = json.loads(resp.text)
    assert belief["consensus_key"] == "9"  # local max of [3,1,9,2]


def test_fake_reduces_global_max_with_neighbor_key():
    # Agent 1's local max is 8, but a neighbor reports 9 -> should output 9.
    inst = BenchmarkInstance(
        benchmark="silo_bench", case_id="I-01", case_name="Global Max",
        n_agents=2, shards=[[3, 1, 9, 2], [5, 8, 4]], ground_truth=9,
        task_prompt="Max. Agent {agent_id}: {input_shard}",
    )
    from exp_graph.messaging.messages import OutboxMessage

    neighbor = OutboxMessage.from_belief_state(
        agent_id=0, round_idx=0,
        belief_state=BeliefState(status="candidate", consensus_key="9"),
    )
    prompt = _prompt_for(inst, 1, BeliefState(), [neighbor])
    resp = BenchmarkFakeLLMClient().complete(prompt, model_name="fake")
    belief = json.loads(resp.text)
    assert belief["consensus_key"] == "9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_fake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.llm.fake'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/llm/fake.py`:

```python
"""Benchmark-aware deterministic fake LLM for offline smoke runs.

Unlike exp_graph's FakeLLMClient (hardwired to CF / array-search), this client
never crashes on arbitrary benchmark tasks. For associative-reduce cases it
computes the reduced answer from the local shard plus neighbor consensus keys so
that offline runs can converge; for everything else it returns a valid
"unknown" belief (the pipeline still runs end-to-end, just without a correct
answer offline).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import masbench  # noqa: F401
from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens

# case_id -> reducer over a flat list of numbers
_REDUCERS: dict[str, Callable[[list[float]], Any]] = {
    "I-01": max,  # Global Max
}


class BenchmarkFakeLLMClient:
    """Deterministic, task-tolerant fake client."""

    def complete(
        self, prompt: str, model_name: str, temperature: float | None = None
    ) -> LLMResponse:
        local = _block(prompt, "LOCAL_OBSERVATION_JSON:", "OLD_BELIEF_STATE_JSON:")
        old = _block(prompt, "OLD_BELIEF_STATE_JSON:", "INBOX_JSON:")
        inbox = _block(prompt, "INBOX_JSON:", None)
        belief = _solve(str(local.get("case_id", "")), local, old, inbox)
        text = json.dumps(belief)
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
            ),
        )


def _block(prompt: str, start: str, end: str | None) -> Any:
    begin = prompt.index(start) + len(start)
    raw = prompt[begin:].strip() if end is None else prompt[begin : prompt.index(end, begin)].strip()
    return json.loads(raw)


def _as_number(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_numbers(local: dict, old: dict, inbox: list) -> list[float]:
    numbers: list[float] = []
    shard = local.get("input_shard")
    if isinstance(shard, list):
        numbers += [n for n in (_as_number(v) for v in shard) if n is not None]
    for source in [old, *inbox]:
        if isinstance(source, dict):
            key = source.get("consensus_key")
            n = _as_number(key)
            if n is not None:
                numbers.append(n)
    return numbers


def _solve(case_id: str, local: dict, old: dict, inbox: list) -> dict:
    reducer = _REDUCERS.get(case_id)
    if reducer is not None:
        numbers = _candidate_numbers(local, old, inbox)
        if numbers:
            result = reducer(numbers)
            if float(result).is_integer():
                result = int(result)
            return {
                "status": "candidate",
                "proposal": f"Reduced answer over visible data is {result}.",
                "consensus_key": str(result),
                "support": [f"reduced {len(numbers)} visible values"],
                "uncertainty": "",
                "open_questions": [],
                "private_notes": "deterministic reduce over local shard + neighbor keys",
            }
    return {
        "status": "unknown",
        "proposal": "Offline fake client cannot solve this task type.",
        "consensus_key": "UNKNOWN",
        "support": [f"case_id={case_id}"],
        "uncertainty": "No deterministic offline solver for this task.",
        "open_questions": ["Use a real LLM provider to attempt this task."],
        "private_notes": "fake fallback",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_fake.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add masbench/src/masbench/llm/fake.py masbench/tests/test_fake.py
git commit -m "feat(masbench): add benchmark-aware fake LLM client"
```

---

## Task 7: `engine.run_instance` + offline end-to-end smoke (THE milestone)

**Files:**
- Create: `masbench/src/masbench/engine.py`
- Test: `masbench/tests/test_engine_fake.py`

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_engine_fake.py`:

```python
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance

DATA = Path(__file__).parent / "data"


def _instance(case_id):
    adapter = SiloBenchAdapter(DATA)
    return next(adapter.iter_instances(cases=[case_id]))


def test_offline_global_max_succeeds_on_mesh():
    inst = _instance("I-01")
    cfg = RunConfig(topology="mesh", llm_provider="fake", max_rounds=3, n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.success is True               # fake reduces to global max on mesh
    assert score.final_answer == "9"
    assert score.n_model_calls > 0
    assert score.n_messages > 0


def test_offline_unknown_task_runs_without_crashing():
    inst = _instance("III-21")
    cfg = RunConfig(topology="mesh", llm_provider="fake", max_rounds=2, n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.success is False              # fake can't sort; pipeline still runs
    assert "stop_reason" in score.extra


def test_planner_on_is_not_yet_supported():
    import pytest

    inst = _instance("I-01")
    cfg = RunConfig(use_planner=True)
    with pytest.raises(NotImplementedError, match="Plan 2/3"):
        run_instance(inst, cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_engine_fake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.engine'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/engine.py`:

```python
"""Engine bridge: run one BenchmarkInstance through the exp_graph SynchronousRunner."""

from __future__ import annotations

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import create_llm_client
from exp_graph.runner import SynchronousRunner

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.core.task_bridge import BenchmarkTaskAdapter
from masbench.llm.fake import BenchmarkFakeLLMClient


def _build_llm_client(cfg: RunConfig) -> LLMClient:
    if cfg.llm_provider == "fake":
        return BenchmarkFakeLLMClient()
    return create_llm_client(
        cfg.llm_provider,
        base_url=cfg.base_url,
        api_key_env=cfg.api_key_env,
        thinking_enabled=cfg.thinking_enabled,
    )


def _count_messages(result) -> int:
    total = 0
    for log in result.round_logs:
        total += sum(len(neighbors) for neighbors in log.neighbors.values())
    return total


def run_instance(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None = None,
) -> ScoreResult:
    """Run one instance planner-OFF via SynchronousRunner and score it."""
    if cfg.use_planner:
        raise NotImplementedError(
            "use_planner requires the generic protocol runner delivered in Plan 2/3. "
            "Plan 1 supports the planner-OFF SynchronousRunner path only."
        )

    task_adapter = BenchmarkTaskAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents

    experiment_config = ExperimentConfig(
        topology_name=cfg.topology,
        n_agents=n_agents,
        max_rounds=cfg.max_rounds,
        seed=cfg.seed,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        temperature=cfg.temperature,
        consensus_threshold=cfg.consensus_threshold,
        final_accept_threshold=cfg.final_accept_threshold,
        trace_enabled=False,
    )
    client = llm_client or _build_llm_client(cfg)
    result = SynchronousRunner(
        config=experiment_config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()

    return ScoreResult(
        success=bool(result.metrics.final_accuracy),
        partial=None,
        n_messages=_count_messages(result),
        n_model_calls=int(result.metrics.total_model_calls),
        tokens=int(result.metrics.total_token_cost),
        final_answer=result.final_result.final_key,
        extra={
            "case_id": instance.case_id,
            "topology": cfg.topology,
            "stop_reason": result.stop_reason,
            "consensus_reached": result.final_result.consensus_reached,
            "aggregation_method": result.final_result.aggregation_method,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_engine_fake.py -v`
Expected: PASS (3 passed). This proves the full pipeline runs offline on real Silo-Bench-shaped data.

- [ ] **Step 5: Commit**

```bash
git add masbench/src/masbench/engine.py masbench/tests/test_engine_fake.py
git commit -m "feat(masbench): add engine bridge and offline end-to-end smoke"
```

---

## Task 8: CLI — `run`, `run-suite`, `report`

**Files:**
- Create: `masbench/src/masbench/cli.py`
- Test: `masbench/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `masbench/tests/test_cli.py`:

```python
import json
from pathlib import Path

from masbench.cli import main

DATA = Path(__file__).parent / "data"


def test_run_suite_writes_summary(tmp_path):
    out = tmp_path / "smoke"
    rc = main([
        "run-suite", "--benchmark", "silo_bench",
        "--benchmarks-dir", str(DATA),
        "--cases", "I-01",
        "--topology", "mesh", "--llm", "fake", "--max-rounds", "3",
        "--out", str(out),
    ])
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["n_instances"] == 1
    assert summary["success_rate"] == 1.0
    # one per-instance record was written
    records = list(out.glob("I-01_*.json"))
    assert len(records) == 1


def test_report_reads_run_dir(tmp_path, capsys):
    out = tmp_path / "smoke"
    main([
        "run-suite", "--benchmark", "silo_bench", "--benchmarks-dir", str(DATA),
        "--cases", "I-01", "--topology", "mesh", "--llm", "fake",
        "--max-rounds", "3", "--out", str(out),
    ])
    rc = main(["report", "--run-dir", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "success_rate" in printed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'masbench.cli'`.

- [ ] **Step 3: Write minimal implementation**

Create `masbench/src/masbench/cli.py`:

```python
"""masbench command-line interface."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance


def _adapter(benchmark: str, benchmarks_dir: str) -> SiloBenchAdapter:
    if benchmark != "silo_bench":
        raise SystemExit(f"unknown benchmark '{benchmark}' (Plan 1 supports silo_bench)")
    return SiloBenchAdapter(benchmarks_dir)


def _cfg_from_args(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        benchmark=args.benchmark,
        use_planner=getattr(args, "planner", False),
        topology=args.topology,
        max_rounds=args.max_rounds,
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        seed=args.seed,
    )


def _filters(args: argparse.Namespace) -> dict:
    filters: dict = {}
    if getattr(args, "levels", None):
        filters["levels"] = args.levels
    if getattr(args, "agent_counts", None):
        filters["agent_counts"] = [int(a) for a in args.agent_counts]
    if getattr(args, "cases", None):
        filters["cases"] = args.cases
    return filters


def _record(instance: BenchmarkInstance, cfg: RunConfig, score: ScoreResult) -> dict:
    return {
        "benchmark": instance.benchmark,
        "case_id": instance.case_id,
        "case_name": instance.case_name,
        "n_agents": instance.n_agents,
        "config": asdict(cfg),
        "score": asdict(score),
    }


def _cmd_run(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    cfg = _cfg_from_args(args)
    instance = next(adapter.iter_instances(cases=[args.case], agent_counts=[args.n_agents]))
    score = run_instance(instance, cfg)
    print(json.dumps(_record(instance, cfg, score), indent=2, sort_keys=True))
    return 0


def _cmd_run_suite(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    cfg = _cfg_from_args(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for instance in adapter.iter_instances(**_filters(args)):
        run_cfg = RunConfig(**{**asdict(cfg), "n_agents": instance.n_agents})
        score = run_instance(instance, run_cfg)
        record = _record(instance, run_cfg, score)
        records.append(record)
        fname = f"{instance.case_id}_n{instance.n_agents}_seed{run_cfg.seed}.json"
        (out / fname).write_text(json.dumps(record, indent=2, sort_keys=True))
        print(f"{instance.case_id} n{instance.n_agents}: success={score.success} "
              f"answer={score.final_answer} tokens={score.tokens}")
    summary = _summarize(records)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nsuccess_rate={summary['success_rate']:.3f} over {summary['n_instances']} instances")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    records = [
        json.loads(p.read_text())
        for p in sorted(run_dir.glob("*.json"))
        if p.name != "summary.json"
    ]
    summary = _summarize(records)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _summarize(records: list[dict]) -> dict:
    n = len(records)
    successes = sum(1 for r in records if r["score"]["success"])
    tokens = sum(int(r["score"]["tokens"]) for r in records)
    messages = sum(int(r["score"]["n_messages"]) for r in records)
    return {
        "n_instances": n,
        "success_rate": (successes / n) if n else 0.0,
        "successes": successes,
        "total_tokens": tokens,
        "total_messages": messages,
        "by_case": {
            r["case_id"]: {"success": r["score"]["success"], "answer": r["score"]["final_answer"]}
            for r in records
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="masbench", description="Clean MAS benchmark pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--benchmark", default="silo_bench")
        p.add_argument("--benchmarks-dir", default="third_party/acl26-silo-bench/benchmarks")
        p.add_argument("--topology", default="mesh")
        p.add_argument("--max-rounds", type=int, default=4)
        p.add_argument("--llm", dest="llm", default="fake",
                       help="fake | openai | deepseek | bailian | dashscope | qwen | alibaba | xiaomi")
        p.add_argument("--model-name", default="fake")
        p.add_argument("--base-url", default=None)
        p.add_argument("--api-key-env", default=None)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--planner", action="store_true",
                       help="(Plan 2/3) enable the QueenBee planner; not yet supported")

    p_run = sub.add_parser("run", help="run a single instance")
    add_common(p_run)
    p_run.add_argument("--case", required=True)
    p_run.add_argument("--n-agents", type=int, required=True)
    p_run.set_defaults(func=_cmd_run)

    p_suite = sub.add_parser("run-suite", help="run a grid of instances")
    add_common(p_suite)
    p_suite.add_argument("--levels", nargs="+", default=None)
    p_suite.add_argument("--agent-counts", nargs="+", default=None)
    p_suite.add_argument("--cases", nargs="+", default=None)
    p_suite.add_argument("--out", required=True)
    p_suite.set_defaults(func=_cmd_run_suite)

    p_report = sub.add_parser("report", help="aggregate a run directory")
    p_report.add_argument("--run-dir", required=True)
    p_report.set_defaults(func=_cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd masbench && uv run --extra dev python -m pytest tests/test_cli.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `cd masbench && uv run --extra dev python -m pytest -v`
Expected: PASS (all tests across the 7 test files).

- [ ] **Step 6: Commit**

```bash
git add masbench/src/masbench/cli.py masbench/tests/test_cli.py
git commit -m "feat(masbench): add run/run-suite/report CLI"
```

---

## Task 9: Silo-Bench data submodule, README, and real-run docs

**Files:**
- Create: `masbench/README.md`
- Create: `masbench/configs/smoke.yaml`
- Modify: `.gitmodules` (via `git submodule add`)

- [ ] **Step 1: Add the Silo-Bench submodule (provides the real 180 instances)**

Run:
```bash
cd /Users/robintian/AI/Agent-Expretional-Graph-topology-equivalence
git submodule add https://github.com/jwyjohn/acl26-silo-bench masbench/third_party/acl26-silo-bench
```
Expected: clones into `masbench/third_party/acl26-silo-bench`; `masbench/third_party/acl26-silo-bench/benchmarks/I-01_n2.json` exists.

Verify: `ls masbench/third_party/acl26-silo-bench/benchmarks | head` lists `I-01_n10.json` etc.

> If offline / no network: skip this step; the loader accepts any `--benchmarks-dir`, and tests use the vendored fixtures in `tests/data/`. Document this in the README.

- [ ] **Step 2: Write the README**

Create `masbench/README.md`:

````markdown
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
````

- [ ] **Step 3: Write the example suite config**

Create `masbench/configs/smoke.yaml`:

```yaml
# Documentation-only example mirroring the offline smoke command.
benchmark: silo_bench
benchmarks_dir: third_party/acl26-silo-bench/benchmarks
levels: [I]
topology: mesh
llm: fake
max_rounds: 3
out: runs/smoke
```

- [ ] **Step 4: Verify the real data loads through the loader (if submodule present)**

Run:
```bash
cd masbench && uv run python -c "
from masbench.adapters.silo_bench import SiloBenchAdapter
a = SiloBenchAdapter('third_party/acl26-silo-bench/benchmarks')
xs = list(a.iter_instances(levels=['I'], agent_counts=[2]))
print('loaded', len(xs), 'level-I n2 instances; first:', xs[0].case_id, xs[0].case_name)
"
```
Expected: prints `loaded 10 level-I n2 instances; first: I-01 Global Max` (skip if submodule absent).

- [ ] **Step 5: Commit**

```bash
git add .gitmodules masbench/third_party masbench/README.md masbench/configs/smoke.yaml
git commit -m "docs(masbench): add Silo-Bench submodule, README, and run configs"
```

---

## Plan 2 (outline): Generic protocol runner

Goal: make the temporal-DAG / finite-protocol execution path task-agnostic so the QueenBee planner can run on any benchmark — without rewriting CF.

- **Define `ProtocolTaskAdapter`** (ABC in `masbench/core/protocol_adapter.py`) capturing the 7 protocol methods `ProtocolRunner` calls on its adapter today: `initial_protocol_belief`, `format_protocol_init_prompt`, `validate_protocol_initial_belief_state`, `merge_protocol_inbox`, `format_protocol_merge_prompt`, `apply_verified_protocol_merge`, `validate_protocol_belief_state` (signatures verified in `exp-graph/src/exp_graph/runner/protocol.py`).
- **`GenericProtocolRunner`** (`masbench/runner/generic_protocol.py`): adapt `ProtocolRunner` so final aggregation and step metrics come from the adapter (or a generic implementation) instead of the module-level CF functions `run_cf_final_aggregation` / `build_cf_step_metrics`. Generic final aggregation = group by `normalize_consensus_key` → pick the designated holder / majority → `evaluate_final_answer`. Generic step metrics = success/coverage/cost (no RMSE).
- **`SiloProtocolAdapter`**: generic structured-answer protocol belief (each agent carries its partial answer + provenance source ids; deterministic merge = union/combine; LLM merge prompt = "merge neighbor answer artifacts into one global answer").
- **Tests**: run a fixed `protocol_spec` (e.g. tree-reduce) on the I-01 fixture with the fake client; assert convergence + scoring parity with the SynchronousRunner path.
- Decision needed at Plan-2 start: fork `ProtocolRunner` into `masbench` vs. minimally parameterize `exp_graph`'s copy (the user chose "reuse engine"; a fork keeps `exp_graph` untouched and is the safer default — confirm then).

## Plan 3 (outline): Full QueenBee on Silo-Bench + official partial scoring

- Wire the temporal-DAG graph generation (`exp_graph.mas.graph_generation` / `mas.pipeline`) and skill-evolution (`mas.evolution`, `SkillBank`) to the `GenericProtocolRunner`.
- Generalize the minister/evolution evidence from RMSE to the generic `ScoreResult` (success-rate / cost) — `summary_to_aggregate_row` in `exp_graph/mas/runner.py` is the adapter point.
- Implement `cfg.use_planner=True` / `cfg.use_skill_evolution=True` in `engine.run_instance` routing to the QueenBee pipeline.
- Add official Silo-Bench partial-correctness scoring by importing `acl26-silo-bench/src/utils/metrics.py` (and per-protocol `evaluate.py`) where importable; populate `ScoreResult.partial`.
- Handle segmented tasks (`metadata.is_segmented == true`) via per-agent answer scoring using `meta["expected_outputs"]`.

---

## Self-Review

**1. Spec coverage:** Spec §4 architecture → Tasks 1–8 create exactly the listed modules. §5 abstractions (BenchmarkInstance/ScoreResult/RunConfig/BenchmarkTaskAdapter) → Tasks 2,3,4. §6 engine bridge (planner on/off) → Task 7 (planner-OFF; planner-ON raises with a Plan 2/3 pointer, per the user's "full" decision now decomposed). §7 CLI → Task 8. §8 Silo scoring (success self-computed; partial deferred) → Tasks 4,5,7 + Plan 3. §9 milestones (offline smoke + real run) → Tasks 7 (smoke) and 9 (README real-run). §10 Phase 2 (scheduling) → unchanged, future. §12 risks (packaging, answer extraction) → Task 1 (`pythonpath`/bootstrap), Task 4 (`canonical_answer`). Gap intentionally deferred: full temporal-DAG planner-ON → Plans 2–3 (outlined).

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to". Every code step has complete code; every run step has an exact command and expected output. The `[PLACEHOLDER]` strings inside the Silo JSON fixtures are quoted upstream data, not plan placeholders.

**3. Type consistency:** `BenchmarkInstance(benchmark, case_id, case_name, n_agents, shards, ground_truth, task_prompt, meta)` used identically in Tasks 2,4,5,6. `RunConfig` fields (`use_planner`, `topology`, `llm_provider`, `model_name`, `base_url`, `api_key_env`, `n_agents`, `max_rounds`, `seed`, `consensus_threshold`, `final_accept_threshold`, `temperature`) consistent across Tasks 3,7,8. `ScoreResult(success, partial, n_messages, n_model_calls, tokens, final_answer, extra)` consistent across Tasks 3,7,8. `canonical_answer` / `GROUND_TRUTH_KEY="answer_key"` consistent across Tasks 4,6 (fake emits `consensus_key` as a canonical string; bridge compares via `canonical_answer`). Engine uses verified exp_graph signatures: `ExperimentConfig(...)`, `SynchronousRunner(config=, task_adapter=, global_task=, llm_client=).run()`, `result.metrics.final_accuracy/total_model_calls/total_token_cost`, `result.final_result.final_key`, `result.round_logs[].neighbors`.
