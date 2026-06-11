"""Round-10 deployment stability: dedupe keeps instruction-bearing twins,
replay-first excludes fresh candidates, motif displacement needs a margin.

dev-6 evidence: refine r2 +20.8pp (7:2) then r3 reshuffled the deployment
among near-tied candidates and scored 0; the gen-mode PASS deployed a
verified recipe whose instructions had been silently stripped by the
structural-dedupe representative choice (bare twin's candidate_id sorted
first).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from exp_graph.mas.graph_generation import plan_free_graph
from exp_graph.mas.schemas import MASRuntimeConfig, ObjectiveSpec, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank

from masbench.recipes import parse_recipe, recipe_skill_card

RECIPE = json.dumps({
    "name": "boundary_chain", "selected_primary": 1,
    "steps": [{"edges": [[0, 1]], "instruction": "compute segment; forward boundary"}],
})


def _bank() -> SkillBank:
    spec = parse_recipe(RECIPE, n_agents=2, max_steps=4)
    card = recipe_skill_card(
        spec, task_family="silo", bucket="os", lossless_slot="lossless",
        n_agents=2, verify_count=2,
    )
    return SkillBank(skills=[card])


def _plan(runtime: MASRuntimeConfig):
    request = PlannerRequest(
        task_family="silo", n_agents=2,
        objective=ObjectiveSpec.from_name("accuracy_first"),
        planner_mode="graph_generate",
    )
    with tempfile.TemporaryDirectory() as td:
        return plan_free_graph(
            request=request, runtime=runtime, skill_bank=_bank(), seed=0,
            task_adapter=None, output_dir=Path(td), llm_client=None,
        )


def test_dedupe_keeps_instruction_bearing_twin():
    """The fake offline candidate is structurally identical at n=2; the
    representative must be the instruction-bearing seeded replay."""
    runtime = MASRuntimeConfig(
        llm_provider="fake", model_name="fake", num_graph_candidates=2,
        use_motif_prior=True,
    )
    res = _plan(runtime)
    assert res.selected_candidate_id.startswith("skill_")
    assert [s.instruction for s in res.plan.protocol_spec.steps] == [
        "compute segment; forward boundary"
    ]


def test_replay_first_excludes_fresh_candidates():
    runtime = MASRuntimeConfig(
        llm_provider="fake", model_name="fake", num_graph_candidates=3,
        use_motif_prior=True, replay_first=True,
    )
    res = _plan(runtime)
    assert res.selected_candidate_id.startswith("skill_")


def test_motif_displacement_requires_margin():
    from exp_graph.mas.graph_generation import _select_candidate
    from exp_graph.mas import graph_generation as gg

    class _State:
        def __init__(self, cid, spec):
            self.spec = spec

            class R:
                candidate_id = cid
            self.record = R()

    incumbent_spec = parse_recipe(RECIPE, n_agents=2, max_steps=4)
    challenger_spec = parse_recipe(json.dumps({
        "name": "challenger", "selected_primary": 0,
        "steps": [
            {"edges": [[0, 1]], "instruction": "x"},
            {"edges": [[1, 0]], "instruction": "y"},
        ],
    }), n_agents=2, max_steps=4)
    incumbent = _State("skill_a", incumbent_spec)
    challenger = _State("skill_b", challenger_spec)

    from exp_graph.mas.motifs import spec_motif_keys
    inc_keys = spec_motif_keys(incumbent_spec)
    cha_keys = [k for k in spec_motif_keys(challenger_spec) if k not in set(inc_keys)]
    # challenger barely better (0.05 advantage) -> sticky incumbent holds
    stats = {inc_keys[0]: {"mean_loss": 0.50, "n": 9}}
    for k in cha_keys:
        stats[k] = {"mean_loss": 0.45, "n": 9}
    def _runtime(cha_loss: float, margin: float) -> MASRuntimeConfig:
        s = dict(stats)
        for k in cha_keys:
            s[k] = {"mean_loss": cha_loss, "n": 9}
        return MASRuntimeConfig(
            llm_provider="fake", model_name="fake", use_motif_prior=True,
            motif_stats=s, motif_displacement_margin=margin,
        )

    # challenger barely better -> sticky incumbent holds
    assert _select_candidate([incumbent, challenger], _runtime(0.45, 0.1)) is incumbent
    # clearly better (>= margin advantage) -> displacement allowed
    assert _select_candidate([incumbent, challenger], _runtime(0.15, 0.1)) is challenger
    # margin 0 (historical behavior): even hair-thin advantage displaces
    assert _select_candidate([incumbent, challenger], _runtime(0.45, 0.0)) is challenger


def test_m14_preserve_skips_rewrite_modify_rewrites():
    """dev-8 4-arm: unconditional rewriting dragged a 41.7% bare structure to
    33.3%. Direct-slot-trusted deployments (Preserve) keep the proven
    artifact verbatim; tier-2 transfers (Modify) get rewritten."""
    from exp_graph.mas.graph_generation import (
        _graph_from_skill_protocol,
        _rewrite_replay_instructions,
    )
    from exp_graph.protocols.spec import ProtocolGraphSpec
    from masbench.transfer import deployment_view
    from exp_graph.mas.schemas import SkillCard

    def _card(skill_id, ledger):
        return SkillCard(
            skill_id=skill_id, objective="balanced", task_family="silo",
            trigger={"task_family": "silo"},
            organization_policy={
                "topology_name": skill_id,
                "protocol_spec": {
                    "name": skill_id, "n_agents": 2,
                    "steps": [{"transmissions": [[0, 1]], "description": "x",
                               "operator": "replay", "instruction": "stored role"}],
                    "metadata": {"selected_primary": 1},
                },
                "transfer_evidence": ledger,
            },
            expected_tradeoff={"mean_primary_loss": 0.1},
            tags=["mas", "silo"],
        )

    direct = _card("direct", {
        "os": {"n": 2, "em_sum": 2.0}, "os#lossless": {"n": 2, "em_sum": 2.0},
    })
    generalist = _card("generalist", {
        "of": {"n": 6, "em_sum": 5.0},
        "of#lossy": {"n": 3, "em_sum": 3.0}, "of#lossless": {"n": 3, "em_sum": 2.0},
    })
    # kind tier -> preserve
    view, _, _, tier = deployment_view(
        SkillBank(skills=[direct]), None, "os", kind="lossless", fallback_tier=True,
    )
    assert tier == "kind"
    s = next(iter(view))
    assert s.organization_policy["deploy_action"] == "preserve"
    spec = ProtocolGraphSpec.model_validate(s.organization_policy["protocol_spec"])
    plan = _graph_from_skill_protocol(s, spec)
    assert plan.allow_instruction_rewrite is False
    # breadth extrapolation (no direct slot evidence) -> modify
    view2, _, _, tier2 = deployment_view(
        SkillBank(skills=[generalist]), None, "of", kind="other-slot",
        fallback_tier=True,
    )
    s2 = next(iter(view2))
    assert s2.organization_policy["deploy_action"] == "modify"
    spec2 = ProtocolGraphSpec.model_validate(s2.organization_policy["protocol_spec"])
    plan2 = _graph_from_skill_protocol(s2, spec2)
    assert plan2.allow_instruction_rewrite is True

    # Preserve-marked plans are excluded from the rewrite pass entirely.
    class _Boom:
        def complete(self, *a, **k):
            raise AssertionError("rewrite must not be called for preserve plans")

    from exp_graph.mas.schemas import MASRuntimeConfig
    runtime = MASRuntimeConfig(
        llm_provider="openai", model_name="m", replay_instruction_rewrite=True,
    )
    _rewrite_replay_instructions([plan], runtime=runtime, llm_client=_Boom(), task_brief="t")
    assert plan.steps[0].instruction == "stored role"


def test_m15_gen_mode_portfolio_includes_named_aggregators():
    from masbench.evolve import _portfolio_topologies
    from masbench.core.config import RunConfig

    gen_cfg = RunConfig(planner_mode="graph_generate")
    topos = _portfolio_topologies(gen_cfg)
    assert "chain" in topos and "one_peer_exponential_dag_star" in topos
    assert "tree" in topos and "mesh_star" in topos
    refine_cfg = RunConfig(planner_mode="topology_select")
    assert _portfolio_topologies(refine_cfg) == ["chain"]
