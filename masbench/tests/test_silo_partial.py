"""Tests for graded PARTIAL-CORRECTNESS scoring on Silo-Bench (Plan 4 Task 2).

Strict success/exact-match stays 1.0/0.0; ``partial`` carries a graded signal in
[0, 1]. ``silo_partial_score`` accepts the natural (answer, ground_truth,
output_type) triple and coerces canonical-JSON strings via ``canonical_answer``-
style parsing, so it works whether it is handed a raw value or the canonical key
that masbench stores in ``global_task[GROUND_TRUTH_KEY]``.
"""

from __future__ import annotations

from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_protocol import SiloProtocolAdapter, score_protocol_answer
from masbench.adapters.silo_scoring import silo_partial_score, uses_official_lis
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.core.task_bridge import GROUND_TRUTH_KEY, canonical_answer
from masbench.engine import run_instance

DATA = Path(__file__).parent / "data"


def _instance(case_id: str) -> BenchmarkInstance:
    adapter = SiloBenchAdapter(DATA)
    return next(adapter.iter_instances(cases=[case_id]))


# --------------------------------------------------------------------------- #
# silo_partial_score: by-type fallback
# --------------------------------------------------------------------------- #
def test_numeric_near_miss_is_partial():
    # answer 8 vs truth 9: graded, strictly between 0 and 1, and NOT a success.
    score = silo_partial_score(8, 9, "distributed")
    assert 0.0 < score < 1.0
    # 1 - |8-9|/max(1,9) = 1 - 1/9 ~= 0.888...
    assert abs(score - (1 - 1 / 9)) < 1e-9


def test_numeric_exact_is_one():
    assert silo_partial_score(9, 9, "distributed") == 1.0


def test_numeric_string_coercion_matches_int():
    # canonical_answer renders the truth as a JSON string "9"; the scorer must
    # parse it back so "9" and 9 compare/grade identically.
    truth_key = canonical_answer(9)
    assert isinstance(truth_key, str)
    assert silo_partial_score("8", truth_key, "distributed") == silo_partial_score(
        8, 9, "distributed"
    )


def test_numeric_far_miss_floors_at_zero():
    # A wildly off answer never goes negative.
    assert silo_partial_score(-100, 1, "distributed") == 0.0


def test_zero_truth_numeric():
    assert silo_partial_score(0, 0, "distributed") == 1.0
    assert silo_partial_score(1, 0, "distributed") < 1.0
    assert silo_partial_score(1, 0, "distributed") >= 0.0


def test_sorted_list_near_miss_is_partial():
    # [1,2,4,3] vs [1,2,3,4]: two positions match exactly; ordering quality high
    # but not perfect. Either way it must land strictly inside (0, 1).
    score = silo_partial_score([1, 2, 4, 3], [1, 2, 3, 4], "distributed")
    assert 0.0 < score < 1.0


def test_list_exact_is_one():
    assert silo_partial_score([1, 2, 3, 4], [1, 2, 3, 4], "distributed") == 1.0


def test_list_reversed_is_low_but_ordered_subseq_counts():
    # Fully reversed: no position matches, but the LIS-based ordering ratio still
    # credits the single-element longest increasing subsequence (1/4), so the
    # blended score is low yet positive.
    score = silo_partial_score([4, 3, 2, 1], [1, 2, 3, 4], "distributed")
    assert 0.0 < score < 0.5


def test_set_jaccard():
    # Treated as sets when both look set-like via output_type hint "set".
    score = silo_partial_score([1, 2, 3], [2, 3, 4], "set")
    # Jaccard of {1,2,3} and {2,3,4} = |{2,3}| / |{1,2,3,4}| = 2/4 = 0.5
    assert abs(score - 0.5) < 1e-9


def test_dict_key_value_overlap():
    # {a:1, b:2, c:9} vs {a:1, b:5, c:9}: 2 of 3 key/value pairs match -> 2/3.
    score = silo_partial_score({"a": 1, "b": 2, "c": 9}, {"a": 1, "b": 5, "c": 9}, "distributed")
    assert abs(score - (2 / 3)) < 1e-9


