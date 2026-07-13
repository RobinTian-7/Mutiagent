"""Batch consolidation for AutoSkill-style planner skill evolution."""

# ============================================================
# 【模块导读】AutoSkill 风格的规划器技能进化批次固化(合并入库)。
# - consolidate_skill_updates 应用补丁批次；gate=True 时启用留出集验证门：
#   批次先应用到技能库克隆上，前后各测一次留出目标值 J_val(越低越好)，
#   仅当 j_after <= j_before - epsilon(容差) 才提交，拒绝则真实技能库原样不动。
# - _apply_patch_batch/_merge_patch_group 负责补丁分组、幂等去重、字段合并与版本化。
# - _recompute_tradeoff/_recompute_dynamics/_recompute_confidence 由证据重算卡上统计量。
# ============================================================
from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from pydantic import TypeAdapter

from exp_graph.mas.evidence import read_evidence_jsonl
from exp_graph.mas.schemas import (
    EvidenceRecord,
    EvolutionResult,
    ModeSkillPayload,
    SkillCard,
    SkillPatch,
    SkillRevision,
)
from exp_graph.mas.skill_bank import SkillBank, dump_skill_file, load_skill_file
from exp_graph.mas.skill_payloads import (
    compatibility_policy_from_payload,
    merge_mode_payload,
    mode_payload_from_skill,
    payload_revision,
    skill_type_for_payload,
    with_inferred_payload,
)


_MODE_PAYLOAD_ADAPTER = TypeAdapter(ModeSkillPayload)


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# 【职责】读取补丁目录下全部 *.json(兼容列表或 {"patches": [...]} 两种形态)为补丁列表。
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


# 【职责】把补丁列表以排序 JSON 落盘(自动创建父目录)。
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


# 【职责】把一个已验证的补丁批次应用到内存技能库——留出集验证门(gate)的入口。
# - gate=False(默认)：每个补丁无条件应用，逐字节保留既有 count_frequency 进化行为。
# - gate=True 且 validation_rows 非空：执行论文的留出集接受规则——批次先应用到 bank 的克隆上。
# - 前后各测一次留出目标值 J_val(越低越好)，仅当 j_after <= j_before - epsilon(容差) 才提交回真实 bank。
# - epsilon 语义：epsilon=0 即要求 J_val 不退步；epsilon>0 则要求至少改进 epsilon 才接受。
# - 拒绝时真实 bank 原样不动(等效回滚)，结果记录 counts['gated_out']、一条警告与 gate_* 字段。
# - 门一旦运行，j_before/j_after/gate_accepted 一定会被记录。
def consolidate_skill_updates(
    *,
    bank: SkillBank,
    patches: list[SkillPatch],
    evidence_records: list[EvidenceRecord],
    batch_id: str | None = None,
    validation_rows: list[dict[str, object]] | None = None,
    epsilon: float = 0.0,
    gate: bool = False,
) -> tuple[SkillBank, EvolutionResult]:
    """Apply one validated patch batch to a skill bank in memory.

    With ``gate=False`` (the default) every patch is applied unconditionally,
    preserving all existing count-frequency evolution behavior byte-for-byte.

    With ``gate=True`` and non-empty ``validation_rows`` the paper's held-out
    acceptance rule is enforced: the batch is applied to a *clone* of ``bank``,
    the held-out objective ``J_val`` is measured before and after, and the
    patches are committed to the real ``bank`` only if
    ``j_after <= j_before - epsilon``. On rejection the real ``bank`` is left
    untouched and the rejection is recorded on the returned
    :class:`EvolutionResult` (``counts['gated_out']``, a warning, and the
    ``gate_*`` fields). ``j_before``/``j_after``/``gate_accepted`` are always
    recorded when the gate runs.
    """
    batch = batch_id or f"revision_batch_{utc_stamp()}"

    if not (gate and validation_rows):
        return bank, _apply_patch_batch(
            bank=bank,
            patches=patches,
            evidence_records=evidence_records,
            batch=batch,
        )

    from exp_graph.mas.validation import validation_objective

    j_before = validation_objective(bank, validation_rows)
    candidate = _clone_skill_bank(bank)
    candidate_result = _apply_patch_batch(
        bank=candidate,
        patches=patches,
        evidence_records=evidence_records,
        batch=batch,
    )
    j_after = validation_objective(candidate, validation_rows)

    if j_after <= j_before - epsilon:
        # 中文：接受——把克隆库的技能就地提交回真实技能库，
        #   使调用方手中原有的 ``bank`` 引用继续有效。
        # Accept: commit the cloned skills back onto the real bank in place so
        # callers keep their existing ``bank`` reference.
        bank.skills = candidate.skills
        candidate_result.gate_accepted = True
        candidate_result.gate_j_before = j_before
        candidate_result.gate_j_after = j_after
        return bank, candidate_result

    # 中文：拒绝——真实技能库保持不动，并报告拒绝原因。
    # Reject: leave the real bank untouched and report why.
    gated_out = sum(
        count
        for key, count in candidate_result.counts.items()
        if key in {"added", "merged", "deprecated"}
    )
    rejection = EvolutionResult(
        batch_id=batch,
        counts={"gated_out": gated_out} if gated_out else {"gated_out": 0},
        revisions=[],
        warnings=[
            "validation gate rejected patch batch "
            f"(J_val before={j_before:.6f}, after={j_after:.6f}, "
            f"epsilon={epsilon:.6f}); skill bank unchanged"
        ],
        gate_accepted=False,
        gate_j_before=j_before,
        gate_j_after=j_after,
    )
    return bank, rejection


