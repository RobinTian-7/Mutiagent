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

- `llm/`
  - `LLMClient` 是统一接口。
  - `FakeLLMClient` 用于可复现离线测试。
  - `OpenAIChatClient` 用于真实 LLM 调用。

- `runner/`
  - `SynchronousRunner` 维护全局通信轮次。
  - 每轮使用 topology 计算 neighbors，并通过 barrier 同步 commit。

- `aggregator/runtime_consensus.py`
  - 每轮运行。
  - 只统计 `consensus_key`，复杂度接近 O(N)。
  - 不调用 LLM。

- `aggregator/final_reducer.py`
  - 只在停机后运行一次。
  - 执行 candidate grouping、group summary 和 cross-group adjudication。
  - 可选 LLM adjudicator 最多调用一次，并且只输入少量 group summary。

- `metrics/`
  - 汇总准确率、共识状态、轮数、调用数、token 估算和每轮 key 轨迹。

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

1. final reducer 先按规范化 consensus_key 分组。
2. 每组生成 GroupSummary。
3. 规则选择 top group；必要时可选一次 LLM adjudicator。
4. 输出 FinalResult。

## Extension Points

添加新 topology：

1. 新增 `Topology` 子类。
2. 实现 `get_neighbors(...)`。
3. 注册到 `topology/factory.py`。

添加新任务：

1. 新增 `TaskAdapter` 实现。
2. 保证 consensus_key 能被 adapter 规范化。
3. 保证 `evaluate_final_answer(...)` 可评价最终 key。
4. 不修改 runner 或 topology。

