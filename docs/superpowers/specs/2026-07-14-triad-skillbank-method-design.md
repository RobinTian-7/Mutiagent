# TRIAD-SkillBank 方法设计档案

> **TRIAD — Typed Randomized Interventional Attribution with Diversity**
> **中文名：类型化随机干预归因与多样性技能库**

| 项目 | 内容 |
|---|---|
| 文档性质 | 研究方法设计，不是实现代码或实验结论 |
| 方法状态 | **待验证、可证伪的研究假设** |
| 来源对话 | `6a564e0e-c458-83ea-ac26-30891caf10f3`（QueenBee SkillBank 设计） |
| QueenBee 审核基线 | commit `8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a` |
| 归档日期 | 2026-07-14 |
| 目标读者 | 后续实现 Agent、实验 Agent、审计 Agent、方法比较 Agent |
| 相关设计 | [PIF-Bank 方法设计](./2026-07-14-pif-bank-method-design.md) |

本文把来源对话中的最终方法收敛成一份**足够详细但不等同于代码实现**的设计档案。文中只保留概念 schema、关键公式、短伪代码、实现边界和实验合同；具体 Pydantic 字段、序列化格式、函数签名和迁移脚本应在实现阶段另写 specification。

---

## 1. 阅读约定与结论边界

### 1.1 证据标签

本文使用四种标签，避免把现状、推断和提案混在一起：

- **`CURRENT_CODE_FACT`**：固定 commit 中可以直接复核的当前行为。
- **`SOURCE_CONVERSATION_CLAIM`**：来源对话给出的研究审计结论；本文没有重新执行全部外部文献审计。
- **`AUDIT_INFERENCE`**：根据当前代码结构推导出的风险，需要实验验证。
- **`TRIAD_PROPOSAL`**：本文建议新增的机制，仓库当前并未实现。

### 1.2 一句话结论

> **TRIAD-SkillBank 在现有完整 `SkillCard` 之上增加可确定性绑定的 typed `SkillAtom` 和 bounded `Portfolio`，通过真实执行的 removal、pair-factorial 与 swap-in 对照分配局部信用，再用随机化选择和 Quality-Diversity archive 防止早期垄断；任何局部信用都不能绕过 QueenBee 现有的完整 Bank gate。**

### 1.3 正确的研究状态表述

在正式实验通过预注册标准前，只能说：

> 经过来源对话整理、固定 commit 代码复核和设计对抗审阅后，TRIAD-SkillBank 是一个 PIF-compatible、可实施、可比较、可证伪的 portfolio attribution/search 研究假设；它尚未被证明有效，真实实验必须允许选择更简单的 current QueenBee 或 PIF-style baseline。

不得写成“TRIAD 已经提升 QueenBee”“已经解决信用分配”或“首次实现组合技能归因”。

---

## 2. 它解决的到底是什么问题

### 2.1 QueenBee 已经具备的基础

**`CURRENT_CODE_FACT`**：当前 QueenBee 已经拥有：

- typed `mode_payload`，分别承载 named topology、paper transport、Graph、PhaseProgram 和 Python source；
- `SkillCard` 中分开的 executable/organization 信息、`reasoning_policy`、insight、evidence、failure、counterexample 和 confidence；
- 按 task、`information_goal`、planner mode、provenance、agent size 和 Python worker contract 的硬隔离；
- `reuse`、Python parent-aware `mutate` 和 fresh/innovation 分支；
- topology equivalence、retrieval dedupe、显式 compaction 和 bounded Bank；
- answer-free `FailureRecord` / `FailureCluster`；
- `V/K/U/P/S/stage_score/C/D` 和 paired `strict_dense_v2` gate；
- Graph/Phase deterministic validation，以及 Python parent hash、EVOLVE block、AST/contract validation。

所以 TRIAD **不是**“再增加一个记忆库”“再加失败反思”“再加一个 gate”“把 source 存进 Skill”或“增加 reuse/mutate/fresh”。这些已存在或已有近似机制。

### 2.2 当前真正缺失的三类可回答问题

设一个完整候选同时包含多个可复用机制：路由片段、reasoning policy、提交规则、去重策略或一个 Python block patch。候选成功后，当前系统仍难以可靠回答：

1. **单项贡献**：组合中的 Atom `i` 在当前背景下是否真的有用？
2. **组合贡献**：Atom `i` 与 `j` 是协同、冲突，还是只是各自有效？
3. **机会贡献**：被检索但没被采用的 Atom，换入同一 slot 后是否优于现任 Atom？

当前 whole-skill ablation 可以比较完整 executable/topology；insight attribution 明确属于非因果 association。二者都不能完整回答上述三问。

### 2.3 根本失败模式

**`AUDIT_INFERENCE`**：如果 outcome 继续只记在整张卡上，可能出现：

- 一个组合胜出，内部所有机制都被误记为正向；
- 同一 topology 下不同 reasoning policy 被结构去重或共享证据掩盖；
- 两个单独普通的机制因强协同而有效，却分别被淘汰；
- 被检索但未选中的潜在好机制永远得不到 execution evidence；
- 早期幸运赢家获得更多使用、更多 evidence、再获得更多使用；
- FailureCluster 说明“一类失败常出现”，却不能指出哪个可替换部分负责；
- Bank 保留表面多样性，但实际使用集中在少数 Skill 上。

TRIAD 的目标不是宣称这些风险已经发生，而是提供能够**测量并推翻这些假设**的实验结构。

---

## 3. 方法的最小身份

TRIAD 只有在以下机制同时存在时才成立：

1. 有一个 immutable、已验证的 `BaseArtifactRevision`；
2. Atom 有 typed slot、确定性 binder 和 immutable revision identity；
3. Portfolio 是有序、容量有界的 Atom bindings；
4. runtime 仍执行完整 materialized `SkillCard`，绝不直接执行零散文本；
5. 单 Atom 信用只能来自真实 matched removal；
6. pair interaction 只能来自完整四臂 factorial；
7. retrieved-unused 未执行时只记 exposure，真实 swap-in 后才有 opportunity credit；
8. 三类信用来自同一 immutable raw observation ledger，不能重复造样本；
9. selector 的 slate、可行集合、概率和随机种子在 outcome 前冻结；
10. audit 预算在执行前原子预留，不能看完结果再补做有利对照；
11. local credit 只影响 TRAIN 中的检索、mutation 与 archive；
12. 最终部署仍由完整 candidate Bank 的 held-out dense gate 决定；
13. `sink/all_agents`、mode、worker contract、execution contract 和 split 隔离不被放松；
14. TEST、答案、ground truth、expected output 和 private prompt 永不进入 Bank。

