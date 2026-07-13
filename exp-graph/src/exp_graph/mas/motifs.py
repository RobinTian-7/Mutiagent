"""Structural-motif credit attribution for generated temporal DAGs.

Plan 3 Part G.  QueenBee historically attributes evidence (loss, cost) to a
whole *topology name* or an opaque equivalence hash.  That blocks knowledge
reuse: a structurally-novel generated DAG -- different agent count, different
labels, a never-before-seen exact shape -- shares no name/hash with any past
winner, so it inherits nothing, even when it reuses well-understood
*sub-structure* (e.g. "a high-fan-in gather into one sink").

This module factors a :class:`~exp_graph.protocols.ProtocolGraphSpec` (the
temporal-DAG representation: ``spec.steps[i].transmissions`` is the list of
``(src, dst)`` edges fired simultaneously in round ``i``) into a small set of
interpretable, label-invariant **structural motifs**.  Each motif becomes a
canonical ``"feature=value"`` attribution key.  Evidence is then aggregated
*per motif key*, and a possibly-novel spec is scored by the evidence-weighted
mean loss of the motif keys it shares with past evidence.  Credit therefore
transfers structurally rather than by name.

All features are small hashable values (``str`` / ``int`` / ``bool``) so they
serialize cleanly into evidence rows and skill metadata.

This module is purely additive and does not change planner selection.  See the
``# Activation:`` note in ``exp_graph.mas.graph_generation`` for where a live
graph-candidate scorer could call :func:`score_spec_by_motifs`.
"""
# ============================================================
# 【模块导读】生成式时序 DAG 的结构母题信用归因(Plan 3 Part G)。
# 旧做法把证据(损失/成本)记到整个拓扑名或不透明等价哈希上：结构新颖的生成
# DAG 与历史赢家不共享名字/哈希，即便复用成熟子结构(如高汇入边数聚进单一
# 汇点)也继承不到信用。本模块把 ProtocolGraphSpec(steps[i].transmissions 为
# 第 i 轮同时发射的 (src,dst) 边)分解为可解释、标签不变的结构母题；母题成为
# 规范化 "feature=value" 归因键，证据按键聚合，新颖 spec 以共享键的证据加权
# 平均损失打分——信用按结构而非名字迁移。特征均为小的可哈希标量，序列化干净。
# 本模块纯增量、不改变规划器选择；激活点见 graph_generation 的说明注释。
# ============================================================

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Sequence

from exp_graph.protocols import ProtocolGraphSpec

# 中文：按优先级从证据行读取的损失键。mean_primary_loss 是通用基准产出的统一
#   "越低越好"损失；仅 CF 证据带 mean_rmse。两者都是越低越好
#   (见 scoring.primary_loss_metric)，可原样互换接入。
# Loss keys read from evidence rows, in priority order.  ``mean_primary_loss``
# is the uniform lower-is-better loss produced by generic benchmarks; CF-only
# evidence carries ``mean_rmse``.  Both are lower-is-better (see
# ``exp_graph.mas.scoring.primary_loss_metric``), so either slots in unchanged.
_LOSS_KEYS: tuple[str, ...] = ("mean_primary_loss", "mean_rmse")


