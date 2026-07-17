# TRACER-SkillBank 方法设计档案

> **TRACER — Typed Retrieval, Attribution, Composition, Exposure, and Regret SkillBank**

| 项目 | 内容 |
|---|---|
| Method ID | `tracer_skillbank_v0` |
| 文档性质 | 详细研究方案，不是实现代码或实验结论 |
| 方法状态 | **未实现、未验证、可证伪的研究假设** |
| 来源对话 | `6a564a5d-79a0-83ea-9c5b-8bcf71203803`（SkillBank 研究假设） |
| QueenBee 审核基线 | commit `8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a` |
| 归档日期 | 2026-07-14 |
| 目标读者 | 实现 Agent、实验 Agent、代码审计 Agent、方法比较 Agent |
| 相关设计 | [PIF-Bank](./2026-07-14-pif-bank-method-design.md)、[TRIAD-SkillBank](./2026-07-14-triad-skillbank-method-design.md) |

本文把来源对话中的最终方法统一命名为 **TRACER-SkillBank**，并收敛成一份**详细但不等同于代码实现**的方法档案。文中给出对象关系、状态机、估计量、算法流程、工程边界、比较合同和实验标准；不展开完整 Pydantic schema、函数签名、迁移脚本或可直接复制的实现代码。

---

## 1. 阅读约定与结论边界

### 1.1 证据标签

- **`CURRENT_CODE_FACT`**：固定 commit 中可以直接复核的行为。
- **`SOURCE_CONVERSATION_CLAIM`**：来源对话给出的论文、博客或 prior-art 审计结论；本文没有重新执行完整外部审计。
- **`AUDIT_INFERENCE`**：根据代码与方法结构推导出的风险，需要实验验证。
- **`TRACER_PROPOSAL`**：建议新增的算法或工程机制，当前仓库尚未实现。

### 1.2 一句话核心思想

> **TRACER-SkillBank 把 Skill 使用建模为“检索 slate → 组合 bundle → materialize/execute”的两阶段 logged decision process，在 TRAIN 中用受预算约束的 matched drop 与 same-slot swap probes，分别测量已使用 Skill、被检索但未使用 Skill和模型实际采纳 Skill 的价值，再让这些证据驱动 retrieval、targeted mutation、bounded QD archive 与 revival；完整 Bank 的部署仍由 QueenBee 的 held-out dense gate 决定。**

### 1.3 方法最值得验证的假设

TRACER 关注一个比“Skill 好不好”更细的问题：

> 一张 Skill 没被使用，究竟是因为它没有被检索、被 Composer 排除、没有被 materialize、弱模型没有遵循，还是它被正确使用后仍然无效？

当前 SkillBank 通常只能观察完整 candidate 的结果。TRACER 试图把这条链拆开，并把“检索到了但错过了更好 Skill”定义成可执行、可反驳的 **opportunity regret**。

### 1.4 正确的研究状态表述

在正式实验通过预注册标准前，只能说：

> TRACER-SkillBank 是经过来源对话整理、固定 commit 代码复核和方法对抗审阅后，针对 QueenBee retrieval exposure、bundle selection、weak-model adoption 与 missed opportunity 的可实施研究假设；它尚未被证明有效。

不得写成“TRACER 已解决 exposure bias”“已得到因果 Skill credit”或“已证明比 PIF/TRIAD 更好”。

---

## 2. 当前 QueenBee 基线与精确缺口

### 2.1 当前已经具备的能力

**`CURRENT_CODE_FACT`**：固定 commit 已经拥有：

- 五种 planner mode 与独立的 typed `mode_payload`；
- named topology、paper transport、Graph、PhaseProgram、Python 五类 executable artifact；
- 独立 `reasoning_policy`、evidence、failure、counterexample、confidence 和 provenance；
- request-scoped 的 task、objective、`sink/all_agents`、agent range 等过滤，以及 generated-mode、provenance allowlist 与 Python worker contract 的条件匹配；其中非 generated mode、非 clean Graph 路径和未提供 provenance allowlist 的请求存在明确兼容例外；
- 悲观 retrieval loss、证据数量排序、topology equivalence dedupe 与 bounded compaction；
- `reuse`、Python parent-aware `mutate` 和 fresh/innovation；
- answer-free `FailureRecord` / `FailureCluster`；
- whole executable/topology ablation 与明确标为非因果的 insight association；
- `V/K/U/P/S/stage_score/C/D` 和 paired `strict_dense_v2` gate；
- Graph/Phase validator 与 Python parent SHA、EVOLVE block、AST/contract 安全边界。

所以 TRACER 不是“给 Skill 加类型”“记录失败”“加入 archive”“增加 mutation”“增加 gate”或“做多样性检索”的改名版本。

### 2.2 当前 `operator_compose` 不等于多 Skill composition

**`CURRENT_CODE_FACT`**：确定性的 `OperatorComposePlanner` 先取得 `TopologySelectPlanner` 的 base plan。正常选卡路径至多消费一张 `SkillCard`；但空检索、avoid veto 或 loss floor 可产生不绑定 Skill 的 fallback plan，而且 operators 为空时会使用 objective-derived defaults。随后 planner 才把最终 operators 编译成完整 spec。

正常选卡路径是：

```text
one selected SkillCard
    → its operator list
    → compiled ProtocolGraphSpec
```

fallback 路径则可能是：

```text
no selected SkillCard
    → fallback topology and/or objective-default operators
    → compiled ProtocolGraphSpec
```

它不是：

```text
several independently retrieved Skills
    → typed slots and compatibility
    → one bundle
    → member-level and selection-level evidence
```

另一个 LLM planner 路径可在 prompt 中看到至多 6 张 positive Skill contexts，并可返回自选 `skill_id` 与 `operators`；实际可见数量可能是 0、1 或多张。当前 validator 不能证明这些 operators 只来自一张卡，也没有多卡 bundle identity、member-level materialization trace 或组合信用。因此它最多是**不可审计的隐式综合**，不能算已有的 typed multi-Skill composition。

因此“真正的多 Skill bundle lifecycle”是可新增空间，但必须复用当前完整 artifact validators，不能变成自由代码拼接。

### 2.3 当前等价性对 reasoning variant 的风险

**`CURRENT_CODE_FACT`**：正常 retrieval 先排序，再按 goal-prefixed equivalence key 保留首个结果：能推导 topology hash 时使用 `information_goal + topology_hash`，否则退回 `information_goal + skill_id`。显式 compaction 会选一个代表卡，并合并 evidence、risk、failure、counterexample 等 metadata。Topology fingerprint 本身不包含 `reasoning_policy`。

**`AUDIT_INFERENCE`**：相同结构、不同 merge/send/submit policy 的卡可能在 retrieval 或 compaction 时只剩一个代表。Mode/contract 的 retrieval 隔离减少了明显串库，但没有给 reasoning variant 独立的长期竞争身份。

TRACER 必须让：

```text
same structure hash + different reasoning-policy hash
```

成为不同 `SkillVariantRevision`，而不是重复存三份相同 executable 或把 policy 证据混成一张卡。

### 2.4 当前没有通用的 exposure/adoption ledger

当前代码可记录 selected Skill、hot-start branch、Python exposed/used insight 等特定信息，但没有对所有 Skill 统一记录：

```text
eligible
retrieved
selected by composer
materialized into artifact
host-verifiably followed
executed with a valid outcome
```

Matched benefit 属于单独的 credit ledger，而不是 event flag。尤其 retrieved-but-unused 当前没有通用 efficacy estimand。没有被选中不等于负信用，也不等于零信用。

### 2.5 当前 retrieval fallback 不是绝对 hard silo

**`CURRENT_CODE_FACT`**：`SkillBank.retrieve()` 正常路径执行 request-scoped filters；其中 planner-mode matcher 对 `topology_select` / `operator_compose` 不做 generated-mode 强隔离，非 clean Graph 路径允许 named/source-less anchors，provenance 也只有请求提供 allowlist 时才过滤。除此之外，`TopologySelectPlanner` 在检索结果为空时还会回退到 Bank 中全部 selectable skills。Generation-context 路径同样有意采用不同的 mode/provenance 可见性规则。

因此 TRACER 不能笼统写“复用现有 retrieval 就自动保持所有 silo”。它必须在 slate commit 前再次验证每个 variant 的 task/goal/mode/contract/provenance namespace；空结果只能选择同 namespace 的显式 baseline 或失败，不能回退到全 Bank。

### 2.6 差距矩阵

| 问题 | 当前最接近机制 | TRACER 需要新增什么 |
|---|---|---|
| 多 Skill 组合 | 单卡 `operators` compose | typed root/adjunct bundle 与 slot contract |
| 检索 exposure | deterministic sorted results | outcome 前冻结的 slate、exclusions、随机概率和 event log |
| Composer selection | 选完整 Skill/branch | bundle candidate set、selection event 与 missed-alternative audit |
| Weak-model use | outcome 与少量 trace | selected→activated→followed adoption 诊断；benefit 单列 matched ITT credit |
| Used Skill credit | whole executable ablation | 合法 matched drop/removal |
| Retrieved-unused credit | 无通用机制 | compatible same-slot swap opportunity effect |
| Pair interaction | 无 | 预算允许时完整四臂 factorial；单 pair-drop 不能冒充 interaction |
| Model transfer | 通用 evidence | model/runtime/contract-conditioned adoption 与 variant evidence |
| Diversity | Top-N + structural dedupe | behavior cells、probe debt、use concentration、revival |
| Deployment | `strict_dense_v2` | 保留现有 gate；local credit 不能直接部署 |

---

## 3. TRACER 的最小方法身份

只有同时满足以下约束，才应称为 `tracer_skillbank_v0`：

1. 检索和组合是两个可分别审计的决策阶段；
2. `SkillFamily` 只提供语义组织与先验，不是 executable identity；
3. `SkillVariantRevision` 才是 mode/contract-scoped 的可执行与可验证单位；
4. Bundle 有且只有一个 executable root，adjunct 必须通过 typed hook；
5. runtime 始终执行完整 materialized `SkillCard` 或等价完整 artifact；
6. 每个 eligible/retrieved/selected/activated/followed event 有稳定定义；
7. retrieved-unused 不执行时只获得 exposure，不获得 efficacy credit；
8. opportunity credit 只能来自 compatible same-slot swap 的真实 matched run；
9. used Skill 的局部信用来自合法 drop/removal，不来自同一次 outcome 的平均分摊；
10. pair interaction 只能来自完整四臂 block；
11. logged propensity 只在有随机 support 和 positivity 时用于估计，记录概率本身不创造因果识别；
12. probe debt 只是调度优先级，不是正面或负面 evidence；
13. local evidence 只影响 TRAIN search、mutation 和 archive；
14. 完整 Bank 仍经过 held-out dense gate；
15. TEST、answer、ground truth、expected output 和 private prompt 永不进入 Bank。

