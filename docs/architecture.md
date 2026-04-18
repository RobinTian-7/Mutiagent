# Architecture

This repository implements a minimal runnable reproduction of the paper's coordination structure, not the full benchmark pipeline.

## Core Design

The runtime is organized around append-only traces. Agents produce `Event` and `Claim` records; graphs and metrics are reconstructed afterward from those records. This follows the paper's event-level formulation, where coordination dynamics are analyzed from timestamped actions, claim references, and task dependencies.

The implementation deliberately separates three structures:

1. Physical communication topology: who can communicate with whom.
2. Task/subtask tree: how work is decomposed through delegation.
3. Claim DAG: how reasoning evolves through parent claim references.

These structures should not be collapsed into one graph.

Exponential graph support lives only in the physical communication topology.
`static_exponential` and `one_peer_exponential` decide which neighbor claims an
agent can read in a round. They do not choose claims, rewrite parent links,
replace the Claim DAG, or modify DTI triggers.

## Runtime Flow

`src/simulation/workflow.py` builds a LangGraph `StateGraph`. Each round:

1. The acting agent resolves physical neighbors from the active topology.
2. The acting agent reads visible structured `Claim` records from those neighbors and itself.
3. A pluggable claim router selects a candidate claim from the visible set.
4. The mock agent emits one coordination event and one resulting claim.
5. Event and claim records are appended to state.
6. If DTI is enabled, the per-cascade monitor updates local `(t_r, M_r)` state and may insert a merge event.

The physical neighbor schedule is recorded in `neighbor_trace`. It is runtime
observability for communication paths, not a logical reasoning graph.

The demo uses mock agents so it can run without API keys. This is an engineering assumption documented in `docs/assumptions.md`.

## Component Map

- `src/schemas/`: Pydantic models for claims, events, subtasks, and cascades.
- `src/topology/`: chain, star, mesh, static exponential, and one-peer exponential communication graphs.
- `src/routing/`: topology visibility and reinforced claim selection.
- `src/tracing/`: append-only JSONL trace writer.
- `src/reconstruction/`: Claim DAG, subtask tree, and cascade reconstruction.
- `src/interventions/`: Deficit-Triggered Integration.
- `src/analysis/`: cascade size, TCE, top-k contribution, revision waves, contradiction bursts, and merge fan-in.
- `examples/`: runnable scripts for demo generation and qualitative DTI comparison.

## DTI Placement

DTI is implemented as a local intervention layer, not a global scheduler. It monitors each active cascade by root claim id, computes an integration deficit, and triggers a merge only when the deficit crosses a threshold. Triggered integration consolidates active branch heads and resumes exploration from the merged claim.

DTI remains cascade-level and state-dependent under all topologies. Exponential
graphs only change which neighboring structured claims are visible before local
routing and action selection.

## Output Contract

`examples/run_demo.py` writes:

- `event_trace.jsonl`
- `claims.jsonl`
- `neighbor_trace.json`
- `reconstructed_claim_dag.json`
- `cascade_summary.json`
- `top_k_contribution_metrics.json`

The JSON outputs are generated artifacts and are ignored by Git.
