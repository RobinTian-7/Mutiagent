# masbench Plan 2: Generalize exp_graph's CF-hardwired protocol engine (in-place)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **All implementer/reviewer subagents run on Opus 4.8** (user directive).

**Goal:** Make exp_graph's temporal-DAG protocol execution path (`ProtocolRunner` + final aggregation + step metrics) **task-agnostic**, so the QueenBee planner can run on arbitrary structured-answer benchmarks (Silo-Bench), while keeping count_frequency (CF) behavior byte-identical.

**Architecture:** Additive in-place generalization. Introduce a `ProtocolTaskAdapter` interface + generic result/metric types + generic vote aggregation. `CountFrequencyTaskAdapter` becomes the reference implementation, delegating to the existing `run_cf_final_aggregation` / `build_cf_step_metrics` so CF is unchanged. `ProtocolRunner` calls the adapter (not module-level CF functions) and its result model accepts the generic types.

**Tech Stack:** Python 3.11+, pydantic v2, pytest, run via `uv` (see [[uv-python-env]] / masbench Plan 1). exp_graph has its own uv project.

**THE GUARDRAIL (non-negotiable):** After every task, `uv run --directory exp-graph --extra dev python -m pytest -q` must stay **191 passed, 1 skipped** (the pre-refactor baseline). Any drop = a regression to fix before proceeding. This is how we prove CF behavior is preserved.

**Decision (user):** in-place generalization of exp_graph (not a masbench fork). Full self-evolution overhaul is **Plan 3** (this plan only generalizes the execution/aggregation/metrics path so the planner can run; evolution-objective generalization + the 5 skill improvements are Plan 3).

**Spec:** `docs/superpowers/specs/2026-06-07-masbench-pipeline-benchmarks-design.md` §2.1.

---

## Verified current interfaces (what we generalize)

- `exp_graph/runner/protocol.py`: `ProtocolRunner.__init__(*, config, task_adapter: CountFrequencyTaskAdapter, global_task, llm_client=None)`. In `run()` it calls these CF-coupled things:
  - the 7 adapter protocol methods (already methods on `CountFrequencyTaskAdapter`): `initial_protocol_belief`, `format_protocol_init_prompt`, `validate_protocol_initial_belief_state`, `merge_protocol_inbox`, `format_protocol_merge_prompt`, `apply_verified_protocol_merge`, `validate_protocol_belief_state`.
  - module-level `run_cf_final_aggregation(...)` (protocol.py:386) → `CFProtocolFinalResult`.
  - module-level `build_cf_step_metrics(...)` (protocol.py:983) → `(list[CFAgentStepMetric], CFGlobalStepMetric)`.
  - `ProtocolExperimentResult.final_result: CFProtocolFinalResult`, `agent_step_metrics: list[CFAgentStepMetric]`, `global_step_metrics: list[CFGlobalStepMetric]`, and `to_summary_dict()` emits `FinalRMSE/VoteRMSE/AverageRMSE/...`.
- `exp_graph/aggregator/cf_final.py`: `CFProtocolFinalResult{final_key, final_counts, selected_primary, aggregation_method, rmse, normalized_l1_error, exact_match, vote: CFHeadResult, average, vote_average_disagreement_rmse, answer_agent_ids}`; `run_cf_final_aggregation(*, agent_states, global_task, task_adapter, topology_name, star_center, average_include_min_coverage, selected_primary, answer_agent_ids_override)`; `answer_agents_for_topology(...)`.
- `exp_graph/metrics/cf_protocol.py`: `CFAgentStepMetric`, `CFGlobalStepMetric`, `build_cf_step_metrics(*, agent_states, global_task, task_adapter, topology_name, step_idx, phase, send_counts, receive_counts, average_include_min_coverage)`.
- `exp_graph/mas/runner.py`: `summary_to_aggregate_row(summary)` maps `FinalRMSE→MeanFinalRMSE` etc. for ministers.

---

## File Structure

