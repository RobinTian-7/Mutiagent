"""Organization operators that compile to finite protocol graph specs."""
# ============================================================
# 【模块导读】组织操作子：可编译(成协议调度)为有限协议图规范的声明式算子。
# OPERATOR_REGISTRY 登记 local_solve/peer_propagate/mesh_broadcast/
# tree_reduce/star_sink/vote_select/average_select/fallback 等操作子；
# compose_protocol_from_operators 把操作子链映射到最接近的受支持拓扑，
# 再展开成逐步传输表(ProtocolGraphSpec)。
# ============================================================

from __future__ import annotations

from dataclasses import dataclass

from exp_graph.protocols import (
    ProtocolGraphSpec,
    ProtocolStepSpec,
    build_protocol_schedule,
)


# 【职责】组织操作子的声明式描述(名字+一句话说明)，登记于 OPERATOR_REGISTRY。
@dataclass(frozen=True)
class OrganizationOperator:
    """Declarative description of an organization operator."""

    name: str
    description: str


# 【职责】操作子注册表：登记全部受支持操作子及其语义。
# - local_solve=各自求解本地分片；peer_propagate=单邻居指数传播部分信念
# - mesh_broadcast=一步稠密全网广播；tree_reduce=二叉树归约进最终汇点
# - star_sink=非汇点一步汇聚到汇点；vote_select/average_select=终选策略
# - fallback=规划器记录一条兜底组织策略
OPERATOR_REGISTRY: dict[str, OrganizationOperator] = {
    "local_solve": OrganizationOperator("local_solve", "Agents solve local shards."),
    "peer_propagate": OrganizationOperator(
        "peer_propagate",
        "Agents spread partial beliefs through one-peer exponential propagation.",
    ),
    "mesh_broadcast": OrganizationOperator(
        "mesh_broadcast",
        "Agents broadcast to all other agents in one dense step.",
    ),
    "tree_reduce": OrganizationOperator(
        "tree_reduce",
        "Agents reduce information through a binary tree into the final sink.",
    ),
    "star_sink": OrganizationOperator(
        "star_sink",
        "Non-sink agents send to the final sink in one gather step.",
    ),
    "vote_select": OrganizationOperator(
        "vote_select",
        "Final selection uses vote across answer holders.",
    ),
    "average_select": OrganizationOperator(
        "average_select",
        "Final selection prefers averaged full-coverage answers.",
    ),
    "fallback": OrganizationOperator(
        "fallback",
        "Planner records a fallback organization policy.",
    ),
}


# 【职责】把受支持的操作子组合编译(成协议调度)为有限 ProtocolGraphSpec。
# - 流程：操作子归一化 -> topology_for_operator_chain 映射到最近拓扑 ->
#   build_protocol_schedule 展开逐步传输 -> 每步反推主导操作子
# - metadata 记录 compiled_from_topology 与可选 max_messages
def compose_protocol_from_operators(
    *,
    name: str,
    n_agents: int,
    operators: list[str],
    max_messages: int | None = None,
) -> ProtocolGraphSpec:
    """Compile supported operator compositions into a finite protocol spec."""
    normalized = [operator.strip().lower() for operator in operators]
    topology = topology_for_operator_chain(normalized)
    schedule = build_protocol_schedule(topology, n_agents)
    steps = [
        ProtocolStepSpec(
            transmissions=step.transmissions,
            description=step.description,
            operator=operator_for_description(step.description, normalized),
        )
        for step in schedule
    ]
    metadata: dict[str, object] = {
        "compiled_from_topology": topology,
        "planner_generated": True,
    }
    if max_messages is not None:
        metadata["max_messages"] = max_messages
    return ProtocolGraphSpec(
        name=name,
        n_agents=n_agents,
        steps=steps,
        operators=normalized,
        metadata=metadata,
    )


# 【职责】返回操作子链对应的"最接近的受支持拓扑"名。
# - peer_propagate+star_sink/tree_reduce -> 单邻居指数 DAG 星形/树形变体；
#   仅 peer_propagate -> 投票变体；mesh_broadcast(+star_sink) -> mesh(_star)；
#   tree_reduce -> tree；star_sink -> star；都没有则退化为 chain
def topology_for_operator_chain(operators: list[str]) -> str:
    """Return the nearest supported topology for an operator chain."""
    operator_set = set(operators)
    if "peer_propagate" in operator_set and "star_sink" in operator_set:
        return "one_peer_exponential_dag_star"
    if "peer_propagate" in operator_set and "tree_reduce" in operator_set:
        return "one_peer_exponential_dag_tree"
    if "peer_propagate" in operator_set:
        return "one_peer_exponential_dag_vote"
    if "mesh_broadcast" in operator_set and "star_sink" in operator_set:
        return "mesh_star"
    if "mesh_broadcast" in operator_set:
        return "mesh"
    if "tree_reduce" in operator_set:
        return "tree"
    if "star_sink" in operator_set:
        return "star"
    return "chain"


# 【职责】从编译后调度步的描述文本反推该步的主导组织操作子。
# - 关键词匹配 one_peer/mesh/tree/star 等；都不中时取链中首个非
#   local_solve 操作子，再没有则记为 custom
def operator_for_description(description: str, operators: list[str]) -> str:
    """Infer the dominant organization operator for a compiled schedule step."""
    text = description.lower()
    if "one_peer" in text:
        return "peer_propagate"
    if "mesh" in text and "aggregation" not in text:
        return "mesh_broadcast"
    if "tree" in text or "reduction" in text:
        return "tree_reduce"
    if "star" in text or "sink" in text or "gather" in text:
        return "star_sink"
    return next((item for item in operators if item != "local_solve"), "custom")
