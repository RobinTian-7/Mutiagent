from pathlib import Path

from exp_graph.mas.schemas import PlannerRequest, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import (
    SkillBank,
    render_skill_bank_markdown,
    render_skill_markdown,
)


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def test_skill_bank_loads_yaml_subset_and_retrieves_selectable_skills() -> None:
    bank = SkillBank.load_dir(SKILL_DIR)
    request = PlannerRequest.from_names(n_agents=8, objective="balanced")

    matches = bank.retrieve(request)

    assert bank.get("cf_avoid_sparse_random") is not None
    assert {skill.skill_id for skill in matches} == {"cf_middle_ground_mesh_star"}


def test_skill_bank_save_load_and_markdown_render(tmp_path) -> None:
    bank = SkillBank.load_dir(SKILL_DIR)
    saved_dir = tmp_path / "skills"
    markdown_dir = tmp_path / "notes"

    bank.save_dir(saved_dir)
    loaded = SkillBank.load_dir(saved_dir)
    render_skill_bank_markdown(loaded, markdown_dir)

    assert loaded.get("cf_accuracy_peer_star") is not None
    assert (markdown_dir / "cf_accuracy_peer_star.md").exists()
    markdown = render_skill_markdown(loaded.get("cf_budget_tree"))
    assert "# cf_budget_tree" in markdown
    assert "## Evidence" in markdown


def test_skill_bank_applies_add_merge_discard_patches() -> None:
    seed = SkillCard(
        skill_id="cf_seed",
        objective="balanced",
        organization_policy={"topology_name": "mesh_star"},
        expected_tradeoff={"mean_rmse": 0.2},
    )
    candidate = SkillCard(
        skill_id="cf_seed",
        objective="balanced",
        organization_policy={"topology_name": "mesh_star"},
        expected_tradeoff={"mean_rmse": 0.1},
        evidence=[{"mean_rmse": 0.1}],
    )
    new_skill = SkillCard(
        skill_id="cf_new",
        objective="budget_first",
        organization_policy={"topology_name": "tree"},
    )
    bank = SkillBank([seed])

    outcomes = bank.apply_patches(
        [
            SkillPatch(patch_id="merge", action="merge", target_skill_id="cf_seed",
                       candidate_skill=candidate, lesson="better evidence"),
            SkillPatch(patch_id="add", action="add", candidate_skill=new_skill),
            SkillPatch(patch_id="discard", action="discard"),
        ]
    )

    assert outcomes == {"added": 1, "merged": 1, "discarded": 1}
    assert bank.get("cf_seed").version == "0.1.1"
    assert bank.get("cf_seed").expected_tradeoff["mean_rmse"] == 0.1
    assert bank.get("cf_new") is not None