```
exp-graph/src/exp_graph/
├── tasks/
│   ├── protocol_adapter.py      # NEW: ProtocolTaskAdapter ABC + GenericVoteProtocolMixin
│   └── count_frequency.py       # MODIFY: declare it implements ProtocolTaskAdapter; add finalize/step-metric/answer methods that delegate to cf_final/cf_protocol
├── aggregator/
│   ├── protocol_final.py        # NEW: ProtocolFinalResult + run_protocol_vote_aggregation (generic, vote-only)
│   └── cf_final.py              # UNCHANGED (CF reference impl that the CF adapter delegates to)
├── metrics/
│   ├── protocol.py              # NEW: ProtocolAgentStepMetric, ProtocolGlobalStepMetric, build_protocol_step_metrics (generic)
│   └── cf_protocol.py           # UNCHANGED (CF reference impl)
├── runner/
│   └── protocol.py              # MODIFY: type hint -> ProtocolTaskAdapter; call adapter.finalize_protocol / adapter.build_protocol_step_metrics; result model accepts generic | CF types; to_summary_dict generic-aware
└── tasks/
    └── global_max.py            # NEW (test fixture task): a minimal generic ProtocolTaskAdapter proving the non-CF path
exp-graph/tests/
├── test_protocol_adapter_generic.py   # NEW: global_max runs through ProtocolRunner end-to-end (fake LLM)
└── (existing 191 tests must stay green)
```

---

## Task 1: `ProtocolTaskAdapter` interface + generic result/metric types

**Files:**
- Create: `exp-graph/src/exp_graph/aggregator/protocol_final.py`
- Create: `exp-graph/src/exp_graph/metrics/protocol.py`
- Create: `exp-graph/src/exp_graph/tasks/protocol_adapter.py`
- Test: `exp-graph/tests/test_protocol_adapter_iface.py`

- [ ] **Step 1: Write the failing test** — `exp-graph/tests/test_protocol_adapter_iface.py`:

```python
from exp_graph.aggregator.protocol_final import ProtocolFinalResult
from exp_graph.metrics.protocol import ProtocolAgentStepMetric, ProtocolGlobalStepMetric
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter


def test_protocol_final_result_fields():
    r = ProtocolFinalResult(
        final_key="9", final_answer=9, selected_primary="vote",
        aggregation_method="vote", primary_metric=1.0, exact_match=True,
        supporting_agents=[1], answer_agent_ids=[0, 1], top_ratio=1.0,
    )
    assert r.final_key == "9" and r.exact_match is True


def test_protocol_step_metric_fields():
    a = ProtocolAgentStepMetric(
        step_idx=0, phase="after_step", topology="mesh", agent_id=0,
        active_sender=True, active_receiver=False, coverage_ratio=0.5,
        primary_metric=1.0, exact_match=False, sent_count=1, received_count=0,
    )
    g = ProtocolGlobalStepMetric(
        step_idx=0, phase="after_step", topology="mesh", mean_coverage=0.5,
        min_coverage=0.0, max_coverage=1.0, mean_primary_metric=0.5,
        best_primary_metric=1.0, worst_primary_metric=0.0,
        exact_match_agents=0, full_coverage_agents=0, vote_top_ratio=1.0,
    )
    assert a.coverage_ratio == 0.5 and g.mean_coverage == 0.5


def test_protocol_task_adapter_is_abstract():
    assert hasattr(ProtocolTaskAdapter, "finalize_protocol")
    assert hasattr(ProtocolTaskAdapter, "build_protocol_step_metrics")
    assert getattr(ProtocolTaskAdapter.finalize_protocol, "__isabstractmethod__", False) is False  # has a default
```

- [ ] **Step 2: Run to verify it fails** — `uv run --directory exp-graph --extra dev python -m pytest tests/test_protocol_adapter_iface.py -q` → FAIL (modules missing).

- [ ] **Step 3: Implement**

`exp-graph/src/exp_graph/aggregator/protocol_final.py`:

