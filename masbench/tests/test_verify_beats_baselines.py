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

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from verify_beats_baselines import (  # noqa: E402
    FIXED_ARM_PREFIX,
    _expand_fixed_baselines,
    _pick_fixed_best,
    _stable_rounds,
    _verdict,
    main,
)

DATA = Path(__file__).parent / "data"


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
    assert set(report["arm_means"]) == {"evolved", "select", "graphgen", "fixed"}
    assert report["rounds"] == 2
    assert len(report["rounds_log"]) == 2
    assert report["fixed_best_topology"]
