# Assumptions

本文档记录当前第一阶段实现中的工程假设和简化边界。

## Scope Assumptions

当前仓库只测试 communication topology effect。它不实现 claim graph、cascade reconstruction、DTI、coordination law 或 decentralized SGD 的理论复现。

Exponential graph 只作为 physical neighbor communication topology 使用。它决定每轮 agent 可以读取哪些 neighbors 的 outbox，不决定任务答案如何选择，也不替代 final reducer。

## Topology Assumptions

`mesh` 第一版实现为 fully connected mesh：每个 agent 每轮读取除自己以外的所有 agents 的上一轮 outbox。这是稠密通信 baseline，不是带宽受限 mesh。

`static_exponential` 第一版是单向循环图，距离为 `1, 2, 4, ...`。接口保留 `round_idx`，便于后续扩展成双向或可配置版本。

`one_peer_exponential` 使用 runner 维护的全局通信轮次。所有 agents 在同一轮共享同一个指数尺度 phase。`round_idx` 不属于 agent 私有状态。

当 `n_agents` 不是 `2^k` 时，当前 `one_peer_exponential` 仍然运行：

```text
j = (agent_id + 2^(round_idx mod ceil(log2(n_agents)))) mod n_agents
```

但这只是工程启发式 mixing schedule，不宣称具备论文中 power-of-two 设置下的严格 mixing 或收敛理论保证。

## Agent and State Assumptions

`belief_state` 是 agent 唯一内部主真相源。LLM 每轮只输出新的 belief_state。

`outbox` 由程序从 belief_state 派生，用于邻居传播。它会保留少量 proposal、support、uncertainty 和 request，不包含 `private_notes`。

第一版 prompt 明确要求不要输出长思维链。`private_notes` 字段保留给短内部备注，但不外发。

## Array Search Assumptions

每个 agent 只看到一个 array shard 和 global offset。

如果本地 shard 没有 target，初始 belief_state 使用 `UNKNOWN`，而不是 `NOT_FOUND`。这是为了避免多数 local miss 在传播早期被误判成全局不存在。`NOT_FOUND` 需要更完整的全局覆盖证据，第一版 fake LLM 不主动推出全局 `NOT_FOUND`。

Array search 的第一版 consensus_key 规范化为：

- `FOUND:<global_index>`
- `NOT_FOUND`
- `UNKNOWN`

最终评价只比较规范化 final_key 和 global_task 的 answer_key。

## LLM Assumptions

`FakeLLMClient` 是 deterministic offline client，用于测试拓扑传播和同步 runner，不代表真实 LLM 行为。

真实 LLM 通过 `OpenAIChatClient` 接入。当前 prompt 采用 JSON-only 输出约束，并由 parser 从响应中提取 belief_state。生产实验应记录模型版本、temperature 和失败重试策略；第一版只保留最小接口。

## Aggregation Assumptions

Runtime consensus 是 cheap early-stop 机制，只统计 consensus_key，不调用 LLM，也不做复杂语义聚类。

Final reducer 只在停机后运行一次。第一版先按 consensus_key 分组，默认 score 主要使用 group size ratio；如果 belief_state 提供 confidence，则轻量加入 score。

Optional LLM adjudicator 只允许在最终 top groups 接近时调用一次，且输入限制为少量 GroupSummary 和 global task description。