缺失其中的 exposure、same-slot opportunity 或 adoption 阶梯时，只能称为普通 bundle search 或 TRIAD/PIF-like attribution，不是本文定义的 TRACER。

### 3.1 TRACER 不是什么

- 不是第六种 `planner_mode`；
- 不是跨 Graph/Phase/Python 的 source 拼接器；
- 不是一个新 neural retriever；
- 不是完整 Shapley value；
- 不是“所有被检索 Skill 都共享 outcome”的 EMA；
- 不是靠 LLM 判断自己是否遵循 Skill；
- 不是把 QD、bandit、counterfactual 和 archive 拼起来后就宣称新颖；
- 不是对 TEST 进行在线适应。

---

## 4. 概念对象与 identity

本文只定义对象职责，不给完整 schema。

### 4.1 核心对象

| 对象 | 身份与职责 | 最少应保存 | 不能做什么 |
|---|---|---|---|
| `SkillFamily` | 同一可审计设计 recipe 的组织/prior | family ID、semantic contract、recipe hash、variant refs | 直接执行或跨 mode 继承成功结论 |
| `SkillVariantRevision` | 真正可执行、可验证的 mode-specific identity | atomic Skill ref、mode/goal/contract、structure hash、reasoning hash、revision hash | 因 family 成功跳过本 variant gate |
| `HookSlotRevision` | Adjunct 可绑定的 typed interface | slot kind、input/output contract、binder/verifier version | 接受自由文本或任意 source splice |
| `BundleRevision` | 一次部署候选 | one root、ordered adjunct bindings、namespace、bundle hash | 跨 goal/mode/contract 组合 |
| `RetrievalSlateSnapshot` | 第一阶段 outcome 前快照 | eligible pool hash、retrieved variant IDs、probabilities、exclusions、RNG | outcome 后改概率或补候选 |
| `CompositionSetSnapshot` | 第二阶段 bundle 候选快照 | feasible bundles、hard exclusions、scores、probabilities | 只保留 winner、丢弃未选项 |
| `MechanismEvent` | exposure 与 adoption 的运行事实 | eligible/retrieved/selected/activated/followed/executed flags 与 verifier refs | 把 exposure 或 post-treatment mediator 当 efficacy |
| `AdoptionView` | 从全部 MechanismEvents 聚合的 context-conditioned use/follow 诊断 | normal-policy funnel、probe-arm funnel、denominators、verifier coverage | 只看被 probe 或 followed 的样本，或输出 efficacy |
| `ProbeBlock` | 真实 matched intervention 原始证据 | pre-outcome manifest、arms、execution order、outcomes、cost/failure | 事后选择有利 comparator |
| `CreditView` | 只从 ProbeBlock 派生的 matched efficacy estimate | conditional removal、opportunity、interaction 及 background context | 修改 raw observations 或混入 adoption rate |
| `ArchiveEntry` | probation/active/archive/quarantine 与 revival 状态 | evidence refs、niche、use concentration、probe debt、state reason | 让 quarantine 直接进入 prompt |

### 4.2 Revision identity、hard namespace 与 effect context 必须分层

三类 key 不能混成一个 hash：

```text
Immutable VariantRevision identity:
  atomic payload/source hash
  structure hash
  reasoning-policy hash
  parent/revision lineage
  binder/materializer/compiler/scaffold version that changes the artifact

Hard compatibility namespace:
  task_family
  information_goal: sink | all_agents
  planner_mode / carrier
  worker_contract（Python 时必需）
  execution/input/output/security contract

EffectContextKey:
  model/provider/version and temperature policy
  runtime/verifier version
  agent-count bucket
  task-feature bucket
  all-in budget bucket
```

模型或预算变化不创建新的 executable revision；它创建新的 effect context 或触发重新校准。反过来，payload、reasoning policy 或会改变 materialized artifact 的 compiler/scaffold 变化必须创建新 revision。Family 可以跨 variant 共享一个弱 prior，但不同 hard namespace 或 effect context 的 observed effect、failure、adoption rate 和 interaction 不得直接混成同一个 local posterior。

### 4.3 Family 是 prior，不是可执行对象

Family 的用途是区分：

```text
设计 recipe 是否可能有价值
```

与：

```text
某个 Graph/Phase/Python realization 是否正确实现了它
```

一个 Graph variant 成功，只能提高同 recipe 的其他 variant 的 exploration prior。它不能证明 Python variant 有效，也不能绕过 Python AST、contract、sandbox 或 held-out gate。

跨表示加入同一 Family 至少需要：

1. 相同 canonical semantic contract；
2. 相同、非自由文本的 recipe identity；
3. answer-free synthetic conformance suite；
4. 每个 variant 独立通过 mode-specific validity；
5. 明确记录 family prior 与 variant residual。

如果 family membership 仍依赖 LLM 说“这两个看起来相似”，则该 family 只能作为 context tag，不能进入信用或自动迁移。

### 4.4 Bundle 的最小合同

建议第一版：

```text
exactly one root_executable
at most one reasoning_policy adjunct
at most one safety/runtime-guard adjunct
at most one budget_adapter adjunct
total members <= 4
```

第一版总数 4 与 slot 数不是理论常数；若以后提高到来源方案的 6，必须先新增两个有明确 multiplicity、binder、verifier 和 compatibility rule 的 typed slots，不能只改上限。任何 adjunct 都必须有 host-owned binder 和 verifier；没有 hook 的完整 Skill 标为 `atomic_locked`，仍可作为 root，但不能伪装成可 drop sidecar。

---

## 5. Exposure、Selection 与 Adoption 事件阶梯

### 5.1 事件定义

| 事件 | 唯一定义 | 能更新什么 |
|---|---|---|
| `eligible` | 通过 hard namespace/contract/safety filters | pool coverage，不是信用 |
| `retrieved` | 被写入冻结 slate | exposure count、probe debt |
| `selected` | 被 Composer 放入最终 BundleRevision | selection rate，不是 efficacy |
| `activated` | host 证明该 revision/hook 实际进入被执行 artifact | activation rate |
| `followed` | host verifier 在 trace 中证明声明的可观察机制成立 | following/adoption rate |
| `executed` | 对应完整 artifact 获得一个合法 outcome | composition observation |

本文定义：

\[
Adopted := Activated \land Followed
\]

`selected` 不等于 `activated`，`activated` 不等于 `followed`。是否有益不是单次运行事件；它是完整 matched ProbeBlock 经预注册 hard-metric rule 汇总后产生的 `CreditView` 状态。

### 5.2 Host-verifiable adoption

`activated` 的可验证示例：

- Graph/Phase hook 出现在最终 compiled spec；
- 实际 source hash 在 Python worker 中运行；

`followed` 的可验证示例：

- `coverage_complete_submit` 确实在 coverage complete 后提交；
- `delta_or_no_send` 没有重复发送未变化 state；
- fan-in/message/round bound 在 trace 中成立；
- all-agents 每个 Agent 独立提交。

不可验证示例：

```text
think more carefully
reflect deeply
be creative
```

这类自然语言只能获得完整 bundle outcome，不能获得 facet-level `followed` 证据。LLM 自报“我使用了 Skill”不算 host evidence。

### 5.3 Model-conditioned adoption

至少按以下 context 保存：

```text
model name/version
temperature/provider policy
worker contract
context-budget bucket
runtime/scaffold version
```

分别估计：

\[
P(Activated\mid Selected),\qquad
P(Followed\mid Activated)
\]

这些概率解释“模型能不能用”，不是 Skill 的任务收益。可以在 retrieval ranking 中作为部署可用性信号，但必须与 matched efficacy 分开报告，不能用三个 LCB 的简单乘积冒充新的因果 estimand。

Primary operational efficacy 使用 **assignment/ITT** 语义：一旦 selector 分配某 variant，未激活、未遵循或格式失败都属于该部署政策的真实结果，不能在计算 effect 时事后删除。`followed` 是 treatment 后 mediator；只分析 followed runs 会产生 post-treatment selection bias。若未来要估计 per-protocol/complier effect，必须另有随机 encouragement 与额外识别假设，不能靠普通 propensity 或 DR 自动得到。

### 5.4 事件与账本的禁止更新矩阵

| 只观察到的最高事件 | 允许更新 | 禁止更新 |
|---|---|---|
| `eligible` | eligibility coverage | exposure、efficacy |
| `retrieved` | exposure、probe debt | positive/negative efficacy |
| `selected` | selection frequency | conditional-removal/opportunity effect |
| `activated` | activation posterior | following、efficacy |
| `followed` | adoption posterior | efficacy，除非另有完整 matched contrast；也不能丢弃未 followed arm |
| `executed` | bundle observation | 把 outcome平均分给所有 members |
| matched probe complete | 对应条件性 effect | 其他未干预 member 的信用 |

---

## 6. 完整生命周期

### 6.1 Create / Register

当前 atomic `SkillCard` 继续由现有 generation、validation、evidence、patch 和 gate 流程产生。TRACER 在其上注册 `SkillVariantRevision`：

- executable source仍在原 typed payload；
- variant 保存 immutable ref 与 structure/reasoning hashes；
- family membership 使用 canonical recipe/contract 与 synthetic conformance；
- 旧证据标 `observational_only`；
- 未通过当前 mode validator 的候选不能因 family 标签进入 active Bank。

### 6.2 Retrieve：第一阶段决策

顺序必须是：

1. 当前 QueenBee hard filters；
2. variant hard namespace、model profile 和 budget compatibility；
3. validity/failure/support safety floor；
4. 仅使用预注册 `RetrievalContextKey` 下的 reference-background evidence、opportunity uncertainty、adoption、risk、probe debt、niche rarity 和 concentration ranking；
5. 形成 outcome 前冻结的 logged slate。

来源方案默认 slate 为 8：6 个 exploitation slots + 2 个 randomized exploration slots。这个配置应视为可消融超参数。

### 6.3 Compose：第二阶段决策

Composer 从 slate 中形成一个完整 bundle：

- 先枚举/beam-search root；
- 只沿声明的 HookSlot 尝试 reasoning、guard、budget adjunct；
- deterministic materialize 或给出明确 rejection；
- 冻结 candidate set、excluded reasons、score 和 selection probabilities；
- 再选择一个 BundleRevision。

来源方案建议 beam width ≤16；`tracer_skillbank_v0` 的 bundle size ≤4。Beam search 本身必须是 deterministic、versioned 的 candidate generator；否则所谓 selection propensity 只是在一个不可复核 LLM 候选集上的数字。

### 6.4 Execute

最终 bundle 必须 materialize 为完整现有 artifact，并继续走当前：

```text
ProtocolRunner / Python worker
schema/compiler/AST/sandbox
submission barrier
V/K/U/P/S/stage/C/D scorer
failure classifier
```

TRACER 只增加 host-owned instrumentation，不接管答案生成或评分。

### 6.5 Attribute

普通执行只更新 bundle observation 和事件阶梯。Probe scheduler 在预算内选择：

