# Error Taxonomy for Cooperative Multi-Agent Systems

This document defines a structural error taxonomy for cooperative multi-agent systems.
Errors are identified from observable interaction patterns in the Dynamic Interaction Graph (DIG),
independent of agent internals or task semantics.

---

## 1. Reachability and Completion Errors (Failures)

These errors indicate correctness violations. All reachable work must remain available until consumed,
and the system must emit exactly one completion event after all work is processed.

### 1.1 Early Termination
A completion event is emitted while some reachable work remains unconsumed.
This indicates dropped subproblems and incomplete execution.

### 1.2 Missing Completion
All reachable work has been consumed, but no completion event is emitted within a reasonable time window.
The system finishes computation but fails to terminate.

### 1.3 Orphaned Event
An event is generated but becomes unreachable before any activation consumes it.
This may be caused by invalid routing or premature discarding.

### 1.4 Deadlock
Reachable events or activations exist, but all agents wait indefinitely.
The interaction graph stops evolving despite unfinished work.

---

## 2. Progress Warnings (Risks)

These patterns indicate inefficiency or instability, but do not by themselves guarantee incorrect results.

### 2.1 Partial Aggregation
An activation aggregates only a strict subset of outputs from an earlier activation,
leaving remaining outputs reachable and unconsumed.

### 2.2 Repeated Rerouting
Events are forwarded across multiple activations without being consumed to produce downstream results.
This signals indecision or unclear task ownership.

### 2.3 Cross-Lineage Aggregation
An activation aggregates events whose causal lineages originate from different initial events.
Independent tasks may be incorrectly mixed.

### 2.4 Repeated Sub-Problem Solving
Multiple reducer activations generate overlapping subsolutions for the same subproblem,
resulting in redundant computation.

---

## Design Properties

- Structural and model-agnostic
- No access to agent reasoning required
- Suitable for real-time monitoring
- Supports explainable diagnosis and intervention

---

## Intended Use

This taxonomy supports:
- Monitoring emergent cooperation
- Early failure detection
- Structure-driven system healing
- Explainable debugging of multi-agent executions
