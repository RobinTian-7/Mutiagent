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
from dataclasses import asdict
from pathlib import Path
from typing import Any

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


def _cfg_for(cfg_base: RunConfig, n_agents: int, **overrides: Any) -> RunConfig:
    """Clone ``cfg_base`` with ``n_agents`` pinned and any per-arm overrides."""
    return RunConfig(**{**asdict(cfg_base), "n_agents": n_agents, **overrides})


def _condition_key(case_id: str, n_agents: int) -> str:
    return f"{case_id}|n{n_agents}"


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
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Run the requested ARMS over a Silo-Bench grid and aggregate a Table-1.

    See the module docstring for the arm definitions and outputs. Returns the
    full results dict (``runs`` / ``conditions`` / ``overall`` / ``arms``); also
    writes ``results.json`` + ``results.csv`` + ``report.md`` under ``out`` when
    given.
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

    runs: list[dict[str, Any]] = []
    conditions: dict[str, Any] = {}
    # Accumulated motif evidence from graphgen-generated specs, fed back into
    # later graphgen runs so the structural-motif prior is active, not merely set.
    motif_rows: list[dict[str, Any]] = []

    # The evolved arm is heavy: run it ONCE per (case-set, n_agents) rather than
    # per (case, seed). Cache the evolve summary keyed by n_agents.
    evolved_summaries: dict[int, dict[str, Any]] = {}

    for instance in instances:
        cond_key = _condition_key(instance.case_id, instance.n_agents)
        cond_runs: list[dict[str, Any]] = []
        n_agents = instance.n_agents

        for arm in arms:
            if arm == "fixed":
                cond_runs.extend(
                    _run_fixed_arm(
                        instance, cfg_base, seeds, fixed_topologies, client
                    )
                )
            elif arm == "select":
                cond_runs.extend(
                    _run_select_arm(instance, cfg_base, seeds, client)
                )
            elif arm == "graphgen":
                arm_runs, new_motif_rows = _run_graphgen_arm(
                    instance,
                    cfg_base,
                    seeds,
                    client,
                    graphgen_candidates=graphgen_candidates,
                    motif_rows=motif_rows,
                )
                cond_runs.extend(arm_runs)
                motif_rows.extend(new_motif_rows)
            elif arm == "evolved":
                cond_runs.extend(
                    _run_evolved_arm(
                        instance,
                        adapter,
                        cfg_base,
                        seeds,
                        cases=cases,
                        levels=levels,
                        client=client,
                        cache=evolved_summaries,
                    )
                )
            else:
                raise SystemExit(
                    f"unknown arm '{arm}' "
                    f"(valid: fixed, select, graphgen, evolved)"
                )

        runs.extend(cond_runs)
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
# Per-arm runners.                                                            #
# --------------------------------------------------------------------------- #


def _run_fixed_arm(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seeds: list[int],
    fixed_topologies: list[str],
    client: LLMClient,
) -> list[dict[str, Any]]:
    """Run every fixed topology over every seed (planner-OFF, forced topology)."""
    records: list[dict[str, Any]] = []
    for topology in fixed_topologies:
        for seed in seeds:
            cfg = _cfg_for(cfg_base, instance.n_agents, use_planner=False, seed=seed)
            score = run_fixed_protocol(
                instance, cfg, topology=topology, llm_client=client
            )
            records.append(
                _run_record(
                    "fixed", instance, seed, score,
                    topology=topology, extra={"fixed_topology": topology},
                )
            )
    return records


def _run_select_arm(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seeds: list[int],
    client: LLMClient,
) -> list[dict[str, Any]]:
    """Run the QueenBee ``topology_select`` arm over every seed."""
    records: list[dict[str, Any]] = []
    for seed in seeds:
        cfg = _cfg_for(
            cfg_base,
            instance.n_agents,
            use_planner=True,
            planner_mode="topology_select",
            seed=seed,
        )
        score = run_instance(instance, cfg, llm_client=client)
        records.append(_run_record("select", instance, seed, score))
    return records


def _run_graphgen_arm(
    instance: BenchmarkInstance,
    cfg_base: RunConfig,
    seeds: list[int],
    client: LLMClient,
    *,
    graphgen_candidates: int,
    motif_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the QueenBee graph_generate arm over every seed.

    Accumulated motif evidence (``motif_rows``, each a ``{mean_primary_loss,
    motif_keys}`` row from a prior generated spec) is aggregated into a
    ``motif_stats`` prior and handed to the planner so the structural-motif
    credit prior is active. Returns ``(records, new_motif_rows)`` where the new
    rows are this arm's generated specs' motif evidence, to be appended by the
    caller for subsequent conditions.
    """
    motif_stats = aggregate_motif_losses(motif_rows) if motif_rows else None
    records: list[dict[str, Any]] = []
    new_motif_rows: list[dict[str, Any]] = []
    for seed in seeds:
        cfg = _cfg_for(
            cfg_base,
            instance.n_agents,
            use_planner=True,
            planner_mode="graph_generate",
            num_graph_candidates=graphgen_candidates,
            seed=seed,
        )
        score = run_instance(
            instance, cfg, llm_client=client, motif_stats=motif_stats
        )
        records.append(
            _run_record(
                "graphgen", instance, seed, score,
                extra={
                    "generated_steps": score.extra.get("generated_steps"),
                    "graph_fallback_reason": score.extra.get("graph_fallback_reason"),
                },
            )
        )
        # Feed this run's (topology, loss) back as motif evidence keyed by its
        # selected topology, so the prior accumulates across conditions even
        # though the offline fallback DAG is a named topology.
        new_motif_rows.append(
            {
                "motif_keys": [f"topology={score.extra.get('topology')}"],
                "mean_primary_loss": 0.0 if score.success else 1.0,
            }
        )
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
    """
    n_agents = instance.n_agents
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

    # Evaluate the evolved selection on the held-out/test seeds for this instance.
    test_seeds = [seeds[-1]] if seeds else [0]
    records: list[dict[str, Any]] = []
    for seed in test_seeds:
        cfg = _cfg_for(cfg_base, n_agents, use_planner=False, seed=seed)
        score = run_fixed_protocol(
            instance, cfg, topology=evolved_topology, llm_client=client
        )
        records.append(
            _run_record(
                "evolved", instance, seed, score,
                topology=evolved_topology,
                extra={
                    "gate": {
                        "accepted": bool(gate["accepted"]),
                        "j_before": float(gate["j_before"]),
                        "j_after": float(gate["j_after"]),
                    },
                    "val_success_rate": summary["val_success_rate"],
                    "skill_bank_mutated": summary["skill_bank_mutated"],
                },
            )
        )
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
        # Oracle-fixed annotation when the fixed arm ran.
        if "oracle_fixed" in block:
            oracle = block["oracle_fixed"]
            lines.append("")
            lines.append(
                f"_oracle fixed: `{oracle['topology']}` "
                f"success {_fmt(oracle['success'], pct=True)}%_"
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
