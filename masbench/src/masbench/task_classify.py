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
# ============================================================
# 【模块导读】与基准无关的任务特征分类（阶段 3，M7）。
# 迁移信任机制（台账分桶、类别细化、弃权）消费三个任务属性；本模块用本次运行自身的
# LLM 对任务题面提出与基准无关的分布式计算问题来产出它们——不含基准专用关键词：
# * order_sensitive —— 正确性是否依赖各智能体在某个排序中的位置（序列分段、邻居交换、
#   流水线）？
# * per_agent_output —— 是每个智能体必须持有答案中属于自己的切片，还是只对一个共享的
#   全局答案计分？
# * agg_kind —— 答案所需的统计量家族，取自通用词表（max/min/sum/mean/count/vote/any/
#   set/topk/stats/xor/sort/seq/other）。词表命名的是统计量而非基准 case；other 恒可选。
# 分类在温度 0 下进行，并按题面文本的 SHA-256 持久缓存（MASBENCH_FEATURE_CACHE 指定
# JSON 文件；未设置则只有进程内缓存），因此每个见过的不同任务只花一次 LLM 调用。
# masbench.task_features 里的正则启发式仅作为离线(fake-LLM)兜底保留，使确定性测试能
# 驱动该机制；它们是测试脚手架，不是正式方法。cfg.task_feature_source 决定来源：
# "llm"（默认；fake provider 时兜底到启发式）、"heuristic"（消融臂）。
# ============================================================

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


# 中文：这些类别的正确答案无法由小的局部摘要算出
#   （仅作离线兜底映射；正式方法直接问 LLM）。
# Kinds whose correct answer cannot be computed from small local summaries
# (offline-fallback mapping only; the method asks the LLM directly).
_LOSSLESS_KINDS = frozenset({"count", "set", "topk", "sort", "seq", "stats"})


# 中文：复合答案的离线兜底探测器（正式方法直接问 LLM）。
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


# 【职责】纯启发式的完整分类（离线兜底）：正则特征 + 由类别推 needs_lossless、
#   再用模式推 answer_composite。
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


# 【职责】解析 LLM 分类回复；容忍代码围栏/前缀包裹的 JSON，非法类别归入 other。
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


# 【职责】对单个任务题面做分类；带两级缓存（内存 + 持久 JSON）；失败时兜底到启发式。
# - 兜底顺序：显式 source="heuristic" → 启发式；fake/缺失 LLM → 启发式（离线测试）；
#   LLM 回复无法解析 → 启发式（经 source 字段记录，便于诊断统计各来源占比）。
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
    # 中文：只做一次解析重试：dev-5 曾见无法解析的回复兜底到启发式，
    #   导致单次运行内出现来源混杂的标签。
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


# 【职责】分类结果 → 迁移台账用的粗粒度桶 id（of/os，可带 -seg 后缀）。
def classification_bucket(classification: dict[str, Any]) -> str:
    return feature_key(classification)


# 【职责】分类结果 → 聚合统计量类别（agg_kind，缺省 other）。
def classification_kind(classification: dict[str, Any]) -> str:
    return str(classification.get("agg_kind", "other"))


# 【职责】M12/M16 信任子槽位名："(lossless|lossy)-(scalar|composite)"。
# - M16 依据 dev-9 取证补上答案形态位：II-13/15（标量答案）与 II-17/19（需组装的
#   复合数组）曾共用一个槽位，于是 II-13 的直接证据把 II-17 标成 preserve，
#   裸结构得了 0 分——真正攻克它的其实是 Modify 改写过的指令。
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
