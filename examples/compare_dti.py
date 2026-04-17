#!/usr/bin/env python3
"""Compare DTI on/off qualitatively across topologies.

Runs the simulation for each topology with and without DTI,
and prints a comparison table.

Usage:
    python examples/compare_dti.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.metrics import (
    compute_cascade_sizes,
    compute_merge_fan_in,
    compute_tce,
    compute_top_k_contribution,
)
from src.interventions.dti import DTIConfig, DTIMonitor
from src.reconstruction.cascades import extract_cascades
from src.routing.claim_router import ReinforcedRouter
from src.schemas.claims import Claim
from src.schemas.events import Event
from src.simulation.workflow import run_simulation
from src.topology import ChainTopology, MeshTopology, StarTopology

TOPOLOGIES = {
    "chain": ChainTopology,
    "star": StarTopology,
    "mesh": MeshTopology,
}


def run_condition(topo_name: str, dti: bool, seed: int = 42) -> dict:
    random.seed(seed)
    np.random.seed(seed)

    agent_ids = [f"agent_{i}" for i in range(8)]
    topology = TOPOLOGIES[topo_name](agent_ids)

    dti_monitor = None
    if dti:
        dti_monitor = DTIMonitor(DTIConfig(beta_c=1.0, a_c=0.5, delta_c=2.0))

    result = run_simulation(
        agent_ids=agent_ids,
        topology=topology,
        router=ReinforcedRouter(beta=0.15),
        max_rounds=20,
        dti_enabled=dti,
        dti_monitor=dti_monitor,
    )

    claims = [Claim(**c) if isinstance(c, dict) else c for c in result["claims"]]
    events = [Event(**e) if isinstance(e, dict) else e for e in result["events"]]
    cascades = extract_cascades(claims, events)
    sizes = compute_cascade_sizes(cascades)
    tce = compute_tce(cascades)
    fanins = compute_merge_fan_in(events)
    contrib = compute_top_k_contribution(claims, cascades, agent_ids=agent_ids)

    top10_vals = [m.get("top_10pct", 0) for m in contrib.values()]

    return {
        "n_events": len(events),
        "n_cascades": len(cascades),
        "max_cascade": max(sizes) if sizes else 0,
        "mean_cascade": sum(sizes) / len(sizes) if sizes else 0,
        "mean_tce": sum(tce) / len(tce) if tce else 0,
        "n_merges": len(fanins),
        "mean_fanin": sum(fanins) / len(fanins) if fanins else 0,
        "mean_top10": sum(top10_vals) / len(top10_vals) if top10_vals else 0,
    }


def main() -> None:
    print("=" * 80)
    print("DTI ON/OFF COMPARISON (8 agents, 20 rounds)")
    print("=" * 80)

    header = f"{'Topology':<10} {'DTI':<5} {'Events':<8} {'Cascades':<10} "
    header += f"{'MaxCasc':<9} {'MeanCasc':<10} {'Merges':<8} "
    header += f"{'MeanFanIn':<11} {'Top10%':<8}"
    print(header)
    print("-" * 80)

    for topo_name in TOPOLOGIES:
        for dti in [False, True]:
            m = run_condition(topo_name, dti)
            row = f"{topo_name:<10} {'ON' if dti else 'OFF':<5} "
            row += f"{m['n_events']:<8} {m['n_cascades']:<10} "
            row += f"{m['max_cascade']:<9} {m['mean_cascade']:<10.1f} "
            row += f"{m['n_merges']:<8} {m['mean_fanin']:<11.2f} "
            row += f"{m['mean_top10']:<8.3f}"
            print(row)

    print("\nPaper prediction: DTI should increase merge count and fan-in,")
    print("reduce top-k concentration, and preserve cascade structure.")


if __name__ == "__main__":
    main()
