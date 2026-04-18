# 论文到代码的映射

来源：arXiv 2604.02674v1，**"Laws of Collective Cognition in LLM Multi-Agent Systems"**

已检查的本地 TeX 源码路径：`files/arXiv-2604.02674v1/sec/`。

本文档把论文概念映射到代码组件，标出歧义，并登记实现假设。

---

## A. 从论文抽取出的架构

### A1. LangGraph 使用方式

**论文证据（Sec 3.1）：**

> "The system is implemented using LangGraph, which enforces the specified
> topology and manages message routing."

- LangGraph 是编排骨架。
- 它 enforce communication topology constraints。
- 它管理 agents 之间的 message routing。
- 所有 agents 共享同一个 base LLM、prompt template、tool access 和 task instances。

### A2. Task Tree / Subtask Tree

**论文证据（Sec 3.1, Appendix B.1）：**

- Tasks 被组织成 *task tree*，其中 nodes = tasks，edges = dependency relationships。
- "Workload Expansion Module" 根据 `(benchmark, domain, N)` 生成 task trees。
- 该模块只指定 task availability 和 dependencies，不规定 coordination。
- 层级结构：Task → Subtask → Claim → Event（Appendix B.1）。
- Subtask tree 由 `delegate_subtask` events 构造。
- 每个 subtask 包含：subtask_id、parent_subtask_id、subtask_depth、assigned_agent、subtask_status。
- "The subtask tree records task decomposition induced by delegation, while the claim DAG records the emergent propagation and integration of reasoning"

### A3. Claim DAG

**论文证据（Sec 3.2, Appendix B.2-B.5）：**

- *Claim* 是推理的原子单元：`c_i = (a(c_i), t(c_i), P(c_i), τ(c_i))`
  - `a`：产生该 claim 的 agent
  - `t`：关联 task
  - `P`：parent claims 集合
  - `τ`：claim type
- Claim types：Proposed、Revised、Contradictory、Merged（Appendix Table 6）。
- Claims 形成 DAG `G = (C, E_c)`，其中当 `c_i ∈ P(c_j)` 时，`(c_i, c_j) ∈ E_c`。
- Claim fields：claim_id、parent_claim_ids、root_claim_id、claim_depth、claim_status。
- Root claim assignment：没有 parents 的 claims 是 root claims；descendants 继承 `root_claim_id`。

### A4. Events / Claims / Cascades

**论文证据（Sec 3.2, Table 1, Appendix B.2）：**

- *Event* 是一个 coordination step，用于转换或关联 claims。
- Event types 及其 claim transformations：
  - `revise_claim` → single parent → child（chain）
  - `contradict_claim` → parent → multiple children（branching）
  - `merge_claims` → multiple parents → child（multi-parent DAG）
  - `delegate_subtask` → 创建新的 subtask context（hierarchical tree）
- Event fields：run_id、step_id、agent_id、event_type、target_claim_id、target_subtask_id、timestamp、message_length。
- Derived fields：revision_chain_id、contradiction_group_id、merge_id、merge_parent_ids。

**Cascades（Sec 3.2）：**

- *Cascade* = 所有共享同一 `root_claim_id` 的 claims 集合。
- `C_r = {c_i ∈ C | root(c_i) = c_r}`
- Cascades 是以单个 initial claim 为根的 connected subgraphs of G。
- Cascade size = `|C_r|`，即 cascade 中 claims 的总数。

### A5. Observables

**论文证据（Sec 3.3）：**

- **Delegation cascade size**：以某个 `delegate_subtask` event 为根的 subtask tree 中的 event 数量。
- **Revision wave**：由 `parent_claim_id` 链接的 `revise_claim` events 链长度。
- **Contradiction burst**：对同一个 parent claim 发出 `contradict_claim` 的不同 agents 数量。
- **Merge fan-in**：单个 `merge_claims` event 引用的 `parent_claim_ids` 数量。
- **TCE（Total Cognitive Effort）**：某个 cascade 中 coordination events 的总数：`TCE(c_r) = Σ_{e_k ∈ E_r} 1`
- **Top-k contribution share**：`S_k(c_r) = Σ_{a ∈ Top-k} n_a(c_r) / Σ_{a ∈ A} n_a(c_r)`
- **Extreme-event scaling**：`x_max(N) = max_{c_r} |C_r|`

