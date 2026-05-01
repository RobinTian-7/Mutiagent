# Agent Instructions for `exp-graph`

This subproject is a lightweight LLM multi-agent experiment harness for testing communication topology effects.

## Core Scope

- Study only how physical neighbor communication topology affects task solving.
- Do not introduce Claim DAG, cascades, DTI, reinforced claim routing, or coordination-law reproduction here.
- Keep task logic pluggable through `TaskAdapter`.
- Keep topology routing, task logic, runtime consensus, and final aggregation as separate modules.
- For task initialization, prompts, runtime consensus, final merge/reducer, LLM adjudication, and trace/audit changes, follow the local skill at `.codex/skills/exp-graph-multiagent/SKILL.md`.

## Agent State Rules

- `belief_state` is the only internal source of truth for an agent.
- `outbox` is not an independent truth source.
- `outbox` must be derived by program code from `belief_state` plus metadata.
- The LLM updates only `belief_state`; it must not produce `outbox`.

## Synchronous Runner Rules

- The runner is synchronous and round-based.
- Each round computes all neighbors first, gathers inboxes from previous outboxes, asks all agents for next belief states, builds outboxes, then commits all updates together.
- Do not introduce async or sequential update behavior that lets earlier agents in a round influence later agents in the same round.
- `one_peer_exponential` uses a global `round_idx` owned by the runner. It is not an agent-local counter.

## Topology Rules

- All topologies must implement:
  `get_neighbors(agent_id: int, round_idx: int, n_agents: int) -> list[int]`
- Agent logic must not branch on topology names.
- Exponential graphs only define neighbor communication visibility.
- For non-power-of-two agent counts, one-peer exponential is a heuristic schedule, not a theoretical exact-averaging guarantee.

## Task Rules

- Array search specifics belong in `src/exp_graph/tasks/array_search.py`.
- Core agent, runner, topology, consensus, and final reducer modules must not hard-code array search details.
- Use minimal runnable implementations first; avoid over-engineering.

## LLM Rules

- Prompts should frame each agent as continuing to solve the same shared task.
- Inbox messages are new context, not facts to blindly copy.
- The LLM must output only JSON for the next `belief_state`.
- Do not request or store long chain-of-thought.
