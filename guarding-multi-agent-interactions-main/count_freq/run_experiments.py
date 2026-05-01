"""
run_experiments.py

Run experiments comparing WITH and WITHOUT intervention.
"""

import asyncio
import json
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

# Suppress asyncio cleanup warnings
warnings.filterwarnings('ignore', message='.*Event loop is closed.*')
warnings.filterwarnings('ignore', category=RuntimeWarning, module='asyncio')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from general_agents.policies.agent_policy import LLMAgentPolicy, cleanup_llm_clients
from general_agents.core.environment import MultiAgentEnvironment
from general_agents.problems.count_frequency import CountFrequencyProblem
from general_agents.viz.viz_interactive import create_interactive_viz
from general_agents.analysis.error_detection.llm_judge import LLMJudge


async def run_single_async(problem, agents, timeout, enable_intervention, use_llm_judge=False, realtime_dig_viz=None):
    """Run single experiment async."""
    llm_judge = None
    if use_llm_judge:
        llm_judge = LLMJudge(
            check_interval_activations=5,
            enable_intervention=enable_intervention,
        )
    
    env = MultiAgentEnvironment(
        problem=problem,
        agents=agents,
        enable_intervention=enable_intervention and not use_llm_judge,  # LLM judge handles intervention if enabled
        llm_judge=llm_judge,
        realtime_dig_viz=realtime_dig_viz,
    )
    result = await env.run(timeout_seconds=timeout)
    await cleanup_llm_clients()
    return result


