"""Transparent real/fake LLM MAS pipeline orchestration."""

from __future__ import annotations

import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.mas.consolidation import write_patch_file
from exp_graph.mas.evidence import write_evidence_jsonl
from exp_graph.mas.evolution import (
    TraceAnalystMinister,
    build_cost_patches_from_evidence,
    build_counterexample_patches_from_evidence,
    build_result_patches_from_evidence,
)
from exp_graph.mas.formatting import (
    format_insight_report,
    format_mas_plan,
    format_minister_summary,
)
from exp_graph.mas.graph_generation import plan_free_graph
from exp_graph.mas.insights import LLMInsightMinister, build_evidence_pack
from exp_graph.mas.llm_planner import LLMEmperorPlanner
from exp_graph.mas.evolution import classify_topology
from exp_graph.mas.schemas import (
    EvidenceRecord,
    InsightReport,
    MASPlan,
    MASRuntimeConfig,
    MinisterSummary,
    PlannerRequest,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner import ProtocolExperimentResult, ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks import CountFrequencyTaskAdapter


class MASPipelineResult(BaseModel):
    """Artifacts produced by one transparent MAS pipeline run."""

    request: PlannerRequest
    plan: MASPlan
    protocol_result: ProtocolExperimentResult
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    patches: list[SkillPatch] = Field(default_factory=list)
    minister_summary: MinisterSummary
    insight_report: InsightReport | None = None
    output_dir: str


def run_mas_pipeline(
    *,
    request: PlannerRequest,
    runtime: MASRuntimeConfig,
    skill_bank: SkillBank,
    seed: int,
    global_task: dict[str, Any] | None = None,
    task_adapter: CountFrequencyTaskAdapter | None = None,
    llm_insights: bool = False,
    print_sections: bool = False,
    planner_policy: str = "skill_grounded",
    fixed_topology: str | None = None,
) -> MASPipelineResult:
    """Run emperor planning, soldier execution, minister analysis, and artifact writes."""
    adapter = task_adapter or CountFrequencyTaskAdapter()
    task = global_task or adapter.build_global_task(
        array_size=request.array_size or 64,
        seed=seed,
    )
    output_dir = Path(runtime.output_dir or f"mas_pipeline_{_stamp()}")
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime = runtime.model_copy(update={"output_dir": str(output_dir)})
    trace_dir = Path(runtime.trace_dir or output_dir / "traces")
    if runtime.trace_enabled:
        trace_dir.mkdir(parents=True, exist_ok=True)
        runtime = runtime.model_copy(update={"trace_dir": str(trace_dir)})

    planner: LLMEmperorPlanner | None = LLMEmperorPlanner(
        skill_bank=SkillBank([]) if planner_policy == "llm_free" else skill_bank,
        runtime=runtime,
    )
    free_graph_fallback_reason = None
    free_graph_raw_responses: list[str] = []
    if planner_policy in {"fixed_topology", "topology_sweep"}:
        if not fixed_topology:
            raise ValueError(f"{planner_policy} requires fixed_topology")
        _objective, operators, _skill_id, _lesson = classify_topology(fixed_topology)
        plan = MASPlan(
            planner_mode="topology_select",
            topology_name=fixed_topology,
            skill_id=f"fixed_{fixed_topology}",
            operators=operators,
            rationale=f"Fixed topology baseline for {fixed_topology}.",
        )
    elif planner_policy == "free_graph":
        free_graph = plan_free_graph(
            request=request,
            runtime=runtime,
            skill_bank=skill_bank,
            seed=seed,
            task_adapter=adapter,
            output_dir=output_dir,
        )
        plan = free_graph.plan
        free_graph_fallback_reason = free_graph.fallback_reason
        free_graph_raw_responses = free_graph.raw_responses
        planner = None
    else:
        plan = planner.plan(request)
    _write_json(output_dir / "mas_plan.json", plan.model_dump(mode="json"))
    (output_dir / "mas_plan.md").write_text(format_mas_plan(plan) + "\n", encoding="utf-8")
    _write_json(
        output_dir / "emperor_raw_response.json",
        {
            "fallback_reason": planner.last_fallback_reason if planner is not None else None,
            "raw_response": (
                planner.last_raw_response.model_dump(mode="json")
                if planner is not None and planner.last_raw_response is not None
                else None
            ),
            "free_graph_fallback_reason": free_graph_fallback_reason,
            "free_graph_raw_responses": free_graph_raw_responses,
        },
    )
    if print_sections:
        print("[emperor-plan]")
        print(format_mas_plan(plan))
        if planner is not None and planner.last_fallback_reason:
            print("[emperor-plan-fallback]")
            print(planner.last_fallback_reason)
        if free_graph_fallback_reason:
            print("[emperor-plan-fallback]")
            print(free_graph_fallback_reason)

    config = ProtocolRunnerConfig(
        topology_name=plan.topology_name,
        n_agents=request.n_agents,
        seed=seed,
        model_name=runtime.model_name,
        merge_mode=request.merge_mode,  # type: ignore[arg-type]
        init_mode=request.init_mode,  # type: ignore[arg-type]
        llm_provider=runtime.llm_provider,
        temperature=runtime.temperature,
        json_retry_attempts=runtime.json_retry_attempts,
        allow_deterministic_repair=runtime.allow_deterministic_repair,
        max_parallel_agents=runtime.max_parallel_agents,
        trace_enabled=runtime.trace_enabled,
        retain_traces=runtime.retain_traces,
        trace_dir=runtime.trace_dir,
        verbose_events=runtime.verbose_events,
        protocol_spec=plan.protocol_spec,
        **{
            key: value
            for key, value in plan.config_overrides.items()
            if key != "protocol_spec"
        },
    )
    if print_sections:
        print("[soldier-execution]")
    protocol_result = ProtocolRunner(
        config=config,
        task_adapter=adapter,
        global_task=task,
    ).run()
    summary = protocol_result.to_summary_dict()
    _write_json(
        output_dir / "protocol_result.json",
        protocol_result.model_dump(mode="json"),
    )
    _write_json(output_dir / "run_summary.json", summary)
    _write_csv(output_dir / "run_summary.csv", [summary])
    _write_csv(
        output_dir / "global_step_metrics.csv",
        [row.model_dump(mode="json") for row in protocol_result.global_step_metrics],
    )
    _write_csv(
        output_dir / "agent_step_metrics.csv",
        [row.model_dump(mode="json") for row in protocol_result.agent_step_metrics],
    )

    records = _evidence_records_from_result(protocol_result)
    write_evidence_jsonl(records, output_dir / "evidence_records.jsonl")
    trace_dynamics = [
        record.model_dump(mode="json")
        for record in records
        if record.source_type == "trace"
    ]
    _write_json(output_dir / "trace_dynamics_summary.json", trace_dynamics)
    _write_csv(output_dir / "trace_dynamics_summary.csv", trace_dynamics)

    patch_dir = output_dir / "patches"
    minister_patch_groups = _run_ministers(
        records=records,
        max_workers=runtime.max_parallel_ministers,
    )
    all_patches: list[SkillPatch] = []
    for name, patches in minister_patch_groups.items():
        all_patches.extend(patches)
        write_patch_file(patches, patch_dir / f"{name}_patches.json")

    evidence_pack = build_evidence_pack(
        records=records,
        skill_bank=skill_bank,
        experiment_id=protocol_result.run_id,
    )
    _write_json(output_dir / "evidence_pack.json", evidence_pack)
    insight_report = None
    if llm_insights:
        insight_report = LLMInsightMinister(runtime=runtime).analyze(
            evidence_pack=evidence_pack,
            skill_bank=skill_bank,
        )
        all_patches.extend(insight_report.skill_update_recommendations)
        write_patch_file(
            insight_report.skill_update_recommendations,
            patch_dir / "insight_patches.json",
        )
        _write_json(
            output_dir / "insight_report.json",
            insight_report.model_dump(mode="json"),
        )
        (output_dir / "insight_report.md").write_text(
            format_insight_report(insight_report) + "\n",
            encoding="utf-8",
        )

    summary_model = _build_minister_summary(
        protocol_result=protocol_result,
        patches=all_patches,
        output_dir=output_dir,
    )
    _write_json(
        output_dir / "minister_summary.json",
        summary_model.model_dump(mode="json"),
    )
    (output_dir / "minister_summary.md").write_text(
        format_minister_summary(summary_model) + "\n",
        encoding="utf-8",
    )
    if print_sections:
        print("[minister-summary]")
        print(format_minister_summary(summary_model))
        print("[patch-candidates]")
        for action, count in sorted(Counter(patch.action for patch in all_patches).items()):
            print(f"{action}: {count}")

    return MASPipelineResult(
        request=request,
        plan=plan,
        protocol_result=protocol_result,
        evidence_records=records,
        patches=all_patches,
        minister_summary=summary_model,
        insight_report=insight_report,
        output_dir=str(output_dir),
    )


def _run_ministers(
    *,
    records: list[EvidenceRecord],
    max_workers: int,
) -> dict[str, list[SkillPatch]]:
    jobs = {
        "result": lambda: build_result_patches_from_evidence(records),
        "cost": lambda: build_cost_patches_from_evidence(records),
        "counterexample": lambda: build_counterexample_patches_from_evidence(records),
        "trace": lambda: TraceAnalystMinister().analyze_evidence(records),
    }
    if max_workers <= 1:
        return {name: job() for name, job in jobs.items()}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(job): name for name, job in jobs.items()}
        return {futures[future]: future.result() for future in futures}


