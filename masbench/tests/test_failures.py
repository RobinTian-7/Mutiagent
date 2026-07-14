from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest

from exp_graph.llm.timeout import LLMTimeoutError
from exp_graph.mas.graph_generation import GraphGenerationError
from exp_graph.mas.schemas import ObjectiveSpec, PythonSkillPayload, SkillCard

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import (
    _collect_rows,
    _merge_failure_clusters_into_skill,
    _validate_v2_config,
)
from masbench.failures import (
    AlgorithmFailureError,
    FailureClass,
    FailureRecord,
    classify_exception,
    cluster_failure_records,
    make_failure_record,
    zero_scored_metrics,
)
from masbench.llm.fake import BenchmarkFakeLLMClient


DATA = Path(__file__).parent / "data"


def _record(**updates) -> FailureRecord:
    values = {
        "exc": AlgorithmFailureError("invalid action", stage="action"),
        "planner_mode": "python_generate",
        "information_goal": "all_agents",
        "worker_contract": "message_only_v2",
        "case_id": "II-01",
        "seed": 11,
        "n_agents": 5,
        "branch": "mutate",
        "parent_skill_id": "python_parent",
        "missing_submitters": [3],
        "structural_signature": "hash:abc",
    }
    values.update(updates)
    return make_failure_record(**values)


def test_failure_classifier_is_type_driven_and_unknowns_abort() -> None:
    assert classify_exception(GraphGenerationError("bad graph")) == FailureClass.ALGORITHM
    assert classify_exception(LLMTimeoutError("late")) == FailureClass.INFRASTRUCTURE
    assert classify_exception(AssertionError("host invariant")) == FailureClass.HARNESS
    assert classify_exception(RuntimeError("unknown")) == FailureClass.HARNESS
    with pytest.raises(ValueError, match="failure_policy"):
        _validate_v2_config(RunConfig(failure_policy="typo"))


def test_algorithm_failure_scores_zero_but_preserves_cost() -> None:
    exc = AlgorithmFailureError(
        "invalid submit",
        stage="submit",
        metrics={"C": 14.5, "D": 0.2, "messages": 4, "model_calls": 6, "tokens": 99},
    )
    metrics = zero_scored_metrics(exc)
    assert metrics == {
        "success": 0.0,
        "S": 0.0,
        "P": 0.0,
        "C": 14.5,
        "D": 0.2,
        "messages": 4,
        "model_calls": 6,
        "tokens": 99,
        "per_agent_submissions": [],
    }


def test_failure_record_forbids_unstructured_answer_fields() -> None:
    record = _record()
    payload = record.model_dump(mode="json")
    assert "answer" not in payload
    assert "ground_truth" not in payload
    with pytest.raises(ValidationError):
        FailureRecord.model_validate({**payload, "answer": "leak"})


def test_failure_clusters_are_stable_and_deduplicate_records() -> None:
    first = _record()
    duplicate = _record()
    second = _record(seed=12, missing_submitters=[4])

    one = cluster_failure_records([first, duplicate, second])
    two = cluster_failure_records([second, first])

    assert len(one) == 1
    assert one[0].count == 2
    assert one[0].cluster_id == two[0].cluster_id
    assert set(one[0].record_ids) == {first.record_id, second.record_id}
    assert len(one[0].counterexamples) == 2


def test_failure_cluster_merge_is_deduplicated_and_mode_goal_contract_scoped() -> None:
    matching = _record()
    wrong_goal = _record(information_goal="sink", seed=12)
    wrong_contract = _record(worker_contract="message_only_v1", seed=13)
    clusters = cluster_failure_records([matching, wrong_goal, wrong_contract])
    skill = SkillCard(
        skill_id="python_parent",
        task_family="silo",
        information_goal="all_agents",
        trigger={
            "planner_mode": "python_generate",
            "information_goal": "all_agents",
        },
        mode_payload=PythonSkillPayload(
            source_code="def main():\n    return None\n",
            ast_policy_version="python_ast_v1",
            execution_contract_version="python_mas_v1",
            worker_contract="message_only_v2",
        ),
    )

    merged = _merge_failure_clusters_into_skill(skill, clusters)
    merged_again = _merge_failure_clusters_into_skill(merged, clusters)

    assert len(merged.failure_modes) == 1
    assert merged.failure_modes == merged_again.failure_modes
    assert merged.failure_modes[0]["error_type"] == "AlgorithmFailureError"


def test_honest_collector_zero_scores_drops_or_aborts_by_failure_class(
    monkeypatch,
) -> None:
    monkeypatch.delenv("MASBENCH_EVIDENCE_CACHE", raising=False)
    instance = next(SiloBenchAdapter(DATA).iter_instances(cases=["I-01"]))
    cfg = RunConfig(
        planner_mode="graph_generate",
        llm_provider="fake",
        model_name="fake",
        n_agents=2,
        failure_policy="honest_v2",
        task_feature_source="heuristic",
    )
    objective = ObjectiveSpec.from_name("balanced")
    client = BenchmarkFakeLLMClient()

    def collect(exc: BaseException):
        records = []

        def fail(*args, **kwargs):
            del args, kwargs
            raise exc

        monkeypatch.setattr("masbench.evolve._run_one", fail)
        rows = _collect_rows(
            [instance],
            cfg,
            objective_variants=[objective],
            seeds=[11],
            llm_client=client,
            failure_records=records,
        )
        return rows, records

    rows, records = collect(
        AlgorithmFailureError(
            "invalid action",
            stage="action",
            metrics={"messages": 3, "tokens": 40, "C": 40.0, "D": 0.3},
        )
    )
    assert len(rows) == 1
    assert rows[0]["program_validity"] == 0.0
    assert rows[0]["evolution_success"] == 0.0
    assert rows[0]["MeanTotalMessages"] == 3.0
    assert rows[0]["MeanTokenCost"] == 40.0
    assert records[0].failure_class == FailureClass.ALGORITHM

    rows, records = collect(LLMTimeoutError("provider timeout"))
    assert rows == []
    assert records[0].failure_class == FailureClass.INFRASTRUCTURE

    with pytest.raises(RuntimeError, match="host bug"):
        collect(RuntimeError("host bug"))
