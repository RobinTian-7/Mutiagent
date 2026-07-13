"""SkillBank storage, retrieval, lifecycle, and Markdown rendering."""

# ============================================================
# 【模块导读】技能库(SkillBank)的存储、检索、生命周期与 Markdown 渲染。
# - 检索：按任务族/目标/触发条件过滤，带最少种子数门槛与拓扑等价去重；
#   另有避雷/反例技能的专门检索(retrieve_avoid)作为风险约束；
# - 生命周期：补丁应用(增/并/弃)、压缩与归档、版本号递增；
# - 序列化：技能卡以 JSON 子集 YAML 落盘，另可渲染成 Obsidian Markdown。
# ============================================================
from __future__ import annotations

import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from exp_graph.mas.schemas import ModeSkillPayload, PlannerRequest, SkillCard, SkillPatch
from exp_graph.mas.skill_payloads import (
    compatibility_policy_from_payload,
    merge_mode_payload,
    mode_payload_from_skill,
    payload_revision,
    planner_mode_from_skill,
    python_worker_contract_from_skill,
    skill_type_for_payload,
    with_inferred_payload,
)
from exp_graph.mas.topology_equivalence import (
    fingerprint_protocol_spec,
    topology_hash_from_skill,
)
from exp_graph.protocols import ProtocolGraphSpec


_MODE_PAYLOAD_ADAPTER = TypeAdapter(ModeSkillPayload)


# 【职责】基于文件系统的版本化 MAS 技能库(内存中为 skill_id -> 技能卡字典)。
class SkillBank:
    """Filesystem-backed versioned MAS skill bank."""

    def __init__(self, skills: list[SkillCard] | None = None) -> None:
        normalized = [with_inferred_payload(skill) for skill in (skills or [])]
        self.skills: dict[str, SkillCard] = {
            skill.skill_id: skill for skill in normalized
        }

    def __iter__(self):
        return iter(self.skills.values())

    def __len__(self) -> int:
        return len(self.skills)

    def get(self, skill_id: str) -> SkillCard | None:
        return self.skills.get(skill_id)

    # 【职责】从目录加载全部 *.yaml 技能文件；目录不存在返回空库。
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

    # 【职责】把全部技能按 skill_id 排序写回目录(每个技能一个 .yaml)。
    def save_dir(self, directory: Path | str) -> None:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        for skill in sorted(self.skills.values(), key=lambda item: item.skill_id):
            dump_skill_file(skill, path / f"{skill.skill_id}.yaml")

    # 【职责】检索匹配请求的可选技能(任务族/目标/agent 数/数组规模/拓扑白名单逐项过滤)。
    # - min_seeds 为不确定性感知的最小样本门槛：证据/种子样本数低于门槛的技能被排除；
    #   为 None 时读 request.objective.min_seeds(缺省 1)；min_seeds<=1 不排除任何技能，
    #   默认路径与现状检索逐字节一致；
    # - 目标匹配允许 balanced 兜底；结果按检索排序键排序后做拓扑等价去重。
    def retrieve(
        self,
        request: PlannerRequest,
        *,
        min_seeds: int | None = None,
    ) -> list[SkillCard]:
        """Return skills matching task, objective, n_agents, and topology allowlist.

        ``min_seeds`` excludes skills whose evidence/seed sample count is below
        the threshold (an uncertainty-aware min-sample gate). When ``None`` the
        gate is read from ``request.objective.min_seeds`` if present, else ``1``.
        With ``min_seeds <= 1`` no skill is excluded, so the default path is
        byte-identical to today's retrieval.
        """
        if min_seeds is None:
            min_seeds = int(getattr(request.objective, "min_seeds", 1))
        matches: list[SkillCard] = []
        for skill in self.skills.values():
            if not is_selectable_skill(skill, min_seeds=min_seeds):
                continue
            if skill.task_family != request.task_family:
                continue
            if skill.objective not in {request.objective.name, "balanced"}:
                continue
            if not _matches_information_goal(skill, request):
                continue
            if not _matches_provenance(skill, request):
                continue
            if not _matches_planner_mode(skill, request):
                continue
            if not _matches_python_worker_contract(skill, request):
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
        return _dedupe_retrieved_skills(matches)

    # 【职责】检索匹配的避雷/反例技能，作为风险约束返回(不参与直接选择)。
    # - 只收活跃的避雷技能，其余过滤条件(任务族/目标/agent 数/数组规模)与 retrieve 一致。
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
            if not _matches_information_goal(skill, request):
                continue
            if not _matches_provenance(skill, request):
                continue
            if not _matches_planner_mode(skill, request):
                continue
            if not _matches_python_worker_contract(skill, request):
                continue
            if not self._matches_agent_range(skill, request.n_agents):
                continue
            if not self._matches_array_size(skill, request.array_size):
                continue
            matches.append(skill)
        matches.sort(key=lambda skill: self._retrieval_sort_key(skill, request))
        return _dedupe_retrieved_skills(matches)

    def retrieve_generation_context(
        self,
        request: PlannerRequest,
    ) -> list[SkillCard]:
        """Return hot-start cards that may inform, but never seed, generation.

        Dynamic transports such as SILO p2p/broadcast/SFS cannot be replayed as
        a static ``ProtocolGraphSpec``.  Hot-start training still benefits from
        their measured tradeoffs and reasoning rules, so an explicitly opted-in
        generation request may expose them as prompt context.  This path ignores
        planner-mode/provenance compatibility by design, while retaining task,
        goal, objective, and size isolation.
        """
        if not bool(getattr(request, "include_reference_skills", False)):
            return []
        matches: list[SkillCard] = []
        for skill in self.skills.values():
            tags = {tag.lower() for tag in skill.tags}
            if "hot-start" not in tags:
                continue
            if not _is_active_skill(skill) or is_avoid_skill(skill):
                continue
            if skill.task_family != request.task_family:
                continue
            if skill.objective not in {request.objective.name, "balanced"}:
                continue
            if not _matches_information_goal(skill, request):
                continue
            if not _matches_python_worker_contract(skill, request):
                continue
            if not self._matches_agent_range(skill, request.n_agents):
                continue
            if not self._matches_array_size(skill, request.array_size):
                continue
            matches.append(skill)
        matches.sort(key=lambda skill: self._retrieval_sort_key(skill, request))
        return _dedupe_retrieved_skills(matches)

    # 【职责】应用一条 AutoSkill 风格的生命周期补丁，返回结果动作名。
    # - discard 直接丢弃；deprecate 为目标技能的证据打弃用标记并加 deprecated 标签；
    # - add 需要 candidate_skill；merge 无目标技能时退化为 add，否则并入既有技能。
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

    # 【职责】批量应用补丁并统计各动作计数(deprecated 为 0 时从结果省略)。
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

    # 【职责】按触发条件的 min/max_agents 区间与 agent_counts 白名单判断 agent 数是否适用。
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

    # 【职责】按触发条件的数组规模区间/白名单判断适用性；请求未提供时视为匹配。
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

    # 【职责】检索排序键：条件特异性降序 -> 检索损失升序 -> 证据数降序 -> skill_id。
    @staticmethod
    def _retrieval_sort_key(
        skill: SkillCard,
        request: PlannerRequest,
    ) -> tuple[int, float, int, str]:
        return (
            -_condition_specificity(skill, request),
            _skill_retrieval_loss(skill),
            -_skill_evidence_count(skill),
            skill.skill_id,
        )


