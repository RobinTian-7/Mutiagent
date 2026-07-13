"""Scoring helpers for emperor topology-skill selection."""

# ============================================================
# 【模块导读】皇帝(规划 LLM)选择拓扑技能时的评分辅助。
# - 读取技能的主损失(越低越好)/成本/稳定性指标，做同伴 min-max 归一化后按
#   目标权重加权；支持 LCB 不确定性惩罚(mean+kappa*std/sqrt(n))压低幸运技能。
# ============================================================
from __future__ import annotations

import math
from collections.abc import Iterable

from exp_graph.mas.schemas import ObjectiveSpec, SkillCard

# 中文：LCB(下置信界)惩罚权重 kappa 的模块级默认值。0.0 使 score_skill 与
#   纯均值行为逐字节一致；调用方传入正的 uncertainty_weight 或设置
#   ObjectiveSpec.uncertainty_weight 才会启用。
# Module-level default for the lower-confidence-bound (LCB) penalty weight
# (kappa). ``0.0`` keeps ``score_skill`` byte-identical to the plain-mean
# behavior; callers opt in by passing a positive ``uncertainty_weight`` or by
# setting ``ObjectiveSpec.uncertainty_weight``.
DEFAULT_UNCERTAINTY_WEIGHT = 0.0


# 【职责】把数值相对序列做 [0,1] min-max 归一化；invert=True 表示越低越好(得分取反)。
# - 空序列返回 0.0；序列全体相同返回 1.0。
def min_max_normalize(value: float, values: Iterable[float], *, invert: bool) -> float:
    """Return a [0, 1] normalized score, optionally treating lower as better."""
    series = [float(item) for item in values]
    if not series:
        return 0.0
    low = min(series)
    high = max(series)
    if high == low:
        return 1.0
    normalized = (float(value) - low) / (high - low)
    return 1.0 - normalized if invert else normalized


# 【职责】读技能数值指标：优先 expected_tradeoff，否则取最新一条含该键的证据。
def skill_metric(skill: SkillCard, key: str, default: float = 0.0) -> float:
    """Read a numeric metric from the newest evidence entry that contains it."""
    if key in skill.expected_tradeoff and skill.expected_tradeoff[key] is not None:
        return float(skill.expected_tradeoff[key])
    for evidence in reversed(skill.evidence):
        if key in evidence and evidence[key] is not None:
            return float(evidence[key])
    return default


# 【职责】读技能"越低越好"的主损失精度信号。
# - 通用基准存转换后的 mean_primary_loss(如 Silo-Bench 成功率 -> 1-success)；
# - count_frequency 技能只带 mean_rmse；两者皆越低越好，下游归一化处理完全一致。
def primary_loss_metric(skill: SkillCard, default: float = 1e9) -> float:
    """Read the lower-is-better accuracy signal for a skill.

    Generic benchmarks store a converted ``mean_primary_loss`` (e.g. Silo-Bench
    success-rate -> ``1 - success``); count-frequency skills only carry
    ``mean_rmse``. Both are lower-is-better, so downstream normalization is
    identical regardless of which one supplied the value.
    """
    if _has_metric(skill, "mean_primary_loss"):
        return skill_metric(skill, "mean_primary_loss", default=default)
    return skill_metric(skill, "mean_rmse", default=default)


# 【职责】判断 expected_tradeoff 或任一证据中是否存在该指标键。
def _has_metric(skill: SkillCard, key: str) -> bool:
    if key in skill.expected_tradeoff and skill.expected_tradeoff[key] is not None:
        return True
    return any(
        key in evidence and evidence[key] is not None for evidence in skill.evidence
    )


# 【职责】读主损失的离散度(std)。
# - 与 primary_loss_metric 对应：优先 std_primary_loss(转换后通用损失的离散度)，
#   否则回退 std_rmse(CF/整合流水线今天唯一记录的离散度)；两者描述同一越低越好
#   损失，LCB 不确定性惩罚因此在一致的尺度上计算。
def primary_loss_std(skill: SkillCard, default: float = 0.0) -> float:
    """Read the spread of the lower-is-better accuracy signal for a skill.

    Mirrors :func:`primary_loss_metric`: prefer ``std_primary_loss`` (the spread
    of the converted generic loss) when present, otherwise fall back to
    ``std_rmse`` (the only spread the CF/consolidation pipeline records today).
    Both describe the same lower-is-better loss, so the LCB penalty is computed
    on a consistent scale regardless of which one supplied the value.
    """
    if _has_metric(skill, "std_primary_loss"):
        return skill_metric(skill, "std_primary_loss", default=default)
    return skill_metric(skill, "std_rmse", default=default)


# 【职责】读技能指标背后的独立观测数 n(LCB 标准误项使用)。
# - 优先 confidence.seed_count(不同种子数)，其次 confidence/expected_tradeoff 的
#   active_evidence_count(聚合行数)，最后回退原始证据条数；恒不低于 1，
#   保证 sqrt(n) 有定义。
def evidence_sample_count(skill: SkillCard, default: int = 1) -> int:
    """Read the number of independent observations behind a skill's metrics.

    Prefers ``confidence.seed_count`` (distinct seeds), then
    ``confidence.active_evidence_count`` / ``expected_tradeoff
    .active_evidence_count`` (aggregate rows), then the raw evidence list.
    Used as ``n`` in the LCB standard-error term. Never returns below ``1`` so
    ``sqrt(n)`` is well defined.
    """
    for source, key in (
        (skill.confidence, "seed_count"),
        (skill.confidence, "active_evidence_count"),
        (skill.expected_tradeoff, "active_evidence_count"),
    ):
        value = source.get(key)
        if value is not None:
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count > 0:
                return count
    if skill.evidence:
        return len(skill.evidence)
    return max(1, default)