- used adjunct drop；
- root/reference replacement；
- retrieved-unused same-slot swap；
- 可选的完整 pair factorial block。

Probe 必须 outcome 前选定并完整预留 comparator 成本。完成后从同一 immutable raw block 派生 credit view。

### 6.6 Mutate

只有证据满足预注册 support 才能 targeted mutation：

- background-conditional removal effect 的悲观上界仍为负 → 修改该 variant/slot；
- family prior 正、variant residual 负 → 保留 recipe，重做 realization；
- pair interaction稳定为负 → 禁止组合或修改一个接口；
- opportunity LCB 为正 → 提升 unused variant 或修正 Composer；
- ITT 较差且 activation/following 低 → 优先检查 materializer/instruction 这一机制解释，但不从 ITT 中删除这些失败，也不把 Bank-level outcome 直接归罪于 recipe；
- 无可识别证据 → fresh，而不是编造 mutation target。

### 6.7 Gate

Local credit 只能构造 candidate snapshot。完整 candidate 与 incumbent 在相同 held-out evaluation units 上经过现有 dense gate 语义：algorithm failure、`V/K/U` 不回退，`P` 在 configured `partial_tolerance` 内不回退，paired `stage_score` bootstrap CI 的下界非负，并且 `S/stage` 真正改善；另一条合法路径是质量完全相同，`C`、`D` 均不更差且至少一项严格下降。

当前 `strict_dense_v2` 以 `(case_id, seed)` 建 dict 后按行重采样，不是 case-clustered；重复 key还会被覆盖，质量改善路径也没有独立 `C/D` 上限。TRACER 的正式方法比较应先拒绝重复 evaluation identity，再在其外增加 case-clustered wrapper 和 equal-all-in budget contract，但不得改写当前 gate 的事实语义。

Credit-integrity、diversity 或 adoption checks 可以阻止一个不可信 candidate，但不能让未通过 `strict_dense_v2` 的 candidate 部署。

### 6.8 Archive / Revive

通过 gate 的 variant 进入 active niche；被充分测量且 dominated 的进入 archive；hard-valid 但尚未独立通过 deployment gate、或只随 rejected candidate Bank 出现的 revision 保持 probation；只有 invalid/leaky/sandbox/contract-mismatched artifact 进入 quarantine。Bank-level rejection 不创建 single-Variant harmful credit。Archive 只在预注册 drift/revival budget 中重新探测，不能因为模型版本变化自动恢复 active。

---

## 7. Outcome 与四类估计对象

### 7.1 Outcome vector

记完整 Bundle `B` 的运行结果为：

\[
Z(B)=(V,K,U,P,S,G,-C,-D),\qquad G=stage\_score
\]

所有 effect 同时保存原始差：

```text
delta_V, delta_K, delta_U, delta_P, delta_S, delta_stage
delta_C, delta_D, algorithm_failure_delta
```

`delta_C/delta_D > 0` 表示 treatment 更贵。Ranking 可以使用统一正向 utility，但原始成本方向不能被隐藏。

### 7.2 Used Skill 的 Background-conditional removal effect

对 bundle 中可合法移除的 adjunct `i`：

\[
\tau_i(B,x)=Z(B,x)-Z(B-i,x)
\]

它回答：

> 在当前 Base/root、其他 members 和 task context 固定时，保留 `i` 比移除 `i` 好多少？

它不是 `i` 的全局平均价值。若 `B-i` 无法通过 deterministic binder，记录 `unsupported_nonseparable`，不能把非法 shadow 补成零后奖励 `i`。

Root 不能删除为空。Root comparison必须替换成同 namespace 的预注册 canonical baseline/incumbent root，因而 estimand 是 **replacement effect**，不是 absence effect。

### 7.3 Retrieved-unused 的 Opportunity effect

设 `j` 被检索、与 slot 兼容但未选择，当前该 slot 使用 `i`：

\[
\omega_{j\leftarrow i}(B,x)
=Z(B-i+j,x)-Z(B,x)
\]

这是 TRACER 的核心 estimand：

> Retriever 已把 `j` 放进 slate，但 Composer 错过了它；在相同 slot 和背景下，真实换入 `j` 是否更好？

若 slot 为空，加入 `j` 得到的是 `slot-fill effect`。它会同时改变 bundle size，不得与 same-slot opportunity swap 混为同一 posterior。

仅 `retrieved=True, selected=False` 时，`j` 的 efficacy 状态仍是 `UNIDENTIFIED`。只有真实 swap block 完成后才更新 opportunity credit。

### 7.4 Pair interaction

正式 interaction 必须运行四臂：

```text
B
B - i
B - j
B - {i, j}
```

并计算：

\[
\gamma_{ij}=Z(B)-Z(B-i)-Z(B-j)+Z(B-\{i,j\})
\]

一个 main run 加一个 `pair_drop` shadow 只能测 joint removal，不能识别 `γ`。因此来源方案中的“每任务最多一个 shadow”与“pair interaction”不能同时成立：

- `tracer_skillbank_v0` MVP 的单-shadow路径只做 drop 或 opportunity；
- pair interaction 是正式实验中的 sparse complete-block 扩展；
- 若没有三个可复用/新增 comparator arms，输出只能标 `descriptive_pair_drop`；
- 不允许用共现或单次 pair drop 创建 positive/negative interaction edge。

### 7.5 Adoption statistics

Activation/following 的条件概率由全部 `MechanismEvent` 聚合，不要求该 unit 被 probe，用于回答“模型能否采用”，但不直接回答“采用后是否改善”。推荐分别维护：

```text
activation_rate = P(activated | selected)
follow_rate = P(followed | activated)
followed-block outcome = descriptive diagnostic only
```

如果 selected→activated 很低，问题可能在 materializer；activated→followed 很低，问题可能在弱模型或 instruction。Primary ITT effect仍包含这些失败。`followed` 子集上的 outcome只能作机制诊断，因为它由 treatment 后行为筛选；没有额外随机 encouragement、exclusion 和 monotonicity 等假设时，不能称为 per-protocol causal benefit。

Primary `AdoptionView` 每个 evaluation unit只计一次正常 policy-assigned Bundle，避免一个三臂 pair block让该 unit被重复加权。Comparator/probe arms的 events全部保留，但单列 `probe_arm_adoption` 并按 probe type/target分层；不能与正常 policy funnel直接合并。这样 VOI scheduler决定谁被 probe，不会污染正常 adoption rate。

### 7.6 Family、Variant 与 Policy 层级证据

- Variant effect 是部署与淘汰的主要证据；
- same topology/different reasoning policy 使用独立 variant posterior；
- Family 只从多个经过验证的 variants 获得 shrinkage prior；
- 新 mode 的 variant 起始为 `transfer_probation`；
- family prior 不能抵消 variant 的 validity/coverage/submission regression；
- model profile 变化后 adoption 与 efficacy 均需重新校准。

---

## 8. Logged probability、可识别性与 Probe Scheduler

### 8.1 两阶段 probability 必须分账

一次正常选择至少记录：

```text
retrieval eligibility and exclusions
ordered-slate joint probability and per-slot conditional probabilities
bundle candidate-set generation hash
bundle selection probability
probe eligibility and probability
RNG/config snapshot
```

对于无放回 slate，joint probability 必须由按顺序记录的条件概率相乘，而不是只保存每个 member 的边际 inclusion rate。确定性 exploitation item 在给定 snapshot 下概率为 1；未进入随机 support 的 item 概率为 0。不能给 deterministic top-K 事后伪造一个连续概率。

### 8.2 Logging 不等于因果识别

Propensity 的作用是：

- 审计早期 winner 是否获得不成比例 exposure；
- 计算 randomized exploration/probe 的 support 与 effective sample size；
- 在预注册 positivity 条件下形成 selector-policy 的加权描述；
- 复核某个 Skill 是否从未获得可识别机会。

Primary conditional-removal/opportunity credit 仍来自 matched ProbeBlock。`tracer_skillbank_v0` 的核心 regret 是第 7.3 节的 **local same-slot opportunity regret**，不需要 off-policy evaluation。若扩展研究还要估计冻结 selector policy 的整体价值，必须先定义：

```text
H: outcome 前冻结的 request、Bank、eligible pool 与历史摘要
S: ordered retrieval slate
B: candidate generator 给定 (H,S) 后产生的 feasible BundleRevision
mu_R(S|H), mu_B(B|H,S): behavior policy
pi_R(S|H), pi_B(B|H,S): target policy
D: case-disjoint、冻结的 evaluation-context distribution
```

在这个一次决策、冻结 Bank 的支持域内，policy value 才定义为：

\[
V_D(\pi)=\mathbb{E}_{H\sim D,\;S\sim\pi_R,\;B\sim\pi_B}
[U(Z(B,H))]
\]

相对预注册 comparator `π0` 的 policy regret 为 `V_D(π0)-V_D(π)`。`U` 是 outcome 前冻结、只在 hard safety constraints 均满足后使用的 scalar utility；原始 `V/K/U/P/S/G/C/D` 仍分别报告，不能让 scalar 抵消安全回归。这一 estimand 不估计自适应 Bank 的长期 lifetime value，也不等于某个 `ω_{j←i}`。要识别该 frozen-policy estimand，host 必须依次在冻结有限集合上随机化：

```text
exploration slate membership
bundle selection
probe type
drop/swap/pair target
arm execution order
```

每一步都记录真实条件概率与完整 history/policy snapshot。联合 behavior propensity 是这些有序条件概率的乘积。目标总体只包含 `π(a|H)>0 ⇒ μ(a|H)>0` 的 audit-eligible actions；deterministic exploit 和 zero-support candidates只能进入 observational ledger。

未来若使用 clipped IPW 或 doubly robust estimator，必须满足：

1. assignment 真正随机且概率在 outcome 前冻结；
2. treatment/control 有 overlap；
3. propensity 大于预注册下界；
4. 自适应历史进入 conditioning set，并陈述 sequential ignorability 假设；
5. outcome model、cross-fitting 与 clipping 规则预注册；
6. case 是主要 cluster，不能把相关 seeds 当独立样本；
7. 同时报告 clipping rate、最大权重、ESS、阈值敏感性和 unweighted matched estimate；
8. 明确承认 clipping 会引入偏差；所谓 DR 还要求 propensity 或 cross-fitted outcome model至少一项正确，不能称为天然双重稳健。

记录概率本身不足以把 observational outcome 变成 causal credit。

若 retrieval或bundle selection没有真实随机 support，TRACER 仍可报告 local matched opportunity regret，并可作为 TRIAD-compatible 的 exposure/adoption instrumentation layer，但不能声称完成 frozen-policy OPE、policy regret 或长期 selector 改进的因果识别。

### 8.3 Probe debt

`probe_debt` 只表示：

```text
该 compatible Skill 曝光很多，但缺少 execution/intervention support
```

它可以提高 exploration 或 audit priority，不能提高 Skill 的 predicted efficacy，也不能保护一个已被充分证明有害的 Skill无限期留在 active Bank。