# 【职责】按信息目标匹配技能：sink 卡只服务 sink 请求，all_agents 卡只服务 all_agents。
# - 卡片的目标先看 trigger.information_goal，再看顶层 information_goal 字段；
#   两者都缺的旧卡视为 legacy sink 卡（只匹配 sink 请求，绝不会进入 all_agents）。
def _matches_information_goal(skill: SkillCard, request) -> bool:
    goal = skill.trigger.get("information_goal") or skill.information_goal or "sink"
    return str(goal) == str(getattr(request, "information_goal", "sink") or "sink")


# 【职责】按 provenance 白名单过滤（clean GraphGen 隔离核心）。
# - request.provenance_allowlist 为 None：不过滤（legacy 行为逐字节一致）；
# - 设置后：缺 provenance 的旧卡视为 contaminated 一律排除，具名 fixed 证据不可见。
def _matches_provenance(skill: SkillCard, request) -> bool:
    allowlist = getattr(request, "provenance_allowlist", None)
    if not allowlist:
        return True
    return skill.provenance is not None and str(skill.provenance) in set(allowlist)


# 【职责】按 PythonGen Worker 合约隔离检索：message_only_v1 请求只能看到同合约的
#   Python 卡；缺字段的旧 Python 卡按 action_json_v1 归类。非 Python 卡/非
#   python_generate 请求不受影响(与现状逐字节一致)。
def _matches_python_worker_contract(skill: SkillCard, request) -> bool:
    """Keep the two PythonGen worker-contract archives strictly separate."""
    is_python_card = (
        planner_mode_from_skill(skill) == "python_generate"
        or skill.skill_type == "python_generation_skill"
    )
    if not is_python_card:
        return True
    requested = str(
        getattr(request, "python_worker_contract", "action_json_v1")
        or "action_json_v1"
    )
    return python_worker_contract_from_skill(skill) == requested


