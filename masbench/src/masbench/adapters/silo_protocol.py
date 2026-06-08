"""Silo-Bench behind the QueenBee temporal-DAG protocol engine.

``SiloProtocolAdapter`` lets ``exp_graph.runner.protocol.ProtocolRunner`` drive a
single :class:`~masbench.core.instance.BenchmarkInstance`. It reuses the six base
``TaskAdapter`` methods from :class:`BenchmarkTaskAdapter` (build/split/solve/
normalize/evaluate/format) and the generic finalize/step-metric/answer-holder
defaults from :class:`ProtocolTaskAdapter`; this module only adds the per-agent
belief lifecycle plus the answer/score hooks.

Belief model: every belief carries the agent's current candidate GLOBAL answer in
``structured_state={"task_name": "silo", "case_id": <id>, "answer": <value>}`` and
mirrors its canonical form in ``consensus_key`` (or ``"UNKNOWN"``).

Offline determinism: a single agent holding only one shard usually cannot know
the GLOBAL answer, so beliefs default to CANDIDATE / ``"UNKNOWN"``. For the small
set of associative-reduce cases (e.g. Global Max ``"I-01"`` -> ``max``) a shard's
local reduction is carried in ``structured_state.answer`` so neighbors can fold it
in deterministically, letting a topology whose holder reaches full coverage
converge to the correct answer without any LLM. General tasks (e.g. distributed
sort) have no offline solver: those beliefs stay ``"UNKNOWN"`` and the real merge
is the LLM's job in the online modes.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from exp_graph.agents.schemas import BeliefState, BeliefStatus
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter

from masbench.adapters.silo_scoring import silo_partial_score
from masbench.core.task_bridge import (
    GROUND_TRUTH_KEY,
    BenchmarkTaskAdapter,
    canonical_answer,
)

SILO_PROTOCOL_TASK_NAME = "silo"


def score_protocol_answer(answer: Any, global_task: dict[str, Any]) -> dict[str, Any]:
    """Score one Silo global answer: strict exact-match plus a graded ``partial``.

    ``primary_metric``/``exact_match`` stay the strict 1.0/0.0 success signal used
    by topology selection and evolution; ``partial`` adds the graded
    PARTIAL-CORRECTNESS value in [0, 1] (see ``silo_scoring.silo_partial_score``).
    Module-level so masbench can recompute ``partial`` from a final answer without
    holding a task-adapter instance; the adapter method delegates here.
    """
    if answer is None:
        return {"primary_metric": 0.0, "exact_match": False, "partial": 0.0}
    ground_truth = global_task[GROUND_TRUTH_KEY]
    success = canonical_answer(answer) == ground_truth
    partial = silo_partial_score(
        answer, ground_truth, global_task.get("output_type", "scalar")
    )
    return {
        "primary_metric": 1.0 if success else 0.0,
        "exact_match": success,
        "partial": float(partial),
    }

# case_id -> reducer over a flat list of numbers. Mirrors masbench.llm.fake._REDUCERS:
# only associative reductions that an offline deterministic merge can fold over a
# shard plus neighbor answers belong here. Everything else stays UNKNOWN offline.
_REDUCERS: dict[str, Callable[[list[float]], Any]] = {
    "I-01": max,  # Global Max
}


def _as_number(value: Any) -> float | None:
    """Best-effort numeric coercion that rejects booleans and sentinels."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() in {"UNKNOWN", "NONE", "NULL"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_number(value: float) -> Any:
    """Render an int when the float is integral so answers stay clean (9 not 9.0)."""
    return int(value) if float(value).is_integer() else value


def _answer_from_structured_state(value: Any) -> Any:
    """Pull the candidate answer out of a silo structured_state dict, if present."""
    if not isinstance(value, dict):
        return None
    if value.get("task_name") != SILO_PROTOCOL_TASK_NAME:
        return None
    return value.get("answer")


def _answer_from_message(message: OutboxMessage) -> Any:
    """Recover a neighbor's candidate answer from its outbox message."""
    answer = _answer_from_structured_state(message.structured_payload)
    if answer is not None:
        return answer
    key = message.consensus_key
    if key is None or canonical_answer(key) == "UNKNOWN":
        return None
    # consensus_key is canonical JSON; parse it back so reduce sees real values.
    try:
        return json.loads(key)
    except (TypeError, ValueError):
        return key


