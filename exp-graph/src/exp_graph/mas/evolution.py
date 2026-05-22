"""Minister analysts and batch consolidation for MAS skill evolution."""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from exp_graph.mas.ingest import (
    aggregate_rows_to_evidence,
    group_evidence_by_topology,
    load_experiment_directory,
)
from exp_graph.mas.schemas import EvidenceRecord, EvolutionBatch, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import SkillBank


class ResultAnalystMinister:
    """Extract accuracy/topology patterns from aggregate metrics."""

    source = "result_analyst"

    def analyze(self, aggregate_rows: list[dict[str, Any]]) -> list[SkillPatch]:
        evidence = aggregate_rows_to_evidence(aggregate_rows)
        grouped = group_evidence_by_topology(evidence)
        patches = [
            build_skill_patch_for_topology(topology, rows)
            for topology, rows in sorted(grouped.items())
        ]
        patches.extend(build_negative_patches(evidence))
        return patches


class CostAnalystMinister:
    """Extract budget-first observations from aggregate metrics."""

    source = "cost_analyst"

    def analyze(self, aggregate_rows: list[dict[str, Any]]) -> list[SkillPatch]:
        evidence = aggregate_rows_to_evidence(aggregate_rows)
        if not _has_comparative_topology_evidence(evidence):
            return []
        cheapest = min(
            evidence,
            key=lambda item: (item["mean_token_cost"], item["mean_messages"]),
        )
        _objective, operators, skill_id, _lesson = classify_topology(
            str(cheapest["topology_name"])
        )
        candidate = make_skill_card(
            skill_id=skill_id,
            topology_name=str(cheapest["topology_name"]),
            objective=_objective,
            operators=operators,
            evidence=[
                item
                for item in evidence
                if item["topology_name"] == cheapest["topology_name"]
            ],
            expected_tradeoff={
                "strength": "lowest observed communication cost",
                "weakness": "may sacrifice accuracy compared with peer propagation",
            },
        )
        return [
            SkillPatch(
                patch_id=f"cost_{skill_id}",
                action="merge",
                target_skill_id=candidate.skill_id,
                candidate_skill=candidate,
                evidence=candidate.evidence,
                lesson=(
                    f"{cheapest['topology_name']} is the lowest observed cost "
                    "CF organization among compared topologies."
                ),
                confidence=0.9,
                source=self.source,
            )
        ]


class CounterexampleMinister:
    """Record unstable or dominated topologies as counterexamples."""

    source = "counterexample_analyst"

    def analyze(self, aggregate_rows: list[dict[str, Any]]) -> list[SkillPatch]:
        evidence = aggregate_rows_to_evidence(aggregate_rows)
        return build_negative_patches(evidence)


class TraceAnalystMinister:
    """Extract trace-to-skill dynamics without requiring perfect CF outcomes."""

    source = "trace_analyst"

    def analyze(self, trace_rows: list[dict[str, Any]]) -> list[SkillPatch]:
        return [
            SkillPatch(
                patch_id="trace_noop",
                action="discard",
                lesson="Trace analyst requires detailed trace annotations.",
                confidence=0.0,
                source=self.source,
            )
        ] if trace_rows else []

    def analyze_evidence(self, records: list[EvidenceRecord]) -> list[SkillPatch]:
        patches: list[SkillPatch] = []
        trace_records = [record for record in records if record.source_type == "trace"]
        grouped: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for record in trace_records:
            grouped[record.topology_name].append(record)
        for topology, rows in sorted(grouped.items()):
            objective, operators, skill_id, lesson = classify_topology(topology)
            risk_tags = sorted({tag for row in rows for tag in row.risk_tags})
            update = {
                "expected_dynamics": {
                    "source": self.source,
                    "record_count": len(rows),
                    "risk_tags": risk_tags,
                },
                "risk_notes": [
                    {
                        "source": self.source,
                        "risk_tag": tag,
                        "summary": f"Observed {tag} in trace dynamics for {topology}.",
                    }
                    for tag in risk_tags
                ],
            }
            fallback = {}
            if "sink_quality_gap" in risk_tags:
                fallback["if_sink_quality_gap_high"] = "cf_middle_ground_mesh_star"
            if "merge_retry_burden" in risk_tags or "merge_parse_error" in risk_tags:
                fallback["if_merge_errors_high"] = "use_llm_belief_merge_or_vote"
            if fallback:
                update["fallback"] = fallback
            patches.append(
                SkillPatch(
                    patch_id=f"trace_{skill_id}",
                    action="merge",
                    target_skill_id=skill_id,
                    candidate_skill=make_skill_card(
                        skill_id=skill_id,
                        topology_name=topology,
                        objective=objective,
                        operators=operators,
                        evidence=[],
                        evidence_refs=[record.evidence_id for record in rows],
                        expected_tradeoff={
                            "lesson": lesson,
                            "trace_record_count": len(rows),
                        },
                    ),
                    evidence_refs=[record.evidence_id for record in rows],
                    update=update,
                    lesson=(
                        f"Trace dynamics for {topology} expose reusable MAS "
                        "coverage, aggregation, and merge-quality signals."
                    ),
                    confidence=0.7,
                    source=self.source,
                )
            )
        return patches


