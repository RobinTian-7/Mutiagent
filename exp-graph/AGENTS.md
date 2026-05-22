# Agent Instructions for `exp-graph`

This subproject is a lightweight LLM multi-agent experiment harness for testing communication topology effects.

## General Operating Rules

These rules apply to every task in this project unless explicitly overridden.
Bias toward caution over speed on non-trivial work. Use judgment on trivial tasks.

### Rule 1 — Think Before Coding

- State assumptions explicitly. If uncertain, ask rather than guess.
- Present multiple interpretations when ambiguity exists.
- Push back when a simpler approach exists.
- Stop when confused. Name what's unclear.

### Rule 2 — Simplicity First

- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked. No abstractions for single-use code.
- Test: would a senior engineer say this is overcomplicated? If yes, simplify.

### Rule 3 — Surgical Changes

- Touch only what you must. Clean up only your own mess.
- Do not "improve" adjacent code, comments, or formatting.
- Do not refactor what is not broken. Match existing style.

### Rule 4 — Goal-Driven Execution

- Define success criteria. Loop until verified.
- Do not follow steps blindly. Define success and iterate.
- Strong success criteria let you loop independently.

### Rule 5 — Use the model only for judgment calls

- Use the model for classification, drafting, summarization, and extraction.
- Do not use the model for routing, retries, or deterministic transforms.
- If code can answer, code answers.

### Rule 6 — Token budgets are not advisory

- Per-task budget: 4,000 tokens. Per-session budget: 30,000 tokens.
- If approaching budget, summarize and start fresh.
- Surface the breach. Do not silently overrun.

### Rule 7 — Surface conflicts, don't average them

- If two patterns contradict, pick one: more recent or more tested.
- Explain why. Flag the other for cleanup.
- Do not blend conflicting patterns.

### Rule 8 — Read before you write

- Before adding code, read exports, immediate callers, and shared utilities.
- "Looks orthogonal" is dangerous.
- If unsure why code is structured a way, ask.

### Rule 9 — Tests verify intent, not just behavior

- Tests must encode why behavior matters, not just what it does.
- A test that cannot fail when business logic changes is wrong.

### Rule 10 — Checkpoint after every significant step

- Summarize what was done, what is verified, and what is left.
- Do not continue from a state you cannot describe back.
- If you lose track, stop and restate.

### Rule 11 — Match the codebase's conventions, even if you disagree

- Conformance is greater than taste inside the codebase.
- If a convention seems harmful, surface it. Do not fork silently.

### Rule 12 — Fail loud

- "Completed" is wrong if anything was skipped silently.
- "Tests pass" is wrong if any were skipped.
- Default to surfacing uncertainty, not hiding it.

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
