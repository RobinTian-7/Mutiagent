"""CF single-structure verified-lineage training + one-shot TEST.

The SFTBank ``card_train.py --lineage structure`` flow, run against this
repository's Count Frequency protocol machinery:

    per round: mint a challenger phase program from the incumbent + the
    last duels' answer-free autopsies -> FREEZE it -> duel both artifacts
    on a tier-balanced case envelope (same frozen seed) -> majority
    per-case votes decide, quality before cost -> a stage-1 win must be
    confirmed on fresh disjoint review cases -> only then does the
    challenger enter the lineage as incumbent.

    after all rounds: ONE-shot read-only TEST of the final incumbent on the
    frozen holdout, with reference arms (the v1 seed structure and named
    baseline structures) run on the same cases and seeds.

The information goal defaults to ``sink``: every shard must reach the final
agent, and only that agent's submitted frequency table is scored.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from exp_graph.sft_lineage.cf_cases import (
    CFCase,
    build_case_bank,
    group_by_tier,
    parse_tier_specs,
    split_case_bank,
    task_view,
)
from exp_graph.sft_lineage.cf_executor import evaluate_program_on_cases
from exp_graph.sft_lineage.cf_structures import (
    CF_PHASE_VOCABULARY,
    MAX_COMPILED_STEPS,
    MAX_PHASES,
    SEED_STRUCTURES,
    fake_design,
    seed_program,
    validate_cf_design,
)
from exp_graph.sft_lineage.law import (
    CARD_SEED_BASE,
    DEFAULT_MAX_COST_INFLATION,
    TEST_SEED_BASE,
    LineageBank,
    TournamentLog,
    canonical_json,
    envelope_cases,
    envelope_cost_ratio,
    mint_task_sequence,
    parse_json_reply,
    retire_round_dir,
    review_cases,
    review_verdict,
    round_status,
    round_verdict,
    seed_vote,
    structure_diff,
    summarize_rows,
)

# Paid-call arming discipline: a real-provider campaign must be armed
# explicitly, so a resumed shell or a copy-pasted command cannot spend by
# accident.
PAID_MARKER_ENV = "CF_SFT_PAID_CALLS_APPROVED"
PAID_MARKER_VALUE = "yes"


def _structure_mint_prompt(
    *,
    view: dict[str, Any],
    incumbent_program: dict[str, Any],
    autopsies: list[dict[str, Any]],
    goal: str,
) -> str:
    """Task-informed, insight-informed mint of the NEXT frozen structure.

    The randomness all lives here, BEFORE measurement: whatever this call
    proposes is frozen and dueled as-is, so the verdict is always true of
    the artifact itself.
    """

    lessons = (
        "RECENT DUELS — each entry is a change that was already TRIED "
        "against an incumbent and judged. `changed` lists exactly what that "
        "attempt altered, `verdict`/`per_task` how it fared (dS = quality "
        "delta, dC = cost delta, negative dC is cheaper). Do not re-propose "
        "a change that already lost; do build on what won:\n"
        + json.dumps(autopsies, sort_keys=True)[:1800]
        + "\n\n"
        if autopsies
        else ""
    )
    return (
        "You are evolving ONE frozen multi-agent communication structure "
        "through verified duels. Design the NEXT version as a full phase "
        "sequence.\n\n"
        f"TASK you are optimizing for right now (difficulty tier "
        f"{view['tier']}; {view['n_agents']} agents; the statement below is "
        "what each agent also sees; you are never shown private data or "
        "answers):\n"
        f"{view['task_statement']}\n\n"
        "CURRENT INCUMBENT STRUCTURE (phases JSON):\n"
        f"{json.dumps(incumbent_program.get('phases'), indent=1)[:1800]}\n\n"
        f"{lessons}"
        "Your design will be FROZEN and dueled against the incumbent on "
        "THIS task AND one task from each other difficulty tier — a design "
        "over-fitted to this task loses the away games.\n\n"
        f"PHASE VOCABULARY:\n{CF_PHASE_VOCABULARY}\n\n"
        f"Bounds: at most {MAX_PHASES} phases, compiled schedule at most "
        f"{MAX_COMPILED_STEPS} steps, information goal {goal!r}. The merge "
        "operator is an imperfect LLM: premix buys error-correcting "
        "redundancy at token cost, gather fan-in and depth trade off merge "
        "risk against rounds. Quality is judged first, cost breaks ties.\n"
        "Reply with EXACTLY one JSON object: "
        "{\"phases\": [<PHASE>, ...], \"rationale\": \"<=200 chars\"}"
    )


def _plan_and_validate(
    *,
    planner_client: Any,
    planner_model: str,
    prompt: str,
    goal: str,
    n_agents: int,
) -> tuple[dict[str, Any], str]:
    """One planner call -> validated CF program, with ONE bounded repair.

    The repair happens strictly BEFORE any paid execution, mirroring the
    bounded JSON retries the runner performs inside arms.
    """

    response = planner_client.complete(
        prompt, model_name=planner_model, temperature=0.0
    )
    payload = parse_json_reply(response.text)
    rationale = str(payload.get("rationale") or "")[:200]
    try:
        program = validate_cf_design(
            payload.get("phases"), information_goal=goal, n_agents=n_agents
        )
    except Exception as design_err:  # noqa: BLE001 - one repair, then honest
        print(
            f"[cf-cards] design invalid, one repair attempt: "
            f"{str(design_err)[:160]}",
            flush=True,
        )
        repair = planner_client.complete(
            prompt
            + "\n\nYour previous JSON failed validation:\n"
            + str(design_err)[:600]
            + "\nResend the SAME JSON contract with the problem fixed.",
            model_name=planner_model,
            temperature=0.0,
        )
        payload = parse_json_reply(repair.text)
        rationale = str(payload.get("rationale") or "")[:200]
        program = validate_cf_design(
            payload.get("phases"), information_goal=goal, n_agents=n_agents
        )
    return program, rationale


def _resolve_modes(args: argparse.Namespace) -> tuple[str, str]:
    """(merge_mode, init_mode) under the auto law of the CF experiments:
    offline campaigns run the perfect deterministic operators; real
    campaigns default LLM init for LLM merges."""

    if args.llm == "fake":
        return "deterministic", "deterministic"
    merge_mode = args.merge_mode
    if args.init_mode != "auto":
        return merge_mode, args.init_mode
    init_mode = (
        "deterministic" if merge_mode == "deterministic" else "llm_local_solve"
    )
    return merge_mode, init_mode


def run_single_structure_training(args: argparse.Namespace) -> dict[str, Any]:
    """Single-structure verified lineage over the CF case bank."""

    started = time.monotonic()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    if args.llm == "openai":
        if os.environ.get(PAID_MARKER_ENV) != PAID_MARKER_VALUE:
            raise RuntimeError(
                "PAID_CALLS_NOT_AUTHORIZED: --llm openai requires "
                f"{PAID_MARKER_ENV}={PAID_MARKER_VALUE!r}"
            )
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for --llm openai")
        os.environ.setdefault("OPENAI_TIMEOUT", str(args.request_timeout))

    bank = build_case_bank(
        cases_per_tier=args.cases_per_tier,
        tier_specs=parse_tier_specs(args.tier_spec),
    )
    train_pool, test_case_ids = split_case_bank(
        bank, test_count=args.test_cases
    )
    explicit = [
        c.strip()
        for c in str(args.train_cases or "").split(",")
        if c.strip()
    ]
    if explicit:
        unknown = [c for c in explicit if c not in bank]
        if unknown:
            raise ValueError(f"--train-cases names unknown cases: {unknown}")
        train_pool = list(dict.fromkeys(explicit))
        pulled = [c for c in test_case_ids if c in set(train_pool)]
        test_case_ids = tuple(
            c for c in test_case_ids if c not in set(train_pool)
        )
        print(
            f"[cf-cards] explicit train pool ({len(train_pool)} cases); "
            f"TEST holdout shrunk to {len(test_case_ids)} "
            f"(removed {pulled} — trained-on, cannot be tested)",
            flush=True,
        )
    by_tier, tier_order = group_by_tier(bank, train_pool)
    task_sequence = mint_task_sequence(by_tier, tier_order)

    log = TournamentLog(root / "events.jsonl")
    goal = args.goal
    merge_mode, init_mode = _resolve_modes(args)
    seed_name = str(args.single_card).strip().lower()
    lineage = LineageBank(root / "lineage.json")
    lineage.seed(
        origin=f"seed:{seed_name}",
        title=seed_name.replace("_", " ").title(),
        program=seed_program(
            seed_name, n_agents=args.agents, information_goal=goal
        ),
    )
    log.append(
        "lineage_open",
        {
            "origin": f"seed:{seed_name}",
            "mode": "structure",
            "goal": goal,
            "incumbent": lineage.state["incumbent"],
            "versions": len(lineage.state["versions"]),
        },
    )

    worker_client: Any | None = None
    planner_client: Any | None = None
    if args.llm == "openai":
        from exp_graph.llm.openai_client import OpenAIChatClient

        worker_client = OpenAIChatClient(
            reasoning_effort=args.reasoning_effort
        )
        planner_effort = args.planner_effort or args.reasoning_effort
        planner_client = (
            worker_client
            if planner_effort == args.reasoning_effort
            else OpenAIChatClient(reasoning_effort=planner_effort)
        )
    planner_model = args.planner_model or args.model

    def run_envelope(
        program: dict[str, Any],
        case_ids: tuple[str, ...],
        seed: int,
        label: str,
    ) -> list[dict[str, Any]]:
        """One frozen artifact over the whole envelope, cases in parallel."""

        return evaluate_program_on_cases(
            program=program,
            cases=tuple(bank[c] for c in case_ids),
            seeds=(seed,) * len(case_ids),
            arm_label=label,
            n_agents=args.agents,
            model_name=args.model,
            merge_mode=merge_mode,
            init_mode=init_mode,
            llm_provider=args.llm,
            worker_client=worker_client,
            allow_deterministic_repair=bool(args.allow_deterministic_repair),
            json_retry_attempts=args.json_retry_attempts,
            max_parallel_cases=min(len(case_ids), args.parallel_tests),
            max_parallel_agents=args.max_parallel_agents,
            progress=lambda text: print(f"[cf-cards] {text}", flush=True),
        )

    def last_autopsies(
        before_round: int, *, limit: int
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for prior in range(before_round - 1, -1, -1):
            if len(found) >= limit:
                break
            path = root / f"round-{prior}" / "round-report.json"
            if not path.exists():
                continue
            try:
                report = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if report.get("status") == "completed" and report.get("autopsy"):
                found.append(report["autopsy"])
        return found

    def mint_challenger(
        round_index: int, view: dict[str, Any], incumbent: dict[str, Any]
    ) -> dict[str, Any]:
        if args.llm == "fake":
            return validate_cf_design(
                fake_design(round_index + 1, args.agents),
                information_goal=goal,
                n_agents=args.agents,
            )
        program, _rationale = _plan_and_validate(
            planner_client=planner_client,
            planner_model=planner_model,
            prompt=_structure_mint_prompt(
                view=view,
                incumbent_program=incumbent["program"],
                autopsies=last_autopsies(round_index, limit=3),
                goal=goal,
            ),
            goal=goal,
            n_agents=args.agents,
        )
        return program

    def structure_duel(
        *,
        round_index: int,
        case_id: str,
        tier: str,
        view: dict[str, Any],
        incumbent: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        """One frozen-artifact duel round: mint -> freeze -> envelope."""

        incumbent_program = incumbent["program"]
        challenger_program = mint_challenger(round_index, view, incumbent)
        inc_json = canonical_json(incumbent_program)
        ch_json = canonical_json(challenger_program)
        identical = inc_json == ch_json
        cases = envelope_cases(
            case_id, round_index, by_tier, tier_order,
            width=args.envelope_cases,
        )
        if identical:
            votes = ["tie"] * len(cases)
            rows_inc: list[dict[str, Any]] = []
            rows_ch: list[dict[str, Any]] = []
        else:
            rows_inc = run_envelope(
                incumbent_program, cases, CARD_SEED_BASE,
                f"lineage:v{incumbent['version']}",
            )
            rows_ch = run_envelope(
                challenger_program, cases, CARD_SEED_BASE, "lineage:ch"
            )
            votes = [
                seed_vote(ch, inc) for ch, inc in zip(rows_ch, rows_inc)
            ]
        cost_ratio = envelope_cost_ratio(rows_ch, rows_inc)
        stage1 = round_verdict(
            votes,
            cost_ratio=cost_ratio,
            max_cost_inflation=args.max_cost_inflation,
        )
        # Second stage: a stage-1 win is a nomination, not a promotion.  It
        # must hold up on cases the envelope never touched, or the lineage
        # inherits whatever the first draw got lucky on.
        verdict = stage1
        review: dict[str, Any] | None = None
        if stage1 == "win" and args.review_cases > 0:
            fresh = review_cases(
                cases, round_index, by_tier, tier_order,
                width=args.review_cases,
            )
            if not fresh:
                review = {"skipped": "no disjoint cases available"}
            else:
                rev_inc = run_envelope(
                    incumbent_program, fresh, CARD_SEED_BASE,
                    f"review:v{incumbent['version']}",
                )
                rev_ch = run_envelope(
                    challenger_program, fresh, CARD_SEED_BASE, "review:ch"
                )
                rev_votes = [
                    seed_vote(ch, inc) for ch, inc in zip(rev_ch, rev_inc)
                ]
                confirmed, reason = review_verdict(
                    rev_votes,
                    # Review what stage 1 actually won ON: a cost-decided
                    # win must not be asked to reproduce a quality claim it
                    # never made.
                    require_quality_evidence=(
                        votes.count("quality_win")
                        > votes.count("quality_loss")
                    ),
                )
                review = {
                    "cases": list(fresh),
                    "votes": rev_votes,
                    "confirmed": confirmed,
                    "reason": reason,
                    "cost_ratio": envelope_cost_ratio(rev_ch, rev_inc),
                    "incumbent_rows": rev_inc,
                    "challenger_rows": rev_ch,
                }
                if not confirmed:
                    verdict = "neutral"
                print(
                    f"[cf-cards] review {list(fresh)} -> "
                    f"{'CONFIRMED' if confirmed else 'REJECTED'} ({reason}) "
                    f"votes={rev_votes}",
                    flush=True,
                )
        version = lineage.record_duel(
            round_index=round_index,
            challenger_program=json.loads(ch_json),
            verdict=verdict,
            votes=votes,
        )
        per_task = []
        for index, envelope_case in enumerate(cases):
            entry = {"tier": bank[envelope_case].tier, "vote": votes[index]}
            if (
                rows_ch
                and not rows_ch[index].get("infra")
                and not rows_inc[index].get("infra")
            ):
                entry["dS"] = round(
                    rows_ch[index]["S"] - rows_inc[index]["S"], 4
                )
                entry["dC"] = round(
                    rows_ch[index]["C"] - rows_inc[index]["C"], 1
                )
            per_task.append(entry)
        autopsy = {
            "round": round_index,
            "mode": "structure",
            "mint_tier": tier,
            "verdict": verdict,
            "promoted": verdict == "win",
            "votes": votes,
            "identical_design": identical,
            "cost_ratio": (
                round(cost_ratio, 4) if cost_ratio is not None else None
            ),
            "per_task": per_task,
            "incumbent_kinds": [
                p["kind"] for p in incumbent_program["phases"]
            ],
            "challenger_kinds": [
                p["kind"] for p in challenger_program["phases"]
            ],
            "changed": structure_diff(
                incumbent_program["phases"],
                challenger_program["phases"],
            ),
            "stage1_verdict": stage1,
            "review": (
                {
                    "confirmed": review.get("confirmed"),
                    "reason": review.get("reason"),
                    "votes": review.get("votes"),
                }
                if review
                else None
            ),
        }
        report.update(
            {
                "status": "completed",
                "verdict": verdict,
                "challenger_version": version,
                "promoted": verdict == "win",
                "votes": votes,
                "stage1_verdict": stage1,
                "review": review,
                "envelope_cases": list(cases),
                "identical_design": identical,
                "cost_ratio": (
                    round(cost_ratio, 4) if cost_ratio is not None else None
                ),
                "incumbent_phases": incumbent_program["phases"],
                "challenger_phases": challenger_program["phases"],
                "incumbent_rows": rows_inc,
                "challenger_rows": rows_ch,
                "autopsy": autopsy,
            }
        )
        log.append(
            "duel",
            {
                "round": round_index,
                "mode": "structure",
                "case_tier": tier,
                "incumbent": incumbent["version"],
                "challenger": version,
                "verdict": verdict,
                "votes": votes,
                "promoted": verdict == "win",
            },
        )
        print(
            f"[cf-cards] duel round {round_index} {case_id}: "
            f"v{version} vs v{incumbent['version']} -> {verdict}"
            f"{' PROMOTED' if verdict == 'win' else ''} (votes={votes}"
            + (f", cost x{cost_ratio:.2f}" if cost_ratio is not None else "")
            + ")",
            flush=True,
        )

    for round_index in range(args.rounds):
        if args.resume:
            status = round_status(root, round_index)
            if status == "completed":
                print(
                    f"[cf-cards] round {round_index}: checkpoint hit, "
                    "skipping",
                    flush=True,
                )
                log.append(
                    "round_skipped",
                    {"round": round_index, "reason": "checkpoint_completed"},
                )
                continue
            if status is not None:
                retire_round_dir(root, round_index, log)

        case_id = task_sequence[round_index % len(task_sequence)]
        tier = bank[case_id].tier
        view = task_view(bank[case_id], n_agents=args.agents, goal=goal)
        incumbent = lineage.incumbent()
        report: dict[str, Any] = {
            "round": round_index,
            "case_id": case_id,
            "tier": tier,
            "incumbent_version": incumbent["version"],
            "status": "failed",
        }
        round_dir = root / f"round-{round_index}"
        round_dir.mkdir(parents=True, exist_ok=True)
        try:
            structure_duel(
                round_index=round_index,
                case_id=case_id,
                tier=tier,
                view=view,
                incumbent=incumbent,
                report=report,
            )
        except Exception as exc:  # noqa: BLE001 - round failure is a result
            report["error"] = f"{type(exc).__name__}: {exc}"
            log.append(
                "round_failed",
                {"round": round_index, "error": report["error"][:200]},
            )
            print(
                f"[cf-cards] round {round_index} FAILED: {report['error']}",
                flush=True,
            )
        (round_dir / "round-report.json").write_text(
            json.dumps(report, indent=2, default=str)
        )

    # ---- frozen one-shot TEST with the final incumbent ------------------
    test_report: dict[str, Any] | None = None
    if args.run_test:
        lineage_bytes_before = (root / "lineage.json").read_bytes()
        incumbent = lineage.incumbent()

        def run_test_arm(
            program: dict[str, Any], label: str
        ) -> list[dict[str, Any]]:
            return evaluate_program_on_cases(
                program=program,
                cases=tuple(bank[c] for c in test_case_ids),
                seeds=tuple(
                    TEST_SEED_BASE + index
                    for index in range(len(test_case_ids))
                ),
                arm_label=label,
                n_agents=args.agents,
                model_name=args.model,
                merge_mode=merge_mode,
                init_mode=init_mode,
                llm_provider=args.llm,
                worker_client=worker_client,
                allow_deterministic_repair=bool(
                    args.allow_deterministic_repair
                ),
                json_retry_attempts=args.json_retry_attempts,
                max_parallel_cases=min(
                    len(test_case_ids), args.parallel_tests
                ),
                max_parallel_agents=args.max_parallel_agents,
                progress=lambda text: print(
                    f"[cf-cards] TEST {text}", flush=True
                ),
            )

        test_report = {
            "incumbent_version": incumbent["version"],
            **summarize_rows(
                run_test_arm(incumbent["program"], "lineagetest")
            ),
        }
        # Reference arms on the SAME frozen cases and seeds.  They never
        # feed back into anything — the lineage is already sealed — they
        # exist so the winner's number has something to be read against:
        # v1 answers "what did the rounds buy", the named structures answer
        # "where does this sit against the fixed transports".
        baselines: dict[str, Any] = {}
        if args.test_baselines:
            names = [
                name.strip()
                for name in str(args.test_baselines).split(",")
                if name.strip()
            ]
            for name in names:
                if name == "v1":
                    seed_version = lineage.state["versions"]["1"]
                    if seed_version["version"] == incumbent["version"]:
                        continue
                    baselines["lineage:v1_seed"] = summarize_rows(
                        run_test_arm(
                            seed_version["program"], "baseline:v1"
                        )
                    )
                    continue
                baselines[f"structure:{name}"] = summarize_rows(
                    run_test_arm(
                        seed_program(
                            name,
                            n_agents=args.agents,
                            information_goal=goal,
                        ),
                        f"baseline:{name}",
                    )
                )
            test_report["baselines"] = baselines

        if (root / "lineage.json").read_bytes() != lineage_bytes_before:
            raise RuntimeError(
                "TEST mutated the lineage — read-only law violated"
            )
        log.append("test_sealed", {"aggregate": test_report["aggregate"]})

    campaign_report = {
        "mode": "single_structure",
        "config": {
            "single_card": seed_name,
            "lineage": "structure",
            "rounds": args.rounds,
            "goal": goal,
            "agents": args.agents,
            "envelope_cases": args.envelope_cases,
            "review_cases": args.review_cases,
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "planner_model": planner_model,
            "planner_effort": args.planner_effort or args.reasoning_effort,
            "llm": args.llm,
            "merge_mode": merge_mode,
            "init_mode": init_mode,
            "allow_deterministic_repair": bool(
                args.allow_deterministic_repair
            ),
            "cases_per_tier": args.cases_per_tier,
            "test_case_ids": list(test_case_ids),
        },
        "lineage": lineage.state,
        "test": test_report,
        "wall_time_s": round(time.monotonic() - started, 1),
    }
    (root / "card_train_report.json").write_text(
        json.dumps(campaign_report, indent=2, default=str)
    )
    print(
        f"[cf-cards] report: {root / 'card_train_report.json'}", flush=True
    )
    return campaign_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", choices=("fake", "openai"), default="fake")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument(
        "--reasoning-effort",
        default="minimal",
        help=(
            "reasoning effort for gpt-5-family workers; the CF merge "
            "operator is mechanical, so the campaign default is 'minimal'"
        ),
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="model for structure-mint calls (default: --model)",
    )
    parser.add_argument(
        "--planner-effort",
        default=None,
        help="reasoning effort for the planner (default: --reasoning-effort)",
    )
    parser.add_argument(
        "--goal",
        choices=("sink", "all_agents"),
        default="sink",
        help=(
            "information goal: 'sink' scores ONLY the final agent's "
            "submitted table (aggregation), 'all_agents' keeps the legacy "
            "consensus law"
        ),
    )
    parser.add_argument("--agents", type=int, default=8)
    parser.add_argument(
        "--single-card",
        default="one_peer_star_sink",
        help=(
            "seed structure for the verified lineage; one of: "
            + ", ".join(sorted(SEED_STRUCTURES))
        ),
    )
    parser.add_argument(
        "--lineage",
        choices=("structure",),
        default="structure",
        help=(
            "kept for interface parity with the SFTBank pilot; only the "
            "frozen-artifact 'structure' substrate is transplanted here"
        ),
    )
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument(
        "--envelope-cases",
        type=int,
        default=6,
        help=(
            "duel envelope width; filled tier-balanced from the mint case, "
            "so 6 means two cases per difficulty tier"
        ),
    )
    parser.add_argument(
        "--review-cases",
        type=int,
        default=2,
        help=(
            "second-stage confirmation width: a challenger that wins its "
            "duel must also hold up on this many FRESH cases (disjoint "
            "from the envelope, hardest tiers first). 0 disables"
        ),
    )
    parser.add_argument(
        "--max-cost-inflation",
        type=float,
        default=DEFAULT_MAX_COST_INFLATION,
        help=(
            "optional cap on (challenger spend / incumbent spend) for a "
            "QUALITY win to promote; disabled by default"
        ),
    )
    parser.add_argument(
        "--train-cases",
        default=None,
        help=(
            "explicit comma-separated training pool (mint + duel "
            "envelope). Any listed case that is in the TEST holdout is "
            "dropped from TEST — trained-on cases can't be tested"
        ),
    )
    parser.add_argument("--cases-per-tier", type=int, default=6)
    parser.add_argument(
        "--tier-spec",
        default=None,
        help=(
            "JSON tier override, e.g. "
            '\'{"I": [400, 1, 40], "II": [2000, 1, 300]}\' '
            "as {tier: [array_size, value_min, value_max]}"
        ),
    )
    parser.add_argument("--test-cases", type=int, default=6)
    parser.add_argument(
        "--test-baselines",
        default="v1,star_sink,tree_sink,static_exponential_sink",
        help=(
            "reference arms run on the frozen TEST cases alongside the "
            "winner: 'v1' is the lineage's own seed structure, the rest "
            "are named seed structures. Empty disables"
        ),
    )
    parser.add_argument(
        "--no-test",
        dest="run_test",
        action="store_false",
        default=True,
        help="skip the final one-shot TEST over the holdout",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        default=True,
    )
    parser.add_argument(
        "--merge-mode",
        choices=("llm_full_merge", "llm_belief_merge", "deterministic"),
        default="llm_full_merge",
        help="worker merge operator for --llm openai (fake is deterministic)",
    )
    parser.add_argument(
        "--init-mode",
        choices=("auto", "deterministic", "llm_local_solve"),
        default="auto",
    )
    parser.add_argument(
        "--allow-deterministic-repair",
        action="store_true",
        help=(
            "let invalid LLM merges fall back to the deterministic merge; "
            "OFF by default so duels measure the model's real merge "
            "capability"
        ),
    )
    parser.add_argument("--json-retry-attempts", type=int, default=2)
    parser.add_argument("--parallel-tests", type=int, default=3)
    parser.add_argument("--max-parallel-agents", type=int, default=4)
    parser.add_argument("--request-timeout", type=float, default=1800.0)
    parser.add_argument("--root", default="runs/cf_sft_v5_cards")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_single_structure_training(args)


if __name__ == "__main__":
    main()