def _matches_planner_mode(skill: SkillCard, request) -> bool:
    """Keep free GraphGen and restricted-program skills in separate archives."""
    requested = str(getattr(request, "planner_mode", "topology_select"))
    if requested not in {
        "graph_generate",
        "program_generate",
        "python_generate",
    }:
        return True
    declared = planner_mode_from_skill(skill)
    if skill.mode_payload is not None:
        if requested == "graph_generate":
            if declared == "graph_generate":
                return True
            return bool(
                declared == "topology_select"
                and not getattr(request, "provenance_allowlist", None)
            )
        return declared == requested
    if declared in {
        "graph_generate",
        "program_generate",
        "python_generate",
    }:
        return str(declared) == requested
    spec_data = skill.organization_policy.get("protocol_spec")
    metadata: dict = {}
    if isinstance(spec_data, dict) and isinstance(spec_data.get("metadata"), dict):
        metadata = spec_data["metadata"]
    is_program = bool(
        metadata.get("program_mode") == "program_generate"
        or isinstance(metadata.get("phase_program"), dict)
    )
    is_python = bool(
        skill.provenance == "llm_generated_python"
        or skill.organization_policy.get("planner_mode") == "python_generate"
        or isinstance(skill.organization_policy.get("source_code"), str)
    )
    if (
        requested == "graph_generate"
        and not getattr(request, "provenance_allowlist", None)
        and not is_program
        and not is_python
    ):
        # Legacy and select_then_refine graph paths deliberately admit named or
        # source-less anchors. Clean GraphGen always supplies an allowlist.
        return True
    if requested == "program_generate":
        return (skill.provenance == "program_generated" or is_program) and not is_python
    if requested == "python_generate":
        return is_python and skill.provenance in {
            "llm_generated_python",
            "skill_replay",
        }
    if is_program or is_python or skill.provenance in {
        "program_generated",
        "llm_generated_python",
    }:
        return False
    if metadata.get("generated_graph"):
        return True
    return skill.provenance in {"llm_generated", "skill_replay"}


# 【职责】判断技能是否可被皇帝(规划 LLM)直接选用(活跃且非避雷技能)。
# - min_seeds 提供可选的不确定性感知最小样本门槛：独立观测数不足者排除；
# - 默认 min_seeds=1 放行所有技能(现状行为)，既有调用点均不受影响。
def is_selectable_skill(skill: SkillCard, *, min_seeds: int = 1) -> bool:
    """Return whether a skill is safe for the emperor to choose directly.

    ``min_seeds`` adds an optional uncertainty-aware min-sample gate: skills
    backed by fewer than ``min_seeds`` independent observations are excluded.
    The default ``min_seeds=1`` admits every skill (current behavior), so all
    existing call sites are unaffected.
    """
    tags = {tag.lower() for tag in skill.tags}
    if "reference-only" in tags:
        return False
    declared_mode = planner_mode_from_skill(skill)
    if declared_mode in {"graph_generate", "program_generate", "python_generate"}:
        payload = mode_payload_from_skill(skill)
        required_format = {
            "graph_generate": "graph_skill_v1",
            "program_generate": "phase_program_skill_v1",
            "python_generate": "python_skill_v1",
        }[declared_mode]
        if payload is None or payload.format != required_format:
            return False
    if not (_is_active_skill(skill) and not is_avoid_skill(skill)):
        return False
    if min_seeds > 1 and _skill_sample_count(skill) < min_seeds:
        return False
    return True


# 【职责】判断技能是否只应作为负面约束使用(避雷/反例技能)。
# - 依据：带 counterexample 标签，或 skill_id 以 cf_avoid_ 开头。
def is_avoid_skill(skill: SkillCard) -> bool:
    """Return whether a skill should be used only as a negative constraint."""
    tags = {tag.lower() for tag in skill.tags}
    return "counterexample" in tags or skill.skill_id.startswith("cf_avoid_")


# 【职责】判断技能是否活跃(未带 archived/deprecated 标签)。
def _is_active_skill(skill: SkillCard) -> bool:
    tags = {tag.lower() for tag in skill.tags}
    blocked_tags = {"archived", "deprecated"}
    return not (tags & blocked_tags)


