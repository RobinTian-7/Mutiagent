#!/usr/bin/env python3
"""Minimal topology comparison demo.

Runs the same mock multi-agent protocol across communication topologies and
prints each round's physical neighbors. Outputs are written per topology under
the selected output directory.

Usage:
    python examples/compare_topologies.py
    python examples/compare_topologies.py --topologies static_exponential one_peer_exponential
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reconstruction.cascades import extract_cascades
from src.routing.claim_router import ReinforcedRouter
from src.schemas.claims import Claim
from src.schemas.events import Event
from src.simulation.workflow import run_simulation
from src.topology import create_topology, topology_names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare physical topologies")
    parser.add_argument("--agents", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--beta", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="examples/output/topology_comparison")
    parser.add_argument(
        "--topologies",
        nargs="+",
        choices=topology_names(),
        default=topology_names(),
    )
    return parser.parse_args()


def _coerce_claims(raw: list) -> list[Claim]:
    return [Claim(**claim) if isinstance(claim, dict) else claim for claim in raw]


def _coerce_events(raw: list) -> list[Event]:
    return [Event(**event) if isinstance(event, dict) else event for event in raw]


def _write_jsonl(path: Path, records: list) -> None:
    with open(path, "w") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")


def run_topology(topo_name: str, args: argparse.Namespace) -> dict:
    random.seed(args.seed)
    np.random.seed(args.seed)

    agent_ids = [f"agent_{i}" for i in range(args.agents)]
    topology = create_topology(topo_name, agent_ids)
    result = run_simulation(
        agent_ids=agent_ids,
        topology=topology,
        router=ReinforcedRouter(beta=args.beta),
        max_rounds=args.rounds,
        dti_enabled=False,
    )

    claims = _coerce_claims(result["claims"])
    events = _coerce_events(result["events"])
    cascades = extract_cascades(claims, events)
    neighbor_trace = result.get("neighbor_trace", [])

    output_dir = Path(args.output_dir) / topo_name
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "event_trace.jsonl", events)
    _write_jsonl(output_dir / "claims.jsonl", claims)
    with open(output_dir / "neighbor_trace.json", "w") as f:
        json.dump(neighbor_trace, f, indent=2)

    visible_counts = [len(row["visible_claim_ids"]) for row in neighbor_trace]
    return {
        "topology": topo_name,
        "events": len(events),
        "claims": len(claims),
        "cascades": len(cascades),
        "max_cascade": max((c.size for c in cascades), default=0),
        "mean_visible_claims": (
            sum(visible_counts) / len(visible_counts) if visible_counts else 0.0
        ),
        "neighbor_trace": neighbor_trace,
    }


def print_neighbors(summary: dict) -> None:
    print(f"\n=== {summary['topology']} ===")
    current_round = None
    for row in summary["neighbor_trace"]:
        if row["round"] != current_round:
            current_round = row["round"]
            print(f"Round {current_round}")
        neighbors = ", ".join(row["neighbors"]) or "-"
        print(f"  {row['agent_id']} -> [{neighbors}]")


def main() -> None:
    args = parse_args()
    summaries = []
    for topo_name in args.topologies:
        summary = run_topology(topo_name, args)
        summaries.append(summary)
        print_neighbors(summary)

    print("\n--- Propagation Summary ---")
    header = (
        f"{'Topology':<24} {'Events':<8} {'Claims':<8} {'Cascades':<9} "
        f"{'MaxCasc':<8} {'MeanVisible':<12}"
    )
    print(header)
    print("-" * len(header))
    for summary in summaries:
        print(
            f"{summary['topology']:<24} {summary['events']:<8} "
            f"{summary['claims']:<8} {summary['cascades']:<9} "
            f"{summary['max_cascade']:<8} {summary['mean_visible_claims']:<12.2f}"
        )

    print(f"\nOutputs written under {args.output_dir}/")


if __name__ == "__main__":
    main()
