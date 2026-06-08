"""Paper-grade experiment harness: compare arms on Silo-Bench (Plan 4 Task 6).

``run_benchmark`` orchestrates the *existing* engine/evolve building blocks into
a Table-1-style comparison of communication-structure policies ("arms") over a
grid of Silo-Bench conditions ``(case_id, n_agents)`` and random seeds. Nothing
new is invented about how a run executes -- every arm routes through the same
:class:`~exp_graph.runner.protocol.ProtocolRunner` and the same masbench scorer,
so the metrics are directly comparable. The harness only decides *which structure
each arm uses* and then aggregates.

Arms
----
* **fixed** -- planner-OFF baselines. For each topology in ``fixed_topologies``
  we force that named protocol topology through :func:`engine.run_fixed_protocol`
  (the protocol path, not the legacy ``SynchronousRunner``; see that function for
  why). The per-condition *best* fixed topology is reported as the **oracle
  fixed** baseline, with the full per-topology breakdown retained.
* **select** -- QueenBee ``topology_select`` (``use_planner=True``).
* **graphgen** -- QueenBee ``graph_generate`` (the emperor LLM invents a temporal
  DAG). ``num_graph_candidates`` is bumped to >1 by default so the structural
  motif prior can matter; accumulated motif evidence from earlier arms' generated
  specs is passed in to activate that prior.
* **evolved** -- the gated self-evolution loop (:func:`evolve.run_evolution`) run
  ONCE per ``(case-set, n_agents)`` on the train seeds, then its post-evolution
  topology selection is evaluated on the held-out/test seeds. The gate decision
  is attached to every condition that the evolve run covered.

Outputs (written under ``out`` when provided)
---------------------------------------------
* ``results.json`` -- raw per-run records (``runs``) plus per-condition and
  overall aggregates (``conditions`` / ``overall``).
* ``results.csv`` -- one row per condition x arm with mean +/- std columns.
* ``report.md`` -- a markdown table per condition (arm | success | partial |
  msgs | calls | tokens), the best arm per condition bolded, and a top summary
  line of overall success per arm.

Offline honesty (fake LLM)
--------------------------
With ``--llm fake`` every run is deterministic and Silo's offline path is
topology-invariant on *success* (a case is solved or not, the same for every
topology). The harness still runs end to end and the table is well-formed; the
arm comparison only becomes scientifically meaningful with a real LLM (or
multi-seed runs that genuinely differ per topology). The ``evolved`` arm's gate
is made non-degenerate offline exactly as ``masbench evolve`` does -- via a small
synthetic multi-topology held-out set plus a baseline incumbent (see
:mod:`masbench.evolve`).
"""

from __future__ import annotations

import csv
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.llm.base import LLMClient
from exp_graph.mas.motifs import aggregate_motif_losses

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.engine import _build_llm_client, run_fixed_protocol, run_instance
from masbench.evolve import (
    INCUMBENT_BASELINE_TOPOLOGY,
    accepting_held_out_rows,
    run_evolution,
)

# Default planner-OFF fixed baselines. These are *protocol-schedule* topology
# names understood by ``build_protocol_schedule`` (chain/tree/mesh_star/
# one_peer_exponential_dag_star), which is why the fixed arm runs via the
# protocol path (engine.run_fixed_protocol) rather than the SynchronousRunner.
DEFAULT_FIXED_TOPOLOGIES = (
    "tree",
    "mesh_star",
    "one_peer_exponential_dag_star",
    "chain",
)

# Default arm set when the caller does not specify one.
DEFAULT_ARMS = ("fixed", "select", "graphgen")

# Default candidate count for the graphgen arm. >1 so the structural-motif prior
# can actually change which generated DAG is picked (it is inert with a single
# surviving candidate).
DEFAULT_GRAPHGEN_CANDIDATES = 4

# The metric columns aggregated and rendered, in display order.
_METRIC_KEYS = ("success", "partial", "n_messages", "n_model_calls", "tokens")


def _mean_std(values: list[float]) -> dict[str, float]:
    """Population mean and std of ``values`` (std 0 for a single sample)."""
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "std": 0.0}
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return {"mean": mean, "std": math.sqrt(var)}