```python
"""Generic, task-agnostic final aggregation (vote-only) for protocol runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState


class ProtocolFinalResult(BaseModel):
    """Task-agnostic final aggregation result."""

    final_key: str
    final_answer: Any = None
    selected_primary: str = "vote"
    aggregation_method: str = "vote"
    primary_metric: float = 0.0          # task-defined; higher-is-better for success-rate tasks
    exact_match: bool = False
    supporting_agents: list[int] = Field(default_factory=list)
    answer_agent_ids: list[int] = Field(default_factory=list)
    top_ratio: float | None = None


class _VoteAdapter(Protocol):
    def extract_protocol_answer(self, belief_state: Any) -> Any: ...
    def protocol_answer_key(self, answer: Any) -> str: ...
    def score_protocol_answer(self, answer: Any, global_task: dict[str, Any]) -> dict[str, Any]: ...


def run_protocol_vote_aggregation(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: _VoteAdapter,
    answer_agent_ids: list[int],
) -> ProtocolFinalResult:
    """Group the holders' answers by canonical key, pick the majority, score it."""
    groups: dict[str, list[int]] = defaultdict(list)
    answer_by_key: dict[str, Any] = {}
    for agent_id in answer_agent_ids:
        answer = task_adapter.extract_protocol_answer(agent_states[agent_id].belief_state)
        key = task_adapter.protocol_answer_key(answer)
        groups[key].append(agent_id)
        answer_by_key[key] = answer

    if not groups:
        scored = task_adapter.score_protocol_answer(None, global_task)
        return ProtocolFinalResult(
            final_key="UNKNOWN", final_answer=None, primary_metric=float(scored.get("primary_metric", 0.0)),
            exact_match=bool(scored.get("exact_match", False)),
            answer_agent_ids=list(answer_agent_ids), top_ratio=0.0,
        )

    top_key, supporting = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
    answer = answer_by_key[top_key]
    scored = task_adapter.score_protocol_answer(answer, global_task)
    return ProtocolFinalResult(
        final_key=top_key,
        final_answer=answer,
        selected_primary="vote",
        aggregation_method="vote",
        primary_metric=float(scored.get("primary_metric", 0.0)),
        exact_match=bool(scored.get("exact_match", False)),
        supporting_agents=sorted(supporting),
        answer_agent_ids=list(answer_agent_ids),
        top_ratio=len(supporting) / max(1, len(answer_agent_ids)),
    )
```

`exp-graph/src/exp_graph/metrics/protocol.py`:

```python
"""Generic, task-agnostic per-step protocol metrics."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Protocol

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState


class ProtocolAgentStepMetric(BaseModel):
    step_idx: int
    phase: str
    topology: str
    agent_id: int
    active_sender: bool
    active_receiver: bool
    coverage_ratio: float
    primary_metric: float
    exact_match: bool
    sent_count: int = 0
    received_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class ProtocolGlobalStepMetric(BaseModel):
    step_idx: int
    phase: str
    topology: str
    mean_coverage: float
    min_coverage: float
    max_coverage: float
    mean_primary_metric: float
    best_primary_metric: float
    worst_primary_metric: float
    exact_match_agents: int
    full_coverage_agents: int
    vote_top_ratio: float


class _MetricAdapter(Protocol):
    def compute_protocol_agent_metrics(self, *, belief_state: Any, global_task: dict[str, Any], n_agents: int) -> dict[str, Any]: ...
    def extract_protocol_answer(self, belief_state: Any) -> Any: ...
    def protocol_answer_key(self, answer: Any) -> str: ...


def build_protocol_step_metrics(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: _MetricAdapter,
    topology_name: str,
    step_idx: int,
    phase: str,
    send_counts: Counter[int],
    receive_counts: Counter[int],
) -> tuple[list[ProtocolAgentStepMetric], ProtocolGlobalStepMetric]:
    rows: list[ProtocolAgentStepMetric] = []
    for agent_id, state in enumerate(agent_states):
        m = task_adapter.compute_protocol_agent_metrics(
            belief_state=state.belief_state, global_task=global_task, n_agents=len(agent_states),
        )
        sent = int(send_counts.get(agent_id, 0))
        recv = int(receive_counts.get(agent_id, 0))
        rows.append(ProtocolAgentStepMetric(
            step_idx=step_idx, phase=phase, topology=topology_name, agent_id=agent_id,
            active_sender=sent > 0, active_receiver=recv > 0,
            coverage_ratio=float(m.get("coverage_ratio", 0.0)),
            primary_metric=float(m.get("primary_metric", 0.0)),
            exact_match=bool(m.get("exact_match", False)),
            sent_count=sent, received_count=recv, extra=dict(m),
        ))
    keys = [task_adapter.protocol_answer_key(task_adapter.extract_protocol_answer(s.belief_state)) for s in agent_states]
    top = max(Counter(keys).values()) / max(1, len(keys)) if keys else 0.0
    g = ProtocolGlobalStepMetric(
        step_idx=step_idx, phase=phase, topology=topology_name,
        mean_coverage=statistics.fmean(r.coverage_ratio for r in rows),
        min_coverage=min(r.coverage_ratio for r in rows),
        max_coverage=max(r.coverage_ratio for r in rows),
        mean_primary_metric=statistics.fmean(r.primary_metric for r in rows),
        best_primary_metric=max(r.primary_metric for r in rows),
        worst_primary_metric=min(r.primary_metric for r in rows),
        exact_match_agents=sum(1 for r in rows if r.exact_match),
        full_coverage_agents=sum(1 for r in rows if r.coverage_ratio >= 1.0),
        vote_top_ratio=top,
    )
    return rows, g
```