### 8.4 Probe priority

采用带正下界的 additive value-of-information priority，避免某个零项让新 Variant 永远得不到 probe：

\[
Priority=
\frac{
w_u\,Uncertainty+w_s\,DecisionSensitivity+w_e\,ExpectedUse+w_d\,NormalizedProbeDebt
}{\max(PredictedAllInCost,c_{min})}
\]

四个输入先映射到 `[0,1]`；`w_*`、`c_min` 与 tie-break outcome 前冻结。新 Variant 的 uncertainty floor 必须大于 0，而已充分判负且不影响决策的 Variant 可以由安全规则排除，不靠 priority 归零。

优先探测：

- exposure 高、execution 低的 compatible unused variant；
- 高频使用但 conditional-removal effect 不确定的 adjunct；
- 即将淘汰或 promotion 的 variant；
- model/runtime 变化后 adoption 失准的旧 Skill；
- 会改变 Composer选择的 opportunity contrast。

不探测：hard incompatible、leaky、sandbox/contract invalid、TEST 条件或预算无法完整覆盖的 block。

### 8.5 Source candidate probabilities

来源方案原始写法给出：

```text
drop probe: 10%
unused swap: 10%
pair probe: 5%
no probe: 75%
```

若把 5% `pair probe` 解释成完整 factorial block，每个 pair unit 需要 3 个增量 executions，则总 multiplier 是：

\[
1+0.10+0.10+3\times0.05=1.35
\]

它与来源同时声明的 `1.25×` 不兼容。`tracer_skillbank_v0` 冻结为数学一致的 25% execution-cap候选：

| Block | Unit sampling rate | 每 unit 增量 executions | 总增量份额 |
|---|---:|---:|---:|
| Removal/replacement pool：adjunct drop **或** root/reference replacement | 10% | 1 | 10% |
| Opportunity pool：same-slot swap；slot-fill 只能占此池且单独记账 | 10% | 1 | 10% |
| Complete pair factorial | 最多 `0.05 / 3`（即 `1⅔%`） | 3 | 最多 5% |
| No probe block | 至少 `78⅓%` | 0 | 0% |

上述三个 pool 对一个 normal unit 互斥。因此“每任务最多一个 shadow”改为“每个 normal unit 最多一个预提交 `ProbeBlock`”；pair block内部允许 3 个增量 arms。Root replacement 不是额外第四个 rate，slot-fill 也不是额外第五个 rate。Revival 只能消费既有 pool 中至多 5% 的 probe executions，不能叠加预算。MVP 默认关闭 pair，将未用的5%预算留空或重新预注册，不能事后转移。若坚持5%完整pair blocks，必须诚实改成1.35×并作为独立预算臂比较。

上述只是 execution-unit 维度；tokens、calls、repairs、provider cost 和 wall time仍须逐维预留并满足相同 incremental cap。

---

## 9. Retrieval 与 Bundle Selection

### 9.1 Hard filter 永远优先

TRACER 复用并加强当前隔离：

```text
task family / objective
information_goal
planner_mode / carrier
worker and execution contract
provenance
agent range / task features
security and budget class
materializer support
```

Embedding 或 LLM semantic similarity只能是次级提示，不能绕过 executable compatibility。

### 9.2 Variant retrieval score

Retrieval 发生在 Bundle 形成之前，不能直接使用任意 `τ_i(B,x)` 或 `ω_{j←i}(B,x)`。先定义有限、版本化的 `RetrievalContextKey`：

```text
hard namespace
slot kind
root/structure-family bin（root 候选使用 canonical-incumbent bin）
task/model/agent/budget bins
reference-background policy version
```

每条 local effect 同时保存精确 `background_signature`。只有以下 evidence 可汇总为 retrieval signal：

1. 与 `RetrievalContextKey` 完全匹配的预注册 reference background；
2. 同一有限 background bin 内、保留异质性和 local support 的预注册分层 shrinkage；
3. 使用 case-disjoint `ATTRIB_DEV` 选择、随后冻结的 cross-background predictor，并显式计入开发误差；`ATTRIB_VAL` 绝不能用于选择或修改 predictor。

不同 root、伙伴、slot 或 budget 下的 conditional effects 不能直接平均成全局 Variant 分数。没有合格背景 evidence 时，该项为 unknown，只能依赖 uncertainty/probe-debt exploration，不能填零。

对通过 hard filters 的 variant，可以使用：

\[
R(v\mid k)=LCB_{reference\ removal}(v\mid k)
+\beta_o UCB_{opportunity}(v\mid k)
+\beta_a AdoptionSupport(v\mid k)
+\beta_d ProbeDebt(v)
+\beta_n NicheRarity(v)
-\beta_r Risk(v)
-\beta_h Concentration(v)
-\beta_c Cost(v)
\]

解释边界：

- `LCB_reference removal` 只服务当前 retrieval context/reference-background 中已有 matched support 的 exploitation；
- `UCB_opportunity` 只给尚不确定但有正可能的 variant 探索机会；
- adoption component 不等于 efficacy；
- probe debt 与 niche rarity 是 exploration terms；
- hard metric regression 不能被 scalar score 抵消。

### 9.3 Logged slate

来源候选为 8 个 variants：6 exploit + 2 explore。探索池必须有显式分布，例如对 probe debt、niche rarity 和 opportunity uncertainty 的 softmax；所有 eligible candidates、probabilities 和 exclusions 在 outcome 前持久化。

一个 Skill 没进入 slate时只能解释为 retrieval decision。不能根据它未被执行推断其好坏。

### 9.4 Deterministic Composer + randomized selector

Composer 使用 versioned deterministic beam/enumeration构造候选 bundle，再从完整 safe set 中选择。来源候选：beam width ≤16，90% 最高分、10% 从其余 safe bundles 随机化。

必须区分：

```text
candidate generation probability
bundle selection probability conditional on candidate set
member inclusion probability
```

如果 candidate generator 是不可复核的 LLM，则只能记录 observed candidate set，不能声称已知所有 bundle 的 selection propensity。

### 9.5 Bundle score

安全候选可按下式排序：

\[
Score(B)=
\sum_{i\in B}LCB(\tau_i)
+\sum_{i<j}SupportedLCB(\gamma_{ij})
-Risk(B)-Cost(B)
+VOI(B)-Concentration(B)
\]

未观测 pair 不默认为正 synergy。Exploit 使用零或轻微负先验；Explore 可以使用 uncertainty bonus。没有完整 factorial support 的 `descriptive_pair_drop` 不能进入 interaction sum。

每个 `τ_i` 必须与候选 Bundle 的精确 `background_signature` 匹配。若使用第 9.2 节的分层或 cross-background 预测，prediction uncertainty 必须计入 LCB；没有可验证映射的 evidence 视为 unknown。Retrieval prior 只能帮助缩小候选集，不能在 composition 阶段冒充该具体 Bundle 已经被证明有效。

---

## 10. Carrier-specific 合同

### 10.1 共通原则

TRACER 跨 carrier 共享 Family/Variant/Event/Ledger 生命周期，但不共享一个 untyped executable payload。每种 carrier 必须单独实现：

```text
hook declaration
binder/materializer
reverse trace
static validator
runtime verifier
neutral/replacement comparator
```

没有这些能力的对象保持 atomic root。

### 10.2 Graph

Root variant 保存完整 Graph payload。Adjunct 只能修改声明的 typed hook，例如：

- receiver instruction；
- provenance/merge policy；
- send mode；
- submission guard；
- fan-in/message bound。

不能在 runtime 悄悄增加未验证 edges。Materialize 后重新检查 agent IDs、self-loop、duplicate edge、step/message/fan-in budget、temporal reachability 和 goal coverage。

### 10.3 PhaseProgram

推荐作为第一种 bundle carrier，因为 DSL 与 deterministic compiler 已存在。可声明的 hooks包括：

- phase instruction；
- send mode；
- state retention；
- submit condition；
- gather/broadcast parameter；
- safety/budget guard。

每个 bundle 都重新产生完整 `phase_program_v1` 和 compiled protocol，不能执行零散 phase 文本。

### 10.4 Python

Python 禁止把 sidecar 文本直接拼进 source。只有两种合法路径：

1. 已验证 Python variant明确声明支持该 policy/hook revision；
2. 先用当前 exact parent + one EVOLVE block mutation 生成新的完整 variant，再独立验证与 gate。

每个 Python executable identity至少绑定 source SHA、parent SHA、block ID、diff SHA、AST policy、worker/execution contract 和 scaffold version。一个 TRACER bundle 的 Python MVP 最多一个 executable patch。

当前单次 `apply_python_mutation_patch` 只替换一个既存 block，但一个 repair run可能连续应用多个 patches，最终甚至触及不同 blocks。TRACER 若把 Python 变化当成单 facet intervention，必须在最终 parent→child diff和完整 patch sequence上强制“恰好一个既存 block 改变”；branch 名称或单次 helper 合法性都不足以证明原子变化。

### 10.5 Reasoning policy

Reasoning policy必须是 typed、可 materialize、可 host 验证的字段，例如 merge、send、submit、provenance。相同 executable structure、不同 reasoning hash保留不同 variants。

如果 policy 只有不可观测自然语言效果，它仍可参与完整 variant comparison，但不能成为独立 adoption/drop facet。

### 10.6 Safety guard 与 budget adapter

Hard sandbox/leak/contract guards属于系统边界，不是可随机移除的 Skill。只有确实 materialize 到 runtime 行为、且移除仍安全合法的 guard/adapter，才能作为 bundle member 估计 efficacy。

---

## 11. Credit 状态与层级更新

### 11.1 状态机

Exposure、runtime realization 与 probe maturity 是三个正交轴，不能压成一条要求 `followed` 后才能 `PROBED` 的线性状态机：

```text
Exposure axis:
  UNSEEN → ELIGIBLE_UNRETRIEVED → EXPOSED → SELECTED

Realization axis:
  NOT_SELECTED | SELECTED_UNACTIVATED | ACTIVATED_UNFOLLOWED |
  FOLLOWED | FOLLOWING_UNVERIFIABLE

Probe-maturity axis:
  UNPROBED → PROBED_INSUFFICIENT →
  CONFLICTED | SUPPORTED_POSITIVE | SUPPORTED_NEGATIVE | SUPPORTED_NULL
```

完整 matched assignment 无论 treatment arm 是否 activated/followed，都更新 ITT ProbeBlock；这些失败正是部署政策的一部分。`UNIDENTIFIED` 是 `UNPROBED`/`PROBED_INSUFFICIENT` 的用户级别总称，不是第四套 enum。`transfer_probation` 属于 lifecycle eligibility，而不是 credit maturity。以上三轴也都不同于 active/archive 生命周期。

### 11.2 条件性 posterior

每个 variant/context 至少保存：