class SiloProtocolAdapter(BenchmarkTaskAdapter, ProtocolTaskAdapter):
    """Drive one Silo-Bench BenchmarkInstance through ProtocolRunner.

    ``__init__(self, instance)`` is inherited from :class:`BenchmarkTaskAdapter`;
    the six base TaskAdapter methods come from there too, and the generic
    finalize/step-metric/answer-holder defaults come from
    :class:`ProtocolTaskAdapter`. Only the belief lifecycle + answer/score hooks
    are defined here.
    """

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _case_id(self) -> str:
        return str(self.instance.case_id)

    def _reducer(self) -> Callable[[list[float]], Any] | None:
        return _REDUCERS.get(self._case_id())

    def _local_reduce(self, shard: Any) -> Any:
        """Reduce a single shard locally for the deterministic offline path."""
        reducer = self._reducer()
        if reducer is None or not isinstance(shard, list):
            return None
        numbers = [n for n in (_as_number(v) for v in shard) if n is not None]
        if not numbers:
            return None
        return _normalize_number(float(reducer(numbers)))

    def _structured_state(self, answer: Any) -> dict[str, Any]:
        return {
            "task_name": SILO_PROTOCOL_TASK_NAME,
            "case_id": self._case_id(),
            "answer": answer,
        }

    def _belief_from_answer(
        self,
        answer: Any,
        *,
        status: BeliefStatus,
        proposal: str,
        open_questions: list[str] | None = None,
        uncertainty: str = "",
        support: list[str] | None = None,
        private_notes: str = "silo protocol belief",
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
            structured_state=self._structured_state(answer),
        )

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: per-agent belief lifecycle
    # ------------------------------------------------------------------ #
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState:
        agent_id = int(local_observation["agent_id"])
        n_agents = int(local_observation["n_agents"])
        shard = local_observation.get("input_shard")
        local_answer = self._local_reduce(shard)

        # A lone agent with a deterministic local solver can compute the full,
        # FINAL answer. Otherwise we hold a CANDIDATE and never claim to KNOW the
        # global answer: consensus_key stays UNKNOWN, while structured_state.answer
        # carries the shard's local contribution so neighbors can reduce it.
        if n_agents == 1 and local_answer is not None:
            return self._belief_from_answer(
                local_answer,
                status=BeliefStatus.FINAL,
                proposal=f"Global answer is {local_answer}.",
                private_notes="silo single-agent deterministic local solve",
            )

        if local_answer is not None:
            belief = self._belief_from_answer(
                local_answer,
                status=BeliefStatus.CANDIDATE,
                proposal=(
                    f"Agent {agent_id} local reduction is {local_answer}; "
                    "other shards may change the global answer."
                ),
                uncertainty="Need contributions from the remaining agents.",
                open_questions=["Share your shard's contribution."],
                support=[f"agent {agent_id} local reduction={local_answer}"],
                private_notes="silo local reduction (partial)",
            )
            # Carry the partial contribution for neighbors, but do not yet claim a
            # known GLOBAL answer.
            return belief.model_copy(update={"consensus_key": "UNKNOWN"})

        return self._belief_from_answer(
            None,
            status=BeliefStatus.CANDIDATE,
            proposal=(
                f"Agent {agent_id} holds a private shard; the global answer is "
                "not yet known."
            ),
            uncertainty="Need information from other agents for the global answer.",
            open_questions=["What do other agents' shards contribute?"],
            support=[f"agent {agent_id} local shard only"],
            private_notes="silo local shard only",
        )

    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState:
        reducer = self._reducer()
        if reducer is None:
            # No offline solver for this task: the real merge is the LLM's job.
            # Preserve any candidate contribution already carried; never invent one.
            own = _answer_from_structured_state(old_belief_state.structured_state)
            return self._belief_from_answer(
                None,
                status=BeliefStatus.CANDIDATE,
                proposal="No deterministic offline merge for this task.",
                uncertainty="Use an LLM merge mode to combine neighbor answers.",
                open_questions=["Combine neighbor answers via the LLM."],
                support=(
                    [f"carried local contribution={own}"] if own is not None else []
                ),
                private_notes="silo non-reduce merge (offline UNKNOWN)",
            ).model_copy(
                update={"structured_state": self._structured_state(own)}
            )

        numbers: list[float] = []
        own = _answer_from_structured_state(old_belief_state.structured_state)
        own_num = _as_number(own)
        if own_num is not None:
            numbers.append(own_num)
        for message in inbox:
            message_num = _as_number(_answer_from_message(message))
            if message_num is not None:
                numbers.append(message_num)

        if not numbers:
            return self._belief_from_answer(
                None,
                status=BeliefStatus.CANDIDATE,
                proposal="No candidate contributions to reduce yet.",
                uncertainty="Need at least one shard contribution.",
                open_questions=["Share your shard's contribution."],
                private_notes="silo reduce merge (empty)",
            )

        reduced = _normalize_number(float(reducer(numbers)))
        return self._belief_from_answer(
            reduced,
            status=BeliefStatus.CANDIDATE,
            proposal=f"Reduced answer across known contributions is {reduced}.",
            uncertainty="Unmerged shards could still change the answer.",
            open_questions=["Share any further shard contributions."],
            support=[f"reduced {len(numbers)} visible contributions -> {reduced}"],
            private_notes="silo deterministic reduce over shard + neighbor answers",
        )

    def format_protocol_init_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        task_context = self.format_adjudication_context(global_task)
        prompt_context = self.format_task_prompt_context(global_task, local_observation)
        return f"""You are one agent collaborating to solve a single Silo-Bench task.

Solve THIS task as far as your own shard allows. Your shard is usually only part
of the input, so you may not be able to determine the GLOBAL answer alone.

Rules: output exactly one JSON object (a belief_state) and nothing outside it (no
markdown fences, no prose). Put your best current GLOBAL answer in
structured_state.answer using its natural JSON type (a number, string, list, or
object). If you cannot yet determine the global answer, use null and set
consensus_key to "UNKNOWN".

TASK_FOR_AGENT:
{prompt_context}
Return belief_state:
{{
  "status": "candidate",
  "proposal": "short summary of what you can determine from your shard",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "what you still need from other agents",
  "open_questions": ["what do other agents' shards contribute?"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "{SILO_PROTOCOL_TASK_NAME}",
    "case_id": "{self._case_id()}",
    "answer": null
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
        verified_answer = (
            _answer_from_structured_state(deterministic_belief.structured_state)
            if deterministic_belief is not None
            else None
        )
        return f"""You are one agent solving a single Silo-Bench task. Goal: the