# 【职责】返回悲观(损失上置信界)的精度主损失。
# - loss_lcb = mean_loss + kappa*std/sqrt(max(1,n))；kappa==0 时恰为 mean_loss，
#   下游归一化不变；高 std 和/或很小的 n 会抬高损失，压低"幸运"高方差技能。
def lcb_primary_loss(
    skill: SkillCard,
    *,
    uncertainty_weight: float,
    default: float = 1e9,
) -> float:
    """Return a pessimistic (upper-confidence-bound) accuracy *loss*.

    ``loss_lcb = mean_loss + kappa * std / sqrt(max(1, n))``. With
    ``uncertainty_weight`` (kappa) ``== 0`` this is exactly ``mean_loss`` so
    downstream normalization is unchanged. A high ``std`` and/or tiny ``n``
    inflate the loss, demoting "lucky" high-variance skills.
    """
    mean_loss = primary_loss_metric(skill, default=default)
    if uncertainty_weight <= 0.0:
        return mean_loss
    std = primary_loss_std(skill, default=0.0)
    n = evidence_sample_count(skill, default=1)
    return mean_loss + uncertainty_weight * std / math.sqrt(max(1, n))


# 【职责】对单个技能相对同伴(peers)按目标加权评分，返回(总分, 分解字典)。
# - uncertainty_weight(kappa)控制精度项的 LCB 不确定性惩罚：归一化前先把精度信号
#   换成悲观损失 mean_loss + kappa*std/sqrt(max(1,n))，使高方差/小样本的"幸运"
#   技能相对稳定技能被压低；
# - kappa 为 None(默认)时读 ObjectiveSpec.uncertainty_weight，否则用模块默认 0.0；
#   kappa==0 时 LCB 损失等于均值损失，本函数与纯均值行为逐字节一致；
# - 分解字典：accuracy/cost/stability 为同伴归一化得分；rmse/token_cost/messages/
#   std_rmse 为原始指标；uncertainty_*/loss_lcb 为追加的不确定性诊断字段。
def score_skill(
    skill: SkillCard,
    *,
    objective: ObjectiveSpec,
    peers: list[SkillCard],
    uncertainty_weight: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Score one skill against peer skills for the requested objective.

    ``uncertainty_weight`` (kappa) controls a lower-confidence-bound (LCB)
    penalty on the accuracy term: the accuracy signal becomes a pessimistic
    loss ``mean_loss + kappa * std / sqrt(max(1, n))`` before normalization, so
    a high-variance / tiny-sample "lucky" skill is demoted relative to a stable
    one. When ``None`` (the default) the weight is read from
    ``ObjectiveSpec.uncertainty_weight`` if present, else the module default
    ``0.0``. With kappa == 0 the LCB loss equals ``mean_loss`` and this function
    is byte-identical to the plain-mean behavior.
    """
    if uncertainty_weight is None:
        uncertainty_weight = float(
            getattr(objective, "uncertainty_weight", DEFAULT_UNCERTAINTY_WEIGHT)
        )

    rmse = primary_loss_metric(skill, default=1e9)
    token_cost = skill_metric(skill, "mean_token_cost", default=1e9)
    messages = skill_metric(skill, "mean_messages", default=1e9)
    std_rmse = skill_metric(skill, "std_rmse", default=0.0)
    loss_lcb = lcb_primary_loss(
        skill, uncertainty_weight=uncertainty_weight, default=1e9
    )
    loss_lcb_values = [
        lcb_primary_loss(item, uncertainty_weight=uncertainty_weight, default=1e9)
        for item in peers
    ]
    token_values = [skill_metric(item, "mean_token_cost", default=1e9) for item in peers]
    message_values = [skill_metric(item, "mean_messages", default=1e9) for item in peers]
    std_values = [skill_metric(item, "std_rmse", default=0.0) for item in peers]

    accuracy_score = min_max_normalize(loss_lcb, loss_lcb_values, invert=True)
    token_score = min_max_normalize(token_cost, token_values, invert=True)
    message_score = min_max_normalize(messages, message_values, invert=True)
    cost_score = (token_score + message_score) / 2.0
    stability_score = min_max_normalize(std_rmse, std_values, invert=True)

    score = (
        objective.accuracy_weight * accuracy_score
        + objective.cost_weight * cost_score
        + objective.stability_weight * stability_score
    )
    return score, {
        "accuracy": accuracy_score,
        "cost": cost_score,
        "stability": stability_score,
        "rmse": rmse,
        "token_cost": token_cost,
        "messages": messages,
        "std_rmse": std_rmse,
        # 中文：追加的不确定性诊断键；上面的既有键保持不变。
        # Additive uncertainty diagnostics; existing keys above are unchanged.
        "uncertainty_weight": uncertainty_weight,
        "uncertainty_std": primary_loss_std(skill, default=0.0),
        "uncertainty_n": float(evidence_sample_count(skill, default=1)),
        "loss_lcb": loss_lcb,
    }
