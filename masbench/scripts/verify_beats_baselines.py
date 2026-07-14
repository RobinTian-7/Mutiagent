"""Phase-2 frozen judge: does R-round self-evolution beat EVERY baseline?

Protocol (honest by construction):
  1. Disjoint case split. Prefer explicit ``--train-cases``/``--test-cases``;
     otherwise the lexicographic tail of ``--cases`` is TEST, as in phase 1.
  2. Evolve for ``--rounds`` R (>=1) rounds on TRAIN only, ACCUMULATING the
     skill bank + motif stats across rounds (the "after several evolutions"
     state is what gets judged).
  3. ``fixed_best_on_train``: every topology in ``--fixed-topologies`` runs on
     the TRAIN cases x train seeds; the best mean exact-match (lexicographic
     tiebreak) is selected -- the strongest constant named-topology policy
     choosable WITHOUT test data. Oracle-on-test is deliberately NOT a baseline.
  4. Paired eval on TEST: for each (case, seed), evolved and every requested
     baseline run with identical conditions. A pair where ANY arm errors is
     DROPPED whole (symmetric), and counted. ``--baselines`` can additionally
     select the paper's dynamic P2P, Broadcast, and SFS transports.
  5. PASS iff, against EACH requested baseline: paired mean delta
     (evolved - baseline) >= --delta-min AND (evolved-only wins - baseline-only
     wins) >= --win-margin.
  6. Rounds STABILITY is a separate reported verdict (not the exit code): with
     --curves-json (a ``masbench curve`` output), the last 3 rounds' scores
     must all exceed every baseline recorded in that file.

Exit code: 0 = verified win over all baselines, 1 = not verified, 2 = aborted
(budget guard). Offline (--llm fake) Silo is topology-invariant, so this MUST
exit 1 with "machinery OK"; that is the harness smoke test.
The report retains per-agent submissions and paper S/P/C/D for every arm.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner.protocol import ProtocolActionError

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_paper_protocols import (
    PAPER_PROTOCOL_ARMS,
    run_silo_paper_protocol,
)
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.diagnostics import run_full_information_single_agent
from masbench.curve import (
    _bank_and_motif,
    _bounded,
    _evolved_planner_mode,
    _merge_motif,
    _split_cases,
)
from masbench.engine import _build_llm_client, run_fixed_protocol
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution
from masbench.failures import (
    FailureClass,
    classify_exception,
    make_failure_record,
    zero_scored_metrics,
)

BASELINES = ("select", "graphgen", "fixed")
AVAILABLE_BASELINES = (*BASELINES, "programgen", "pycodegen", *PAPER_PROTOCOL_ARMS)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Persist checkpoint metadata without exposing a partially written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _checkpoint_config(args: argparse.Namespace) -> dict[str, Any]:
    """Canonical verifier arguments that must match when resuming."""

    payload = dict(vars(args))
    payload.pop("resume", None)
    return payload


def _load_deployed_round(
    skill_banks_root: Path,
    completed_rounds: int,
) -> tuple[SkillBank, dict[str, Any], list[dict[str, Any]]]:
    """Load the exact bank, motif, and logs after a completed round."""

    if completed_rounds <= 0:
        return SkillBank(), {}, []
    round_logs: list[dict[str, Any]] = []
    for round_number in range(1, completed_rounds + 1):
        round_dir = skill_banks_root / f"round_{round_number:02d}"
        summary_path = round_dir / "evolution_summary.json"
        bank_path = round_dir / "deployed" / "bank.json"
        motif_path = round_dir / "deployed_motif_stats.json"
        for required in (summary_path, bank_path, motif_path):
            if not required.is_file():
                raise RuntimeError(
                    f"resume checkpoint is incomplete; missing {required}"
                )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        round_logs.append(
            {
                "round": round_number,
                "n_skills": int(summary.get("skill_bank_size_after", 0)),
                "gate": summary.get("gate"),
                "skill_ids": summary.get("skill_ids_after"),
                "rejected_skill_ids": summary.get("rejected_skill_ids"),
                "hot_start": summary.get("hot_start"),
            }
        )
    last_dir = skill_banks_root / f"round_{completed_rounds:02d}"
    bank_payload = json.loads(
        (last_dir / "deployed" / "bank.json").read_text(encoding="utf-8")
    )
    bank = SkillBank(
        skills=[
            SkillCard.model_validate(item)
            for item in bank_payload.get("skills", [])
        ]
    )
    motif = json.loads(
        (last_dir / "deployed_motif_stats.json").read_text(encoding="utf-8")
    )
    return bank, motif, round_logs


def _resolve_case_split(
    all_cases: list[str],
    *,
    holdout_frac: float,
    train_cases: list[str] | None = None,
    test_cases: list[str] | None = None,
) -> tuple[list[str], list[str], str]:
    """Resolve an auditable explicit split or fall back to tail holdout."""
    if (train_cases is None) != (test_cases is None):
        raise ValueError("--train-cases and --test-cases must be provided together")
    if train_cases is None:
        train, test = _split_cases(all_cases, holdout_frac)
        return train, test, "lexicographic_holdout"

    train = list(dict.fromkeys(train_cases))
    test = list(dict.fromkeys(test_cases or []))
    if not train or not test:
        raise ValueError("explicit TRAIN and TEST case lists must both be non-empty")
    overlap = set(train) & set(test)
    if overlap:
        raise ValueError(f"TRAIN and TEST cases overlap: {sorted(overlap)}")
    missing = (set(train) | set(test)) - set(all_cases)
    if missing:
        raise ValueError(
            "requested cases are unavailable for the selected levels/agent count: "
            f"{sorted(missing)}"
        )
    return train, test, "explicit"


def _save_skill_bank_snapshot(
    root: Path,
    *,
    relative_name: str,
    skills: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Persist one auditable bank as JSON plus one YAML file per skill."""
    snapshot_dir = root / relative_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    bank = SkillBank(skills=[SkillCard.model_validate(item) for item in skills])
    canonical = [
        skill.model_dump(mode="json")
        for skill in sorted(bank, key=lambda item: item.skill_id)
    ]
    bank.save_dir(snapshot_dir / "skills")
    payload = {
        "n_skills": len(canonical),
        "skill_ids": [item["skill_id"] for item in canonical],
        "skills": canonical,
    }
    (snapshot_dir / "bank.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=str)
    )
    return {
        "name": relative_name,
        "n_skills": len(canonical),
        "skill_ids": payload["skill_ids"],
        "bank_json": str(Path(relative_name) / "bank.json"),
        "skills_dir": str(Path(relative_name) / "skills"),
        "metadata_json": str(Path(relative_name) / "metadata.json"),
    }


def _pick_fixed_best(rows: list[dict[str, Any]]) -> str:
    """Argmax mean exact over per-run rows {topology, exact}; ties -> lexicographic."""
    by_topology: dict[str, list[float]] = {}
    for row in rows:
        by_topology.setdefault(str(row["topology"]), []).append(float(row["exact"]))
    means = {t: sum(v) / len(v) for t, v in by_topology.items() if v}
    best = max(means.values())
    return min(t for t, m in means.items() if m == best)


