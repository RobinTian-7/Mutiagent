"""Segmented Silo-Bench scoring (Plan 4 Task 3).

Segmented tasks give every agent its OWN ``expected_output`` (not one shared
global answer), so the vote-based single-answer success rate is meaningless for
them. These tests cover:

* the loader marking ``is_segmented`` + per-agent ``expected_outputs``;
* ``BenchmarkInstance.segmented`` convenience + the same flag on ``global_task``;
* the engine's per-agent segmented scoring path (end to end, offline) returning
  the segmented structure without crashing;
* a direct unit test of ``_score_segmented`` against CONSTRUCTED final agent
  states, where per-agent correctness is fully deterministic;
* non-segmented instances staying on the unchanged (vote) scoring path.
"""

from __future__ import annotations

from pathlib import Path

from exp_graph.agents.schemas import AgentState, BeliefState, BeliefStatus
from exp_graph.runner.protocol import ProtocolExperimentResult

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.engine import _score_segmented, run_instance

DATA = Path(__file__).parent / "data"


def _instance(case_id: str) -> BenchmarkInstance:
    adapter = SiloBenchAdapter(DATA)
    return next(adapter.iter_instances(cases=[case_id]))


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
def test_loader_marks_segmented() -> None:
    """The loader carries is_segmented + per-agent expected_outputs."""
    seg = _instance("SEG-99")
    assert seg.meta["is_segmented"] is True
    assert seg.segmented is True
    assert seg.meta["expected_outputs"] == [[1, 3, 6], [10, 15]]

    plain = _instance("I-01")
    assert plain.meta["is_segmented"] is False
    assert plain.segmented is False
    # Non-segmented agents all share the single global answer.
    assert plain.meta["expected_outputs"] == [9, 9]


def test_global_task_carries_segmented_flag() -> None:
    """build_global_task surfaces the segmented flag for the engine."""
    seg = _instance("SEG-99")
    global_task = SiloProtocolAdapter(seg).build_global_task()
    assert global_task["segmented"] is True

    plain_task = SiloProtocolAdapter(_instance("I-01")).build_global_task()
    assert plain_task["segmented"] is False


# --------------------------------------------------------------------------- #
# Engine end-to-end: the segmented scoring PATH runs and is structured.
# --------------------------------------------------------------------------- #
def test_segmented_scoring_per_agent_planner_off() -> None:
    """Planner-OFF run on the segmented fixture uses per-agent scoring.

    Offline (fake LLM, deterministic) there is no per-agent segment solver for
    this synthetic task, so neither agent recovers its own expected segment:
    ``success`` is deterministically False and ``per_agent_correct`` is all
    False. What matters is that the SEGMENTED path is taken (``extra`` carries
    the per-agent structure) instead of the single voted answer.
    """
    seg = _instance("SEG-99")
    cfg = RunConfig(topology="mesh", llm_provider="fake", max_rounds=2, n_agents=2)
    score = run_instance(seg, cfg)

    assert isinstance(score, ScoreResult)
    assert score.extra["segmented"] is True
    assert score.extra["per_agent_correct"] == [False, False]
    assert score.success is False
    assert isinstance(score.partial, float)
    assert 0.0 <= score.partial <= 1.0


def test_segmented_scoring_per_agent_planner_on() -> None:
    """Planner-ON run on the segmented fixture also uses per-agent scoring."""
    seg = _instance("SEG-99")
    cfg = RunConfig(use_planner=True, llm_provider="fake", n_agents=2)
    score = run_instance(seg, cfg)

    assert isinstance(score, ScoreResult)
    assert score.extra["planner"] is True
    assert score.extra["segmented"] is True
    assert isinstance(score.extra["per_agent_correct"], list)
    assert len(score.extra["per_agent_correct"]) == 2


def test_non_segmented_unchanged() -> None:
    """I-01 still scored the normal (vote) way; no segmented tag."""
    plain = _instance("I-01")
    cfg = RunConfig(topology="mesh", llm_provider="fake", max_rounds=3, n_agents=2)
    score = run_instance(plain, cfg)

    assert score.extra.get("segmented") in (None, False)
    assert "per_agent_correct" not in score.extra
    # Unchanged offline associative-reduce convergence to the global max.
    assert score.success is True
    assert score.final_answer == "9"


# --------------------------------------------------------------------------- #
# Direct unit test of _score_segmented with CONSTRUCTED final agent states.
# --------------------------------------------------------------------------- #
def _belief_with_answer(answer: object, agent_id: int, n_agents: int) -> AgentState:
    """Build an AgentState whose belief carries ``answer`` like the runner would."""
    belief = BeliefState(
        status=BeliefStatus.FINAL,
        proposal="constructed",
        consensus_key="constructed",
        structured_state={"task_name": "silo", "case_id": "SEG-99", "answer": answer},
    )
    return AgentState(
        local_observation={"agent_id": agent_id, "n_agents": n_agents},
        belief_state=belief,
    )


def _result_with_states(states: list[AgentState]) -> ProtocolExperimentResult:
    """Minimal ProtocolExperimentResult exposing only final_agent_states.

    ``model_construct`` skips validation so we don't have to fabricate the whole
    final_result; ``_score_segmented`` only ever reads ``final_agent_states``.
    """
    return ProtocolExperimentResult.model_construct(final_agent_states=states)


def test_score_segmented_all_correct() -> None:
    """Each agent emits its own expected segment -> success True, partial 1.0."""
    seg = _instance("SEG-99")
    adapter = SiloProtocolAdapter(seg)
    global_task = adapter.build_global_task()
    states = [
        _belief_with_answer([1, 3, 6], 0, 2),
        _belief_with_answer([10, 15], 1, 2),
    ]
    result = _result_with_states(states)

    success, partial, per_agent = _score_segmented(result, seg, adapter, global_task)
    assert success is True
    assert partial == 1.0
    assert per_agent == [True, True]


def test_score_segmented_one_wrong() -> None:
    """One agent wrong -> success False, partial strictly inside (0, 1)."""
    seg = _instance("SEG-99")
    adapter = SiloProtocolAdapter(seg)
    global_task = adapter.build_global_task()
    states = [
        _belief_with_answer([1, 3, 6], 0, 2),          # correct
        _belief_with_answer([99, 99], 1, 2),           # wrong segment
    ]
    result = _result_with_states(states)

    success, partial, per_agent = _score_segmented(result, seg, adapter, global_task)
    assert success is False
    assert per_agent == [True, False]
    assert 0.0 < partial < 1.0


def test_score_segmented_missing_states_treated_wrong() -> None:
    """Short/absent final_agent_states fall back gracefully (missing == wrong)."""
    seg = _instance("SEG-99")
    adapter = SiloProtocolAdapter(seg)
    global_task = adapter.build_global_task()
    # Only one of two agents present.
    result = _result_with_states([_belief_with_answer([1, 3, 6], 0, 2)])

    success, partial, per_agent = _score_segmented(result, seg, adapter, global_task)
    assert success is False
    assert per_agent == [True, False]
    assert 0.0 <= partial < 1.0
