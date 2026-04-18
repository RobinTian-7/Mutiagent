# Assumptions

This file records implementation choices that go beyond explicit TeX evidence. The goal is to keep engineering assumptions separate from paper-supported structure.

## Paper Source Location

The user prompt referenced `/Users/robintian/AI/Agent-Expretional-Graph/arXiv-2604.02674v1/sec`, but the TeX files present in this workspace are under `files/arXiv-2604.02674v1/sec`. The implementation and review use the available local TeX files.

## Mock Agent Policy

The paper states that agents share a common LLM, prompt, tools, and task instances, but it does not provide the exact prompt or action-selection policy. The runnable demo uses `src/agents/mock_agent.py` to emit propose, revise, contradict, merge, and delegate events without requiring API keys.

Assumption: stochastic action probabilities approximate the paper's qualitative structure: delegation and contradiction expand cascades, revision refines claims, and merge is less frequent. This is suitable for structural smoke tests, not score reproduction.

## Task Expansion

The paper describes a workload expansion module that generates benchmark-grounded task trees conditioned on benchmark, domain, and agent count. The repository does not reproduce those benchmark generators.

Assumption: the demo uses simplified task/subtask identifiers induced by delegation events. This preserves the separation between task decomposition and reasoning lineage while avoiding unsupported benchmark synthesis.

## Execution Step Semantics

The TeX specifies event-level traces and repeated execution but does not fully define how a runnable simulator should schedule turns.

Assumption: one workflow round lets each agent act once; one emitted event is one coordination step. This makes runs deterministic in size for a fixed seed and keeps scheduling simple.

## Reinforced Routing Defaults

The paper defines reinforced routing as `P(c_i | F_t) ∝ x_i(t)^β`, but a simulator must choose a β before collecting traces.

Assumption: `β = 0.15` is the default and remains configurable. Claim activity defaults to `1` for unseen claims so new claims are selectable.

## DTI Parameters

The paper states that `a_c` and `δ_c` are estimated from baseline traces per condition class, and that `β_c` is an empirical contradiction scaling exponent.

Assumption: the demo exposes these parameters directly and uses conservative defaults. Tests use stronger values only to exercise trigger paths quickly. Demo DTI runs are qualitative checks, not estimates from full baseline logs.

## DTI Merge Content

The paper describes a structured integration prompt over active branch heads but does not provide exact prompt text.

Assumption: the mock DTI merge emits a synthetic merged claim whose parent ids are the active branch heads. This preserves DAG structure and merge fan-in semantics without claiming semantic synthesis quality.

## Cross-Root Merge Semantics

The paper defines cascades by shared `root_claim_id`, and DTI explicitly integrates active branch heads for one root claim. It does not fully specify whether ordinary merge events may combine claims from different roots.

Assumption: regular demo merges are restricted to claims sharing the selected claim's `root_claim_id`. If fewer than two same-root claims are visible, a forced mock merge falls back to a revision. This is conservative because it preserves cascade-local interpretation.

## Topology Scope

The paper studies chain, star, tree, hierarchical, fully connected, sparse mesh, and dynamic reputation topologies.

Assumption: the MVP implements chain, star, and mesh from the original reproduction scope. Tree, hierarchical, sparse mesh, and dynamic reputation are left as TODOs because their concrete runtime definitions are not specified in the inspected TeX.

## Exponential Graph Scope

Static exponential and one-peer exponential topologies are based on `Exponential Graph is Provably Efficient for Decentralized Deep Training` (arXiv 2110.13363). The directly supported structure is the physical communication schedule:

- static exponential: each node sees cyclic neighbors at distances `1, 2, 4, ...`
- one-peer exponential: each node sees one cyclic exponential-distance neighbor per round, rotating through the same distances

Assumption A14: in this repository, exponential graphs control only neighbor communication visibility. They do not replace the Claim DAG, do not select which claim to route to, do not alter reinforced routing, and do not change DTI deficit triggers, merge behavior, or consolidation semantics.

Assumption A15: the one-peer exact-averaging theorem from arXiv 2110.13363 is not claimed as a theorem about LLM claim propagation. For `n` that is a power of two, the schedule mirrors the paper's clean periodic structure. For non-power-of-two `n`, the implementation continues to run as an engineering heuristic for sparse rotating communication, without claiming periodic exact averaging.

## Structured Neighbor Exchange

The current simulator does not exchange free-form chain-of-thought between agents. Neighbor visibility exposes structured `Claim` records filtered by physical topology and round. Claim content in the mock simulator is intentionally short synthetic text; parent ids, root ids, claim type, agent id, and depth carry the trace semantics used by reconstruction and metrics.

## Qualitative DTI Comparison

The paper reports that DTI increases integration and can reduce elite concentration in high-imbalance regimes. In this mock simulation, DTI consistently increases merge count and merge fan-in, while top-k concentration varies by topology and seed.

Assumption: qualitative comparison should be interpreted as a structural sanity check only. It demonstrates the local trigger and merge mechanism, not the paper's empirical performance claims.