### A6. Topology Routing

**论文证据（Sec 3.1）：**

- 测试的 topologies：chain、star、tree、hierarchical、fully connected、sparse mesh、dynamic reputation。
- LangGraph enforces topology，即 topology 决定谁可以和谁通信。
- "Topology determines how far these expansions propagate: denser interaction graphs enable repeated engagement with active trajectories"
- 物理通信拓扑与逻辑 claim routing 分离。

### A7. Reinforced Routing

**论文证据（Sec 4.2）：**

- `P(c_i | F_t) = x_i(t)^β / Σ_j x_j(t)^β`
- `x_i(t)` = claim `c_i` 的累计 coordination activity，即 downstream events 数量。
- `β > 0` 控制 reinforcement strength。
- `β = 0` → uniform routing；`β > 0` → preferential attachment。
- `R(x,N) ∝ x^{β(N)}`，routing ratio。
- `β(N) = d log R(x,N) / d log x`，preferential attachment exponent。
- 实验上 `β̂ > 0` 在所有 conditions 下成立，并随 `N` 增强。

### A8. Deficit-Triggered Integration (DTI)

**论文证据（Sec 6, Appendix C, Algorithm 1）：**

- 在 cascade level 运行，维护每个 root claim 的状态 `(t_r, M_r)`。
- `t_r` = active cascade segment 中已经经过的 coordination events。
- `M_r` = 当前 cascade segment 中已经实现的 merge events。
- Exploration pressure：`P_r(t_r) = a_c · t_r^{β̂_c}`
  - `β̂_c` = 经验 contradiction scaling exponent
  - `a_c` = 每个 condition class 的 normalization constant（topology × task family）
- Integration deficit：`Δ_r(t_r) = P_r(t_r) - M_r`
- Trigger condition：`Δ_r(t_r) > δ_c`，其中 `δ_c` 是 condition-specific threshold。
- 触发后：
  1. 收集 active branch heads：`B_r = ActiveBranches(r)`
  2. 对 `B_r` 应用 structured integration prompt → merged claim `ẽ`
  3. 把 `ẽ` 记录为 attached to root `r` 的 merge event
  4. 广播 `ẽ` 作为 updated shared context
  5. Reset：`t_r ← 0, M_r ← 1`，避免立即重复触发
- 参数 `a_c` 和 `δ_c` 从 baseline traces 估计：
  - `δ_c = mean + 1σ`，基于 cascade termination points 的 integration deficit
- Memory：`O(|R|)`，其中 `R` 是 active cascades。
- 每个 event：constant-time updates；只有 trigger 时才调用 LLM。

---

## B. 论文隐含的代码组件

### B1. Schemas (`src/schemas/`)

| Schema | Key Fields | Paper Source |
|--------|-----------|--------------|
| Claim | id, parent_claim_ids, root_claim_id, agent_id, content, timestamp, claim_type, claim_depth, subtask_id | Sec 3.2, App Tables 7-8 |
| Event | event_id, run_id, step_id, agent_id, event_type, target_claim_id, target_subtask_id, timestamp, message_length | App Table 9 |
| Subtask | subtask_id, parent_subtask_id, subtask_depth, assigned_agent, subtask_status | App Table 11 |
| Cascade | root_claim_id, claim_ids (derived) | Sec 3.2 |
| DerivedCoordination | revision_chain_id, contradiction_group_id, merge_id, merge_parent_ids | App Table 12 |

### B2. Runtime State

