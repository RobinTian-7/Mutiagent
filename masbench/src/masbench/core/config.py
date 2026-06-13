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
    # Phase-2 anti-saturation: in select_then_refine evolution, each round ALSO
    # runs this many graph_generate evidence runs per train instance USING THE
    # CURRENT BANK (the deployed refine path), so self-generated designs enter
    # the minister with their executable specs and compete with named
    # topologies in later rounds. 0 disables (phase-1 behaviour). Env override:
    # MASBENCH_EVOLVE_EXPLORE (lets the frozen verify scripts control it).
    evolve_explore: int = 1
    # Temperature for the graph-GENERATION call only (None = use `temperature`).
    # Exploration sets this hot (0.7) so successive rounds propose DIFFERENT
    # designs at deterministic protocol execution; deployment stays cold.
    graph_gen_temperature: float | None = None
    # Phase-3 M1: evidence-conditioned transfer gate on deployment. "feature"
    # (default): a skill's executable spec is replayable on a case only when
    # the skill's ledger shows measured success in the case's task-feature
    # bucket; nothing trusted -> the exact cold path (empty bank, no motif).
    # "off": phase-2 behavior (case-blind replay). Env override:
    # MASBENCH_TRANSFER_GATE (lets frozen verify scripts run the ablation).
    transfer_gate: str = "feature"
    # Phase-3 M3: comma-separated named topologies measured as EXTRA evidence
    # each round (the objective-variant detour only measures aggregation
    # defaults). "" disables. Env override: MASBENCH_EVIDENCE_PORTFOLIO.
    evidence_portfolio: str = "chain"
    # Phase-3 M4: LCB pessimism for the motif prior (exp_graph
    # MASRuntimeConfig.motif_uncertainty_kappa). A 1-run lucky motif cannot
    # outrank a measured veteran. 0.0 = phase-2 behavior.
    motif_uncertainty_kappa: float = 0.5
    # Round-10 deployment stability (dev-6 r3 reshuffle): replay-first
    # selection + sticky motif displacement margin.
    replay_first: bool = True
    motif_displacement_margin: float = 0.1
    # Operator bar raise (vs fixed-best, abstention bleeds pairs): when a
    # case's slot has no trusted skill, deploy a broad-uniform bucket
    # generalist (M8 breadth) before going cold. Env: MASBENCH_FALLBACK_TIER.
    fallback_tier: bool = True
    # Phase-3 M10: run budget (protocol executions per evolution round) for
    # train-time VERIFIED recipe search on unanchored bucket#slots. 0 = off.
    # Env: MASBENCH_RECIPE_BUDGET.
    recipe_search_budget: int = 18
    # Phase-3 M27 (hi-power forensics): portfolio (named-topology) evidence
    # is collected on train_seeds only -- at n=5 the sole os anchor II-13
    # gives each topology just len(train_seeds)=2 evaluations, so one bad
    # provider-drift window flips one_peer's os trust to 0 and gen falls
    # back to a weak org. This factor derives extra portfolio seeds
    # (s + 1009*k) so trust is built on len(train_seeds)*factor samples.
    # 1 = off, byte-identical to before (CF unaffected: CF never uses it).
    portfolio_seed_factor: int = 1
    # Phase-3 M20: run budget for train-time instruction-EXEMPLAR
    # verification (architect writes per-step instructions for the bucket
    # champion's structure on a train anchor; executed on verify seeds; a
    # passing set is stored on the card and anchors deploy-time Modify
    # rewrites, removing the per-deployment instruction-draw lottery). 0 = off.
    exemplar_search_budget: int = 6
    # Phase-3 M23 (operator: stronger PLANNER, frozen workers): when set,
    # architect-side calls (emperor graph generation, instruction rewrite,
    # recipe search, exemplar writing) use this model while workers keep
    # model_name. None = no split (byte-identical historical behavior).
    planner_model_name: str | None = None
    # Phase-3 M9: replay candidates get per-step receiver instructions
    # REWRITTEN for the current task (one emperor call per seeded candidate)
    # and the protocol runner injects them into merge prompts. False =
    # verbatim structure-only replay (pre-M9). Env: MASBENCH_REPLAY_REWRITE.
    replay_rewrite: bool = True
    # Phase-3 M7 (generalizability): how task features (bucket + agg kind)
    # are derived from the task statement. "llm" (default): the run's own
    # LLM answers benchmark-agnostic questions (order-sensitivity, answer
    # locality, statistic family), temp-0, cached per text hash (env
    # MASBENCH_FEATURE_CACHE persists across processes); fake provider falls
    # back to heuristics. "heuristic": regex fallback only (offline tests /
    # ablation arm; NOT the method).
    task_feature_source: str = "llm"
    # Phase-3 M5: the generation gate evaluates each arm on
    # len(val_seeds) * gate_seed_factor derived seeds (s, s+1009, s+2017, ...)
    # instead of the raw val_seeds, and tolerates exactly one discordant miss
    # (epsilon_eff = max(epsilon, 1/n_samples)). A 3-sample binary gate is a
    # coin flip: dev round 1 rejected a genuinely-good bank on cold 3/3 vs
    # deployed 2/3. Env override: MASBENCH_GATE_SEED_FACTOR.
    gate_seed_factor: int = 3
    # Held-out acceptance gate for run_evolution. ``auto`` (default): gate on the
    # DEPLOYED objective -- generation loss when the evolved state will generate
    # at eval (graph_generate / select_then_refine), topology-selection J
    # otherwise. ``off``: no held-out gate at all (the drift-ablation arm; also
    # settable per-run via the MASBENCH_GATE_MODE env var so frozen drivers like
    # scripts/verify_evolve.py can run the ablation without growing flags).
    gate_mode: str = "auto"
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