def aggregate_condition(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate raw per-run records into per-arm mean +/- std.

    ``runs`` are the flat per-run dicts produced by :func:`_run_record` (one per
    arm x seed [x topology]). Returns ``{arm: {metric: {"mean","std"}, "n": int}}``
    where each metric is one of :data:`_METRIC_KEYS` (success/partial are coerced
    to floats so a boolean success rate falls out of the mean).
    """
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_arm.setdefault(run["arm"], []).append(run)

    aggregates: dict[str, Any] = {}
    for arm, arm_runs in by_arm.items():
        entry: dict[str, Any] = {"n": len(arm_runs)}
        for metric in _METRIC_KEYS:
            entry[metric] = _mean_std([float(r[metric]) for r in arm_runs])
        aggregates[arm] = entry
    return aggregates


def _run_record(
    arm: str,
    instance: BenchmarkInstance,
    seed: int,
    score: ScoreResult,
    *,
    topology: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One flat raw per-run record (JSON-serializable)."""
    record = {
        "arm": arm,
        "case_id": instance.case_id,
        "n_agents": instance.n_agents,
        "seed": seed,
        "topology": topology if topology is not None else score.extra.get("topology"),
        "success": bool(score.success),
        "partial": float(score.partial or 0.0),
        "n_messages": int(score.n_messages),
        "n_model_calls": int(score.n_model_calls),
        "tokens": int(score.tokens),
        "final_answer": score.final_answer,
    }
    if extra:
        record.update(extra)
    return record


# --------------------------------------------------------------------------- #
# Crash-safety: per-run isolation + checkpoint + resume (Plan 5 Task 2).      #
# --------------------------------------------------------------------------- #


# A run unit's identity. Used BOTH to decide whether a loaded record means the
# run is already done (resume) and to dedupe records read back from runs.jsonl.
# The fixed arm sweeps several topologies per (case,n,seed), so its key carries
# the per-topology ``fixed_topology``; every other arm leaves that None.
def _run_key(record: dict[str, Any]) -> tuple:
    """Stable identity tuple for one run record: (arm, case, n, seed, topology)."""
    return (
        record["arm"],
        record["case_id"],
        record["n_agents"],
        record["seed"],
        record.get("fixed_topology"),
    )


def _failed_record(
    arm: str,
    instance: BenchmarkInstance,
    seed: int,
    exc: BaseException,
    *,
    topology: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A FAILED run record: same shape as a normal one, metrics zeroed + error.

    Produced when an individual run raises (incl. :class:`LLMTimeoutError`) so the
    grid keeps going instead of aborting. ``success=False``, all counts 0, and the
    error type+message is stored under ``extra["error"]`` for later triage.
    """
    record: dict[str, Any] = {
        "arm": arm,
        "case_id": instance.case_id,
        "n_agents": instance.n_agents,
        "seed": seed,
        "topology": topology,
        "success": False,
        "partial": 0.0,
        "n_messages": 0,
        "n_model_calls": 0,
        "tokens": 0,
        "final_answer": None,
        "error": f"{type(exc).__name__}: {exc}",
    }
    if extra:
        record.update(extra)
    return record


def _run_unit(
    produce: Callable[[], ScoreResult],
    *,
    arm: str,
    instance: BenchmarkInstance,
    seed: int,
    topology: str | None,
    extra: dict[str, Any] | None = None,
    extra_from_score: Callable[[ScoreResult], dict[str, Any]] | None = None,
    progress: "_Progress | None" = None,
) -> dict[str, Any]:
    """Run ONE unit in isolation -> a real record, or a failed record on any error.

    ``produce`` is a thunk that performs the single underlying run and returns its
    :class:`ScoreResult`. Any exception it raises (incl. ``LLMTimeoutError``) is
    swallowed into a FAILED record (via :func:`_failed_record`) carrying the same
    ``arm``/``topology``/``extra``, so a single hung or crashing run can never
    abort the surrounding grid. ``extra_from_score`` (when given) derives extra
    record fields from the successful score (e.g. graphgen's generated-graph
    diagnostics); it is only consulted on the success path.

    This is the SINGLE chokepoint every produced run-record passes through in BOTH
    the sequential and the ``--workers`` parallel path, so it is where the live
    progress tick belongs (Plan 5 Task 5): the underlying run is timed with
    ``time.monotonic()`` and, once the record is built (success OR failed),
    :meth:`_Progress.tick` is called (thread-safe via its own lock) exactly once.
    Resumed/skipped units never reach here, so they are not ticked (they are
    pre-counted into the header's ``resumed``).

    Only ``Exception`` is isolated (``LLMTimeoutError`` is a ``RuntimeError``); a
    ``KeyboardInterrupt``/``SystemExit`` still propagates so an operator can abort
    a long grid with Ctrl-C and finished runs stay safely checkpointed on disk.
    """
    started = time.monotonic()
    try:
        score = produce()
    except Exception as exc:  # noqa: BLE001 - isolation: one bad run never aborts the grid
        record = _failed_record(
            arm, instance, seed, exc, topology=topology, extra=extra
        )
    else:
        merged = dict(extra or {})
        if extra_from_score is not None:
            merged.update(extra_from_score(score))
        record = _run_record(
            arm, instance, seed, score, topology=topology, extra=merged or None
        )
    if progress is not None:
        progress.tick(record, time.monotonic() - started)
    return record


class _Checkpoint:
    """Append-as-you-go run log + completed-key set for crash-safe resume.

    Threaded through ``run_benchmark`` into the per-arm runners. Each produced run
    record is :meth:`append`-ed immediately as one JSON line to ``out/runs.jsonl``
    (so a crash mid-grid keeps the finished runs on disk); :meth:`done` reports
    whether a run key was already present on resume so the runner can skip it. A
    lock guards the file + the key set so this stays correct under the sequential
    grid today and the ``--workers`` pool added in Plan 5 Task 3.
    """

    def __init__(
        self, path: Path | None, *, completed_keys: set[tuple] | None = None
    ) -> None:
        # ``path`` is None when no ``out`` dir was given: runs are still isolated
        # and tracked in-memory, but nothing is persisted to disk.
        self._path = path
        self._lock = threading.Lock()
        self._completed: set[tuple] = set(completed_keys or set())

    def done(self, key: tuple) -> bool:
        """True if a record with this :func:`_run_key` is already complete."""
        with self._lock:
            return key in self._completed

    def append(self, record: dict[str, Any]) -> None:
        """Persist one record (success or failed) and mark its key complete."""
        line = json.dumps(record, default=str) + "\n"
        with self._lock:
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            self._completed.add(_run_key(record))


def _fmt_hms(seconds: float) -> str:
    """Render an elapsed duration as ``H:MM:SS`` (no fractional part)."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


class _Progress:
    """Live per-run progress printer for a long ``run_benchmark`` grid.

    A real-LLM grid can run for hours; before this, ``run_benchmark`` printed
    nothing until the very end, so a hung run looked identical to slow progress.
    This prints ONE startup :meth:`header` line and then ONE :meth:`tick` line per
    finished run-unit (success or failed). The single hook lives in
    :func:`_run_unit` -- the chokepoint every produced record passes through in
    BOTH the sequential and the ``--workers`` parallel path -- so progress covers
    both with one wiring point.

    ``tick`` is called from worker threads under ``--workers>1``; a lock guards the
    counters + the print so lines never interleave and ``done`` is a clean
    monotone 1..to_run. Every method is a no-op when ``enabled`` is False
    (``--quiet`` / ``progress=False``), so the disabled path costs only a branch.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.total = 0
        self.to_run = 0
        self.done = 0
        self.ok = 0
        self.start = time.monotonic()
        self._lock = threading.Lock()

    def header(
        self,
        *,
        total: int,
        resumed: int,
        to_run: int,
        arms: list[str],
        n_conditions: int,
        n_seeds: int,
        workers: int,
        out: str | Path | None,
    ) -> None:
        """Print the one-line startup banner (counts, parallelism, out dir)."""
        self.total = total
        self.to_run = to_run
        if not self.enabled:
            return
        resumed_note = f", {resumed} already done (resume)" if resumed else ""
        out_note = f" | out={out}" if out is not None else ""
        print(
            f"bench: {total} run-units "
            f"(arms={len(arms)} × conditions={n_conditions} × seeds={n_seeds}), "
            f"{to_run} to run{resumed_note} | workers={workers}{out_note}",
            flush=True,
        )

    def tick(self, record: dict[str, Any], elapsed_s: float) -> None:
        """Account for + print one finished run-unit (thread-safe)."""
        with self._lock:
            self.done += 1
            ok = bool(record.get("success"))
            if ok:
                self.ok += 1
            if not self.enabled:
                return
            cumulative = _fmt_hms(time.monotonic() - self.start)
            arm = record.get("arm", "?")
            case_id = record.get("case_id", "?")
            n = record.get("n_agents", "?")
            seed = record.get("seed", "?")
            tokens = record.get("tokens", 0)
            status = "ok" if ok else "FAIL"
            line = (
                f"[{self.done}/{self.to_run}] {cumulative} "
                f"{arm} {case_id} n{n} seed{seed} → {status} "
                f"tok={tokens} ({elapsed_s:.1f}s) | success {self.ok}/{self.done}"
            )
            error = record.get("error")
            if error:
                line += f"  err={error}"
            print(line, flush=True)


def _load_checkpoint(out: Path, *, resume: bool) -> tuple[_Checkpoint, list[dict[str, Any]]]:
    """Prepare ``out/runs.jsonl`` and return ``(_Checkpoint, prior_records)``.

    With ``resume`` and an existing log: read it, dedupe by :func:`_run_key`
    (last-writer-wins), seed the checkpoint's completed set with those keys, and
    return the deduped prior records so they fold into the final aggregate.
    Without resume: truncate any existing log so a re-run starts fresh and never
    double-counts.
    """
    out.mkdir(parents=True, exist_ok=True)
    path = out / "runs.jsonl"

    prior: list[dict[str, Any]] = []
    if resume and path.is_file():
        by_key: dict[tuple, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            by_key[_run_key(record)] = record
        prior = list(by_key.values())
        # Rewrite the deduped set so the on-disk log matches what we resume from.
        with path.open("w", encoding="utf-8") as fh:
            for record in prior:
                fh.write(json.dumps(record, default=str) + "\n")
    else:
        # Fresh run: drop any stale log so appended records don't double-count.
        path.write_text("", encoding="utf-8")

    completed = {_run_key(r) for r in prior}
    return _Checkpoint(path, completed_keys=completed), prior


def _cfg_for(cfg_base: RunConfig, n_agents: int, **overrides: Any) -> RunConfig:
    """Clone ``cfg_base`` with ``n_agents`` pinned and any per-arm overrides."""
    return RunConfig(**{**asdict(cfg_base), "n_agents": n_agents, **overrides})


def _condition_key(case_id: str, n_agents: int) -> str:
    return f"{case_id}|n{n_agents}"


def _all_unit_keys(
    instances: list[BenchmarkInstance],
    arms: list[str],
    *,
    seeds: list[int],
    fixed_topologies: list[str],
) -> list[tuple]:
    """Enumerate every run-unit's :func:`_run_key`-shaped identity tuple.

    The SINGLE source of truth for "how many run-units does this grid have" --
    used to compute ``total``/``resumed`` for the progress header so the count is
    correct for BOTH the sequential and the ``--workers`` path (each path produces
    exactly one record per key here). Mirrors the per-arm expansion of both
    execution paths: the fixed arm fans out per topology (its key carries the
    topology), select/graphgen are one unit per (instance, seed), and the evolved
    arm evaluates only on the held-out *test* seed (``seeds[-1]``).
    """
    test_seeds = [seeds[-1]] if seeds else [0]
    keys: list[tuple] = []
    for arm in arms:
        if arm == "fixed":
            for instance in instances:
                for topology in fixed_topologies:
                    for seed in seeds:
                        keys.append(
                            ("fixed", instance.case_id, instance.n_agents, seed, topology)
                        )
        elif arm in ("select", "graphgen"):
            for instance in instances:
                for seed in seeds:
                    keys.append(
                        (arm, instance.case_id, instance.n_agents, seed, None)
                    )
        elif arm == "evolved":
            for instance in instances:
                for seed in test_seeds:
                    keys.append(
                        ("evolved", instance.case_id, instance.n_agents, seed, None)
                    )
        else:
            raise SystemExit(
                f"unknown arm '{arm}' (valid: fixed, select, graphgen, evolved)"
            )
    return keys


def run_benchmark(
    adapter: SiloBenchAdapter,
    *,
    cases: list[str] | None = None,
    levels: list[str] | None = None,
    agent_counts: list[int] | None = None,
    seeds: tuple[int, ...] | list[int] = (0,),
    arms: list[str] | tuple[str, ...] = DEFAULT_ARMS,
    cfg_base: RunConfig,
    fixed_topologies: list[str] | tuple[str, ...] | None = None,
    graphgen_candidates: int = DEFAULT_GRAPHGEN_CANDIDATES,
    out: str | Path | None = None,
    resume: bool = False,
    workers: int = 1,
    progress: bool = True,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Run the requested ARMS over a Silo-Bench grid and aggregate a Table-1.

    See the module docstring for the arm definitions and outputs. Returns the
    full results dict (``runs`` / ``conditions`` / ``overall`` / ``arms``); also
    writes ``results.json`` + ``results.csv`` + ``report.md`` under ``out`` when
    given.

    Crash-safety (Plan 5 Task 2): when ``out`` is given, every individual run is
    isolated (any exception -> a FAILED record, never an abort) and each produced
    record is appended immediately to ``out/runs.jsonl``. With ``resume=True`` an
    existing ``runs.jsonl`` is read back, already-finished runs are SKIPPED (not
    re-executed) and folded into the final aggregate; without resume the log is
    truncated so a re-run starts fresh. ``resume`` requires ``out`` (it is the
    checkpoint location) -- it is silently inert when ``out`` is None.

    Concurrency (Plan 5 Task 3): the grid is embarrassingly parallel and the
    underlying LLM calls are I/O-bound (they release the GIL), so ``workers > 1``
    dispatches the independent run-units to a
    :class:`~concurrent.futures.ThreadPoolExecutor` for near-linear speedup. The
    full task list (across all instances x arms x seeds, expanding the fixed
    arm's per-topology units) is built up front, ``ckpt.done`` units filtered
    out, then everything is submitted at once; each finished unit's record is
    appended through the lock-guarded ``ckpt.append`` so the checkpoint/resume
    semantics are unchanged and there are no double-appends. Two arm-specifics
    are handled before dispatch (see :func:`_build_parallel_tasks`): the graphgen
    motif prior is SNAPSHOTTED once (cross-run motif accumulation becomes a
    best-effort prior under concurrency; per-run correctness is unaffected) and
    the heavy ``run_evolution`` is run sequentially and once per ``n_agents``.
    ``workers <= 1`` keeps the exact sequential path below (incl. the incremental
    motif feed), so it is byte-for-byte the pre-concurrency behaviour.
    """
    arms = list(arms)
    seeds = list(seeds)
    fixed_topologies = list(fixed_topologies or DEFAULT_FIXED_TOPOLOGIES)

    # The offline fake LLM only understands the deterministic soldier prompts; the
    # llm_* merge/init modes emit prompts it cannot parse and would crash deep in
    # the client. Fail fast with an actionable message instead.
    if cfg_base.llm_provider == "fake" and (
        cfg_base.merge_mode != "deterministic"
        or cfg_base.init_mode != "deterministic"
    ):
        raise SystemExit(
            "the offline fake LLM only supports merge-mode=deterministic and "
            "init-mode=deterministic; pass a real --llm provider to use "
            f"merge-mode={cfg_base.merge_mode!r} / init-mode={cfg_base.init_mode!r}."
        )

    # One shared offline client keeps fake-LLM runs cheap and deterministic.
    client = llm_client or _build_llm_client(cfg_base)

    instances = list(
        adapter.iter_instances(levels=levels, agent_counts=agent_counts, cases=cases)
    )
    if not instances:
        raise SystemExit(
            "no Silo-Bench instances matched the given cases/agent-counts/levels"
        )

    # Checkpoint: when ``out`` is given, prepare ``out/runs.jsonl`` (truncate on a
    # fresh run, read+dedupe on resume) and seed the run list with prior records so
    # they fold into the final aggregate. With no ``out`` the checkpoint is an
    # in-memory no-op that still gives every run unit its isolation wrapper.
    if out is not None:
        ckpt, prior_records = _load_checkpoint(Path(out), resume=resume)
    else:
        ckpt, prior_records = _Checkpoint(None), []

    # Live progress (Plan 5 Task 5): enumerate every run-unit ONCE (the single
    # source of truth shared by both execution paths) to compute the header
    # counts. ``resumed`` = units already checkpointed (skipped, never ticked);
    # ``to_run`` = the units this session will actually execute + tick. The tick
    # itself fires from inside ``_run_unit`` (the per-unit chokepoint), so the
    # sequential and ``--workers`` paths are both covered by one hook.
    prog = _Progress(enabled=progress)
    unit_keys = _all_unit_keys(
        instances, arms, seeds=seeds, fixed_topologies=fixed_topologies
    )
    total = len(unit_keys)
    resumed = sum(1 for key in unit_keys if ckpt.done(key))
    prog.header(
        total=total,
        resumed=resumed,
        to_run=total - resumed,
        arms=arms,
        n_conditions=len(instances),
        n_seeds=len(seeds),
        workers=workers,
        out=out,
    )

    runs: list[dict[str, Any]] = list(prior_records)
    conditions: dict[str, Any] = {}
    # Accumulated motif evidence from graphgen-generated specs, fed back into
    # later graphgen runs so the structural-motif prior is active, not merely set.
    motif_rows: list[dict[str, Any]] = []

    # The evolved arm is heavy: run it ONCE per (case-set, n_agents) rather than
    # per (case, seed). Cache the evolve summary keyed by n_agents.
    evolved_summaries: dict[int, dict[str, Any]] = {}

    # Prior (resumed) records bucketed by condition so each condition aggregate is
    # built from EVERYTHING for it -- runs replayed from the checkpoint plus runs
    # produced this session -- not just what executed now.
    prior_by_cond: dict[str, list[dict[str, Any]]] = {}
    for record in prior_records:
        key = _condition_key(record["case_id"], record["n_agents"])
        prior_by_cond.setdefault(key, []).append(record)

    if workers > 1:
        # Parallel path: build the full not-yet-done task list up front (snapshot
        # the graphgen motif prior, pre-run the heavy evolution sequentially), then
        # dispatch every run-unit to a thread pool. Each finished record is folded
        # back through the lock-guarded ``ckpt.append`` so checkpoint/resume and the
        # no-double-append guarantee are unchanged. Aggregation is order-independent.
        new_runs = _run_parallel(
            instances,
            arms,
            cfg_base=cfg_base,
            seeds=seeds,
            fixed_topologies=fixed_topologies,
            graphgen_candidates=graphgen_candidates,
            motif_rows=motif_rows,
            evolved_summaries=evolved_summaries,
            adapter=adapter,
            cases=cases,
            levels=levels,
            client=client,
            ckpt=ckpt,
            workers=workers,
            progress=prog,
        )
        runs.extend(new_runs)
        # Aggregate each condition from EVERYTHING for it (resumed + freshly run).
        by_cond_runs: dict[str, list[dict[str, Any]]] = {
            k: list(v) for k, v in prior_by_cond.items()
        }
        for record in new_runs:
            by_cond_runs.setdefault(
                _condition_key(record["case_id"], record["n_agents"]), []
            ).append(record)
        for instance in instances:
            cond_key = _condition_key(instance.case_id, instance.n_agents)
            conditions[cond_key] = _aggregate_condition_block(
                instance, by_cond_runs.get(cond_key, [])
            )
    else:
        for instance in instances:
            cond_key = _condition_key(instance.case_id, instance.n_agents)
            new_runs = []
            n_agents = instance.n_agents

            for arm in arms:
                if arm == "fixed":
                    new_runs.extend(
                        _run_fixed_arm(
                            instance, cfg_base, seeds, fixed_topologies, client, ckpt,
                            progress=prog,
                        )
                    )
                elif arm == "select":
                    new_runs.extend(
                        _run_select_arm(
                            instance, cfg_base, seeds, client, ckpt, progress=prog
                        )
                    )
                elif arm == "graphgen":
                    arm_runs, new_motif_rows = _run_graphgen_arm(
                        instance,
                        cfg_base,
                        seeds,
                        client,
                        ckpt,
                        graphgen_candidates=graphgen_candidates,
                        motif_rows=motif_rows,
                        progress=prog,
                    )
                    new_runs.extend(arm_runs)
                    motif_rows.extend(new_motif_rows)
                elif arm == "evolved":
                    new_runs.extend(
                        _run_evolved_arm(
                            instance,
                            adapter,
                            cfg_base,
                            seeds,
                            cases=cases,
                            levels=levels,
                            client=client,
                            cache=evolved_summaries,
                            ckpt=ckpt,
                            progress=prog,
                        )
                    )
                else:
                    raise SystemExit(
                        f"unknown arm '{arm}' "
                        f"(valid: fixed, select, graphgen, evolved)"
                    )

            runs.extend(new_runs)
            # Aggregate the condition from resumed + freshly produced records.
            cond_runs = prior_by_cond.get(cond_key, []) + new_runs
            conditions[cond_key] = _aggregate_condition_block(instance, cond_runs)

    overall = _aggregate_overall(runs, arms)
    results = {
        "arms": arms,
        "seeds": seeds,
        "fixed_topologies": fixed_topologies,
        "conditions": conditions,
        "overall": overall,
        "runs": runs,
    }

    if out is not None:
        _write_outputs(results, Path(out))
    return results


# --------------------------------------------------------------------------- #
# Concurrency: parallel run-unit dispatch (Plan 5 Task 3).                    #
# --------------------------------------------------------------------------- #


@dataclass
class _RunTask:
    """One independent, not-yet-done run-unit to dispatch to the thread pool.

    ``produce`` is the record-producing thunk (already wrapped through
    :func:`_run_unit`, so it returns a real OR a failed record and never raises
    for an ordinary run error). Each ``_RunTask`` maps 1:1 to one
    ``(arm, case, n, seed[, topology])`` run-key, which the up-front
    ``ckpt.done`` filter guarantees is unique across the whole task list.
    """

    produce: Callable[[], dict[str, Any]]


def _run_parallel(
    instances: list[BenchmarkInstance],
    arms: list[str],
    *,
    cfg_base: RunConfig,
    seeds: list[int],
    fixed_topologies: list[str],
    graphgen_candidates: int,
    motif_rows: list[dict[str, Any]],
    evolved_summaries: dict[int, dict[str, Any]],
    adapter: SiloBenchAdapter,
    cases: list[str] | None,
    levels: list[str] | None,
    client: LLMClient,
    ckpt: _Checkpoint,
    workers: int,
    progress: _Progress | None = None,
) -> list[dict[str, Any]]:
    """Dispatch the full not-yet-done run-unit grid to a ``ThreadPoolExecutor``.

    The task list is built FIRST (every instance x arm x seed, the fixed arm
    expanded per topology), filtering out ``ckpt.done`` units, then all of it is
    submitted at once -- so scheduling is simple and overlap is maximal. As each
    future completes its record is appended through the lock-guarded
    ``ckpt.append`` (safe under concurrency) and collected; completion order does
    not matter because aggregation is order-independent.

    Two arm-specifics are resolved BEFORE dispatch:

    * **graphgen** -- the sequential "feed each generated run's motif row
      forward" cannot work under parallel dispatch, so ``motif_stats`` is
      SNAPSHOTTED once from ``motif_rows`` (possibly empty) and the same snapshot
      is passed to every graphgen unit. Cross-run motif accumulation is therefore
      a best-effort prior under ``workers>1``; per-run correctness is unaffected
      (the sequential ``workers<=1`` path keeps the incremental feed).
    * **evolved** -- the heavy ``run_evolution`` mutates a shared skill bank and
      is cached, so it is run SEQUENTIALLY and ONCE per distinct ``n_agents``
      (that still has a pending eval) BEFORE any parallel dispatch; only the
      independent per-instance ``run_fixed_protocol`` eval units go to the pool.
      Two ``run_evolution``s never run concurrently.

    Returns the list of freshly produced records (resumed records are not
    re-run and not included here).
    """
    tasks: list[_RunTask] = _build_parallel_tasks(
        instances,
        arms,
        cfg_base=cfg_base,
        seeds=seeds,
        fixed_topologies=fixed_topologies,
        graphgen_candidates=graphgen_candidates,
        motif_rows=motif_rows,
        evolved_summaries=evolved_summaries,
        adapter=adapter,
        cases=cases,
        levels=levels,
        client=client,
        ckpt=ckpt,
        progress=progress,
    )
    if not tasks:
        return []

    new_runs: list[dict[str, Any]] = []
    # The context manager's __exit__ waits for in-flight futures; that is fine
    # because each unit is bounded by the per-request timeout. A KeyboardInterrupt
    # propagates out (stops new scheduling); already-finished units are on disk.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(task.produce) for task in tasks]
        for future in as_completed(futures):
            record = future.result()
            ckpt.append(record)  # lock-guarded: safe + no double-append
            new_runs.append(record)
    return new_runs


def _build_parallel_tasks(
    instances: list[BenchmarkInstance],
    arms: list[str],
    *,
    cfg_base: RunConfig,
    seeds: list[int],
    fixed_topologies: list[str],
    graphgen_candidates: int,
    motif_rows: list[dict[str, Any]],
    evolved_summaries: dict[int, dict[str, Any]],
    adapter: SiloBenchAdapter,
    cases: list[str] | None,
    levels: list[str] | None,
    client: LLMClient,
    ckpt: _Checkpoint,
    progress: _Progress | None = None,
) -> list[_RunTask]:
    """Build the full list of not-yet-done run-units across the whole grid.

    Each appended task produces exactly one record for one unique run-key (the
    ``ckpt.done`` filter is applied here, so the pool never sees a duplicate or
    an already-finished unit). The graphgen motif snapshot and the sequential
    pre-run of the evolved arm's ``run_evolution`` (see :func:`_run_parallel`)
    happen here, before any task is dispatched. ``progress`` (when given) is
    threaded into each task's :func:`_run_unit` so the per-unit tick fires from
    the worker thread that finished it.
    """
    tasks: list[_RunTask] = []

    # graphgen: one motif-prior snapshot for the whole parallel batch.
    motif_stats = aggregate_motif_losses(motif_rows) if motif_rows else None

    for arm in arms:
        if arm == "fixed":
            for instance in instances:
                for topology in fixed_topologies:
                    for seed in seeds:
                        key = (
                            "fixed",
                            instance.case_id,
                            instance.n_agents,
                            seed,
                            topology,
                        )
                        if ckpt.done(key):
                            continue
                        tasks.append(
                            _fixed_task(
                                instance, cfg_base, seed, topology, client,
                                progress=progress,
                            )
                        )
        elif arm == "select":
            for instance in instances:
                for seed in seeds:
                    key = (
                        "select",
                        instance.case_id,
                        instance.n_agents,
                        seed,
                        None,
                    )
                    if ckpt.done(key):
                        continue
                    tasks.append(
                        _select_task(
                            instance, cfg_base, seed, client, progress=progress
                        )
                    )
        elif arm == "graphgen":
            for instance in instances:
                for seed in seeds:
                    key = (
                        "graphgen",
                        instance.case_id,
                        instance.n_agents,
                        seed,
                        None,
                    )
                    if ckpt.done(key):
                        continue
                    tasks.append(
                        _graphgen_task(
                            instance,
                            cfg_base,
                            seed,
                            client,
                            graphgen_candidates=graphgen_candidates,
                            motif_stats=motif_stats,
                            progress=progress,
                        )
                    )
        elif arm == "evolved":
            tasks.extend(
                _evolved_tasks(
                    instances,
                    cfg_base,
                    seeds,
                    adapter=adapter,
                    cases=cases,
                    levels=levels,
                    client=client,
                    cache=evolved_summaries,
                    ckpt=ckpt,
                    progress=progress,
                )
            )
        else:
            raise SystemExit(
                f"unknown arm '{arm}' (valid: fixed, select, graphgen, evolved)"
            )

    return tasks


def _fixed_task(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seed: int,
    topology: str,
    client: LLMClient,
    *,
    progress: _Progress | None = None,
) -> _RunTask:
    """A single fixed-arm (topology, seed) run-unit (mirrors :func:`_run_fixed_arm`)."""
    cfg = _cfg_for(cfg_base, instance.n_agents, use_planner=False, seed=seed)
    return _RunTask(
        produce=lambda: _run_unit(
            lambda: run_fixed_protocol(
                instance, cfg, topology=topology, llm_client=client
            ),
            arm="fixed",
            instance=instance,
            seed=seed,
            topology=topology,
            extra={"fixed_topology": topology},
            progress=progress,
        )
    )


def _select_task(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seed: int,
    client: LLMClient,
    *,
    progress: _Progress | None = None,
) -> _RunTask:
    """A single select-arm seed run-unit (mirrors :func:`_run_select_arm`)."""
    cfg = _cfg_for(
        cfg_base,
        instance.n_agents,
        use_planner=True,
        planner_mode="topology_select",
        seed=seed,
    )
    return _RunTask(
        produce=lambda: _run_unit(
            lambda: run_instance(instance, cfg, llm_client=client),
            arm="select",
            instance=instance,
            seed=seed,
            topology=None,
            extra=None,
            progress=progress,
        )
    )


def _graphgen_task(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seed: int,
    client: LLMClient,
    *,
    graphgen_candidates: int,
    motif_stats: Any,
    progress: _Progress | None = None,
) -> _RunTask:
    """A single graphgen-arm seed run-unit (mirrors :func:`_run_graphgen_arm`).

    Under concurrency the motif prior is a fixed snapshot (``motif_stats``); a
    generated run does NOT feed its motif row forward, so unlike the sequential
    path no ``new_motif_rows`` are accumulated mid-flight.
    """
    cfg = _cfg_for(
        cfg_base,
        instance.n_agents,
        use_planner=True,
        planner_mode="graph_generate",
        num_graph_candidates=graphgen_candidates,
        seed=seed,
    )
    return _RunTask(
        produce=lambda: _run_unit(
            lambda: run_instance(
                instance, cfg, llm_client=client, motif_stats=motif_stats
            ),
            arm="graphgen",
            instance=instance,
            seed=seed,
            topology=None,
            extra_from_score=lambda s: {
                "generated_steps": s.extra.get("generated_steps"),
                "graph_fallback_reason": s.extra.get("graph_fallback_reason"),
            },
            progress=progress,
        )
    )


def _evolved_tasks(
    instances: list[BenchmarkInstance],
    cfg_base: RunConfig,
    seeds: list[int],
    *,
    adapter: SiloBenchAdapter,
    cases: list[str] | None,
    levels: list[str] | None,
    client: LLMClient,
    cache: dict[int, dict[str, Any]],
    ckpt: _Checkpoint,
    progress: _Progress | None = None,
) -> list[_RunTask]:
    """Build the evolved arm's eval run-units, pre-running evolution sequentially.

    The heavy ``run_evolution`` mutates a shared skill bank + is cached, so it is
    NOT safe to run concurrently. For every distinct ``n_agents`` that has at
    least one pending eval seed, this runs (and caches) ``run_evolution`` here,
    SEQUENTIALLY, before returning any task. Only the resulting per-instance
    ``run_fixed_protocol`` eval units (independent) become pool tasks. Mirrors the
    train/test split, gate-extra attachment and synthetic-offline gate of
    :func:`_run_evolved_arm`.
    """
    test_seeds = [seeds[-1]] if seeds else [0]

    # Which instances still have a pending eval? (and which n_agents they need.)
    pending: list[tuple[BenchmarkInstance, list[int]]] = []
    for instance in instances:
        pending_seeds = [
            seed
            for seed in test_seeds
            if not ckpt.done(
                ("evolved", instance.case_id, instance.n_agents, seed, None)
            )
        ]
        if pending_seeds:
            pending.append((instance, pending_seeds))
    if not pending:
        return []

    # Pre-run + cache the heavy evolution sequentially, once per needed n_agents.
    needed_n_agents = {instance.n_agents for instance, _ in pending}
    for n_agents in sorted(needed_n_agents):
        if n_agents not in cache:
            cache[n_agents] = _compute_evolution_summary(
                n_agents,
                adapter,
                cfg_base,
                seeds,
                cases=cases,
                levels=levels,
                client=client,
            )

    # Now build the independent per-instance eval tasks.
    tasks: list[_RunTask] = []
    for instance, pending_seeds in pending:
        summary = cache[instance.n_agents]
        evolved_topology = summary["final_selection"]["topology_name"]
        evolved_extra = _evolved_extra(summary)
        for seed in pending_seeds:
            cfg = _cfg_for(
                cfg_base, instance.n_agents, use_planner=False, seed=seed
            )
            tasks.append(
                _RunTask(
                    produce=(
                        lambda inst=instance, c=cfg, s=seed, topo=evolved_topology, ex=evolved_extra: _run_unit(
                            lambda: run_fixed_protocol(
                                inst, c, topology=topo, llm_client=client
                            ),
                            arm="evolved",
                            instance=inst,
                            seed=s,
                            topology=topo,
                            extra=ex,
                            progress=progress,
                        )
                    )
                )
            )
    return tasks


def _compute_evolution_summary(
    n_agents: int,
    adapter: SiloBenchAdapter,
    cfg_base: RunConfig,
    seeds: list[int],
    *,
    cases: list[str] | None,
    levels: list[str] | None,
    client: LLMClient,
) -> dict[str, Any]:
    """Run the heavy gated ``run_evolution`` for one ``n_agents`` (offline-honest).

    Same train/test split + synthetic-offline gate as :func:`_run_evolved_arm`;
    factored out so both the sequential and parallel paths produce an identical
    summary.
    """
    train_seeds = list(seeds[:-1]) or list(seeds)
    val_seeds = [seeds[-1]] if seeds else [0]
    cfg = _cfg_for(
        cfg_base,
        n_agents,
        use_planner=True,
        use_skill_evolution=True,
    )
    use_synth = cfg_base.llm_provider == "fake"
    return run_evolution(
        adapter,
        cases=cases,
        agent_counts=[n_agents],
        levels=levels,
        train_seeds=train_seeds,
        val_seeds=val_seeds,
        cfg=cfg,
        held_out_rows=accepting_held_out_rows() if use_synth else None,
        seed_incumbent_topology=(
            INCUMBENT_BASELINE_TOPOLOGY if use_synth else None
        ),
        llm_client=client,
    )


def _evolved_extra(summary: dict[str, Any]) -> dict[str, Any]:
    """The gate/summary fields attached to every evolved eval record."""
    gate = summary["gate"]
    return {
        "gate": {
            "accepted": bool(gate["accepted"]),
            "j_before": float(gate["j_before"]),
            "j_after": float(gate["j_after"]),
        },
        "val_success_rate": summary["val_success_rate"],
        "skill_bank_mutated": summary["skill_bank_mutated"],
    }


# --------------------------------------------------------------------------- #
# Per-arm runners.                                                            #
# --------------------------------------------------------------------------- #


def _run_fixed_arm(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seeds: list[int],
    fixed_topologies: list[str],
    client: LLMClient,
    ckpt: _Checkpoint,
    *,
    progress: _Progress | None = None,
) -> list[dict[str, Any]]:
    """Run every fixed topology over every seed (planner-OFF, forced topology).

    Each (topology, seed) is its own checkpointed run unit (the fixed arm's key
    carries ``fixed_topology``): already-done units are skipped on resume, every
    produced record is isolated against failure and appended immediately.
    """
    records: list[dict[str, Any]] = []
    for topology in fixed_topologies:
        for seed in seeds:
            key = ("fixed", instance.case_id, instance.n_agents, seed, topology)
            if ckpt.done(key):
                continue
            cfg = _cfg_for(cfg_base, instance.n_agents, use_planner=False, seed=seed)
            record = _run_unit(
                lambda c=cfg, t=topology: run_fixed_protocol(
                    instance, c, topology=t, llm_client=client
                ),
                arm="fixed",
                instance=instance,
                seed=seed,
                topology=topology,
                extra={"fixed_topology": topology},
                progress=progress,
            )
            ckpt.append(record)
            records.append(record)
    return records


def _run_select_arm(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seeds: list[int],
    client: LLMClient,
    ckpt: _Checkpoint,
    *,
    progress: _Progress | None = None,
) -> list[dict[str, Any]]:
    """Run the QueenBee ``topology_select`` arm over every seed (isolated/resumable)."""
    records: list[dict[str, Any]] = []
    for seed in seeds:
        key = ("select", instance.case_id, instance.n_agents, seed, None)
        if ckpt.done(key):
            continue
        cfg = _cfg_for(
            cfg_base,
            instance.n_agents,
            use_planner=True,
            planner_mode="topology_select",
            seed=seed,
        )
        record = _run_unit(
            lambda c=cfg: run_instance(instance, c, llm_client=client),
            arm="select",
            instance=instance,
            seed=seed,
            topology=None,
            extra=None,
            progress=progress,
        )
        ckpt.append(record)
        records.append(record)
    return records


def _run_graphgen_arm(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seeds: list[int],
    client: LLMClient,
    ckpt: _Checkpoint,
    *,
    graphgen_candidates: int,
    motif_rows: list[dict[str, Any]],
    progress: _Progress | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the QueenBee graph_generate arm over every seed (isolated/resumable).

    Accumulated motif evidence (``motif_rows``, each a ``{mean_primary_loss,
    motif_keys}`` row from a prior generated spec) is aggregated into a
    ``motif_stats`` prior and handed to the planner so the structural-motif
    credit prior is active. Returns ``(records, new_motif_rows)`` where the new
    rows are this arm's generated specs' motif evidence, to be appended by the
    caller for subsequent conditions. A failed or resumed (skipped) run
    contributes no motif evidence (it has no fresh selected-topology/loss signal).
    """
    motif_stats = aggregate_motif_losses(motif_rows) if motif_rows else None
    records: list[dict[str, Any]] = []
    new_motif_rows: list[dict[str, Any]] = []
    for seed in seeds:
        key = ("graphgen", instance.case_id, instance.n_agents, seed, None)
        if ckpt.done(key):
            continue
        cfg = _cfg_for(
            cfg_base,
            instance.n_agents,
            use_planner=True,
            planner_mode="graph_generate",
            num_graph_candidates=graphgen_candidates,
            seed=seed,
        )
        record = _run_unit(
            lambda c=cfg: run_instance(
                instance, c, llm_client=client, motif_stats=motif_stats
            ),
            arm="graphgen",
            instance=instance,
            seed=seed,
            topology=None,
            extra_from_score=lambda s: {
                "generated_steps": s.extra.get("generated_steps"),
                "graph_fallback_reason": s.extra.get("graph_fallback_reason"),
            },
            progress=progress,
        )
        # A real run feeds its (selected topology, loss) back as motif evidence so
        # the prior accumulates across conditions; a failed run (carrying
        # ``error``) has no fresh topology/loss signal and contributes none.
        if "error" not in record:
            new_motif_rows.append(
                {
                    "motif_keys": [f"topology={record.get('topology')}"],
                    "mean_primary_loss": 0.0 if record["success"] else 1.0,
                }
            )
        ckpt.append(record)
        records.append(record)
    return records, new_motif_rows


def _run_evolved_arm(
    instance: BenchmarkInstance,
    adapter: SiloBenchAdapter,
    cfg_base: RunConfig,
    seeds: list[int],
    *,
    cases: list[str] | None,
    levels: list[str] | None,
    client: LLMClient,
    cache: dict[int, dict[str, Any]],
    ckpt: _Checkpoint,
    progress: _Progress | None = None,
) -> list[dict[str, Any]]:
    """Run (or reuse) the gated evolution loop, eval its selection on test seeds.

    The evolution loop is run ONCE per ``n_agents`` over the whole case set (it is
    much heavier than a single run), cached, and its post-evolution topology
    selection is then evaluated on the held-out *test* seeds for THIS instance.
    The gate decision + pre/post held-out success from the evolve summary are
    attached to every produced record so each condition carries them.

    Train/test seed split: the LAST seed is held out as test, the rest train. A
    single seed is used for both (offline runs are seed-invariant, so this still
    runs end to end). Offline, the gate is made non-degenerate with a synthetic
    multi-topology held-out set + a baseline incumbent (same as ``masbench
    evolve``); with a real LLM ``run_benchmark`` callers can disable that, but the
    harness defaults to honest-offline behaviour.

    Crash-safety: only the per-instance EVAL run is a checkpointed run unit (keyed
    like a fixed run with ``fixed_topology`` = the evolved topology is NOT used --
    the eval's key topology is None, matching its record). On resume an
    already-done eval is skipped; the heavy ``run_evolution`` is then triggered
    lazily, only when at least one eval for this ``n_agents`` still needs running
    (so a fully-resumed evolved arm never re-pays the evolution cost). The eval is
    isolated against failure like every other run unit.
    """
    n_agents = instance.n_agents
    test_seeds = [seeds[-1]] if seeds else [0]

    # Which eval seeds still need running for THIS instance?
    pending_seeds = [
        seed
        for seed in test_seeds
        if not ckpt.done(("evolved", instance.case_id, n_agents, seed, None))
    ]
    if not pending_seeds:
        # Everything for this instance is already checkpointed -> no evolution,
        # no eval; the resumed records carry the gate/summary fields already.
        return []

    # Lazily compute (and cache) the heavy evolution summary -- only now that we
    # know an eval actually needs it.
    if n_agents not in cache:
        train_seeds = list(seeds[:-1]) or list(seeds)
        val_seeds = [seeds[-1]] if seeds else [0]
        cfg = _cfg_for(
            cfg_base,
            n_agents,
            use_planner=True,
            use_skill_evolution=True,
        )
        use_synth = cfg_base.llm_provider == "fake"
        cache[n_agents] = run_evolution(
            adapter,
            cases=cases,
            agent_counts=[n_agents],
            levels=levels,
            train_seeds=train_seeds,
            val_seeds=val_seeds,
            cfg=cfg,
            held_out_rows=accepting_held_out_rows() if use_synth else None,
            seed_incumbent_topology=(
                INCUMBENT_BASELINE_TOPOLOGY if use_synth else None
            ),
            llm_client=client,
        )

    summary = cache[n_agents]
    evolved_topology = summary["final_selection"]["topology_name"]
    gate = summary["gate"]
    evolved_extra = {
        "gate": {
            "accepted": bool(gate["accepted"]),
            "j_before": float(gate["j_before"]),
            "j_after": float(gate["j_after"]),
        },
        "val_success_rate": summary["val_success_rate"],
        "skill_bank_mutated": summary["skill_bank_mutated"],
    }

    # Evaluate the evolved selection on the held-out/test seeds for this instance.
    records: list[dict[str, Any]] = []
    for seed in pending_seeds:
        cfg = _cfg_for(cfg_base, n_agents, use_planner=False, seed=seed)
        record = _run_unit(
            lambda c=cfg: run_fixed_protocol(
                instance, c, topology=evolved_topology, llm_client=client
            ),
            arm="evolved",
            instance=instance,
            seed=seed,
            topology=evolved_topology,
            extra=evolved_extra,
            progress=progress,
        )
        ckpt.append(record)
        records.append(record)
    return records


# --------------------------------------------------------------------------- #
# Aggregation blocks.                                                         #
# --------------------------------------------------------------------------- #


def _aggregate_condition_block(
    instance: BenchmarkInstance, cond_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the per-condition block: per-arm aggregates + oracle/breakdown extras."""
    arms_agg = aggregate_condition(cond_runs)
    block: dict[str, Any] = {
        "case_id": instance.case_id,
        "n_agents": instance.n_agents,
        "arms": arms_agg,
    }

    # The 'evolved' arm carries a gate decision: surface it on the aggregate.
    evolved_runs = [r for r in cond_runs if r["arm"] == "evolved"]
    if evolved_runs and "gate" in evolved_runs[0]:
        block["arms"]["evolved"]["gate"] = evolved_runs[0]["gate"]

    # Fixed arm: report the oracle (best topology per condition) + breakdown.
    fixed_runs = [r for r in cond_runs if r["arm"] == "fixed"]
    if fixed_runs:
        by_topology: dict[str, list[dict[str, Any]]] = {}
        for r in fixed_runs:
            by_topology.setdefault(r["topology"], []).append(r)
        fixed_by_topology = {
            topo: _aggregate_metric_block(rows)
            for topo, rows in by_topology.items()
        }
        block["fixed_by_topology"] = fixed_by_topology
        # Oracle fixed = the topology with the highest mean success (tie-break:
        # lower tokens), recomputed as that topology's own aggregate.
        best_topo = max(
            fixed_by_topology,
            key=lambda t: (
                fixed_by_topology[t]["success"]["mean"],
                -fixed_by_topology[t]["tokens"]["mean"],
            ),
        )
        block["oracle_fixed"] = {**fixed_by_topology[best_topo], "topology": best_topo}
    return block


def _aggregate_metric_block(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """mean +/- std for the metric keys over a flat list of run records."""
    entry: dict[str, Any] = {"n": len(runs)}
    for metric in _METRIC_KEYS:
        entry[metric] = _mean_std([float(r[metric]) for r in runs])
    return entry


def _aggregate_overall(
    runs: list[dict[str, Any]], arms: list[str]
) -> dict[str, Any]:
    """Overall (across all conditions) per-arm aggregate."""
    overall: dict[str, Any] = {}
    for arm in arms:
        arm_runs = [r for r in runs if r["arm"] == arm]
        if arm_runs:
            overall[arm] = _aggregate_metric_block(arm_runs)
    return overall


# --------------------------------------------------------------------------- #
# Rendering / output.                                                         #
# --------------------------------------------------------------------------- #


def _fmt(stat: dict[str, float], *, pct: bool = False) -> str:
    """Render a mean +/- std stat. ``pct`` shows success/partial as percentages."""
    mean, std = stat["mean"], stat["std"]
    if pct:
        return f"{mean * 100:.1f}±{std * 100:.1f}"
    if mean >= 100:
        return f"{mean:.0f}±{std:.0f}"
    return f"{mean:.2f}±{std:.2f}"


def render_report(results: dict[str, Any]) -> str:
    """Render the Table-1-style markdown report from a results dict."""
    arms = results["arms"]
    lines: list[str] = ["# masbench bench report", ""]

    # Top summary line: overall success per arm.
    overall = results.get("overall", {})
    summary_bits = [
        f"{arm}={_fmt(overall[arm]['success'], pct=True)}%"
        for arm in arms
        if arm in overall
    ]
    lines.append("**Overall success (mean±std over all runs):** " + ", ".join(summary_bits))
    lines.append("")

    header = (
        "| arm | success | partial | msgs | calls | tokens |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )

    for cond_key, block in results["conditions"].items():
        lines.append(f"## {block['case_id']} (n={block['n_agents']})  `{cond_key}`")
        lines.append("")
        # Best arm per condition by mean success (tie-break: lower tokens).
        arm_aggs = block["arms"]
        present_arms = [a for a in arms if a in arm_aggs]
        if present_arms:
            best_arm = max(
                present_arms,
                key=lambda a: (
                    arm_aggs[a]["success"]["mean"],
                    -arm_aggs[a]["tokens"]["mean"],
                ),
            )
        else:
            best_arm = None
        lines.append(header)
        for arm in present_arms:
            agg = arm_aggs[arm]
            label = f"**{arm}**" if arm == best_arm else arm
            row = (
                f"| {label} "
                f"| {_fmt(agg['success'], pct=True)}% "
                f"| {_fmt(agg['partial'], pct=True)}% "
                f"| {_fmt(agg['n_messages'])} "
                f"| {_fmt(agg['n_model_calls'])} "
                f"| {_fmt(agg['tokens'])} |"
            )
            lines.append(row)
        # Oracle-fixed annotation + per-topology breakdown when the fixed arm ran.
        if "oracle_fixed" in block:
            oracle = block["oracle_fixed"]
            n_topo = len(block.get("fixed_by_topology", {}))
            lines.append("")
            lines.append(
                f"_oracle fixed (best topology): `{oracle['topology']}` "
                f"success {_fmt(oracle['success'], pct=True)}% — note the `fixed` row "
                f"above is the MEAN over {n_topo} topologies (pessimistic); compare "
                f"methods against this oracle, not the mean._"
            )
        if "fixed_by_topology" in block:
            oracle_topo = block.get("oracle_fixed", {}).get("topology")
            lines.append("")
            lines.append("Fixed baselines per topology (oracle in **bold**):")
            lines.append("")
            lines.append(header.replace("| arm ", "| fixed topology "))
            for topo, agg in sorted(
                block["fixed_by_topology"].items(),
                key=lambda kv: (-kv[1]["success"]["mean"], kv[1]["tokens"]["mean"]),
            ):
                label = f"**{topo}**" if topo == oracle_topo else topo
                lines.append(
                    f"| {label} "
                    f"| {_fmt(agg['success'], pct=True)}% "
                    f"| {_fmt(agg['partial'], pct=True)}% "
                    f"| {_fmt(agg['n_messages'])} "
                    f"| {_fmt(agg['n_model_calls'])} "
                    f"| {_fmt(agg['tokens'])} |"
                )
        # Gate annotation when the evolved arm ran.
        if "evolved" in arm_aggs and "gate" in arm_aggs["evolved"]:
            gate = arm_aggs["evolved"]["gate"]
            lines.append(
                f"_evolved gate: accepted={gate['accepted']} "
                f"J_before={gate['j_before']:.3f} J_after={gate['j_after']:.3f}_"
            )
        lines.append("")
    return "\n".join(lines)


def _csv_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the per-condition aggregates into one row per condition x arm."""
    rows: list[dict[str, Any]] = []
    for cond_key, block in results["conditions"].items():
        for arm, agg in block["arms"].items():
            row: dict[str, Any] = {
                "condition": cond_key,
                "case_id": block["case_id"],
                "n_agents": block["n_agents"],
                "arm": arm,
                "n": agg["n"],
            }
            for metric in _METRIC_KEYS:
                row[f"{metric}_mean"] = agg[metric]["mean"]
                row[f"{metric}_std"] = agg[metric]["std"]
            rows.append(row)
    return rows


def _write_outputs(results: dict[str, Any], out: Path) -> None:
    """Write results.json + results.csv + report.md under ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True, default=str)
    )
    rows = _csv_rows(results)
    if rows:
        fieldnames = list(rows[0].keys())
        with (out / "results.csv").open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:  # pragma: no cover - empty grid guarded earlier
        (out / "results.csv").write_text("")
    (out / "report.md").write_text(render_report(results))
