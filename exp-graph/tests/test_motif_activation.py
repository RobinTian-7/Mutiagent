"""Activation of the structural-motif credit prior in candidate selection.

Plan 4 Task 5 (#2).  Plan 3 Part G built the motif machinery
(``exp_graph.mas.motifs``) and unit-proved it in ``tests/test_motifs.py`` but did
NOT wire it into graph-candidate selection -- ``graph_generation._evaluate_candidates``
carried only an ``# Activation point`` comment.  These tests prove the OPT-IN
wiring: when ``MASRuntimeConfig.use_motif_prior`` is on and ``motif_stats`` is
supplied, ``plan_free_graph`` ranks valid compiled candidates by their
motif-predicted loss (lower = better); when off (the default) selection is
byte-identical to today's first-valid behavior.

The fake-emperor path (``llm_provider="fake"``) deterministically emits a tree,
a star, and a chain candidate (after equivalence dedup) for n_agents=4.  The
tree (generation index 0) is today's default pick.  The star has a distinct
``fan_in_bucket=med`` motif while the tree/chain share ``fan_in_bucket=low``, so
crafted motif_stats that reward ``fan_in_bucket=med`` must flip the selection
from the tree to the star -- proving credit transfers through structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exp_graph.mas.graph_generation import (
    GraphValidationOptions,
    _fake_graph_candidates,
    _validate_and_compile_candidates,
    plan_free_graph,
)
from exp_graph.mas.motifs import spec_motif_keys
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.tasks import CountFrequencyTaskAdapter


def _fake_request() -> PlannerRequest:
    return PlannerRequest.from_names(
        n_agents=4,
        array_size=8,
        planner_mode="graph_generate",
    )


def _fake_valid_specs() -> dict[str, object]:
    """Compiled specs for the deterministic fake-emperor candidates (n_agents=4).

    Returned keyed by candidate_id so a test can read each candidate's motif
    keys to design discriminating stats.
    """
    options = GraphValidationOptions(n_agents=4)
    graphs = _fake_graph_candidates(_fake_request(), 4)
    states = _validate_and_compile_candidates(graphs, options)
    return {
        state.record.candidate_id: state.spec
        for state in states
        if state.spec is not None
    }


def test_motif_prior_off_unchanged(tmp_path: Path) -> None:
    """Default (use_motif_prior=False) selects today's first-valid candidate.

    Over >=2 fake candidates the tree (candidate_0, generation index 0) is the
    historical default pick; the prior is off so even motif_stats that would
    otherwise reward the star must NOT change the selection.
    """
    specs = _fake_valid_specs()
    # Stats that would reward the star (fan_in_bucket=med) over the tree
    # (fan_in_bucket=low) IF the prior were active -- it is not.
    biased_stats = {
        "fan_in_bucket=med": {"mean_loss": 0.01, "n": 10},
        "fan_in_bucket=low": {"mean_loss": 0.99, "n": 10},
    }

    result = plan_free_graph(
        request=_fake_request(),
        runtime=MASRuntimeConfig(
            llm_provider="fake",
            graph_search_mode="single",
            num_graph_candidates=4,
            use_motif_prior=False,  # default; spelled out for emphasis
            motif_stats=biased_stats,
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )

    # Today's behavior: first valid candidate after dedup is the tree.
    assert result.selected_candidate_id == "candidate_0"
    assert result.plan.protocol_spec.name == "generated_tree_reduce_n4"
    # Sanity: the star really is a distinct candidate that the biased stats
    # would have preferred, so the assertion above is a real no-op proof.
    assert "candidate_1" in specs
    assert "fan_in_bucket=med" in spec_motif_keys(specs["candidate_1"])


def test_motif_prior_off_without_stats_unchanged(tmp_path: Path) -> None:
    """use_motif_prior=True but motif_stats=None is inert (single-run plan path).

    This mirrors masbench's single-run ``_plan_graph_generate``: the flag is on
    but no Silo evidence exists yet, so motif_stats is None and selection must
    stay byte-identical to the default first-valid pick.
    """
    result = plan_free_graph(
        request=_fake_request(),
        runtime=MASRuntimeConfig(
            llm_provider="fake",
            graph_search_mode="single",
            num_graph_candidates=4,
            use_motif_prior=True,
            motif_stats=None,
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )

    assert result.selected_candidate_id == "candidate_0"
    assert result.plan.protocol_spec.name == "generated_tree_reduce_n4"


def test_motif_prior_on_prefers_good_motif(tmp_path: Path) -> None:
    """With the prior ON, the candidate with the better (lower) motif loss wins.

    Craft motif_stats that assign LOW loss to a motif present only in the star
    (``fan_in_bucket=med``) and HIGH loss to the motif shared by the tree/chain
    (``fan_in_bucket=low``).  The default pick is the tree (candidate_0); the
    prior must flip the selection to the star (candidate_1).
    """
    specs = _fake_valid_specs()
    # Confirm the discriminating motif before relying on it.
    assert "fan_in_bucket=med" in spec_motif_keys(specs["candidate_1"])  # star
    assert "fan_in_bucket=low" in spec_motif_keys(specs["candidate_0"])  # tree
    assert "fan_in_bucket=low" in spec_motif_keys(specs["candidate_2"])  # chain

    motif_stats = {
        "fan_in_bucket=med": {"mean_loss": 0.02, "n": 8},
        "fan_in_bucket=low": {"mean_loss": 0.95, "n": 8},
    }

    result = plan_free_graph(
        request=_fake_request(),
        runtime=MASRuntimeConfig(
            llm_provider="fake",
            graph_search_mode="single",
            num_graph_candidates=4,
            use_motif_prior=True,
            motif_stats=motif_stats,
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )

    # The star (fan_in_bucket=med, low predicted loss) beats the default tree.
    assert result.selected_candidate_id == "candidate_1"
    assert result.plan.protocol_spec.name == "generated_star_sink_n4"


def test_motif_prior_single_candidate_unchanged(tmp_path: Path) -> None:
    """With a single candidate the prior cannot change the (only) selection."""
    result = plan_free_graph(
        request=_fake_request(),
        runtime=MASRuntimeConfig(
            llm_provider="fake",
            graph_search_mode="single",
            num_graph_candidates=1,
            use_motif_prior=True,
            motif_stats={"fan_in_bucket=low": {"mean_loss": 0.99, "n": 5}},
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )

    # Only the tree is generated for num_graph_candidates=1; it is selected
    # regardless of the (punitive) motif stats for its own bucket.
    assert result.selected_candidate_id == "candidate_0"
    assert result.plan.protocol_spec.name == "generated_tree_reduce_n4"


def test_motif_prior_on_unknown_motif_keeps_default(tmp_path: Path) -> None:
    """When no candidate shares a known motif key, the default order is kept.

    ``score_spec_by_motifs`` returns +inf (high-uncertainty sentinel) for every
    candidate, so the prior must not reorder -- the default first-valid tree
    stays selected rather than an arbitrary inf-tie winner.
    """
    result = plan_free_graph(
        request=_fake_request(),
        runtime=MASRuntimeConfig(
            llm_provider="fake",
            graph_search_mode="single",
            num_graph_candidates=4,
            use_motif_prior=True,
            motif_stats={"never_seen_feature=zzz": {"mean_loss": 0.1, "n": 9}},
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )

    assert result.selected_candidate_id == "candidate_0"
    assert result.plan.protocol_spec.name == "generated_tree_reduce_n4"
