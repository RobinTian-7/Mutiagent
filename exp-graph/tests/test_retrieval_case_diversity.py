"""M19a (dev-11): retrieval pessimism over case diversity.

A 2-row single-case perfect score (LCB 0+0.5/sqrt(2)=0.354) outranked a
multi-case generalist and hijacked winner-take-all replay. Cards now carry
``expected_tradeoff.evidence_case_count`` (stamped by masbench's transfer
ledger); retrieval adds ``RETRIEVAL_CASE_KAPPA / case_count``. Cards
without the field (all CF cards) keep their exact historical value.
"""

from __future__ import annotations

import math

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import (
    RETRIEVAL_CASE_KAPPA,
    RETRIEVAL_LCB_KAPPA,
    _skill_retrieval_loss,
)


def _card(skill_id: str, loss: float, n: int, cases: int | None):
    tradeoff = {"mean_primary_loss": loss, "active_evidence_count": n}
    if cases is not None:
        tradeoff["evidence_case_count"] = cases
    return SkillCard(
        skill_id=skill_id,
        objective="balanced",
        task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy={"planner_mode": "graph_generate"},
        expected_tradeoff=tradeoff,
        confidence={"seed_count": n},
        tags=["mas"],
    )


def test_multi_case_generalist_outranks_single_case_perfect():
    recipe = _card("recipe", loss=0.0, n=2, cases=1)
    generalist = _card("one_peer", loss=0.30, n=20, cases=7)
    assert _skill_retrieval_loss(generalist) < _skill_retrieval_loss(recipe)


def test_absent_field_keeps_historical_value():
    card = _card("legacy", loss=0.2, n=4, cases=None)
    expected = 0.2 + RETRIEVAL_LCB_KAPPA / math.sqrt(4)
    assert _skill_retrieval_loss(card) == expected


def test_case_term_value():
    card = _card("x", loss=0.0, n=4, cases=2)
    expected = 0.0 + RETRIEVAL_LCB_KAPPA / math.sqrt(4) + RETRIEVAL_CASE_KAPPA / 2
    assert abs(_skill_retrieval_loss(card) - expected) < 1e-12
