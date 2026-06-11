"""Opt-in evidence cache for bank-INDEPENDENT protocol runs.

Dev-round cost profile showed ~60-70% of spend is evolution evidence, and
rounds 2..R re-measure runs whose inputs are identical to round 1's: named-
topology evidence rows use a FRESH EMPTY bank by construction, and the
generation gate's ``j_before`` uses an empty bank + cold generation. At
temperature 0 these are the same measurement; re-running them buys no new
information. With ``MASBENCH_EVIDENCE_CACHE=<file>`` such runs are served from
a persistent JSON cache (thread-safe, write-through).

NEVER cached (bank-dependent or the actual measurement): explore runs, gate
``j_after``, and all paired-eval runs. Env unset: no behaviour change.

Honesty note (also in the phase-2 prereg changelog): caching replaces "a fresh
sample each round" with "the same sample reused". At temperature 0 the two are
statistically equivalent; judgment logic in the frozen verify scripts is
untouched -- they simply call this pipeline.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def cache_path() -> Path | None:
    raw = os.environ.get("MASBENCH_EVIDENCE_CACHE", "").strip()
    return Path(raw) if raw else None


class EvidenceCache:
    """Persistent (case, condition, model)-keyed store of evidence rows."""

    def __init__(self, path: Path | str | None) -> None:
        self._path = Path(path) if path else None
        self._data: dict[str, dict[str, Any]] = {}
        if self._path is not None and self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except Exception:
                self._data = {}

    @staticmethod
    def key(
        *,
        case_id: str,
        n_agents: int,
        planner_mode: str,
        objective: str,
        seed: int,
        cfg: Any,
    ) -> str:
        parts = (
            case_id, str(n_agents), planner_mode, objective, str(seed),
            str(getattr(cfg, "llm_provider", "")), str(getattr(cfg, "model_name", "")),
            str(getattr(cfg, "merge_mode", "")), str(getattr(cfg, "init_mode", "")),
            str(getattr(cfg, "temperature", "")),
            str(getattr(cfg, "num_graph_candidates", "")),
        )
        return "|".join(parts)

    def get(self, key: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data.get(key)
            return dict(row) if row is not None else None

    def put(self, key: str, row: dict[str, Any]) -> None:
        slim = {k: v for k, v in row.items() if _json_safe(v)}
        with _LOCK:
            self._data[key] = slim
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(self._data))


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def open_cache() -> EvidenceCache | None:
    """The env-configured cache, or None when disabled."""
    path = cache_path()
    return EvidenceCache(path) if path is not None else None