# 【职责】深拷贝技能库：候选补丁只作用于副本，绝不触碰原库。
def _clone_skill_bank(bank: SkillBank) -> SkillBank:
    """Deep-copy a skill bank so candidate patches never touch the original."""
    return SkillBank([skill.model_copy(deep=True) for skill in bank])


# 【职责】无条件路径：把补丁批次就地应用到技能库，返回 EvolutionResult 统计。
# - 目标技能缺失且无候选卡→丢弃并告警；有候选卡→新增(add)并记首条修订。
# - 已应用过的 patch_id 跳过(幂等)；拓扑/触发条件不匹配的补丁丢弃；其余合并并记录修订。
def _apply_patch_batch(
    *,
    bank: SkillBank,
    patches: list[SkillPatch],
    evidence_records: list[EvidenceRecord],
    batch: str,
) -> EvolutionResult:
    """Apply a patch batch to ``bank`` in place (the unconditional path)."""
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

    return EvolutionResult(
        batch_id=batch,
        counts=dict(counts),
        revisions=revisions,
        warnings=warnings,
    )


# 【职责】磁盘级进化流程：加载技能目录→固化(合并入库)→校验后原子替换落盘，可选备份。
# - 先写 *_tmp 目录并逐个校验 YAML 可加载，再替换原目录；修订结果写入 mas_skill_revisions。
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


# 【职责】按目标技能 id 分组补丁(discard 跳过)；无 target 但有候选卡时先路由再归组。
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


# 【职责】候选卡路由：找同任务族、同目标、同拓扑且条件范围兼容的在位者技能；否则用候选自身 id。
def _route_candidate(bank: SkillBank, candidate: SkillCard) -> str:
    candidate_payload = mode_payload_from_skill(candidate)
    for skill in bank:
        current_payload = mode_payload_from_skill(skill)
        if (
            skill.task_family == candidate.task_family
            and skill.objective == candidate.objective
            and skill.topology_name == candidate.topology_name
            and (
                current_payload is None
                or candidate_payload is None
                or current_payload.format == candidate_payload.format
            )
            and _condition_scope_compatible(skill, candidate)
        ):
            return skill.skill_id
    return candidate.skill_id


