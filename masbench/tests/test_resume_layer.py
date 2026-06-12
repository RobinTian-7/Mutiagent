"""M18 resume layer: interrupted runs relaunch and replay finished work.

Operator directive: every test must be resumable from its archive. The
frozen judges cannot change, so resumability lives in the pipeline:
deterministic-keyed caches for deployment-phase rows (bank-content-hashed)
and verified recipes, plus the existing evidence cache. Relaunching the
same driver IS the resume.
"""

from __future__ import annotations

from pathlib import Path

import masbench.evolve as evolve
from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.skill_bank import SkillBank
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import evolution_objective_spec
from masbench.transfer import bank_state_hash

DATA = Path(__file__).parent / "data"


def _instance():
    return next(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )


def test_bank_state_hash_stable_and_sensitive():
    from masbench.recipes import parse_recipe, recipe_skill_card
    import json

    empty1, empty2 = bank_state_hash(SkillBank()), bank_state_hash(SkillBank())
    assert empty1 == empty2
    spec = parse_recipe(json.dumps({
        "name": "x", "selected_primary": 1,
        "steps": [{"edges": [[0, 1]], "instruction": "i"}],
    }), n_agents=2, max_steps=4)
    card = recipe_skill_card(spec, task_family="silo", bucket="os",
                             lossless_slot="lossless-scalar", n_agents=2, verify_count=2)
    with_skill = bank_state_hash(SkillBank(skills=[card]))
    assert with_skill != empty1
    assert bank_state_hash(SkillBank(), {"k": {"mean_loss": 0.1, "n": 1}}) != empty1


def _count_plans(monkeypatch):
    counter = {"n": 0}
    orig = evolve._plan_graph_generate

    def spy(cfg, **kwargs):
        counter["n"] += 1
        return orig(cfg, **kwargs)

    monkeypatch.setattr(evolve, "_plan_graph_generate", spy)
    return counter


def _cfg() -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate",
        num_graph_candidates=2, n_agents=2,
    )


def test_run_one_rows_replay_across_invocations(tmp_path, monkeypatch):
    import json

    cache_file = tmp_path / "evalcache.json"
    monkeypatch.setenv("MASBENCH_EVAL_CACHE", str(cache_file))
    counter = _count_plans(monkeypatch)
    cfg, inst = _cfg(), _instance()
    objective = evolution_objective_spec(cfg)
    client = create_llm_client("fake")
    row1 = evolve._run_one(inst, cfg, objective=objective, skill_bank=SkillBank(),
                           seed=7, llm_client=client, motif_stats=None)
    assert counter["n"] == 1 and len(json.loads(cache_file.read_text())) == 1
    row2 = evolve._run_one(inst, cfg, objective=objective, skill_bank=SkillBank(),
                           seed=7, llm_client=client, motif_stats=None)
    assert counter["n"] == 1, "replay must not re-plan"
    assert row2["ExactMatchRate"] == row1["ExactMatchRate"]
    assert row2["case_id"] == row1["case_id"]
    # different seed -> fresh measurement, new cache entry
    evolve._run_one(inst, cfg, objective=objective, skill_bank=SkillBank(),
                    seed=8, llm_client=client, motif_stats=None)
    assert counter["n"] == 2 and len(json.loads(cache_file.read_text())) == 2


def test_eval_cache_off_means_no_behavior_change(tmp_path, monkeypatch):
    monkeypatch.delenv("MASBENCH_EVAL_CACHE", raising=False)
    counter = _count_plans(monkeypatch)
    cfg, inst = _cfg(), _instance()
    objective = evolution_objective_spec(cfg)
    client = create_llm_client("fake")
    for _ in range(2):
        evolve._run_one(inst, cfg, objective=objective, skill_bank=SkillBank(),
                        seed=7, llm_client=client, motif_stats=None)
    assert counter["n"] == 2, "without the env the work happens every time"
