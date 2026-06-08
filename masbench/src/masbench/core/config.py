"""Run configuration for one benchmark execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunConfig:
    """How to run one instance. ``use_planner`` is reserved for Plan 2/3."""

    benchmark: str = "silo_bench"
    use_planner: bool = False
    use_skill_evolution: bool = False
    topology: str = "mesh"
    objective: str = "balanced"
    # Planner-path only. ``topology_select`` (default) picks a named topology;
    # ``graph_generate`` has the emperor LLM invent a bespoke temporal DAG via
    # exp_graph.mas.graph_generation.plan_free_graph, then executes its
    # protocol_spec. The graph_* knobs are the hard constraints handed to the
    # generator (defaults mirror MASRuntimeConfig / the paper).
    planner_mode: str = "topology_select"
    num_graph_candidates: int = 1
    graph_max_steps: int = 4
    graph_max_messages: int = 32
    graph_max_receiver_fan_in: int = 4
    # Planner-path only: how soldiers initialize/merge beliefs in ProtocolRunner.
    merge_mode: str = "deterministic"
    init_mode: str = "deterministic"
    n_agents: int | None = None
    max_rounds: int = 4
    llm_provider: str = "fake"
    model_name: str = "fake"
    base_url: str | None = None
    api_key_env: str | None = None
    thinking_enabled: bool | None = None
    seed: int = 0
    consensus_threshold: float = 0.8
    final_accept_threshold: float = 0.7
    temperature: float = 0.0