`exp-graph/src/exp_graph/tasks/protocol_adapter.py`:

```python
"""Task-agnostic protocol adapter interface for ProtocolRunner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from typing import Any

from exp_graph.agents.schemas import AgentState, BeliefState
from exp_graph.aggregator.protocol_final import ProtocolFinalResult, run_protocol_vote_aggregation
from exp_graph.messaging import OutboxMessage
from exp_graph.metrics.protocol import (
    ProtocolAgentStepMetric,
    ProtocolGlobalStepMetric,
    build_protocol_step_metrics,
)
from exp_graph.tasks.base import TaskAdapter


class ProtocolTaskAdapter(TaskAdapter, ABC):
    """Adapter that ProtocolRunner drives. CF and generic tasks both implement this.

    The 7 belief methods below carry the per-agent protocol semantics; the
    finalize/step-metric/answer methods let the runner stay task-agnostic.
    """

    # --- per-agent protocol belief lifecycle (already on CountFrequencyTaskAdapter) ---
    @abstractmethod
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState: ...
    @abstractmethod
    def format_protocol_init_prompt(self, *, global_task: dict[str, Any], local_observation: dict[str, Any]) -> str: ...
    @abstractmethod
    def validate_protocol_initial_belief_state(self, *, belief_state: BeliefState, local_observation: dict[str, Any], global_task: dict[str, Any]) -> BeliefState: ...
    @abstractmethod
    def merge_protocol_inbox(self, *, old_belief_state: BeliefState, inbox: list[OutboxMessage], global_task: dict[str, Any]) -> BeliefState: ...
    @abstractmethod
    def format_protocol_merge_prompt(self, *, merge_mode: str, global_task: dict[str, Any], local_observation: dict[str, Any], old_belief_state: BeliefState, inbox: list[OutboxMessage], deterministic_belief: BeliefState | None = None) -> str: ...
    @abstractmethod
    def apply_verified_protocol_merge(self, *, llm_belief_state: BeliefState, verified_belief_state: BeliefState) -> BeliefState: ...
    @abstractmethod
    def validate_protocol_belief_state(self, *, belief_state: BeliefState, global_task: dict[str, Any], n_agents: int, transport_belief_state: BeliefState | None = None) -> BeliefState: ...

    # --- answer extraction / scoring (used by generic aggregation + metrics) ---
    @abstractmethod
    def extract_protocol_answer(self, belief_state: BeliefState) -> Any: ...
    @abstractmethod
    def protocol_answer_key(self, answer: Any) -> str: ...
    @abstractmethod
    def score_protocol_answer(self, answer: Any, global_task: dict[str, Any]) -> dict[str, Any]:
        """Return at least {'primary_metric': float, 'exact_match': bool}."""
        ...
    @abstractmethod
    def compute_protocol_agent_metrics(self, *, belief_state: BeliefState, global_task: dict[str, Any], n_agents: int) -> dict[str, Any]:
        """Return at least {'coverage_ratio': float, 'primary_metric': float, 'exact_match': bool}."""
        ...

    # --- holder selection + finalize/metrics: generic defaults (CF overrides finalize/step) ---
    def answer_holders(self, *, topology_name: str, n_agents: int, star_center: int) -> list[int]:
        return list(range(n_agents))

    def finalize_protocol(self, *, agent_states: list[AgentState], global_task: dict[str, Any], topology_name: str, star_center: int = 0, average_include_min_coverage: float = 1.0, selected_primary: str = "topology_default", answer_agent_ids_override: list[int] | None = None) -> Any:
        ids = answer_agent_ids_override or self.answer_holders(topology_name=topology_name, n_agents=len(agent_states), star_center=star_center)
        return run_protocol_vote_aggregation(agent_states=agent_states, global_task=global_task, task_adapter=self, answer_agent_ids=ids)

    def build_protocol_step_metrics(self, *, agent_states: list[AgentState], global_task: dict[str, Any], topology_name: str, step_idx: int, phase: str, send_counts: Counter[int], receive_counts: Counter[int], average_include_min_coverage: float = 1.0) -> tuple[list[Any], Any]:
        return build_protocol_step_metrics(agent_states=agent_states, global_task=global_task, task_adapter=self, topology_name=topology_name, step_idx=step_idx, phase=phase, send_counts=send_counts, receive_counts=receive_counts)
```

