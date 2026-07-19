"""Real Phase-program execution runtime for the v5 pilot (Stage 12 bringup).

This is the layer the mechanics task deferred: it actually runs a compiled
Phase program on a real Silo-Bench case through the shared ``ProtocolRunner``
and the official scorer, then projects the result into the exact
``DenseOutcome`` the FactorBank gate consumes.  It deliberately REUSES the
production scorer (`_score_protocol_result` + `_apply_precomputed_information_
goal_score` + `dense_sample`) rather than reimplementing any metric, so
probe/FINAL_VAL evidence is scored byte-identically to bench/eval.

Real model calls are metered at whole-arm aggregate granularity: one probe
arm = one whole ``ProtocolRunner`` run, whose real per-call tokens/model-calls
are summed by the runner and recorded as one aggregate store call (the exact
counts also travel in the DenseOutcome C/D).  See
``docs/sft_phase_v5/plan_deviations.md`` §8.  Deterministic ``merge_mode``
makes zero model calls, so a run that must exercise the model uses
``llm_belief_merge`` + ``llm_local_solve``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from exp_graph.mas.factor_bank import DenseOutcome
from exp_graph.mas.phase_program import PhaseProgram, compile_phase_program_spec
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig


@dataclass(frozen=True)
class ArmRunResult:
    """One scored, metered whole-program arm run."""

    dense_outcome: DenseOutcome
    prompt_tokens: int
    completion_tokens: int
    model_calls: int
    messages: int
    total_steps: int
    success: bool
    partial: float
    execution_class: Literal["completed", "algorithm_failure"]
    safe_failure_code: str | None
    failed_stage_rank: int | None


def phase_program_for_artifact(registry: Any, artifact_handle: Any) -> PhaseProgram:
    """Resolve the exact PhaseProgram behind a registry artifact handle."""

    record = registry.resolve_artifact(artifact_handle)
    return PhaseProgram.model_validate(record.program.model_dump(mode="python"))


# Strategy-C directive: the submission barrier's failure mode is agents
# submitting their LOCAL aggregate (per-shard counts, partial maps) instead of
# combining every relayed contribution into the task's single GLOBAL answer.
# This host directive names that exact obligation.  It is answer-free (states
# the combination duty, never any task content) and is A/B-gated so the legacy
# barrier stays byte-identical when disabled.
GLOBAL_MERGE_SUBMISSION_DIRECTIVE = (
    "IMPORTANT: The task asks for ONE GLOBAL answer over ALL agents' shards "
    "combined. Your FINAL_PROTOCOL_BELIEF_JSON already contains everything "
    "that reached you: your own shard's contribution plus the contributions "
    "relayed from other agents (look in structured_state, proposal, and "
    "support). Do NOT submit your local shard's partial value. First combine "
    "ALL distinct per-agent contributions according to the task's own "
    "definition (for counts: sum the per-shard counts; for extrema: take the "
    "extremum of the per-shard extrema; for maps/lists: merge the partial "
    "entries into one complete structure), then submit that single combined "
    "global answer."
)


def run_phase_program_arm(
    *,
    program: PhaseProgram,
    instance: Any,
    n_agents: int,
    information_goal: str,
    seed: int,
    model_name: str,
    temperature: float,
    llm_provider: str,
    llm_client: Any,
    merge_mode: str = "llm_belief_merge",
    init_mode: str = "llm_local_solve",
    max_parallel_agents: int = 1,
    require_all_submissions: bool = False,
    final_submission_retries: int = 2,
    strengthen_submission_merge: bool = False,
) -> ArmRunResult:
    """Run one compiled Phase program on one Silo case and score it densely.

    The returned ``DenseOutcome`` is produced by the SAME scorer the gate uses.
    Token/model-call counts are the runner's authoritative aggregate for this
    whole arm run.
    """

    from masbench.engine import _protocol_adapter, _score_protocol_result
    from masbench.gates import dense_sample
    from masbench.evolve import _apply_precomputed_information_goal_score
    from exp_graph.mas.runner import summary_to_aggregate_row

    program = PhaseProgram.model_validate(program.model_dump(mode="python"))
    task_adapter = _protocol_adapter(instance, information_goal=information_goal)
    global_task = task_adapter.build_global_task()
    spec, _compiled = compile_phase_program_spec(program, n_agents=n_agents)
    config = ProtocolRunnerConfig(
        topology_name="chain",  # inert: protocol_spec drives the schedule
        n_agents=n_agents,
        seed=seed,
        model_name=model_name,
        merge_mode=merge_mode,
        init_mode=init_mode,
        llm_provider=llm_provider,
        temperature=temperature,
        # Sub-agent fan-out within this one arm run. The injected client stack
        # is thread-safe (stateless wrappers over the thread-safe SDK client),
        # and the runner aggregates usage only after futures complete; the
        # process-wide admission gate bounds total in-flight calls regardless.
        max_parallel_agents=max(1, int(max_parallel_agents)),
        # The registry's runtime profile pins enable_step_instructions=True in
        # every execution image, so the live runner must honor step
        # instructions too — otherwise an instruction-locus mutation would
        # change the attested image without changing behavior (an activation
        # honesty gap).  Bases whose instructions are None are unaffected.
        enable_step_instructions=True,
        protocol_spec=spec,
    )
    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=llm_client,
    ).run()
    # All-agents runs add the runtime-owned final submission barrier: every
    # agent must turn its final belief into one explicit, audited answer (the
    # same law the standard all_agents eval path enforces).  Sink mode has no
    # barrier; belief answers are graded as-is.  A barrier exhaustion is an
    # algorithm-level outcome: scoring proceeds without overrides and the
    # missing submissions honestly floor the quality metrics.
    final_submission_batch = None
    answer_overrides = None
    submitted_rounds = None
    if information_goal == "all_agents" and require_all_submissions:
        import json as _json

        from exp_graph.mas.python_code import MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION
        from exp_graph.runner.protocol import ProtocolActionError
        from masbench.final_submissions import run_final_submission_barrier

        prompts: dict[int, str] = {}
        for agent_id, state in enumerate(result.final_agent_states):
            submit_context = task_adapter.format_python_submit_prompt(
                global_task=global_task,
                local_observation=state.local_observation,
            )
            belief_json = _json.dumps(
                state.belief_state.model_dump(mode="json"),
                ensure_ascii=True,
                sort_keys=True,
            )
            directive = (
                GLOBAL_MERGE_SUBMISSION_DIRECTIVE + "\n\n"
                if strengthen_submission_merge
                else ""
            )
            prompts[agent_id] = (
                submit_context
                + "\n\nFINAL_PROTOCOL_BELIEF_JSON:\n"
                + belief_json
                + "\n\n"
                + directive
                + MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION
            )
        try:
            final_submission_batch = run_final_submission_barrier(
                prompts=prompts,
                llm_client=llm_client,
                model_name=model_name,
                temperature=temperature,
                max_parallel_agents=max(1, int(max_parallel_agents)),
                retries=max(0, int(final_submission_retries)),
            )
        except ProtocolActionError:
            final_submission_batch = None
        if final_submission_batch is not None:
            answer_overrides = [
                final_submission_batch.answers[agent_id]
                for agent_id in range(n_agents)
            ]
            final_round = int(result.total_steps) + (
                1 if init_mode == "llm_local_solve" else 0
            )
            submitted_rounds = [final_round for _ in range(n_agents)]
    score = _score_protocol_result(
        result,
        instance,
        task_adapter,
        global_task,
        extra={"case_id": getattr(instance, "case_id", "unknown")},
        information_goal=information_goal,
        answer_overrides=answer_overrides,
        submitted_rounds=submitted_rounds,
        final_submission_batch=final_submission_batch,
    )
    row = summary_to_aggregate_row(result.to_summary_dict())
    _apply_precomputed_information_goal_score(
        row,
        score=score,
        information_goal=information_goal,
        result=result,
        task_adapter=task_adapter,
    )
    dense_row = dense_sample(row)
    dense = DenseOutcome(
        V=dense_row["V"],
        K=dense_row["K"],
        U=dense_row["U"],
        P=dense_row["P"],
        S=dense_row["S"],
        stage_score=dense_row["stage_score"],
        C=dense_row["C"],
        D=dense_row["D"],
    )
    # Honest terminal classification.  A structurally valid run that produced a
    # scoreable answer is ``completed`` even if its quality is all-zero; a
    # validity floor (the program image did not run as a valid protocol) is a
    # real algorithm failure that keeps its cost.
    if dense.V >= 1.0:
        execution_class: Literal["completed", "algorithm_failure"] = "completed"
        safe_failure_code = None
        failed_stage_rank = None
    else:
        execution_class = "algorithm_failure"
        safe_failure_code = "program_validity_floor"
        failed_stage_rank = 0
    # Whole-arm metering truth includes the submission barrier's calls: the
    # store receipt and ArmReceipt usage must carry every provider crossing
    # this arm made, whether or not the paper C metric counts it the same way.
    barrier_prompt = (
        final_submission_batch.prompt_tokens
        if final_submission_batch is not None
        else 0
    )
    barrier_completion = (
        final_submission_batch.completion_tokens
        if final_submission_batch is not None
        else 0
    )
    barrier_calls = (
        final_submission_batch.model_calls
        if final_submission_batch is not None
        else 0
    )
    return ArmRunResult(
        dense_outcome=dense,
        prompt_tokens=int(result.total_prompt_tokens) + int(barrier_prompt),
        completion_tokens=(
            int(result.total_completion_tokens) + int(barrier_completion)
        ),
        model_calls=int(result.total_model_calls) + int(barrier_calls),
        messages=int(result.total_messages),
        total_steps=int(result.total_steps),
        success=bool(score.success),
        partial=float(score.partial or 0.0),
        execution_class=execution_class,
        safe_failure_code=safe_failure_code,
        failed_stage_rank=failed_stage_rank,
    )


__all__ = [
    "ArmRunResult",
    "phase_program_for_artifact",
    "run_phase_program_arm",
]
