"""Opt-in self-evolve diagnostics dump, gated by ``MASBENCH_EVOLVE_DUMP_DIR``.

``verify_evolve.py`` is the frozen judgment target and must not grow features,
so mechanism evidence is exported from the pipeline side instead: when the env
var names a directory, ``run_evolution`` writes its full summary (evolved bank,
gate decision, motif stats) to ``evolution_NNN.json`` and every ``_run_one``
appends one JSONL record (per-run topology / generated DAG spec / metrics) to
``eval_runs.jsonl``. A verify run then yields before/after design evidence as a
side effect, at zero extra LLM cost. Env unset: everything is a no-op and the
pipeline is byte-identical.
"""
# ============================================================
# 【模块导读】可选启用的自进化诊断转储，由环境变量 MASBENCH_EVOLVE_DUMP_DIR 控制。
# verify_evolve.py 是冻结的判定目标、不许新增功能，因此机制证据改由管线一侧导出：
# 当该环境变量指向一个目录时，run_evolution 会把完整总结（进化后技能库、门决策、
# 结构母题统计）写入 evolution_NNN.json，且每次 _run_one 都向 eval_runs.jsonl 追加
# 一条 JSONL 记录（单次运行的拓扑 / 生成的 DAG spec / 指标）。于是一次 verify 运行
# 顺带产出进化前后的设计证据，额外 LLM 成本为零。环境变量未设置：一切都是空操作，
# 管线逐字节不变。
# ============================================================
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def dump_dir() -> Path | None:
    raw = os.environ.get("MASBENCH_EVOLVE_DUMP_DIR", "").strip()
    return Path(raw) if raw else None


def enabled() -> bool:
    return dump_dir() is not None


# 【职责】写出一份带自增编号的进化总结 JSON（技能库 + 门决策 + 结构母题）。
def dump_evolution_summary(summary: dict[str, Any]) -> None:
    """Write one numbered evolution summary JSON (bank + gate + motifs)."""
    directory = dump_dir()
    if directory is None:
        return
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        index = len(list(directory.glob("evolution_*.json")))
        path = directory / f"evolution_{index:03d}.json"
        path.write_text(json.dumps(summary, indent=2, default=str))


# 【职责】向 eval_runs.jsonl 追加一条单次运行记录（线程安全；_run_one 会在多工作线程间扇出）。
def dump_eval_run(record: dict[str, Any]) -> None:
    """Append one per-run record (thread-safe; _run_one fans out across workers)."""
    directory = dump_dir()
    if directory is None:
        return
    line = json.dumps(record, default=str)
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "eval_runs.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# 【职责】把 ProtocolGraphSpec | dict | None 转成 JSON 安全值（优先走 model_dump）。
def serialize_spec(spec: Any) -> Any:
    """ProtocolGraphSpec | dict | None -> JSON-safe value."""
    if spec is None or isinstance(spec, dict):
        return spec
    dump = getattr(spec, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return str(spec)
