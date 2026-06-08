"""Silo-Bench loader: benchmarks/{Level}-{NN}_n{agents}.json -> BenchmarkInstance."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from masbench.core.benchmark import BenchmarkAdapter
from masbench.core.instance import BenchmarkInstance

_FILENAME_RE = re.compile(r"(?P<level>[IVX]+)-(?P<num>\d+)_n(?P<agents>\d+)\.json$")


class SiloBenchAdapter(BenchmarkAdapter):
    """Load Silo-Bench instances from a directory of benchmark JSON files."""

    name = "silo_bench"

    def __init__(self, benchmarks_dir: str | Path) -> None:
        self.benchmarks_dir = Path(benchmarks_dir)

    def iter_instances(
        self,
        *,
        levels: list[str] | None = None,
        agent_counts: list[int] | None = None,
        cases: list[str] | None = None,
    ) -> Iterable[BenchmarkInstance]:
        if not self.benchmarks_dir.is_dir():
            raise FileNotFoundError(
                f"Silo-Bench benchmarks dir not found: {self.benchmarks_dir}. "
                "Add the submodule or pass --benchmarks-dir (see masbench/README.md)."
            )
        for path in sorted(self.benchmarks_dir.glob("*.json")):
            resolved = self._resolve_file(path)
            if resolved is None:
                continue
            data, level, agents = resolved
            if levels is not None and level not in set(levels):
                continue
            if agent_counts is not None and agents not in set(agent_counts):
                continue
            if cases is not None and data.get("case_id") not in set(cases):
                continue
            yield self._to_instance(data)

    def _resolve_file(self, path: Path) -> tuple[dict, str, int] | None:
        """Return ``(data, level, agents)`` for a loadable instance file, else None.

        Fast path: the canonical ``{Level}-{NN}_n{agents}.json`` filename encodes
        level + agent count, so non-instance files (e.g. ``benchmark_summary.json``)
        are skipped without being read. Fallback: a file whose name does not match
        (e.g. a vendored test fixture) is loaded only if its body is structurally a
        single instance (has ``case_id`` + ``agent_configs``); ``level`` is then
        derived from the ``case_id`` prefix and ``agents`` from the body. Aggregate
        files lack those keys and so are still skipped.
        """
        match = _FILENAME_RE.search(path.name)
        if match is not None:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data, match.group("level"), int(match.group("agents"))

        data = json.loads(path.read_text(encoding="utf-8"))
        if not (isinstance(data, dict) and "case_id" in data and "agent_configs" in data):
            return None
        case_id = str(data["case_id"])
        level = case_id.split("-", 1)[0] if "-" in case_id else case_id
        metadata = data.get("metadata", {})
        agents = int(metadata.get("num_agents", len(data["agent_configs"])))
        return data, level, agents

    def _to_instance(self, data: dict) -> BenchmarkInstance:
        agent_configs = data["agent_configs"]
        shards = [ac["input_shard"] for ac in agent_configs]
        expected_outputs = [ac.get("expected_output") for ac in agent_configs]
        metadata = dict(data.get("metadata", {}))
        # Per-agent expected answers (segmented tasks differ per agent; plain
        # tasks repeat the single global answer). Always carried so the engine
        # can grade per agent.
        metadata["expected_outputs"] = expected_outputs
        # Normalize the segmented flag to a real bool so the engine can branch on
        # it unconditionally (older/synthetic files may omit it -> False).
        metadata["is_segmented"] = bool(metadata.get("is_segmented", False))
        return BenchmarkInstance(
            benchmark="silo_bench",
            case_id=data["case_id"],
            case_name=data.get("case_name", ""),
            n_agents=int(metadata.get("num_agents", len(agent_configs))),
            shards=shards,
            ground_truth=expected_outputs[0] if expected_outputs else None,
            task_prompt=data.get("task_description", ""),
            meta=metadata,
        )
