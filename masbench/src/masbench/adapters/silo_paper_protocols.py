"""Clean first-party runner for the three SILO-BENCH paper transports.

The vendored benchmark engine cannot be called directly from QueenBee runs: it
uses a separate model client and its task files contain topology annotations that
the clean pipeline deliberately removes.  This runner preserves the paper tool
semantics while using masbench's sanitized task view and shared LLM client.

The transports are dynamic, not precompiled graphs:

* ``p2p``: an agent chooses each individual recipient;
* ``broadcast``: one outward action reaches every other agent;
* ``sfs``: agents coordinate through a round-delayed shared file store.

All actions are synchronous: information produced in round ``r`` can only be
observed in round ``r + 1``.  Every agent submits its own final answer.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Literal

from exp_graph.llm.base import LLMClient
from exp_graph.llm.parser import extract_json_object
from exp_graph.mas.information_flow import coverage_by_agent
from exp_graph.mas.leakage_audit import (
    FORBIDDEN_PROMPT_TOKENS,
    assert_prompt_clean,
)

from masbench.adapters.silo_paper_metrics import (
    evaluate_paper_submissions,
    paper_communication_density,
    paper_token_consumption,
)
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.core.task_bridge import private_expected_outputs
from masbench.core.task_view import public_task_view

PaperProtocol = Literal["p2p", "broadcast", "sfs"]
PAPER_PROTOCOL_ARMS: tuple[PaperProtocol, ...] = ("p2p", "broadcast", "sfs")

_ALIASES = {
    "p2p": "p2p",
    "msg": "p2p",
    "broadcast": "broadcast",
    "bp": "broadcast",
    "sfs": "sfs",
}

_COMMON_RULES = """
Return exactly one JSON object with an `actions` array and no markdown.
Actions are executed in order. `wait` and `submit_result` end the round, so put
all other actions before them. Information produced this round becomes visible
next round. Once submitted, you cannot act again. Every agent must independently
submit the correct answer; do not assume a leader will submit for you.
""".strip()

_TRANSPORT_DOCS: dict[PaperProtocol, str] = {
    "p2p": """
PAPER_PROTOCOL_NAME: p2p
Available tools:
- send_message(target_id: int, content: str): send to one other agent.
- receive_messages(): collect your unread messages from earlier rounds.
- wait(): end this round without submitting.
- submit_result(answer: any): submit your own final answer and stop.
Example shape:
{"actions":[{"tool":"receive_messages","parameters":{}},{"tool":"send_message","parameters":{"target_id":1,"content":"useful information"}},{"tool":"wait","parameters":{}}]}
""".strip(),
    "broadcast": """
PAPER_PROTOCOL_NAME: broadcast
Available tools:
- broadcast_message(content: str): one broadcast to every other agent.
- receive_messages(): collect unread broadcasts from earlier rounds.
- list_agents(): list the participating agent IDs.
- wait(): end this round without submitting.
- submit_result(answer: any): submit your own final answer and stop.
Example shape:
{"actions":[{"tool":"receive_messages","parameters":{}},{"tool":"broadcast_message","parameters":{"content":"useful information"}},{"tool":"wait","parameters":{}}]}
""".strip(),
    "sfs": """
PAPER_PROTOCOL_NAME: sfs
Available tools:
- list_files(prefix: str optional): list visible shared files.
- read_file(path: str): read one visible file.
- write_file(path: str, content: any): write a value visible next round.
- delete_file(path: str): delete a file starting next round.
- wait(): end this round without submitting.
- submit_result(answer: any): submit your own final answer and stop.
Example shape:
{"actions":[{"tool":"list_files","parameters":{}},{"tool":"read_file","parameters":{"path":"agent_0_data"}},{"tool":"wait","parameters":{}}]}
""".strip(),
}


def normalize_paper_protocol(protocol: str) -> PaperProtocol:
    try:
        return _ALIASES[str(protocol).strip().lower()]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError(
            f"unknown SILO paper protocol {protocol!r}; expected p2p, broadcast, or sfs"
        ) from exc


def _redact_untrusted_text(value: Any) -> Any:
    """Keep model-produced history from tripping the benchmark leak audit."""
    if isinstance(value, str):
        redacted = value
        for token in FORBIDDEN_PROMPT_TOKENS:
            redacted = re.sub(re.escape(token), "[REDACTED]", redacted, flags=re.I)
        return redacted
    if isinstance(value, list):
        return [_redact_untrusted_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_untrusted_text(item) for key, item in value.items()}
    return value


def build_paper_protocol_prompt(
    *,
    protocol: PaperProtocol,
    adapter: SiloProtocolAdapter,
    global_task: dict[str, Any],
    local_observation: dict[str, Any],
    round_idx: int,
    max_rounds: int,
    history: list[dict[str, Any]],
) -> str:
    """Build one audit-clean, paper-tool-compatible agent prompt."""
    agent_id = int(local_observation["agent_id"])
    state = {
        "agent_id": agent_id,
        "num_agents": int(local_observation["n_agents"]),
        "round": round_idx,
        "max_rounds": max_rounds,
        "final_round": round_idx >= max_rounds,
        "prior_tool_results": _redact_untrusted_text(history),
    }
    prompt = f"""You are agent {agent_id} in a SILO-BENCH multi-agent run.
