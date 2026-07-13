"""Hot-start pretraining and paired reuse/innovation evolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from exp_graph.mas.schemas import (
    NamedTopologySkillPayload,
    ObjectiveSpec,
    PaperTransportSkillPayload,
    PlannerRequest,
    SkillCard,
)
from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import _resolve_hot_start_settings, run_evolution

DATA = Path(__file__).parent / "data"


def _cfg(**updates) -> RunConfig:
    values = {
        "use_planner": True,
        "use_skill_evolution": True,
        "llm_provider": "fake",
        "model_name": "fake",
        "merge_mode": "deterministic",
        "init_mode": "deterministic",
        "objective": "accuracy_first",
        "planner_mode": "topology_select",
        "evolved_mode": "topology_select",
        "evidence_portfolio": "",
        "hot_start_enabled": True,
        "hot_start_protocols": "",
        "hot_start_topologies": "mesh",
        "hot_start_seed_count": 1,
        "hot_start_dual_branch": True,
        "hot_start_innovation_mode": "graph_generate",
        "num_graph_candidates": 1,
    }
    values.update(updates)
    return RunConfig(**values)


def _run(cfg: RunConfig, **kwargs):
    return run_evolution(
        SiloBenchAdapter(DATA),
        cases=["I-01"],
        levels=["I"],
        agent_counts=[2],
        train_seeds=[1],
        val_seeds=[2],
        cfg=cfg,
        workers=1,
        progress=False,
        **kwargs,
    )


def test_hot_start_seeds_fixed_skill_and_runs_both_branches() -> None:
    summary = _run(_cfg())

    hot = summary["hot_start"]
    assert summary["clean_run"] is False
    assert hot["pretraining"]["status"] == "seeded"
    assert hot["pretraining"]["n_fixed_rows"] == 1
    assert hot["pretraining"]["n_protocol_rows"] == 0
    assert hot["dual_branch"]["n_pairs_requested"] == 1
    assert hot["dual_branch"]["branches"]["reuse"]["n_rows"] == 1
    assert hot["dual_branch"]["branches"]["innovation"]["n_rows"] == 1
    assert hot["dual_branch"]["cost"]["runs"] == 2
    assert summary["n_explore_rows"] == 0

    seeded = [
        SkillCard.model_validate(raw)
        for raw in summary["evolved_skills"]
        if "hot-start" in raw.get("tags", [])
    ]
    assert seeded
    assert any("executable-seed" in skill.tags for skill in seeded)
    assert any(
        isinstance(skill.organization_policy.get("protocol_spec"), dict)
        for skill in seeded
    )
    assert all(
        isinstance(skill.organization_policy.get("structure_code"), dict)
        for skill in seeded
    )
    assert all(skill.design_insights for skill in seeded)
    assert all(skill.evidence for skill in seeded)


def test_all_agents_auto_hot_start_is_exactly_five_primary_skills() -> None:
    summary = _run(
        _cfg(
            silo_eval_mode="all_agents",
            max_rounds=1,
            hot_start_protocols="auto",
            hot_start_topologies="auto",
            hot_start_dual_branch=False,
        )
    )
    pretraining = summary["hot_start"]["pretraining"]
    assert pretraining["protocols"] == ["p2p", "broadcast", "sfs"]
    assert pretraining["topologies"] == [
        "one_peer_exponential_dag",
        "static_exponential",
    ]
    assert pretraining["n_pretrain_rows"] == 5
    assert len(pretraining["seeded_skill_ids"]) == 5

    hot_cards = [
        SkillCard.model_validate(raw)
        for raw in summary["evolved_skills"]
        if "hot-start" in raw.get("tags", [])
    ]
    assert len(hot_cards) == 5
    for card in hot_cards:
        code = card.organization_policy.get("structure_code")
        assert isinstance(code, dict) and code.get("source")
        assert card.design_insights
        assert card.evidence
        assert card.expected_dynamics["hot_start_evidence_summary"]
    assert sum(
        isinstance(card.mode_payload, PaperTransportSkillPayload)
        for card in hot_cards
    ) == 3
    assert sum(
        isinstance(card.mode_payload, NamedTopologySkillPayload)
        for card in hot_cards
    ) == 2
    audit = summary["skill_payload_audit"]["deployed"]
    assert audit["format_counts"]["paper_transport_skill_v1"] == 3
    assert audit["format_counts"]["named_topology_skill_v1"] >= 2
    assert audit["missing_generated_payload_skill_ids"] == []
    assert "mode_payload" in audit["iterative_fields"]
    assert "reasoning_policy" in audit["iterative_fields"]


def test_sink_auto_hot_start_uses_gathering_fixed_portfolio() -> None:
    instance = next(
        SiloBenchAdapter(DATA).iter_instances(cases=["I-01"], agent_counts=[2])
    )
    settings = _resolve_hot_start_settings(
        _cfg(hot_start_protocols="auto", hot_start_topologies="auto"),
        [instance],
    )
    assert settings["protocols"] == []
    assert settings["topologies"] == [
        "one_peer_exponential_dag_star",
        "mesh_star",
        "star",
        "chain",
        "tree",
        "two_stage_layer",
        "balanced_log_layer",
    ]


def test_hot_start_pretraining_is_not_repaid_on_next_round() -> None:
    first = _run(_cfg())
    second = _run(_cfg(), initial_skills=first["evolved_skills"])

    pretraining = second["hot_start"]["pretraining"]
    assert pretraining["status"] == "reused_existing_seed"
    assert pretraining["n_pretrain_rows"] == 0
    assert pretraining["cost"]["runs"] == 0
    # The per-task improve/expand pair still runs every evolution round.
    assert second["hot_start"]["dual_branch"]["cost"]["runs"] == 2


def test_paper_protocol_pretraining_creates_context_only_skill() -> None:
    summary = _run(
        _cfg(
            silo_eval_mode="all_agents",
            max_rounds=1,
            hot_start_protocols="p2p",
            hot_start_topologies="",
            hot_start_dual_branch=False,
        )
    )
    cards = [SkillCard.model_validate(raw) for raw in summary["evolved_skills"]]
    paper = next(
        card
        for card in cards
        if card.organization_policy.get("dynamic_transport") == "p2p"
    )
    assert {"hot-start", "hot-start-protocol", "reference-only"} <= set(paper.tags)
    assert paper.organization_policy["replayable"] is False
    assert paper.organization_policy.get("protocol_spec") is None
    assert isinstance(paper.mode_payload, PaperTransportSkillPayload)
    assert paper.mode_payload.protocol == "p2p"

    request = PlannerRequest(
        task_family="silo",
        n_agents=2,
        objective=ObjectiveSpec.from_name("balanced"),
        planner_mode="topology_select",
        information_goal="all_agents",
    )
    bank = SkillBank(cards)
    assert paper not in bank.retrieve(request)
    assert bank.retrieve_generation_context(
        request.model_copy(update={"include_reference_skills": True})
    )


def test_paper_protocol_skill_executes_in_hot_start_reuse_branch() -> None:
    summary = _run(
        _cfg(
            silo_eval_mode="all_agents",
            max_rounds=1,
            hot_start_protocols="p2p",
            hot_start_topologies="",
            hot_start_dual_branch=True,
        )
    )
    reuse = summary["hot_start"]["dual_branch"]["branches"]["reuse"]
    assert reuse["n_rows"] == 1
    assert reuse["outputs"][0]["topology"] == "paper_p2p"
    assert reuse["outputs"][0]["parent_skill_id"]
    assert reuse["cost"]["model_calls"] == 2


def test_explicit_paper_protocol_hot_start_rejects_sink_mode() -> None:
    with pytest.raises(ValueError, match="all_agents"):
        _run(_cfg(hot_start_protocols="p2p"))


def test_cli_parses_hot_start_controls() -> None:
    from masbench.cli import build_parser

    args = build_parser().parse_args(
        [
            "evolve",
            "--hot-start",
            "--hot-start-protocols",
            "p2p,broadcast",
            "--hot-start-topologies",
            "one_peer_exponential_dag,static_exponential",
            "--hot-start-seed-count",
            "2",
            "--hot-start-innovation-mode",
            "program_generate",
            "--out",
            "unused",
        ]
    )
    assert args.hot_start_enabled is True
    assert args.hot_start_protocols == "p2p,broadcast"
    assert args.hot_start_topologies == (
        "one_peer_exponential_dag,static_exponential"
    )
    assert args.hot_start_seed_count == 2
    assert args.hot_start_innovation_mode == "program_generate"
