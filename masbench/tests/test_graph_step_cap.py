"""Generated organizations must be able to express linear-depth schedules.

P2 confirmatory-2 failure analysis: the reserved sequential-paradigm tasks
(II-13 palindrome, II-16 trapping-rain) have chain-style optimal organizations
needing ~n-1 steps at n=10, but the generation path capped graphs at
graph_max_steps=4 -- the winning organization was INEXPRESSIBLE for every
generation-based arm (replay, fresh gen, probe), while named-topology compile
(`chain`) has no such cap. The cap now scales with n (task-agnostic).
"""
from masbench.core.config import RunConfig
from masbench.engine import _effective_graph_max_steps


def test_cap_scales_with_agent_count():
    cfg = RunConfig(n_agents=10)
    assert _effective_graph_max_steps(cfg, 10) >= 11, "chain at n=10 needs ~9 steps + sink/broadcast"
    assert _effective_graph_max_steps(cfg, 5) >= 6


def test_small_n_keeps_existing_floor():
    cfg = RunConfig(n_agents=2)
    assert _effective_graph_max_steps(cfg, 2) == 4, "small n keeps the historical cap"


def test_explicit_config_wins():
    cfg = RunConfig(n_agents=10, graph_max_steps=20)
    assert _effective_graph_max_steps(cfg, 10) == 20, "an explicit non-default cap is honored"
