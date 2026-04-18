# Agent Expressional Graph

Runnable reproduction scaffold for the paper "Laws of Collective Cognition in LLM Multi-Agent Systems" (arXiv 2604.02674v1).

This repository prioritizes structural fidelity over benchmark-level score replication. It implements event-trace-driven multi-agent coordination with a physical communication topology, a separate logical Claim DAG, cascade reconstruction, reinforced claim routing, and Deficit-Triggered Integration (DTI).

## Paper Sources

The implementation was mapped from the TeX source under:

```bash
files/arXiv-2604.02674v1/sec/
```

See:

- `docs/paper_to_code_mapping.md` for paper evidence and code mapping.
- `docs/assumptions.md` for implementation choices not fully specified in the paper.
- `docs/architecture.md` for the runtime design.

## Repository Layout

```text
src/schemas/          Claim, Event, Subtask, Cascade schemas
src/topology/         Chain, star, mesh, and exponential communication topologies
src/routing/          Topology visibility and reinforced claim routing
src/simulation/       LangGraph orchestration workflow
src/interventions/    Deficit-Triggered Integration
src/reconstruction/   Claim DAG, subtask tree, and cascade reconstruction
src/analysis/         TCE, cascade size, top-k contribution, event metrics
examples/             Runnable demo and DTI comparison script
tests/                Unit and smoke tests
configs/              Default experiment configuration
```

Local paper/reference files are kept in `files/` and ignored by Git.

## Setup

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional analysis dependencies:

```bash
pip install -e ".[analysis]"
```

## Run Tests

```bash
pytest
```

Current suite covers schema validation, Claim DAG reconstruction, cascade extraction, topology neighbor behavior, routing behavior, DTI trigger/no-trigger paths, and an end-to-end smoke run.

## Run the Minimal Demo

Default run:

```bash
python examples/run_demo.py
```

Mesh topology with DTI:

```bash
python examples/run_demo.py --topology mesh --dti --agents 8 --rounds 20
```

One-peer exponential topology with neighbor schedule output:

```bash
python examples/run_demo.py --topology one_peer_exponential --agents 8 --rounds 4 --print-neighbors
```

Compare physical propagation behavior across topologies:

```bash
python examples/compare_topologies.py --agents 8 --rounds 4
```

Generated outputs:

```text
examples/output/event_trace.jsonl
examples/output/claims.jsonl
examples/output/neighbor_trace.json
examples/output/reconstructed_claim_dag.json
examples/output/cascade_summary.json
examples/output/top_k_contribution_metrics.json
```

Compare DTI on/off qualitatively:

```bash
python examples/compare_dti.py
```

## Fidelity Boundary

### Paper-Faithful
- Claim DAG G = (C, E_c) reconstructed from parent_claim_ids (Sec 3.2)
- Cascades C_r = {c_i | root(c_i) = c_r} (Sec 3.2)
- Event types: propose, revise, contradict, merge, delegate (Table 1)
- Reinforced routing P(c_i) ∝ x_i(t)^β (Sec 4.2, Eq. 3)
- DTI per-cascade deficit monitoring with threshold trigger (Sec 6, Algorithm 1)
- All observables: TCE, cascade size, top-k contribution, revision waves, contradiction bursts, merge fan-in (Sec 3.3)
- Task tree / Claim DAG separation by design (Appendix B.1)
- Append-only traces as the primary runtime record (Appendix B.3)
- Static and one-peer exponential neighbor schedules are based on the communication topologies in arXiv 2110.13363.

### Assumption-Based
- Mock agent action selection (no real LLM calls) — Assumption A12
- Default β = 0.15 from paper's GPT-4o-mini estimate — Assumption A9
- DTI parameters (a_c, δ_c) use demo defaults — Assumption A10
- Exponential graphs are used only as physical neighbor communication schedules, not as Claim DAG or DTI replacements — Assumption A14
- One-peer exponential runs for non-power-of-two agent counts as an engineering mixing heuristic, without claiming the paper's exact averaging guarantee — Assumption A15
- Cross-root merges restricted to same cascade — Assumption A13

See [docs/assumptions.md](docs/assumptions.md) for the full registry.

### Future Work
- Real LLM-backed agents with structured prompts
- Benchmark-conditioned task expansion module (GAIA, SWE-bench, REALM, MultiAgentBench)
- Tree, hierarchical, sparse mesh, dynamic reputation topologies
- Baseline-estimated DTI parameters per condition class
- Statistical analysis pipeline (power-law fitting, CCDF plots, EVT scaling)
- Multi-seed experiment runner with aggregation