- exposure、selection、activation、following、probe counts；
- distinct cases 与 nested seeds；
- conditional-removal/opportunity 分量均值和区间；
- hard regression counts；
- support/overlap/propensity summaries；
- sparse positive/negative pair refs；
- failure stage 与 answer-free evidence refs；
- probe debt 和 last calibrated model/runtime。

### 11.3 Hierarchical shrinkage

低样本 variant 可向经过验证的 family prior收缩，但必须保留：

```text
family prior
variant-local observations
variant residual
transfer weight
```

跨 mode、model 或 worker contract 的 transfer weight 默认很小，目标 context 没有 paired support 时状态为 `transfer_probation`。

Family prior observations不得增加目标 variant 的 local `n`、local ESS 或 distinct-case count，也不能缩窄本地区间到仿佛已经执行过的程度。报告必须并列给出 prior contribution 与 local support，防止 confidence laundering。

### 11.4 自动负面动作的最低支持

来源方案建议的候选阈值为：minimum usable propensity `0.05`、weight clip `10`、ESS ≥8、distinct cases ≥3。它们只能作为 pilot 参数。

在未达到预注册 support 前：

- 可以提高 probe priority；
- 可以暂时移出 exploitation；
- 不能自动删除 Family；
- 不能把 `EXPOSED_UNPROBED` 改成 harmful；
- 不能用 family prior掩盖本地 negative validity evidence。

---

## 12. Quality-Diversity Archive 与 Revival

### 12.1 QD 的角色

QD、capacity 和 anti-monopoly 不是 TRACER 的独立 novelty。它们用于确保 exposure/probe机制不会再次只服务一个早期 winner。

Behavior descriptors 必须来自 schema、compiled artifact 或 trace，例如：

```text
task/goal/mode/contract
agent-count bucket
communication depth / density / fan-in
coverage shape
finite reasoning-policy class
cost and robustness bins
model adoption bucket
```

禁止用 LLM 自报的“creative”“robust”“novel”划分 niche。

Niche 维度必须来自**有限、版本化的 bins**。`reasoning_policy_hash`、revision hash、任意新标签或 raw continuous value只用于 identity，不得直接生成新 niche；连续量先进入预注册区间。否则 per-niche cap 仍允许无限创建 cells。

### 12.2 来源候选容量

```text
active families <= 128
active variant revisions <= 256
deployable bundle revisions <= 256
active effect-context posteriors <= 2048
global sparse pair edges <= 2048 and <= 8 per variant
per niche <= 4
archive metadata <= 512
active payload bytes <= 256 MiB
archive metadata bytes <= 64 MiB
retrieval-visible Skill context <= 1,500 tokens per request
```

每个 Family 默认最多 8 个 active revisions；超过 global/context cap 时先压缩或 archive，不能靠创建更多 context keys 规避上限。Raw immutable experiment ledger 可存放在 Bank 外部的有保留期审计存储中，但 prompt-visible/active Bank 必须受上述条数、bytes 和 context-token 三重上限控制。每 niche 可保留 quality、cost、robustness 和 exploration elite。所有数字应作为预注册消融参数，不是方法恒定真理。

### 12.3 四种 archive 状态

| 状态 | 含义 | 默认检索行为 |
|---|---|---|
| `probation` | hard-valid，但尚未独立 gate 或随某个 rejected Bank snapshot 未部署 | 仅 TRAIN exploration；不能作 deployed parent |
| `active` | 通过 gate，可参与 exploitation/exploration | 允许 |
| `archive` | 当前 dominated、stale 或低 support，但保留 lineage/evidence | 仅 revival |
| `quarantine` | invalid、leaky、sandbox 或 contract mismatch | 禁止作为 Skill；只保留安全审计记录 |

Bank-level gate 比较的是完整 selector/candidate snapshot，拒绝不能自动归因给某一个 Variant。一个 hard-valid Variant 随 candidate Bank 被拒时保留为 `probation` 或 archive evidence，同时保存 rejected-snapshot ref；它不得部署或成为 parent，但也不因此获得 single-Variant negative credit。Quarantine outcome 只有转换为 answer-free failure summary 后才能影响未来 proposal，不能把原 artifact 注入 prompt。

### 12.4 Eviction

顺序建议：

1. invalid/deprecated；
2. exact duplicate revision；
3. 充分 support 下同 niche Pareto-dominated；
4. 高 algorithm/adoption failure 且无反证；
5. 长期 stale、无独特 niche、无正 opportunity；
6. 超出 cell capacity 的最低 safe LCB。

`probe debt` 高但未探测的 variant 应获得短保护期，不能仅因低使用率淘汰。

### 12.5 Revival

触发条件：model/provider version、worker contract、task distribution 或 active Bank performance 发生预注册变化；或 archive variant 在相邻 context 有正 opportunity evidence。

Revival 只获得 exploration/probe机会，不能直接恢复 active。来源方案建议 revival 不超过 probe budget 的 5%。

---

## 13. Failure、Split、泄漏与预算

### 13.1 Failure 语义

TRACER 继承 TRIAD 与当前 QueenBee 的 honesty boundary：

| 状态 | 是否更新 efficacy | 处理 |
|---|---|---|
| Proposal failure | 否 | 保留 proposer/host 成本和原因 |
| Unsupported/nonseparable intervention | 否 | compatibility evidence，不补零 |
| Legal static algorithm failure | 是，作为真实负 outcome | canonical treatment identity成立且安全 guard 通过；零质量，保留成本 |
| Runtime algorithm failure | 是，作为真实负 outcome | 零质量、保留成本、answer-free cluster |
| Infrastructure failure | 否 | paired block incomplete；不只保留成功 arm |
| Harness failure | 否 | 作废 replicate 并调查 |

Hard namespace、forbidden API、sandbox、leak 或 contract mismatch 永不为 exploration 放宽。

**`CURRENT_CODE_FACT`**：当前 infrastructure run不参与质量评分，但 failure record 可能先被记录并进入后续 cluster/context。TRACER 必须在 raw ledger保留 `failure_class`，只让 algorithm failure进入 efficacy和negative mutation evidence；infrastructure只标记 block incomplete，不能成为有害 Skill 提示。

### 13.2 Split 合同

为与 PIF/TRIAD 公平比较，采用相同状态机：

| Split | 用途 | 写回 |
|---|---|---|
| `TRAIN_UPDATE` | retrieval、selection、probe、posterior、mutation、archive | 可以 |
| `TRAIN_SHADOW` | attribution pipeline诊断 | 完全不回写，不支持 confirmatory claim |
| `ATTRIB_DEV` | estimator、background bins、predictor 与 adoption-bottleneck选择 | 可冻结方法配置；不得把 outcomes写成 Bank efficacy evidence |
| `ATTRIB_VAL` | 预冻结、case-disjoint matched probes；验证 effect sign/rank/coverage | 完全不回写；是 attribution confirmatory claim 的唯一来源 |
| `GATE_DEV` | 重复 candidate snapshot gate | 不回写 causal/adoption ledger |
| `FINAL_VAL` | TEST 前 one-shot snapshot admission | 不回写；失败部署 incumbent并留在分母 |
| `TEST` | end-to-end frozen comparison | 完全只读 |

Case 跨 split 不重叠；同 case 的不同 seeds 不能分到不同 split。`ATTRIB_DEV` 是开发 split，任何基于它选择的 estimator、background bins、predictor、阈值或 adoption bottleneck 都必须形成版本化配置。`ATTRIB_VAL` 的 comparator、effect predictor、background bins、thresholds 与 probe manifest在观察其 outcome 前冻结；它只评估从 `TRAIN_UPDATE` 学到的信用，不重新拟合 posterior。更严格地说，`ATTRIB_VAL` 结果必须在 candidate Bank、GATE_DEV、FINAL_VAL 与最终 deployed snapshot 全部冻结之后才解封；它只能接受/否证研究主张，不能启停 phase、换 candidate、重排 archive 或修改 TEST policy。`GATE_DEV`、`FINAL_VAL` 与 `TEST` 不得替代 `ATTRIB_VAL`，也不执行 attribution probes。

这套七阶段 split 是 **`TRACER_PROPOSAL`**，不是当前 `evolve` 的现成语义：当前 VAL failure/insight 可写回 candidate 后再用于 gate，singleton bucket 还可能在内部 split中同时进入 TRAIN/VAL。正式 TRACER 必须使用显式 case-disjoint manifests 和不可写的 ATTRIB_VAL/GATE_DEV/FINAL_VAL reports，不能把当前 VAL 路径直接改名为 held-out。

### 13.3 TEST immutability

TEST 前后冻结并核对：

- Bank/family/variant/bundle catalogs；
- exposure、selection、adoption、probe-debt counters；
- credit/failure ledger；
- selector/QD/revival state；
- mutation parent registry；
- prompt/cache 中的持久化状态。

TEST 无 exploration、无 probe、无 posterior/failure/archive 更新。当前仓库的 TEST control flow 没有明显训练写回路径，但也没有覆盖所有上述状态的 Frozen facade；这是提案而非现有事实。

### 13.4 泄漏边界

禁止持久化：

```text
answer / final_answer / worker raw answer
ground_truth / expected_output / reference solution
private/local/raw task prompt
TEST score feedback or full TEST trace
benchmark shard or reversible oracle encoding
```

允许：case hash、task bucket、seed、artifact/revision hashes、event flags、`V/K/U/P/S/G/C/D`、coverage/submission presence、answer-free failure signature、model/runtime config hash。

`case_id` 只用于 matching/audit，不能成为 planner retrieval feature。

### 13.5 统一预算

所有方法使用同一六维 `BudgetVector`：

```text
execution_units
tokens
model_calls
repair_calls
provider_cost_usd
wall_time_seconds
```

来源 TRACER 候选把平均训练 execution multiplier 限制为 `≤1.25×`。本文只有在第 8.5 节修正后的 `10% removal/replacement + 10% opportunity + ≤0.05/3 complete pair blocks` 调度下保留该上限；原始5% pair-block解释会变成1.35×。25%应记录为 **incremental probe cap hypothesis**，不能在 primary comparison 中免费增加预算。

正式比较同时报告：

1. **Primary：equal all-in**。Current/PIF/TRIAD/TRACER 的全部 pre-TEST research/search evaluation 使用相同六维总预算；TRACER 用一部分 normal runs 换 probes，ATTRIB_DEV、ATTRIB_VAL、失败 arms 与 repairs 也计入方法总成本，不能当作免费评估。
2. **Diagnostic：equal normal work**。允许 TRACER 额外 probes，但六维每项 incremental overhead ≤25%，用于测量绝对 attribution feasibility。
3. **Sensitivity：10% vs 25% cap**。检验核心结论是否只在高 probe 预算下成立。

任何 ProbeBlock 在执行前完整预留 treatment/comparator 的 all-in 与 incremental cost；预算不足时不启动，不能产生 half-block evidence。

---

## 14. 与 Current、PIF、TRIAD 和 whole-program 方法的比较

### 14.1 术语映射

