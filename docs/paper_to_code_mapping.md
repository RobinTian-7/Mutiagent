# Paper-to-Code Mapping

Source: arXiv 2604.02674v1 — "Laws of Collective Cognition in LLM Multi-Agent Systems"

This document maps paper concepts to code components, identifies ambiguities,
and registers implementation assumptions.

---

## A. Architecture Extracted from the Paper

### A1. LangGraph Usage
**Paper evidence (Sec 3.1):**
> "The system is implemented using LangGraph, which enforces the specified
> topology and manages message routing."

- LangGraph is the orchestration backbone
- It enforces communication topology constraints
- It manages message routing between agents
- All agents share the same base LLM, prompt template, tool access, and task instances

### A2. Task Tree / Subtask Tree
**Paper evidence (Sec 3.1, Appendix B.1):**
- Tasks are organized as a *task tree* where nodes = tasks, edges = dependency relationships
- A "Workload Expansion Module" generates task trees conditioned on (benchmark, domain, N)
- The module specifies task availability and dependencies only — no prescribed coordination
- Hierarchy: Task → Subtask → Claim → Event (Appendix B.1)
- Subtask tree is constructed from `delegate_subtask` events
- Each subtask has: subtask_id, parent_subtask_id, subtask_depth, assigned_agent, subtask_status
- "The subtask tree records task decomposition induced by delegation, while the claim DAG records the emergent propagation and integration of reasoning"

### A3. Claim DAG
**Paper evidence (Sec 3.2, Appendix B.2–B.5):**
- A *claim* is the atomic unit of reasoning: c_i = (a(c_i), t(c_i), P(c_i), τ(c_i))
  - a: producing agent
  - t: associated task
  - P: set of parent claims
  - τ: claim type
- Claim types: Proposed, Revised, Contradictory, Merged (Appendix Table 6)
- Claims form a DAG G = (C, E_c) where (c_i, c_j) ∈ E_c if c_i ∈ P(c_j)
- Claim fields: claim_id, parent_claim_ids, root_claim_id, claim_depth, claim_status
- Root claim assignment: claims with no parents are root claims; descendants inherit root_claim_id

### A4. Events / Claims / Cascades
**Paper evidence (Sec 3.2, Table 1, Appendix B.2):**
- An *event* is a coordination step that transforms or relates claims
- Event types and their claim transformations:
  - `revise_claim` → single parent → child (chain)
  - `contradict_claim` → parent → multiple children (branching)
  - `merge_claims` → multiple parents → child (multi-parent DAG)
  - `delegate_subtask` → creates new subtask context (hierarchical tree)
- Event fields: run_id, step_id, agent_id, event_type, target_claim_id, target_subtask_id, timestamp, message_length
- Derived fields: revision_chain_id, contradiction_group_id, merge_id, merge_parent_ids

**Cascades (Sec 3.2):**
- A *cascade* = set of all claims sharing the same root_claim_id
- C_r = {c_i ∈ C | root(c_i) = c_r}
- Cascades are connected subgraphs of G rooted at a single initial claim
- Cascade size = |C_r| (total claims in cascade)

### A5. Observables
**Paper evidence (Sec 3.3):**
- **Delegation cascade size:** number of events in subtask tree rooted at a delegate_subtask event
- **Revision wave:** length of chain of revise_claim events linked by parent_claim_id
- **Contradiction burst:** number of distinct agents issuing contradict_claim on same parent claim
- **Merge fan-in:** number of parent_claim_ids referenced by a single merge_claims event
- **TCE (Total Cognitive Effort):** total number of coordination events in a cascade: TCE(c_r) = Σ_{e_k ∈ E_r} 1
- **Top-k contribution share:** S_k(c_r) = Σ_{a ∈ Top-k} n_a(c_r) / Σ_{a ∈ A} n_a(c_r)
- **Extreme-event scaling:** x_max(N) = max_{c_r} |C_r|

### A6. Topology Routing
**Paper evidence (Sec 3.1):**
- Topologies tested: chain, star, tree, hierarchical, fully connected, sparse mesh, dynamic reputation
- LangGraph enforces topology — topology determines who can communicate with whom
- "Topology determines how far these expansions propagate: denser interaction graphs enable repeated engagement with active trajectories"
- Physical communication topology is separate from logical claim routing

