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


def serialize_spec(spec: Any) -> Any:
    """ProtocolGraphSpec | dict | None -> JSON-safe value."""
    if spec is None or isinstance(spec, dict):
        return spec
    dump = getattr(spec, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return str(spec)
