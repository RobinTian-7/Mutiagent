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
import re
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

Answer four questions about WHAT THE TASK REQUIRES (not about any suggested protocol):
1. order_sensitive: Does computing the correct answer depend on the agents' POSITIONS in an ordering (consecutive segments of one sequence, neighbor exchange, pipeline stages)? true/false. Tasks where shards can be combined in any order (max, sums, counts over a multiset) are false.
2. per_agent_output: Must EACH agent end up holding its OWN distinct part of the answer (per-segment results), rather than one shared global answer? true/false.
3. agg_kind: Which ONE statistic family best describes the required answer? Choose exactly one of: %s. Use "seq" for order-dependent transforms over sequences (prefix sums, sliding windows, automata, chained hashes, substring/subsequence structure), "stats" for variance-like statistics, "other" if nothing fits.
4. needs_lossless: Can each agent's shard be safely REDUCED to a small local summary (a max, a sum, one vote) before sharing, and the summaries combined into the correct answer? If yes -> false. If instead the raw data (or near-complete structure) must reach whoever computes the answer -- counting distinct/structured occurrences, cross-boundary patterns, reconstructing sequences -- then true.
5. answer_composite: Is the required FINAL ANSWER a single small value (one number, one word, one boolean) -> false, or a COMPOSITE structure that must be assembled (an array/sequence, a dictionary, per-position or per-segment results) -> true.

Reply with ONLY a JSON object: {"order_sensitive": bool, "per_agent_output": bool, "agg_kind": "<kind>", "needs_lossless": bool, "answer_composite": bool}"""


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


# Kinds whose correct answer cannot be computed from small local summaries
# (offline-fallback mapping only; the method asks the LLM directly).
_LOSSLESS_KINDS = frozenset({"count", "set", "topk", "sort", "seq", "stats"})


# Offline-fallback composite-answer detector (the method asks the LLM).
_COMPOSITE_PATTERNS = (
    re.compile(r"output:?\**\s*(a |the )?(complete |sorted |full )?"
               r"(array|list|dictionary|sequence)", re.IGNORECASE),
    re.compile(r"\blist of \d+|\btop \d+|\b\d+ largest\b", re.IGNORECASE),
    re.compile(r"submits? (their|its) (own |)?(portion|segment|part)", re.IGNORECASE),
    re.compile(r"dictionary mapping", re.IGNORECASE),
)
_SCALAR_PATTERNS = (
    re.compile(r"output:?\**\s*a single (integer|number|value|word|string|boolean)",
               re.IGNORECASE),
)


def _heuristic_composite(task_text: str) -> bool:
    text = task_text or ""
    if any(p.search(text) for p in _SCALAR_PATTERNS):
        return False
    return any(p.search(text) for p in _COMPOSITE_PATTERNS)


def _heuristic_classification(task_text: str) -> dict[str, Any]:
    feats = _heuristic_features(task_text)
    kind = _heuristic_agg_kind(task_text)
    return {
        "order_sensitive": bool(feats["order_sensitive"]),
        "per_agent_output": bool(feats["per_agent_output"]),
        "agg_kind": kind,
        "needs_lossless": kind in _LOSSLESS_KINDS,
        "answer_composite": _heuristic_composite(task_text),
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
        "needs_lossless": bool(data.get("needs_lossless", kind in _LOSSLESS_KINDS)),
        "answer_composite": bool(data.get("answer_composite", False)),
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
    parsed = None
    # One parse-retry: dev-5 saw unparseable replies fall back to heuristics,
    # creating mixed-source labels within a single run.
    for _ in range(2):
        try:
            response = llm_client.complete(prompt, model_name=model_name, temperature=0.0)
            parsed = _parse_classification(getattr(response, "text", "") or "")
        except Exception:
            parsed = None
        if parsed is not None:
            break
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


def classification_lossless_slot(classification: dict[str, Any]) -> str:
    """M12/M16 trust sub-slot name: '(lossless|lossy)-(scalar|composite)'.

    M16 added the answer-shape bit after dev-9 forensics: II-13/15 (scalar
    answers) and II-17/19 (composite arrays needing assembly) shared one
    slot, so direct II-13 evidence marked II-17 'preserve' and the bare
    structure scored 0 where Modify-rewritten instructions had cracked it.
    """
    lossless = "lossless" if classification.get("needs_lossless") else "lossy"
    shape = "composite" if classification.get("answer_composite") else "scalar"
    return f"{lossless}-{shape}"