def _evidence_records_from_result(
    result: ProtocolExperimentResult,
) -> list[EvidenceRecord]:
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    summary = result.to_summary_dict()
    run_record = EvidenceRecord(
        evidence_id=f"run:{result.run_id}",
        source_dir=result.trace_path or "",
        source_type="run",
        topology_name=result.config.topology_name,
        n_agents=result.config.n_agents,
        seed=result.config.seed,
        metrics={
            "job_id": result.config.run_id,
            "array_size": summary["ArraySize"],
            "merge_mode": summary["MergeMode"],
            "init_mode": summary["InitMode"],
            "provider": result.config.llm_provider,
            "model": result.config.model_name,
            "total_steps": summary["TotalSteps"],
            "total_messages": summary["TotalMessages"],
            "total_model_calls": summary["TotalModelCalls"],
            "token_cost": summary["TotalPromptTokens"]
            + summary["TotalCompletionTokens"],
            "total_fallbacks": summary["TotalDeterministicFallbacks"],
            "final_rmse": summary["FinalRMSE"],
            "final_norm_l1": summary["FinalNormalizedL1Error"],
            "final_exact_match": summary["FinalExactMatch"],
            "vote_rmse": summary["VoteRMSE"],
            "average_rmse": summary["AverageRMSE"],
            "vote_average_disagreement_rmse": summary[
                "VoteAverageDisagreementRMSE"
            ],
            "generated_graph": bool(
                result.config.protocol_spec
                and result.config.protocol_spec.metadata.get("generated_graph")
            ),
            "generated_graph_candidate_id": (
                result.config.protocol_spec.metadata.get("candidate_id")
                if result.config.protocol_spec is not None
                else None
            ),
            "generated_graph_selected_primary": (
                result.config.protocol_spec.metadata.get("selected_primary")
                if result.config.protocol_spec is not None
                else None
            ),
            "protocol_spec_metadata": (
                result.config.protocol_spec.metadata
                if result.config.protocol_spec is not None
                else {}
            ),
        },
        risk_tags=_run_risk_tags(summary),
        created_at=created_at,
    )
    return [run_record, _trace_record_from_result(result, created_at)]