缺少其中任一核心项，只能称为 `TRIAD-inspired`。

---

## 4. 概念数据模型

这里给出 agent 实现时必须理解的对象关系，不给完整代码定义。

### 4.1 六个核心对象

| 对象 | 作用 | 最少应包含 | 不能包含 |
|---|---|---|---|
| `BaseArtifactRevision` | 一条 lineage 的冻结、可运行基础 | payload hash、carrier、namespace、validator/compiler version、来源 | 可变 registry 状态、答案 |
| `SkillAtomRevision` | 最小可绑定、可移除、可归因的机制 | Atom ID/version、slot、typed operation、parent/base compatibility、requires/conflicts、behavior descriptor | 自由声称的因果结论、TEST 内容 |
| `PortfolioRevision` | 实际候选的有序 Atom bindings | base revision、ordered bindings、portfolio hash、lineage | 未解析自然语言列表 |
| `RetrievalSlateSnapshot` | 一次选择前冻结的候选 Atom 集 | request namespace、base、Atom revision IDs、retrieval reasons | outcome 后动态加入的候选 |
| `SelectionEvent` | 可复核的事前选择 | feasible/eligible portfolios、每项概率、excluded reasons、selector config/hash、RNG | outcome、后验改写概率 |
| `ExecutionBlock` | 一次 normal/audit 的 immutable 原始证据 | manifest、所有 arm observations、成本、failure state | 派生后再篡改 raw arms |

### 4.2 Namespace 是 identity 的一部分

至少必须绑定：

```text
task_family
information_goal: sink | all_agents
planner_mode
carrier
worker_contract（Python 时必需）
execution_contract
scaffold/compiler/materializer version
agent-count / task-feature compatibility
```

不同 namespace 的 Atom 不共享 direct posterior，不构成同一 Portfolio，也不允许 fallback 串库。

### 4.3 Base、Atom 与 Portfolio

记 Base 为 `B`，有序 Atom 集为：

\[
P=(a_1,a_2,\ldots,a_k),\quad k\le 3
\]

materializer 执行：

\[
M(B,P)\rightarrow\text{完整 typed SkillCard 或静态拒绝原因}
\]

必须同时保留 `P=∅` 的 **Base-only** identity。它既是合法部署候选，也是 removal/factorial 的必要对照。

### 4.4 Atom 必须是操作，不只是摘要

一个合法 Atom 需要回答：

- 它绑定到哪个 carrier 和 slot？
- 它对 Base 做什么确定性操作？
- 哪些 dependencies 必须先存在？
- 与哪些 Atom 冲突？
- 如何从最终 artifact 反向确认它确实被应用？
- 移除后是否仍能 materialize 一个合法完整 artifact？

如果这些问题没有确定性答案，则该机制标为 `atomic_locked` 或 `unsupported_nonseparable`，仍可作为完整 Skill 使用，但不能获得 Atom-level efficacy credit。

### 4.5 三种 Constraint 必须分开

“Constraint”不能混成一种对象：

| 类型 | 例子 | 是否参与 Atom efficacy |
|---|---|---|
| Hard compatibility guard | contract、namespace、sandbox、forbidden API、leak guard | 否，永不可为探索放宽 |
| Selector constraint | exposure cap、某类 portfolio 暂不进入 exploitation | 评估 selector policy，不作为普通 Atom removal |
| Runtime guard Atom | materialized 后改变提交、检查、验证行为 | 可以，但必须有 typed binder 和真实执行对照 |

---

## 5. 运行结果与三类信用

### 5.1 Outcome 向量

一次完整运行产生：

\[
Y=(V,K,U,P,S,G,C,D,F)
\]

其中 `G = stage_score`，`F` 是 failure class。用于方向统一的效用向量为：

\[
z(Y)=(V,K,U,P,S,G,-C,-D)
\]

`C/D` 的原始差仍按“candidate - comparator”保存：正数表示更贵。`V/K/U/P` 的硬回归不能被单一 scalar 掩盖。

### 5.2 View A：条件性 Removal effect

在相同 case、seed、Base、模型、预算、合同和背景 Portfolio 下，比较：

\[
\delta_i(P,x)=z(Y(B\oplus P,x))-z(Y(B\oplus(P\setminus\{i\}),x))
\]

它回答：

> 在这个 Base、这个背景组合和这个任务 context 中，保留 Atom `i` 比移除它好多少？

它**不是** `i` 的全局平均因果效应。一个 Atom 在 `P1` 中为正、在 `P2` 中为负是合法结果，应保存 context-specific evidence，不能粗暴平均成“略有用”。

若移除 `i` 后无法 deterministic materialize，则记录 `unsupported_nonseparable`，不能把非法 arm 补成零分后奖励 `i`。

### 5.3 View B：Pair factorial interaction

只有以下四个 arm 都能合法 materialize 和完整执行时才估计：

```text
P
P - i
P - j
P - {i, j}
```

交互为：

\[
\eta_{ij}=z(Y_P)-z(Y_{P-i})-z(Y_{P-j})+z(Y_{P-\{i,j\}})
\]

- `η > 0`：组合价值超过两个条件性主效应之和；
- `η < 0`：冲突、冗余或负协同；
- `η ≈ 0`：在当前 context 中近似可加。

`stage_score` 是分段非线性指标，所以 `η_stage` 只能解释为 outcome-scale interaction。还必须报告 `V/K/U/P/S/C/D` 的分量，不得只报一个漂亮总数。

### 5.4 View C：Retrieved-unused Opportunity effect

Atom `j` 被检索但没有执行时，只做：

```text
exposure_count(j) += 1
```

不奖励，也不惩罚。

只有把 `j` 真实换入与现任 `i` 相同的 typed slot，并运行 matched 两臂后，才估计：

\[
\omega_{j\leftarrow i}=z(Y(B\oplus(P-i+j)))-z(Y(B\oplus P))
\]

它回答：

> 在当前 Base、slot、背景组合和任务中，`j` 替换 `i` 是否更好？

Opportunity evidence 可以提高 `j` 后续普通执行或 removal audit 的优先级，但不能冒充 `j` 的 main deployment effect。

### 5.5 三个 view，共用一份 raw ledger

三类信用不是三份相互独立的数据。正确结构是：

```text
precommitted manifest
        ↓
immutable arm observations
        ↓
removal / interaction / opportunity derived views
```

同一个 arm 可以复用于多个合法 contrast，但统计时必须保留 block/case cluster，不能把共享 arm 当作多条独立样本扩大 `n`。

