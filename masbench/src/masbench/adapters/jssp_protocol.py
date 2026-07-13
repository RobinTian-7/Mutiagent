"""JSSP behind the QueenBee temporal-DAG protocol engine.

``JSSPProtocolAdapter`` lets ``exp_graph.runner.protocol.ProtocolRunner`` drive a
single JSSP :class:`~masbench.core.instance.BenchmarkInstance`. It reuses the six
base ``TaskAdapter`` methods from :class:`BenchmarkTaskAdapter` and the generic
finalize/step-metric/answer-holder defaults from :class:`ProtocolTaskAdapter`;
this module only adds the per-agent belief lifecycle plus the answer/score hooks
(mirroring :mod:`masbench.adapters.silo_protocol`).

Belief model: every belief carries the agent's current candidate GLOBAL schedule
in ``structured_state={"task_name": "jssp", "case_id": <id>, "answer": <answer
dict or None>, "known_jobs": {job_id: ops}}`` and mirrors the answer's canonical
form in ``consensus_key`` (or ``"UNKNOWN"``). ``known_jobs`` is the union of job
operation lists this agent has seen (its own plus those carried by neighbor
messages), so coverage can grow deterministically while the SCHEDULE itself is
only ever produced by an LLM.

Offline determinism: there is NO offline JSSP solver. Initial beliefs are
UNKNOWN with the agent's own job operations in support; deterministic merges
union known-jobs info and transport already-proposed answers but NEVER fabricate
a schedule, so a pure offline (fake provider) run completes end to end with
``exact_match`` 0.0 -- the machinery test, like Silo's non-reduce offline path.

The deterministic VALIDATOR :func:`validate_schedule` is the scoring backbone:
an answer only counts if it is a complete, precedence-correct, non-overlapping
schedule whose reported makespan equals the true one.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from exp_graph.agents.schemas import BeliefState, BeliefStatus
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter

from masbench.core.task_bridge import (
    BenchmarkTaskAdapter,
    canonical_answer,
    private_answer_key,
)

JSSP_PROTOCOL_TASK_NAME = "jssp"

_ANSWER_SCHEMA = (
    '{"makespan": <int>, "schedule": [{"job": <j>, "op": <k>, '
    '"machine": <m>, "start": <s>, "end": <e>}, ...]}'
)


def _as_int(value: Any) -> int | None:
    """Strict integer coercion: ints (not bools) and integral floats only."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    return None


