# 给实现 Agent 的完整提示词：独立 Python Code Planner

你正在仓库中工作：

`/Users/robintian/AI/queenbee-clean`

请先阅读根目录 `AGENTS.md`，再检查 `git status --short` 和相关实现。当前工作树包含用户未提交的重要改动；不得回退、覆盖、格式化、搬移或整理无关文件。不要使用 `git reset --hard`、`git checkout --` 等破坏性命令。不要修改 `archive/` 和 `masbench/third_party/`，不要提交 `runs/` 产物。

## 一、先确认并保护现有实现

本任务开始前，仓库已经存在且必须保持可用的独立路径：

1. `topology_select`：选择具名拓扑。
2. `operator_compose`：组合现有操作子。
3. `graph_generate`：自由 GraphGen；仍支持显式时序边和现有 `topology_program_v1`。不得删除、改名或改成受限 DSL。
4. `program_generate`：受限 `phase_program_v1` 阶段 DSL；只允许 `gather`、`broadcast`、`pairwise_exchange`、`consensus`，由确定性编译器展开。不得让本任务复用、替换或绕过它。
5. bench 中已有 `graphgen` 和 `programgen` 两个互相独立的 arm，以及 fixed、p2p、broadcast、sfs、evolved 等路径。

当前自进化实现也属于受保护行为：

- 训练信号按 `V -> K -> U -> P -> S` 分阶段：程序/结构合法性、信息覆盖、提交率、部分正确率、成功率；`C/D` 作为成本指标单独记录。
- 生成失败要形成 `validity=0` 的训练证据，并只能进入负面 `counterexample/failure_modes`，不能成为可选择的成功技能。
- SkillCard 分开保存 `organization_policy` 与 `reasoning_policy`。
- 技能按 `information_goal + planner_mode + provenance` 隔离。
- 已有同 `(case, seed, n, goal)` 的逐技能配对消融、保持各 Level 都有训练样本的课程增长，以及 full-information single-agent 能力诊断。

新增功能必须采用加法式集成。不得把任何现有分支统一改写为 Python 路径，不得扩大现有 GraphGen/ProgramGen 的 clean provenance 白名单，不得改变论文 fixed transports 的 Prompt、调度、评分和指标。

开始实施前，先定位并理解这些文件，但不要因它们处于 dirty 状态而重写：

- `exp-graph/src/exp_graph/mas/schemas.py`
- `exp-graph/src/exp_graph/mas/graph_generation.py`
- `exp-graph/src/exp_graph/mas/phase_program.py`
- `exp-graph/src/exp_graph/mas/phase_program_generation.py`
- `exp-graph/src/exp_graph/mas/skill_bank.py`
- `masbench/src/masbench/engine.py`
- `masbench/src/masbench/evolve.py`
- `masbench/src/masbench/bench.py`
- `masbench/src/masbench/curve.py`
- `masbench/scripts/verify_beats_baselines.py`

## 二、目标：新增第五种独立 Planner 模式

新增可选模式：

```text
planner_mode = "python_generate"
```

对应 bench 非默认 arm：

```text
--arms pycodegen
```

仅在 `python_generate` 模式下，Planner LLM 不输出 JSON 边表、`topology_program_v1`、`phase_program_v1` 或 `ProtocolGraphSpec`，而是输出一份完整、可保存、可独立执行的 `program.py`。

这句话只约束新模式。原 `graph_generate` 和 `program_generate` 的输入输出契约必须保持原样。

生成程序直接使用仓库现有 `LLMClient`/OpenAI-compatible client 调用 Worker Agent，并自行维护：

- 每个 Agent 的上一轮状态；
- 每个 Agent 的 inbox；
- Agent 本轮是否发送；
- 消息接收者；
- 跨轮消息投递；
- 每个 Agent 的最终提交；
- 模型调用、消息、token 和轮数账本。

若代码存在语法、API、数据流、安全策略、预算、输出 schema 或 fake dry-run 错误，最多进行 3 次有界 ReAct `replace_code` 修复。修复失败必须诚实记录为 `python_generation_failed`，禁止静默切换到具名拓扑、GraphGen、ProgramGen 或任何固定协议。

