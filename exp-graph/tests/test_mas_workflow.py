import importlib.util
import json
import sys
from pathlib import Path

import pytest

from exp_graph.mas.workflow import (
    MASWorkflowConfig,
    WORKFLOW_NODES,
    WorkflowRunOptions,
    build_node_command,
    load_workflow_config,
    run_workflow,
)


REPO = Path(__file__).parents[1]
SKILL_DIR = REPO / "configs" / "mas_skills"


def _small_config(tmp_path: Path) -> MASWorkflowConfig:
    return MASWorkflowConfig(
        repo_dir=str(REPO),
        python_bin=sys.executable,
        skill_dir=str(SKILL_DIR),
        output_dir=str(tmp_path / "workflow"),
        objectives=["accuracy_first"],
        topologies=["tree"],
        n_agents=[2],
        array_sizes=[8],
        value_min=0,
        value_max=3,
        train_seeds=[1],
        test_seeds=[2],
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        max_parallel_runs=1,
        max_parallel_agents=1,
        max_parallel_ministers=1,
        max_parallel_insight_shards=1,
        trace=True,
        retain_traces=True,
    )


def test_workflow_command_builders_match_expected_cli(tmp_path) -> None:
    config = _small_config(tmp_path)

    train = build_node_command(config, "train_matrix")
    assert train is not None
    assert train[:3] == [sys.executable, "-m", "exp_graph.mas.cli"]
    assert "run-matrix" in train
    assert "topology_sweep" in train
    assert str(SKILL_DIR) in train
    assert train[train.index("--value-max") + 1] == "3"

    evolve = build_node_command(config, "evolve_skills")
    assert evolve is not None
    assert "evolve-skills" in evolve
    assert "--patch-dir" in evolve

    benchmark = build_node_command(config, "benchmark_report")
    assert benchmark is not None
    assert "benchmark-report" in benchmark


def test_workflow_command_builders_include_role_llm_config(tmp_path) -> None:
    config = _small_config(tmp_path).model_copy(
        update={"role_llm_config": "configs/role_llm_profiles/demo.json"}
    )

    train = build_node_command(config, "train_matrix")
    insights = build_node_command(config, "analyze_insights")
    test_fixed = build_node_command(config, "test_fixed")

    assert train is not None
    assert insights is not None
    assert test_fixed is not None
    for command in [train, insights, test_fixed]:
        idx = command.index("--role-llm-config")
        assert command[idx + 1] == "configs/role_llm_profiles/demo.json"


def test_workflow_real_role_llm_config_requires_confirmation(tmp_path) -> None:
    role_config = tmp_path / "roles.json"
    role_config.write_text(
        json.dumps({"emperor": {"platform": "openai", "model_name": "gpt-test"}}),
        encoding="utf-8",
    )
    config = _small_config(tmp_path).model_copy(
        update={"role_llm_config": str(role_config)}
    )

    with pytest.raises(RuntimeError, match="real LLM jobs"):
        run_workflow(config, WorkflowRunOptions(workflow_backend="shell"))


def test_workflow_dry_run_writes_plan_without_running_jobs(tmp_path) -> None:
    config = _small_config(tmp_path)
    state = run_workflow(
        config,
        WorkflowRunOptions(workflow_backend="shell", dry_run=True, debug=True),
    )

    state_path = Path(state.output_dir) / "workflow_state.json"
    report_path = Path(state.output_dir) / "workflow_report.md"
    assert state_path.exists()
    assert report_path.exists()
    assert not (Path(state.train_dir) / "matrix_manifest.jsonl").exists()
    assert state.node_results["train_matrix"].status == "skipped"


def test_workflow_pause_before_evolve(tmp_path) -> None:
    config = _small_config(tmp_path)
    state = run_workflow(
        config,
        WorkflowRunOptions(
            workflow_backend="shell",
            only_node="review_before_evolve",
            pause_before_evolve=True,
        ),
    )

    assert state.node_results["review_before_evolve"].status == "paused"
    assert state.review_decision == "paused_before_evolve"


def test_workflow_stop_after_node(tmp_path) -> None:
    config = _small_config(tmp_path)
    state = run_workflow(
        config,
        WorkflowRunOptions(workflow_backend="shell", dry_run=True, stop_after="collect_train"),
    )

    assert state.node_results["collect_train"].status == "skipped"
    assert "analyze_insights" not in state.node_results


def test_workflow_shell_backend_fake_smoke(tmp_path) -> None:
    config = _small_config(tmp_path)
    state = run_workflow(config, WorkflowRunOptions(workflow_backend="shell"))

    assert state.node_results["benchmark_report"].status == "succeeded"
    assert (Path(state.benchmark_dir) / "benchmark_report.md").exists()
    assert (Path(state.output_dir) / "workflow_report.md").exists()


def test_langgraph_backend_missing_dependency(tmp_path) -> None:
    if importlib.util.find_spec("langgraph") is not None:
        pytest.skip("langgraph is installed in this environment")
    config = _small_config(tmp_path)

    with pytest.raises(RuntimeError, match="langgraph is not installed"):
        run_workflow(config, WorkflowRunOptions(workflow_backend="langgraph", dry_run=True))


def test_langgraph_backend_fake_smoke_if_installed(tmp_path) -> None:
    if importlib.util.find_spec("langgraph") is None:
        pytest.skip("langgraph is not installed")
    config = _small_config(tmp_path)
    state = run_workflow(
        config,
        WorkflowRunOptions(workflow_backend="langgraph", dry_run=True),
    )
    assert state.node_results[WORKFLOW_NODES[-1]].status == "skipped"


def test_workflow_resume_after_pause_continues(tmp_path) -> None:
    config = _small_config(tmp_path)
    run_workflow(
        config,
        WorkflowRunOptions(
            workflow_backend="shell",
            only_node="review_before_evolve",
            pause_before_evolve=True,
        ),
    )

    state = run_workflow(
        config,
        WorkflowRunOptions(
            workflow_backend="shell",
            only_node="review_before_evolve",
            pause_before_evolve=True,
            resume=True,
        ),
    )

    assert state.node_results["review_before_evolve"].status == "succeeded"
    assert state.review_decision == "approved_by_resume"


def test_workflow_config_loads_json_and_overrides(tmp_path) -> None:
    path = tmp_path / "workflow.json"
    path.write_text(
        json.dumps(
            {
                "repo_dir": str(REPO),
                "skill_dir": str(SKILL_DIR),
                "output_dir": str(tmp_path / "out"),
                "objectives": "accuracy_first,budget_first",
                "n_agents": "2,4",
            }
        ),
        encoding="utf-8",
    )

    config = load_workflow_config(path, overrides={"llm_provider": "fake"})

    assert config.objectives == ["accuracy_first", "budget_first"]
    assert config.n_agents == [2, 4]
    assert config.llm_provider == "fake"
