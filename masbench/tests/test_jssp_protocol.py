"""Tests for JSSPProtocolAdapter: validator, scoring, belief lifecycle, offline e2e."""

from __future__ import annotations

import json
from pathlib import Path

from exp_graph.agents.schemas import BeliefState, BeliefStatus
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter

from masbench.adapters.jssp_bench import JSSPBenchAdapter
from masbench.adapters.jssp_protocol import (
    JSSPProtocolAdapter,
    score_protocol_answer,
    validate_schedule,
)
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.core.task_bridge import BenchmarkTaskAdapter
from masbench.engine import _protocol_adapter, run_fixed_protocol, run_instance

DATA = Path(__file__).parent / "data" / "jssp"

# tiny2x2 job specs: job0 = (m0,2)->(m1,2); job1 = (m1,3)->(m0,2).
TINY_JOBS = [[[0, 2], [1, 2]], [[1, 3], [0, 2]]]
TINY_N_MACHINES = 2
TINY_UB = 5


def _tiny_instance() -> BenchmarkInstance:
    return next(JSSPBenchAdapter(DATA).iter_instances(cases=["tiny2x2"]))


def _entry(job: int, op: int, machine: int, start: int, end: int) -> dict:
    return {"job": job, "op": op, "machine": machine, "start": start, "end": end}


def _optimal_answer() -> dict:
    """HAND-BUILT optimal tiny2x2 schedule (makespan 5).

    Derivation: machine 1 must run job1 op0 (3) then job0 op1 (2) -- 5 time
    units of load on one machine -- so makespan >= 5. The schedule below
    achieves 5: M0 runs j0op0 [0,2) and j1op1 [3,5); M1 runs j1op0 [0,3) and
    j0op1 [3,5). Precedence holds (j0: 3 >= 2; j1: 3 >= 3), so 5 is optimal.
    """
    return {
        "makespan": 5,
        "schedule": [
            _entry(0, 0, 0, 0, 2),
            _entry(0, 1, 1, 3, 5),
            _entry(1, 0, 1, 0, 3),
            _entry(1, 1, 0, 3, 5),
        ],
    }


def _suboptimal_answer() -> dict:
    """Valid but suboptimal (makespan 7): j1op1 idles on M0 until t=5."""
    return {
        "makespan": 7,
        "schedule": [
            _entry(0, 0, 0, 0, 2),
            _entry(0, 1, 1, 3, 5),
            _entry(1, 0, 1, 0, 3),
            _entry(1, 1, 0, 5, 7),
        ],
    }


# --------------------------------------------------------------------------- #
# Deterministic validator
# --------------------------------------------------------------------------- #
def test_valid_optimal_schedule_passes():
    valid, makespan, errors = validate_schedule(
        _optimal_answer(), TINY_JOBS, TINY_N_MACHINES
    )
    assert valid is True
    assert makespan == TINY_UB
    assert errors == []


def test_precedence_violation_rejected():
    # j0 op1 starts at 1 < j0 op0's end (2); everything else kept consistent.
    answer = {
        "makespan": 8,
        "schedule": [
            _entry(0, 0, 0, 0, 2),
            _entry(0, 1, 1, 1, 3),
            _entry(1, 0, 1, 3, 6),
            _entry(1, 1, 0, 6, 8),
        ],
    }
    valid, _makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert any("precedence" in err for err in errors)


def test_machine_overlap_rejected():
    # j0op1 [2,4) and j1op0 [3,6) collide on machine 1; precedence is fine.
    answer = {
        "makespan": 8,
        "schedule": [
            _entry(0, 0, 0, 0, 2),
            _entry(0, 1, 1, 2, 4),
            _entry(1, 0, 1, 3, 6),
            _entry(1, 1, 0, 6, 8),
        ],
    }
    valid, _makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert any("overlap" in err for err in errors)


def test_wrong_duration_rejected():
    # j0 op0 scheduled for 3 time units; its spec duration is 2.
    answer = {
        "makespan": 10,
        "schedule": [
            _entry(0, 0, 0, 0, 3),
            _entry(0, 1, 1, 3, 5),
            _entry(1, 0, 1, 5, 8),
            _entry(1, 1, 0, 8, 10),
        ],
    }
    valid, _makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert any("duration mismatch" in err for err in errors)


def test_missing_op_rejected():
    answer = _optimal_answer()
    answer["schedule"] = [e for e in answer["schedule"] if (e["job"], e["op"]) != (1, 1)]
    # Keep the reported makespan equal to the remaining max end so the ONLY
    # error is the missing operation.
    answer["makespan"] = 5
    valid, _makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert errors == ["missing operation (job 1, op 1)"]


def test_duplicate_op_rejected():
    answer = _optimal_answer()
    answer["schedule"].append(_entry(0, 0, 0, 0, 2))
    valid, _makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert any("duplicate" in err for err in errors)