- [ ] **Step 4: Run to verify it passes** — `uv run --directory exp-graph --extra dev python -m pytest tests/test_protocol_adapter_iface.py -q` → PASS.

- [ ] **Step 5: Guardrail** — `uv run --directory exp-graph --extra dev python -m pytest -q` → still **191 passed, 1 skipped** (we only ADDED files).

- [ ] **Step 6: Commit** — `git add exp-graph/src/exp_graph/aggregator/protocol_final.py exp-graph/src/exp_graph/metrics/protocol.py exp-graph/src/exp_graph/tasks/protocol_adapter.py exp-graph/tests/test_protocol_adapter_iface.py && git commit -m "feat(exp_graph): add task-agnostic ProtocolTaskAdapter + generic aggregation/metrics"`

---

## Task 2: Make `CountFrequencyTaskAdapter` the reference `ProtocolTaskAdapter` (CF unchanged)

**Files:**
- Modify: `exp-graph/src/exp_graph/tasks/count_frequency.py`
- Test: `exp-graph/tests/test_cf_is_protocol_adapter.py`

CF already has the 7 belief methods, `extract_protocol_counts`, `compute_protocol_agent_metrics`, `count_domain_keys`. We make it subclass `ProtocolTaskAdapter` and add the small answer/score methods + override `finalize_protocol`/`build_protocol_step_metrics` to delegate to the EXISTING `run_cf_final_aggregation`/`build_cf_step_metrics` (so CF output is byte-identical) + override `answer_holders` to call `answer_agents_for_topology`.

- [ ] **Step 1: Write the failing test** — `exp-graph/tests/test_cf_is_protocol_adapter.py`:

```python
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter


def test_cf_is_a_protocol_task_adapter():
    a = CountFrequencyTaskAdapter()
    assert isinstance(a, ProtocolTaskAdapter)


def test_cf_answer_key_and_score():
    a = CountFrequencyTaskAdapter()
    gt = a.build_global_task(array=[1, 1, 2], value_min=0, value_max=2)
    counts = {"1": 2, "2": 1}
    key = a.protocol_answer_key(counts)
    assert key == gt["answer_key"]                       # FREQ_JSON canonical
    scored = a.score_protocol_answer(counts, gt)
    assert scored["exact_match"] is True
    assert scored["primary_metric"] == 0.0               # CF primary_metric = RMSE (0 = perfect)
```

- [ ] **Step 2: Run to verify it fails** — `uv run --directory exp-graph --extra dev python -m pytest tests/test_cf_is_protocol_adapter.py -q` → FAIL.

- [ ] **Step 3: Implement.** In `count_frequency.py`:
  - Change `class CountFrequencyTaskAdapter(TaskAdapter):` → `class CountFrequencyTaskAdapter(ProtocolTaskAdapter):` (import `from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter`). NOTE: this import must not create a cycle — `protocol_adapter` imports `tasks.base` (fine) and aggregator/metrics generic (fine); it does NOT import count_frequency, so no cycle.
  - Add methods (place near the existing protocol methods):