| 方法 | 可执行身份 | 组合/部署身份 | 主要信用问题 |
|---|---|---|---|
| Current QueenBee | `SkillCard` | 单卡/完整 candidate Bank | whole-card outcome 与 association |
| PIF-Bank | Factor revision | `SkillComposition` | 单 factor `from→to` replacement |
| TRIAD-SkillBank | Base + typed `SkillAtomRevision` | bounded ordered `PortfolioRevision` | background-conditional removal 与 sparse factorial |
| TRACER-SkillBank | `SkillVariantRevision`；Family仅为 prior | root + typed adjunct `BundleRevision` | two-stage exposure/adoption 与 retrieved-unused opportunity regret |

`SkillVariantRevision` 不自动等于 TRIAD `SkillAtomRevision`。若未来实现共享同一 deterministic binder substrate，应复用 identity/ledger；若一个 TRACER root 是完整 atomic Skill，它就不是可移除 Atom。

### 14.2 主比较矩阵

| 维度 | Current | PIF | TRIAD | TRACER |
|---|---|---|---|---|
| 搜索单位 | 完整 Skill/candidate | typed factor replacement | typed Atom portfolio | Family-filtered variant bundle |
| Selection stages | 单次 retrieval/planning | composition retrieval | portfolio selection | logged retrieval slate + bundle selection |
| Exposure ledger | 无通用机制 | 可选 | frozen slate/portfolio event | 核心对象，分 retrieval 与 composition |
| Adoption ledger | 无通用机制 | 非核心 | materialization contract | selected→activated→followed 为核心 |
| Local credit | whole ablation | exact one-factor swap | matched removal | matched drop/root replacement |
| Retrieved-unused | 未识别 | 通常非核心 | opportunity swap | 核心 opportunity-regret estimand |
| Pair effect | 无 | selected executable×policy 2×2 | sparse four-arm factorial | 可选 complete-block factorial |
| Family/variant | 无 | factor/context hierarchy | Atom/context hierarchy | semantic Family prior + mode-specific variant residual |
| Diversity | Top-N/dedupe | factor niches | QD portfolio archive | QD + exposure debt + model-drift revival |
| Cost | 低 | 中 | 中高，10%候选 cap | 高，来源候选25% cap |
| 最强适用场景 | 简单稳定 Bank | factor identity清楚 | 固定 Base 的可分解 portfolio | two-stage missed selection 与弱模型 adoption |

### 14.3 TRACER 相对 TRIAD 的不可约增量

二者重叠很大：typed composition、matched removal、opportunity、bounded QD、failure/budget/split纪律都可共享。TRACER 不应复制一套平行 materializer/ledger。

工程上，`BundleRevision` 可以映射为 TRIAD 的 `PortfolioRevision`：TRACER root对应固定 executable/base binding，adjuncts对应 typed Atom bindings；TRACER 真正新增的是 Family/Variant prior refs、retrieval-stage snapshot、composition-stage snapshot、activation/following events、probe debt和revival state。若两套实现并存，应共享 immutable artifact、materializer和raw ProbeBlock，而不是维护两份事实来源。

TRACER 真正额外关注：

1. **两阶段 decision process**：retrieval exposure 与 bundle inclusion 分开；
2. **Adoption funnel**：selected、activated、followed 三类运行事实与 matched ITT benefit 分账；
3. **Opportunity regret 作为主目标**：系统是否错过 slate 中的更优 compatible variant；
4. **Family/variant/model hierarchy**：设计 recipe、具体 realization 与弱模型可用性分账；
5. **Revival under drift**：archive variant 在 model/task 变化后有预算地重新校准。

TRIAD 的优势是 deterministic Atom decomposition 与 complete matched attribution更清楚，预算更保守。如果主要问题是“哪个局部 factor 有用”，优先 TRIAD/PIF；只有证据表明 retrieval/composer/adoption bottleneck显著时，TRACER 的额外复杂度才有理由。

如果 retrieval、bundle和probe assignment没有满足正支持与顺序随机化，TRACER 的身份必须降级为 **“TRIAD-compatible retrieval/adoption instrumentation layer”**；此时可以报告 exposure funnel、matched local probes和调度诊断，但不能声称已学习 policy-conditioned regret 或完成 OPE。

### 14.4 退化条件

TRACER 应主动退化为更简单方法：

- Bundle 几乎总是 singleton → PIF-like root replacement；
- Adjunct 无 deterministic hooks → whole-Skill current/PIF；
- retrieved-unused swap几乎没有正 signal → 删除 opportunity layer；
- selected→activated→followed 接近 1 且跨模型稳定 → 删除 adoption calibration；
- pair blocks预算不足 → 不维护 interaction；
- Family membership无法客观验证 → 只保留 variant，不做 cross-mode prior；
- equal-all-in 下不优于 PIF/TRIAD → 不采用 TRACER。

### 14.5 与 AFlow、ADAS、AlphaEvolve/DGM

| 方法 | 主要对象 | 与 TRACER 的区别 |
|---|---|---|
| AFlow | 完整 workflow code 与 parent experience | TRACER 维护 persistent variant exposure/adoption，不搜索一棵完整 workflow tree |
| ADAS | 完整 Agent Python code archive | TRACER 不让 meta-agent全量重写并共享 whole-agent fitness |
| AlphaEvolve | program population/database | TRACER 的 credit 对象是 typed reusable variant/slot/bundle；官方完整 runner未公开 |
| DGM | agent code lineage 与 stepping stones | TRACER archive有界，并审计 unused opportunity；不把完整 self-modifying agent作为 Skill |

**`SOURCE_CONVERSATION_CLAIM`**：CTA、SkillC、CCPO、SHARP、HiveMind、Generative Skill Composition、SkillBrew、SkillOps、SRA/R3 等近邻已分别覆盖 paired audit、agent/node credit、skill composition、Bank curation、typed contracts 或 incorporation。TRACER 的窄增量只能表述为这些机制在 QueenBee typed contracts 下围绕 two-stage exposure/adoption/opportunity 的系统化组合，不能宣称每个组件首次出现。

---

## 15. 高层算法

以下是方法顺序，不是实现代码：

```text
load current QueenBee Bank as immutable variant revisions
mark legacy outcomes observational_only

for each TRAIN_UPDATE evaluation unit:
    hard-filter mode/goal/contract-compatible variants
    build and freeze a logged exploit+explore retrieval slate
    deterministically generate safe root+adjunct bundle candidates
    freeze candidate set, exclusions, selection probabilities and RNG
    select one BundleRevision
    materialize a complete existing SkillCard/artifact
    record selected, activated and host-verified followed events

    if a complete probe was preselected and six-dimensionally reserved:
        execute matched drop OR same-slot opportunity arms
        optionally execute a full four-arm pair block when formal budget permits
    else:
        execute the selected normal bundle

seal raw observations
derive removal/opportunity/interaction CreditViews without duplicating samples
aggregate normal-policy AdoptionViews from all MechanismEvents
update TRAIN-only context estimates, probe debt and answer-free failures

use ATTRIB_DEV only to select estimator/background/adoption-bottleneck configuration
freeze the learned credit predictor, thresholds and background policy

propose one evidence-targeted variant change or a fresh compatible variant
build a capacity-bounded QD candidate snapshot
gate candidate vs incumbent on frozen GATE_DEV units
run one-shot FINAL_VAL; failed replicates deploy incumbent and remain in denominator
freeze the final deployed snapshot and TEST policy
only now unseal and evaluate case-disjoint ATTRIB_VAL ProbeBlocks; report without adaptation
continue to TEST regardless of ATTRIB_VAL pass/fail
run TEST through a frozen facade and assert every persistent-state hash unchanged
```

禁止三条捷径：

1. 给所有 retrieved 或 selected members共享同一个 outcome；
2. 用一个 pair-drop shadow 声称 pair interaction；
3. 把 logged probability 当成 matched intervention 的替代品。

---

## 16. Default-off 分阶段落地

### Phase 0：Exposure shadow logging

- 只记录 eligible、retrieved、selected 与 exclusion reason；
- 不改变当前 retrieval/selection；
- 不创建 efficacy credit；
- 加 TEST all-state hash 和 leak canaries。

**完成条件**：feature off 时当前行为不变，日志不含答案/私有 prompt。

### Phase 1：One-root + one typed adjunct

- 推荐 PhaseProgram；
- 只支持一个 reasoning/guard/budget hook；
- 建立 Variant、HookSlot、Bundle identity；
- materializer/reverse trace/verifier 全由 host 控制。

**完成条件**：selected/activated/followed 可以机械复核。

### Phase 2：Matched drop

- 在小比例 TRAIN_UPDATE units 中预先调度一个 adjunct drop；
- shadow estimates 不影响 deployment；
- 用 TRAIN_SHADOW 检查 pipeline 与 manifest，ATTRIB_DEV 选择 predictor；只有在 deployed snapshot冻结后解封的 case-disjoint ATTRIB_VAL 可支持 held-out sign/rank claim；
- unsupported removal 不补零。

**完成条件**：complete-block rate、effect direction、failure 和六维成本可审计。

### Phase 3：Same-slot opportunity swap

- 从 slate 中选择 retrieved-unused compatible variant；
- 与当前同 slot member做真实 swap；
- opportunity evidence先 shadow 使用；
- 检查是否能预测后续 normal selection收益。

这是 TRACER 的核心 novelty test。若 drop+swap 不优于 drop-only，停止扩展。

### Phase 4：Randomized two-stage selector

- outcome 前冻结 retrieval与bundle候选概率；
- 开启 probe debt、positivity/ESS audit；
- 仍以 matched estimate为 primary；
- 对照 no-randomization 与 logging-only。

### Phase 5：Family/model hierarchy + QD/revival

- 同 topology different policy identity；
- Family prior与variant residual；
- model-conditioned adoption；
- bounded behavior cells、archive 与 drift-triggered revival。

### Phase 6：Sparse complete pair blocks

- 只对高频、高不确定且会改变 bundle ranking 的 pair；
- 必须完整四臂与独立预算；
- power 不足时关闭，不输出 interaction claim。

### 16.1 建议模块边界

| 位置 | 职责 |
|---|---|
| 新增 `tracer_artifacts.py` | Family/Variant/Hook/Bundle immutable identity |
| 新增 `tracer_events.py` | retrieval/composition/adoption event log 与全事件 AdoptionView |
| 新增 `tracer_probes.py` | pre-outcome manifests、matched block scheduling |
| 新增 `tracer_credit.py` | raw block → removal/opportunity/pair matched efficacy views |
| 新增 `tracer_archive.py` | context estimates、QD、capacity、revival |
| `schemas.py` | 只增加共享概念 shape，不改变旧 payload union |
| `skill_bank.py` | default-off logged retrieval 与 reasoning-aware variant adapter |
| `planner.py` | 新 bundle planner surface；legacy `operator_compose` 保持不变 |
| Graph/Phase/Python modules | carrier-specific hooks/materializers，不共用 untyped source |
| `masbench/evolve.py` | probe schedule、mutation target、candidate snapshot |
| `engine.py` | materialized variant refs 与 host-verifiable events |
| `failures.py` | answer-free family/variant/bundle/probe refs |
| `gates.py` | 保留 dense语义，增加 case-clustered method comparison wrapper |
| `verify_beats_baselines.py` | seven-stage case-disjoint split、all-state TEST hashes、equal-budget reports |

