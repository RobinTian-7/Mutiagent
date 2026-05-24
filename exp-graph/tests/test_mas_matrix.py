import json
from pathlib import Path

from exp_graph.mas.matrix import (
    analyze_matrix_insights,
    collect_matrix,
    expand_matrix_jobs,
    run_matrix,
)
from exp_graph.mas.schemas import EvidenceRecord, RoleLLMConfig, RoleLLMProfiles
from exp_graph.mas.skill_bank import SkillBank


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def test_run_matrix_expands_all_jobs() -> None:
    jobs = expand_matrix_jobs(
        objectives=["accuracy_first", "balanced"],
        planner_modes=["operator_compose"],
        planner_policies=["skill_grounded", "fixed_topology"],
        topologies=["tree", "mesh_star"],
        n_agents_values=[2, 4],
        array_sizes=[8],
        seeds=[1, 2],
        merge_mode="deterministic",
        init_mode="deterministic",
        llm_provider="fake",
        model_name="fake",
        skill_bank=SkillBank.load_dir(SKILL_DIR),
    )

    assert len(jobs) == 24
    assert len({job.job_id for job in jobs}) == 24
    assert sum(1 for job in jobs if job.planner_policy == "skill_grounded") == 8
    assert sum(1 for job in jobs if job.planner_policy == "fixed_topology") == 16


def test_run_matrix_expands_free_graph_jobs_without_topology_cross_product() -> None:
    jobs = expand_matrix_jobs(
        objectives=["accuracy_first"],
        planner_modes=["graph_generate"],
        planner_policies=["free_graph"],
        topologies=["tree", "mesh_star"],
        n_agents_values=[4],
        array_sizes=[8],
        seeds=[1, 2],
        merge_mode="deterministic",
        init_mode="deterministic",
        llm_provider="fake",
        model_name="fake",
        skill_bank=SkillBank.load_dir(SKILL_DIR),
        graph_search_mode="topk",
        num_graph_candidates=3,
        graph_candidate_score_mode="accuracy_max",
        graph_validation_seeds=[1],
    )

    assert len(jobs) == 2
    assert all(job.topology_name is None for job in jobs)
    assert all(job.graph_search_mode == "topk" for job in jobs)
    assert all(job.num_graph_candidates == 3 for job in jobs)
    assert all(job.graph_candidate_score_mode == "accuracy_max" for job in jobs)


def test_matrix_jobs_preserve_role_llm_config() -> None:
    profiles = RoleLLMProfiles(
        emperor=RoleLLMConfig(platform="deepseek", model_name="deepseek-v4-flash"),
        soldier=RoleLLMConfig(
            platform="bailian",
            model_name="qwen3.5-flash",
            thinking_enabled=False,
        ),
    )
    jobs = expand_matrix_jobs(
        objectives=["accuracy_first"],
        planner_modes=["topology_select"],
        planner_policies=["fixed_topology"],
        topologies=["tree"],
        n_agents_values=[2],
        array_sizes=[8],
        value_min=0,
        value_max=1023,
        seeds=[1],
        merge_mode="deterministic",
        init_mode="deterministic",
        llm_provider="fake",
        model_name="fake",
        role_llm_profiles=profiles,
        role_llm_config_path="configs/role_llm_profiles/demo.json",
        skill_bank=SkillBank.load_dir(SKILL_DIR),
    )

    job = jobs[0]
    assert job.role_llm_config_path == "configs/role_llm_profiles/demo.json"
    assert job.value_min == 0
    assert job.value_max == 1023
    assert job.role_llm_profiles is not None
    assert job.role_llm_profiles.emperor.model_name == "deepseek-v4-flash"
    assert job.role_llm_profiles.soldier.thinking_enabled is False


