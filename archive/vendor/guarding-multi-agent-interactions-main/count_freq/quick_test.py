"""
quick_test.py

Quick test script for real-time DIG visualization on Count Frequency problem.
"""

import asyncio
import sys
import os
import webbrowser
import shutil
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from count_freq.run_experiments import run_single_experiment
from general_agents.viz.viz_realtime import RealtimeDIGVisualizer
from general_agents.viz.viz_interactive import create_interactive_viz


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Real-time DIG visualization demo (count frequency)")
    parser.add_argument(
        "--no-intv",
        action="store_true",
        help="Disable intervention (default: intervention enabled)"
    )
    args = parser.parse_args()
    
    enable_intervention = not args.no_intv
    # Setup timestamped folder for results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_folder = Path("experiment_results") / f"demo_{timestamp}"
    run_folder.mkdir(parents=True, exist_ok=True)
    
    changelog_filename = run_folder / "changelog.json"
    html_filename = run_folder / "interactive_dig.html"
    fig_filename = run_folder / "realtime_dig_final.png"
    
    # Demo config
    problem_size = 10000
    timeout_seconds = 60.0
    num_agents = 6

    print("=" * 60)
    print("REAL-TIME DIG VISUALIZATION DEMO WITH INTERVENTION (COUNT FREQ)")
    print("=" * 60)
    print()
    print(f"Intervention: {'ENABLED' if enable_intervention else 'DISABLED'}")
    if enable_intervention:
        print("You will see:")
        print("  - Agents attempting to submit without full coverage")
        print("  - System detecting uncovered edges and blocking submission")
        print("  - System intervention messages routing back to agents")
        print("  - System activations (purple nodes) appearing in the DIG")
    else:
        print("Running without intervention - agents can submit anytime")
    print()
    print(f"Running with {problem_size} items, {num_agents} agents, {timeout_seconds:.0f}s timeout...")
    print(f"Results folder: {run_folder}")
    print("=" * 60)

    # Create real-time visualizer
    viz = RealtimeDIGVisualizer(update_interval=500)
    viz.start(block=False)

    # Run ONE experiment with intervention
    dig_result = None
    try:
        import time
        from general_agents.problems.count_frequency import CountFrequencyProblem
        from general_agents.policies.agent_policy import LLMAgentPolicy
        from general_agents.core.environment import MultiAgentEnvironment

        # Create problem
        example_list = [18, 20, 20, 25, 27, 30, 30, 30, 45, 70, 70, 11, 51, 70, 70, 11, 51] * 100000
        problem = CountFrequencyProblem(example_list[:problem_size])

        # Create agents
        agent_names = [f"Agent{i}" for i in range(1, num_agents+1)]
        agents = {name: LLMAgentPolicy(name) for name in agent_names}
        
        print(f"\nCreated {len(agents)} agents: {list(agents.keys())}")
        
        # Run environment
        env = MultiAgentEnvironment(
            problem=problem,
            agents=agents,
            enable_intervention=enable_intervention,
            realtime_dig_viz=viz
        )
        
        print("Starting environment run...")
        start_time = time.time()
        
        async def run_async():
            return await env.run(timeout_seconds=timeout_seconds)
        
        dig, winning_event, num_activations, timed_out = asyncio.run(run_async())
        
        runtime = time.time() - start_time
        
        # Evaluate using problem's method (metrics defined by problem)
        eval_result = problem.evaluate_solution(dig)
        metric_name = eval_result.get("metric_name", "error") if eval_result else "error"
        error = eval_result.get("error", float('inf')) if eval_result else float('inf')
        valid = eval_result.get("valid", False) if eval_result else False
        correct = eval_result.get("correct", False) if eval_result else False
        
        print(f"\n[DONE] Demo complete!")
        print(f"  Valid: {valid}, Correct: {correct}, {metric_name}: {error:.2f}")
        print(f"  Runtime: {runtime:.2f}s")
        print(f"  Timed out: {timed_out}")
        print(f"  Total activations: {num_activations}")
        
        # Display error detection statistics
        if dig.detection_stats:
            print(f"\n[ERROR DETECTIONS]")
            total_detections = sum(dig.detection_stats.values())
            print(f"  Total detections: {total_detections}")
            for detection_type, count in dig.detection_stats.items():
                print(f"  - {detection_type}: {count}")
        
        # Display intervention statistics
        if dig.intervention_stats:
            print(f"\n[INTERVENTIONS]")
            total_interventions = sum(dig.intervention_stats.values())
            print(f"  Total interventions: {total_interventions}")
            for intervention_type, count in dig.intervention_stats.items():
                print(f"  - {intervention_type}: {count}")
        
        # Save results to folder
        print(f"\n[SAVE] Saving results to {run_folder}...")
        
        # Save DIG changelog
        dig.save_changelog(str(changelog_filename))
        print(f"  - Changelog: {changelog_filename.name}")
        
        # Create and save interactive visualization
        create_interactive_viz(dig, str(html_filename))
        print(f"  - Interactive viz: {html_filename.name}")
        
        # Save final realtime figure
        if viz and hasattr(viz, 'fig'):
            viz.fig.savefig(str(fig_filename), dpi=150, bbox_inches='tight')
            print(f"  - Realtime figure: {fig_filename.name}")
        
        print(f"\n[SUMMARY]")
        print(f"  Results saved to: {run_folder}")
        print(f"  Total changes: {len(dig.changelog)}")
        
        # Open in browser
        print(f"\n[Browser] Opening interactive visualization...")
        webbrowser.open(f"file://{html_filename.absolute()}")
        
        print("\nDemo complete! Check the HTML file for interactive visualization.")
        viz.wait_for_close()
        
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