def test_wrong_reported_makespan_rejected():
    answer = _optimal_answer()
    answer["makespan"] = 6  # true max end is 5
    valid, makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert makespan == 5  # the true makespan is still computed
    assert any("reported makespan 6 != max end time 5" in err for err in errors)


def test_wrong_machine_and_negative_start_rejected():
    answer = _optimal_answer()
    answer["schedule"][3] = _entry(1, 1, 1, 3, 5)  # spec says machine 0
    valid, _makespan, errors = validate_schedule(answer, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert any("must run on machine 0" in err for err in errors)

    answer2 = _optimal_answer()
    answer2["schedule"][0] = _entry(0, 0, 0, -2, 0)
    valid2, _m2, errors2 = validate_schedule(answer2, TINY_JOBS, TINY_N_MACHINES)
    assert valid2 is False
    assert any("negative start" in err for err in errors2)


def test_malformed_answers_rejected():
    assert validate_schedule(None, TINY_JOBS, TINY_N_MACHINES)[0] is False
    assert validate_schedule([1, 2], TINY_JOBS, TINY_N_MACHINES)[0] is False
    assert validate_schedule({"makespan": 5}, TINY_JOBS, TINY_N_MACHINES)[0] is False
    no_int = _optimal_answer()
    no_int["makespan"] = "five"
    valid, _m, errors = validate_schedule(no_int, TINY_JOBS, TINY_N_MACHINES)
    assert valid is False
    assert any("'makespan' must be an integer" in err for err in errors)
    bool_makespan = _optimal_answer()
    bool_makespan["makespan"] = True  # bools are not schedule integers
    assert validate_schedule(bool_makespan, TINY_JOBS, TINY_N_MACHINES)[0] is False


# --------------------------------------------------------------------------- #
# Scoring math
# --------------------------------------------------------------------------- #
def test_scoring_math():
    adapter = JSSPProtocolAdapter(_tiny_instance())
    global_task = adapter.build_global_task()
    assert global_task["answer_key"] == "5"

    optimal = adapter.score_protocol_answer(_optimal_answer(), global_task)
    assert optimal["exact_match"] == 1.0
    assert optimal["primary_metric"] == 1.0
    assert optimal["primary_metric_name"] == "jssp_quality"
    assert optimal["valid"] is True and optimal["makespan"] == 5

    sub = adapter.score_protocol_answer(_suboptimal_answer(), global_task)
    assert sub["exact_match"] == 0.0
    assert abs(sub["primary_metric"] - TINY_UB / 7) < 1e-9

    invalid = dict(_optimal_answer(), makespan=6)
    bad = adapter.score_protocol_answer(invalid, global_task)
    assert bad["exact_match"] == 0.0 and bad["primary_metric"] == 0.0

    none = adapter.score_protocol_answer(None, global_task)
    assert none["exact_match"] == 0.0 and none["primary_metric"] == 0.0


def test_scoring_with_loose_upper_bound_caps_at_one():
    # With a loose UB (the naive bound 9), a valid makespan-5 schedule beats
    # it: exact_match 1.0 and primary capped at 1.0 (min(1, 9/5)).
    global_task = {
        "shards": TINY_JOBS,
        "meta": {"n_machines": TINY_N_MACHINES, "upper_bound": 9},
        "answer_key": "9",
    }
    scored = score_protocol_answer(_optimal_answer(), global_task)
    assert scored["exact_match"] == 1.0
    assert scored["primary_metric"] == 1.0


def test_canonical_answer_key_grouping():
    adapter = JSSPProtocolAdapter(_tiny_instance())
    answer = _optimal_answer()
    # Key-order permutation and a JSON round trip group to the SAME key.
    reordered = {"schedule": answer["schedule"], "makespan": answer["makespan"]}
    roundtrip = json.loads(json.dumps(answer))
    key = adapter.protocol_answer_key(answer)
    assert adapter.protocol_answer_key(reordered) == key
    assert adapter.protocol_answer_key(roundtrip) == key
    # Different answers group apart; None is UNKNOWN.
    assert adapter.protocol_answer_key(_suboptimal_answer()) != key
    assert adapter.protocol_answer_key(None) == "UNKNOWN"


# --------------------------------------------------------------------------- #
# Belief lifecycle (deterministic offline path)
# --------------------------------------------------------------------------- #
def test_is_protocol_adapter_and_initial_belief():
    adapter = JSSPProtocolAdapter(_tiny_instance())
    assert isinstance(adapter, ProtocolTaskAdapter)
    assert isinstance(adapter, BenchmarkTaskAdapter)

    global_task = adapter.build_global_task()
    obs = adapter.split_into_local_observations(global_task, 2)
    belief = adapter.initial_protocol_belief(obs[0])
    # Initial belief is UNKNOWN: an agent holding one job cannot know the
    # global schedule; its own job ops travel in support/known_jobs.
    assert belief.consensus_key == "UNKNOWN"
    assert belief.structured_state["task_name"] == "jssp"
    assert belief.structured_state["case_id"] == "tiny2x2"
    assert belief.structured_state["answer"] is None
    assert belief.structured_state["known_jobs"] == {"0": TINY_JOBS[0]}
    assert any("[[0, 2], [1, 2]]" in s for s in belief.support)


def test_deterministic_merge_unions_known_jobs_never_fabricates():
    adapter = JSSPProtocolAdapter(_tiny_instance())
    global_task = adapter.build_global_task()
    obs = adapter.split_into_local_observations(global_task, 2)
    belief0 = adapter.initial_protocol_belief(obs[0])
    belief1 = adapter.initial_protocol_belief(obs[1])
    inbox = [OutboxMessage.from_belief_state(agent_id=1, round_idx=0, belief_state=belief1)]

    merged = adapter.merge_protocol_inbox(
        old_belief_state=belief0, inbox=inbox, global_task=global_task
    )
    # Knows both jobs now, but NEVER fabricates a schedule offline.
    assert merged.structured_state["known_jobs"] == {
        "0": TINY_JOBS[0],
        "1": TINY_JOBS[1],
    }
    assert merged.structured_state["answer"] is None
    assert merged.consensus_key == "UNKNOWN"


def test_deterministic_merge_transports_best_valid_answer():
    adapter = JSSPProtocolAdapter(_tiny_instance())
    global_task = adapter.build_global_task()
    obs = adapter.split_into_local_observations(global_task, 2)
    belief0 = adapter.initial_protocol_belief(obs[0])
    carrying = BeliefState(
        status=BeliefStatus.CANDIDATE,
        proposal="full schedule",
        consensus_key="UNKNOWN",
        structured_state={
            "task_name": "jssp",
            "case_id": "tiny2x2",
            "answer": _suboptimal_answer(),
            "known_jobs": {"1": TINY_JOBS[1]},
        },
    )
    inbox = [OutboxMessage.from_belief_state(agent_id=1, round_idx=1, belief_state=carrying)]
    merged = adapter.merge_protocol_inbox(
        old_belief_state=belief0, inbox=inbox, global_task=global_task
    )
    # The valid neighbor schedule is transported (not fabricated) and keyed.
    assert merged.structured_state["answer"] == _suboptimal_answer()
    assert merged.consensus_key == adapter.protocol_answer_key(_suboptimal_answer())


def test_apply_verified_merge_validates_llm_answer():
    adapter = JSSPProtocolAdapter(_tiny_instance())

    def _llm_belief(answer):
        return BeliefState(
            status=BeliefStatus.CANDIDATE,
            proposal="llm proposal",
            consensus_key="UNKNOWN",
            structured_state={
                "task_name": "jssp",
                "case_id": "tiny2x2",
                "answer": answer,
                "known_jobs": {},
            },
        )

    verified = adapter.merge_protocol_inbox(
        old_belief_state=adapter.initial_protocol_belief(
            adapter.split_into_local_observations(adapter.build_global_task(), 2)[0]
        ),
        inbox=[],
        global_task=adapter.build_global_task(),
    )

    # A fully VALID LLM schedule is adopted.
    good = adapter.apply_verified_protocol_merge(
        llm_belief_state=_llm_belief(_optimal_answer()),
        verified_belief_state=verified,
    )
    assert good.structured_state["answer"] == _optimal_answer()
    assert good.consensus_key == adapter.protocol_answer_key(_optimal_answer())

    # An INVALID LLM schedule falls back to the verified (non-fabricated) one.
    invalid = dict(_optimal_answer(), makespan=6)
    bad = adapter.apply_verified_protocol_merge(
        llm_belief_state=_llm_belief(invalid),
        verified_belief_state=verified,
    )
    assert bad.structured_state["answer"] is None
    assert bad.consensus_key == "UNKNOWN"


def test_prompts_and_adjudication_context_hide_upper_bound():
    adapter = JSSPProtocolAdapter(_tiny_instance())
    global_task = adapter.build_global_task()
    obs = adapter.split_into_local_observations(global_task, 2)

    ctx = adapter.format_adjudication_context(global_task)
    assert "shards" not in ctx
    assert "answer_key" not in ctx
    assert "upper_bound" not in ctx["meta"]
    assert ctx["meta"]["n_machines"] == 2
    # The original global task is NOT mutated.
    assert global_task["meta"]["upper_bound"] == TINY_UB

    init_prompt = adapter.format_protocol_init_prompt(
        global_task=global_task, local_observation=obs[0]
    )
    for marker in ("TASK_FOR_AGENT:", "LOCAL_OBSERVATION_JSON:", "INBOX_JSON:"):
        assert marker in init_prompt
    assert "upper_bound" not in init_prompt
    assert "answer_key" not in init_prompt

    merge_prompt = adapter.format_protocol_merge_prompt(
        merge_mode="llm_full_merge",
        global_task=global_task,
        local_observation=obs[0],
        old_belief_state=adapter.initial_protocol_belief(obs[0]),
        inbox=[],
        deterministic_belief=None,
    )
    for marker in ("KNOWN_JOBS_JSON:", "YOUR_ANSWER_JSON:", "VERIFIED_ANSWER_JSON:"):
        assert marker in merge_prompt
    assert "upper_bound" not in merge_prompt

    brief = adapter.describe_task()
    assert "makespan" in brief
    assert len(brief) <= 400

    probe = adapter.build_probe_global_task(seed=3)
    assert probe["case_id"] == "tiny2x2"


# --------------------------------------------------------------------------- #
# Engine factory + offline end-to-end (machinery only; no capability claim)
# --------------------------------------------------------------------------- #
def test_engine_factory_routes_by_benchmark():
    jssp_adapter = _protocol_adapter(_tiny_instance())
    assert isinstance(jssp_adapter, JSSPProtocolAdapter)

    silo_instance = BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",
        case_name="Global Max",
        n_agents=2,
        shards=[[3, 1, 9, 2], [5, 8, 4]],
        ground_truth=9,
        task_prompt="Find the GLOBAL MAXIMUM. Agent {agent_id} holds {input_shard}",
        meta={"output_type": "distributed"},
    )
    silo_adapter = _protocol_adapter(silo_instance)
    assert isinstance(silo_adapter, SiloProtocolAdapter)
    assert not isinstance(silo_adapter, JSSPProtocolAdapter)