## 三、不要新增模型编排 DSL

禁止给生成程序新增以下类型的高层编排接口：

```python
ctx.call_agents()
ctx.send()
ctx.next_round()
ctx.submit_all()
```

生成程序应直接使用现有客户端接口，例如：

```python
from exp_graph.llm.factory import create_llm_client

client = create_llm_client(
    worker_cfg["provider"],
    base_url=worker_cfg.get("base_url"),
    api_key_env=worker_cfg.get("api_key_env"),
)
response = client.complete(
    prompt,
    model_name=worker_cfg["model_name"],
    temperature=worker_cfg["temperature"],
)
```

允许新增宿主侧 `PythonCodePlanner`、`CodeValidator`、`CodeRepairLoop`、`CodeProcessRunner` 以及仅用于 Python 子进程的计量/安全包装器。这些只负责生成、检查、执行和权威记账，不得暴露 send/round/topology 等新编排原语，也不得改变共享 `create_llm_client` 或其他模式的行为。

## 四、完整可执行程序契约

生成结果必须是完整 `program.py`，不能是代码片段、Markdown 代码围栏、补丁或带 TODO/占位符的模板。

程序必须：

1. 从 stdin 读取一个 sanitized execution payload。
2. 使用 payload 中宿主授权的非秘密 Worker 配置；不得硬编码或修改 provider、model、base URL、temperature、API key env 名或预算。
3. 只通过现有 `create_llm_client` 和 `LLMClient.complete` 调用 Worker。
4. 将唯一一个最终 JSON 对象写到 stdout；不得打印调试文本。
5. 不得参与评分，也不得读取 private scoring payload。
6. 不得要求人工补代码。

stdin payload 只能包含：

```json
{
  "execution_contract_version": "python_mas_v1",
  "task_description": "sanitized model-visible task",
  "information_goal": "sink or all_agents",
  "selected_primary": 0,
  "n_agents": 3,
  "max_rounds": 4,
  "budgets": {
    "max_model_calls": 20,
    "max_completion_tokens": 4000,
    "max_messages": 30
  },
  "worker_llm": {
    "provider": "host-authorized provider",
    "model_name": "host-authorized model",
    "base_url": null,
    "api_key_env": "host-authorized env name",
    "temperature": 0.0
  },
  "agents": [
    {"agent_id": 0, "local_prompt": "pre-rendered private prompt"}
  ]
}
```

payload 不得包含 expected output、ground truth、case_id、Level 标签、评分字段、最优拓扑、baseline 表现、SkillBank 内容、旧 runs 或 private scoring payload。API key 本身绝不能进入 payload；子进程环境只保留运行该已授权客户端所必需的最小变量，生成代码本身不得读取环境变量。

stdout 运行时 schema 至少为：

```json
{
  "submissions": [
    {"agent_id": 0, "answer": null, "submitted_round": null}
  ],
  "rounds_executed": 0,
  "messages": [
    {
      "round_sent": 0,
      "round_delivered": 1,
      "src": 0,
      "dst": 1,
      "source_ids": [0],
      "body": null
    }
  ],
  "usage": {
    "model_calls": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0
  },
  "errors": []
}
```

宿主必须校验 stdout schema、Agent id、轮次、消息预算、调用预算和 token 预算。程序报告的 usage 不能被盲信：至少要逐次累加实际 `LLMResponse.usage`，并由 Python-only runner 的执行账本核对调用数。若无法核对，运行失败，不得用估算值伪装成实测值。

## 五、运行语义

必须实现并测试：

