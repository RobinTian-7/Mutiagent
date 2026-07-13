# Leakage fixes + sink / all_agents evaluation modes (2026-07-11)

本文记录 2026-07-11 的端到端修复：(A) 答案/拓扑泄漏、指数图注入、fallback
污染与审计缺失的修复；(B) Silo-Bench 新增 `sink` 与 `all_agents` 两种真正
独立的评测模式。两种模式在 **生成、执行、评分、SkillBank、缓存、报告** 六层
全部隔离。

## A. 泄漏修复：数据流前后对比

### 修复前（contaminated 世代）

```
silo JSON ──> instance.meta{expected_outputs, optimal_topology, ...}
          ──> build_global_task() 把 meta 整个塞进 global_task
          ──> format_adjudication_context()（顶层黑名单，嵌套字段直接穿过）
          ──> TASK_CONTEXT_JSON ──> 模型可见 ✗ 答案+最优拓扑泄漏
task_description（含 "Communication Protocol: Topology: Chain ..."）
          ──> 每个 agent 的提示词 ✗ 拓扑泄漏
graphgen 提示词 required_json_shape：distance-doubling/pow2(r)/ceil_log2 示例
          ──> 皇帝 LLM ✗ 指数图注入
graphgen 失败 ──> _fallback_operator_plan ──> one_peer_exponential_dag_star
          ──> 记为 graphgen 臂结果 ✗ fallback 污染
架构师提示词/回复 ──> TemporaryDirectory ──> 删除 ✗ 不可审计
```

### 修复后（clean 世代）

```
silo JSON ──> sanitize_task_description()   # 整段删除 Communication Protocol
          ──> meta 剥掉 optimal_topology/optimal_message_count/theoretical_complexity
          ──> build_global_task():
                公开字段 + PRIVATE_SCORING_KEY("_private_scoring")
                └─ answer_key / expected_outputs 只存在于私有载荷
模型可见面（唯一入口 public_task_view，显式白名单、嵌套安全）：
    task_family/benchmark/task_ref(sha256(case_id)[:12])/case_name/
    n_agents/output_type/segmented        # 无 meta、无 shards、无 case_id
评分器（唯一入口 private_answer_key / private_expected_outputs）
    └─ 读 _private_scoring —— 与模型上下文物理隔离
graphgen 提示词：required_json_shape 只含 "<int expression>" 类型/语法占位符；
    程序语言说明只保留 abs/min/max 与通用运算符（无 pow2/ceil_log2/floor_log2）
graphgen 失败 ──> GraphGenerationError ──> 运行失败(success=False,
    extra.graph_generation_failed=原因)；绝无具名拓扑兜底
每次架构师调用 ──> 持久目录 runs/graphgen_artifacts/<case>_<n>_<seed>_<mode>_<ts>/
    architect_call.json：脱敏渲染提示词 + prompt_sha256 + 原始回复 +
    逐候选解析/展开边/校验/修复记录 + 失败原因 + 最终选择原因
    （API key 值级扫描替换为 [REDACTED:<ENV>]）
所有模型可见提示词 ──> leakage audit（exp_graph.mas.leakage_audit）：
    禁 expected_output(s)/answer_key/ground_truth/optimal_topology/
    optimal_message_count/"communication protocol"/one_peer/exponential/
    distance-doubling/pow2 —— 命中即抛错，绝不发送
```

### Provenance（结构来源）

每个候选与 SkillCard 记录 `provenance ∈ {llm_generated, skill_replay,
fixed_named, named_fallback, fake}`（解析层强制盖章，模型自称值不采信）。

- **clean GraphGen**（默认 `RunConfig.clean_graphgen=True`）：技能检索传
  `provenance_allowlist=["llm_generated","skill_replay"]`；缺 provenance 的旧卡
  视为 **contaminated** 一律排除（文件不删）；fixed 臂证据
  （`fixed_named`）对 GraphGen 完全不可见——拓扑名、边表、性能证据都进不来。
- **非 clean 路径**：`evolved_mode=select_then_refine` 按定义要从具名锚点精修
  （fixed→graphgen 迁移），每条记录标注 `clean_graphgen=False`，不得用于
  clean GraphGen 结论。

## B. 两种评测模式

统一类型：`exp_graph.mas.schemas.InformationGoal = Literal["sink","all_agents"]`。
CLI：`--silo-eval-mode sink|all_agents`（masbench run/run-suite/bench/evolve/
curve 与 `scripts/verify_beats_baselines.py`）。`RunConfig.silo_eval_mode`、
`PlannerRequest.information_goal`、`MASRuntimeConfig.information_goal`、
`GraphValidationOptions.information_goal`、适配器、`EvidenceCache.key`
（`mode=...` 字段）、`results.json`/report.md 头部、SkillCard trigger 与 verify
manifest 全部携带该模式。旧核心调用默认 sink 兼容；科学脚本必须显式传参。

### 结构传播检测（与 LLM 答案正确性无关）

`exp_graph.mas.information_flow`：`knowledge[i]` 初始 `{i}`；每步同时执行，
`next` 先复制旧状态，对每条 `src->dst` 令 `next[dst] |= previous[src]`；发送者
与未接收者保留旧状态。

- sink 通过：`knowledge[selected_primary] ⊇ {0..n-1}`。
- all_agents 通过：对每个 j，`knowledge[j] ⊇ {0..n-1}`。

