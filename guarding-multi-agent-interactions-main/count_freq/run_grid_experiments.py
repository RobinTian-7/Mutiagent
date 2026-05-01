"""
run_grid_experiments.py

Run experiments across a grid of configurations:
- Number of agents: 1, 2, 5, 10, 20
- Problem sizes: 10, 100, 200, 500
- With and without intervention
"""

import json
import time
from datetime import datetime
from pathlib import Path
from run_experiments import run_single
from general_agents.viz.viz_interactive import create_interactive_viz
from general_agents.viz.viz_realtime import RealtimeDIGVisualizer

def run_grid_experiments(
    agent_counts: list = [1, 2, 6],
    problem_sizes: list = [50, 200, 500],
    timeouts: list = [30.0, 30.0, 60.0],
    pauses: list = [0.0, 0.0, 0.0],
):
    """Run experiments across a grid of agent counts and problem sizes."""
    
    # Setup output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("experiment_results") / f"grid_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create subfolder for interactive graphs
    viz_dir = output_dir / "interactive_graphs"
    viz_dir.mkdir(parents=True, exist_ok=True)
    
    # Create subfolder for realtime figures
    realtime_dir = output_dir / "realtime_figures"
    realtime_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("GRID EXPERIMENT")
    print("=" * 70)
    print(f"Agent counts: {agent_counts}")
    print(f"Problem sizes: {problem_sizes}")
    print(f"Timeouts: {timeouts}")
    print(f"Output: {output_dir}")
    print("=" * 70)
    
    all_results = {
        "config": {
            "agent_counts": agent_counts,
            "problem_sizes": problem_sizes,
            "timeouts": timeouts,
        },
        "experiments": []
    }
    
    total_runs = len(agent_counts) * len(problem_sizes) * 2  # 2 = with/without intervention
    run_num = 0
    
    for num_agents in agent_counts:
        for size_idx, list_size in enumerate(problem_sizes):
            for enable_intervention in [False, True]:
                run_num += 1
                label = "WITH" if enable_intervention else "WITHOUT"
                interv_suffix = "with_interv" if enable_intervention else "no_interv"
                
                # Get timeout for this problem size
                run_timeout = timeouts[size_idx] if size_idx < len(timeouts) else timeouts[-1]
                run_pause = pauses[size_idx] if size_idx < len(pauses) else pauses[-1]
                
                print(f"\n{'='*70}")
                print(f"[{run_num}/{total_runs}] Agents: {num_agents}, Size: {list_size}, {label} intervention")
                print("=" * 70)
                
                # Create realtime visualizer for this experiment
                viz = RealtimeDIGVisualizer(update_interval=500)
                viz.start(block=False)
                
                try:
                    problem, dig, eval_result, runtime, timed_out = run_single(
                        list_size=list_size,
                        num_agents=num_agents,
                        timeout=run_timeout,
                        enable_intervention=enable_intervention,
                        realtime_dig_viz=viz,
                    )
                    
                    # Save interactive graph
                    viz_filename = viz_dir / f"agents{num_agents}_size{list_size}_{interv_suffix}.html"
                    create_interactive_viz(dig, str(viz_filename))
                    print(f"  Saved: {viz_filename.name}")
                    
                    # Save realtime figure
                    realtime_filename = realtime_dir / f"agents{num_agents}_size{list_size}_{interv_suffix}.png"
                    if viz and hasattr(viz, 'fig'):
                        viz.fig.savefig(str(realtime_filename), dpi=150, bbox_inches='tight')
                        print(f"  Saved: {realtime_filename.name}")
                    
                    # Get metrics
                    efficiency = dig.get_efficiency_metrics()
                    error = eval_result["error"]
                    valid = eval_result["valid"]
                    correct = eval_result["correct"]
                    
                    result = {
                        "num_agents": num_agents,
                        "list_size": list_size,
                        "intervention": enable_intervention,
                        "valid": valid,
                        "correct": correct,
                        "error": error if error != float('inf') else None,
                        "metric_name": eval_result["metric_name"],
                        "elapsed_time": efficiency["elapsed_time"],
                        "activation_time": efficiency["activation_time"],
                        "num_activations": efficiency["num_activations"],
                        "runtime": runtime,
                        "timed_out": timed_out,
                        "detections": dict(dig.detection_stats) if dig.detection_stats else {},
                        "interventions": dict(dig.intervention_stats) if dig.intervention_stats else {},
                        "viz_file": str(viz_filename.name),
                        "realtime_fig": str(realtime_filename.name),
                    }
                    
                    # Log
                    print(f"  Valid: {valid}, Correct: {correct}, {eval_result['metric_name']}: {error:.2f}")
                    print(f"  Elapsed: {efficiency['elapsed_time']:.1f}s, Activation: {efficiency['activation_time']:.1f}s, #Activations: {efficiency['num_activations']}")
                    if dig.detection_stats:
                        print(f"  Detections: {dict(dig.detection_stats)}")
                    if dig.intervention_stats:
                        print(f"  Interventions: {dict(dig.intervention_stats)}")
                    
                except Exception as e:
                    print(f"  ERROR: {e}")
                    result = {
                        "num_agents": num_agents,
                        "list_size": list_size,
                        "intervention": enable_intervention,
                        "error_message": str(e),
                    }
                finally:
                    # Close the visualizer
                    import matplotlib.pyplot as plt
                    plt.close('all')
                
                all_results["experiments"].append(result)
                
                # Save results after each experiment (incremental save)
                results_file = output_dir / "grid_results.json"
                with open(results_file, "w") as f:
                    json.dump(all_results, f, indent=2)
                
                # Update figures after each experiment
                try:
                    from plot_grid_results import plot_grid_results
                    plot_grid_results(str(results_file), str(output_dir))
                except Exception as e:
                    print(f"  Warning: Could not update figures: {e}")
                
                # Pause between experiments if configured
                if run_pause > 0 and run_num < total_runs:
                    print(f"  Pausing for {run_pause}s...")
                    time.sleep(run_pause)
    
    # Final summary table
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    
    # Header
    print(f"{'Agents':<8} {'Size':<8} {'Interv':<8} {'Valid':<8} {'Correct':<8} {'RMSE':<10} {'Elapsed':<10} {'#Act':<8}")
    print("-" * 70)
    
    for exp in all_results["experiments"]:
        if "error_message" in exp:
            print(f"{exp['num_agents']:<8} {exp['list_size']:<8} {str(exp['intervention']):<8} ERROR: {exp['error_message']}")
        else:
            rmse = f"{exp['error']:.2f}" if exp['error'] is not None else "N/A"
            print(f"{exp['num_agents']:<8} {exp['list_size']:<8} {str(exp['intervention']):<8} {str(exp['valid']):<8} {str(exp['correct']):<8} {rmse:<10} {exp['elapsed_time']:<10.1f} {exp['num_activations']:<8}")
    
    print(f"\n{'='*70}")
    print(f"Results saved to: {results_file}")
    print(f"Figures saved to: {output_dir}")
    print("=" * 70)
    
    return str(results_file)


if __name__ == "__main__":
    run_grid_experiments(
        # agent_counts=[1, 2, 6],
        # problem_sizes=[50, 200, 600],
        # timeouts=[30.0, 30.0, 60.0],
        # pauses=[5.0, 10.0, 30.0],
        agent_counts=[1, 3, 6],
        problem_sizes=[3000, 6000, 12000],
        timeouts=[30.0, 30.0, 60.0],
        pauses=[10.0, 10.0, 30.0],
    )