def test_offline_e2e_run_instance_completes_with_exact_match_zero():
    # The cli `run` path: run_instance with the fake provider and deterministic
    # modes must COMPLETE on tiny2x2 and score exact_match 0.0 (no offline
    # solver fabricates a schedule) -- the machinery test, like Silo's
    # topology-invariant offline path.
    inst = _tiny_instance()
    cfg = RunConfig(
        benchmark="jssp",
        topology="chain",
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        n_agents=2,
        max_rounds=2,
    )
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.success is False  # exact_match 0.0: machinery green only
    assert score.partial == 0.0
    assert score.n_model_calls > 0
    assert score.extra["case_id"] == "tiny2x2"


def test_offline_e2e_fixed_protocol_runner_chain():
    # The protocol path (the one the planner/bench arms use) with the JSSP
    # protocol adapter: deterministic init+merge on a chain topology completes
    # with exact_match 0.0 and zero LLM calls.
    inst = _tiny_instance()
    cfg = RunConfig(
        benchmark="jssp",
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        n_agents=2,
    )
    score = run_fixed_protocol(inst, cfg, topology="chain")
    assert isinstance(score, ScoreResult)
    assert score.success is False
    assert score.partial == 0.0
    assert score.n_messages > 0
    assert score.n_model_calls == 0  # fully deterministic offline protocol run
    assert score.final_answer == "UNKNOWN"
    assert score.extra["fixed"] is True and score.extra["topology"] == "chain"