- 每个 Agent 默认保留上一轮状态；只有新动作明确更新的字段才覆盖。
- Agent 可以选择本轮不发送。
- 第 `r` 轮产生的消息只能进入第 `r+1` 轮 inbox，同轮不可见。
- 每轮所有活跃 Agent 读取同一个上一轮快照，不能因 Python 遍历顺序产生串行偷看。
- 已提交 Agent 后续轮次不再调用，也不再发送。
- sink 模式只要求 `selected_primary` 最终提交；其他 Agent 可为 null。
- all_agents 模式要求每个 Agent 独立提交；多数票不得掩盖错误或缺失 Agent。
- 达到 `max_rounds`、调用、消息、token 或 wall-clock 预算后确定性停止。
- 每个真实 Worker 调用、实际投递消息和执行轮次都必须进入宿主可核对账本。

Worker Agent 使用统一动作 JSON：

```json
{
  "state": {},
  "should_send": false,
  "recipients": [],
  "message": null,
  "source_ids": [],
  "submit": false,
  "answer": null
}
```

程序负责解析动作、对非法 recipient/source id 失败关闭、保留旧状态、去重 source provenance，并延迟投递到下一轮。不得把解析失败自动改成成功提交。

## 六、SILO 数据隔离和可证明数据流

原始 SILO 可信环境把 `Xi` 放进 Agent `i` 的初始本地 Prompt；本模式保持相同语义。

Python architect 生成代码时只能看到：

- sanitized task description；
- `n_agents`；
- sink/all_agents 信息目标；
- 预算；
- Python 输入输出契约与安全规则。

architect 不能看到具体 shards、local prompts、case_id、expected outputs、分数或旧实验结果。

运行时每个 `local_prompt[i]` 视为带 `agent_id=i` 的 tainted 数据。`CodeValidator` 必须采用 fail-closed 的 AST/有限数据流规则：

- `local_prompt[i]` 只能流入 Agent `i` 的 Worker prompt。
- 不允许把两个或多个 local prompt 拼接、聚合或交给同一个 Worker。
- 不允许把 Agent `i` 的原始 local prompt 放入 state、message、stdout 或 Agent `j` 的 prompt。
- 允许 Agent `i` 的 Worker 输出经显式 message 发送给其他 Agent；这是被计量的信息传播，不等同于泄露原始 local prompt。
- 不允许对 tainted local prompt 做 split、slice、正则、`json.loads`、数值解析、排序、聚合或直接 Python 求解。
- 不允许 Python 代码从多个 shard 直接计算全局答案。
- 不允许访问 scorer、benchmark 原始文件、SkillBank、runs 或 private payload。

为了让静态证明可行，生成代码必须限制在可分析子集：规范的 `for agent_id in range(n_agents)`、显式按 id 索引、有限局部变量、禁止动态别名和高阶函数。无法证明某条 tainted 数据流安全时，拒绝执行，不得猜测。

fake dry-run 还必须给每个 local prompt 注入不同 canary，动态检查 canary 不会跨 Agent 直接流动、不会进入 message/stdout。静态检查和动态 canary 任一失败都算 `DataFlowError`。

## 七、Python 安全策略

生成代码不能未经检查直接运行。验证顺序：

```text
extract source
-> ast.parse
-> AST policy validation
-> API validation
-> taint/data-flow validation
-> py_compile
-> fake canary dry-run
-> isolated execution
-> output/accounting validation
```

至少禁止：

- 白名单外 import；
- `open` 和任何文件系统访问；
- `eval`、`exec`、`compile`；
- subprocess、线程、进程、socket；
- requests/http 客户端或绕过现有 LLM client 的网络调用；
- 反射、动态属性、dunder 访问、monkey patch；
- 递归、无界 while、无法静态证明上界的循环；
- 动态代码生成；
- 直接读取环境变量、API key 或系统信息；
- 直接实例化其他模型客户端；
- 修改宿主授权的模型配置、温度或预算；
- 捕获并吞掉预算/安全异常；
- 伪造、覆盖或漏记 usage/message/round；
- 读取 scorer、benchmark 文件、SkillBank、旧 runs；
- 将 local prompts、完整 inbox 或私密消息体打印/落盘。

优先允许：

- `json`、`sys`、必要且明确列入白名单的纯计算标准库；
- 有静态上界的 `for/range`；
- `if/else`；
- 非递归函数；
- 局部变量、列表、字典、集合；
- 基础算术、比较、布尔表达式；
- 唯一允许的 `create_llm_client` 构造和 `.complete` 调用；
- stdout 唯一最终 JSON。

