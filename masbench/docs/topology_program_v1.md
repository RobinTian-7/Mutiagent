# Topology Program v1

> This is the expression-capable source format accepted inside the existing
> free `graph_generate` path. The restricted `phase_program_v1` compiler and
> independent `program_generate` planner are documented in
> [phase_program_v1.md](phase_program_v1.md). Neither mode replaces the other.

`topology_program_v1` is the compact, declarative source language accepted by
the QueenBee `graph_generate` planner. It lets an emperor LLM describe repeated
or parameterized communication schedules without listing every temporal edge.

The program is never executed as Python. A small AST interpreter evaluates only
whitelisted integer expressions, expands finite loops, and emits the existing
`GeneratedGraphPlan.steps`. Validation, repair, topology fingerprinting, probe
evaluation, skill selection, and `ProtocolRunner` execution then use the same
path as legacy explicit graph candidates.

## Candidate shape

```json
{
  "candidate_id": "chain_program",
  "name": "sequential_relay",
  "graph_type": "temporal_dag",
  "n_agents": 4,
  "program": {
    "format": "topology_program_v1",
    "selected_primary": "n_agents - 1",
    "body": [
      {
        "op": "repeat",
        "var": "i",
        "range": {"start": 0, "stop": "n_agents - 1", "step": 1},
        "body": [
          {
            "op": "step",
            "description": "forward accumulated state",
            "edges": [{"src": "i", "dst": "i + 1"}]
          }
        ]
      }
    ]
  }
}
```

This expands to three simultaneous-step edge lists: `0->1`, `1->2`, and
`2->3`. A candidate must provide exactly one of `program` or legacy `steps`.

## Language

- A root `step` emits one simultaneous communication round.
- A root `repeat` iterates a finite, stop-exclusive integer range. Its body is
  one or more sequential `step` statements.
- Each edge template has `src`, `dst`, an optional boolean `when`, and optional
  finite `for_each` loops. All expansions of an edge template stay in the same
  communication round.
- Integer expressions may use `n_agents`, in-scope loop variables, bounded
  arithmetic and bitwise operators, comparisons, boolean operators, and
  `abs`, `min`, `max`, `pow2`, `ceil_log2`, or `floor_log2`.
- `while`, imports, attributes, subscripts, mutation, recursion, arbitrary
  function calls, file access, and network access are not part of the language.

## State semantics

Every runner step reads a snapshot of the previous agent states. Sending does
not consume or clear the sender state. A receiver merges its previous state with
its inbox, and an agent with no incoming messages keeps its state unchanged.
An agent sends only when an expanded edge names it as `src`; a false `when`
predicate therefore means "do not send" without requiring an idle operation.

An empty expanded step is omitted because it cannot change any state under
these semantics.

## Safety and budgets

Expansion is bounded by the same `graph_max_steps` and `graph_max_messages`
limits used for explicit candidates, plus limits on loop iterations, expression
size, integer magnitude, and total compiler operations. A program that exceeds
a limit is rejected as one candidate; it does not poison valid candidates in
the same LLM response.

The compiler records the source hash, compiler version, expanded step/message
counts, warnings, and whether deterministic graph repair changed the expansion.
The source and compilation record are stored in `ProtocolGraphSpec.metadata`.

## Compatibility and replay

Legacy LLM responses with explicit `steps` remain valid. The deterministic fake
emperor also keeps its existing explicit candidates, preserving the offline
honesty path.

Graph Skill replay treats the expanded `protocol_spec` inside
`graph_skill_v1` as the verified executable artifact. The original topology
program is retained beside it in that Graph-only payload; it is not silently
recompiled when replaying an already verified skill, and it cannot be merged
into PhaseProgram or PythonGenerate payloads.