---

## 6. 完整生命周期

### 6.1 Create

Atom 有三种来源：

1. **Legacy extraction**：从现有 Skill 的可解析结构中提取；旧 outcome 只标 `observational_only`。
2. **Mutation**：对一个已知 slot 做一个局部、typed 变更。
3. **Fresh**：只生成一个新 Atom 或一条新 Base lineage，而非一次把多个未知变化都记成独立正向机制。

新 Atom 初始为 `candidate/probation`。没有 binder、reverse trace 或合法 neutral removal 的机制保持 atomic locked。

### 6.2 Retrieve

顺序必须是：

1. 当前 QueenBee hard filters；
2. Base/slot/dependency compatibility；
3. hard safety constraints；
4. context-specific support、effect LCB、failure risk、cost 和 diversity；
5. 构成最多 6 个 Atom 的 frozen slate。

Embedding 只能是次级排序信号。关闭 embedding 后方法仍必须可运行。

### 6.3 Compose

Portfolio 最多 3 个 Atom。对最多 6 个 Atom 的 slate，枚举：

\[
1+\binom61+\binom62+\binom63=42
\]

个 identity，其中 `1` 是 Base-only。枚举不等于都调用 worker。Host 必须把静态处理分成两层，不能用一个模糊的 `feasible` 布尔值全部过滤：

1. **不可放宽的 audit-eligibility guards**：namespace/base/slot 不匹配、dependency/conflict、无法 deterministic bind 或 reverse trace、worker/execution contract 不匹配、forbidden API、sandbox 或 leak violation。此类 identity 完全排除，只形成 compatibility/safety record，不进入 efficacy。
2. **算法有效性检查**：通过上述边界、已有 canonical Portfolio/bind attempt，但被预注册的 payload schema、compiler、coverage 或 algorithmic budget validator 拒绝。此类 proposed treatment 保留为 `legal_static_algorithm_failure` 的完整零质量 outcome，不调用 worker，也不因事前可见而从 proposal-validity 统计中消失。

因此要同时保存 `audit-eligible set`、`static-failed outcomes` 和 `runtime-safe set`。只有最后一类可以进入正常 exploitation；audit/attribution 是否纳入 static-failed treatment 必须由 outcome 前冻结的协议决定，不能只分析 validator-passing candidates。

### 6.4 Select

正常 selector 只在 `runtime-safe set` 中排除证据下界不合格的 exploitation 候选，再使用带非零 exploration 的随机 selector：

\[
\pi(P\mid x)=(1-\epsilon)\operatorname{softmax}(Q(P)/\tau)
+\epsilon\operatorname{Uniform}(\mathcal F_{safe})
\]

每次必须在 outcome 前持久化：

- slate、hard-excluded reasons、audit-eligible set、static-failed outcomes 与 runtime-safe/selector-eligible set；
- 每个 eligible portfolio 的概率；
- excluded reason；
- selector code/config hash；
- RNG seed/state；
- 最终 selected portfolio。

随机化的目的不是“增加随机性”，而是防止早期 score 与未来 exposure 完全共线，并为 missed-alternative audit 提供可复核选择过程。

### 6.5 Execute

runtime 永远收到完整 materialized artifact：

- Graph → 完整 `GraphSkillPayload` / graph spec；
- PhaseProgram → 完整 `phase_program_v1` 及 compiled spec；
- Python → 完整 source、hash、AST/contract metadata；
- fixed/paper transport → 当前 runner 能合法执行的完整对象。

Atom 本身不是 runtime API。

### 6.6 Attribute

正常运行先产生 composition-level observation。Audit scheduler 在预算内选择预先合法的 removal、factorial 或 swap block。完整 block sealed 后，确定性派生三类 effect view。

### 6.7 Mutate

Mutation target 由 host 根据局部 evidence 选择：

- coverage 失败 → routing/dissemination slot；
- submission 失败 → submit policy/guard；
- cost 高、质量平 → density/rounds/send mode；
- reasoning positive、structure neutral → 保持 executable，只改 policy；
- pair interaction 显著负 → 禁止组合或只 mutation 其中一个；
- exposed 多、executed 少 → 提高 opportunity audit，而非直接淘汰。

LLM 只提议受限局部变化，不负责给自己分信用。

### 6.8 Gate

局部 posterior 只能构造 candidate Bank。完整 candidate 与 incumbent 在相同 held-out evaluation units 上比较，最终仍经过 `strict_dense_v2` 语义：failure/V/K/U/P 不回退，paired dense outcome 真正改善，或质量完全相同而成本下降。

TRIAD 建议在 gate 外再加一个 case-clustered wrapper：case 是主要独立单位，seed 嵌套在 case 内，逐 `Level × goal` cell 保留硬检查。这个统计增强是提案，不是当前 gate 已有事实。

### 6.9 Archive / Tombstone

被拒 candidate 不得成为 deployed parent，但其 answer-free failure 和 audit evidence可留在审计存储。被充分测量且 dominated 的 Atom 归档；无 active composition 引用时删除大 payload，只保留 hash、lineage、淘汰原因和失败摘要。

---

## 7. Carrier-specific 设计

### 7.1 PhaseProgram：推荐 MVP carrier

PhaseProgram 最适合第一版，因为 DSL 与 deterministic compiler 已存在，边界清楚。

可用 Atom：

- 插入、删除或替换一个 `gather` / `broadcast` / `pairwise_exchange` / `consensus` phase；
- 修改一个 typed parameter，如 hub、pattern、max rounds、stop condition、send mode；
- 替换一个 phase instruction，但必须有独立 reasoning hash；
- 增加明确的 dissemination 或 submission guard。

每个 Portfolio 都重新构造完整 program 并经过 compiler、coverage 和 budget validation。

### 7.2 Graph

Graph Atom 不能是任意 edge list。第一版只支持 host 能精确识别和反向追踪的 fragment：

- 一个 topology construct 产生的连续 step block；
- gather、broadcast、pairwise、relay 等结构片段；
- selected-primary 变化；
- 与片段绑定的 instruction/policy revision。

组合后重新检查 agent bounds、self-loop、duplicate edge、step/message/fan-in 上限、temporal reachability，以及 `sink/all_agents` coverage。

### 7.3 Python

Python 风险最高，MVP 只允许一个 executable Atom：

```text
exact parent source SHA
+ existing EVOLVE block ID
+ replacement body / patch SHA
+ resulting source SHA
+ AST、worker 和 execution contract
```

