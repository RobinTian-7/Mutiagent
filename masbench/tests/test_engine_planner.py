"""Tests for the engine's --planner path: QueenBee planner + ProtocolRunner."""

from __future__ import annotations

from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance

DATA = Path(__file__).parent / "data"


def _instance(case_id: str):
    adapter = SiloBenchAdapter(DATA)
    return next(adapter.iter_instances(cases=[case_id]))


def test_planner_path_runs_global_max_offline():
    """planner=True drives I-01 through EmperorPlanner + ProtocolRunner offline.

    Objective "balanced" makes the empty SkillBank fall back to
    ``default_topology_for_objective`` = ``mesh_star``, a topology whose holder
    reaches full coverage so the deterministic associative-reduce (max) converges
    to the correct global answer (9) with no real LLM.
    """
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
    assert score.success is True
    assert score.final_answer == "9"
    assert score.extra["planner"] is True
    assert isinstance(score.extra["topology"], str)
    assert score.extra["topology"]


def test_planner_offmode_still_uses_synchronous():
    """planner=False keeps the unchanged SynchronousRunner path."""
    inst = _instance("I-01")
    cfg = RunConfig(use_planner=False, llm_provider="fake", topology="mesh", n_agents=2)
    score = run_instance(inst, cfg)

    assert isinstance(score, ScoreResult)
    # planner-OFF path never tags the record as a planner run.
    assert score.extra.get("planner") in (None, False)