def validate_schedule(
    answer: Any, jobs: list[Any], n_machines: int
) -> tuple[bool, int | None, list[str]]:
    """Deterministically validate one JSSP answer against the job specs.

    ``answer`` must be a dict ``{"makespan": int, "schedule": [...]}`` whose
    schedule covers EVERY (job, op) exactly once; per job, operations run in
    order with ``start >= previous end``; each operation's machine and duration
    match the job spec; no two operations overlap on the same machine; all
    starts are >= 0; and the reported makespan equals the maximum end time.

    Returns ``(valid, true_makespan, errors)`` where ``true_makespan`` is the
    maximum end over parseable entries (None when none parse) -- for a valid
    schedule it equals the reported makespan.
    """
    if not isinstance(answer, dict):
        return False, None, ["answer must be a JSON object with 'makespan' and 'schedule'"]

    errors: list[str] = []
    reported = _as_int(answer.get("makespan"))
    if reported is None:
        errors.append("'makespan' must be an integer")

    schedule = answer.get("schedule")
    if not isinstance(schedule, list):
        errors.append("'schedule' must be a list of operation entries")
        return False, None, errors

    n_jobs = len(jobs)
    seen: dict[tuple[int, int], tuple[int, int, int]] = {}
    by_machine: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)
    max_end: int | None = None

    for idx, entry in enumerate(schedule):
        if not isinstance(entry, dict):
            errors.append(f"schedule[{idx}] must be an object")
            continue
        fields = {
            name: _as_int(entry.get(name))
            for name in ("job", "op", "machine", "start", "end")
        }
        bad = [name for name, val in fields.items() if val is None]
        if bad:
            errors.append(f"schedule[{idx}] missing/non-integer fields: {bad}")
            continue
        job, op = fields["job"], fields["op"]
        machine, start, end = fields["machine"], fields["start"], fields["end"]
        if not (0 <= job < n_jobs):
            errors.append(f"schedule[{idx}] references unknown job {job}")
            continue
        ops = jobs[job]
        if not (0 <= op < len(ops)):
            errors.append(f"schedule[{idx}] references unknown op {op} of job {job}")
            continue
        if (job, op) in seen:
            errors.append(f"duplicate entry for (job {job}, op {op})")
            continue
        seen[(job, op)] = (machine, start, end)
        spec_machine, spec_duration = int(ops[op][0]), int(ops[op][1])
        if machine != spec_machine:
            errors.append(
                f"(job {job}, op {op}) must run on machine {spec_machine}, "
                f"not {machine}"
            )
        if not (0 <= machine < n_machines):
            errors.append(f"(job {job}, op {op}) uses machine {machine} outside range")
        if start < 0:
            errors.append(f"(job {job}, op {op}) has negative start {start}")
        if end - start != spec_duration:
            errors.append(
                f"(job {job}, op {op}) duration mismatch: spec {spec_duration}, "
                f"scheduled {end - start}"
            )
        by_machine[machine].append((start, end, job, op))
        max_end = end if max_end is None else max(max_end, end)

    # Coverage: every (job, op) exactly once.
    for job in range(n_jobs):
        for op in range(len(jobs[job])):
            if (job, op) not in seen:
                errors.append(f"missing operation (job {job}, op {op})")

    # Per-job precedence: op k may start only after op k-1 ends.
    for job in range(n_jobs):
        for op in range(1, len(jobs[job])):
            prev, cur = seen.get((job, op - 1)), seen.get((job, op))
            if prev is None or cur is None:
                continue
            if cur[1] < prev[2]:
                errors.append(
                    f"precedence violation: (job {job}, op {op}) starts at "
                    f"{cur[1]} before op {op - 1} ends at {prev[2]}"
                )

    # Machine exclusivity: no two operations overlap on the same machine.
    for machine, intervals in sorted(by_machine.items()):
        ordered = sorted(intervals)
        for (s1, e1, j1, o1), (s2, e2, j2, o2) in zip(ordered, ordered[1:]):
            if s2 < e1:
                errors.append(
                    f"machine {machine} overlap: (job {j1}, op {o1}) "
                    f"[{s1},{e1}) and (job {j2}, op {o2}) [{s2},{e2})"
                )

    if reported is not None and max_end is not None and reported != max_end:
        errors.append(f"reported makespan {reported} != max end time {max_end}")

    return (not errors), max_end, errors


def _upper_bound(global_task: dict[str, Any]) -> int | None:
    """Known upper bound for this task (meta first, private payload fallback)."""
    meta = global_task.get("meta") or {}
    bound = _as_int(meta.get("upper_bound"))
    if bound is not None:
        return bound
    try:
        return _as_int(json.loads(str(private_answer_key(global_task) or "")))
    except (TypeError, ValueError):
        return None