最终 parent→child diff 必须证明恰好一个既存 EVOLVE block 改变。Branch 名叫 `mutate` 不足以证明单 Atom 变化。

多个 Python Atom 只有在不同 block、相同 parent、应用顺序可证明交换、最终 SHA 一致且完整 validator 全通过时才能进入未来版本；否则永久标 `conflict`。

### 7.4 Reasoning-policy Atom

相同 topology 不应自动等于相同 Skill。reasoning-policy Atom 可以表示：

- source-aware deduplication；
- provenance retention；
- delta-only forwarding；
- conflict resolution；
- coverage-complete submission；
- uncertainty/stop policy。

但只有 runner/materializer 能在固定 executable 下独立替换并验证该 policy 时，才可获得独立 credit。仅仅存在 `reasoning_policy` 字段，不代表它已成为可干预执行因子。

结构 fingerprint 相同、reasoning hash 不同的 Portfolio 必须保留为不同 identity。

### 7.5 Named topology 与 paper transport

如果当前 runtime 不支持独立 slot binding，就将它们作为 `atomic_locked` Base 或 baseline，不强行拆分。方法完整性不应靠伪造不存在的 policy swap 获得。

---

## 8. Retrieval score、随机化与多样性

### 8.1 安全约束先于 scalar score

以下风险不能被低成本或高 predicted stage 抵消：

- payload/contract 无效；
- `V`、minimum `K`、`U` 的悲观边界不合格；
- `P` 超过预注册 tolerance 的回退；
- algorithm failure 风险过高；
- forbidden API、sandbox 或 leak violation；
- namespace 不匹配。

### 8.2 Portfolio 排序

对通过安全检查的 Portfolio，可使用下式排序：

\[
Q(P)=LCB_G(P)+\rho LCB_S(P)-\lambda_C\hat C(P)-\lambda_D\hat D(P)
+\lambda_E VOI(P)+\lambda_N NicheRarity(P)-\lambda_H Concentration(P)-\lambda_R Risk(P)
\]

其中：

- `LCB`：实际 observation 与局部 effect 的悲观估计；
- `VOI`：测试该候选可能改变未来决策的价值；
- `NicheRarity`：保护尚未覆盖的行为 cell；
- `Concentration`：惩罚长期只使用同一 Atom/lineage；
- `Risk`：answer-free failure、negative interaction 和 constraint evidence。

这个 scalar 只用于 TRAIN selection，不能代替 dense gate。

### 8.3 QD archive

QD 不是 TRIAD 的独立 novelty，而是防止 attribution 结果再次收敛成单一冠军的容量层。Behavior descriptor 必须由 host 计算，例如：

- carrier 与 goal；
- depth、message density、fan-in；
- gather-only / gather+broadcast / pairwise / consensus；
- coverage profile；
- edited Python block；
- submission schedule；
- reasoning family/hash。

禁止用 LLM 自报的“creative”“robust”“novel”作为 cell。

初始实验可预注册：active Atom 全局上限 256、每 `namespace × behavior cell` 上限 4、slate ≤6、Portfolio ≤3。它们是待调参数，不是方法真理。

### 8.4 淘汰顺序

1. invalid / deprecated；
2. exact duplicate；
3. 有充分 evidence 且同 cell Pareto-dominated；
4. 高失败风险且无反证；
5. 长期无执行、低 support、无独特 niche；
6. 超出 cell capacity 的最低 LCB 项。

以下对象有保护期：新 probation Atom、唯一 reasoning variant、active safety constraint、已有正 opportunity 但尚无足够 normal execution 的 Atom。

### 8.5 早期垄断指标

至少报告：

\[
HHI=\sum_i p_i^2
\]

以及 top-1 exposure share、top-1 execution share、effective number of used Atoms、使用覆盖率和未执行 exposure 比例。降低集中度本身不是成功；必须同时保持或提升质量。

---

## 9. Audit 协议与成本边界

### 9.1 Matched block 共同不变量

同一 contrast 的 arms 必须固定：

```text
case ID 与 task seed
model / temperature / provider policy
runtime、scorer、worker contract
information_goal、mode、agent count
Base revision 与非目标 Atom bindings
token/call/message/timeout budget
```

执行顺序随机化，manifest 在第一个 outcome 前持久化。不能先看 normal run，再决定是否补做对自己有利的 confirmatory arm。

### 9.2 Failure 状态机

| 状态 | 是否更新 efficacy | 处理 |
|---|---|---|
| Proposal failure | 否 | 保留 proposer 成本和失败原因 |
| Unsupported bind / nonseparable | 否 | 形成 compatibility evidence，不补零 |
| Legal static algorithm failure | 是，作为真实负 outcome | 前提是 canonical bind attempt 已成立且不可放宽 guard 全通过；`V/K/U/P/S/G=0`，不调用 worker，保留 host/proposer 成本 |
| Runtime algorithm failure | 是，作为真实负 outcome | 同上，并进入 answer-free failure cluster |
| Infrastructure failure | 否 | 整个 matched unit 标 incomplete，不单留成功 arm |
| Harness failure | 否 | 立即作废 replicate 并调查 |

如果所有合法 arms 都是零，只更新 validity/failure/compatibility；不要把“同样失败”解释为 efficacy tie。若质量完全相同而只有 `C/D` 不同，只更新 cost effect。

### 9.3 预算使用统一的六维向量

至少同时控制：

```text
execution_units
tokens
model_calls
repair_calls
provider_cost_usd
wall_time_seconds
```

这六项是全文唯一权威的 `BudgetVector`；normal run、audit reservation、方法比较、接受标准和停止标准都逐维使用它。若离线/fake provider 没有真实价格，`provider_cost_usd=0` 并另报估算价，不能删除该维度后悄悄改变公平合同。

Audit block 执行前同时预留：

1. 完整 block 的 all-in 最坏成本；
2. 相对 normal selected arm 的 incremental audit 成本。

任何一个维度不足都不启动 block，避免只跑 treatment、不跑 comparator。

### 9.4 10% audit cap

候选默认对 `BudgetVector` 的每一维都满足 10% incremental cap。下面的 execution-unit 公式只是其中一维：

\[
N_{audit,incremental}\le\lfloor0.10N_{normal}\rfloor
\]

Audit block 替代对应 normal run，因此 primary 公平比较使用 **equal all-in budget**，而不是给 TRIAD 额外 10% 后再与 baseline 比。

Pair factorial 通常需要 3 个增量 arms。若只把 audit execution 预算的 20% 给 pair，那么要获得 6 个完整 pair blocks，仅 execution-unit 这一维就至少需要：

