"""Frozen-structure execution: one CF program over frozen cases and seeds.

The lineage law consumes plain per-case fact rows (the ``seed_vote``
contract: ``S`` decides first, ``stage_score`` refines, ``C`` breaks ties;
``infra`` rows are void, ``algorithm_failure`` rows are catastrophic-
eligible).  This module produces those rows by driving
:class:`exp_graph.runner.ProtocolRunner` with a compiled CF program.

Failures are recorded, never retried and never dropped: an infrastructure
failure keeps its row (excluded from quality means, counted in the report)
so a flaky run cannot silently shrink the evaluation set.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from exp_graph.runner import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks import CountFrequencyTaskAdapter

from exp_graph.sft_lineage.cf_cases import CFCase
from exp_graph.sft_lineage.cf_structures import compile_cf_program

_TRANSPORT_MARKERS = (
    "connection",
    "timeout",
    "timed out",
    "rate limit",
    "ratelimit",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "ssl",
    "429",
    "502",
    "503",
)


def _is_transport_error(exc: Exception) -> bool:
    if exc.__class__.__module__.split(".")[0] == "openai":
        return True
    haystack = f"{type(exc).__name__} {exc}".lower()
    return any(marker in haystack for marker in _TRANSPORT_MARKERS)


def run_case(
    *,
    program: dict[str, Any],
    case: CFCase,
    seed: int,
    n_agents: int,
    model_name: str,
    merge_mode: str,
    init_mode: str,
    llm_provider: str,
    worker_client: Any | None,
    allow_deterministic_repair: bool,
    json_retry_attempts: int,
    max_parallel_agents: int,
    arm_label: str,
) -> dict[str, Any]:
    """Execute one (program, case, seed) run and reduce it to fact rows.

    ``S`` is sink quality in [0, 1] (1 - normalized L1 error, so an exact
    table scores 1.0), ``stage_score`` is the strictly finer RMSE view used
    only to order same-S rows, and ``C`` is the paid token total — or, in
    deterministic offline runs where no tokens exist, the message count, so
    offline duels still have a real cost axis to decide ties.
    """

    task_adapter = CountFrequencyTaskAdapter()
    global_task = task_adapter.build_global_task(**case.task_kwargs(seed))
    spec = compile_cf_program(program, n_agents=n_agents)
    config = ProtocolRunnerConfig(
        topology_name=spec.name,
        n_agents=n_agents,
        seed=int(seed),
        model_name=model_name,
        merge_mode=merge_mode,
        init_mode=init_mode,
        llm_provider=llm_provider,
        temperature=0.0,
        json_retry_attempts=json_retry_attempts,
        allow_deterministic_repair=allow_deterministic_repair,
        max_parallel_agents=max_parallel_agents,
        protocol_spec=spec,
        run_id=f"{arm_label}:{case.case_id}:seed{seed}",
    )
    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=worker_client,
    ).run()

    final = result.final_result
    tokens = result.total_prompt_tokens + result.total_completion_tokens
    quality = 1.0 - min(1.0, float(final.normalized_l1_error))
    sink_rows = [
        row
        for row in result.agent_step_metrics
        if row.agent_id in final.answer_agent_ids
    ]
    if sink_rows:
        last_step = max(row.step_idx for row in sink_rows)
        sink_coverage = max(
            row.coverage_ratio
            for row in sink_rows
            if row.step_idx == last_step
        )
    else:
        sink_coverage = 0.0
    return {
        "infra": None,
        "execution_class": "completed",
        "success": bool(final.exact_match),
        "S": round(quality, 6),
        "stage_score": round(1.0 / (1.0 + float(final.rmse)), 6),
        "C": float(tokens if result.total_model_calls else result.total_messages),
        "D": float(result.total_steps),
        "rmse": float(final.rmse),
        "normalized_l1_error": float(final.normalized_l1_error),
        "sink_coverage": float(sink_coverage),
        "answer_agent_ids": list(final.answer_agent_ids),
        "messages": result.total_messages,
        "model_calls": result.total_model_calls,
        "prompt_tokens": result.total_prompt_tokens,
        "completion_tokens": result.total_completion_tokens,
        "retry_attempts": result.total_retry_attempts,
        "deterministic_fallbacks": result.total_deterministic_fallbacks,
    }


def evaluate_program_on_cases(
    *,
    program: dict[str, Any],
    cases: tuple[CFCase, ...],
    seeds: tuple[int, ...],
    arm_label: str,
    n_agents: int,
    model_name: str,
    merge_mode: str,
    init_mode: str,
    llm_provider: str,
    worker_client: Any | None,
    allow_deterministic_repair: bool,
    json_retry_attempts: int = 2,
    max_parallel_cases: int = 1,
    max_parallel_agents: int = 1,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """One frozen artifact over frozen (case, seed) pairs, cases in parallel.

    Row order matches ``cases`` so paired zips against another arm stay
    aligned.  A raised run keeps its slot: transport-shaped errors become
    void ``infra`` rows, everything else an ``algorithm_failure`` row that
    ``seed_vote`` treats as catastrophic-eligible.
    """

    if len(cases) != len(seeds):
        raise ValueError("cases and seeds must pair one-to-one")

    def _run_one(index: int) -> dict[str, Any]:
        case = cases[index]
        try:
            row = run_case(
                program=program,
                case=case,
                seed=seeds[index],
                n_agents=n_agents,
                model_name=model_name,
                merge_mode=merge_mode,
                init_mode=init_mode,
                llm_provider=llm_provider,
                worker_client=worker_client,
                allow_deterministic_repair=allow_deterministic_repair,
                json_retry_attempts=json_retry_attempts,
                max_parallel_agents=max_parallel_agents,
                arm_label=arm_label,
            )
        except Exception as exc:  # noqa: BLE001 - a failed run is a result
            error = f"{type(exc).__name__}: {exc}"
            if _is_transport_error(exc):
                row = {"infra": error[:500]}
            else:
                row = {
                    "infra": None,
                    "execution_class": "algorithm_failure",
                    "success": False,
                    "S": 0.0,
                    "stage_score": 0.0,
                    "C": 0.0,
                    "error": error[:500],
                }
        row["case_id"] = case.case_id
        row["seed"] = int(seeds[index])
        if progress is not None:
            progress(f"{arm_label} {case.case_id} seed={seeds[index]} done")
        return row

    workers = max(1, min(int(max_parallel_cases), len(cases)))
    if workers == 1:
        return [_run_one(index) for index in range(len(cases))]
    rows: list[dict[str, Any] | None] = [None] * len(cases)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_one, index): index
            for index in range(len(cases))
        }
        for future, index in futures.items():
            rows[index] = future.result()
    return [row for row in rows if row is not None]