# 【职责】压缩技能库：每个条件桶只保留 RMSE 最低的前 N 个可选技能，其余归档。
# - 活跃避雷技能单独保留并做拓扑等价去重；不可选技能直接归档；
# - 返回(活跃库, 归档库, 摘要)，摘要含各桶保留/归档与等价重复分组信息。
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

    active_avoid, archived_avoid_duplicates, avoid_duplicate_groups = (
        _dedupe_equivalent_skills(active_avoid)
    )
    archived.extend(archived_avoid_duplicates)

    active: list[SkillCard] = []
    bucket_summaries: dict[str, dict[str, object]] = {}
    duplicate_groups_by_bucket: dict[str, list[dict[str, object]]] = {}
    for bucket, skills in sorted(grouped.items()):
        unique_skills, duplicate_archived, duplicate_groups = _dedupe_equivalent_skills(
            skills
        )
        archived.extend(duplicate_archived)
        duplicate_groups_by_bucket[bucket] = duplicate_groups
        ranked = sorted(
            unique_skills,
            key=_skill_compaction_sort_key,
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
            "duplicate_equivalent_topology_groups": duplicate_groups,
        }

    summary = {
        "max_per_condition": limit,
        "active_count": len(active) + len(active_avoid),
        "active_avoid_count": len(active_avoid),
        "archived_count": len(archived),
        "condition_buckets": bucket_summaries,
        "avoid_duplicate_equivalent_topology_groups": avoid_duplicate_groups,
        "duplicate_equivalent_topology_groups": duplicate_groups_by_bucket,
    }
    return SkillBank([*active, *active_avoid]), SkillBank(archived), summary


# 【职责】压缩技能目录：加载 -> 压缩 -> 分写活跃/归档目录并落盘压缩摘要 JSON。
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


# 【职责】按拓扑等价键对检索结果保序去重(保留排序后首个)。
def _dedupe_retrieved_skills(skills: list[SkillCard]) -> list[SkillCard]:
    result: list[SkillCard] = []
    seen: set[str] = set()
    for skill in skills:
        key = _skill_equivalence_key(skill)
        if key in seen:
            continue
        seen.add(key)
        result.append(skill)
    return result


# 【职责】按拓扑等价键分组：每组保留压缩排序最优者并并入其余证据，重复者归档。
# - 返回(保留列表, 归档列表, 重复分组说明)。
def _dedupe_equivalent_skills(
    skills: list[SkillCard],
) -> tuple[list[SkillCard], list[SkillCard], list[dict[str, object]]]:
    grouped: dict[str, list[SkillCard]] = {}
    for skill in skills:
        grouped.setdefault(_skill_equivalence_key(skill), []).append(skill)

    kept: list[SkillCard] = []
    archived: list[SkillCard] = []
    duplicate_groups: list[dict[str, object]] = []
    for key, group in sorted(grouped.items()):
        if len(group) == 1:
            kept.append(_annotate_skill_topology_hash(group[0]))
            continue
        representative = min(group, key=_skill_compaction_sort_key)
        merged = _merge_equivalent_topology_skills(representative, group)
        kept.append(merged)
        duplicates = [skill for skill in group if skill.skill_id != representative.skill_id]
        archived.extend(
            _archive_skill(
                skill,
                f"duplicate_equivalent_topology_of:{representative.skill_id}",
            )
            for skill in duplicates
        )
        duplicate_groups.append(
            {
                "topology_equivalence_hash": key,
                "kept": representative.skill_id,
                "merged": [skill.skill_id for skill in duplicates],
            }
        )
    return kept, archived, duplicate_groups


# 【职责】把一组拓扑等价技能并入代表技能：合并别名/证据/风险等并记录等价哈希。
def _merge_equivalent_topology_skills(
    representative: SkillCard,
    group: list[SkillCard],
) -> SkillCard:
    aliases = _dedupe(
        [
            str(alias)
            for skill in group
            for alias in _skill_topology_aliases(skill)
            if alias
        ]
    )
    merged_ids = _dedupe([skill.skill_id for skill in group])
    policy = dict(representative.organization_policy)
    topology_hash = topology_hash_from_skill(representative)
    if topology_hash:
        policy["topology_equivalence_hash"] = topology_hash
    canonical = _canonical_edges_from_skill(representative)
    if canonical:
        policy["canonical_temporal_edges"] = canonical
    policy["topology_aliases"] = aliases
    policy["merged_skill_ids"] = merged_ids
    policy["duplicate_topology_count"] = max(0, len(group) - 1)

    expected_dynamics = dict(representative.expected_dynamics)
    expected_dynamics["merged_skill_ids"] = merged_ids
    expected_dynamics["topology_aliases"] = aliases
    if topology_hash:
        expected_dynamics["topology_equivalence_hash"] = topology_hash

    return representative.model_copy(
        update={
            "organization_policy": policy,
            "expected_dynamics": expected_dynamics,
            "evidence": _dedupe_dicts(
                [item for skill in group for item in skill.evidence]
            ),
            "evidence_refs": _dedupe(
                [ref for skill in group for ref in skill.evidence_refs]
            ),
            "risk_notes": _dedupe_dicts(
                [item for skill in group for item in skill.risk_notes]
            ),
            "failure_modes": _dedupe_dicts(
                [item for skill in group for item in skill.failure_modes]
            ),
            "counterexamples": _dedupe_dicts(
                [item for skill in group for item in skill.counterexamples]
            ),
            "hypotheses": _dedupe_dicts(
                [item for skill in group for item in skill.hypotheses]
            ),
            "revision_history": _dedupe_dicts(
                [item for skill in group for item in skill.revision_history]
            ),
        }
    )


