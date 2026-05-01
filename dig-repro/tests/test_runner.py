from pathlib import Path

from dig_repro.baselines import SystemKind
from dig_repro.runtime import DIGExperimentRunner, ExperimentConfig
from dig_repro.tasks import CountFrequencyTask, NewsgroupsFrequencyTask


def test_runner_exports_graph_and_trace(tmp_path: Path):
    config = ExperimentConfig(
        task_name="count_frequency",
        system_name=SystemKind.MAS_DIG.value,
        n_agents=3,
        difficulty="easy",
        seed=1,
        max_activations=40,
        split_threshold=5,
        export_dir=str(tmp_path),
    )
    result = DIGExperimentRunner(config=config, task_adapter=CountFrequencyTask()).run(
        array_size=12,
        value_domain_size=3,
    )
    assert result.metrics.valid_output is True
    assert result.metrics.rmse == 0.0
    assert result.graph["nodes"]
    assert Path(result.exports["graph"]).exists()
    assert Path(result.exports["trace"]).exists()


def test_dig_beats_mas_only_on_medium_cf():
    task = CountFrequencyTask()
    common = dict(
        task_name="count_frequency",
        n_agents=6,
        difficulty="medium",
        seed=4,
        max_activations=90,
        split_threshold=20,
    )
    mas_only = DIGExperimentRunner(
        config=ExperimentConfig(system_name=SystemKind.MAS_ONLY.value, **common),
        task_adapter=task,
    ).run(array_size=180, value_domain_size=5)
    mas_dig = DIGExperimentRunner(
        config=ExperimentConfig(system_name=SystemKind.MAS_DIG.value, **common),
        task_adapter=task,
    ).run(array_size=180, value_domain_size=5)

    assert mas_only.metrics.valid_output is False
    assert mas_dig.metrics.valid_output is True
    assert mas_dig.metrics.rmse == 0.0
    assert len(mas_dig.interventions) >= 1


def test_llm_judge_periodically_intervenes():
    config = ExperimentConfig(
        task_name="count_frequency",
        system_name=SystemKind.MAS_LLM_JUDGE.value,
        n_agents=6,
        difficulty="medium",
        seed=4,
        max_activations=90,
        split_threshold=20,
        judge_interval=6,
    )
    result = DIGExperimentRunner(config=config, task_adapter=CountFrequencyTask()).run(
        array_size=180,
        value_domain_size=5,
    )
    assert len(result.interventions) > 0


def test_newsgroups_smoke():
    config = ExperimentConfig(
        task_name="newsgroups_frequency",
        system_name=SystemKind.MAS_DIG.value,
        n_agents=4,
        difficulty="easy",
        seed=3,
        max_activations=80,
        split_threshold=8,
    )
    result = DIGExperimentRunner(config=config, task_adapter=NewsgroupsFrequencyTask()).run(
        num_documents=30,
    )
    assert result.metrics.valid_output is True
    assert result.metrics.rmse == 0.0
