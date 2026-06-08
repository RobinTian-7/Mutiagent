"""Matrix execution, collection, and batch insight analysis for MAS runs."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.mas.consolidation import write_patch_file
from exp_graph.mas.evidence import read_evidence_jsonl, write_evidence_jsonl
from exp_graph.mas.evolution import (
    TraceAnalystMinister,
    build_cost_patches_from_evidence,
    build_counterexample_patches_from_evidence,
    build_result_patches_from_evidence,
    classify_topology,
    condition_specific_skill_id,
    default_operation_recommendations,
    infer_condition_scope,
    infer_topology_structure_features,
)
from exp_graph.mas.formatting import format_insight_report
from exp_graph.mas.insights import (
    falsify_insights,
    insight_report_to_patches,
    topology_structures_from_records,
)
from exp_graph.mas.pipeline import run_mas_pipeline
from exp_graph.mas.role_llm import (
    create_role_llm_client,
    resolve_role_llm_config,
)
from exp_graph.mas.schemas import (
    EvidenceRecord,
    InsightReport,
    MASInsight,
    MASRuntimeConfig,
    PlannerRequest,
    RoleLLMProfiles,
    SkillCard,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank


DEFAULT_TOPOLOGIES = [
    "tree",
    "one_peer_exponential_dag_star",
    "mesh_dag",
    "balanced_log_layer",
]


class MatrixJob(BaseModel):
    """One matrix experiment job."""

    job_id: str
    phase: str = "train"
    objective: str
    planner_mode: str
    planner_policy: str
    topology_name: str | None = None
    n_agents: int
    array_size: int
    value_min: int = 0
    value_max: int = 9
    seed: int
    merge_mode: str
    init_mode: str
    llm_provider: str
    model_name: str
    role_llm_profiles: RoleLLMProfiles | None = None
    role_llm_config_path: str | None = None
    skill_bank_version: str = ""
    graph_search_mode: str = "single"
    num_graph_candidates: int = 1
    graph_top_k: int = 1
    graph_candidate_score_mode: str = "objective"
    graph_max_steps: int = 4
    graph_max_messages: int = 32
    graph_max_receiver_fan_in: int = 4
    graph_repair_attempts: int = 1
    graph_validation_seeds: list[int] = Field(default_factory=list)


class MatrixJobStatus(BaseModel):
    """Status of one matrix job."""

    job_id: str
    status: str
    started_at: str = ""
    ended_at: str = ""
    error: str = ""
    output_dir: str = ""
    run_id: str | None = None
    final_rmse: float | None = None
    exact_match: bool | None = None
    token_cost: int = 0


class MatrixRunResult(BaseModel):
    """Summary of a matrix execution."""

    output_dir: str
    total_jobs: int
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    statuses: list[MatrixJobStatus] = Field(default_factory=list)


class MatrixCollectResult(BaseModel):
    """Summary of collected matrix artifacts."""

    output_dir: str
    evidence_count: int
    patch_count: int
    run_count: int
    condition_count: int


def expand_matrix_jobs(
    *,
    objectives: list[str],
    planner_modes: list[str],
    planner_policies: list[str],
    topologies: list[str],
    n_agents_values: list[int],
    array_sizes: list[int],
    seeds: list[int],
    merge_mode: str,
    init_mode: str,
    llm_provider: str,
    model_name: str,
    skill_bank: SkillBank,
    value_min: int = 0,
    value_max: int = 9,
    role_llm_profiles: RoleLLMProfiles | None = None,
    role_llm_config_path: str | None = None,
    graph_search_mode: str = "single",
    num_graph_candidates: int = 1,
    graph_top_k: int = 1,
    graph_candidate_score_mode: str = "objective",
    graph_max_steps: int = 4,
    graph_max_messages: int = 32,
    graph_max_receiver_fan_in: int = 4,
    graph_repair_attempts: int = 1,
    graph_validation_seeds: list[int] | None = None,
    phase: str = "train",
) -> list[MatrixJob]:
    """Expand objective x policy x topology x size x seed into deterministic jobs."""
    skill_version = _skill_bank_version(skill_bank)
    role_profiles_payload = (
        role_llm_profiles.model_dump(mode="json")
        if role_llm_profiles is not None
        else None
    )
    topology_values = topologies or DEFAULT_TOPOLOGIES
    jobs: list[MatrixJob] = []
    for objective in objectives:
        for planner_mode in planner_modes:
            for planner_policy in planner_policies:
                policy_topologies = (
                    topology_values
                    if planner_policy in {"fixed_topology", "topology_sweep"}
                    else [None]
                )
                for topology_name in policy_topologies:
                    for n_agents in n_agents_values:
                        for array_size in array_sizes:
                            for seed in seeds:
                                base = {
                                    "phase": phase,
                                    "objective": objective,
                                    "planner_mode": planner_mode,
                                    "planner_policy": planner_policy,
                                    "topology_name": topology_name,
                                    "n_agents": n_agents,
                                    "array_size": array_size,
                                    "value_min": value_min,
                                    "value_max": value_max,
                                    "seed": seed,
                                    "merge_mode": merge_mode,
                                    "init_mode": init_mode,
                                    "llm_provider": llm_provider,
                                    "model_name": model_name,
                                    "role_llm_profiles": role_profiles_payload,
                                    "role_llm_config_path": role_llm_config_path,
                                    "skill_bank_version": skill_version,
                                    "graph_search_mode": graph_search_mode,
                                    "num_graph_candidates": num_graph_candidates,
                                    "graph_top_k": graph_top_k,
                                    "graph_candidate_score_mode": graph_candidate_score_mode,
                                    "graph_max_steps": graph_max_steps,
                                    "graph_max_messages": graph_max_messages,
                                    "graph_max_receiver_fan_in": graph_max_receiver_fan_in,
                                    "graph_repair_attempts": graph_repair_attempts,
                                    "graph_validation_seeds": graph_validation_seeds or [],
                                }
                                jobs.append(
                                    MatrixJob(
                                        job_id=_stable_job_id(base),
                                        **base,
                                    )
                                )
    return jobs


def run_matrix(
    *,
    skill_dir: Path | str,
    output_dir: Path | str,
    objectives: list[str],
    planner_modes: list[str],
    planner_policies: list[str],
    topologies: list[str],
    n_agents_values: list[int],
    array_sizes: list[int],
    seeds: list[int],
    llm_provider: str,
    model_name: str,
    merge_mode: str,
    init_mode: str,
    trace_enabled: bool,
    retain_traces: bool,
    max_parallel_runs: int,
    max_parallel_agents: int,
    max_parallel_ministers: int,
    value_min: int = 0,
    value_max: int = 9,
    role_llm_profiles: RoleLLMProfiles | None = None,
    role_llm_config_path: str | None = None,
    verbose_events: bool = False,
    graph_search_mode: str = "single",
    num_graph_candidates: int = 1,
    graph_top_k: int = 1,
    graph_candidate_score_mode: str = "objective",
    graph_max_steps: int = 4,
    graph_max_messages: int = 32,
    graph_max_receiver_fan_in: int = 4,
    graph_repair_attempts: int = 1,
    graph_validation_seeds: list[int] | None = None,
    phase: str = "train",
    resume: bool = True,
) -> MatrixRunResult:
    """Run a full MAS experiment matrix using job-level parallelism."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    bank = SkillBank.load_dir(skill_dir)
    jobs = expand_matrix_jobs(
        objectives=objectives,
        planner_modes=planner_modes,
        planner_policies=planner_policies,
        topologies=topologies,
        n_agents_values=n_agents_values,
        array_sizes=array_sizes,
        value_min=value_min,
        value_max=value_max,
        seeds=seeds,
        merge_mode=merge_mode,
        init_mode=init_mode,
        llm_provider=llm_provider,
        model_name=model_name,
        role_llm_profiles=role_llm_profiles,
        role_llm_config_path=role_llm_config_path,
        skill_bank=bank,
        graph_search_mode=graph_search_mode,
        num_graph_candidates=num_graph_candidates,
        graph_top_k=graph_top_k,
        graph_candidate_score_mode=graph_candidate_score_mode,
        graph_max_steps=graph_max_steps,
        graph_max_messages=graph_max_messages,
        graph_max_receiver_fan_in=graph_max_receiver_fan_in,
        graph_repair_attempts=graph_repair_attempts,
        graph_validation_seeds=graph_validation_seeds or [],
        phase=phase,
    )
    _write_json(
        root / "matrix_config.json",
        {
            "phase": phase,
            "skill_dir": str(skill_dir),
            "objectives": objectives,
            "planner_modes": planner_modes,
            "planner_policies": planner_policies,
            "topologies": topologies,
            "n_agents": n_agents_values,
            "array_sizes": array_sizes,
            "value_min": value_min,
            "value_max": value_max,
            "seeds": seeds,
            "llm_provider": llm_provider,
            "model_name": model_name,
            "role_llm_config_path": role_llm_config_path,
            "role_llm_profiles": (
                role_llm_profiles.model_dump(mode="json")
                if role_llm_profiles is not None
                else None
            ),
            "merge_mode": merge_mode,
            "init_mode": init_mode,
            "trace_enabled": trace_enabled,
            "retain_traces": retain_traces,
            "verbose_events": verbose_events,
            "max_parallel_runs": max_parallel_runs,
            "max_parallel_agents": max_parallel_agents,
            "max_parallel_ministers": max_parallel_ministers,
            "graph_search_mode": graph_search_mode,
            "num_graph_candidates": num_graph_candidates,
            "graph_top_k": graph_top_k,
            "graph_candidate_score_mode": graph_candidate_score_mode,
            "graph_max_steps": graph_max_steps,
            "graph_max_messages": graph_max_messages,
            "graph_max_receiver_fan_in": graph_max_receiver_fan_in,
            "graph_repair_attempts": graph_repair_attempts,
            "graph_validation_seeds": graph_validation_seeds or [],
            "created_at": _now(),
        },
    )
    _write_jsonl(root / "matrix_manifest.jsonl", [job.model_dump() for job in jobs])

    def run_one(job: MatrixJob) -> MatrixJobStatus:
        return _run_matrix_job(
            job=job,
            skill_dir=skill_dir,
            matrix_dir=root,
            trace_enabled=trace_enabled,
            retain_traces=retain_traces,
            verbose_events=verbose_events,
            max_parallel_agents=max_parallel_agents,
            max_parallel_ministers=max_parallel_ministers,
            resume=resume,
        )

    statuses: list[MatrixJobStatus] = []
    workers = max(1, max_parallel_runs)
    if workers == 1:
        for job in jobs:
            statuses.append(run_one(job))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_one, job): job for job in jobs}
            for future in as_completed(futures):
                statuses.append(future.result())

    _write_jsonl(
        root / "matrix_status.jsonl",
        [status.model_dump(mode="json") for status in statuses],
    )
    result = MatrixRunResult(
        output_dir=str(root),
        total_jobs=len(jobs),
        succeeded=sum(1 for status in statuses if status.status == "succeeded"),
        failed=sum(1 for status in statuses if status.status == "failed"),
        skipped=sum(1 for status in statuses if status.status == "skipped"),
        statuses=sorted(statuses, key=lambda item: item.job_id),
    )
    _write_json(root / "matrix_summary.json", result.model_dump(mode="json"))
    return result


