"""
viz_realtime.py

Real-time matplotlib visualization of DIG (Directed Interaction Graph) construction.
Shows live updates as agents interact, with dual-layer structure (activations + events).
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.animation import FuncAnimation
import queue
from typing import Set

from ..core.dig import InteractionMode, InteractionLog
from ..analysis.error_detection.error_detection import detect_and_report_errors
from ..core.dig import build_activation_event_graph


class RealtimeDIGVisualizer:
    """
    Real-time matplotlib visualization of DIG construction with dual-layer structure.
    Shows activation nodes (circles) and event nodes (squares) with edges.
    Runs error detection and displays system agent interventions.
    """
    
    def __init__(self, update_interval: int = 500):
        """
        Initialize the real-time DIG visualizer.
        
        Args:
            update_interval: Update interval in milliseconds
        """
        self.update_interval = update_interval
        self.update_queue = queue.Queue()
        self.current_dig = None
        self.detected_errors: Set[str] = set()
        self.window_closed = False
        
        # Matplotlib setup - 3 subplots: all edges, solid edges only, legend
        self.fig, (self.ax1, self.ax2, self.ax3) = plt.subplots(3, 1, figsize=(14, 14), sharex=True)
        self.fig.suptitle('Real-time DIG', fontsize=14, fontweight='bold')
        
        # Connect close event
        self.fig.canvas.mpl_connect('close_event', self._on_close)
        
        # Color mapping for interaction modes (kept for compatibility)
        self.mode_colors = {
            InteractionMode.RESPOND: '#1f77b4',
            InteractionMode.REROUTE: '#ff7f0e',
            InteractionMode.WAIT: '#bcbd22',
            InteractionMode.DISCARD: '#d62728',
            InteractionMode.SUBMIT: '#2ca02c',
            InteractionMode.TERMINATE: '#9467bd',
        }
        
        # Edge action colors (per-edge decisions)
        self.edge_action_colors = {
            'consume': '#2ca02c',   # Green - processed
            'reroute': '#9370db',   # Purple - forwarded
            'discard': '#d62728',   # Red - dropped
            'wait': '#ff8c00',      # Orange - deferred
            'pending': 'gray',      # Gray - not yet decided
        }
        
        # Single color for all agent activations (decisions are now per-edge)
        self.agent_color = '#1f77b4'  # Blue for all agent nodes
        
        # Special color for system agent
        self.system_color = '#ff1493'  # Hot pink for system agent
        
        self.anim = None
        
    def update_from_dig(self, dig: InteractionLog):
        """Queue a DIG update for visualization."""
        self.update_queue.put(dig)
        # Nudge the GUI event loop without blocking the async runner.
        try:
            if self.fig and self.fig.canvas:
                self.fig.canvas.draw_idle()
                self.fig.canvas.flush_events()
        except Exception:
            pass
    
    def _process_updates(self, frame):
        """Process queued DIG updates and redraw visualization."""
        # Process all queued updates
        while not self.update_queue.empty():
            try:
                self.current_dig = self.update_queue.get_nowait()
            except queue.Empty:
                break
        
        if self.current_dig is None:
            return
        
        dig = self.current_dig
        
        # Run error detection
        detect_and_report_errors(dig, self.detected_errors)
        
        # Clear axes
        self.ax1.clear()
        self.ax2.clear()
        self.ax3.clear()
        
        if not dig.activations:
            self.ax1.text(0.5, 0.5, 'Waiting for activations...', 
                         ha='center', va='center', transform=self.ax1.transAxes)
            self.ax2.text(0.5, 0.5, 'Waiting for activations...', 
                         ha='center', va='center', transform=self.ax2.transAxes)
            self.ax3.text(0.5, 0.5, 'Waiting for activations...', 
                         ha='center', va='center', transform=self.ax3.transAxes)
            return
        
        # Calculate time reference
        t0 = min(a.started_at for a in dig.activations.values())
        
        # Assign lanes for agents
        agent_names = sorted({a.agent_name for a in dig.activations.values()})
        lane_for_agent = {name: idx for idx, name in enumerate(agent_names)}
        
        # Build graph structure
        try:
            nodes, edges, _, _, _ = build_activation_event_graph(dig)
        except Exception as e:
            print(f"[DIG VIZ] Error building graph: {e}")
            return
        
        # ========== SUBPLOT 1: Timeline with nodes and edges ==========
        self.ax1.set_title('DIG', fontsize=11, pad=10)
        self.ax1.set_ylabel('Agent', fontsize=10)
        self.ax1.set_yticks(range(len(agent_names)))
        self.ax1.set_yticklabels(agent_names, fontsize=9)
        self.ax1.grid(False)
        
        # Identify rerouted recipients (edges that should be colored purple)
        rerouted_edge_keys = set()
        for evt in dig.events.values():
            for recipient, reroute_act_id in evt.rerouted_recipients.items():
                edge_key = f"{evt.id}->{dig.activations.get(reroute_act_id).id if reroute_act_id in dig.activations else recipient}"
                # Need to find the activation that receives this event
                for act_id, act in dig.activations.items():
                    if evt.id in act.input_event_ids and act.agent_name == recipient:
                        rerouted_edge_keys.add(f"{evt.id}->{act_id}")
                        break
        
        # Compute event positions (used for edges and nodes)
        event_positions = {}
        for node in nodes:
            if node.meta.get('type') == "event":
                evt = dig.events.get(node.id)
                if not evt:
                    continue
                
                x_val = 0
                y_val = 0
                if evt.source_activation_id:
                    src_act = dig.activations.get(evt.source_activation_id)
                    if src_act:
                        x_val = (src_act.started_at + src_act.ended_at) / 2 - t0
                        src_y = lane_for_agent.get(src_act.agent_name, 0)
                        recipient_ys = []
                        for recipient in evt.recipients:
                            if recipient not in evt.rerouted_recipients and recipient in lane_for_agent:
                                recipient_ys.append(lane_for_agent[recipient])
                        for deleted_recipient in evt.deleted_recipients:
                            if deleted_recipient in lane_for_agent:
                                recipient_ys.append(lane_for_agent[deleted_recipient])
                        if recipient_ys:
                            avg_recipient_y = sum(recipient_ys) / len(recipient_ys)
                            y_val = (src_y + avg_recipient_y) / 2
                        else:
                            y_val = src_y
                else:
                    dest_times = []
                    dest_ys = []
                    for edge in edges:
                        if edge.src == evt.id:
                            dst_node = next((n for n in nodes if n.id == edge.dst), None)
                            if dst_node and dst_node.meta.get('type') == 'activation':
                                dst_act = dig.activations.get(edge.dst)
                                if dst_act:
                                    dest_times.append(dst_act.started_at - t0)
                                    dest_ys.append(lane_for_agent.get(dst_act.agent_name, 0))
                    if dest_times:
                        x_val = min(dest_times) * 0.9 if min(dest_times) > 0 else -0.5
                        y_val = sum(dest_ys) / len(dest_ys)
                    else:
                        x_val = -0.5
                        y_val = len(agent_names) / 2.0
                
                event_positions[evt.id] = (x_val, y_val)

        # Apply vertical repulsion to event nodes that are close in time
        def apply_vertical_repulsion(positions, min_distance=0.3, x_threshold=1.5):
            if len(positions) < 2:
                return positions
            event_ids = list(positions.keys())
            new_positions = dict(positions)
            for _ in range(10):
                moved = False
                for i, eid1 in enumerate(event_ids):
                    x1, y1 = new_positions[eid1]
                    for eid2 in event_ids[i + 1:]:
                        x2, y2 = new_positions[eid2]
                        if abs(x1 - x2) <= x_threshold and abs(y1 - y2) < min_distance:
                            delta = (min_distance - abs(y1 - y2)) / 2.0
                            if y1 <= y2:
                                y1 -= delta
                                y2 += delta
                            else:
                                y1 += delta
                                y2 -= delta
                            new_positions[eid1] = (x1, y1)
                            new_positions[eid2] = (x2, y2)
                            moved = True
                if not moved:
                    break
            return new_positions

        event_positions = apply_vertical_repulsion(event_positions)

        # Draw edges first (background layer)
        for edge in edges:
            src_node = next((n for n in nodes if n.id == edge.src), None)
            dst_node = next((n for n in nodes if n.id == edge.dst), None)
            if not src_node or not dst_node:
                continue
            
            # Check if this specific edge is deleted (incoming edge to reroute/discard agent)
            edge_key = f"{edge.src}->{edge.dst}"
            is_deleted_edge = edge_key in dig.deleted_edges
            
            # Get time and position from DIG objects, not GraphNode
            src_time = 0
            dst_time = 0
            src_y = 0
            dst_y = 0
            
            # Source: activation or event
            if src_node.meta.get('type') == 'activation':
                src_act = dig.activations.get(edge.src)
                if src_act:
                    src_time = src_act.started_at - t0
                    src_y = lane_for_agent.get(src_act.agent_name, 0)
            elif src_node.meta.get('type') == 'event':
                if edge.src in event_positions:
                    src_time, src_y = event_positions[edge.src]
            
            # Destination: activation or event
            if dst_node.meta.get('type') == 'activation':
                dst_act = dig.activations.get(edge.dst)
                if dst_act:
                    dst_time = dst_act.started_at - t0
                    dst_y = lane_for_agent.get(dst_act.agent_name, 0)
            elif dst_node.meta.get('type') == 'event':
                if edge.dst in event_positions:
                    dst_time, dst_y = event_positions[edge.dst]
            
            # Get edge type from DIG data
            dst_act = dig.activations.get(edge.dst) if dst_node.meta.get('type') == 'activation' else None
            src_evt = dig.events.get(edge.src)
            
            # Determine edge action: input_action > recipient_edge_type > pending
            edge_action = 'pending'
            if dst_act and dst_act.input_actions:
                edge_action = dst_act.input_actions.get(edge.src, 'pending')
            # If no explicit action, check if it was a rerouted delivery
            if edge_action == 'pending' and src_evt and dst_act:
                if src_evt.recipient_edge_type.get(dst_act.agent_name) == 'rerouted_delivery':
                    edge_action = 'rerouted'
            # Override from graph metadata when available (ensures reroute visuals are consistent)
            if edge.meta.get("line_color") == "purple":
                edge_action = 'reroute' if edge.meta.get("line_style") == "dash" else 'rerouted'
            
            # Simple style mapping: action -> (color, alpha, linewidth, linestyle)
            style_map = {
                'consume': ('#2ca02c', 0.8, 1.5, '-'),      # solid green
                'rerouted': ('#9370db', 0.8, 1.5, '-'),     # solid purple
                'reroute': ('#9370db', 0.7, 1.5, '--'),     # dashed purple
                'discard': ('#d62728', 0.7, 1.5, '--'),     # dashed red
                'wait': ('#ff8c00', 0.7, 1.5, '--'),        # dashed orange
                'pending': ('gray', 0.4, 1.0, '-'),         # solid gray
            }
            color, alpha, lw, ls = style_map.get(edge_action, style_map['pending'])
            self.ax1.plot([src_time, dst_time], [src_y, dst_y], color=color, alpha=alpha, linewidth=lw, linestyle=ls, zorder=1)
        
        # Draw system annotation edges (dashed lines for full coverage interventions)
        for evt in dig.events.values():
            if hasattr(evt, 'system_annotation') and evt.system_annotation:
                annotation = evt.system_annotation
                system_act_id = annotation.get('system_activation_id')
                
                if system_act_id and system_act_id in dig.activations:
                    system_act = dig.activations[system_act_id]
                    system_time = system_act.started_at - t0
                    system_y = lane_for_agent.get('system', 0)
                    
                    # Get event position
                    if evt.id in event_positions:
                        evt_time, evt_y = event_positions[evt.id]
                        
                        # Draw dashed line from system to event
                        self.ax1.plot([system_time, evt_time], [system_y, evt_y],
                                     color='orange', alpha=0.6, linewidth=2,
                                     linestyle='--', zorder=1)
        
        # Draw activation nodes (circles)
        for node in nodes:
            if node.meta.get('type') == "activation":
                act = dig.activations.get(node.id)
                if not act:
                    continue
                
                x_val = act.started_at - t0
                y_val = lane_for_agent[act.agent_name]
                
                # Special handling for system agent
                if act.agent_name == "system":
                    color = self.system_color
                    marker = 's'  # Square for system
                    size = 150
                    # Add system marker text
                    self.ax1.text(x_val, y_val, 'SYS', fontsize=7, ha='center', va='center', zorder=4, weight='bold')
                else:
                    # Color by classification: submitting=green, reducing=blue, expanding=dark yellow
                    classification = node.meta.get('classification')
                    if classification == 'submitting':
                        color = '#2ca02c'  # Green for submitting
                    elif classification == 'problem-reducing':
                        color = '#1f77b4'  # Blue for problem-reducing
                    else:  # problem-expanding
                        color = '#DAA520'  # Dark yellow (goldenrod) for problem-expanding
                    marker = 'o'
                    size = 100
                
                self.ax1.scatter(x_val, y_val, c=color, marker=marker, s=size, 
                               edgecolors='white', linewidths=1, zorder=3, alpha=0.8)
        
        # Draw event nodes (squares) - position between source and recipient
        for node in nodes:
            if node.meta.get('type') == "event":
                evt = dig.events.get(node.id)
                if not evt:
                    continue
                
                # Check if this is an initial problem event
                is_initial = evt.source_activation_id is None
                
                if evt.id in event_positions:
                    x_val, y_val = event_positions[evt.id]
                else:
                    x_val = -0.5
                    y_val = len(agent_names) / 2.0
                
                # Use distinct color for initial events
                marker_color = '#4CAF50' if is_initial else 'lightgray'  # Green for initial
                marker_size = 80 if is_initial else 60
                
                self.ax1.scatter(x_val, y_val, c=marker_color, marker='s', s=marker_size, 
                               edgecolors='black', linewidths=0.8, zorder=2, alpha=0.7)
        
        # ========== SUBPLOT 2: Timeline with SOLID edges only (no deleted edges) ==========
        self.ax2.set_title('DIG (Clean)', fontsize=11, pad=10)
        self.ax2.set_ylabel('Agent', fontsize=10)
        self.ax2.set_yticks(range(len(agent_names)))
        self.ax2.set_yticklabels(agent_names, fontsize=9)
        self.ax2.grid(False)
        
        # Draw only solid edges (consume or pending - skip reroute/discard/wait which are dashed)
        for edge in edges:
            src_node = next((n for n in nodes if n.id == edge.src), None)
            dst_node = next((n for n in nodes if n.id == edge.dst), None)
            if not src_node or not dst_node:
                continue
            
            # Get per-edge action from destination activation
            edge_action = None
            dst_act = dig.activations.get(edge.dst) if dst_node.meta.get('type') == 'activation' else None
            if dst_act and dst_act.input_actions:
                edge_action = dst_act.input_actions.get(edge.src)
            
            # Skip dashed edges (reroute, discard, wait) - only show solid edges (consume, pending)
            if edge_action in ('reroute', 'discard', 'wait'):
                continue
            
            # Get time and position (same logic as ax1)
            src_time = 0
            dst_time = 0
            src_y = 0
            dst_y = 0
            
            # Source: activation or event
            if src_node.meta.get('type') == 'activation':
                src_act = dig.activations.get(edge.src)
                if src_act:
                    src_time = src_act.started_at - t0
                    src_y = lane_for_agent.get(src_act.agent_name, 0)
            elif src_node.meta.get('type') == 'event':
                if edge.src in event_positions:
                    src_time, src_y = event_positions[edge.src]
            
            # Destination: activation or event
            if dst_node.meta.get('type') == 'activation':
                dst_act = dig.activations.get(edge.dst)
                if dst_act:
                    dst_time = dst_act.started_at - t0
                    dst_y = lane_for_agent.get(dst_act.agent_name, 0)
            elif dst_node.meta.get('type') == 'event':
                if edge.dst in event_positions:
                    dst_time, dst_y = event_positions[edge.dst]
            
            # Check if it's a rerouted edge for color
            is_system_edge = edge.meta.get('system_event', False)
            
            # Edge color based on action (only consume or pending at this point)
            if is_system_edge:
                # System event edge: dashed gray
                self.ax2.plot([src_time, dst_time], [src_y, dst_y], 
                             color='gray', alpha=0.2, linewidth=0.8, 
                             linestyle='--', zorder=1)
            elif edge_action == 'consume':
                # Consumed: solid green
                self.ax2.plot([src_time, dst_time], [src_y, dst_y], 
                             color=self.edge_action_colors['consume'], alpha=0.7, linewidth=1.5, 
                             linestyle='-', zorder=1)
            else:
                # Pending: solid gray
                self.ax2.plot([src_time, dst_time], [src_y, dst_y], 
                             color='gray', alpha=0.3, linewidth=0.8, 
                             linestyle='-', zorder=1)
        
        # Draw activation nodes (circles) on ax2
        for node in nodes:
            if node.meta.get('type') == "activation":
                act = dig.activations.get(node.id)
                if not act:
                    continue
                
                x_val = act.started_at - t0
                y_val = lane_for_agent[act.agent_name]
                
                # Special handling for system agent
                if act.agent_name == "system":
                    color = self.system_color
                    marker = 's'
                    size = 150
                    self.ax2.text(x_val, y_val, 'SYS', fontsize=7, ha='center', va='center', zorder=4, weight='bold')
                else:
                    # Color by classification: submitting=green, reducing=blue, expanding=dark yellow
                    classification = node.meta.get('classification')
                    if classification == 'submitting':
                        color = '#2ca02c'  # Green for submitting
                    elif classification == 'problem-reducing':
                        color = '#1f77b4'  # Blue for problem-reducing
                    else:  # problem-expanding
                        color = '#DAA520'  # Dark yellow (goldenrod) for problem-expanding
                    marker = 'o'
                    size = 100
                
                self.ax2.scatter(x_val, y_val, c=color, marker=marker, s=size, 
                               edgecolors='white', linewidths=1, zorder=3, alpha=0.8)
        
        # Draw event nodes (squares) on ax2
        for node in nodes:
            if node.meta.get('type') == "event":
                evt = dig.events.get(node.id)
                if not evt:
                    continue
                
                # Check if this is an initial problem event
                is_initial = evt.source_activation_id is None
                
                if evt.id in event_positions:
                    x_val, y_val = event_positions[evt.id]
                else:
                    x_val = -0.5
                    y_val = len(agent_names) / 2.0
                
                # Use distinct color for initial events
                marker_color = '#4CAF50' if is_initial else 'lightgray'  # Green for initial
                marker_size = 80 if is_initial else 60
                
                self.ax2.scatter(x_val, y_val, c=marker_color, marker='s', s=marker_size, 
                               edgecolors='black', linewidths=0.8, zorder=2, alpha=0.7)
        
        # ========== SUBPLOT 3: Gantt chart (temporal bars) ==========
        self.ax3.set_title('Activation Time', fontsize=11, pad=10)
        self.ax3.set_xlabel('Time (s)', fontsize=10)
        self.ax3.set_ylabel('Agent', fontsize=10)
        self.ax3.set_yticks(range(len(agent_names)))
        self.ax3.set_yticklabels(agent_names, fontsize=9)
        self.ax3.grid(False)
        
        # Get efficiency metrics from DIG
        metrics = dig.get_efficiency_metrics()
        total_elapsed_time = metrics["elapsed_time"]
        total_activation_time = metrics["activation_time"]
        
        # Draw temporal bars for each activation
        for act in dig.activations.values():
            start_time = act.started_at - t0
            end_time = act.ended_at - t0
            duration = end_time - start_time
            y_val = lane_for_agent[act.agent_name]
            
            # Special handling for system agent
            if act.agent_name == "system":
                color = self.system_color
            else:
                # All agent activations are same color (decisions are per-edge now)
                color = self.agent_color
            
            self.ax3.barh(y_val, duration, left=start_time, height=0.6, 
                         color=color, alpha=0.7, edgecolor='white', linewidth=1)
        
        # Add timer annotations
        timer_text = f"Time so far: {total_elapsed_time:.2f}s\nSum of activation time: {total_activation_time:.2f}s"
        self.ax3.text(0.02, 0.98, timer_text, transform=self.ax3.transAxes,
                     fontsize=9, verticalalignment='top', bbox=dict(boxstyle='round', 
                     facecolor='wheat', alpha=0.5))
        
        # Add legend for edge actions (per-edge decisions)
        from matplotlib.lines import Line2D
        legend_elements = [
            # Nodes
            mpatches.Patch(color=self.agent_color, label='Agent Activation'),
            mpatches.Patch(color=self.system_color, label='System'),
            # Edge actions
            Line2D([0], [0], color=self.edge_action_colors['consume'], linewidth=2, linestyle='-', label='Consume'),
            Line2D([0], [0], color=self.edge_action_colors['reroute'], linewidth=2, linestyle='--', label='Reroute'),
            Line2D([0], [0], color=self.edge_action_colors['discard'], linewidth=2, linestyle='--', label='Discard'),
            Line2D([0], [0], color=self.edge_action_colors['wait'], linewidth=2, linestyle='--', label='Wait'),
            Line2D([0], [0], color=self.edge_action_colors['pending'], linewidth=2, linestyle='-', label='Pending'),
        ]
        self.ax3.legend(handles=legend_elements, loc='upper right', fontsize=8, ncol=7)
        
        # Adjust layout
        self.fig.tight_layout()
    
    def clear(self):
        """Clear the current DIG visualization."""
        self.current_dig = None
        self.detected_errors.clear()
        self.ax1.clear()
        self.ax2.clear()
        self.ax3.clear()
        self.ax1.set_title('Timeline View (All Edges)')
        self.ax2.set_title('Timeline View (Solid Edges Only)')
        self.ax3.set_title('Gantt Chart View')
        self.ax2.set_xlabel('Time (s)')
        self.ax2.set_ylabel('Events')
        self.ax2.grid(False)
        self.fig.canvas.draw_idle()
    
    def start(self, block=True):
        """
        Start the real-time visualization animation.
        
        Args:
            block: Whether to block until window is closed (default True)
        """
        # Enable interactive mode for real-time updates
        plt.ion()
        
        self.anim = FuncAnimation(
            self.fig, self._process_updates, 
            interval=self.update_interval, 
            cache_frame_data=False
        )
        
        # Show the figure
        plt.show(block=block)
        
        # If non-blocking, ensure the figure is drawn
        if not block:
            plt.pause(0.001)
    
    def _on_close(self, event):
        """Handle window close event."""
        self.window_closed = True
    
    def wait_for_close(self):
        """Wait for the visualization window to be closed."""
        while not self.window_closed and plt.fignum_exists(self.fig.number):
            plt.pause(0.1)
