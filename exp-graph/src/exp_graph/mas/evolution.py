"""Minister analysts and batch consolidation for MAS skill evolution."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from exp_graph.mas.ingest import (
    aggregate_rows_to_evidence,
    load_experiment_directory,
)
from exp_graph.mas.schemas import EvidenceRecord, EvolutionBatch, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import SkillBank


class ResultAnalystMinister:
    """Extract accuracy/topology patterns from aggregate metrics."""

    source = "result_analyst"

    def analyze(self, aggregate_rows: list[dict[str, Any]]) -> list[SkillPatch]:
        evidence = aggregate_rows_to_evidence(aggregate_rows)
        grouped = _group_dict_evidence_for_skills(evidence)
        patches = [
            build_skill_patch_for_topology(
                str(rows[0].get("topology_name", rows[0].get("Topology", group_key))),
                rows,
            )
            for group_key, rows in sorted(grouped.items())
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
        grouped[_record_skill_group_key(record)].append(record)
    patches: list[SkillPatch] = []
    for _group_key, rows in sorted(grouped.items()):
        topology = rows[0].topology_name
        objective, operators, skill_id, lesson = classify_topology(topology)
        refs = [record.evidence_id for record in rows]
        analysis_evidence = _records_to_analysis_evidence(rows)
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
            analysis_evidence=analysis_evidence,
            evidence_refs=refs,
            expected_tradeoff=expected_tradeoff,
        )
        patches.append(
            SkillPatch(
                patch_id=f"result_{candidate.skill_id}",
                action="merge",
                target_skill_id=candidate.skill_id,
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
    cheapest_group_key = _record_skill_group_key(cheapest)
    cheapest_rows = [
        record
        for record in aggregate_records
        if _record_skill_group_key(record) == cheapest_group_key
    ]
    refs = [record.evidence_id for record in cheapest_rows]
    candidate = make_skill_card(
        skill_id=skill_id,
        topology_name=cheapest.topology_name,
        objective=objective,
        operators=operators,
        evidence=[],
        analysis_evidence=_records_to_analysis_evidence(cheapest_rows),
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
    grouped_rows: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for rows in dominated.values():
        for row in rows:
            grouped_rows[_record_skill_group_key(row)].append(row)
    for _group_key, rows in sorted(grouped_rows.items()):
        topology = rows[0].topology_name
        refs = [record.evidence_id for record in rows]
        candidate = make_skill_card(
            skill_id=f"cf_avoid_{topology}",
            topology_name=topology,
            objective="balanced",
            operators=[],
            evidence=[],
            analysis_evidence=_records_to_analysis_evidence(rows),
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
                patch_id=(
                    f"counterexample_{candidate.skill_id}"
                    if _topology_uses_condition_bucket(topology)
                    else f"counterexample_{topology}"
                ),
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
    expected_tradeoff: dict[str, object] = {
        "mean_rmse": avg_rmse,
        "mean_token_cost": avg_tokens,
        "mean_messages": avg_messages,
        "lesson": lesson,
    }
    # Generic (non-CF) evidence carries a converted primary loss + its name;
    # propagate them so scoring reads the loss directly from the skill card.
    # CF rows never carry these keys, so this branch is a no-op for CF skills.
    primary_losses = [
        float(row["mean_primary_loss"])
        for row in rows
        if row.get("mean_primary_loss") is not None
    ]
    if primary_losses:
        expected_tradeoff["mean_primary_loss"] = statistics.fmean(primary_losses)
        metric_names = {
            str(row["primary_metric_name"])
            for row in rows
            if row.get("primary_metric_name") is not None
        }
        if len(metric_names) == 1:
            expected_tradeoff["primary_metric_name"] = next(iter(metric_names))
    candidate = make_skill_card(
        skill_id=skill_id,
        topology_name=topology,
        objective=objective,
        operators=operators,
        evidence=rows,
        expected_tradeoff=expected_tradeoff,
    )
    return SkillPatch(
        patch_id=f"result_{candidate.skill_id}",
        action="merge",
        target_skill_id=candidate.skill_id,
        candidate_skill=candidate,
        evidence=rows,
        lesson=lesson,
        confidence=0.75,
        source="result_analyst",
    )


def build_negative_patches(evidence: list[dict[str, Any]]) -> list[SkillPatch]:
    grouped = _group_dict_evidence_for_skills(evidence)
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
    for group_key, rows in sorted(grouped.items()):
        topology = str(rows[0]["topology_name"])
        if topology not in dominated:
            continue
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
                patch_id=(
                    f"counterexample_{candidate.skill_id}"
                    if _topology_uses_condition_bucket(topology)
                    else f"counterexample_{topology}"
                ),
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
    analysis_evidence: list[dict[str, Any]] | None = None,
    evidence_refs: list[str] | None = None,
    counterexamples: list[dict[str, object]] | None = None,
) -> SkillCard:
    feature_evidence = analysis_evidence if analysis_evidence is not None else evidence
    condition_scope = infer_condition_scope(feature_evidence)
    structure_features = infer_topology_structure_features(
        topology_name,
        feature_evidence,
    )
    protocol_spec = _best_protocol_spec(feature_evidence)
    operation_recommendations = default_operation_recommendations(
        topology_name,
        structure_features,
        condition_scope,
    )
    final_skill_id = condition_specific_skill_id(
        skill_id,
        topology_name,
        condition_scope,
    )
    trigger = {
        "task_family": "count_frequency",
        "min_agents": condition_scope.get("min_agents", 1),
        "max_agents": condition_scope.get("max_agents", 999),
        "agent_bucket": condition_scope.get("agent_bucket", "agents_any"),
        "condition_key": condition_scope.get("condition_key", "agents_any__arrays_any"),
    }
    if condition_scope.get("min_array_size") is not None:
        trigger.update(
            {
                "min_array_size": condition_scope["min_array_size"],
                "max_array_size": condition_scope["max_array_size"],
                "array_size_bucket": condition_scope.get(
                    "array_size_bucket",
                    "arrays_any",
                ),
            }
        )
    if condition_scope.get("agent_counts"):
        trigger["agent_counts"] = condition_scope["agent_counts"]
    if condition_scope.get("array_sizes"):
        trigger["array_sizes"] = condition_scope["array_sizes"]
    return SkillCard(
        skill_id=final_skill_id,
        version="0.1.0",
        task_family="count_frequency",
        trigger=trigger,
        objective=objective,  # type: ignore[arg-type]
        organization_policy={
            "planner_mode": (
                "graph_generate"
                if topology_name.startswith("generated:")
                else "topology_select"
            ),
            "topology_name": topology_name,
            "operators": operators,
            "protocol_spec": protocol_spec,
            "structure_features": structure_features,
            "operation_recommendations": operation_recommendations,
        },
        expected_tradeoff=expected_tradeoff,
        expected_dynamics={
            "condition_scope": condition_scope,
            "structure_features": structure_features,
            "protocol_spec_hash": _protocol_spec_hash(protocol_spec),
        },
        evidence=evidence,
        evidence_refs=evidence_refs or [],
        fallback={
            "budget_first": "cf_budget_tree"
            if final_skill_id != "cf_budget_tree"
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


def _best_protocol_spec(evidence: list[dict[str, Any]]) -> dict[str, object] | None:
    candidates: list[tuple[float, dict[str, object]]] = []
    for row in evidence:
        spec = row.get("protocol_spec")
        if spec is None and isinstance(row.get("metrics"), dict):
            spec = row["metrics"].get("protocol_spec")  # type: ignore[index]
        if not isinstance(spec, dict) or not spec.get("steps"):
            continue
        rmse = _evidence_float(row, "mean_rmse", "final_rmse")
        candidates.append((rmse if rmse is not None else float("inf"), spec))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _protocol_spec_hash(protocol_spec: dict[str, object] | None) -> str | None:
    if protocol_spec is None:
        return None
    payload = json.dumps(protocol_spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


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


def infer_condition_scope(evidence: list[dict[str, Any]]) -> dict[str, object]:
    """Summarize the condition bucket where a skill has evidence."""
    agent_counts = sorted(
        {
            value
            for row in evidence
            if (value := _evidence_int(row, "n_agents", "Agents")) is not None
        }
    )
    array_sizes = sorted(
        {
            value
            for row in evidence
            if (value := _evidence_int(row, "array_size", "ArraySize")) is not None
        }
    )
    min_agents = min(agent_counts) if agent_counts else 1
    max_agents = max(agent_counts) if agent_counts else 999
    agent_bucket = (
        f"agents_{min_agents}"
        if agent_counts and min_agents == max_agents
        else f"agents_{min_agents}_{max_agents}" if agent_counts else "agents_any"
    )
    scope: dict[str, object] = {
        "min_agents": min_agents,
        "max_agents": max_agents,
        "agent_bucket": agent_bucket,
        "agent_counts": agent_counts,
    }
    if array_sizes:
        min_array = min(array_sizes)
        max_array = max(array_sizes)
        array_bucket = (
            f"arrays_{min_array}"
            if min_array == max_array
            else f"arrays_{min_array}_{max_array}"
        )
        scope.update(
            {
                "min_array_size": min_array,
                "max_array_size": max_array,
                "array_size_bucket": array_bucket,
                "array_sizes": array_sizes,
            }
        )
    else:
        array_bucket = "arrays_any"
    scope["condition_key"] = f"{agent_bucket}__{array_bucket}"
    return scope


def infer_topology_structure_features(
    topology_name: str,
    evidence: list[dict[str, Any]],
) -> dict[str, object]:
    """Record explicit topology structure signals, not just its name."""
    name = topology_name.lower()
    motifs = []
    for token, motif in [
        ("tree", "hierarchical_reduce"),
        ("star", "single_sink"),
        ("mesh", "peer_broadcast"),
        ("peer", "peer_exchange"),
        ("exponential", "log_distance_peer_exchange"),
        ("flow", "temporal_flow"),
        ("freq", "frequency_counting_protocol"),
        ("sink", "explicit_sink"),
    ]:
        if token in name and motif not in motifs:
            motifs.append(motif)
    selected_primary_values = sorted(
        {
            value
            for row in evidence
            if (
                value := _evidence_int(
                    row,
                    "generated_graph_selected_primary",
                    "selected_primary",
                )
            )
            is not None
        }
    )
    mean_steps = _mean_evidence_float(evidence, "mean_protocol_steps", "protocol_steps")
    mean_messages = _mean_evidence_float(
        evidence,
        "mean_protocol_messages",
        "protocol_messages",
        "mean_messages",
        "MeanTotalMessages",
    )
    generated_rates = [
        value
        for row in evidence
        if (
            value := _evidence_float(row, "generated_graph_rate", "generated_graph")
        )
        is not None
    ]
    metadata = [
        value
        for row in evidence
        if isinstance(value := row.get("protocol_spec_metadata"), dict)
    ]
    features: dict[str, object] = {
        "topology_name": topology_name,
        "generated_graph": topology_name.startswith("generated:")
        or any(value > 0 for value in generated_rates),
        "motifs": motifs or ["unspecified_generated_structure"],
        "aggregation_pattern": _aggregation_pattern_from_motifs(motifs),
        "sink_pattern": "single_selected_primary"
        if selected_primary_values or "single_sink" in motifs
        else "not_explicit",
        "selected_primary_values": selected_primary_values,
        "mean_protocol_steps": mean_steps,
        "mean_protocol_messages": mean_messages,
        "evidence_metadata_keys": sorted(
            {
                str(key)
                for item in metadata
                for key in item.keys()
            }
        ),
    }
    if metadata:
        candidate_ids = sorted(
            {
                str(item["candidate_id"])
                for item in metadata
                if item.get("candidate_id") is not None
            }
        )
        if candidate_ids:
            features["candidate_ids"] = candidate_ids
    return features


def default_operation_recommendations(
    topology_name: str,
    structure_features: dict[str, object],
    condition_scope: dict[str, object],
) -> list[dict[str, object]]:
    """Produce operation-level planner hints from structure evidence."""
    motifs = set(structure_features.get("motifs", []))
    recommendations: list[dict[str, object]] = [
        {
            "action_type": "preserve",
            "target": "condition_trigger",
            "instruction": (
                "Apply this skill only inside the recorded agent and array-size "
                "condition bucket unless held-out evidence expands it."
            ),
            "conditions": {
                "condition_key": condition_scope.get("condition_key"),
                "agent_bucket": condition_scope.get("agent_bucket"),
                "array_size_bucket": condition_scope.get("array_size_bucket"),
            },
        }
    ]
    if "hierarchical_reduce" in motifs or "temporal_flow" in motifs:
        recommendations.append(
            {
                "action_type": "preserve",
                "target": "edge_schedule",
                "instruction": (
                    "Use staged reduce edges where every receiver that aggregates "
                    "partials can forward the merged state in a later step."
                ),
                "expected_effect": {"coverage": "increase", "message_cost": "bounded"},
            }
        )
    if structure_features.get("sink_pattern") == "single_selected_primary":
        recommendations.append(
            {
                "action_type": "preserve",
                "target": "final_reducer",
                "instruction": (
                    "Set selected_primary to the final sink and score only that "
                    "answer holder for generated DAG runs."
                ),
                "expected_effect": {"final_answer_noise": "decrease"},
            }
        )
    if topology_name.startswith("generated:"):
        recommendations.append(
            {
                "action_type": "mutate",
                "target": "free_graph_generation",
                "instruction": (
                    "When exploring variants, change fan-in, sink placement, or "
                    "audit edges while keeping full temporal reachability to the "
                    "selected primary."
                ),
                "expected_effect": {"candidate_diversity": "increase"},
            }
        )
    return recommendations


def condition_specific_skill_id(
    skill_id: str,
    topology_name: str,
    condition_scope: dict[str, object],
) -> str:
    if not _uses_condition_specific_identity(skill_id, topology_name):
        return skill_id
    condition_key = str(condition_scope.get("condition_key", ""))
    if not condition_key or condition_key == "agents_any__arrays_any":
        return skill_id
    suffix = condition_key.replace("agents_", "a").replace("arrays_", "arr")
    return f"{skill_id}__{suffix}"


def _group_dict_evidence_for_skills(
    evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        topology = str(row.get("topology_name", row.get("Topology", "")))
        if _topology_uses_condition_bucket(topology):
            key = f"{topology}|{_dict_condition_key(row)}"
        else:
            key = topology
        grouped[key].append(row)
    return grouped


def _record_skill_group_key(record: EvidenceRecord) -> str:
    if _topology_uses_condition_bucket(record.topology_name):
        return f"{record.topology_name}|{_record_condition_key(record)}"
    return record.topology_name


def _records_to_analysis_evidence(
    records: list[EvidenceRecord],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        rows.append(
            {
                "evidence_id": record.evidence_id,
                "source_type": record.source_type,
                "topology_name": record.topology_name,
                "n_agents": record.n_agents,
                "seed": record.seed,
                **record.metrics,
                "risk_tags": record.risk_tags,
                "dynamics": record.dynamics,
            }
        )
    return rows


def _topology_uses_condition_bucket(topology_name: str) -> bool:
    return topology_name.startswith("generated:")


def _uses_condition_specific_identity(skill_id: str, topology_name: str) -> bool:
    return _topology_uses_condition_bucket(topology_name) or skill_id.startswith(
        "cf_avoid_generated:"
    )


def _dict_condition_key(row: dict[str, Any]) -> str:
    agents = _evidence_int(row, "n_agents", "Agents")
    array_size = _evidence_int(row, "array_size", "ArraySize")
    return f"agents_{agents or 'any'}__arrays_{array_size or 'any'}"


def _record_condition_key(record: EvidenceRecord) -> str:
    array_size = record.metrics.get("array_size")
    return f"agents_{record.n_agents or 'any'}__arrays_{array_size or 'any'}"


def _aggregation_pattern_from_motifs(motifs: list[str]) -> str:
    if "hierarchical_reduce" in motifs:
        return "hierarchical"
    if "single_sink" in motifs:
        return "star_sink"
    if "peer_broadcast" in motifs:
        return "broadcast_then_reduce"
    if "peer_exchange" in motifs:
        return "peer_exchange"
    return "unspecified"


def _evidence_int(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if value is None and "metrics" in row and isinstance(row["metrics"], dict):
            value = row["metrics"].get(key)
        if value in {None, ""}:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
    return None


def _evidence_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None and "metrics" in row and isinstance(row["metrics"], dict):
            value = row["metrics"].get(key)
        if value in {None, ""}:
            continue
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _mean_evidence_float(evidence: list[dict[str, Any]], *keys: str) -> float:
    values = [
        value
        for row in evidence
        if (value := _evidence_float(row, *keys)) is not None
    ]
    return statistics.fmean(values) if values else 0.0