\[
N_{normal}\ge 6\times3/(0.10\times0.20)=900
\]

另外五维仍须逐项通过 reservation。因此 MVP 不应声称能在小样本下检验 interaction；先验证 removal 与 opportunity 的可行性，正式实验达到 power 后再开启 sparse factorial。

---

## 10. Split、泄漏与只读边界

### 10.1 建议四阶段 split

| Split | 用途 | 能否更新 Bank/effect |
|---|---|---|
| `TRAIN` | proposal、selection、audit、posterior、archive | 可以 |
| `GATE_DEV` | 重复比较 candidate 与 incumbent，决定 search trajectory | 不回写 Atom efficacy；只产 immutable gate report |
| `FINAL_VAL` | TEST 前 one-shot snapshot admission；失败则部署 incumbent | 不回写；每 replicate 只用一次 |
| `TEST` | end-to-end 方法结论的最终 frozen benchmark | 完全只读 |

case 必须跨 split 不重叠；不能把同一 case 的不同 seed 分到不同 split 来伪装独立。

为了在影响正式 search 前检查 attribution pipeline，`TRAIN` 可以在 manifest 冻结时再按 case 划成 `TRAIN_UPDATE` 与可选的 `TRAIN_SHADOW`。`TRAIN_SHADOW` 永不回写 estimate、selector、failure 或 archive，只能作工程诊断，不能支持 confirmatory claim；FINAL_VAL 只决定该 replicate 部署 candidate 还是 incumbent，正式 end-to-end 方法结论来自 frozen TEST。

若某 replicate 的 FINAL_VAL 未通过预注册 gate，该 replicate 必须部署 incumbent snapshot、标记 `method_failure=True`，并继续保留在该方法的比较分母中；不得丢弃或用新 seed 替换失败 replicate。

### 10.2 TEST immutability

TEST 前后不仅比较 Bank hash，还要冻结并核对：

- Bank snapshot 和 artifact catalog；
- selector/QD/exposure counters；
- effect/failure ledger；
- mutation parent registry；
- prompt/cache 中可持久化状态。

TEST failure 不进入 FailureCluster，TEST exposure 不更新 concentration，TEST outcome 不改变任何 posterior。当前仓库控制流中未发现明确 TEST write-back，但也没有这样的完整 frozen facade；这是 TRIAD 的新增安全要求。

### 10.3 禁止持久化的语义

Bank、Atom、manifest、failure 与 effect records 均不得包含：

```text
answer / final_answer
ground_truth / expected_output / reference_solution
private_prompt / local_prompt / raw_task_prompt
TEST outcome content
benchmark shard 或可逆编码的 oracle 信息
```

允许保存：case hash、task feature bucket、seed、revision hashes、`V/K/U/P/S/G/C/D`、coverage/submission presence、failure class/signature、model/runtime config hash。

Leak check 应使用对象级 allowlist 加递归 key/value 扫描，而不是只维护一个容易绕过的字段黑名单。

---

## 11. 与现有方法的可比较边界

### 11.1 Current QueenBee、PIF 与 TRIAD

| 维度 | Current QueenBee | PIF-Bank | TRIAD-SkillBank |
|---|---|---|---|
| 部署单位 | 完整 `SkillCard` | 完整 composition | 完整 materialized `SkillCard` |
| 学习单位 | 主要是整卡/完整 executable | `ExecutableFactor`、`ReasoningPolicyFactor`、`ConstraintFactor` revision | Base 中的 typed `SkillAtom` 与 bounded Portfolio |
| 直接信用 | whole-skill ablation；insight association 非因果 | 固定其他 factor 的 `from→to` paired replacement | 固定背景的 `P` vs `P-i` removal |
| 二阶交互 | 无显式 factor interaction | executable × policy 的选择性 2×2 | 任意合法 Atom pair 的 sparse four-arm factorial |
| retrieved-unused | 无通用 efficacy ledger | 通常不是核心 estimand | 只有真实 same-slot swap-in 才获得 opportunity effect |
| 随机 selector | 非核心机制 | 可选 exposure-aware retrieval | outcome 前冻结概率的核心搜索机制 |
| 多样性 | bounded compaction | factor niches/exposure control | host-defined QD cells + concentration audit |
| 成本 | 最低 | 中等 | 最高，必须被 audit cap 约束 |
| 主要优势 | 简单、已有实现 | factor identity 清楚、归因成本较低 | 能研究多 Atom portfolio、交互和 missed alternatives |
| 主要风险 | whole-card credit 混淆 | 预设 factorization 可能过粗 | nonseparability、样本不足、审计成本、高阶交互 |

### 11.2 TRIAD 与 PIF 的关系

PIF 以明确 `factor revision from→to` 的 replacement contrast 为中心；TRIAD 以 fixed Base 内的 multi-Atom Portfolio 为中心，增加 background-conditional removal、frozen-slate opportunity swap 和 sparse pair factorial。

二者共享：

- typed namespace；
- immutable revision identity；
- matched case/seed；
- full outcome vector；
- strict Bank-level gate；
- TEST immutability；
- answer-free evidence。

若 Portfolio 主要是 singleton、Atom 不可安全拆分、pair evidence不足或 opportunity 很少，TRIAD 应退化到 PIF-like 设计，甚至直接选择 PIF。复杂方法没有默认优先权。

### 11.3 与 AFlow、ADAS、AlphaEvolve 的区别

| 方法 | 搜索对象 | 历史/信用单位 | TRIAD 的区别 |
|---|---|---|---|
| AFlow | 完整 workflow code | parent workflow 与修改经验 | TRIAD 不把 whole workflow 的收益平均给内部 Atom；用 typed matched intervention |
| ADAS | 完整 Agent Python code | append-only whole-agent fitness | TRIAD 不把完整 archive 注入 proposer；有 hard contracts、bounded archive 和局部 credit |
| AlphaEvolve | 完整 program population | evaluator 给 whole program 评分 | TRIAD 专门分解 reusable portfolio contribution；官方 runner未公开，不能声称实现复现 |

### 11.4 与近邻工作的 novelty 边界

**`SOURCE_CONVERSATION_CLAIM`**：GraSP、MemSkill、Skill1、CTA、Graph-GRPO、CRAFT、SCAR、Shapley-Coop 等近邻已分别覆盖 typed composition、multi-skill selection、selection/utilization 区分、paired trace audit 或其他粒度的 credit assignment。

因此不能声称以下单项是 TRIAD 首创：typed Skill、组合 Skill、randomization、counterfactual audit、pair interaction、QD archive 或 causal credit。