### 图校验与修复（按模式切换，绝不混用）

- sink：沿用汇点覆盖校验；修复=补"未覆盖→汇点"边（`_repair_sink_coverage`）。
- all_agents：校验=全员全覆盖（gather-only star 直接判无效）；修复=
  `_repair_all_agents_coverage` 传播/共识阶段（先聚到枢纽、再枢纽广播），
  预算内补不齐则留给校验拒绝。**不得用 sink 修复冒充 all_agents 修复**。

### 评分

- **sink**：只有 selected_primary 的答案用于主评分。sink_id 解析：生成图取
  `protocol_spec.metadata.selected_primary`；具名拓扑取结构覆盖率最高者
  （并列取最小 id）。输出 `sink_exact / sink_partial / sink_id /
  sink_information_coverage / messages / model_calls / tokens`；
  其他 agent 保留局部状态、不要求正确。
- **all_agents**：逐 agent 独立判分（非 segmented 对同一全局答案；segmented
  对各自 expected output）。输出 `per_agent_correct / agent_success_rate S /
  all_agents_exact(仅 S=1) / partial P / information_coverage_by_agent /
  mean|min_information_coverage / all_agents_full_information / messages /
  tokens / communication_density(=消息数 / (n·(n-1)·步数))`。
  **主 success = all_agents_exact，多数票永不作数**：gather-only star 即使
  sink 正确也判失败；多数对、一个错 → 失败。

### Prompt 分离（六个独立构造函数）

架构师：`build_sink_graph_prompt` / `build_all_agents_graph_prompt`
（`build_free_graph_prompt` 保留为分派器）。士兵：
`format_sink_protocol_init_prompt` / `format_sink_protocol_merge_prompt` /
`format_all_agents_protocol_init_prompt` /
`format_all_agents_protocol_merge_prompt`。

两套模板在角色、目标、图约束、完成条件、输出解释与自检上均不同：

- sink 架构师："SINGLE-SINKPOINT"，偏 gather/reduce/单汇点/低冗余，自检
  "任一 source 无时序路径到 sink 即自拒"；sink 士兵："只有指定 sink 负责最终
  全局答案；接收者无损合并并继续向 sink 转发；非 sink 不要求持有全局答案"。
- all_agents 架构师："FULL-DISSEMINATION"，要求 spread-back/return/consensus
  阶段，完成条件=每个 agent 收到所有人信息，自检"任一 agent 信息不全即自拒/
  只汇不散即自拒/依赖单一 leader 即自拒"；all_agents 士兵："每个 agent 都必须
  最终持有正确答案并独立提交；持续传播新信息；不得把 selected_primary 当唯一
  持有者"。模板有 snapshot 测试（内容与哈希均不同）且全部过泄漏审计。

### SkillBank / 训练隔离

- 卡片：`information_goal` 进 trigger 与顶层字段，显式模式下 `skill_id` 追加
  `__sink`/`__all_agents` 后缀；检索按请求模式过滤（缺目标的旧卡=legacy sink，
  绝不进 all_agents）；`_skill_equivalence_key` 带模式前缀，压缩/去重不可跨模式
  合并。CF 等无显式目标的 legacy 证据 → 卡片字节级不变。
- 证据行携带 `information_goal` + `provenance`；`run_evolution` 在 gate 前断言
  行模式一致（混模式即抛错），summary 记录 `information_goal`。
- motif：行带 `information_goal`，聚合前按当前模式过滤（bench 两条路径）；
- recipe/exemplar/迁移信任台账经 deployment_view 读卡片证据（卡片已按模式
  隔离）；证据/评估缓存键含 `mode=`。
- `clean_run` 标志写入 bench `results.json` 与 verify 报告/manifest。

## 测试与 demo

- `masbench/tests/test_eval_modes_and_leakage.py`（12 项）与
  `exp-graph/tests/test_information_flow_modes.py`（11 项）覆盖规范的 15 类
  必测；两包全量离线套件：exp-graph 291 passed + 2 skipped，masbench 330 passed。
- 离线 demo（不调用任何付费 API）：
  - `uv run python scripts/demo_sink_mode.py` —— 单汇点 full coverage +
    sink 模式 fixed/graphgen 端到端；
  - `uv run python scripts/demo_all_agents_mode.py` —— gather-only 被拒、
    gather+broadcast 通过、一错全败。

## 已知限制

1. 结构覆盖按**计划内**调度边计算（非逐条实际投递）；运行器只在 outbox 缺失时
   跳投递，两者差异极小，但严格说 coverage 是结构上界。
2. sink 模式对 segmented 任务按 sink 自身分段判分（语义上 sink 只对自己的
   分段负责）；如需"sink 汇总全部分段"语义需另行定义输出格式。
3. `select_then_refine` 与 clean GraphGen 定义冲突，按"非 clean 路径"保留并
   标注，而非删除。
4. 旧 SkillBank 文件未迁移（按规范不删除）；它们在 clean 检索中不可见。
5. 泄漏审计是子串级：它保证禁令 token 不出现，不能证明语义级零泄漏。
6. 士兵在 llm_full_merge 下理论上可在 belief 里自由转述分片内容——审计管住
   我们注入的上下文，不管模型自己生成的文本（这是所有多 agent 通信的固有面）。