def _trace_record_from_result(
    result: ProtocolExperimentResult,
    created_at: str,
) -> EvidenceRecord:
    initial = min(result.global_step_metrics, key=lambda row: row.step_idx)
    final = max(result.global_step_metrics, key=lambda row: row.step_idx)
    final_step = max(row.step_idx for row in result.agent_step_metrics)
    final_agents = [
        row for row in result.agent_step_metrics if row.step_idx == final_step
    ]
    sink_id = result.config.n_agents - 1
    sink = next((row for row in final_agents if row.agent_id == sink_id), None)
    best_global_rmse = min((row.global_rmse for row in final_agents), default=0.0)
    sink_global_rmse = sink.global_rmse if sink is not None else 0.0
    fan_ins = [len(trace.neighbors) for trace in result.agent_step_traces]
    dynamics = {
        "coverage_growth": {
            "initial_mean_coverage": initial.mean_coverage,
            "final_mean_coverage": final.mean_coverage,
            "mean_coverage_gain": final.mean_coverage - initial.mean_coverage,
            "initial_max_coverage": initial.max_coverage,
            "final_max_coverage": final.max_coverage,
            "max_coverage_gain": final.max_coverage - initial.max_coverage,
            "final_full_coverage_agents": final.full_coverage_agents,
        },
        "aggregation_reliability": {
            "sink_agent_id": sink_id,
            "sink_global_rmse": sink_global_rmse,
            "best_agent_global_rmse": best_global_rmse,
            "sink_best_rmse_gap": sink_global_rmse - best_global_rmse,
            "sink_coverage_ratio": sink.coverage_ratio if sink is not None else 0.0,
            "vote_rmse": final.vote_rmse,
            "average_rmse": final.average_rmse,
            "is_sink_topology": any(
                token in result.config.topology_name
                for token in ["star", "tree", "sink", "dag_mesh", "random"]
            ),
        },
        "merge_quality": {
            "parse_error_count": sum(
                1 for trace in result.agent_step_traces if trace.parse_error
            ),
            "retry_attempts": result.total_retry_attempts,
            "trace_rows": len(result.agent_step_traces),
            "avg_fan_in": fmean(fan_ins) if fan_ins else 0.0,
            "prompt_tokens": result.total_prompt_tokens,
            "completion_tokens": result.total_completion_tokens,
        },
    }
    risk_tags = _dynamics_risk_tags(dynamics)
    if (
        final.full_coverage_agents > 0
        and not result.final_result.exact_match
        and result.final_result.rmse > 1.0
    ):
        risk_tags.append("full_coverage_wrong_answer")
    return EvidenceRecord(
        evidence_id=f"trace:{result.run_id}",
        source_dir=result.trace_path or "",
        source_type="trace",
        topology_name=result.config.topology_name,
        n_agents=result.config.n_agents,
        seed=result.config.seed,
        dynamics=dynamics,
        risk_tags=sorted(set(risk_tags)),
        created_at=created_at,
    )


