"""Process-local security and metering wrapper for generated Python programs.

This module runs only inside the isolated child. It patches the existing factory
in that process before the generated source imports it, preserving the public
``LLMClient.complete`` API while making provider/model configuration and usage
accounting authoritative to the host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sys
from pathlib import Path
from typing import Any

from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens
from exp_graph.llm.factory import create_llm_client as _real_factory
import exp_graph.llm.factory as factory_module
from exp_graph.mas.python_code import (
    MESSAGE_ONLY_MESSAGE_INSTRUCTION,
    MESSAGE_ONLY_SUBMIT_INSTRUCTION,
    MESSAGE_ONLY_V2_MESSAGE_INSTRUCTION,
    MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION,
)


_ACTION_INSTRUCTION = (
    "Return one JSON action with state, should_send, recipients, message, "
    "source_ids, submit, answer. Use only your local prompt, previous state, "
    "and delivered inbox.\n"
)
_MESSAGE_ONLY_MODES = ("send", "reflect", "submit")
_MESSAGE_ONLY_V2_MODES = ("send", "reflect", "submit")


class _LimitedStdout:
    """Child-local byte counter enforcing stdout size before host allocation."""

    def __init__(self, inner: Any, max_bytes: int) -> None:
        self.inner = inner
        self.max_bytes = max_bytes
        self.written = 0

    def write(self, value: str) -> int:
        size = len(value.encode("utf-8"))
        if self.written + size > self.max_bytes:
            raise RuntimeError("BudgetError: stdout output-size budget exceeded")
        written = self.inner.write(value)
        self.written += size
        return written

    def flush(self) -> None:
        self.inner.flush()


class _PythonSmokeClient:
    """Honest offline worker: valid JSON state, deliberately no task solution."""

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        del model_name, temperature
        if json_mode is False:
            contract = _prompt_header_str(prompt, "PYTHON_WORKER_CONTRACT")
            control = _prompt_json_line(prompt, "PYTHON_CONTROL_JSON")
            if contract == "message_only_v2" and control.get("mode") == "submit":
                # A JSON string proves native-value parsing without pretending
                # that the offline fake solved the benchmark task.
                text = json.dumps("UNKNOWN")
            else:
                text = (
                    "Offline smoke summary: deterministic fake worker text. "
                    "No offline task solver is used."
                )
        else:
            text = json.dumps(
                {
                    "status": "unknown",
                    "proposal": "Offline Python worker smoke state.",
                    "consensus_key": "UNKNOWN",
                    "support": [],
                    "uncertainty": "No offline task solver is used.",
                    "open_questions": [],
                    "private_notes": "fake wiring only",
                }
            )
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
            ),
        )


class _MeteredClient:
    def __init__(self, inner: Any, auth: dict[str, Any], ledger: dict[str, Any], path: Path):
        self.inner = inner
        self.auth = auth
        self.ledger = ledger
        self.path = path
        self.worker_contract = str(auth.get("worker_contract") or "action_json_v1")
        n_agents = int(auth["n_agents"])
        self.expected_states: dict[int, dict[str, Any]] = {
            agent_id: {} for agent_id in range(n_agents)
        }
        # 中文：message_only_v1 的权威运行时状态：Worker/生成程序都不能覆盖它。
        #   previous_outputs=各 agent 上一轮 Worker 文本；known_sources=宿主合并的
        #   provenance；pending_envelopes=已发送、待(或已)投递的完整信封(含 body，
        #   仅内存持有，绝不写入 ledger 文件)；submitted_rounds=已提交轮次。
        # Authoritative message_only_v1 runtime state; neither the worker nor
        # the generated program can override it. previous_outputs holds each
        # agent's last worker text; known_sources the host-merged provenance;
        # pending_envelopes the full sent envelopes (bodies stay in memory
        # only, never in the ledger file); submitted_rounds the submit rounds.
        self.previous_outputs: dict[int, str] = {
            agent_id: "" for agent_id in range(n_agents)
        }
        self.known_sources: dict[int, set[int]] = {
            agent_id: {agent_id} for agent_id in range(n_agents)
        }
        self.pending_envelopes: list[dict[str, Any]] = []
        self.submitted_rounds: dict[int, int] = {}
        self.pending_barrier_submissions: dict[int, int] = {}
        self.declared_submit_round: int | None = None
        self.frozen_barrier_states: dict[int, dict[str, Any]] = {}
        self.frozen_barrier_inboxes: dict[int, list[dict[str, Any]]] = {}
        self.called_pairs: set[tuple[int, int]] = set()
        self.max_round_seen = -1
        self.total_messages = 0

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        json_mode: bool | None = None,
    ) -> LLMResponse:
        expected = self.auth["worker_llm"]
        if model_name != expected["model_name"]:
            raise RuntimeError("APIError: worker model_name differs from host authorization")
        if temperature != expected["temperature"]:
            raise RuntimeError("APIError: worker temperature differs from host authorization")
        calls = int(self.ledger["usage"]["model_calls"])
        if calls >= int(self.auth["budgets"]["max_model_calls"]):
            raise RuntimeError("BudgetError: model call budget exhausted")
        if self.worker_contract == "message_only_v1":
            return self._complete_message_only(
                prompt,
                model_name=model_name,
                temperature=temperature,
                json_mode=json_mode,
            )
        if self.worker_contract == "message_only_v2":
            return self._complete_message_only_v2(
                prompt,
                model_name=model_name,
                temperature=temperature,
                json_mode=json_mode,
            )
        if json_mode is not None:
            raise RuntimeError(
                "APIError: json_mode is not part of the action_json_v1 worker contract"
            )
        agent_id = _prompt_header_int(prompt, "PYTHON_AGENT_ID")
        round_idx = _prompt_header_int(prompt, "PYTHON_ROUND")
        previous_state = _prompt_json_line(prompt, "PREVIOUS_STATE_JSON")
        delivered_inbox = _prompt_json_line(prompt, "DELIVERED_INBOX_JSON")
        if not isinstance(previous_state, dict) or not isinstance(delivered_inbox, list):
            raise RuntimeError("DataFlowError: malformed state or inbox prompt metadata")
        if previous_state != self.expected_states[agent_id]:
            raise RuntimeError(
                "DataFlowError: previous state was not retained from this agent's prior action"
            )
        _validate_canonical_prompt(
            prompt,
            agent_id=agent_id,
            round_idx=round_idx,
            previous_state=previous_state,
            delivered_inbox=delivered_inbox,
            local_prompt=str(self.auth["agent_local_prompts"][str(agent_id)]),
        )
        _validate_canaries(prompt, agent_id, self.auth.get("agent_canaries", {}))
        response = self.inner.complete(
            prompt,
            model_name=model_name,
            temperature=temperature,
        )
        usage = response.usage
        next_state, action_metadata = _interpret_worker_action(
            response.text,
            previous_state=previous_state,
            delivered_inbox=delivered_inbox,
            agent_id=agent_id,
            round_idx=round_idx,
            auth=self.auth,
        )
        self.expected_states[agent_id] = next_state
        self.ledger["usage"]["model_calls"] += int(usage.model_calls)
        self.ledger["usage"]["prompt_tokens"] += int(usage.prompt_tokens)
        self.ledger["usage"]["completion_tokens"] += int(usage.completion_tokens)
        self.ledger["calls"].append(
            {
                "agent_id": agent_id,
                "round": round_idx,
                "previous_state_keys": sorted(str(key) for key in previous_state),
                "previous_state_sha256": hashlib.sha256(
                    json.dumps(previous_state, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "delivered_inbox": [
                    _sanitize_message_envelope(item) for item in delivered_inbox
                ],
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "model_calls": int(usage.model_calls),
                "prompt_tokens": int(usage.prompt_tokens),
                "completion_tokens": int(usage.completion_tokens),
                **action_metadata,
            }
        )
        _write_ledger(self.path, self.ledger)
        if self.ledger["usage"]["completion_tokens"] > int(
            self.auth["budgets"]["max_completion_tokens"]
        ):
            raise RuntimeError("BudgetError: completion token budget exceeded")
        return response

    def _complete_message_only(
        self,
        prompt: str,
        *,
        model_name: str,
        temperature: float | None,
        json_mode: bool | None,
    ) -> LLMResponse:
        """Meter one message_only_v1 worker call against authoritative state.

        The generated program supplies only the Planner control and rendering;
        this wrapper independently simulates delivery, provenance merging and
        per-agent memory, and rejects any divergence fail-closed.
        """
        if json_mode is not False:
            raise RuntimeError(
                "APIError: message_only_v1 workers must be called with json_mode=False"
            )
        contract = _prompt_header_str(prompt, "PYTHON_WORKER_CONTRACT")
        if contract != "message_only_v1":
            raise RuntimeError(
                "DataFlowError: worker prompt declares a different worker contract"
            )
        n_agents = int(self.auth["n_agents"])
        max_rounds = int(self.auth["max_rounds"])
        agent_id = _prompt_header_int(prompt, "PYTHON_AGENT_ID")
        round_idx = _prompt_header_int(prompt, "PYTHON_ROUND")
        if not 0 <= agent_id < n_agents:
            raise RuntimeError("DataFlowError: worker agent id outside the agent range")
        if not 0 <= round_idx < max_rounds:
            raise RuntimeError("DataFlowError: worker round outside the round budget")
        if round_idx < self.max_round_seen:
            raise RuntimeError(
                "DataFlowError: worker call violates monotonic round ordering"
            )
        if (round_idx, agent_id) in self.called_pairs:
            raise RuntimeError(
                "DataFlowError: an agent was called more than once in the same round"
            )
        if agent_id in self.submitted_rounds:
            raise RuntimeError("DataFlowError: a submitted agent was called again")
        control = _prompt_json_line(prompt, "PYTHON_CONTROL_JSON")
        known_ids = _prompt_json_line(prompt, "KNOWN_SOURCE_IDS_JSON")
        previous_output = _prompt_json_line(prompt, "PREVIOUS_OUTPUT_JSON")
        delivered_inbox = _prompt_json_line(prompt, "DELIVERED_INBOX_JSON")
        if (
            not isinstance(control, dict)
            or not isinstance(known_ids, list)
            or not isinstance(previous_output, str)
            or not isinstance(delivered_inbox, list)
        ):
            raise RuntimeError(
                "DataFlowError: malformed control/state prompt metadata"
            )
        mode = str(control.get("mode") or "")
        raw_recipients = control.get("recipients")
        if set(control) != {"mode", "recipients"} or not isinstance(
            raw_recipients, list
        ):
            raise RuntimeError("DataFlowError: malformed planner control object")
        if mode not in _MESSAGE_ONLY_MODES:
            raise RuntimeError(
                "DataFlowError: planner control mode is not send/reflect/submit"
            )
        recipients = [int(value) for value in raw_recipients]
        if mode != "send" and recipients:
            raise RuntimeError("DataFlowError: recipients require send mode")
        if len(set(recipients)) != len(recipients):
            raise RuntimeError("DataFlowError: duplicate recipients")
        for recipient in recipients:
            if recipient < 0 or recipient >= n_agents or recipient == agent_id:
                raise RuntimeError(
                    "DataFlowError: recipient outside the agent range"
                )
        if mode == "send" and self.total_messages + len(recipients) > int(
            self.auth["budgets"]["max_messages"]
        ):
            raise RuntimeError("BudgetError: message budget exhausted")
        # Authoritative delivery simulation: merge every envelope due at or
        # before this round (idle rounds merge provenance without a call),
        # and require the prompt inbox to equal exactly this round's batch.
        due_now: list[dict[str, Any]] = []
        for envelope in self.pending_envelopes:
            if envelope["dst"] != agent_id or envelope["merged"]:
                continue
            if int(envelope["round_delivered"]) > round_idx:
                continue
            envelope["merged"] = True
            self.known_sources[agent_id].update(
                int(value) for value in envelope["source_ids"]
            )
            if int(envelope["round_delivered"]) == round_idx:
                due_now.append(envelope)
        expected_inbox = sorted(
            (
                json.dumps(_public_envelope(item), sort_keys=True)
                for item in due_now
            ),
        )
        actual_inbox = sorted(
            json.dumps(_public_envelope(item), sort_keys=True)
            for item in delivered_inbox
        )
        if actual_inbox != expected_inbox:
            raise RuntimeError(
                "DataFlowError: worker inbox does not match runtime deliveries"
            )
        if list(known_ids) != sorted(self.known_sources[agent_id]):
            raise RuntimeError(
                "DataFlowError: prompt source ids differ from the runtime provenance"
            )
        if previous_output != self.previous_outputs[agent_id]:
            raise RuntimeError(
                "DataFlowError: previous output was not retained by the runtime rule"
            )
        instruction = (
            MESSAGE_ONLY_SUBMIT_INSTRUCTION
            if mode == "submit"
            else MESSAGE_ONLY_MESSAGE_INSTRUCTION
        )
        local_prompt = str(self.auth["agent_local_prompts"][str(agent_id)])
        expected_prompt = (
            "PYTHON_WORKER_CONTRACT:message_only_v1\n"
            f"PYTHON_AGENT_ID:{agent_id}\n"
            f"PYTHON_ROUND:{round_idx}\n"
            "PYTHON_CONTROL_JSON:"
            + json.dumps(control, sort_keys=True)
            + "\nKNOWN_SOURCE_IDS_JSON:"
            + json.dumps(known_ids)
            + "\nPREVIOUS_OUTPUT_JSON:"
            + json.dumps(previous_output)
            + "\nDELIVERED_INBOX_JSON:"
            + json.dumps(delivered_inbox, sort_keys=True)
            + "\n"
            + instruction
            + "LOCAL_PROMPT:\n"
            + local_prompt
        )
        if prompt != expected_prompt:
            raise RuntimeError(
                "DataFlowError: worker prompt differs from the canonical "
                "message_only form"
            )
        _validate_canaries(prompt, agent_id, self.auth.get("agent_canaries", {}))
        response = self.inner.complete(
            prompt,
            model_name=model_name,
            temperature=temperature,
            json_mode=False,
        )
        usage = response.usage
        worker_output = str(response.text).strip()
        self.called_pairs.add((round_idx, agent_id))
        self.max_round_seen = round_idx
        if mode == "send":
            for recipient in recipients:
                self.pending_envelopes.append(
                    {
                        "round_sent": round_idx,
                        "round_delivered": round_idx + 1,
                        "src": agent_id,
                        "dst": recipient,
                        "source_ids": sorted(self.known_sources[agent_id]),
                        "body": worker_output,
                        "merged": False,
                    }
                )
            self.total_messages += len(recipients)
        if mode in {"send", "reflect"}:
            self.previous_outputs[agent_id] = worker_output
        if mode == "submit":
            self.submitted_rounds[agent_id] = round_idx
        self.ledger["usage"]["model_calls"] += int(usage.model_calls)
        self.ledger["usage"]["prompt_tokens"] += int(usage.prompt_tokens)
        self.ledger["usage"]["completion_tokens"] += int(usage.completion_tokens)
        self.ledger["calls"].append(
            {
                "agent_id": agent_id,
                "round": round_idx,
                "mode": mode,
                "recipients": recipients,
                "known_source_ids": sorted(self.known_sources[agent_id]),
                "delivered_inbox": [
                    _sanitize_message_envelope(item) for item in delivered_inbox
                ],
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "worker_output_sha256": _value_sha256(worker_output),
                "model_calls": int(usage.model_calls),
                "prompt_tokens": int(usage.prompt_tokens),
                "completion_tokens": int(usage.completion_tokens),
            }
        )
        _write_ledger(self.path, self.ledger)
        if self.ledger["usage"]["completion_tokens"] > int(
            self.auth["budgets"]["max_completion_tokens"]
        ):
            raise RuntimeError("BudgetError: completion token budget exceeded")
        return response

    def _prepare_submit_barrier(self, submit_round: int) -> None:
        """Freeze every agent's post-communication view before any submit call."""
        n_agents = int(self.auth["n_agents"])
        if self.auth["information_goal"] == "all_agents":
            expected_submit_ids = list(range(n_agents))
        else:
            expected_submit_ids = [int(self.auth["selected_primary"])]
        remaining_calls = int(self.auth["budgets"]["max_model_calls"]) - int(
            self.ledger["usage"]["model_calls"]
        )
        if remaining_calls < len(expected_submit_ids):
            raise RuntimeError(
                "BudgetError: synchronized submit call budget exhausted before barrier"
            )
        remaining_tokens = int(
            self.auth["budgets"]["max_completion_tokens"]
        ) - int(self.ledger["usage"]["completion_tokens"])
        if remaining_tokens < len(expected_submit_ids):
            raise RuntimeError(
                "BudgetError: synchronized submit token budget exhausted before barrier"
            )

        snapshot_fingerprint: dict[str, Any] = {}
        for agent_id in range(n_agents):
            due_at_barrier: list[dict[str, Any]] = []
            for envelope in self.pending_envelopes:
                if envelope["dst"] != agent_id or envelope["merged"]:
                    continue
                if int(envelope["round_delivered"]) > submit_round:
                    continue
                envelope["merged"] = True
                self.known_sources[agent_id].update(
                    int(value) for value in envelope["source_ids"]
                )
                if int(envelope["round_delivered"]) == submit_round:
                    due_at_barrier.append(envelope)
            public_inbox = [_public_envelope(item) for item in due_at_barrier]
            self.frozen_barrier_states[agent_id] = {
                "previous_output": self.previous_outputs[agent_id],
                "source_ids": sorted(self.known_sources[agent_id]),
            }
            self.frozen_barrier_inboxes[agent_id] = public_inbox
            snapshot_fingerprint[str(agent_id)] = {
                "previous_output_sha256": _value_sha256(
                    self.previous_outputs[agent_id]
                ),
                "known_source_ids": sorted(self.known_sources[agent_id]),
                "delivered_inbox": [
                    _sanitize_message_envelope(item) for item in public_inbox
                ],
            }
        self.ledger["submit_barrier"] = {
            "enabled": True,
            "worker_contract": "message_only_v2",
            "information_goal": str(self.auth["information_goal"]),
            "submit_round": submit_round,
            "expected_agent_ids": expected_submit_ids,
            "observed_agent_ids": [],
            "synchronized": False,
            "final_snapshot_sha256": _value_sha256(snapshot_fingerprint),
            "answer_format": "single_json_value",
            "parser": "json.loads_whole_response",
        }
        _write_ledger(self.path, self.ledger)

    def _complete_message_only_v2(
        self,
        prompt: str,
        *,
        model_name: str,
        temperature: float | None,
        json_mode: bool | None,
    ) -> LLMResponse:
        """Enforce communication-only planning and one synchronized submit."""
        if json_mode is not False:
            raise RuntimeError(
                "APIError: message_only_v2 workers must be called with json_mode=False"
            )
        contract = _prompt_header_str(prompt, "PYTHON_WORKER_CONTRACT")
        if contract != "message_only_v2":
            raise RuntimeError(
                "DataFlowError: worker prompt declares a different worker contract"
            )
        n_agents = int(self.auth["n_agents"])
        max_rounds = int(self.auth["max_rounds"])
        agent_id = _prompt_header_int(prompt, "PYTHON_AGENT_ID")
        round_idx = _prompt_header_int(prompt, "PYTHON_ROUND")
        submit_round = _prompt_header_int(prompt, "PYTHON_SUBMIT_ROUND")
        if submit_round < 0 or submit_round >= max_rounds:
            raise RuntimeError(
                "DataFlowError: submit barrier is outside the round budget"
            )
        if self.declared_submit_round is None:
            self.declared_submit_round = submit_round
        elif self.declared_submit_round != submit_round:
            raise RuntimeError(
                "DataFlowError: inconsistent PYTHON_SUBMIT_ROUND declaration"
            )
        if not 0 <= agent_id < n_agents:
            raise RuntimeError("DataFlowError: worker agent id outside the agent range")
        if not 0 <= round_idx < max_rounds:
            raise RuntimeError("DataFlowError: worker round outside the round budget")
        if round_idx < self.max_round_seen:
            raise RuntimeError(
                "DataFlowError: worker call violates monotonic round ordering"
            )
        if (round_idx, agent_id) in self.called_pairs:
            raise RuntimeError(
                "DataFlowError: an agent was called more than once in the same round"
            )
        if agent_id in self.submitted_rounds:
            raise RuntimeError("DataFlowError: a submitted agent was called again")

        control = _prompt_json_line(prompt, "PYTHON_CONTROL_JSON")
        known_ids = _prompt_json_line(prompt, "KNOWN_SOURCE_IDS_JSON")
        previous_output = _prompt_json_line(prompt, "PREVIOUS_OUTPUT_JSON")
        delivered_inbox = _prompt_json_line(prompt, "DELIVERED_INBOX_JSON")
        if (
            not isinstance(control, dict)
            or not isinstance(known_ids, list)
            or not isinstance(previous_output, str)
            or not isinstance(delivered_inbox, list)
        ):
            raise RuntimeError(
                "DataFlowError: malformed control/state prompt metadata"
            )
        mode = str(control.get("mode") or "")
        raw_recipients = control.get("recipients")
        if set(control) != {"mode", "recipients"} or not isinstance(
            raw_recipients, list
        ):
            raise RuntimeError("DataFlowError: malformed planner control object")
        if mode not in _MESSAGE_ONLY_V2_MODES:
            raise RuntimeError(
                "DataFlowError: planner control mode is not send/reflect/submit"
            )
        recipients = [int(value) for value in raw_recipients]
        if mode != "send" and recipients:
            raise RuntimeError("DataFlowError: recipients require send mode")
        if len(set(recipients)) != len(recipients):
            raise RuntimeError("DataFlowError: duplicate recipients")
        for recipient in recipients:
            if recipient < 0 or recipient >= n_agents or recipient == agent_id:
                raise RuntimeError(
                    "DataFlowError: recipient outside the agent range"
                )
        if mode == "submit":
            if round_idx != submit_round:
                raise RuntimeError(
                    "DataFlowError: submit is allowed only at the synchronized barrier"
                )
            expected_submit_ids = (
                list(range(n_agents))
                if self.auth["information_goal"] == "all_agents"
                else [int(self.auth["selected_primary"])]
            )
            if agent_id not in expected_submit_ids:
                raise RuntimeError(
                    "DataFlowError: agent is not a required barrier submitter"
                )
            if not self.frozen_barrier_states:
                self._prepare_submit_barrier(submit_round)
            expected_state = self.frozen_barrier_states[agent_id]
            expected_inbox_items = self.frozen_barrier_inboxes[agent_id]
        else:
            if round_idx >= submit_round:
                raise RuntimeError(
                    "DataFlowError: communication is forbidden at the submit barrier"
                )
            if mode == "send" and self.total_messages + len(recipients) > int(
                self.auth["budgets"]["max_messages"]
            ):
                raise RuntimeError("BudgetError: message budget exhausted")
            due_now: list[dict[str, Any]] = []
            for envelope in self.pending_envelopes:
                if envelope["dst"] != agent_id or envelope["merged"]:
                    continue
                if int(envelope["round_delivered"]) > round_idx:
                    continue
                envelope["merged"] = True
                self.known_sources[agent_id].update(
                    int(value) for value in envelope["source_ids"]
                )
                if int(envelope["round_delivered"]) == round_idx:
                    due_now.append(envelope)
            expected_state = {
                "previous_output": self.previous_outputs[agent_id],
                "source_ids": sorted(self.known_sources[agent_id]),
            }
            expected_inbox_items = [_public_envelope(item) for item in due_now]

        expected_inbox = sorted(
            json.dumps(_public_envelope(item), sort_keys=True)
            for item in expected_inbox_items
        )
        actual_inbox = sorted(
            json.dumps(_public_envelope(item), sort_keys=True)
            for item in delivered_inbox
        )
        if actual_inbox != expected_inbox:
            raise RuntimeError(
                "DataFlowError: worker inbox does not match runtime deliveries"
            )
        if list(known_ids) != list(expected_state["source_ids"]):
            raise RuntimeError(
                "DataFlowError: prompt source ids differ from runtime provenance"
            )
        if previous_output != expected_state["previous_output"]:
            raise RuntimeError(
                "DataFlowError: previous output differs from the frozen runtime state"
            )
        instruction = (
            MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION
            if mode == "submit"
            else MESSAGE_ONLY_V2_MESSAGE_INSTRUCTION
        )
        if mode == "submit":
            private_prompt = str(
                self.auth["agent_submit_prompts"][str(agent_id)]
            )
            prompt_header = "SUBMIT_PROMPT:\n"
        else:
            private_prompt = str(
                self.auth["agent_communication_prompts"][str(agent_id)]
            )
            prompt_header = "COMMUNICATION_PROMPT:\n"
        expected_prompt = (
            "PYTHON_WORKER_CONTRACT:message_only_v2\n"
            f"PYTHON_AGENT_ID:{agent_id}\n"
            f"PYTHON_ROUND:{round_idx}\n"
            f"PYTHON_SUBMIT_ROUND:{submit_round}\n"
            "PYTHON_CONTROL_JSON:"
            + json.dumps(control, sort_keys=True)
            + "\nKNOWN_SOURCE_IDS_JSON:"
            + json.dumps(known_ids)
            + "\nPREVIOUS_OUTPUT_JSON:"
            + json.dumps(previous_output)
            + "\nDELIVERED_INBOX_JSON:"
            + json.dumps(delivered_inbox, sort_keys=True)
            + "\n"
            + prompt_header
            + private_prompt
            + "\n"
            + instruction
        )
        if prompt != expected_prompt:
            raise RuntimeError(
                "DataFlowError: worker prompt differs from canonical message_only_v2 form"
            )
        _validate_canaries(prompt, agent_id, self.auth.get("agent_canaries", {}))
        response = self.inner.complete(
            prompt,
            model_name=model_name,
            temperature=temperature,
            json_mode=False,
        )
        usage = response.usage
        worker_output = str(response.text).strip()
        answer_value: Any = None
        answer_format_valid = True
        if mode == "submit":
            try:
                answer_value = json.loads(
                    worker_output,
                    parse_constant=_reject_nonfinite_json,
                )
            except (json.JSONDecodeError, ValueError):
                answer_format_valid = False

        self.called_pairs.add((round_idx, agent_id))
        self.max_round_seen = round_idx
        if mode == "send":
            for recipient in recipients:
                self.pending_envelopes.append(
                    {
                        "round_sent": round_idx,
                        "round_delivered": round_idx + 1,
                        "src": agent_id,
                        "dst": recipient,
                        "source_ids": sorted(self.known_sources[agent_id]),
                        "body": worker_output,
                        "merged": False,
                    }
                )
            self.total_messages += len(recipients)
        if mode in {"send", "reflect"}:
            self.previous_outputs[agent_id] = worker_output

        self.ledger["usage"]["model_calls"] += int(usage.model_calls)
        self.ledger["usage"]["prompt_tokens"] += int(usage.prompt_tokens)
        self.ledger["usage"]["completion_tokens"] += int(usage.completion_tokens)
        call_record = {
            "agent_id": agent_id,
            "round": round_idx,
            "submit_round": submit_round,
            "mode": mode,
            "recipients": recipients,
            "known_source_ids": list(expected_state["source_ids"]),
            "delivered_inbox": [
                _sanitize_message_envelope(item) for item in delivered_inbox
            ],
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "worker_output_sha256": _value_sha256(worker_output),
            "answer_format_valid": answer_format_valid,
            "model_calls": int(usage.model_calls),
            "prompt_tokens": int(usage.prompt_tokens),
            "completion_tokens": int(usage.completion_tokens),
        }
        submit_budget_error = False
        if mode == "submit" and answer_format_valid:
            call_record["answer_sha256"] = _value_sha256(answer_value)
            barrier = self.ledger["submit_barrier"]
            candidate_count = len(self.pending_barrier_submissions) + 1
            remaining_submitters = len(barrier["expected_agent_ids"]) - candidate_count
            completion_remaining = int(
                self.auth["budgets"]["max_completion_tokens"]
            ) - int(self.ledger["usage"]["completion_tokens"])
            if completion_remaining < remaining_submitters:
                submit_budget_error = True
            else:
                self.pending_barrier_submissions[agent_id] = round_idx
                if sorted(self.pending_barrier_submissions) == barrier[
                    "expected_agent_ids"
                ]:
                    self.submitted_rounds = dict(
                        self.pending_barrier_submissions
                    )
                    barrier["observed_agent_ids"] = sorted(
                        self.submitted_rounds
                    )
                    barrier["synchronized"] = (
                        len(set(self.submitted_rounds.values())) == 1
                    )
        self.ledger["calls"].append(call_record)
        _write_ledger(self.path, self.ledger)
        if self.ledger["usage"]["completion_tokens"] > int(
            self.auth["budgets"]["max_completion_tokens"]
        ):
            raise RuntimeError("BudgetError: completion token budget exceeded")
        if submit_budget_error:
            raise RuntimeError(
                "BudgetError: submit response left insufficient token budget "
                "for the complete barrier"
            )
        if mode == "submit" and not answer_format_valid:
            raise RuntimeError(
                "AnswerFormatError: submit output must be exactly one valid JSON value"
            )
        return response