def build_evolution_batch_from_experiment_dir(
    directory: Path | str,
    *,
    batch_id: str = "cf_bootstrap",
) -> EvolutionBatch:
    data = load_experiment_directory(directory)
    result_patches = ResultAnalystMinister().analyze(data["aggregate"])
    cost_patches = CostAnalystMinister().analyze(data["aggregate"])
    return EvolutionBatch(
        batch_id=batch_id,
        patches=[*result_patches, *cost_patches],
        summary="Bootstrap emperor skills from CF protocol aggregate metrics.",
    )


def build_evolution_batch_from_evidence(
    records: list[EvidenceRecord],
    *,
    batch_id: str = "cf_evidence_batch",
) -> EvolutionBatch:
    """Build patch candidates from append-only evidence records."""
    patches = [
        *build_result_patches_from_evidence(records),
        *build_cost_patches_from_evidence(records),
        *build_counterexample_patches_from_evidence(records),
        *TraceAnalystMinister().analyze_evidence(records),
    ]
    return EvolutionBatch(
        batch_id=batch_id,
        patches=patches,
        summary="Build skill patch candidates from append-only MAS evidence.",
    )


def consolidate_batch(batch: EvolutionBatch, bank: SkillBank | None = None) -> SkillBank:
    """Apply add/merge/discard patches as one batch."""
    skill_bank = bank or SkillBank()
    for patch in batch.patches:
        if patch.action == "discard":
            continue
        if patch.target_skill_id and skill_bank.get(patch.target_skill_id):
            skill_bank.apply_patch(patch.model_copy(update={"action": "merge"}))
        elif patch.candidate_skill is not None:
            skill_bank.apply_patch(patch.model_copy(update={"action": "add"}))
    return skill_bank


def build_result_patches_from_evidence(
    records: list[EvidenceRecord],
) -> list[SkillPatch]:
    aggregate_records = [
        record
        for record in records
        if record.source_type in {"aggregate", "run"} and record.status == "observed"
    ]
    grouped: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in aggregate_records:
        grouped[record.topology_name].append(record)
    patches: list[SkillPatch] = []
    for topology, rows in sorted(grouped.items()):
        objective, operators, skill_id, lesson = classify_topology(topology)
        refs = [record.evidence_id for record in rows]
        expected_tradeoff = {
            "mean_rmse": _mean_record_metric(rows, "mean_rmse", "final_rmse"),
            "mean_token_cost": _mean_record_metric(
                rows,
                "mean_token_cost",
                "token_cost",
            ),
            "mean_messages": _mean_record_metric(
                rows,
                "mean_messages",
                "total_messages",
            ),
            "exact_match_rate": _mean_record_metric(
                rows,
                "exact_match_rate",
                "final_exact_match",
            ),
            "lesson": lesson,
        }
        candidate = make_skill_card(
            skill_id=skill_id,
            topology_name=topology,
            objective=objective,
            operators=operators,
            evidence=[],
            evidence_refs=refs,
            expected_tradeoff=expected_tradeoff,
        )
        patches.append(
            SkillPatch(
                patch_id=f"result_{skill_id}",
                action="merge",
                target_skill_id=skill_id,
                candidate_skill=candidate,
                evidence_refs=refs,
                update={
                    "organization_policy": {
                        "rationale_rules": [lesson],
                    },
                },
                lesson=lesson,
                confidence=0.75,
                source="result_analyst",
            )
        )
    return patches


