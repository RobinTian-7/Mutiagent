from exp_graph.mas.evolution import (
    ResultAnalystMinister,
    build_result_patches_from_evidence,
    consolidate_batch,
)
from exp_graph.mas.schemas import EvidenceRecord, EvolutionBatch
from exp_graph.mas.skill_bank import SkillBank


def _row(topology: str, rmse: float, messages: float) -> dict:
    return {
        "Topology": topology,
        "Agents": 8,
        "ArraySize": 256,
        "MergeMode": "deterministic",
        "InitMode": "deterministic",
        "Runs": 3,
        "MeanFinalRMSE": rmse,
        "StdFinalRMSE": 0.01,
        "MeanFinalNormalizedL1Error": rmse,
        "ExactMatchRate": 1.0 if rmse == 0.0 else 0.5,
        "MeanTotalSteps": 4,
        "MeanTotalMessages": messages,
        "MeanTotalModelCalls": 0,
        "MeanTokenCost": messages * 100,
        "MeanVoteTopRatio": 1.0,
    }


def test_result_analyst_builds_skill_and_counterexample_patches() -> None:
    rows = [
        _row("one_peer_exponential_dag_star", 0.02, 31.0),
        _row("tree", 0.10, 7.0),
        _row("random", 0.60, 12.0),
    ]

    patches = ResultAnalystMinister().analyze(rows)

    patch_ids = {patch.patch_id for patch in patches}
    assert "result_cf_accuracy_peer_star" in patch_ids
    assert "result_cf_budget_tree" in patch_ids
    assert "counterexample_random" in patch_ids


def test_consolidate_batch_adds_and_merges_versioned_skills() -> None:
    rows = [_row("one_peer_exponential_dag_star", 0.02, 31.0)]
    patches = ResultAnalystMinister().analyze(rows)
    first_bank = consolidate_batch(
        EvolutionBatch(batch_id="first", patches=patches),
        SkillBank(),
    )
    second_bank = consolidate_batch(
        EvolutionBatch(batch_id="second", patches=patches),
        first_bank,
    )

    skill = second_bank.get("cf_accuracy_peer_star")
    assert skill is not None
    assert skill.version == "0.1.1"
    assert len(skill.evidence) >= 2


def test_generated_topology_skill_records_structure_and_condition_bucket() -> None:
    records = [
        EvidenceRecord(
            evidence_id="run:generated_tree:8:1024:1",
            source_type="run",
            topology_name="generated:balanced_tree_star",
            n_agents=8,
            seed=1,
            metrics={
                "array_size": 1024,
                "final_rmse": 1.0,
                "total_messages": 7,
                "token_cost": 100,
                "final_exact_match": False,
                "generated_graph_selected_primary": 7,
                "protocol_steps": 3,
                "protocol_messages": 7,
            },
        )
    ]

    patches = build_result_patches_from_evidence(records)

    skill = patches[0].candidate_skill
    assert skill is not None
    assert skill.skill_id.endswith("__a8__arr1024")
    assert patches[0].target_skill_id == skill.skill_id
    assert skill.trigger["agent_bucket"] == "agents_8"
    assert skill.trigger["array_size_bucket"] == "arrays_1024"
    assert skill.organization_policy["planner_mode"] == "graph_generate"
    structure = skill.organization_policy["structure_features"]
    assert "hierarchical_reduce" in structure["motifs"]
    assert structure["sink_pattern"] == "single_selected_primary"
    recommendations = skill.organization_policy["operation_recommendations"]
    assert any(item["target"] == "final_reducer" for item in recommendations)


def test_generated_topology_skills_are_bucketed_by_condition() -> None:
    records = [
        EvidenceRecord(
            evidence_id=f"run:generated_tree:8:{array_size}:1",
            source_type="run",
            topology_name="generated:balanced_tree_star",
            n_agents=8,
            seed=1,
            metrics={
                "array_size": array_size,
                "final_rmse": 1.0,
                "total_messages": 7,
                "token_cost": 100,
            },
        )
        for array_size in [128, 512]
    ]

    patches = build_result_patches_from_evidence(records)

    skill_ids = {patch.candidate_skill.skill_id for patch in patches if patch.candidate_skill}
    assert skill_ids == {
        "cf_topology_generated:balanced_tree_star__a8__arr128",
        "cf_topology_generated:balanced_tree_star__a8__arr512",
    }