# 【职责】从 spec 提取可解释、标签不变的结构母题字典(值为小的可哈希标量)。
# - 只由时序 DAG 的逐步 (src,dst) 传输计算：重标号的同构 DAG 母题相同
# - n_steps=轮数；max_receiver_fan_in=单步单接收者最大汇入边数；
#   fan_in_bucket=其粗桶(low<=2/med<=4/high，桶才是跨规模可迁移的母题)
# - has_sink/sink_count=汇点(收过边且此后不再发送的最终持有者；
#   selected_primary 恒计入)；has_audit_edges=是否存在冗余回传审计边
# - reduction_depth=首次有单个 agent 覆盖全部证据 agent 的轮次(归约树高；
#   永不全覆盖回退 n_steps，空调度为 0)；total_messages=总有向消息数
def extract_motifs(spec: ProtocolGraphSpec) -> dict[str, object]:
    """Return interpretable, label-invariant structural motifs for ``spec``.

    Each value is a small hashable scalar (``str`` / ``int`` / ``bool``).  The
    features are computed purely from the temporal DAG -- the per-step
    ``(src, dst)`` transmissions -- so two structurally identical DAGs with the
    agents relabeled produce the same motifs.

    Features
    --------
    ``n_steps``
        Number of communication rounds.
    ``max_receiver_fan_in``
        Largest number of distinct incoming edges any single agent receives in
        any one step (peak per-step reducer width).
    ``fan_in_bucket``
        Coarse bucket of ``max_receiver_fan_in``: ``"low"`` (<=2),
        ``"med"`` (<=4), else ``"high"``.  The bucket is the reusable motif
        (exact widths rarely transfer across agent counts; "is there a wide
        gather" does).
    ``has_sink`` / ``sink_count``
        A *sink* is a final holder: an agent that receives at least one edge and
        never sends on any *later* step than its last received edge.  The
        ``selected_primary`` (declared final answer holder) is always counted as
        a sink when present.  ``has_sink`` is ``sink_count >= 1``.
    ``has_audit_edges``
        Whether any edge is a redundant *back-coverage / audit* edge: an edge
        ``(src, dst)`` where, before that step, ``src`` already transitively
        covers ``dst`` (so ``dst``'s own evidence is already inside ``src``'s
        artifact).  Sending it back is provenance/audit, not forward reduction.
    ``reduction_depth``
        The 1-based round index by which some single agent first covers every
        agent that ever produced or held evidence (the reduction "tree height").
        Falls back to ``n_steps`` when no single holder ever achieves full
        coverage.  ``0`` for an empty schedule.
    ``total_messages``
        Total directed transmissions across all steps.
    """
    steps = _normalized_steps(spec)
    n_agents = int(spec.n_agents)
    selected_primary = _optional_int(spec.metadata.get("selected_primary"))

    n_steps = len(steps)
    total_messages = sum(len(edges) for edges in steps)
    max_fan_in = _max_receiver_fan_in(steps)
    coverage_history = _coverage_history(steps, n_agents)
    sink_count = _sink_count(steps, n_agents, selected_primary)

    return {
        "n_steps": n_steps,
        "max_receiver_fan_in": max_fan_in,
        "fan_in_bucket": _fan_in_bucket(max_fan_in),
        "has_sink": sink_count >= 1,
        "sink_count": sink_count,
        "has_audit_edges": _has_audit_edges(steps, n_agents),
        "reduction_depth": _reduction_depth(steps, n_agents, coverage_history),
        "total_messages": total_messages,
    }


# 【职责】把母题字典转成规范化 "feature=value" 归因键列表(排序保证确定性)。
# - 布尔归一化为小写 true/false，其余取 str(value)；同构 spec 键集相同
def motif_feature_keys(motifs: dict[str, object]) -> list[str]:
    """Return canonical ``"feature=value"`` attribution tokens for ``motifs``.

    Booleans normalize to ``true`` / ``false`` (lower-case) and every other
    value to ``str(value)``.  The list is sorted so it is deterministic and so
    structurally identical specs yield identical key sets regardless of dict
    iteration order.  Example::

        ["depth=2", "fan_in_bucket=low", "has_audit_edges=false",
         "has_sink=true", "max_receiver_fan_in=1", "n_steps=2",
         "sink_count=1", "total_messages=3"]
    """
    keys: list[str] = []
    for name in sorted(motifs):
        keys.append(f"{name}={_token_value(motifs[name])}")
    return keys


# 【职责】便捷入口：一次调用取得 spec 的结构母题归因键列表。
def spec_motif_keys(spec: ProtocolGraphSpec) -> list[str]:
    """Convenience: motif attribution keys for a spec in one call."""
    return motif_feature_keys(extract_motifs(spec))


