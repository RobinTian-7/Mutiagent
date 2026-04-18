# exp-graph

`exp-graph` 是一个轻量的 LLM multi-agent communication topology effect 实验仓库。

当前第一阶段只研究一件事：在同一个同步多轮 multi-agent 解题协议中，只改变 agents 的 neighbor communication topology，观察最终正确率、达成共识速度、模型调用/token 成本，以及 agent 数规模变化下的表现。

当前内置任务是 `distributed_array_search`：所有 agents 共享同一个全局数组搜索任务，每个 agent 只看到自己的数组 shard 和全局 offset。系统需要判断 target 是否存在，并在存在时返回第一个全局位置。

## Scope

本仓库当前不复现 claim graph、cascade、DTI 或 coordination law。Exponential graph 在这里只控制物理通信层：

- 每一轮每个 agent 能看到哪些 neighbors
- 每一轮哪些 neighbor outbox 会进入当前 agent 的 inbox

它不替代 Claim DAG，也不参与 task-specific answer selection。任务逻辑在 `TaskAdapter` 中，运行时 cheap consensus 在 `aggregator/runtime_consensus.py` 中，最终停机后的 reducer 在 `aggregator/final_reducer.py` 中。

## Core State Model

每个 agent 的唯一内部主状态是 `belief_state`。LLM 每轮只输出新的 `belief_state`，不直接输出 outbox。

最小 `belief_state` schema:

```json
{
  "status": "unknown | candidate | final",
  "proposal": "...",
  "consensus_key": "... | UNKNOWN | null",
  "support": ["...", "..."],
  "uncertainty": "...",
  "open_questions": ["...", "..."],
  "private_notes": "..."
}
```

`outbox` 是程序从 `belief_state` 和元信息自动派生的短外发视图：

```json
{
  "agent_id": 0,
  "round_idx": 1,
  "status": "final",
  "proposal": "...",
  "consensus_key": "FOUND:12",
  "support": ["..."],
  "uncertainty": "",
  "request": ""
}
```

`outbox` 不是独立真相源，不允许和 `belief_state` 表达不同答案。

## Topologies

所有 topology 共享同一个接口：

```python
get_neighbors(agent_id: int, round_idx: int, n_agents: int) -> list[int]
```

当前支持：

- `chain`
- `star`
- `mesh`
- `static_exponential`
- `one_peer_exponential`

`static_exponential` 使用循环索引连接多个指数距离 neighbor：

```text
neighbors(i) = {(i + 2^k) mod n | k = 0, ..., ceil(log2(n))-1}
```

`one_peer_exponential` 每轮只连接一个指数距离 neighbor，并使用 runner 维护的全局通信轮次：

```text
j = (agent_id + 2^(round_idx mod ceil(log2(n_agents)))) mod n_agents
```

## TaskAdapter

任务特化逻辑集中在 `src/exp_graph/tasks/` 下。

`TaskAdapter` 提供：

- `build_global_task(...)`
- `split_into_local_observations(...)`
- `initial_local_solve(...)`
- `normalize_consensus_key(...)`
- `evaluate_final_answer(...)`
- `format_task_prompt_context(...)`

核心 agent、runner、topology、runtime consensus 和 final reducer 不写死 array search 细节。后续添加新任务时，优先新增 adapter，而不是改 runner。

## Synchronous Runner

runner 是同步轮式调度，每轮固定执行：

1. 根据 topology 计算每个 agent 的 neighbors
2. 收集 neighbors 上一轮 outbox，形成 inbox
3. 每个 agent 基于 local observation、旧 belief_state 和 inbox 调用 LLM 更新 belief_state
4. 程序从新 belief_state 派生 outbox
5. 统一 commit 所有 agent 状态
6. 执行 cheap runtime consensus detection
7. 达到阈值或最大轮数后停止

运行时共识检测只统计 `belief_state.consensus_key`，不调用 LLM，不做复杂文本聚合。最终停机后才运行 final reducer。

## Install

```bash
cd exp-graph
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

也可以使用父仓库已有环境运行，只要安装了 `pydantic` 和 `pytest`。

## Run

离线 deterministic fake LLM：

```bash
python examples/run_array_search.py --topology one_peer_exponential --n-agents 8 --max-rounds 5 --seed 7
```

切换 topology：

```bash
python examples/run_array_search.py --topology chain
python examples/run_array_search.py --topology star
python examples/run_array_search.py --topology mesh
python examples/run_array_search.py --topology static_exponential
python examples/run_array_search.py --topology one_peer_exponential
```

使用 OpenAI client：

```bash
OPENAI_API_KEY=... python examples/run_array_search.py --llm-provider openai --model-name gpt-4o-mini
```

## Test

```bash
pytest
```

测试覆盖 topology neighbor correctness、one-peer global round alignment、array shard splitting、initial local solve、outbox derivation、runtime consensus、final reducer 和 minimal end-to-end smoke。

