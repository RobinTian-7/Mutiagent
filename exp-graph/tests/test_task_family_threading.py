"""Tests for threading ``task_family`` through the minister/skill-creation path.

The ResultAnalyst (and the other ministers) historically hardcoded
``count_frequency`` on every emitted skill card and trigger. These tests pin down
two behaviors:

1. **CF default is byte-identical.** Calling ``analyze(rows)`` with no
   ``task_family`` argument still emits exactly the CF skill_ids and
   ``task_family == "count_frequency"`` it always did.
2. **Family threading is native.** Calling ``analyze(rows, task_family="silo")``
   emits skills tagged ``silo`` (card + trigger), retrievable by a silo
   ``PlannerRequest`` but never by a ``count_frequency`` one. Because the
   ``SkillBank`` keys by ``skill_id``, non-CF ids are namespaced by family so a
   CF skill and a silo skill for the same topology can coexist in one bank.
"""

from __future__ import annotations

from exp_graph.mas.evolution import (
    ResultAnalystMinister,
    make_skill_card,
)
from exp_graph.mas.schemas import ObjectiveSpec, PlannerRequest
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


def _cf_rows() -> list[dict]:
    return [
        _row("one_peer_exponential_dag_star", 0.02, 31.0),
        _row("tree", 0.10, 7.0),
        _row("random", 0.60, 12.0),
    ]


# Baseline captured from the current (pre-change) ResultAnalyst on ``_cf_rows``.
_EXPECTED_CF_SKILL_IDS = {
    "cf_accuracy_peer_star",
    "cf_topology_random",
    "cf_budget_tree",
    "cf_avoid_random",
    "cf_avoid_tree",
}


def test_default_analyze_is_count_frequency_and_keeps_cf_skill_ids() -> None:
    """Default call (no task_family) is byte-identical to the CF era."""
    patches = ResultAnalystMinister().analyze(_cf_rows())

    skill_ids = {
        patch.candidate_skill.skill_id
        for patch in patches
        if patch.candidate_skill is not None
    }
    assert skill_ids == _EXPECTED_CF_SKILL_IDS

    for patch in patches:
        card = patch.candidate_skill
        assert card is not None
        assert card.task_family == "count_frequency"
        assert card.trigger["task_family"] == "count_frequency"


def test_explicit_count_frequency_matches_default() -> None:
    """Passing the default family explicitly yields identical skill cards."""
    default_patches = ResultAnalystMinister().analyze(_cf_rows())
    explicit_patches = ResultAnalystMinister().analyze(
        _cf_rows(), task_family="count_frequency"
    )
    assert [p.model_dump() for p in default_patches] == [
        p.model_dump() for p in explicit_patches
    ]


def test_analyze_silo_family_tags_cards_and_triggers() -> None:
    """analyze(..., task_family='silo') tags every card + trigger as silo."""
    patches = ResultAnalystMinister().analyze(_cf_rows(), task_family="silo")
    assert patches  # sanity: we did emit something
    for patch in patches:
        card = patch.candidate_skill
        assert card is not None
        assert card.task_family == "silo"
        assert card.trigger["task_family"] == "silo"


def test_silo_skills_retrievable_only_by_silo_request() -> None:
    """A bank built from silo patches is retrieved by silo, not by CF, requests."""
    patches = ResultAnalystMinister().analyze(_cf_rows(), task_family="silo")
    bank = SkillBank(
        [
            patch.candidate_skill
            for patch in patches
            if patch.candidate_skill is not None
        ]
    )

    silo_request = PlannerRequest(
        task_family="silo",
        n_agents=8,
        array_size=256,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )
    cf_request = PlannerRequest(
        task_family="count_frequency",
        n_agents=8,
        array_size=256,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )

    silo_matches = bank.retrieve(silo_request)
    cf_matches = bank.retrieve(cf_request)

    assert silo_matches, "silo request must retrieve the natively-tagged silo skills"
    assert all(skill.task_family == "silo" for skill in silo_matches)
    assert cf_matches == [], "count_frequency request must not see silo skills"


def test_cf_and_silo_skills_coexist_without_collision() -> None:
    """Same topology in two families must not collide in one SkillBank dict.

    The bank keys by ``skill_id``; if non-CF ids were not namespaced, the silo
    ``cf_accuracy_peer_star`` would overwrite the CF one. Threading a distinct
    family must therefore keep both retrievable.
    """
    cf_patches = ResultAnalystMinister().analyze(_cf_rows())
    silo_patches = ResultAnalystMinister().analyze(_cf_rows(), task_family="silo")

    bank = SkillBank()
    for patch in [*cf_patches, *silo_patches]:
        if patch.candidate_skill is not None:
            bank.skills[patch.candidate_skill.skill_id] = patch.candidate_skill

    cf_selectable = {
        skill.skill_id for skill in bank if skill.task_family == "count_frequency"
    }
    silo_selectable = {
        skill.skill_id for skill in bank if skill.task_family == "silo"
    }

    # No id is shared between the two families (namespacing for non-CF).
    assert cf_selectable.isdisjoint(silo_selectable)
    # Both families keep one entry per emitted skill (no overwrite).
    assert len(cf_selectable) == len(
        {p.candidate_skill.skill_id for p in cf_patches if p.candidate_skill}
    )
    assert len(silo_selectable) == len(
        {p.candidate_skill.skill_id for p in silo_patches if p.candidate_skill}
    )

    # And each family is retrievable on its own request.
    silo_request = PlannerRequest(
        task_family="silo",
        n_agents=8,
        array_size=256,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )
    cf_request = PlannerRequest(
        task_family="count_frequency",
        n_agents=8,
        array_size=256,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )
    assert all(s.task_family == "silo" for s in bank.retrieve(silo_request))
    assert all(
        s.task_family == "count_frequency" for s in bank.retrieve(cf_request)
    )


def test_make_skill_card_threads_non_cf_family_and_namespaces_id() -> None:
    """make_skill_card stamps the family and namespaces non-CF ids directly."""
    cf_card = make_skill_card(
        skill_id="cf_accuracy_peer_star",
        topology_name="one_peer_exponential_dag_star",
        objective="accuracy_first",
        operators=["local_solve"],
        evidence=[],
        expected_tradeoff={},
    )
    assert cf_card.task_family == "count_frequency"
    assert cf_card.skill_id == "cf_accuracy_peer_star"
    assert cf_card.trigger["task_family"] == "count_frequency"

    silo_card = make_skill_card(
        skill_id="cf_accuracy_peer_star",
        topology_name="one_peer_exponential_dag_star",
        objective="accuracy_first",
        operators=["local_solve"],
        evidence=[],
        expected_tradeoff={},
        task_family="silo",
    )
    assert silo_card.task_family == "silo"
    assert silo_card.trigger["task_family"] == "silo"
    # Namespaced so it cannot collide with the CF card in a SkillBank dict.
    assert silo_card.skill_id != cf_card.skill_id
    assert silo_card.skill_id.startswith("silo")
