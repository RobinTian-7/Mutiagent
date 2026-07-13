"""Graded PARTIAL-CORRECTNESS scoring for Silo-Bench (Plan 4 Task 2).

masbench's strict signal is exact-match (1.0/0.0). Paper-grade data also needs a
continuous quality score P in [0, 1] alongside the strict success rate, so that
the gap ``P - S`` can localise where coordination breaks down (Silo-Bench paper
Section 3.3). This module provides ``silo_partial_score(answer, ground_truth,
output_type)`` which grades a single GLOBAL answer against the single GLOBAL
ground truth.

Why not call Silo's official ``compute_partial_correctness`` directly?
    Silo's official metric (``third_party/acl26-silo-bench/src/utils/metrics.py``)
    has signature ``compute_partial_correctness(submissions, expected_output,
    level)``: it grades a list of *per-agent* submissions against a dict carrying
    ``per_agent_values`` and a paradigm ``level`` ("I"/"II"/"III"). masbench
    aggregates to one global answer and carries one canonical ground-truth string
    plus ``output_type`` (which in the shipped benchmarks is uniformly
    ``"distributed"`` and so is not a usable type discriminator). The official
    per-agent API therefore does not map cleanly onto ``(answer, expected)``, so
    we use a robust by-structure fallback below.

    We DO reuse Silo's official algorithmic primitive for sequence ordering: the
    longest-increasing-subsequence helper that underpins their Level-III ordering
    metric. It is imported lazily (guarded by ImportError; the module lives under
    a non-package ``src/`` path, so it is loaded by file location) and falls back
    to a local copy if unavailable. ``uses_official_lis()`` reports which path is
    live.

Fallback grading, dispatched on the parsed value's structure (with an
``output_type`` hint that routes "set"-like answers to Jaccard):
    * exact match (canonical)            -> 1.0
    * numeric scalar                     -> max(0, 1 - |a-t| / max(1, |t|))
    * list / sequence                    -> blend of positional-match fraction and
                                            LIS-based ordering ratio (sort-like)
    * set (hint or unhashable mismatch)  -> Jaccard overlap
    * dict                               -> fraction of key/value pairs that match
    * string                             -> normalized token-overlap (F1)
    * None / sentinel / type mismatch    -> 0.0

Both ``answer`` and ``ground_truth`` may be raw Python values OR canonical-JSON
strings (e.g. the ``answer_key`` masbench stores in ``global_task``); they are
coerced via the same parsing ``canonical_answer`` uses, so ``"9"`` and ``9`` or
``"[3, 1]"`` and ``[3, 1]`` grade identically.
"""
# ============================================================
# 【模块导读】Silo-Bench 的分级 partial 部分正确度评分。
# 严格信号是精确匹配(1.0/0.0)；论文级数据还需 [0,1] 的连续质量分 P，用 P-S 的差定位
# 协调在哪里崩。核心函数 silo_partial_score(answer, ground_truth, output_type)。
# 不直接调 Silo 官方 compute_partial_correctness：其签名是「逐 agent 提交列表」，与本处
# 「单一全局答案」对不齐，故采用按结构分派的稳健兜底评分。但复用其官方 LIS(最长递增子
# 序列)原语做序列排序质量：按文件位置惰性 import、ImportError 兜底到本地实现，
# uses_official_lis() 报告当前走哪条路。分派：精确→1.0/数值→归一距离/列表→位置命中与
# LIS 排序比的混合/集合→Jaccard/字典→键值命中率/字符串→词元 F1/其余→0.0。
# ============================================================

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable

from masbench.core.task_bridge import canonical_answer

_UNKNOWN_SENTINELS = {"UNKNOWN", "NONE", "NULL"}


# --------------------------------------------------------------------------- #
# Official LIS primitive (lazy, guarded). Reused for sequence ordering quality.
# --------------------------------------------------------------------------- #
# 【职责】最长严格递增子序列长度(官方 LIS 不可用时的本地兜底实现)。
def _local_lis_length(seq: list[Any]) -> int:
    """Longest strictly-increasing subsequence length (local fallback)."""
    if not seq:
        return 0
    from bisect import bisect_left

    tails: list[Any] = []
    for x in seq:
        pos = bisect_left(tails, x)
        if pos == len(tails):
            tails.append(x)
        else:
            tails[pos] = x
    return len(tails)


