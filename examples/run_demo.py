#!/usr/bin/env python3
"""Minimal runnable demo: 8 agents, chain/star/mesh, DTI on/off.

Outputs to examples/output/:
  - event_trace.jsonl
  - claims.jsonl
  - reconstructed_claim_dag.json
  - cascade_summary.json
  - top_k_contribution_metrics.json

Usage:
    python examples/run_demo.py
    python examples/run_demo.py --topology mesh --dti
    python examples/run_demo.py --topology star --rounds 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.metrics import (
    compute_cascade_sizes,
    compute_contradiction_burst_sizes,
    compute_merge_fan_in,
    compute_revision_wave_lengths,
    compute_tce,
    compute_top_k_contribution,
    export_contribution_metrics,
)
from src.interventions.dti import DTIConfig, DTIMonitor
from src.reconstruction.cascades import extract_cascades, export_cascade_summary
from src.reconstruction.claim_dag import export_claim_dag, reconstruct_claim_dag
from src.routing.claim_router import ReinforcedRouter
from src.schemas.claims import Claim
from src.schemas.events import Event
from src.simulation.workflow import run_simulation
from src.topology import ChainTopology, MeshTopology, StarTopology

TOPOLOGY_MAP = {
    "chain": ChainTopology,
    "star": StarTopology,
    "mesh": MeshTopology,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run coordination cascade demo")
    parser.add_argument("--agents", type=int, default=8, help="Number of agents")
    parser.add_argument(
        "--topology", choices=["chain", "star", "mesh"], default="chain"
    )
    parser.add_argument("--rounds", type=int, default=20, help="Execution rounds")
    parser.add_argument("--beta", type=float, default=0.15, help="Reinforcement β")
    parser.add_argument("--dti", action="store_true", help="Enable DTI")
    parser.add_argument("--output-dir", default="examples/output", help="Output directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    import random
    import numpy as np

    random.seed(args.seed)
    np.random.seed(args.seed)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    agent_ids = [f"agent_{i}" for i in range(args.agents)]
    topology_cls = TOPOLOGY_MAP[args.topology]
    topology = topology_cls(agent_ids)
    router = ReinforcedRouter(beta=args.beta)

    dti_monitor = None
    if args.dti:
        dti_monitor = DTIMonitor(DTIConfig(beta_c=1.0, a_c=0.5, delta_c=2.0))

    print(f"Running: {args.agents} agents, {args.topology} topology, "
          f"{'DTI ON' if args.dti else 'DTI OFF'}, {args.rounds} rounds")

    result = run_simulation(
        agent_ids=agent_ids,
        topology=topology,
        router=router,
        max_rounds=args.rounds,
        dti_enabled=args.dti,
        dti_monitor=dti_monitor,
    )

    # Parse results
    claims = []
    for c in result["claims"]:
        claims.append(Claim(**c) if isinstance(c, dict) else c)

    events = []
    for e in result["events"]:
        events.append(Event(**e) if isinstance(e, dict) else e)

    print(f"Generated {len(events)} events, {len(claims)} claims")

    # Write event_trace.jsonl
    with open(output_dir / "event_trace.jsonl", "w") as f:
        for e in events:
            f.write(e.model_dump_json() + "\n")

    # Write claims.jsonl
    with open(output_dir / "claims.jsonl", "w") as f:
        for c in claims:
            f.write(c.model_dump_json() + "\n")

    # Reconstruct claim DAG
    dag = reconstruct_claim_dag(claims)
    dag_export = export_claim_dag(dag)
    with open(output_dir / "reconstructed_claim_dag.json", "w") as f:
        json.dump(dag_export, f, indent=2, default=str)
    print(f"Claim DAG: {dag_export['num_nodes']} nodes, {dag_export['num_edges']} edges")

    # Extract cascades
    cascades = extract_cascades(claims, events)
    cascade_data = export_cascade_summary(cascades)
    with open(output_dir / "cascade_summary.json", "w") as f:
        json.dump(cascade_data, f, indent=2, default=str)
    print(f"Cascades: {len(cascades)} total")

    # Compute metrics
    sizes = compute_cascade_sizes(cascades)
    tce_values = compute_tce(cascades)
    revision_lengths = compute_revision_wave_lengths(claims)
    contradiction_sizes = compute_contradiction_burst_sizes(claims)
    merge_fanins = compute_merge_fan_in(events)

    contributions = compute_top_k_contribution(claims, cascades, agent_ids=agent_ids)
    contrib_export = export_contribution_metrics(contributions)
    with open(output_dir / "top_k_contribution_metrics.json", "w") as f:
        json.dump(contrib_export, f, indent=2, default=str)

    # Summary statistics
    print("\n--- Summary Statistics ---")
    print(f"Cascade sizes: min={min(sizes)}, max={max(sizes)}, "
          f"mean={sum(sizes)/len(sizes):.1f}" if sizes else "No cascades")
    print(f"TCE values: min={min(tce_values)}, max={max(tce_values)}, "
          f"mean={sum(tce_values)/len(tce_values):.1f}" if tce_values else "No TCE")
    if revision_lengths:
        print(f"Revision waves: {len(revision_lengths)} chains, "
              f"mean length={sum(revision_lengths)/len(revision_lengths):.1f}")
    if contradiction_sizes:
        print(f"Contradiction bursts: {len(contradiction_sizes)} bursts, "
              f"mean size={sum(contradiction_sizes)/len(contradiction_sizes):.1f}")
    if merge_fanins:
        print(f"Merge fan-in: {len(merge_fanins)} merges, "
              f"mean fan-in={sum(merge_fanins)/len(merge_fanins):.1f}")

    # Top-k summary
    if contrib_export:
        top10_values = [m.get("top_10pct", 0) for m in contrib_export]
        mean_top10 = sum(top10_values) / len(top10_values) if top10_values else 0
        print(f"Top-10% contribution share (mean): {mean_top10:.3f}")

    print(f"\nOutputs written to {output_dir}/")


if __name__ == "__main__":
    main()
