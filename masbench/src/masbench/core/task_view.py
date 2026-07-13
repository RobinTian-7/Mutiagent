"""Public task view: the ONLY task dict shape allowed into model context.

The global task masbench builds carries a private scoring payload (the answer
key and per-agent expected outputs) that the scorer needs and the model must
never see. The old defence was a top-level denylist, which nested leaks walked
straight past (``meta.expected_outputs``). This module replaces it with an
explicit ALLOWLIST:

* :func:`public_task_view` keeps only known-safe fields and recursively drops
  everything else, so a new nested field is private-by-default.
* :func:`private_scoring_payload` is the single accessor scorers use to reach
  the private payload (kept under ``PRIVATE_SCORING_KEY`` in the global task).
* ``task_ref`` replaces ``case_id`` in anything model-visible: the raw Silo
  case id (e.g. ``II-12``) indexes a public benchmark file that contains the
  answers, so model context gets only an opaque digest of it.
"""
# ============================================================
# 【模块导读】public task view：允许进入模型上下文的唯一任务字典形状。
# 全局任务里带评分需要、模型绝不能看的 private scoring payload（答案键 +
# 逐 agent 期望输出）。旧防线是顶层黑名单，嵌套字段（meta.expected_outputs）
# 可以直接绕过；本模块改为显式白名单：public_task_view 只保留已知安全字段并
# 递归丢弃其余，新增嵌套字段默认私有。case_id 在模型可见面一律换成不可查表的
# task_ref 摘要（原始 case_id 可直接在公开基准文件里查到答案）。
# ============================================================

from __future__ import annotations

import hashlib
from typing import Any

# 中文：全局任务里私有评分载荷的保留键。任何模型可见渲染都必须先经
#   public_task_view，该键在白名单之外，物理上到不了提示词。
# Reserved key for the private scoring payload inside the global task. Every
# model-visible rendering goes through public_task_view, which allowlists it
# away, so the payload physically cannot reach a prompt.
PRIVATE_SCORING_KEY = "_private_scoring"

# 中文：模型可见的顶层字段白名单。刻意不含：case_id/case_name 原文之外的
#   meta、shards、answer_key、expected_outputs、segmented 映射之外的任何字段。
# Allowlisted top-level fields for model context. Deliberately excludes meta,
# shards, case_id, and every scoring field.
_PUBLIC_TOP_LEVEL: tuple[str, ...] = (
    "task_family",
    "benchmark",
    "task_ref",
    "case_name",
    "n_agents",
    "output_type",
    "segmented",
)


# 【职责】case_id 的不可逆短摘要：模型可见上下文中代替 case_id 的稳定标识。
def task_ref(case_id: str) -> str:
    """Opaque, stable reference for a case id (safe for model context)."""
    return hashlib.sha256(str(case_id).encode("utf-8")).hexdigest()[:12]


# 【职责】构造模型可见的公共任务视图（显式白名单；嵌套字段默认丢弃）。
# - 不含 meta/shards/case_id/答案类字段；task_ref 提供不可查表的任务标识。
def public_task_view(global_task: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted, nested-safe view of a global task for model context."""
    view: dict[str, Any] = {}
    for key in _PUBLIC_TOP_LEVEL:
        if key in global_task and global_task[key] is not None:
            view[key] = _public_scalar(global_task[key])
    if "task_ref" not in view and global_task.get("case_id") is not None:
        view["task_ref"] = task_ref(str(global_task["case_id"]))
    return view


# 【职责】白名单值只放行标量与字符串（防止把嵌套 dict 偷运出去）。
def _public_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # 中文：非标量一律转字符串截断——白名单字段本就不该是容器。
    # Non-scalars collapse to a truncated string: allowlisted fields are not
    # supposed to be containers in the first place.
    return str(value)[:200]


# 【职责】评分器专用：取全局任务里的 private scoring payload（模型不可见）。
def private_scoring_payload(global_task: dict[str, Any]) -> dict[str, Any]:
    """Scorer-only accessor for the private payload (empty dict if absent)."""
    payload = global_task.get(PRIVATE_SCORING_KEY)
    return payload if isinstance(payload, dict) else {}