Feature flags 建议：

```text
tracer_enabled = false
tracer_exposure_logging
tracer_bundle_compose
tracer_drop_probe
tracer_opportunity_probe
tracer_randomized_selector
tracer_family_prior
tracer_model_adoption
tracer_qd_revival
tracer_pair_factorial
tracer_test_frozen_assert
```

---

## 17. 实验、消融与接受标准

### 17.1 研究问题

1. Exposure/adoption ladder 是否揭示 current outcome 无法区分的 bottleneck？
2. Used-variant drop estimate 能否预测 held-out matched effect？
3. Retrieved-unused opportunity estimate 能否改善下一轮 bundle selection？
4. Family/model-conditioned evidence 是否减少跨 mode/model 负迁移？
5. Probe debt、QD 与 revival 能否降低垄断而不损质量？
6. Equal all-in budget 下 full TRACER 是否值得超过 PIF/TRIAD 的复杂度？

### 17.2 必须分开的主 cell

```text
Level II × sink
Level II × all_agents
Level III × sink
Level III × all_agents
```

正式实验覆盖 agent counts `2/5/10`。所有方法使用相同 case、task seed、model、worker prompts、timeout、validators、failure semantics、scorer 和六维 all-in budget。

### 17.3 MVP

MVP 只验证 feasibility 与核心 opportunity hypothesis：

1. current QueenBee；
2. exposure logging only；
3. drop-only；
4. drop + same-slot opportunity；
5. 可选 TRIAD/PIF-compatible matched baseline。

MVP 先使用 PhaseProgram one-root + one-adjunct，不做 Family cross-mode transfer、不做 pair interaction、不让 credit 影响部署。

至少检查：

- typed bundle materialization/activation/following rate；
- complete matched-block rate；
- opportunity positive rate 与 next-run prediction；
- conditional-removal effect sign stability；
- algorithm/infrastructure/harness failure；
- 六维 10%/25% probe sensitivity；
- TEST frozen/leakage canaries。

### 17.4 正式比较臂

1. current evolved QueenBee；
2. PIF-style exact factor replacement；
3. TRIAD full portfolio attribution；
4. TRACER logging-only；
5. TRACER drop-only；
6. TRACER drop+opportunity；
7. full TRACER；
8. QD-only/randomized-only controls；
9. 预算允许时 AFlow-style/ADAS-style whole-candidate controls，明确非官方复现。

Pilot 每个方法至少 3 个独立 search replicates；正式 method claim 固定为 5 个独立 search replicates。这里的 replicate 是从初始 Bank 开始的完整独立 search trajectory，不是同一 case 的 task seed、worker seed 或 provider retry；这些 execution seeds 必须嵌套在 replicate×case 内并在方法间配对。不同方法可产生不同 search trajectory，但必须共享初始 Bank、proposer、evaluation units、RNG policy family 和 all-in budget。

### 17.5 预注册的主分析合同

默认 confirmatory contract 冻结如下；若研究者要改 primary endpoint，必须在任何 `ATTRIB_VAL`、`FINAL_VAL` 或 `TEST` outcome 可见前发布新版本，而不是在结果后从 `S`/`stage` 中挑赢家。

1. **Primary comparator**：current evolved QueenBee。PIF/TRIAD 不用于选择 primary endpoint。
2. **Primary endpoint**：frozen TEST `stage_score` macro mean。先在每个 search replicate 内对 case 等权平均；execution seeds留在 case cluster内；agent counts `2/5/10` 在 cell 内各占 `1/3`；四个 `Level×goal` cells 各占 `1/4`；多 task families 再等权 macro-average。
3. **Primary contrast**：full TRACER minus current，要求 point delta `≥+0.03` 且 paired two-level bootstrap 95% CI 下界 `>0`。外层重采样独立 search replicates，内层成对重采样 case；同 case 的全部 task/worker seeds作为一个 cluster。5 个 replicates只是最低门槛；若区间仍过宽则结论是证据不足，而不是改用 seeds 作为独立样本。
4. **Protected secondary**：strict `S` 的 macro delta 非劣 margin为 `-0.01`；若要声称 `S` 改善，还要求 delta `≥+0.03` 且 multiplicity-adjusted CI 下界 `>0`。
5. **Cell reporting**：四个主 cells 全部报告，不允许只满足其中三个。`V/min K/U/P/algorithm failure` 继续逐 cell 执行预注册 non-regression rule；不能由 macro gain 抵消。
6. **Multiplicity**：唯一 primary contrast不做事后 multiplicity 调整；四个 cell effects、`S` 改善、cost/diversity和各消融均为 secondary family，使用 Holm correction并同时给 raw/adjusted intervals。
7. **PIF/TRIAD comparator**：在 GATE_DEV 上预先选定二者中较强者，TEST 不重新选择。Full TRACER 对该 comparator 的 macro `stage_score` 与 `S` 非劣 margin均为 `-0.01`，95% CI 下界必须高于 margin。
8. **Missing/failed replicate**：按第 17.10 节部署 incumbent，仍留在分母；不换 seed、不删 trajectory。

### 17.6 必报指标

质量与成本：

```text
V, mean/min K, U, P, S, stage_score, C, D
algorithm / infrastructure / harness failure
execution units, tokens, model calls, repair calls, provider cost, wall time
```

Attribution：conditional-removal/opportunity held-out sign accuracy、Spearman correlation、CI/coverage、complete blocks、distinct cases、ESS、nonseparable rate、pair sign stability。

Adoption：selected→activated、activated→followed，按 model/mode/contract 分层；matched ITT positive/null/negative support 作为 Attribution 指标单列，禁止报告 `followed→beneficial` 的 post-treatment 条件比例作为 efficacy。

Selection：eligible/retrieved/selected coverage、opportunity capture rate、missed-positive rate、probe debt distribution。

Bank：probation/active/archive/quarantine count、niche coverage、top-1 use share、HHI、effective used variants、turnover/revival success、bytes/context footprint。

逐 Agent：submission presence、exact、partial、coverage、submitted round、failure reason。

### 17.7 必要消融

| 消融 | 回答的问题 |
|---|---|
| full-no-opportunity | 保留 randomization、Family、QD、adoption等全部机制，只关闭 opportunity credit/selection；原 10% pool按 outcome 前规则换为等成本 normal work |
| full-no-adoption-calibration | 仍记录 events，但 ranking/mutation/revival不读取 AdoptionView；其余机制与预算相同 |
| no randomization | propensity/support 是否改善 evidence coverage |
| no probe debt | 长期未测 variants 是否继续被垄断 |
| no family prior | 跨 realization prior 是否帮助或造成负迁移 |
| no QD/revival | archive diversity与drift recalibration 是否必要 |
| drop-only | opportunity 是否比 ordinary ablation多提供价值 |
| logging-only | 仅记录 exposure 是否已经足够 |
| 10% vs 25% cap | 结论是否依赖高 probe budget |
| pair off vs complete factorial | pair layer 是否值得额外成本 |
| no reasoning hash | same topology policy variants 是否被错误合并 |

### 17.8 Attribution 升级标准

只有同时满足以下条件，才允许说“TRACER credit 有预测价值”：

1. 证据只来自 case-disjoint `ATTRIB_VAL`，每类声称至少 32 个 distinct cases、四个主 cell 每个至少 8 个，propensity-weighted claim 的 ESS ≥20；
2. conditional-removal/opportunity effect sign accuracy point estimate ≥65%，case-clustered bootstrap 95% CI 下界 >50%；
3. predicted effect 与 observed delta 的 Spearman `ρ ≥ 0.30`，case-clustered 95% CI 下界 >0；
4. drop+opportunity 相对 drop-only 降低后续预冻结 selection 的 matched opportunity regret，paired case-clustered 95% CI 下界 >0；
5. hard metric regression prediction不被 scalar平均掩盖；
6. 结果优于 permutation、whole-skill mean 和 observational co-use baseline。

如果只满足 training correlation，不得说 credit 有效。

### 17.9 End-to-end 方法升级标准

TRACER 被称为“有效方法”至少需要：

1. case-disjoint TRAIN_UPDATE/TRAIN_SHADOW/ATTRIB_DEV/ATTRIB_VAL/GATE_DEV/FINAL_VAL/TEST；
2. 至少 3 个 task families；每个适用 family 报告全部四个 Level×goal cells，agent counts含2/5/10；
3. 5 个独立 search replicates，task/worker seeds按第17.5节嵌套；
4. 满足第17.5节唯一 primary endpoint：macro `stage_score +0.03 absolute` 且 paired two-level bootstrap 95% CI 下界 `>0`；
5. strict `S` 与 PIF/TRIAD 非劣、cell-level safety、multiplicity均满足第17.5节；
6. algorithm failure、`V`、minimum `K`、`U`、`P` 不回归；
7. full TRACER 对 `full-no-opportunity` 的 equal-all-in macro stage secondary contrast经 Holm correction 后 CI 下界 >0；MVP 另要求 `drop+opportunity` 对 `drop-only` 的受控 contrast同方向，不能用 full 对 logging-only 的混杂差异证明 opportunity；
8. equal all-in 下对 GATE_DEV 预选的 PIF/TRIAD comparator满足 `-0.01` 非劣 margin。若 TRACER 对该 comparator 的 macro stage CI 下界不大于 0，保留其额外复杂度还必须同时满足第17.8节 attribution标准，以及一个预注册 adoption contrast：在 ATTRIB_DEV 上预选 activation 或 following 作为 bottleneck，`full` 对 `full-no-adoption-calibration` 的该 transition macro rate提高至少 5 pp、Holm-adjusted 95% CI 下界 >0，同时 macro stage和`S`的CI下界均高于 `-0.01`；未预选 bottleneck就不能事后援引此例外；
9. diagnostic incremental probe 的六维每项 overhead ≤25%，并报告10% sensitivity；
10. HHI/top-1 share下降时，exact quality退化不超过1 pp；
11. leakage/isolation/harness canaries全部通过；
12. 独立 rerun方向一致。

这些是接受合同，不是预期结果陈述。

### 17.10 FINAL_VAL 失败处理

某 replicate 的 candidate snapshot 若未通过 one-shot FINAL_VAL：

- 部署该 replicate 的 incumbent；
- 标记 `method_failure=True`；
- 继续保留在 TRACER 的 TEST 比较分母；
- 不替换 seed，不只报告成功 trajectory。

---

## 18. 可证伪预测与停止标准

### 18.1 六个可量化预测