- Append-only event trace（JSONL）
- Per-agent state：visible claims，由 topology 过滤
- Per-cascade DTI state：每个 active root claim 的 `(t_r, M_r)`
- Global claim registry：`id → Claim`

### B3. Routing Modules (`src/routing/`)

- **Topology routing**：决定 communication visibility，即谁可以给谁发消息。
- **Claim routing**：选择 agent 下一步作用于哪个 claim。
  - Reinforced routing：`P(c_i) ∝ x_i(t)^β`（Eq. 3）
  - 可插拔接口，用于替换 routing policies。

### B4. Topology Modules (`src/topology/`)

- Interface：`get_neighbors(agent_id, round_idx=0) → list of visible agent_ids`
- 原始复现范围中的 implementations：chain、star、mesh
- 来自 arXiv 2110.13363 的额外物理 topology implementations：
  `static_exponential` 和 `one_peer_exponential`
- 可扩展到：tree、hierarchical、fully connected、sparse mesh、dynamic reputation

### B5. Reconstruction Modules (`src/reconstruction/`)

- 从 event traces 重建 Claim DAG：`parent_claim_ids → edges`
- 从 delegation events 重建 subtask tree
- 按 `root_claim_id` 分组提取 cascades
- Root claim assignment propagation

### B6. Intervention Modules (`src/interventions/`)

- DTI monitor：per-cascade state tracking
- DTI trigger：deficit computation + threshold check
- DTI action：branch head collection + merge invocation
- DTI state reset

### B7. Analysis Modules (`src/analysis/`)

- Cascade size computation
- TCE computation
- Top-k contribution share
- Delegation cascade size（subtask tree）
- Revision wave length
- Contradiction burst size
- Merge fan-in

---

## C. 歧义

### C1. Agent Decision Logic

论文没有指定 agents 用于在 propose/revise/contradict/merge/delegate actions 之间选择的精确 prompts 或 decision logic。论文说所有 agents 共享一个 "reasoning prompt template"，但没有提供该 template。

### C2. Task Expansion Module

"Workload Expansion Module" 会根据 `(b, d, N)` 生成 task trees，但只做了高层描述，没有给出算法细节。论文说它会 "generates benchmark-grounded task sets"，但没有展开 generation procedure。

### C3. Action Selection Mechanism

当一个 agent 轮到行动时，它如何决定 emit 哪种 event type？论文把 events 描述为 observed primitives，但没有规定 decision policy，除了 claim selection 使用 reinforced routing。

### C4. Contradiction Temporal Window

Contradiction bursts 被定义为在 temporal window `τ` 内 referencing same parent claim 的 claims，但没有给出 `τ` 的具体值。

### C5. Dynamic Reputation Topology

论文列出了这个 topology，但没有详细定义。

### C6. Agent Assignment to Subtasks

论文没有完全指定 agents 如何分配到 subtasks。

### C7. Execution Steps / Termination

论文提到 "20 execution steps per run"，但没有说明这是 per-agent 还是 global，也没有说明一个 step 的精确定义。

### C8. LLM Integration Prompt for DTI Merge

DTI 说明会对 `B_r` 应用 "a structured integration prompt"，但没有提供精确 prompt。

### C9. β Estimation

论文从 traces 中经验估计 β，但 simulation 在收集 traces 之前就需要一个 β 值。这对 simulation 形成了先有鸡还是先有蛋的问题。

### C10. Normalization Constant a_c

对 DTI 来说，`a_c` "captures the empirical relationship between cascade growth and merge activity"，但除了从 baseline traces 估计外，没有给出精确计算方式。

### C11. Cross-Root Merge Semantics

论文通过共享 `root_claim_id` 定义 cascades，并且 DTI 整合某一个 root claim 的 active branch heads。它没有完全说明普通 merge events 是否可以合并不同 root cascades 中的 claims。

### C12. Exponential Graph Transfer

arXiv 2110.13363 为 decentralized deep training 和 averaging 定义了 exponential graphs。它没有声称同样的 averaging theorem 可以直接应用到 LLM claim propagation。

