"""Finite directed communication schedules for protocol experiments."""
# ============================================================
# 【模块导读】协议实验用的有限有向通信调度。
# CommunicationStep 表示一个同时通信步；build_protocol_schedule
# 把命名拓扑（chain/tree/star/mesh/各类指数 DAG/分层等）编译为
# 有限的协议调度(逐步通信计划)，供 ProtocolRunner 逐通信步执行。
# ============================================================

from __future__ import annotations

import math
import random

from pydantic import BaseModel, Field


# 【职责】一个同时进行的有向通信步（执行器调度的基本单元）。
class CommunicationStep(BaseModel):
    """One simultaneous directed communication step."""

    # 通信步编号（从 0 起，调度内连续）
    step_idx: int
    # 本步同时投递的有向边 (src, dst) 列表
    transmissions: list[tuple[int, int]] = Field(default_factory=list)
    # 人类可读的步骤描述
    description: str = ""
    # 中文：可选的面向接收方的角色指引(M9)；所有命名拓扑均为 None，故既有调度全部不变。
    # Optional receiver-facing role guidance (M9); None on all named
    # topologies, so every existing schedule is unchanged.
    instruction: str | None = None

    # 【职责】本步实际出现的发送方集合。
    @property
    def active_senders(self) -> set[int]:
        return {src for src, _ in self.transmissions}

    # 【职责】本步实际出现的接收方集合。
    @property
    def active_receivers(self) -> set[int]:
        return {dst for _, dst in self.transmissions}


# 【职责】为指定命名拓扑构建有限通信协议调度；未知拓扑名抛错。
# - 校验 n_agents 为正、star_center 合法；单 agent 直接返回空调度。
# - chain：第 i 步 agent i -> i+1 顺序传递；star：叶子汇入中心，可选中心回广播。
# - one_peer_exponential 在本函数内联构造：τ 个相位，第 k 步发给距离 2^k (mod n) 的伙伴。
# - 其余命名拓扑分派到下方各构造函数（tree/mesh/随机 DAG/指数 DAG/分层等）。
def build_protocol_schedule(
    topology_name: str,
    n_agents: int,
    *,
    star_center: int = 0,
    include_star_broadcast: bool = False,
    random_seed: int = 0,
) -> list[CommunicationStep]:
    """Build the finite communication protocol for the requested topology."""
    if n_agents < 1:
        raise ValueError("n_agents must be positive")
    if not 0 <= star_center < n_agents:
        raise ValueError("star_center must be a valid agent id")
    if n_agents == 1:
        return []

    topology = topology_name.strip().lower()
    if topology == "chain":
        return [
            CommunicationStep(
                step_idx=idx,
                transmissions=[(idx, idx + 1)],
                description=f"chain: agent {idx} sends to agent {idx + 1}",
            )
            for idx in range(n_agents - 1)
        ]

    if topology == "tree":
        return _build_binary_reduce_tree_schedule(n_agents)

    if topology == "star":
        leaves = [agent_id for agent_id in range(n_agents) if agent_id != star_center]
        schedule = [
            CommunicationStep(
                step_idx=0,
                transmissions=[(leaf, star_center) for leaf in leaves],
                description=f"star: leaves send to center agent {star_center}",
            )
        ]
        if include_star_broadcast:
            schedule.append(
                CommunicationStep(
                    step_idx=1,
                    transmissions=[(star_center, leaf) for leaf in leaves],
                    description=f"star: center agent {star_center} broadcasts",
                )
            )
        return schedule

    if topology == "mesh":
        return _build_mesh_propagation(n_agents)

    if topology in {
        "mesh_star",
        "mesh_sink",
        "mesh_dag_star",
        "mesh_dag_sink",
    }:
        return _build_mesh_protocol(n_agents, aggregation="star")

    if topology in {"dag_mesh", "mesh_dag"}:
        return _build_dag_mesh_schedule(n_agents)

    if topology in {"random", "random_dag"}:
        return _build_random_dag_schedule(n_agents, random_seed=random_seed)

    if topology == "static_exponential_dag":
        return _build_static_exponential_dag_schedule(n_agents)

    if topology in {
        "one_peer_exponential_dag",
        "one_peer_exponential_dag_vote",
    }:
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="vote",
        )

    if topology == "one_peer_exponential_dag_tree":
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="tree",
        )

    if topology == "one_peer_exponential_dag_star":
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="star",
        )

    if topology in {
        "one_peer_exponential_dag_static",
        "one_peer_exponential_dag_static_exponential_dag",
    }:
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="static_exponential_dag",
        )

    if topology in {"two_stage_layer", "layer_two_stage", "two_stage"}:
        return _build_two_stage_layer_schedule(n_agents)

    if topology in {
        "balanced_log_layer",
        "balance_log_layer",
        "layer_balanced_log",
        "layer_balance_log",
        "balanced_log",
        "balance_log",
    }:
        return _build_balanced_log_layer_schedule(n_agents)

    if topology == "static_exponential":
        return _build_static_exponential_propagation(n_agents)

    if topology in {
        "static_exponential_star",
        "static_exponential_sink",
        "static_exponential_dag_star",
        "static_exponential_dag_sink",
    }:
        return _build_static_exponential_protocol(n_agents, aggregation="star")

    if topology == "one_peer_exponential":
        tau = _tau(n_agents)
        return [
            CommunicationStep(
                step_idx=step_idx,
                transmissions=_dedupe_edges(
                    (src, (src + 2**step_idx) % n_agents)
                    for src in range(n_agents)
                ),
                description=(
                    "one_peer_exponential: "
                    f"distance {2**step_idx} peer phase"
                ),
            )
            for step_idx in range(tau)
        ]

    raise ValueError(f"unsupported protocol topology: {topology_name}")


