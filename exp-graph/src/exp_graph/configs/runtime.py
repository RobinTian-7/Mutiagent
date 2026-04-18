"""Runtime configuration schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ExperimentConfig(BaseModel):
    """Configuration for a topology-effect experiment run."""

    topology_name: str = "chain"
    n_agents: int = 8
    max_rounds: int = 5
    seed: int = 0
    model_name: str = "gpt-4o-mini"
    prompt_template_name: str = "solver_v1"
    llm_provider: str = "auto"
    consensus_threshold: float = 0.8
    final_accept_threshold: float = 0.7
    adjudication_margin: float = 0.1
    use_llm_adjudicator: bool = False