# 【职责】加载 Silo 官方 LIS 原语，返回(lis 函数, 是否用了官方)。
# - 按文件位置 import：parents[3] 是仓库根，官方度量在
#   third_party/acl26-silo-bench/src/utils/metrics.py(该目录非包，只能按路径加载)。
# - 任何 import/属性/IO/类型错误都兜底到本地 _local_lis_length。
def _load_official_lis() -> tuple[Callable[[list[Any]], int], bool]:
    """Return (lis_fn, used_official). Import Silo's helper by file location."""
    metrics_path = (
        Path(__file__).resolve().parents[3]
        / "third_party"
        / "acl26-silo-bench"
        / "src"
        / "utils"
        / "metrics.py"
    )
    try:
        spec = importlib.util.spec_from_file_location(
            "masbench._silo_official_metrics", metrics_path
        )
        if spec is None or spec.loader is None:
            raise ImportError("no loader for silo metrics")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = module._longest_increasing_subsequence_length  # type: ignore[attr-defined]
        # 中文：冒烟校验契约，防止上游重构悄悄把我们弄坏。
        # Smoke-check the contract so a refactor upstream can't silently break us.
        if fn([0, 2, 1, 3]) != 3:
            raise ImportError("silo LIS contract changed")
        return fn, True
    except (ImportError, AttributeError, OSError, TypeError):
        return _local_lis_length, False


_LIS_LENGTH, _USES_OFFICIAL_LIS = _load_official_lis()


def uses_official_lis() -> bool:
    """True iff the sequence-ordering ratio uses Silo's official LIS primitive."""
    return _USES_OFFICIAL_LIS


