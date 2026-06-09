"""--evolved-test-seeds K: the evolved arm trains on seeds[:-K] and EVALUATES on
the last K held-out seeds (gate val = same K). K>1 gives the evolved arm K x more
evaluation points per condition, cutting the binary-per-condition variance that
made the smoke results uninterpretable. Also: the evolved record's gate carries
its `mode` (generation vs topology-select), previously dropped.
"""
from pathlib import Path

import masbench.bench as bench
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig

DATA = Path(__file__).parent / "data"


def test_train_test_split():
    assert bench._train_test_seeds([1, 2, 3, 4, 5], 2) == ([1, 2, 3], [4, 5])
    assert bench._train_test_seeds([1, 2], 1) == ([1], [2])
    assert bench._train_test_seeds([1], 1) == ([1], [1])        # too few -> reuse
    assert bench._train_test_seeds([1, 2, 3], 3) == ([1, 2, 3], [1, 2, 3])


def _run(tmp_path, **over):
    cfg = RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", **over,
    )
    return bench.run_benchmark(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], seeds=[1, 2, 3],
        arms=["evolved"], cfg_base=cfg, out=tmp_path / "x", workers=1,
    )


def test_evolved_evaluates_on_k_test_seeds(tmp_path):
    res = _run(tmp_path, evolved_test_seeds=2)
    seeds = {r["seed"] for r in res["runs"] if r["arm"] == "evolved"}
    assert seeds == {2, 3}  # the last 2 seeds held out + evaluated


def test_evolved_gate_carries_generation_mode(tmp_path):
    res = _run(tmp_path, evolved_mode="graph_generate", num_graph_candidates=2)
    evolved = [r for r in res["runs"] if r["arm"] == "evolved"]
    assert evolved and all(r["gate"].get("mode") == "generation" for r in evolved)
