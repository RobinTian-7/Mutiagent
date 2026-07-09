# 假设

本文档记录超出明确 TeX 证据的实现选择。目标是把工程假设和论文直接支持的结构分开。

## 论文源码位置

用户提示中引用的是 `/Users/robintian/AI/Agent-Expretional-Graph/arXiv-2604.02674v1/sec`，但当前 workspace 中实际存在的 TeX 文件位于 `files/arXiv-2604.02674v1/sec`。实现和审查使用的是本地可用的 TeX 文件。

## Mock Agent Policy

论文说明 agents 共享同一个 LLM、prompt、tools 和 task instances，但没有给出精确 prompt 或 action-selection policy。可运行 demo 使用 `src/agents/mock_agent.py` 产生 propose、revise、contradict、merge、delegate events，因此不需要 API keys。

假设：随机 action probabilities 近似论文中的定性结构：delegation 和 contradiction 扩展 cascades，revision 细化 claims，merge 相对少见。这个设计适合 structural smoke tests，不用于分数复现。

## Task Expansion

论文描述了一个 workload expansion module，它会根据 benchmark、domain 和 agent count 生成 benchmark-grounded task trees。本仓库不复现这些 benchmark generators。

假设：demo 使用由 delegation events 诱导出的简化 task/subtask identifiers。这保留了 task decomposition 与 reasoning lineage 的分离，同时避免引入论文未指定的 benchmark synthesis。

## Execution Step Semantics

TeX 指定了 event-level traces 和重复执行，但没有完全定义 runnable simulator 应该如何调度 turns。

假设：一个 workflow round 让每个 agent 行动一次；一个 emitted event 就是一个 coordination step。这样在固定 seed 下 run size 是确定的，调度也保持简单。

## Reinforced Routing Defaults

论文定义 reinforced routing 为 `P(c_i | F_t) ∝ x_i(t)^β`，但 simulator 在收集 traces 前必须先选择一个 β。

假设：`β = 0.15` 是默认值，并保持可配置。Claim activity 对未见过的 claims 默认为 `1`，确保新 claims 可以被选择。

## DTI Parameters

论文说明 `a_c` 和 `δ_c` 从每个 condition class 的 baseline traces 估计，`β_c` 是经验 contradiction scaling exponent。

假设：demo 直接暴露这些参数，并使用保守默认值。测试中使用更强的值只是为了快速覆盖 trigger paths。Demo DTI runs 是定性检查，不是从完整 baseline logs 估计出的结果。

## DTI Merge Content

论文描述了一个作用于 active branch heads 的 structured integration prompt，但没有给出精确 prompt 文本。

假设：mock DTI merge 会产生一个 synthetic merged claim，它的 parent ids 是 active branch heads。这样可以保留 DAG 结构和 merge fan-in 语义，但不声称具有语义综合质量。

## Cross-Root Merge Semantics

论文通过共享 `root_claim_id` 定义 cascades，并且 DTI 明确整合某个 root claim 的 active branch heads。它没有完全说明普通 merge events 是否可以合并来自不同 roots 的 claims。

假设：常规 demo merges 限制为与 selected claim 共享 `root_claim_id` 的 claims。如果可见 claims 中同 root 数量少于两个，强制 mock merge 会退回 revision。这是保守做法，因为它保持了 cascade-local interpretation。

## Topology Scope

论文研究 chain、star、tree、hierarchical、fully connected、sparse mesh 和 dynamic reputation topologies。

假设：MVP 实现原始复现范围中的 chain、star 和 mesh。Tree、hierarchical、sparse mesh 和 dynamic reputation 保留为 TODO，因为 inspected TeX 中没有给出它们的具体 runtime definitions。

## Exponential Graph Scope

Static exponential 和 one-peer exponential topologies 基于 `Exponential Graph is Provably Efficient for Decentralized Deep Training`（arXiv 2110.13363）。这里直接支持的是物理通信 schedule：

- static exponential：每个节点看到循环距离为 `1, 2, 4, ...` 的 neighbors
- one-peer exponential：每个节点每轮看到一个循环 exponential-distance neighbor，并在这些距离间轮换

Assumption A14：在本仓库中，exponential graphs 只控制 neighbor communication visibility。它们不替代 Claim DAG，不选择 route 到哪个 claim，不修改 reinforced routing，也不改变 DTI deficit triggers、merge behavior 或 consolidation semantics。

Assumption A15：arXiv 2110.13363 中的 one-peer exact-averaging theorem 不被声称为关于 LLM claim propagation 的定理。当 `n` 是 2 的整数次幂时，schedule 对齐论文中的整齐周期结构。当 `n` 不是 2 的整数次幂时，实现仍会作为稀疏轮换通信的工程启发式继续运行，但不声称 periodic exact averaging。

## Structured Neighbor Exchange

当前 simulator 不在 agents 之间交换自由形式的 chain-of-thought。Neighbor visibility 暴露的是由物理 topology 和 round 过滤后的结构化 `Claim` records。Mock simulator 中的 claim content 刻意保持为短 synthetic text；parent ids、root ids、claim type、agent id 和 depth 承载 reconstruction 与 metrics 所需的 trace semantics。

## Qualitative DTI Comparison

论文报告 DTI 会增加 integration，并可能在 high-imbalance regimes 中降低 elite concentration。在这个 mock simulation 中，DTI 会稳定增加 merge count 和 merge fan-in，而 top-k concentration 会随 topology 和 seed 变化。

假设：定性对比只能解释为 structural sanity check。它展示的是 local trigger 和 merge mechanism，不是论文中的经验性能结论。