可检验的窄 novelty hypothesis 是：

> 在 QueenBee 的 Graph/Phase/Python typed executable contracts 下，把 deterministic Atom binding、真实 removal、sparse factorial、retrieved-unused swap-in、事前随机 selector、bounded QD 和 dense Bank gate组合为一个受限、answer-free、TEST-immutable 的 SkillBank 学习循环，是否能以有限 GPT-4o-mini 预算改善 held-out portfolio选择。

这是“组合在该架构中的增量”主张，不是任何组件的“首次”。

---

## 12. 高层算法

以下伪代码只表达方法顺序，不是待复制的实现代码：

```text
initialize artifact catalog and Bank snapshot from current QueenBee
mark legacy outcomes observational_only

for each TRAIN round:
    freeze a case-disjoint training manifest
    for each evaluation unit:
        choose a validated Base within the hard namespace
        retrieve at most 6 compatible Atom revisions
        enumerate Base-only and portfolios of at most 3 Atoms
        deterministically bind every identity
        separate hard exclusions, static-failed zero outcomes and runtime-safe identities
        freeze audit-eligible/runtime-safe sets, probabilities and RNG
        select one normal Portfolio and materialize a full SkillCard

        if an audit block is preselected and fully budget-reserved:
            execute every matched arm in randomized order
        else:
            execute the selected normal Portfolio

        seal immutable observations
        derive removal / interaction / opportunity contrasts
        update TRAIN-only context-specific estimates and failures

    propose one-slot mutations from answer-free evidence
    compact into a bounded candidate snapshot with QD cells
    compare candidate vs incumbent on frozen GATE_DEV units
    accept or roll back the whole snapshot using dense gate semantics

run one-shot FINAL_VAL without write-back
if a replicate fails FINAL_VAL, deploy its incumbent and keep it in the denominator
run TEST through a fully frozen facade and assert all-state hashes unchanged
```

三个容易犯错的实现捷径必须禁止：

1. 先运行 normal arm，再决定补哪个有利对照；
2. 将同时改变多个 Atom 的胜出结果平均奖励给所有成员；
3. 将 retrieved-but-unused 的 exposure 当作 efficacy evidence。

---

## 13. 分阶段落地方案

### Phase 0：Shadow identity

- 只建立 immutable Base/Atom/Portfolio identity 和 legacy migration；
- 不改变当前 retrieval 或部署；
- 验证 namespace、hash、round-trip、no-leak、same topology/different policy identity；
- 所有旧 evidence 标 `observational_only`。

**完成条件**：feature off 时当前输出和测试语义不变。

### Phase 1：PhaseProgram single-Atom materializer

- 只支持一个 phase/parameter/policy slot；
- Base-only 和 single-Atom 均能 deterministic materialize；
- static invalid 与 runtime algorithm failure语义分开；
- 暂不改变 selector。

**完成条件**：正反向 trace、coverage/budget validation 和完整 runner 均通过。

### Phase 2：Raw ledger + removal

- 增加 pre-outcome manifest 和 immutable arm observations；
- 只做 single-Atom removal；
- effect 先 shadow 计算，不影响 retrieval；
- 用 manifest 预先 case-disjoint 的 `TRAIN_SHADOW` 检查 effect sign prediction；该 fold 不回写、不能作 confirmatory claim。

**完成条件**：shared arms 不重复计数，incomplete blocks 不产生 effect。

### Phase 3：Python one-block Atom

- 复用当前 exact parent + EVOLVE block patch；
- 由最终 diff 验证单块变化；
- 一个 Portfolio 最多一个 Python executable Atom。

**完成条件**：AST、contract、sandbox、dry run、source hash 全部保持当前安全边界。

### Phase 4：Frozen selector + opportunity

- slate≤6、Portfolio≤3；
- outcome 前持久化 hard exclusions、audit-eligible/static-failed/runtime-safe partitions、全概率和 RNG；
- 开启 same-slot swap audit；
- effect 仍可保持 shadow，不立即影响部署。

**完成条件**：retrieved-unused 未执行绝不更新 efficacy。

### Phase 5：Sparse factorial

- 只对高频、高不确定、会改变决策的 pair 调度四臂 block；
- 预算和 power 不足时自动关闭；
- 每个 Atom 只保留少量有充分 support 的 interaction edges。

### Phase 6：QD 与 snapshot gate

- effect/VOI/concentration 开始影响 TRAIN retrieval；
- 加 bounded behavior cells 和 archive；
- candidate Bank 仍整体通过 held-out gate；
- 开启完整 ablation 与 equal-all-in comparison。

### 建议模块边界

| 位置 | 职责 |
|---|---|
| 新增 `triad_artifacts.py` | immutable Base/Atom/Portfolio revisions 与 hashing |
| 新增 `triad_materializers.py` | carrier-specific bind、reverse trace、static validation |
| 新增 `triad_selector.py` | slate、feasible set、probabilities、selection event |
| 新增 `triad_ledger.py` | manifests、raw observations、derived contrasts |
| 新增 `triad_archive.py` | context estimates、QD cells、capacity、eviction |
| `schemas.py` | 只增加共享 shape，不破坏旧 `SkillCard` |
| `skill_bank.py` | default-off adapter；feature off 保持旧 retrieval |
| Graph/Phase/Python generators | 暴露 typed materializer surface，不共用 untyped payload |
| `masbench/evolve.py` | branch schedule、audit schedule、candidate snapshot |
| `failures.py` | 带 revision/block ref 的 answer-free failure |
| `gates.py` | 保留 dense semantics，增加 case-clustered evaluation wrapper |
| `verify_beats_baselines.py` | 四阶段 split、all-state TEST hashes、equal-budget report |

建议 feature flags：

```text
triad_enabled = false
triad_shadow_identity
triad_removal_audit
triad_opportunity_audit
triad_pair_audit
triad_random_selector
triad_qd_archive
triad_test_frozen_assert
```

---

## 14. 实验与消融

### 14.1 研究问题

1. Atom removal effect 能否预测 held-out matched effect？
2. Opportunity audit 能否发现 selector 长期遗漏的真实更优替代？
3. Pair interaction 是否稳定、稀疏且值得额外执行成本？
4. Randomization/QD 能否降低使用集中度而不损害质量？
5. Full TRIAD 在 equal all-in budget 下是否优于 current QueenBee 和 PIF？

### 14.2 必须分开的实验 cell

```text
Level II × sink
Level II × all_agents
Level III × sink
Level III × all_agents
```

