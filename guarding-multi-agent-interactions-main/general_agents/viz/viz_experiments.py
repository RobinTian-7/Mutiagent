"""
viz_experiments.py

Visualization of experiment summary results (RMSE, runtime) across multiple trials.
Supports both real-time updates during experiments and static plots from saved results.
"""

import json
import sys
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.gridspec import GridSpec
import numpy as np
from typing import Dict, List, Optional
import threading
import queue
import time


class RealtimeExperimentPlotter:
    """
    Real-time plotter that updates visualizations as experiments complete.
    """
    
    def __init__(self, list_sizes: List[int], team_sizes: List[int], trials_per_config: int = 1):
        """
        Initialize the real-time plotter.
        
        Args:
            list_sizes: List of task load sizes to experiment with
            team_sizes: List of team sizes to experiment with
            trials_per_config: Number of trials per configuration
        """
        self.list_sizes = sorted(list_sizes)
        self.team_sizes = sorted(team_sizes)
        self.trials_per_config = trials_per_config
        
        # Data storage for results
        self.results = {}  # (list_size, team_size) -> list of (mse, runtime, timed_out)
        for ls in list_sizes:
            for ts in team_sizes:
                self.results[(ls, ts)] = []
        
        # Queue for receiving updates from experiment thread
        self.update_queue = queue.Queue()
        
        # Setup figure and axes with better sizing
        self.fig = plt.figure(figsize=(18, 11))
        gs = GridSpec(2, 2, figure=self.fig, hspace=0.35, wspace=0.35)
        
        # Create subplots
        self.ax_rmse_heatmap = self.fig.add_subplot(gs[0, 0])
        self.ax_runtime_heatmap = self.fig.add_subplot(gs[0, 1])
        self.ax_rmse_line = self.fig.add_subplot(gs[1, 0])
        self.ax_runtime_line = self.fig.add_subplot(gs[1, 1])
        
        # Initialize plots
        self._setup_plots()
        
        # Animation control
        self.running = True
        self.last_update = time.time()
        
    def _setup_plots(self):
        """Setup initial plot structure and styling."""
        # RMSE Heatmap
        self.ax_rmse_heatmap.set_title('RMSE Heatmap (Real-time)', fontsize=14, fontweight='bold')
        self.ax_rmse_heatmap.set_xlabel('Task Load (List Size)', fontsize=11)
        self.ax_rmse_heatmap.set_ylabel('Team Size', fontsize=11)
        
        # Runtime Heatmap
        self.ax_runtime_heatmap.set_title('Runtime Heatmap (Real-time)', fontsize=14, fontweight='bold')
        self.ax_runtime_heatmap.set_xlabel('Task Load (List Size)', fontsize=11)
        self.ax_runtime_heatmap.set_ylabel('Team Size', fontsize=11)
        
        # RMSE Line Chart
        self.ax_rmse_line.set_title('RMSE vs Task Load', fontsize=14, fontweight='bold')
        self.ax_rmse_line.set_xlabel('Task Load (List Size)', fontsize=11)
        self.ax_rmse_line.set_ylabel('RMSE', fontsize=11)
        self.ax_rmse_line.grid(True, alpha=0.3)
        if max(self.list_sizes) / min(self.list_sizes) > 10:
            self.ax_rmse_line.set_xscale('log')
        
        # Runtime Line Chart
        self.ax_runtime_line.set_title('Runtime vs Task Load', fontsize=14, fontweight='bold')
        self.ax_runtime_line.set_xlabel('Task Load (List Size)', fontsize=11)
        self.ax_runtime_line.set_ylabel('Runtime (seconds)', fontsize=11)
        self.ax_runtime_line.grid(True, alpha=0.3)
        if max(self.list_sizes) / min(self.list_sizes) > 10:
            self.ax_runtime_line.set_xscale('log')
        
        # Add progress text
        self.progress_text = self.fig.text(0.5, 0.95, 'Starting experiments...', 
                                          ha='center', fontsize=12, fontweight='bold')
    
    def add_result(self, list_size: int, team_size: int, mse: float, runtime: float, timed_out: bool):
        """
        Add a new experimental result (called from experiment thread).
        
        Args:
            list_size: Size of the problem list
            team_size: Number of agents
            mse: Mean squared error
            runtime: Runtime in seconds
            timed_out: Whether the experiment timed out
        """
        self.update_queue.put({
            'list_size': list_size,
            'team_size': team_size,
            'mse': mse,
            'runtime': runtime,
            'timed_out': timed_out
        })
    
    def _process_updates(self):
        """Process all pending updates from the queue."""
        updated = False
        while not self.update_queue.empty():
            try:
                data = self.update_queue.get_nowait()
                key = (data['list_size'], data['team_size'])
                self.results[key].append({
                    'mse': data['mse'],
                    'runtime': data['runtime'],
                    'timed_out': data['timed_out']
                })
                updated = True
            except queue.Empty:
                break
        return updated
    
    def _update_plots(self, frame):
        """Update all plots with current data (called by animation)."""
        # Process any new results
        if not self._process_updates():
            return
        
        # Clear axes
        self.ax_rmse_heatmap.clear()
        self.ax_runtime_heatmap.clear()
        self.ax_rmse_line.clear()
        self.ax_runtime_line.clear()
        
        # Recalculate statistics
        rmse_matrix = np.full((len(self.team_sizes), len(self.list_sizes)), np.nan)
        runtime_matrix = np.full((len(self.team_sizes), len(self.list_sizes)), np.nan)
        
        completed_count = 0
        total_count = len(self.list_sizes) * len(self.team_sizes) * self.trials_per_config
        
        for i, ts in enumerate(self.team_sizes):
            for j, ls in enumerate(self.list_sizes):
                key = (ls, ts)
                results = self.results[key]
                
                if results:
                    avg_mse = np.mean([r['mse'] for r in results])
                    avg_runtime = np.mean([r['runtime'] for r in results])
                    rmse_matrix[i, j] = np.sqrt(avg_mse)
                    runtime_matrix[i, j] = avg_runtime
                    completed_count += len(results)
        
        # Update heatmaps
        self._update_heatmap(self.ax_rmse_heatmap, rmse_matrix, 
                            'RMSE Heatmap (Real-time)', 'RdYlGn_r', 'RMSE', lower_is_better=True)
        self._update_heatmap(self.ax_runtime_heatmap, runtime_matrix,
                            'Runtime Heatmap (Real-time)', 'RdYlGn_r', 'Runtime (s)', lower_is_better=True)
        
        # Update line charts
        self._update_line_charts()
        
        # Update progress text
        progress_pct = (completed_count / total_count) * 100 if total_count > 0 else 0
        self.progress_text.set_text(
            f'Progress: {completed_count}/{total_count} experiments ({progress_pct:.1f}%)'
        )
    
    def _update_heatmap(self, ax, matrix, title, cmap, label, lower_is_better=True):
        """Update a heatmap plot.
        
        Args:
            ax: Matplotlib axis
            matrix: Data matrix to plot
            title: Plot title
            cmap: Colormap name
            label: Colorbar label
            lower_is_better: If True, green=good/low, red=bad/high
        """
        # Create masked array to handle NaN values
        masked_matrix = np.ma.masked_invalid(matrix)
        
        # Get valid data range for better color scaling
        valid_data = masked_matrix.compressed()
        if len(valid_data) > 0:
            vmin = np.min(valid_data)
            vmax = np.max(valid_data)
            # Add some padding to the range for better visualization
            vrange = vmax - vmin
            if vrange > 0:
                vmin = vmin - 0.05 * vrange
                vmax = vmax + 0.05 * vrange
        else:
            vmin, vmax = None, None
        
        im = ax.imshow(masked_matrix, cmap=cmap, aspect='auto', 
                      interpolation='nearest', vmin=vmin, vmax=vmax)
        ax.set_xticks(range(len(self.list_sizes)))
        ax.set_yticks(range(len(self.team_sizes)))
        ax.set_xticklabels([f"{size}" for size in self.list_sizes], fontsize=10)
        ax.set_yticklabels([f"{size}" for size in self.team_sizes], fontsize=10)
        ax.set_xlabel('Task Load (List Size)', fontsize=11, fontweight='bold')
        ax.set_ylabel('Team Size', fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold')
        
        # Add subtle grid lines
        ax.set_xticks(np.arange(len(self.list_sizes)) - 0.5, minor=True)
        ax.set_yticks(np.arange(len(self.team_sizes)) - 0.5, minor=True)
        ax.grid(which='minor', color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
        
        # Add text annotations with adaptive color for contrast
        for i in range(len(self.team_sizes)):
            for j in range(len(self.list_sizes)):
                if not np.isnan(matrix[i, j]):
                    value_str = f'{matrix[i, j]:.2f}' if label == 'RMSE' else f'{matrix[i, j]:.1f}s'
                    
                    # Choose text color based on background intensity
                    if len(valid_data) > 0 and vmax > vmin:
                        normalized_val = (matrix[i, j] - vmin) / (vmax - vmin)
                        text_color = 'white' if normalized_val > 0.5 else 'black'
                    else:
                        text_color = 'black'
                    
                    ax.text(j, i, value_str, ha="center", va="center", 
                           color=text_color, fontsize=11, fontweight='bold')
        
        cbar = plt.colorbar(im, ax=ax, label=label)
        cbar.ax.tick_params(labelsize=10)
    
    def _update_line_charts(self):
        """Update line charts for RMSE and Runtime vs Task Load."""
        colors = plt.cm.viridis(np.linspace(0, 1, len(self.team_sizes)))
        
        for idx, team_size in enumerate(self.team_sizes):
            rmse_values = []
            runtime_values = []
            plot_list_sizes = []
            
            for list_size in self.list_sizes:
                key = (list_size, team_size)
                results = self.results[key]
                
                if results:
                    avg_mse = np.mean([r['mse'] for r in results])
                    avg_runtime = np.mean([r['runtime'] for r in results])
                    rmse_values.append(np.sqrt(avg_mse))
                    runtime_values.append(avg_runtime)
                    plot_list_sizes.append(list_size)
            
            if rmse_values:
                self.ax_rmse_line.plot(plot_list_sizes, rmse_values, 
                                      marker='o', label=f'{team_size} agents',
                                      color=colors[idx], linewidth=2, markersize=8)
                self.ax_runtime_line.plot(plot_list_sizes, runtime_values,
                                         marker='s', label=f'{team_size} agents',
                                         color=colors[idx], linewidth=2, markersize=8)
        
        # RMSE Line Chart
        self.ax_rmse_line.set_xlabel('Task Load (List Size)', fontsize=11)
        self.ax_rmse_line.set_ylabel('RMSE', fontsize=11)
        self.ax_rmse_line.set_title('RMSE vs Task Load', fontsize=14, fontweight='bold')
        self.ax_rmse_line.grid(True, alpha=0.3)
        if len(self.list_sizes) > 1 and max(self.list_sizes) / min(self.list_sizes) > 10:
            self.ax_rmse_line.set_xscale('log')
        self.ax_rmse_line.legend(fontsize=9)
        
        # Runtime Line Chart
        self.ax_runtime_line.set_xlabel('Task Load (List Size)', fontsize=11)
        self.ax_runtime_line.set_ylabel('Runtime (seconds)', fontsize=11)
        self.ax_runtime_line.set_title('Runtime vs Task Load', fontsize=14, fontweight='bold')
        self.ax_runtime_line.grid(True, alpha=0.3)
        if len(self.list_sizes) > 1 and max(self.list_sizes) / min(self.list_sizes) > 10:
            self.ax_runtime_line.set_xscale('log')
        self.ax_runtime_line.legend(fontsize=9)
    
    def start(self, block=True):
        """Start the real-time visualization.
        
        Args:
            block: If True, blocks until window is closed. If False, returns immediately.
        """
        # Create animation
        self.ani = animation.FuncAnimation(
            self.fig, 
            self._update_plots,
            interval=1000,  # Update every 1 second
            blit=False,
            cache_frame_data=False
        )
        
        plt.show(block=block)
    
    def stop(self):
        """Stop the animation and close the plot."""
        self.running = False
        if hasattr(self, 'ani'):
            self.ani.event_source.stop()
    
    def is_window_open(self):
        """Check if the plot window is still open."""
        return plt.fignum_exists(self.fig.number)
    
    def save_final_plot(self, filename: str):
        """Save the final state of the plot to a file."""
        self.fig.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"Final plot saved to: {filename}")


# ============================================================================
# Static Plotting Functions (for saved experiment results)
# ============================================================================

def load_results(results_file: str) -> dict:
    """Load experimental results from JSON file.
    
    Args:
        results_file: Path to JSON file containing experiment results
        
    Returns:
        Dictionary containing experiment results
    """
    with open(results_file, 'r') as f:
        return json.load(f)


def plot_heatmaps(results: dict, output_prefix: str = "experiment"):
    """
    Create heatmap visualizations for RMSE and Runtime from saved results.
    
    Args:
        results: Dict containing experimental results
        output_prefix: Prefix for output filenames
    """
    # Handle both old and new result structures
    if "data" in results:
        data = results["data"]
    elif "data_no_intervention" in results:
        data = results["data_no_intervention"]
    else:
        print("No data found in results")
        return
    
    list_sizes = sorted(set(d["list_size"] for d in data))
    team_sizes = sorted(set(d["team_size"] for d in data))
    
    # Create matrices for heatmaps
    rmse_matrix = np.zeros((len(team_sizes), len(list_sizes)))
    runtime_matrix = np.zeros((len(team_sizes), len(list_sizes)))
    
    # Fill matrices (convert MSE to RMSE)
    for item in data:
        i = team_sizes.index(item["team_size"])
        j = list_sizes.index(item["list_size"])
        rmse_matrix[i, j] = np.sqrt(item["avg_mse"])
        runtime_matrix[i, j] = item["avg_runtime"]
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # RMSE Heatmap
    im1 = ax1.imshow(rmse_matrix, cmap='YlOrRd', aspect='auto', interpolation='nearest')
    ax1.set_xticks(range(len(list_sizes)))
    ax1.set_yticks(range(len(team_sizes)))
    ax1.set_xticklabels([f"{size}" for size in list_sizes])
    ax1.set_yticklabels([f"{size}" for size in team_sizes])
    ax1.set_xlabel('Task Load (List Size)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Team Size (Number of Agents)', fontsize=12, fontweight='bold')
    ax1.set_title('Root Mean Squared Error (RMSE)\nLower is Better', fontsize=14, fontweight='bold')
    
    # Add text annotations
    for i in range(len(team_sizes)):
        for j in range(len(list_sizes)):
            text = ax1.text(j, i, f'{rmse_matrix[i, j]:.2f}',
                           ha="center", va="center", color="black", fontsize=10)
    
    plt.colorbar(im1, ax=ax1, label='RMSE')
    
    # Runtime Heatmap
    im2 = ax2.imshow(runtime_matrix, cmap='YlGnBu', aspect='auto', interpolation='nearest')
    ax2.set_xticks(range(len(list_sizes)))
    ax2.set_yticks(range(len(team_sizes)))
    ax2.set_xticklabels([f"{size}" for size in list_sizes])
    ax2.set_yticklabels([f"{size}" for size in team_sizes])
    ax2.set_xlabel('Task Load (List Size)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Team Size (Number of Agents)', fontsize=12, fontweight='bold')
    ax2.set_title('Runtime (seconds)\nLower is Better', fontsize=14, fontweight='bold')
    
    # Add text annotations
    for i in range(len(team_sizes)):
        for j in range(len(list_sizes)):
            text = ax2.text(j, i, f'{runtime_matrix[i, j]:.2f}s',
                           ha="center", va="center", color="black", fontsize=10)
    
    plt.colorbar(im2, ax=ax2, label='Runtime (s)')
    
    plt.tight_layout()
    heatmap_file = f"{output_prefix}_heatmaps.png"
    plt.savefig(heatmap_file, dpi=300, bbox_inches='tight')
    print(f"Heatmaps saved to: {heatmap_file}")
    plt.close()


def plot_line_charts(results: dict, output_prefix: str = "experiment"):
    """
    Create line charts showing trends from saved results.
    
    Args:
        results: Dict containing experimental results
        output_prefix: Prefix for output filenames
    """
    # Handle both old and new result structures
    if "data" in results:
        data = results["data"]
    elif "data_no_intervention" in results:
        data = results["data_no_intervention"]
    else:
        print("No data found in results")
        return
    
    list_sizes = sorted(set(d["list_size"] for d in data))
    team_sizes = sorted(set(d["team_size"] for d in data))
    
    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    colors = plt.cm.viridis(np.linspace(0, 1, len(team_sizes)))
    
    # RMSE vs Task Load (different lines for team sizes)
    for idx, team_size in enumerate(team_sizes):
        rmse_values = [np.sqrt(item["avg_mse"]) for item in data if item["team_size"] == team_size]
        ax1.plot(list_sizes, rmse_values, marker='o', label=f'{team_size} agents',
                color=colors[idx], linewidth=2, markersize=8)
    ax1.set_xlabel('Task Load (List Size)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('RMSE', fontsize=12, fontweight='bold')
    ax1.set_title('RMSE vs Task Load', fontsize=14, fontweight='bold')
    ax1.set_xscale('log')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Runtime vs Task Load (different lines for team sizes)
    for idx, team_size in enumerate(team_sizes):
        runtime_values = [item["avg_runtime"] for item in data if item["team_size"] == team_size]
        ax2.plot(list_sizes, runtime_values, marker='s', label=f'{team_size} agents',
                color=colors[idx], linewidth=2, markersize=8)
    ax2.set_xlabel('Task Load (List Size)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Runtime (seconds)', fontsize=12, fontweight='bold')
    ax2.set_title('Runtime vs Task Load', fontsize=14, fontweight='bold')
    ax2.set_xscale('log')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    line_file = f"{output_prefix}_line_charts.png"
    plt.savefig(line_file, dpi=300, bbox_inches='tight')
    print(f"Line charts saved to: {line_file}")
    plt.close()


def print_summary_table(results: dict):
    """Print a summary table of results.
    
    Args:
        results: Dict containing experimental results
    """
    # Handle both old and new result structures
    if "data" in results:
        data = results["data"]
    elif "data_no_intervention" in results:
        data = results["data_no_intervention"]
    else:
        print("No data found in results")
        return
    
    print("\n" + "=" * 80)
    print("EXPERIMENTAL RESULTS SUMMARY")
    print("=" * 80)
    print(f"{'List Size':<12} {'Team Size':<12} {'Avg RMSE':<15} {'Avg Runtime':<15} {'Timeout Rate':<15}")
    print("-" * 80)
    
    for item in sorted(data, key=lambda x: (x["list_size"], x["team_size"])):
        rmse = np.sqrt(item["avg_mse"])
        print(f"{item['list_size']:<12} {item['team_size']:<12} "
              f"{rmse:<15.2f} {item['avg_runtime']:<15.2f} "
              f"{item['timeout_rate']:<15.1%}")
    
    print("=" * 80)


def plot_from_file(results_file: str):
    """
    Main function to generate all visualizations from a saved results file.
    
    Args:
        results_file: Path to JSON file containing experiment results
    """
    print(f"Loading results from: {results_file}")
    results = load_results(results_file)
    
    # Extract base name for output files
    output_prefix = results_file.replace('.json', '')
    
    print("\nGenerating visualizations...")
    
    # Generate plots
    plot_heatmaps(results, output_prefix)
    plot_line_charts(results, output_prefix)
    
    # Print summary
    print_summary_table(results)
    
    print("\n[DONE] All visualizations complete!")


def main():
    """CLI entry point for plotting saved experiment results."""
    if len(sys.argv) < 2:
        print("Usage: python viz_experiments.py <results_file.json>")
        print("\nSearching for most recent results file...")
        
        # Try to find the most recent results file
        import glob
        results_files = glob.glob("experiment_results/results_*.json")
        if results_files:
            results_file = max(results_files, key=lambda x: int(x.split('_')[-1].replace('.json', '')))
            print(f"Found: {results_file}")
            plot_from_file(results_file)
        else:
            print("No results files found in experiment_results/")
            sys.exit(1)
    else:
        plot_from_file(sys.argv[1])


if __name__ == "__main__":
    main()
