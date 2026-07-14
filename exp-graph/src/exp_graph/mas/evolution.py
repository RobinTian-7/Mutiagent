"""Minister analysts and batch consolidation for MAS skill evolution."""

# ============================================================
# 【模块导读】面向 MAS 技能进化的大臣分析器与批次固化(合并入库)。
# - 结果/成本/反例/轨迹四类大臣从证据中提炼技能补丁(冠军选择、避雷、触发条件等生成规则)。
# - classify_topology / make_skill_card 把拓扑证据组装成带触发条件的技能卡。
# - consolidate_batch 把 add/merge/discard 补丁作为一个批次应用到技能库。
# ============================================================
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
from exp_graph.mas.schemas import (
    EvidenceRecord,
    EvolutionBatch,
    GraphSkillPayload,
    ModeSkillPayload,
    NamedTopologySkillPayload,
    PhaseProgramSkillPayload,
    PythonSkillPayload,
    SkillCard,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.skill_payloads import skill_type_for_payload


# 【职责】结果分析大臣：从聚合指标中提炼精度/拓扑模式。
# - 证据按拓扑(生成图叠加条件桶)分组，逐组生成合并补丁，并追加避雷(反例)补丁。
class ResultAnalystMinister:
    """Extract accuracy/topology patterns from aggregate metrics."""

    source = "result_analyst"

    def analyze(
        self,
        aggregate_rows: list[dict[str, Any]],
        *,
        task_family: str = "count_frequency",
    ) -> list[SkillPatch]:
        evidence = aggregate_rows_to_evidence(aggregate_rows)
        grouped = _group_dict_evidence_for_skills(evidence)
        patches = [
            build_skill_patch_for_topology(
                str(rows[0].get("topology_name", rows[0].get("Topology", group_key))),
                rows,
                task_family=task_family,
            )
            for group_key, rows in sorted(grouped.items())
        ]
        patches.extend(build_negative_patches(evidence, task_family=task_family))
        return patches


# 【职责】成本分析大臣：从聚合指标中提炼预算优先的观察。
# - 需≥2 种拓扑可比才出手：按(平均 token 成本, 平均消息数)选最便宜拓扑生成补丁(置信度 0.9)。
class CostAnalystMinister:
    """Extract budget-first observations from aggregate metrics."""

    source = "cost_analyst"

    def analyze(
        self,
        aggregate_rows: list[dict[str, Any]],
        *,
        task_family: str = "count_frequency",
    ) -> list[SkillPatch]:
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
            task_family=task_family,
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


# 【职责】反例大臣：把不稳定或被支配的拓扑记录为反例(避雷技能补丁)。
class CounterexampleMinister:
    """Record unstable or dominated topologies as counterexamples."""

    source = "counterexample_analyst"

    def analyze(
        self,
        aggregate_rows: list[dict[str, Any]],
        *,
        task_family: str = "count_frequency",
    ) -> list[SkillPatch]:
        evidence = aggregate_rows_to_evidence(aggregate_rows)
        return build_negative_patches(evidence, task_family=task_family)


# 【职责】轨迹分析大臣：不要求 CF 结果完美，也能从轨迹证据中提炼可复用的动态信号。
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

    # 【职责】按拓扑聚合 trace 证据：汇总 risk_tags 生成风险注记与回退提示(置信度 0.7)。
    # - sink_quality_gap→回退中庸 mesh_star；合并重试/解析错误→改用 LLM 信念合并或投票。
    def analyze_evidence(
        self,
        records: list[EvidenceRecord],
        *,
        task_family: str = "count_frequency",
    ) -> list[SkillPatch]:
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
            candidate = make_skill_card(
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
                task_family=task_family,
            )
            patches.append(
                SkillPatch(
                    patch_id=f"trace_{candidate.skill_id}",
                    action="merge",
                    target_skill_id=candidate.skill_id,
                    candidate_skill=candidate,
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


# 【职责】从实验目录加载聚合数据，由结果/成本两位大臣生成引导(bootstrap)进化批次。
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


# 【职责】从只追加(append-only)的证据记录构建补丁候选批次。
# - 汇集结果/成本/反例/轨迹四路大臣的补丁为一个 EvolutionBatch。
def build_evolution_batch_from_evidence(
    records: list[EvidenceRecord],
    *,
    batch_id: str = "cf_evidence_batch",
    task_family: str = "count_frequency",
) -> EvolutionBatch:
    """Build patch candidates from append-only evidence records."""
    patches = [
        *build_result_patches_from_evidence(records, task_family=task_family),
        *build_cost_patches_from_evidence(records, task_family=task_family),
        *build_counterexample_patches_from_evidence(records, task_family=task_family),
        *TraceAnalystMinister().analyze_evidence(records, task_family=task_family),
    ]
    return EvolutionBatch(
        batch_id=batch_id,
        patches=patches,
        summary="Build skill patch candidates from append-only MAS evidence.",
    )


# 【职责】把 add/merge/discard 补丁作为一个批次应用(固化/合并入库)到技能库。
# - discard 跳过；目标技能已在库→按 merge 应用；否则有候选技能卡→按 add 应用。
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


# 【职责】结果补丁生成规则：取 observed 的 aggregate/run 证据，按拓扑(生成图叠加条件桶)分组。
# - 每组汇总 rmse/token 成本/消息数/精确匹配率的均值写入期望权衡，并附经验教训。
# - 产出 merge 补丁并把教训写入 rationale_rules，置信度 0.75。
def build_result_patches_from_evidence(
    records: list[EvidenceRecord],
    *,
    task_family: str = "count_frequency",
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
            task_family=task_family,
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


# 【职责】成本补丁生成规则：证据须覆盖≥2 种拓扑才可比，否则不产出。
# - 按(token 成本, 消息数)取最便宜记录，为其技能卡生成 merge 补丁。
# - 期望权衡写明"最低观测通信成本/与对等(peer)传播相比可能牺牲精度"，置信度 0.9。
def build_cost_patches_from_evidence(
    records: list[EvidenceRecord],
    *,
    task_family: str = "count_frequency",
) -> list[SkillPatch]:
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
        task_family=task_family,
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


# 【职责】反例(避雷)补丁生成规则：按 n_agents 分组比较各拓扑 rmse。
# - rmse 超过组内最优 1.75 倍判为"被支配"，为其生成 cf_avoid_* 避雷技能补丁。
# - 补丁附"该拓扑在观测证据中被支配"的风险注记，置信度 0.7。
def build_counterexample_patches_from_evidence(
    records: list[EvidenceRecord],
    *,
    task_family: str = "count_frequency",
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
            task_family=task_family,
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


# 【职责】为单个拓扑的证据行生成结果合并补丁：汇总 rmse/token/消息均值并构造技能卡(置信度 0.75)。
def build_skill_patch_for_topology(
    topology: str,
    rows: list[dict[str, Any]],
    *,
    task_family: str = "count_frequency",
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
    # 中文：通用(非 CF)证据带有换算后的主损失及其指标名；把两者透传到技能卡，
    #   让评分逻辑直接从技能卡读取损失。CF 行从不携带这些键，故该分支对 CF 技能是空操作。
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
        task_family=task_family,
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


# 【职责】dict 证据版避雷补丁规则：同 n_agents 组内 rmse > 最优×1.75 判为被支配。
# - 为被支配拓扑生成 cf_avoid_* 避雷技能补丁(置信度 0.7)。
def build_negative_patches(
    evidence: list[dict[str, Any]],
    *,
    task_family: str = "count_frequency",
) -> list[SkillPatch]:
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
            task_family=task_family,
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


# 【职责】把拓扑名映射为(目标, 算子, 技能 id, 经验教训)：补丁命名与技能定位的基础规则。
# - peer+star=精度优先；tree=预算优先；mesh_star=中庸；其余拓扑走通用兜底 id。
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


# 【职责】从证据行推断 information_goal；混合模式的证据违反隔离不变式，直接报错。
def _evidence_information_goal(evidence: list[dict[str, Any]]) -> str:
    goals = {
        str(row.get("information_goal"))
        for row in evidence
        if row.get("information_goal")
    }
    if len(goals) > 1:
        raise ValueError(
            f"skill evidence mixes information goals {sorted(goals)}; "
            "sink and all_agents evidence must never merge into one card"
        )
    return goals.pop() if goals else "sink"


# 【职责】推断卡片 provenance：证据行显式值优先；否则按拓扑名推断
#   (generated:* -> llm_generated，具名拓扑 -> fixed_named)。
def _evidence_provenance(
    evidence: list[dict[str, Any]], topology_name: str
) -> str:
    allowed = {
        "llm_generated",
        "program_generated",
        "llm_generated_python",
        "skill_replay",
        "fixed_named",
        "named_fallback",
        "fake",
    }
    explicit = [
        str(row.get("provenance"))
        for row in evidence
        if str(row.get("provenance")) in allowed
    ]
    if explicit:
        # 中文：若同时出现具名与生成来源，取"最脏"者，防止具名兜底伪装成生成结构。
        # If named and generated provenances co-occur, keep the dirtiest one so a
        # named fallback can never masquerade as a generated structure.
        for dirty in ("fake", "named_fallback", "fixed_named"):
            if dirty in explicit:
                return dirty
        if "program_generated" in explicit:
            return "program_generated"
        if "llm_generated_python" in explicit:
            return "llm_generated_python"
        if "llm_generated" in explicit:
            return "llm_generated"
        if "skill_replay" in explicit:
            return "skill_replay"
        return explicit[0]
    if str(topology_name).startswith("program:"):
        return "program_generated"
    if str(topology_name).startswith("python:"):
        return "llm_generated_python"
    return (
        "llm_generated"
        if str(topology_name).startswith("generated:")
        else "fixed_named"
    )


def _evidence_planner_mode(
    evidence: list[dict[str, Any]], topology_name: str
) -> str:
    modes = {
        (
            "topology_select"
            if str(row.get("planner_mode")) == "fixed_named"
            else str(row.get("planner_mode"))
        )
        for row in evidence
        if row.get("planner_mode")
    }
    if len(modes) > 1:
        raise ValueError(
            f"skill evidence mixes planner modes {sorted(modes)}; generated "
            "program and free-graph evidence must never merge into one card"
        )
    if modes:
        return modes.pop()
    if str(topology_name).startswith("program:"):
        return "program_generate"
    if str(topology_name).startswith("python:"):
        return "python_generate"
    if str(topology_name).startswith("generated:"):
        return "graph_generate"
    return "topology_select"


# 【职责】把证据组装成一张技能卡：推断条件范围、结构特征、最佳协议规格与操作建议。
# - 触发条件记录任务族与 agent/数组规模条件桶；skill_id 先按条件桶、再按任务族限定命名。
# - 回退默认指向预算优先 cf_budget_tree；非 CF 的 cf_avoid_* 额外打 counterexample 标签。
# - information_goal/provenance：显式参数优先，否则从证据行推断。skill_id 追加模式
#   后缀，trigger 记录 information_goal —— sink 与 all_agents 的卡从命名到检索全隔离。
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
    task_family: str = "count_frequency",
    information_goal: str | None = None,
    provenance: str | None = None,
) -> SkillCard:
    feature_evidence = analysis_evidence if analysis_evidence is not None else evidence
    # 中文：目标显式性判定：显式参数或证据行携带 information_goal 才启用模式命名空间
    #   （Silo 行自泄漏修复起总是携带）；CF 等 legacy 证据不携带 -> 卡片字节级不变。
    # Mode namespacing activates only when the goal is EXPLICIT (param or rows;
    # Silo rows always carry it since the leakage fix). Legacy CF evidence has
    # no goal signal, so those cards stay byte-identical.
    _rows_goal = _evidence_information_goal(feature_evidence)
    _goal_explicit = information_goal is not None or any(
        row.get("information_goal") for row in feature_evidence
    )
    resolved_goal = information_goal or _rows_goal
    resolved_provenance = provenance or (
        _evidence_provenance(feature_evidence, topology_name)
        if _goal_explicit
        or any(row.get("provenance") for row in feature_evidence)
        else None
    )
    resolved_planner_mode = _evidence_planner_mode(
        feature_evidence,
        topology_name,
    )
    _planner_mode_explicit = any(
        row.get("planner_mode") for row in feature_evidence
    ) or str(topology_name).startswith(("program:", "python:"))
    condition_scope = infer_condition_scope(feature_evidence)
    structure_features = infer_topology_structure_features(
        topology_name,
        feature_evidence,
    )
    protocol_spec = _best_protocol_spec(feature_evidence)
    reasoning_policy = _reasoning_policy_from_spec(protocol_spec)
    python_policy = (
        _best_python_policy(feature_evidence)
        if resolved_planner_mode == "python_generate"
        else None
    )
    if resolved_planner_mode == "python_generate":
        reasoning_policy = _python_reasoning_policy(
            str((python_policy or {}).get("worker_contract") or "action_json_v1")
        )
    observed_failure_modes = _failure_modes_from_evidence(feature_evidence)
    observed_counterexamples = _failure_counterexamples(feature_evidence)
    operation_recommendations = default_operation_recommendations(
        topology_name,
        structure_features,
        condition_scope,
    )
    final_skill_id = family_scoped_skill_id(
        condition_specific_skill_id(
            skill_id,
            topology_name,
            condition_scope,
        ),
        task_family,
    )
    # 中文：显式目标时 skill_id 追加信息目标后缀（sink 卡与 all_agents 卡不可能同名，
    #   consolidation 的按 id 路由天然隔离），trigger 记录 information_goal。
    # With an explicit goal the skill_id gets the goal suffix (sink and
    # all_agents cards can never share an id) and the trigger records the goal.
    if _goal_explicit:
        final_skill_id = f"{final_skill_id}__{resolved_goal}"
    trigger = {
        "task_family": task_family,
        "min_agents": condition_scope.get("min_agents", 1),
        "max_agents": condition_scope.get("max_agents", 999),
        "agent_bucket": condition_scope.get("agent_bucket", "agents_any"),
        "condition_key": condition_scope.get("condition_key", "agents_any__arrays_any"),
    }
    if _goal_explicit:
        trigger["information_goal"] = resolved_goal
    if _planner_mode_explicit:
        trigger["planner_mode"] = resolved_planner_mode
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
    budget_fallback_id = family_scoped_skill_id("cf_budget_tree", task_family)
    if _goal_explicit:
        budget_fallback_id = f"{budget_fallback_id}__{resolved_goal}"
    tags = ["mas", "emperor-skill", _family_tag(task_family), objective]
    # 中文：CF 的避雷技能靠 ``cf_avoid_`` id 前缀识别(``is_avoid_skill``)。
    #   非 CF 的 id 带任务族命名空间(``silo__cf_avoid_*``)，该前缀检查不再命中，
    #   故显式打标签使其保持"仅负面约束"；CF 的标签保持逐字节不变(不加标签)。
    # For CF, avoid skills are detected by their ``cf_avoid_`` id prefix
    # (``is_avoid_skill``). Non-CF ids are family-namespaced (``silo__cf_avoid_*``)
    # so that prefix check no longer fires; tag them explicitly so they stay
    # negative-only constraints. CF tags are left byte-identical (no tag added).
    if task_family != "count_frequency" and skill_id.startswith("cf_avoid_"):
        tags.append("counterexample")
    validity_observations = [
        float(row["program_validity"])
        for row in feature_evidence
        if row.get("program_validity") is not None
    ]
    if validity_observations and max(validity_observations) <= 0.0:
        tags.append("counterexample")
    organization_policy: dict[str, object] = {
        "planner_mode": resolved_planner_mode,
        "topology_name": topology_name,
        "operators": operators,
        "protocol_spec": protocol_spec,
        "structure_features": structure_features,
        "operation_recommendations": operation_recommendations,
    }
    if python_policy is not None:
        organization_policy.update(python_policy)
    mode_payload = _build_mode_payload(
        planner_mode=resolved_planner_mode,
        topology_name=topology_name,
        protocol_spec=protocol_spec,
        python_policy=python_policy,
    )
    return SkillCard(
        skill_id=final_skill_id,
        version="0.1.0",
        task_family=task_family,
        skill_type=skill_type_for_payload(mode_payload),
        trigger=trigger,
        information_goal=(resolved_goal if _goal_explicit else None),  # type: ignore[arg-type]
        provenance=resolved_provenance,  # type: ignore[arg-type]
        objective=objective,  # type: ignore[arg-type]
        mode_payload=mode_payload,
        organization_policy=organization_policy,
        reasoning_policy=reasoning_policy,
        expected_tradeoff=expected_tradeoff,
        expected_dynamics={
            "condition_scope": condition_scope,
            "structure_features": structure_features,
            "protocol_spec_hash": _protocol_spec_hash(protocol_spec),
            "program_sha256": (
                python_policy.get("program_sha256") if python_policy else None
            ),
        },
        evidence=evidence,
        evidence_refs=evidence_refs or [],
        fallback={
            "budget_first": budget_fallback_id
            if final_skill_id != budget_fallback_id
            else None
        },
        failure_modes=observed_failure_modes,
        counterexamples=[*(counterexamples or []), *observed_counterexamples],
        tags=tags,
    )


def _build_mode_payload(
    *,
    planner_mode: str,
    topology_name: str,
    protocol_spec: dict[str, object] | None,
    python_policy: dict[str, object] | None,
) -> ModeSkillPayload | None:
    """Build one mode-owned executable payload for a newly learned skill."""
    if planner_mode == "python_generate":
        if python_policy is None:
            return None
        source = python_policy.get("source_code")
        if not isinstance(source, str) or not source.strip():
            return None
        runtime_summary = python_policy.get("observed_runtime_trace_summary")
        return PythonSkillPayload(
            source_code=source,
            program_sha256=str(python_policy.get("program_sha256") or ""),
            ast_policy_version=str(python_policy.get("ast_policy_version") or ""),
            execution_contract_version=str(
                python_policy.get("execution_contract_version") or ""
            ),
            worker_contract=(
                str(python_policy.get("worker_contract"))
                if python_policy.get("worker_contract")
                in {"message_only_v1", "message_only_v2"}
                else "action_json_v1"
            ),
            repair_attempts=int(python_policy.get("repair_attempts", 0) or 0),
            artifact_reference=(
                str(python_policy["artifact_reference"])
                if python_policy.get("artifact_reference")
                else None
            ),
            runtime_trace_summary=(
                dict(runtime_summary) if isinstance(runtime_summary, dict) else {}
            ),
            innovation_strategy=(
                str(python_policy["innovation_strategy"])
                if python_policy.get("innovation_strategy")
                else None
            ),
            parent_skill_id=(
                str(python_policy["parent_skill_id"])
                if python_policy.get("parent_skill_id")
                else None
            ),
            exposed_insight_ids=list(
                python_policy.get("exposed_insight_ids", []) or []
            ),
            used_insight_ids=list(
                python_policy.get("used_insight_ids", []) or []
            ),
            parent_program_sha256=(
                str(python_policy["parent_program_sha256"])
                if python_policy.get("parent_program_sha256")
                else None
            ),
            mutation_diff_sha256=(
                str(python_policy["mutation_diff_sha256"])
                if python_policy.get("mutation_diff_sha256")
                else None
            ),
            mutation_provenance=(
                dict(python_policy.get("mutation_provenance", {}))
                if isinstance(python_policy.get("mutation_provenance"), dict)
                else {}
            ),
        )
    if not isinstance(protocol_spec, dict):
        return None
    metadata = protocol_spec.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if planner_mode == "program_generate":
        phase_program = metadata.get("phase_program")
        if not isinstance(phase_program, dict):
            return None
        compilation = metadata.get("phase_program_compilation")
        compilation = compilation if isinstance(compilation, dict) else {}
        return PhaseProgramSkillPayload(
            topology_name=topology_name,
            phase_program=phase_program,
            compiled_protocol_spec=protocol_spec,
            compiler_version=str(compilation.get("compiler_version") or "1"),
            program_sha256=str(compilation.get("source_hash") or ""),
        )
    if planner_mode == "graph_generate":
        topology_program = metadata.get("topology_program")
        return GraphSkillPayload(
            topology_name=topology_name,
            protocol_spec=protocol_spec,
            topology_program=(
                dict(topology_program) if isinstance(topology_program, dict) else None
            ),
            structure_code={
                "schema_version": "graph_skill_code_v1",
                "language": (
                    "topology_program_v1"
                    if isinstance(topology_program, dict)
                    else "protocol_graph_spec_v1"
                ),
                "execution": "compile_or_direct_protocol_spec",
            },
        )
    return NamedTopologySkillPayload(
        topology_name=topology_name,
        protocol_spec=protocol_spec,
        structure_code={
            "schema_version": "named_topology_skill_code_v1",
            "language": "named_topology_v1",
            "source": f"build_protocol_schedule({topology_name!r}, n_agents)",
            "execution": "direct_protocol_spec",
        },
    )


def _mean_record_metric(records: list[EvidenceRecord], *keys: str) -> float:
    values = [
        _record_metric(record, *keys)
        for record in records
        if any(key in record.metrics and record.metrics[key] is not None for key in keys)
    ]
    return statistics.fmean(values) if values else 0.0


# 【职责】在证据中选 rmse 最低行携带的 protocol_spec 作为最佳协议规格(无则返回 None)。
def _best_protocol_spec(evidence: list[dict[str, Any]]) -> dict[str, object] | None:
    candidates: list[tuple[float, dict[str, object]]] = []
    for row in evidence:
        spec = row.get("protocol_spec")
        if spec is None and isinstance(row.get("metrics"), dict):
            spec = row["metrics"].get("protocol_spec")  # type: ignore[index]
        if not isinstance(spec, dict) or not spec.get("steps"):
            continue
        loss = _evidence_float(
            row,
            "mean_primary_loss",
            "mean_rmse",
            "final_rmse",
        )
        candidates.append((loss if loss is not None else float("inf"), spec))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _best_python_policy(
    evidence: list[dict[str, Any]],
) -> dict[str, object] | None:
    """Select the lowest-loss validated Python program and its audit contract."""
    candidates: list[tuple[float, int, dict[str, object]]] = []
    for row in evidence:
        source = row.get("python_source")
        if source is None and isinstance(row.get("metrics"), dict):
            source = row["metrics"].get("python_source")  # type: ignore[index]
        if not isinstance(source, str) or not source.strip():
            continue
        validity = _evidence_float(row, "program_validity")
        if validity is not None and validity < 1.0:
            continue
        policy: dict[str, object] = {
            "source_code": source,
            "program_sha256": str(row.get("program_sha256") or ""),
            "ast_policy_version": str(row.get("ast_policy_version") or ""),
            "execution_contract_version": str(
                row.get("execution_contract_version") or ""
            ),
            "worker_contract": str(
                row.get("worker_contract") or "action_json_v1"
            ),
            "repair_attempts": int(row.get("repair_attempts", 0) or 0),
            "observed_runtime_trace_summary": row.get("runtime_trace_summary")
            if isinstance(row.get("runtime_trace_summary"), dict)
            else {},
            "innovation_strategy": row.get("python_innovation_strategy"),
            "parent_skill_id": row.get("python_parent_skill_id"),
            "exposed_insight_ids": list(
                row.get("python_exposed_insight_ids", []) or []
            ),
            "used_insight_ids": list(
                row.get("python_used_insight_ids", []) or []
            ),
            "mutation_provenance": (
                dict(row.get("python_mutation_provenance", {}))
                if isinstance(row.get("python_mutation_provenance"), dict)
                else {}
            ),
        }
        mutation = policy["mutation_provenance"]
        if isinstance(mutation, dict):
            if mutation.get("parent_program_sha256"):
                policy["parent_program_sha256"] = str(
                    mutation["parent_program_sha256"]
                )
            patches = mutation.get("patches")
            if isinstance(patches, list) and patches:
                final_patch = patches[-1]
                if isinstance(final_patch, dict) and final_patch.get("diff_sha256"):
                    policy["mutation_diff_sha256"] = str(
                        final_patch["diff_sha256"]
                    )
        artifact = row.get("python_artifacts_dir")
        if artifact:
            policy["artifact_reference"] = str(artifact)
        loss = _evidence_float(
            row,
            "mean_primary_loss",
            "mean_rmse",
            "final_rmse",
        )
        strategy = str(policy.get("innovation_strategy") or "")
        innovation_priority = (
            0 if strategy == "mutate" else 1 if strategy == "fresh" else 2
        )
        candidates.append(
            (
                loss if loss is not None else float("inf"),
                innovation_priority,
                policy,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _python_reasoning_policy(
    worker_contract: str = "action_json_v1",
) -> dict[str, object]:
    """Describe the verified Worker contract independently of graph schedules."""
    if worker_contract == "message_only_v2":
        return {
            "worker_contract": "message_only_v2",
            "planner_control_schema": ["mode", "recipients"],
            "communication_control_modes": ["send", "reflect", "idle"],
            "submit_barrier": (
                "after all planned communication and final delivery, every "
                "required agent submits from one frozen logical snapshot"
            ),
            "worker_output": (
                "plain text during send/reflect; exactly one JSON value during "
                "the synchronized submit barrier"
            ),
            "state_retention": (
                "the runtime keeps each agent's previous worker output and "
                "merges source_ids on delivery"
            ),
            "message_contract": {
                "delivery": "round r messages become visible in round r+1",
                "preserve_source_provenance": True,
                "deduplicate_by_source": True,
                "provenance_author": "runtime",
            },
            "answer_contract": "single_json_value",
            "verified_instruction_summary": (
                "The Planner designs communication only; the runtime owns the "
                "global submit barrier, and workers return benchmark-ready "
                "JSON answer values without prose."
            ),
        }
    if worker_contract == "message_only_v1":
        return {
            "worker_contract": "message_only_v1",
            "planner_control_schema": ["mode", "recipients"],
            "control_modes": ["send", "reflect", "submit", "idle"],
            "worker_output": (
                "plain text only: a rolling-summary message body or the final "
                "answer; workers never author state, recipients, source_ids "
                "or submit flags"
            ),
            "state_retention": (
                "the runtime keeps each agent's previous worker output and "
                "merges source_ids on delivery"
            ),
            "message_contract": {
                "delivery": "round r messages become visible in round r+1",
                "preserve_source_provenance": True,
                "deduplicate_by_source": True,
                "provenance_author": "runtime",
            },
            "submit_guard": (
                "submitted agents receive no later calls and send no messages"
            ),
            "verified_instruction_summary": (
                "The Planner source routes, the runtime owns state and "
                "provenance, and each worker turns its local prompt, previous "
                "output and delivered inbox into one plain-text message or "
                "answer."
            ),
        }
    return {
        "worker_action_schema": [
            "state",
            "should_send",
            "recipients",
            "message",
            "source_ids",
            "submit",
            "answer",
        ],
        "state_retention": "retain previous state; update only explicit fields",
        "message_contract": {
            "delivery": "round r messages become visible in round r+1",
            "preserve_source_provenance": True,
            "deduplicate_by_source": True,
        },
        "submit_guard": "submitted agents receive no later calls and send no messages",
        "verified_instruction_summary": (
            "Each active agent acts from the same previous-round snapshot using only "
            "its own local prompt plus explicitly delivered worker-output messages."
        ),
    }


def _reasoning_policy_from_spec(
    protocol_spec: dict[str, object] | None,
) -> dict[str, object]:
    if not isinstance(protocol_spec, dict):
        return {}
    metadata = protocol_spec.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    instructions = []
    for index, raw_step in enumerate(protocol_spec.get("steps") or []):
        if not isinstance(raw_step, dict):
            continue
        instruction = raw_step.get("instruction")
        if instruction:
            instructions.append(
                {"step_index": index, "instruction": str(instruction)}
            )
    policy: dict[str, object] = {}
    for key in ("state_retention", "allow_no_send", "submit_when"):
        if key in metadata:
            policy[key] = metadata[key]
    if instructions:
        policy["step_instructions"] = instructions
        policy["merge_contract"] = {
            "preserve_source_provenance": True,
            "deduplicate_by_source": True,
        }
    return policy


def _failure_modes_from_evidence(
    evidence: list[dict[str, Any]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        stage = str(row.get("evolution_stage") or "")
        if stage and stage != "success":
            grouped[stage].append(row)
    result: list[dict[str, object]] = []
    for stage, rows in sorted(grouped.items()):
        result.append(
            {
                "stage": stage,
                "count": len(rows),
                "mean_structural_coverage": statistics.fmean(
                    float(row.get("structural_coverage", 0.0) or 0.0)
                    for row in rows
                ),
                "mean_submission_rate": statistics.fmean(
                    float(row.get("submission_rate", 0.0) or 0.0)
                    for row in rows
                ),
                "mean_partial": statistics.fmean(
                    float(row.get("evolution_partial", 0.0) or 0.0)
                    for row in rows
                ),
            }
        )
    return result


def _failure_counterexamples(
    evidence: list[dict[str, Any]],
) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    for row in evidence:
        stage = str(row.get("evolution_stage") or "")
        if not stage or stage == "success":
            continue
        examples.append(
            {
                "case_id": row.get("case_id"),
                "seed": row.get("seed"),
                "stage": stage,
                "structural_coverage": row.get("structural_coverage"),
                "submission_rate": row.get("submission_rate"),
                "partial": row.get("evolution_partial"),
                "failure_reason": (
                    row.get("python_generation_failed")
                    or row.get("program_generation_failed")
                    or row.get("graph_generation_failed")
                ),
                "failure_category": row.get("python_failure_category"),
                "artifact_reference": row.get("python_artifacts_dir"),
            }
        )
        if len(examples) >= 5:
            break
    return examples


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


# 【职责】归纳技能有证据支撑的条件桶：agent 数与数组规模的最小/最大范围、桶名与 condition_key。
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


# 【职责】显式记录拓扑结构信号(而非只记名字)：由名字识别结构母题(motif)。
# - 并汇总聚合模式、汇点模式、协议步数/消息数、生成图标志与候选 id 等特征。
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


# 【职责】由结构证据产出操作级规划器提示(preserve/mutate 操作建议)。
# - 默认保留条件触发：仅在有记录的 agent/数组规模条件桶内应用该技能。
# - 分层归约/时序流母题保留分阶段归约边；单主汇点保留最终归约器；生成图允许受限变异。
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


# 【职责】生成图类拓扑把条件桶键编码进 skill_id 后缀(如 __a4arr128)；通用桶保持原 id。
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


# 【职责】按任务族给 skill_id 加命名空间，防止非 CF 技能与 CF 技能在同一技能库中撞 id。
# - 技能库以 skill_id 为字典键存储；Silo 与 CF 若归类到同一 id 会互相覆盖。
# - count_frequency 的 id 逐字节不变(历史默认)，其他任务族加前缀；幂等：已带前缀则不变。
def family_scoped_skill_id(skill_id: str, task_family: str) -> str:
    """Namespace a skill_id by family so non-CF skills cannot collide with CF.

    ``SkillBank`` stores skills in a dict keyed by ``skill_id``; a Silo skill and
    a CF skill that classify to the same id (e.g. ``cf_accuracy_peer_star``) would
    otherwise overwrite each other in one bank. We keep ``count_frequency`` ids
    byte-identical (the legacy default) and prefix every other family so the two
    coexist. Idempotent: an id already carrying its family prefix is unchanged.
    """
    if task_family == "count_frequency":
        return skill_id
    prefix = f"{task_family}__"
    if skill_id.startswith(prefix):
        return skill_id
    return f"{prefix}{skill_id}"


# 【职责】生成镜像任务族的装饰性 tags 项(CF 固定为 count-frequency，其余下划线转连字符)。
def _family_tag(task_family: str) -> str:
    """Cosmetic ``tags`` entry mirroring the family (CF stays ``count-frequency``)."""
    if task_family == "count_frequency":
        return "count-frequency"
    return task_family.replace("_", "-")


# 【职责】按拓扑分组 dict 证据行；生成图拓扑在分组键上叠加条件桶(agents__arrays)。
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


# 【职责】仅 "generated:" 前缀的生成图拓扑使用条件桶身份。
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