正式实验还应覆盖 agent counts `2/5/10`。所有方法使用相同 case manifest、task seed、model、timeout、proposal budget 和 execution budget。

### 14.3 比较臂

主比较：

1. current evolved QueenBee；
2. PIF-style factor replacement；
3. TRIAD shadow-only（不影响 retrieval）；
4. full TRIAD。

必要固定/搜索 baselines：cold GraphGen、cold PhaseProgram/PythonGen、`one_peer_exponential_dag`、`static_exponential`、all-agents P2P/Broadcast/SFS，以及预算允许时的 AFlow-style、ADAS-style whole-candidate control。后两者必须标“style control”，不能冒充官方复现。

### 14.4 MVP 与正式实验要分开

**MVP 目标是可行性，不宣称方法有效：**

- PhaseProgram single-Atom；
- removal 和少量 opportunity；
- shadow credit，不改变 deployed Bank；
- 检查合法 bind 率、complete-block 率、leakage、成本和 held-out effect sign；
- 不把小样本 pair interaction 当结论。

**正式实验：**

- 至少 3 个独立 search seeds；
- case-disjoint TRAIN/GATE_DEV/FINAL_VAL/TEST；
- 足够 normal executions 支撑预注册 pair blocks；
- current/PIF/TRIAD 使用同一六维 `BudgetVector` 的 equal all-in budgets；
- FINAL_VAL one-shot，失败 replicate 部署 incumbent 但仍留在分母中，TEST frozen；
- paired、case-clustered bootstrap。

### 14.5 必报指标

质量和效率：

```text
V, mean/min K, U, P, S, stage_score, C, D
algorithm / infrastructure / harness failure
tokens, model calls, repair calls, execution units, provider cost, wall time
```

逐 Agent：submission presence、exact、partial、coverage、submitted round、failure reason。

Attribution：complete removal blocks、held-out sign accuracy、predicted-vs-observed correlation、pair sign stability、opportunity hit rate、effective sample size、unsupported nonseparable rate。

Bank：Atom/Portfolio 数、cell coverage、top-1 share、HHI、effective used Atom count、archive/eviction/tombstone rate、reuse/mutate/fresh 使用与边际收益。

### 14.6 必要消融

| 消融 | 要回答的问题 |
|---|---|
| no removal | 局部主效应是否有价值 |
| no opportunity | missed-alternative audit 是否必要 |
| no pair | interaction 是否值得成本 |
| no randomization | 事前随机选择是否改善 evidence coverage |
| no QD | 多样性层是否真实影响使用集中度 |
| observational-only | matched intervention 是否优于共现统计 |
| singleton Portfolio | 复杂 portfolio 是否比 PIF-like 单因子更有价值 |
| reuse-only / mutate-only / fresh-only | 三分支的边际贡献 |

### 14.7 升级为“有效方法”的预注册最低标准

同时满足：

1. 至少 3 个独立 search seeds；
2. 至少两个 task level/family，agent counts 包含 2、5、10；
3. 在预注册固定 cell weights 的 case-paired frozen TEST aggregate 上，full TRIAD 相对 `current QueenBee` 与 `PIF` 中较强者的 `stage_score` 至少 `+0.03 absolute`；
4. 上述 primary contrast 的 paired、case-clustered bootstrap 95% CI 下界 `> 0`；
5. 在同一 primary contrast 上，strict exact `S` 至少 `+0.03 absolute`；
6. algorithm failure、`V`、minimum `K`、`U`、`P` 均不回归；
7. 相对共同 normal budget，六维 `BudgetVector` 中每一项的 incremental audit overhead 均不超过 10%，且 primary 方法比较本身采用 equal all-in budget；
8. FINAL_VAL 失败的 replicate 以 incumbent outcome 和 `method_failure=True` 保留，仍满足以上 pooled 标准；
9. full TRIAD 优于 no-pair、no-opportunity、no-QD、no-randomization 中至少两个关键消融；
10. TEST/ground-truth/private-prompt leakage 为零；
11. 独立复现方向一致。

这些阈值是接受合同，不是预期结果陈述。

---

## 15. 可证伪预测与停止标准

### 15.1 六个明确预测

1. **Removal prediction**：context-specific Atom estimate 对 held-out removal effect 的方向准确率显著高于 whole-skill mean、共现 association 和 permutation baseline。
2. **Opportunity value**：高 exposure/低 execution 的 Atom 中，swap-in audit 能找到非零比例的真实正替代。
3. **Sparse interaction**：少量 pair 有跨 seed 稳定的非零 interaction，并能改善 portfolio ranking。
4. **Anti-monopoly**：HHI/top-1 share 下降，使用覆盖率上升，同时 dense quality 不下降。
5. **Bank uplift**：equal all-in budget 下 full TRIAD 的 frozen Bank 优于 current 与 PIF。
6. **Weak-model usability**：GPT-4o-mini 的 bounded local proposal validity 足以产生可审计 evidence，不依赖强模型阅读完整 archive。

### 15.2 最可能的三个根本失败

1. **不可分解**：多数有效 Skill 没有合法 neutral removal，Atom credit 无法识别。
2. **高阶交互主导**：一阶与二阶 effect 无法预测完整 Portfolio，高成本 factorial 仍不够。
3. **成本不合算**：在六维 10% incremental audit cap 和 equal all-in method budget 内 evidence 太少，放宽预算后收益又不足以覆盖成本。

### 15.3 停止条件

| 现象 | 结论/动作 |
|---|---|
| known-valid control ≥95%，新 proposal validity <30%，连续两轮无改善 | model/proposal floor，停止扩预算 |
| 可分解 support 低于预注册阈值 | 不宣称 Atom attribution；退回 PIF/whole-skill |
| held-out removal sign accuracy ≤55% 且不优于 permutation | 主信用假设失败 |
| ≥10 个完整 pair blocks 后 pair sign 频繁翻转 | 关闭 interaction layer |
| opportunity positive rate 接近随机且不能改变选择 | 关闭 opportunity ledger |
| HHI 降但 quality 显著降 | diversity intervention 失败 |
| 六维中任一 incremental audit overhead >10% 且无正向 CI | 成本假设失败 |
| composition 可预测而一/二阶 effect 不可预测 | 高阶 interaction 主导，停止局部因果主张 |

以下任一发生立即作废 replicate：

- TEST 前后任一 mutable state hash 改变；
- answer、ground truth、expected output 或 private prompt 进入 Bank；
- `sink/all_agents`、mode 或 worker contract 串库；
- harness failure；
- audit 未事前冻结或只保留成功 arm；
- Python 绕过现有 AST/sandbox/contract validator；
- 任一方法突破预注册 all-in budget。