# 【职责】按结构母题键聚合"越低越好"损失，返回 {键: {mean_loss, n}}。
# - 每行损失优先取 mean_primary_loss，否则 mean_rmse
# - 母题键按先到先得取自 row["motif_keys"](预计算)、row["protocol_spec"]
#   (序列化 spec)或 row["spec"](活对象)；无损失或无母题键的行跳过
# - n 为参与行数，mean_loss 为其算术平均损失
def aggregate_motif_losses(rows: Iterable[dict]) -> dict[str, dict]:
    """Aggregate lower-is-better loss per structural-motif key.

    Each evidence ``row`` supplies a loss (``mean_primary_loss`` preferred, else
    ``mean_rmse``) and a set of motif keys, taken from whichever of these the
    row carries (first match wins):

    * ``row["motif_keys"]`` -- a precomputed list of ``"feature=value"`` tokens;
    * ``row["protocol_spec"]`` -- a serialized :class:`ProtocolGraphSpec`;
    * ``row["spec"]`` -- a live :class:`ProtocolGraphSpec`.

    Returns ``{key: {"mean_loss": float, "n": int}}`` where ``n`` is the number
    of contributing rows and ``mean_loss`` their arithmetic mean loss.  Rows
    without a usable loss or without any motif key are skipped.
    """
    sums: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for row in rows:
        loss = _row_loss(row)
        if loss is None:
            continue
        for key in _row_motif_keys(row):
            sums[key] += loss
            counts[key] += 1
    return {
        key: {"mean_loss": sums[key] / counts[key], "n": int(counts[key])}
        for key in counts
    }


# 【职责】用母题证据预测 spec 的"越低越好"损失——结构母题信用先验的打分核心。
# - 对 spec 与 motif_stats 共享的母题键按样本数 n 加权平均：
#   score = sum(n_k*mean_loss_k)/sum(n_k)；被更多赢家背书的母题权重更大
# - 键标签不变，新颖 spec(新 agent 数/新形状)可经共享母题继承历史信用，
#   如未见过的 7 agent 星形收束经 fan_in_bucket=high 继承 5/6 agent 的低损失
# - 与统计无任何共享键(或统计为空)时返回 float("inf") 高不确定性哨兵，
#   由调用方处理(如回退探针评测，而非轻信凭空的低损失)
def score_spec_by_motifs(
    spec: ProtocolGraphSpec,
    motif_stats: dict[str, dict],
    *,
    uncertainty_kappa: float = 0.0,
) -> float:
    """Predict a lower-is-better loss for ``spec`` from motif evidence.

    The prediction is the evidence-weighted mean of ``mean_loss`` over the
    spec's motif keys that appear in ``motif_stats``, weighting each key by its
    sample count ``n`` (a motif backed by more winners counts more)::

        score = sum_k n_k * mean_loss_k / sum_k n_k   over shared keys k

    Lower = predicted better.  Because the keys are structural and
    label-invariant, a *novel* spec (new agent count, new labels, unseen exact
    shape) inherits credit from past winners through the motifs they share --
    e.g. a never-seen 7-agent star gather inherits the low loss accumulated by
    5- and 6-agent star gathers via the shared ``fan_in_bucket=high`` key.

    When the spec shares **no** known motif key with ``motif_stats`` (or the
    stats are empty), no evidence applies, so this returns a neutral
    high-uncertainty sentinel ``float("inf")`` for the caller to handle (e.g.
    fall back to a probe evaluation rather than trusting a fabricated low loss).
    """
    keys = spec_motif_keys(spec)
    weighted_sum = 0.0
    weight_total = 0.0
    for key in keys:
        entry = motif_stats.get(key)
        if not entry:
            continue
        n = float(entry.get("n", 0) or 0)
        if n <= 0.0:
            continue
        # 中文：uncertainty_kappa>0 时按 LCB 风格对每键信用做悲观修正：
        #   1 次幸运运行的母题记 mean+kappa，16 样本老将记 mean+kappa/4。
        #   否则唯一命中键为"1 次运行损失 0"的 spec 会压过所有实测充分的冠军
        #   (轮次曲线上的"冠军翻转"不稳定)。默认 0.0 与历史行为逐字节一致。
        # ``uncertainty_kappa`` > 0 makes the per-key credit pessimistic
        # (LCB-style): a motif backed by one lucky run scores mean + kappa
        # while a 16-sample veteran scores mean + kappa/4. Without it, a spec
        # whose ONLY matched key is a 1-run loss-0 motif outranks every
        # well-measured champion (the rounds-curve "champion flip"
        # instability). Default 0.0 keeps historical behavior byte-identical.
        adjusted = float(entry["mean_loss"]) + (
            uncertainty_kappa / math.sqrt(n) if uncertainty_kappa > 0.0 else 0.0
        )
        weighted_sum += n * adjusted
        weight_total += n
    if weight_total <= 0.0:
        return math.inf
    return weighted_sum / weight_total


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