def test_offline_planner_path_completes():
    # Planner ON exercises the second factory site (_run_planner) for jssp.
    inst = _tiny_instance()
    cfg = RunConfig(
        benchmark="jssp",
        use_planner=True,
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        n_agents=2,
    )
    score = run_instance(inst, cfg)
    assert isinstance(score, ScoreResult)
    assert score.extra["planner"] is True
    assert score.success is False


def test_engine_partial_routes_to_jssp_scorer():
    """Real-LLM smoke regression: a VALID suboptimal schedule (makespan 7 vs
    UB 5) arrived as a canonical JSON STRING and scored partial 0.0 through
    the hardwired silo scorer. The engine must route by benchmark and the
    jssp scorer must coerce string answers; expected partial = 5/7."""
    from masbench.engine import _partial_score

    answer = (
        '{"makespan":7,"schedule":['
        '{"end":2,"job":0,"machine":0,"op":0,"start":0},'
        '{"end":3,"job":1,"machine":1,"op":0,"start":0},'
        '{"end":5,"job":0,"machine":1,"op":1,"start":3},'
        '{"end":7,"job":1,"machine":0,"op":1,"start":5}]}'
    )
    global_task = {
        "benchmark": "jssp",
        "shards": [[[0, 2], [1, 2]], [[1, 3], [0, 2]]],
        "meta": {"n_machines": 2, "upper_bound": 5},
        "answer_key": "5",
    }
    assert abs(_partial_score(answer, global_task) - 5.0 / 7.0) < 1e-9
