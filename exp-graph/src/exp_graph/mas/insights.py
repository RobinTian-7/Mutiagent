"""LLM post-run insight generation and insight-to-skill patch mapping."""

# ============================================================
# 【模块导读】运行后的 LLM 设计洞见(insight)生成，以及洞见→技能补丁的映射。
# - 可选路径：仅在 --use-llm-insights 打开时启用。
# - 主链路：build_evidence_pack 压缩证据 → LLMInsightMinister 产出洞见报告
#   → verify_insight_report 规则校验 → falsify_insights 留出集证伪
#   → insight_report_to_patches 转成技能补丁候选。
# - 注意：本文件 JSON 负载/字符串里的英文是发给 LLM 的运行时提示词，不可改动。
# ============================================================
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean, median
from typing import Any

from exp_graph.llm.base import LLMClient
from exp_graph.mas.evolution import (
    classify_topology,
    condition_specific_skill_id,
    default_operation_recommendations,
    infer_condition_scope,
    infer_topology_structure_features,
)
from exp_graph.mas.objective_metrics import primary_loss
from exp_graph.mas.role_llm import create_role_llm_client, resolve_role_llm_config
from exp_graph.mas.schemas import (
    EvidenceRecord,
    InsightReport,
    MASInsight,
    MASRuntimeConfig,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank


# 【职责】把证据压缩成提示词尺寸的 MAS 设计摘要(按拓扑汇总指标/动态/条件范围/结构特征)。
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
        prompt_rows = _record_prompt_rows(rows)
        topology_summaries[topology] = {
            "evidence_refs": [row.evidence_id for row in rows],
            "n_agents": sorted({row.n_agents for row in rows if row.n_agents}),
            "seeds": sorted({row.seed for row in rows if row.seed is not None}),
            "metrics": _metric_summary(rows),
            "dynamics": _dynamics_summary(rows),
            "condition_scope": infer_condition_scope(prompt_rows),
            "structure_features": infer_topology_structure_features(
                topology,
                prompt_rows,
            ),
            "topology_structures": topology_structures_from_records(rows),
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


# 【职责】LLM 洞见大臣：执行结束后生成"以证据为依据"的 MAS 设计洞见报告。
# - fake 平台走确定性报告；真实 LLM 失败时降级为只含一条被拒记录的报告。
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
        role_llm = resolve_role_llm_config(self.runtime, "minister")
        if role_llm.platform == "fake":
            return verify_insight_report(
                _deterministic_insight_report(evidence_pack, skill_bank)
            )
        try:
            client = self.llm_client or create_role_llm_client(self.runtime, "minister")
            response = client.complete(
                build_insight_prompt(evidence_pack=evidence_pack),
                model_name=role_llm.model_name,
                temperature=role_llm.temperature,
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


# 【职责】构建"只返回 JSON"的运行后洞见提取提示词(其中英文均为运行时提示词，勿改)。
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
            "Write each accepted structure-design lesson so it can be stored as a planner skill design_insight, not only as a metric summary.",
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


# 【职责】规则校验：洞见成为补丁候选前——缺证据引用即拒；单证据且非假设的降级为假设。
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


# 【职责】把已校验洞见转为"不直接写库"的补丁候选。
# - require_verified 默认 False，行为逐字节不变：每条非 rejected 且有更新内容的洞见都产补丁。
# - 为 True(--evolve 证伪后路径)时，仅 claim_status=="observed"(留出集证伪通过)的洞见产补丁。
def insight_report_to_patches(
    report: InsightReport,
    *,
    require_verified: bool = False,
) -> list[SkillPatch]:
    """Convert verified insights into non-writing patch candidates.

    ``require_verified`` is opt-in and defaults to ``False`` so the existing
    behavior is byte-identical: every non-``rejected`` insight that yields a
    non-empty update produces a patch. When ``True`` (the QueenBee ``--evolve``
    path after :func:`falsify_insights`), only insights whose held-out
    falsification check passed (``claim_status == "observed"``) emit patches;
    contradicted (``"rejected"``) and unverifiable (``"hypothesis"``/
    ``"inferred"``) insights are skipped so a plausible-but-wrong insight cannot
    become an accepted skill patch.
    """
    patches: list[SkillPatch] = []
    for insight in report.key_insights:
        if insight.claim_status == "rejected":
            continue
        if require_verified and insight.claim_status != "observed":
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


# 中文：这些操作 action_type 断言某拓扑是"好"(规划器应保留/选它)或"坏"(应弃用)。
#   mutate 与 validate 不作损失断言，只带这两类操作的洞见视为无可检验极性。
# Operation ``action_type`` values that assert a topology is *good* (planner
# should keep/choose it) versus *bad* (planner should drop it). ``mutate`` and
# ``validate`` make no loss claim, so an insight carrying only those is treated
# as having no checkable polarity.
_PREFER_ACTIONS: frozenset[str] = frozenset({"preserve", "prefer"})
_AVOID_ACTIONS: frozenset[str] = frozenset({"avoid"})

# 中文：越高越好的聚合指标名，比较前必须换算成统一的"越低越好"损失。
#   与 objective_metrics 保持一致，使成功率类基准也能正确证伪。
# Higher-is-better aggregate metric names that must be converted to a uniform
# lower-is-better loss before comparison. Mirrors objective_metrics so a
# success-rate benchmark falsifies correctly.
_HIGHER_IS_BETTER_ROW_KEYS: tuple[str, ...] = (
    "mean_success",
    "success_rate",
    "mean_primary",
    "exact_match_rate",
    "mean_partial",
)
# 中文：越低越好的损失列，按序尝试。mean_rmse 是跨种子聚合列；
#   final_rmse/rmse/loss 覆盖单次运行与本身已是损失的行。
# Lower-is-better loss columns, tried in order. ``mean_rmse`` is the cross-seed
# aggregate column; ``final_rmse``/``rmse``/``loss`` cover single-run and
# already-loss rows.
_LOWER_IS_BETTER_ROW_KEYS: tuple[str, ...] = (
    "loss",
    "primary_loss",
    "mean_rmse",
    "final_rmse",
    "rmse",
)


# 【职责】留出集证伪：LLM 洞见成为补丁前，用留出聚合行检验其可证伪的拓扑断言。
# - 断言"好"(preserve/prefer)成立当且仅当该拓扑在其条件内的损失 <= 同条件行的中位损失。
# - 断言"坏"(avoid)成立当且仅当其损失 >= 中位。通过→observed；被反驳→rejected 并记为反例。
# - 提取不出断言或缺相关行→保持 hypothesis(不可验证)；纯增量：默认流水线不调用则行为不变。
def falsify_insights(
    report: InsightReport,
    held_out_rows: list[dict[str, Any]],
) -> InsightReport:
    """Held-out falsification of LLM insights before they can become patches.

    For each :class:`MASInsight` we derive a *checkable* topology claim from its
    structured fields and test it against held-out aggregate ``held_out_rows``
    (the cross-seed ``conditions`` rows, each carrying ``topology_name``,
    optionally ``n_agents``/``array_size``, and a lower-is-better loss column).

    A claimed-good topology ``T`` (``preserve``/``prefer``) holds iff ``T``'s
    loss in its condition is ``<=`` the median loss of rows in that condition; a
    claimed-bad topology (``avoid``) holds iff ``T``'s loss is ``>=`` the median.
    On a verified claim ``claim_status`` becomes ``"observed"``; on a
    contradicted claim it becomes ``"rejected"`` and the insight is recorded as a
    counterexample; if the claim is not extractable or the relevant rows are
    missing it is left as ``"hypothesis"`` (unverifiable). Loosely-structured
    insights never crash -- they fall through to ``"hypothesis"``.

    This is purely additive: callers that never invoke it (the default pipeline)
    see no behavior change, and :func:`insight_report_to_patches` keeps emitting
    every non-rejected insight unless ``require_verified=True`` is passed.
    """
    checked: list[MASInsight] = []
    rejected = list(report.rejected_insights)
    for insight in report.key_insights:
        status = _falsify_one(insight, held_out_rows)
        if status is None:
            checked.append(insight)
            continue
        if status == "rejected":
            rejected.append(
                {
                    "insight_id": insight.insight_id,
                    "reason": "falsification_contradicted",
                    "summary": insight.summary,
                }
            )
        checked.append(insight.model_copy(update={"claim_status": status}))
    return report.model_copy(
        update={"key_insights": checked, "rejected_insights": rejected}
    )


# 【职责】证伪单条洞见：返回 observed/rejected/hypothesis；None 表示无可检断言、保持原状。
def _falsify_one(
    insight: MASInsight,
    held_out_rows: list[dict[str, Any]],
) -> str | None:
    """Return ``observed``/``rejected``/``hypothesis`` or ``None`` to leave as-is.

    ``None`` means "no checkable claim could be extracted" -- the insight is left
    untouched (still whatever status the upstream rule layer assigned, e.g.
    ``hypothesis``). Every extractable-but-unverifiable case returns the explicit
    ``"hypothesis"`` string.
    """
    claim = _extract_topology_claim(insight)
    if claim is None:
        # Loosely-structured insight: cannot derive a falsifiable prediction.
        return "hypothesis" if insight.claim_status != "rejected" else None
    topology, polarity, condition = claim
    rows = _rows_in_condition(held_out_rows, condition)
    losses = [loss for row in rows if (loss := _row_loss(row)) is not None]
    target_losses = [
        loss
        for row in rows
        if _row_topology_matches(row, topology)
        and (loss := _row_loss(row)) is not None
    ]
    if not losses or not target_losses:
        # Relevant rows missing => cannot verify.
        return "hypothesis"
    target_loss = fmean(target_losses)
    median_loss = _median(losses)
    if polarity == "good":
        verified = target_loss <= median_loss
    else:  # polarity == "bad"
        verified = target_loss >= median_loss
    return "observed" if verified else "rejected"


# 【职责】尽力从洞见提取(拓扑, 极性, 条件)三元组；识别不出拓扑则返回 None。
# - 拓扑依次取自：操作建议的 topology_name→受影响技能 id 反查→标题首词。
# - 极性取自操作 action_type(preserve/prefer=好, avoid=坏)；有拓扑无极性时默认"好"。
def _extract_topology_claim(
    insight: MASInsight,
) -> tuple[str, str, dict[str, Any]] | None:
    """Best-effort extraction of ``(topology, polarity, condition)`` from a claim.

    Topology token is read, in priority order, from: an explicit
    ``topology_name`` on an ``operation_recommendation``; the insight's
    ``affected_skills`` (mapping a ``cf_*`` skill id back to its topology); or
    the insight ``title``. Polarity (``"good"``/``"bad"``) is taken from the
    operation ``action_type`` (preserve/prefer => good, avoid => bad); if no
    operation carries a polarity but a topology is present we default to ``good``
    (the planner is being told to keep it). Returns ``None`` when no topology can
    be identified.
    """
    polarity = _claim_polarity(insight.operation_recommendations)
    topology = _topology_from_operations(insight.operation_recommendations)
    if topology is None:
        topology = _topology_from_skills(insight.affected_skills)
    if topology is None:
        topology = _topology_from_title(insight.title)
    if topology is None:
        return None
    condition = _condition_from_insight(insight)
    return topology, polarity or "good", condition


def _claim_polarity(operations: list[dict[str, Any]]) -> str | None:
    has_good = False
    has_bad = False
    for op in operations:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action_type", "")).strip().lower()
        if action in _PREFER_ACTIONS:
            has_good = True
        elif action in _AVOID_ACTIONS:
            has_bad = True
    if has_bad and not has_good:
        return "bad"
    if has_good and not has_bad:
        return "good"
    # Mixed or no polarity-bearing action: leave undecided (caller defaults).
    return None


def _topology_from_operations(operations: list[dict[str, Any]]) -> str | None:
    for op in operations:
        if not isinstance(op, dict):
            continue
        for source in (op, op.get("conditions")):
            if isinstance(source, dict):
                value = source.get("topology_name")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _topology_from_skills(affected_skills: list[str]) -> str | None:
    for skill_id in affected_skills:
        topology = _topology_from_skill_id(str(skill_id))
        if topology:
            return topology
    return None


# 中文：classify_topology 赋予这些稳定技能 id；此处做反查，
#   让只携带 affected_skills 的洞见仍可被检验。
# classify_topology assigns these stable skill ids; invert them so an insight
# that only carries ``affected_skills`` is still checkable.
_SKILL_ID_TOPOLOGY: dict[str, str] = {
    "cf_accuracy_peer_star": "one_peer_exponential_dag_star",
    "cf_budget_tree": "tree",
    "cf_middle_ground_mesh_star": "mesh_star",
}


def _topology_from_skill_id(skill_id: str) -> str | None:
    # Strip the condition-bucket suffix (``__a4arr128``) appended by
    # condition_specific_skill_id before matching.
    base = skill_id.split("__", 1)[0]
    if base in _SKILL_ID_TOPOLOGY:
        return _SKILL_ID_TOPOLOGY[base]
    # Generic fallback for ``cf_topology_<name>`` ids.
    prefix = "cf_topology_"
    if base.startswith(prefix) and len(base) > len(prefix):
        return base[len(prefix) :]
    return None


def _topology_from_title(title: str) -> str | None:
    # The deterministic minister titles read ``"<topology> tradeoff ..."`` /
    # ``"<topology> has reusable risk boundary"``; take the leading token only if
    # it is a known topology to avoid grabbing generic advice titles.
    head = title.strip().split(" ", 1)[0] if title else ""
    known = set(_SKILL_ID_TOPOLOGY.values())
    return head if head in known else None


def _condition_from_insight(insight: MASInsight) -> dict[str, Any]:
    for bucket in insight.condition_buckets:
        if isinstance(bucket, dict) and bucket:
            return bucket
    return {}


# 【职责】按洞见的条件桶(agent/数组规模范围)筛选留出行；无条件则全部行在范围内。
def _rows_in_condition(
    rows: list[dict[str, Any]],
    condition: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filter held-out rows to the insight's condition bucket when one is given.

    Matches on ``n_agents``/``array_size`` ranges from an ``infer_condition_scope``
    bucket (``min_agents``/``max_agents``/``min_array_size``/``max_array_size``).
    With no condition (or no range keys) every row is in scope ("overall").
    """
    if not condition:
        return list(rows)
    min_agents = _as_int(condition.get("min_agents"))
    max_agents = _as_int(condition.get("max_agents"))
    min_array = _as_int(condition.get("min_array_size"))
    max_array = _as_int(condition.get("max_array_size"))
    if (
        min_agents is None
        and max_agents is None
        and min_array is None
        and max_array is None
    ):
        return list(rows)
    selected: list[dict[str, Any]] = []
    for row in rows:
        n_agents = _as_int(row.get("n_agents"))
        if n_agents is not None:
            if min_agents is not None and n_agents < min_agents:
                continue
            if max_agents is not None and n_agents > max_agents:
                continue
        array_size = _as_int(row.get("array_size"))
        if array_size is not None and (min_array is not None or max_array is not None):
            if min_array is not None and array_size < min_array:
                continue
            if max_array is not None and array_size > max_array:
                continue
        selected.append(row)
    return selected


def _row_topology_matches(row: dict[str, Any], topology: str) -> bool:
    return str(row.get("topology_name", "")) == topology


# 【职责】把一行留出聚合行归一为"越低越好"的损失：优先低优列，否则换算首个高优列。
def _row_loss(row: dict[str, Any]) -> float | None:
    """Uniform lower-is-better loss for one held-out aggregate row.

    Prefers an explicit lower-is-better column; otherwise converts the first
    available higher-is-better column via the shared ``primary_loss`` rule.
    """
    for key in _LOWER_IS_BETTER_ROW_KEYS:
        value = row.get(key)
        if value is not None:
            return float(value)
    for key in _HIGHER_IS_BETTER_ROW_KEYS:
        value = row.get(key)
        if value is not None:
            return primary_loss(key, float(value))
    return None


def _median(values: list[float]) -> float:
    return float(median(values))


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# 【职责】fake 平台的确定性洞见报告：按拓扑生成"权衡"与"风险边界"两类洞见。
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


# 【职责】按洞见类型映射为技能卡字段更新(理由规则/动态/风险注记/假设/验证计划等)。
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
    update = _attach_operation_update(update, insight)
    return _attach_design_insight_update(update, insight)


def _attach_design_insight_update(
    update: dict[str, object],
    insight: MASInsight,
) -> dict[str, object]:
    merged = dict(update)
    merged["design_insights"] = [
        {
            "insight_id": insight.insight_id,
            "insight_type": insight.insight_type,
            "claim_status": insight.claim_status,
            "title": insight.title,
            "summary": insight.summary,
            "evidence_refs": insight.evidence_refs,
            "metric_snapshot": insight.metric_snapshot,
            "recommended_actions": insight.recommended_actions,
            "operation_recommendations": insight.operation_recommendations,
            "condition_buckets": insight.condition_buckets,
            "confidence": insight.confidence,
            "falsification_test": insight.falsification_test,
        }
    ]
    return merged


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


# 【职责】返回确定性、提示词尺寸的已执行拓扑结构集合：必含最好与最坏，按哈希序补齐至上限。
def topology_structures_from_records(
    rows: list[EvidenceRecord],
    *,
    limit: int = 4,
) -> list[dict[str, object]]:
    """Return a deterministic, prompt-sized set of executed topology structures."""
    by_hash: dict[str, dict[str, object]] = {}
    for row in rows:
        structure = row.metrics.get("topology_structure")
        if not isinstance(structure, dict):
            continue
        structure_hash = str(
            structure.get("structure_hash")
            or row.metrics.get("topology_structure_hash")
            or ""
        )
        if not structure_hash:
            continue
        item = by_hash.setdefault(
            structure_hash,
            {
                "structure": structure,
                "evidence_refs": [],
                "rmse_values": [],
            },
        )
        refs = item["evidence_refs"]
        if isinstance(refs, list):
            refs.append(row.evidence_id)
        score = _record_metric_value(row, "mean_rmse", "final_rmse")
        scores = item["rmse_values"]
        if isinstance(scores, list) and score is not None:
            scores.append(score)

    candidates = []
    for structure_hash, item in by_hash.items():
        scores = item["rmse_values"]
        mean_rmse = fmean(scores) if isinstance(scores, list) and scores else None
        structure = dict(item["structure"]) if isinstance(item["structure"], dict) else {}
        structure["evidence_refs"] = sorted(
            str(ref) for ref in item["evidence_refs"] if ref is not None
        )
        if mean_rmse is not None:
            structure["mean_rmse"] = mean_rmse
        candidates.append(
            (
                mean_rmse if mean_rmse is not None else float("inf"),
                structure_hash,
                structure,
            )
        )
    if not candidates:
        return []

    selected: dict[str, dict[str, object]] = {}
    best = min(candidates, key=lambda item: (item[0], item[1]))
    worst = max(candidates, key=lambda item: (item[0], item[1]))
    for _, structure_hash, structure in [best, worst]:
        selected[structure_hash] = structure
    for _, structure_hash, structure in sorted(candidates, key=lambda item: item[1]):
        if len(selected) >= limit:
            break
        selected.setdefault(structure_hash, structure)
    return [selected[key] for key in sorted(selected)]


def _record_metric_value(row: EvidenceRecord, *keys: str) -> float | None:
    for key in keys:
        value = row.metrics.get(key)
        if value is not None:
            return float(value)
    return None


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
