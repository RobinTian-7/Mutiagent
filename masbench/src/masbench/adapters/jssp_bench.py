"""JSSP loader: OR-library-format ``*.jssp`` files -> BenchmarkInstance.

Job-Shop Scheduling (JSSP, REALM-Bench / M-APPLE-OS, arXiv 2502.18836) mapped
onto masbench's generalized multi-agent interface: each AGENT owns exactly ONE
JOB's ordered operation list, machines are exclusive, and the team must agree
on one global schedule minimizing makespan.

File format (OR-library job-shop):
    * lines starting with ``#`` are comments; an optional ``# ub: <int>``
      comment carries the known upper bound (optimal makespan);
    * the first non-comment line is ``n_jobs n_machines``;
    * then one line per job: ``machine duration`` pairs, one pair per
      operation, in processing order.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from masbench.core.benchmark import BenchmarkAdapter
from masbench.core.instance import BenchmarkInstance

_UB_RE = re.compile(r"^#\s*ub\s*:\s*(\d+)\s*$", re.IGNORECASE)

# Natural-language statement rendered per agent by
# BenchmarkTaskAdapter.format_task_prompt_context ({agent_id}/{input_shard} are
# literal placeholders replaced there; the JSON braces survive because the
# bridge uses str.replace, not str.format).
_TASK_PROMPT = (
    "Job-Shop Scheduling (JSSP). The team must schedule {n_jobs} jobs on "
    "{n_machines} machines.\n"
    "You are agent {agent_id} and you own exactly ONE job: job {agent_id}. "
    "Your job's ordered operations are: {input_shard}\n"
    "Each operation is a pair [machine, duration]. Operations of a job MUST "
    "run in the listed order: operation k+1 may start only after operation k "
    "has finished. Each machine can process at most one operation at a time "
    "(machines are exclusive; no preemption; durations are fixed).\n"
    "Goal: cooperate with the other agents to produce ONE global schedule "
    "covering every operation of every job that MINIMIZES the makespan (the "
    "time the last operation finishes).\n"
    'The final answer must be a single JSON object of the form '
    '{"makespan": <int>, "schedule": [{"job": <j>, "op": <k>, '
    '"machine": <m>, "start": <s>, "end": <e>}, ...]} with one entry per '
    "operation (every (job, op) exactly once), integer times, and "
    "start/end consistent with the durations and constraints above."
)


def _parse_jssp_file(path: Path) -> tuple[int, int, list[list[list[int]]], int | None]:
    """Parse one ``*.jssp`` file -> (n_jobs, n_machines, jobs, upper_bound).

    ``jobs[j]`` is job ``j``'s ordered operation list ``[[machine, duration],
    ...]``. ``upper_bound`` is the ``# ub: <int>`` comment value, or None.
    """
    upper_bound: int | None = None
    data_lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = _UB_RE.match(line)
            if match is not None:
                upper_bound = int(match.group(1))
            continue
        data_lines.append(line)

    if not data_lines:
        raise ValueError(f"JSSP file has no data lines: {path}")
    header = data_lines[0].split()
    if len(header) < 2:
        raise ValueError(f"JSSP header must be 'n_jobs n_machines': {path}")
    n_jobs, n_machines = int(header[0]), int(header[1])
    if n_jobs < 1 or n_machines < 1:
        raise ValueError(f"JSSP needs >=1 job and >=1 machine: {path}")
    if len(data_lines) - 1 < n_jobs:
        raise ValueError(
            f"JSSP file declares {n_jobs} jobs but has only "
            f"{len(data_lines) - 1} job lines: {path}"
        )

    jobs: list[list[list[int]]] = []
    for job_idx in range(n_jobs):
        tokens = [int(tok) for tok in data_lines[1 + job_idx].split()]
        if not tokens or len(tokens) % 2 != 0:
            raise ValueError(
                f"job line {job_idx} must hold 'machine duration' pairs: {path}"
            )
        ops = [[tokens[i], tokens[i + 1]] for i in range(0, len(tokens), 2)]
        for machine, duration in ops:
            if not (0 <= machine < n_machines):
                raise ValueError(
                    f"job {job_idx} references machine {machine} outside "
                    f"0..{n_machines - 1}: {path}"
                )
            if duration < 0:
                raise ValueError(f"job {job_idx} has negative duration: {path}")
        jobs.append(ops)
    return n_jobs, n_machines, jobs, upper_bound


class JSSPBenchAdapter(BenchmarkAdapter):
    """Load JSSP instances from a directory of OR-library-format ``*.jssp`` files."""

    name = "jssp"

    def __init__(self, benchmarks_dir: str | Path) -> None:
        self.benchmarks_dir = Path(benchmarks_dir)

    def iter_instances(
        self,
        *,
        levels: list[str] | None = None,
        agent_counts: list[int] | None = None,
        cases: list[str] | None = None,
    ) -> Iterable[BenchmarkInstance]:
        """Yield instances. ``levels`` is accepted for interface parity but JSSP
        has no level taxonomy (ignored); ``agent_counts`` filters by n_jobs;
        ``cases`` filters by case_id (= filename stem)."""
        del levels  # JSSP has no levels; accepted so generic callers can pass it.
        if not self.benchmarks_dir.is_dir():
            raise FileNotFoundError(
                f"JSSP benchmarks dir not found: {self.benchmarks_dir}. "
                "Pass --benchmarks-dir pointing at a directory of *.jssp files."
            )
        for path in sorted(self.benchmarks_dir.glob("*.jssp")):
            case_id = path.stem
            if cases is not None and case_id not in set(cases):
                continue
            n_jobs, n_machines, jobs, upper_bound = _parse_jssp_file(path)
            if agent_counts is not None and n_jobs not in set(agent_counts):
                continue
            yield self._to_instance(case_id, n_jobs, n_machines, jobs, upper_bound)

    def _to_instance(
        self,
        case_id: str,
        n_jobs: int,
        n_machines: int,
        jobs: list[list[list[int]]],
        upper_bound: int | None,
    ) -> BenchmarkInstance:
        # Known optimum if provided; otherwise the trivially-feasible naive
        # bound (run every operation back to back = sum of all durations).
        bound = (
            int(upper_bound)
            if upper_bound is not None
            else sum(duration for ops in jobs for _machine, duration in ops)
        )
        task_prompt = _TASK_PROMPT.replace("{n_jobs}", str(n_jobs)).replace(
            "{n_machines}", str(n_machines)
        )
        return BenchmarkInstance(
            benchmark="jssp",
            case_id=case_id,
            case_name=f"JSSP {n_jobs}x{n_machines}",
            n_agents=n_jobs,
            shards=jobs,
            ground_truth=bound,
            task_prompt=task_prompt,
            meta={
                "n_machines": n_machines,
                "upper_bound": bound,
                "output_type": "json",
                "is_segmented": False,
            },
        )