# 【职责】把 spec 各步传输去重并 int 化，得到规范逐步边表。
def _normalized_steps(spec: ProtocolGraphSpec) -> list[list[tuple[int, int]]]:
    """Per-step deduped, int-cast edge lists from a spec."""
    steps: list[list[tuple[int, int]]] = []
    for step in spec.steps:
        seen: set[tuple[int, int]] = set()
        edges: list[tuple[int, int]] = []
        for src, dst in step.transmissions:
            edge = (int(src), int(dst))
            if edge in seen:
                continue
            seen.add(edge)
            edges.append(edge)
        steps.append(edges)
    return steps


# 【职责】全调度内"单步单接收者"的最大汇入边数(峰值归约宽度)。
def _max_receiver_fan_in(steps: Sequence[Sequence[tuple[int, int]]]) -> int:
    best = 0
    for edges in steps:
        fan_in: Counter[int] = Counter()
        for _src, dst in edges:
            fan_in[dst] += 1
        if fan_in:
            best = max(best, max(fan_in.values()))
    return best


# 【职责】汇入边数粗桶：<=2 为 low，<=4 为 med，否则 high。
def _fan_in_bucket(max_fan_in: int) -> str:
    if max_fan_in <= 2:
        return "low"
    if max_fan_in <= 4:
        return "med"
    return "high"


# 【职责】覆盖历史：每步之后各 agent 所覆盖的 agent 集合快照。
# - 初始各自只覆盖自己；边 (src,dst) 使 dst 获得 src 截至上一步的覆盖
#   (同时语义：接收者用不到其他接收者同步内的更新)
def _coverage_history(
    steps: Sequence[Sequence[tuple[int, int]]],
    n_agents: int,
) -> list[dict[int, frozenset[int]]]:
    """Coverage set held by each agent *after* each step.

    Each agent starts covering only itself.  When edge ``(src, dst)`` fires in a
    step, ``dst`` gains everything ``src`` covered *as of the previous step*
    (simultaneous semantics: receivers cannot use another receiver's same-step
    update).  Returns one ``{agent: frozenset(covered_agents)}`` snapshot per
    step.
    """
    coverage = {agent: frozenset({agent}) for agent in range(n_agents)}
    history: list[dict[int, frozenset[int]]] = []
    for edges in steps:
        updates = {agent: set(values) for agent, values in coverage.items()}
        for src, dst in edges:
            if src in coverage and dst in updates:
                updates[dst] |= coverage[src]
        coverage = {agent: frozenset(values) for agent, values in updates.items()}
        history.append(coverage)
    return history