def test_run_matrix_serializes_role_llm_config(tmp_path) -> None:
    profiles = RoleLLMProfiles(
        emperor=RoleLLMConfig(platform="fake", model_name="emperor-fake"),
        soldier=RoleLLMConfig(
            platform="fake",
            model_name="soldier-fake",
            thinking_enabled=False,
        ),
        minister=RoleLLMConfig(platform="fake", model_name="minister-fake"),
    )

    run_matrix(
        skill_dir=SKILL_DIR,
        output_dir=tmp_path,
        objectives=["budget_first"],
        planner_modes=["topology_select"],
        planner_policies=["fixed_topology"],
        topologies=["tree"],
        n_agents_values=[2],
        array_sizes=[8],
        value_min=0,
        value_max=3,
        seeds=[1],
        llm_provider="fake",
        model_name="legacy-fake",
        role_llm_profiles=profiles,
        role_llm_config_path="configs/role_llm_profiles/demo.json",
        merge_mode="deterministic",
        init_mode="deterministic",
        trace_enabled=True,
        retain_traces=True,
        max_parallel_runs=1,
        max_parallel_agents=1,
        max_parallel_ministers=1,
    )

    config = json.loads((tmp_path / "matrix_config.json").read_text())
    manifest_row = json.loads(
        (tmp_path / "matrix_manifest.jsonl").read_text().splitlines()[0]
    )

    assert config["role_llm_config_path"] == "configs/role_llm_profiles/demo.json"
    assert config["value_max"] == 3
    assert manifest_row["value_min"] == 0
    assert manifest_row["value_max"] == 3
    assert config["role_llm_profiles"]["minister"]["model_name"] == "minister-fake"
    assert manifest_row["role_llm_profiles"]["soldier"]["model_name"] == "soldier-fake"


def test_run_matrix_resume_skips_success(tmp_path) -> None:
    first = run_matrix(
        skill_dir=SKILL_DIR,
        output_dir=tmp_path,
        objectives=["budget_first"],
        planner_modes=["topology_select"],
        planner_policies=["fixed_topology"],
        topologies=["tree"],
        n_agents_values=[2],
        array_sizes=[8],
        seeds=[1],
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        trace_enabled=True,
        retain_traces=True,
        max_parallel_runs=1,
        max_parallel_agents=1,
        max_parallel_ministers=1,
    )
    second = run_matrix(
        skill_dir=SKILL_DIR,
        output_dir=tmp_path,
        objectives=["budget_first"],
        planner_modes=["topology_select"],
        planner_policies=["fixed_topology"],
        topologies=["tree"],
        n_agents_values=[2],
        array_sizes=[8],
        seeds=[1],
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        trace_enabled=True,
        retain_traces=True,
        max_parallel_runs=1,
        max_parallel_agents=1,
        max_parallel_ministers=1,
    )

    assert first.succeeded == 1
    assert second.skipped == 1


def test_collect_matrix_merges_evidence_patches_and_metrics(tmp_path) -> None:
    matrix_dir = tmp_path / "matrix"
    run_matrix(
        skill_dir=SKILL_DIR,
        output_dir=matrix_dir,
        objectives=["accuracy_first"],
        planner_modes=["topology_select"],
        planner_policies=["fixed_topology"],
        topologies=["tree", "one_peer_exponential_dag_star"],
        n_agents_values=[2],
        array_sizes=[8],
        seeds=[1, 2],
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        trace_enabled=True,
        retain_traces=True,
        max_parallel_runs=2,
        max_parallel_agents=1,
        max_parallel_ministers=1,
    )

    result = collect_matrix(
        matrix_dir=matrix_dir,
        output_dir=matrix_dir / "collected",
    )

    assert result.run_count == 4
    assert result.evidence_count == 8
    assert (matrix_dir / "collected" / "batch_evidence.jsonl").exists()
    assert (matrix_dir / "collected" / "batch_patches" / "result_patches.json").exists()
    assert (matrix_dir / "collected" / "batch_patches" / "cost_patches.json").exists()
    assert (matrix_dir / "collected" / "cross_seed_metrics.json").exists()


