"""Engine bridge: run one BenchmarkInstance through the exp_graph SynchronousRunner."""

from __future__ import annotations

import tempfile
from pathlib import Path

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import create_llm_client
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

from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.core.task_bridge import BenchmarkTaskAdapter
from masbench.llm.fake import BenchmarkFakeLLMClient


def _build_llm_client(cfg: RunConfig) -> LLMClient:
    if cfg.llm_provider == "fake":
        return BenchmarkFakeLLMClient()
    return create_llm_client(
        cfg.llm_provider,
        base_url=cfg.base_url,
        api_key_env=cfg.api_key_env,
        thinking_enabled=cfg.thinking_enabled,
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


def _run_planner(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None,
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
    generation and the soldier execution.
    """
    task_adapter = SiloProtocolAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    client = llm_client or _build_llm_client(cfg)

    if cfg.planner_mode == "graph_generate":
        plan, planner_extra = _plan_graph_generate(
            cfg, n_agents=n_agents, task_adapter=task_adapter, client=client
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

    final = result.final_result
    extra = {
        "case_id": instance.case_id,
        "planner": True,
        "topology": plan.topology_name,
        "objective": cfg.objective,
        "aggregation_method": final.aggregation_method,
    }
    extra.update(planner_extra)
    return ScoreResult(
        success=bool(final.exact_match),
        partial=getattr(final, "primary_metric", None),
        n_messages=int(result.total_messages),
        n_model_calls=int(result.total_model_calls),
        tokens=int(result.total_prompt_tokens) + int(result.total_completion_tokens),
        final_answer=final.final_key,
        extra=extra,
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


def _plan_graph_generate(
    cfg: RunConfig,
    *,
    n_agents: int,
    task_adapter: SiloProtocolAdapter,
    client: LLMClient,
):
    """FULL QueenBee plan: the emperor LLM invents a bespoke temporal DAG.

    Delegates to ``exp_graph.mas.graph_generation.plan_free_graph``, which
    generates candidate DAGs, validates/repairs them, and (offline / on junk)
    falls back to a fixed operator topology. We reuse the SAME ``client`` for the
    generation call. ``plan_free_graph`` requires an ``output_dir`` for its
    artifacts; we hand it a throwaway temp dir so the repo is not polluted, and
    in the default single-search mode the ``task_adapter`` is never invoked for
    probe evaluation (so passing the Silo adapter is safe).
    """
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
        num_graph_candidates=cfg.num_graph_candidates,
        graph_max_steps=cfg.graph_max_steps,
        graph_max_messages=cfg.graph_max_messages,
        graph_max_receiver_fan_in=cfg.graph_max_receiver_fan_in,
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
            skill_bank=SkillBank(),
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
) -> ScoreResult:
    """Run one instance and score it.

    ``cfg.use_planner`` selects the QueenBee planner + generalized ProtocolRunner;
    otherwise the planner-OFF SynchronousRunner path runs unchanged.
    """
    if cfg.use_planner:
        return _run_planner(instance, cfg, llm_client=llm_client)

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

    return ScoreResult(
        success=bool(result.metrics.final_accuracy),
        partial=None,
        n_messages=_count_messages(result),
        n_model_calls=int(result.metrics.total_model_calls),
        tokens=int(result.metrics.total_token_cost),
        final_answer=result.final_result.final_key,
        extra={
            "case_id": instance.case_id,
            "topology": cfg.topology,
            "stop_reason": result.stop_reason,
            "consensus_reached": result.final_result.consensus_reached,
            "aggregation_method": result.final_result.aggregation_method,
        },
    )