### A7. Reinforced Routing
**Paper evidence (Sec 4.2):**
- P(c_i | F_t) = x_i(t)^β / Σ_j x_j(t)^β
- x_i(t) = accumulated coordination activity of claim c_i (number of downstream events)
- β > 0 controls reinforcement strength
- β = 0 → uniform routing; β > 0 → preferential attachment
- R(x,N) ∝ x^{β(N)} — routing ratio
- β(N) = d log R(x,N) / d log x — preferential attachment exponent
- Empirically β̂ > 0 across all conditions, strengthens with N

### A8. Deficit-Triggered Integration (DTI)
**Paper evidence (Sec 6, Appendix C, Algorithm 1):**
- Operates at cascade level, maintaining per-root-claim state: (t_r, M_r)
- t_r = coordination events elapsed in active cascade segment
- M_r = realized merge events in current cascade segment
- Exploration pressure: P_r(t_r) = a_c · t_r^{β̂_c}
  - β̂_c = empirically observed contradiction scaling exponent
  - a_c = normalization constant per condition class (topology × task family)
- Integration deficit: Δ_r(t_r) = P_r(t_r) - M_r
- Trigger condition: Δ_r(t_r) > δ_c (condition-specific threshold)
- On trigger:
  1. Collect active branch heads B_r = ActiveBranches(r)
  2. Apply structured integration prompt to B_r → merged claim ẽ
  3. Log ẽ as merge event attached to root r
  4. Broadcast ẽ as updated shared context
  5. Reset: t_r ← 0, M_r ← 1 (prevents immediate retriggering)
- Parameters a_c and δ_c estimated from baseline traces:
  - δ_c = mean + 1σ of integration deficit at cascade termination points
- Memory: O(|R|) where R = active cascades
- Each event: constant-time updates; LLM calls only on trigger

---

## B. Code Components Implied by the Paper

### B1. Schemas (`src/schemas/`)
| Schema | Key Fields | Paper Source |
|--------|-----------|--------------|
| Claim | id, parent_claim_ids, root_claim_id, agent_id, content, timestamp, claim_type, claim_depth, subtask_id | Sec 3.2, App Tables 7-8 |
| Event | event_id, run_id, step_id, agent_id, event_type, target_claim_id, target_subtask_id, timestamp, message_length | App Table 9 |
| Subtask | subtask_id, parent_subtask_id, subtask_depth, assigned_agent, subtask_status | App Table 11 |
| Cascade | root_claim_id, claim_ids (derived) | Sec 3.2 |
| DerivedCoordination | revision_chain_id, contradiction_group_id, merge_id, merge_parent_ids | App Table 12 |

### B2. Runtime State
- Append-only event trace (JSONL)
- Per-agent state: visible claims (filtered by topology)
- Per-cascade DTI state: (t_r, M_r) per active root claim
- Global claim registry (id → Claim)

### B3. Routing Modules (`src/routing/`)
- **Topology routing:** determines communication visibility (who can send to whom)
- **Claim routing:** selects which claim an agent acts on next
  - Reinforced routing: P(c_i) ∝ x_i(t)^β (Eq. 3)
  - Pluggable interface for alternative policies

### B4. Topology Modules (`src/topology/`)
- Interface: get_neighbors(agent_id) → list of visible agent_ids
- Implementations: chain, star, mesh (minimum viable)
- Extensible to: tree, hierarchical, fully connected, sparse mesh, dynamic reputation

### B5. Reconstruction Modules (`src/reconstruction/`)
- Claim DAG from event traces (parent_claim_ids → edges)
- Subtask tree from delegation events
- Cascade extraction from root_claim_id grouping
- Root claim assignment propagation

### B6. Intervention Modules (`src/interventions/`)
- DTI monitor: per-cascade state tracking
- DTI trigger: deficit computation + threshold check
- DTI action: branch head collection + merge invocation
- DTI state reset

### B7. Analysis Modules (`src/analysis/`)
- Cascade size computation
- TCE computation
- Top-k contribution share
- Delegation cascade size (subtask tree)
- Revision wave length
- Contradiction burst size
- Merge fan-in

---