def score_protocol_answer(answer: Any, global_task: dict[str, Any]) -> dict[str, Any]:
    """Score one JSSP global answer with the deterministic validator.

    ``primary_metric`` is 0.0 for an invalid schedule, else ``min(1.0, UB /
    makespan)`` (1.0 at or below the known upper bound, graded toward 0 as the
    schedule gets longer). ``exact_match`` is 1.0 iff the schedule is valid and
    its makespan is <= UB. Module-level so masbench can score a final answer
    without holding a task-adapter instance; the adapter method delegates here.
    """
    base = {
        "primary_metric": 0.0, "partial": 0.0, "exact_match": 0.0,
        "primary_metric_name": "jssp_quality",
    }
    if isinstance(answer, str):
        # Engine paths hand over the CANONICAL-KEY string form of the final
        # answer (real-LLM smoke: a valid makespan-7 schedule arrived as a
        # JSON string and scored 0); the validator needs the object back.
        try:
            answer = json.loads(answer)
        except (json.JSONDecodeError, ValueError):
            return {**base, "valid": False, "makespan": None,
                    "errors": ["answer is a non-JSON string"]}
    if answer is None:
        return {**base, "valid": False, "makespan": None, "errors": ["no answer"]}
    jobs = list(global_task.get("shards") or [])
    n_machines = int((global_task.get("meta") or {}).get("n_machines", 0))
    valid, makespan, errors = validate_schedule(answer, jobs, n_machines)
    bound = _upper_bound(global_task)
    if not valid or makespan is None or makespan <= 0 or bound is None:
        return {**base, "valid": bool(valid), "makespan": makespan, "errors": errors[:8]}
    quality = min(1.0, float(bound) / float(makespan))
    return {
        "primary_metric": quality,
        # ``partial`` is the engine's graded-score key (ScoreResult.partial);
        # for JSSP it IS the quality ratio.
        "partial": quality,
        "exact_match": 1.0 if makespan <= bound else 0.0,
        "primary_metric_name": "jssp_quality",
        "valid": True,
        "makespan": makespan,
        "errors": [],
    }


def _answer_from_structured_state(value: Any) -> Any:
    """Pull the candidate answer dict out of a jssp structured_state, if present."""
    if not isinstance(value, dict):
        return None
    if value.get("task_name") != JSSP_PROTOCOL_TASK_NAME:
        return None
    answer = value.get("answer")
    return answer if isinstance(answer, dict) else None


def _known_jobs_from_structured_state(value: Any) -> dict[str, Any]:
    """Pull the known-jobs map out of a jssp structured_state ({} if absent)."""
    if not isinstance(value, dict) or value.get("task_name") != JSSP_PROTOCOL_TASK_NAME:
        return {}
    known = value.get("known_jobs")
    if not isinstance(known, dict):
        return {}
    return {str(job_id): ops for job_id, ops in known.items()}


