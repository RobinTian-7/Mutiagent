"""M27: portfolio-evidence seed expansion (hi-power forensics).

one_peer's os trust was built on just 2 train-seed evaluations of the sole
os anchor II-13; one drift window flipped it to 0/2 and gen fell back to a
weak org. portfolio_seed_factor derives extra portfolio seeds so trust is
built on len(train_seeds)*factor samples. factor=1 is byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import masbench.evolve as evolve
from exp_graph.llm.factory import create_llm_client
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig

DATA = Path(__file__).parent / "data"


def _cfg(factor: int) -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate",
        num_graph_candidates=2, n_agents=2, portfolio_seed_factor=factor,
    )


def _portfolio_seed_counts(monkeypatch, factor):
    seen = {}
    orig = evolve._collect_portfolio_rows

    def spy(instances, cfg, *, topologies, seeds, **kw):
        seen["seeds"] = list(seeds)
        return orig(instances, cfg, topologies=topologies, seeds=seeds, **kw)

    monkeypatch.setattr(evolve, "_collect_portfolio_rows", spy)
    evolve.run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "II-13"], agent_counts=[2],
        train_seeds=[1, 2], val_seeds=[3], cfg=_cfg(factor),
        levels=["I", "II"], llm_client=create_llm_client("fake"),
        workers=1, progress=False, initial_skills=[],
    )
    return seen.get("seeds", [])


def test_factor_one_is_exact_train_seeds(monkeypatch):
    seeds = _portfolio_seed_counts(monkeypatch, 1)
    assert seeds == [1, 2], "factor 1 must be byte-identical to train_seeds"


def test_factor_expands_seeds(monkeypatch):
    seeds = _portfolio_seed_counts(monkeypatch, 4)
    # 2 train seeds x 4 = 8 distinct derived seeds (s + 1009*k)
    assert len(seeds) == 8
    assert set([1, 2]).issubset(set(seeds))
    assert len(set(seeds)) == 8, "derived seeds must be distinct"


def test_env_override(monkeypatch):
    monkeypatch.setenv("MASBENCH_PORTFOLIO_SEED_FACTOR", "3")
    seeds = _portfolio_seed_counts(monkeypatch, 1)  # cfg says 1, env says 3
    assert len(seeds) == 6