1. **Exposure diagnosis**：TRACER 能把未使用 Skill 中的 retrieval miss、selection miss、activation miss 和 following miss稳定分开。
2. **Opportunity prediction**：positive opportunity LCB 能预测后续 normal same-slot swap收益。
3. **Credit fidelity**：conditional-removal/opportunity estimates 比 whole-card mean 和共现 association 更接近独立 matched ablation。
4. **Weak-model calibration**：model-conditioned adoption降低 GPT-4o-mini 上的 selected-but-unfollowed 比例。
5. **Anti-monopoly**：HHI/top-1 share下降、coverage上升，同时 dense quality非劣。
6. **Bank uplift**：equal all-in 下 full TRACER 提升 frozen TEST Bank质量，且收益不是仅由 QD或randomization解释。

### 18.2 最可能的根本失败

1. **Opportunity 稀疏**：Retriever 已经足够好，retrieved-unused swap几乎没有正价值。
2. **Adoption 不可验证**：大多数 reasoning Skill没有 host-observable semantics。
3. **Probe 成本/方差过高**：25%预算仍无法形成稳定 matched support。
4. **Family 负迁移**：抽象 recipe无法可靠对齐 Graph/Phase/Python realizations。
5. **高阶组合主导**：drop和pair无法预测bundle效果。
6. **复杂度不值**：PIF/TRIAD以更低成本达到相同或更好结果。

### 18.3 停止条件

| 现象 | 结论/动作 |
|---|---|
| selected→activated 或 activated→followed 长期低于预注册 floor | 修 materializer/model contract；暂停 adoption-mediated/per-protocol 主张，但 ITT 仍包含这些失败 |
| opportunity held-out sign accuracy ≤55% | 核心 opportunity 假设失败 |
| drop+opportunity 不优于 drop-only | 停止 TRACER 扩展 |
| credit Spearman <0.20 | 信用机制失败 |
| ESS < raw probes 的30%或 positivity不足 | 停止 propensity/DR claim |
| 多数 adjunct nonseparable | 退回 whole-Skill/PIF |
| pair完整块不足或跨 seed频繁变号 | 关闭 interaction layer |
| 10%与25%均无正向 CI | probe budget假设失败 |
| HHI下降但质量退化 >1 pp | diversity layer失败 |
| equal all-in 不优于更简单 baseline | 不采用 TRACER |

以下任一发生立即作废 replicate：

- TEST 前后任一 persistent state 改变；
- answer、ground truth、expected output、private prompt 或 TEST feedback进入Bank；
- `sink/all_agents`、mode、worker contract或model context串账；
- harness failure；
- 事后选择 comparator 或只保留成功 probe arm；
- pair interaction没有完整四臂却进入 credit；
- Python绕过现有AST/sandbox/contract validator；
- 任一方法突破预注册六维 all-in budget。

---

## 19. 给实现与比较 Agent 的检查表

### 19.1 判断是不是 TRACER

- Retrieval 与 Composition 是否分别有 outcome 前快照？
- Family 是否只提供 prior，Variant 才是 executable identity？
- Bundle 是否 one root + typed adjuncts，而不是任意 source splice？
- selected、activated、followed 是否作为运行事实分别定义，matched benefit 是否只存在于 CreditView？
- Adoption 是否由 host verifier，而不是 LLM 自报？
- Retrieved-unused 未 probe 是否保持 UNIDENTIFIED？
- Opportunity 是否 true same-slot swap？
- Pair effect 是否完整四臂？
- Propensity 是否来自真实 random support？
- Probe debt 是否只影响调度，不影响 efficacy？
- Model/mode/contract 是否进入 effect context？
- Local credit 是否无法绕过 Bank gate？
- FINAL_VAL/TEST 是否不回写？

### 19.2 比较时必须对齐

- 相同初始 Bank 与 atomic artifacts；
- 相同 proposer、model、worker prompts、validators；
- 相同 case/seed evaluation units；
- 相同六维 all-in budget；
- 相同 failure、split、gate和TEST纪律；
- 报告不同 search trajectories，不强迫候选相同；
- 同时报告 end-to-end、attribution、adoption、diversity和cost；
- 不把 shadow probes当免费数据；
- 不把 Family prior当已验证 transfer。

### 19.3 何时优先更简单方案

优先 current QueenBee、PIF 或 TRIAD，如果：

- 没有两阶段 retrieval/composer bottleneck；
- Bundle大多为singleton；
- adoption几乎总是1；
- opportunity signal稀少；
- deterministic hook覆盖率低；
- pair/propensity support不足；
- equal all-in结果不优于简单方法。

---

## 20. 固定 commit 代码依据

### 20.1 仓库入口

- [固定 commit `8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a`](https://github.com/RobinTian-7/Mutiagent/commit/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a)
- [根 `AGENTS.md`](../../../AGENTS.md)
- [根 `README.md`](../../../README.md)
- [`masbench/docs/self_evolution_changes.md`](../../../masbench/docs/self_evolution_changes.md)
- [`masbench/docs/experiments.md`](../../../masbench/docs/experiments.md)
- [`masbench/docs/python_generate.md`](../../../masbench/docs/python_generate.md)

### 20.2 关键 claim-to-code permalinks

| 当前代码事实 | 固定 commit permalink |
|---|---|
| Planner modes、goals、worker contracts | [`schemas.py#L21-L54`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/schemas.py#L21-L54) |
| Typed payloads 与 `SkillCard` | [`schemas.py#L409-L590`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/schemas.py#L409-L590) |
| Retrieval request-scoped filters | [`skill_bank.py#L84-L125`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L84-L125) |
| Retrieval ordering | [`skill_bank.py#L293-L303`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L293-L303) |
| Goal/provenance/mode/contract matchers | [`skill_bank.py#L307-L404`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L307-L404) |
| Empty retrieval 后 TopologySelect 回退全 Bank selectable cards | [`planner.py#L73-L87`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/planner.py#L73-L87) |
| Retrieval dedupe 与 compaction merge | [`skill_bank.py#L553-L660`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L553-L660) |
| Goal-prefixed topology-or-skill fallback equivalence key | [`skill_bank.py#L676-L686`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/skill_bank.py#L676-L686) |
| Topology fingerprint 只编码 temporal structure，不编码 reasoning policy | [`topology_equivalence.py#L34-L83`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/topology_equivalence.py#L34-L83), [`#L133-L159`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/topology_equivalence.py#L133-L159) |
| Current `operator_compose` 取得单卡或 fallback base plan，再编译 card/default operators | [`planner.py#L115-L145`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/planner.py#L115-L145), [`#L172-L207`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/planner.py#L172-L207) |
| LLM planner 可见至多 6 张 positive Skill contexts，但没有显式 bundle identity | [`llm_planner.py#L36-L110`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/llm_planner.py#L36-L110), [`#L122-L176`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/llm_planner.py#L122-L176) |
| Hot-start reuse/mutate/fresh branches | [`evolve.py#L2208-L2662`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L2208-L2662) |
| Whole executable/topology ablation | [`evolve.py#L3477-L3570`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L3477-L3570) |
| Insight association明确非因果 | [`evolve.py#L3790-L3926`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L3790-L3926) |
| VAL insight 以 held-out rows falsify 后 apply | [`evolve.py#L3382-L3412`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L3382-L3412) |
| Current VAL failure/insight write-back | [`evolve.py#L4488-L4593`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L4488-L4593) |
| Dense metric mapping 与 paired gate | [`gates.py#L13-L183`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/gates.py#L13-L183) |
| Failure classification 与 answer-free records | [`failures.py#L34-L252`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/failures.py#L34-L252) |
| Infrastructure record 可先被记录，随后进入统一 cluster/write-back 链 | [`evolve.py#L237-L410`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L237-L410), [`#L4492-L4515`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L4492-L4515), [`#L4586-L4593`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L4586-L4593) |
| Python exact EVOLVE-block patch | [`python_mutation.py#L67-L205`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/exp-graph/src/exp_graph/mas/python_mutation.py#L67-L205) |
| Internal split 的 singleton overlap 行为 | [`evolve.py#L3573-L3621`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/src/masbench/evolve.py#L3573-L3621) |
| Current TEST control flow，无完整 Frozen facade | [`verify_beats_baselines.py#L1039-L1055`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/scripts/verify_beats_baselines.py#L1039-L1055), [`#L1133-L1262`](https://github.com/RobinTian-7/Mutiagent/blob/8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a/masbench/scripts/verify_beats_baselines.py#L1133-L1262) |

### 20.3 来源边界与外部背景

- 来源对话 ID：`6a564a5d-79a0-83ea-9c5b-8bcf71203803`
- [Lilian Weng harness blog（2026-07-04）](https://lilianweng.github.io/posts/2026-07-04-harness/)
- [AFlow](https://arxiv.org/abs/2410.10762)
- [Automated Design of Agentic Systems](https://arxiv.org/abs/2408.08435)
- [AlphaEvolve](https://arxiv.org/abs/2506.13131)
- [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954)

这些链接用于恢复来源语境，不表示本文重新完成了来源对话中的 13 份 PDF 去重、博客 39 项引用、全部 Tier A/B 论文或官方仓库审计。对外论文、novelty 或发布日期敏感主张必须重新联网核验版本、官方身份、commit/tag 与访问日期。

---

## 21. 最小不可删减定义

如果后续论文或实现说明只能保留一段，应保留：

> TRACER-SkillBank 把 QueenBee 的 Skill 使用建模为 outcome 前冻结的两阶段决策：先从 hard-compatible `SkillVariantRevision` 中生成带真实随机 support 的 retrieval slate，再由 deterministic candidate generator和logged selector形成 one-root typed `BundleRevision`。`SkillFamily` 只提供语义 prior，不能执行或跨 mode 绕过验证。系统分别记录 selected、activated 与 host-verifiably followed；matched benefit只存在于独立 CreditView，retrieved-unused 未执行只增加 exposure/probe debt。Efficacy 只来自真实 matched blocks：可分离 member 的 drop/root replacement、compatible same-slot unused swap，以及预算允许时的完整四臂 pair factorial。Logged propensity只在 positivity成立时辅助审计/估计，不能替代 matched probes。Credit、adoption、failure和model context分账，只能影响 TRAIN search、mutation、QD archive和revival；最终部署仍由 frozen Bank-level dense gate 决定。正式比较使用六维 equal-all-in budget，25%只是 source probe-cap hypothesis；FINAL_VAL失败部署incumbent并留在分母，TEST对所有持久状态完全只读。

---

## 22. Changelog

- **2026-07-14 / `tracer_skillbank_v0`**：将指定对话中的 TRACER 方法归档为详细方案；明确 Family/Variant/Bundle 边界、two-stage exposure、host-verifiable adoption、same-slot opportunity regret、single-shadow 与 pair-factorial 的识别差异、25% source cap 与六维 equal-all-in 比较、PIF/TRIAD 映射、分阶段落地与可证伪实验。按用户要求不展开完整实现代码。
