"""Optional LangGraph backend for MAS outer workflows."""

from __future__ import annotations

from typing import Any

from exp_graph.mas.workflow import (
    MASWorkflowConfig,
    MASWorkflowState,
    WorkflowExecutionError,
    WorkflowRunOptions,
    _append_event,
    _load_or_create_state,
    _selected_nodes,
    execute_workflow_node,
    write_workflow_report,
)


def run_langgraph_workflow(
    *,
    config: MASWorkflowConfig,
    options: WorkflowRunOptions,
) -> MASWorkflowState:
    """Run the workflow through LangGraph if the optional dependency exists."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - depends on optional extra.
        raise RuntimeError(
            "LangGraph backend requested but langgraph is not installed. "
            "Install it with: pip install -e '.[workflow]'"
        ) from exc

    initial = _load_or_create_state(config, options)
    nodes = _selected_nodes(initial, options)
    _append_event(config, {"event": "workflow_start", "backend": "langgraph", "nodes": nodes})
    if not nodes:
        write_workflow_report(config, initial)
        return initial

    graph = StateGraph(dict)
    for node_name in nodes:
        graph.add_node(node_name, _node_fn(config, options, node_name))
    graph.set_entry_point(nodes[0])
    for index, node_name in enumerate(nodes):
        if index == len(nodes) - 1:
            graph.add_edge(node_name, END)
            continue
        next_node = nodes[index + 1]
        graph.add_conditional_edges(
            node_name,
            _route_fn(node_name, next_node, options),
            {"next": next_node, "end": END},
        )
    app = graph.compile()
    final_payload = app.invoke(initial.model_dump(mode="json"))
    final = MASWorkflowState.model_validate(final_payload)
    write_workflow_report(config, final)
    if final.failed_node:
        result = final.node_results.get(final.failed_node)
        raise WorkflowExecutionError(result.error if result else final.failed_node)
    _append_event(config, {"event": "workflow_done", "failed_node": final.failed_node})
    return final


def _node_fn(config: MASWorkflowConfig, options: WorkflowRunOptions, node_name: str):
    def run_node(payload: dict[str, Any]) -> dict[str, Any]:
        state = MASWorkflowState.model_validate(payload)
        execute_workflow_node(
            config=config,
            options=options,
            state=state,
            node_name=node_name,
        )
        return state.model_dump(mode="json")

    return run_node


def _route_fn(node_name: str, next_node: str, options: WorkflowRunOptions):
    def route(payload: dict[str, Any]) -> str:
        state = MASWorkflowState.model_validate(payload)
        result = state.node_results.get(node_name)
        if state.failed_node:
            return "end"
        if result and result.status == "paused":
            return "end"
        if options.stop_after == node_name:
            return "end"
        return "next"

    return route
