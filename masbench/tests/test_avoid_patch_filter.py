"""Avoid-patch dominance filter (round-1 root cause).

``build_negative_patches``'s rule -- dominated iff ``loss > best * 1.75`` -- was
designed for continuous CF RMSE aggregates. On Silo's per-(case,seed) BINARY
rows the best row is usually 0.0, so EVERY topology with any failed case gets a
counterexample/avoid skill: round 1's bank advertised avoid_{mesh_star,
peer_star,tree} simultaneously (all topologies!), injecting contradictory
context that dragged held-out generation from 54.2% to 37.5%.

masbench therefore drops avoid patches unless the topology's MEAN primary loss
is at least ``AVOID_MEAN_LOSS_GAP`` (0.25 absolute) above the best topology's
mean -- an avoid rule must be earned by a real aggregate gap, not by one binary
miss. exp_graph's CF behavior is untouched.
"""
from masbench.evolve import AVOID_MEAN_LOSS_GAP, _filter_misfired_avoids, _is_avoid_patch
from exp_graph.mas.evolution import ResultAnalystMinister


def _row(topology: str, exact: float, case: str = "c1", seed: int = 1):
    return {
        "Topology": topology, "Agents": 5, "ArraySize": 0,
        "MergeMode": "llm_full_merge", "InitMode": "llm_local_solve", "Runs": 1,
        "MeanFinalRMSE": 1.0 - exact, "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": 0.0, "ExactMatchRate": exact,
        "MeanPrimaryMetric": exact, "PrimaryMetricName": "primary",
        "MeanTotalSteps": 3, "MeanTotalMessages": 10.0,
        "MeanTotalModelCalls": 5, "MeanTokenCost": 1000.0,
        "MeanVoteTopRatio": 1.0, "case_id": case, "seed": seed,
        "task_family": "silo", "mean_primary_loss": 1.0 - exact,
    }


def _patches(rows):
    return ResultAnalystMinister().analyze(rows, task_family="silo")


def test_tied_topologies_lose_all_avoid_patches():
    # Every topology solves c1 and fails c2 -> identical means -> NO avoids.
    rows = []
    for topo in ("tree", "mesh_star", "one_peer_exponential_dag_star"):
        rows.append(_row(topo, 1.0, "c1"))
        rows.append(_row(topo, 0.0, "c2"))
    patches = _patches(rows)
    assert any(_is_avoid_patch(p) for p in patches), "minister misfires pre-filter"
    kept = _filter_misfired_avoids(patches, rows)
    assert not [p for p in kept if _is_avoid_patch(p)]
    assert [p for p in kept if not _is_avoid_patch(p)], "positives survive"


def test_clearly_worse_topology_keeps_its_avoid_patch():
    rows = []
    for case in ("c1", "c2", "c3", "c4"):
        rows.append(_row("tree", 0.0, case))            # mean loss 1.0
        rows.append(_row("mesh_star", 1.0, case))        # mean loss 0.0
    patches = _patches(rows)
    kept = _filter_misfired_avoids(patches, rows)
    avoid_skill_ids = [str(p.candidate_skill.skill_id) for p in kept if _is_avoid_patch(p)]
    assert any("tree" in sid for sid in avoid_skill_ids), "real dominance must survive"
    assert not any("mesh_star" in sid for sid in avoid_skill_ids)


def test_gap_threshold_is_the_declared_constant():
    assert AVOID_MEAN_LOSS_GAP == 0.25


def test_underpowered_champion_cannot_anchor_dominance():
    """P2 round-1 bug: a single explored run at loss 0.0 became the dominance
    champion and EVERY named topology (incl. the deployed winner) got an avoid
    skill. The best-mean anchor must itself be well-measured (n >= 3)."""
    rows = []
    for case in ("c1", "c2", "c3"):
        for topo in ("tree", "mesh_star", "one_peer_exponential_dag_star"):
            rows.append(_row(topo, 1.0 if case == "c1" else 0.0, case))  # mean loss 0.667
    rows.append(_row("generated:lucky", 1.0, "c1"))  # n=1, loss 0.0 -> not a valid anchor
    patches = _patches(rows)
    kept = _filter_misfired_avoids(patches, rows)
    avoid_skill_ids = [str(p.candidate_skill.skill_id) for p in kept if _is_avoid_patch(p)]
    assert not avoid_skill_ids, f"n=1 champion must not anchor avoids, got {avoid_skill_ids}"


def test_well_measured_champion_still_anchors():
    rows = []
    for case in ("c1", "c2", "c3", "c4"):
        rows.append(_row("mesh_star", 1.0, case))   # n=4, loss 0.0 -> valid anchor
        rows.append(_row("tree", 0.0, case))         # n=4, loss 1.0 -> dominated
    kept = _filter_misfired_avoids(_patches(rows), rows)
    avoid_skill_ids = [str(p.candidate_skill.skill_id) for p in kept if _is_avoid_patch(p)]
    assert any("tree" in sid for sid in avoid_skill_ids)
