"""D1: top-k candidate PROBE-evaluation must work for Silo (not just CF).

The exp_graph probe path was CF-hardwired (built a random array via
build_global_task(array_size=...) and read summary["FinalRMSE"]). With
graph_validation_seeds>0 on a Silo adapter it must probe-run each candidate on
the Silo instance and score it generically -- not crash into the fallback.

Offline (fake, deterministic merge/init) the probe runs without LLM and Silo
success is topology-invariant, so this checks the MECHANISM (probe ran, no
CF-signature fallback), not a score difference.
"""
from pathlib import Path

from masbench import engine
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.llm.fake import BenchmarkFakeLLMClient

DATA = Path(__file__).parent / "data"


def test_silo_candidate_probe_eval_runs_without_cf_fallback():
    inst = list(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )[0]
    cfg = RunConfig(
        llm_provider="fake", num_graph_candidates=2, graph_validation_seeds=2,
        n_agents=2, objective="accuracy_first",
        merge_mode="deterministic", init_mode="deterministic",
    )
    plan, extra = engine._plan_graph_generate(
        cfg, n_agents=2, task_adapter=SiloProtocolAdapter(inst),
        client=BenchmarkFakeLLMClient(),
    )
    # Probe-eval ran on the Silo instance (no CF build_global_task signature crash
    # -> no fallback).
    assert extra.get("graph_fallback_reason") is None
