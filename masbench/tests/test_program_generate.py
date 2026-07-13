from __future__ import annotations

import json
from pathlib import Path

from exp_graph.mas.phase_program_generation import PhaseProgramGenerationError
from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.cli import main
from masbench.core.config import RunConfig
from masbench.engine import run_instance
from masbench.evolve import _run_one, evolution_objective_spec
from masbench.llm.fake import BenchmarkFakeLLMClient


DATA = Path(__file__).parent / "data"


def _instance():
    return next(SiloBenchAdapter(DATA).iter_instances(cases=["I-01"]))


def test_program_generate_is_independent_and_auditable(tmp_path: Path) -> None:
    score = run_instance(
        _instance(),
        RunConfig(
            use_planner=True,
            planner_mode="program_generate",
            llm_provider="fake",
            n_agents=2,
            silo_eval_mode="all_agents",
            program_artifacts_dir=str(tmp_path),
        ),
    )

    assert score.extra["planner_mode"] == "program_generate"
    assert score.extra["program_format"] == "phase_program_v1"
    assert score.extra["provenance"] == "fake"
    artifact_dir = Path(score.extra["program_artifacts_dir"])
    audit = json.loads((artifact_dir / "program_architect_call.json").read_text())
    assert audit["planner_mode"] == "program_generate"
    assert audit["program_format"] == "phase_program_v1"
    assert not (artifact_dir / "architect_call.json").exists()


def test_graph_generate_remains_a_distinct_mode(tmp_path: Path) -> None:
    score = run_instance(
        _instance(),
        RunConfig(
            use_planner=True,
            planner_mode="graph_generate",
            llm_provider="fake",
            n_agents=2,
            graph_artifacts_dir=str(tmp_path),
        ),
    )

    assert score.extra["planner_mode"] == "graph_generate"
    assert "program_format" not in score.extra


def test_cli_accepts_program_generate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MASBENCH_PROGRAM_ARTIFACTS_DIR", str(tmp_path))
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
            "program_generate",
            "--llm",
            "fake",
        ]
    )

    assert rc == 0


def test_invalid_program_becomes_validity_zero_training_evidence(
    monkeypatch,
) -> None:
    def fail(*args, **kwargs):
        raise PhaseProgramGenerationError("no valid phase program")

    monkeypatch.setattr("masbench.evolve._plan_program_generate", fail)
    cfg = RunConfig(
        planner_mode="program_generate",
        evolved_mode="program_generate",
        llm_provider="fake",
        n_agents=2,
        task_feature_source="heuristic",
    )
    row = _run_one(
        _instance(),
        cfg,
        objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(),
        seed=7,
        llm_client=BenchmarkFakeLLMClient(),
        diag_phase="test",
    )

    assert row["program_validity"] == 0.0
    assert row["evolution_stage"] == "validity"
    assert row["mean_primary_loss"] == 1.0
    assert row["program_generation_failed"] == "no valid phase program"
