"""
run_experiments.py

Run experiments for the NewsGroup Frequency problem with/without intervention.
"""

import asyncio
import json
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
from sklearn.datasets import fetch_20newsgroups

# Suppress asyncio cleanup warnings
warnings.filterwarnings("ignore", message=".*Event loop is closed.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="asyncio")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from general_agents.agent_policy import LLMAgentPolicy, cleanup_llm_clients
from general_agents.environment import MultiAgentEnvironment
from general_agents.problems.newsgroup_frequency import NewsGroupFrequencyProblem
from general_agents.viz.viz_interactive import create_interactive_viz


def load_20ng_all_standardized(
    remove=("headers", "footers", "quotes"),
    shuffle: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Returns:
      - documents: List[{"doc_id": str, "category": str, "text": str}]
      - categories: List[str] length 20
    """
    bunch = fetch_20newsgroups(subset="all", remove=remove, shuffle=shuffle)
    categories = list(bunch.target_names)

    documents: List[Dict[str, Any]] = []
    for i, text in enumerate(bunch.data):
        label_idx = int(bunch.target[i])
        documents.append(
            {
                "doc_id": f"all_{i}",
                "category": categories[label_idx],
                "text": text,
            }
        )
    return documents, categories


async def run_single_async(problem, agents, timeout, enable_intervention):
    """Run single experiment async."""
    env = MultiAgentEnvironment(
        problem=problem,
        agents=agents,
        enable_intervention=enable_intervention,
    )
    result = await env.run(timeout_seconds=timeout)
    await cleanup_llm_clients()
    return result


def run_single(
    doc_count: int,
    num_agents: int,
    timeout: float,
    enable_intervention: bool,
    docs_all: List[Dict[str, Any]],
    categories: List[str],
    seed: int = 0,
    shuffle_docs: bool = True,
) -> Tuple[NewsGroupFrequencyProblem, Any, Dict[str, Any], float, bool]:
    """
    Run a single experiment. Returns (problem, dig, eval_result, runtime, timed_out).

    eval_result expected shape (mirrors CountFrequency usage):
      {
        "metric_name": str,
        "error": float,
        "valid": bool,
        "correct": bool,
        "solution": ...,
        "reference": ...,
      }
    """
    # Sample docs
    docs = list(docs_all)
    if shuffle_docs:
        rng = np.random.default_rng(seed)
        rng.shuffle(docs)
    docs = docs[:doc_count]

    problem = NewsGroupFrequencyProblem(docs, categories)

    agents = {f"Agent{i}": LLMAgentPolicy(f"Agent{i}") for i in range(1, num_agents + 1)}

    start = time.time()
    dig, winner, num_act, timed_out = asyncio.run(
        run_single_async(problem, agents, timeout, enable_intervention)
    )
    runtime = time.time() - start

    # Evaluate via problem method (same pattern as CountFrequency script)
    eval_result = problem.evaluate_solution(dig)

    return problem, dig, eval_result, runtime, timed_out


# Alias for backward compatibility
run_single_experiment = run_single


def run_experiments(
    doc_count: int = 30,
    num_agents: int = 3,
    timeout: float = 120.0,
    num_trials: int = 3,
    compare: bool = True,
    shuffle_docs: bool = True,
):
    """
    Run experiments comparing with/without intervention for NewsGroupFrequencyProblem.
    """
    # Load dataset once
    docs_all, categories = load_20ng_all_standardized()

    # Setup output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("experiment_results_newsgroup") / f"run_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("EXPERIMENT (NEWSGROUP): Comparing WITH vs WITHOUT Intervention")
    print("=" * 60)
    print(
        f"Doc count: {doc_count}, Agents: {num_agents}, Timeout: {timeout}s, "
        f"Trials: {num_trials}, ShuffleDocs: {shuffle_docs}"
    )
    print(f"Output: {output_dir}")
    print("=" * 60)

    modes = [False, True] if compare else [True]
    results = {
        "config": {
            "doc_count": doc_count,
            "num_agents": num_agents,
            "timeout": timeout,
            "num_trials": num_trials,
            "shuffle_docs": shuffle_docs,
        },
        "no_intervention": [],
        "with_intervention": [],
    }

    metric_name: Optional[str] = None

    for enable_intervention in modes:
        label = "WITH" if enable_intervention else "WITHOUT"
        key = "with_intervention" if enable_intervention else "no_intervention"

        print(f"\n{'='*60}")
        print(f"Running {num_trials} trials {label} intervention...")
        print(f"{'='*60}")

        for trial in range(1, num_trials + 1):
            print(f"\n[Trial {trial}/{num_trials}]")

            problem, dig, eval_result, runtime, timed_out = run_single(
                doc_count=doc_count,
                num_agents=num_agents,
                timeout=timeout,
                enable_intervention=enable_intervention,
                docs_all=docs_all,
                categories=categories,
                seed=trial - 1,
                shuffle_docs=shuffle_docs,
            )

            metric_name = eval_result.get("metric_name", "Error")
            error = eval_result.get("error", float("inf"))
            valid = bool(eval_result.get("valid", False))
            correct = bool(eval_result.get("correct", False))
            solution = eval_result.get("solution", {})
            reference = eval_result.get("reference", {})

            efficiency = dig.get_efficiency_metrics() if hasattr(dig, "get_efficiency_metrics") else {
                "elapsed_time": runtime,
                "activation_time": None,
                "num_activations": None,
            }

            # Save visualization
            suffix = "int" if enable_intervention else "no_int"
            viz_file = output_dir / f"viz_trial{trial}_{suffix}.html"
            create_interactive_viz(dig, str(viz_file))

            # Log
            err_print = error if error is not None else float("inf")
            print(
                f"  Valid: {valid}, Correct: {correct}, {metric_name}: {err_print:.2f}, "
                f"Runtime: {runtime:.1f}s, Timeout: {timed_out}"
            )
            if efficiency.get("num_activations") is not None:
                print(
                    f"  Elapsed: {efficiency['elapsed_time']:.1f}s, "
                    f"Activation: {efficiency['activation_time']:.1f}s, "
                    f"Activations: {efficiency['num_activations']}"
                )
            print(f"  Solution:  {solution}")
            print(f"  Reference: {reference}")

            if getattr(dig, "detection_stats", None):
                print(f"  Detected errors: {dict(dig.detection_stats)}")
            if getattr(dig, "intervention_stats", None):
                print(f"  Interventions: {dict(dig.intervention_stats)}")

            results[key].append(
                {
                    "trial": trial,
                    "error": None if error == float("inf") else error,  # JSON no Infinity
                    "runtime": runtime,
                    "elapsed_time": efficiency.get("elapsed_time"),
                    "activation_time": efficiency.get("activation_time"),
                    "num_activations": efficiency.get("num_activations"),
                    "timed_out": timed_out,
                    "valid": valid,
                    "correct": correct,
                    "detections": dict(getattr(dig, "detection_stats", {})) if getattr(dig, "detection_stats", None) else {},
                    "interventions": dict(getattr(dig, "intervention_stats", {})) if getattr(dig, "intervention_stats", None) else {},
                }
            )

    results["config"]["metric_name"] = metric_name

    # Summary (same as CountFrequency script)
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for key, label in [("no_intervention", "WITHOUT"), ("with_intervention", "WITH")]:
        trials = results.get(key, [])
        if not trials:
            continue

        correct_trials = [t for t in trials if t["correct"]]
        valid_trials = [t for t in trials if t["valid"]]
        correct_rate = len(correct_trials) / len(trials) if trials else 0
        valid_rate = len(valid_trials) / len(trials) if trials else 0

        trials_with_error = [t for t in valid_trials if t["error"] is not None]
        avg_error = (
            sum(t["error"] for t in trials_with_error) / len(trials_with_error)
            if trials_with_error
            else float("inf")
        )
        avg_runtime = sum(t["runtime"] for t in trials) / len(trials) if trials else 0

        avg_elapsed = (
            sum((t["elapsed_time"] or 0) for t in trials) / len(trials)
            if trials
            else 0
        )
        # activation_time might be None if not provided
        activation_times = [t["activation_time"] for t in trials if t["activation_time"] is not None]
        avg_activation = sum(activation_times) / len(activation_times) if activation_times else None

        num_acts = [t["num_activations"] for t in trials if t["num_activations"] is not None]
        avg_num_activations = sum(num_acts) / len(num_acts) if num_acts else None

        all_detections: Dict[str, int] = {}
        all_interventions: Dict[str, int] = {}
        for t in trials:
            for k2, v2 in t.get("detections", {}).items():
                all_detections[k2] = all_detections.get(k2, 0) + int(v2)
            for k2, v2 in t.get("interventions", {}).items():
                all_interventions[k2] = all_interventions.get(k2, 0) + int(v2)

        print(f"\n{label} intervention:")
        print(f"  Correct solutions: {len(correct_trials)}/{len(trials)} ({correct_rate:.0%})")
        print(f"  Valid solutions: {len(valid_trials)}/{len(trials)} ({valid_rate:.0%})")
        print(f"  Avg {metric_name}: {avg_error:.2f}")
        print(f"  Avg Elapsed: {avg_elapsed:.1f}s")
        if avg_activation is not None:
            print(f"  Avg Activation: {avg_activation:.1f}s")
        if avg_num_activations is not None:
            print(f"  Avg #Activations: {avg_num_activations:.1f}")
        if all_detections:
            print(f"  Detected errors: {all_detections}")
        if all_interventions:
            print(f"  Interventions applied: {all_interventions}")

    # Save results
    results_file = output_dir / "results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Results saved to: {results_file}")
    print(f"Visualizations saved to: {output_dir}")
    print("=" * 60)

    return str(results_file)


if __name__ == "__main__":
    run_experiments(
        doc_count=100,
        num_agents=3,
        timeout=60.0,
        num_trials=1,
        compare=True,
        shuffle_docs=True,
    )
