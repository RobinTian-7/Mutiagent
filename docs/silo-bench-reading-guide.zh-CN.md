# Silo-Bench 主线源码阅读指南（中文）

目标：只读"真实 Silo 实验会执行到"的代码。关键主线文件已加中文导读注释；
本文给出清单、阅读顺序和排除理由。

## 注释约定

- `# ====【模块导读】====`：模块 docstring 之后，翻译该模块的英文 docstring 要点。
- `# 【职责】…`：关键 class/函数上方，一句话职责 + docstring 关键点中文翻译。
- `# 中文：…`：函数体内重要英文注释段的对照翻译（紧贴在原英文注释上方）。
- 所有英文原注释、docstring、LLM 提示词模板**原样保留**，未做任何代码改动。

查漏补缺记录：已补 `agents/schemas.py`、`messaging/messages.py`、
`tasks/protocol_adapter.py`、`aggregator/protocol_final.py`、`metrics/protocol.py`、
`masbench/recipes.py` 和 `masbench/bench.py` 的中文导读注释。

## 执行链总览（对应真实实验命令）

```
masbench.cli (run/run-suite/evolve/bench/curve)
  └─ adapters/silo_bench.py        Silo JSON → BenchmarkInstance
  └─ engine.run_instance / run_fixed_protocol
       ├─ planner-OFF:  exp_graph SynchronousRunner（仅 run/run-suite 不带 --planner）
       ├─ --planner topology_select:  mas/planner.EmperorPlanner（技能库选命名拓扑）
       └─ --planner graph_generate:   mas/graph_generation.plan_free_graph（皇帝 LLM 生成时序 DAG）
             ↓ (protocol_spec / topology_name)
       exp_graph runner/protocol.ProtocolRunner   ← 所有实验臂共用的执行器
             ↓ ProtocolExperimentResult
       adapters/silo_protocol + silo_scoring + engine._score_protocol_result → ScoreResult
  └─ bench.py（四臂对比）/ evolve.py（门控自进化）/ curve.py（学习曲线）
  └─ scripts/full_cluster_eval.py（集群整评：进化曲线 + gen vs fixed/select）
```

- `masbench bench` 的**所有臂**（fixed/select/graphgen/evolved）都走 ProtocolRunner；
- `masbench evolve` = 收集证据 → 大臣提技能补丁 → **留出集验证门**决定是否入库；
- 门的数学：`exp_graph/mas/validation.py::validation_objective`（J_val）+
  `exp_graph/mas/consolidation.py::consolidate_skill_updates`（前后对比、不退步才提交）。

## 推荐阅读顺序

### 第 1 步 · 数据形态（masbench/core，30 分钟）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `masbench/src/masbench/core/instance.py` | 41 | BenchmarkInstance：shards/ground_truth/segmented |
| `masbench/src/masbench/core/benchmark.py` | 20 | 适配器抽象接口 |
| `masbench/src/masbench/core/config.py` | 152 | RunConfig：所有实验旋钮（planner/merge/init/graph_*） |
| `masbench/src/masbench/core/scoring.py` | 19 | ScoreResult：success/partial/消息与 token 计量 |
| `masbench/src/masbench/adapters/silo_bench.py` | 95 | Silo JSON 文件 → 实例（文件名解析、segmented 归一化） |

### 第 2 步 · 任务桥与评分（1 小时）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `masbench/src/masbench/core/task_bridge.py` | 159 | BenchmarkTaskAdapter 六方法 + canonical_answer 规范化 |
| `masbench/src/masbench/adapters/silo_scoring.py` | 291 | partial 分级评分；经 parents[3] 加载 Silo 官方 LIS |
| `masbench/src/masbench/adapters/silo_protocol.py` | 555 | **核心**：SiloProtocolAdapter 信念生命周期 + 提示词模板 |