---

## 16. 给实现与比较 Agent 的检查表

### 16.1 判断一个设计是不是 TRIAD

- Atom 是否有 deterministic typed slot/binder，而不是自然语言标签？
- Base-only 是否始终存在？
- Portfolio identity 是否 immutable、ordered、capacity-bounded？
- Runtime 是否仍执行完整 typed artifact？
- Removal 不合法时是否标 nonseparable，而非补零？
- Legal algorithm failure 是否诚实零分并保留成本？
- Pair interaction 是否来自完整四臂？
- Retrieved-unused 是否只有真实 swap 后才有 efficacy？
- Slate、eligible set、概率、RNG 是否在 outcome 前冻结？
- Audit 是否完整预留 all-in 与 incremental budget？
- 三类 view 是否引用同一 raw observations？
- Local effect 是否无法绕过 Bank gate？
- FINAL_VAL/TEST 是否完全不回写？

### 16.2 与其他方法比较时必须对齐

- 相同初始 Bank/Base substrate；
- 相同 proposer model 和 proposal call/token cap；
- 相同 case/seed evaluation units；
- 相同六维 all-in `execution_units/tokens/model_calls/repair_calls/provider_cost_usd/wall_time_seconds` budget；
- 相同 hard validators、failure semantics 和 dense gate；
- 报告 trajectory divergence，而不是强迫不同方法产生相同 candidates；
- 同时报告 performance、attribution quality、diversity 和 cost；
- 不把 TRIAD 的额外 audit 当免费数据。

### 16.3 何时优先选择更简单方法

优先 current QueenBee 或 PIF，如果：

- 主要候选是 atomic whole program；
- 可安全干预的 factor 很少；
- Portfolio 几乎总是 singleton；
- pair/opportunity evidence 无法在预算内形成；
- PIF replacement 已能稳定预测 held-out effect；
- TRIAD 只提升多样性指标而不提升最终质量。

---

## 17. 固定 commit 代码依据

### 17.1 仓库入口

- [固定 commit `8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a`](https://github.com/RobinTian-7/Mutiagent/commit/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a)
- [根 `AGENTS.md`](../../../AGENTS.md)
- [根 `README.md`](../../../README.md)
- [`masbench/docs/self_evolution_changes.md`](../../../masbench/docs/self_evolution_changes.md)
- [`masbench/docs/experiments.md`](../../../masbench/docs/experiments.md)
- [`masbench/docs/python_generate.md`](../../../masbench/docs/python_generate.md)

### 17.2 关键 claim-to-code permalinks

| 当前代码事实 | 固定 commit permalink |
|---|---|
| Planner modes、goal、worker contracts | [`schemas.py#L21-L54`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/schemas.py#L21-L54) |
| Typed payloads 与 `SkillCard` | [`schemas.py#L409-L590`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/schemas.py#L409-L590) |
| Retrieval hard filters | [`skill_bank.py#L84-L125`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L84-L125) |
| Mode/goal/contract matchers | [`skill_bank.py#L307-L438`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L307-L438) |
| Retrieval dedupe 与显式 compaction merge 的区别 | [`skill_bank.py#L553-L660`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L553-L660) |
| Topology fingerprint 不含 reasoning policy | [`topology_equivalence.py#L34-L94`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/topology_equivalence.py#L34-L94) |
| Staged dense score | [`evolve.py#L519-L548`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L519-L548) |
| Whole executable/topology ablation | [`evolve.py#L3477-L3570`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L3477-L3570) |
| Insight association 明确非因果 | [`evolve.py#L3790-L3926`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L3790-L3926) |
| Current VAL write-back path | [`evolve.py#L4488-L4593`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L4488-L4593) |
| `strict_dense_v2` paired gate | [`gates.py#L78-L183`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/gates.py#L78-L183) |
| Failure classification 与 answer-free records | [`failures.py#L34-L252`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/failures.py#L34-L252) |
| Phase DSL 与 deterministic compiler | [`phase_program.py#L38-L203`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/phase_program.py#L38-L203) |
| Python exact block patch | [`python_mutation.py#L67-L205`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/python_mutation.py#L67-L205) |
| Current TEST control flow，无完整 Frozen facade | [`verify_beats_baselines.py#L1039-L1055`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/scripts/verify_beats_baselines.py#L1039-L1055), [`#L1133-L1213`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/scripts/verify_beats_baselines.py#L1133-L1213) |

### 17.3 外部背景链接

- [Lilian Weng：Harness Engineering for Agentic Systems（2026-07-04）](https://lilianweng.github.io/posts/2026-07-04-harness/)
- [AFlow](https://arxiv.org/abs/2410.10762)
- [Automated Design of Agentic Systems](https://arxiv.org/abs/2408.08435)
- [AlphaEvolve](https://arxiv.org/abs/2506.13131)
- [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954)

这些链接用于恢复来源语境，不表示本文重新完成了来源对话中全部博客引用、上传 PDF 去重和官方仓库审计。正式论文或对外 novelty 声明前必须重新核对论文版本、官方代码身份、commit/tag 和访问日期。

---

## 18. 最小不可删减定义

如果后续论文或实现说明只能保留一段，应保留：

> TRIAD-SkillBank 在 immutable、carrier-native Base 上，用具有 typed slot、deterministic binder、dependency 和 revision identity 的 SkillAtoms 构成 bounded ordered Portfolio，但 runtime 仍执行完整 materialized SkillCard。信用只来自真实 matched blocks：固定背景的 removal、完整四臂 pair factorial，或 frozen slate 中 retrieved-unused Atom 对 selected Atom 的 same-slot swap-in；未执行 exposure 不获得 efficacy。所有 contrasts 由同一 immutable raw observation ledger 派生，结构不可分不补零，合法 algorithm failure 诚实记零质量并保留成本，infrastructure 不更新，harness 终止。Selector、概率、RNG 和 audit manifest 在 outcome 前冻结；audit 受 complete-block all-in budget 限制。Local evidence 只影响 TRAIN search，最终部署仍由 frozen Bank-level dense gate 决定，FINAL_VAL/TEST 不回写且以 all-state hash 审计。

---

## 19. Changelog

- **2026-07-14 / concise design archive**：根据用户要求，将原先接近实现规格的长文收敛为详细方法方案；保留方法身份、归因公式、生命周期、carrier 边界、成本、安全、比较、落地阶段、实验与证伪标准，移除完整代码式 schema、逐字段 validator 和长篇实现伪代码。
