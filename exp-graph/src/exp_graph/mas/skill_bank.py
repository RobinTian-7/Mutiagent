"""SkillBank storage, retrieval, lifecycle, and Markdown rendering."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from exp_graph.mas.schemas import PlannerRequest, SkillCard, SkillPatch


class SkillBank:
    """Filesystem-backed versioned MAS skill bank."""

    def __init__(self, skills: list[SkillCard] | None = None) -> None:
        self.skills: dict[str, SkillCard] = {
            skill.skill_id: skill for skill in (skills or [])
        }

    def __iter__(self):
        return iter(self.skills.values())

    def __len__(self) -> int:
        return len(self.skills)

    def get(self, skill_id: str) -> SkillCard | None:
        return self.skills.get(skill_id)

    @classmethod
    def load_dir(cls, directory: Path | str) -> "SkillBank":
        path = Path(directory)
        if not path.exists():
            return cls([])
        skills = [
            load_skill_file(file_path)
            for file_path in sorted(path.glob("*.yaml"))
        ]
        return cls(skills)

    def save_dir(self, directory: Path | str) -> None:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        for skill in sorted(self.skills.values(), key=lambda item: item.skill_id):
            dump_skill_file(skill, path / f"{skill.skill_id}.yaml")

    def retrieve(self, request: PlannerRequest) -> list[SkillCard]:
        """Return skills matching task, objective, n_agents, and topology allowlist."""
        matches: list[SkillCard] = []
        for skill in self.skills.values():
            if not is_selectable_skill(skill):
                continue
            if skill.task_family != request.task_family:
                continue
            if skill.objective not in {request.objective.name, "balanced"}:
                continue
            topology = skill.topology_name
            if request.allowed_topologies and topology not in request.allowed_topologies:
                continue
            if not self._matches_agent_range(skill, request.n_agents):
                continue
            if not self._matches_array_size(skill, request.array_size):
                continue
            matches.append(skill)
        matches.sort(key=lambda skill: self._retrieval_sort_key(skill, request))
        return matches

    def retrieve_avoid(self, request: PlannerRequest) -> list[SkillCard]:
        """Return matching avoid/counterexample skills as risk constraints."""
        matches: list[SkillCard] = []
        for skill in self.skills.values():
            if not is_avoid_skill(skill):
                continue
            if not _is_active_skill(skill):
                continue
            if skill.task_family != request.task_family:
                continue
            if skill.objective not in {request.objective.name, "balanced"}:
                continue
            if not self._matches_agent_range(skill, request.n_agents):
                continue
            if not self._matches_array_size(skill, request.array_size):
                continue
            matches.append(skill)
        matches.sort(key=lambda skill: self._retrieval_sort_key(skill, request))
        return matches

    def apply_patch(self, patch: SkillPatch) -> str:
        """Apply one AutoSkill-style lifecycle patch."""
        if patch.action == "discard":
            return "discarded"
        if patch.action == "deprecate":
            if patch.target_skill_id and patch.target_skill_id in self.skills:
                skill = self.skills[patch.target_skill_id]
                self.skills[skill.skill_id] = skill.model_copy(
                    update={
                        "evidence": [
                            {
                                **item,
                                "status": item.get("status", "deprecated"),
                                "deprecation_reason": item.get(
                                    "deprecation_reason",
                                    patch.lesson or "deprecated by patch",
                                ),
                            }
                            for item in skill.evidence
                        ],
                        "revision_history": [
                            *skill.revision_history,
                            {
                                "patch_ids": [patch.patch_id],
                                "summary": patch.lesson,
                            },
                        ],
                        "tags": _dedupe([*skill.tags, "deprecated"]),
                    }
                )
            return "deprecated"
        if patch.action == "add":
            if patch.candidate_skill is None:
                raise ValueError("add patch requires candidate_skill")
            self.skills[patch.candidate_skill.skill_id] = patch.candidate_skill
            return "added"
        if patch.action == "merge":
            if not patch.target_skill_id:
                raise ValueError("merge patch requires target_skill_id")
            current = self.skills.get(patch.target_skill_id)
            if current is None:
                if patch.candidate_skill is None:
                    raise ValueError("merge patch has no target and no candidate")
                self.skills[patch.candidate_skill.skill_id] = patch.candidate_skill
                return "added"
            self.skills[current.skill_id] = merge_skill(current, patch)
            return "merged"
        raise ValueError(f"unsupported patch action: {patch.action}")

    def apply_patches(self, patches: list[SkillPatch]) -> dict[str, int]:
        counts = {"added": 0, "merged": 0, "discarded": 0, "deprecated": 0}
        for patch in patches:
            outcome = self.apply_patch(patch)
            counts[outcome] += 1
        return {
            key: value
            for key, value in counts.items()
            if value or key != "deprecated"
        }

    @staticmethod
    def _matches_agent_range(skill: SkillCard, n_agents: int) -> bool:
        trigger = skill.trigger
        min_agents = trigger.get("min_agents")
        max_agents = trigger.get("max_agents")
        if min_agents is not None and n_agents < int(min_agents):
            return False
        if max_agents is not None and n_agents > int(max_agents):
            return False
        agent_counts = trigger.get("agent_counts")
        if agent_counts is not None and n_agents not in {int(item) for item in agent_counts}:
            return False
        return True

    @staticmethod
    def _matches_array_size(skill: SkillCard, array_size: int | None) -> bool:
        if array_size is None:
            return True
        trigger = skill.trigger
        min_array = trigger.get("min_array_size")
        max_array = trigger.get("max_array_size")
        if min_array is not None and array_size < int(min_array):
            return False
        if max_array is not None and array_size > int(max_array):
            return False
        array_sizes = trigger.get("array_sizes")
        if array_sizes is not None and array_size not in {
            int(item) for item in array_sizes
        }:
            return False
        return True

    @staticmethod
    def _retrieval_sort_key(
        skill: SkillCard,
        request: PlannerRequest,
    ) -> tuple[int, float, int, str]:
        return (
            -_condition_specificity(skill, request),
            _skill_mean_rmse(skill),
            -_skill_evidence_count(skill),
            skill.skill_id,
        )


def is_selectable_skill(skill: SkillCard) -> bool:
    """Return whether a skill is safe for the emperor to choose directly."""
    return _is_active_skill(skill) and not is_avoid_skill(skill)


def is_avoid_skill(skill: SkillCard) -> bool:
    """Return whether a skill should be used only as a negative constraint."""
    tags = {tag.lower() for tag in skill.tags}
    return "counterexample" in tags or skill.skill_id.startswith("cf_avoid_")


def _is_active_skill(skill: SkillCard) -> bool:
    tags = {tag.lower() for tag in skill.tags}
    blocked_tags = {"archived", "deprecated"}
    return not (tags & blocked_tags)


def compact_skill_bank(
    bank: SkillBank,
    *,
    max_per_condition: int = 3,
) -> tuple[SkillBank, SkillBank, dict[str, object]]:
    """Keep only the lowest-RMSE selectable skills in each condition bucket."""
    limit = max(1, int(max_per_condition))
    grouped: dict[str, list[SkillCard]] = {}
    archived: list[SkillCard] = []
    active_avoid: list[SkillCard] = []
    for skill in sorted(bank, key=lambda item: item.skill_id):
        if is_avoid_skill(skill) and _is_active_skill(skill):
            active_avoid.append(skill)
            continue
        if not is_selectable_skill(skill):
            archived.append(_archive_skill(skill, "non_selectable"))
            continue
        bucket = _skill_condition_bucket(skill)
        grouped.setdefault(bucket, []).append(skill)

    active: list[SkillCard] = []
    bucket_summaries: dict[str, dict[str, object]] = {}
    for bucket, skills in sorted(grouped.items()):
        ranked = sorted(
            skills,
            key=lambda skill: (
                _skill_mean_rmse(skill),
                -_skill_evidence_count(skill),
                skill.skill_id,
            ),
        )
        kept = ranked[:limit]
        dropped = ranked[limit:]
        active.extend(kept)
        archived.extend(
            _archive_skill(skill, f"outside_top_{limit}_for_condition_bucket")
            for skill in dropped
        )
        bucket_summaries[bucket] = {
            "kept": [skill.skill_id for skill in kept],
            "archived": [skill.skill_id for skill in dropped],
        }

    summary = {
        "max_per_condition": limit,
        "active_count": len(active) + len(active_avoid),
        "active_avoid_count": len(active_avoid),
        "archived_count": len(archived),
        "condition_buckets": bucket_summaries,
    }
    return SkillBank([*active, *active_avoid]), SkillBank(archived), summary


def compact_skill_dir(
    *,
    skill_dir: Path | str,
    output_dir: Path | str,
    archive_dir: Path | str,
    max_per_condition: int = 3,
) -> dict[str, object]:
    """Compact a skill directory into active and archived skill directories."""
    active, archived, summary = compact_skill_bank(
        SkillBank.load_dir(skill_dir),
        max_per_condition=max_per_condition,
    )
    output_path = Path(output_dir)
    archive_path = Path(archive_dir)
    for path in [output_path, archive_path]:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    active.save_dir(output_path)
    archived.save_dir(archive_path)
    summary = {
        **summary,
        "input_dir": str(skill_dir),
        "output_dir": str(output_path),
        "archive_dir": str(archive_path),
    }
    (output_path / "skill_compaction_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _condition_specificity(skill: SkillCard, request: PlannerRequest) -> int:
    trigger = skill.trigger
    score = 0
    if trigger.get("condition_key"):
        score += 8
    agent_counts = trigger.get("agent_counts")
    if agent_counts is not None and request.n_agents in {int(item) for item in agent_counts}:
        score += 4
    elif (
        trigger.get("min_agents") is not None
        and trigger.get("max_agents") is not None
        and int(trigger["min_agents"]) == int(trigger["max_agents"]) == request.n_agents
    ):
        score += 4
    elif trigger.get("min_agents") is not None or trigger.get("max_agents") is not None:
        score += 2

    if request.array_size is not None:
        array_sizes = trigger.get("array_sizes")
        if array_sizes is not None and request.array_size in {
            int(item) for item in array_sizes
        }:
            score += 4
        elif (
            trigger.get("min_array_size") is not None
            and trigger.get("max_array_size") is not None
            and int(trigger["min_array_size"])
            == int(trigger["max_array_size"])
            == request.array_size
        ):
            score += 4
        elif (
            trigger.get("min_array_size") is not None
            or trigger.get("max_array_size") is not None
        ):
            score += 2
    return score


def _skill_mean_rmse(skill: SkillCard) -> float:
    value = skill.expected_tradeoff.get("mean_rmse")
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _skill_evidence_count(skill: SkillCard) -> int:
    value = skill.expected_tradeoff.get("active_evidence_count")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return len(skill.evidence_refs) + len(skill.evidence)


def _skill_condition_bucket(skill: SkillCard) -> str:
    trigger = skill.trigger
    return json.dumps(
        {
            "task_family": skill.task_family,
            "objective": skill.objective,
            "agent_bucket": trigger.get("agent_bucket")
            or _range_bucket(trigger, "agents", "min_agents", "max_agents"),
            "array_size_bucket": trigger.get("array_size_bucket")
            or _range_bucket(trigger, "arrays", "min_array_size", "max_array_size"),
        },
        sort_keys=True,
    )


def _range_bucket(
    trigger: dict[str, object],
    prefix: str,
    min_key: str,
    max_key: str,
) -> str:
    min_value = trigger.get(min_key)
    max_value = trigger.get(max_key)
    if min_value is not None and max_value is not None and int(min_value) == int(max_value):
        return f"{prefix}_{int(min_value)}"
    if min_value is not None or max_value is not None:
        return f"{prefix}_{min_value or 'any'}_{max_value or 'any'}"
    return f"{prefix}_any"


def _archive_skill(skill: SkillCard, reason: str) -> SkillCard:
    tags = _dedupe([*skill.tags, "archived"])
    dynamics = dict(skill.expected_dynamics)
    dynamics["archive_reason"] = reason
    return skill.model_copy(update={"tags": tags, "expected_dynamics": dynamics})


def merge_skill(skill: SkillCard, patch: SkillPatch) -> SkillCard:
    """Merge a candidate patch into an existing skill identity."""
    candidate = patch.candidate_skill
    evidence = [*skill.evidence, *patch.evidence]
    evidence_refs = _dedupe([*skill.evidence_refs, *patch.evidence_refs])
    counterexamples = list(skill.counterexamples)
    risk_notes = list(skill.risk_notes)
    failure_modes = list(skill.failure_modes)
    hypotheses = list(skill.hypotheses)
    validation_plan = list(skill.validation_plan)
    if candidate is not None:
        evidence.extend(candidate.evidence)
        evidence_refs = _dedupe([*evidence_refs, *candidate.evidence_refs])
        counterexamples.extend(candidate.counterexamples)
        risk_notes.extend(candidate.risk_notes)
        failure_modes.extend(candidate.failure_modes)
        hypotheses.extend(candidate.hypotheses)
        validation_plan.extend(candidate.validation_plan)
    if patch.action == "merge" and patch.lesson:
        evidence.append(
            {
                "lesson": patch.lesson,
                "source": patch.source,
                "confidence": patch.confidence,
            }
        )
        risk_notes.append(
            {
                "summary": patch.lesson,
                "source": patch.source,
                "confidence": patch.confidence,
            }
        )
    update_data = patch.update or {}
    _extend_dict_items(risk_notes, update_data.get("risk_notes"))
    _extend_dict_items(failure_modes, update_data.get("failure_modes"))
    _extend_dict_items(hypotheses, update_data.get("hypotheses"))
    _extend_dict_items(validation_plan, update_data.get("validation_plan"))
    update = {
        "version": bump_patch_version(skill.version),
        "evidence": evidence,
        "evidence_refs": evidence_refs,
        "counterexamples": counterexamples,
        "risk_notes": risk_notes,
        "failure_modes": failure_modes,
        "hypotheses": hypotheses,
        "validation_plan": validation_plan,
    }
    if candidate is not None:
        merged_policy = dict(skill.organization_policy)
        merged_policy = _merge_policy(merged_policy, candidate.organization_policy)
        update["organization_policy"] = merged_policy
        merged_tradeoff = dict(skill.expected_tradeoff)
        merged_tradeoff.update(candidate.expected_tradeoff)
        update["expected_tradeoff"] = merged_tradeoff
        merged_fallback = dict(skill.fallback)
        merged_fallback.update(candidate.fallback)
        update["fallback"] = merged_fallback
        merged_dynamics = dict(skill.expected_dynamics)
        merged_dynamics.update(candidate.expected_dynamics)
        update["expected_dynamics"] = merged_dynamics
        merged_confidence = dict(skill.confidence)
        merged_confidence.update(candidate.confidence)
        update["confidence"] = merged_confidence
    if "expected_dynamics" in update_data and isinstance(
        update_data["expected_dynamics"],
        dict,
    ):
        merged_dynamics = dict(update.get("expected_dynamics", skill.expected_dynamics))
        merged_dynamics.update(update_data["expected_dynamics"])
        update["expected_dynamics"] = merged_dynamics
    if "fallback" in update_data and isinstance(update_data["fallback"], dict):
        merged_fallback = dict(update.get("fallback", skill.fallback))
        merged_fallback.update(update_data["fallback"])
        update["fallback"] = merged_fallback
    if "organization_policy" in update_data and isinstance(
        update_data["organization_policy"],
        dict,
    ):
        merged_policy = dict(update.get("organization_policy", skill.organization_policy))
        merged_policy = _merge_policy(merged_policy, update_data["organization_policy"])
        update["organization_policy"] = merged_policy
    return skill.model_copy(update=update)


def bump_patch_version(version: str) -> str:
    parts = [int(part) for part in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    parts[-1] += 1
    return ".".join(str(part) for part in parts[:3])


def load_skill_file(path: Path | str) -> SkillCard:
    """Load a skill file. JSON is accepted as the YAML-compatible subset."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError(
                f"{file_path} is not JSON-subset YAML and PyYAML is unavailable"
            ) from exc
        data = yaml.safe_load(text)
    return SkillCard.model_validate(data)


