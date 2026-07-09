# 架构

本仓库实现的是论文协作结构的最小可运行复现，不是完整 benchmark pipeline。

## 核心设计

运行时围绕 append-only traces 组织。Agents 产生 `Event` 和 `Claim` 记录；图结构和指标在运行后从这些记录中重建。这对应论文的 event-level formulation：协作动态通过带时间戳的 actions、claim references 和 task dependencies 来分析。

实现刻意分离三种结构：

1. 物理通信拓扑：谁可以和谁通信。
2. Task/subtask tree：工作如何通过 delegation 被分解。
3. Claim DAG：推理如何通过 parent claim references 演化。

这三种结构不应该合并成一张图。

Exponential graph 支持只存在于物理通信拓扑层。`static_exponential` 和 `one_peer_exponential` 决定某个 agent 在一轮中可以读取哪些 neighbor claims。它们不选择 claims，不改写 parent links，不替代 Claim DAG，也不修改 DTI triggers。

## 运行流程

`src/simulation/workflow.py` 构建 LangGraph `StateGraph`。每一轮：

1. 当前 acting agent 从 active topology 解析物理 neighbors。
2. 当前 acting agent 从这些 neighbors 和自身读取可见的结构化 `Claim` records。
3. 可插拔 claim router 从 visible set 中选择一个 candidate claim。
4. Mock agent 产生一个 coordination event 和一个 resulting claim。
5. Event 和 claim records 被追加到 state。
6. 如果启用 DTI，per-cascade monitor 更新本地 `(t_r, M_r)` 状态，并可能插入一个 merge event。

物理 neighbor schedule 会记录到 `neighbor_trace`。它是 communication paths 的运行时可观测信息，不是逻辑推理图。

Demo 使用 mock agents，因此无需 API keys 即可运行。这是一个工程假设，记录在 `docs/assumptions.md`。

## 组件映射

- `src/schemas/`：claims、events、subtasks、cascades 的 Pydantic models。
- `src/topology/`：chain、star、mesh、static exponential、one-peer exponential 通信图。
- `src/routing/`：topology visibility 与 reinforced claim selection。
- `src/tracing/`：append-only JSONL trace writer。
- `src/reconstruction/`：Claim DAG、subtask tree、cascade reconstruction。
- `src/interventions/`：Deficit-Triggered Integration。
- `src/analysis/`：cascade size、TCE、top-k contribution、revision waves、contradiction bursts、merge fan-in。
- `examples/`：用于 demo 生成和 DTI 定性对比的可运行脚本。

## DTI 的位置

DTI 实现为局部 intervention layer，而不是全局 scheduler。它以 root claim id 为单位监控每个 active cascade，计算 integration deficit，并且只在 deficit 超过 threshold 时触发 merge。被触发的 integration 会整合 active branch heads，并从 merged claim 继续探索。

在所有 topology 下，DTI 都保持 cascade-level、state-dependent。Exponential graphs 只改变 local routing 和 action selection 之前哪些 neighboring structured claims 可见。

## 输出契约

`examples/run_demo.py` 写出：

- `event_trace.jsonl`
- `claims.jsonl`
- `neighbor_trace.json`
- `reconstructed_claim_dag.json`
- `cascade_summary.json`
- `top_k_contribution_metrics.json`

这些 JSON 输出是 generated artifacts，并被 Git 忽略。