```python
    def extract_protocol_answer(self, belief_state: BeliefState) -> dict[str, int]:
        return self.extract_protocol_counts(belief_state)

    def protocol_answer_key(self, answer: Any) -> str:
        return count_frequency_consensus_key(answer or {})

    def score_protocol_answer(self, answer: Any, global_task: dict[str, Any]) -> dict[str, Any]:
        domain = self.count_domain_keys(global_task)
        truth = canonicalize_counts(global_task["answer_counts"])
        pred = canonicalize_counts(answer or {})
        return {
            "primary_metric": compute_rmse(pred, truth, domain),   # RMSE; lower better
            "exact_match": pred == truth,
        }

    def answer_holders(self, *, topology_name: str, n_agents: int, star_center: int) -> list[int]:
        from exp_graph.aggregator.cf_final import answer_agents_for_topology
        return answer_agents_for_topology(topology_name=topology_name, n_agents=n_agents, star_center=star_center)

    def finalize_protocol(self, *, agent_states, global_task, topology_name, star_center=0, average_include_min_coverage=1.0, selected_primary="topology_default", answer_agent_ids_override=None):
        from exp_graph.aggregator.cf_final import run_cf_final_aggregation
        return run_cf_final_aggregation(
            agent_states=agent_states, global_task=global_task, task_adapter=self,
            topology_name=topology_name, star_center=star_center,
            average_include_min_coverage=average_include_min_coverage,
            selected_primary=selected_primary, answer_agent_ids_override=answer_agent_ids_override,
        )

    def build_protocol_step_metrics(self, *, agent_states, global_task, topology_name, step_idx, phase, send_counts, receive_counts, average_include_min_coverage=1.0):
        from exp_graph.metrics.cf_protocol import build_cf_step_metrics
        return build_cf_step_metrics(
            agent_states=agent_states, global_task=global_task, task_adapter=self,
            topology_name=topology_name, step_idx=step_idx, phase=phase,
            send_counts=send_counts, receive_counts=receive_counts,
            average_include_min_coverage=average_include_min_coverage,
        )
```
  (`compute_rmse`, `canonicalize_counts`, `count_frequency_consensus_key` are already defined in this module.) Use local imports inside `finalize_protocol`/`build_protocol_step_metrics`/`answer_holders` to avoid import cycles (cf_final imports count_frequency).

- [ ] **Step 4: Run to verify it passes** — `uv run --directory exp-graph --extra dev python -m pytest tests/test_cf_is_protocol_adapter.py -q` → PASS.

- [ ] **Step 5: Guardrail** — full exp_graph suite still **191 passed, 1 skipped**.

- [ ] **Step 6: Commit** — `git add exp-graph/src/exp_graph/tasks/count_frequency.py exp-graph/tests/test_cf_is_protocol_adapter.py && git commit -m "feat(exp_graph): CountFrequencyTaskAdapter implements ProtocolTaskAdapter (CF unchanged, delegates to cf_final/cf_protocol)"`

---

## Task 3: Reroute `ProtocolRunner` through the adapter (result model accepts generic types)

**Files:**
- Modify: `exp-graph/src/exp_graph/runner/protocol.py`
- Test: `exp-graph/tests/test_protocol_runner_generic_wiring.py`

- [ ] **Step 1: Write the failing test** — assert the runner accepts a `ProtocolTaskAdapter` type and that CF still produces a `CFProtocolFinalResult`:

```python
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter
from exp_graph.aggregator.cf_final import CFProtocolFinalResult


def test_cf_protocol_runner_still_returns_cf_result():
    adapter = CountFrequencyTaskAdapter()
    gt = adapter.build_global_task(array=[1, 2, 1, 3], value_min=0, value_max=3)
    cfg = ProtocolRunnerConfig(topology_name="tree", n_agents=4, merge_mode="deterministic", init_mode="deterministic")
    result = ProtocolRunner(config=cfg, task_adapter=adapter, global_task=gt).run()
    assert isinstance(result.final_result, CFProtocolFinalResult)   # CF path preserved
    summary = result.to_summary_dict()
    assert "FinalRMSE" in summary
```

- [ ] **Step 2: Run to verify it fails or passes** — it may already PASS (CF unchanged); if so, this test just locks behavior. Run it.