def _answer_from_message(message: OutboxMessage) -> Any:
    """Recover a neighbor's candidate answer dict from its outbox message."""
    answer = _answer_from_structured_state(message.structured_payload)
    if answer is not None:
        return answer
    key = message.consensus_key
    if key is None or canonical_answer(key) == "UNKNOWN":
        return None
    try:
        parsed = json.loads(key)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class JSSPProtocolAdapter(BenchmarkTaskAdapter, ProtocolTaskAdapter):
    """Drive one JSSP BenchmarkInstance through ProtocolRunner.

    ``__init__(self, instance)`` is inherited from :class:`BenchmarkTaskAdapter`;
    the six base TaskAdapter methods come from there too, and the generic
    finalize/step-metric/answer-holder defaults from :class:`ProtocolTaskAdapter`.
    Only the belief lifecycle + answer/score hooks are defined here.
    """

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _case_id(self) -> str:
        return str(self.instance.case_id)

    def _jobs(self) -> list[Any]:
        return list(self.instance.shards)

    def _n_machines(self) -> int:
        return int(self.instance.meta.get("n_machines", 0))

    def _validate_answer(self, answer: Any) -> tuple[bool, int | None]:
        valid, makespan, _errors = validate_schedule(
            answer, self._jobs(), self._n_machines()
        )
        return valid, makespan

    def _best_answer(self, candidates: list[Any]) -> Any:
        """Deterministically pick the best candidate answer (never fabricate).

        Prefers VALID schedules with the smallest makespan (canonical-string
        tie-break); with no valid candidate, carries the first dict-shaped one
        so an LLM-proposed draft is transported rather than dropped.
        """
        dicts = [c for c in candidates if isinstance(c, dict)]
        valid_pool = []
        for candidate in dicts:
            valid, makespan = self._validate_answer(candidate)
            if valid and makespan is not None:
                valid_pool.append((makespan, canonical_answer(candidate), candidate))
        if valid_pool:
            return min(valid_pool, key=lambda item: (item[0], item[1]))[2]
        return dicts[0] if dicts else None

    def _structured_state(
        self, answer: Any, known_jobs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "task_name": JSSP_PROTOCOL_TASK_NAME,
            "case_id": self._case_id(),
            "answer": answer,
            "known_jobs": dict(known_jobs or {}),
        }

    def _belief_from_answer(
        self,
        answer: Any,
        *,
        status: BeliefStatus,
        proposal: str,
        known_jobs: dict[str, Any] | None = None,
        open_questions: list[str] | None = None,
        uncertainty: str = "",
        support: list[str] | None = None,
        private_notes: str = "jssp protocol belief",
    ) -> BeliefState:
        key = canonical_answer(answer) if answer is not None else "UNKNOWN"
        return BeliefState(
            status=status,
            proposal=proposal,
            consensus_key=key,
            support=support if support is not None else [],
            uncertainty=uncertainty,
            open_questions=open_questions if open_questions is not None else [],
            private_notes=private_notes,
            structured_state=self._structured_state(answer, known_jobs),
        )

    def _missing_jobs(self, known_jobs: dict[str, Any]) -> list[int]:
        return [
            job_id
            for job_id in range(self.instance.n_agents)
            if str(job_id) not in known_jobs
        ]

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: per-agent belief lifecycle
    # ------------------------------------------------------------------ #
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState:
        agent_id = int(local_observation["agent_id"])
        shard = local_observation.get("input_shard")
        known_jobs = {str(agent_id): shard}
        # No offline JSSP solver exists: the initial belief is always UNKNOWN,
        # carrying the agent's own job operations in support/known_jobs so
        # neighbors can accumulate coverage deterministically.
        return self._belief_from_answer(
            None,
            status=BeliefStatus.CANDIDATE,
            proposal=(
                f"Agent {agent_id} owns job {agent_id} with "
                f"{len(shard) if isinstance(shard, list) else 0} ordered operations; "
                "the global schedule is not yet known."
            ),
            known_jobs=known_jobs,
            uncertainty="Need the other agents' job operations to build a schedule.",
            open_questions=[
                "Share your job's ordered [machine, duration] operations."
            ],
            support=[f"agent {agent_id} job ops={json.dumps(shard)}"],
            private_notes="jssp local job only",
        )

    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState:
        # Union known-jobs info from the old belief and every neighbor message.
        known_jobs = _known_jobs_from_structured_state(old_belief_state.structured_state)
        for message in inbox:
            for job_id, ops in _known_jobs_from_structured_state(
                message.structured_payload
            ).items():
                known_jobs.setdefault(job_id, ops)

        # Transport the best already-proposed answer; NEVER fabricate one
        # offline (constructing a schedule is the LLM's job in online modes).
        own = _answer_from_structured_state(old_belief_state.structured_state)
        candidates = [own] + [_answer_from_message(message) for message in inbox]
        answer = self._best_answer([c for c in candidates if c is not None])

        missing = self._missing_jobs(known_jobs)
        if answer is not None:
            proposal = "Carrying the best schedule proposed so far."
        elif missing:
            proposal = (
                f"Collected operations for jobs "
                f"{sorted(int(j) for j in known_jobs)}; still missing jobs {missing}."
            )
        else:
            proposal = (
                "All jobs' operations are known, but no deterministic offline "
                "scheduler exists; an LLM merge must construct the schedule."
            )
        return self._belief_from_answer(
            answer,
            status=BeliefStatus.CANDIDATE,
            proposal=proposal,
            known_jobs=known_jobs,
            uncertainty=(
                "Schedule construction requires an LLM merge mode."
                if answer is None
                else "A better schedule may still be found."
            ),
            open_questions=(
                [f"Share operations for jobs {missing}."]
                if missing
                else ["Propose or refine the full schedule JSON."]
            ),
            support=[
                f"known jobs: {sorted(int(j) for j in known_jobs)} "
                f"of {self.instance.n_agents}"
            ],
            private_notes="jssp deterministic merge (union known jobs; no fabrication)",
        )

    def format_protocol_init_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        task_context = self.format_adjudication_context(global_task)
        prompt_context = self.format_task_prompt_context(global_task, local_observation)
        agent_id = int(local_observation["agent_id"])
        return f"""You are one agent in a team solving a single Job-Shop Scheduling (JSSP) task.

You own ONE job's ordered operations. Share them with the team and state the
constraints they impose (operation order within your job; machine exclusivity).
A single agent usually CANNOT determine the optimal global schedule alone, so do
not invent other jobs' data.

Rules: output exactly one JSON object (a belief_state) and nothing outside it (no
markdown fences, no prose). If you can already produce a complete valid global
schedule, put it in structured_state.answer using the exact form
{_ANSWER_SCHEMA}; otherwise set answer to null and consensus_key to "UNKNOWN".

TASK_FOR_AGENT:
{prompt_context}
Return belief_state:
{{
  "status": "candidate",
  "proposal": "short summary: your job's operations and the constraints they impose",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "which jobs' operations you still need",
  "open_questions": ["share your job's ordered [machine, duration] operations"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "{JSSP_PROTOCOL_TASK_NAME}",
    "case_id": "{self._case_id()}",
    "answer": null,
    "known_jobs": {{"{agent_id}": {json.dumps(local_observation.get("input_shard"), ensure_ascii=True)}}}
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

LOCAL_OBSERVATION_JSON:
{json.dumps(local_observation, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{{}}

INBOX_JSON:
[]
"""

    def format_protocol_merge_prompt(
        self,
        *,
        merge_mode: str,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        deterministic_belief: BeliefState | None = None,
    ) -> str:
        task_context = self.format_adjudication_context(global_task)
        own_answer = _answer_from_structured_state(old_belief_state.structured_state)
        inbox_answers = [_answer_from_message(message) for message in inbox]
        known_jobs = _known_jobs_from_structured_state(old_belief_state.structured_state)
        for message in inbox:
            for job_id, ops in _known_jobs_from_structured_state(
                message.structured_payload
            ).items():
                known_jobs.setdefault(job_id, ops)
        verified_answer = (
            _answer_from_structured_state(deterministic_belief.structured_state)
            if deterministic_belief is not None
            else None
        )
        old_belief_json = json.dumps(
            old_belief_state.model_dump(mode="json"), ensure_ascii=True, sort_keys=True
        )
        inbox_json = json.dumps(
            [message.model_dump(mode="json") for message in inbox],
            ensure_ascii=True,
            sort_keys=True,
        )
        return f"""You are one agent in a team solving a single Job-Shop Scheduling (JSSP)
task. Goal: ONE global schedule over every agent's job that minimizes makespan.

Mode={merge_mode}. Integrate the neighbor messages: union their job-operation
knowledge (KNOWN_JOBS_JSON) into yours, and compare any proposed schedules in
YOUR_ANSWER_JSON / INBOX_ANSWERS_JSON. Once enough jobs are known, CONSTRUCT or
REFINE the full schedule: every (job, op) exactly once, each job's operations in
order (start >= previous end), end - start equal to the duration, no two
operations overlapping on the same machine, makespan = the latest end time. Do
not invent job data; only use what is given. If VERIFIED_ANSWER_JSON is not
null, it is a deterministically transported candidate you may keep or improve.

Rules: output exactly one JSON object (a belief_state) and nothing outside it.
Put the full schedule in structured_state.answer using the exact form
{_ANSWER_SCHEMA}, and set consensus_key to the same answer (compact canonical
JSON), or "UNKNOWN" if you still cannot build a complete schedule.

TASK_FOR_AGENT:
{self.format_task_prompt_context(global_task, local_observation)}
Return belief_state:
{{
  "status": "candidate",
  "proposal": "short",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "short",
  "open_questions": ["short"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "{JSSP_PROTOCOL_TASK_NAME}",
    "case_id": "{self._case_id()}",
    "answer": null,
    "known_jobs": {{}}
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

KNOWN_JOBS_JSON:
{json.dumps(known_jobs, ensure_ascii=True, sort_keys=True)}

YOUR_ANSWER_JSON:
{json.dumps(own_answer, ensure_ascii=True)}

INBOX_ANSWERS_JSON:
{json.dumps(inbox_answers, ensure_ascii=True)}

VERIFIED_ANSWER_JSON:
{json.dumps(verified_answer, ensure_ascii=True)}

LOCAL_OBSERVATION_JSON:
{json.dumps(local_observation, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{old_belief_json}

INBOX_JSON:
{inbox_json}
"""

    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState:
        n_agents = int(local_observation["n_agents"])
        agent_id = int(local_observation["agent_id"])
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is None:
            answer = self._answer_from_consensus_key(belief_state.consensus_key)
        # The agent's own job is ground truth at init regardless of LLM claims.
        known_jobs = _known_jobs_from_structured_state(belief_state.structured_state)
        known_jobs[str(agent_id)] = local_observation.get("input_shard")
        return self._finalize_validated_belief(
            answer,
            known_jobs=known_jobs,
            all_covered=n_agents == 1,
            llm_belief=belief_state,
        )

    def validate_protocol_belief_state(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> BeliefState:
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is None:
            answer = self._answer_from_consensus_key(belief_state.consensus_key)
        known_jobs = _known_jobs_from_structured_state(belief_state.structured_state)
        if transport_belief_state is not None:
            if answer is None:
                answer = _answer_from_structured_state(
                    transport_belief_state.structured_state
                )
            for job_id, ops in _known_jobs_from_structured_state(
                transport_belief_state.structured_state
            ).items():
                known_jobs.setdefault(job_id, ops)
        return self._finalize_validated_belief(
            answer,
            known_jobs=known_jobs,
            all_covered=n_agents == 1,
            llm_belief=belief_state,
        )

    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState:
        # Keep the LLM's wording, but run its schedule through the deterministic
        # validator: a fully VALID LLM schedule is adopted (best of LLM/verified
        # by makespan); an invalid one falls back to the verified transported
        # answer rather than poisoning consensus.
        llm_answer = _answer_from_structured_state(llm_belief_state.structured_state)
        if llm_answer is None:
            llm_answer = self._answer_from_consensus_key(llm_belief_state.consensus_key)
        verified_answer = _answer_from_structured_state(
            verified_belief_state.structured_state
        )
        llm_valid, _ = self._validate_answer(llm_answer)
        if llm_valid:
            answer = self._best_answer([llm_answer, verified_answer])
        else:
            answer = verified_answer
        known_jobs = _known_jobs_from_structured_state(
            verified_belief_state.structured_state
        )
        for job_id, ops in _known_jobs_from_structured_state(
            llm_belief_state.structured_state
        ).items():
            known_jobs.setdefault(job_id, ops)
        key = canonical_answer(answer) if answer is not None else "UNKNOWN"
        return BeliefState(
            status=verified_belief_state.status,
            proposal=llm_belief_state.proposal or verified_belief_state.proposal,
            consensus_key=key,
            support=llm_belief_state.support or verified_belief_state.support,
            uncertainty=(
                llm_belief_state.uncertainty
                if llm_belief_state.uncertainty
                else verified_belief_state.uncertainty
            ),
            open_questions=(
                []
                if verified_belief_state.status == BeliefStatus.FINAL
                else (
                    llm_belief_state.open_questions
                    or verified_belief_state.open_questions
                )
            ),
            private_notes=llm_belief_state.private_notes,
            confidence=llm_belief_state.confidence,
            structured_state=self._structured_state(answer, known_jobs),
        )

    def build_probe_global_task(
        self, *, seed: int = 0, runtime: Any = None, request: Any = None
    ) -> dict:
        """Candidate probe-eval task (D1): JSSP instances are fixed, so every
        probe uses the instance's own task; the ProtocolRunner varies by seed."""
        return self.build_global_task()

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: answer extraction / scoring / metrics
    # ------------------------------------------------------------------ #
    def extract_protocol_answer(self, belief_state: BeliefState) -> Any:
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is not None:
            return answer
        return self._answer_from_consensus_key(belief_state.consensus_key)

    def protocol_answer_key(self, answer: Any) -> str:
        return canonical_answer(answer)

    def score_protocol_answer(
        self, answer: Any, global_task: dict[str, Any]
    ) -> dict[str, Any]:
        return score_protocol_answer(answer, global_task)

    def compute_protocol_agent_metrics(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> dict[str, Any]:
        answer = self.extract_protocol_answer(belief_state)
        scored = score_protocol_answer(answer, global_task)
        known_jobs = _known_jobs_from_structured_state(belief_state.structured_state)
        valid_ids = {
            str(job_id) for job_id in range(n_agents)
        } & set(known_jobs)
        coverage = len(valid_ids) / max(1, n_agents)
        return {
            "coverage_ratio": float(coverage),
            "primary_metric": float(scored["primary_metric"]),
            "exact_match": bool(scored["exact_match"]),
        }

    # ------------------------------------------------------------------ #
    # Architect / adjudication context
    # ------------------------------------------------------------------ #
    def describe_task(self) -> str:
        """Compact JSSP statement for the graph-generating architect."""
        n_jobs = self.instance.n_agents
        n_machines = self._n_machines()
        return (
            f"{self.instance.case_name}: job-shop scheduling with {n_jobs} jobs on "
            f"{n_machines} machines. Each agent owns ONE job's ordered "
            "(machine, duration) operations; operations of a job run in order and "
            "machines are exclusive. The team must agree on one global schedule "
            "JSON {\"makespan\": int, \"schedule\": [...]} covering every "
            "operation and minimizing the makespan."
        )[:400]

    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        # Base (BenchmarkTaskAdapter) drops raw shards and the blocked
        # answer/answer_key keys; additionally scrub the known upper bound from
        # meta -- for JSSP it IS the answer key (exact_match <=> makespan <= UB).
        base = super().format_adjudication_context(global_task)
        meta = base.get("meta")
        if isinstance(meta, dict):
            base["meta"] = {
                key: value for key, value in meta.items() if key != "upper_bound"
            }
        return base

    # ------------------------------------------------------------------ #
    # Internal validation helpers
    # ------------------------------------------------------------------ #
    def _answer_from_consensus_key(self, key: str | None) -> Any:
        if key is None or canonical_answer(key) == "UNKNOWN":
            return None
        try:
            parsed = json.loads(key)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _finalize_validated_belief(
        self,
        answer: Any,
        *,
        known_jobs: dict[str, Any],
        all_covered: bool,
        llm_belief: BeliefState,
    ) -> BeliefState:
        """Normalize an LLM answer onto consensus_key/structured_state/status.

        Tolerant: an unparseable/absent answer collapses to a valid UNKNOWN
        candidate rather than raising, so the runner never crashes on a stray
        LLM reply (deterministic repair handles it upstream as needed).
        """
        key = canonical_answer(answer) if answer is not None else "UNKNOWN"
        normalized_answer = answer if key != "UNKNOWN" else None
        status = BeliefStatus.FINAL if all_covered else BeliefStatus.CANDIDATE
        return llm_belief.model_copy(
            update={
                "status": status,
                "consensus_key": key,
                "structured_state": self._structured_state(
                    normalized_answer, known_jobs
                ),
            }
        )