FIXED_ARM_PREFIX = "fixed:"


def _expand_fixed_baselines(
    baselines: tuple[str, ...],
    fixed_topologies: list[str],
    *,
    per_topology: bool,
) -> tuple[tuple[str, ...], frozenset[str]]:
    """Expand the aggregate ``fixed`` baseline into per-topology paired arms.

    When ``per_topology`` is set AND ``fixed`` is a requested baseline, every
    entry of ``fixed_topologies`` becomes its OWN independent paired arm, keyed
    ``fixed:<topology>`` (evaluated on each held-out (case, seed) exactly like
    any other arm and judged with the untouched ``_verdict`` logic). The
    aggregate ``fixed`` arm (``fixed_best_on_train``) is retained as a
    SUPPLEMENTARY paired arm rather than the sole fixed baseline, so the paper's
    two named transports are compared directly instead of being collapsed to
    their train-selected maximum. Order is preserved and the aggregate ``fixed``
    moves to the end.

    Returns ``(eval_baselines, supplementary_arms)``: the ordered baselines to
    evaluate, and the subset that is reported but excluded from the verifier's
    own pass/fail gate. When ``per_topology`` is false (the default) the input
    is returned unchanged, so existing behavior and the frozen offline test are
    fully preserved.
    """
    if not per_topology or "fixed" not in baselines:
        return baselines, frozenset()
    topologies = list(dict.fromkeys(str(t) for t in fixed_topologies))
    if not topologies:
        return baselines, frozenset()
    expanded = [name for name in baselines if name != "fixed"]
    expanded.extend(f"{FIXED_ARM_PREFIX}{topology}" for topology in topologies)
    expanded.append("fixed")  # aggregate fixed_best_on_train, supplementary
    return tuple(dict.fromkeys(expanded)), frozenset({"fixed"})


def _verdict(
    pairs: list[dict[str, Any]], *, delta_min: float, win_margin: int,
    baselines: tuple[str, ...] = BASELINES,
) -> dict[str, Any]:
    """Paired verdict vs every requested baseline."""
    n = len(pairs)
    means = {
        arm: (sum(float(p[arm]) for p in pairs) / n if n else 0.0)
        for arm in ("evolved", *baselines)
    }
    per_baseline: dict[str, Any] = {}
    for b in baselines:
        wins = sum(1 for p in pairs if p["evolved"] > p[b])
        losses = sum(1 for p in pairs if p["evolved"] < p[b])
        delta = means["evolved"] - means[b]
        per_baseline[b] = {
            "delta": delta,
            "evolved_only_wins": wins,
            "baseline_only_wins": losses,
            "passed": bool(delta >= delta_min and (wins - losses) >= win_margin),
        }
    return {
        "arm_means": means,
        "per_baseline": per_baseline,
        "passed": bool(n > 0 and all(v["passed"] for v in per_baseline.values())),
    }


def _stable_rounds(curves: dict[str, Any], k: int = 3) -> bool:
    """Last k rounds of a ``masbench curve`` rounds_curve all strictly above
    every baseline recorded in the file."""
    rounds = curves.get("rounds_curve") or []
    baselines = curves.get("baselines") or {}
    if len(rounds) < k or not baselines:
        return False
    bar = max(float(v) for v in baselines.values())
    return all(float(r["score"]) > bar for r in rounds[-k:])


def _metrics_from_score(
    score: Any,
    *,
    honest_failures: bool = False,
) -> dict[str, Any]:
    """Paper metrics plus every submitted answer from a ScoreResult."""
    extra = score.extra or {}
    exact = 1.0 if score.success else 0.0
    result = {
        "success": exact,
        "S": float(extra.get("paper_S", exact) or 0.0),
        "P": float(extra.get("paper_P", score.partial or 0.0) or 0.0),
        "C": float(extra.get("paper_C", 0.0) or 0.0),
        "D": float(extra.get("paper_D", 0.0) or 0.0),
        "messages": int(score.n_messages),
        "model_calls": int(score.n_model_calls),
        "tokens": int(score.tokens),
        "per_agent_submissions": extra.get("per_agent_submissions", []),
    }
    result["failure_class"] = str(
        extra.get("failure_class", FailureClass.SUCCESS.value)
    )
    if extra.get("failure_record"):
        result["failure_record"] = extra["failure_record"]
    if honest_failures and result["failure_class"] == FailureClass.SUCCESS.value:
        coverage = extra.get(
            "min_information_coverage",
            extra.get("sink_information_coverage", 1.0),
        )
        submissions = list(extra.get("per_agent_submissions", []) or [])
        missing_submission = any(
            isinstance(item, dict)
            and item.get("answer") in (None, "", "null", "unknown")
            for item in submissions
        )
        if float(coverage or 0.0) < 1.0 or missing_submission:
            result["failure_class"] = FailureClass.ALGORITHM.value
            result["failure_stage"] = (
                "coverage" if float(coverage or 0.0) < 1.0 else "submission"
            )
    return result


def _metrics_from_evolution_row(row: dict[str, Any]) -> dict[str, Any]:
    """Paper metrics carried by the unified scorer into an evolution row."""
    exact = float(row.get("ExactMatchRate", 0.0))
    result = {
        "success": exact,
        "S": float(row.get("paper_S", exact) or 0.0),
        "P": float(
            row.get("paper_P", row.get("PartialCorrectness", exact)) or 0.0
        ),
        "C": float(row.get("paper_C", 0.0) or 0.0),
        "D": float(row.get("paper_D", 0.0) or 0.0),
        "messages": int(row.get("MeanTotalMessages", 0) or 0),
        "model_calls": int(row.get("MeanTotalModelCalls", 0) or 0),
        "tokens": int(row.get("MeanTokenCost", 0) or 0),
        "per_agent_submissions": row.get("per_agent_submissions", []),
    }
    result["failure_class"] = str(
        row.get("failure_class", FailureClass.SUCCESS.value)
    )
    if row.get("failure_record"):
        result["failure_record"] = row["failure_record"]
    return result


def _require_complete_submissions(
    metrics: dict[str, Any], *, n_agents: int, arm: str
) -> dict[str, Any]:
    """Reject a supposedly completed all-agent arm with null answer slots."""

    submissions = list(metrics.get("per_agent_submissions") or [])
    by_agent = {
        int(item["agent_id"]): item
        for item in submissions
        if isinstance(item, dict) and "agent_id" in item
    }
    missing = []
    for agent_id in range(n_agents):
        item = by_agent.get(agent_id)
        answer = item.get("answer") if item is not None else None
        if answer is None or (
            isinstance(answer, str)
            and answer.strip().lower() in {"", "null", "none", "unknown"}
        ):
            missing.append(agent_id)
    if missing:
        raise ProtocolActionError(
            f"{arm} did not produce required final answers for agents {missing}"
        )
    metrics["all_submitted"] = True
    return metrics