def test_dict_exact_is_one():
    assert silo_partial_score({"a": 1, "b": 2}, {"a": 1, "b": 2}, "distributed") == 1.0


def test_string_token_overlap():
    # Non-numeric, non-JSON strings: normalized token overlap.
    score = silo_partial_score("the quick fox", "the quick brown fox", "distributed")
    assert 0.0 < score < 1.0


def test_string_exact_is_one():
    assert silo_partial_score("Candidate_D", "Candidate_D", "distributed") == 1.0


def test_unparseable_or_none_is_zero():
    assert silo_partial_score(None, 9, "distributed") == 0.0
    assert silo_partial_score("UNKNOWN", 9, "distributed") == 0.0


def test_type_mismatch_is_zero():
    # A scalar answer against a list truth cannot be graded sensibly -> 0.0.
    assert silo_partial_score(5, [1, 2, 3], "distributed") == 0.0


def test_official_lis_is_used_for_sequences():
    """We reuse Silo's official LIS primitive for sequence ordering quality."""
    assert uses_official_lis() is True


# --------------------------------------------------------------------------- #
# score_protocol_answer now exposes partial alongside exact_match
# --------------------------------------------------------------------------- #
def test_score_protocol_answer_carries_partial():
    inst = BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-09",
        case_name="Top-K",
        n_agents=2,
        shards=[[1, 2], [3, 4]],
        ground_truth=[1, 2, 3, 4],
        meta={"output_type": "distributed"},
    )
    adapter = SiloProtocolAdapter(inst)
    global_task = adapter.build_global_task()

    near = adapter.score_protocol_answer([1, 2, 4, 3], global_task)
    assert near["exact_match"] is False
    assert near["primary_metric"] == 0.0  # strict signal unchanged
    assert 0.0 < near["partial"] < 1.0  # graded signal present

    exact = adapter.score_protocol_answer([1, 2, 3, 4], global_task)
    assert exact["exact_match"] is True
    assert exact["primary_metric"] == 1.0
    assert exact["partial"] == 1.0


def test_score_protocol_answer_module_function_matches_method():
    inst = BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",
        case_name="Global Max",
        n_agents=2,
        shards=[[3, 1, 9, 2], [5, 8, 4]],
        ground_truth=9,
        meta={"output_type": "distributed"},
    )
    adapter = SiloProtocolAdapter(inst)
    global_task = adapter.build_global_task()
    assert score_protocol_answer(8, global_task) == adapter.score_protocol_answer(
        8, global_task
    )


# --------------------------------------------------------------------------- #
# End-to-end: ScoreResult.partial is a graded float in [0, 1]
# --------------------------------------------------------------------------- #
def test_run_instance_planner_partial_is_float():
    inst = _instance("I-01")
    cfg = RunConfig(use_planner=True, llm_provider="fake", n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert isinstance(score.partial, float)
    assert 0.0 <= score.partial <= 1.0
    # I-01 converges offline, so it is both an exact success and full partial.
    assert score.success is True
    assert score.partial == 1.0


def test_run_instance_planner_off_partial_is_float():
    inst = _instance("I-01")
    cfg = RunConfig(use_planner=False, llm_provider="fake", topology="mesh", n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert isinstance(score.partial, float)
    assert 0.0 <= score.partial <= 1.0
    assert score.success is True
    assert score.partial == 1.0


def test_run_instance_partial_independent_of_strict_success():
    """A non-converging task still yields a graded partial float (>= 0)."""
    inst = _instance("III-21")  # distributed sort: no offline solver
    cfg = RunConfig(use_planner=False, llm_provider="fake", topology="mesh", n_agents=2)
    score = run_instance(inst, cfg)
    assert isinstance(score.partial, float)
    assert 0.0 <= score.partial <= 1.0
