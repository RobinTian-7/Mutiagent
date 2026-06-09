"""Run configuration for one benchmark execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunConfig:
    """How to run one instance. ``use_planner`` is reserved for Plan 2/3."""

    benchmark: str = "silo_bench"
    use_planner: bool = False
    use_skill_evolution: bool = False
    # B2 (opt-in): run the LLM design-insight minister over the evolution evidence,
    # falsify insights against held-out, and fold the VERIFIED ones into the skill
    # bank (richer design rules that drive generation). Default off (extra LLM calls).
    use_llm_insights: bool = False
    topology: str = "mesh"
    objective: str = "balanced"
    # Planner-path only. ``topology_select`` (default) picks a named topology;
    # ``graph_generate`` has the emperor LLM invent a bespoke temporal DAG via
    # exp_graph.mas.graph_generation.plan_free_graph, then executes its
    # protocol_spec. The graph_* knobs are the hard constraints handed to the
    # generator (defaults mirror MASRuntimeConfig / the paper).
    planner_mode: str = "topology_select"
    # The `evolved` bench arm's mode. ``topology_select`` (default): evolution
    # tunes the skill bank, then PICKS a named topology. ``graph_generate``:
    # evolution tunes the skill bank, then the emperor GENERATES a bespoke DAG
    # from those evolved skills (self-designed topology) -- the evolved bank is
    # threaded into plan_free_graph at eval time. ``select_then_refine``: evidence
    # is collected via topology_select (so the bank's minister skills carry the
    # WORKING topologies' reference protocol_specs), then the eval GENERATES a DAG
    # the emperor refines from those references (anchor on what works, then
    # economize) -- best-of-both vs from-scratch graph_generate.
    evolved_mode: str = "topology_select"
    # How many trailing seeds the evolved arm holds out for EVAL (and the gate's
    # val): train = seeds[:-K], test = seeds[-K:]. Default 1 (current behaviour);
    # K>1 evaluates evolved on more held-out seeds -> far less per-condition
    # variance (each condition is no longer a single binary outcome).
    evolved_test_seeds: int = 1
    num_graph_candidates: int = 1
    # D1 (opt-in): >0 turns on top-k candidate PROBE-evaluation -- each generated
    # candidate is actually run on this many validation seeds and the best-scoring
    # one is selected (vs the default blind first-valid/motif pick). 0 = off.
    graph_validation_seeds: int = 0
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
    # Per-request hard wall-clock timeout (seconds) for non-fake LLM calls. A
    # hung provider request is abandoned after this budget so the run fails fast
    # instead of freezing (see masbench.llm.timeout.TimeoutLLMClient). <=0/None
    # disables the guard. The fake client is instant, so it is never wrapped.
    request_timeout: float = 90.0
