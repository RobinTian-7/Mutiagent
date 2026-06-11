"""Benchmark-agnostic task-feature classification (phase 3, M7).

The transfer-trust machinery (ledger buckets, kind refinement, abstention)
consumes three task properties. This module produces them from the task
STATEMENT via the run's own LLM, asking benchmark-agnostic distributed-
computation questions -- no benchmark-specific keywords:

* ``order_sensitive`` -- does correctness depend on agents' positions in an
  ordering (sequence segments, neighbor exchange, pipelines)?
* ``per_agent_output`` -- must each agent hold its OWN slice of the answer,
  or is one shared global answer scored?
* ``agg_kind`` -- the statistic family the answer requires, from a generic
  vocabulary (max/min/sum/mean/count/vote/any/set/topk/stats/xor/sort/seq/
  other). The vocabulary names statistics, not benchmark cases; ``other`` is
  always available.

Classification is temperature-0 and cached persistently by the SHA-256 of
the statement text (env ``MASBENCH_FEATURE_CACHE`` names the JSON file;
unset -> in-process cache only), so it costs one LLM call per distinct task
ever seen.

The regex heuristics in :mod:`masbench.task_features` remain ONLY as the
offline (fake-LLM) fallback so deterministic tests can exercise the
machinery; they are test scaffolding, not the method. ``cfg.task_feature_source``
selects: ``"llm"`` (default; falls back to heuristics for the fake provider),
``"heuristic"`` (ablation arm).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from exp_graph.llm.base import LLMClient

from masbench.task_features import agg_kind as _heuristic_agg_kind
from masbench.task_features import extract_task_features as _heuristic_features
from masbench.task_features import feature_key

AGG_KINDS = (
    "max", "min", "sum", "mean", "count", "vote", "any", "set",
    "topk", "stats", "xor", "sort", "seq", "other",
)

_PROMPT = """You are analyzing a task for a team of agents where each agent privately holds one shard of the data.

Task statement (placeholders like {{agent_id}}/{{input_shard}} stand for per-agent values):
---
%s
---

Answer three questions about WHAT THE TASK REQUIRES (not about any suggested protocol):
1. order_sensitive: Does computing the correct answer depend on the agents' POSITIONS in an ordering (consecutive segments of one sequence, neighbor exchange, pipeline stages)? true/false. Tasks where shards can be combined in any order (max, sums, counts over a multiset) are false.
2. per_agent_output: Must EACH agent end up holding its OWN distinct part of the answer (per-segment results), rather than one shared global answer? true/false.
3. agg_kind: Which ONE statistic family best describes the required answer? Choose exactly one of: %s. Use "seq" for order-dependent transforms over sequences (prefix sums, sliding windows, automata, chained hashes, substring/subsequence structure), "stats" for variance-like statistics, "other" if nothing fits.

Reply with ONLY a JSON object: {"order_sensitive": bool, "per_agent_output": bool, "agg_kind": "<kind>"}"""


_LOCK = threading.Lock()
_MEMORY_CACHE: dict[str, dict[str, Any]] = {}


def _cache_path() -> Path | None:
    raw = os.environ.get("MASBENCH_FEATURE_CACHE", "").strip()
    return Path(raw) if raw else None


def _text_key(task_text: str) -> str:
    return hashlib.sha256(task_text.encode("utf-8")).hexdigest()


def _load_persistent(key: str) -> dict[str, Any] | None:
    path = _cache_path()
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    value = data.get(key)
    return dict(value) if isinstance(value, dict) else None


def _store_persistent(key: str, value: dict[str, Any]) -> None:
    path = _cache_path()
    if path is None:
        return
    with _LOCK:
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            data = {}
        data[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True))


def _heuristic_classification(task_text: str) -> dict[str, Any]:
    feats = _heuristic_features(task_text)
    return {
        "order_sensitive": bool(feats["order_sensitive"]),
        "per_agent_output": bool(feats["per_agent_output"]),
        "agg_kind": _heuristic_agg_kind(task_text),
        "source": "heuristic",
    }


def _parse_classification(text: str) -> dict[str, Any] | None:
    """Parse the LLM reply; tolerate fenced/prefixed JSON."""
    raw = text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    kind = str(data.get("agg_kind", "other")).strip().lower()
    if kind not in AGG_KINDS:
        kind = "other"
    return {
        "order_sensitive": bool(data.get("order_sensitive", False)),
        "per_agent_output": bool(data.get("per_agent_output", False)),
        "agg_kind": kind,
        "source": "llm",
    }


def classify_task(
    task_text: str,
    *,
    llm_client: LLMClient | None,
    model_name: str = "",
    llm_provider: str = "",
    source: str = "llm",
) -> dict[str, Any]:
    """Classify one task statement; cached; falls back to heuristics.

    Fallback order: explicit ``source="heuristic"`` -> heuristics; fake/absent
    LLM -> heuristics (offline tests); LLM reply unparseable -> heuristics
    (logged via the ``source`` field so diagnostics can count it).
    """
    text = task_text or ""
    if source == "heuristic" or llm_client is None or llm_provider == "fake":
        return _heuristic_classification(text)
    key = _text_key(text)
    with _LOCK:
        cached = _MEMORY_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    persistent = _load_persistent(key)
    if persistent is not None:
        with _LOCK:
            _MEMORY_CACHE[key] = dict(persistent)
        return persistent
    prompt = _PROMPT % (text[:4000], ", ".join(AGG_KINDS))
    try:
        response = llm_client.complete(prompt, model_name=model_name, temperature=0.0)
        parsed = _parse_classification(getattr(response, "text", "") or "")
    except Exception:
        parsed = None
    result = parsed if parsed is not None else {
        **_heuristic_classification(text), "source": "heuristic_fallback",
    }
    with _LOCK:
        _MEMORY_CACHE[key] = dict(result)
    _store_persistent(key, result)
    return result


def classification_bucket(classification: dict[str, Any]) -> str:
    return feature_key(classification)


def classification_kind(classification: dict[str, Any]) -> str:
    return str(classification.get("agg_kind", "other"))
