"""M21: graded trust currency (jssp-easy forensics).

The trust ledger read binary ExactMatchRate; on quality-graded benchmarks
(JSSP: quality = UB/makespan) the learner could never earn deployment
trust (a 23%-quality schedule counted as total failure) and abstained
forever -- evolution ran but never deployed. _row_em now prefers the
benchmark's own MeanPrimaryMetric. Silo invariance is pinned: silo rows
carry MeanPrimaryMetric == ExactMatchRate by construction.
"""

from __future__ import annotations

from pathlib import Path

from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.skill_bank import SkillBank
from masbench.adapters.jssp_bench import JSSPBenchAdapter
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import _run_one, evolution_objective_spec
from masbench.transfer import _row_em, build_transfer_ledger

DATA = Path(__file__).parent / "data"


def _cfg(n_agents: int) -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate",
        num_graph_candidates=2, n_agents=n_agents,
    )


def test_silo_rows_have_equal_primary_and_em():
    # the M21 invariance condition: switching the ledger to
    # MeanPrimaryMetric is byte-identical on Silo because the two fields
    # are equal on every silo row
    inst = next(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )
    cfg = _cfg(2)
    row = _run_one(
        inst, cfg, objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(), seed=3,
        llm_client=create_llm_client("fake"), motif_stats=None,
    )
    assert "MeanPrimaryMetric" in row
    assert float(row["MeanPrimaryMetric"]) == float(row["ExactMatchRate"])
    assert _row_em(row) == float(row["ExactMatchRate"])


def test_jssp_row_em_prefers_quality():
    inst = next(iter(JSSPBenchAdapter(DATA / "jssp").iter_instances(cases=["tiny2x2"])))
    cfg = _cfg(inst.n_agents)
    row = _run_one(
        inst, cfg, objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(), seed=3,
        llm_client=create_llm_client("fake"), motif_stats=None,
    )
    assert "MeanPrimaryMetric" in row
    assert _row_em(row) == float(row["MeanPrimaryMetric"])


def test_ledger_accrues_graded_credit():
    rows = [
        {"Topology": "generated:org", "task_features_key": "of",
         "task_needs_lossless": True, "task_answer_composite": True,
         "case_id": "synA", "ExactMatchRate": 0.0, "MeanPrimaryMetric": 0.8},
        {"Topology": "generated:org", "task_features_key": "of",
         "task_needs_lossless": True, "task_answer_composite": True,
         "case_id": "synB", "ExactMatchRate": 0.0, "MeanPrimaryMetric": 0.6},
    ]
    ledger = build_transfer_ledger(rows)
    slot = ledger["generated:org"]["of"]
    assert slot["n"] == 2
    assert abs(slot["em_sum"] - 1.4) < 1e-9  # graded, not binary-zero


def test_legacy_rows_fall_back_to_em():
    assert _row_em({"ExactMatchRate": 1.0}) == 1.0
    assert _row_em({"ExactMatchRate": 0.0}) == 0.0
    assert _row_em({"MeanPrimaryMetric": "junk", "ExactMatchRate": 1.0}) == 1.0
