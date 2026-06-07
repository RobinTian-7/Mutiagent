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
