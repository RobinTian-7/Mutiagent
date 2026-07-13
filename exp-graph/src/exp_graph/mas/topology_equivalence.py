"""Temporal topology equivalence helpers for generated MAS protocols."""
# ============================================================
# 【模块导读】生成式 MAS 协议的时序拓扑等价工具(等价拓扑指纹去重的基础)。
# 为协议规范构建两种稳定哈希：exact_execution_hash(带原始标号的精确执行哈希)
# 与 topology_equivalence_hash(标签不变哈希，基于"初始着色+迭代颜色精化+
# 同色组内枚举重标号"得到的字典序最小规范时序边表)。
# 供候选(DAG)去重、重放(历史结构)识别与技能归因使用。
# ============================================================

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from exp_graph.protocols import ProtocolGraphSpec

TemporalEdge = tuple[int, int, int]


# 【职责】单个时序拓扑的稳定指纹：等价哈希+精确执行哈希+规范时序边表。
@dataclass(frozen=True)
class TopologyFingerprint:
    """Stable hashes and canonical forms for one temporal topology."""

    topology_equivalence_hash: str
    exact_execution_hash: str
    canonical_temporal_edges: list[TemporalEdge]


# 【职责】等价拓扑指纹主入口：从协议 spec 构建精确/等价两种哈希(去重核心)。
# - 从 metadata 读 selected_primary 后委托给 fingerprint_temporal_edges
def fingerprint_protocol_spec(
    spec: ProtocolGraphSpec,
) -> TopologyFingerprint:
    """Build exact and equivalence hashes from a protocol spec."""
    selected = _optional_int(spec.metadata.get("selected_primary"))
    return fingerprint_temporal_edges(
        n_agents=spec.n_agents,
        steps=[step.transmissions for step in spec.steps],
        selected_primary=selected,
    )


# 【职责】为时序路由构建精确哈希与标签不变(重标号不变)的等价哈希。
# - 边解释为 (step, src, dst)；时间展开执行图中步间时间必然前进，
#   因此 agent 级反馈(跨步回边)是合法的
# - exact 载荷含原始标号步表；等价载荷用规范时序边表
def fingerprint_temporal_edges(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    selected_primary: int | None = None,
) -> TopologyFingerprint:
    """Build exact and label-invariant hashes for temporal routes.

    Edges are interpreted as (step, src, dst).  Agent-level feedback is valid
    because time always advances between steps in the expanded execution graph.
    """
    normalized_steps = _normalize_steps(steps)
    exact_payload = {
        "n_agents": int(n_agents),
        "selected_primary": selected_primary,
        "steps": normalized_steps,
    }
    exact_hash = _digest(exact_payload)
    canonical = canonical_temporal_edges(
        n_agents=n_agents,
        steps=normalized_steps,
        selected_primary=selected_primary,
    )
    equivalence_payload = {
        "n_agents": int(n_agents),
        "canonical_temporal_edges": canonical,
    }
    return TopologyFingerprint(
        topology_equivalence_hash=_digest(equivalence_payload),
        exact_execution_hash=exact_hash,
        canonical_temporal_edges=canonical,
    )


# 【职责】返回字典序最小的重标号时序边表——等价类的规范形。
# - 初始着色(逐步出/入度时间线、是否 selected_primary、是否纯接收者)
#   -> 迭代颜色精化缩小搜索空间 -> 同色组内枚举排列取最小重标号
def canonical_temporal_edges(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    selected_primary: int | None = None,
) -> list[TemporalEdge]:
    """Return the lexicographically minimal relabeled temporal edge list."""
    normalized_steps = _normalize_steps(steps)
    agents = tuple(range(int(n_agents)))
    initial_colors = _initial_agent_colors(
        n_agents=int(n_agents),
        steps=normalized_steps,
        selected_primary=selected_primary,
    )
    refined_colors = _refine_agent_colors(
        n_agents=int(n_agents),
        steps=normalized_steps,
        colors=initial_colors,
    )
    color_groups: dict[tuple[object, ...], list[int]] = {}
    for agent, color in refined_colors.items():
        color_groups.setdefault(color, []).append(agent)
    ordered_groups = [
        tuple(sorted(group))
        for _color, group in sorted(
            color_groups.items(),
            key=lambda item: (repr(item[0]), len(item[1]), tuple(sorted(item[1]))),
        )
    ]
    best: list[TemporalEdge] | None = None
    for ordered_agents in _candidate_orders(ordered_groups):
        mapping = {agent: idx for idx, agent in enumerate(ordered_agents)}
        relabeled = sorted(
            (step_idx, mapping[src], mapping[dst])
            for step_idx, edges in enumerate(normalized_steps)
            for src, dst in edges
        )
        if best is None or relabeled < best:
            best = relabeled
    if best is not None:
        return best
    return [(step_idx, agent, agent) for step_idx, agent in enumerate(agents[:0])]


