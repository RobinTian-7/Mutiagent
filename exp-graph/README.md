# exp-graph

`exp-graph` 是一个轻量的 LLM multi-agent communication topology effect 实验仓库。

当前第一阶段只研究一件事：在同一个同步多轮 multi-agent 解题协议中，只改变 agents 的 neighbor communication topology，观察最终正确率、达成共识速度、模型调用/token 成本，以及 agent 数规模变化下的表现。

当前内置任务包括：

- `distributed_array_search`：所有 agents 共享同一个全局数组搜索任务，每个 agent 只看到自己的数组 shard 和全局 offset。系统需要判断 target 是否存在，并在存在时返回第一个全局位置。
- `count_frequency` / CF：所有 agents 共享同一个全局整数数组，每个 agent 只看到自己的 shard。系统需要统计每个不同整数在全局数组中的出现频率。

## Scope

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
- `format_consensus_key_instructions(...)`

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

运行时共识检测只统计 `belief_state.consensus_key`，不调用 LLM，不做复杂文本聚合。达到 `max_rounds` 或 runtime consensus 后，runner 会自动调用 final reducer，把最后一轮所有 agent 的 `belief_state` merge 成唯一 `FinalResult`。

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

运行 CF / count-frequency：

```bash
python examples/run_count_frequency.py \
  --topology one_peer_exponential \
  --n-agents 8 \
  --max-rounds 5 \
  --array-size 1000 \
  --seed 7
```

CF 也可以使用论文常见规模：

```bash
python examples/run_count_frequency.py --array-size 1000
python examples/run_count_frequency.py --array-size 5000
python examples/run_count_frequency.py --array-size 10000
```

切换 topology：

```bash
python examples/run_array_search.py --topology chain
python examples/run_array_search.py --topology star
python examples/run_array_search.py --topology mesh
python examples/run_array_search.py --topology static_exponential
python examples/run_array_search.py --topology one_peer_exponential
```

同样可以把 `run_array_search.py` 换成 `run_count_frequency.py` 来比较 CF 任务下的 topology effect。

有限步 CF protocol 实验脚本：

```bash
python ../run_cf_protocol_experiments.py \
  --array-size 5000 \
  --value-min 1 \
  --value-max 1000 \
  --agent-counts 8 16 32 \
  --seeds 1 2 3 \
  --topologies mesh static_exponential one_peer_exponential \
  --merge-mode deterministic \
  --output-dir ../cf_protocol_results
```

`run_cf_protocol_experiments.py` 支持三种 merge mode：

- `deterministic`: 程序按 source-agent partials 做完美合并，是 topology 信息传播上限 baseline。
- `llm_belief_merge`: LLM 更新 proposal/support/uncertainty 等 belief 文本字段；程序保留已验证的 CF `structured_state`，防止重复计数和格式幻觉。
- `llm_full_merge`: LLM 自己输出最终 CF `structured_state.merged_counts`，程序只做 JSON/schema/domain 校验和评估，不从 `partials` 重新计算答案。若要让最终数组频数字典来自 LLM 自己的合并结果，用这个模式。

真实 LLM protocol merge 示例：

```bash
export OPENAI_API_KEY=...

python ../run_cf_protocol_experiments.py \
  --array-size 5000 \
  --value-min 1 \
  --value-max 1000 \
  --agent-counts 8 \
  --seeds 1 \
  --topologies mesh one_peer_exponential \
  --merge-mode llm_full_merge \
  --llm-provider openai \
  --model-name gpt-4o-mini \
  --temperature 0.0 \
  --json-retry-attempts 2 \
  --max-parallel-agents 4 \
  --trace \
  --output-dir ../cf_protocol_llm_results
```

默认情况下，LLM protocol merge 如果在重试后仍输出非法 JSON 或非法 CF `structured_state`，会 fallback 到 deterministic merge，并在结果中记录 `TotalDeterministicFallbacks`。如果你要严格测试“LLM 独立给出最后答案”，加：

```bash
--merge-mode llm_full_merge --no-deterministic-repair
```

使用 OpenAI client：

```bash
OPENAI_API_KEY=... python examples/run_array_search.py --llm-provider openai --model-name gpt-4o-mini
```

MAS 也支持显式的角色模型配置，让 emperor、soldier、minister 使用不同的
OpenAI-compatible 平台和模型。未传 `--role-llm-config` 时，旧的
`--llm-provider` / `--model-name` 行为保持不变。传入角色配置后，soldier
会被强制设为 non-thinking；emperor 和 minister 默认允许 thinking：

```bash
export DEEPSEEK_API_KEY=...
export DASHSCOPE_API_KEY=...

python -m exp_graph.mas.cli run \
  --skill-dir configs/mas_skills \
  --n-agents 8 \
  --array-size 1024 \
  --merge-mode llm_full_merge \
  --init-mode llm_local_solve \
  --role-llm-config configs/role_llm_profiles/deepseek_emperor_bailian_soldier.json \
  --output-dir runs/role_llm_demo
```

控制真实 LLM sampling temperature：

```bash
python examples/run_array_search.py \
  --llm-provider openai \
  --model-name gpt-4o-mini \
  --temperature 0.2
```

主实验建议先固定 `--temperature 0.0` 降低随机性；如果要报告稳健性，再额外 sweep `0.2`、`0.7` 等设置。

真实 LLM 如果返回非法 JSON，agent 会进行结构化重试。默认最多重试 2 次，可通过参数调整：

```bash
python examples/run_array_search.py \
  --llm-provider openai \
  --model-name gpt-4o-mini \
  --json-retry-attempts 2
```

retry 发生时，系统会把 schema、validation error、上一次坏响应和原始任务 prompt 发回模型，要求只重新生成一个合法 `belief_state` JSON。retry 的模型调用和 token 会计入 metrics。

保存真实 LLM 调试 trace：

```bash
python examples/run_array_search.py \
  --llm-provider openai \
  --model-name gpt-4o-mini \
  --trace-dir outputs/traces
```

trace 是 JSONL，每行记录一个 agent 在一个通信轮次中的 prompt、raw response、解析后的 belief_state、outbox、neighbors、inbox、token 和 retry 次数。`llm_calls` 会逐次保存该 step 中每一次真实 LLM 调用的 input prompt 和 output response，因此 retry 调用也可审计。`round_idx` 仍然是内部 0-based 索引；metrics 中的 `rounds_to_consensus` 是对外报告用的 1-based 通信轮数。

批量实验时，trace 会按轮追加到磁盘，不默认常驻 `ExperimentResult` 内存。需要在交互式 debug 中同时保留内存副本时，加：

```bash
python examples/run_array_search.py \
  --trace-dir outputs/traces \
  --retain-traces
```

如果打开可选 LLM final adjudicator，输入只包含 task adapter 提供的无标签 adjudication context 和少量 `GroupSummary`。Array search 不会把 `array`、`answer_key` 或 `answer_index` 传给 adjudicator。

## Test

```bash
pytest
```

测试覆盖 topology neighbor correctness、one-peer global round alignment、array shard splitting、initial local solve、outbox derivation、runtime consensus、final reducer 和 minimal end-to-end smoke。
