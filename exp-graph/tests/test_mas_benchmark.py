import json
from pathlib import Path

from exp_graph.mas.benchmark import build_benchmark_report


def test_benchmark_report_compares_evolved_against_frozen_and_oracle(tmp_path) -> None:
    fixed_dir = tmp_path / "fixed" / "collected"
    v0_dir = tmp_path / "v0" / "collected"
    v1_dir = tmp_path / "v1" / "collected"
    _write_metrics(
        fixed_dir,
        [
            _condition(
                planner_policy="fixed_topology",
                topology_name="tree",
                mean_rmse=5.0,
                mean_messages=7,
                mean_token_cost=100,
            ),
            _condition(
                planner_policy="fixed_topology",
                topology_name="one_peer_exponential_dag_star",
                mean_rmse=2.0,
                mean_messages=31,
                mean_token_cost=300,
            ),
            _condition(
                planner_policy="fixed_topology",
                topology_name="mesh_star",
                mean_rmse=3.0,
                mean_messages=63,
                mean_token_cost=500,
            ),
        ],
    )
    _write_metrics(
        v0_dir,
        [
            _condition(
                planner_policy="skill_grounded",
                topology_name="tree",
                mean_rmse=4.5,
                mean_messages=7,
                mean_token_cost=110,
                skill_grounding_rate=1.0,
            ),
            _condition(
                planner_policy="llm_free",
                topology_name="mesh_star",
                mean_rmse=3.5,
                mean_messages=63,
                mean_token_cost=550,
            ),
        ],
    )
    _write_metrics(
        v1_dir,
        [
            _condition(
                planner_policy="skill_grounded",
                topology_name="one_peer_exponential_dag_star",
                mean_rmse=2.1,
                mean_messages=31,
                mean_token_cost=330,
                skill_grounding_rate=1.0,
            ),
        ],
    )

    result = build_benchmark_report(
        fixed_collected_dir=fixed_dir,
        v0_collected_dir=v0_dir,
        v1_collected_dir=v1_dir,
        output_dir=tmp_path / "benchmark",
    )

    assert result.method_count == 7
    assert Path(result.summary_csv).exists()
    assert Path(result.by_condition_csv).exists()
    report = json.loads(Path(result.report_json).read_text(encoding="utf-8"))
    by_method = {row["method"]: row for row in report["method_summary"]}
    assert by_method["oracle_best_topology"]["regret_vs_oracle"] == 0.0
    assert (
        by_method["evolved_skillbank_v1"]["regret_vs_oracle"]
        < by_method["frozen_skillbank_v0"]["regret_vs_oracle"]
    )
    assert "reduced regret_vs_oracle" in report["claim_draft"]["text"]


def _write_metrics(path: Path, conditions: list[dict]) -> None:
    path.mkdir(parents=True)
    (path / "cross_seed_metrics.json").write_text(
        json.dumps({"conditions": conditions}),
        encoding="utf-8",
    )


def _condition(
    *,
    planner_policy: str,
    topology_name: str,
    mean_rmse: float,
    mean_messages: float,
    mean_token_cost: float,
    skill_grounding_rate: float = 0.0,
) -> dict:
    return {
        "objective": "accuracy_first",
        "planner_policy": planner_policy,
        "topology_name": topology_name,
        "n_agents": 4,
        "array_size": 32,
        "merge_mode": "llm_full_merge",
        "init_mode": "llm_local_solve",
        "run_count": 5,
        "mean_rmse": mean_rmse,
        "std_rmse": 0.1,
        "exact_match_rate": 0.0,
        "mean_messages": mean_messages,
        "mean_model_calls": mean_messages + 4,
        "mean_token_cost": mean_token_cost,
        "valid_plan_rate": 1.0,
        "skill_grounding_rate": skill_grounding_rate,
        "fallback_rate": 0.0,
        "full_coverage_wrong_answer_rate": 0.2,
    }