# 【职责】兼容性守卫：候选卡拓扑与条件范围、证据引用的拓扑与触发条件都须匹配目标技能。
def _patch_matches_skill_topology(
    skill: SkillCard,
    patch: SkillPatch,
    records_by_id: dict[str, EvidenceRecord],
) -> bool:
    skill_topology = skill.topology_name
    current_payload = mode_payload_from_skill(skill)
    raw_payload = (patch.update or {}).get("mode_payload")
    if isinstance(raw_payload, dict):
        try:
            patch_payload = _MODE_PAYLOAD_ADAPTER.validate_python(raw_payload)
        except ValueError:
            return False
        if (
            current_payload is not None
            and patch_payload.format != current_payload.format
        ):
            return False
    if not skill_topology:
        return True
    if patch.candidate_skill is not None:
        candidate_topology = patch.candidate_skill.topology_name
        if candidate_topology and candidate_topology != skill_topology:
            return False
        candidate_payload = (
            mode_payload_from_skill(patch.candidate_skill)
        )
        if (
            current_payload is not None
            and candidate_payload is not None
            and current_payload.format != candidate_payload.format
        ):
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


# 【职责】生成图拓扑要求双方 condition_key 一致；非生成图拓扑不设此限制。
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


# 【职责】仅 "generated:" 前缀的生成图拓扑使用条件桶。
def _topology_uses_condition_bucket(topology_name: str | None) -> bool:
    return bool(topology_name and topology_name.startswith("generated:"))


# 【职责】校验证据记录落在技能触发条件内：agent 数与数组规模的范围及枚举约束。
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


# 【职责】由 add 补丁构造新技能卡：并入证据引用、按证据重算权衡/动态、写入首条修订历史。
def _prepare_new_skill(
    patch: SkillPatch,
    records_by_id: dict[str, EvidenceRecord],
) -> SkillCard:
    if patch.candidate_skill is None:
        raise ValueError("add patch requires candidate_skill")
    skill = with_inferred_payload(patch.candidate_skill)
    patch_update = patch.update or {}
    refs = _dedupe([*skill.evidence_refs, *patch.evidence_refs])
    recomputed_tradeoff = _recompute_tradeoff(refs, records_by_id)
    recomputed_dynamics = _recompute_dynamics(refs, records_by_id)
    design_insights = list(skill.design_insights)
    counterexamples = list(skill.counterexamples)
    risk_notes = list(skill.risk_notes)
    failure_modes = list(skill.failure_modes)
    hypotheses = list(skill.hypotheses)
    validation_plan = list(skill.validation_plan)
    for key, target in (
        ("design_insights", design_insights),
        ("counterexamples", counterexamples),
        ("risk_notes", risk_notes),
        ("failure_modes", failure_modes),
        ("hypotheses", hypotheses),
        ("validation_plan", validation_plan),
    ):
        _extend_unique_dicts(target, patch_update.get(key))
    trigger = _merge_nested_mapping(
        skill.trigger,
        patch_update.get("trigger")
        if isinstance(patch_update.get("trigger"), dict)
        else {},
    )
    reasoning_policy = _merge_nested_mapping(
        skill.reasoning_policy,
        patch_update.get("reasoning_policy")
        if isinstance(patch_update.get("reasoning_policy"), dict)
        else {},
    )
    organization_policy = dict(skill.organization_policy)
    if isinstance(patch_update.get("organization_policy"), dict):
        organization_policy = _merge_organization_policy(
            organization_policy,
            patch_update["organization_policy"],
        )
    mode_payload = skill.mode_payload
    if isinstance(patch_update.get("mode_payload"), dict):
        mode_payload = merge_mode_payload(
            mode_payload,
            _MODE_PAYLOAD_ADAPTER.validate_python(patch_update["mode_payload"]),
        )
    organization_policy = compatibility_policy_from_payload(
        organization_policy,
        mode_payload,
    )
    tradeoff = _merge_nested_mapping(skill.expected_tradeoff, recomputed_tradeoff)
    if isinstance(patch_update.get("expected_tradeoff"), dict):
        tradeoff = _merge_nested_mapping(
            tradeoff,
            patch_update["expected_tradeoff"],
        )
    dynamics = _merge_nested_mapping(skill.expected_dynamics, recomputed_dynamics)
    if isinstance(patch_update.get("expected_dynamics"), dict):
        dynamics = _merge_nested_mapping(
            dynamics,
            patch_update["expected_dynamics"],
        )
    fallback = _merge_nested_mapping(
        skill.fallback,
        patch_update.get("fallback")
        if isinstance(patch_update.get("fallback"), dict)
        else {},
    )
    confidence = _merge_nested_mapping(
        skill.confidence,
        _recompute_confidence(refs, records_by_id),
    )
    confidence = _merge_nested_mapping(
        confidence,
        patch_update.get("confidence")
        if isinstance(patch_update.get("confidence"), dict)
        else {},
    )
    tags = list(skill.tags)
    if isinstance(patch_update.get("tags"), list):
        tags = _dedupe([*tags, *[str(item) for item in patch_update["tags"]]])
    payload_change = payload_revision(None, mode_payload)
    revision: dict[str, object] = {
        "patch_ids": [patch.patch_id],
        "summary": patch.lesson,
        "created_at": utc_now(),
    }
    if payload_change is not None:
        revision["mode_payload_revision"] = payload_change
    update = {
        "evidence": _dedupe_dicts([*skill.evidence, *patch.evidence]),
        "evidence_refs": refs,
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
        "expected_tradeoff": tradeoff,
        "expected_dynamics": dynamics,
        "fallback": fallback,
        "confidence": confidence,
        "tags": tags,
        "update_rule": str(patch_update.get("update_rule") or skill.update_rule),
        "revision_history": [revision],
    }
    return skill.model_copy(update=update)