- [ ] **Step 3: Implement the reroute.** In `protocol.py`:
  - Change the import/type hint: `task_adapter: CountFrequencyTaskAdapter` → `task_adapter: "ProtocolTaskAdapter"` in `ProtocolRunner.__init__` and `_MergeOutcome`/helpers as needed (import `from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter`).
  - Replace the module-level call `final_result = run_cf_final_aggregation(...)` (protocol.py:386) with `final_result = self.task_adapter.finalize_protocol(agent_states=agent_states, global_task=self.global_task, topology_name=self.config.topology_name, star_center=self.config.star_center, average_include_min_coverage=self.config.average_include_min_coverage, selected_primary=self.config.selected_primary, answer_agent_ids_override=self._metadata_answer_agent_ids())`.
  - Replace `build_cf_step_metrics(...)` in `_record_metrics` (protocol.py:983) with `self.task_adapter.build_protocol_step_metrics(...)` (same kwargs minus task_adapter).
  - Generalize `ProtocolExperimentResult` typing: change `final_result: CFProtocolFinalResult` → `final_result: CFProtocolFinalResult | ProtocolFinalResult`; `agent_step_metrics: list[CFAgentStepMetric | ProtocolAgentStepMetric]`; `global_step_metrics: list[CFGlobalStepMetric | ProtocolGlobalStepMetric]` (import the generic types). Keep field names.
  - Make `to_summary_dict()` robust: when `final_result` is a `CFProtocolFinalResult`, emit the existing CF keys (unchanged). When it's a generic `ProtocolFinalResult`, emit generic keys (`PrimaryMetric`, `ExactMatch`, `VoteTopRatio`, `FinalKey`, and set `FinalRMSE`=None or omit). Use `isinstance`/`getattr` so CF output is byte-identical. (Add `Task`, `Topology`, `Agents`, `Seed`, `MergeMode`, `InitMode`, `TotalSteps/Messages/ModelCalls/Tokens` as before; those are generic already. The CF-only keys read from the CF result.)

- [ ] **Step 4: Run** — the new test PASSES; `to_summary_dict` for CF unchanged.

- [ ] **Step 5: Guardrail (critical)** — full exp_graph suite still **191 passed, 1 skipped**. test_protocol_runner.py, test_mas_runner.py, test_mas_pipeline.py, test_end_to_end.py especially must stay green. If any fail, the reroute changed CF behavior — fix until identical.

- [ ] **Step 6: Commit** — `git add exp-graph/src/exp_graph/runner/protocol.py exp-graph/tests/test_protocol_runner_generic_wiring.py && git commit -m "refactor(exp_graph): ProtocolRunner finalizes/metrics via ProtocolTaskAdapter (CF byte-identical)"`

---

## Task 4: A minimal generic protocol task (`global_max`) proving the non-CF path

**Files:**
- Create: `exp-graph/src/exp_graph/tasks/global_max.py`
- Test: `exp-graph/tests/test_protocol_adapter_generic.py`

This is the proof that the generalized engine runs a non-CF structured-answer task end-to-end. `GlobalMaxTaskAdapter(ProtocolTaskAdapter)` shards a list of ints; each agent's belief carries its running max; merge = max over inbox; answer = the int; `protocol_answer_key` = str(int); `score_protocol_answer` = {primary_metric: 1.0 if==truth else 0.0, exact_match: ==truth}. Uses the generic `finalize_protocol`/`build_protocol_step_metrics` defaults (vote). Implement the 7 belief methods minimally (deterministic merge; LLM prompts can be simple — the test uses `merge_mode="deterministic"`, `init_mode="deterministic"`, so only `initial_protocol_belief` + `merge_protocol_inbox` are exercised).

- [ ] **Step 1: Write the failing test** — `tests/test_protocol_adapter_generic.py`:

```python
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.aggregator.protocol_final import ProtocolFinalResult
from exp_graph.tasks.global_max import GlobalMaxTaskAdapter


def test_global_max_runs_through_protocol_runner():
    adapter = GlobalMaxTaskAdapter()
    gt = adapter.build_global_task(values=[3, 1, 9, 2, 5, 8, 4, 0])
    cfg = ProtocolRunnerConfig(topology_name="mesh_star", n_agents=8, merge_mode="deterministic", init_mode="deterministic")
    result = ProtocolRunner(config=cfg, task_adapter=adapter, global_task=gt).run()
    assert isinstance(result.final_result, ProtocolFinalResult)
    assert result.final_result.final_key == "9"
    assert result.final_result.exact_match is True
    assert result.final_result.primary_metric == 1.0
```

