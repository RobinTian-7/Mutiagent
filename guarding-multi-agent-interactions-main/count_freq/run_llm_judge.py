"""
run_llm_judge.py

Test LLM judge with count frequency problem.
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from general_agents.core.environment import MultiAgentEnvironment
from general_agents.problems.count_frequency import CountFrequencyProblem
from general_agents.policies.agent_policy import LLMAgentPolicy, cleanup_llm_clients
from general_agents.analysis.error_detection.llm_judge import LLMJudge
from general_agents.viz.viz_interactive import create_interactive_viz
from general_agents.viz.viz_realtime import RealtimeDIGVisualizer


async def test_llm_judge():
    """Test LLM judge with count frequency problem."""
    
    # Setup output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("experiment_results") / "llm_judge_test" / f"demo_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # ----------------------------
    # Config
    # ----------------------------
    problem_size = 10000
    timeout_seconds = 180.0
    num_agents = 6

    # Create problem
    print("Creating test problem...")
    base = [1, 2, 2, 3, 3, 3, 7, 7, 1, 5, 5, 5, 5] * 100000
    example_list = base[:problem_size]
    problem = CountFrequencyProblem(example_list)
    
    # Create agents
    print("Creating agents...")
    agents = {
        f"Agent{i}": LLMAgentPolicy(f"Agent{i}")
        for i in range(1, num_agents+1)
    }
    
    # Initialize LLM judge
    print("Initializing LLM judge...")
    llm_judge = LLMJudge(
        check_interval_activations=5,  # Check every 5 activations
        enable_intervention=True,       # Apply interventions
    )
    
    # Initialize realtime visualization
    print("Initializing realtime visualization...")
    realtime_viz = RealtimeDIGVisualizer(update_interval=500)
    realtime_viz.start(block=False)
    
    # Create environment with LLM judge and realtime viz
    print("Creating environment...")
    env = MultiAgentEnvironment(
        problem=problem,
        agents=agents,
        enable_intervention=False,  # Let LLM judge handle interventions
        llm_judge=llm_judge,
        realtime_dig_viz=realtime_viz,
    )
    
    # Run experiment
    print("\n" + "="*60)
    print("Running experiment with LLM judge...")
    print("="*60)
    print("Watch the matplotlib window for real-time visualization!")
    print("="*60)
    
    dig, winner, num_activations, timed_out = await env.run(timeout_seconds=timeout_seconds)
    
    # Keep realtime visualization window open for viewing
    # (it will close when user closes the matplotlib window)
    
    # Cleanup
    await cleanup_llm_clients()
    
    # Evaluate results
    eval_result = problem.evaluate_solution(dig)
    
    print("\n" + "="*60)
    print("Results:")
    print("="*60)
    print(f"Valid: {eval_result['valid']}")
    print(f"Correct: {eval_result['correct']}")
    print(f"Error ({eval_result['metric_name']}): {eval_result['error']:.2f}")
    print(f"Timed out: {timed_out}")
    print(f"Activations: {num_activations}")
    print(f"\nSolution:  {eval_result['solution']}")
    print(f"Reference: {eval_result['reference']}")
    
    if dig.detection_stats:
        print(f"\nDetected errors: {dict(dig.detection_stats)}")
    if dig.intervention_stats:
        print(f"Interventions applied: {dict(dig.intervention_stats)}")
    
    # Get efficiency metrics
    efficiency = dig.get_efficiency_metrics()
    print(f"\nEfficiency:")
    print(f"  Elapsed time: {efficiency['elapsed_time']:.1f}s")
    print(f"  Activation time: {efficiency['activation_time']:.1f}s")
    print(f"  Num activations: {efficiency['num_activations']}")
    
    # Create interactive visualization
    viz_file = output_dir / "interactive_viz.html"
    
    print(f"\nCreating interactive visualization: {viz_file}")
    create_interactive_viz(dig, str(viz_file))
    
    # Save final realtime viz figure
    fig_file = output_dir / "realtime_viz_final.png"
    realtime_viz.fig.savefig(str(fig_file), dpi=150, bbox_inches='tight')
    
    print(f"\n{'='*60}")
    print("Visualizations created:")
    print(f"  Realtime (final frame): {fig_file}")
    print(f"  Interactive HTML: {viz_file}")
    print(f"{'='*60}")
    
    return dig, eval_result


if __name__ == "__main__":
    asyncio.run(test_llm_judge())