def build_cost_patches_from_evidence(records: list[EvidenceRecord]) -> list[SkillPatch]:
    aggregate_records = [
        record
        for record in records
        if record.source_type in {"aggregate", "run"} and record.status == "observed"
    ]
    if not _has_comparative_record_evidence(aggregate_records):
        return []
    cheapest = min(
        aggregate_records,
        key=lambda record: (
            _record_metric(record, "mean_token_cost", "token_cost"),
            _record_metric(record, "mean_messages", "total_messages"),
        ),
    )
    objective, operators, skill_id, _lesson = classify_topology(cheapest.topology_name)
    refs = [record.evidence_id for record in aggregate_records
            if record.topology_name == cheapest.topology_name]
    candidate = make_skill_card(
        skill_id=skill_id,
        topology_name=cheapest.topology_name,
        objective=objective,
        operators=operators,
        evidence=[],
        evidence_refs=refs,
        expected_tradeoff={
            "strength": "lowest observed communication cost",
            "weakness": "may sacrifice accuracy compared with peer propagation",
        },
    )
    return [
        SkillPatch(
            patch_id=f"cost_{skill_id}",
            action="merge",
            target_skill_id=candidate.skill_id,
            candidate_skill=candidate,
            evidence_refs=refs,
            lesson=(
                f"{cheapest.topology_name} is the lowest observed cost CF "
                "organization among compared topologies."
            ),
            confidence=0.9,
            source="cost_analyst",
        )
    ]


def build_counterexample_patches_from_evidence(
    records: list[EvidenceRecord],
) -> list[SkillPatch]:
    aggregate_records = [
        record
        for record in records
        if record.source_type in {"aggregate", "run"} and record.status == "observed"
    ]
    grouped_by_agent: dict[int, list[EvidenceRecord]] = defaultdict(list)
    for record in aggregate_records:
        if record.n_agents is not None:
            grouped_by_agent[record.n_agents].append(record)
    dominated: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for rows in grouped_by_agent.values():
        best_rmse = min(_record_metric(row, "mean_rmse", "final_rmse") for row in rows)
        for row in rows:
            if _record_metric(row, "mean_rmse", "final_rmse") > best_rmse * 1.75:
                dominated[row.topology_name].append(row)
    patches = []
    for topology, rows in sorted(dominated.items()):
        refs = [record.evidence_id for record in rows]
        candidate = make_skill_card(
            skill_id=f"cf_avoid_{topology}",
            topology_name=topology,
            objective="balanced",
            operators=[],
            evidence=[],
            evidence_refs=refs,
            expected_tradeoff={
                "strength": "negative routing evidence",
                "weakness": "dominated by stronger CF topology choices",
            },
            counterexamples=[
                {
                    "evidence_id": record.evidence_id,
                    "topology_name": topology,
                    "mean_rmse": _record_metric(record, "mean_rmse", "final_rmse"),
                }
                for record in rows
            ],
        )
        patches.append(
            SkillPatch(
                patch_id=f"counterexample_{topology}",
                action="merge",
                target_skill_id=candidate.skill_id,
                candidate_skill=candidate,
                evidence_refs=refs,
                update={
                    "risk_notes": [
                        {
                            "source": "counterexample_analyst",
                            "summary": f"{topology} is dominated in observed CF evidence.",
                        }
                    ]
                },
                lesson=f"Avoid {topology} as a default CF planner choice.",
                confidence=0.7,
                source="counterexample_analyst",
            )
        )
    return patches


def build_skill_patch_for_topology(
    topology: str,
    rows: list[dict[str, Any]],
) -> SkillPatch:
    avg_rmse = statistics.fmean(float(row["mean_rmse"]) for row in rows)
    avg_tokens = statistics.fmean(float(row["mean_token_cost"]) for row in rows)
    avg_messages = statistics.fmean(float(row["mean_messages"]) for row in rows)
    objective, operators, skill_id, lesson = classify_topology(topology)
    candidate = make_skill_card(
        skill_id=skill_id,
        topology_name=topology,
        objective=objective,
        operators=operators,
        evidence=rows,
        expected_tradeoff={
            "mean_rmse": avg_rmse,
            "mean_token_cost": avg_tokens,
            "mean_messages": avg_messages,
            "lesson": lesson,
        },
    )
    return SkillPatch(
        patch_id=f"result_{skill_id}",
        action="merge",
        target_skill_id=skill_id,
        candidate_skill=candidate,
        evidence=rows,
        lesson=lesson,
        confidence=0.75,
        source="result_analyst",
    )


