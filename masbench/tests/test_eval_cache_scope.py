"""M18b (dev-15): the eval cache covers DEPLOYMENT rows only.

A rejected evolution round resets the chain to an empty bank; with
evolution-internal rows cached, every later round becomes a byte-identical
replay of the rejected one (dev-15's refine arm: three "rounds" frozen at
j 0.44->0.67 = one cached computation). Internal rows (diag_phase set) now
bypass the eval cache; judge deployment rows (diag_phase == "") keep the
M18 resume property.
"""

from __future__ import annotations

import json
from pathlib import Path

import masbench.evolve as evolve
from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.skill_bank import SkillBank
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import _run_one, evolution_objective_spec

DATA = Path(__file__).parent / "data"


def _cfg() -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate",
        num_graph_candidates=2, n_agents=2,
    )


def _inst():
    return next(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )


def test_internal_phases_bypass_eval_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "evalcache.json"
    monkeypatch.setenv("MASBENCH_EVAL_CACHE", str(cache_file))
    cfg, inst = _cfg(), _inst()
    objective = evolution_objective_spec(cfg)
    client = create_llm_client("fake")

    for phase in ("evidence", "explore", "gate:before"):
        _run_one(inst, cfg, objective=objective, skill_bank=SkillBank(),
                 seed=7, llm_client=client, motif_stats=None, diag_phase=phase)
    assert not cache_file.exists() or json.loads(cache_file.read_text()) == {}

    # deployment rows (default phase "") still cache + replay
    _run_one(inst, cfg, objective=objective, skill_bank=SkillBank(),
             seed=7, llm_client=client, motif_stats=None)
    assert len(json.loads(cache_file.read_text())) == 1
