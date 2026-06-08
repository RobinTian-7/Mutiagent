from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance

DATA = Path(__file__).parent / "data"


def _instance(case_id):
    adapter = SiloBenchAdapter(DATA)
    return next(adapter.iter_instances(cases=[case_id]))


def test_offline_global_max_succeeds_on_mesh():
    inst = _instance("I-01")
    cfg = RunConfig(topology="mesh", llm_provider="fake", max_rounds=3, n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.success is True               # fake reduces to global max on mesh
    assert score.final_answer == "9"
    assert score.n_model_calls > 0
    assert score.n_messages > 0


def test_offline_unknown_task_runs_without_crashing():
    inst = _instance("III-21")
    cfg = RunConfig(topology="mesh", llm_provider="fake", max_rounds=2, n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.success is False              # fake can't sort; pipeline still runs
    assert "stop_reason" in score.extra


def test_planner_on_runs_via_protocol_runner():
    # Planner path is now wired (Plan 3 Part B): it routes through EmperorPlanner
    # + ProtocolRunner instead of raising. See test_engine_planner.py for the full
    # offline-convergence assertions.
    inst = _instance("I-01")
    cfg = RunConfig(use_planner=True, llm_provider="fake", n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.extra["planner"] is True