def build_negative_patches(evidence: list[dict[str, Any]]) -> list[SkillPatch]:
    grouped = group_evidence_by_topology(evidence)
    if not grouped:
        return []
    by_agent: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        by_agent[int(item["n_agents"])].append(item)
    dominated: set[str] = set()
    for rows in by_agent.values():
        best_rmse = min(float(row["mean_rmse"]) for row in rows)
        for row in rows:
            if float(row["mean_rmse"]) > best_rmse * 1.75:
                dominated.add(str(row["topology_name"]))
    patches: list[SkillPatch] = []
    for topology in sorted(dominated):
        rows = grouped[topology]
        candidate = make_skill_card(
            skill_id=f"cf_avoid_{topology}",
            topology_name=topology,
            objective="balanced",
            operators=[],
            evidence=rows,
            expected_tradeoff={
                "strength": "negative routing evidence",
                "weakness": "dominated by stronger CF topology choices",
            },
            counterexamples=rows,
        )
        patches.append(
            SkillPatch(
                patch_id=f"counterexample_{topology}",
                action="merge",
                target_skill_id=candidate.skill_id,
                candidate_skill=candidate,
                evidence=rows,
                lesson=f"Avoid {topology} as a default CF planner choice.",
                confidence=0.7,
                source="counterexample_analyst",
            )
        )
    return patches


def classify_topology(topology: str) -> tuple[str, list[str], str, str]:
    if topology == "one_peer_exponential_dag_star":
        return (
            "accuracy_first",
            ["local_solve", "peer_propagate", "star_sink"],
            "cf_accuracy_peer_star",
            "Peer propagation followed by star sink is the accuracy-first CF policy.",
        )
    if topology == "tree":
        return (
            "budget_first",
            ["local_solve", "tree_reduce"],
            "cf_budget_tree",
            "Tree reduction is the budget-first CF policy.",
        )
    if topology == "mesh_star":
        return (
            "balanced",
            ["local_solve", "mesh_broadcast", "star_sink"],
            "cf_middle_ground_mesh_star",
            "Mesh broadcast plus star sink is a middle-ground coverage policy.",
        )
    return (
        "balanced",
        [],
        f"cf_topology_{topology}",
        f"Observed CF evidence for topology {topology}.",
    )


def make_skill_card(
    *,
    skill_id: str,
    topology_name: str,
    objective: str,
    operators: list[str],
    evidence: list[dict[str, Any]],
    expected_tradeoff: dict[str, object],
    evidence_refs: list[str] | None = None,
    counterexamples: list[dict[str, object]] | None = None,
) -> SkillCard:
    return SkillCard(
        skill_id=skill_id,
        version="0.1.0",
        task_family="count_frequency",
        trigger={
            "task_family": "count_frequency",
            "min_agents": min(int(row["n_agents"]) for row in evidence) if evidence else 1,
            "max_agents": max(int(row["n_agents"]) for row in evidence) if evidence else 999,
        },
        objective=objective,  # type: ignore[arg-type]
        organization_policy={
            "planner_mode": "topology_select",
            "topology_name": topology_name,
            "operators": operators,
            "protocol_spec": None,
        },
        expected_tradeoff=expected_tradeoff,
        evidence=evidence,
        evidence_refs=evidence_refs or [],
        fallback={
            "budget_first": "cf_budget_tree"
            if skill_id != "cf_budget_tree"
            else None
        },
        counterexamples=counterexamples or [],
        tags=["mas", "emperor-skill", "count-frequency", objective],
    )


def _mean_record_metric(records: list[EvidenceRecord], *keys: str) -> float:
    values = [
        _record_metric(record, *keys)
        for record in records
        if any(key in record.metrics and record.metrics[key] is not None for key in keys)
    ]
    return statistics.fmean(values) if values else 0.0


def _record_metric(record: EvidenceRecord, *keys: str) -> float:
    for key in keys:
        value = record.metrics.get(key)
        if value is not None:
            return float(value)
    return 0.0


def _has_comparative_topology_evidence(evidence: list[dict[str, Any]]) -> bool:
    return len({str(item.get("topology_name", "")) for item in evidence}) >= 2


def _has_comparative_record_evidence(records: list[EvidenceRecord]) -> bool:
    return len({record.topology_name for record in records}) >= 2