在独立子进程执行，设置 wall-clock timeout、CPU、内存、文件描述符和输出大小限制。运行目录使用临时隔离目录；测试进程和主 benchmark 进程不得直接 `exec` 生成代码。资源限制在不同平台无法完全一致时，要 fail closed 或清楚记录降级，不能声称不存在的隔离。

## 八、ReAct 修复

状态机：

```text
generate
-> validate
-> observe sanitized error
-> replace_code
-> validate again
-> 最多 3 次修复
```

错误分类：

- `SyntaxError`
- `PolicyError`
- `APIError`
- `DataFlowError`
- `BudgetError`
- `OutputSchemaError`
- `RuntimeError`

Observation 只能包含：

- 当前代码；
- 错误类型；
- 行号、列号；
- 脱敏 traceback；
- 违反的固定规则；
- fake canary 的抽象违规说明，不包含真实 prompt。

不得提供标准答案、partial、success、baseline 表现、技能排名或“修改后得分”。唯一动作是返回一份完整替换代码 `replace_code`。修复器不得修改安全策略、测试、预算、scorer 或其他 Planner 模式。

## 九、sink 与 all_agents architect Prompt

必须构造两份实质不同的 Python architect Prompt，不能共用一个 Prompt 后只在末尾替换一句话。

sink Prompt 应明确：

- 目标是让必要信息汇聚到 `selected_primary`；
- 允许非汇点不提交；
- 优先减少无关传播；
- 输出 schema 仍包含每个 Agent 的 submission 槽位，未提交为 null。

all_agents Prompt 应明确：

- 目标是让信息经过显式消息共享，使每个 Agent 都能独立提交；
- gather-only 行为不满足目标；
- 禁止多数票替代逐 Agent 提交；
- 每个 Agent 的覆盖、提交和答案分别评分。

两个 Prompt 都必须：

- 不含答案、shards、case_id、Level、最优拓扑和旧实验表现；
- 不提供 chain、mesh、指数图、论文协议或 `phase_program_v1` 的可复制结构示例；
- 只提供程序契约、安全 Python 子集和对应信息目标；
- 要求输出完整纯 Python 源码，不带 Markdown；
- 发送前经过现有 leakage audit。

## 十、独立集成入口

至少支持：

```bash
python -m masbench.cli run ... \
  --planner --planner-mode python_generate
```

bench 新增非默认 arm：

```bash
python -m masbench.cli bench ... \
  --arms graphgen programgen pycodegen
```

若生成型自进化路径已统一支持独立 planner 分支，则同时支持：

```text
--evolved-mode python_generate
```

以及 curve/verify 中同名模式。实现时必须显式分派：

```text
graph_generate   -> 原 plan_free_graph
program_generate -> 原 plan_phase_program
python_generate  -> 新 PythonCodePlanner
```

禁止用一个笼统 `if generated` 把三者全部路由到 GraphGen。`topology_select`、`operator_compose`、fixed、p2p、broadcast、sfs、graphgen、programgen、evolved 的现有行为必须保持。

为 `RunConfig`/`MASRuntimeConfig` 增加 Python 专属配置，例如：

- `python_repair_attempts`
- `python_execution_timeout`
- `python_cpu_seconds`
- `python_memory_mb`
- `python_max_output_bytes`
- `python_artifacts_dir`
- `python_dry_run`
- `python_ast_policy_version`
- `python_execution_contract_version`

不得复用或改变 `graph_repair_attempts`、`program_repair_attempts`、GraphGen/ProgramGen artifact 目录或 clean 开关。

## 十一、接入现有自进化，但保持三种生成模式隔离

成功执行的 Python run 必须使用当前统一训练信号：