### 第 3 步 · 引擎执行层（exp_graph，2 小时）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `exp-graph/src/exp_graph/agents/schemas.py` | 100 | BeliefState/BeliefStatus |
| `exp-graph/src/exp_graph/messaging/messages.py` | 49 | OutboxMessage |
| `exp-graph/src/exp_graph/tasks/base.py` | 86 | TaskAdapter 基接口 |
| `exp-graph/src/exp_graph/tasks/protocol_adapter.py` | 188 | ProtocolTaskAdapter 钩子（silo_protocol 实现它） |
| `exp-graph/src/exp_graph/protocols/spec.py` | 79 | ProtocolGraphSpec/StepSpec：时序 DAG 数据结构 |
| `exp-graph/src/exp_graph/protocols/schedules.py` | 535 | 命名拓扑 → 有限通信调度（tree/mesh_star/…） |
| `exp-graph/src/exp_graph/runner/protocol.py` | 1088 | **核心**：ProtocolRunner 主循环（初始化→逐步投递→merge→final） |
| `exp-graph/src/exp_graph/aggregator/protocol_final.py` | 81 | 通用投票聚合 |
| `exp-graph/src/exp_graph/metrics/protocol.py` | 100 | 步级指标 |
| （次线）`exp-graph/src/exp_graph/runner/synchronous.py` | 317 | planner-OFF 平底路径，浏览即可 |

### 第 4 步 · LLM 客户端层（40 分钟）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `exp-graph/src/exp_graph/llm/base.py` | 55 | LLMClient 接口 / usage 合并 |
| `exp-graph/src/exp_graph/llm/factory.py` | 88 | provider 分发；WALLCLOCK_TIMEOUT_ENV 全局超时机制 |
| `exp-graph/src/exp_graph/llm/openai_client.py` | 201 | OpenAI 兼容客户端（本地集群端点也走这里） |
| `exp-graph/src/exp_graph/llm/parser.py` + `retry.py` + `timeout.py` | 206 | belief 解析/JSON 修复/重试提示/墙钟守卫 |
| `exp-graph/src/exp_graph/llm/fake.py` | 328 | 离线确定性客户端（离线 smoke 的行为边界） |
| `masbench/src/masbench/llm/fake.py` + `retry.py` + `timeout.py` | 201 | masbench 侧包装（有界重试在墙钟守卫外层的原因） |

### 第 5 步 · QueenBee 规划：拓扑从哪来（2.5 小时）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `exp-graph/src/exp_graph/mas/schemas.py` | 404 | PlannerRequest/MASPlan/ObjectiveSpec/SkillCard/MASRuntimeConfig |
| `exp-graph/src/exp_graph/mas/planner.py` | 319 | EmperorPlanner：检索→评分→否决→下限→兜底 |
| `exp-graph/src/exp_graph/mas/operators.py` | 120 | 操作子拼协议（local_solve/tree_reduce/…） |
| `exp-graph/src/exp_graph/mas/skill_bank.py` | 966 | 技能库：retrieve/retrieve_avoid/版本化/序列化 |
| `exp-graph/src/exp_graph/mas/scoring.py` | 185 | score_skill：不确定性惩罚 + 同伴归一化 |
| `exp-graph/src/exp_graph/mas/graph_generation.py` | 1638 | **核心**：plan_free_graph 生成→校验→修复→去重→选择→探针→兜底 |
| `exp-graph/src/exp_graph/mas/topology_equivalence.py` | 240 | 等价 DAG 指纹去重 |
| `exp-graph/src/exp_graph/mas/motifs.py` | 400 | 结构母题信用先验 |
| （可选）`exp-graph/src/exp_graph/mas/role_llm.py` | 109 | 皇帝/士兵分模型（仅设 planner_model_name 时激活） |

