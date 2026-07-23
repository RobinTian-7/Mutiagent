"""LLM post-run insight generation and insight-to-skill patch mapping."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean
from typing import Any

from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.evolution import (
    classify_topology,
    condition_specific_skill_id,
    default_operation_recommendations,
    infer_condition_scope,
    infer_topology_structure_features,
)
from exp_graph.mas.schemas import (
    EvidenceRecord,
    InsightReport,
    MASInsight,
    MASRuntimeConfig,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank


def build_evidence_pack(
    *,
    records: list[EvidenceRecord],
    skill_bank: SkillBank,
    experiment_id: str,
) -> dict[str, Any]:
    """Compress evidence into a prompt-sized MAS design summary."""
    active = [record for record in records if record.status == "observed"]
    by_topology: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in active:
        by_topology[record.topology_name].append(record)
    topology_summaries = {}
    for topology, rows in sorted(by_topology.items()):
        topology_summaries[topology] = {
            "evidence_refs": [row.evidence_id for row in rows],
            "n_agents": sorted({row.n_agents for row in rows if row.n_agents}),
            "seeds": sorted({row.seed for row in rows if row.seed is not None}),
            "metrics": _metric_summary(rows),
            "dynamics": _dynamics_summary(rows),
            "condition_scope": infer_condition_scope(_record_prompt_rows(rows)),
            "structure_features": infer_topology_structure_features(
                topology,
                _record_prompt_rows(rows),
            ),
            "risk_tags": sorted({tag for row in rows for tag in row.risk_tags}),
        }
    return {
        "experiment_id": experiment_id,
        "record_count": len(active),
        "topologies": topology_summaries,
        "current_skill_versions": {
            skill.skill_id: skill.version for skill in skill_bank
        },
    }


class LLMInsightMinister:
    """Generate evidence-grounded MAS design insights after execution."""

    source = "llm_insight_minister"

    def __init__(
        self,
        *,
        runtime: MASRuntimeConfig,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.runtime = runtime
        self.llm_client = llm_client
        self.last_raw_response: str | None = None

    def analyze(
        self,
        *,
        evidence_pack: dict[str, Any],
        skill_bank: SkillBank,
    ) -> InsightReport:
        if self.runtime.llm_provider == "fake":
            return verify_insight_report(
                _deterministic_insight_report(evidence_pack, skill_bank)
            )
        try:
            client = self.llm_client or create_llm_client(self.runtime.llm_provider)
            response = client.complete(
                build_insight_prompt(evidence_pack=evidence_pack),
                model_name=self.runtime.model_name,
                temperature=self.runtime.temperature,
            )
            self.last_raw_response = response.text
            report = InsightReport.model_validate(_loads_json_object(response.text))
            return verify_insight_report(report)
        except Exception as exc:  # pragma: no cover - manual/OpenAI path.
            return verify_insight_report(
                InsightReport(
                    report_id=f"insight_report_{_stamp()}",
                    experiment_id=str(evidence_pack.get("experiment_id", "unknown")),
                    executive_summary=(
                        "LLM insight generation failed; emitted one rejected record."
                    ),
                    rejected_insights=[
                        {
                            "reason": "llm_failure",
                            "error": str(exc),
                        }
                    ],
                )
            )


def build_insight_prompt(*, evidence_pack: dict[str, Any]) -> str:
    """Build a JSON-only prompt for post-run MAS insight extraction."""
    payload = {
        "role": (
            "You are a post-run MAS topology and skill-evolution analyst. Your "
            "responsibility is to convert experiment evidence into reusable "
            "planner skills that help the next topology planner design better "
            "explicit communication DAGs from scratch."
        ),
        "task": (
            "Analyze the evidence, diagnose which topology structures, edge "
            "patterns, and merge dynamics helped or failed, and derive reusable "
            "MAS design insights. Do not merely summarize metrics. Explain the "
            "mechanism, the affected planner skill, the topology design implication, "
            "and the falsification test. Return one valid json object only."
        ),
        "analysis_responsibilities": [
            "Separate observed evidence from hypotheses and label confidence accordingly.",
            "Identify whether failures come from missing coverage, excessive fan-in, weak sink choice, duplicate-count risk, poor provenance flow, or cost/accuracy mismatch.",
            "Translate each useful observation into an action the topology planner can use when generating future DAG edges.",
            "For every useful insight, emit operation_recommendations as concrete operations: preserve/mutate/avoid/validate, a target such as edge_schedule, sink_selection, fan_in_limit, reducer_scope, skill_trigger, and a directly executable instruction.",
            "Emit condition_buckets when the lesson only appears for specific n_agents or array_size ranges; avoid overgeneralizing a skill outside its bucket.",
            "Recommend avoid-skills for repeatedly bad structures and positive skills only for structures with evidence-backed benefit.",
            "Prefer concrete topology rules over generic advice such as use better communication.",
        ],
        "evidence_pack": evidence_pack,
        "output_schema": {
            "report_id": "string",
            "experiment_id": evidence_pack.get("experiment_id"),
            "executive_summary": "string",
            "key_insights": [
                {
                    "insight_id": "string",
                    "title": "string",
                    "insight_type": (
                        "design_principle | tradeoff | scaling_pattern | "
                        "dynamics_pattern | risk_pattern | operator_rule | "
                        "hypothesis | followup_experiment"
                    ),
                    "claim_status": "observed | inferred | hypothesis",
                    "summary": "string",
                    "evidence_refs": ["evidence id"],
                    "metric_snapshot": {},
                    "affected_skills": ["skill id"],
                    "recommended_actions": ["string"],
                    "operation_recommendations": [
                        {
                            "action_type": "preserve | mutate | avoid | validate",
                            "target": (
                                "edge_schedule | sink_selection | fan_in_limit | "
                                "reducer_scope | provenance_flow | skill_trigger"
                            ),
                            "instruction": "specific topology-planner operation",
                            "conditions": {
                                "agent_bucket": "agents_8",
                                "array_size_bucket": "arrays_1024",
                            },
                            "expected_effect": {
                                "rmse": "decrease",
                                "messages": "bounded",
                            },
                        }
                    ],
                    "condition_buckets": [
                        {
                            "agent_bucket": "agents_8",
                            "array_size_bucket": "arrays_1024",
                            "supporting_refs": ["evidence id"],
                        }
                    ],
                    "confidence": 0.0,
                    "falsification_test": "string",
                }
            ],
            "followup_experiments": [],
        },
        "verification_rules": [
            "Return exactly one json object, not markdown and not prose.",
            "Every insight must cite evidence_refs from the evidence pack.",
            "Single-seed claims must be marked hypothesis.",
            "Each recommended action must name the planner behavior it should change.",
            "Each operation_recommendation must be executable by changing generated DAG edges, sink choice, fan-in, reducer scope, or skill trigger conditions.",
            "Do not claim a topology is good only because it is cheap; include accuracy and coverage evidence.",
            "Unsupported claims should be omitted.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def verify_insight_report(report: InsightReport) -> InsightReport:
    """Rule-check insights before they become patch candidates."""
    accepted: list[MASInsight] = []
    rejected = list(report.rejected_insights)
    for insight in report.key_insights:
        if not insight.evidence_refs:
            rejected.append(
                {
                    "insight_id": insight.insight_id,
                    "reason": "missing_evidence_refs",
                    "summary": insight.summary,
                }
            )
            continue
        updated = insight
        if len(insight.evidence_refs) <= 1 and insight.claim_status != "hypothesis":
            updated = insight.model_copy(update={"claim_status": "hypothesis"})
        accepted.append(updated)
    recommendations = insight_report_to_patches(
        report.model_copy(update={"key_insights": accepted})
    )
    return report.model_copy(
        update={
            "key_insights": accepted,
            "rejected_insights": rejected,
            "skill_update_recommendations": recommendations,
        }
    )


def insight_report_to_patches(report: InsightReport) -> list[SkillPatch]:
    """Convert verified insights into non-writing patch candidates."""
    patches: list[SkillPatch] = []
    for insight in report.key_insights:
        if insight.claim_status == "rejected":
            continue
        target = insight.affected_skills[0] if insight.affected_skills else None
        if target is None:
            continue
        update = _insight_update(insight)
        if not update:
            continue
        patches.append(
            SkillPatch(
                patch_id=f"insight_{insight.insight_id}",
                action="merge",
                target_skill_id=target,
                evidence_refs=insight.evidence_refs,
                update=update,
                lesson=insight.summary,
                confidence=insight.confidence,
                source="llm_insight_minister",
            )
        )
    return patches


def _deterministic_insight_report(
    evidence_pack: dict[str, Any],
    skill_bank: SkillBank,
) -> InsightReport:
    insights: list[MASInsight] = []
    topologies = evidence_pack.get("topologies", {})
    if isinstance(topologies, dict):
        for topology, summary in sorted(topologies.items()):
            if not isinstance(summary, dict):
                continue
            refs = [str(ref) for ref in summary.get("evidence_refs", [])]
            objective, _operators, skill_id, lesson = classify_topology(topology)
            risk_tags = summary.get("risk_tags", [])
            condition_scope = summary.get("condition_scope", {})
            structure_features = summary.get("structure_features", {})
            operation_recommendations = default_operation_recommendations(
                topology,
                structure_features if isinstance(structure_features, dict) else {},
                condition_scope if isinstance(condition_scope, dict) else {},
            )
            condition_buckets = [
                condition_scope
            ] if isinstance(condition_scope, dict) and condition_scope else []
            candidate_skill_id = condition_specific_skill_id(
                skill_id,
                topology,
                condition_scope if isinstance(condition_scope, dict) else {},
            )
            affected = (
                [candidate_skill_id]
                if skill_bank.get(candidate_skill_id)
                else [skill_id] if skill_bank.get(skill_id) else []
            )
            if refs:
                insights.append(
                    MASInsight(
                        insight_id=f"{_slug(topology)}_tradeoff",
                        title=f"{topology} tradeoff should stay evidence-backed",
                        insight_type="tradeoff",
                        claim_status="hypothesis" if len(refs) <= 1 else "observed",
                        summary=(
                            f"{lesson} Current evidence should update the "
                            f"{objective} planner tradeoff and confidence."
                        ),
                        evidence_refs=refs,
                        metric_snapshot=summary.get("metrics", {}),
                        affected_skills=affected,
                        recommended_actions=["merge evidence into planner skill"],
                        operation_recommendations=operation_recommendations,
                        condition_buckets=condition_buckets,
                        confidence=0.65,
                        falsification_test=(
                            "Run additional seeds and compare regret against "
                            "fixed topology baselines."
                        ),
                    )
                )
            if risk_tags and refs:
                insights.append(
                    MASInsight(
                        insight_id=f"{_slug(topology)}_risk",
                        title=f"{topology} has reusable risk boundary",
                        insight_type="risk_pattern",
                        claim_status="hypothesis" if len(refs) <= 1 else "inferred",
                        summary=(
                            f"Trace/result evidence for {topology} shows risk tags "
                            f"{', '.join(str(tag) for tag in risk_tags)}; planner "
                            "skills should preserve fallback conditions."
                        ),
                        evidence_refs=refs,
                        metric_snapshot={"risk_tags": risk_tags},
                        affected_skills=affected,
                        recommended_actions=["merge risk notes and fallback hints"],
                        operation_recommendations=[
                            {
                                "action_type": "avoid",
                                "target": "skill_trigger",
                                "instruction": (
                                    "Keep this risk as a condition-bucketed fallback "
                                    "instead of promoting it to a global topology rule."
                                ),
                                "conditions": condition_scope
                                if isinstance(condition_scope, dict)
                                else {},
                            }
                        ],
                        condition_buckets=condition_buckets,
                        confidence=0.55,
                        falsification_test=(
                            "Check whether risk tags persist across larger n_agents."
                        ),
                    )
                )
    return InsightReport(
        report_id=f"insight_report_{_stamp()}",
        experiment_id=str(evidence_pack.get("experiment_id", "unknown")),
        executive_summary=(
            "Generated evidence-grounded MAS design insights for planner-skill "
            "iteration."
        ),
        key_insights=insights,
    )


def _insight_update(insight: MASInsight) -> dict[str, object]:
    update: dict[str, object]
    if insight.insight_type in {"design_principle", "tradeoff"}:
        update = {
            "organization_policy": {
                "rationale_rules": [insight.summary],
            }
        }
    elif insight.insight_type == "dynamics_pattern":
        update = {
            "expected_dynamics": {
                insight.insight_id: {
                    "summary": insight.summary,
                    "metric_snapshot": insight.metric_snapshot,
                }
            }
        }
    elif insight.insight_type == "risk_pattern":
        update = {
            "risk_notes": [
                {
                    "source": "llm_insight_minister",
                    "insight_id": insight.insight_id,
                    "summary": insight.summary,
                    "metric_snapshot": insight.metric_snapshot,
                }
            ]
        }
    elif insight.insight_type == "operator_rule":
        update = {
            "organization_policy": {
                "operator_constraints": [
                    {
                        "source": "llm_insight_minister",
                        "summary": insight.summary,
                    }
                ]
            }
        }
    elif insight.insight_type == "hypothesis":
        update = {
            "hypotheses": [
                {
                    "source": "llm_insight_minister",
                    "summary": insight.summary,
                    "evidence_refs": insight.evidence_refs,
                }
            ]
        }
    elif insight.insight_type == "followup_experiment":
        update = {
            "validation_plan": [
                {
                    "source": "llm_insight_minister",
                    "summary": insight.summary,
                    "falsification_test": insight.falsification_test,
                }
            ]
        }
    elif insight.insight_type == "scaling_pattern":
        update = {
            "expected_tradeoff": {
                "scaling_pattern": insight.summary,
            }
        }
    else:
        update = {}
    return _attach_operation_update(update, insight)


def _attach_operation_update(
    update: dict[str, object],
    insight: MASInsight,
) -> dict[str, object]:
    if not insight.operation_recommendations and not insight.condition_buckets:
        return update
    merged = dict(update)
    policy = dict(merged.get("organization_policy", {}))
    dynamics = dict(merged.get("expected_dynamics", {}))
    if insight.operation_recommendations:
        policy["operation_recommendations"] = insight.operation_recommendations
    if insight.condition_buckets:
        dynamics["condition_buckets"] = insight.condition_buckets
    if policy:
        merged["organization_policy"] = policy
    if dynamics:
        merged["expected_dynamics"] = dynamics
    return merged


def _metric_summary(rows: list[EvidenceRecord]) -> dict[str, float]:
    metrics = [row.metrics for row in rows if row.metrics]
    return {
        "rmse": _mean_metric(metrics, "mean_rmse", "final_rmse"),
        "messages": _mean_metric(metrics, "mean_messages", "total_messages"),
        "token_cost": _mean_metric(metrics, "mean_token_cost", "token_cost"),
        "exact_match_rate": _mean_metric(metrics, "exact_match_rate"),
    }


def _dynamics_summary(rows: list[EvidenceRecord]) -> dict[str, object]:
    trace_rows = [row for row in rows if row.source_type == "trace"]
    return {
        "trace_count": len(trace_rows),
        "coverage_gain": _mean_nested(
            trace_rows,
            "coverage_growth",
            "mean_coverage_gain",
        ),
        "sink_best_rmse_gap": _mean_nested(
            trace_rows,
            "aggregation_reliability",
            "sink_best_rmse_gap",
        ),
        "retry_attempts": _mean_nested(trace_rows, "merge_quality", "retry_attempts"),
    }


def _record_prompt_rows(rows: list[EvidenceRecord]) -> list[dict[str, object]]:
    return [
        {
            "evidence_id": row.evidence_id,
            "source_type": row.source_type,
            "topology_name": row.topology_name,
            "n_agents": row.n_agents,
            "seed": row.seed,
            **row.metrics,
            "risk_tags": row.risk_tags,
            "dynamics": row.dynamics,
        }
        for row in rows
    ]


def _mean_metric(metrics: list[dict[str, object]], *keys: str) -> float:
    values = []
    for row in metrics:
        for key in keys:
            value = row.get(key)
            if value is not None:
                values.append(float(value))
                break
    return fmean(values) if values else 0.0


def _mean_nested(rows: list[EvidenceRecord], section: str, key: str) -> float:
    values = []
    for row in rows:
        section_data = row.dynamics.get(section, {})
        if isinstance(section_data, dict) and section_data.get(key) is not None:
            values.append(float(section_data[key]))
    return fmean(values) if values else 0.0


def _loads_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
