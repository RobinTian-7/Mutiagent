"""M7: benchmark-agnostic LLM task classification (heuristics = fallback only)."""

from __future__ import annotations

import json

from masbench.task_classify import (
    AGG_KINDS,
    classification_bucket,
    classification_kind,
    classify_task,
)


class _ScriptedClient:
    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def complete(self, prompt, **kwargs):
        self.calls += 1
        self._last_prompt = prompt

        class R:
            pass

        r = R()
        r.text = self._text
        return r


def test_llm_classification_parses_and_buckets():
    client = _ScriptedClient(
        'Here you go:\n```json\n{"order_sensitive": true, "per_agent_output": false, "agg_kind": "seq"}\n```'
    )
    out = classify_task(
        "agents hold consecutive parts of one sequence...",
        llm_client=client, model_name="m", llm_provider="openai",
    )
    assert out["source"] == "llm"
    assert classification_bucket(out) == "os"
    assert classification_kind(out) == "seq"


def test_unknown_kind_coerced_to_other_and_cached():
    client = _ScriptedClient(
        '{"order_sensitive": false, "per_agent_output": false, "agg_kind": "weird_thing"}'
    )
    text = "some unique task text for cache test 12345"
    out1 = classify_task(text, llm_client=client, model_name="m", llm_provider="openai")
    out2 = classify_task(text, llm_client=client, model_name="m", llm_provider="openai")
    assert out1["agg_kind"] == "other" and out1["agg_kind"] in AGG_KINDS
    assert client.calls == 1, "second call must hit the in-memory cache"
    assert out2 == out1


def test_fake_provider_uses_heuristics():
    out = classify_task(
        "Count adjacent equal pairs. Agent Ordering: agents hold CONSECUTIVE segments.",
        llm_client=_ScriptedClient("never called"), model_name="fake", llm_provider="fake",
    )
    assert out["source"] == "heuristic"
    assert classification_bucket(out) == "os"


def test_junk_reply_falls_back_to_heuristics():
    client = _ScriptedClient("I cannot answer that.")
    out = classify_task(
        "Find the GLOBAL MAXIMUM across all agents' data. unique-junk-test",
        llm_client=client, model_name="m", llm_provider="openai",
    )
    assert out["source"] == "heuristic_fallback"
    assert classification_bucket(out) == "of"
    assert classification_kind(out) == "max"


def test_persistent_cache_roundtrip(tmp_path, monkeypatch):
    cache = tmp_path / "features.json"
    monkeypatch.setenv("MASBENCH_FEATURE_CACHE", str(cache))
    client = _ScriptedClient(
        '{"order_sensitive": false, "per_agent_output": false, "agg_kind": "count"}'
    )
    text = "count things, persistent cache test"
    classify_task(text, llm_client=client, model_name="m", llm_provider="openai")
    assert cache.exists() and "count" in cache.read_text()
    # New module state would normally re-ask; the persistent file answers.
    import masbench.task_classify as tc
    monkeypatch.setattr(tc, "_MEMORY_CACHE", {})
    client2 = _ScriptedClient("should not be called")
    out = classify_task(text, llm_client=client2, model_name="m", llm_provider="openai")
    assert client2.calls == 0
    assert out["agg_kind"] == "count"


def test_prompt_contains_no_benchmark_specific_keywords():
    """The classification prompt must ask generic questions; benchmark-specific
    template markers (Silo's 'Agent Ordering:'/'{input_shard}' headers) must
    not be baked into the QUESTION text."""
    from masbench.task_classify import _PROMPT

    lowered = _PROMPT.lower()
    assert "silo" not in lowered
    assert "agent ordering:" not in lowered
    assert "communication protocol" not in lowered