def test_analyze_matrix_insights_fake_outputs_patches(tmp_path) -> None:
    evidence_path = tmp_path / "batch_evidence.jsonl"
    records = [
        EvidenceRecord(
            evidence_id="run:peer:1",
            source_type="run",
            topology_name="one_peer_exponential_dag_star",
            n_agents=8,
            seed=1,
            metrics={
                "objective": "accuracy_first",
                "planner_policy": "fixed_topology",
                "array_size": 64,
                "merge_mode": "llm_full_merge",
                "init_mode": "llm_local_solve",
                "final_rmse": 9.0,
                "final_exact_match": False,
                "token_cost": 100,
            },
        ),
        EvidenceRecord(
            evidence_id="trace:peer:1",
            source_type="trace",
            topology_name="one_peer_exponential_dag_star",
            n_agents=8,
            seed=1,
            metrics={
                "objective": "accuracy_first",
                "planner_policy": "fixed_topology",
                "array_size": 64,
                "merge_mode": "llm_full_merge",
                "init_mode": "llm_local_solve",
            },
            risk_tags=["full_coverage_wrong_answer"],
        ),
    ]
    from exp_graph.mas.evidence import write_evidence_jsonl

    write_evidence_jsonl(records, evidence_path)
    summary_path = tmp_path / "cross_seed_metrics.json"
    summary_path.write_text(
        """
{
  "conditions": [
    {
      "objective": "accuracy_first",
      "planner_policy": "fixed_topology",
      "topology_name": "one_peer_exponential_dag_star",
      "n_agents": 8,
      "array_size": 64,
      "merge_mode": "llm_full_merge",
      "init_mode": "llm_local_solve",
      "run_count": 1,
      "mean_rmse": 9.0,
      "mean_token_cost": 100.0,
      "full_coverage_wrong_answer_rate": 1.0
    }
  ]
}
""",
        encoding="utf-8",
    )
    trace_path = tmp_path / "cross_seed_trace_summary.json"
    trace_path.write_text('{"conditions": []}', encoding="utf-8")

    report = analyze_matrix_insights(
        skill_dir=SKILL_DIR,
        evidence_file=evidence_path,
        summary_file=summary_path,
        trace_summary_file=trace_path,
        llm_provider="fake",
        model_name="fake",
        max_parallel_insight_shards=1,
        output_dir=tmp_path / "insights",
    )

    assert report.key_insights
    assert any(
        insight.insight_type == "risk_pattern" for insight in report.key_insights
    )
    assert report.skill_update_recommendations
    assert (tmp_path / "insights" / "patches" / "insight_patches.json").exists()


def test_collect_matrix_records_free_graph_metadata(tmp_path) -> None:
    matrix_dir = tmp_path / "matrix"
    run_matrix(
        skill_dir=SKILL_DIR,
        output_dir=matrix_dir,
        objectives=["accuracy_first"],
        planner_modes=["graph_generate"],
        planner_policies=["free_graph"],
        topologies=[],
        n_agents_values=[2],
        array_sizes=[8],
        seeds=[1],
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        trace_enabled=True,
        retain_traces=True,
        max_parallel_runs=1,
        max_parallel_agents=1,
        max_parallel_ministers=1,
        graph_search_mode="topk",
        num_graph_candidates=2,
        graph_validation_seeds=[1],
    )

    collect_matrix(matrix_dir=matrix_dir, output_dir=matrix_dir / "collected")
    plan_summary = (matrix_dir / "collected" / "matrix_plan_summary.csv").read_text(
        encoding="utf-8"
    )
    metrics = (matrix_dir / "collected" / "cross_seed_metrics.json").read_text(
        encoding="utf-8"
    )

    assert "generated_graph" in plan_summary
    assert "candidate_count" in plan_summary
    assert "graph_candidate_score_mode" in plan_summary
    assert "generated_graph_rate" in metrics
