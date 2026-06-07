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
            match = _FILENAME_RE.search(path.name)
            if match is None:
                continue
            level = match.group("level")
            agents = int(match.group("agents"))
            if levels is not None and level not in set(levels):
                continue
            if agent_counts is not None and agents not in set(agent_counts):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if cases is not None and data.get("case_id") not in set(cases):
                continue
            yield self._to_instance(data)

    def _to_instance(self, data: dict) -> BenchmarkInstance:
        agent_configs = data["agent_configs"]
        shards = [ac["input_shard"] for ac in agent_configs]
        expected_outputs = [ac.get("expected_output") for ac in agent_configs]
        metadata = dict(data.get("metadata", {}))
        metadata["expected_outputs"] = expected_outputs
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