Analyze the task, use only your private shard and information returned by tools,
coordinate economically, and make sure every agent can submit its own answer.

{_COMMON_RULES}

{_TRANSPORT_DOCS[protocol]}

TASK_FOR_AGENT:
{adapter.format_task_prompt_context(global_task, local_observation)}
PUBLIC_TASK_JSON:
{json.dumps(public_task_view(global_task), ensure_ascii=True, sort_keys=True)}

LOCAL_OBSERVATION_JSON:
{json.dumps(local_observation, ensure_ascii=True, sort_keys=True)}

ROUND_STATE_JSON:
{json.dumps(state, ensure_ascii=True, sort_keys=True)}

SILO_PROTOCOL_ACTION_JSON:
"""
    return assert_prompt_clean(
        prompt,
        context=f"SILO paper {protocol} agent={agent_id} round={round_idx}",
    )


def _parse_actions(text: str) -> list[dict[str, Any]]:
    payload = extract_json_object(text)
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        raise ValueError("paper protocol response must contain an actions array")
    actions: list[dict[str, Any]] = []
    for raw in raw_actions[:32]:
        if not isinstance(raw, dict) or not isinstance(raw.get("tool"), str):
            continue
        parameters = raw.get("parameters")
        actions.append(
            {
                "tool": raw["tool"].strip(),
                "parameters": parameters if isinstance(parameters, dict) else {},
            }
        )
    return actions


def _result(tool: str, value: Any) -> dict[str, Any]:
    return {"tool": tool, "result": value}


def run_silo_paper_protocol(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    protocol: str,
    llm_client: LLMClient,
) -> ScoreResult:
    """Run one clean SILO instance with one of the paper's three transports."""
    selected = normalize_paper_protocol(protocol)
    if instance.benchmark != "silo_bench":
        raise ValueError("SILO paper protocols only support silo_bench instances")
    if (cfg.silo_eval_mode or "sink") != "all_agents":
        raise ValueError(
            "SILO paper protocols require --silo-eval-mode all_agents because "
            "the paper grades every agent submission"
        )

    adapter = SiloProtocolAdapter(instance, information_goal="all_agents")
    global_task = adapter.build_global_task()
    observations = adapter.split_into_local_observations(global_task, instance.n_agents)
    n_agents = instance.n_agents
    max_rounds = max(1, int(cfg.max_rounds))

    histories: list[list[dict[str, Any]]] = [[] for _ in range(n_agents)]
    submitted = [False] * n_agents
    answers: list[Any] = [None] * n_agents
    submitted_rounds: list[int | None] = [None] * n_agents
    # Structural provenance only: source ids model which private shards could
    # have reached each agent through successful transport operations.  This is
    # deliberately independent of message text and does not alter paper S/P/C/D.
    knowledge: list[set[int]] = [{agent_id} for agent_id in range(n_agents)]

    messages: list[dict[str, Any]] = []
    broadcasts: list[dict[str, Any]] = []
    files: dict[str, dict[str, Any]] = {}
    outward_events = [0] * n_agents
    write_events = 0
    parse_errors = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_model_calls = 0
    rounds_executed = 0

    for round_idx in range(1, max_rounds + 1):
        rounds_executed = round_idx
        visible_files = copy.deepcopy(files)
        pending_file_ops: list[tuple[str, str, Any, int, list[int]]] = []

        for agent_id in range(n_agents):
            if submitted[agent_id]:
                continue
            prompt = build_paper_protocol_prompt(
                protocol=selected,
                adapter=adapter,
                global_task=global_task,
                local_observation=observations[agent_id],
                round_idx=round_idx,
                max_rounds=max_rounds,
                history=histories[agent_id],
            )
            response = llm_client.complete(
                prompt,
                model_name=cfg.model_name,
                temperature=cfg.temperature,
            )
            total_prompt_tokens += int(response.usage.prompt_tokens)
            total_completion_tokens += int(response.usage.completion_tokens)
            total_model_calls += int(response.usage.model_calls)

            parse_error: str | None = None
            try:
                actions = _parse_actions(response.text)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                actions = []
                parse_error = f"{type(exc).__name__}: {exc}"
                parse_errors += 1

            tool_results: list[dict[str, Any]] = []
            for action in actions:
                tool = action["tool"]
                params = action["parameters"]

                if selected == "p2p" and tool == "send_message":
                    try:
                        target = int(params.get("target_id", -1))
                    except (TypeError, ValueError):
                        target = -1
                    if target == agent_id or not 0 <= target < n_agents:
                        tool_results.append(
                            _result(tool, {"success": False, "message": "invalid target_id"})
                        )
                    else:
                        messages.append(
                            {
                                "sender_id": agent_id,
                                "recipient_id": target,
                                "content": str(params.get("content", "")),
                                "source_ids": sorted(knowledge[agent_id]),
                                "round": round_idx,
                                "read": False,
                            }
                        )
                        outward_events[agent_id] += 1
                        tool_results.append(_result(tool, {"success": True}))

                elif selected in {"p2p", "broadcast"} and tool == "receive_messages":
                    received: list[dict[str, Any]] = []
                    source = messages if selected == "p2p" else broadcasts
                    for message in source:
                        eligible = (
                            message["round"] < round_idx
                            and not message.get("read_by", {}).get(agent_id, False)
                        )
                        if selected == "p2p":
                            eligible = eligible and message["recipient_id"] == agent_id
                        else:
                            eligible = eligible and message["sender_id"] != agent_id
                        if not eligible:
                            continue
                        if selected == "p2p":
                            message["read"] = True
                        message.setdefault("read_by", {})[agent_id] = True
                        knowledge[agent_id].update(message.get("source_ids", []))
                        received.append(
                            {
                                "from": message["sender_id"],
                                "content": message["content"],
                                "round": message["round"],
                            }
                        )
                    tool_results.append(_result(tool, {"messages": received}))

                elif selected == "broadcast" and tool == "broadcast_message":
                    broadcasts.append(
                        {
                            "sender_id": agent_id,
                            "content": str(params.get("content", "")),
                            "source_ids": sorted(knowledge[agent_id]),
                            "round": round_idx,
                            "read_by": {},
                        }
                    )
                    # The paper/vendor count one broadcast action as one outward
                    # message, not N-1 synthetic pairwise messages.
                    outward_events[agent_id] += 1
                    tool_results.append(_result(tool, {"success": True}))

                elif selected == "broadcast" and tool == "list_agents":
                    tool_results.append(
                        _result(tool, {"agent_ids": list(range(n_agents)), "total": n_agents})
                    )

                elif selected == "sfs" and tool == "list_files":
                    prefix = str(params.get("prefix", ""))
                    listing = [
                        {
                            "path": path,
                            "modified_by": entry["writer_id"],
                            "modified_at_round": entry["round"],
                        }
                        for path, entry in sorted(visible_files.items())
                        if path.startswith(prefix)
                    ]
                    tool_results.append(_result(tool, {"files": listing}))

                elif selected == "sfs" and tool == "read_file":
                    path = str(params.get("path", ""))
                    entry = visible_files.get(path)
                    if entry is None:
                        tool_results.append(_result(tool, {"success": False}))
                    else:
                        writer_id = int(entry["writer_id"])
                        if writer_id != agent_id:
                            # Paper Eq. 5 defines SFS m_i by successful reads of
                            # files written by i, preserving actual transfer.
                            outward_events[writer_id] += 1
                        knowledge[agent_id].update(entry.get("source_ids", []))
                        tool_results.append(
                            _result(
                                tool,
                                {
                                    "success": True,
                                    "content": entry["content"],
                                    "metadata": {
                                        "modified_by": writer_id,
                                        "modified_at_round": entry["round"],
                                    },
                                },
                            )
                        )

                elif selected == "sfs" and tool == "write_file":
                    path = str(params.get("path", "")).strip()[:200]
                    if not path:
                        tool_results.append(_result(tool, {"success": False}))
                    else:
                        pending_file_ops.append(
                            (
                                "write",
                                path,
                                params.get("content"),
                                agent_id,
                                sorted(knowledge[agent_id]),
                            )
                        )
                        write_events += 1
                        tool_results.append(_result(tool, {"success": True}))

                elif selected == "sfs" and tool == "delete_file":
                    path = str(params.get("path", "")).strip()[:200]
                    pending_file_ops.append(("delete", path, None, agent_id, []))
                    tool_results.append(
                        _result(tool, {"success": path in visible_files})
                    )

                elif tool == "wait":
                    tool_results.append(_result(tool, {"status": "waiting"}))
                    break

                elif tool == "submit_result":
                    answers[agent_id] = params.get("answer")
                    submitted[agent_id] = True
                    submitted_rounds[agent_id] = round_idx
                    tool_results.append(_result(tool, {"status": "submitted"}))
                    break

                else:
                    tool_results.append(
                        _result(tool, {"success": False, "error": "tool unavailable"})
                    )

            if not actions:
                tool_results.append(
                    _result(
                        "system",
                        {
                            "error": parse_error or "no valid actions",
                            "hint": "Return a JSON object containing an actions array.",
                        },
                    )
                )
            histories[agent_id].append(
                {
                    "round": round_idx,
                    "tool_results": tool_results,
                }
            )

        for operation, path, content, writer_id, source_ids in pending_file_ops:
            if operation == "delete":
                files.pop(path, None)
            else:
                files[path] = {
                    "content": content,
                    "writer_id": writer_id,
                    "round": round_idx,
                    "source_ids": source_ids,
                }

        if all(submitted):
            break

    expected_outputs = private_expected_outputs(global_task)
    if len(expected_outputs) != n_agents:
        expected_outputs = [instance.ground_truth for _ in range(n_agents)]
    paper = evaluate_paper_submissions(
        case_id=instance.case_id,
        answers=answers,
        expected_outputs=expected_outputs,
        submitted_rounds=submitted_rounds,
    )
    communication_events = sum(outward_events)
    paper_c = paper_token_consumption(total_completion_tokens, rounds_executed)
    paper_d = paper_communication_density(communication_events, n_agents)
    success = n_agents > 0 and float(paper["paper_S"]) == 1.0
    information_coverage = coverage_by_agent(knowledge)

    extra = {
        "case_id": instance.case_id,
        "information_goal": "all_agents",
        "silo_eval_mode": "all_agents",
        "paper_protocol": selected,
        "topology": f"paper_{selected}",
        "fixed": True,
        "provenance": "paper_protocol_fixed",
        "paper_S": float(paper["paper_S"]),
        "paper_P": float(paper["paper_P"]),
        "paper_C": paper_c,
        "paper_D": paper_d,
        "agent_success_rate": float(paper["paper_S"]),
        "all_agents_exact": success,
        "communication_density": paper_d,
        "per_agent_submissions": paper["per_agent_submissions"],
        "per_agent_answers": paper["per_agent_answers"],
        "per_agent_correct": paper["per_agent_correct"],
        "per_agent_partial": paper["per_agent_partial"],
        "information_coverage_by_agent": information_coverage,
        "mean_information_coverage": (
            sum(information_coverage) / len(information_coverage)
            if information_coverage
            else 0.0
        ),
        "min_information_coverage": (
            min(information_coverage) if information_coverage else 0.0
        ),
        "all_agents_full_information": bool(
            information_coverage and min(information_coverage) >= 1.0
        ),
        "rounds_executed": rounds_executed,
        "all_submitted": all(submitted),
        "outward_events_by_agent": outward_events,
        "sfs_write_events": write_events if selected == "sfs" else None,
        "parse_errors": parse_errors,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "paper_metric_notes": {
            "C": "output tokens divided by executed rounds",
            "D": (
                "successful cross-agent file reads / N(N-1)"
                if selected == "sfs"
                else "outward transport actions / N(N-1)"
            ),
        },
    }
    return ScoreResult(
        success=success,
        partial=float(paper["paper_P"]),
        n_messages=communication_events,
        n_model_calls=total_model_calls,
        tokens=total_prompt_tokens + total_completion_tokens,
        final_answer=answers,
        extra=extra,
    )
