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
                "final_rmse": 0.2,
                "total_messages": 3,
                "token_cost": 100,
                "final_exact_match": False,
            },
            risk_tags=["non_exact_final"],
        )
    ]
    pack = build_evidence_pack(
        records=records,
        skill_bank=bank,
        experiment_id="abc",
    )

    report = LLMInsightMinister(
        runtime=MASRuntimeConfig(llm_provider="fake", model_name="fake")
    ).analyze(evidence_pack=pack, skill_bank=bank)

    assert report.key_insights
    assert all(insight.evidence_refs for insight in report.key_insights)
    assert all(insight.claim_status == "hypothesis" for insight in report.key_insights)
    assert report.skill_update_recommendations
    assert report.skill_update_recommendations[0].action == "merge"
