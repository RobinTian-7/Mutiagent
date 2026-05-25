from pathlib import Path

from exp_graph.mas.insights import LLMInsightMinister, build_evidence_pack
from exp_graph.mas.schemas import EvidenceRecord, MASRuntimeConfig
from exp_graph.mas.skill_bank import SkillBank


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def test_fake_llm_insight_minister_outputs_verified_patch_candidates():
    bank = SkillBank.load_dir(SKILL_DIR)
    records = [
        EvidenceRecord(
            evidence_id="run:abc",
            source_type="run",
            topology_name="tree",
            n_agents=4,
            seed=1,
            metrics={
                "array_size": 128,
                "final_rmse": 0.2,
                "total_messages": 3,
                "token_cost": 100,
                "final_exact_match": False,
                "topology_structure": {
                    "structure_hash": "tree-a",
                    "topology_name": "tree",
                    "n_agents": 4,
                    "selected_primary": 3,
                    "total_steps": 2,
                    "total_messages": 3,
                    "steps": [
                        {
                            "step_idx": 0,
                            "description": "pair reduce",
                            "transmissions": [[0, 1], [2, 3]],
                        },
                        {
                            "step_idx": 1,
                            "description": "final reduce",
                            "transmissions": [[1, 3]],
                        },
                    ],
                },
            },
            risk_tags=["non_exact_final"],
        )
    ]
    pack = build_evidence_pack(
        records=records,
        skill_bank=bank,
        experiment_id="abc",
    )
    structures = pack["topologies"]["tree"]["topology_structures"]
    assert structures[0]["structure_hash"] == "tree-a"
    assert structures[0]["steps"][0]["transmissions"] == [[0, 1], [2, 3]]

    report = LLMInsightMinister(
        runtime=MASRuntimeConfig(llm_provider="fake", model_name="fake")
    ).analyze(evidence_pack=pack, skill_bank=bank)

    assert report.key_insights
    assert all(insight.evidence_refs for insight in report.key_insights)
    assert all(insight.claim_status == "hypothesis" for insight in report.key_insights)
    assert all(insight.operation_recommendations for insight in report.key_insights)
    assert all(insight.condition_buckets for insight in report.key_insights)
    assert report.skill_update_recommendations
    assert report.skill_update_recommendations[0].action == "merge"
    update = report.skill_update_recommendations[0].update
    assert "operation_recommendations" in update["organization_policy"]
    assert update["design_insights"]
    insight = update["design_insights"][0]
    assert insight["insight_id"] == report.key_insights[0].insight_id
    assert insight["summary"] == report.key_insights[0].summary
    assert insight["evidence_refs"] == report.key_insights[0].evidence_refs
    assert insight["operation_recommendations"]