# 【职责】τ = max(1, ceil(log2(n)))：指数类拓扑的相位数。
def _tau(n_agents: int) -> int:
    return max(1, math.ceil(math.log2(n_agents)))


# 【职责】tree 拓扑：构建汇入最后一个 agent 的平衡二叉归约树。
# - 每步 stride 翻倍：块内左半汇点发给右半汇点，约 log2(n) 步归约到汇点 agent n-1。
def _build_binary_reduce_tree_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build a balanced binary reduction tree into the final agent."""
    schedule: list[CommunicationStep] = []
    stride = 1
    step_idx = 0
    while stride < n_agents:
        transmissions: list[tuple[int, int]] = []
        block_size = stride * 2
        for block_start in range(0, n_agents, block_size):
            left_sink = min(block_start + stride - 1, n_agents - 1)
            right_sink = min(block_start + block_size - 1, n_agents - 1)
            if left_sink < right_sink:
                transmissions.append((left_sink, right_sink))
        if transmissions:
            schedule.append(
                CommunicationStep(
                    step_idx=step_idx,
                    transmissions=transmissions,
                    description=(
                        "tree: binary reduction "
                        f"stride={stride} into right-block sinks"
                    ),
                )
            )
            step_idx += 1
        stride *= 2
    return schedule


# 【职责】dag_mesh 拓扑：按拓扑序逐目的地扫过的稠密 DAG。
# - 共 n-1 步：第 dst-1 步由所有编号更小的前驱同时发给 agent dst。
def _build_dag_mesh_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build a dense DAG swept in topological destination order."""
    return [
        CommunicationStep(
            step_idx=dst - 1,
            transmissions=[(src, dst) for src in range(dst)],
            description=f"dag_mesh: all predecessors send to agent {dst}",
        )
        for dst in range(1, n_agents)
    ]


# 【职责】random_dag 拓扑：带种子、按目的地顺序扫过的稀疏随机 DAG。
# - agent 编号即 DAG 拓扑序，边恒由小编号指向大编号。
# - 始终保留链式主干，保证每个源最终可达汇点 agent n-1。
# - 额外前向边按适中概率采样，使基线保持稀疏、可与其他有限协议对比。
def _build_random_dag_schedule(
    n_agents: int,
    *,
    random_seed: int,
) -> list[CommunicationStep]:
    """Build a seeded sparse random DAG swept in destination order.

    Agent ids define the DAG topological order, so edges always point from a
    lower id to a higher id. A chain backbone is always present to guarantee
    every source can eventually reach the final sink agent ``n_agents - 1``.
    Extra forward edges are sampled with a modest density so the baseline stays
    sparse and comparable to the other finite protocols.
    """
    rng = random.Random(random_seed)
    edge_probability = min(0.5, max(0.25, math.log2(n_agents) / n_agents))
    edges: set[tuple[int, int]] = {
        (src, src + 1)
        for src in range(n_agents - 1)
    }
    for src in range(n_agents):
        for dst in range(src + 2, n_agents):
            if rng.random() < edge_probability:
                edges.add((src, dst))

    schedule: list[CommunicationStep] = []
    for dst in range(1, n_agents):
        transmissions = [
            (src, dst)
            for src in range(dst)
            if (src, dst) in edges
        ]
        schedule.append(
            CommunicationStep(
                step_idx=len(schedule),
                transmissions=transmissions,
                description=(
                    "random_dag: seeded random predecessors "
                    f"send to agent {dst} "
                    f"(seed={random_seed}, p={edge_probability:.3f})"
                ),
            )
        )
    return schedule


# 【职责】mesh 拓扑：单个稠密全互联广播步（所有 agent 两两互发）。
def _build_mesh_propagation(n_agents: int) -> list[CommunicationStep]:
    """Build one dense all-to-all mesh propagation step."""
    return [
        CommunicationStep(
            step_idx=0,
            transmissions=[
                (src, dst)
                for src in range(n_agents)
                for dst in range(n_agents)
                if src != dst
            ],
            description="mesh: all agents broadcast to all other agents",
        )
    ]