# --------------------------------------------------------------------------- #
# Coercion helpers (mirror canonical_answer parsing, but return live values)
# --------------------------------------------------------------------------- #
# 【职责】尽力把值解析为实时 Python 值；未知/空哨兵返回 None。
# - 数字/JSON 样式的字符串会被解析，布尔归并，其余原样返回；与 canonical_answer 对齐，
#   使原始值与其规范字符串形解析结果一致。
def _coerce(value: Any) -> Any:
    """Best-effort parse to a live Python value; None for unknown/empty sentinels.

    Strings that look like numbers or JSON are parsed; bare booleans are folded;
    everything else is returned as-is. Mirrors ``canonical_answer`` so that a raw
    value and its canonical-string form coerce to the same thing.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, list, dict)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() in _UNKNOWN_SENTINELS:
            return None
        if text.lower() in {"true", "false"}:
            return text.lower() == "true"
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
    return value


# 【职责】数值强制转换，拒绝布尔(避免 True/1 被当数字评分)。
def _as_number(value: Any) -> float | None:
    """Numeric coercion that rejects booleans (so True/1 don't grade as numbers)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# --------------------------------------------------------------------------- #
# Per-structure graders (each returns a score in [0, 1])
# --------------------------------------------------------------------------- #
# 【职责】数值评分：相等得 1，否则按归一化距离 max(0, 1-|a-t|/max(1,|t|))。
def _score_numeric(a: float, t: float) -> float:
    if a == t:
        return 1.0
    return max(0.0, 1.0 - abs(a - t) / max(1.0, abs(t)))


# 【职责】集合评分：两个集合的 Jaccard 重叠(交/并)。
def _score_set(a: Any, t: Any) -> float:
    try:
        a_set, t_set = set(a), set(t)
    except TypeError:
        return 0.0
    if not a_set and not t_set:
        return 1.0
    union = a_set | t_set
    if not union:
        return 1.0
    return len(a_set & t_set) / len(union)


# 【职责】序列评分：位置命中比与基于 LIS 的排序比取均值。
# - 位置比奖励「对的值在对的槽」；排序比(最长正确顺序子序列/目标长度，用官方 LIS)奖励整体
#   有序但个别位置错位的排序类答案。取均值使 [1,2,4,3] vs [1,2,3,4] 之类近似严格落在(0,1)。
def _score_sequence(a: list[Any], t: list[Any]) -> float:
    """Blend positional-match fraction with an LIS-based ordering ratio.

    The positional fraction rewards getting the right value in the right slot; the
    ordering ratio (longest correctly-ordered subsequence / target length, via the
    official LIS primitive) rewards sort-like answers that are globally ordered
    even when individual positions are shifted. Their mean keeps near-misses such
    as ``[1,2,4,3]`` vs ``[1,2,3,4]`` strictly inside (0, 1).
    """
    if not a and not t:
        return 1.0
    if not t:
        return 0.0

    positional = sum(1 for x, y in zip(a, t) if x == y) / len(t)

    # 中文：把每个答案元素映射到它在目标中首次出现的位置，这些位置上的 LIS 即最长的
    #   正确顺序连段。
    # Map each answer element to the position of its first occurrence in target,
    # then the LIS over those positions is the longest correctly-ordered run.
    target_pos: dict[Any, int] = {}
    for i, v in enumerate(t):
        try:
            target_pos.setdefault(v, i)
        except TypeError:  # unhashable element -> ordering ratio not applicable
            return positional
    try:
        positions = [target_pos[x] for x in a if x in target_pos]
    except TypeError:
        return positional
    ordering = _LIS_LENGTH(positions) / len(t)

    return (positional + ordering) / 2.0


# 【职责】字典评分：键值对完全匹配的比例(按键的并集)。
def _score_dict(a: dict[Any, Any], t: dict[Any, Any]) -> float:
    if not a and not t:
        return 1.0
    keys = set(a) | set(t)
    if not keys:
        return 1.0
    matches = sum(1 for k in keys if k in a and k in t and a[k] == t[k])
    return matches / len(keys)


# 【职责】字符串评分：分词后的词元重叠 F1(精确率与召回率的调和平均)。
def _score_string(a: str, t: str) -> float:
    a_tokens, t_tokens = _tokenize(a), _tokenize(t)
    if not a_tokens and not t_tokens:
        return 1.0
    if not a_tokens or not t_tokens:
        return 0.0
    overlap = 0
    remaining = list(t_tokens)
    for tok in a_tokens:
        if tok in remaining:
            remaining.remove(tok)
            overlap += 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(a_tokens)
    recall = overlap / len(t_tokens)
    return 2 * precision * recall / (precision + recall)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
# 【职责】对一个 Silo 全局答案给出 [0,1] 的分级部分正确度——本模块对外主入口。
# - answer/ground_truth 可为原始值或规范化 JSON 串；output_type 只是粗提示，真正分派看
#   值的结构，「set」类提示会把列表比较路由到 Jaccard。
# - 无法解析、null/哨兵、或结构无法与真值合理比较的答案一律 0.0；精确(规范)匹配恒为 1.0。
def silo_partial_score(answer: Any, ground_truth: Any, output_type: str) -> float:
    """Graded partial-correctness in [0, 1] for one Silo global answer.

    ``answer`` / ``ground_truth`` may be raw values or canonical-JSON strings.
    ``output_type`` is a coarse hint; the value's structure drives dispatch, with
    a "set"-like hint routing list comparisons to Jaccard. Unparseable answers, a
    null/sentinel, or an answer whose structure cannot be sensibly compared to the
    truth all score 0.0. Exact (canonical) matches always score 1.0.
    """
    # 中文：精确匹配快捷路径，保证 partial >= 严格信号，并避免命中时的浮点漂移。
    # Exact-match shortcut keeps partial >= the strict signal and avoids
    # float drift on clean hits.
    if canonical_answer(answer) == canonical_answer(ground_truth) != "UNKNOWN":
        return 1.0

    a = _coerce(answer)
    t = _coerce(ground_truth)
    if a is None or t is None:
        return 0.0

    hint = (output_type or "").strip().lower()

    # 中文：数值标量(拒绝布尔，使其落到仅精确匹配的处理)。
    # Numeric scalar (reject bools so they fall through to exact-only handling).
    a_num, t_num = _as_number(a), _as_number(t)
    if a_num is not None and t_num is not None:
        return _score_numeric(a_num, t_num)

    # 中文：set 提示：把列表/序列答案当作无序集合评分。
    # Set hint: grade list/sequence answers as unordered sets.
    if hint in {"set", "set_of_values", "unordered_set"} and isinstance(
        a, (list, tuple)
    ) and isinstance(t, (list, tuple)):
        return _score_set(a, t)

    if isinstance(t, dict):
        return _score_dict(a, t) if isinstance(a, dict) else 0.0

    if isinstance(t, (list, tuple)):
        if not isinstance(a, (list, tuple)):
            return 0.0
        return _score_sequence(list(a), list(t))

    if isinstance(t, str):
        return _score_string(a, t) if isinstance(a, str) else 0.0

    if isinstance(t, bool):
        return 1.0 if a == t else 0.0

    # 中文：未知/不可比较的结构。
    # Unknown / incomparable structure.
    return 0.0