def _prompt_header_str(prompt: str, header: str) -> str:
    marker = f"{header}:"
    if marker not in prompt:
        raise RuntimeError(f"DataFlowError: worker prompt lacks {header}")
    return prompt.split(marker, 1)[1].splitlines()[0].strip()


def _public_envelope(item: Any) -> dict[str, Any]:
    """Project one envelope onto the exact fields a recipient may see."""
    if not isinstance(item, dict):
        raise RuntimeError("DataFlowError: inbox entry is not an object")
    try:
        return {
            "round_sent": int(item["round_sent"]),
            "round_delivered": int(item["round_delivered"]),
            "src": int(item["src"]),
            "dst": int(item["dst"]),
            "source_ids": sorted(int(value) for value in item["source_ids"]),
            "body": str(item["body"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("DataFlowError: malformed inbox envelope") from exc


def _prompt_header_int(prompt: str, header: str) -> int:
    marker = f"{header}:"
    if marker not in prompt:
        raise RuntimeError(f"DataFlowError: worker prompt lacks {header}")
    raw = prompt.split(marker, 1)[1].splitlines()[0].strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"DataFlowError: invalid {header}") from exc


def _prompt_json_line(prompt: str, header: str) -> Any:
    marker = f"{header}:"
    if marker not in prompt:
        raise RuntimeError(f"DataFlowError: worker prompt lacks {header}")
    raw = prompt.split(marker, 1)[1].splitlines()[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DataFlowError: invalid {header}") from exc


def _validate_canonical_prompt(
    prompt: str,
    *,
    agent_id: int,
    round_idx: int,
    previous_state: dict[str, Any],
    delivered_inbox: list[Any],
    local_prompt: str,
) -> None:
    expected = (
        f"PYTHON_AGENT_ID:{agent_id}\n"
        f"PYTHON_ROUND:{round_idx}\n"
        + _ACTION_INSTRUCTION
        + "PREVIOUS_STATE_JSON:"
        + json.dumps(previous_state)
        + "\nDELIVERED_INBOX_JSON:"
        + json.dumps(delivered_inbox)
        + "\nLOCAL_PROMPT:\n"
        + local_prompt
    )
    if prompt != expected:
        raise RuntimeError(
            "DataFlowError: worker prompt differs from the canonical local/state/inbox form"
        )


def _interpret_worker_action(
    response_text: str,
    *,
    previous_state: dict[str, Any],
    delivered_inbox: list[Any],
    agent_id: int,
    round_idx: int,
    auth: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        action = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OutputSchemaError: worker action is not JSON") from exc
    if not isinstance(action, dict):
        raise RuntimeError("OutputSchemaError: worker action must be an object")
    known_sources = set(previous_state.get("source_ids", [agent_id]))
    known_sources.add(agent_id)
    for delivered in delivered_inbox:
        if isinstance(delivered, dict):
            known_sources.update(int(value) for value in delivered.get("source_ids", []))
    if "should_send" in action:
        action_explicit = True
        update = action.get("state", {})
        raw_sources = action.get("source_ids", [])
        raw_recipients = action.get("recipients", [])
        if (
            not isinstance(update, dict)
            or not isinstance(raw_sources, list)
            or not isinstance(raw_recipients, list)
        ):
            raise RuntimeError("OutputSchemaError: invalid worker state or provenance")
        source_ids = sorted(int(value) for value in raw_sources)
        recipients = [int(value) for value in raw_recipients]
        if (
            len(set(source_ids)) != len(source_ids)
            or agent_id not in source_ids
            or not set(source_ids) <= known_sources
        ):
            raise RuntimeError("DataFlowError: invalid worker source provenance")
        if (
            len(set(recipients)) != len(recipients)
            or any(
                recipient < 0
                or recipient >= int(auth["n_agents"])
                or recipient == agent_id
                for recipient in recipients
            )
        ):
            raise RuntimeError("DataFlowError: invalid worker recipients")
        should_send = bool(action.get("should_send", False))
        submit = bool(action.get("submit", False))
        message = action.get("message")
        answer = action.get("answer")
    else:
        action_explicit = False
        update = action
        source_ids = sorted(known_sources)
        if auth["information_goal"] == "sink":
            recipients = (
                [int(auth["selected_primary"])]
                if agent_id != int(auth["selected_primary"])
                else []
            )
        else:
            recipients = (
                [(agent_id + 1) % int(auth["n_agents"])]
                if int(auth["n_agents"]) > 1
                else []
            )
        should_send = bool(recipients)
        if (
            auth["information_goal"] == "all_agents"
            and round_idx == 0
            and agent_id == int(auth["n_agents"]) - 1
        ):
            should_send = False
        submit = round_idx + 1 >= int(auth["max_rounds"])
        message = action
        answer = _fallback_answer(action)
    next_state = dict(previous_state)
    next_state.update(update)
    next_state["source_ids"] = sorted(source_ids)
    metadata = {
        "action_explicit": action_explicit,
        "action_should_send": should_send,
        "action_recipients": recipients,
        "action_source_ids": source_ids,
        "action_message_sha256": _value_sha256(message),
        "action_submit": submit,
        "action_answer_sha256": _value_sha256(answer),
    }
    return next_state, metadata


def _fallback_answer(action: dict[str, Any]) -> Any:
    answer = action.get("answer")
    if answer is None:
        structured = action.get("structured_state")
        if isinstance(structured, dict):
            answer = structured.get("answer")
    if answer is None:
        key = action.get("consensus_key")
        if key not in (None, "", "UNKNOWN"):
            answer = key
    return answer


def _sanitize_message_envelope(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RuntimeError("DataFlowError: inbox entry is not an object")
    try:
        return {
            "round_sent": int(item["round_sent"]),
            "round_delivered": int(item["round_delivered"]),
            "src": int(item["src"]),
            "dst": int(item["dst"]),
            "source_ids": sorted(int(value) for value in item.get("source_ids", [])),
            "body_sha256": _value_sha256(item.get("body")),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("DataFlowError: malformed inbox envelope") from exc


def _value_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


def _validate_canaries(prompt: str, agent_id: int, canaries: dict[str, str]) -> None:
    if not canaries:
        return
    expected = canaries.get(str(agent_id))
    if expected is None or expected not in prompt:
        raise RuntimeError("DataFlowError: current agent canary is missing")
    for other_id, canary in canaries.items():
        if int(other_id) != agent_id and canary in prompt:
            raise RuntimeError("DataFlowError: another agent's local prompt leaked")


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--program", required=True)
    parser.add_argument("--auth", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    auth = json.loads(Path(args.auth).read_text(encoding="utf-8"))
    ledger_path = Path(args.ledger)
    ledger: dict[str, Any] = {
        "factory_calls": 0,
        "worker_contract": str(auth.get("worker_contract") or "action_json_v1"),
        "calls": [],
        "usage": {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
        "errors": [],
    }
    _write_ledger(ledger_path, ledger)

    def secure_factory(
        provider: str,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
        thinking_enabled: bool | None = None,
        timeout_s: float | None = None,
    ) -> _MeteredClient:
        del thinking_enabled, timeout_s
        expected = auth["worker_llm"]
        ledger["factory_calls"] += 1
        if ledger["factory_calls"] != 1:
            raise RuntimeError("APIError: create_llm_client called more than once")
        if provider != expected["provider"]:
            raise RuntimeError("APIError: provider differs from host authorization")
        if base_url != expected.get("base_url"):
            raise RuntimeError("APIError: base_url differs from host authorization")
        if api_key_env != expected.get("api_key_env"):
            raise RuntimeError("APIError: api_key_env differs from host authorization")
        inner = (
            _PythonSmokeClient()
            if provider == "fake"
            else _real_factory(
                provider,
                base_url=base_url,
                api_key_env=api_key_env,
            )
        )
        _write_ledger(ledger_path, ledger)
        return _MeteredClient(inner, auth, ledger, ledger_path)

    factory_module.create_llm_client = secure_factory
    sys.argv = [args.program]
    sys.stdout = _LimitedStdout(sys.stdout, int(auth["max_output_bytes"]))
    try:
        runpy.run_path(args.program, run_name="__main__")
    except BaseException as exc:
        ledger["errors"].append(
            {"type": type(exc).__name__, "message": str(exc)[:1000]}
        )
        _write_ledger(ledger_path, ledger)
        raise
    _write_ledger(ledger_path, ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
