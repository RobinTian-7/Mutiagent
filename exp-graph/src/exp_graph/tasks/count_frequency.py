"""Distributed counting-frequency task adapter."""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from typing import Any

from exp_graph.agents.schemas import BeliefState, BeliefStatus
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.base import TaskAdapter
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter


CF_STATE_MARKER = "CF_STATE_JSON:"
FREQ_KEY_PREFIX = "FREQ_JSON:"
CF_OUTBOX_SCHEMA_VERSION = "cf-outbox-v1"


def canonicalize_counts(counts: dict[Any, Any] | Counter) -> dict[str, int]:
    """Return a deterministic count map with string keys and positive int counts."""
    cleaned: dict[str, int] = {}
    for key, value in dict(counts).items():
        count = int(value)
        if count <= 0:
            continue
        cleaned[str(key)] = cleaned.get(str(key), 0) + count
    return {
        key: cleaned[key]
        for key in sorted(cleaned, key=_sort_count_key)
    }


def counts_to_json(counts: dict[Any, Any] | Counter) -> str:
    """Encode counts as compact canonical JSON."""
    return json.dumps(
        canonicalize_counts(counts),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def count_frequency_consensus_key(counts: dict[Any, Any] | Counter) -> str:
    """Build the task-level final consensus key for a complete count map."""
    return f"{FREQ_KEY_PREFIX}{counts_to_json(counts)}"


def _counts_from_freq_key(key: str | None) -> dict[str, int] | None:
    text = str(key or "").strip()
    if not text.upper().startswith(FREQ_KEY_PREFIX):
        return None
    try:
        parsed = json.loads(text[len(FREQ_KEY_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return canonicalize_counts(parsed)


def local_frequency_counts(values: list[int]) -> dict[str, int]:
    """Count integer values in one shard."""
    return canonicalize_counts(Counter(int(value) for value in values))


def canonicalize_partials(partials: dict[Any, dict[Any, Any]]) -> dict[str, dict[str, int]]:
    """Canonicalize per-agent partial count maps."""
    cleaned: dict[str, dict[str, int]] = {}
    for agent_id, counts in dict(partials).items():
        cleaned[str(int(agent_id))] = canonicalize_counts(counts)
    return {
        agent_id: cleaned[agent_id]
        for agent_id in sorted(cleaned, key=lambda item: int(item))
    }


def counts_from_partials(partials: dict[Any, dict[Any, Any]]) -> dict[str, int]:
    """Merge per-agent partial count maps without double-counting agents."""
    total: Counter[str] = Counter()
    for counts in canonicalize_partials(partials).values():
        total.update(counts)
    return canonicalize_counts(total)


def encode_cf_state(partials: dict[Any, dict[Any, Any]]) -> str:
    """Encode mergeable CF state for proposal/outbox propagation."""
    canonical_partials = canonicalize_partials(partials)
    payload = {
        "counts": counts_from_partials(canonical_partials),
        "covered_agents": [int(agent_id) for agent_id in canonical_partials],
        "partials": canonical_partials,
    }
    return (
        CF_STATE_MARKER
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    )


def parse_cf_state_payload(text: str | None) -> dict[str, Any] | None:
    """Parse the first CF_STATE_JSON payload from text."""
    if not text:
        return None
    marker_idx = str(text).find(CF_STATE_MARKER)
    if marker_idx < 0:
        return None
    payload_start = marker_idx + len(CF_STATE_MARKER)
    raw = str(text)[payload_start:].lstrip()
    try:
        payload, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    partials = payload.get("partials")
    if isinstance(partials, dict):
        canonical_partials = canonicalize_partials(partials)
    else:
        canonical_partials = {}
    return {
        "counts": counts_from_partials(canonical_partials),
        "covered_agents": [int(agent_id) for agent_id in canonical_partials],
        "partials": canonical_partials,
    }


def build_cf_structured_state(
    *,
    partials: dict[Any, dict[Any, Any]],
    source_sizes: dict[Any, Any] | None = None,
    n_agents: int | None = None,
    merged_counts: dict[Any, Any] | None = None,
) -> dict[str, Any]:
    """Build canonical structured CF state for belief_state/outbox transport."""
    canonical_partials = canonicalize_partials(partials)
    canonical_sizes = {
        str(int(agent_id)): int(size)
        for agent_id, size in dict(source_sizes or {}).items()
        if str(int(agent_id)) in canonical_partials
    }
    canonical_merged_counts = (
        canonicalize_counts(merged_counts)
        if merged_counts is not None
        else counts_from_partials(canonical_partials)
    )
    return {
        "task_name": "count_frequency",
        "known_sources": [int(agent_id) for agent_id in canonical_partials],
        "partials": canonical_partials,
        "merged_counts": canonical_merged_counts,
        "source_sizes": canonical_sizes,
        "n_agents": n_agents,
    }


def extract_cf_structured_state(value: Any) -> dict[str, Any] | None:
    """Normalize a structured CF state dict if present."""
    if not isinstance(value, dict):
        return None
    if value.get("task_name") != "count_frequency" or "partials" not in value:
        return None
    partials = value.get("partials")
    if not isinstance(partials, dict):
        return None
    source_sizes = value.get("source_sizes")
    n_agents = value.get("n_agents")
    merged_counts = value.get("merged_counts")
    return build_cf_structured_state(
        partials=partials,
        source_sizes=source_sizes if isinstance(source_sizes, dict) else None,
        n_agents=int(n_agents) if n_agents is not None else None,
        merged_counts=merged_counts if isinstance(merged_counts, dict) else None,
    )


def build_cf_outbox_projection(message: OutboxMessage) -> dict[str, Any]:
    """Project an internal outbox into the answer artifact shown to the LLM."""
    return _build_cf_outbox_projection(
        sender_id=message.agent_id,
        round_idx=message.round_idx,
        status=message.status,
        consensus_key=message.consensus_key,
        support=message.support,
        uncertainty=message.uncertainty,
        request=message.request,
        structured_state=message.structured_payload,
    )


class CountFrequencyTaskAdapter(ProtocolTaskAdapter):
    """Task adapter for computing frequencies over a sharded integer array."""

    task_name = "count_frequency"

    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        """Build a global counting-frequency task.

        Accepted kwargs:
        - array: optional explicit list[int]
        - array_size: generated array length, default 1000
        - seed: random seed for generated task, default 0
        - value_min: generated minimum integer, default 0
        - value_max: generated maximum integer, default 9
        """
        if "array" in kwargs:
            array = [int(value) for value in kwargs["array"]]
            value_min = min(array, default=0)
            value_max = max(array, default=0)
        else:
            rng = random.Random(kwargs.get("seed", 0))
            array_size = int(kwargs.get("array_size", 1000))
            value_min = int(kwargs.get("value_min", 0))
            value_max = int(kwargs.get("value_max", 9))
            if value_max < value_min:
                raise ValueError("value_max must be greater than or equal to value_min")
            array = [rng.randint(value_min, value_max) for _ in range(array_size)]

        answer_counts = local_frequency_counts(array)
        answer_key = count_frequency_consensus_key(answer_counts)
        return {
            "task_name": self.task_name,
            "array": array,
            "array_length": len(array),
            "value_min": value_min,
            "value_max": value_max,
            "answer_counts": answer_counts,
            "answer_key": answer_key,
            "source_answer_counts_by_n_agents": {},
            "description": (
                "Compute the frequency of every distinct integer in the global array."
            ),
        }

    def split_into_local_observations(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> list[dict[str, Any]]:
        if n_agents < 1:
            raise ValueError("n_agents must be positive")

        self.build_source_answer_counts(global_task, n_agents)
        array = list(global_task["array"])
        observations = []
        base_size, remainder = divmod(len(array), n_agents)
        offset = 0
        for agent_id in range(n_agents):
            shard_size = base_size + (1 if agent_id < remainder else 0)
            shard = array[offset : offset + shard_size]
            observations.append(
                {
                    "task_name": self.task_name,
                    "agent_id": agent_id,
                    "array_shard": shard,
                    "global_offset": offset,
                    "shard_start": offset,
                    "shard_end_exclusive": offset + shard_size,
                    "n_agents": n_agents,
                    "array_length": int(global_task["array_length"]),
                    "value_min": int(global_task["value_min"]),
                    "value_max": int(global_task["value_max"]),
                }
            )
            offset += shard_size
        return observations

    def build_source_answer_counts(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> dict[str, dict[str, int]]:
        """Build scoring-only shard truth counts for a specific agent split.

        These counts are never copied into local_observation or prompts. They are
        used only by metrics to compare an agent answer against the shards whose
        information the agent currently carries.
        """
        if n_agents < 1:
            raise ValueError("n_agents must be positive")
        cache = global_task.setdefault("source_answer_counts_by_n_agents", {})
        cache_key = str(int(n_agents))
        if cache_key not in cache:
            array = list(global_task["array"])
            base_size, remainder = divmod(len(array), n_agents)
            offset = 0
            source_counts: dict[str, dict[str, int]] = {}
            for agent_id in range(n_agents):
                shard_size = base_size + (1 if agent_id < remainder else 0)
                shard = array[offset : offset + shard_size]
                source_counts[str(agent_id)] = local_frequency_counts(shard)
                offset += shard_size
            cache[cache_key] = source_counts
        return canonicalize_partials(cache[cache_key])

    def truth_counts_for_sources(
        self,
        *,
        global_task: dict[str, Any],
        n_agents: int,
        source_ids: list[int] | set[int],
    ) -> dict[str, int]:
        """Return the scoring truth for the union of known source shards."""
        source_truth = self.build_source_answer_counts(global_task, n_agents)
        selected = {
            str(int(source_id)): source_truth.get(str(int(source_id)), {})
            for source_id in source_ids
        }
        return counts_from_partials(selected)

    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        agent_id = int(local_observation["agent_id"])
        n_agents = int(local_observation["n_agents"])
        shard = [int(value) for value in local_observation["array_shard"]]
        local_counts = local_frequency_counts(shard)
        partials = {agent_id: local_counts}
        structured_state = build_cf_structured_state(
            partials=partials,
            source_sizes={agent_id: len(shard)},
            n_agents=n_agents,
        )
        state_payload = encode_cf_state(partials)

        if n_agents == 1:
            status = "final"
            consensus_key = count_frequency_consensus_key(local_counts)
            proposal = f"Global frequency counts are {counts_to_json(local_counts)}. {state_payload}"
            uncertainty = ""
            open_questions: list[str] = []
        else:
            status = "candidate"
            consensus_key = "UNKNOWN"
            proposal = (
                f"Partial frequency counts from agent {agent_id} are "
                f"{counts_to_json(local_counts)}. {state_payload}"
            )
            uncertainty = "Need partial counts from the remaining agents."
            open_questions = ["Share any missing CF partial counts."]

        return {
            "status": status,
            "proposal": proposal,
            "consensus_key": consensus_key,
            "support": [
                f"agent {agent_id} counted shard "
                f"[{local_observation['shard_start']}, "
                f"{local_observation['shard_end_exclusive']})",
                f"local_counts_json={counts_to_json(local_counts)}",
                f"covered_agents=[{agent_id}]",
            ],
            "uncertainty": uncertainty,
            "open_questions": open_questions,
            "private_notes": "local CF partial counts only",
            "structured_state": structured_state,
        }

    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState:
        """Create the initial protocol belief using the existing agent schema."""
        return BeliefState(**self.initial_local_solve(local_observation))

    def format_protocol_init_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        """Build the CF-specific prompt for LLM local initialization."""
        task_context = self.format_adjudication_context(global_task)
        local_context = dict(local_observation)
        return f"""You are one agent solving a local Count Frequency shard.

Count the frequency of each integer in LOCAL_CONTEXT_JSON.array_shard. This is only your local shard, not the global answer.

Reason inside the JSON `analysis` field before filling the answer fields:
record the shard size, list the distinct values you saw, and verify that
sum(merged_counts.values()) equals the shard length. Keep all reasoning
inside the JSON; do not emit prose or markdown outside it.

Rules: output exactly one JSON object and nothing outside it. Put your local
count dictionary in structured_state.merged_counts. Do not output partials or
source_sizes.

Return belief_state:
{{
  "analysis": {{
    "shard_length": 0,
    "distinct_values": [],
    "arithmetic_check": "sum(merged_counts.values()) == shard_length"
  }},
  "status": "candidate",
  "proposal": "short local count summary",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "need other agents",
  "open_questions": ["share other shards"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "count_frequency",
    "merged_counts": {{"1": 2}}
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

LOCAL_CONTEXT_JSON:
{json.dumps(local_context, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{{}}

INBOX_JSON:
[]
"""

    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState:
        """Validate and normalize an LLM-produced local CF initial belief."""
        belief_state = self._repair_protocol_belief_from_consensus_key(belief_state)
        if not isinstance(belief_state.structured_state, dict):
            raise ValueError("structured_state must be a count_frequency object")
        if belief_state.structured_state.get("task_name") != "count_frequency":
            raise ValueError("structured_state.task_name must be count_frequency")

        structured = extract_cf_structured_state(belief_state.structured_state)
        if structured is not None and structured.get("merged_counts"):
            local_counts = canonicalize_counts(structured["merged_counts"])
        elif isinstance(belief_state.structured_state.get("merged_counts"), dict):
            local_counts = canonicalize_counts(
                belief_state.structured_state["merged_counts"]
            )
        else:
            raise ValueError(
                "local init structured_state must include merged_counts as "
                "the LLM's local shard count"
            )

        value_min = int(global_task["value_min"])
        value_max = int(global_task["value_max"])
        for key, count in local_counts.items():
            _validate_count_entry(key, count, value_min=value_min, value_max=value_max)

        agent_id = int(local_observation["agent_id"])
        n_agents = int(local_observation["n_agents"])
        shard_size = len(list(local_observation.get("array_shard", [])))
        structured_state = build_cf_structured_state(
            partials={agent_id: local_counts},
            source_sizes={agent_id: shard_size},
            n_agents=n_agents,
            merged_counts=local_counts,
        )
        all_covered = n_agents == 1
        return belief_state.model_copy(
            update={
                "status": BeliefStatus.FINAL if all_covered else BeliefStatus.CANDIDATE,
                "consensus_key": (
                    count_frequency_consensus_key(local_counts)
                    if all_covered
                    else "UNKNOWN"
                ),
                "structured_state": structured_state,
            }
        )

    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState:
        """Merge structured CF packets by source id without double-counting."""
        partials, source_sizes, n_agents = self.extract_protocol_partials(
            old_belief_state
        )
        for message in inbox:
            message_partials, message_sizes, message_n = self.extract_message_partials(
                message
            )
            if message_n is not None:
                n_agents = message_n
            for source_id, counts in message_partials.items():
                if source_id not in partials:
                    partials[source_id] = counts
            for source_id, size in message_sizes.items():
                source_sizes.setdefault(source_id, size)

        if n_agents is None:
            n_agents = len(partials)
        return self.belief_from_partials(
            partials=partials,
            source_sizes=source_sizes,
            n_agents=n_agents,
            global_task=global_task,
        )

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
        """Build the CF-specific LLM prompt for protocol merge steps."""
        task_context = self.format_adjudication_context(global_task)
        local_context = _compact_local_observation(local_observation)
        old_belief = _compact_protocol_belief(old_belief_state)
        inbox_payload = [
            _compact_protocol_message(message)
            for message in inbox
        ]

        if merge_mode == "llm_belief_merge":
            if deterministic_belief is None:
                raise ValueError("deterministic_belief is required for llm_belief_merge")
            mode_instructions = (
                "Mode=llm_belief_merge. Use VERIFIED_MERGE_BELIEF_JSON as factual. "
                "Only improve proposal/support/uncertainty/open_questions/private_notes. "
                "Do not invent counts or sources. In `analysis`, briefly note which "
                "verified facts you relied on; leave the structured CF fields untouched."
            )
            verified_merge = _compact_protocol_belief(deterministic_belief)
        elif merge_mode == "llm_full_merge":
            mode_instructions = (
                "Mode=llm_full_merge. Treat OLD_BELIEF_STATE_JSON.artifact as "
                "your current answer artifact and INBOX_JSON as neighbor answer "
                "artifacts. Your job is to refine one frequency-count answer: "
                "compare the maps, merge non-overlapping source coverage using "
                "provenance.source_agent_ids, and avoid blindly adding counts "
                "when provenance overlaps. Output only the updated belief_state "
                "with structured_state.merged_counts as your current answer. "
                "The runtime keeps hidden scoring provenance separately; "
                "evaluation uses your merged_counts. Use the `analysis` field to "
                "show your provenance bookkeeping before producing merged_counts."
            )
            verified_merge = None
        else:
            raise ValueError(f"unsupported merge_mode for prompt: {merge_mode}")

        return f"""You are a CF protocol solver. Goal: global value frequencies from sharded agents.

{mode_instructions}

Reason inside the JSON `analysis` field before producing the answer.
Walk through provenance: list the source agent ids already covered by your
old belief, list the source agent ids each neighbor message covers, mark
which neighbor sources overlap with what you already had, state your merge
plan, and verify the arithmetic. Keep reasoning inside the JSON object.

Rules:
- Output exactly one JSON object and nothing outside it (no markdown fences,
  no prose before or after).
- Read neighbor messages as answer artifacts, not as chat history.
- Do not copy INBOX_JSON or outbox envelopes into your response.
- Always set consensus_key to "UNKNOWN" in your JSON response.
- Never put the full frequency dictionary inside consensus_key. The runtime
  derives the canonical final key from structured_state.merged_counts.

Return belief_state:
{{
  "analysis": {{
    "sources_in_old_belief": [0, 1],
    "sources_in_inbox": {{"agent_2": [2], "agent_3": [1, 3]}},
    "overlap_check": "agent_3 overlaps on source 1; only sources [3] are new",
    "merge_plan": "add agent_2 partial; from agent_3 take only source 3",
    "arithmetic_check": "sum(merged_counts) == sum of source_sizes for covered sources"
  }},
  "status": "unknown|candidate|final",
  "proposal": "short",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "short",
  "open_questions": ["short"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "count_frequency",
    "merged_counts": {{"1": 2}}
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

LOCAL_CONTEXT_JSON:
{json.dumps(local_context, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{json.dumps(old_belief, ensure_ascii=True, sort_keys=True)}

INBOX_JSON:
{json.dumps(inbox_payload, ensure_ascii=True, sort_keys=True)}

VERIFIED_MERGE_BELIEF_JSON:
{json.dumps(verified_merge, ensure_ascii=True, sort_keys=True)}
"""

    def validate_protocol_belief_state(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> BeliefState:
        """Validate and normalize a CF protocol belief produced by an LLM."""
        belief_state = self._repair_protocol_belief_from_consensus_key(belief_state)
        structured = self.validate_protocol_structured_state(
            belief_state.structured_state,
            global_task=global_task,
            n_agents=n_agents,
            transport_belief_state=transport_belief_state,
        )
        covered_agents = set(int(agent_id) for agent_id in structured["known_sources"])
        all_covered = len(covered_agents) >= n_agents
        status = BeliefStatus.FINAL if all_covered else BeliefStatus.CANDIDATE
        consensus_key = (
            count_frequency_consensus_key(structured["merged_counts"])
            if all_covered
            else "UNKNOWN"
        )
        return belief_state.model_copy(
            update={
                "status": status,
                "consensus_key": consensus_key,
                "structured_state": structured,
            }
        )

    def validate_protocol_structured_state(
        self,
        value: Any,
        *,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> dict[str, Any]:
        """Validate source ids and count domain for LLM-produced CF state."""
        structured = self._normalize_llm_protocol_structured_state(
            value=value,
            transport_belief_state=transport_belief_state,
        )

        value_min = int(global_task["value_min"])
        value_max = int(global_task["value_max"])
        partials = canonicalize_partials(structured["partials"])
        for source_id in partials:
            parsed_source_id = int(source_id)
            if parsed_source_id < 0 or parsed_source_id >= n_agents:
                raise ValueError(f"source agent id out of range: {source_id}")
            for key, count in partials[source_id].items():
                _validate_count_entry(key, count, value_min=value_min, value_max=value_max)

        merged_counts = canonicalize_counts(structured.get("merged_counts", {}))
        if not merged_counts and partials:
            raise ValueError(
                "llm_full_merge structured_state must include merged_counts as "
                "the LLM's current answer"
            )
        for key, count in merged_counts.items():
            _validate_count_entry(key, count, value_min=value_min, value_max=value_max)

        source_sizes = {
            str(agent_id): _expected_source_size(global_task, n_agents, agent_id)
            for agent_id in (int(source_id) for source_id in partials)
        }
        return build_cf_structured_state(
            partials=partials,
            source_sizes=source_sizes,
            n_agents=n_agents,
            merged_counts=merged_counts,
        )

    def _normalize_llm_protocol_structured_state(
        self,
        *,
        value: Any,
        transport_belief_state: BeliefState | None,
    ) -> dict[str, Any]:
        """Accept compact LLM answers while preserving runtime transport state."""
        if not isinstance(value, dict):
            raise ValueError("structured_state must be a count_frequency object")
        if value.get("task_name") != "count_frequency":
            raise ValueError("structured_state.task_name must be count_frequency")
        if not isinstance(value.get("merged_counts"), dict):
            raise ValueError(
                "llm_full_merge structured_state must include merged_counts as "
                "the LLM's current answer"
            )

        if isinstance(value.get("partials"), dict):
            structured = extract_cf_structured_state(value)
            if structured is None:
                raise ValueError("structured_state partials are invalid")
            return structured

        transport_structured = (
            extract_cf_structured_state(transport_belief_state.structured_state)
            if transport_belief_state is not None
            else None
        )
        if transport_structured is None:
            raise ValueError(
                "compact llm_full_merge structured_state requires runtime transport partials"
            )
        return build_cf_structured_state(
            partials=transport_structured["partials"],
            source_sizes=transport_structured["source_sizes"],
            n_agents=transport_structured["n_agents"],
            merged_counts=value.get("merged_counts"),
        )

    def _repair_protocol_belief_from_consensus_key(
        self,
        belief_state: BeliefState,
    ) -> BeliefState:
        """Repair missing merged_counts from an LLM-supplied FREQ_JSON key."""
        if not isinstance(belief_state.structured_state, dict):
            return belief_state
        if belief_state.structured_state.get("merged_counts"):
            return belief_state
        counts = _counts_from_freq_key(belief_state.consensus_key)
        if counts is None:
            return belief_state
        structured_state = dict(belief_state.structured_state)
        structured_state.setdefault("task_name", "count_frequency")
        structured_state["merged_counts"] = counts
        return belief_state.model_copy(update={"structured_state": structured_state})

    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState:
        """Keep LLM-facing wording while preserving verified CF structure."""
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
                if getattr(verified_belief_state.status, "value", verified_belief_state.status)
                == "final"
                else llm_belief_state.open_questions
                or verified_belief_state.open_questions
            ),
            private_notes=llm_belief_state.private_notes,
            confidence=llm_belief_state.confidence,
            structured_state=verified_belief_state.structured_state,
        )

    def belief_from_partials(
        self,
        *,
        partials: dict[Any, dict[Any, Any]],
        source_sizes: dict[Any, Any],
        n_agents: int,
        global_task: dict[str, Any],
    ) -> BeliefState:
        """Build a BeliefState from canonical CF partials."""
        structured_state = build_cf_structured_state(
            partials=partials,
            source_sizes=source_sizes,
            n_agents=n_agents,
        )
        counts = structured_state["merged_counts"]
        covered_agents = structured_state["known_sources"]
        state_payload = encode_cf_state(structured_state["partials"])
        all_covered = len(covered_agents) >= n_agents
        if all_covered:
            return BeliefState(
                status="final",
                proposal=(
                    f"Global frequency counts are {counts_to_json(counts)}. "
                    f"{state_payload}"
                ),
                consensus_key=count_frequency_consensus_key(counts),
                support=[
                    f"covered_agents={covered_agents}",
                    f"counts_json={counts_to_json(counts)}",
                ],
                uncertainty="",
                open_questions=[],
                private_notes="protocol merge covered all CF sources",
                structured_state=structured_state,
            )

        missing_agents = [
            agent_id for agent_id in range(n_agents) if agent_id not in set(covered_agents)
        ]
        return BeliefState(
            status="candidate",
            proposal=(
                f"Partial frequency counts over agents {covered_agents} are "
                f"{counts_to_json(counts)}. {state_payload}"
            ),
            consensus_key="UNKNOWN",
            support=[
                f"covered_agents={covered_agents}",
                f"counts_json={counts_to_json(counts)}",
            ],
            uncertainty=f"Missing partial counts from agents {missing_agents}.",
            open_questions=["Share any missing CF partial counts."],
            private_notes="protocol partial CF merge state",
            structured_state=structured_state,
        )

    def extract_protocol_partials(
        self,
        belief_state: BeliefState,
    ) -> tuple[dict[str, dict[str, int]], dict[str, int], int | None]:
        """Extract canonical CF partials from a belief state."""
        structured = extract_cf_structured_state(belief_state.structured_state)
        if structured is None:
            payload = parse_cf_state_payload(belief_state.proposal)
            structured = (
                build_cf_structured_state(partials=payload["partials"])
                if payload
                else build_cf_structured_state(partials={})
            )
        return (
            canonicalize_partials(structured["partials"]),
            {str(key): int(value) for key, value in structured.get("source_sizes", {}).items()},
            int(structured["n_agents"]) if structured.get("n_agents") is not None else None,
        )

    def extract_message_partials(
        self,
        message: OutboxMessage,
    ) -> tuple[dict[str, dict[str, int]], dict[str, int], int | None]:
        """Extract canonical CF partials from an outbox message."""
        structured = extract_cf_structured_state(message.structured_payload)
        if structured is None:
            payload = parse_cf_state_payload(message.proposal)
            structured = (
                build_cf_structured_state(partials=payload["partials"])
                if payload
                else build_cf_structured_state(partials={})
            )
        return (
            canonicalize_partials(structured["partials"]),
            {str(key): int(value) for key, value in structured.get("source_sizes", {}).items()},
            int(structured["n_agents"]) if structured.get("n_agents") is not None else None,
        )

    def extract_protocol_counts(self, belief_state: BeliefState) -> dict[str, int]:
        """Extract the merged CF counts carried by a belief state."""
        structured = extract_cf_structured_state(belief_state.structured_state)
        if structured is not None:
            return canonicalize_counts(structured.get("merged_counts", {}))
        payload = parse_cf_state_payload(belief_state.proposal)
        if payload:
            return canonicalize_counts(payload.get("counts", {}))
        partials, _, _ = self.extract_protocol_partials(belief_state)
        return counts_from_partials(partials)

    def compute_protocol_agent_metrics(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> dict[str, Any]:
        """Compute per-agent local accuracy from carried CF sources."""
        partials, source_sizes, _ = self.extract_protocol_partials(belief_state)
        counts = self.extract_protocol_counts(belief_state)
        known_sources = sorted(int(agent_id) for agent_id in partials)
        local_truth = self.truth_counts_for_sources(
            global_task=global_task,
            n_agents=n_agents,
            source_ids=known_sources,
        )
        global_truth = canonicalize_counts(global_task["answer_counts"])
        domain = self.count_domain_keys(global_task)
        global_array_size = max(1, int(global_task["array_length"]))
        known_item_count = sum(
            int(source_sizes.get(str(agent_id), 0))
            for agent_id in known_sources
        )
        local_array_size = max(1, known_item_count)
        coverage = known_item_count / global_array_size
        local_normalized_l1 = normalized_l1_error(
            counts,
            local_truth,
            array_size=local_array_size,
            domain_keys=domain,
        )
        global_normalized_l1 = normalized_l1_error(
            counts,
            global_truth,
            array_size=global_array_size,
            domain_keys=domain,
        )
        local_rmse = compute_rmse(counts, local_truth, domain)
        global_rmse = compute_rmse(counts, global_truth, domain)
        local_exact_match = canonicalize_counts(counts) == local_truth
        global_exact_match = canonicalize_counts(counts) == global_truth
        return {
            "known_sources": known_sources,
            "known_source_count": len(partials),
            "coverage_ratio": coverage,
            "known_item_count": known_item_count,
            "local_normalized_l1_error": local_normalized_l1,
            "global_normalized_l1_error": global_normalized_l1,
            "normalized_l1_error": local_normalized_l1,
            "local_rmse": local_rmse,
            "global_rmse": global_rmse,
            "rmse": local_rmse,
            "local_exact_match": local_exact_match,
            "global_exact_match": global_exact_match,
            "exact_match": local_exact_match,
        }

    def count_domain_keys(self, global_task: dict[str, Any]) -> list[str]:
        """Return the value domain for CF metrics."""
        value_min = int(global_task["value_min"])
        value_max = int(global_task["value_max"])
        return [str(value) for value in range(value_min, value_max + 1)]

    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        if key_or_proposal is None:
            return "UNKNOWN"

        text = str(key_or_proposal).strip()
        if not text or text.upper() in {"NULL", "NONE", "UNKNOWN", "PARTIAL"}:
            return "UNKNOWN"

        upper_text = text.upper()
        if upper_text.startswith(FREQ_KEY_PREFIX):
            raw_counts = text[len(FREQ_KEY_PREFIX) :]
            try:
                parsed = json.loads(raw_counts)
            except json.JSONDecodeError:
                return "UNKNOWN"
            if not isinstance(parsed, dict):
                return "UNKNOWN"
            return count_frequency_consensus_key(parsed)

        return "UNKNOWN"

    def evaluate_final_answer(
        self,
        global_task: dict[str, Any],
        final_key: str | None,
    ) -> bool:
        return self.normalize_consensus_key(final_key) == global_task["answer_key"]

    def format_task_prompt_context(
        self,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        return (
            f"Task: {global_task['description']}\n"
            f"Global array length: {global_task['array_length']}\n"
            f"Integer value range for generated data: "
            f"[{global_task['value_min']}, {global_task['value_max']}]\n"
            f"Your shard global range: "
            f"[{local_observation['shard_start']}, "
            f"{local_observation['shard_end_exclusive']})\n"
            f"Total agents: {local_observation['n_agents']}\n"
            f"Your array_shard: {local_observation['array_shard']}\n"
            "Maintain a machine-readable CF_STATE_JSON payload in proposal. "
            "It must contain partials, covered_agents, and merged counts."
        )

    def format_consensus_key_instructions(self) -> str:
        """Return counting-frequency consensus-key rules for solver prompts."""
        return (
            "For count_frequency, keep consensus_key=UNKNOWN in LLM output and "
            "put frequency counts in the task's structured state. The runtime "
            "derives the canonical FREQ_JSON key from the count map when needed."
        )

    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        """Return task context for adjudication without answer counts."""
        return {
            "task_name": self.task_name,
            "description": global_task["description"],
            "array_length": global_task["array_length"],
            "value_min": global_task["value_min"],
            "value_max": global_task["value_max"],
        }

    # --- ProtocolTaskAdapter answer/score/finalize (delegates to cf_final/cf_protocol) ---
    def extract_protocol_answer(self, belief_state: BeliefState) -> dict[str, int]:
        return self.extract_protocol_counts(belief_state)

    def protocol_answer_key(self, answer: Any) -> str:
        return count_frequency_consensus_key(answer or {})

    def score_protocol_answer(
        self, answer: Any, global_task: dict[str, Any]
    ) -> dict[str, Any]:
        domain = self.count_domain_keys(global_task)
        truth = canonicalize_counts(global_task["answer_counts"])
        pred = canonicalize_counts(answer or {})
        return {
            "primary_metric": compute_rmse(pred, truth, domain),
            "exact_match": pred == truth,
        }

    def answer_holders(
        self, *, topology_name: str, n_agents: int, star_center: int
    ) -> list[int]:
        from exp_graph.aggregator.cf_final import answer_agents_for_topology

        return answer_agents_for_topology(
            topology_name=topology_name, n_agents=n_agents, star_center=star_center
        )

    def finalize_protocol(
        self,
        *,
        agent_states,
        global_task,
        topology_name,
        star_center=0,
        average_include_min_coverage=1.0,
        selected_primary="topology_default",
        answer_agent_ids_override=None,
    ):
        from exp_graph.aggregator.cf_final import run_cf_final_aggregation

        return run_cf_final_aggregation(
            agent_states=agent_states,
            global_task=global_task,
            task_adapter=self,
            topology_name=topology_name,
            star_center=star_center,
            average_include_min_coverage=average_include_min_coverage,
            selected_primary=selected_primary,
            answer_agent_ids_override=answer_agent_ids_override,
        )

    def build_protocol_step_metrics(
        self,
        *,
        agent_states,
        global_task,
        topology_name,
        step_idx,
        phase,
        send_counts,
        receive_counts,
        average_include_min_coverage=1.0,
    ):
        from exp_graph.metrics.cf_protocol import build_cf_step_metrics

        return build_cf_step_metrics(
            agent_states=agent_states,
            global_task=global_task,
            task_adapter=self,
            topology_name=topology_name,
            step_idx=step_idx,
            phase=phase,
            send_counts=send_counts,
            receive_counts=receive_counts,
            average_include_min_coverage=average_include_min_coverage,
        )


def _sort_count_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _validate_count_entry(
    key: Any,
    count: Any,
    *,
    value_min: int,
    value_max: int,
) -> None:
    parsed_key = int(key)
    if parsed_key < value_min or parsed_key > value_max:
        raise ValueError(f"count key out of task value range: {key}")
    if int(count) < 0:
        raise ValueError(f"negative count for key {key}: {count}")


def _compact_local_observation(local_observation: dict[str, Any]) -> dict[str, Any]:
    """Keep local prompt context label-safe and avoid replaying large raw shards."""
    shard = list(local_observation.get("array_shard", []))
    return {
        key: value
        for key, value in local_observation.items()
        if key != "array_shard"
    } | {
        "shard_length": len(shard),
    }


def _compact_protocol_belief(belief_state: BeliefState) -> dict[str, Any]:
    """Project an internal belief into the answer artifact shown to the LLM."""
    return _build_cf_outbox_projection(
        sender_id=None,
        round_idx=None,
        status=_status_value(belief_state.status),
        consensus_key=belief_state.consensus_key,
        support=belief_state.support,
        uncertainty=belief_state.uncertainty,
        request=(belief_state.open_questions[0] if belief_state.open_questions else ""),
        structured_state=belief_state.structured_state,
    )


def _compact_protocol_message(message: OutboxMessage) -> dict[str, Any]:
    """Keep inbox prompts focused on answer artifacts, not internal state."""
    return build_cf_outbox_projection(message)


def _compact_protocol_structured_state(value: Any) -> dict[str, Any]:
    """Return only the LLM-visible answer part of internal CF state."""
    structured = extract_cf_structured_state(value)
    if structured is None:
        return {}
    return {
        "task_name": "count_frequency",
        "known_sources": structured["known_sources"],
        "merged_counts": structured["merged_counts"],
        "n_agents": structured["n_agents"],
    }


def _build_cf_outbox_projection(
    *,
    sender_id: int | None,
    round_idx: int | None,
    status: str,
    consensus_key: str | None,
    support: list[str],
    uncertainty: str,
    request: str,
    structured_state: Any,
) -> dict[str, Any]:
    structured = extract_cf_structured_state(structured_state)
    if structured is None:
        known_sources: list[int] = []
        answer: dict[str, int] = {}
        n_agents = None
    else:
        known_sources = [int(agent_id) for agent_id in structured["known_sources"]]
        answer = canonicalize_counts(structured.get("merged_counts", {}))
        n_agents = structured.get("n_agents")

    coverage_hint = {
        "known_source_count": len(known_sources),
        "n_agents": n_agents,
    }
    projected: dict[str, Any] = {
        "schema_version": CF_OUTBOX_SCHEMA_VERSION,
        "task_name": "count_frequency",
        "message_type": "answer_artifact",
        "status": status,
        "artifact": {
            "kind": "frequency_counts",
            "answer": answer,
            "answer_format": "sparse_counts_by_integer_string",
            "consensus_key": _compact_consensus_key_for_prompt(consensus_key),
        },
        "provenance": {
            "source_agent_ids": known_sources,
            "coverage_hint": coverage_hint,
        },
        "quality": {
            "support": [str(item) for item in support[:3]],
            "uncertainty": str(uncertainty or ""),
            "conflicts": [],
        },
        "request": {
            "action": "merge_and_refine",
            "instruction": (
                str(request)
                if request
                else "Merge this answer artifact with your current answer."
            ),
        },
    }
    if sender_id is not None:
        projected["sender_id"] = int(sender_id)
    if round_idx is not None:
        projected["round_idx"] = int(round_idx)
    if sender_id is not None and round_idx is not None:
        projected["sender_message_id"] = f"{int(sender_id)}:{int(round_idx)}"
    return projected


def _status_value(status: Any) -> str:
    return str(status.value) if hasattr(status, "value") else str(status)


def _compact_consensus_key_for_prompt(key: str | None) -> str:
    text = str(key or "").strip()
    if text.startswith(FREQ_KEY_PREFIX):
        return "DERIVED_FROM_MERGED_COUNTS"
    return text if text else "UNKNOWN"


def _expected_source_size(
    global_task: dict[str, Any],
    n_agents: int,
    agent_id: int,
) -> int:
    array_length = int(global_task["array_length"])
    base_size, remainder = divmod(array_length, n_agents)
    return base_size + (1 if agent_id < remainder else 0)


def compute_rmse(
    pred_counts: dict[Any, Any],
    true_counts: dict[Any, Any],
    domain_keys: list[str],
) -> float:
    """Return root-sum-squared count error over the task value domain.

    This is intentionally not divided by the domain size. The public metric name
    remains RMSE for continuity with existing experiment outputs.
    """
    if not domain_keys:
        return 0.0
    pred = canonicalize_counts(pred_counts)
    truth = canonicalize_counts(true_counts)
    squared_error = sum(
        (float(pred.get(key, 0)) - float(truth.get(key, 0))) ** 2
        for key in domain_keys
    )
    return math.sqrt(squared_error)


def normalized_l1_error(
    pred_counts: dict[Any, Any],
    true_counts: dict[Any, Any],
    *,
    array_size: int,
    domain_keys: list[str],
) -> float:
    if array_size <= 0:
        return 0.0
    pred = canonicalize_counts(pred_counts)
    truth = canonicalize_counts(true_counts)
    return sum(
        abs(float(pred.get(key, 0)) - float(truth.get(key, 0)))
        for key in domain_keys
    ) / array_size
