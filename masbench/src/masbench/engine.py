"""Engine bridge: run one BenchmarkInstance through the exp_graph SynchronousRunner."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import WALLCLOCK_TIMEOUT_ENV, create_llm_client
from exp_graph.mas.graph_generation import plan_free_graph
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.schemas import (
    MASRuntimeConfig,
    ObjectiveSpec,
    PlannerRequest,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner import SynchronousRunner
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig

from masbench.adapters.silo_protocol import (
    SiloProtocolAdapter,
    score_protocol_answer,
)
from masbench.adapters.silo_scoring import silo_partial_score
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.llm.retry import RetryLLMClient
from masbench.core.task_bridge import BenchmarkTaskAdapter, canonical_answer
from masbench.llm.fake import BenchmarkFakeLLMClient


def _build_llm_client(cfg: RunConfig) -> LLMClient:
    if cfg.llm_provider == "fake":
        # The fake client is instant and deterministic; no timeout guard needed.
        return BenchmarkFakeLLMClient()
    # Make the hard wall-clock guard UNIVERSAL. Engine-internal sites build their
    # OWN clients via create_llm_client (role clients, the graph-generation
    # candidate evaluator, the insight minister, the ProtocolRunner fallback);
    # setting the env ensures those are guarded too -- not only the client we
    # thread in here. Without it, a hung call on an unwrapped internal client
    # freezes the whole run (this was the real root cause of the evolved/graphgen
    # "no progress" stall).
    os.environ[WALLCLOCK_TIMEOUT_ENV] = str(cfg.request_timeout)
    # Bounded transient-connection retry OUTSIDE the wall-clock guard: each
    # attempt gets its own timeout budget, and a single network blip can no
    # longer kill a whole verify/bench eval pool (round-3C crashed at 32/72
    # eval runs on one APIConnectionError). attempts=5/base 5s linear backoff
    # rides out ~75s outages (phase-3 dev-5: a multi-blip burst beat the old
    # 3x2s budget and crashed the refine run through the frozen eval pool).
    return RetryLLMClient(
        create_llm_client(
            cfg.llm_provider,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
            thinking_enabled=cfg.thinking_enabled,
            timeout_s=cfg.request_timeout,
        ),
        attempts=5,
        base_delay=5.0,
    )


def _count_messages(result) -> int:
    """Structural upper bound on inter-agent messages.

    Sums each round's topology fan-in (``round_logs[*].neighbors``). This counts
    the edges the topology exposes, which is an upper bound: the runner skips
    delivering a neighbor's ``None`` outbox. Exact per-delivery counts arrive with
    the generic protocol runner in Plan 2.
    """
    total = 0
    for log in result.round_logs:
        total += sum(len(neighbors) for neighbors in log.neighbors.values())
    return total


def _partial_score(final_answer: Any, global_task: dict) -> float:
    """Graded PARTIAL-CORRECTNESS for a final answer, computed in masbench.

    exp_graph stays untouched: we recompute the [0, 1] partial signal here from
    the run's final answer + the instance ground truth carried in ``global_task``.
    ``success``/exact-match keep coming from exp_graph's strict scoring; this only
    fills ``ScoreResult.partial`` with the graded value. ``final_answer`` may be a
    live value or a canonical-key string; ``silo_partial_score`` coerces either.
    """
    return float(score_protocol_answer(final_answer, global_task)["partial"])


def _score_segmented(
    result: Any,
    instance: BenchmarkInstance,
    adapter: SiloProtocolAdapter,
    global_task: dict,
) -> tuple[bool, float, list[bool]]:
    """Grade a SEGMENTED Silo run from the FINAL PER-AGENT states.

    Segmented tasks give every agent its OWN ``expected_output`` (carried in
    ``meta['expected_outputs'][agent_id]``), so the single voted global answer is
    meaningless. For each agent we read its final belief
    (``result.final_agent_states[agent_id].belief_state``), extract that agent's
    answer via :meth:`SiloProtocolAdapter.extract_protocol_answer`, and compare it
    (canonicalized) to that agent's expected segment.

    Returns ``(success, partial, per_agent_correct)`` where:

    * ``success`` is True iff EVERY agent is exact-correct on its own segment;
    * ``partial`` is the mean of :func:`silo_partial_score` over agents (graded
      per-agent quality in [0, 1]);
    * ``per_agent_correct[i]`` is the strict exact-match for agent ``i``.

    Robust to a missing/short ``final_agent_states``: any agent without a state is
    treated as wrong (answer ``None`` -> partial 0.0). With zero expected agents
    (degenerate) it reports ``(False, 0.0, [])`` rather than a vacuous success.
    """
    expected_outputs = instance.meta.get("expected_outputs") or []
    n_agents = len(expected_outputs)
    final_states = list(getattr(result, "final_agent_states", []) or [])
    output_type = global_task.get("output_type", "scalar")

    per_agent_correct: list[bool] = []
    partials: list[float] = []
    for agent_id in range(n_agents):
        expected = expected_outputs[agent_id]
        if agent_id < len(final_states):
            belief = final_states[agent_id].belief_state
            answer = adapter.extract_protocol_answer(belief)
        else:
            answer = None  # missing state -> treat as wrong
        correct = (
            answer is not None
            and canonical_answer(answer) == canonical_answer(expected)
        )
        per_agent_correct.append(bool(correct))
        partials.append(float(silo_partial_score(answer, expected, output_type)))

    success = n_agents > 0 and all(per_agent_correct)
    partial = (sum(partials) / len(partials)) if partials else 0.0
    return success, partial, per_agent_correct


def _score_protocol_result(
    result: Any,
    instance: BenchmarkInstance,
    task_adapter: SiloProtocolAdapter,
    global_task: dict,
    *,
    extra: dict,
) -> ScoreResult:
    """Turn a ``ProtocolRunner`` result into a graded :class:`ScoreResult`.

    Shared by the planner (select/graph_generate) and forced-fixed-topology paths
    so every arm in the benchmark harness is scored and metered identically: the
    same segmented/plain grading, the same message/model-call/token accounting
    from the protocol result's ``total_*`` counters. ``extra`` is the
    caller-specific diagnostic dict (topology, planner flag, ...); the segmented
    branch annotates it in place.
    """
    final = result.final_result
    extra = {**extra, "aggregation_method": final.aggregation_method}
    # masbench owns the graded partial: success/exact-match stay strict (from
    # exp_graph's final), while ``partial`` is recomputed here from the final
    # answer + ground truth. Prefer the live final_answer, fall back to the key.
    final_value = final.final_answer if final.final_answer is not None else final.final_key
    if instance.segmented:
        # Per-agent grading: the single voted answer is meaningless here.
        success, partial, per_agent_correct = _score_segmented(
            result, instance, task_adapter, global_task
        )
        extra["segmented"] = True
        extra["per_agent_correct"] = per_agent_correct
    else:
        success = bool(final.exact_match)
        partial = _partial_score(final_value, global_task)
    return ScoreResult(
        success=success,
        partial=partial,
        n_messages=int(result.total_messages),
        n_model_calls=int(result.total_model_calls),
        tokens=int(result.total_prompt_tokens) + int(result.total_completion_tokens),
        final_answer=final.final_key,
        extra=extra,
    )


def run_fixed_protocol(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    topology: str,
    llm_client: LLMClient | None = None,
) -> ScoreResult:
    """Run one instance on a FORCED protocol topology (planner-OFF baseline arm).

    The "fixed" baseline arm of the paper-grade harness runs each named topology
    directly through the generalized :class:`ProtocolRunner` with NO planner and
    NO generated ``protocol_spec`` — the topology name is compiled to a finite
    communication schedule by ``build_protocol_schedule``. This is deliberately
    the *protocol* path rather than the legacy ``SynchronousRunner`` path:

    * ``SynchronousRunner`` (the ``use_planner=False`` path in ``run_instance``)
      only accepts the physical topology set
      ``chain/ring/star/mesh/static_exponential/one_peer_exponential`` and meters
      messages by a structural upper bound.
    * The paper's fixed baselines are the *protocol-schedule* topologies
      (``tree``, ``mesh_star``, ``one_peer_exponential_dag_star``, ``chain``),
      which only ``build_protocol_schedule`` understands, and they share the exact
      message/model-call/token accounting the ``select``/``graphgen`` arms use.

    Forcing the topology here therefore keeps the whole arm comparison
    apples-to-apples (one runner, one scorer) while letting the fixed arm sweep
    the same named topologies the planner can pick.
    """
    task_adapter = SiloProtocolAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    client = llm_client or _build_llm_client(cfg)

    config = ProtocolRunnerConfig(
        topology_name=topology,
        n_agents=n_agents,
        seed=cfg.seed,
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
    )
    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()
    extra = {
        "case_id": instance.case_id,
        "planner": False,
        "topology": topology,
        "objective": cfg.objective,
        "fixed": True,
    }
    return _score_protocol_result(
        result, instance, task_adapter, global_task, extra=extra
    )


def _run_planner(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
) -> ScoreResult:
    """Run one instance through the QueenBee planner + ProtocolRunner and score it.

    ``cfg.planner_mode`` selects how the communication structure is chosen:

    * ``"topology_select"`` (default): ``EmperorPlanner`` picks a named topology;
      with the (empty for now) SkillBank it falls back to
      ``default_topology_for_objective``.
    * ``"graph_generate"``: the emperor LLM invents a bespoke temporal DAG via
      ``plan_free_graph``; the generated ``protocol_spec`` drives the runner. With
      a fake/junk LLM, ``plan_free_graph`` validates/repairs and ultimately falls
      back to a fixed operator topology, so the run never crashes offline.

    Either way the resulting ``plan.topology_name`` + ``plan.protocol_spec`` drive
    the generalized ProtocolRunner. The same ``client`` is reused for any DAG
    generation and the soldier execution. ``motif_stats`` (graph_generate only) is
    accumulated motif evidence that activates the structural-motif credit prior
    when ranking generated candidates (see ``_plan_graph_generate``).
    """
    task_adapter = SiloProtocolAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    client = llm_client or _build_llm_client(cfg)

    if cfg.planner_mode == "graph_generate":
        plan, planner_extra = _plan_graph_generate(
            cfg,
            n_agents=n_agents,
            task_adapter=task_adapter,
            client=client,
            motif_stats=motif_stats,
            skill_bank=skill_bank,
        )
    else:
        plan, planner_extra = _plan_topology_select(cfg, n_agents=n_agents)

    # Build the runner config. ``plan.config_overrides`` may carry a protocol_spec
    # (operator/graph planner modes) alongside the one we pass explicitly, so we
    # layer overrides on top of the base kwargs to avoid duplicate-key errors.
    config_kwargs: dict = {
        "topology_name": plan.topology_name,
        "n_agents": n_agents,
        "seed": cfg.seed,
        "merge_mode": cfg.merge_mode,
        "init_mode": cfg.init_mode,
        "protocol_spec": plan.protocol_spec,
        "llm_provider": cfg.llm_provider,
        "model_name": cfg.model_name,
        "temperature": cfg.temperature,
    }
    config_kwargs.update(plan.config_overrides)
    config = ProtocolRunnerConfig(**config_kwargs)

    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()

    extra = {
        "case_id": instance.case_id,
        "planner": True,
        "topology": plan.topology_name,
        "objective": cfg.objective,
    }
    extra.update(planner_extra)
    return _score_protocol_result(
        result, instance, task_adapter, global_task, extra=extra
    )


def _plan_topology_select(cfg: RunConfig, *, n_agents: int):
    """QueenBee topology-select plan (Plan 3 B): pick a named topology."""
    request = PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name(cfg.objective),
    )
    plan = EmperorPlanner(SkillBank()).plan(request)
    return plan, {"planner_mode": "topology_select"}


def _effective_graph_max_steps(cfg: RunConfig, n_agents: int) -> int:
    """Step cap for GENERATED organizations, scaling with n.

    The historical fixed cap (4) made linear-depth schedules inexpressible at
    n=10 -- a chain pass needs ~n-1 steps -- while named-topology compilation
    has no cap, so generation-based arms were structurally barred from the
    organizations sequential tasks need (P2 confirmatory-2 failure analysis).
    An explicitly configured non-default cap is honored unchanged.
    """
    if cfg.graph_max_steps != 4:
        return cfg.graph_max_steps
    return max(4, n_agents + 2)


def _replay_rewrite_enabled(cfg: RunConfig) -> bool:
    raw = os.environ.get("MASBENCH_REPLAY_REWRITE", "").strip()
    if raw:
        return raw not in {"0", "false", "off"}
    return bool(getattr(cfg, "replay_rewrite", False))


def _plan_graph_generate(
    cfg: RunConfig,
    *,
    n_agents: int,
    task_adapter: SiloProtocolAdapter,
    client: LLMClient,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
):
    """FULL QueenBee plan: the emperor LLM invents a bespoke temporal DAG.

    Delegates to ``exp_graph.mas.graph_generation.plan_free_graph``, which
    generates candidate DAGs, validates/repairs them, and (offline / on junk)
    falls back to a fixed operator topology. We reuse the SAME ``client`` for the
    generation call. ``plan_free_graph`` requires an ``output_dir`` for its
    artifacts; we hand it a throwaway temp dir so the repo is not polluted, and
    in the default single-search mode the ``task_adapter`` is never invoked for
    probe evaluation (so passing the Silo adapter is safe).

    Structural-motif credit prior (Plan 4 Task 5): we turn ``use_motif_prior`` ON
    so QueenBee ranks newly generated candidates partly by how their motifs
    performed in past evidence (see ``exp_graph.mas.motifs``). ``motif_stats`` is
    that evidence, aggregated by ``aggregate_motif_losses``. A single-run plan
    has no accumulated Silo evidence yet, so ``motif_stats`` defaults to None and
    the prior is inert (selection unchanged); the bench/evolve harness supplies
    ``motif_stats`` from prior runs to activate it. The prior only changes the
    pick when >1 candidate survives, so set ``cfg.num_graph_candidates > 1`` to
    let it fire.
    """
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        # Generation-only temperature override: exploration proposes designs HOT
        # (diversity across rounds) while protocol execution stays at
        # cfg.temperature; None -> no split (deployment path).
        temperature=(
            cfg.graph_gen_temperature
            if getattr(cfg, "graph_gen_temperature", None) is not None
            else cfg.temperature
        ),
        num_graph_candidates=cfg.num_graph_candidates,
        graph_max_steps=_effective_graph_max_steps(cfg, n_agents),
        graph_max_messages=cfg.graph_max_messages,
        graph_max_receiver_fan_in=cfg.graph_max_receiver_fan_in,
        use_motif_prior=True,
        motif_stats=motif_stats,
        # M4: a 1-run lucky motif must not outrank a measured veteran.
        motif_uncertainty_kappa=getattr(cfg, "motif_uncertainty_kappa", 0.0),
        # M9: adapt replayed structures' per-step role guidance to THIS task.
        replay_instruction_rewrite=_replay_rewrite_enabled(cfg),
        # Round-10 deployment stability: trusted replays out-compete fresh
        # same-run generations; motif prior displaces the deterministic head
        # only with a real predicted-loss margin.
        replay_first=bool(getattr(cfg, "replay_first", False)),
        motif_displacement_margin=float(getattr(cfg, "motif_displacement_margin", 0.0)),
        # D2: reject/repair generated DAGs whose sink isn't reachable from ALL
        # agents (the lossy-reduction failure mode that made generation lose).
        graph_require_full_sink_coverage=True,
        # D1: probe-evaluate each candidate on N validation seeds (real task runs)
        # and select the best-scoring one; 0 -> off (blind first-valid/motif pick).
        graph_search_mode=("topk" if cfg.graph_validation_seeds > 0 else "single"),
        graph_validation_seeds=list(range(cfg.graph_validation_seeds)),
    )
    request = PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name(cfg.objective),
        planner_mode="graph_generate",
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
    )
    with tempfile.TemporaryDirectory(prefix="masbench_graphgen_") as tmpdir:
        result = plan_free_graph(
            request=request,
            runtime=runtime,
            skill_bank=skill_bank if skill_bank is not None else SkillBank(),
            seed=cfg.seed,
            task_adapter=task_adapter,
            output_dir=Path(tmpdir),
            llm_client=client,
        )
    plan = result.plan
    spec = plan.protocol_spec
    extra = {
        "planner_mode": "graph_generate",
        "generated_steps": len(spec.steps) if spec is not None else 0,
        "graph_fallback_reason": result.fallback_reason,
    }
    return plan, extra


def run_instance(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None = None,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
) -> ScoreResult:
    """Run one instance and score it.

    ``cfg.use_planner`` selects the QueenBee planner + generalized ProtocolRunner;
    otherwise the planner-OFF SynchronousRunner path runs unchanged. ``motif_stats``
    is forwarded to the graph_generate planner so accumulated motif evidence can
    activate the structural-motif credit prior (inert on the other paths).
    ``skill_bank`` (graph_generate only) is the bank whose evolved design_insights
    the emperor uses to DESIGN the DAG; defaults to an empty bank (cold generation,
    the plain graphgen behaviour).
    """
    if cfg.use_planner:
        return _run_planner(
            instance,
            cfg,
            llm_client=llm_client,
            motif_stats=motif_stats,
            skill_bank=skill_bank,
        )

    task_adapter = BenchmarkTaskAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents

    experiment_config = ExperimentConfig(
        topology_name=cfg.topology,
        n_agents=n_agents,
        max_rounds=cfg.max_rounds,
        seed=cfg.seed,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        temperature=cfg.temperature,
        consensus_threshold=cfg.consensus_threshold,
        final_accept_threshold=cfg.final_accept_threshold,
        trace_enabled=False,
    )
    client = llm_client or _build_llm_client(cfg)
    result = SynchronousRunner(
        config=experiment_config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()

    # masbench owns the graded partial (exp_graph untouched). The planner-OFF
    # final answer is the canonical key; recompute partial from it + ground truth.
    extra = {
        "case_id": instance.case_id,
        "topology": cfg.topology,
        "stop_reason": result.stop_reason,
        "consensus_reached": result.final_result.consensus_reached,
        "aggregation_method": result.final_result.aggregation_method,
    }
    if instance.segmented:
        # Per-agent grading from the final belief states. The synchronous runner
        # belief model matches the protocol one, so the Silo protocol adapter's
        # extract_protocol_answer reads each agent's answer the same way.
        success, partial, per_agent_correct = _score_segmented(
            result, instance, SiloProtocolAdapter(instance), global_task
        )
        extra["segmented"] = True
        extra["per_agent_correct"] = per_agent_correct
    else:
        success = bool(result.metrics.final_accuracy)
        partial = _partial_score(result.final_result.final_key, global_task)
    return ScoreResult(
        success=success,
        partial=partial,
        n_messages=_count_messages(result),
        n_model_calls=int(result.metrics.total_model_calls),
        tokens=int(result.metrics.total_token_cost),
        final_answer=result.final_result.final_key,
        extra=extra,
    )