# 【职责】mesh_star 系列拓扑：mesh 广播后接汇入单一汇点的终局归约，再重编号通信步。
def _build_mesh_protocol(
    n_agents: int,
    *,
    aggregation: str,
) -> list[CommunicationStep]:
    """Build mesh propagation followed by a final reducer into one sink."""
    schedule = _build_mesh_propagation(n_agents)
    if aggregation == "star":
        tail = _build_star_sink_gather_schedule(
            n_agents,
            description_prefix="mesh",
        )
    else:
        raise ValueError(f"unsupported mesh aggregation: {aggregation}")
    return _renumber_schedule([*schedule, *tail])


# 【职责】static_exponential_dag 拓扑：按目的地顺序的稀疏指数前驱层。
# - 每个 dst 从 dst-2^k（k<τ 且不越界）的前驱同时收取消息。
def _build_static_exponential_dag_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build sparse exponential predecessor layers in destination order."""
    tau = _tau(n_agents)
    schedule: list[CommunicationStep] = []
    for dst in range(1, n_agents):
        transmissions = [
            (dst - 2**phase, dst)
            for phase in range(tau)
            if dst - 2**phase >= 0
        ]
        if transmissions:
            schedule.append(
                CommunicationStep(
                    step_idx=len(schedule),
                    transmissions=transmissions,
                    description=(
                        "static_exponential_dag: exponential predecessors "
                        f"send to agent {dst}"
                    ),
                )
            )
    return schedule


# 【职责】static_exponential 拓扑：同一组固定指数边（去重后）重复传播 τ 个通信步。
def _build_static_exponential_propagation(
    n_agents: int,
) -> list[CommunicationStep]:
    """Build repeated fixed exponential-edge propagation phases."""
    tau = _tau(n_agents)
    transmissions = _dedupe_edges(
        (src, (src + 2**phase) % n_agents)
        for src in range(n_agents)
        for phase in range(tau)
    )
    return [
        CommunicationStep(
            step_idx=step_idx,
            transmissions=transmissions,
            description="static_exponential: fixed exponential edges",
        )
        for step_idx in range(tau)
    ]


# 【职责】static_exponential_star 系列：静态指数传播后接单一汇点的星形收集。
def _build_static_exponential_protocol(
    n_agents: int,
    *,
    aggregation: str,
) -> list[CommunicationStep]:
    """Build static exponential propagation followed by one final sink."""
    schedule = _build_static_exponential_propagation(n_agents)
    if aggregation == "star":
        tail = _build_star_sink_gather_schedule(
            n_agents,
            description_prefix="static_exponential",
        )
    else:
        raise ValueError(
            f"unsupported static exponential aggregation: {aggregation}"
        )
    return _renumber_schedule([*schedule, *tail])


# 【职责】one_peer_exponential_dag 的传播段：可回绕的单伙伴指数传播相位。
# - 第 k 相位每个 agent 发给距离 2^k (mod n) 的伙伴，高编号回绕发给低编号
#   （如轮次 0: 7→0；轮次 1: 6→0, 7→1）。
# - ceil(log2(n)) 个相位后，每个 agent 都持有全部 n 个 agent 的数据。
def _build_one_peer_exponential_dag_propagation(
    n_agents: int,
) -> list[CommunicationStep]:
    """Build wrapping one-peer exponential propagation phases.

    Each phase uses distance 2^k (mod n_agents), so high-index agents wrap
    around and send to low-index agents (e.g. round 0: 7→0; round 1: 6→0,
    7→1).  After ceil(log2(n)) phases every agent holds all n agents' data.
    """
    schedule: list[CommunicationStep] = []
    for phase in range(_tau(n_agents)):
        distance = 2**phase
        transmissions = [
            (src, (src + distance) % n_agents)
            for src in range(n_agents)
        ]
        schedule.append(
            CommunicationStep(
                step_idx=len(schedule),
                transmissions=transmissions,
                description=(
                    "one_peer_exponential_dag: "
                    f"distance {distance} propagation"
                ),
            )
        )
    return schedule


# 【职责】one_peer_exponential_dag_* 家族：单伙伴 DAG 传播 + 可选终局归约尾段。
# - vote：不加尾段、靠投票聚合；tree/star/static_exponential_dag：拼接对应归约调度后重编号。
def _build_one_peer_exponential_dag_protocol(
    n_agents: int,
    *,
    aggregation: str,
) -> list[CommunicationStep]:
    """Build one-peer DAG propagation followed by an optional final reducer."""
    schedule = _build_one_peer_exponential_dag_propagation(n_agents)
    if aggregation == "vote":
        return schedule
    if aggregation == "tree":
        tail = _build_binary_reduce_tree_schedule(n_agents)
    elif aggregation == "star":
        tail = _build_star_sink_gather_schedule(
            n_agents,
            description_prefix="one_peer_exponential_dag",
        )
    elif aggregation == "static_exponential_dag":
        tail = _build_static_exponential_dag_schedule(n_agents)
    else:
        raise ValueError(f"unsupported one-peer DAG aggregation: {aggregation}")
    return _renumber_schedule([*schedule, *tail])


# 【职责】单步星形收集：其余 agent 全部发往最后一个 agent（协议汇点）。
def _build_star_sink_gather_schedule(
    n_agents: int,
    *,
    description_prefix: str,
) -> list[CommunicationStep]:
    """Build a single star gather into the final agent as protocol sink."""
    sink = n_agents - 1
    return [
        CommunicationStep(
            step_idx=0,
            transmissions=[
                (src, sink)
                for src in range(n_agents)
                if src != sink
            ],
            description=(
                f"{description_prefix} aggregation: "
                f"star gather to agent {sink}"
            ),
        )
    ]


# 【职责】two_stage_layer 拓扑：输入层 -> 隐藏层 -> 终局汇点的稠密分层通信。
# - 非汇点 agent 对半切为输入/隐藏两层；仅一个非汇点时它直接发给汇点。
def _build_two_stage_layer_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build input -> hidden -> final-sink dense layered communication."""
    sink = n_agents - 1
    non_sink = list(range(sink))
    if not non_sink:
        return []
    if len(non_sink) == 1:
        return [
            CommunicationStep(
                step_idx=0,
                transmissions=[(non_sink[0], sink)],
                description="two_stage_layer: only input agent sends to final sink",
            )
        ]

    split_idx = math.ceil(len(non_sink) / 2)
    input_layer = non_sink[:split_idx]
    hidden_layer = non_sink[split_idx:]
    schedule = [
        CommunicationStep(
            step_idx=0,
            transmissions=[
                (src, dst)
                for src in input_layer
                for dst in hidden_layer
            ],
            description="two_stage_layer: input layer sends to hidden layer",
        ),
        CommunicationStep(
            step_idx=1,
            transmissions=[(src, sink) for src in hidden_layer],
            description="two_stage_layer: hidden layer sends to final sink",
        ),
    ]
    return [step for step in schedule if step.transmissions]