- [ ] **Step 2: Run → fail.** **Step 3: Implement** `GlobalMaxTaskAdapter` (full belief lifecycle for the deterministic path; `build_global_task(values=...)` stores `values`, `answer=max(values)`, `answer_key=str(max)`; `split_into_local_observations` shards; `initial_protocol_belief` sets belief with structured_state `{"task_name":"global_max","max":local_max}` and consensus_key=str(local_max); `merge_protocol_inbox` takes max over self+inbox; `extract_protocol_answer` returns the int; `compute_protocol_agent_metrics` returns coverage (1/n..1) + primary_metric(1.0 if local max==global truth else 0.0) + exact_match). Implement LLM prompt methods as simple JSON-returning prompts for completeness (not exercised by this deterministic test). **Step 4: Run → pass. Step 5: Guardrail 191. Step 6: Commit** `feat(exp_graph): add GlobalMaxTaskAdapter proving the generic protocol path`.

---

## Task 5: Generalize evidence summary keys for evolution (additive, CF back-compat)

**Files:**
- Modify: `exp-graph/src/exp_graph/runner/protocol.py` (`to_summary_dict` — already touched in Task 3; here add generic primary-metric keys)
- Modify: `exp-graph/src/exp_graph/mas/runner.py` (`summary_to_aggregate_row` — accept generic summaries)
- Test: `exp-graph/tests/test_generic_summary_evidence.py`

- [ ] Add `PrimaryMetric`, `PrimaryMetricName` (e.g. "rmse" for CF, "success" for generic), `ExactMatch` to `to_summary_dict` for BOTH paths (CF sets PrimaryMetric=rmse, PrimaryMetricName="rmse"; generic sets PrimaryMetric=primary_metric, PrimaryMetricName from the task). Keep all existing CF keys. Update `summary_to_aggregate_row` to read `PrimaryMetric` with fallback to `FinalRMSE`, emitting both `MeanFinalRMSE` (CF) and a generic `MeanPrimaryMetric` so Plan 3's generalized ministers can consume either. Test: a generic summary maps without KeyError; a CF summary still yields `MeanFinalRMSE`. Guardrail 191. Commit.

---

## Task 6: Final verification + docs

- [ ] Run the FULL exp_graph suite + the new generic tests: `uv run --directory exp-graph --extra dev python -m pytest -q` → **≥191 passed** (existing) **+ new tests**, 1 skipped, 0 failed.
- [ ] Run masbench suite (ensure Plan 1 still green): `uv run --directory masbench --extra dev python -m pytest -q` → 28 passed.
- [ ] Append a short "Plan 2 done — generic protocol engine" note to `masbench/README.md` Status section.
- [ ] Commit docs.

---

## Self-Review (author)

**Spec coverage:** Generalization seams from spec §2.1 / Agent-B blueprint → Task 1 (interface+generic agg/metrics), Task 2 (CF reference impl), Task 3 (runner reroute + result typing), Task 4 (non-CF proof), Task 5 (evidence keys for evolution). The temporal-DAG generator + ProtocolGraphSpec need NO change (already task-agnostic) — correctly out of scope. Plan 3 consumes this: SiloProtocolAdapter(ProtocolTaskAdapter) + evolution-objective generalization + the 5 skill improvements.

**Guardrail discipline:** every task re-runs the 191-test baseline; CF delegation (Task 2) + isinstance-guarded `to_summary_dict` (Task 3) keep CF byte-identical. The generic path is proven independently by Task 4.

**Risks:** (a) import cycle count_frequency↔protocol_adapter↔cf_final — mitigated by local imports in the CF delegation methods (Task 2) and protocol_adapter NOT importing count_frequency. (b) pydantic union typing on `ProtocolExperimentResult.final_result` — if serialization of the CF subtype regresses, Task 3's guardrail (test_protocol_runner) catches it. (c) `to_summary_dict` divergence — locked by the Task 3 test asserting `FinalRMSE` present for CF.
