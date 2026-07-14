"""Phase-2 frozen judge: evolved (after R evolution rounds) must beat EVERY
baseline {select, graphgen, fixed_best_on_train} in the SAME paired protocol.

Pure verdict/selection/stability logic is unit-tested; the end-to-end offline
(fake-LLM) run is the machinery smoke and MUST end "machinery OK" + exit 1
(offline Silo is topology-invariant -> all arms tie -> no improvement).
Once this file and the script are green, the script's judgment logic is FROZEN.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from exp_graph.mas.schemas import SkillCard  # noqa: E402
from exp_graph.mas.skill_payloads import (  # noqa: E402
    python_worker_contract_from_skill,
)

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import verify_beats_baselines as verifier  # noqa: E402
from verify_beats_baselines import (  # noqa: E402
    FIXED_ARM_PREFIX,
    _load_deployed_round,
    _expand_fixed_baselines,
    _metrics_from_score,
    _pick_fixed_best,
    _require_complete_submissions,
    _stable_rounds,
    _verdict,
    main,
    parse_args,
)

DATA = Path(__file__).parent / "data"


def test_parser_accepts_explicit_disjoint_validation_cases(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_beats_baselines.py",
            "--train-cases", "II-11", "III-21",
            "--val-cases", "II-13", "III-23",
            "--test-cases", "II-12", "III-22",
        ],
    )

    args = parse_args()

    assert args.train_cases == ["II-11", "III-21"]
    assert args.val_cases == ["II-13", "III-23"]
    assert args.test_cases == ["II-12", "III-22"]


def test_parser_accepts_strict_submissions_and_resume(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_beats_baselines.py",
            "--require-all-submissions",
            "--final-submission-retries",
            "4",
            "--llm-timeout-attempts",
            "5",
            "--require-complete-runs",
            "--resume",
        ],
    )

    args = parse_args()

    assert args.require_all_submissions is True
    assert args.final_submission_retries == 4
    assert args.llm_timeout_attempts == 5
    assert args.require_complete_runs is True
    assert args.resume is True


def test_required_submission_check_rejects_null_slots() -> None:
    metrics = {
        "per_agent_submissions": [
            {"agent_id": 0, "answer": 3},
            {"agent_id": 1, "answer": None},
        ]
    }

    with pytest.raises(ValueError, match=r"agents \[1\]"):
        _require_complete_submissions(metrics, n_agents=2, arm="fixed")


def test_load_deployed_round_restores_bank_motif_and_log(tmp_path) -> None:
    round_dir = tmp_path / "round_01"
    (round_dir / "deployed").mkdir(parents=True)
    (round_dir / "deployed" / "bank.json").write_text(
        json.dumps({"n_skills": 0, "skill_ids": [], "skills": []})
    )
    (round_dir / "deployed_motif_stats.json").write_text(
        json.dumps({"peer_exchange": {"mean": 0.5}})
    )
    (round_dir / "evolution_summary.json").write_text(
        json.dumps(
            {
                "skill_bank_size_after": 0,
                "gate": {"accepted": False},
                "skill_ids_after": [],
                "rejected_skill_ids": [],
                "hot_start": {"enabled": False},
            }
        )
    )

    bank, motif, logs = _load_deployed_round(tmp_path, 1)

    assert len(bank) == 0
    assert motif == {"peer_exchange": {"mean": 0.5}}
    assert logs == [
        {
            "round": 1,
            "n_skills": 0,
            "gate": {"accepted": False},
            "skill_ids": [],
            "rejected_skill_ids": [],
            "hot_start": {"enabled": False},
        }
    ]


def test_resume_skips_completed_evolution_rounds(
    tmp_path, capsys, monkeypatch
) -> None:
    argv = [
        "verify_beats_baselines.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "1", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "--baselines", "fixed",
        "--fixed-topologies", "chain",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 1
    capsys.readouterr()
    checkpoint = json.loads((tmp_path / "run_checkpoint.json").read_text())
    assert checkpoint["status"] == "complete"
    assert checkpoint["completed_rounds"] == 1

    def _unexpected_evolution(*args, **kwargs):
        raise AssertionError("completed evolution round should be resumed")

    monkeypatch.setattr(verifier, "run_evolution", _unexpected_evolution)
    monkeypatch.setattr(sys, "argv", [*argv, "--resume"])
    assert main() == 1
    assert "resume: loading completed evolution rounds 1..1" in capsys.readouterr().out


def test_pick_fixed_best_argmax_with_lexicographic_tiebreak():
    rows = [
        {"topology": "tree", "exact": 0.0},
        {"topology": "tree", "exact": 1.0},
        {"topology": "mesh_star", "exact": 1.0},
        {"topology": "mesh_star", "exact": 1.0},
        {"topology": "chain", "exact": 1.0},
        {"topology": "chain", "exact": 1.0},
    ]
    # mesh_star and chain tie at 1.0 -> lexicographic tiebreak picks chain
    assert _pick_fixed_best(rows) == "chain"


def test_honest_verifier_marks_returned_coverage_failure_as_algorithmic() -> None:
    score = SimpleNamespace(
        success=False,
        partial=0.0,
        n_messages=3,
        n_model_calls=4,
        tokens=50,
        extra={
            "paper_S": 0.0,
            "paper_P": 0.0,
            "paper_C": 12.5,
            "paper_D": 0.5,
            "min_information_coverage": 0.5,
            "per_agent_submissions": [
                {"agent_id": 0, "answer": None},
                {"agent_id": 1, "answer": 3},
            ],
        },
    )

    metrics = _metrics_from_score(score, honest_failures=True)

    assert metrics["failure_class"] == "algorithm_failure"
    assert metrics["failure_stage"] == "coverage"
    assert metrics["C"] == pytest.approx(12.5)
    assert metrics["D"] == pytest.approx(0.5)


def test_verdict_requires_beating_every_baseline():
    # 10 pairs: evolved solves 8; select solves 2, graphgen 2, fixed 8 (tie).
    pairs = []
    for k in range(10):
        pairs.append({
            "case_id": "X", "seed": k,
            "evolved": 1.0 if k < 8 else 0.0,
            "select": 1.0 if k < 2 else 0.0,
            "graphgen": 1.0 if k < 2 else 0.0,
            "fixed": 1.0 if k < 8 else 0.0,
        })
    verdict = _verdict(pairs, delta_min=0.05, win_margin=2)
    assert verdict["per_baseline"]["select"]["passed"] is True
    assert verdict["per_baseline"]["graphgen"]["passed"] is True
    assert verdict["per_baseline"]["fixed"]["passed"] is False  # tie, no margin
    assert verdict["passed"] is False  # must beat ALL baselines


def test_verdict_passes_when_all_beaten():
    pairs = [
        {"case_id": "X", "seed": k,
         "evolved": 1.0 if k < 7 else 0.0,
         "select": 1.0 if k < 3 else 0.0,
         "graphgen": 0.0,
         "fixed": 1.0 if k < 4 else 0.0}
        for k in range(10)
    ]
    verdict = _verdict(pairs, delta_min=0.05, win_margin=2)
    assert verdict["passed"] is True
    assert verdict["per_baseline"]["fixed"]["delta"] == pytest.approx(0.3)


def test_stable_rounds_needs_last_k_above_all_baselines():
    curves = {
        "baselines": {"select": 0.4, "graphgen": 0.3},
        "rounds_curve": [
            {"round": 0, "score": 0.2},
            {"round": 1, "score": 0.5},
            {"round": 2, "score": 0.35},  # dips below select
            {"round": 3, "score": 0.5},
            {"round": 4, "score": 0.6},
        ],
    }
    assert _stable_rounds(curves, k=3) is False  # round 2 in last-3 window? last3 = r2,r3,r4 -> r2 below
    curves["rounds_curve"][2]["score"] = 0.45
    assert _stable_rounds(curves, k=3) is True


def test_expand_fixed_baselines_off_is_identity():
    baselines = ("p2p", "broadcast", "sfs", "pycodegen", "fixed")
    topos = ["one_peer_exponential_dag", "static_exponential"]
    # Flag off -> unchanged, no supplementary arm (behavior-preserving default).
    out, supp = _expand_fixed_baselines(baselines, topos, per_topology=False)
    assert out == baselines
    assert supp == frozenset()


def test_expand_fixed_baselines_promotes_each_topology_and_keeps_aggregate():
    baselines = ("p2p", "broadcast", "sfs", "pycodegen", "fixed")
    topos = ["one_peer_exponential_dag", "static_exponential"]
    out, supp = _expand_fixed_baselines(baselines, topos, per_topology=True)
    # Each fixed topology becomes its OWN independent paired arm; the aggregate
    # fixed_best_on_train is retained at the end as a supplementary arm.
    assert out == (
        "p2p",
        "broadcast",
        "sfs",
        "pycodegen",
        f"{FIXED_ARM_PREFIX}one_peer_exponential_dag",
        f"{FIXED_ARM_PREFIX}static_exponential",
        "fixed",
    )
    assert supp == frozenset({"fixed"})
    # The two named transports are now distinct, gate-eligible baselines while
    # 'fixed' (best-on-train) is reported-only.
    primary = tuple(b for b in out if b not in supp)
    assert primary == (
        "p2p",
        "broadcast",
        "sfs",
        "pycodegen",
        f"{FIXED_ARM_PREFIX}one_peer_exponential_dag",
        f"{FIXED_ARM_PREFIX}static_exponential",
    )


def test_expand_fixed_baselines_noop_without_fixed_or_topologies():
    # No 'fixed' baseline requested -> nothing to expand even with the flag on.
    out, supp = _expand_fixed_baselines(("p2p", "sfs"), ["chain"], per_topology=True)
    assert out == ("p2p", "sfs") and supp == frozenset()
    # 'fixed' requested but no topologies -> unchanged.
    out2, supp2 = _expand_fixed_baselines(("fixed",), [], per_topology=True)
    assert out2 == ("fixed",) and supp2 == frozenset()


def test_offline_fake_run_per_topology_fixed_arms(tmp_path, capsys, monkeypatch):
    """Per-topology fixed arms: two independent paired arms + supplementary
    fixed_best, offline. Machinery OK, exit 1 (topology-invariant fake Silo)."""
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    argv = [
        "verify_beats_baselines.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "2", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "12",
        "--baselines", "fixed",
        "--fixed-topologies", "one_peer_exponential_dag", "static_exponential",
        "--fixed-per-topology-arms",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    code = main()
    out = capsys.readouterr().out
    assert code == 1, "offline arms tie -> no verified win"
    assert "machinery" in out and "OK" in out
    report = json.loads((tmp_path / "verify_beats_baselines_n2.json").read_text())
    assert report["passed"] is False
    # Two named fixed topologies are independent paired arms; aggregate fixed
    # is retained (supplementary).
    assert set(report["arm_means"]) == {
        "evolved",
        f"{FIXED_ARM_PREFIX}one_peer_exponential_dag",
        f"{FIXED_ARM_PREFIX}static_exponential",
        "fixed",
    }
    assert report["fixed_per_topology_arms"] is True
    assert report["supplementary_baselines"] == ["fixed"]
    assert f"{FIXED_ARM_PREFIX}one_peer_exponential_dag" in report["primary_baselines"]
    assert f"{FIXED_ARM_PREFIX}static_exponential" in report["primary_baselines"]
    assert "fixed" not in report["primary_baselines"]
    # fixed_best_on_train is still selected and reported.
    assert report["fixed_best_topology"] in {
        "one_peer_exponential_dag",
        "static_exponential",
    }
    # Each fixed topology arm carries its own paper metrics in pair_details.
    for detail in report["pair_details"]:
        assert f"{FIXED_ARM_PREFIX}one_peer_exponential_dag" in detail["arms"]
        assert f"{FIXED_ARM_PREFIX}static_exponential" in detail["arms"]


def test_offline_fake_run_machinery_ok_exit_1(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    argv = [
        "verify_beats_baselines.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "2", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "12",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    code = main()
    out = capsys.readouterr().out
    assert code == 1, "offline arms tie -> no verified win"
    assert "machinery" in out and "OK" in out
    report = json.loads((tmp_path / "verify_beats_baselines_n2.json").read_text())
    assert report["passed"] is False
    assert report["failure_policy"] == "legacy_drop"
    assert report["evolution_gate_policy"] == "legacy_non_regression"
    assert report["python_innovation_strategy"] == "mutate_and_fresh"
    assert Path(report["artifact_roots"]["graph_generate"]).parent == tmp_path
    assert Path(report["artifact_roots"]["program_generate"]).parent == tmp_path
    assert Path(report["artifact_roots"]["python_generate"]).parent == tmp_path
    assert set(report["arm_means"]) == {"evolved", "select", "graphgen", "fixed"}
    assert report["rounds"] == 2
    assert len(report["rounds_log"]) == 2
    assert report["fixed_best_topology"]


def test_hot_python_context_marks_verifier_and_manifest_non_clean(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    argv = [
        "verify_beats_baselines.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "1", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "--baselines", "pycodegen",
        "--silo-eval-mode", "all_agents",
        "--evolved-mode", "python_generate",
        "--hot-start",
        "--hot-start-innovation-mode", "python_generate",
        "--python-innovation-strategy", "fresh",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert main() == 1
    capsys.readouterr()
    report = json.loads((tmp_path / "verify_beats_baselines_n2.json").read_text())
    manifest = json.loads(
        (tmp_path / "skill_banks" / "manifest.json").read_text()
    )
    assert report["clean_pythongen"] is False
    assert manifest["clean_pythongen"] is False
    assert report["rounds_log"][0]["hot_start"]["dual_branch"][
        "python_context_exposed"
    ] is True


def test_python_worker_contract_flag_defaults_to_action_json_v1(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    argv = [
        "verify_beats_baselines.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "1", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "--baselines", "pycodegen",
        "--silo-eval-mode", "all_agents",
        "--evolved-mode", "python_generate",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    capsys.readouterr()
    report = json.loads((tmp_path / "verify_beats_baselines_n2.json").read_text())
    manifest = json.loads(
        (tmp_path / "skill_banks" / "manifest.json").read_text()
    )
    assert report["python_worker_contract"] == "action_json_v1"
    assert manifest["python_worker_contract"] == "action_json_v1"


def test_python_worker_contract_flag_selects_message_only_v2_for_every_python_arm(
    tmp_path, capsys, monkeypatch
):
    """Explicitly selecting message_only_v2 must reach every python_generate
    arm: the evolved planner path AND the pycodegen baseline (both build their
    RunConfig from the same ``cfg``/``replace(cfg, ...)`` call in this
    script)."""
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    argv = [
        "verify_beats_baselines.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "1", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "--baselines", "pycodegen",
        "--silo-eval-mode", "all_agents",
        "--evolved-mode", "python_generate",
        "--python-worker-contract", "message_only_v2",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    capsys.readouterr()
    report = json.loads((tmp_path / "verify_beats_baselines_n2.json").read_text())
    manifest = json.loads(
        (tmp_path / "skill_banks" / "manifest.json").read_text()
    )
    assert report["python_worker_contract"] == "message_only_v2"
    assert manifest["python_worker_contract"] == "message_only_v2"
    # The deployed bank's python skills (evolved arm) were retrieved/created
    # under message_only_v2 end to end, from CLI flag through RunConfig into
    # the SkillBank that reaches evaluation.
    final_bank = json.loads(
        (tmp_path / "skill_banks" / "final" / "deployed" / "bank.json").read_text()
    )
    python_skills = [
        SkillCard.model_validate(item)
        for item in final_bank["skills"]
        if item.get("skill_type") == "python_generation_skill"
    ]
    assert python_skills, "expected at least one python skill in the deployed bank"
    for skill in python_skills:
        assert python_worker_contract_from_skill(skill) == "message_only_v2"
