"""Central, auditable failure semantics for benchmark and evolution runs.

The important distinction is scientific rather than cosmetic: an invalid
program is evidence about the algorithm and must score zero, while a transient
provider outage says nothing about either arm and may justify dropping the
whole paired unit.  Host/configuration bugs are never converted into data.
"""

from __future__ import annotations

import errno
import hashlib
import json
import socket
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from urllib.error import URLError

from pydantic import BaseModel, ConfigDict, Field

import masbench  # noqa: F401  (bootstraps the sibling exp_graph package)
from exp_graph.llm.timeout import LLMTimeoutError
from exp_graph.mas.graph_generation import GraphGenerationError
from exp_graph.mas.phase_program import PhaseProgramError
from exp_graph.mas.phase_program_generation import PhaseProgramGenerationError
from exp_graph.mas.python_code import PythonCodeError
from exp_graph.mas.python_code_generation import PythonGenerationError
from exp_graph.mas.python_mutation import PythonMutationError
from exp_graph.mas.topology_program import TopologyProgramError
from exp_graph.runner.protocol import ProtocolActionError


class FailureClass(str, Enum):
    SUCCESS = "success"
    ALGORITHM = "algorithm_failure"
    INFRASTRUCTURE = "infrastructure_failure"
    HARNESS = "harness_error"


class ClassifiedFailure(RuntimeError):
    """Base exception carrying safe stage/cost metadata across a boundary."""

    failure_class: FailureClass

    def __init__(
        self,
        message: str,
        *,
        stage: str = "unknown",
        metrics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.metrics = dict(metrics or {})


class AlgorithmFailureError(ClassifiedFailure):
    failure_class = FailureClass.ALGORITHM


class InfrastructureFailureError(ClassifiedFailure):
    failure_class = FailureClass.INFRASTRUCTURE


class HarnessError(ClassifiedFailure):
    failure_class = FailureClass.HARNESS


_ALGORITHM_EXCEPTIONS = (
    AlgorithmFailureError,
    GraphGenerationError,
    PhaseProgramGenerationError,
    PythonGenerationError,
    PythonCodeError,
    PythonMutationError,
    PhaseProgramError,
    TopologyProgramError,
    ProtocolActionError,
)
_INFRASTRUCTURE_EXCEPTIONS = (
    InfrastructureFailureError,
    LLMTimeoutError,
    TimeoutError,
    ConnectionError,
    socket.timeout,
    URLError,
)
_TRANSIENT_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EHOSTUNREACH,
    errno.ENETDOWN,
    errno.ENETUNREACH,
    errno.ENETRESET,
    errno.EPIPE,
    errno.ETIMEDOUT,
}


def _optional_network_exception_types() -> tuple[type[BaseException], ...]:
    """Resolve installed provider/network exceptions without requiring them."""
    result: list[type[BaseException]] = []
    try:
        import httpx

        result.extend(
            [
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ]
        )
    except ImportError:
        pass
    try:
        import openai

        result.extend([openai.APIConnectionError, openai.APITimeoutError])
    except (ImportError, AttributeError):
        pass
    return tuple(result)


_OPTIONAL_NETWORK_EXCEPTIONS = _optional_network_exception_types()


def classify_exception(exc: BaseException) -> FailureClass:
    """Classify from concrete exception types; unknowns are harness errors."""
    if isinstance(exc, _ALGORITHM_EXCEPTIONS):
        return FailureClass.ALGORITHM
    if isinstance(exc, _INFRASTRUCTURE_EXCEPTIONS + _OPTIONAL_NETWORK_EXCEPTIONS):
        return FailureClass.INFRASTRUCTURE
    if isinstance(exc, OSError) and exc.errno in _TRANSIENT_ERRNOS:
        return FailureClass.INFRASTRUCTURE
    if isinstance(exc, HarnessError):
        return FailureClass.HARNESS
    # Assertion/config/schema failures and every unknown exception are host-side
    # until explicitly typed otherwise.  This prevents silent scientific drops.
    return FailureClass.HARNESS


