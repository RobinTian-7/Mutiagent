from pathlib import Path

from exp_graph.mas.schemas import PlannerRequest, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import (
    SkillBank,
    compact_skill_bank,
    compact_skill_dir,
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


def test_skill_bank_retrieval_respects_array_size_bucket() -> None:
    bank = SkillBank(
        [
            SkillCard(
                skill_id="cf_generated_arr128",
                objective="balanced",
                trigger={
                    "task_family": "count_frequency",
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 128,
                    "max_array_size": 128,
                    "condition_key": "agents_8__arrays_128",
                },
                organization_policy={"topology_name": "generated:balanced_tree_star"},
            ),
            SkillCard(
                skill_id="cf_generated_arr512",
                objective="balanced",
                trigger={
                    "task_family": "count_frequency",
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 512,
                    "max_array_size": 512,
                    "condition_key": "agents_8__arrays_512",
                },
                organization_policy={"topology_name": "generated:balanced_tree_star"},
            ),
        ]
    )

    matches = bank.retrieve(
        PlannerRequest.from_names(n_agents=8, array_size=512, objective="balanced")
    )

    assert [skill.skill_id for skill in matches] == ["cf_generated_arr512"]


def test_skill_bank_retrieval_ranks_condition_and_rmse_quality() -> None:
    bank = SkillBank(
        [
            SkillCard(
                skill_id="generic_low_rmse",
                objective="balanced",
                organization_policy={"topology_name": "generated:generic"},
                expected_tradeoff={"mean_rmse": 1.0, "active_evidence_count": 5},
            ),
            SkillCard(
                skill_id="exact_high_rmse",
                objective="balanced",
                trigger={
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 512,
                    "max_array_size": 512,
                    "condition_key": "agents_8__arrays_512",
                },
                organization_policy={"topology_name": "generated:exact_high"},
                expected_tradeoff={"mean_rmse": 5.0, "active_evidence_count": 2},
            ),
            SkillCard(
                skill_id="exact_low_rmse",
                objective="balanced",
                trigger={
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 512,
                    "max_array_size": 512,
                    "condition_key": "agents_8__arrays_512",
                },
                organization_policy={"topology_name": "generated:exact_low"},
                expected_tradeoff={"mean_rmse": 2.0, "active_evidence_count": 1},
            ),
            SkillCard(
                skill_id="archived_exact_best",
                objective="balanced",
                trigger={
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 512,
                    "max_array_size": 512,
                },
                organization_policy={"topology_name": "generated:archived"},
                expected_tradeoff={"mean_rmse": 0.0},
                tags=["archived"],
            ),
            SkillCard(
                skill_id="deprecated_exact_best",
                objective="balanced",
                trigger={
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 512,
                    "max_array_size": 512,
                },
                organization_policy={"topology_name": "generated:deprecated"},
                expected_tradeoff={"mean_rmse": 0.0},
                tags=["deprecated"],
            ),
        ]
    )

    matches = bank.retrieve(
        PlannerRequest.from_names(n_agents=8, array_size=512, objective="balanced")
    )

    assert [skill.skill_id for skill in matches] == [
        "exact_low_rmse",
        "exact_high_rmse",
        "generic_low_rmse",
    ]


def test_compact_skill_bank_keeps_top_rmse_per_condition_bucket() -> None:
    same_bucket = [
        SkillCard(
            skill_id=f"bucket_skill_{idx}",
            objective="balanced",
            trigger={
                "agent_bucket": "agents_8",
                "array_size_bucket": "arrays_512",
                "min_agents": 8,
                "max_agents": 8,
                "min_array_size": 512,
                "max_array_size": 512,
            },
            organization_policy={"topology_name": f"generated:bucket_{idx}"},
            expected_tradeoff=tradeoff,
        )
        for idx, tradeoff in [
            (1, {"mean_rmse": 4.0}),
            (2, {"mean_rmse": 1.0}),
            (3, {"mean_rmse": 2.0}),
            (4, {}),
        ]
    ]
    bank = SkillBank(
        [
            *same_bucket,
            SkillCard(
                skill_id="other_array_bucket",
                objective="balanced",
                trigger={
                    "agent_bucket": "agents_8",
                    "array_size_bucket": "arrays_1024",
                    "min_agents": 8,
                    "max_agents": 8,
                    "min_array_size": 1024,
                    "max_array_size": 1024,
                },
                organization_policy={"topology_name": "generated:other"},
                expected_tradeoff={"mean_rmse": 9.0},
            ),
            SkillCard(
                skill_id="cf_avoid_bad",
                objective="balanced",
                organization_policy={"topology_name": "generated:bad"},
            ),
        ]
    )

    active, archived, summary = compact_skill_bank(bank, max_per_condition=3)

    assert set(active.skills) == {
        "bucket_skill_1",
        "bucket_skill_2",
        "bucket_skill_3",
        "other_array_bucket",
        "cf_avoid_bad",
    }
    assert set(archived.skills) == {"bucket_skill_4"}
    assert summary["active_count"] == 5
    assert summary["active_avoid_count"] == 1
    assert archived.get("bucket_skill_4").tags == ["archived"]


def test_skill_bank_retrieves_avoid_skills_as_negative_constraints() -> None:
    avoid = SkillCard(
        skill_id="cf_avoid_generated:bad",
        objective="balanced",
        trigger={
            "min_agents": 8,
            "max_agents": 8,
            "min_array_size": 512,
            "max_array_size": 512,
        },
        organization_policy={"topology_name": "generated:bad"},
    )
    deprecated = avoid.model_copy(
        update={
            "skill_id": "cf_avoid_generated:old",
            "tags": ["deprecated"],
        }
    )
    bank = SkillBank([avoid, deprecated])

    matches = bank.retrieve_avoid(
        PlannerRequest.from_names(n_agents=8, array_size=512, objective="balanced")
    )

    assert [skill.skill_id for skill in matches] == ["cf_avoid_generated:bad"]
    assert bank.retrieve(
        PlannerRequest.from_names(n_agents=8, array_size=512, objective="balanced")
    ) == []


def test_compact_skill_dir_writes_active_and_archive_dirs(tmp_path) -> None:
    source = tmp_path / "source"
    active_dir = tmp_path / "active"
    archive_dir = tmp_path / "archive"
    SkillBank(
        [
            SkillCard(
                skill_id="keep",
                objective="balanced",
                organization_policy={"topology_name": "generated:keep"},
                expected_tradeoff={"mean_rmse": 1.0},
            ),
            SkillCard(
                skill_id="drop",
                objective="balanced",
                organization_policy={"topology_name": "generated:drop"},
                expected_tradeoff={"mean_rmse": 2.0},
            ),
        ]
    ).save_dir(source)

    summary = compact_skill_dir(
        skill_dir=source,
        output_dir=active_dir,
        archive_dir=archive_dir,
        max_per_condition=1,
    )

    assert summary["active_count"] == 1
    assert SkillBank.load_dir(active_dir).get("keep") is not None
    assert SkillBank.load_dir(archive_dir).get("drop") is not None
    assert (active_dir / "skill_compaction_summary.json").exists()


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


def test_skill_bank_deprecate_patch_blocks_retrieval() -> None:
    skill = SkillCard(
        skill_id="cf_seed",
        objective="balanced",
        organization_policy={"topology_name": "generated:seed"},
    )
    bank = SkillBank([skill])

    bank.apply_patches(
        [
            SkillPatch(
                patch_id="deprecate",
                action="deprecate",
                target_skill_id="cf_seed",
                lesson="no longer active",
            )
        ]
    )

    assert "deprecated" in bank.get("cf_seed").tags
    assert bank.retrieve(PlannerRequest.from_names(n_agents=8, objective="balanced")) == []