## C. Ambiguities

### C1. Agent Decision Logic
The paper does not specify the exact prompts or decision logic agents use to choose
between propose/revise/contradict/merge/delegate actions. The paper says all agents
share a common "reasoning prompt template" but does not provide it.

### C2. Task Expansion Module
The "Workload Expansion Module" that generates task trees conditioned on (b, d, N) is
described at a high level but not specified algorithmically. The paper says it
"generates benchmark-grounded task sets" but does not detail the generation procedure.

### C3. Action Selection Mechanism
When an agent takes a turn, how does it decide which event type to emit? The paper
describes events as observed primitives but does not prescribe the decision policy
(beyond reinforced routing for claim selection).

### C4. Contradiction Temporal Window
Contradiction bursts are defined as claims "referencing the same parent claim within a
temporal window τ" — the specific value of τ is not given.

### C5. Dynamic Reputation Topology
Listed as a topology but not defined in detail.

### C6. Agent Assignment to Subtasks
How agents are assigned to subtasks is not fully specified.

### C7. Execution Steps / Termination
The paper mentions "20 execution steps per run" but does not clarify whether this
is per-agent or global, or what constitutes one step.

### C8. LLM Integration Prompt for DTI Merge
DTI says "a structured integration prompt is applied to B_r" — the exact prompt
is not provided.

### C9. β Estimation
The paper estimates β empirically from traces, but the simulation needs a β
value to run in the first place. This creates a chicken-and-egg problem for
simulation.

### C10. Normalization Constant a_c
For DTI, a_c "captures the empirical relationship between cascade growth and
merge activity" — the exact computation is not specified beyond being estimated
from baseline traces.

---

## D. Assumption Registry

| ID | Ambiguity | Assumption | Rationale |
|----|-----------|-----------|-----------|
| A1 | C1: Agent decision logic | Use a simple LLM prompt that presents visible claims and asks the agent to choose an action type + target claim. Action types: propose, revise, contradict, merge, delegate. | Conservative: lets the LLM decide naturally without hard-coding action probabilities. |
| A2 | C2: Task expansion | Generate a simple dependency DAG with depth proportional to log(N) and branching factor ~2-3. Tasks are generic reasoning problems. | Conservative: preserves tree structure without over-engineering benchmark grounding. |
| A3 | C3: Action selection | Agent LLM chooses action type based on visible state. Reinforced routing (Eq. 3) selects the target claim; the agent then decides the action type. | Conservative: separates claim selection (paper-specified) from action selection (not specified). |
| A4 | C4: Temporal window | Set τ = 1 step (contradiction burst = claims contradicting the same parent within the same execution round). | Most conservative: smallest possible window. |
| A5 | C5: Dynamic reputation | Not implemented in MVP. Only chain, star, mesh. | Conservative: implement only what is well-defined. |
| A6 | C6: Agent assignment | Round-robin assignment of subtasks to agents, filtered by topology visibility. | Simple and neutral — avoids introducing unspecified optimization. |
| A7 | C7: Execution steps | 20 global rounds. In each round, every agent acts once. | Conservative interpretation of "20 execution steps per run." |
| A8 | C8: DTI merge prompt | Use a structured prompt: "Given these branch-head claims, synthesize them into a single coherent position." | Minimal: implements the described merge semantics without over-specifying. |
| A9 | C9: β for simulation | Use β = 0.15 as default (matches empirical β̂ from Table in Appendix for GPT-4o-mini). Allow configuration. | Paper reports β̂ values; using the primary model's estimate is faithful. |
| A10 | C10: DTI a_c | Estimate a_c = (mean merge count) / (mean cascade length)^{β̂_c} from a short baseline run. Default to a_c = 0.1 if no baseline. | Conservative: uses paper's described estimation procedure. |
| A11 | C7: Step definition | One "step" = one agent performing one coordination action (producing one event). 20 steps = 20 rounds × N agents = 20N total events maximum. | Consistent with "execution steps per run" at 20, treating as rounds. |
| A12 | - | For simulation without real LLM calls, provide a mock agent that selects actions stochastically with biases matching paper's observed distributions (delegation and contradiction dominate expansion, merge is rarer). | Needed for runnable demo without API keys. |
