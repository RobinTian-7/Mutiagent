import json
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
        value_min=0,
        value_max=3,
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
    summary = result.protocol_result.to_summary_dict()
    assert summary["ValueMin"] == 0
    assert summary["ValueMax"] == 3
    assert set(result.protocol_result.global_task["answer_counts"]).issubset(
        {"0", "1", "2", "3"}
    )
    assert result.patches
    assert (tmp_path / "mas_plan.json").exists()
    assert (tmp_path / "evidence_records.jsonl").exists()
    assert (tmp_path / "patches" / "trace_patches.json").exists()
    assert (tmp_path / "insight_report.md").exists()
    evidence_pack = json.loads((tmp_path / "evidence_pack.json").read_text())
    tree_structures = evidence_pack["topologies"][result.plan.topology_name][
        "topology_structures"
    ]
    assert tree_structures
    assert tree_structures[0]["total_steps"] == result.protocol_result.total_steps
    assert tree_structures[0]["steps"][0]["transmissions"]
    run_record = next(
        record for record in result.evidence_records if record.source_type == "run"
    )
    assert run_record.metrics["value_max"] == 3
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
    run_record = next(
        record for record in result.evidence_records if record.source_type == "run"
    )
    topology_structure = run_record.metrics["topology_structure"]
    assert topology_structure["topology_name"].startswith("generated:")
    assert topology_structure["steps"][0]["transmissions"]
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