# 【职责】balanced_log_layer 拓扑：log 深度的均衡分层，相邻层间稠密全连边。
# - 非汇点均分为 ceil(log2(n)) 个连续层并附加汇点层，逐层稠密传递到汇点。
def _build_balanced_log_layer_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build log-depth balanced layers with adjacent-layer dense edges."""
    sink = n_agents - 1
    non_sink = list(range(sink))
    if not non_sink:
        return []

    layer_count = max(1, math.ceil(math.log2(n_agents)))
    layers = _partition_contiguous(non_sink, layer_count)
    layers.append([sink])

    schedule: list[CommunicationStep] = []
    for step_idx, (src_layer, dst_layer) in enumerate(zip(layers, layers[1:])):
        transmissions = [
            (src, dst)
            for src in src_layer
            for dst in dst_layer
        ]
        if transmissions:
            schedule.append(
                CommunicationStep(
                    step_idx=step_idx,
                    transmissions=transmissions,
                    description=(
                        "balanced_log_layer: dense adjacent-layer transfer "
                        f"layer {step_idx} -> {step_idx + 1}"
                    ),
                )
            )
    return schedule


# 【职责】把有序 agent 编号切成大小近等、连续且非空的层。
def _partition_contiguous(items: list[int], layer_count: int) -> list[list[int]]:
    """Split ordered agent ids into near-equal contiguous non-empty layers."""
    if not items:
        return []
    layer_count = max(1, min(layer_count, len(items)))
    base_size, remainder = divmod(len(items), layer_count)
    layers: list[list[int]] = []
    cursor = 0
    for layer_idx in range(layer_count):
        size = base_size + (1 if layer_idx < remainder else 0)
        layers.append(items[cursor : cursor + size])
        cursor += size
    return layers


# 【职责】拼接多段调度后重排 step_idx，保证通信步编号连续。
def _renumber_schedule(schedule: list[CommunicationStep]) -> list[CommunicationStep]:
    """Return a schedule with contiguous step indices."""
    return [
        step.model_copy(update={"step_idx": step_idx})
        for step_idx, step in enumerate(schedule)
    ]


# 【职责】边去重并剔除自环，保持首次出现顺序。
def _dedupe_edges(edges) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    ordered: list[tuple[int, int]] = []
    for src, dst in edges:
        edge = (int(src), int(dst))
        if edge[0] == edge[1] or edge in seen:
            continue
        seen.add(edge)
        ordered.append(edge)
    return ordered
