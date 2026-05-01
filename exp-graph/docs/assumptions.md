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

## Count Frequency Assumptions

CF / count-frequency 任务要求统计全局整数数组中每个不同元素的出现频率。当前 adapter 默认生成 `[0, 9]` 范围内的整数，使 `FREQ_JSON` key 在真实 LLM prompt 中保持可读、可复制；可以通过 `--value-min` 和 `--value-max` 调整。

每个 agent 的初始 belief_state 只包含自己的 shard partial counts。为了避免重复计数，proposal 中携带 `CF_STATE_JSON` 载荷，内部保留 `partials`，即 `agent_id -> local_count_map`。邻居传播时合并的是 per-agent partials，而不是简单累加自由文本计数。

CF 的 runtime consensus key 规则是：

- 未覆盖全部 agents 时使用 `UNKNOWN`
- 覆盖全部 agents 后使用 `FREQ_JSON:<canonical_counts_json>`

`FREQ_JSON` 直接携带 canonical count map，而不是 hash。这个选择是工程假设：它更利于真实 LLM 复制和审计，但当 distinct value 数很大时会增加 prompt 和 key 长度。

CF protocol runner 额外支持三种 merge mode：

- `deterministic`: 程序合并 source-agent partial count maps。这不调用 LLM，用来测 topology 在完美合并条件下的信息传播上限。
- `llm_belief_merge`: LLM 更新 belief_state 的文本层字段，但程序用 verified merge 覆盖 `status`、`consensus_key` 和 `structured_state`。这是为了把 topology effect 和大规模字典算术幻觉部分分离。
- `llm_full_merge`: LLM 自己输出 `structured_state.merged_counts`，最终 CF answer 来自这个字段。`partials` 只作为信息覆盖和来源追踪使用，程序不会从 `partials` 重新计算 `merged_counts`。程序仍会做 JSON/schema/source-id/value-domain 校验，并把 LLM 给出的合法 merged counts 规范化成 final key。

`llm_full_merge` 默认允许 deterministic fallback：如果模型在 retry 后仍输出非法 JSON 或非法 CF state，runner 会使用程序 merge 继续实验，并记录 `TotalDeterministicFallbacks`。严格测试 LLM 独立答案时，应关闭 fallback，例如使用 `--no-deterministic-repair`。这会让坏输出直接使该 run 失败，实验解释更干净，但批量运行更容易中断。

## LLM Assumptions

`FakeLLMClient` 是 deterministic offline client，用于测试拓扑传播和同步 runner，不代表真实 LLM 行为。

真实 LLM 通过 `OpenAIChatClient` 接入。当前 prompt 采用 JSON-only 输出约束，并由 parser 从响应中提取 belief_state。`temperature` 是 `ExperimentConfig` 的显式参数，CLI 可通过 `--temperature` 控制。主实验建议固定 temperature 降低随机性；稳健性实验再扫描多个 temperature。

当前实现包含 JSON validation + retry。若模型输出无法解析为 `BeliefState`，agent 会把 schema、错误信息、坏响应和原始 prompt 发回同一个 provider，最多重试 `json_retry_attempts` 次。该策略假设 provider 的第二次输出有机会修正格式错误；它不是语义正确性保证，只保证尽量得到符合 schema 的 belief_state。

## Aggregation Assumptions

Runtime consensus 是 cheap early-stop 机制，只统计 consensus_key，不调用 LLM，也不做复杂语义聚类。

Final reducer 只在停机后运行一次。第一版先按 consensus_key 分组，默认 score 固定为 group size ratio。belief_state 中的 confidence 可以被 trace 记录，但不会进入默认 score，避免有/无 confidence 的 group 使用不同评分公式。

Optional LLM adjudicator 只允许在最终 top groups 接近时调用一次，且输入限制为少量 GroupSummary 和 task adapter 提供的无标签 adjudication context。Array search 的 adjudication context 不包含 `array`、`answer_key` 或 `answer_index`。

## Trace Assumptions

runner 可以在 `trace_dir` 中按轮追加每个 agent 的 trace JSONL。每条 trace 包含 step 级汇总字段，也包含 `llm_calls`，逐次保存该 agent step 内每一次 LLM 调用的 input prompt 和 output response；JSON retry 产生的调用也会作为单独元素记录。默认不把完整 trace 常驻 `ExperimentResult.agent_step_traces`，避免批量真实 LLM 实验时内存随 `agents × rounds × prompt_size` 增长。交互式 debug 时可以设置 `retain_traces=True` 保留内存副本。

内部 `round_idx` 是 0-based；对外 metrics 的 `rounds_to_consensus` 是 1-based 通信轮数。第一轮通信达成共识时，`round_idx = 0`，`rounds_to_consensus = 1`。