correct GLOBAL answer across every agent's shard.

Mode={merge_mode}. Merge YOUR_ANSWER_JSON with the neighbor answer artifacts in
INBOX_ANSWERS_JSON into one global answer for this task. Do not invent data; only
combine what is given plus your own shard. If a deterministic check is provided
in VERIFIED_ANSWER_JSON and is not null, prefer it.

Rules: output exactly one JSON object (a belief_state) and nothing outside it.
Put the merged GLOBAL answer in structured_state.answer using its natural JSON
type. Set consensus_key to the same answer (compact canonical form), or
"UNKNOWN" if you still cannot determine it.

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
    "task_name": "{SILO_PROTOCOL_TASK_NAME}",
    "case_id": "{self._case_id()}",
    "answer": null
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

YOUR_ANSWER_JSON:
{json.dumps(own_answer, ensure_ascii=True)}

INBOX_ANSWERS_JSON:
{json.dumps(inbox_answers, ensure_ascii=True)}

VERIFIED_ANSWER_JSON:
{json.dumps(verified_answer, ensure_ascii=True)}
"""

    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState:
        n_agents = int(local_observation["n_agents"])
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is None:
            answer = self._answer_from_consensus_key(belief_state.consensus_key)
        # A single agent covers the whole task; otherwise a fresh shard belief is
        # only a candidate.
        all_covered = n_agents == 1
        return self._finalize_validated_belief(
            answer,
            all_covered=all_covered,
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
        if answer is None and transport_belief_state is not None:
            answer = _answer_from_structured_state(
                transport_belief_state.structured_state
            )
            if answer is None:
                answer = self._answer_from_consensus_key(
                    transport_belief_state.consensus_key
                )
        all_covered = n_agents == 1
        return self._finalize_validated_belief(
            answer,
            all_covered=all_covered,
            llm_belief=belief_state,
        )

    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState:
        # Keep the LLM's wording but trust the verified (deterministic) answer.
        return BeliefState(
            status=verified_belief_state.status,
            proposal=llm_belief_state.proposal or verified_belief_state.proposal,
            consensus_key=verified_belief_state.consensus_key,
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
            structured_state=verified_belief_state.structured_state,
        )

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
        # Strict exact-match drives primary_metric/exact_match (unchanged); the
        # graded PARTIAL-CORRECTNESS value rides alongside in ``partial``.
        return score_protocol_answer(answer, global_task)

    def compute_protocol_agent_metrics(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> dict[str, Any]:
        answer = self.extract_protocol_answer(belief_state)
        correct = (
            answer is not None
            and canonical_answer(answer) == global_task[GROUND_TRUTH_KEY]
        )
        # Honest coverage proxy: this belief reflects the full answer only once it
        # equals the ground truth; until then it carries strictly partial info.
        return {
            "coverage_ratio": 1.0 if correct else 0.0,
            "primary_metric": 1.0 if correct else 0.0,
            "exact_match": correct,
        }

    # ------------------------------------------------------------------ #
    # Internal validation helpers
    # ------------------------------------------------------------------ #
    def _answer_from_consensus_key(self, key: str | None) -> Any:
        if key is None or canonical_answer(key) == "UNKNOWN":
            return None
        try:
            return json.loads(key)
        except (TypeError, ValueError):
            return key

    def _finalize_validated_belief(
        self,
        answer: Any,
        *,
        all_covered: bool,
        llm_belief: BeliefState,
    ) -> BeliefState:
        """Normalize an LLM answer onto consensus_key/structured_state/status.

        Tolerant: an unparseable/absent answer collapses to a valid UNKNOWN
        candidate rather than raising, so the runner never crashes on a stray LLM
        reply (it falls back through deterministic repair upstream as needed).
        """
        key = canonical_answer(answer) if answer is not None else "UNKNOWN"
        normalized_answer = answer if key != "UNKNOWN" else None
        status = BeliefStatus.FINAL if all_covered else BeliefStatus.CANDIDATE
        return llm_belief.model_copy(
            update={
                "status": status,
                "consensus_key": key,
                "structured_state": self._structured_state(normalized_answer),
            }
        )
