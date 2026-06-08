# masbench: 干净的 MAS Benchmark 流水线 + 外部 benchmark 集成

- **日期**: 2026-06-07
- **状态**: 设计已通过，进入实现计划
- **分支**: `codex/topology-equivalence-dedup`
- **作者**: tcjclaude@gmail.com + Claude

## 1. 背景与目标

仓库里有一篇论文 **"QueenBee Planner: Skill-Evolving Communication Topologies for
Token-Efficient LLM Multi-Agent Systems"**（`paper/acl_draft.tex`）。其实验只用一个合成任务
**Count-Frequency (CF)**：全局数组被切片给 N 个 agent，agent 之间按**时序 DAG 拓扑**通信，
末端 agent 输出全局频率向量，按 **RMSE / exact-match / messages / tokens** 评分。论文真正的
贡献是一个**生成拓扑的 planner + 自进化的 skill bank**。

可运行的流水线在 `exp-graph/`（顶层 `run_cf_*.py` 只是调用它）。核心抽象是 `TaskAdapter`。

**目标**：从中提取/重构一个**干净、可复用的 pipeline**（新包 `masbench/`，复用 `exp_graph` 引擎），
并接入三个外部 MAS benchmark，让用户能跑测试。三个 benchmark 分两种范式：

| Benchmark | 性质 | 与本 pipeline 的契合度 |
|---|---|---|
| **Silo-Bench** (arXiv 2603.01045, github.com/jwyjohn/acl26-silo-bench) | 30 个分布式协调算法任务，3 个复杂度等级；每个 agent 持私有 shard，exact-match + partial-correctness 评分 | **直接契合**——是 CF 任务的 30 任务版扩展 |
| **REALM-Bench** (ACM 10.1145/3770854.3785692, Geng & Chang, KDD'26) | 真实世界动态**规划/调度** | 不同范式——"MAS 产出方案"，按合法性/最优性评分 |
| **M-APPLE-OS / ALAS** (github.com/genglongling/M-APPLE-OS, arXiv 2505.12501) | **作业车间调度 JSSP** (DMU/TA/ABZ/SWV/YN) | 不同范式——输出是**调度方案**，按 makespan/optimal-rate 评分 |

REALM-Bench 与 M-APPLE-OS 同一作者 (Longling Geng)，都是规划/调度，共享一套"调度任务"框法。

## 2. 已确认的决策

1. **范围/顺序**：先做 Silo-Bench，再做 REALM-Bench + M-APPLE-OS（Phase 2）。
2. **pipeline 核心**：**可配置**——QueenBee 的 planner 与 skill-evolution 做成每次运行可开/关的开关。
3. **首个里程碑**：**离线 fake-LLM 冒烟测试 + 一条文档化的真实模型运行命令**，两者都要。
4. **代码位置**：**新建独立包** `masbench/`，复用 `exp_graph` 引擎，不重写引擎。
5. **数据与评分**：benchmark 用 **git submodule/下载脚本** 拉取，**复用官方评分器**（不可用时回退自算）。
6. **planner-ON 路径（设计后追加）**：在 Silo-Bench 上跑 **完整时序DAG QueenBee**（而非仅拓扑选择）。

### 2.1 设计后关键工程发现（影响落地）

`exp_graph` 有**两条执行引擎**：
- `SynchronousRunner`（`runner/synchronous.py`）— **任务无关**，只用基类 6 方法 `TaskAdapter`，物理邻居拓扑
  (`chain/ring/star/mesh/static_exponential/one_peer_exponential`)，终聚合/指标均通用。`array_search.py` 即范例。
  → **Silo-Bench planner-OFF 干净走这条，不改引擎。**
- `ProtocolRunner` + `MASProtocolRunner`（`runner/protocol.py`）— 论文 QueenBee 的**时序DAG/有限协议**路径，
  但 **CF 写死**：类型注解 `CountFrequencyTaskAdapter`，调 CF 专用 protocol-belief 方法，终聚合/指标用模块级
  `run_cf_final_aggregation` / `build_cf_step_metrics`(RMSE)。`FakeLLMClient` 也只支持 CF/array-search。

因此「完整时序DAG QueenBee 跑 Silo-Bench」必须**把 CF 写死的协议引擎泛化**（与「不重写引擎」的初衷有张力，
用户已确认走完整路线）。据此把工作**拆成依赖有序的 3 个可执行计划**：
- **Plan 1** 基础设施 + planner-OFF 可跑里程碑（`SynchronousRunner` 路径，离线冒烟 + 真实运行）→ 即「能跑测试」。
- **Plan 2** 通用协议运行器（把 `ProtocolRunner` + 终聚合 + 步指标泛化为任务无关；Silo 协议适配器）。
- **Plan 3** 完整 QueenBee（时序DAG 生成 + skill-evolution 接到通用协议路径；进化指标 RMSE→通用；官方 partial 评分）。

计划文件：`docs/superpowers/plans/2026-06-07-masbench-plan1-foundation.md`（Plan 1 全量；Plan 2/3 在其末尾有概要）。

## 3. 核实过的硬事实（实现依据）

### 3.1 `exp_graph.TaskAdapter` 接口（`exp-graph/src/exp_graph/tasks/base.py`）

抽象方法（必须实现）：
- `build_global_task(self, **kwargs) -> dict` — 构造/归一全局任务
- `split_into_local_observations(self, global_task, n_agents) -> list[dict]` — 切成每 agent 局部观测
- `initial_local_solve(self, local_observation) -> dict` — 仅凭局部观测的初始 belief_state
- `normalize_consensus_key(self, key_or_proposal: str | None) -> str` — 归一答案 key（用于分组/投票）
- `evaluate_final_answer(self, global_task, final_key: str | None) -> bool` — 判定最终 key 是否解对
- `format_task_prompt_context(self, global_task, local_observation) -> str` — agent prompt 的任务上下文

可覆写：`format_consensus_key_instructions()`、`format_adjudication_context()`（后者会屏蔽
`answer/answer_key/ground_truth/label` 等字段，防止泄漏 ground truth）。

### 3.2 `exp_graph` 执行入口

- **固定拓扑路径**：`ProtocolRunner(config: ProtocolRunnerConfig, task_adapter, global_task).run()`
  返回 `ProtocolExperimentResult`（含 `to_summary_dict()`）。
  `ProtocolRunnerConfig` 关键键：`topology_name, n_agents, seed, merge_mode, init_mode, protocol_spec`。
- **planner 路径**：`exp_graph.mas.runner.MASProtocolRunner(skill_bank, task_adapter).run(request: PlannerRequest, global_task, seed, evolve: bool)`。
  内部：`EmperorPlanner(skill_bank).plan(request)` → `MASPlan(topology_name, protocol_spec, config_overrides)` → `ProtocolRunner`。
  `evolve=True` 时跑 `ResultAnalystMinister().analyze(...)` + `consolidate_batch(...)` 更新 skill bank。
- **网格/批量**：`exp_graph/mas/matrix.py`（run-matrix / eval-matrix / collect-matrix）。
- **planner/skill 相关**：`EmperorPlanner`(`mas/planner.py`)、`SkillBank`(`mas/skill_bank.py`)、
  `mas/evolution.py`、`mas/schemas.py`（`PlannerRequest/MASPlan/ObjectiveSpec/SkillCard`）。
- **LLM**：`exp_graph/llm/factory.py` + `fake.py`（fake 离线）+ `mas/role_llm.py`（role profile：emperor/soldier/minister 各自端点）。
- **注意**：`exp_graph/metrics/cf_protocol.py` 的指标是 **CF/RMSE 专用**，不通用 → masbench 自带通用 scorer。

### 3.3 Silo-Bench 数据 schema（`benchmarks/{Level}-{NN}_n{agents}.json`，180 个文件）

每个实例（已核实，样本 `benchmarks/I-01_n2.json`）：
```json
{
  "case_id": "I-01", "case_name": "Global Max", "paradigm": "Paradigm I",
  "leetcode": {...},
  "metadata": {
    "num_agents": 2, "optimal_topology": "Star ... then broadcast",
    "optimal_message_count": "...", "theoretical_complexity": "O(N) - MapReduce/Aggregation",
    "output_type": "distributed", "is_segmented": false
  },
  "task_description": "**Task: Global Maximum** ... {agent_id} ... {input_shard} ...",
  "agent_configs": [
    {"agent_id": 0, "system_prompt": "[PLACEHOLDER]...", "user_prompt": "...rendered...",
     "input_shard": [309, -772, ...], "expected_output": 827},
    {"agent_id": 1, "input_shard": [...], "expected_output": 827}
  ]
}
```
关键点：
- **ground truth 直接内嵌**在每个 `agent_configs[].expected_output`（Global Max 是同一全局标量；
  其他任务类型可能是列表/字典）。→ **Success Rate (exact-match) 无需任何外部代码**。
- 30 任务 / 3 等级：Level I 聚合 (I-01..I-10)、Level II mesh 邻居通信 (II-11..II-20)、
  Level III 全局 shuffle (III-21..III-30)；agent 规模 ∈ {2,5,10,20,50,100}。
- **官方评分/引擎**：`src/{broadcast,msg,sfs}/evaluate.py`、`src/utils/metrics.py`、`src/engine.py`、
  `src/batch_run.py`、`src/analyze.py`、`src/models.py`。`broadcast/msg/sfs` 是其三种通信协议
  （广播 / P2P 消息 / 共享文件系统）——**我们不使用其引擎驱动**，只用其数据 + 可选 partial 评分。

## 4. 架构（`masbench/` 新顶层包）

```
masbench/
├── pyproject.toml                # 依赖 exp_graph（uv workspace 成员 / path 依赖）+ pyyaml
├── src/masbench/
│   ├── core/
│   │   ├── instance.py           # BenchmarkInstance（归一化数据结构）
│   │   ├── benchmark.py          # BenchmarkAdapter ABC（iter_instances + scorer 工厂）
│   │   ├── task_bridge.py        # 通用 BenchmarkTaskAdapter(exp_graph.TaskAdapter)
│   │   ├── scoring.py            # ScoreResult + 通用评分（success/partial/cost，不绑定 RMSE）
│   │   ├── config.py             # RunConfig（planner 开关 / 拓扑 / LLM / seed …）
│   │   └── registry.py           # benchmark 名称 -> adapter
│   ├── adapters/
│   │   └── silo_bench.py         # Phase 1：Silo-Bench 加载 + 评分
│   ├── engine.py                 # RunConfig + instance -> exp_graph 运行器（planner on/off 分流）
│   └── cli.py                    # masbench run / run-suite / report
├── third_party/                  # git submodule: acl26-silo-bench（后续 + M-APPLE-OS / REALM-Bench）
├── configs/                      # 示例 run 配置（smoke / real）
├── tests/test_silo_smoke.py      # 离线 fake-LLM 端到端冒烟
└── README.md                     # 离线 + 真实两种跑法
```

## 5. 核心抽象

```python
@dataclass
class BenchmarkInstance:
    benchmark: str            # "silo_bench"
    case_id: str              # "I-01"
    case_name: str            # "Global Max"
    n_agents: int
    shards: list[Any]         # 每个 agent 的私有数据（index = agent_id）
    ground_truth: Any         # 全局期望答案
    task_prompt: str          # 任务描述模板（含 {agent_id}/{input_shard} 占位）
    meta: dict                # paradigm / complexity / optimal_topology / output_type …

@dataclass
class ScoreResult:
    success: bool             # 精确匹配（主指标 = Success Rate）
    partial: float | None     # [0,1] 任务定制（可选）
    n_messages: int
    n_model_calls: int
    tokens: int
    extra: dict

class BenchmarkAdapter(ABC):
    name: str
    def iter_instances(self, **filters) -> Iterable[BenchmarkInstance]: ...
    def make_scorer(self, instance) -> Callable[[Any, dict], ScoreResult]: ...
    # to_task_adapter 由通用桥提供，benchmark 一般无需自定义
```

- **`BenchmarkTaskAdapter(TaskAdapter)`**：通用桥，输入一个 `BenchmarkInstance` + 一个 scorer，
  实现 6 个抽象方法：
  - `build_global_task` → 把 instance 转成 global_task dict（shards 合并视图 + 私有 ground_truth 字段，
    字段名用会被 `format_adjudication_context` 屏蔽的 `answer_key/ground_truth` 以防泄漏）。
  - `split_into_local_observations` → 用 `instance.shards[agent_id]` 产出每 agent 观测。
  - `initial_local_solve` → 给一个保守的初始 belief（或交给 `init_mode=llm_local_solve`）。
  - `evaluate_final_answer` → 解析最终 key → 与 `ground_truth` 做归一化 exact-match → bool。
  - `format_task_prompt_context` → 用 `instance.task_prompt` 渲染。
  - `normalize_consensus_key` → 把答案规范化为 canonical JSON 字符串（排序）。

```python
@dataclass
class RunConfig:
    benchmark: str
    use_planner: bool = False           # planner 开关（关键）
    use_skill_evolution: bool = False
    topology: str = "one_peer_exponential_dag_star"  # planner 关时使用
    objective: str = "balanced"         # planner 开时使用
    n_agents: int | None = None         # 默认取 instance.n_agents
    max_rounds: int = 4
    merge_mode: str = "llm_full_merge"
    init_mode: str = "llm_local_solve"
    llm: str = "fake"                   # "fake" | provider 名 | role-profile 路径
    seed: int = 0
```

## 6. 引擎桥（`engine.py`）

```python
def run_instance(instance, cfg: RunConfig) -> RunResult:
    scorer = registry.get(cfg.benchmark).make_scorer(instance)
    task_adapter = BenchmarkTaskAdapter(instance, scorer)
    global_task = task_adapter.build_global_task()
    n = cfg.n_agents or instance.n_agents
    if not cfg.use_planner:
        config = ProtocolRunnerConfig(topology_name=cfg.topology, n_agents=n, seed=cfg.seed,
                                      merge_mode=cfg.merge_mode, init_mode=cfg.init_mode)
        result = ProtocolRunner(config=config, task_adapter=task_adapter, global_task=global_task).run()
    else:
        request = PlannerRequest(n_agents=n, objective=cfg.objective,
                                 merge_mode=cfg.merge_mode, init_mode=cfg.init_mode)
        result = MASProtocolRunner(skill_bank, task_adapter).run(
            request=request, global_task=global_task, seed=cfg.seed, evolve=cfg.use_skill_evolution)
    return assemble_run_result(instance, cfg, result, scorer)
```
- LLM 选择：`cfg.llm == "fake"` → exp_graph fake client；否则走 `llm/factory.py` 或 role profile。
- planner 开时需要一个 `SkillBank`（可空/默认初始化，或从 `configs/mas_skills` 加载）。

## 7. CLI

- `masbench run --benchmark silo_bench --case I-01 --n-agents 2 --llm fake`
- `masbench run-suite --benchmark silo_bench --levels I --agent-counts 2,5 --llm fake --out runs/smoke [--planner] [--evolve]`
- `masbench report --run-dir runs/smoke` → 汇总 success-rate / partial / 成本（messages/calls/tokens）表。

输出：每个实例一条 JSON 记录（instance 元数据 + RunConfig + ScoreResult + trace 摘要），suite 级
汇总 CSV/JSON + markdown 报告。

## 8. Silo-Bench 评分策略

- `success`：解析 MAS 最终答案 → 与 `instance.ground_truth` 归一化精确匹配。**自算，零外部依赖。**
  - 答案抽取需按 `meta.output_type` / 任务类型稳健解析：标量（Global Max）、列表（Distributed Sort）、
    字典等 → canonical JSON。
- `partial`：可选。优先尝试 import Silo-Bench `src/utils/metrics.py` / `src/{protocol}/evaluate.py`；
  若与其 engine 输出耦合不可直接用，则 Phase 1 先给少量自写回退（如排序按位置正确率、集合用 Jaccard），
  其余返回 `None`。官方 partial 逐步接。

## 9. 里程碑

**M1（离线冒烟）**：`pytest masbench/tests/test_silo_smoke.py` —— 用 fake-LLM 对 ~3 个小实例
（如 I-01_n2, I-02_n2, II-11_n2）planner 关 + 开 各跑通，断言产出合法 `ScoreResult`（fake 下不要求答对，
只验证端到端链路与评分不报错）。另 `run-suite ... --llm fake` 可跑。

**M2（真实运行命令）**：README 文档化命令，用现有 `configs/role_llm_profiles/*.json`：
```
masbench run-suite --benchmark silo_bench --levels I --agent-counts 2 \
  --llm-profile configs/role_llm_profiles/<profile>.json --out runs/silo_real
```

## 10. Phase 2 草图（之后单独 spec）

REALM-Bench + M-APPLE-OS = 调度/规划范式。新增 `SchedulingBenchmarkAdapter`：实例携带问题规格
（jobs/machines/约束），输出是**调度方案**，评分调官方校验器（M-APPLE-OS `src/utils/validation_tools.py`
的 success/optimal-rate；REALM-Bench scorer）——非 RMSE/exact。MAS 框法：agent 各持子问题、按拓扑
通信、终端 agent 拼装方案。`ScoreResult` 已能容纳（success=合法且最优, partial=optimal-rate, extra=makespan）。

## 11. 不做（YAGNI / 非目标）

- 不重写 `exp_graph` 引擎（复用 ProtocolRunner / MASProtocolRunner / EmperorPlanner / SkillBank）。
- 不动论文代码、顶层 `run_cf_*.py`、顶层 `/src`（Claim-DAG 那套）。
- Phase 1 不实现 REALM-Bench / M-APPLE-OS。
- 不一次性重写全部 30 个 Silo-Bench partial 评分器——先保 success。

## 12. 风险/待定（实现期解决）

1. **打包**：`masbench` 如何 import `exp_graph` —— 倾向 uv workspace 成员或 path 依赖；需确认现有
   `exp-graph/pyproject.toml` 与 `uv.lock` 的安装方式。
2. **官方 partial 评分器**可能与 Silo-Bench engine 输出格式耦合，需小 shim；success 不受影响。
3. **答案抽取**：把 MAS 字符串答案稳健解析回 标量/列表/字典 做 exact-match（按 output_type 分派）。
4. **planner 开时的 SkillBank 初始化**：空 bank vs 复用 `configs/mas_skills`，需在桥里给合理默认。

## 13. 关键文件引用

- 接口：`exp-graph/src/exp_graph/tasks/base.py`
- 固定拓扑运行器：`exp-graph/src/exp_graph/runner/protocol.py`
- planner 运行器：`exp-graph/src/exp_graph/mas/runner.py`
- planner / skill：`exp-graph/src/exp_graph/mas/planner.py`、`mas/skill_bank.py`、`mas/evolution.py`、`mas/schemas.py`
- 网格：`exp-graph/src/exp_graph/mas/matrix.py`
- LLM：`exp-graph/src/exp_graph/llm/factory.py`、`llm/fake.py`、`mas/role_llm.py`
- CF 参考实现（对照模板）：`exp-graph/src/exp_graph/tasks/count_frequency.py`
- Silo-Bench：`github.com/jwyjohn/acl26-silo-bench`（`benchmarks/*.json`、`src/utils/metrics.py`、`src/{broadcast,msg,sfs}/evaluate.py`）