def dump_skill_file(skill: SkillCard, path: Path | str) -> None:
    """Write skill as JSON-subset YAML so no runtime YAML dependency is required."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(skill.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _extend_dict_items(target: list[dict[str, object]], value: object) -> None:
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


def _merge_policy(
    current: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(current)
    for key, value in incoming.items():
        if key in {"operation_recommendations", "operator_constraints"}:
            existing = merged.get(key, [])
            existing_items = existing if isinstance(existing, list) else [existing]
            incoming_items = value if isinstance(value, list) else [value]
            merged[key] = _dedupe_dicts(
                [
                    item if isinstance(item, dict) else {"summary": str(item)}
                    for item in [*existing_items, *incoming_items]
                    if item
                ]
            )
            continue
        if key == "rationale_rules":
            existing = merged.get(key, [])
            merged[key] = _dedupe(
                [
                    *[
                        str(item)
                        for item in (existing if isinstance(existing, list) else [])
                    ],
                    *[
                        str(item)
                        for item in (value if isinstance(value, list) else [])
                    ],
                ]
            )
            continue
        if key in {"structure_features", "condition_scope"} and isinstance(value, dict):
            existing = merged.get(key)
            merged[key] = {
                **(existing if isinstance(existing, dict) else {}),
                **value,
            }
            continue
        merged[key] = value
    return merged


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


def render_skill_markdown(skill: SkillCard) -> str:
    """Render one skill to an Obsidian-friendly Markdown note."""
    lines = [
        "---",
        f"skill_id: {skill.skill_id}",
        f"version: {skill.version}",
        f"task_family: {skill.task_family}",
        f"objective: {skill.objective}",
        "---",
        f"# {skill.skill_id}",
        "",
        "## Organization Policy",
        "",
        "```json",
        json.dumps(skill.organization_policy, indent=2, sort_keys=True),
        "```",
        "",
        "## Expected Tradeoff",
        "",
        "```json",
        json.dumps(skill.expected_tradeoff, indent=2, sort_keys=True),
        "```",
        "",
        "## Expected Dynamics",
        "",
        "```json",
        json.dumps(skill.expected_dynamics, indent=2, sort_keys=True),
        "```",
        "",
        "## Evidence Refs",
        "",
        "```json",
        json.dumps(skill.evidence_refs, indent=2, sort_keys=True),
        "```",
        "",
        "## Evidence",
        "",
        "```json",
        json.dumps(skill.evidence, indent=2, sort_keys=True),
        "```",
        "",
        "## Risk Notes",
        "",
        "```json",
        json.dumps(skill.risk_notes, indent=2, sort_keys=True),
        "```",
        "",
        "## Fallback",
        "",
        "```json",
        json.dumps(skill.fallback, indent=2, sort_keys=True),
        "```",
    ]
    if skill.counterexamples:
        lines.extend(
            [
                "",
                "## Counterexamples",
                "",
                "```json",
                json.dumps(skill.counterexamples, indent=2, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def render_skill_bank_markdown(bank: SkillBank, output_dir: Path | str) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    for skill in bank:
        (path / f"{skill.skill_id}.md").write_text(
            render_skill_markdown(skill),
            encoding="utf-8",
        )
