"""B2: the LLM design-insight minister runs over the evolution evidence,
insights are falsified against held-out, and VERIFIED ones fold into the skill
bank (feeding generation). Opt-in via use_llm_insights; off by default.

Offline (fake) the minister uses its deterministic fallback report, so this
checks the MECHANISM (ran, falsified, reported), not insight quality.
"""
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution

DATA = Path(__file__).parent / "data"


def _cfg(**over) -> RunConfig:
    return RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", **over,
    )


def test_llm_insights_run_and_reported_when_enabled():
    s = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "I-02"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(use_llm_insights=True), levels=["I"],
        seed_incumbent_topology="mesh_star",
    )
    assert "n_insight_patches" in s
    assert isinstance(s["n_insight_patches"], int)


def test_llm_insights_off_by_default():
    s = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"],
        seed_incumbent_topology="mesh_star",
    )
    assert s.get("n_insight_patches", 0) == 0