# 【职责】把一组补丁合并进既有技能卡，返回(新卡, 变更字段列表)——版本化与字段合并规则所在。
# - deprecate 补丁只追加 deprecated 标签；其余补丁累积证据/反例/风险注记/假设/设计洞见。
# - update 里的 fallback/trigger/expected_*/organization_policy 按各自规则并入既有字段。
# - 候选技能卡的对应字段同样并入；补丁 lesson 追加为带置信度的风险注记。
# - 期望权衡/动态先按证据引用重算、再叠加显式更新；置信度整体重算。
# - 版本号按补丁是否触碰 trigger/fallback/expected_dynamics/design_insights 升 minor 或 patch。
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
    reasoning_policy = dict(skill.reasoning_policy)
    current_mode_payload = mode_payload_from_skill(skill)
    mode_payload = current_mode_payload
    validation_plan = list(skill.validation_plan)
    expected_tradeoff_updates: dict[str, object] = {}
    expected_dynamics_updates: dict[str, object] = {}
    confidence_updates: dict[str, object] = {}
    trigger = dict(skill.trigger)
    tags = list(skill.tags)
    update_rule = skill.update_rule
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
        if patch.candidate_skill is not None:
            candidate = with_inferred_payload(patch.candidate_skill)
            evidence.extend(candidate.evidence)
            evidence_refs = _dedupe([*evidence_refs, *candidate.evidence_refs])
            _extend_unique_dicts(counterexamples, candidate.counterexamples)
            _extend_unique_dicts(risk_notes, candidate.risk_notes)
            _extend_unique_dicts(failure_modes, candidate.failure_modes)
            _extend_unique_dicts(hypotheses, candidate.hypotheses)
            _extend_unique_dicts(design_insights, candidate.design_insights)
            _extend_unique_dicts(validation_plan, candidate.validation_plan)
            trigger = _merge_nested_mapping(trigger, candidate.trigger)
            fallback = _merge_nested_mapping(fallback, candidate.fallback)
            organization_policy = _merge_organization_policy(
                organization_policy,
                candidate.organization_policy,
            )
            reasoning_policy = _merge_nested_mapping(
                reasoning_policy,
                candidate.reasoning_policy,
            )
            mode_payload = merge_mode_payload(
                mode_payload,
                candidate.mode_payload,
            )
            expected_tradeoff_updates = _merge_nested_mapping(
                expected_tradeoff_updates,
                candidate.expected_tradeoff,
            )
            expected_dynamics_updates = _merge_nested_mapping(
                expected_dynamics_updates,
                candidate.expected_dynamics,
            )
            confidence_updates = _merge_nested_mapping(
                confidence_updates,
                candidate.confidence,
            )
            tags = _dedupe([*tags, *candidate.tags])
            if candidate.update_rule:
                update_rule = candidate.update_rule
        # Explicit patch.update is the final authority over the candidate
        # snapshot, so a minister can refine every section in the same patch.
        if isinstance(update.get("trigger"), dict):
            trigger = _merge_nested_mapping(trigger, update["trigger"])
        if isinstance(update.get("fallback"), dict):
            fallback = _merge_nested_mapping(fallback, update["fallback"])
        if isinstance(update.get("expected_tradeoff"), dict):
            expected_tradeoff_updates = _merge_nested_mapping(
                expected_tradeoff_updates,
                update["expected_tradeoff"],
            )
        if isinstance(update.get("expected_dynamics"), dict):
            expected_dynamics_updates = _merge_nested_mapping(
                expected_dynamics_updates,
                update["expected_dynamics"],
            )
        if isinstance(update.get("organization_policy"), dict):
            organization_policy = _merge_organization_policy(
                organization_policy,
                update["organization_policy"],
            )
        if isinstance(update.get("reasoning_policy"), dict):
            reasoning_policy = _merge_nested_mapping(
                reasoning_policy,
                update["reasoning_policy"],
            )
        if isinstance(update.get("mode_payload"), dict):
            mode_payload = merge_mode_payload(
                mode_payload,
                _MODE_PAYLOAD_ADAPTER.validate_python(update["mode_payload"]),
            )
        if isinstance(update.get("confidence"), dict):
            confidence_updates = _merge_nested_mapping(
                confidence_updates,
                update["confidence"],
            )
        if isinstance(update.get("tags"), list):
            tags = _dedupe([*tags, *[str(item) for item in update["tags"]]])
            tags_changed = True
        if isinstance(update.get("update_rule"), str):
            update_rule = str(update["update_rule"])
        if patch.lesson:
            risk_notes.append(
                {
                    "source": patch.source,
                    "patch_id": patch.patch_id,
                    "summary": patch.lesson,
                    "confidence": patch.confidence,
                }
            )

    organization_policy = compatibility_policy_from_payload(
        organization_policy,
        mode_payload,
    )
    tradeoff = _merge_nested_mapping(
        skill.expected_tradeoff,
        _recompute_tradeoff(evidence_refs, records_by_id),
    )
    tradeoff = _merge_nested_mapping(tradeoff, expected_tradeoff_updates)
    dynamics = _merge_nested_mapping(
        skill.expected_dynamics,
        _recompute_dynamics(evidence_refs, records_by_id),
    )
    dynamics = _merge_nested_mapping(dynamics, expected_dynamics_updates)
    confidence = _merge_nested_mapping(skill.confidence, confidence_updates)
    confidence = _merge_nested_mapping(
        confidence,
        _recompute_confidence(evidence_refs, records_by_id),
    )
    merged_values: dict[str, object] = {
        "skill_type": (
            skill_type_for_payload(mode_payload)
            if skill.skill_type == "planner_organization_policy"
            else skill.skill_type
        ),
        "evidence": _dedupe_dicts(evidence),
        "evidence_refs": evidence_refs,
        "trigger": trigger,
        "mode_payload": mode_payload,
        "organization_policy": organization_policy,
        "reasoning_policy": reasoning_policy,
        "expected_tradeoff": tradeoff or skill.expected_tradeoff,
        "expected_dynamics": dynamics or skill.expected_dynamics,
        "design_insights": _dedupe_design_insights(design_insights),
        "counterexamples": _dedupe_dicts(counterexamples),
        "risk_notes": _dedupe_dicts(risk_notes),
        "failure_modes": _dedupe_dicts(failure_modes),
        "hypotheses": _dedupe_dicts(hypotheses),
        "fallback": fallback,
        "validation_plan": _dedupe_dicts(validation_plan),
        "confidence": confidence or skill.confidence,
        "tags": tags,
        "update_rule": update_rule,
    }
    changed.update(
        key for key, value in merged_values.items() if getattr(skill, key) != value
    )
    if tags_changed:
        changed.add("tags")
    payload_change = payload_revision(current_mode_payload, mode_payload)
    revision_entry: dict[str, object] = {
        "patch_ids": [patch.patch_id for patch in patches],
        "evidence_refs": evidence_refs,
        "changed_fields": sorted(changed),
        "summary": "; ".join(patch.lesson for patch in patches if patch.lesson),
        "created_at": utc_now(),
    }
    if payload_change is not None:
        revision_entry["mode_payload_revision"] = payload_change
    revision_history = [*skill.revision_history, revision_entry]
    changed.add("revision_history")
    new_version = _bump_version(
        skill.version,
        minor=(
            _requires_minor_bump(patches)
            or bool({"mode_payload", "reasoning_policy"} & changed)
        ),
    )
    return skill.model_copy(
        update={
            "version": new_version,
            **merged_values,
            "revision_history": revision_history,
        }
    ), sorted(changed)