def _build_minister_summary(
    *,
    protocol_result: ProtocolExperimentResult,
    patches: list[SkillPatch],
    output_dir: Path,
) -> MinisterSummary:
    counter = Counter(patch.action for patch in patches)
    lessons = [patch.lesson for patch in patches if patch.lesson][:12]
    risk_notes = [
        patch.lesson
        for patch in patches
        if patch.source in {"counterexample_analyst", "trace_analyst"}
        and patch.lesson
    ][:12]
    return MinisterSummary(
        run_id=protocol_result.run_id,
        final_rmse=protocol_result.final_result.rmse,
        exact_match=protocol_result.final_result.exact_match,
        total_messages=protocol_result.total_messages,
        total_model_calls=protocol_result.total_model_calls,
        token_cost=protocol_result.total_prompt_tokens
        + protocol_result.total_completion_tokens,
        patch_counts=dict(counter),
        lessons=lessons,
        risk_notes=risk_notes,
        artifacts={
            "output_dir": str(output_dir),
            "patch_dir": str(output_dir / "patches"),
            "evidence_records": str(output_dir / "evidence_records.jsonl"),
        },
    )


def _run_risk_tags(summary: dict[str, Any]) -> list[str]:
    tags = []
    if not bool(summary.get("FinalExactMatch")):
        tags.append("non_exact_final")
    if int(summary.get("TotalDeterministicFallbacks") or 0) > 0:
        tags.append("deterministic_fallback")
    return tags


def _dynamics_risk_tags(dynamics: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    coverage = dynamics.get("coverage_growth", {})
    aggregation = dynamics.get("aggregation_reliability", {})
    merge = dynamics.get("merge_quality", {})
    if isinstance(coverage, dict) and float(coverage.get("mean_coverage_gain", 0.0)) <= 0:
        tags.append("coverage_stall")
    if (
        isinstance(aggregation, dict)
        and float(aggregation.get("sink_best_rmse_gap", 0.0)) > 0
    ):
        tags.append("sink_quality_gap")
    if isinstance(merge, dict) and int(merge.get("retry_attempts", 0)) > 0:
        tags.append("merge_retry_burden")
    if isinstance(merge, dict) and int(merge.get("parse_error_count", 0)) > 0:
        tags.append("merge_parse_error")
    return tags


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