# 【职责】取或推导 SkillCard 类对象的等价拓扑哈希。
# - 优先用存档的 topology_equivalence_hash；缺失则解析其
#   organization_policy.protocol_spec 现算，解析失败返回 None
def topology_hash_from_skill(skill: object) -> str | None:
    """Return or derive a topology equivalence hash for a SkillCard-like object."""
    organization_policy = getattr(skill, "organization_policy", {}) or {}
    stored = organization_policy.get("topology_equivalence_hash")
    if stored:
        return str(stored)
    spec_data = None
    try:
        from exp_graph.mas.schemas import SkillCard
        from exp_graph.mas.skill_payloads import protocol_spec_from_skill

        if isinstance(skill, SkillCard):
            spec_data = protocol_spec_from_skill(skill)
    except (ImportError, TypeError):
        spec_data = None
    if spec_data is None:
        spec_data = organization_policy.get("protocol_spec")
    if not isinstance(spec_data, dict):
        return None
    try:
        spec = ProtocolGraphSpec.model_validate(spec_data)
    except Exception:
        return None
    return fingerprint_protocol_spec(spec).topology_equivalence_hash


# 【职责】生成写入协议 metadata 的当前拓扑指纹字段(哈希+规范边表)。
def protocol_metadata_with_fingerprint(
    spec: ProtocolGraphSpec,
) -> dict[str, object]:
    """Return protocol metadata containing current topology fingerprints."""
    fp = fingerprint_protocol_spec(spec)
    return {
        "topology_equivalence_hash": fp.topology_equivalence_hash,
        "exact_execution_hash": fp.exact_execution_hash,
        "canonical_temporal_edges": [list(edge) for edge in fp.canonical_temporal_edges],
    }


# 【职责】每步边集合去重、int 化并排序，得到规范步表。
def _normalize_steps(
    steps: Sequence[Sequence[tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    normalized: list[list[tuple[int, int]]] = []
    for edges in steps:
        normalized.append(sorted({(int(src), int(dst)) for src, dst in edges}))
    return normalized


# 【职责】初始着色：为颜色精化提供起点。
# - 颜色=(逐步出/入度时间线, 是否 selected_primary, 是否只收不发的纯接收者)
def _initial_agent_colors(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    selected_primary: int | None,
) -> dict[int, tuple[object, ...]]:
    colors: dict[int, tuple[object, ...]] = {}
    final_receivers = {dst for edges in steps for _src, dst in edges}
    sources = {src for edges in steps for src, _dst in edges}
    for agent in range(n_agents):
        timeline = []
        for edges in steps:
            out_count = sum(1 for src, _dst in edges if src == agent)
            in_count = sum(1 for _src, dst in edges if dst == agent)
            timeline.append((out_count, in_count))
        colors[agent] = (
            tuple(timeline),
            agent == selected_primary,
            agent in final_receivers and agent not in sources,
        )
    return colors


# 【职责】迭代颜色精化(类 Weisfeiler-Lehman)：用邻居颜色的逐步签名细分颜色。
# - 至多迭代 2*n_agents 轮，压缩后达到不动点即返回
def _refine_agent_colors(
    *,
    n_agents: int,
    steps: Sequence[Sequence[tuple[int, int]]],
    colors: dict[int, tuple[object, ...]],
) -> dict[int, tuple[object, ...]]:
    current = dict(colors)
    for _ in range(max(1, n_agents * 2)):
        next_colors: dict[int, tuple[object, ...]] = {}
        for agent in range(n_agents):
            step_signature = []
            for edges in steps:
                outgoing = sorted(current[dst] for src, dst in edges if src == agent)
                incoming = sorted(current[src] for src, dst in edges if dst == agent)
                step_signature.append((tuple(outgoing), tuple(incoming)))
            next_colors[agent] = (current[agent], tuple(step_signature))
        compressed = _compress_colors(next_colors)
        if compressed == current:
            return compressed
        current = compressed
    return current


# 【职责】把颜色值重编号为稳定小整数(按 repr 排序)，便于比较是否收敛。
def _compress_colors(
    colors: dict[int, tuple[object, ...]],
) -> dict[int, tuple[object, ...]]:
    ranked = {
        color: idx
        for idx, color in enumerate(sorted(set(colors.values()), key=repr))
    }
    return {agent: (ranked[color],) for agent, color in colors.items()}


# 【职责】按同色组产出候选 agent 排列：组间顺序固定，组内枚举全部排列。
# - 排列总数超过 200000 时只产出一个排序稳定的兜底排列，限制运行时
def _candidate_orders(groups: Sequence[Sequence[int]]) -> Iterable[tuple[int, ...]]:
    total = 1
    for group in groups:
        total *= _factorial(len(group))
    if total > 200_000:
        # 中文：为较大且高度对称的图保住运行时上界。精化后的颜色组在实际
        #   使用中仍给出确定、稳定的标号。
        # Keep runtime bounded for larger, highly symmetric graphs.  The refined
        # color groups still give deterministic, stable labels for practical use.
        yield tuple(agent for group in groups for agent in sorted(group))
        return
    for pieces in itertools.product(*(itertools.permutations(group) for group in groups)):
        yield tuple(agent for piece in pieces for agent in piece)


def _factorial(value: int) -> int:
    result = 1
    for number in range(2, value + 1):
        result *= number
    return result


# 【职责】JSON 规范序列化后取 sha256 十六进制前 12 位作为短哈希。
def _digest(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
