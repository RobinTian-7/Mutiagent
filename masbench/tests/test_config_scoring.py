from masbench.core.config import RunConfig
from masbench.core.scoring import ScoreResult


def test_run_config_defaults():
    cfg = RunConfig()
    assert cfg.benchmark == "silo_bench"
    assert cfg.use_planner is False
    assert cfg.topology == "mesh"
    assert cfg.llm_provider == "fake"
    assert cfg.max_rounds == 4


def test_score_result_shape():
    score = ScoreResult(success=True, n_messages=4, n_model_calls=8, tokens=120)
    assert score.success is True
    assert score.partial is None
    assert score.n_messages == 4
    assert score.extra == {}