### 第 6 步 · masbench 引擎桥 + CLI（1 小时，建议读两遍）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `masbench/src/masbench/__init__.py` | 31 | ../exp-graph/src 的 sys.path 兜底桥 |
| `masbench/src/masbench/engine.py` | 572 | **总纲**：run_instance/run_fixed_protocol/_plan_graph_generate |
| `masbench/src/masbench/cli.py` | 511 | 五个子命令如何把参数接到引擎 |

### 第 7 步 · 自进化闭环（3 小时）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `exp-graph/src/exp_graph/mas/runner.py` | 103 | summary_to_aggregate_row：运行摘要 → 证据行 |
| `exp-graph/src/exp_graph/mas/evidence.py` + `ingest.py` + `objective_metrics.py` | 552 | 证据行构造/读写/损失换算 |
| `exp-graph/src/exp_graph/mas/evolution.py` | 1085 | ResultAnalystMinister：证据 → 技能补丁 |
| `exp-graph/src/exp_graph/mas/validation.py` | 155 | **J_val 目标函数**（门的打分一半） |
| `exp-graph/src/exp_graph/mas/consolidation.py` | 871 | **验证门**：J 前后对比、不退步才提交 |
| （可选）`exp-graph/src/exp_graph/mas/insights.py` | 950 | LLM 设计洞见 + 证伪（--use-llm-insights 才启用） |
| `masbench/src/masbench/task_classify.py` + `task_features.py` | 369 | 任务分类/特征（技能触发条件用） |
| `masbench/src/masbench/recipes.py` + `transfer.py` + `cache.py` + `diag.py` | 1239 | 配方搜索/技能迁移信任/证据缓存/诊断 |
| `masbench/src/masbench/evolve.py` | 1974 | **核心**：run_evolution 全流程（含合成留出集的离线诚实性） |

### 第 8 步 · 实验 harness（2 小时）
| 文件 | 约行数 | 读什么 |
| --- | --- | --- |
| `masbench/src/masbench/bench.py` | 1829 | 四臂对比：run 单元隔离/checkpoint/--resume/--workers |
| `masbench/src/masbench/curve.py` | 290 | 数据量曲线 + 轮次曲线 |
| `masbench/scripts/full_cluster_eval.py` | 279 | 集群整评：K 次独立进化 + round 级断点续跑 |

## 排除清单（真实 Silo 实验不经过）

| 路径 | 理由 |
| --- | --- |
| `masbench/adapters/jssp_bench.py`, `jssp_protocol.py` | JSSP 基准，仅 `--benchmark jssp` 时用 |
| `exp_graph/tasks/count_frequency.py`, `metrics/cf_protocol.py`, `aggregator/cf_final.py` | Count-Frequency 传统任务；protocol.py 引用它们只为 CF 字节兼容，Silo 分支不经过 |
| `exp_graph/topology/`, `agents/agent.py`, `aggregator/final_reducer.py`, `aggregator/runtime_consensus.py`, `metrics/logger.py`, `llm/prompts.py` | SynchronousRunner（planner-OFF 平底路径）专属依赖 |
| `exp_graph/mas/{cli,benchmark,pipeline,search,workflow,langgraph_workflow,matrix,formatting,llm_planner}.py` | CF 时代的 pipeline/CLI 入口，masbench 不引用（已 grep 验证） |
| `exp_graph/tracing/` | masbench 固定 trace_enabled=False |
| `exp-graph/examples/`, `exp-graph/scripts/` | CF 示例与旧实验脚本 |
| `archive/` | 冻结历史（原型、vendored 代码、实验台账） |

## 与真实实验命令的对应

- `masbench run-suite --llm fake`（离线 smoke）：第 1、2 步 + SynchronousRunner。
- `masbench run --planner --planner-mode graph_generate`：第 1–6 步全链路。
- `masbench evolve`：再加第 7 步。
- `masbench bench --arms fixed select graphgen evolved`：再加 bench.py。
- `scripts/full_cluster_eval.py`（集群 GPT-OSS 整评）：evolve + curve 的组合复用。
