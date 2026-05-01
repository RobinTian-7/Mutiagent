# Architecture

`exp-graph` 的核心边界是：topology 只决定谁能和谁通信，任务 adapter 只决定任务语义，runner 只负责同步调度，aggregator 只负责共识检测和最终整合。

## Modules

- `agents/`
  - `AgentConfig` 保存静态配置，例如 `agent_id`、`role`、`model_name`。
  - `AgentState` 保存运行态，包括 `local_observation`、`belief_state`、`inbox`、`outbox`。
  - `SolverAgent` 构造 prompt、调用 LLM、解析新 belief_state，并派生 outbox。

- `topology/`
  - 只实现 `get_neighbors(agent_id, round_idx, n_agents)`。
  - 不知道任务内容，不知道 consensus_key，不参与 final answer 选择。

- `messaging/`
  - 定义结构化 `OutboxMessage`。
  - outbox 从 belief_state 派生，不是独立状态。

- `tasks/`
  - `TaskAdapter` 是任务插件接口。
  - `ArraySearchTaskAdapter` 负责全局任务构建、local observation 切分、初始本地求解、consensus_key 规范化和最终答案评价。
  - `CountFrequencyTaskAdapter` 负责 CF/count-frequency 的 shard 切分、per-agent partial counts、mergeable CF state prompt 载荷、consensus_key 规范化和最终答案评价。

- `llm/`
  - `LLMClient` 是统一接口。
  - `FakeLLMClient` 用于可复现离线测试。
  - `OpenAIChatClient` 用于真实 LLM 调用。

- `runner/`
  - `SynchronousRunner` 维护全局通信轮次。
  - 每轮使用 topology 计算 neighbors，并通过 barrier 同步 commit。
  - `ProtocolRunner` 用于 CF 有限步通信协议实验。它仍复用 `AgentState`、`BeliefState`、`OutboxMessage`，但通信 schedule 可以是 chain 串行传递、star gather/broadcast、mesh all-to-all、static exponential 或 one-peer exponential。
  - `ProtocolRunnerConfig.merge_mode` 控制接收方如何更新 belief：
    - `deterministic`: 程序按 source partials 合并，是完美通信 baseline。
    - `llm_belief_merge`: LLM 更新 belief 文本字段，程序保留 verified CF `structured_state`。
    - `llm_full_merge`: LLM 自己输出 CF `structured_state`，程序只校验和规范化。

- `aggregator/runtime_consensus.py`
  - 每轮运行。
  - 只统计 `consensus_key`，复杂度接近 O(N)。
  - 不调用 LLM。

- `aggregator/final_reducer.py`
  - 只在停机后运行一次。
  - 执行 candidate grouping、group summary 和 cross-group adjudication。
  - 可选 LLM adjudicator 最多调用一次，并且只输入无标签 task context 和少量 group summary。
  - reducer score 第一版固定为 `size_ratio`，避免不同 group 因是否输出 confidence 而使用不同评分公式。

- `metrics/`
  - 汇总准确率、共识状态、轮数、调用数、token 估算和每轮 key 轨迹。

- `tracing/`
  - 记录每轮每个 agent 的 prompt、raw response、parsed belief_state、outbox、neighbors、inbox、token 和 retry 次数。
  - `llm_calls` 逐次记录该 agent step 内每一次 LLM 调用的 input prompt 和 output response，包括 retry。
  - runner 可通过 `trace_dir` 将 trace 按轮追加成 JSONL。
  - 默认不把完整 trace 常驻 `ExperimentResult` 内存；需要时使用 `retain_traces`。

## Data Flow

初始化：

1. `TaskAdapter.build_global_task(...)` 创建全局任务。
2. `TaskAdapter.split_into_local_observations(...)` 生成每个 agent 的局部观测。
3. `TaskAdapter.initial_local_solve(...)` 为每个 agent 生成初始 belief_state。
4. 程序从初始 belief_state 派生 round 0 outbox。

每一轮：

1. runner 使用 topology 和全局 `round_idx` 计算 neighbors。
2. runner 从上一轮 outbox 生成当前 inbox。
3. agent 基于 local observation、旧 belief_state 和 inbox 继续求解任务。
4. LLM 只输出新的 belief_state。
5. 程序派生新的 outbox。
6. runner 一次性 commit 所有 agent 状态。
7. runtime consensus 统计当前所有 consensus_key。

停机后：

1. runner 记录 `stop_reason`，例如 `runtime_consensus` 或 `max_rounds`。
2. final reducer 先按规范化 consensus_key 分组。
3. 每组生成 GroupSummary。
4. 规则选择 top group；必要时可选一次 LLM adjudicator。
5. 输出唯一 FinalResult。

LLM adjudicator 的 global task 输入由 `TaskAdapter.format_adjudication_context(...)` 生成，不能包含 ground-truth labels。

CF protocol runner 的有限步流程：

1. `CountFrequencyTaskAdapter.initial_protocol_belief(...)` 为每个 agent 创建本地 partial counts。
2. `protocols.build_protocol_schedule(...)` 根据 topology 生成有限步 transmissions。
3. 每一步只激活当前 schedule 的 receivers。
4. receiver 根据 `merge_mode` 执行 deterministic merge 或 LLM-backed belief merge。
5. 程序从新的 belief_state 派生 outbox。
6. 每一步记录 per-agent coverage/RMSE 和 global vote/average heads。
7. schedule 结束后运行 `aggregator.cf_final.run_cf_final_aggregation(...)`。

## Extension Points

添加新 topology：

1. 新增 `Topology` 子类。
2. 实现 `get_neighbors(...)`。
3. 注册到 `topology/factory.py`。

添加新任务：

1. 新增 `TaskAdapter` 实现。
2. 保证 consensus_key 能被 adapter 规范化。
3. 通过 `format_consensus_key_instructions(...)` 提供任务专用 prompt 指令。
4. 保证 `evaluate_final_answer(...)` 可评价最终 key。
5. 不修改 runner 或 topology。
