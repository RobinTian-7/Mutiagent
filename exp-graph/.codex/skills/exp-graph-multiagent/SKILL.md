---
name: exp-graph-multiagent
description: Use when working inside exp-graph on task initialization, TaskAdapter design, agent belief-state prompts, runtime consensus, final merge/reducer, LLM adjudication, or trace/audit behavior for the topology-effect multi-agent system.
---

# exp-graph Multi-Agent Contracts

Use this skill only for the `exp-graph` subproject. The project is a lightweight LLM multi-agent topology-effect harness, not a Claim DAG / cascade / DTI reproduction.

## Invariants

- The experimental variable is physical neighbor communication topology.
- All agents solve one shared `global_task`; each agent sees a different `local_observation`.
- `belief_state` is the only internal agent truth source.
- `outbox` is derived by program code from `belief_state` plus metadata. The LLM must not output outbox.
- `runtime_consensus` and `final_reducer` are separate layers.
- Task-specific logic belongs behind `TaskAdapter`; runner, topology, agent, and reducer code should not hard-code array-search details.

## Task Initialization Contract

When adding or changing a task adapter, implement these methods:

```python
build_global_task(...)
split_into_local_observations(global_task, n_agents)
initial_local_solve(local_observation)
normalize_consensus_key(key_or_proposal)
evaluate_final_answer(global_task, final_key)
format_task_prompt_context(global_task, local_observation)
format_consensus_key_instructions()
format_adjudication_context(global_task)
```

Rules:

- `build_global_task` may include private evaluation fields such as `answer_key`, but those fields must never be passed to LLM prompts or final adjudication.
- `split_into_local_observations` must preserve the shared-task framing: agents receive partial observations, not separate unrelated tasks.
- `initial_local_solve` must use only the local observation. It creates the initial `belief_state` and round-0 outbox before communication begins.
- For distributed search-style tasks, local absence is usually `UNKNOWN`, not global `NOT_FOUND`, unless the local observation proves global coverage.
- `normalize_consensus_key` owns task-specific canonicalization. Core aggregation should group normalized keys, not parse task semantics.
- `format_consensus_key_instructions` owns task-specific consensus-key prompt wording. Generic prompt builders must not hard-code array-search keys.
- `format_adjudication_context` must be label-safe: no `answer`, `answer_key`, `answer_index`, `ground_truth`, full hidden arrays, or equivalent leakage.

## Agent Prompt Contract

Prompts should describe the agent as continuing to solve the same shared task:

```text
You have local_observation, previous belief_state, and this round's inbox.
Treat inbox as context, not guaranteed truth.
Update your own belief_state.
Return only one JSON object.
Do not output outbox.
Do not output chain-of-thought or extra prose.
```

The LLM output must be a `belief_state` JSON object:

```json
{
  "status": "unknown | candidate | final",
  "proposal": "...",
  "consensus_key": "... | UNKNOWN | null",
  "support": ["..."],
  "uncertainty": "...",
  "open_questions": ["..."],
  "private_notes": "..."
}
```

The runner/agent layer handles JSON validation and retry. Retry prompts may include the schema, validation error, bad response, and original prompt; retry calls must be counted in usage metrics.

## Runner and Communication Contract

Each synchronous communication round must follow the barrier pattern:

1. Compute neighbors for all agents with `topology.get_neighbors(agent_id, round_idx, n_agents)`.
2. Build inboxes from neighbors' previous outboxes.
3. Ask every agent to produce a new `belief_state`.
4. Derive new outboxes from new belief states.
5. Commit all states together.
6. Run cheap runtime consensus.

`round_idx` is owned by the runner. For `one_peer_exponential`, all agents share the same global phase in a given round.

Parallel LLM calls are allowed inside a round, but they must not violate the barrier: no agent may read another agent's same-round update.

## Final Merge / Reducer Contract

Runtime consensus:

- Runs every round.
- Counts `belief_state.consensus_key` only.
- Does not call LLM.
- Does not do semantic proposal merging.

Final reducer:

- Runs only after stopping.
- First groups candidates by normalized `consensus_key`.
- Summarizes each group into `GroupSummary`.
- Default score is `size_ratio`; do not mix scoring formulas based on whether some agents happened to output confidence.
- Rule-based selection should run before optional LLM adjudication.

Optional LLM adjudicator:

- May run at most once per experiment, after stopping.
- Should be used only when top groups are close.
- Input must be limited to label-safe task context plus top `GroupSummary` objects.
- Never pass ground truth fields such as `answer_key`, `answer_index`, or hidden full task labels.
- Output must be structured JSON:

```json
{
  "selected_group_key": "... | NO_CONSENSUS",
  "decision": "accept | reject | no_consensus",
  "reason": "...",
  "confidence": 0.0
}
```

## Metrics and Trace Contract

- Keep internal `round_idx` 0-based.
- Report `rounds_to_consensus` as 1-based communication rounds.
- Preserve `stop_round_idx` for internal indexing.
- Record model calls, retry calls, prompt tokens, completion tokens, final accuracy, consensus status, top keys, and active key counts.
- For real LLM runs, prefer `trace_dir` to write JSONL traces to disk.
- Do not retain full prompt/response traces in memory during batch experiments unless `retain_traces=True`.
- Trace records should include prompt, raw response, parsed belief state, outbox, neighbors, inbox, token usage, model calls, and retry attempts.

## Review Checklist

Before accepting changes to initialization or merge logic, check:

- No task labels leak into prompts or adjudicator context.
- Initial local solve uses only local observation.
- LLM outputs only `belief_state`; outbox is derived.
- Runtime consensus remains cheap and key-based.
- Final reducer runs only after stopping.
- Default reducer score is explainable and continuous across groups.
- `rounds_to_consensus` is externally 1-based.
- Real LLM paths expose configurable `model_name`, `temperature`, `json_retry_attempts`, and trace controls.
