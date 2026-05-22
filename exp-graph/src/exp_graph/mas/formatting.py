"""Human-readable formatting for the transparent MAS pipeline."""

from __future__ import annotations

import json
from collections import Counter

from exp_graph.mas.schemas import (
    EvolutionResult,
    InsightReport,
    MASPlan,
    MinisterSummary,
    SkillPatch,
)


def format_mas_plan(plan: MASPlan) -> str:
    """Render an emperor plan for console and Markdown artifacts."""
    lines = [
        f"planner_mode: {plan.planner_mode}",
        f"skill_id: {plan.skill_id or 'none'}",
        f"topology_name: {plan.topology_name}",
        f"operators: {', '.join(plan.operators) if plan.operators else 'none'}",
        f"score: {plan.score:.4f}",
        f"fallback_skill_id: {plan.fallback_skill_id or 'none'}",
        f"rationale: {plan.rationale or 'none'}",
    ]
    if plan.protocol_spec is not None:
        lines.append(f"protocol_steps: {len(plan.protocol_spec.steps)}")
        lines.append(
            "protocol_messages: "
            + str(sum(len(step.transmissions) for step in plan.protocol_spec.steps))
        )
    if plan.alternatives:
        lines.append("alternatives:")
        for item in plan.alternatives:
            lines.append(
                "  - "
                + json.dumps(item, ensure_ascii=True, sort_keys=True)
            )
    return "\n".join(lines)


def format_patch_counts(patches: list[SkillPatch]) -> str:
    counts = Counter(patch.action for patch in patches)
    return "\n".join(
        f"{action}: {counts.get(action, 0)}"
        for action in ["add", "merge", "discard", "deprecate"]
    )


def format_minister_summary(summary: MinisterSummary) -> str:
    """Render the post-run minister summary."""
    lines = [
        f"run_id: {summary.run_id}",
        f"final_rmse: {summary.final_rmse}",
        f"exact_match: {summary.exact_match}",
        f"total_messages: {summary.total_messages}",
        f"total_model_calls: {summary.total_model_calls}",
        f"token_cost: {summary.token_cost}",
        "patch_counts:",
    ]
    for key, value in sorted(summary.patch_counts.items()):
        lines.append(f"  {key}: {value}")
    if summary.lessons:
        lines.append("lessons:")
        lines.extend(f"  - {lesson}" for lesson in summary.lessons)
    if summary.risk_notes:
        lines.append("risk_notes:")
        lines.extend(f"  - {note}" for note in summary.risk_notes)
    if summary.artifacts:
        lines.append("artifacts:")
        for key, value in sorted(summary.artifacts.items()):
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def format_insight_report(report: InsightReport) -> str:
    """Render an evidence-grounded insight report."""
    lines = [
        f"report_id: {report.report_id}",
        f"experiment_id: {report.experiment_id}",
        "",
        report.executive_summary or "No executive summary.",
    ]
    if report.key_insights:
        lines.extend(["", "key_insights:"])
        for insight in report.key_insights:
            lines.extend(
                [
                    f"  - {insight.title}",
                    f"    type: {insight.insight_type}",
                    f"    status: {insight.claim_status}",
                    f"    confidence: {insight.confidence:.2f}",
                    f"    evidence_refs: {', '.join(insight.evidence_refs)}",
                    f"    summary: {insight.summary}",
                ]
            )
            if insight.operation_recommendations:
                lines.append("    operation_recommendations:")
                lines.extend(
                    "      - "
                    + json.dumps(item, ensure_ascii=True, sort_keys=True)
                    for item in insight.operation_recommendations
                )
    if report.rejected_insights:
        lines.extend(["", "rejected_insights:"])
        lines.extend(
            f"  - {json.dumps(item, ensure_ascii=True, sort_keys=True)}"
            for item in report.rejected_insights
        )
    return "\n".join(lines)


def format_evolution_result(result: EvolutionResult) -> str:
    """Render persisted skill-bank update results."""
    lines = [f"batch_id: {result.batch_id}", "counts:"]
    for key, value in sorted(result.counts.items()):
        lines.append(f"  {key}: {value}")
    if result.revisions:
        lines.append("revisions:")
        for revision in result.revisions:
            lines.append(
                f"  - {revision.skill_id}: {revision.from_version} -> "
                f"{revision.to_version} ({', '.join(revision.changed_fields)})"
            )
    if result.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {warning}" for warning in result.warnings)
    return "\n".join(lines)
