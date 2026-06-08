"""Tests for the engine's graph_generate planner: LLM temporal-DAG planning.

These exercise Plan 4 Task 1: ``RunConfig.planner_mode == "graph_generate"``
routes the engine through ``exp_graph.mas.graph_generation.plan_free_graph`` (the
emperor invents a bespoke temporal communication DAG) and then executes the
generated ``protocol_spec`` through ``ProtocolRunner``. Offline (fake LLM) the
emperor emits deterministic fake DAG candidates that compile to valid specs (or,
on junk, falls back to a fixed operator topology); either way the run must not
crash and must tag ``extra["planner_mode"] == "graph_generate"``.
"""

from __future__ import annotations

from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.cli import main
from masbench.core.config import RunConfig
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance

DATA = Path(__file__).parent / "data"


def _instance(case_id: str):
    adapter = SiloBenchAdapter(DATA)
    return next(adapter.iter_instances(cases=[case_id]))


def test_graphgen_offline_runs_and_falls_back():
    """planner_mode=graph_generate drives I-01 through plan_free_graph offline.

    With ``--llm fake`` the emperor produces deterministic fake DAG candidates
    that compile to valid protocol specs (or falls back to a fixed topology). We
    only assert the run completes and is tagged graph_generate; correctness is
    not asserted because the offline fake path may not converge on the global
    answer for an invented DAG.
    """
    inst = _instance("I-01")
    cfg = RunConfig(
        use_planner=True,
        planner_mode="graph_generate",
        llm_provider="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        n_agents=2,
        objective="accuracy_first",
    )
    score = run_instance(inst, cfg)

    assert isinstance(score, ScoreResult)
    assert score.extra["planner"] is True
    assert score.extra["planner_mode"] == "graph_generate"
    # A generated/compiled DAG carries at least one step; record it for evidence.
    assert score.extra["generated_steps"] >= 1
    assert isinstance(score.extra["topology"], str) and score.extra["topology"]


def test_topology_select_still_default():
    """Default planner_mode keeps the unchanged Plan 3 B topology_select path."""
    inst = _instance("I-01")
    cfg = RunConfig(
        use_planner=True,
        llm_provider="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        n_agents=2,
        objective="balanced",
    )
    score = run_instance(inst, cfg)

    assert isinstance(score, ScoreResult)
    assert score.extra["planner"] is True
    # Default mode is topology_select; absent is also treated as select.
    assert score.extra.get("planner_mode", "topology_select") == "topology_select"
    # Unchanged from Plan 3 B: balanced -> mesh_star converges on I-01 offline.
    assert score.success is True
    assert score.final_answer == "9"


def test_cli_graph_generate_parses_and_runs(tmp_path):
    """A real CLI parse smoke for run + --planner-mode graph_generate exits 0."""
    rc = main(
        [
            "run",
            "--benchmark",
            "silo_bench",
            "--benchmarks-dir",
            str(DATA),
            "--case",
            "I-01",
            "--n-agents",
            "2",
            "--planner",
            "--planner-mode",
            "graph_generate",
            "--llm",
            "fake",
            "--objective",
            "accuracy_first",
        ]
    )
    assert rc == 0
