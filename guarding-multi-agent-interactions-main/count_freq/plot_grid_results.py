"""
plot_grid_results.py

Generate figures from grid experiment results.
"""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np


def load_results(results_file: str) -> dict:
    """Load results from JSON file."""
    with open(results_file, "r") as f:
        return json.load(f)


def plot_grid_results(results_file: str, output_dir: str = None):
    """Generate figures from grid experiment results."""
    
    results = load_results(results_file)
    
    if output_dir is None:
        output_dir = Path(results_file).parent
    else:
        output_dir = Path(output_dir)
    
    config = results["config"]
    experiments = results["experiments"]
    
    agent_counts = config["agent_counts"]
    problem_sizes = config["problem_sizes"]
    
    # Organize data by (num_agents, list_size, intervention)
    data = {}
    for exp in experiments:
        if "error_message" in exp:
            continue
        key = (exp["num_agents"], exp["list_size"], exp["intervention"])
        data[key] = exp
    
    # Colors
    color_no_interv = '#e74c3c'  # Red
    color_with_interv = '#2ecc71'  # Green
    
    # Find max valid RMSE across all experiments for consistent y-axis
    all_valid_rmse = []
    for exp in experiments:
        if "error_message" not in exp and exp.get("error") is not None:
            all_valid_rmse.append(exp["error"])
    max_valid_rmse = max(all_valid_rmse) if all_valid_rmse else 100
    inf_placeholder = 2 * max_valid_rmse
    
    # --- Create separate figure for each agent count ---
    for num_agents in agent_counts:
        fig, axes = plt.subplots(2, 3, figsize=(18, 9))
        fig.suptitle(f"Results for {num_agents} Agent(s): With vs Without Intervention", fontsize=14, fontweight='bold')
        
        # --- Plot 1: Valid Submission Rate ---
        ax1 = axes[0, 0]
        valid_no = [1 if data.get((num_agents, size, False), {}).get("valid", False) else 0 for size in problem_sizes]
        valid_with = [1 if data.get((num_agents, size, True), {}).get("valid", False) else 0 for size in problem_sizes]
        
        x = np.arange(len(problem_sizes))
        width = 0.35
        ax1.bar(x - width/2, valid_no, width, label='No Intervention', color=color_no_interv, alpha=0.8)
        ax1.bar(x + width/2, valid_with, width, label='With Intervention', color=color_with_interv, alpha=0.8)
        
        ax1.set_xlabel("Problem Size")
        ax1.set_ylabel("Valid Submission (1=Yes, 0=No)")
        ax1.set_title("Valid Submission Rate")
        ax1.set_xticks(x)
        ax1.set_xticklabels(problem_sizes)
        ax1.legend(fontsize=9)
        ax1.set_ylim(0, 1.2)
        
        # --- Plot 2: RMSE (error) ---
        ax2 = axes[0, 1]
        rmse_no_raw = [data.get((num_agents, size, False), {}).get("error") for size in problem_sizes]
        rmse_with_raw = [data.get((num_agents, size, True), {}).get("error") for size in problem_sizes]
        
        # Separate valid and inf points
        valid_sizes_no = [s for s, e in zip(problem_sizes, rmse_no_raw) if e is not None]
        valid_rmse_no = [e for e in rmse_no_raw if e is not None]
        inf_sizes_no = [s for s, e in zip(problem_sizes, rmse_no_raw) if e is None]
        
        valid_sizes_with = [s for s, e in zip(problem_sizes, rmse_with_raw) if e is not None]
        valid_rmse_with = [e for e in rmse_with_raw if e is not None]
        inf_sizes_with = [s for s, e in zip(problem_sizes, rmse_with_raw) if e is None]
        
        # Plot valid points
        if valid_sizes_no:
            ax2.plot(valid_sizes_no, valid_rmse_no, 'o--', label='No Intervention', 
                     color=color_no_interv, markersize=10, linewidth=2)
        if valid_sizes_with:
            ax2.plot(valid_sizes_with, valid_rmse_with, 's-', label='With Intervention', 
                     color=color_with_interv, markersize=10, linewidth=2)
        
        # Plot inf points
        if inf_sizes_no:
            ax2.scatter(inf_sizes_no, [inf_placeholder] * len(inf_sizes_no), marker='X', s=150, 
                       color=color_no_interv, edgecolors='black', linewidths=1, zorder=5)
            for size in inf_sizes_no:
                ax2.annotate('∞', (size, inf_placeholder), textcoords="offset points", 
                            xytext=(0, 10), ha='center', fontsize=12, fontweight='bold', color=color_no_interv)
        if inf_sizes_with:
            ax2.scatter(inf_sizes_with, [inf_placeholder] * len(inf_sizes_with), marker='X', s=150, 
                       color=color_with_interv, edgecolors='black', linewidths=1, zorder=5)
            for size in inf_sizes_with:
                ax2.annotate('∞', (size, inf_placeholder), textcoords="offset points", 
                            xytext=(0, -18), ha='center', fontsize=12, fontweight='bold', color=color_with_interv)
        
        ax2.set_xlabel("Problem Size")
        ax2.set_ylabel("RMSE (lower is better)")
        ax2.set_title("Solution Quality (RMSE)")
        ax2.legend(fontsize=9)
        ax2.set_xscale('log')
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, inf_placeholder * 1.25)
        ax2.axhline(y=inf_placeholder, color='gray', linestyle=':', alpha=0.5)
        ax2.text(problem_sizes[-1], inf_placeholder * 1.03, 'invalid (∞)', fontsize=9, color='gray', alpha=0.8, ha='right')
        
        # --- Plot 3: Elapsed Time ---
        ax3 = axes[1, 0]
        time_no = [data.get((num_agents, size, False), {}).get("elapsed_time", np.nan) for size in problem_sizes]
        time_with = [data.get((num_agents, size, True), {}).get("elapsed_time", np.nan) for size in problem_sizes]
        
        ax3.plot(problem_sizes, time_no, 'o--', label='No Intervention', 
                 color=color_no_interv, markersize=10, linewidth=2)
        ax3.plot(problem_sizes, time_with, 's-', label='With Intervention', 
                 color=color_with_interv, markersize=10, linewidth=2)
        
        ax3.set_xlabel("Problem Size")
        ax3.set_ylabel("Elapsed Time (s)")
        ax3.set_title("Elapsed Time")
        ax3.legend(fontsize=9)
        ax3.set_xscale('log')
        ax3.grid(True, alpha=0.3)
        
        # --- Plot 4: Number of Activations ---
        ax4 = axes[1, 1]
        act_no = [data.get((num_agents, size, False), {}).get("num_activations", 0) for size in problem_sizes]
        act_with = [data.get((num_agents, size, True), {}).get("num_activations", 0) for size in problem_sizes]
        
        ax4.plot(problem_sizes, act_no, 'o--', label='No Intervention', 
                 color=color_no_interv, markersize=10, linewidth=2)
        ax4.plot(problem_sizes, act_with, 's-', label='With Intervention', 
                 color=color_with_interv, markersize=10, linewidth=2)
        
        ax4.set_xlabel("Problem Size")
        ax4.set_ylabel("Number of Activations")
        ax4.set_title("Agent Activations")
        ax4.legend(fontsize=9)
        ax4.set_xscale('log')
        ax4.grid(True, alpha=0.3)
        
        # --- Plot 5: Error Detection Counts ---
        ax5 = axes[0, 2]
        
        # Collect all error categories across all experiments
        all_error_categories = set()
        for size in problem_sizes:
            for interv in [False, True]:
                detections = data.get((num_agents, size, interv), {}).get("detections", {})
                all_error_categories.update(detections.keys())
        
        # Sort categories for consistent ordering
        error_categories = sorted(all_error_categories)
        
        if error_categories:
            # Prepare data for each category
            x_pos = np.arange(len(problem_sizes))
            width = 0.35
            
            # Sum up all error counts for each condition
            total_no = []
            total_with = []
            
            for size in problem_sizes:
                detections_no = data.get((num_agents, size, False), {}).get("detections", {})
                detections_with = data.get((num_agents, size, True), {}).get("detections", {})
                
                total_no.append(sum(detections_no.values()))
                total_with.append(sum(detections_with.values()))
            
            ax5.bar(x_pos - width/2, total_no, width, label='No Intervention', 
                   color=color_no_interv, alpha=0.8)
            ax5.bar(x_pos + width/2, total_with, width, label='With Intervention', 
                   color=color_with_interv, alpha=0.8)
            
            ax5.set_xlabel("Problem Size")
            ax5.set_ylabel("Total Error Detections")
            ax5.set_title("Error Detection Counts")
            ax5.set_xticks(x_pos)
            ax5.set_xticklabels(problem_sizes)
            ax5.legend(fontsize=9)
            ax5.grid(True, alpha=0.3, axis='y')
        else:
            ax5.text(0.5, 0.5, 'No error detections', ha='center', va='center', 
                    transform=ax5.transAxes, fontsize=12)
            ax5.set_title("Error Detection Counts")
        
        # --- Plot 6: Error Detection Breakdown ---
        ax6 = axes[1, 2]
        
        if error_categories:
            # Show breakdown by category for "with intervention" case
            category_counts = {cat: [] for cat in error_categories}
            
            for size in problem_sizes:
                detections_with = data.get((num_agents, size, True), {}).get("detections", {})
                for cat in error_categories:
                    category_counts[cat].append(detections_with.get(cat, 0))
            
            # Stack bar chart
            bottom = np.zeros(len(problem_sizes))
            colors_palette = plt.cm.Set3(np.linspace(0, 1, len(error_categories)))
            
            for idx, cat in enumerate(error_categories):
                ax6.bar(problem_sizes, category_counts[cat], label=cat, 
                       bottom=bottom, color=colors_palette[idx], alpha=0.8)
                bottom += np.array(category_counts[cat])
            
            ax6.set_xlabel("Problem Size")
            ax6.set_ylabel("Error Count")
            ax6.set_title("Error Categories (With Intervention)")
            ax6.set_xscale('log')
            ax6.legend(fontsize=8, loc='best')
            ax6.grid(True, alpha=0.3, axis='y')
        else:
            ax6.text(0.5, 0.5, 'No error categories', ha='center', va='center', 
                    transform=ax6.transAxes, fontsize=12)
            ax6.set_title("Error Categories")
        
        plt.tight_layout()
        
        # Save figure
        fig_path = output_dir / f"results_{num_agents}_agents.png"
        plt.savefig(fig_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {fig_path}")
        
        pdf_path = output_dir / f"results_{num_agents}_agents.pdf"
        plt.savefig(pdf_path, bbox_inches='tight')
        print(f"Saved: {pdf_path}")
        
        plt.close()
    
    # --- Summary figure comparing all agent counts ---
    fig, ax = plt.subplots(figsize=(10, 6))
    
    labels = []
    no_interv_valid = []
    with_interv_valid = []
    
    for num_agents in agent_counts:
        for size in problem_sizes:
            labels.append(f"A{num_agents}-S{size}")
            no_interv_valid.append(1 if data.get((num_agents, size, False), {}).get("valid", False) else 0)
            with_interv_valid.append(1 if data.get((num_agents, size, True), {}).get("valid", False) else 0)
    
    x = np.arange(len(labels))
    width = 0.35
    
    ax.bar(x - width/2, no_interv_valid, width, label='Without Intervention', color=color_no_interv, alpha=0.8)
    ax.bar(x + width/2, with_interv_valid, width, label='With Intervention', color=color_with_interv, alpha=0.8)
    
    ax.set_xlabel("Configuration (Agents-Size)")
    ax.set_ylabel("Valid Submission")
    ax.set_title("Intervention Effect on Valid Submissions")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.legend()
    ax.set_ylim(0, 1.3)
    
    for i, (no, with_) in enumerate(zip(no_interv_valid, with_interv_valid)):
        if with_ > no:
            ax.annotate('↑', (i, 1.1), ha='center', fontsize=12, color='green')
        elif with_ < no:
            ax.annotate('↓', (i, 1.1), ha='center', fontsize=12, color='red')
    
    plt.tight_layout()
    
    fig_path = output_dir / "intervention_effectiveness.png"
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {fig_path}")
    
    plt.close()
    
    return str(output_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default to most recent grid results
        results_dir = Path("experiment_results")
        grid_dirs = sorted(results_dir.glob("grid_*"))
        if grid_dirs:
            latest = grid_dirs[-1] / "grid_results.json"
            print(f"Using latest grid results: {latest}")
            plot_grid_results(str(latest))
        else:
            print("Usage: python plot_grid_results.py <path_to_grid_results.json>")
    else:
        plot_grid_results(sys.argv[1])