def failure_stage(exc: BaseException, default: str = "unknown") -> str:
    value = getattr(exc, "stage", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(exc, (GraphGenerationError, PhaseProgramGenerationError)):
        return "generation"
    if isinstance(exc, PythonGenerationError):
        return str(exc.error_type or "python_generation")
    if isinstance(exc, PythonCodeError):
        return str(getattr(exc, "error_type", None) or "python_execution")
    return default


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def zero_scored_metrics(
    exc: BaseException | None = None,
    *,
    prior_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return S/P=0 while retaining cost already incurred by a failed arm."""
    carried: dict[str, Any] = {}
    if isinstance(getattr(exc, "metrics", None), Mapping):
        carried.update(getattr(exc, "metrics"))
    if prior_metrics:
        carried.update(prior_metrics)
    return {
        "success": 0.0,
        "S": 0.0,
        "P": 0.0,
        "C": _finite_number(carried.get("C", carried.get("paper_C", 0.0))),
        "D": _finite_number(carried.get("D", carried.get("paper_D", 0.0))),
        "messages": int(_finite_number(carried.get("messages", 0))),
        "model_calls": int(_finite_number(carried.get("model_calls", 0))),
        "tokens": int(_finite_number(carried.get("tokens", 0))),
        "per_agent_submissions": [],
    }


class FailureRecord(BaseModel):
    """Answer-free failure evidence suitable for persistence and prompting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_key: str = Field(min_length=1)
    failure_class: FailureClass
    planner_mode: str = Field(min_length=1)
    information_goal: str = Field(min_length=1)
    worker_contract: str = Field(default="n/a", min_length=1)
    case_id: str = Field(min_length=1)
    seed: int
    n_agents: int = Field(ge=1)
    branch: str = Field(default="main", min_length=1)
    parent_skill_id: str | None = None
    program_sha256: str | None = None
    failure_stage: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    missing_submitters: tuple[int, ...] = ()
    error_agent_ids: tuple[int, ...] = ()
    missing_source_ids_by_agent: dict[int, tuple[int, ...]] = Field(
        default_factory=dict
    )
    per_agent_partial: dict[int, float] = Field(default_factory=dict)
    artifact_reference: str | None = None
    structural_signature: str = Field(default="unknown", min_length=1)

    @property
    def record_id(self) -> str:
        payload = self.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        return f"failure_{digest}"


class FailureCluster(BaseModel):
    """Stable grouping of equivalent answer-free failure records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: str = Field(min_length=1)
    planner_mode: str = Field(min_length=1)
    information_goal: str = Field(min_length=1)
    worker_contract: str = Field(min_length=1)
    failure_stage: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    structural_signature: str = Field(min_length=1)
    count: int = Field(ge=1)
    record_ids: tuple[str, ...]
    summary: str = Field(min_length=1)
    counterexamples: tuple[dict[str, Any], ...] = ()


def make_failure_record(
    *,
    exc: BaseException,
    planner_mode: str,
    information_goal: str,
    case_id: str,
    seed: int,
    n_agents: int,
    branch: str = "main",
    worker_contract: str = "n/a",
    parent_skill_id: str | None = None,
    program_sha256: str | None = None,
    stage: str | None = None,
    missing_submitters: list[int] | tuple[int, ...] = (),
    error_agent_ids: list[int] | tuple[int, ...] = (),
    missing_source_ids_by_agent: Mapping[int, list[int] | tuple[int, ...]] | None = None,
    per_agent_partial: Mapping[int, float] | None = None,
    artifact_reference: str | Path | None = None,
    structural_signature: str = "unknown",
) -> FailureRecord:
    run_key = f"{case_id}|n={n_agents}|seed={seed}|{planner_mode}|{branch}"
    return FailureRecord(
        run_key=run_key,
        failure_class=classify_exception(exc),
        planner_mode=planner_mode,
        information_goal=information_goal,
        worker_contract=worker_contract,
        case_id=case_id,
        seed=seed,
        n_agents=n_agents,
        branch=branch,
        parent_skill_id=parent_skill_id,
        program_sha256=program_sha256,
        failure_stage=stage or failure_stage(exc),
        error_type=type(exc).__name__,
        missing_submitters=tuple(sorted(set(missing_submitters))),
        error_agent_ids=tuple(sorted(set(error_agent_ids))),
        missing_source_ids_by_agent={
            int(agent): tuple(sorted(set(ids)))
            for agent, ids in (missing_source_ids_by_agent or {}).items()
        },
        per_agent_partial={
            int(agent): max(0.0, min(1.0, float(value)))
            for agent, value in (per_agent_partial or {}).items()
        },
        artifact_reference=(str(artifact_reference) if artifact_reference else None),
        structural_signature=structural_signature,
    )


def _cluster_key(record: FailureRecord) -> tuple[str, ...]:
    return (
        record.planner_mode,
        record.information_goal,
        record.worker_contract,
        record.failure_stage,
        record.error_type,
        record.structural_signature,
    )


def cluster_failure_records(records: list[FailureRecord]) -> list[FailureCluster]:
    grouped: dict[tuple[str, ...], dict[str, FailureRecord]] = {}
    for record in records:
        grouped.setdefault(_cluster_key(record), {})[record.record_id] = record
    clusters: list[FailureCluster] = []
    for key in sorted(grouped):
        unique = grouped[key]
        digest = hashlib.sha256(
            json.dumps(key, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        first = next(iter(unique.values()))
        counterexamples: list[dict[str, Any]] = []
        for record in unique.values():
            example = {
                "missing_submitters": list(record.missing_submitters),
                "error_agent_ids": list(record.error_agent_ids),
                "missing_source_ids_by_agent": {
                    str(agent): list(ids)
                    for agent, ids in record.missing_source_ids_by_agent.items()
                },
            }
            if any(example.values()) and example not in counterexamples:
                counterexamples.append(example)
            if len(counterexamples) >= 3:
                break
        clusters.append(
            FailureCluster(
                cluster_id=f"failure_cluster_{digest}",
                planner_mode=first.planner_mode,
                information_goal=first.information_goal,
                worker_contract=first.worker_contract,
                failure_stage=first.failure_stage,
                error_type=first.error_type,
                structural_signature=first.structural_signature,
                count=len(unique),
                record_ids=tuple(sorted(unique)),
                summary=(
                    f"{len(unique)} {first.error_type} failure(s) during "
                    f"{first.failure_stage} for {first.planner_mode}/"
                    f"{first.information_goal}"
                ),
                counterexamples=tuple(counterexamples),
            )
        )
    return clusters


def relevant_failure_context(
    clusters: list[FailureCluster],
    *,
    planner_mode: str,
    information_goal: str,
    worker_contract: str | None = None,
    limit: int = 4,
    max_chars: int = 4_000,
) -> list[dict[str, Any]]:
    """Return a small deterministic negative context for an architect."""
    relevant = [
        cluster
        for cluster in clusters
        if cluster.planner_mode == planner_mode
        and cluster.information_goal == information_goal
        and (worker_contract is None or cluster.worker_contract == worker_contract)
    ]
    relevant.sort(key=lambda item: (-item.count, item.cluster_id))
    output: list[dict[str, Any]] = []
    used = 2
    for cluster in relevant[: max(0, limit)]:
        item = cluster.model_dump(mode="json")
        encoded = json.dumps(item, sort_keys=True)
        if used + len(encoded) > max_chars:
            break
        output.append(item)
        used += len(encoded) + 1
    return output
