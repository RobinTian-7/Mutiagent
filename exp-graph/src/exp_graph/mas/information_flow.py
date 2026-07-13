"""Structural information-propagation over a temporal communication schedule.

Answer-independent coverage detection: it asks WHETHER the structure can move
every agent's initial knowledge to where the evaluation mode needs it, not
whether the LLM actually produced a correct answer. Semantics (fixed by the
sink/all_agents evaluation-mode spec):

* ``knowledge[i]`` starts as ``{i}``.
* Steps execute simultaneously: ``next`` is first a copy of the previous
  state; for every edge ``src -> dst`` in the step, ``next[dst]`` absorbs
  ``previous[src]``. Senders and non-receivers keep their old state.
* sink passes iff ``knowledge[selected_primary]`` contains ``0..n_agents-1``.
* all_agents passes iff EVERY agent's knowledge contains ``0..n_agents-1``.
"""
# ============================================================
# 【模块导读】时序通信结构上的信息传播检测（与 LLM 答案正确性无关）。
# knowledge[i] 初始为 {i}；每步同时执行：next 先复制旧状态，再对每条 src->dst
# 令 next[dst] 并入 previous[src]；发送者与未接收者保留旧状态。
# sink 通过条件：knowledge[selected_primary] 覆盖 0..n-1；
# all_agents 通过条件：每个 agent 的 knowledge 都覆盖 0..n-1。
# ============================================================

from __future__ import annotations

from collections.abc import Iterable, Sequence

from exp_graph.mas.schemas import InformationGoal

Edge = tuple[int, int]


# 【职责】按"同时执行 + 复制旧状态"的时序语义推进知识集合，返回每 agent 的最终知识。
def propagate_knowledge(
    n_agents: int,
    steps: Sequence[Iterable[Edge]],
) -> list[set[int]]:
    """Final ``knowledge`` sets after simultaneous per-step propagation.

    ``steps`` is one edge iterable per simultaneous communication step
    (edges are ``(src, dst)``). Out-of-range and self-loop edges are ignored
    rather than raising: coverage detection must be robust to a graph the
    validator is about to reject anyway.
    """
    if n_agents < 1:
        return []
    knowledge: list[set[int]] = [{i} for i in range(n_agents)]
    for edges in steps:
        nxt = [set(k) for k in knowledge]
        for src, dst in edges:
            if src == dst:
                continue
            if 0 <= src < n_agents and 0 <= dst < n_agents:
                nxt[dst] |= knowledge[src]
        knowledge = nxt
    return knowledge


# 【职责】每个 agent 的信息覆盖率：|knowledge[j]| / n_agents，取值 [0,1]。
def coverage_by_agent(knowledge: list[set[int]]) -> list[float]:
    n = len(knowledge)
    if n == 0:
        return []
    return [len(k & set(range(n))) / n for k in knowledge]


# 【职责】sink 模式结构通过判定：selected_primary 的知识覆盖全部 agent。
def sink_covered(knowledge: list[set[int]], sink: int) -> bool:
    n = len(knowledge)
    if n == 0 or not 0 <= sink < n:
        return False
    return set(range(n)) <= knowledge[sink]


# 【职责】all_agents 模式结构通过判定：每个 agent 的知识都覆盖全部 agent。
def all_agents_covered(knowledge: list[set[int]]) -> bool:
    n = len(knowledge)
    if n == 0:
        return False
    full = set(range(n))
    return all(full <= k for k in knowledge)


# 【职责】按信息目标给出结构通过判定（sink 需 sink id；all_agents 忽略它）。
def goal_covered(
    knowledge: list[set[int]],
    *,
    goal: InformationGoal,
    sink: int | None = None,
) -> bool:
    if goal == "all_agents":
        return all_agents_covered(knowledge)
    return sink is not None and sink_covered(knowledge, sink)


# 【职责】列出知识未覆盖全体的 agent（all_agents 修复/报错定位用）。
def agents_without_full_information(knowledge: list[set[int]]) -> list[int]:
    n = len(knowledge)
    full = set(range(n))
    return [j for j in range(n) if not full <= knowledge[j]]