---

## D. 假设登记表

| ID | Ambiguity | Assumption | Rationale |
|----|-----------|-----------|-----------|
| A1 | C1: Agent decision logic | 使用简单 LLM prompt，向 agent 展示 visible claims，并要求 agent 选择 action type + target claim。Action types: propose, revise, contradict, merge, delegate. | 保守做法：让 LLM 自然决策，不硬编码 action probabilities。 |
| A2 | C2: Task expansion | 生成简单 dependency DAG，depth 与 `log(N)` 成比例，branching factor 约为 2-3。Tasks 使用通用 reasoning problems。 | 保守做法：保留 tree structure，不过度工程化 benchmark grounding。 |
| A3 | C3: Action selection | Agent LLM 基于 visible state 选择 action type。Reinforced routing（Eq. 3）选择 target claim；agent 随后决定 action type。 | 保守做法：把论文指定的 claim selection 与未指定的 action selection 分离。 |
| A4 | C4: Temporal window | 设置 `τ = 1 step`，即 contradiction burst = 同一 execution round 内 contradict 同一 parent 的 claims。 | 最保守：使用最小可能窗口。 |
| A5 | C5: Dynamic reputation | MVP 不实现。只实现 chain、star、mesh。 | 保守做法：只实现定义清楚的内容。 |
| A6 | C6: Agent assignment | 对 subtasks 做 round-robin assignment，并受 topology visibility 过滤。 | 简单且中性，避免引入未指定 optimization。 |
| A7 | C7: Execution steps | 20 个 global rounds。每个 round 中每个 agent 行动一次。 | 对 "20 execution steps per run" 的保守解释，将其视为 rounds。 |
| A8 | C8: DTI merge prompt | 使用 structured prompt: "Given these branch-head claims, synthesize them into a single coherent position." | 最小实现：保留描述的 merge semantics，不过度指定。 |
| A9 | C9: β for simulation | 默认使用 `β = 0.15`，匹配 Appendix table 中 GPT-4o-mini 的经验 `β̂`。允许配置。 | 论文报告了 `β̂` 值；使用主模型估计值是忠实做法。 |
| A10 | C10: DTI a_c | 从短 baseline run 估计 `a_c = (mean merge count) / (mean cascade length)^{β̂_c}`。如果没有 baseline，则默认 `a_c = 0.1`。 | 保守做法：使用论文描述的估计过程。 |
| A11 | C7: Step definition | 一个 "step" = 一个 agent 执行一个 coordination action，即产生一个 event。20 steps = 20 rounds × N agents = 最多 20N 个 events。 | 与 "execution steps per run" 为 20 的描述一致，将其解释为 rounds。 |
| A12 | - | 对不调用真实 LLM 的 simulation，提供 mock agent，按近似论文 observed distributions 的 biases 随机选择 actions：delegation 和 contradiction 主导 expansion，merge 较少。 | 让 demo 无需 API keys 即可运行。 |
| A13 | C11: Cross-root merge semantics | 常规 demo merges 限制为与 selected claim 共享同一 root 的 claims。如果可见 same-root claims 少于两个，则退回 revision。 | 保守做法：保持 cascade-local interpretation，并匹配 DTI 的 root-local integration 描述。 |
| A14 | C12: Exponential graph transfer | 只把 static/one-peer exponential graphs 用作物理 neighbor visibility schedules。不把它们耦合进 claim routing、Claim DAG edges 或 DTI trigger logic。 | 保持物理通信拓扑与逻辑协作分离。 |
| A15 | C12: Non-power-of-two one-peer schedule | 对非 2 的整数次幂 agent 数量，保留 one-peer rotating exponential schedule 作为启发式，不声称 periodic exact averaging。 | arXiv 2110.13363 的 exact averaging 结果在 2 的幂下最干净；simulator 仍需要支持任意 N 的可运行 topology。 |