# 【职责】给技能补写拓扑等价哈希与规范时序边(已有则不覆盖)。
def _annotate_skill_topology_hash(skill: SkillCard) -> SkillCard:
    topology_hash = topology_hash_from_skill(skill)
    if not topology_hash:
        return skill
    policy = dict(skill.organization_policy)
    policy.setdefault("topology_equivalence_hash", topology_hash)
    canonical = _canonical_edges_from_skill(skill)
    if canonical:
        policy.setdefault("canonical_temporal_edges", canonical)
    return skill.model_copy(update={"organization_policy": policy})


# 【职责】技能等价键：有拓扑哈希用 "topology:<hash>"，否则退回 "skill:<id>"。
def _skill_equivalence_key(skill: SkillCard) -> str:
    # 中文：等价键带 information_goal 前缀——sink 与 all_agents 的卡即使结构等价
    #   也绝不允许在压缩/去重时互相合并。
    # The equivalence key is prefixed by information_goal: sink and all_agents
    # cards must never merge during compaction even when structurally equal.
    goal = skill.trigger.get("information_goal") or skill.information_goal or "sink"
    topology_hash = topology_hash_from_skill(skill)
    if topology_hash:
        return f"{goal}::topology:{topology_hash}"
    return f"{goal}::skill:{skill.skill_id}"


# 【职责】压缩排序键：平均损失升序 -> 证据数降序 -> skill_id。
def _skill_compaction_sort_key(skill: SkillCard) -> tuple[float, int, str]:
    return (
        _skill_mean_rmse(skill),
        -_skill_evidence_count(skill),
        skill.skill_id,
    )


# 【职责】收集技能的拓扑别名(自身拓扑名 + 策略中已有 topology_aliases)。
def _skill_topology_aliases(skill: SkillCard) -> list[str]:
    policy = skill.organization_policy
    aliases = []
    if skill.topology_name:
        aliases.append(skill.topology_name)
    existing = policy.get("topology_aliases")
    if isinstance(existing, list):
        aliases.extend(str(item) for item in existing)
    return aliases


# 【职责】取规范时序边：优先策略里已存的，否则由 protocol_spec 计算结构指纹得到。
def _canonical_edges_from_skill(skill: SkillCard) -> list[list[int]]:
    policy = skill.organization_policy
    existing = policy.get("canonical_temporal_edges")
    if isinstance(existing, list):
        return [
            [int(edge[0]), int(edge[1]), int(edge[2])]
            for edge in existing
            if isinstance(edge, (list, tuple)) and len(edge) == 3
        ]
    spec_data = policy.get("protocol_spec")
    if not isinstance(spec_data, dict):
        return []
    try:
        spec = ProtocolGraphSpec.model_validate(spec_data)
    except Exception:
        return []
    return [
        list(edge)
        for edge in fingerprint_protocol_spec(spec).canonical_temporal_edges
    ]


# 【职责】计算技能触发条件对请求的特异性得分(越具体越优先检索)。
# - condition_key +8；agent 数精确命中 +4、仅有区间 +2；数组规模同理。
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


# 中文：通用(携带主损失)技能检索排序的悲观项：只测过一次、损失为 0 的技能排为
#   0 + kappa/1 = 0.5；16 行老将在损失 0.25 时排为 0.25 + 0.125 = 0.375 ——
#   老将先被检索。Phase-3 开发第 1 轮：一个 1 行"幸运"探索组织在纯均值排序中
#   挤掉了已验证冠军，该用例的留出集得分下降 25 个百分点。
# Pessimism for retrieval ordering of GENERIC (loss-carrying) skills: a skill
# measured once at loss 0 ranks as 0 + kappa/1 = 0.5, a 16-row veteran at loss
# 0.25 ranks as 0.25 + 0.125 = 0.375 -- the veteran retrieves first. Phase-3
# dev round 1: a 1-row lucky explore organization displaced the proven
# champion in raw-mean order and the held-out score dropped 25pp on that case.
RETRIEVAL_LCB_KAPPA = 0.5
# 中文：M19a(dev-11)：种子并非独立证据——一个只覆盖单一 CASE 的 2 行满分技能
#   (LCB 0.354)压过了覆盖 7 个 case 的通才，劫持了赢家通吃的回放。
#   为不同 case 的多样性单设悲观项；没有该标记的卡(全部 CF 卡)逐字节一致。
# M19a (dev-11): seeds are not independent evidence -- a 2-row single-CASE
# perfect score (LCB 0.354) outranked a 7-case generalist and hijacked
# winner-take-all replay. Distinct-case diversity gets its own pessimism
# term; cards without the stamp (all CF cards) are byte-identical.
RETRIEVAL_CASE_KAPPA = 0.25