def run_single(list_size, num_agents, timeout, enable_intervention, use_llm_judge=False, realtime_dig_viz=None):
    """Run a single experiment. Returns (problem, dig, eval_result, runtime, timed_out)."""
    # Create problem
    base = [1, 2, 2, 3, 3, 3, 7, 7, 1, 5, 5, 5, 5]
    example_list = (base * ((list_size // len(base)) + 1))[:list_size]
    problem = CountFrequencyProblem(example_list)
    
    # Create agents
    agents = {f"Agent{i}": LLMAgentPolicy(f"Agent{i}") for i in range(1, num_agents + 1)}
    
    # Run
    start = time.time()
    dig, winner, num_act, timed_out = asyncio.run(
        run_single_async(problem, agents, timeout, enable_intervention, use_llm_judge, realtime_dig_viz)
    )
    runtime = time.time() - start
    
    # Evaluate using problem's method
    eval_result = problem.evaluate_solution(dig)
    
    return problem, dig, eval_result, runtime, timed_out


# Alias for backward compatibility
run_single_experiment = run_single


def run_experiments(
    list_size: int = 500,
    num_agents: int = 3,
    timeout: float = 60.0,
    num_trials: int = 3,
    compare: bool = True,
):
    """Run experiments comparing with/without intervention."""
    
    # Setup output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("experiment_results") / f"run_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("EXPERIMENT: Comparing WITH vs WITHOUT Intervention")
    print("=" * 60)
    print(f"List size: {list_size}, Agents: {num_agents}, Timeout: {timeout}s, Trials: {num_trials}")
    print(f"Output: {output_dir}")
    print("=" * 60)
    
    modes = [False, True] if compare else [True]
    results = {"config": {"list_size": list_size, "num_agents": num_agents, 
                          "timeout": timeout, "num_trials": num_trials},
               "no_intervention": [], "with_intervention": []}
    
    metric_name = None  # Will be set from problem
    
    for enable_intervention in modes:
        label = "WITH" if enable_intervention else "WITHOUT"
        key = "with_intervention" if enable_intervention else "no_intervention"
        
        print(f"\n{'='*60}")
        print(f"Running {num_trials} trials {label} intervention...")
        print(f"{'='*60}")
        
        for trial in range(1, num_trials + 1):
            print(f"\n[Trial {trial}/{num_trials}]")
            
            problem, dig, eval_result, runtime, timed_out = run_single(
                list_size, num_agents, timeout, enable_intervention
            )
            
            # Get metric name from problem
            metric_name = eval_result["metric_name"]
            error = eval_result["error"]
            valid = eval_result["valid"]
            correct = eval_result["correct"]
            solution = eval_result["solution"]
            reference = eval_result["reference"]
            
            # Get efficiency metrics from DIG
            efficiency = dig.get_efficiency_metrics()
            
            # Save visualization
            suffix = "int" if enable_intervention else "no_int"
            viz_file = output_dir / f"viz_trial{trial}_{suffix}.html"
            create_interactive_viz(dig, str(viz_file))
            
            # Log
            print(f"  Valid: {valid}, Correct: {correct}, {metric_name}: {error:.2f}, Runtime: {runtime:.1f}s, Timeout: {timed_out}")
            print(f"  Elapsed: {efficiency['elapsed_time']:.1f}s, Activation: {efficiency['activation_time']:.1f}s, Activations: {efficiency['num_activations']}")
            print(f"  Solution:  {solution}")
            print(f"  Reference: {reference}")
            if dig.detection_stats:
                print(f"  Detected errors: {dict(dig.detection_stats)}")
            if dig.intervention_stats:
                print(f"  Interventions: {dict(dig.intervention_stats)}")
            
            results[key].append({
                "trial": trial, 
                "error": error if error != float('inf') else None,  # JSON doesn't support Infinity
                "runtime": runtime,
                "elapsed_time": efficiency["elapsed_time"],
                "activation_time": efficiency["activation_time"],
                "num_activations": efficiency["num_activations"],
                "timed_out": timed_out, "valid": valid, "correct": correct,
                "detections": dict(dig.detection_stats) if dig.detection_stats else {},
                "interventions": dict(dig.intervention_stats) if dig.intervention_stats else {}
            })
    
    # Store metric name in results
    results["config"]["metric_name"] = metric_name
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for key, label in [("no_intervention", "WITHOUT"), ("with_intervention", "WITH")]:
        trials = results[key]
        if not trials:
            continue  # Skip if no trials for this mode
        
        correct_trials = [t for t in trials if t["correct"]]  # Exact match
        valid_trials = [t for t in trials if t["valid"]]  # Got a solution
        correct_rate = len(correct_trials) / len(trials) if trials else 0
        valid_rate = len(valid_trials) / len(trials) if trials else 0
        # Only average over trials with valid error (not None)
        trials_with_error = [t for t in valid_trials if t["error"] is not None]
        avg_error = sum(t["error"] for t in trials_with_error) / len(trials_with_error) if trials_with_error else float('inf')
        avg_runtime = sum(t["runtime"] for t in trials) / len(trials) if trials else 0
        
        # Efficiency metrics
        avg_elapsed = sum(t["elapsed_time"] for t in trials) / len(trials) if trials else 0
        avg_activation = sum(t["activation_time"] for t in trials) / len(trials) if trials else 0
        avg_num_activations = sum(t["num_activations"] for t in trials) / len(trials) if trials else 0
        
        # Aggregate detections and interventions across all trials
        all_detections = {}
        all_interventions = {}
        for t in trials:
            for k, v in t.get("detections", {}).items():
                all_detections[k] = all_detections.get(k, 0) + v
            for k, v in t.get("interventions", {}).items():
                all_interventions[k] = all_interventions.get(k, 0) + v
        
        print(f"\n{label} intervention:")
        print(f"  Correct solutions: {len(correct_trials)}/{len(trials)} ({correct_rate:.0%})")
        print(f"  Valid solutions: {len(valid_trials)}/{len(trials)} ({valid_rate:.0%})")
        print(f"  Avg {metric_name}: {avg_error:.2f}")
        print(f"  Avg Elapsed: {avg_elapsed:.1f}s, Avg Activation: {avg_activation:.1f}s, Avg #Activations: {avg_num_activations:.1f}")
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
        list_size=500,
        num_agents=3,
        timeout=60.0,
        num_trials=1,
        compare=True,  # Only run WITH intervention (like demo)
    )
