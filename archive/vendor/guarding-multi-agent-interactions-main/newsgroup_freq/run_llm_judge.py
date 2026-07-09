"""
run_llm_judge.py

Test script for running LLM judge on the NewsGroup Frequency problem.
"""

import asyncio
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.datasets import fetch_20newsgroups

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from general_agents.core.environment import MultiAgentEnvironment
from general_agents.problems.newsgroup_frequency import NewsGroupFrequencyProblem
from general_agents.policies.agent_policy import LLMAgentPolicy, cleanup_llm_clients
from general_agents.analysis.error_detection.llm_judge import LLMJudge
from general_agents.viz.viz_interactive import create_interactive_viz
from general_agents.viz.viz_realtime import RealtimeDIGVisualizer


def load_20ng_all_standardized(
    remove=("headers", "footers", "quotes"),
    shuffle: bool = True,
    seed: int = 0,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    bunch = fetch_20newsgroups(subset="all", remove=remove, shuffle=False)
    categories = list(bunch.target_names)

    docs: List[Dict[str, Any]] = []
    for i, text in enumerate(bunch.data):
        label_idx = int(bunch.target[i])
        docs.append(
            {
                "doc_id": f"all_{i}",
                "category": categories[label_idx],  # stored ONLY for evaluation
                "text": text,
            }
        )

    if shuffle:
        rng = np.random.default_rng(seed)
        rng.shuffle(docs)

    return docs, categories


async def test_llm_judge_newsgroup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("experiment_results_newsgroup") / "llm_judege_test" / f"demo_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    changelog_filename = output_dir / "changelog.json"
    html_filename = output_dir / "interactive_dig.html"
    fig_filename = output_dir / "realtime_dig_final.png"
    summary_filename = output_dir / "summary.json"

    # ----------------------------
    # Config
    # ----------------------------
    seed = 0
    problem_size = 150
    timeout_seconds = 180.0
    num_agents = 6

    print("=" * 60)
    print("LLM JUDGE TEST (NEWSGROUP) — TIMESTAMPED RUN")
    print("=" * 60)
    print(f"Results folder: {output_dir}")
    print(f"Docs: {problem_size}, Agents: {num_agents}, Timeout: {timeout_seconds:.0f}s")
    print("=" * 60)

    # Load & sample docs
    print("Loading 20 Newsgroups dataset...")
    docs_all, categories = load_20ng_all_standardized(shuffle=True, seed=seed)
    docs = docs_all[:problem_size]

    # Create problem
    print("Creating test problem...")
    problem = NewsGroupFrequencyProblem(docs, categories)

    # Create agents
    print("Creating agents...")
    agents = {f"Agent{i}": LLMAgentPolicy(f"Agent{i}") for i in range(1, num_agents + 1)}

    # Initialize LLM judge
    print("Initializing LLM judge...")
    llm_judge = LLMJudge(
        check_interval_activations=5,
        enable_intervention=True,
    )

    # Initialize realtime viz
    print("Initializing realtime visualization...")
    realtime_viz = RealtimeDIGVisualizer(update_interval=500)
    realtime_viz.start(block=False)

    # Create environment
    print("Creating environment...")
    env = MultiAgentEnvironment(
        problem=problem,
        agents=agents,
        enable_intervention=False,  # Let LLM judge handle interventions
        llm_judge=llm_judge,
        realtime_dig_viz=realtime_viz,
    )

    # Run experiment
    print("\n" + "=" * 60)
    print("Running experiment with LLM judge (NEWSGROUP)...")
    print("=" * 60)

    start_time = time.time()
    dig, winner, num_activations, timed_out = await env.run(timeout_seconds=timeout_seconds)
    runtime = time.time() - start_time

    # Cleanup
    await cleanup_llm_clients()

    # Evaluate
    eval_result = problem.evaluate_solution(dig)

    # Print summary
    print(f"\n[DONE] Run complete!")
    print(f"  Valid: {eval_result.get('valid')}, Correct: {eval_result.get('correct')}, "
          f"{eval_result.get('metric_name', 'error')}: {eval_result.get('error', float('inf')):.2f}")
    print(f"  Runtime: {runtime:.2f}s")
    print(f"  Timed out: {timed_out}")
    print(f"  Total activations: {num_activations}")

    if getattr(dig, "detection_stats", None) and dig.detection_stats:
        print(f"\nDetected errors: {dict(dig.detection_stats)}")
    if getattr(dig, "intervention_stats", None) and dig.intervention_stats:
        print(f"Interventions applied: {dict(dig.intervention_stats)}")

    efficiency = dig.get_efficiency_metrics()
    print(f"\nEfficiency:")
    print(f"  Elapsed time: {efficiency['elapsed_time']:.1f}s")
    print(f"  Activation time: {efficiency['activation_time']:.1f}s")
    print(f"  Num activations: {efficiency['num_activations']}")

    # ----------------------------
    # Save artifacts (match demo)
    # ----------------------------
    print(f"\n[SAVE] Saving results to {output_dir}...")

    # 1) DIG changelog
    dig.save_changelog(str(changelog_filename))
    print(f"  - Changelog: {changelog_filename.name}")

    # 2) Interactive HTML
    create_interactive_viz(dig, str(html_filename))
    print(f"  - Interactive viz: {html_filename.name}")

    # 3) Final realtime figure
    if hasattr(realtime_viz, "fig") and realtime_viz.fig is not None:
        realtime_viz.fig.savefig(str(fig_filename), dpi=150, bbox_inches="tight")
        print(f"  - Realtime figure: {fig_filename.name}")

    # 4) Summary json (useful for tables/aggregation)
    summary = {
        "timestamp": timestamp,
        "seed": seed,
        "doc_count": problem_size,
        "num_agents": num_agents,
        "timeout_seconds": timeout_seconds,
        "runtime_seconds": runtime,
        "timed_out": bool(timed_out),
        "num_activations": int(num_activations),
        "efficiency": efficiency,
        "eval_result": eval_result,
        "detection_stats": dict(getattr(dig, "detection_stats", {}) or {}),
        "intervention_stats": dict(getattr(dig, "intervention_stats", {}) or {}),
    }
    summary_filename.write_text(json.dumps(summary, indent=2))
    print(f"  - Summary: {summary_filename.name}")

    print(f"\n[SUMMARY]")
    print(f"  Results saved to: {output_dir}")
    print(f"  Total changes: {len(getattr(dig, 'changelog', []))}")

    # Optional: open in browser automatically
    print(f"\n[Browser] Opening interactive visualization...")
    webbrowser.open(f"file://{html_filename.absolute()}")

    print("\nDone! Close the matplotlib window when finished.")
    realtime_viz.wait_for_close()

    return dig, eval_result


if __name__ == "__main__":
    asyncio.run(test_llm_judge_newsgroup())
