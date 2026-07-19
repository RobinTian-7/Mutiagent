"""Concurrent whole-program case evaluation for the v5 real pilot.

One "test" here is one benchmark case run: a full compiled Phase program
executed on one real Silo case through :mod:`real_runner` (production scorer,
whole-arm usage aggregate).  The pool runs several such tests concurrently
while each test fans its sub-agents out via ``max_parallel_agents``; the
process-wide LLM admission gate (``exp_graph.llm.concurrency``) bounds total
in-flight provider calls no matter how the two layers multiply.

This layer is deliberately OUTSIDE the scientific Bank: it never touches
FactorBank/Registry/store state.  The sealed TEST executor and the external
baseline arm both reduce to "evaluate this frozen program on these frozen
cases", which is exactly what this module owns.  Failures are recorded, never
retried and never dropped: an infrastructure failure keeps its row (excluded
from quality means, counted in the denominator report) so a flaky run cannot
silently shrink the evaluation set.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from exp_graph.mas.phase_program import PhaseProgram

from masbench.sft_pilot.real_runner import ArmRunResult, run_phase_program_arm


@dataclass(frozen=True)
class CaseEvalRow:
    """One case-level evaluation observation for one labeled arm."""

    arm_label: str
    case_id: str
    seed: int
    result: ArmRunResult | None
    infrastructure_error: str | None = None

    @property
    def completed(self) -> bool:
        return (
            self.result is not None
            and self.result.execution_class == "completed"
        )


def evaluate_program_on_cases(
    *,
    program: PhaseProgram,
    instances: tuple[Any, ...],
    seeds: tuple[int, ...],
    arm_label: str,
    n_agents: int,
    information_goal: str,
    model_name: str,
    temperature: float,
    llm_provider: str,
    llm_client: Any,
    merge_mode: str = "llm_belief_merge",
    init_mode: str = "llm_local_solve",
    max_parallel_cases: int = 3,
    max_parallel_agents: int = 5,
    require_all_submissions: bool = False,
    strengthen_submission_merge: bool = False,
    progress: Any = None,
) -> tuple[CaseEvalRow, ...]:
    """Evaluate one frozen program on every ``(instance, seed)`` pair.

    Rows come back in the input order regardless of completion order, so the
    caller's report is deterministic for a fixed case list.  A raising case
    run becomes an ``infrastructure_error`` row — the denominator never
    shrinks silently.
    """

    if len(instances) != len(seeds):
        raise ValueError("instances and seeds must pair one-to-one")
    if not instances:
        return ()

    def _run_one(index: int) -> CaseEvalRow:
        instance = instances[index]
        seed = seeds[index]
        try:
            result = run_phase_program_arm(
                program=program,
                instance=instance,
                n_agents=n_agents,
                information_goal=information_goal,
                seed=seed,
                model_name=model_name,
                temperature=temperature,
                llm_provider=llm_provider,
                llm_client=llm_client,
                merge_mode=merge_mode,
                init_mode=init_mode,
                max_parallel_agents=max_parallel_agents,
                require_all_submissions=require_all_submissions,
                strengthen_submission_merge=strengthen_submission_merge,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never retried
            return CaseEvalRow(
                arm_label=arm_label,
                case_id=str(getattr(instance, "case_id", f"case-{index}")),
                seed=seed,
                result=None,
                infrastructure_error=f"{type(exc).__name__}: {exc}",
            )
        return CaseEvalRow(
            arm_label=arm_label,
            case_id=str(getattr(instance, "case_id", f"case-{index}")),
            seed=seed,
            result=result,
        )

    rows: list[CaseEvalRow | None] = [None] * len(instances)
    workers = max(1, min(int(max_parallel_cases), len(instances)))
    if workers == 1:
        for index in range(len(instances)):
            rows[index] = _run_one(index)
            if progress is not None:
                progress(rows[index])
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_one, index): index
                for index in range(len(instances))
            }
            for future in as_completed(futures):
                index = futures[future]
                rows[index] = future.result()
                if progress is not None:
                    progress(rows[index])
    return tuple(row for row in rows if row is not None)


_DENSE_FIELDS = ("V", "K", "U", "P", "S", "stage_score", "C", "D")


def aggregate_eval_rows(rows: tuple[CaseEvalRow, ...]) -> dict[str, float]:
    """Case-level aggregate for one arm: quality means over completed runs.

    Infrastructure rows never enter quality means (they have no honest
    outcome) but stay in the denominator counters; algorithm failures keep
    their observed all-zero/cost outcome inside the means, exactly like the
    Bank's own evidence law.
    """

    total = len(rows)
    completed = [
        row for row in rows if row.result is not None
    ]
    scored = [
        row
        for row in completed
        if row.result is not None
        and row.result.execution_class in {"completed", "algorithm_failure"}
    ]
    quality = [row for row in scored if row.completed]
    aggregate: dict[str, float] = {
        "cases_total": float(total),
        "cases_scored": float(len(scored)),
        "cases_completed": float(len(quality)),
        "algorithm_failures": float(
            sum(
                1
                for row in scored
                if row.result is not None
                and row.result.execution_class == "algorithm_failure"
            )
        ),
        "infrastructure_failures": float(
            sum(1 for row in rows if row.infrastructure_error is not None)
        ),
    }
    if scored:
        for field in _DENSE_FIELDS:
            aggregate[f"mean_{field}"] = sum(
                float(getattr(row.result.dense_outcome, field))
                for row in scored
                if row.result is not None
            ) / len(scored)
        aggregate["success_rate"] = sum(
            1.0
            for row in scored
            if row.result is not None and row.result.success
        ) / len(scored)
        aggregate["mean_partial"] = sum(
            float(row.result.partial)
            for row in scored
            if row.result is not None
        ) / len(scored)
    aggregate["total_model_calls"] = float(
        sum(
            row.result.model_calls
            for row in rows
            if row.result is not None
        )
    )
    aggregate["total_prompt_tokens"] = float(
        sum(
            row.result.prompt_tokens
            for row in rows
            if row.result is not None
        )
    )
    aggregate["total_completion_tokens"] = float(
        sum(
            row.result.completion_tokens
            for row in rows
            if row.result is not None
        )
    )
    return aggregate


__all__ = [
    "CaseEvalRow",
    "aggregate_eval_rows",
    "evaluate_program_on_cases",
]