# 【职责】检索排名损失：对携带主损失的技能加 LCB 悲观项与 case 多样性悲观项。
# - CF 技能从不携带 mean_primary_loss，落回 _skill_mean_rmse，
#   其历史"按原始 RMSE 升序"的检索顺序逐字节不变。
def _skill_retrieval_loss(skill: SkillCard) -> float:
    """Retrieval-ranking loss: LCB-adjusted for loss-carrying skills.

    CF skills never carry ``mean_primary_loss``, so they fall through to
    ``_skill_mean_rmse`` and their historical raw-RMSE-ascending retrieval
    order stays byte-identical.
    """
    loss = skill.expected_tradeoff.get("mean_primary_loss")
    if loss is None:
        return _skill_mean_rmse(skill)
    try:
        loss_f = float(loss)
    except (TypeError, ValueError):
        return _skill_mean_rmse(skill)
    n = max(1, _skill_sample_count(skill))
    ranked = loss_f + RETRIEVAL_LCB_KAPPA / math.sqrt(n)
    cases = skill.expected_tradeoff.get("evidence_case_count")
    if cases is not None:
        try:
            ranked += RETRIEVAL_CASE_KAPPA / max(1.0, float(cases))
        except (TypeError, ValueError):
            pass
    return ranked


# 【职责】读排名用的平均损失：优先 mean_primary_loss，否则 mean_rmse(缺失为 +inf)。
def _skill_mean_rmse(skill: SkillCard) -> float:
    # 中文：通用基准技能把主指标桥接进 mean_rmse(可能越高越好，如成功率)，同时
    #   携带统一的越低越好 mean_primary_loss。存在损失键时按损失排名——按原始
    #   成功率升序排序曾返回"最差优先"的检索(P2 confirmatory-1 根因：一个训练
    #   损失 1.0 的设计在留出条件上被 20/20 次回放)。CF 技能从不携带损失键，
    #   其历史按原始 RMSE 升序的顺序逐字节一致。
    # Generic-benchmark skills bridge their primary metric into ``mean_rmse``
    # (which may be HIGHER-is-better, e.g. a success rate) and carry the
    # uniform lower-is-better ``mean_primary_loss`` alongside. Rank by the
    # loss when present -- sorting raw success ascending returned WORST-first
    # retrieval (P2 confirmatory-1 root cause: a train-loss-1.0 design was
    # replayed 20/20 on held-out conditions). CF skills never carry the loss
    # key, so their historical raw-RMSE-ascending order is byte-identical.
    loss = skill.expected_tradeoff.get("mean_primary_loss")
    if loss is not None:
        try:
            return float(loss)
        except (TypeError, ValueError):
            pass
    value = skill.expected_tradeoff.get("mean_rmse")
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


# 【职责】读证据条数：优先 expected_tradeoff.active_evidence_count，否则引用+内嵌合计。
def _skill_evidence_count(skill: SkillCard) -> int:
    value = skill.expected_tradeoff.get("active_evidence_count")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return len(skill.evidence_refs) + len(skill.evidence)


# 【职责】最小样本检索门槛所用的独立观测数。
# - 委托 exp_graph.mas.scoring.evidence_sample_count，保证这里的 n 与 LCB 精度
#   惩罚使用的一致(seed_count -> active_evidence_count -> 原始证据条数)。
def _skill_sample_count(skill: SkillCard) -> int:
    """Independent-observation count used for the min-sample retrieval gate.

    Delegates to :func:`exp_graph.mas.scoring.evidence_sample_count` so the
    ``n`` here matches the one the LCB accuracy penalty uses (seed_count, then
    active_evidence_count, then raw evidence length).
    """
    from exp_graph.mas.scoring import evidence_sample_count

    return evidence_sample_count(skill, default=1)


# 【职责】技能的条件桶键(任务族/目标/agent 桶/数组规模桶的 JSON)，用于压缩分组。
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


# 【职责】把触发条件的 min/max 区间规整成桶名(区间两端相等取单值，缺省为 any)。
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


# 【职责】打 archived 标签并在 expected_dynamics 记录归档原因。
def _archive_skill(skill: SkillCard, reason: str) -> SkillCard:
    tags = _dedupe([*skill.tags, "archived"])
    dynamics = dict(skill.expected_dynamics)
    dynamics["archive_reason"] = reason
    return skill.model_copy(update={"tags": tags, "expected_dynamics": dynamics})


