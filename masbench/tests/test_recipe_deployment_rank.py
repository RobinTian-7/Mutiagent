"""Round-9 screen fix: a verified recipe must be able to win seeding.

The gen-mode screen banked 3 verified recipes that never deployed: minister
cards carry agent_counts + condition_key (specificity 12) and outranked the
recipe's bare trigger (~2), so the top-3 seeded replay slots never reached
it. Recipe cards now carry the same condition shape; among equal-specificity
cards the LCB loss (0.0 + 0.5/sqrt(2) = 0.354) beats typical minister cards.
"""

from __future__ import annotations

import json

from exp_graph.mas.schemas import ObjectiveSpec, PlannerRequest, SkillCard
from exp_graph.mas.skill_bank import SkillBank

from masbench.recipes import parse_recipe, recipe_skill_card

RECIPE = json.dumps({
    "name": "boundary_chain",
    "selected_primary": 4,
    "steps": [{"edges": [[0, 1], [1, 2], [2, 3], [3, 4]],
               "instruction": "compute your segment; forward boundary"}],
})


def _minister_card(skill_id: str, loss: float, n: int) -> SkillCard:
    return SkillCard(
        skill_id=skill_id, objective="balanced", task_family="silo",
        trigger={
            "task_family": "silo", "agent_counts": [5],
            "condition_key": f"{skill_id}::a5",
        },
        organization_policy={
            "topology_name": skill_id,
            "protocol_spec": {
                "name": skill_id, "n_agents": 5,
                "steps": [{"transmissions": [[0, 4]], "description": "x", "operator": "replay"}],
                "metadata": {},
            },
        },
        expected_tradeoff={"mean_primary_loss": loss, "active_evidence_count": n},
        confidence={"seed_count": n},
        tags=["mas", "silo"],
    )


def test_recipe_outranks_weaker_minister_cards_in_retrieval():
    spec = parse_recipe(RECIPE, n_agents=5, max_steps=7)
    recipe = recipe_skill_card(
        spec, task_family="silo", bucket="os", lossless_slot="lossless",
        n_agents=5, verify_count=2,
    )
    weak = _minister_card("one_peer_exponential_dag_star", loss=0.5, n=6)
    bank = SkillBank(skills=[weak, recipe])
    request = PlannerRequest(
        task_family="silo", n_agents=5, objective=ObjectiveSpec.from_name("balanced")
    )
    order = [s.skill_id for s in bank.retrieve(request)]
    # recipe LCB = 0 + .5/sqrt(2) = .354 < weak's .5 + .5/sqrt(6) = .704
    assert order.index(recipe.skill_id) < order.index(weak.skill_id), order
