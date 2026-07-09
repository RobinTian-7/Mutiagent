# archive/ — frozen history

Nothing here is on any import path and nothing in `exp-graph/` or `masbench/`
depends on it. Kept for provenance; treat as read-only. If you need one of
these lines of work again, fork it out rather than reviving it in place.

| subdir | was (repo root) | what it is |
| --- | --- | --- |
| `legacy-agent-graph/` | `src/`, `tests/`, `examples/`, `configs/`, `summarize/`, `run_*.py`, `pyproject.toml`, `README*.md`, `mutiplan.md`, `docs/{architecture,assumptions,paper_to_code_mapping}*` | The original "Agent Expressional Graph" prototype: reproduction scaffold for *Laws of Collective Cognition in LLM Multi-Agent Systems* (claim DAG, cascade reconstruction, DTI) plus the early Count-Frequency topology-sweep drivers. Superseded by `exp-graph/` + `masbench/`. |
| `dig-repro/` | `dig-repro/` | Separate small reproduction (own README/docs/examples). |
| `vendor/guarding-multi-agent-interactions-main/` | `guarding-multi-agent-interactions-main/` | Vendored snapshot of an external repo, reference only. |
| `lab_records/` | `lab_records/` | Frozen judge/ledger JSONs from the self-evolution studies (confirmatory runs, N=24 meta-analysis draws). The reports in `masbench/docs/` cite these — do not edit. |

Deleted from this branch entirely (recoverable from git history on
`selfevolve-lab` / `main`): `exp-graph/runs/` (~186 MB of evolution run
artifacts) and the root `*_results/` + `cf_topology_sweep_*` output dirs
(~580 MB of Count-Frequency sweep outputs).