# 【职责】由 observed 的 aggregate/run 证据重算期望权衡：各项指标均值与活跃证据数。
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


# 【职责】由 observed 的 trace 证据重算期望动态：覆盖增长/聚合可靠性/合并质量/风险标签。
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


# 【职责】由 observed 证据重算置信度：score = max(0, 证据强度 - 风险惩罚)。
# - 证据强度 evidence_strength = min(0.9, 0.2 + 0.1×去重种子数 + 0.1×去重 agent 规模数)。
# - 风险惩罚 risk_penalty = min(0.4, 0.05×风险标签种类数)，来源是各证据记录 risk_tags 的去重并集。
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


# 【职责】组织策略合并规则：topology/operators/planner_mode 冲突时保留在位者值(丢弃新值)。
# - rationale_rules 按字符串去重合并；operation_recommendations/operator_constraints 转字典去重合并。
# - structure_features/condition_scope 做字典浅合并(新键覆盖同名键)；其余键直接被新值覆盖。
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


def _merge_nested_mapping(
    current: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Recursively merge learned policy sections and retain sibling fields."""
    merged = dict(current)
    for key, value in incoming.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_nested_mapping(existing, value)
            continue
        if isinstance(existing, list) and isinstance(value, list):
            combined: list[object] = []
            for item in [*existing, *value]:
                if item not in combined:
                    combined.append(item)
            merged[key] = combined
            continue
        merged[key] = value
    return merged


# 【职责】给缺 evidence_id 的旧式证据条目补 status=deprecated(遗留占位)标记。
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


# 【职责】补丁触碰可执行载荷或行为语义等字段时升 minor。
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
                "mode_payload",
                "reasoning_policy",
                "organization_policy",
            ]
        ):
            return True
        candidate = patch.candidate_skill
        if candidate is not None and (
            candidate.mode_payload is not None or candidate.reasoning_policy
        ):
            return True
    return False


# 【职责】语义化版本自增：minor 升中位并清零末位；否则仅升 patch 位。
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


# 【职责】幂等检查：patch_id 已出现在技能修订历史中即视为已应用。
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


# 【职责】落盘前校验：目录中每个 YAML 技能文件都能成功加载(失败即抛错阻止替换)。
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


# 【职责】设计洞见去重：有 insight_id 按 id 去重，否则按 JSON 序列化整体去重。
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