- `V`：源码解析、安全策略、API、数据流、编译、dry-run 和真实运行全部通过才为 1，否则为 0。
- `K`：宿主根据实际、已校验的 `(round, src, dst, source_ids)` 投递账本计算 sink 或 all_agents 信息覆盖；不得由生成程序自报一个覆盖分数。
- `U`：实际有效提交率。
- `P`：现有 SILO paper partial scorer。
- `S`：现有 sink/all_agents scorer；all_agents 仍要求每个 Agent 独立正确。
- `C/D`：继续使用现有论文 token/通信成本定义，单独报告。

使用现有阶段损失顺序 `V -> K -> U -> P -> S`，不要恢复成只看二元 ExactMatch。Python 生成失败或验证失败要生成 `validity=0` 的证据行，并保存错误分类、最小反例和修复轨迹；它只能成为带 `counterexample` 标签的负面技能，`is_selectable_skill` 必须拒绝它。

Python SkillCard 使用独立来源：

```text
provenance = "llm_generated_python"
planner_mode = "python_generate"
```

clean Python 检索只允许：

```text
llm_generated_python
skill_replay（且卡片明确 planner_mode=python_generate、契约版本匹配、程序通过验证）
```

必须扩展现有 planner-mode 隔离逻辑：

- GraphGen 不得检索 Python 或 PhaseProgram 技能。
- ProgramGen 不得检索 Python 或自由 GraphGen 技能。
- PythonGen 不得检索 GraphGen、ProgramGen、fixed_named、named_fallback、fake 或缺 provenance 的旧卡。
- `select_then_refine` 的既有非 clean GraphGen 语义不得被 Python 白名单改变。

SkillCard 中：

`organization_policy` 保存：

- `planner_mode`
- `program_sha256`
- source code 或稳定 artifact 引用
- AST policy version
- execution contract version
- repair attempts
- observed runtime trace summary

`reasoning_policy` 保存：

- Worker action schema
- state retention 规则
- message provenance/去重规则
- submit guard
- 已验证的逐轮/逐 Agent 指令摘要

失败分类进入 `failure_modes/counterexamples`。不要把失败程序写成成功技能；允许把它保存为不可选择的负面反例卡。

现有逐技能同配对消融必须覆盖 Python 技能，状态仍使用 `accepted_improved`、`accepted_no_change`、`insufficient_evidence`、`rejected`，不能把无提升写成“进化成功”。课程训练必须继续让请求中的 II 和 III 在每轮都有代表。full-information single-agent、cold pycodegen 和 evolved PythonGen 应能作为能力/组织诊断分别报告，但 capability diagnostic 不参与竞争 verdict。

## 十二、审计产物

每次生成使用独立 Python artifact 树，不能写进 GraphGen 或 ProgramGen 目录。至少保存：

```text
architect_prompt.txt
attempt_00.py
attempt_00_validation.json
attempt_01.py
attempt_01_validation.json
final_program.py
stdin_payload.redacted.json
stdout.json
stderr.redacted.txt
repair_trace.json
execution_report.json
program_hash.txt
```

`stdin_payload.redacted.json` 必须移除 local prompt 正文，只保留 Agent id、长度和哈希。持久化 `stdout.json` 必须对 message body、state、inbox、local prompt 和答案做脱敏或哈希；原始 stdout 只允许在内存中交给私有 scorer，评分后丢弃。不得保存 API key 或 private scoring payload。

`execution_report.json` 至少记录：

- `syntax_valid_at_1`
- `repair_attempts`
- `policy_valid`
- `data_flow_valid`
- `compile_valid`
- `dry_run_valid`
- `runtime_success`
- `planner_model_calls`
- `repair_model_calls`
- `worker_model_calls`
- `prompt_tokens`
- `completion_tokens`
- `messages`
- `rounds`
- `information_goal`
- `program_sha256`
- `ast_policy_version`
- `execution_contract_version`
- `failure_reason`

所有失败路径也必须写完整审计信息。禁止保存未脱敏 traceback、密钥、真实 local prompts、ground truth、最优拓扑和旧实验结果。

## 十三、离线必测项目

测试不得依赖真实 API key 或网络。至少覆盖：