# 【职责】归约深度：首个"某单一 agent 覆盖全部证据 agent"的 1 基轮次。
# - 证据 agent=曾作为源或目的出现者；从不通信的孤立 agent 不计，
#   稀疏调度在大 n_agents 下不会被误判为永不归约
# - 永不全覆盖时回退 n_steps；空调度为 0
def _reduction_depth(
    steps: Sequence[Sequence[tuple[int, int]]],
    n_agents: int,
    coverage_history: Sequence[dict[int, frozenset[int]]],
) -> int:
    """First 1-based round where one agent covers every evidence-bearing agent.

    Evidence-bearing agents are those that ever appear as a source or
    destination (isolated agents that never communicate are ignored so a sparse
    schedule over a large ``n_agents`` is not penalized as never-reducing).
    Falls back to ``n_steps`` when full coverage is never reached.  ``0`` for an
    empty schedule.
    """
    if not steps:
        return 0
    participants = {
        agent
        for edges in steps
        for edge in edges
        for agent in edge
    }
    if not participants:
        return len(steps)
    target = frozenset(participants)
    for round_idx, coverage in enumerate(coverage_history, start=1):
        if any(target <= covered for covered in coverage.values()):
            return round_idx
    return len(steps)


# 【职责】统计汇点(最终持有者)数量。
# - 汇点=收过至少一条边、且其最后收边之后不再发送的 agent；
#   声明的 selected_primary 恒计为汇点(自动去重)
def _sink_count(
    steps: Sequence[Sequence[tuple[int, int]]],
    n_agents: int,
    selected_primary: int | None,
) -> int:
    """Count final holders.

    An agent is a sink if it receives at least one edge and never sends on any
    step strictly *after* its last received edge.  The declared
    ``selected_primary`` is always counted as a sink (deduped).
    """
    last_in: dict[int, int] = {}
    last_out: dict[int, int] = {}
    for step_idx, edges in enumerate(steps):
        for src, dst in edges:
            last_out[src] = step_idx
            last_in[dst] = step_idx
    sinks: set[int] = set()
    for agent, in_step in last_in.items():
        out_step = last_out.get(agent)
        if out_step is None or out_step <= in_step:
            sinks.add(agent)
    if selected_primary is not None and 0 <= selected_primary < n_agents:
        sinks.add(selected_primary)
    return len(sinks)


# 【职责】是否存在冗余的"回覆盖/审计"边。
# - 若截至上一步 src 已传递覆盖 dst(dst 的证据早已流入 src)，再发 (src,dst)
#   不带来前向归约，属于溯源/审计/修复边
def _has_audit_edges(
    steps: Sequence[Sequence[tuple[int, int]]],
    n_agents: int,
) -> bool:
    """Whether any edge is a redundant back-coverage / audit edge.

    Edge ``(src, dst)`` is back-coverage if, as of the *previous* step, ``src``
    already transitively covers ``dst`` -- i.e. ``dst``'s own evidence has
    already flowed into ``src``.  Sending ``src``'s artifact back to ``dst`` then
    adds no forward reduction; it is a provenance/audit/repair edge.
    """
    coverage = {agent: frozenset({agent}) for agent in range(n_agents)}
    for edges in steps:
        for src, dst in edges:
            if src in coverage and dst in coverage[src]:
                return True
        updates = {agent: set(values) for agent, values in coverage.items()}
        for src, dst in edges:
            if src in coverage and dst in updates:
                updates[dst] |= coverage[src]
        coverage = {agent: frozenset(values) for agent, values in updates.items()}
    return False


def _row_loss(row: dict) -> float | None:
    for key in _LOSS_KEYS:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _row_motif_keys(row: dict) -> list[str]:
    precomputed = row.get("motif_keys")
    if isinstance(precomputed, (list, tuple)):
        return [str(key) for key in precomputed]
    spec = _row_spec(row)
    if spec is not None:
        return spec_motif_keys(spec)
    return []


def _row_spec(row: dict) -> ProtocolGraphSpec | None:
    live = row.get("spec")
    if isinstance(live, ProtocolGraphSpec):
        return live
    spec_data = row.get("protocol_spec")
    if isinstance(spec_data, ProtocolGraphSpec):
        return spec_data
    if isinstance(spec_data, dict):
        try:
            return ProtocolGraphSpec.model_validate(spec_data)
        except Exception:
            return None
    return None


def _token_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
