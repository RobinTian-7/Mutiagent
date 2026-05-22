from pathlib import Path

from exp_graph.mas.pipeline import run_mas_pipeline
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def test_pipeline_run_writes_artifacts_but_not_skill_bank(tmp_path):
    before = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(SKILL_DIR.glob("*.yaml"))
    }
    bank = SkillBank.load_dir(SKILL_DIR)
    request = PlannerRequest.from_names(
        n_agents=4,
        objective="budget_first",
        planner_mode="operator_compose",
        array_size=8,
        merge_mode="deterministic",
        init_mode="deterministic",
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        trace_enabled=True,
        retain_traces=True,
        output_dir=str(tmp_path),
        max_parallel_ministers=2,
    )

    result = run_mas_pipeline(
        request=request,
        runtime=runtime,
        skill_bank=bank,
        seed=1,
        llm_insights=True,
    )

    assert result.protocol_result.final_result.exact_match is True
    assert result.patches
    assert (tmp_path / "mas_plan.json").exists()
    assert (tmp_path / "evidence_records.jsonl").exists()
    assert (tmp_path / "patches" / "trace_patches.json").exists()
    assert (tmp_path / "insight_report.md").exists()
    after = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(SKILL_DIR.glob("*.yaml"))
    }
    assert after == before


def test_free_graph_policy_runs_single_mode_fake(tmp_path):
    bank = SkillBank.load_dir(SKILL_DIR)
    request = PlannerRequest.from_names(
        n_agents=4,
        objective="accuracy_first",
        planner_mode="graph_generate",
        array_size=8,
        merge_mode="deterministic",
        init_mode="deterministic",
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        trace_enabled=True,
        retain_traces=True,
        output_dir=str(tmp_path),
    )

    result = run_mas_pipeline(
        request=request,
        runtime=runtime,
        skill_bank=bank,
        seed=1,
        planner_policy="free_graph",
    )

    assert result.plan.planner_mode == "graph_generate"
    assert result.plan.topology_name.startswith("generated:")
    assert result.plan.protocol_spec is not None
    assert result.protocol_result.total_messages > 0
    assert (tmp_path / "generated_graph_candidates.json").exists()
    assert (tmp_path / "selected_graph_plan.json").exists()


def test_free_graph_topk_generates_and_selects_best_fake(tmp_path):
    bank = SkillBank.load_dir(SKILL_DIR)
    request = PlannerRequest.from_names(
        n_agents=4,
        objective="budget_first",
        planner_mode="graph_generate",
        array_size=8,
        merge_mode="deterministic",
        init_mode="deterministic",
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        graph_search_mode="topk",
        num_graph_candidates=4,
        graph_top_k=2,
        graph_validation_seeds=[1, 2],
        output_dir=str(tmp_path),
    )

    result = run_mas_pipeline(
        request=request,
        runtime=runtime,
        skill_bank=bank,
        seed=3,
        planner_policy="free_graph",
    )

    assert result.plan.topology_name.startswith("generated:")
    assert (tmp_path / "graph_candidate_eval").exists()
    assert (tmp_path / "graph_validation_summary.json").exists()
