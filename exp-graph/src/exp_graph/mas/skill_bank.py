"""SkillBank storage, retrieval, lifecycle, and Markdown rendering."""

from __future__ import annotations

import json
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
            matches.append(skill)
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


def is_selectable_skill(skill: SkillCard) -> bool:
    """Return whether a skill is safe for the emperor to choose directly."""
    tags = {tag.lower() for tag in skill.tags}
    return "counterexample" not in tags and not skill.skill_id.startswith("cf_avoid_")


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
        merged_policy.update(candidate.organization_policy)
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
        merged_policy.update(update_data["organization_policy"])
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