1. 合法完整程序一次生成成功。
2. `SyntaxError` 经一次 ReAct 修复后成功。
3. 三次修复失败后诚实 `python_generation_failed`，无任何兜底。
4. `import os`、`open`、`eval`、`exec`、`subprocess`、`socket` 被拒绝。
5. 无限循环、递归、未知上界循环和超预算调用被拒绝或超时终止。
6. 修改 provider/model/base URL/temperature/budget 被拒绝。
7. 多 Agent local prompt 拼接触发 `DataFlowError`。
8. Agent `i` 的 local prompt 直接流向 Agent `j` 触发 `DataFlowError`。
9. fake canary 跨 Agent 直接泄露被拒绝。
10. Agent 默认保留上一轮状态。
11. `should_send=false` 时不发送。
12. 本轮消息下一轮才可见。
13. 同一轮读取上一轮快照，不受循环顺序影响。
14. 已提交 Agent 不再调用或发送。
15. sink 和 all_agents 使用实质不同的 architect Prompt 和现有评分器。
16. all_agents 中一个 Agent 错误或缺提交时整次失败。
17. fake LLM 端到端运行，不调用网络、不伪造解题成功。
18. token、调用、实际消息和轮数统计正确，程序谎报 usage 时被拒绝。
19. 审计产物完整且不含答案、local prompt、密钥、ground truth、最优拓扑。
20. Python 失败证据为 `V=0`，只生成不可选择的负面卡。
21. Python 技能与 GraphGen/ProgramGen/fixed 技能双向检索隔离。
22. `graph_generate` 仍走原自由图路径，`program_generate` 仍走原 `phase_program_v1` 路径。
23. bench 同时运行 `graphgen programgen pycodegen`，三者记录正确的 planner mode/provenance/artifact 目录。
24. 现有课程、逐技能消融和 capability diagnostic 在 Python 模式下保持正确。
25. 两个包完整测试继续通过。

不要删除、弱化或改写现有 GraphGen/ProgramGen 测试来让新功能通过。

## 十四、离线 Demo

新增一个最小 demo：

- 3 个 Agent；
- fake architect 生成完整可运行 `program.py`；
- 至少执行两轮；
- 展示状态保留；
- 至少一个 Agent 某轮选择不发送；
- 展示消息在下一轮才可见；
- 输出 3 条独立 submission；
- 打印生成代码、验证/修复摘要和 artifact 路径；
- 明确 fake 只验证线路，不代表真实解题能力。

Demo 产物写入临时目录或 gitignored `runs/`，不得提交。

## 十五、验收标准

完成前必须：

1. 阅读并遵守 `AGENTS.md`。
2. 检查 dirty worktree，只修改任务相关文件，不覆盖用户改动。
3. 运行 `exp-graph` 全量 pytest。
4. 运行 `masbench` 全量 pytest。
5. 运行 `python_generate` 离线 demo。
6. 运行一个 `graphgen + programgen + pycodegen` 离线 bench smoke。
7. 检查 `git diff --check`。
8. 不修改 `archive/` 和 `third_party/`。
9. 不提交 run outputs。
10. 更新 CLI help、README 和专门设计文档。
11. 明确哪些隔离能力是静态证明，哪些只是运行时检测或平台限制。
12. 不调用付费 API；除非用户另行明确授权真实实验。

不要停在设计说明。请完成实现、测试、离线 demo 和审计后再反馈。

## 十六、最终反馈格式

请用中文提交：

1. 人话说明 `python_generate` 如何工作，以及它与 `graph_generate`、`program_generate` 的区别。
2. 修改文件及可点击链接。
3. 生成程序的完整示例。
4. 一次 ReAct 修复示例。
5. AST、taint/data-flow、子进程和预算隔离策略。
6. `V/K/U/P/S/C/D` 如何从 Python 真实执行记录计算。
7. SkillBank planner-mode/provenance 隔离与失败反例处理。
8. CLI、bench、evolved/verify 示例。
9. 全量测试结果。
10. 离线 demo 和三生成 arm smoke 摘要。
11. 已知限制与下一步。
12. 明确说明是否调用了付费 API。
