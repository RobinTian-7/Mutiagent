from exp_graph.mas.evolution import ResultAnalystMinister, consolidate_batch
from exp_graph.mas.schemas import EvolutionBatch
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
