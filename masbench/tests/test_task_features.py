"""M1 feature extractor: validated against the benchmark's own paradigm labels.

The extractor reads ONLY the task description text. The benchmark's
``paradigm`` field is loaded here purely as offline ground truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.task_features import (
    extract_task_features,
    feature_key,
    instance_feature_key,
)

BENCH_DIR = Path(__file__).resolve().parents[1] / "third_party" / "acl26-silo-bench" / "benchmarks"

ALL_CASES = [f"I-{i:02d}" for i in range(1, 11)] + [f"II-{i}" for i in range(11, 21)]

# Cases whose statement says each agent submits its OWN slice of the answer.
SEGMENTED_CASES = {"II-11", "II-14", "II-20"}


def _case_json(case_id: str) -> dict:
    return json.loads((BENCH_DIR / f"{case_id}_n5.json").read_text())


@pytest.mark.skipif(not BENCH_DIR.exists(), reason="silo benchmark data not present")
def test_order_sensitivity_matches_benchmark_paradigm_labels():
    """Text-only order_sensitive == (paradigm II) for ALL 20 I+II cases."""
    for case_id in ALL_CASES:
        data = _case_json(case_id)
        text = data["task_description"]
        if not isinstance(text, str):
            text = json.dumps(text)
        feats = extract_task_features(text)
        expect = "II" in str(data.get("paradigm", ""))
        assert feats["order_sensitive"] == expect, (case_id, feats)


@pytest.mark.skipif(not BENCH_DIR.exists(), reason="silo benchmark data not present")
def test_per_agent_output_buckets():
    for case_id in ALL_CASES:
        data = _case_json(case_id)
        text = data["task_description"]
        if not isinstance(text, str):
            text = json.dumps(text)
        feats = extract_task_features(text)
        assert feats["per_agent_output"] == (case_id in SEGMENTED_CASES), (case_id, feats)


@pytest.mark.skipif(not BENCH_DIR.exists(), reason="silo benchmark data not present")
def test_instance_feature_key_buckets():
    adapter = SiloBenchAdapter(str(BENCH_DIR))
    keys = {
        inst.case_id: instance_feature_key(inst)
        for inst in adapter.iter_instances(levels=["I", "II"], agent_counts=[5])
    }
    assert keys["I-01"] == "of"
    assert keys["I-09"] == "of"
    assert keys["II-13"] == "os"
    assert keys["II-15"] == "os"
    assert keys["II-16"] == "os"
    assert keys["II-11"] == "os-seg"
    assert keys["II-14"] == "os-seg"
    assert keys["II-20"] == "os-seg"


def test_feature_key_canonical():
    assert feature_key({"order_sensitive": False, "per_agent_output": False}) == "of"
    assert feature_key({"order_sensitive": True, "per_agent_output": False}) == "os"
    assert feature_key({"order_sensitive": True, "per_agent_output": True}) == "os-seg"
    assert feature_key({}) == "of"


def test_empty_text_is_order_free():
    assert extract_task_features(None) == {
        "order_sensitive": False,
        "per_agent_output": False,
    }
