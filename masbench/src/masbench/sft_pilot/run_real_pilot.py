"""Stage-12 pilot driver: replicated real SFT-Bank runs vs the anchor baseline.

Orchestration shape (the concurrency contract this driver guarantees):

- N replicate experiments (default 3) run CONCURRENTLY, one thread each —
  "several tests in flight".  Inside a replicate every probe/FINAL_VAL/TEST
  arm is one whole n-agent program run whose sub-agents fan out via
  ``max_parallel_agents`` (default 5) — "each test runs its sub-agents
  concurrently".
- One process-wide admission gate (``configure_global_llm_concurrency``,
  default 15) bounds total in-flight OpenAI calls across every layer, so
  3 concurrent tests x 5 sub-agents can never exceed the cap no matter how
  phases overlap.  The observed peak lands in the final report.
- The baseline arm (the frozen structural-anchor program — the current
  QueenBee static deployment) is evaluated on the SAME held-out TEST cases
  and seeds as every replicate's deployed program, through the same runner,
  scorer, client stack, and per-case budget.

Paid-call law: ``--llm openai`` refuses to start unless the external
``MASBENCH_SFT_PAID_PILOT_AUTHORIZED`` marker is set (same marker the sealed
profile entry demands) and prints the worst-case budget preview first.
``--llm fake`` rehearses the identical end-to-end mechanics offline.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any

from exp_graph.llm.concurrency import (
    configure_global_llm_concurrency,
    global_llm_limiter,
    maybe_limit_concurrency,
)


PAID_MARKER_ENV = "MASBENCH_SFT_PAID_PILOT_AUTHORIZED"
PAID_MARKER_VALUE = "yes-i-authorize-paid-gpt-4o-mini-calls"
STATE_KEY_ENV = "MASBENCH_SFT_STATE_KEY"

# gpt-4o-mini list prices (USD per 1M tokens) for the report's cost line —
# reporting only; authorization caps use the fixed conservative coefficients.
_PRICE_IN_PER_M = 0.15
_PRICE_OUT_PER_M = 0.60

_DENSE_FIELDS = ("V", "K", "U", "P", "S", "stage_score", "C", "D")


@dataclass(frozen=True)
class CaseSplit:
    test_case_ids: tuple[str, ...]
    replicate_probe: tuple[tuple[str, ...], ...]
    replicate_generation: tuple[str, ...]
    replicate_final_val: tuple[tuple[str, ...], ...]


def split_cases(
    all_case_ids: tuple[str, ...], *, replicates: int, test_count: int
) -> CaseSplit:
    """Deterministic split: shared TEST holdout + per-replicate train slices.

    TEST takes every stratified slot (indices ``i % 5 in {3, 4}`` over the
    sorted ids by default sizing) so it spreads across the benchmark's level
    ordering; the remaining pool rotates by six per replicate so each
    replicate's own probe/generation/FINAL_VAL cases are disjoint within the
    replicate and never touch TEST.
    """

    ordered = tuple(sorted(all_case_ids))
    if test_count >= len(ordered) - 9:
        raise ValueError("test_count leaves too few cases for training slices")
    stride_test = [
        case_id
        for index, case_id in enumerate(ordered)
        if index % 5 in {3, 4}
    ]
    test_ids = tuple(stride_test[:test_count])
    if len(test_ids) < test_count:
        remaining = [c for c in ordered if c not in set(stride_test)]
        test_ids = tuple(list(test_ids) + remaining[: test_count - len(test_ids)])
    pool = tuple(c for c in ordered if c not in set(test_ids))
    if len(pool) < 9:
        raise ValueError("case pool is too small for one replicate")
    probe: list[tuple[str, ...]] = []
    generation: list[str] = []
    final_val: list[tuple[str, ...]] = []
    for replicate in range(replicates):
        rotated = pool[replicate * 6 % len(pool):] + pool[: replicate * 6 % len(pool)]
        probe.append(tuple(rotated[0:6]))
        generation.append(rotated[6])
        final_val.append(tuple(rotated[7:9]))
    return CaseSplit(
        test_case_ids=test_ids,
        replicate_probe=tuple(probe),
        replicate_generation=tuple(generation),
        replicate_final_val=tuple(final_val),
    )


def _resolve_master_key(root: Path) -> bytes:
    encoded = os.environ.get(STATE_KEY_ENV)
    if encoded:
        from masbench.sft_phase_pilot import _decode_master_key

        return _decode_master_key()
    key = secrets.token_bytes(32)
    key_path = root / "master_key.hex"
    key_path.write_text(key.hex(), encoding="utf-8")
    os.chmod(key_path, 0o600)
    os.environ[STATE_KEY_ENV] = key.hex()
    print(f"[pilot] generated pilot master key at {key_path}")
    return key


def _build_arm_client(
    llm: str, *, timeout_s: float, reasoning_effort: str | None = None
):
    """No-retry scientific arm client: Limiter(Timeout(OpenAI(max_retries=0)))."""

    if llm == "fake":
        from masbench.llm.fake import BenchmarkFakeLLMClient

        return BenchmarkFakeLLMClient()
    from exp_graph.llm.openai_client import OpenAIChatClient
    from exp_graph.llm.timeout import TimeoutLLMClient

    return maybe_limit_concurrency(
        TimeoutLLMClient(
            OpenAIChatClient(
                max_retries=0,
                require_provider_usage=True,
                reasoning_effort=reasoning_effort,
            ),
            timeout_s,
        )
    )


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [row[field] for row in rows if field in row]
    return sum(values) / len(values) if values else None


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def build_effect_table(report: dict[str, Any]) -> str:
    """Render the final markdown effect table from the pilot report."""

    lines: list[str] = []
    baseline = report["baseline"]["aggregate"]
    lines.append("## SFT-Bank real pilot — effect table (TEST, held-out)\n")
    header = (
        "| arm | cases | success | mean S | mean P | mean stage | mean V "
        "| mean C (tokens) | mean D (msgs) | algo fail | infra fail |"
    )
    lines.append(header)
    lines.append("|" + "---|" * 11)

    def _arm_row(label: str, agg: dict[str, Any]) -> str:
        return (
            f"| {label} | {int(agg.get('cases_scored', 0))} "
            f"| {_fmt(agg.get('success_rate'))} "
            f"| {_fmt(agg.get('mean_S'))} "
            f"| {_fmt(agg.get('mean_P'))} "
            f"| {_fmt(agg.get('mean_stage_score'))} "
            f"| {_fmt(agg.get('mean_V'))} "
            f"| {_fmt(agg.get('mean_C'), 0)} "
            f"| {_fmt(agg.get('mean_D'), 1)} "
            f"| {int(agg.get('algorithm_failures', 0))} "
            f"| {int(agg.get('infrastructure_failures', 0))} |"
        )

    for label in sorted(report.get("baselines", {"anchor": report["baseline"]})):
        lines.append(
            _arm_row(label, report["baselines"][label]["aggregate"])
        )
    for rep in report["replicates"]:
        if rep.get("status") != "completed":
            lines.append(
                f"| SFT {rep.get('experiment_id', '?')} | FAILED: "
                f"{rep.get('error', 'unknown')} |" + " |" * 9
            )
            continue
        label = (
            f"SFT deployed ({rep['experiment_id']}, "
            f"{rep['test']['deployed_label']}, "
            f"gate={'accept' if rep['gate'].get('accepted') else 'reject'})"
        )
        lines.append(_arm_row(label, rep["test"]["aggregate"]))
    lines.append("")
    return "\n".join(lines)


def run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    import masbench  # noqa: F401  (bootstraps sibling exp_graph)
    from masbench.adapters.silo_bench import SiloBenchAdapter
    from masbench.sft_pilot.real_eval import (
        aggregate_eval_rows,
        evaluate_program_on_cases,
    )
    from masbench.sft_pilot.real_experiment import (
        RealExperimentSpec,
        author_real_v5_experiment,
    )
    from masbench.sft_pilot.real_train import (
        TEST_SEED_BASE,
        run_real_replicate,
    )
    from masbench.sft_pilot.experiment import preview_experiment_budget

    started = time.monotonic()
    repo_root = Path(__file__).resolve().parents[3].parent
    benchmarks_dir = (
        Path(args.benchmarks_dir)
        if args.benchmarks_dir
        else repo_root / "masbench" / "third_party" / "acl26-silo-bench" / "benchmarks"
    ).resolve()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    if args.llm == "openai":
        if os.environ.get(PAID_MARKER_ENV) != PAID_MARKER_VALUE:
            raise RuntimeError(
                "PAID_CALLS_NOT_AUTHORIZED: a real pilot requires "
                f"{PAID_MARKER_ENV}={PAID_MARKER_VALUE!r} set externally"
            )
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for --llm openai")

    limiter = configure_global_llm_concurrency(args.max_concurrent)
    print(
        f"[pilot] global LLM concurrency cap = "
        f"{limiter.max_concurrent if limiter else 'off'}"
    )

    adapter = SiloBenchAdapter(benchmarks_dir)
    instances = list(adapter.iter_instances(agent_counts=[args.agents]))
    instances_by_case = {inst.case_id: inst for inst in instances}
    print(
        f"[pilot] {len(instances)} real Silo cases at n_agents={args.agents}"
    )
    bases_count = len(
        [b for b in str(args.bases).split(",") if b.strip()]
    )
    split = split_cases(
        tuple(instances_by_case),
        replicates=max(args.replicates, bases_count),
        test_count=args.test_cases,
    )
    print(f"[pilot] TEST holdout ({len(split.test_case_ids)}): {list(split.test_case_ids)}")

    master = _resolve_master_key(root)
    fixed_git_commit = args.git_commit

    bases = [b.strip() for b in str(args.bases).split(",") if b.strip()]
    experiments = []
    for index, base in enumerate(bases):
        spec = RealExperimentSpec(
            experiment_id=f"sft-v5-{base}",
            root=root / f"rep-{base}",
            benchmarks_dir=benchmarks_dir,
            fixed_git_commit=fixed_git_commit,
            master_key=master,
            n_agents=args.agents,
            probe_case_ids=split.replicate_probe[index],
            generation_case_id=split.replicate_generation[index],
            final_val_case_ids=split.replicate_final_val[index],
            test_case_ids=split.test_case_ids,
            information_goal=args.goal,
            base_structure=base,
            model_name=args.model,
            reasoning_effort=(
                args.reasoning_effort if args.llm == "openai" else None
            ),
            search_layer=args.search_layer,
        )
        (root / f"rep-{base}").mkdir(parents=True, exist_ok=True)
        experiment = author_real_v5_experiment(spec)
        preview = preview_experiment_budget(experiment.seal, experiment.protocol)
        print(
            f"[pilot] authored {spec.experiment_id}: seal "
            f"{experiment.seal.digest[:16]}…, worst-case "
            f"{preview['max_model_calls']} store calls / "
            f"{preview['max_input_tokens']} in / "
            f"{preview['max_output_tokens']} out tokens"
        )
        experiments.append(experiment)

    arm_client = _build_arm_client(
        args.llm,
        timeout_s=args.request_timeout,
        reasoning_effort=(
            args.reasoning_effort if args.llm == "openai" else None
        ),
    )
    _FAKE_BASE_VALUES = {
        "gather_broadcast": 2,
        "sfs": 2,
        "static_exponential": 1,
        "one_peer_exponential_dag": "all_to_all",
        "broadcast": "exponential",
        "p2p": "bidirectional_ring",
        "one_peer_instruction": (
            "Absorb every incoming contribution, then recompute and carry "
            "the combined global answer forward each round."
        ),
    }

    _FAKE_ROUND_VALUES = {
        "gather_broadcast": [2, 3],
        "sfs": [2, 3],
        "static_exponential": [1, 2],
        "p2p": ["bidirectional_ring", "exponential"],
        "one_peer_exponential_dag": ["all_to_all"],
        "broadcast": ["exponential"],
        "one_peer_instruction": [
            (
                "Absorb every incoming contribution, then recompute and "
                "carry the combined global answer forward each round."
            ),
            (
                "Recompute the combined global answer from every "
                "contribution seen so far before relaying."
            ),
        ],
    }

    def _fake_transport(base: str, round_idx: int = 0):
        if args.llm != "fake":
            return None
        from masbench.sft_pilot.llm_meter import FakeDeterministicPilotTransport

        if args.search_layer == "whole_composition":
            # Deterministic structural rehearsal op: insert one bounded
            # pairwise-exchange phase after phase 0.
            return FakeDeterministicPilotTransport(
                reply_factory=lambda _digest: json.dumps(
                    {
                        "operation": {
                            "op_kind": "insert_phase",
                            "index": 1,
                            "phase": {
                                "kind": "pairwise_exchange",
                                "pattern": "rotating",
                                "max_rounds": 2,
                            },
                        }
                    }
                ),
                expected_model=args.model,
            )
        # An explicit non-default fake value (tests forcing duplicates)
        # overrides the per-base round table.
        if int(args.fake_generated_value) != 2:
            values = [int(args.fake_generated_value)]
        else:
            values = _FAKE_ROUND_VALUES.get(
                base, [int(args.fake_generated_value)]
            )
        value = values[min(round_idx, len(values) - 1)]
        return FakeDeterministicPilotTransport(
            reply_factory=lambda _digest: json.dumps({"value": value}),
            expected_model=args.model,
        )

    log_lock = threading.Lock()

    def log(message: str) -> None:
        with log_lock:
            print(message, flush=True)

    reports: list[dict[str, Any]] = []
    chain_lock = threading.Lock()
    print(
        f"[pilot] running {len(experiments)} base chains concurrently "
        f"(rounds<={args.rounds}, parallel tests={args.parallel_tests}, "
        f"sub-agents per test={args.max_parallel_agents})"
    )

    def _run_chain(base_index: int) -> list[dict[str, Any]]:
        from masbench.sft_pilot.real_train import anchor_generation_surface

        base = bases[base_index]
        chain_reports: list[dict[str, Any]] = []
        experiment = experiments[base_index]
        source_override = None
        for round_idx in range(max(1, int(args.rounds))):
            if round_idx > 0:
                prev = chain_reports[-1]
                if (
                    prev.get("status") != "completed"
                    or prev.get("test", {}).get("deployed_label")
                    != "gated_target"
                ):
                    break
                if args.search_layer == "whole_composition":
                    # Anchorize: the accepted whole composition becomes the
                    # next round's anchor program; a fresh sealed experiment
                    # freezes it (genesis locus = phase-0 pattern flip).
                    accepted_program = prev.get("target_program")
                    if not accepted_program:
                        break
                    spec = RealExperimentSpec(
                        experiment_id=f"sft-v5-{base}-r{round_idx + 1}",
                        root=root / f"rep-{base}-r{round_idx + 1}",
                        benchmarks_dir=benchmarks_dir,
                        fixed_git_commit=fixed_git_commit,
                        master_key=master,
                        n_agents=args.agents,
                        probe_case_ids=experiment.spec.probe_case_ids,
                        generation_case_id=experiment.spec.generation_case_id,
                        final_val_case_ids=experiment.spec.final_val_case_ids,
                        test_case_ids=split.test_case_ids,
                        information_goal=args.goal,
                        base_structure=base,
                        model_name=args.model,
                        reasoning_effort=(
                            args.reasoning_effort
                            if args.llm == "openai"
                            else None
                        ),
                        search_layer=args.search_layer,
                        source_program_override=accepted_program,
                    )
                    (root / f"rep-{base}-r{round_idx + 1}").mkdir(
                        parents=True, exist_ok=True
                    )
                    experiment = author_real_v5_experiment(spec)
                    log(
                        f"[pilot] {base} round {round_idx + 1}: anchorized "
                        "at the accepted whole composition"
                    )
                    report = run_real_replicate(
                        experiment,
                        instances_by_case=instances_by_case,
                        llm_provider=args.llm,
                        arm_llm_client=arm_client,
                        generation_transport=_fake_transport(base, round_idx),
                        max_parallel_agents=args.max_parallel_agents,
                        test_parallel_cases=args.parallel_tests,
                        strengthen_submission_merge=bool(
                            args.strengthen_submission
                        ),
                        log=log,
                    )
                    report["base_structure"] = base
                    report["round"] = round_idx + 1
                    chain_reports.append(report)
                    continue
                accepted_value = prev["generated_hub_value"]
                prev_plan = experiment.seal.structural_anchor_plan
                prev_source, _ = anchor_generation_surface(
                    prev_plan, args.agents
                )
                spec = RealExperimentSpec(
                    experiment_id=f"sft-v5-{base}-r{round_idx + 1}",
                    root=root / f"rep-{base}-r{round_idx + 1}",
                    benchmarks_dir=benchmarks_dir,
                    fixed_git_commit=fixed_git_commit,
                    master_key=master,
                    n_agents=args.agents,
                    probe_case_ids=experiment.spec.probe_case_ids,
                    generation_case_id=experiment.spec.generation_case_id,
                    final_val_case_ids=experiment.spec.final_val_case_ids,
                    test_case_ids=split.test_case_ids,
                    information_goal=args.goal,
                    base_structure=base,
                    source_value_override=accepted_value,
                    target_value_override=prev_source,
                    model_name=args.model,
                    reasoning_effort=(
                        args.reasoning_effort if args.llm == "openai" else None
                    ),
                )
                (root / f"rep-{base}-r{round_idx + 1}").mkdir(
                    parents=True, exist_ok=True
                )
                experiment = author_real_v5_experiment(spec)
                log(
                    f"[pilot] {base} round {round_idx + 1}: anchored at "
                    f"accepted value {accepted_value!r}"
                )
            report = run_real_replicate(
                experiment,
                instances_by_case=instances_by_case,
                llm_provider=args.llm,
                arm_llm_client=arm_client,
                generation_transport=_fake_transport(base, round_idx),
                max_parallel_agents=args.max_parallel_agents,
                test_parallel_cases=args.parallel_tests,
                strengthen_submission_merge=bool(
                    args.strengthen_submission
                ),
                log=log,
            )
            report["base_structure"] = base
            report["round"] = round_idx + 1
            chain_reports.append(report)
        return chain_reports

    with ThreadPoolExecutor(max_workers=args.parallel_tests) as executor:
        futures = {
            executor.submit(_run_chain, base_index): bases[base_index]
            for base_index in range(len(bases))
        }
        for future in as_completed(futures):
            base = futures[future]
            try:
                chain = future.result()
                with chain_lock:
                    reports.extend(chain)
                log(
                    f"[pilot] chain {base} finished with "
                    f"{len(chain)} round(s)"
                )
            except Exception as exc:  # noqa: BLE001 - keep other chains
                log(f"[pilot] chain {base} FAILED: {exc}")
                report_path = (
                    root / f"rep-{base}" / "replicate-report.json"
                )
                if report_path.exists():
                    with chain_lock:
                        reports.append(
                            json.loads(
                                report_path.read_text(encoding="utf-8")
                            )
                        )
                else:
                    with chain_lock:
                        reports.append(
                            {
                                "experiment_id": f"sft-v5-{base}",
                                "status": "failed",
                                "error": str(exc),
                            }
                        )
    reports.sort(key=lambda item: item.get("experiment_id", ""))

    # --- Baseline arm: the frozen anchor program on the same TEST cases.
    test_instances = tuple(
        instances_by_case[case_id] for case_id in split.test_case_ids
    )
    test_seeds = tuple(
        TEST_SEED_BASE + index for index in range(len(test_instances))
    )

    def _rows_payload(rows):
        return [
            {
                "case_id": row.case_id,
                "seed": row.seed,
                "infrastructure_error": row.infrastructure_error,
                **(
                    {
                        "execution_class": row.result.execution_class,
                        "success": row.result.success,
                        "partial": row.result.partial,
                        **{
                            name: getattr(row.result.dense_outcome, name)
                            for name in _DENSE_FIELDS
                        },
                        "model_calls": row.result.model_calls,
                        "prompt_tokens": row.result.prompt_tokens,
                        "completion_tokens": row.result.completion_tokens,
                    }
                    if row.result is not None
                    else {}
                ),
            }
            for row in rows
        ]

    baselines: dict[str, Any] = {}
    for experiment in experiments:
        base = experiment.spec.base_structure
        label = f"base:{base}"
        print(f"[pilot] evaluating {label} source program on TEST cases")
        rows = evaluate_program_on_cases(
            program=experiment.seal.structural_anchor_plan.source_program,
            instances=test_instances,
            seeds=test_seeds,
            arm_label=label,
            n_agents=args.agents,
            information_goal=args.goal,
            model_name=args.model,
            temperature=0.0,
            llm_provider=args.llm,
            llm_client=arm_client,
            merge_mode="deterministic" if args.llm == "fake" else "llm_belief_merge",
            init_mode="deterministic" if args.llm == "fake" else "llm_local_solve",
            max_parallel_cases=args.parallel_tests,
            max_parallel_agents=args.max_parallel_agents,
            require_all_submissions=(
                args.goal == "all_agents" and args.llm != "fake"
            ),
            strengthen_submission_merge=bool(args.strengthen_submission),
            progress=lambda row: log(f"[pilot] {row.arm_label} {row.case_id} done"),
        )
        baselines[label] = {
            "aggregate": aggregate_eval_rows(rows),
            "rows": _rows_payload(rows),
        }

    # Paper-protocol reference arms (the benchmark's own three transports).
    paper_protocols = [
        p.strip() for p in str(args.paper_protocols).split(",") if p.strip()
    ]
    if paper_protocols and args.llm == "openai" and args.goal == "all_agents":
        from masbench.adapters.silo_paper_protocols import (
            run_silo_paper_protocol,
        )
        from masbench.core.config import RunConfig

        paper_cfg = RunConfig(
            benchmark="silo_bench",
            silo_eval_mode="all_agents",
            llm_provider="openai",
            model_name=args.model,
            temperature=0.0,
        )

        def _paper_case(job):
            protocol, index = job
            instance = test_instances[index]
            try:
                score = run_silo_paper_protocol(
                    instance,
                    paper_cfg,
                    protocol=protocol,
                    llm_client=arm_client,
                )
                return protocol, {
                    "case_id": instance.case_id,
                    "seed": test_seeds[index],
                    "success": bool(score.success),
                    "partial": float(score.partial or 0.0),
                    "model_calls": int(score.n_model_calls),
                    "prompt_tokens": int(score.tokens),
                    "completion_tokens": 0,
                    "messages": int(score.n_messages),
                }
            except Exception as exc:  # noqa: BLE001 - honest infra row
                return protocol, {
                    "case_id": instance.case_id,
                    "seed": test_seeds[index],
                    "infrastructure_error": f"{type(exc).__name__}: {exc}",
                }

        jobs = [
            (protocol, index)
            for protocol in paper_protocols
            for index in range(len(test_instances))
        ]
        paper_rows: dict[str, list[dict[str, Any]]] = {
            p: [] for p in paper_protocols
        }
        with ThreadPoolExecutor(max_workers=args.parallel_tests) as pool:
            for protocol, row in pool.map(_paper_case, jobs):
                paper_rows[protocol].append(row)
                log(f"[pilot] paper:{protocol} {row['case_id']} done")
        for protocol, rows in paper_rows.items():
            scored = [r for r in rows if "success" in r]
            aggregate = {
                "cases_total": float(len(rows)),
                "cases_scored": float(len(scored)),
                "infrastructure_failures": float(len(rows) - len(scored)),
                "success_rate": (
                    sum(1.0 for r in scored if r["success"]) / len(scored)
                    if scored
                    else None
                ),
                "mean_partial": (
                    sum(r["partial"] for r in scored) / len(scored)
                    if scored
                    else None
                ),
                "total_model_calls": float(
                    sum(r.get("model_calls", 0) for r in rows)
                ),
                "total_prompt_tokens": float(
                    sum(r.get("prompt_tokens", 0) for r in rows)
                ),
                "total_completion_tokens": 0.0,
            }
            baselines[f"paper:{protocol}"] = {
                "aggregate": aggregate,
                "rows": rows,
            }

    baseline = baselines.get(
        f"base:{experiments[0].spec.base_structure}", {"aggregate": {}, "rows": []}
    )

    # --- Budget + concurrency accounting.
    def _tokens(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
        calls = sum(int(row.get("model_calls", 0) or 0) for row in rows)
        prompt = sum(int(row.get("prompt_tokens", 0) or 0) for row in rows)
        completion = sum(
            int(row.get("completion_tokens", 0) or 0) for row in rows
        )
        return calls, prompt, completion

    accounting: dict[str, Any] = {"arms": {}}
    total_calls = total_in = total_out = 0
    for rep in reports:
        if rep.get("status") != "completed":
            continue
        rep_rows: list[dict[str, Any]] = []
        for unit in rep.get("units", []):
            for side in ("source", "target"):
                if unit.get(side):
                    rep_rows.append(unit[side])
        gate = rep.get("gate", {})
        for role in ("incumbent_rows", "candidate_rows"):
            rep_rows.extend(gate.get(role, []) or [])
        rep_rows.extend(rep.get("test", {}).get("rows", []) or [])
        calls, prompt, completion = _tokens(rep_rows)
        accounting["arms"][rep["experiment_id"]] = {
            "model_calls": calls,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        }
        total_calls += calls
        total_in += prompt
        total_out += completion
    calls, prompt, completion = _tokens(baseline["rows"])
    accounting["arms"]["baseline_anchor"] = {
        "model_calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
    }
    total_calls += calls
    total_in += prompt
    total_out += completion
    accounting["total"] = {
        "model_calls": total_calls,
        "prompt_tokens": total_in,
        "completion_tokens": total_out,
        "approx_cost_usd": round(
            total_in / 1e6 * _PRICE_IN_PER_M + total_out / 1e6 * _PRICE_OUT_PER_M,
            4,
        ),
    }
    limiter = global_llm_limiter()
    accounting["concurrency"] = {
        "cap": limiter.max_concurrent if limiter else None,
        "peak_in_flight": limiter.peak_in_flight if limiter else None,
    }

    report = {
        "pilot": "sft_v5_real_pilot",
        "llm": args.llm,
        "n_agents": args.agents,
        "replicates": reports,
        "baseline": baseline,
        "baselines": baselines,
        "case_split": {
            "test": list(split.test_case_ids),
            "probe": [list(item) for item in split.replicate_probe],
            "generation": list(split.replicate_generation),
            "final_val": [list(item) for item in split.replicate_final_val],
        },
        "accounting": accounting,
        "wall_time_s": round(time.monotonic() - started, 1),
        "fixed_git_commit": fixed_git_commit,
    }
    report_path = root / "pilot_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    table = build_effect_table(report)
    (root / "effect_table.md").write_text(table, encoding="utf-8")
    print(table)
    print(f"[pilot] report: {report_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", choices=("fake", "openai"), default="fake")
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="worker model for every arm (must be within the widened "
        "protocol model law)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        choices=(None, "low", "medium", "high"),
        help="reasoning effort for the worker model (reasoning families "
        "omit sampling temperature at the transport)",
    )
    parser.add_argument(
        "--goal",
        choices=("sink", "all_agents"),
        default="all_agents",
        help=(
            "information goal: all_agents grades every agent's own final "
            "answer and (on real runs) enforces the per-agent submission "
            "barrier; sink grades only the designated sink"
        ),
    )
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument(
        "--strengthen-submission",
        action="store_true",
        help="enable the strategy-C global-merge submission directive "
        "for every arm (uniform equal treatment)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="chained evolution rounds per base (round k+1 anchors at round "
        "k's accepted value; stops early on reject/neutral/harmful)",
    )
    parser.add_argument(
        "--bases",
        default=(
            "one_peer_exponential_dag,static_exponential,p2p,broadcast,sfs"
        ),
        help="comma list of anchor base structures; one sealed experiment each",
    )
    parser.add_argument(
        "--paper-protocols",
        default="p2p,broadcast,sfs",
        help="paper transports evaluated as reference arms on TEST (real runs)",
    )
    parser.add_argument(
        "--search-layer",
        choices=("direct_factor", "whole_composition"),
        default="direct_factor",
        help=(
            "Scientific channel for this run's transitions: direct scalar "
            "mutations (default) or whole-composition structural operations"
        ),
    )
    parser.add_argument("--test-cases", type=int, default=12)
    parser.add_argument("--agents", type=int, default=5)
    parser.add_argument("--parallel-tests", type=int, default=3)
    parser.add_argument("--max-parallel-agents", type=int, default=5)
    parser.add_argument("--max-concurrent", type=int, default=15)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument(
        "--fake-generated-value",
        type=int,
        default=2,
        help="offline rehearsal only: the fake transport's generated scalar",
    )
    parser.add_argument("--benchmarks-dir", default=None)
    parser.add_argument(
        "--root",
        default=None,
        help="pilot output root (default masbench/runs/sft_v5_real_<stamp>)",
    )
    parser.add_argument(
        "--git-commit",
        default=None,
        help="frozen commit recorded in the manifests (default: current HEAD)",
    )
    args = parser.parse_args()
    if args.root is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        args.root = str(
            Path(__file__).resolve().parents[3] / "runs" / f"sft_v5_real_{stamp}"
        )
    if args.git_commit is None:
        import subprocess

        args.git_commit = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    run_pilot(args)


if __name__ == "__main__":
    main()
