from __future__ import annotations

from exp_graph.mas.schemas import SkillCard, SkillPatch

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.evolve import _curriculum_train_instances, _paired_skill_ablation


def _instance(case_id: str) -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id=case_id,
        case_name=case_id,
        n_agents=5,
        shards=[[1] for _ in range(5)],
        ground_truth=1,
        task_prompt="Combine private inputs: {input_shard}",
        meta={"num_agents": 5, "expected_outputs": [1] * 5},
    )


def _patch(name: str) -> SkillPatch:
    skill = SkillCard(
        skill_id=f"skill_{name}",
        task_family="silo",
        organization_policy={"topology_name": name},
    )
    return SkillPatch(
        patch_id=f"patch_{name}",
        action="merge",
        target_skill_id=skill.skill_id,
        candidate_skill=skill,
    )


def test_curriculum_keeps_every_level_present_and_grows() -> None:
    instances = [
        *[_instance(f"II-{index:02d}") for index in range(1, 4)],
        *[_instance(f"III-{index:02d}") for index in range(1, 4)],
    ]
    first, info = _curriculum_train_instances(
        instances,
        RunConfig(
            curriculum_enabled=True,
            curriculum_round=1,
            curriculum_total_rounds=3,
        ),
    )
    final, _ = _curriculum_train_instances(
        instances,
        RunConfig(
            curriculum_enabled=True,
            curriculum_round=3,
            curriculum_total_rounds=3,
        ),
    )

    assert {item.case_id.split("-", 1)[0] for item in first} == {"II", "III"}
    assert len(first) == 2
    assert len(final) == 6
    assert info["fraction"] == 1 / 3


def test_strict_paired_ablation_rejects_individual_loser() -> None:
    rows = []
    for seed in (1, 2):
        for topology, loss in (("winner", 0.2), ("loser", 0.8), ("control", 0.5)):
            rows.append(
                {
                    "case_id": "II-01",
                    "seed": seed,
                    "Agents": 5,
                    "information_goal": "all_agents",
                    "Topology": topology,
                    "mean_primary_loss": loss,
                }
            )

    kept, reports = _paired_skill_ablation(
        [_patch("winner"), _patch("loser")],
        rows,
        strict=True,
    )

    assert [patch.candidate_skill.skill_id for patch in kept] == ["skill_winner"]
    by_skill = {report["skill_id"]: report for report in reports}
    assert by_skill["skill_winner"]["wins"] == 2
    assert by_skill["skill_loser"]["losses"] == 2
    assert (
        kept[0].candidate_skill.confidence["paired_ablation"]["status"]
        == "accepted_improved"
    )
