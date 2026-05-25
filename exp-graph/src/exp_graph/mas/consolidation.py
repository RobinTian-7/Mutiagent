"""Batch consolidation for AutoSkill-style planner skill evolution."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from exp_graph.mas.evidence import read_evidence_jsonl
from exp_graph.mas.schemas import (
    EvidenceRecord,
    EvolutionResult,
    SkillCard,
    SkillPatch,
    SkillRevision,
)
from exp_graph.mas.skill_bank import SkillBank, dump_skill_file, load_skill_file


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_patch_dir(patch_dir: Path | str) -> list[SkillPatch]:
    path = Path(patch_dir)
    patches: list[SkillPatch] = []
    if not path.exists():
        return patches
    for file_path in sorted(path.glob("*.json")):
        data = json.loads(file_path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("patches", [data])
        patches.extend(SkillPatch.model_validate(item) for item in items)
    return patches


def write_patch_file(patches: list[SkillPatch], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [patch.model_dump(mode="json") for patch in patches],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def consolidate_skill_updates(
    *,
    bank: SkillBank,
    patches: list[SkillPatch],
    evidence_records: list[EvidenceRecord],
    batch_id: str | None = None,
) -> tuple[SkillBank, EvolutionResult]:
    """Apply one validated patch batch to a skill bank in memory."""
    batch = batch_id or f"revision_batch_{utc_stamp()}"
    records_by_id = {record.evidence_id: record for record in evidence_records}
    grouped = _group_patches(bank, patches)
    counts: Counter[str] = Counter()
    revisions: list[SkillRevision] = []
    warnings: list[str] = []

    for skill_id, skill_patches in grouped.items():
        current = bank.get(skill_id)
        if current is None:
            add_patch = next(
                (patch for patch in skill_patches if patch.candidate_skill is not None),
                None,
            )
            if add_patch is None:
                counts["discarded"] += len(skill_patches)
                warnings.append(f"discarded patches for missing skill {skill_id}")
                continue
            skill = _prepare_new_skill(add_patch, records_by_id)
            bank.skills[skill.skill_id] = skill
            counts["added"] += 1
            revisions.append(
                _revision(
                    skill_id=skill.skill_id,
                    from_version=None,
                    to_version=skill.version,
                    batch_id=batch,
                    patches=[add_patch],
                    evidence_refs=skill.evidence_refs,
                    changed_fields=["skill"],
                    summary=f"Added new planner skill {skill.skill_id}.",
                )
            )
            continue

        applicable = [
            patch
            for patch in skill_patches
            if not _patch_already_applied(current, patch.patch_id)
        ]
        skipped = len(skill_patches) - len(applicable)
        counts["skipped_already_applied"] += skipped
        if not applicable:
            continue
        compatible = []
        for patch in applicable:
            if _patch_matches_skill_topology(current, patch, records_by_id):
                compatible.append(patch)
            else:
                counts["discarded"] += 1
                warnings.append(
                    f"discarded {patch.patch_id}: evidence/candidate topology "
                    f"does not match target skill {current.skill_id}"
                )
        applicable = compatible
        if not applicable:
            continue
        from_version = current.version
        updated, changed_fields = _merge_patch_group(
            current,
            applicable,
            records_by_id,
        )
        if changed_fields:
            bank.skills[current.skill_id] = updated
            counts["merged"] += 1
            revisions.append(
                _revision(
                    skill_id=updated.skill_id,
                    from_version=from_version,
                    to_version=updated.version,
                    batch_id=batch,
                    patches=applicable,
                    evidence_refs=updated.evidence_refs,
                    changed_fields=changed_fields,
                    summary=_revision_summary(updated, changed_fields),
                )
            )
        else:
            counts["discarded"] += len(applicable)

    for patch in patches:
        if patch.action == "discard":
            counts["discarded"] += 1
        if patch.action == "deprecate":
            counts["deprecated"] += 1

    return bank, EvolutionResult(
        batch_id=batch,
        counts=dict(counts),
        revisions=revisions,
        warnings=warnings,
    )


def evolve_skill_dir(
    *,
    skill_dir: Path | str,
    evidence_file: Path | str | None,
    patch_dir: Path | str,
    backup: bool,
    markdown_dir: Path | str | None = None,
    revision_dir: Path | str | None = None,
) -> EvolutionResult:
    """Load, consolidate, and persist a skill bank with optional backup."""
    skill_path = Path(skill_dir)
    bank = SkillBank.load_dir(skill_path)
    records = read_evidence_jsonl(evidence_file) if evidence_file else []
    patches = load_patch_dir(patch_dir)
    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=patches,
        evidence_records=records,
    )
    if backup and skill_path.exists():
        backup_path = skill_path.with_name(f"{skill_path.name}_backup_{utc_stamp()}")
        shutil.copytree(skill_path, backup_path)
    tmp_path = skill_path.with_name(f"{skill_path.name}_tmp_{result.batch_id}")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    for skill in updated:
        dump_skill_file(skill, tmp_path / f"{skill.skill_id}.yaml")
    _validate_skill_dir(tmp_path)
    if skill_path.exists():
        shutil.rmtree(skill_path)
    tmp_path.rename(skill_path)
    revision_path = Path(revision_dir or skill_path.parent / "mas_skill_revisions")
    revision_path.mkdir(parents=True, exist_ok=True)
    (revision_path / f"{result.batch_id}.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if markdown_dir is not None:
        from exp_graph.mas.skill_bank import render_skill_bank_markdown

        render_skill_bank_markdown(updated, markdown_dir)
    return result


def _group_patches(
    bank: SkillBank,
    patches: list[SkillPatch],
) -> dict[str, list[SkillPatch]]:
    grouped: dict[str, list[SkillPatch]] = defaultdict(list)
    for patch in patches:
        if patch.action == "discard":
            continue
        skill_id = patch.target_skill_id
        if not skill_id and patch.candidate_skill is not None:
            skill_id = _route_candidate(bank, patch.candidate_skill)
        if not skill_id:
            continue
        grouped[skill_id].append(patch.model_copy(update={"target_skill_id": skill_id}))
    return grouped


def _route_candidate(bank: SkillBank, candidate: SkillCard) -> str:
    for skill in bank:
        if (
            skill.task_family == candidate.task_family
            and skill.objective == candidate.objective
            and skill.topology_name == candidate.topology_name
            and _condition_scope_compatible(skill, candidate)
        ):
            return skill.skill_id
    return candidate.skill_id


def _patch_matches_skill_topology(
    skill: SkillCard,
    patch: SkillPatch,
    records_by_id: dict[str, EvidenceRecord],
) -> bool:
    skill_topology = skill.topology_name
    if not skill_topology:
        return True
    if patch.candidate_skill is not None:
        candidate_topology = patch.candidate_skill.topology_name
        if candidate_topology and candidate_topology != skill_topology:
            return False
        if not _condition_scope_compatible(skill, patch.candidate_skill):
            return False
    for ref in patch.evidence_refs:
        record = records_by_id.get(ref)
        if record is None or not record.topology_name:
            continue
        if record.topology_name != skill_topology:
            return False
        if not _record_matches_skill_trigger(skill, record):
            return False
    return True


def _condition_scope_compatible(current: SkillCard, incoming: SkillCard) -> bool:
    if not (
        _topology_uses_condition_bucket(current.topology_name)
        or _topology_uses_condition_bucket(incoming.topology_name)
    ):
        return True
    current_key = current.trigger.get("condition_key")
    incoming_key = incoming.trigger.get("condition_key")
    if current_key or incoming_key:
        return current_key == incoming_key
    return True


def _topology_uses_condition_bucket(topology_name: str | None) -> bool:
    return bool(topology_name and topology_name.startswith("generated:"))


def _record_matches_skill_trigger(skill: SkillCard, record: EvidenceRecord) -> bool:
    trigger = skill.trigger
    min_agents = trigger.get("min_agents")
    max_agents = trigger.get("max_agents")
    if record.n_agents is not None:
        if min_agents is not None and record.n_agents < int(min_agents):
            return False
        if max_agents is not None and record.n_agents > int(max_agents):
            return False
        agent_counts = trigger.get("agent_counts")
        if agent_counts is not None and record.n_agents not in {
            int(item) for item in agent_counts
        }:
            return False
    array_size = record.metrics.get("array_size")
    if array_size is not None:
        min_array = trigger.get("min_array_size")
        max_array = trigger.get("max_array_size")
        array_int = int(array_size)
        if min_array is not None and array_int < int(min_array):
            return False
        if max_array is not None and array_int > int(max_array):
            return False
        array_sizes = trigger.get("array_sizes")
        if array_sizes is not None and array_int not in {
            int(item) for item in array_sizes
        }:
            return False
    return True


def _prepare_new_skill(
    patch: SkillPatch,
    records_by_id: dict[str, EvidenceRecord],
) -> SkillCard:
    if patch.candidate_skill is None:
        raise ValueError("add patch requires candidate_skill")
    skill = patch.candidate_skill
    refs = _dedupe([*skill.evidence_refs, *patch.evidence_refs])
    recomputed_tradeoff = _recompute_tradeoff(refs, records_by_id)
    recomputed_dynamics = _recompute_dynamics(refs, records_by_id)
    design_insights = list(skill.design_insights)
    _extend_unique_dicts(design_insights, patch.update.get("design_insights"))
    update = {
        "evidence_refs": refs,
        "design_insights": _dedupe_design_insights(design_insights),
        "expected_tradeoff": {
            **skill.expected_tradeoff,
            **recomputed_tradeoff,
        },
        "expected_dynamics": {
            **skill.expected_dynamics,
            **recomputed_dynamics,
        },
        "revision_history": [
            {
                "patch_ids": [patch.patch_id],
                "summary": patch.lesson,
                "created_at": utc_now(),
            }
        ],
    }
    return skill.model_copy(update=update)


def _merge_patch_group(
    skill: SkillCard,
    patches: list[SkillPatch],
    records_by_id: dict[str, EvidenceRecord],
) -> tuple[SkillCard, list[str]]:
    changed: set[str] = set()
    evidence_refs = _dedupe([
        *skill.evidence_refs,
        *[
            ref
            for patch in patches
            for ref in patch.evidence_refs
        ],
    ])
    evidence = _deprecate_legacy_evidence(skill.evidence)
    counterexamples = list(skill.counterexamples)
    risk_notes = list(skill.risk_notes)
    failure_modes = list(skill.failure_modes)
    hypotheses = list(skill.hypotheses)
    design_insights = list(skill.design_insights)
    fallback = dict(skill.fallback)
    organization_policy = dict(skill.organization_policy)
    validation_plan = list(skill.validation_plan)
    expected_tradeoff_updates: dict[str, object] = {}
    expected_dynamics_updates: dict[str, object] = {}
    trigger = dict(skill.trigger)
    tags = list(skill.tags)
    tags_changed = False

    for patch in patches:
        if patch.action == "deprecate":
            changed.add("evidence")
            tags = _dedupe([*tags, "deprecated"])
            tags_changed = True
            continue
        evidence.extend(patch.evidence)
        update = patch.update or {}
        _extend_unique_dicts(counterexamples, update.get("counterexamples"))
        _extend_unique_dicts(risk_notes, update.get("risk_notes"))
        _extend_unique_dicts(failure_modes, update.get("failure_modes"))
        _extend_unique_dicts(hypotheses, update.get("hypotheses"))
        _extend_unique_dicts(validation_plan, update.get("validation_plan"))
        _extend_unique_dicts(design_insights, update.get("design_insights"))
        if "fallback" in update and isinstance(update["fallback"], dict):
            fallback.update(update["fallback"])
        if "trigger" in update and isinstance(update["trigger"], dict):
            trigger.update(update["trigger"])
        if "expected_tradeoff" in update and isinstance(
            update["expected_tradeoff"],
            dict,
        ):
            expected_tradeoff_updates.update(update["expected_tradeoff"])
        if "expected_dynamics" in update and isinstance(
            update["expected_dynamics"],
            dict,
        ):
            expected_dynamics_updates.update(update["expected_dynamics"])
        if "organization_policy" in update and isinstance(
            update["organization_policy"], dict
        ):
            organization_policy = _merge_organization_policy(
                organization_policy,
                update["organization_policy"],
            )
        if patch.candidate_skill is not None:
            candidate = patch.candidate_skill
            evidence.extend(candidate.evidence)
            evidence_refs = _dedupe([*evidence_refs, *candidate.evidence_refs])
            _extend_unique_dicts(counterexamples, candidate.counterexamples)
            _extend_unique_dicts(risk_notes, candidate.risk_notes)
            _extend_unique_dicts(failure_modes, candidate.failure_modes)
            _extend_unique_dicts(hypotheses, candidate.hypotheses)
            _extend_unique_dicts(design_insights, candidate.design_insights)
            fallback.update(candidate.fallback)
            organization_policy = _merge_organization_policy(
                organization_policy,
                candidate.organization_policy,
            )
            expected_dynamics_updates.update(candidate.expected_dynamics)
        if patch.lesson:
            risk_notes.append(
                {
                    "source": patch.source,
                    "patch_id": patch.patch_id,
                    "summary": patch.lesson,
                    "confidence": patch.confidence,
                }
            )

    tradeoff = {
        **skill.expected_tradeoff,
        **_recompute_tradeoff(evidence_refs, records_by_id),
        **expected_tradeoff_updates,
    }
    dynamics = {
        **skill.expected_dynamics,
        **_recompute_dynamics(evidence_refs, records_by_id),
        **expected_dynamics_updates,
    }
    confidence = _recompute_confidence(evidence_refs, records_by_id)
    new_version = _bump_version(skill.version, minor=_requires_minor_bump(patches))
    revision_history = [
        *skill.revision_history,
        {
            "patch_ids": [patch.patch_id for patch in patches],
            "evidence_refs": evidence_refs,
            "summary": "; ".join(patch.lesson for patch in patches if patch.lesson),
            "created_at": utc_now(),
        },
    ]
    changed.update(
        [
            "evidence_refs",
            "evidence",
            "trigger",
            "expected_tradeoff",
            "expected_dynamics",
            "design_insights",
            "risk_notes",
            "fallback",
            "confidence",
            "revision_history",
        ]
    )
    if tags_changed:
        changed.add("tags")
    return skill.model_copy(
        update={
            "version": new_version,
            "evidence": evidence,
            "evidence_refs": evidence_refs,
            "trigger": trigger,
            "expected_tradeoff": tradeoff or skill.expected_tradeoff,
            "expected_dynamics": dynamics or skill.expected_dynamics,
            "design_insights": _dedupe_design_insights(design_insights),
            "counterexamples": _dedupe_dicts(counterexamples),
            "risk_notes": _dedupe_dicts(risk_notes),
            "failure_modes": _dedupe_dicts(failure_modes),
            "hypotheses": _dedupe_dicts(hypotheses),
            "fallback": fallback,
            "organization_policy": organization_policy,
            "validation_plan": _dedupe_dicts(validation_plan),
            "confidence": confidence or skill.confidence,
            "revision_history": revision_history,
            "tags": tags,
        }
    ), sorted(changed)


def _recompute_tradeoff(
    evidence_refs: list[str],
    records_by_id: dict[str, EvidenceRecord],
) -> dict[str, object]:
    rows = [
        records_by_id[ref]
        for ref in evidence_refs
        if ref in records_by_id
        and records_by_id[ref].status == "observed"
        and records_by_id[ref].source_type in {"aggregate", "run"}
    ]
    if not rows:
        return {}
    metrics = [row.metrics for row in rows]
    return {
        "mean_rmse": _mean_metric(metrics, "mean_rmse", "final_rmse"),
        "std_rmse": _mean_metric(metrics, "std_rmse"),
        "mean_norm_l1": _mean_metric(metrics, "mean_norm_l1", "final_norm_l1"),
        "exact_match_rate": _mean_metric(
            metrics,
            "exact_match_rate",
            "final_exact_match",
        ),
        "mean_messages": _mean_metric(metrics, "mean_messages", "total_messages"),
        "mean_model_calls": _mean_metric(metrics, "mean_model_calls", "total_model_calls"),
        "mean_token_cost": _mean_metric(metrics, "mean_token_cost", "token_cost"),
        "active_evidence_count": len(rows),
    }


def _recompute_dynamics(
    evidence_refs: list[str],
    records_by_id: dict[str, EvidenceRecord],
) -> dict[str, object]:
    rows = [
        records_by_id[ref]
        for ref in evidence_refs
        if ref in records_by_id
        and records_by_id[ref].status == "observed"
        and records_by_id[ref].source_type == "trace"
    ]
    if not rows:
        return {}
    return {
        "coverage_growth": {
            "mean_coverage_gain": _mean_nested(rows, "coverage_growth", "mean_coverage_gain"),
            "mean_final_coverage": _mean_nested(rows, "coverage_growth", "final_mean_coverage"),
            "mean_final_max_coverage": _mean_nested(rows, "coverage_growth", "final_max_coverage"),
        },
        "aggregation_reliability": {
            "mean_sink_best_rmse_gap": _mean_nested(
                rows,
                "aggregation_reliability",
                "sink_best_rmse_gap",
            ),
            "mean_sink_coverage": _mean_nested(
                rows,
                "aggregation_reliability",
                "sink_coverage_ratio",
            ),
        },
        "merge_quality": {
            "mean_retry_attempts": _mean_nested(rows, "merge_quality", "retry_attempts"),
            "mean_parse_errors": _mean_nested(rows, "merge_quality", "parse_error_count"),
            "mean_avg_fan_in": _mean_nested(rows, "merge_quality", "avg_fan_in"),
        },
        "risk_tags": sorted({tag for row in rows for tag in row.risk_tags}),
    }


def _recompute_confidence(
    evidence_refs: list[str],
    records_by_id: dict[str, EvidenceRecord],
) -> dict[str, object]:
    rows = [
        records_by_id[ref]
        for ref in evidence_refs
        if ref in records_by_id and records_by_id[ref].status == "observed"
    ]
    if not rows:
        return {}
    seeds = {row.seed for row in rows if row.seed is not None}
    agents = {row.n_agents for row in rows if row.n_agents is not None}
    risk_types = {tag for row in rows for tag in row.risk_tags}
    evidence_strength = min(0.9, 0.2 + 0.1 * len(seeds) + 0.1 * len(agents))
    risk_penalty = min(0.4, 0.05 * len(risk_types))
    return {
        "score": max(0.0, evidence_strength - risk_penalty),
        "evidence_strength": evidence_strength,
        "risk_penalty": risk_penalty,
        "active_evidence_count": len(rows),
        "seed_count": len(seeds),
        "agent_count_count": len(agents),
        "last_validated": utc_now(),
    }


def _merge_organization_policy(
    current: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(current)
    for key, value in incoming.items():
        if key in {"topology_name", "operators", "planner_mode"} and key in merged:
            if merged[key] != value:
                continue
        if key in {"rationale_rules", "operation_recommendations", "operator_constraints"}:
            existing = merged.get(key, [])
            if key == "rationale_rules":
                merged[key] = _dedupe(
                    [
                        *list(existing if isinstance(existing, list) else []),
                        *list(value if isinstance(value, list) else []),
                    ]
                )
            else:
                incoming_items = value if isinstance(value, list) else [value]
                existing_items = existing if isinstance(existing, list) else [existing]
                merged[key] = _dedupe_dicts(
                    [
                        item if isinstance(item, dict) else {"summary": str(item)}
                        for item in [*existing_items, *incoming_items]
                        if item
                    ]
                )
            continue
        if key in {"structure_features", "condition_scope"} and isinstance(
            value,
            dict,
        ):
            current_value = merged.get(key)
            merged[key] = {
                **(current_value if isinstance(current_value, dict) else {}),
                **value,
            }
            continue
        merged[key] = value
    return merged


def _deprecate_legacy_evidence(evidence: list[dict[str, object]]) -> list[dict[str, object]]:
    updated = []
    for item in evidence:
        if "evidence_id" in item:
            updated.append(item)
        else:
            entry = dict(item)
            entry.setdefault("status", "deprecated")
            entry.setdefault("deprecation_reason", "legacy_placeholder")
            updated.append(entry)
    return updated


def _requires_minor_bump(patches: list[SkillPatch]) -> bool:
    for patch in patches:
        update = patch.update or {}
        if any(
            key in update
            for key in [
                "trigger",
                "fallback",
                "expected_dynamics",
                "design_insights",
            ]
        ):
            return True
    return False


def _bump_version(version: str, *, minor: bool) -> str:
    parts = [int(part) for part in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if minor:
        parts[1] += 1
        parts[2] = 0
    else:
        parts[2] += 1
    return ".".join(str(part) for part in parts[:3])


def _patch_already_applied(skill: SkillCard, patch_id: str) -> bool:
    for revision in skill.revision_history:
        patch_ids = revision.get("patch_ids", [])
        if isinstance(patch_ids, list) and patch_id in patch_ids:
            return True
    return False


def _revision(
    *,
    skill_id: str,
    from_version: str | None,
    to_version: str | None,
    batch_id: str,
    patches: list[SkillPatch],
    evidence_refs: list[str],
    changed_fields: list[str],
    summary: str,
) -> SkillRevision:
    return SkillRevision(
        revision_id=f"rev_{skill_id}_{utc_stamp()}",
        skill_id=skill_id,
        from_version=from_version,
        to_version=to_version,
        batch_id=batch_id,
        patch_ids=[patch.patch_id for patch in patches],
        evidence_refs=evidence_refs,
        changed_fields=changed_fields,
        summary=summary,
        created_at=utc_now(),
    )


def _revision_summary(skill: SkillCard, changed_fields: list[str]) -> str:
    return f"Updated {skill.skill_id} fields: {', '.join(changed_fields)}."


def _validate_skill_dir(path: Path) -> None:
    for file_path in path.glob("*.yaml"):
        load_skill_file(file_path)


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


def _extend_unique_dicts(target: list[dict[str, object]], value: object) -> None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                target.append(item)
            else:
                target.append({"summary": str(item)})
    elif isinstance(value, dict):
        target.append(value)
    elif value:
        target.append({"summary": str(value)})


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe_dicts(values: list[dict[str, object]]) -> list[dict[str, object]]:
    seen = set()
    result = []
    for value in values:
        key = json.dumps(value, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_design_insights(
    values: list[dict[str, object]],
) -> list[dict[str, object]]:
    seen_ids: set[str] = set()
    seen_payloads: set[str] = set()
    result: list[dict[str, object]] = []
    for value in values:
        insight_id = value.get("insight_id")
        if insight_id:
            key = str(insight_id)
            if key in seen_ids:
                continue
            seen_ids.add(key)
        else:
            key = json.dumps(value, sort_keys=True, default=str)
            if key in seen_payloads:
                continue
            seen_payloads.add(key)
        result.append(value)
    return result
