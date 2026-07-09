"""
viz_interactive.py

Interactive plotly visualizations for DIG (Directed Interaction Graph).
Creates interactive HTML with hover-based edge highlighting showing cumulative coverage.
"""

from typing import Optional, Dict, Set
import json
import os
import textwrap

import plotly.graph_objects as go

from ..core.dig import InteractionLog, InteractionMode
from ..core.dig import build_activation_event_graph
from ..analysis.error_detection.coverage import compute_rule_coverage


def wrap_text(text: str, width: int = 80) -> str:
    """Wrap text to specified width, preserving existing line breaks."""
    if not text:
        return text
    lines = str(text).split('\n')
    wrapped_lines = []
    for line in lines:
        if line.strip():
            wrapped_lines.extend(textwrap.wrap(line, width=width))
        else:
            wrapped_lines.append('')
    return '<br>'.join(wrapped_lines)


def create_interactive_viz(dig: InteractionLog, output_file: str, t0: Optional[float] = None) -> None:
    """
    Create an interactive HTML visualization with cumulative edge highlighting on hover.
    
    When hovering over an activation node, all edges covered up to that point are highlighted.
    
    Args:
        dig: The DIG to visualize
        output_file: Path to save the HTML file
        t0: Reference time (if None, uses first activation time)
    """
    if not dig.activations:
        print("No activations recorded, skipping interactive visualization.")
        return
    
    # Calculate reference time
    if t0 is None:
        t0 = min(a.started_at for a in dig.activations.values())
    
    # Assign vertical lanes for agents
    agent_names = sorted({a.agent_name for a in dig.activations.values()})
    lane_for_agent = {name: idx for idx, name in enumerate(agent_names)}
    
    # Build graph structure
    nodes, edges, activation_inputs, activation_outputs, event_source = build_activation_event_graph(dig)
    
    # Compute coverage for all activations
    cov = compute_rule_coverage(nodes, edges, activation_inputs, activation_outputs, event_source)
    
    # Compute cumulative coverage up to each activation (in temporal order)
    activations_by_time = sorted(dig.activations.values(), key=lambda a: a.started_at)
    cumulative_cov: Dict[str, Dict[str, any]] = {}
    all_covered_edges: Set[str] = set()
    all_covered_problems: Set[str] = set()
    
    for act in activations_by_time:
        # Add this activation's coverage
        node_cov = cov.get(act.id, {})
        direct_edges = set(node_cov.get("direct", []))
        soft_edges = set(node_cov.get("soft", []))
        all_covered_edges.update(direct_edges)
        all_covered_edges.update(soft_edges)
        
        # Extract problem IDs from all events seen so far
        for event_id in activation_inputs.get(act.id, []):
            evt = dig.events.get(event_id)
            if evt and evt.payload:
                prob_id = evt.payload.get("problem_id")
                if prob_id:
                    all_covered_problems.add(prob_id)
        
        # Store cumulative state for this activation
        cumulative_cov[act.id] = {
            "total_edges": len(all_covered_edges),
            "edges": list(all_covered_edges),
            "total_problems": len(all_covered_problems),
            "problems": list(all_covered_problems)
        }
    
    # Create figure
    fig = go.Figure()
    
    # ========== Compute event node positions first ==========
    event_positions: Dict[str, tuple] = {}  # event_id -> (x, y)
    
    for node in nodes:
        if node.meta.get('type') == "event":
            evt = dig.events.get(node.id)
            if not evt:
                continue
            
            # Check if this is an initial problem event (no source activation)
            if not evt.source_activation_id:
                # Initial event: position before all activations
                # Find destination activations
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
                
                if dest_times and dest_ys:
                    # Position slightly before first destination (10% back)
                    min_dest_time = min(dest_times)
                    x_val = min_dest_time * 0.9 if min_dest_time > 0 else -0.5
                    y_val = sum(dest_ys) / len(dest_ys)
                else:
                    # No destinations, put at start
                    x_val = -0.5
                    y_val = len(agent_names) / 2.0
                
                event_positions[evt.id] = (x_val, y_val)
                continue
            
            # Regular event with source activation
            src_time, src_y = 0, 0
            src_end_time = 0
            src_act = None
            if evt.source_activation_id:
                src_act = dig.activations.get(evt.source_activation_id)
                if src_act:
                    src_time = src_act.started_at - t0
                    src_end_time = src_act.ended_at - t0
                    src_y = lane_for_agent.get(src_act.agent_name, 0)
            
            # Check if source is a submit activation
            is_submit = src_act and src_act.mode == InteractionMode.SUBMIT
            
            # Find destination activations for vertical positioning
            dest_ys = []
            for edge in edges:
                if edge.src == evt.id:
                    dst_node = next((n for n in nodes if n.id == edge.dst), None)
                    if dst_node and dst_node.meta.get('type') == 'activation':
                        dst_act = dig.activations.get(edge.dst)
                        if dst_act:
                            dest_ys.append(lane_for_agent.get(dst_act.agent_name, 0))
            
            # Position event
            if is_submit:
                # Submit events: position to the right of the source node
                x_val = src_end_time + 0.5  # Offset to the right of end time
                y_val = src_y
            elif dest_ys:
                # Normal events: horizontal at END of source activation (slightly left to avoid overlap), vertical at average of destinations
                x_val = src_end_time - 0.25  # Slightly left to avoid overlapping with next activation
                y_val = sum(dest_ys) / len(dest_ys)
            else:
                x_val = (src_end_time if src_end_time > 0 else src_time) - 0.25
                y_val = src_y
            
            event_positions[evt.id] = (x_val, y_val)
    
    # ========== Apply vertical repulsion to overlapping event nodes ==========
    # Keep x fixed, adjust y to avoid overlap
    def apply_vertical_repulsion(positions: Dict[str, tuple], min_distance: float = 0.3, x_threshold: float = 1.5) -> Dict[str, tuple]:
        """Apply vertical repulsion to event nodes that are too close horizontally."""
        if len(positions) < 2:
            return positions
        
        # Convert to list for iteration
        event_ids = list(positions.keys())
        new_positions = dict(positions)
        
        # Multiple passes to resolve overlaps
        for _ in range(10):
            moved = False
            for i, eid1 in enumerate(event_ids):
                x1, y1 = new_positions[eid1]
                for eid2 in event_ids[i+1:]:
                    x2, y2 = new_positions[eid2]
                    
                    # Check if horizontally close
                    if abs(x1 - x2) < x_threshold:
                        # Check if vertically overlapping
                        dy = y2 - y1
                        if abs(dy) < min_distance:
                            # Apply repulsion - push apart vertically
                            push = (min_distance - abs(dy)) / 2 + 0.05
                            if dy >= 0:
                                new_positions[eid1] = (x1, y1 - push)
                                new_positions[eid2] = (x2, y2 + push)
                            else:
                                new_positions[eid1] = (x1, y1 + push)
                                new_positions[eid2] = (x2, y2 - push)
                            moved = True
            if not moved:
                break
        
        return new_positions
    
    event_positions = apply_vertical_repulsion(event_positions)
    
    # ========== Add edges first (so they appear below nodes) ==========
    edge_traces = []
    edge_ids_list = []
    
    for edge in edges:
        src_node = next((n for n in nodes if n.id == edge.src), None)
        dst_node = next((n for n in nodes if n.id == edge.dst), None)
        if not src_node or not dst_node:
            continue
        
        # Get coordinates
        src_time, src_y = 0, 0
        dst_time, dst_y = 0, 0
        
        # Source node
        if src_node.meta.get('type') == 'activation':
            src_act = dig.activations.get(edge.src)
            if src_act:
                src_time = src_act.started_at - t0
                src_y = lane_for_agent.get(src_act.agent_name, 0)
        elif src_node.meta.get('type') == 'event':
            # Use precomputed event position
            if edge.src in event_positions:
                src_time, src_y = event_positions[edge.src]
        
        # Destination node
        if dst_node.meta.get('type') == 'activation':
            dst_act = dig.activations.get(edge.dst)
            if dst_act:
                dst_time = dst_act.started_at - t0
                dst_y = lane_for_agent.get(dst_act.agent_name, 0)
        elif dst_node.meta.get('type') == 'event':
            # Use precomputed event position
            if edge.dst in event_positions:
                dst_time, dst_y = event_positions[edge.dst]
        
        # Get edge action from DIG data
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
        
        # Simple style mapping: action -> (color, dash, width)
        style_map = {
            'consume': ('rgba(44,160,44,0.8)', 'solid', 1.5),
            'rerouted': ('rgba(147,112,219,0.8)', 'solid', 1.5),
            'reroute': ('rgba(147,112,219,0.7)', 'dash', 1.5),
            'discard': ('rgba(214,39,40,0.7)', 'dash', 1.5),
            'wait': ('rgba(255,140,0,0.7)', 'dash', 1.5),
            'pending': ('rgba(128,128,128,0.4)', 'solid', 1.0),
        }
        line_color, line_dash, line_width = style_map.get(edge_action, style_map['pending'])
        
        # Create edge trace
        edge_trace = go.Scatter(
            x=[src_time, dst_time, None],
            y=[src_y, dst_y, None],
            mode='lines',
            line=dict(color=line_color, width=line_width, dash=line_dash),
            hoverinfo='skip',
            showlegend=False,
        )
        
        edge_traces.append(edge_trace)
        edge_ids_list.append(edge.id)
        fig.add_trace(edge_trace)
    
    # ========== Add system annotation edges (dashed lines for full coverage interventions) ==========
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
                    annotation_trace = go.Scatter(
                        x=[system_time, evt_time, None],
                        y=[system_y, evt_y, None],
                        mode='lines',
                        line=dict(
                            color='rgba(255,165,0,0.6)',  # Orange for system annotation
                            width=2,
                            dash='dash'
                        ),
                        hoverinfo='skip',
                        showlegend=False,
                        meta={'annotation': True, 'intervention_type': annotation.get('intervention_type')}
                    )
                    fig.add_trace(annotation_trace)
    
    # ========== Add activation nodes (circles) ==========
    activation_traces = []
    
    for node in nodes:
        if node.meta.get('type') == "activation":
            act = dig.activations.get(node.id)
            if not act:
                continue
            
            x_val = act.started_at - t0
            y_val = lane_for_agent[act.agent_name]
            # Color by classification: system=magenta, submitting=green, reducing=blue, expanding=dark yellow
            if act.agent_name == 'system':
                color = '#8B008B'  # Magenta for system
            else:
                classification = node.meta.get('classification')
                if classification == 'submitting':
                    color = '#2ca02c'  # Green for submitting
                elif classification == 'problem-reducing':
                    color = '#1f77b4'  # Blue for problem-reducing
                else:  # problem-expanding
                    color = '#DAA520'  # Dark yellow (goldenrod) for problem-expanding
            
            # Get coverage info for this activation (current node only)
            node_cov = cov.get(act.id, {})
            direct_edges = node_cov.get("direct", [])
            soft_edges = node_cov.get("soft", [])
            dashed_edges = node_cov.get("dashed", [])
            total_covered_this_node = len(direct_edges) + len(soft_edges)
            
            # Get cumulative coverage up to this point
            cumul = cumulative_cov.get(act.id, {})
            cumul_edges = cumul.get("total_edges", 0)
            cumul_problems = cumul.get("total_problems", 0)
            problem_list = cumul.get("problems", [])
            
            # Coverage edges to highlight (solid edges + dashed edges)
            # Solid edges are from backward traversal, dashed edges are only directly connected
            covered_edge_ids = direct_edges + soft_edges
            dashed_edge_ids = dashed_edges
            
            # Format problem list for display
            problem_str = wrap_text(", ".join(str(p) for p in problem_list), width=80)
            
            # Format reasoning with line breaks for readability
            reasoning_text = act.reasoning or 'No reasoning provided'
            wrapped_reasoning = wrap_text(reasoning_text, width=80)
            
            # Format tool calls with raw arguments
            if act.tool_calls:
                tool_info_lines = []
                for call in act.tool_calls:
                    tool_name = call.get('tool', call.get('tool_name', 'unknown'))
                    # Show all arguments as-is
                    args_parts = []
                    for key, value in call.items():
                        if key not in ['tool', 'tool_name']:
                            args_parts.append(f"{key}={repr(value)}")
                    args_str = ', '.join(args_parts)
                    wrapped_args = wrap_text(args_str, width=70)
                    tool_info_lines.append(f"- {tool_name}(<br>    {wrapped_args}<br>  )")
                
                tool_info = '<br>'.join(tool_info_lines)
            else:
                tool_info = 'No tools used'
            
            # Add intervention type if this is a system activation
            intervention_info = ""
            if act.agent_name == "system" and act.intervention_type:
                intervention_info = f"<br><b>Intervention Type:</b> {act.intervention_type}"
            
            # Format mode - handle both InteractionMode enum and string
            mode_display = act.mode.name if hasattr(act.mode, 'name') else str(act.mode)
            
            # Get classification from node metadata (computed in graph builder)
            node = next((n for n in nodes if n.id == act.id), None)
            classification = ""
            if node and node.meta.get('classification'):
                class_type = node.meta['classification']
                if class_type == "submitting":
                    classification = "<br><b style='color:green;'>Classification: Submitting</b>"
                elif class_type == "problem-expanding":
                    classification = "<br><b style='color:#c0b000;'>Classification: Problem-Expanding</b>"
                else:
                    classification = "<br><b style='color:blue;'>Classification: Problem-Reducing</b>"
            
            # Get buffer contents (input events) at time of activation
            # Show exactly what agent sees: event_id, info (system), payload (agent, minus data)
            buffer_event_ids = act.input_event_ids
            buffer_info = f"Buffer size: {len(buffer_event_ids)}"
            if len(buffer_event_ids) > 0:
                buffer_msgs = []
                for idx, ev_id in enumerate(buffer_event_ids):
                    if ev_id in dig.events:
                        ev = dig.events[ev_id]
                        # Build observation format (same as build_observation in dig.py)
                        obs_entry = {
                            "event_id": ev.id,
                            "info": ev.info,
                            "payload": {k: v for k, v in ev.payload.items() if k != "data"}
                        }
                        buffer_msgs.append(f"<br>  Event {idx+1}:")
                        obs_str = wrap_text(json.dumps(obs_entry, ensure_ascii=False), width=60)
                        buffer_msgs.append(f"    {obs_str}")
                buffer_info += "".join(buffer_msgs)
            
            # Build per-event decisions info
            decisions_info = ""
            if act.input_actions:
                decision_lines = ["<b>Decisions:</b>"]
                for ev_id, action in act.input_actions.items():
                    ev = dig.events.get(ev_id)
                    # Get reroute recipients if action is reroute
                    recipients_str = ""
                    if action == "reroute" and ev:
                        # Find who this was rerouted to
                        rerouted_to = [r for r, src_act in ev.rerouted_recipients.items() if src_act == act.id]
                        if rerouted_to:
                            recipients_str = f" → {', '.join(rerouted_to)}"
                    decision_lines.append(f"<br>  {ev_id}: <b>{action}</b>{recipients_str}")
                decisions_info = "".join(decision_lines) + "<br>"
            
            # Different hover text for system vs regular agents
            if act.agent_name == "system":
                hover_text = (
                    f"<b>{act.agent_name}</b><br>"
                    f"Mode: {mode_display}<br>"
                    f"ID: {act.id}<br>"
                    f"Time: {x_val:.2f}s<br>"
                    f"Duration: {act.ended_at - act.started_at:.2f}s{intervention_info}"
                )
            else:
                hover_text = (
                    f"<b>{act.agent_name}</b><br>"
                    f"Mode: {mode_display}<br>"
                    f"ID: {act.id}<br>"
                    f"Time: {x_val:.2f}s<br>"
                    f"Duration: {act.ended_at - act.started_at:.2f}s{intervention_info}{classification}<br>"
                    f"{decisions_info}"
                    f"<b>Buffer:</b><br>{buffer_info}<br>"
                    f"<b>Tools:</b><br>{tool_info}<br>"
                    f"<b>Reasoning:</b><br>{wrapped_reasoning}"
                )
            
            activation_trace = go.Scatter(
                x=[x_val],
                y=[y_val],
                mode='markers',
                marker=dict(size=12, color=color, symbol='circle', line=dict(width=1, color='white')),
                text=[hover_text],
                hovertemplate='%{text}<extra></extra>',
                customdata=[[json.dumps({'type': 'activation', 'node_id': act.id, 'covered_edges': covered_edge_ids, 'dashed_edges': dashed_edge_ids})]],
                showlegend=False,
                name=f'act_{act.agent_name}'
            )
            
            activation_traces.append(activation_trace)
            fig.add_trace(activation_trace)
    
    # ========== Add event nodes (squares) ==========
    for node in nodes:
        if node.meta.get('type') == "event":
            evt = dig.events.get(node.id)
            if not evt:
                continue
            if evt.id not in event_positions:
                # Fallback: position event near its source activation if possible
                if evt.source_activation_id and evt.source_activation_id in dig.activations:
                    src_act = dig.activations[evt.source_activation_id]
                    x_val = (src_act.ended_at - t0) - 0.25
                    y_val = lane_for_agent.get(src_act.agent_name, 0)
                else:
                    x_val = -0.5
                    y_val = len(agent_names) / 2.0
                event_positions[evt.id] = (x_val, y_val)
            
            x_val, y_val = event_positions[evt.id]
            
            # Check if this is an initial problem event
            is_initial = evt.source_activation_id is None
            
            # Find incoming and outgoing edges for this event
            incoming_edges = []
            outgoing_edges = []
            for edge in edges:
                if edge.dst == evt.id:
                    incoming_edges.append(edge.id)
                elif edge.src == evt.id:
                    outgoing_edges.append(edge.id)
            
            # Recipients (no delivery status computed in viz)
            delivery_info = list(evt.recipients)
            
            # Format recipients display
            num_recipients = len(evt.recipients)
            if num_recipients > 0:
                recipients_str = f"recipients ({num_recipients}): {', '.join(delivery_info)}"
            else:
                recipients_str = "recipients (0): none"
            
            # Build info display - system/tool-generated (trustworthy)
            info_lines = []
            for k, v in evt.info.items():
                v_str = wrap_text(str(v), width=70)
                info_lines.append(f"  {k}: {v_str}")
            info_str = "<br>".join(info_lines) if info_lines else "  (none)"
            
            # Build payload display - agent-generated
            payload_lines = []
            for k, v in evt.payload.items():
                v_str = wrap_text(str(v), width=70)
                payload_lines.append(f"  {k}: {v_str}")
            payload_str = "<br>".join(payload_lines) if payload_lines else "  (none)"
            
            event_type = "Initial Problem Event" if is_initial else f"Event {evt.id[:8]}..."
            
            hover_text = (
                f"<b>{event_type}</b><br>"
                f"{recipients_str}<br>"
                f"<b>Info (system):</b><br>{info_str}<br>"
                f"<b>Payload (agent):</b><br>{payload_str}"
            )
            
            # Use distinct color for initial events
            marker_color = '#4CAF50' if is_initial else 'lightgray'  # Green for initial, gray for others
            marker_size = 10 if is_initial else 8
            
            fig.add_trace(go.Scatter(
                x=[x_val],
                y=[y_val],
                mode='markers',
                marker=dict(size=marker_size, color=marker_color, symbol='square', line=dict(width=1, color='black')),
                text=[hover_text],
                hovertemplate='%{text}<extra></extra>',
                customdata=[[json.dumps({'type': 'event', 'event_id': evt.id, 'incoming_edges': incoming_edges, 'outgoing_edges': outgoing_edges})]],
                showlegend=False
            ))
    
    # Layout
    fig.update_layout(
        height=800,
        title_text="Interactive DIG - Hover on edges to see action type, hover on nodes for details",
        hovermode='closest',
        showlegend=True,
        plot_bgcolor='rgba(0,0,0,0)',  # Transparent plot background
        paper_bgcolor='rgba(0,0,0,0)',  # Transparent paper background
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.5)",  # 50% transparent white
            font_size=12,
            font_family="monospace",
            align="left",
            namelength=-1
        ),
        xaxis=dict(
            title="Time (s)",
            showgrid=False,
            zeroline=False
        ),
        yaxis=dict(
            title="Agent",
            tickvals=list(range(len(agent_names))),
            ticktext=agent_names,
            showgrid=False,
            zeroline=False
        ),
        legend=dict(
            title="Edge Actions",
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    # Add legend traces for edge action colors with correct line styles
    # consume: solid green, rerouted: solid purple, reroute: dashed purple, discard: dashed red, wait: dashed orange, pending: solid gray
    legend_items = [
        ('Consume', '#2ca02c', 'solid'),
        ('Rerouted', '#9370db', 'solid'),  # New recipient of rerouted event
        ('Reroute', '#9370db', 'dash'),    # Original recipient forwarded
        ('Discard', '#d62728', 'dash'),
        ('Wait', '#ff8c00', 'dash'),
        ('Pending', 'gray', 'solid'),
    ]
    for action_name, action_color, action_dash in legend_items:
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='lines',
            line=dict(color=action_color, width=3, dash=action_dash),
            name=action_name,
            showlegend=True
        ))
    
    # Write HTML with custom JavaScript for edge highlighting
    html_str = fig.to_html(include_plotlyjs='cdn')
    
    # Add custom CSS for hover label styling
    custom_css = """
    <style>
    /* Control hover label width and wrapping */
    .hoverlayer .hovertext {
        max-width: 300px !important;
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
        overflow-wrap: break-word !important;
    }
    .hoverlayer .hovertext path {
        max-width: 300px !important;
    }
    .hoverlayer .hovertext text {
        max-width: 280px !important;
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
    }
    </style>
    """
    
    # Insert CSS into head
    html_str = html_str.replace('</head>', custom_css + '</head>')
    
    # Create edge ID to trace index mapping
    edge_mapping = {edge_ids_list[i]: i for i in range(len(edge_ids_list))}
    
    # Read external JavaScript file
    js_file_path = os.path.join(os.path.dirname(__file__), 'viz_interactive.js')
    with open(js_file_path, 'r') as f:
        external_js = f.read()
    
    # Add initialization script with edge mapping
    custom_js = f"""
    <script>
    {external_js}
    </script>
    <script>
    // Initialize with edge mapping data
    document.addEventListener('DOMContentLoaded', function() {{
        initializeEdgeHighlighting({json.dumps(edge_mapping)}, {len(edge_ids_list)});
    }});
    </script>
    """
    
    # Insert custom JavaScript before closing </body> tag
    html_str = html_str.replace('</body>', custom_js + '</body>')
    
    with open(output_file, 'w') as f:
        f.write(html_str)
    
    print(f"[SAVE] Saved interactive visualization: {output_file}")


def create_activation_event_timeline_coverage_viz(dig: InteractionLog, output_file: str) -> None:
    """
    Legacy function for compatibility. Creates the same interactive visualization.
    """
    create_interactive_viz(dig, output_file)
