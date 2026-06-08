"""Engine bridge: run one BenchmarkInstance through the exp_graph SynchronousRunner."""

from __future__ import annotations

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import create_llm_client
from exp_graph.runner import SynchronousRunner

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


def run_instance(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None = None,
) -> ScoreResult:
    """Run one instance planner-OFF via SynchronousRunner and score it."""
    if cfg.use_planner:
        raise NotImplementedError(
            "use_planner requires the generic protocol runner delivered in Plan 2/3. "
            "Plan 1 supports the planner-OFF SynchronousRunner path only."
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