# 【职责】把候选补丁并入既有技能身份：追加证据/风险/反例等并递增补丁位版本号。
# - merge 且带 lesson 时把教训同时写入证据与风险注记；
# - candidate 存在时其组织策略/预期权衡/回退/动力学/置信按键合并覆盖；
# - patch.update 中的列表字段规整追加、字典字段浅合并。
def merge_skill(skill: SkillCard, patch: SkillPatch) -> SkillCard:
    """Merge a candidate patch into an existing skill identity."""
    candidate = patch.candidate_skill
    evidence = [*skill.evidence, *patch.evidence]
    evidence_refs = _dedupe([*skill.evidence_refs, *patch.evidence_refs])
    design_insights = list(skill.design_insights)
    counterexamples = list(skill.counterexamples)
    risk_notes = list(skill.risk_notes)
    failure_modes = list(skill.failure_modes)
    hypotheses = list(skill.hypotheses)
    validation_plan = list(skill.validation_plan)
    trigger = dict(skill.trigger)
    reasoning_policy = dict(skill.reasoning_policy)
    expected_tradeoff = dict(skill.expected_tradeoff)
    fallback = dict(skill.fallback)
    expected_dynamics = dict(skill.expected_dynamics)
    confidence = dict(skill.confidence)
    organization_policy = dict(skill.organization_policy)
    tags = list(skill.tags)
    update_rule = skill.update_rule
    current_mode_payload = mode_payload_from_skill(skill)
    mode_payload = current_mode_payload
    if candidate is not None:
        if (
            skill.information_goal is not None
            and candidate.information_goal is not None
            and skill.information_goal != candidate.information_goal
        ):
            raise ValueError("cannot merge skills from different information goals")
        evidence.extend(candidate.evidence)
        evidence_refs = _dedupe([*evidence_refs, *candidate.evidence_refs])
        counterexamples.extend(candidate.counterexamples)
        risk_notes.extend(candidate.risk_notes)
        failure_modes.extend(candidate.failure_modes)
        hypotheses.extend(candidate.hypotheses)
        validation_plan.extend(candidate.validation_plan)
        design_insights.extend(candidate.design_insights)
        trigger = _merge_nested_mapping(trigger, candidate.trigger)
        organization_policy = _merge_policy(
            organization_policy,
            candidate.organization_policy,
        )
        reasoning_policy = _merge_nested_mapping(
            reasoning_policy,
            candidate.reasoning_policy,
        )
        expected_tradeoff = _merge_nested_mapping(
            expected_tradeoff,
            candidate.expected_tradeoff,
        )
        fallback = _merge_nested_mapping(fallback, candidate.fallback)
        expected_dynamics = _merge_nested_mapping(
            expected_dynamics,
            candidate.expected_dynamics,
        )
        confidence = _merge_nested_mapping(confidence, candidate.confidence)
        tags = _dedupe([*tags, *candidate.tags])
        if candidate.update_rule:
            update_rule = candidate.update_rule
        candidate_payload = mode_payload_from_skill(candidate)
        mode_payload = merge_mode_payload(mode_payload, candidate_payload)
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
    _extend_dict_items(counterexamples, update_data.get("counterexamples"))
    _extend_dict_items(risk_notes, update_data.get("risk_notes"))
    _extend_dict_items(failure_modes, update_data.get("failure_modes"))
    _extend_dict_items(hypotheses, update_data.get("hypotheses"))
    _extend_dict_items(validation_plan, update_data.get("validation_plan"))
    _extend_dict_items(design_insights, update_data.get("design_insights"))
    for key, current in (
        ("trigger", trigger),
        ("reasoning_policy", reasoning_policy),
        ("expected_tradeoff", expected_tradeoff),
        ("fallback", fallback),
        ("expected_dynamics", expected_dynamics),
        ("confidence", confidence),
    ):
        incoming = update_data.get(key)
        if isinstance(incoming, dict):
            merged = _merge_nested_mapping(current, incoming)
            if key == "trigger":
                trigger = merged
            elif key == "reasoning_policy":
                reasoning_policy = merged
            elif key == "expected_tradeoff":
                expected_tradeoff = merged
            elif key == "fallback":
                fallback = merged
            elif key == "expected_dynamics":
                expected_dynamics = merged
            else:
                confidence = merged
    incoming_policy = update_data.get("organization_policy")
    if isinstance(incoming_policy, dict):
        organization_policy = _merge_policy(organization_policy, incoming_policy)
    incoming_payload = update_data.get("mode_payload")
    if isinstance(incoming_payload, dict):
        mode_payload = merge_mode_payload(
            mode_payload,
            _MODE_PAYLOAD_ADAPTER.validate_python(incoming_payload),
        )
    incoming_tags = update_data.get("tags")
    if isinstance(incoming_tags, list):
        tags = _dedupe([*tags, *[str(item) for item in incoming_tags]])
    if isinstance(update_data.get("update_rule"), str):
        update_rule = str(update_data["update_rule"])
    organization_policy = compatibility_policy_from_payload(
        organization_policy,
        mode_payload,
    )

    update = {
        "skill_type": (
            skill_type_for_payload(mode_payload)
            if skill.skill_type == "planner_organization_policy"
            else skill.skill_type
        ),
        "evidence": _dedupe_dicts(evidence),
        "evidence_refs": evidence_refs,
        "design_insights": _dedupe_design_insights(design_insights),
        "counterexamples": _dedupe_dicts(counterexamples),
        "risk_notes": _dedupe_dicts(risk_notes),
        "failure_modes": _dedupe_dicts(failure_modes),
        "hypotheses": _dedupe_dicts(hypotheses),
        "validation_plan": _dedupe_dicts(validation_plan),
        "trigger": trigger,
        "mode_payload": mode_payload,
        "organization_policy": organization_policy,
        "reasoning_policy": reasoning_policy,
        "expected_tradeoff": expected_tradeoff,
        "fallback": fallback,
        "expected_dynamics": expected_dynamics,
        "confidence": confidence,
        "tags": tags,
        "update_rule": update_rule,
    }
    changed_fields = sorted(
        key for key, value in update.items() if getattr(skill, key) != value
    )
    executable_revision = payload_revision(current_mode_payload, mode_payload)
    revision = {
        "patch_ids": [patch.patch_id],
        "changed_fields": changed_fields,
        "summary": patch.lesson,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    if executable_revision is not None:
        revision["mode_payload_revision"] = executable_revision
    update["revision_history"] = [*skill.revision_history, revision]
    update["version"] = (
        bump_minor_version(skill.version)
        if {"mode_payload", "reasoning_policy", "trigger"} & set(changed_fields)
        else bump_patch_version(skill.version)
    )
    return skill.model_copy(update=update)


# 【职责】递增语义化版本号的补丁位(不足三段先补零)。
def bump_patch_version(version: str) -> str:
    parts = [int(part) for part in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    parts[-1] += 1
    return ".".join(str(part) for part in parts[:3])


def bump_minor_version(version: str) -> str:
    """Increment the semantic minor version for executable/semantic changes."""
    parts = [int(part) for part in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    parts[1] += 1
    parts[2] = 0
    return ".".join(str(part) for part in parts[:3])


# 【职责】加载技能文件：先按 JSON 解析(JSON 是 YAML 兼容子集)，失败再用 PyYAML。
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
    return with_inferred_payload(SkillCard.model_validate(data))


# 【职责】把技能写成 JSON 子集 YAML(键排序、缩进 2)，运行时无需 YAML 依赖。
def dump_skill_file(skill: SkillCard, path: Path | str) -> None:
    """Write skill as JSON-subset YAML so no runtime YAML dependency is required."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(skill.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# 【职责】字符串列表保序去重。
def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


# 【职责】把任意值规整为字典追加进目标列表(非字典包成 {"summary": ...})。
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


def _merge_nested_mapping(
    current: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Recursively update one learned policy without dropping sibling fields."""
    merged = dict(current)
    for key, value in incoming.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_nested_mapping(existing, value)
            continue
        if isinstance(existing, list) and isinstance(value, list):
            items = [*existing, *value]
            unique: list[object] = []
            for item in items:
                if item not in unique:
                    unique.append(item)
            merged[key] = unique
            continue
        merged[key] = value
    return merged


# 【职责】合并组织策略字典。
# - operation_recommendations/operator_constraints 列表去重合并；rationale_rules 去重；
# - structure_features/condition_scope 字典浅合并；其余键由传入方直接覆盖。
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


# 【职责】按 JSON 序列化结果对字典列表保序去重。
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


# 【职责】设计洞见去重：有 insight_id 按 ID，否则按 JSON 负载。
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


# 【职责】把单个技能渲染为 Obsidian 友好的 Markdown 笔记(front-matter + 各节 JSON)。
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
        "## Mode Payload",
        "",
        "```json",
        json.dumps(
            skill.mode_payload.model_dump(mode="json")
            if skill.mode_payload is not None
            else None,
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Organization Policy",
        "",
        "```json",
        json.dumps(skill.organization_policy, indent=2, sort_keys=True),
        "```",
        "",
        "## Reasoning Policy",
        "",
        "```json",
        json.dumps(skill.reasoning_policy, indent=2, sort_keys=True),
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
        "## Design Insights",
        "",
        "```json",
        json.dumps(skill.design_insights, indent=2, sort_keys=True),
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


# 【职责】把整个技能库逐技能渲染成 Markdown 文件写入目录。
def render_skill_bank_markdown(bank: SkillBank, output_dir: Path | str) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    for skill in bank:
        (path / f"{skill.skill_id}.md").write_text(
            render_skill_markdown(skill),
            encoding="utf-8",
        )