def _paper_metric_means(
    pair_details: list[dict[str, Any]], arms: tuple[str, ...]
) -> dict[str, dict[str, float]]:
    """Aggregate S/P/C/D over retained paired evaluation units."""
    means: dict[str, dict[str, float]] = {}
    for arm in arms:
        rows = [detail["arms"][arm] for detail in pair_details]
        means[arm] = {
            metric: (
                sum(float(row[metric]) for row in rows) / len(rows)
                if rows
                else 0.0
            )
            for metric in ("S", "P", "C", "D")
        }
    return means


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmarks-dir", default="third_party/acl26-silo-bench/benchmarks")
    p.add_argument("--llm", default="openai")
    p.add_argument("--model-name", default="gpt-4o-mini")
    p.add_argument("--merge-mode", default="llm_full_merge")
    p.add_argument("--init-mode", default="llm_local_solve")
    p.add_argument("--objective", default="accuracy_first")
    p.add_argument("--evolved-mode", default="select_then_refine",
                   choices=[
                       "topology_select",
                       "graph_generate",
                       "program_generate",
                       "python_generate",
                       "select_then_refine",
                   ])
    p.add_argument("--rounds", type=int, default=3,
                   help="evolution rounds R (bank+motif accumulate across rounds)")
    p.add_argument(
        "--curriculum",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="grow the train subset within every requested level across rounds",
    )
    p.add_argument(
        "--skill-ablation-strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="reject individually measured skills with more paired losses than wins",
    )
    p.add_argument(
        "--capability-diagnostic",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also run the full-information single-agent capability floor",
    )
    p.add_argument(
        "--hot-start",
        dest="hot_start_enabled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="pretrain from fixed organizations/paper transports and run paired "
             "reuse plus fresh-creation branches on every TRAIN pair",
    )
    p.add_argument("--hot-start-protocols", default="auto")
    p.add_argument("--hot-start-topologies", default="auto")
    p.add_argument("--hot-start-seed-count", type=int, default=1)
    p.add_argument(
        "--hot-start-dual-branch",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p.add_argument(
        "--hot-start-innovation-mode",
        choices=["auto", "graph_generate", "program_generate", "python_generate"],
        default="auto",
    )
    p.add_argument(
        "--python-innovation-strategy",
        choices=["fresh", "mutate", "mutate_and_fresh"],
        default="mutate_and_fresh",
    )
    p.add_argument(
        "--failure-policy",
        choices=["legacy_drop", "honest_v2"],
        default="legacy_drop",
    )
    p.add_argument(
        "--evolution-gate-policy",
        choices=["legacy_non_regression", "strict_dense_v2"],
        default="legacy_non_regression",
    )
    p.add_argument("--strict-gate-min-dense-delta", type=float, default=0.01)
    p.add_argument("--strict-gate-partial-tolerance", type=float, default=0.0)
    p.add_argument("--strict-gate-bootstrap-samples", type=int, default=2000)
    p.add_argument("--strict-gate-bootstrap-seed", type=int, default=20260713)
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--levels", nargs="+", default=["II", "III"])
    p.add_argument(
        "--cases", nargs="+", default=None,
        help="cases to split by --holdout-frac; incompatible with explicit case lists",
    )
    p.add_argument(
        "--train-cases", nargs="+", default=None,
        help="explicit TRAIN cases; requires --test-cases",
    )
    p.add_argument(
        "--test-cases", nargs="+", default=None,
        help="explicit held-out TEST cases; requires --train-cases",
    )
    p.add_argument(
        "--val-cases", nargs="+", default=None,
        help=(
            "explicit validation cases kept disjoint from TRAIN and TEST; "
            "when omitted, run_evolution retains its legacy internal split"
        ),
    )
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=list(range(11, 19)))
    p.add_argument("--fixed-topologies", nargs="+",
                   default=["tree", "mesh_star", "one_peer_exponential_dag_star", "chain"])
    p.add_argument(
        "--fixed-per-topology-arms",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="expand the 'fixed' baseline into one INDEPENDENT paired arm per "
             "--fixed-topologies entry (arm key 'fixed:<topology>') while keeping "
             "the aggregate fixed_best_on_train as a supplementary paired arm; "
             "off by default so existing behavior is unchanged",
    )
    p.add_argument(
        "--baselines", nargs="+", choices=list(AVAILABLE_BASELINES),
        default=list(BASELINES),
        help="paired baselines to judge (default: select graphgen fixed); use "
             "'p2p broadcast sfs' for all original SILO-BENCH transports",
    )
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--python-repair-attempts", type=int, default=3)
    p.add_argument(
        "--python-execution-timeout",
        type=float,
        default=None,
        help=(
            "whole Python program timeout; default derives it from request "
            "timeout, rounds, n_agents, and intra-task parallelism"
        ),
    )
    p.add_argument("--python-cpu-seconds", type=int, default=10)
    p.add_argument("--python-memory-mb", type=int, default=512)
    p.add_argument("--python-max-output-bytes", type=int, default=1_000_000)
    p.add_argument("--python-max-model-calls", type=int, default=20)
    p.add_argument("--python-max-completion-tokens", type=int, default=4000)
    p.add_argument("--python-max-messages", type=int, default=30)
    p.add_argument(
        "--require-all-submissions",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "require one non-empty answer from every Agent in every retained "
            "all_agents arm; fixed/paper runs use an audited completion barrier"
        ),
    )
    p.add_argument(
        "--final-submission-retries",
        type=int,
        default=2,
        help="format-only retries per Agent in the strict final-answer barrier",
    )
    p.add_argument(
        "--max-parallel-agents",
        type=int,
        default=5,
        help="parallel Agent calls within one logical round",
    )
    p.add_argument(
        "--python-worker-contract",
        choices=["action_json_v1", "message_only_v1", "message_only_v2"],
        default="action_json_v1",
        help="PythonGen worker output contract for every python_generate arm "
             "(evolved, hot-start, pycodegen baseline); action_json_v1 keeps "
             "the legacy default behaviour",
    )
    p.add_argument(
        "--silo-eval-mode", dest="silo_eval_mode",
        choices=["sink", "all_agents"], default="sink",
        help="information goal for EVERY run in this verification (prompts, "
             "graph validation, scoring, skill bank, caches and the report are "
             "namespaced by it); science runs should pass it explicitly",
    )
    p.add_argument("--graph-validation-seeds", type=int, default=0)
    p.add_argument("--use-llm-insights", action="store_true")
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument(
        "--llm-timeout-attempts",
        type=int,
        default=2,
        help="bounded attempts for one request that hits the wall-clock timeout",
    )
    p.add_argument(
        "--require-complete-runs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="abort at the last checkpoint instead of dropping infrastructure failures",
    )
    p.add_argument("--max-rounds", type=int, default=4,
                   help="maximum rounds for each paper P2P/Broadcast/SFS run")
    p.add_argument(
        "--workers",
        type=int,
        default=2,
        help=(
            "parallel run units; PythonGenerate can additionally issue up to "
            "--max-parallel-agents calls per unit, so size their product to the "
            "provider limit"
        ),
    )
    p.add_argument("--delta-min", type=float, default=0.05)
    p.add_argument("--win-margin", type=int, default=2)
    p.add_argument("--max-runs", type=int, default=600,
                   help="abort before spending if the planned LLM run count exceeds this")
    p.add_argument("--curves-json", default=None,
                   help="optional masbench-curve JSON for the rounds-stability verdict")
    p.add_argument("--out", default="runs/verify_beats_baselines")
    p.add_argument(
        "--resume",
        action="store_true",
        help="resume evolution from the last completed round checkpoint in --out",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    baselines = tuple(dict.fromkeys(args.baselines))
    # Optionally promote each fixed topology to its own paired baseline while
    # keeping fixed_best_on_train as a supplementary arm (see
    # _expand_fixed_baselines). eval_baselines drives every arm dispatch, the
    # budget guard, the verdict table and the report; supplementary_baselines
    # are reported but do NOT gate the exit code.
    eval_baselines, supplementary_baselines = _expand_fixed_baselines(
        baselines, args.fixed_topologies, per_topology=args.fixed_per_topology_arms
    )
    primary_baselines = tuple(
        b for b in eval_baselines if b not in supplementary_baselines
    )
    if set(baselines) & set(PAPER_PROTOCOL_ARMS) and args.silo_eval_mode != "all_agents":
        raise SystemExit(
            "p2p/broadcast/sfs baselines require --silo-eval-mode all_agents"
        )
    if (
        args.hot_start_enabled
        and args.silo_eval_mode != "all_agents"
        and args.hot_start_protocols.strip().lower() not in {"", "auto"}
    ):
        raise SystemExit(
            "hot-start p2p/broadcast/sfs require --silo-eval-mode all_agents"
        )
    explicit_split = args.train_cases is not None or args.test_cases is not None
    if explicit_split and args.cases is not None:
        raise SystemExit(
            "--cases cannot be combined with --train-cases/--test-cases"
        )
    if (args.train_cases is None) != (args.test_cases is None):
        raise SystemExit("--train-cases and --test-cases must be provided together")
    if args.val_cases is not None and not explicit_split:
        raise SystemExit("--val-cases requires --train-cases and --test-cases")
    if args.val_cases is not None:
        named_splits = {
            "TRAIN": set(args.train_cases),
            "VAL": set(args.val_cases),
            "TEST": set(args.test_cases),
        }
        for left, right in (("TRAIN", "VAL"), ("TRAIN", "TEST"), ("VAL", "TEST")):
            case_overlap = named_splits[left] & named_splits[right]
            if case_overlap:
                raise SystemExit(
                    f"{left}/{right} cases must be disjoint; "
                    f"overlap={sorted(case_overlap)}"
                )
    overlap = set(args.eval_seeds) & (set(args.train_seeds) | set(args.val_seeds))
    if overlap:
        raise SystemExit(f"eval seeds must be disjoint from train/val seeds; overlap={sorted(overlap)}")

    cfg = RunConfig(
        benchmark="silo_bench", objective=args.objective,
        merge_mode=args.merge_mode, init_mode=args.init_mode,
        llm_provider=args.llm, model_name=args.model_name,
        request_timeout=args.request_timeout, evolved_mode=args.evolved_mode,
        llm_timeout_attempts=args.llm_timeout_attempts,
        require_complete_runs=args.require_complete_runs,
        num_graph_candidates=args.graphgen_candidates,
        graph_validation_seeds=args.graph_validation_seeds,
        use_llm_insights=args.use_llm_insights, n_agents=args.n_agents,
        max_rounds=args.max_rounds,
        max_parallel_agents=args.max_parallel_agents,
        silo_eval_mode=args.silo_eval_mode,
        curriculum_enabled=args.curriculum,
        curriculum_total_rounds=args.rounds,
        skill_ablation_strict=args.skill_ablation_strict,
        python_repair_attempts=args.python_repair_attempts,
        python_execution_timeout=args.python_execution_timeout,
        python_cpu_seconds=args.python_cpu_seconds,
        python_memory_mb=args.python_memory_mb,
        python_max_output_bytes=args.python_max_output_bytes,
        python_max_model_calls=args.python_max_model_calls,
        python_max_completion_tokens=args.python_max_completion_tokens,
        python_max_messages=args.python_max_messages,
        require_all_submissions=args.require_all_submissions,
        final_submission_retries=args.final_submission_retries,
        python_worker_contract=args.python_worker_contract,
        graph_artifacts_dir=str(Path(args.out) / "graphgen_artifacts"),
        program_artifacts_dir=str(Path(args.out) / "programgen_artifacts"),
        python_artifacts_dir=str(Path(args.out) / "pycodegen_artifacts"),
        hot_start_enabled=args.hot_start_enabled,
        hot_start_protocols=args.hot_start_protocols,
        hot_start_topologies=args.hot_start_topologies,
        hot_start_seed_count=args.hot_start_seed_count,
        hot_start_dual_branch=args.hot_start_dual_branch,
        hot_start_innovation_mode=args.hot_start_innovation_mode,
        python_innovation_strategy=args.python_innovation_strategy,
        failure_policy=args.failure_policy,
        evolution_gate_policy=args.evolution_gate_policy,
        strict_gate_min_dense_delta=args.strict_gate_min_dense_delta,
        strict_gate_partial_tolerance=args.strict_gate_partial_tolerance,
        strict_gate_bootstrap_samples=args.strict_gate_bootstrap_samples,
        strict_gate_bootstrap_seed=args.strict_gate_bootstrap_seed,
    )
    adapter = SiloBenchAdapter(args.benchmarks_dir)
    requested_cases = args.cases
    if explicit_split:
        requested_cases = list(
            dict.fromkeys(
                [*args.train_cases, *(args.val_cases or []), *args.test_cases]
            )
        )
    instances = list(adapter.iter_instances(
        levels=args.levels, agent_counts=[args.n_agents], cases=requested_cases))
    all_cases = sorted({i.case_id for i in instances})
    try:
        train_cases, test_cases, split_mode = _resolve_case_split(
            all_cases,
            holdout_frac=args.holdout_frac,
            train_cases=args.train_cases,
            test_cases=args.test_cases,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    test_instances = [i for i in instances if i.case_id in set(test_cases)]
    train_instances = [i for i in instances if i.case_id in set(train_cases)]
    validation_cases = list(args.val_cases or []) or None
    if validation_cases is not None:
        found_validation = {
            i.case_id for i in instances if i.case_id in set(validation_cases)
        }
        missing_validation = sorted(set(validation_cases) - found_validation)
        if missing_validation:
            raise SystemExit(
                f"validation cases unavailable for n={args.n_agents}: "
                f"{missing_validation}"
            )

    # ---- budget guard (before any spend) ----
    n_pairs = len(test_instances) * len(args.eval_seeds)
    train_evolution_count = (
        len(train_cases)
        if validation_cases is not None
        else max(1, len(train_cases) // 2)
    )
    validation_evolution_count = (
        len(validation_cases)
        if validation_cases is not None
        else max(1, len(train_cases) // 2)
    )
    evo_per_round = (
        train_evolution_count * 3 * len(args.train_seeds)
        + validation_evolution_count * 3 * len(args.val_seeds)
        + 2 * validation_evolution_count * len(args.val_seeds)
    )
    hot_pretrain_runs = 0
    if args.hot_start_enabled:
        topology_count = (
            (2 if args.silo_eval_mode == "all_agents" else 7)
            if args.hot_start_topologies.strip().lower() == "auto"
            else len([x for x in args.hot_start_topologies.split(",") if x.strip()])
        )
        protocol_count = (
            (3 if args.silo_eval_mode == "all_agents" else 0)
            if args.hot_start_protocols.strip().lower() == "auto"
            else len([x for x in args.hot_start_protocols.split(",") if x.strip()])
        )
        hot_pretrain_runs = (
            train_evolution_count
            * max(1, args.hot_start_seed_count)
            * (topology_count + protocol_count)
        )
        if args.hot_start_dual_branch:
            resolved_innovation = args.hot_start_innovation_mode
            if resolved_innovation == "auto":
                resolved_innovation = (
                    args.evolved_mode
                    if args.evolved_mode in {
                        "graph_generate",
                        "program_generate",
                        "python_generate",
                    }
                    else "graph_generate"
                )
            branch_count = (
                3
                if resolved_innovation == "python_generate"
                and args.python_innovation_strategy == "mutate_and_fresh"
                else 2
            )
            evo_per_round += (
                branch_count * train_evolution_count * len(args.train_seeds)
            )
    fixed_sel_runs = (
        len(args.fixed_topologies) * len(train_instances) * len(args.train_seeds)
        if "fixed" in eval_baselines
        else 0
    )
    paired_arm_count = 1 + len(eval_baselines)
    planned = (
        args.rounds * evo_per_round
        + hot_pretrain_runs
        + fixed_sel_runs
        + paired_arm_count * n_pairs
    )
    cleanliness = "hot-start/non-clean" if args.hot_start_enabled else "clean_run"
    print(f"=== SILO EVAL MODE: {args.silo_eval_mode} ({cleanliness} pipeline) ===")
    print(
        f"plan: split={split_mode} TRAIN={train_cases} TEST={test_cases} "
        f"rounds={args.rounds}"
    )
    print(f"plan: ~{args.rounds}x{evo_per_round} evolution + {hot_pretrain_runs} hot-pretrain "
          f"+ {fixed_sel_runs} fixed-selection "
          f"+ {paired_arm_count * n_pairs} paired eval "
          f"({paired_arm_count} arms) = ~{planned} protocol runs "
          f"(n={args.n_agents})")
    if planned > args.max_runs:
        print(f"ABORT: planned {planned} > --max-runs {args.max_runs}")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    skill_banks_root = out / "skill_banks"
    manifest_path = skill_banks_root / "manifest.json"
    checkpoint_path = out / "run_checkpoint.json"
    checkpoint_config_path = out / "checkpoint_config.json"
    requested_checkpoint_config = _checkpoint_config(args)
    completed_rounds = 0
    if args.resume:
        if not checkpoint_path.is_file() or not checkpoint_config_path.is_file():
            raise SystemExit(
                "--resume requires run_checkpoint.json and checkpoint_config.json "
                "inside --out"
            )
        stored_config = json.loads(
            checkpoint_config_path.read_text(encoding="utf-8")
        )
        if stored_config != requested_checkpoint_config:
            raise SystemExit(
                "resume configuration differs from checkpoint_config.json"
            )
        checkpoint_state = json.loads(
            checkpoint_path.read_text(encoding="utf-8")
        )
        completed_rounds = int(checkpoint_state.get("completed_rounds", 0))
        if not 0 <= completed_rounds <= args.rounds:
            raise SystemExit(
                f"invalid completed_rounds={completed_rounds} in checkpoint"
            )
        if not manifest_path.is_file():
            raise SystemExit("resume checkpoint is missing skill_banks/manifest.json")
        skill_bank_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        clean_pythongen = bool(
            skill_bank_manifest.get("clean_pythongen", cfg.clean_pythongen)
        )
        print(
            f"resume: loading completed evolution rounds 1..{completed_rounds}",
            flush=True,
        )
    else:
        clean_pythongen = bool(cfg.clean_pythongen)
        skill_bank_manifest: dict[str, Any] = {
            "schema_version": "skill_bank_audit_v2",
            "silo_eval_mode": args.silo_eval_mode,
            "clean_run": not args.hot_start_enabled,
            "hot_start_enabled": args.hot_start_enabled,
            "python_innovation_strategy": args.python_innovation_strategy,
            "python_worker_contract": args.python_worker_contract,
            "failure_policy": args.failure_policy,
            "evolution_gate_policy": args.evolution_gate_policy,
            "require_all_submissions": args.require_all_submissions,
            "require_complete_runs": args.require_complete_runs,
            "llm_timeout_attempts": args.llm_timeout_attempts,
            "clean_pythongen": clean_pythongen,
            "description": (
                "Every distinct bank used by this verifier. Evolution rounds "
                "retain before, candidate, and gate-approved deployed snapshots."
            ),
            "fixed_uses_skill_bank": False,
            "snapshots": [],
            "rounds": [],
        }

        # Cold controls always use an empty bank. Save each semantic role once
        # rather than writing the same empty payload for every paired run.
        for arm in (
            name
            for name in baselines
            if name in {"graphgen", "programgen", "pycodegen", "select"}
        ):
            entry = _save_skill_bank_snapshot(
                skill_banks_root,
                relative_name=f"controls/{arm}_empty",
                skills=[],
                metadata={
                    "arm": arm,
                    "scope": "shared empty control bank",
                    "used_for_every_control_run": True,
                },
            )
            skill_bank_manifest["snapshots"].append(entry)
        _write_json_atomic(manifest_path, skill_bank_manifest)
        _write_json_atomic(checkpoint_config_path, requested_checkpoint_config)
        _write_json_atomic(
            checkpoint_path,
            {
                "schema_version": "verify_checkpoint_v1",
                "status": "initialized",
                "completed_rounds": 0,
                "requested_rounds": args.rounds,
            },
        )

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))
    generate = cfg.evolved_mode in (
        "graph_generate",
        "program_generate",
        "python_generate",
        "select_then_refine",
    )
    eval_cfg = replace(
        cfg,
        planner_mode=(
            cfg.evolved_mode
            if cfg.evolved_mode
            in {"graph_generate", "program_generate", "python_generate"}
            else ("graph_generate" if generate else "topology_select")
        ),
    )

    # ---- 1. R rounds of evolution on TRAIN only (accumulating) ----
    t0 = time.monotonic()
    bank, motif, rounds_log = _load_deployed_round(
        skill_banks_root, completed_rounds
    )
    for r in range(completed_rounds + 1, args.rounds + 1):
        round_cfg = replace(evo_cfg, curriculum_round=r)
        summ = run_evolution(
            adapter, cases=train_cases, validation_cases=validation_cases,
            agent_counts=[args.n_agents],
            train_seeds=args.train_seeds, val_seeds=args.val_seeds,
            cfg=round_cfg, levels=args.levels, llm_client=client,
            workers=args.workers, progress=True,
            initial_skills=[s.model_dump(mode="json") for s in bank] or None,
        )
        clean_pythongen = clean_pythongen and bool(
            summ.get("clean_pythongen", True)
        )
        skill_bank_manifest["clean_pythongen"] = clean_pythongen
        bank, new_motif = _bank_and_motif(summ)
        motif = _merge_motif(motif, new_motif)
        round_dir = skill_banks_root / f"round_{r:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "evolution_summary.json").write_text(
            json.dumps(summ, indent=2, sort_keys=True, default=str)
        )
        (round_dir / "deployed_motif_stats.json").write_text(
            json.dumps(motif, indent=2, sort_keys=True, default=str)
        )
        snapshots = summ.get("skill_bank_snapshots") or {
            "before": [],
            "candidate": summ.get("evolved_skills", []),
            "deployed": summ.get("evolved_skills", []),
        }
        round_snapshots = []
        for stage in ("before", "candidate", "deployed"):
            entry = _save_skill_bank_snapshot(
                skill_banks_root,
                relative_name=f"round_{r:02d}/{stage}",
                skills=list(snapshots.get(stage) or []),
                metadata={
                    "round": r,
                    "stage": stage,
                    "gate": summ.get("gate"),
                    "meaning": {
                        "before": "bank entering this evolution round",
                        "candidate": "post-update bank before the held-out gate",
                        "deployed": "bank allowed to reach evaluation after the gate",
                    }[stage],
                },
            )
            round_snapshots.append(entry)
            skill_bank_manifest["snapshots"].append(entry)
        skill_bank_manifest["rounds"].append(
            {
                "round": r,
                "gate": summ.get("gate"),
                "hot_start": summ.get("hot_start"),
                "snapshots": [entry["name"] for entry in round_snapshots],
                "evolution_summary": f"round_{r:02d}/evolution_summary.json",
                "deployed_motif_stats": (
                    f"round_{r:02d}/deployed_motif_stats.json"
                ),
            }
        )
        _write_json_atomic(
            manifest_path,
            skill_bank_manifest,
        )
        rounds_log.append({
            "round": r, "n_skills": len(bank), "gate": summ.get("gate"),
            "skill_ids": summ.get("skill_ids_after"),
            "rejected_skill_ids": summ.get("rejected_skill_ids"),
            "hot_start": summ.get("hot_start"),
        })
        _write_json_atomic(
            checkpoint_path,
            {
                "schema_version": "verify_checkpoint_v1",
                "status": "evolution",
                "completed_rounds": r,
                "requested_rounds": args.rounds,
                "last_deployed_bank": f"skill_banks/round_{r:02d}/deployed/bank.json",
                "last_motif_stats": (
                    f"skill_banks/round_{r:02d}/deployed_motif_stats.json"
                ),
            },
        )
        print(f"round {r}/{args.rounds}: skills={len(bank)} gate={summ.get('gate')}")

    skill_bank_manifest["snapshots"] = [
        entry
        for entry in skill_bank_manifest.get("snapshots", [])
        if entry.get("name") != "final/deployed"
    ]
    skill_bank_manifest.pop("final", None)
    final_entry = _save_skill_bank_snapshot(
        skill_banks_root,
        relative_name="final/deployed",
        skills=[skill.model_dump(mode="json") for skill in bank],
        metadata={
            "stage": "final",
            "rounds": args.rounds,
            "meaning": "exact evolved bank used by the paired evaluation",
        },
    )
    (skill_banks_root / "final" / "motif_stats.json").write_text(
        json.dumps(motif, indent=2, sort_keys=True, default=str)
    )
    skill_bank_manifest["snapshots"].append(final_entry)
    skill_bank_manifest["final"] = {
        **final_entry,
        "motif_stats": "final/motif_stats.json",
    }
    _write_json_atomic(
        manifest_path,
        skill_bank_manifest,
    )
    _write_json_atomic(
        checkpoint_path,
        {
            "schema_version": "verify_checkpoint_v1",
            "status": "training_complete",
            "completed_rounds": args.rounds,
            "requested_rounds": args.rounds,
            "final_bank": "skill_banks/final/deployed/bank.json",
            "final_motif_stats": "skill_banks/final/motif_stats.json",
        },
    )

    # ---- 2. fixed_best_on_train (train data only) ----
    fixed_tasks = (
        [
            (inst, topo, seed)
            for topo in args.fixed_topologies
            for inst in train_instances
            for seed in args.train_seeds
        ]
        if "fixed" in eval_baselines
        else []
    )

    def _fixed_train(task) -> dict[str, Any] | None:
        inst, topo, seed = task
        try:
            score = run_fixed_protocol(
                inst, replace(cfg, seed=seed), topology=topo, llm_client=client)
            exact = 1.0 if score.success else 0.0
        except Exception as exc:  # noqa: BLE001 - centrally classified below
            print(f"  [fixed-select] {topo} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            if args.failure_policy == "honest_v2":
                failure_class = classify_exception(exc)
                if failure_class == FailureClass.INFRASTRUCTURE:
                    if args.require_complete_runs:
                        raise
                    return None
                if failure_class == FailureClass.HARNESS:
                    raise
            exact = 0.0
        return {"topology": topo, "exact": exact}

    fixed_rows: list[dict[str, Any]] = []
    fixed_best: str | None = None
    fixed_train_means: dict[str, float] = {}
    if fixed_tasks:
        with ThreadPoolExecutor(max_workers=min(args.workers, len(fixed_tasks))) as ex:
            fixed_rows = [row for row in ex.map(_fixed_train, fixed_tasks) if row is not None]
        if not fixed_rows:
            raise RuntimeError("fixed baseline selection has no non-infrastructure rows")
        fixed_best = _pick_fixed_best(fixed_rows)
        fixed_train_means = {
            t: sum(r["exact"] for r in fixed_rows if r["topology"] == t)
            / max(1, sum(1 for r in fixed_rows if r["topology"] == t))
            for t in args.fixed_topologies
        }
        print(f"fixed_best_on_train: {fixed_best} (train means: {fixed_train_means}) "
              f"({time.monotonic() - t0:.0f}s)")
    _write_json_atomic(
        checkpoint_path,
        {
            "schema_version": "verify_checkpoint_v1",
            "status": "fixed_selection_complete",
            "completed_rounds": args.rounds,
            "requested_rounds": args.rounds,
            "final_bank": "skill_banks/final/deployed/bank.json",
            "fixed_best_topology": fixed_best,
            "fixed_train_means": fixed_train_means,
        },
    )

    # ---- 3. paired 4-arm eval on TEST ----
    pair_keys = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]

    def _arm(task) -> dict[str, Any] | None:
        inst, seed, arm = task
        try:
            if arm in PAPER_PROTOCOL_ARMS:
                score = run_silo_paper_protocol(
                    inst,
                    replace(cfg, seed=seed),
                    protocol=arm,
                    llm_client=client,
                )
                metrics = _metrics_from_score(
                    score,
                    honest_failures=args.failure_policy == "honest_v2",
                )
                return (
                    _require_complete_submissions(
                        metrics, n_agents=args.n_agents, arm=arm
                    )
                    if args.require_all_submissions
                    else metrics
                )
            if arm.startswith(FIXED_ARM_PREFIX):
                topology = arm[len(FIXED_ARM_PREFIX):]
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=topology, llm_client=client)
                metrics = _metrics_from_score(
                    score,
                    honest_failures=args.failure_policy == "honest_v2",
                )
                return (
                    _require_complete_submissions(
                        metrics, n_agents=args.n_agents, arm=arm
                    )
                    if args.require_all_submissions
                    else metrics
                )
            if arm == "fixed":
                assert fixed_best is not None
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=fixed_best, llm_client=client)
                metrics = _metrics_from_score(
                    score,
                    honest_failures=args.failure_policy == "honest_v2",
                )
                return (
                    _require_complete_submissions(
                        metrics, n_agents=args.n_agents, arm=arm
                    )
                    if args.require_all_submissions
                    else metrics
                )
            if arm == "evolved":
                row = _run_one(
                    inst, eval_cfg, objective=objective, skill_bank=bank, seed=seed,
                    llm_client=client, motif_stats=motif or None, diag_phase="")
            elif arm == "select":
                row = _run_one(
                    inst, replace(cfg, planner_mode="topology_select"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            elif arm == "graphgen":
                row = _run_one(
                    inst, replace(cfg, planner_mode="graph_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            elif arm == "programgen":
                row = _run_one(
                    inst, replace(cfg, planner_mode="program_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            else:  # pycodegen
                row = _run_one(
                    inst, replace(cfg, planner_mode="python_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            metrics = _metrics_from_evolution_row(row)
            return (
                _require_complete_submissions(
                    metrics, n_agents=args.n_agents, arm=arm
                )
                if args.require_all_submissions
                else metrics
            )
        except Exception as exc:  # noqa: BLE001 - centrally classified below
            print(f"  [eval] {arm} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            if args.failure_policy == "legacy_drop":
                return None
            failure_class = classify_exception(exc)
            planner_mode = {
                "evolved": eval_cfg.planner_mode,
                "select": "topology_select",
                "graphgen": "graph_generate",
                "programgen": "program_generate",
                "pycodegen": "python_generate",
            }.get(arm, "paper_protocol" if arm in PAPER_PROTOCOL_ARMS else "fixed_named")
            record = make_failure_record(
                exc=exc,
                planner_mode=planner_mode,
                information_goal=args.silo_eval_mode,
                worker_contract=(
                    cfg.python_worker_contract
                    if planner_mode == "python_generate"
                    else "n/a"
                ),
                case_id=inst.case_id,
                seed=seed,
                n_agents=args.n_agents,
                branch=f"eval:{arm}",
                artifact_reference=getattr(exc, "artifacts_dir", None),
                structural_signature=str(
                    getattr(exc, "structural_signature", arm)
                ),
            )
            if failure_class == FailureClass.ALGORITHM:
                return {
                    **zero_scored_metrics(exc),
                    "failure_class": failure_class.value,
                    "failure_record": record.model_dump(mode="json"),
                }
            if failure_class == FailureClass.INFRASTRUCTURE:
                if args.require_complete_runs:
                    raise
                return {
                    "failure_class": failure_class.value,
                    "failure_record": record.model_dump(mode="json"),
                }
            raise

    arms = ("evolved", *eval_baselines)
    tasks = [(inst, seed, arm) for (inst, seed) in pair_keys for arm in arms]
    with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
        flat = list(ex.map(_arm, tasks))
    pairs: list[dict[str, Any]] = []
    pair_details: list[dict[str, Any]] = []
    dropped = 0
    algorithm_failures_by_arm = {arm: 0 for arm in arms}
    infrastructure_failures_by_arm = {arm: 0 for arm in arms}
    harness_errors: list[dict[str, Any]] = []
    dropped_infrastructure_pairs = 0
    zero_scored_algorithm_runs = 0
    for k, (inst, seed) in enumerate(pair_keys):
        start = len(arms) * k
        vals = flat[start:start + len(arms)]
        if any(v is None for v in vals):
            dropped += 1
            continue
        assert all(isinstance(value, dict) for value in vals)
        metrics_by_arm = {
            arm: vals[i]
            for i, arm in enumerate(arms)
        }
        infrastructure_arms = [
            arm
            for arm, metrics in metrics_by_arm.items()
            if metrics.get("failure_class") == FailureClass.INFRASTRUCTURE.value
        ]
        for arm in infrastructure_arms:
            infrastructure_failures_by_arm[arm] += 1
        if infrastructure_arms:
            dropped += 1
            dropped_infrastructure_pairs += 1
            continue
        for arm, metrics in metrics_by_arm.items():
            if metrics.get("failure_class") == FailureClass.ALGORITHM.value:
                algorithm_failures_by_arm[arm] += 1
                zero_scored_algorithm_runs += 1
        pairs.append({
            "case_id": inst.case_id, "seed": seed,
            **{arm: float(metrics_by_arm[arm]["success"]) for arm in arms},
        })
        pair_details.append(
            {
                "case_id": inst.case_id,
                "seed": seed,
                "arms": metrics_by_arm,
            }
        )

    # ---- 4. verdict ----
    verdict = _verdict(
        pairs,
        delta_min=args.delta_min,
        win_margin=args.win_margin,
        baselines=eval_baselines,
    )
    # The verifier's own pass/fail gate is computed over the PRIMARY baselines
    # only; supplementary arms (e.g. the aggregate fixed_best_on_train when
    # per-topology fixed arms are enabled) are reported but never gate the exit
    # code. With per-topology fixed arms off this reduces exactly to
    # verdict["passed"] (supplementary is empty). The pre-registered scientific
    # PASS/FAIL/INCONCLUSIVE is decided by the separate paired-analysis script.
    verifier_passed = bool(
        len(pairs) > 0
        and all(verdict["per_baseline"][b]["passed"] for b in primary_baselines)
    )
    paper_metric_means = _paper_metric_means(pair_details, arms)
    capability_diagnostic: dict[str, Any] = {
        "enabled": bool(args.capability_diagnostic),
        "full_information_single_agent": None,
        "cold_generated": (
            paper_metric_means.get("pycodegen")
            if cfg.evolved_mode == "python_generate"
            else
            paper_metric_means.get("programgen")
            if cfg.evolved_mode == "program_generate"
            else paper_metric_means.get("graphgen")
        ),
        "evolved_generated": paper_metric_means.get("evolved"),
    }
    if args.capability_diagnostic:
        def _full_info(task: tuple[BenchmarkInstance, int]) -> dict[str, Any] | None:
            inst, seed = task
            try:
                return _metrics_from_score(
                    run_full_information_single_agent(
                        inst,
                        replace(cfg, seed=seed),
                        llm_client=client,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - diagnostic is noncompetitive
                print(
                    f"  [diagnostic] {inst.case_id} seed={seed} FAILED: {exc}",
                    flush=True,
                )
                return None

        with ThreadPoolExecutor(
            max_workers=min(args.workers, max(1, len(pair_keys)))
        ) as ex:
            diagnostic_rows = [
                row for row in ex.map(_full_info, pair_keys) if row is not None
            ]
        capability_diagnostic["full_information_single_agent"] = {
            metric: (
                sum(float(row[metric]) for row in diagnostic_rows)
                / len(diagnostic_rows)
                if diagnostic_rows
                else 0.0
            )
            for metric in ("S", "P", "C", "D")
        }
        capability_diagnostic["n_runs"] = len(diagnostic_rows)
    machinery_ok = bool(
        len(bank) > 0
        and len(rounds_log) == args.rounds
        and all(r.get("gate") for r in rounds_log)
    )
    stable_rounds_ok = None
    if args.curves_json:
        stable_rounds_ok = _stable_rounds(json.loads(Path(args.curves_json).read_text()))

    report = {
        "silo_eval_mode": args.silo_eval_mode,
        "clean_run": not args.hot_start_enabled,
        "hot_start_enabled": args.hot_start_enabled,
        "hot_start_protocols": args.hot_start_protocols,
        "hot_start_topologies": args.hot_start_topologies,
        "hot_start_seed_count": args.hot_start_seed_count,
        "hot_start_dual_branch": args.hot_start_dual_branch,
        "hot_start_innovation_mode": args.hot_start_innovation_mode,
        "python_innovation_strategy": args.python_innovation_strategy,
        "python_worker_contract": args.python_worker_contract,
        "require_all_submissions": args.require_all_submissions,
        "final_submission_retries": args.final_submission_retries,
        "require_complete_runs": args.require_complete_runs,
        "request_timeout": args.request_timeout,
        "llm_timeout_attempts": args.llm_timeout_attempts,
        "checkpoint": {
            "enabled": True,
            "resume_requested": bool(args.resume),
            "state_path": str(checkpoint_path),
            "config_path": str(checkpoint_config_path),
            "completed_rounds": args.rounds,
        },
        "evolution_gate_policy": args.evolution_gate_policy,
        "strict_gate": {
            "min_dense_delta": args.strict_gate_min_dense_delta,
            "partial_tolerance": args.strict_gate_partial_tolerance,
            "bootstrap_samples": args.strict_gate_bootstrap_samples,
            "bootstrap_seed": args.strict_gate_bootstrap_seed,
        },
        "artifact_roots": {
            "graph_generate": cfg.graph_artifacts_dir,
            "program_generate": cfg.program_artifacts_dir,
            "python_generate": cfg.python_artifacts_dir,
        },
        "clean_pythongen": clean_pythongen,
        "mode": cfg.evolved_mode, "n_agents": args.n_agents, "rounds": args.rounds,
        "train_cases": train_cases, "val_cases": validation_cases,
        "test_cases": test_cases,
        "split_mode": split_mode,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds,
        "fixed_topologies": args.fixed_topologies,
        "baselines": list(baselines),
        "fixed_per_topology_arms": bool(args.fixed_per_topology_arms),
        "eval_baselines": list(eval_baselines),
        "primary_baselines": list(primary_baselines),
        "supplementary_baselines": sorted(supplementary_baselines),
        "fixed_best_topology": fixed_best, "fixed_train_means": fixed_train_means,
        "n_pairs": len(pairs), "dropped_pairs": dropped,
        "failure_policy": args.failure_policy,
        "algorithm_failures_by_arm": algorithm_failures_by_arm,
        "infrastructure_failures_by_arm": infrastructure_failures_by_arm,
        "harness_errors": harness_errors,
        "dropped_infrastructure_pairs": dropped_infrastructure_pairs,
        "zero_scored_algorithm_runs": zero_scored_algorithm_runs,
        "arm_means": verdict["arm_means"], "per_baseline": verdict["per_baseline"],
        "paper_metric_means": paper_metric_means,
        "capability_diagnostic": capability_diagnostic,
        "pair_details": pair_details,
        "rounds_log": rounds_log, "n_skills": len(bank),
        "skill_bank_manifest": str(manifest_path),
        "n_skill_bank_snapshots": len(skill_bank_manifest["snapshots"]),
        "machinery_ok": machinery_ok, "stable_rounds_ok": stable_rounds_ok,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin},
        "passed": verifier_passed,
        "verdict_passed_all_arms": verdict["passed"],
        "pairs": pairs,
    }
    path = out / f"verify_beats_baselines_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))
    _write_json_atomic(
        checkpoint_path,
        {
            "schema_version": "verify_checkpoint_v1",
            "status": "complete",
            "completed_rounds": args.rounds,
            "requested_rounds": args.rounds,
            "final_bank": "skill_banks/final/deployed/bank.json",
            "report": path.name,
            "n_pairs": len(pairs),
            "dropped_pairs": dropped,
        },
    )

    means = verdict["arm_means"]
    print(f"\n=== SILO EVAL MODE: {args.silo_eval_mode} ===")
    print(f"\npaired held-out exact-match over {len(pairs)} (case,seed) pairs "
          f"({dropped} dropped):")
    print(f"  evolved (R={args.rounds}) : {means['evolved'] * 100:5.1f}%")
    for b in eval_baselines:
        v = verdict["per_baseline"][b]
        label = f"{b}={fixed_best}" if b == "fixed" else b
        tag = " [supplementary]" if b in supplementary_baselines else ""
        print(f"  vs {label:<35}: {means[b] * 100:5.1f}%  delta={v['delta'] * 100:+.1f}pp "
              f"wins={v['evolved_only_wins']}/{v['baseline_only_wins']} "
              f"{'PASS' if v['passed'] else 'fail'}{tag}")
    print("\npaper metrics (mean over retained pairs):")
    print("  arm                    S       P       C       D")
    for arm in arms:
        metric = paper_metric_means[arm]
        print(
            f"  {arm:<20} "
            f"{metric['S'] * 100:6.1f}% "
            f"{metric['P'] * 100:6.1f}% "
            f"{metric['C']:7.1f} "
            f"{metric['D']:7.3f}"
        )
    if args.capability_diagnostic:
        diag_metric = capability_diagnostic["full_information_single_agent"]
        print(
            "  capability floor (one agent, full information): "
            f"S={diag_metric['S'] * 100:.1f}% P={diag_metric['P'] * 100:.1f}%"
        )
    print(f"  machinery : {'OK' if machinery_ok else 'BROKEN'} "
          f"(skills={len(bank)}, rounds={len(rounds_log)})")
    print(f"  banks     : {manifest_path} "
          f"({len(skill_bank_manifest['snapshots'])} snapshots)")
    if stable_rounds_ok is not None:
        print(f"  rounds stability (last 3 > all curve baselines): "
              f"{'OK' if stable_rounds_ok else 'NOT MET'}")
    print(f"  report    : {path}")
    print(
        "\nVERDICT: "
        + (
            "PASS -- evolved beats all primary baselines on held-out Silo"
            if verifier_passed
            else "FAIL -- not verified against all primary baselines"
        )
    )
    return 0 if verifier_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