def collect_matrix(
    *,
    matrix_dir: Path | str,
    output_dir: Path | str,
) -> MatrixCollectResult:
    """Collect matrix run artifacts into batch evidence, patches, and summaries."""
    root = Path(matrix_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = _read_jsonl(root / "matrix_manifest.jsonl")
    jobs_by_id = {str(item["job_id"]): item for item in manifest}
    evidence_by_id: dict[str, EvidenceRecord] = {}
    patches_by_kind: dict[str, dict[str, SkillPatch]] = defaultdict(dict)
    run_rows: list[dict[str, Any]] = []
    plan_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []

    for job_dir in sorted((root / "runs").glob("job_*")):
        status_path = job_dir / "job_status.json"
        if not status_path.exists():
            continue
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status.get("status") != "succeeded":
            continue
        job_id = str(status.get("job_id") or job_dir.name.removeprefix("job_"))
        job = jobs_by_id.get(job_id, {})
        for record in read_evidence_jsonl(job_dir / "evidence_records.jsonl"):
            enriched = _enrich_evidence_with_job(record, job_id, job)
            evidence_by_id[enriched.evidence_id] = enriched
        for patch_path in sorted((job_dir / "patches").glob("*.json")):
            kind = patch_path.stem
            for patch in _read_patch_array(patch_path):
                _merge_patch_into(patches_by_kind[kind], patch)
        run_summary_path = job_dir / "run_summary.json"
        if run_summary_path.exists():
            row = json.loads(run_summary_path.read_text(encoding="utf-8"))
            run_rows.append(_enrich_row(row, job_id, job))
        plan_path = job_dir / "mas_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            graph_summary = {}
            graph_summary_path = job_dir / "graph_validation_summary.json"
            if graph_summary_path.exists():
                graph_summary = json.loads(
                    graph_summary_path.read_text(encoding="utf-8")
                )
            plan_rows.append(_plan_row(plan, job_id, job, graph_summary))
        trace_path = job_dir / "trace_dynamics_summary.json"
        if trace_path.exists():
            for item in json.loads(trace_path.read_text(encoding="utf-8")):
                trace_rows.append(_enrich_row(item, job_id, job))

    evidence = sorted(evidence_by_id.values(), key=lambda record: record.evidence_id)
    write_evidence_jsonl(evidence, out / "batch_evidence.jsonl")
    batch_generated_patches = {
        "result_patches": build_result_patches_from_evidence(evidence),
        "cost_patches": build_cost_patches_from_evidence(evidence),
        "counterexample_patches": build_counterexample_patches_from_evidence(evidence),
        "trace_patches": TraceAnalystMinister().analyze_evidence(evidence),
    }
    for kind, generated in batch_generated_patches.items():
        for patch in generated:
            _merge_patch_into(patches_by_kind[kind], patch)
    batch_patch_dir = out / "batch_patches"
    all_patches = []
    for kind, patches in sorted(patches_by_kind.items()):
        values = sorted(patches.values(), key=lambda patch: patch.patch_id)
        all_patches.extend(values)
        write_patch_file(values, batch_patch_dir / f"{kind}.json")
    for required in [
        "result_patches.json",
        "cost_patches.json",
        "counterexample_patches.json",
        "trace_patches.json",
        "insight_patches.json",
    ]:
        path = batch_patch_dir / required
        if not path.exists():
            write_patch_file([], path)

    _write_csv(out / "matrix_run_summary.csv", run_rows)
    _write_csv(out / "matrix_plan_summary.csv", plan_rows)
    cross_seed_metrics = _cross_seed_metrics(run_rows, plan_rows, evidence)
    trace_summary = _cross_seed_trace_summary(evidence)
    oracle = _oracle_topology_by_condition(cross_seed_metrics)
    _write_json(out / "cross_seed_metrics.json", cross_seed_metrics)
    _write_json(out / "cross_seed_trace_summary.json", trace_summary)
    _write_json(out / "oracle_topology_by_condition.json", oracle)
    result = MatrixCollectResult(
        output_dir=str(out),
        evidence_count=len(evidence),
        patch_count=len(all_patches),
        run_count=len(run_rows),
        condition_count=len(cross_seed_metrics.get("conditions", [])),
    )
    _write_json(out / "collect_summary.json", result.model_dump(mode="json"))
    return result


def analyze_matrix_insights(
    *,
    skill_dir: Path | str,
    evidence_file: Path | str,
    summary_file: Path | str,
    trace_summary_file: Path | str,
    output_dir: Path | str,
    llm_provider: str,
    model_name: str,
    max_parallel_insight_shards: int = 1,
    role_llm_profiles: RoleLLMProfiles | None = None,
    role_llm_config_path: str | None = None,
    falsify_held_out: bool = False,
) -> InsightReport:
    """Extract batch-level MAS design insights from collected matrix evidence.

    ``falsify_held_out`` is opt-in and defaults to ``False`` so the existing
    counterfactual behavior (every rule-verified insight becomes a patch) is
    unchanged. When ``True`` the rule-verified report is additionally run through
    :func:`falsify_insights` against the cross-seed aggregate rows in
    ``summary`` (held-out evidence), and only insights whose held-out check
    passed (``claim_status == "observed"``) are turned into patches via
    ``insight_report_to_patches(require_verified=True)``. Contradicted insights
    are demoted to ``rejected`` and emit no accepted patch.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = read_evidence_jsonl(evidence_file)
    summary = json.loads(Path(summary_file).read_text(encoding="utf-8"))
    trace_summary = json.loads(Path(trace_summary_file).read_text(encoding="utf-8"))
    bank = SkillBank.load_dir(skill_dir)
    shards = _build_insight_shards(
        records=records,
        summary=summary,
        trace_summary=trace_summary,
        skill_bank=bank,
    )
    runtime = MASRuntimeConfig(
        llm_provider=llm_provider,
        model_name=model_name,
        role_llm_profiles=role_llm_profiles,
        role_llm_config_path=role_llm_config_path,
    )
    minister_llm = resolve_role_llm_config(runtime, "minister")
    if minister_llm.platform == "fake":
        reports = [_deterministic_shard_report(shard) for shard in shards]
    else:
        reports = _run_llm_insight_shards(
            shards=shards,
            runtime=runtime,
            max_workers=max_parallel_insight_shards,
        )
    merged = _merge_insight_reports(reports, experiment_id=str(evidence_file))
    verified = _verify_batch_insight_report(merged, records, bank)
    if falsify_held_out:
        held_out_rows = summary.get("conditions", [])
        falsified = falsify_insights(
            verified,
            held_out_rows if isinstance(held_out_rows, list) else [],
        )
        verified = falsified.model_copy(
            update={
                "skill_update_recommendations": insight_report_to_patches(
                    falsified, require_verified=True
                )
            }
        )
    _write_json(out / "insight_report.json", verified.model_dump(mode="json"))
    (out / "insight_report.md").write_text(
        format_insight_report(verified) + "\n",
        encoding="utf-8",
    )
    patch_dir = out / "patches"
    write_patch_file(
        verified.skill_update_recommendations,
        patch_dir / "insight_patches.json",
    )
    default_collected_patch = (
        Path(evidence_file).parent / "batch_patches" / "insight_patches.json"
    )
    if default_collected_patch.parent.exists():
        write_patch_file(verified.skill_update_recommendations, default_collected_patch)
    return verified


def _run_matrix_job(
    *,
    job: MatrixJob,
    skill_dir: Path | str,
    matrix_dir: Path,
    trace_enabled: bool,
    retain_traces: bool,
    verbose_events: bool,
    max_parallel_agents: int,
    max_parallel_ministers: int,
    resume: bool,
) -> MatrixJobStatus:
    job_dir = matrix_dir / "runs" / f"job_{job.job_id}"
    status_path = job_dir / "job_status.json"
    if resume and status_path.exists():
        status = MatrixJobStatus.model_validate(
            json.loads(status_path.read_text(encoding="utf-8"))
        )
        if status.status == "succeeded":
            return status.model_copy(update={"status": "skipped"})
    job_dir.mkdir(parents=True, exist_ok=True)
    _write_json(job_dir / "job_config.json", job.model_dump(mode="json"))
    started_at = _now()
    if verbose_events:
        print(
            (
                "[matrix-job-start] "
                f"job={job.job_id} phase={job.phase} objective={job.objective} "
                f"policy={job.planner_policy} topology={job.topology_name or 'planner'} "
                f"n_agents={job.n_agents} array_size={job.array_size} seed={job.seed}"
            ),
            flush=True,
        )
    try:
        bank = SkillBank.load_dir(skill_dir)
        request = PlannerRequest.from_names(
            n_agents=job.n_agents,
            objective=job.objective,  # type: ignore[arg-type]
            planner_mode=job.planner_mode,  # type: ignore[arg-type]
            array_size=job.array_size,
            merge_mode=job.merge_mode,
            init_mode=job.init_mode,
        )
        runtime = MASRuntimeConfig(
            llm_provider=job.llm_provider,
            model_name=job.model_name,
            role_llm_profiles=job.role_llm_profiles,
            role_llm_config_path=job.role_llm_config_path,
            value_min=job.value_min,
            value_max=job.value_max,
            max_parallel_agents=max_parallel_agents,
            max_parallel_ministers=max_parallel_ministers,
            trace_enabled=trace_enabled,
            retain_traces=retain_traces,
            verbose_events=verbose_events,
            output_dir=str(job_dir),
            graph_search_mode=job.graph_search_mode,
            num_graph_candidates=job.num_graph_candidates,
            graph_top_k=job.graph_top_k,
            graph_candidate_score_mode=job.graph_candidate_score_mode,
            graph_max_steps=job.graph_max_steps,
            graph_max_messages=job.graph_max_messages,
            graph_max_receiver_fan_in=job.graph_max_receiver_fan_in,
            graph_repair_attempts=job.graph_repair_attempts,
            graph_validation_seeds=job.graph_validation_seeds,
        )
        result = run_mas_pipeline(
            request=request,
            runtime=runtime,
            skill_bank=bank,
            seed=job.seed,
            llm_insights=False,
            planner_policy=job.planner_policy,
            fixed_topology=job.topology_name,
            print_sections=verbose_events,
        )
        token_cost = (
            result.protocol_result.total_prompt_tokens
            + result.protocol_result.total_completion_tokens
        )
        status = MatrixJobStatus(
            job_id=job.job_id,
            status="succeeded",
            started_at=started_at,
            ended_at=_now(),
            output_dir=str(job_dir),
            run_id=result.protocol_result.run_id,
            final_rmse=result.protocol_result.final_result.rmse,
            exact_match=result.protocol_result.final_result.exact_match,
            token_cost=token_cost,
        )
    except Exception as exc:  # pragma: no cover - exercised by manual matrix runs.
        status = MatrixJobStatus(
            job_id=job.job_id,
            status="failed",
            started_at=started_at,
            ended_at=_now(),
            output_dir=str(job_dir),
            error=f"{exc}\n{traceback.format_exc()}",
        )
    if verbose_events:
        print(
            (
                "[matrix-job-done] "
                f"job={job.job_id} status={status.status} "
                f"rmse={status.final_rmse} exact={status.exact_match} "
                f"tokens={status.token_cost}"
            ),
            flush=True,
        )
    _write_json(status_path, status.model_dump(mode="json"))
    with (matrix_dir / "logs" / "scheduler.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(status.model_dump(mode="json"), sort_keys=True) + "\n")
    return status


def _cross_seed_metrics(
    run_rows: list[dict[str, Any]],
    plan_rows: list[dict[str, Any]],
    evidence: list[EvidenceRecord],
) -> dict[str, Any]:
    plan_by_job = {row["job_id"]: row for row in plan_rows}
    trace_by_job: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in evidence:
        job_id = str(record.metrics.get("job_id", ""))
        if record.source_type == "trace":
            trace_by_job[job_id].append(record)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in run_rows:
        key = _condition_key(row)
        groups[key].append(row)
    conditions = []
    for key, rows in sorted(groups.items()):
        job_ids = [str(row.get("job_id")) for row in rows]
        plans = [plan_by_job[job_id] for job_id in job_ids if job_id in plan_by_job]
        traces = [trace for job_id in job_ids for trace in trace_by_job.get(job_id, [])]
        retry_values = [
            float(trace.dynamics.get("merge_quality", {}).get("retry_attempts", 0.0))
            for trace in traces
        ]
        parse_values = [
            float(trace.dynamics.get("merge_quality", {}).get("parse_error_count", 0.0))
            for trace in traces
        ]
        full_wrong = [
            1.0 if "full_coverage_wrong_answer" in trace.risk_tags else 0.0
            for trace in traces
        ]
        rmse = [_float(row.get("FinalRMSE")) for row in rows]
        exact = [1.0 if _bool(row.get("FinalExactMatch")) else 0.0 for row in rows]
        condition = {
            **json.loads(key),
            "run_count": len(rows),
            "seeds": sorted({_int(row.get("Seed")) for row in rows}),
            "mean_rmse": _mean(rmse),
            "std_rmse": pstdev(rmse) if len(rmse) > 1 else 0.0,
            "exact_match_rate": _mean(exact),
            "mean_messages": _mean([_float(row.get("TotalMessages")) for row in rows]),
            "mean_model_calls": _mean([_float(row.get("TotalModelCalls")) for row in rows]),
            "mean_token_cost": _mean(
                [
                    _float(row.get("TotalPromptTokens"))
                    + _float(row.get("TotalCompletionTokens"))
                    for row in rows
                ]
            ),
            "mean_retry_attempts": _mean(retry_values),
            "mean_parse_errors": _mean(parse_values),
            "full_coverage_wrong_answer_rate": _mean(full_wrong),
            "skill_grounding_rate": _mean(
                [
                    1.0
                    if plan.get("skill_id")
                    and not str(plan.get("skill_id")).startswith("fixed_")
                    else 0.0
                    for plan in plans
                ]
            ),
            "valid_plan_rate": _mean([1.0 if plan.get("topology_name") else 0.0 for plan in plans]),
            "fallback_rate": _mean(
                [
                    1.0
                    if "[emperor-plan-fallback:" in str(plan.get("rationale", ""))
                    or "[free-graph-fallback:" in str(plan.get("rationale", ""))
                    else 0.0
                    for plan in plans
                ]
            ),
            "mean_protocol_steps": _mean(
                [_float(plan.get("protocol_steps")) for plan in plans]
            ),
            "mean_protocol_messages": _mean(
                [_float(plan.get("protocol_messages")) for plan in plans]
            ),
            "generated_graph_rate": _mean(
                [1.0 if plan.get("generated_graph") else 0.0 for plan in plans]
            ),
            "mean_candidate_count": _mean(
                [_float(plan.get("candidate_count")) for plan in plans]
            ),
            "mean_rejected_candidate_count": _mean(
                [_float(plan.get("rejected_candidate_count")) for plan in plans]
            ),
            "mean_selected_candidate_score": _mean(
                [
                    _float(plan.get("selected_candidate_score"))
                    for plan in plans
                    if plan.get("selected_candidate_score") not in {None, ""}
                ]
            ),
        }
        conditions.append(condition)
    return {"conditions": conditions, "created_at": _now()}


def _cross_seed_trace_summary(evidence: list[EvidenceRecord]) -> dict[str, Any]:
    groups: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in evidence:
        if record.source_type == "trace":
            groups[_record_condition_key(record)].append(record)
    conditions = []
    for key, rows in sorted(groups.items()):
        conditions.append(
            {
                **json.loads(key),
                "trace_count": len(rows),
                "mean_coverage_gain": _mean_nested(
                    rows,
                    "coverage_growth",
                    "mean_coverage_gain",
                ),
                "mean_final_coverage": _mean_nested(
                    rows,
                    "coverage_growth",
                    "final_mean_coverage",
                ),
                "mean_sink_best_rmse_gap": _mean_nested(
                    rows,
                    "aggregation_reliability",
                    "sink_best_rmse_gap",
                ),
                "mean_retry_attempts": _mean_nested(
                    rows,
                    "merge_quality",
                    "retry_attempts",
                ),
                "mean_parse_errors": _mean_nested(
                    rows,
                    "merge_quality",
                    "parse_error_count",
                ),
                "risk_tags": sorted({tag for row in rows for tag in row.risk_tags}),
                "evidence_refs": [row.evidence_id for row in rows],
            }
        )
    return {"conditions": conditions, "created_at": _now()}


def _oracle_topology_by_condition(cross_seed_metrics: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for condition in cross_seed_metrics.get("conditions", []):
        key = json.dumps(
            {
                "objective": condition.get("objective"),
                "n_agents": condition.get("n_agents"),
                "array_size": condition.get("array_size"),
                "merge_mode": condition.get("merge_mode"),
                "init_mode": condition.get("init_mode"),
            },
            sort_keys=True,
        )
        groups[key].append(condition)
    oracle = {}
    for key, rows in sorted(groups.items()):
        best = max(rows, key=_objective_score)
        oracle[key] = {
            "topology_name": best.get("topology_name"),
            "planner_policy": best.get("planner_policy"),
            "score": _objective_score(best),
            "mean_rmse": best.get("mean_rmse"),
            "mean_messages": best.get("mean_messages"),
            "mean_token_cost": best.get("mean_token_cost"),
        }
    return {"conditions": oracle, "created_at": _now()}


def _build_insight_shards(
    *,
    records: list[EvidenceRecord],
    summary: dict[str, Any],
    trace_summary: dict[str, Any],
    skill_bank: SkillBank,
) -> list[dict[str, Any]]:
    records_by_condition: dict[str, list[str]] = defaultdict(list)
    record_objects_by_condition: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        key = _record_condition_key(record)
        records_by_condition[key].append(record.evidence_id)
        record_objects_by_condition[key].append(record)
    trace_by_key = {
        json.dumps(
            {
                key: value
                for key, value in condition.items()
                if key
                in {
                    "objective",
                    "planner_policy",
                    "topology_name",
                    "n_agents",
                    "array_size",
                    "merge_mode",
                    "init_mode",
                    "graph_search_mode",
                }
            },
            sort_keys=True,
        ): condition
        for condition in trace_summary.get("conditions", [])
    }
    shards = []
    for condition in summary.get("conditions", []):
        key_data = {
            key: condition.get(key)
            for key in {
                "objective",
                "planner_policy",
                "topology_name",
                "n_agents",
                "array_size",
                "merge_mode",
                "init_mode",
                "graph_search_mode",
            }
        }
        key = json.dumps(key_data, sort_keys=True)
        _objective, _operators, skill_id, _lesson = classify_topology(
            str(condition.get("topology_name", ""))
        )
        condition_scope = infer_condition_scope([condition])
        candidate_skill_id = condition_specific_skill_id(
            skill_id,
            str(condition.get("topology_name", "")),
            condition_scope,
        )
        shards.append(
            {
                "condition": condition,
                "trace_summary": trace_by_key.get(key, {}),
                "evidence_refs": records_by_condition.get(key, []),
                "topology_structures": topology_structures_from_records(
                    record_objects_by_condition.get(key, [])
                ),
                "affected_skill": (
                    candidate_skill_id
                    if skill_bank.get(candidate_skill_id)
                    else skill_id if skill_bank.get(skill_id) else None
                ),
                "current_skill_versions": {
                    skill.skill_id: skill.version for skill in skill_bank
                },
            }
        )
    return shards


def _deterministic_shard_report(shard: dict[str, Any]) -> InsightReport:
    condition = shard["condition"]
    topology = str(condition.get("topology_name", "unknown"))
    refs = [str(ref) for ref in shard.get("evidence_refs", [])]
    affected = [shard["affected_skill"]] if shard.get("affected_skill") else []
    insights: list[MASInsight] = []
    run_count = int(condition.get("run_count", 0))
    claim_status = "observed" if run_count >= 3 else "hypothesis"
    condition_scope = infer_condition_scope([condition])
    structure_features = infer_topology_structure_features(topology, [condition])
    operation_recommendations = default_operation_recommendations(
        topology,
        structure_features,
        condition_scope,
    )
    condition_buckets = [condition_scope]
    if refs:
        insights.append(
            MASInsight(
                insight_id=f"{_slug(topology)}_{_slug(str(condition.get('objective')))}_tradeoff",
                title=f"{topology} batch tradeoff",
                insight_type="tradeoff",
                claim_status=claim_status,
                summary=(
                    f"{topology} achieved mean RMSE {condition.get('mean_rmse')} "
                    f"with mean token cost {condition.get('mean_token_cost')}."
                ),
                evidence_refs=refs,
                metric_snapshot=condition,
                affected_skills=affected,
                recommended_actions=["merge batch tradeoff evidence"],
                operation_recommendations=operation_recommendations,
                condition_buckets=condition_buckets,
                confidence=0.65 if claim_status == "observed" else 0.4,
                falsification_test="Evaluate on held-out seeds.",
            )
        )
    if float(condition.get("full_coverage_wrong_answer_rate", 0.0)) > 0 and refs:
        insights.append(
            MASInsight(
                insight_id=f"{_slug(topology)}_full_coverage_wrong_answer",
                title=f"{topology} can reach coverage while remaining wrong",
                insight_type="risk_pattern",
                claim_status=claim_status,
                summary=(
                    "Full coverage did not guarantee exact CF counts; planner "
                    "skills should penalize semantic merge risk."
                ),
                evidence_refs=refs,
                metric_snapshot={
                    "full_coverage_wrong_answer_rate": condition.get(
                        "full_coverage_wrong_answer_rate"
                    ),
                    "mean_rmse": condition.get("mean_rmse"),
                },
                affected_skills=affected,
                recommended_actions=[
                    "add full_coverage_wrong_answer risk note and fallback"
                ],
                operation_recommendations=[
                    {
                        "action_type": "avoid",
                        "target": "edge_schedule",
                        "instruction": (
                            "Do not promote this structure globally when full "
                            "coverage still produces wrong final answers; add an "
                            "audit or deterministic merge validation step first."
                        ),
                        "conditions": condition_scope,
                        "expected_effect": {"semantic_merge_risk": "decrease"},
                    }
                ],
                condition_buckets=condition_buckets,
                confidence=0.7 if claim_status == "observed" else 0.45,
                falsification_test=(
                    "Run deterministic structured merge audit on held-out seeds."
                ),
            )
        )
    return InsightReport(
        report_id=f"shard_report_{_slug(topology)}_{_stamp()}",
        experiment_id=str(condition.get("objective", "matrix")),
        executive_summary=f"Batch insights for {topology}.",
        key_insights=insights,
    )


def _run_llm_insight_shards(
    *,
    shards: list[dict[str, Any]],
    runtime: MASRuntimeConfig,
    max_workers: int,
) -> list[InsightReport]:
    def analyze(shard: dict[str, Any]) -> InsightReport:
        role_llm = resolve_role_llm_config(runtime, "minister")
        client = create_role_llm_client(runtime, "minister")
        prompt = _build_batch_insight_prompt(shard)
        response = client.complete(
            prompt,
            model_name=role_llm.model_name,
            temperature=role_llm.temperature,
        )
        return InsightReport.model_validate(_loads_json_object(response.text))

    if max_workers <= 1:
        return [analyze(shard) for shard in shards]
    reports = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(analyze, shard) for shard in shards]
        for future in as_completed(futures):
            try:
                reports.append(future.result())
            except Exception as exc:
                reports.append(
                    InsightReport(
                        report_id=f"failed_shard_{_stamp()}",
                        experiment_id="matrix",
                        rejected_insights=[{"reason": "llm_failure", "error": str(exc)}],
                    )
                )
    return reports


def _verify_batch_insight_report(
    report: InsightReport,
    records: list[EvidenceRecord],
    skill_bank: SkillBank,
) -> InsightReport:
    records_by_id = {record.evidence_id: record for record in records}
    accepted: list[MASInsight] = []
    rejected = list(report.rejected_insights)
    for insight in report.key_insights:
        if not insight.evidence_refs:
            rejected.append({"insight_id": insight.insight_id, "reason": "missing_refs"})
            continue
        missing = [ref for ref in insight.evidence_refs if ref not in records_by_id]
        if missing:
            rejected.append(
                {
                    "insight_id": insight.insight_id,
                    "reason": "missing_evidence",
                    "missing": missing,
                }
            )
            continue
        if not _affected_skills_match_refs(insight, records_by_id, skill_bank):
            rejected.append(
                {
                    "insight_id": insight.insight_id,
                    "reason": "affected_skill_topology_mismatch",
                }
            )
            continue
        seed_count = len(
            {
                records_by_id[ref].seed
                for ref in insight.evidence_refs
                if records_by_id[ref].seed is not None
            }
        )
        updated = insight
        if seed_count < 3 and insight.claim_status != "hypothesis":
            updated = insight.model_copy(update={"claim_status": "hypothesis"})
        accepted.append(updated)
    verified = report.model_copy(update={"key_insights": accepted, "rejected_insights": rejected})
    return verified.model_copy(
        update={"skill_update_recommendations": insight_report_to_patches(verified)}
    )


def _affected_skills_match_refs(
    insight: MASInsight,
    records_by_id: dict[str, EvidenceRecord],
    skill_bank: SkillBank,
) -> bool:
    if not insight.affected_skills:
        return True
    ref_topologies = {
        records_by_id[ref].topology_name
        for ref in insight.evidence_refs
        if records_by_id[ref].topology_name
    }
    for skill_id in insight.affected_skills:
        skill = skill_bank.get(skill_id)
        if skill is None:
            return False
        if skill.topology_name and ref_topologies and skill.topology_name not in ref_topologies:
            return False
    return True


def _merge_insight_reports(
    reports: list[InsightReport],
    *,
    experiment_id: str,
) -> InsightReport:
    insights = []
    rejected = []
    followups = []
    for report in reports:
        insights.extend(report.key_insights)
        rejected.extend(report.rejected_insights)
        followups.extend(report.followup_experiments)
    return InsightReport(
        report_id=f"batch_insight_report_{_stamp()}",
        experiment_id=experiment_id,
        executive_summary="Batch-level MAS insights extracted from matrix evidence.",
        key_insights=insights,
        rejected_insights=rejected,
        followup_experiments=followups,
    )


def _build_batch_insight_prompt(shard: dict[str, Any]) -> str:
    return json.dumps(
        {
            "role": (
                "Batch MAS topology and skill-evolution analyst. Convert this "
                "condition shard into evidence-grounded insights for future "
                "explicit DAG generation."
            ),
            "task": (
                "Return one json object containing evidence-grounded MAS "
                "design insights for this condition shard. Focus on why a "
                "communication structure helped or failed, not just whether the "
                "metric was high or low."
            ),
            "shard": shard,
            "schema": InsightReport.model_json_schema(),
            "analysis_responsibilities": [
                "Identify coverage, sink, fan-in, provenance, and cost/accuracy mechanisms.",
                "State whether each claim is observed, inferred, or a hypothesis.",
                "Recommend planner changes that can alter future generated DAG edges.",
                "Write each accepted structure-design lesson so it can be stored as a planner skill design_insight.",
                "Emit operation_recommendations with action_type, target, instruction, conditions, and expected_effect.",
                "Use condition_buckets when the lesson is specific to n_agents, array_size, objective, or merge/init mode.",
                "Flag repeatedly bad structures as avoid-skill candidates.",
            ],
            "rules": [
                "Every insight must cite evidence_refs from the shard.",
                "Use hypothesis when seed support is below 3.",
                "Do not recommend direct skill writes; only insight patches are allowed.",
                "Each operation recommendation must be executable by changing edge order, sink selection, fan-in, reducer scope, provenance flow, or trigger buckets.",
                "Do not reward a topology for low cost when accuracy or coverage collapsed.",
            ],
        },
        indent=2,
        sort_keys=True,
    )


def _merge_patch_into(target: dict[str, SkillPatch], patch: SkillPatch) -> None:
    current = target.get(patch.patch_id)
    if current is None:
        target[patch.patch_id] = patch
        return
    refs = _dedupe([*current.evidence_refs, *patch.evidence_refs])
    evidence = [*current.evidence, *patch.evidence]
    candidate = current.candidate_skill
    if candidate is not None:
        candidate = candidate.model_copy(
            update={"evidence_refs": _dedupe([*candidate.evidence_refs, *refs])}
        )
    target[patch.patch_id] = current.model_copy(
        update={
            "evidence_refs": refs,
            "evidence": evidence,
            "candidate_skill": candidate,
        }
    )


def _read_patch_array(path: Path) -> list[SkillPatch]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("patches", [data])
    return [SkillPatch.model_validate(item) for item in data]


def _enrich_evidence_with_job(
    record: EvidenceRecord,
    job_id: str,
    job: dict[str, Any],
) -> EvidenceRecord:
    return record.model_copy(
        update={
            "metrics": {
                **record.metrics,
                "job_id": job_id,
                "phase": job.get("phase"),
                "objective": job.get("objective"),
                "planner_mode": job.get("planner_mode"),
                "planner_policy": job.get("planner_policy"),
                "requested_topology": job.get("topology_name"),
                "array_size": record.metrics.get("array_size", job.get("array_size")),
                "merge_mode": record.metrics.get("merge_mode", job.get("merge_mode")),
                "init_mode": record.metrics.get("init_mode", job.get("init_mode")),
                "graph_search_mode": job.get("graph_search_mode"),
                "num_graph_candidates": job.get("num_graph_candidates"),
                "graph_top_k": job.get("graph_top_k"),
                "graph_candidate_score_mode": job.get("graph_candidate_score_mode"),
            }
        }
    )


def _enrich_row(row: dict[str, Any], job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "job_id": job_id,
        "phase": job.get("phase"),
        "objective": job.get("objective"),
        "planner_mode": job.get("planner_mode"),
        "planner_policy": job.get("planner_policy"),
        "requested_topology": job.get("topology_name"),
        "graph_search_mode": job.get("graph_search_mode"),
        "num_graph_candidates": job.get("num_graph_candidates"),
        "graph_candidate_score_mode": job.get("graph_candidate_score_mode"),
    }


def _plan_row(
    plan: dict[str, Any],
    job_id: str,
    job: dict[str, Any],
    graph_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = plan.get("protocol_spec") or {}
    steps = spec.get("steps") if isinstance(spec, dict) else []
    metadata = spec.get("metadata", {}) if isinstance(spec, dict) else {}
    graph_summary = graph_summary or {}
    return {
        "job_id": job_id,
        "phase": job.get("phase"),
        "objective": job.get("objective"),
        "planner_mode": plan.get("planner_mode"),
        "requested_planner_mode": job.get("planner_mode"),
        "planner_policy": job.get("planner_policy"),
        "requested_topology": job.get("topology_name"),
        "topology_name": plan.get("topology_name"),
        "skill_id": plan.get("skill_id"),
        "operators": ",".join(str(item) for item in plan.get("operators", [])),
        "score": plan.get("score"),
        "fallback_skill_id": plan.get("fallback_skill_id"),
        "rationale": plan.get("rationale"),
        "protocol_steps": len(steps) if isinstance(steps, list) else 0,
        "protocol_messages": sum(
            len(step.get("transmissions", []))
            for step in steps
            if isinstance(step, dict)
        )
        if isinstance(steps, list)
        else 0,
        "generated_graph": bool(metadata.get("generated_graph")),
        "generated_graph_candidate_id": metadata.get("candidate_id"),
        "generated_graph_selected_primary": metadata.get("selected_primary"),
        "protocol_spec": spec if isinstance(spec, dict) else {},
        "graph_search_mode": job.get("graph_search_mode"),
        "num_graph_candidates": job.get("num_graph_candidates"),
        "graph_top_k": job.get("graph_top_k"),
        "graph_candidate_score_mode": job.get("graph_candidate_score_mode"),
        "candidate_count": graph_summary.get("candidate_count", 0),
        "rejected_candidate_count": graph_summary.get("rejected_candidate_count", 0),
        "selected_candidate_score": graph_summary.get("selected_candidate_score"),
        "candidate_score_mode": graph_summary.get("candidate_score_mode"),
    }


def _condition_key(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "objective": row.get("objective"),
            "planner_policy": row.get("planner_policy"),
            "topology_name": row.get("Topology") or row.get("topology_name"),
            "n_agents": _int(row.get("Agents") or row.get("n_agents")),
            "array_size": _int(row.get("ArraySize") or row.get("array_size")),
            "merge_mode": row.get("MergeMode") or row.get("merge_mode"),
            "init_mode": row.get("InitMode") or row.get("init_mode"),
            "graph_search_mode": row.get("graph_search_mode"),
        },
        sort_keys=True,
    )


def _record_condition_key(record: EvidenceRecord) -> str:
    return json.dumps(
        {
            "objective": record.metrics.get("objective"),
            "planner_policy": record.metrics.get("planner_policy"),
            "topology_name": record.topology_name,
            "n_agents": record.n_agents,
            "array_size": record.metrics.get("array_size"),
            "merge_mode": record.metrics.get("merge_mode"),
            "init_mode": record.metrics.get("init_mode"),
            "graph_search_mode": record.metrics.get("graph_search_mode"),
        },
        sort_keys=True,
    )


def objective_score(row: dict[str, Any]) -> float:
    """Score one aggregate condition according to the requested objective."""
    objective = str(row.get("objective", "balanced"))
    rmse = float(row.get("mean_rmse", 0.0))
    messages = float(row.get("mean_messages", 0.0))
    tokens = float(row.get("mean_token_cost", 0.0))
    exact = float(row.get("exact_match_rate", 0.0))
    if objective == "budget_first":
        return exact - 0.4 * rmse - 0.02 * messages - 0.0001 * tokens
    if objective == "accuracy_first":
        return exact - rmse - 0.002 * messages - 0.00001 * tokens
    return exact - 0.7 * rmse - 0.01 * messages - 0.00005 * tokens


def _objective_score(row: dict[str, Any]) -> float:
    return objective_score(row)


def _skill_bank_version(bank: SkillBank) -> str:
    payload = {
        skill.skill_id: skill.version
        for skill in sorted(bank, key=lambda item: item.skill_id)
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _stable_job_id(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def _loads_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _mean_nested(rows: list[EvidenceRecord], section: str, key: str) -> float:
    values = []
    for row in rows:
        data = row.dynamics.get(section, {})
        if isinstance(data, dict) and data.get(key) is not None:
            values.append(float(data[key]))
    return _mean(values)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _float(value: Any) -> float:
    if value in {None, ""}:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    if value in {None, ""}:
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
