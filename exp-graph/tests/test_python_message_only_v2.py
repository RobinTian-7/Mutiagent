"""Offline contract tests for synchronized message_only_v2 submission."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.python_code import (
    DEFAULT_MESSAGE_ONLY_PROGRAM,
    DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
    DEFAULT_PYTHON_PROGRAM,
    MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION,
    PythonCodeError,
    PythonExecutionPayload,
    default_python_program,
    validate_python_source,
)
from exp_graph.mas.python_code_generation import (
    PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION,
    _replay_source,
    build_python_architect_prompt,
    build_python_architect_scaffold,
    build_python_repair_prompt,
)
from exp_graph.mas.python_code_runner import CodeProcessRunner
from exp_graph.mas.python_worker_bootstrap import _MeteredClient, _value_sha256
from exp_graph.mas.schemas import (
    MASRuntimeConfig,
    ObjectiveSpec,
    PlannerRequest,
    PythonSkillPayload,
    SkillCard,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.skill_payloads import merge_mode_payload


def _payload(
    *,
    goal: str = "all_agents",
    n_agents: int = 2,
    max_rounds: int = 2,
    max_model_calls: int = 20,
    max_completion_tokens: int = 4000,
    max_messages: int = 30,
) -> dict:
    return {
        "execution_contract_version": "python_mas_v1",
        "worker_contract": "message_only_v2",
        "task_description": "Synthetic offline barrier check.",
        "information_goal": goal,
        "selected_primary": 0,
        "n_agents": n_agents,
        "max_rounds": max_rounds,
        "budgets": {
            "max_model_calls": max_model_calls,
            "max_completion_tokens": max_completion_tokens,
            "max_messages": max_messages,
        },
        "worker_llm": {
            "provider": "fake",
            "model_name": "fake",
            "base_url": None,
            "api_key_env": None,
            "temperature": 0.0,
        },
        "agents": [
            {
                "agent_id": agent_id,
                "communication_prompt": f"COMMUNICATION_PRIVATE_{agent_id}",
                "submit_prompt": (
                    f"SUBMIT_PRIVATE_{agent_id}\n"
                    "PUBLIC_ANSWER_REQUIREMENT:\nReturn one JSON string."
                ),
            }
            for agent_id in range(n_agents)
        ],
    }


def _request(worker_contract: str = "message_only_v2") -> PlannerRequest:
    return PlannerRequest(
        task_family="silo",
        n_agents=2,
        objective=ObjectiveSpec.from_name("balanced"),
        planner_mode="python_generate",
        information_goal="all_agents",
        provenance_allowlist=["llm_generated_python", "skill_replay"],
        python_worker_contract=worker_contract,
    )


def _runtime(worker_contract: str = "message_only_v2") -> MASRuntimeConfig:
    return MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        python_max_rounds=2,
        information_goal="all_agents",
        python_worker_contract=worker_contract,
    )


class _ScriptedWorker:
    def __init__(self, texts: list[str], *, completion_tokens: int = 1) -> None:
        self.texts = list(texts)
        self.completion_tokens = completion_tokens
        self.prompts: list[str] = []
        self.json_modes: list[bool] = []

    def complete(self, prompt, model_name, temperature=None, json_mode=True):
        del model_name, temperature
        self.prompts.append(prompt)
        self.json_modes.append(json_mode)
        text = self.texts.pop(0)
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=2,
                completion_tokens=self.completion_tokens,
            ),
        )


def _auth(
    *,
    n_agents: int = 1,
    max_rounds: int = 1,
    max_model_calls: int = 8,
    max_completion_tokens: int = 100,
    goal: str = "all_agents",
) -> dict:
    return {
        "worker_llm": {
            "provider": "fake",
            "model_name": "fake",
            "base_url": None,
            "api_key_env": None,
            "temperature": 0.0,
        },
        "worker_contract": "message_only_v2",
        "budgets": {
            "max_model_calls": max_model_calls,
            "max_completion_tokens": max_completion_tokens,
            "max_messages": 20,
        },
        "agent_canaries": {},
        "max_output_bytes": 100_000,
        "n_agents": n_agents,
        "information_goal": goal,
        "selected_primary": 0,
        "max_rounds": max_rounds,
        "agent_communication_prompts": {
            str(agent_id): f"communication prompt {agent_id}"
            for agent_id in range(n_agents)
        },
        "agent_submit_prompts": {
            str(agent_id): (
                f"submit prompt {agent_id}\n"
                "PUBLIC_ANSWER_REQUIREMENT:\nReturn one JSON value."
            )
            for agent_id in range(n_agents)
        },
    }


def _metered_client(
    tmp_path: Path,
    inner: _ScriptedWorker,
    auth: dict,
) -> tuple[_MeteredClient, dict]:
    ledger = {
        "factory_calls": 1,
        "worker_contract": "message_only_v2",
        "calls": [],
        "usage": {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
        "errors": [],
    }
    return _MeteredClient(inner, auth, ledger, tmp_path / "ledger.json"), ledger


def _submit_prompt(
    *,
    agent_id: int = 0,
    submit_round: int = 0,
    known_ids: list[int] | None = None,
    previous_output: str = "",
    inbox: list[dict] | None = None,
    submit_prompt: str | None = None,
) -> str:
    control = {"mode": "submit", "recipients": []}
    known_ids = [agent_id] if known_ids is None else known_ids
    inbox = [] if inbox is None else inbox
    submit_prompt = submit_prompt or (
        f"submit prompt {agent_id}\n"
        "PUBLIC_ANSWER_REQUIREMENT:\nReturn one JSON value."
    )
    return (
        "PYTHON_WORKER_CONTRACT:message_only_v2\n"
        f"PYTHON_AGENT_ID:{agent_id}\n"
        f"PYTHON_ROUND:{submit_round}\n"
        f"PYTHON_SUBMIT_ROUND:{submit_round}\n"
        "PYTHON_CONTROL_JSON:"
        + json.dumps(control, sort_keys=True)
        + "\nKNOWN_SOURCE_IDS_JSON:"
        + json.dumps(known_ids)
        + "\nPREVIOUS_OUTPUT_JSON:"
        + json.dumps(previous_output)
        + "\nDELIVERED_INBOX_JSON:"
        + json.dumps(inbox, sort_keys=True)
        + "\n"
        + "SUBMIT_PROMPT:\n"
        + submit_prompt
        + "\n"
        + MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION
    )


def test_v2_scaffold_is_separate_valid_and_has_two_editable_policies() -> None:
    assert default_python_program("message_only_v2") == DEFAULT_MESSAGE_ONLY_V2_PROGRAM
    assert DEFAULT_MESSAGE_ONLY_V2_PROGRAM not in {
        DEFAULT_MESSAGE_ONLY_PROGRAM,
        DEFAULT_PYTHON_PROGRAM,
    }
    assert validate_python_source(
        DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
        worker_contract="message_only_v2",
    ).valid
    assert not validate_python_source(
        DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
        worker_contract="message_only_v1",
    ).valid
    scaffold = build_python_architect_scaffold("message_only_v2")
    assert validate_python_source(scaffold, worker_contract="message_only_v2").valid
    for policy in ("schedule_policy", "routing_policy"):
        assert scaffold.count(f"EVOLVE-BLOCK-START: {policy}") == 1
        assert scaffold.count(f"EVOLVE-BLOCK-END: {policy}") == 1
    assert "EVOLVE-BLOCK-START" not in scaffold.split("def main():", 1)[1]


def test_v2_payload_requires_split_prompts_and_rejects_legacy_local_prompt() -> None:
    assert PythonExecutionPayload.model_validate(_payload()).worker_contract == (
        "message_only_v2"
    )
    legacy = _payload()
    legacy["agents"][0]["local_prompt"] = "legacy belief-state prompt"
    with pytest.raises(ValueError, match="must not carry the legacy local_prompt"):
        PythonExecutionPayload.model_validate(legacy)
    missing_submit = _payload()
    del missing_submit["agents"][0]["submit_prompt"]
    with pytest.raises(ValueError, match="require separate communication_prompt"):
        PythonExecutionPayload.model_validate(missing_submit)


def test_submit_context_precedes_immutable_final_output_contract() -> None:
    prompt = _submit_prompt(
        submit_prompt=(
            "TASK_AND_PRIVATE_DATA:\nFind the maximum of [3, 827].\n\n"
            "PUBLIC_ANSWER_REQUIREMENT:\n"
            "A single integer representing the global maximum value."
        )
    )
    context = prompt.split("SUBMIT_PROMPT:\n", 1)[1].split(
        "\nFINAL OUTPUT CONTRACT:\n", 1
    )[0]
    assert "belief_state" not in context
    assert "structured_state" not in context
    assert "consensus_key" not in context
    assert prompt.index("PUBLIC_ANSWER_REQUIREMENT:") < prompt.index(
        "FINAL OUTPUT CONTRACT:"
    )
    assert prompt.endswith(
        "Your entire response must be the single benchmark answer value.\n"
    )


def test_v2_architect_and_repair_prompts_pin_the_barrier_scaffold() -> None:
    prompt = build_python_architect_prompt(
        request=_request(), task_brief="public brief", runtime=_runtime()
    )
    assert PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION in prompt
    assert "plan_submit_round" in prompt
    assert "synchronized submit barrier" in prompt
    assert "strict whole-response json.loads" in prompt
    repair = build_python_repair_prompt(
        source="import json",
        failure={"error_type": "AnswerFormatError", "message": "bad answer"},
        attempt=1,
        information_goal="all_agents",
        worker_contract="message_only_v2",
    )
    assert PYTHON_MESSAGE_ONLY_V2_SCAFFOLD_VERSION in repair
    assert "plan_submit_round" in repair


def test_two_agents_communicate_then_submit_together_from_final_delivery() -> None:
    result = CodeProcessRunner().run(
        DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
        _payload(n_agents=2, max_rounds=2, max_model_calls=4),
    )
    assert result.runtime_success, result.failure
    assert result.output is not None
    assert result.output.rounds_executed == 2
    assert {(item.round_sent, item.round_delivered) for item in result.output.messages} == {
        (0, 1)
    }
    assert [item.submitted_round for item in result.output.submissions] == [1, 1]
    assert [item.answer for item in result.output.submissions] == [
        "UNKNOWN",
        "UNKNOWN",
    ]
    calls = result.ledger["calls"]
    assert {(item["round"], item["mode"]) for item in calls} == {
        (0, "send"),
        (1, "submit"),
    }
    submit_calls = [item for item in calls if item["mode"] == "submit"]
    assert len(submit_calls) == 2
    assert all(item["delivered_inbox"] for item in submit_calls)
    assert all(item["known_source_ids"] == [0, 1] for item in submit_calls)
    assert result.final_knowledge == [[0, 1], [0, 1]]
    assert result.ledger["submit_barrier"] == {
        "answer_format": "single_json_value",
        "enabled": True,
        "expected_agent_ids": [0, 1],
        "final_snapshot_sha256": result.ledger["submit_barrier"][
            "final_snapshot_sha256"
        ],
        "information_goal": "all_agents",
        "observed_agent_ids": [0, 1],
        "parser": "json.loads_whole_response",
        "submit_round": 1,
        "synchronized": True,
        "worker_contract": "message_only_v2",
    }
    assert len(result.ledger["submit_barrier"]["final_snapshot_sha256"]) == 64


def test_planner_may_choose_one_global_earlier_barrier() -> None:
    source = DEFAULT_MESSAGE_ONLY_V2_PROGRAM.replace(
        "    return max_rounds - 1\n",
        "    return 1\n",
        1,
    )
    result = CodeProcessRunner().run(
        source,
        _payload(n_agents=2, max_rounds=3, max_model_calls=4),
    )
    assert result.runtime_success, result.failure
    assert result.output is not None
    assert result.output.rounds_executed == 2
    assert [item.submitted_round for item in result.output.submissions] == [1, 1]


def test_communication_policy_cannot_return_submit() -> None:
    source = DEFAULT_MESSAGE_ONLY_V2_PROGRAM.replace(
        '    return {"mode": "send", "recipients": recipients}\n',
        '    return {"mode": "submit", "recipients": []}\n',
        1,
    )
    result = CodeProcessRunner().run(source, _payload())
    assert not result.runtime_success
    assert result.failure is not None
    assert result.failure["error_type"] == "DataFlowError"
    assert result.authoritative_usage.model_calls == 0


def test_invalid_global_submit_round_fails_before_worker_calls() -> None:
    source = DEFAULT_MESSAGE_ONLY_V2_PROGRAM.replace(
        "    return max_rounds - 1\n",
        "    return max_rounds\n",
        1,
    )
    result = CodeProcessRunner().run(source, _payload())
    assert not result.runtime_success
    assert result.failure is not None
    assert result.failure["error_type"] == "DataFlowError"
    assert result.authoritative_usage.model_calls == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        ("[1, 2, 3]", [1, 2, 3]),
        ('"accepted"', "accepted"),
        ('{"answer": 42}', {"answer": 42}),
    ],
)
def test_submit_parser_preserves_one_native_json_value(
    tmp_path: Path,
    raw: str,
    expected,
) -> None:
    inner = _ScriptedWorker([raw])
    client, ledger = _metered_client(tmp_path, inner, _auth())
    response = client.complete(
        _submit_prompt(),
        model_name="fake",
        temperature=0.0,
        json_mode=False,
    )
    assert response.text == raw
    assert inner.json_modes == [False]
    assert ledger["calls"][0]["answer_sha256"] == _value_sha256(expected)
    if isinstance(expected, dict):
        assert ledger["calls"][0]["answer_sha256"] != _value_sha256(42)


@pytest.mark.parametrize(
    "raw",
    ["The answer is 42", "Answer: [1, 2, 3]", "```json\n42\n```", "NaN"],
)
def test_submit_parser_rejects_any_non_json_wrapper(
    tmp_path: Path,
    raw: str,
) -> None:
    inner = _ScriptedWorker([raw])
    client, ledger = _metered_client(tmp_path, inner, _auth())
    with pytest.raises(RuntimeError, match="AnswerFormatError"):
        client.complete(
            _submit_prompt(),
            model_name="fake",
            temperature=0.0,
            json_mode=False,
        )
    assert len(ledger["calls"]) == 1
    assert ledger["calls"][0]["answer_format_valid"] is False
    assert "answer_sha256" not in ledger["calls"][0]


def test_early_submit_and_partial_budget_fail_before_calling_worker(
    tmp_path: Path,
) -> None:
    early_inner = _ScriptedWorker(["42"])
    early_client, _ = _metered_client(
        tmp_path,
        early_inner,
        _auth(n_agents=1, max_rounds=2),
    )
    early_prompt = _submit_prompt(submit_round=1).replace(
        "PYTHON_ROUND:1", "PYTHON_ROUND:0"
    )
    with pytest.raises(RuntimeError, match="only at the synchronized barrier"):
        early_client.complete(
            early_prompt,
            model_name="fake",
            temperature=0.0,
            json_mode=False,
        )
    assert early_inner.prompts == []

    budget_inner = _ScriptedWorker(['"a"', '"b"'])
    budget_client, budget_ledger = _metered_client(
        tmp_path,
        budget_inner,
        _auth(n_agents=2, max_rounds=1, max_model_calls=1),
    )
    with pytest.raises(RuntimeError, match="before barrier"):
        budget_client.complete(
            _submit_prompt(),
            model_name="fake",
            temperature=0.0,
            json_mode=False,
        )
    assert budget_inner.prompts == []
    assert budget_ledger["calls"] == []
    assert "submit_barrier" not in budget_ledger

    token_inner = _ScriptedWorker(
        ['"long first"', '"second"'],
        completion_tokens=2,
    )
    token_client, token_ledger = _metered_client(
        tmp_path,
        token_inner,
        _auth(
            n_agents=2,
            max_rounds=1,
            max_model_calls=2,
            max_completion_tokens=2,
        ),
    )
    with pytest.raises(RuntimeError, match="complete barrier"):
        token_client.complete(
            _submit_prompt(),
            model_name="fake",
            temperature=0.0,
            json_mode=False,
        )
    assert len(token_ledger["calls"]) == 1
    assert token_ledger["submit_barrier"]["observed_agent_ids"] == []
    assert token_ledger["submit_barrier"]["synchronized"] is False


def test_sequential_physical_calls_do_not_share_submit_answers(
    tmp_path: Path,
) -> None:
    inner = _ScriptedWorker(['"ANSWER_ZERO_SECRET"', '"answer one"'])
    client, ledger = _metered_client(
        tmp_path,
        inner,
        _auth(n_agents=2, max_rounds=1),
    )
    for agent_id in range(2):
        client.complete(
            _submit_prompt(agent_id=agent_id),
            model_name="fake",
            temperature=0.0,
            json_mode=False,
        )
    assert "ANSWER_ZERO_SECRET" not in inner.prompts[1]
    assert ledger["submit_barrier"]["synchronized"] is True
    assert ledger["submit_barrier"]["observed_agent_ids"] == [0, 1]


def test_sink_barrier_submits_only_selected_primary() -> None:
    result = CodeProcessRunner().run(
        DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
        _payload(goal="sink", n_agents=3, max_rounds=2, max_model_calls=4),
    )
    assert result.runtime_success, result.failure
    assert result.output is not None
    submissions = {item.agent_id: item for item in result.output.submissions}
    assert submissions[0].submitted_round == 1
    assert submissions[1].submitted_round is None
    assert submissions[2].submitted_round is None
    assert result.ledger["submit_barrier"]["expected_agent_ids"] == [0]


def test_host_rejects_tampered_native_submission() -> None:
    runner = CodeProcessRunner()
    payload = _payload(n_agents=2, max_rounds=2, max_model_calls=4)
    result = runner.run(DEFAULT_MESSAGE_ONLY_V2_PROGRAM, payload)
    assert result.runtime_success and result.output is not None
    tampered = result.output.model_copy(deep=True)
    tampered.submissions[0].answer = 42
    with pytest.raises(PythonCodeError, match="parsed Worker answer"):
        runner._validate_output(
            tampered,
            payload,
            result.authoritative_usage,
            result.ledger,
        )


def _card(skill_id: str, worker_contract: str, source: str) -> SkillCard:
    return SkillCard(
        skill_id=skill_id,
        task_family="silo",
        skill_type="python_generation_skill",
        mode_payload=PythonSkillPayload(
            source_code=source,
            ast_policy_version="python_ast_v1",
            execution_contract_version="python_mas_v1",
            worker_contract=worker_contract,
        ),
        provenance="llm_generated_python",
        information_goal="all_agents",
        trigger={"planner_mode": "python_generate"},
        evidence=[{"observation_id": f"{skill_id}-obs"}],
    )


def test_three_contract_skill_retrieval_replay_and_merge_are_isolated() -> None:
    action = _card("action", "action_json_v1", DEFAULT_PYTHON_PROGRAM)
    v1 = _card("v1", "message_only_v1", DEFAULT_MESSAGE_ONLY_PROGRAM)
    v2 = _card("v2", "message_only_v2", DEFAULT_MESSAGE_ONLY_V2_PROGRAM)
    bank = SkillBank([action, v1, v2])
    assert [item.skill_id for item in bank.retrieve(_request())] == ["v2"]
    assert [
        item.skill_id
        for item in bank.retrieve(_request(worker_contract="message_only_v1"))
    ] == ["v1"]
    assert [
        item.skill_id
        for item in bank.retrieve(_request(worker_contract="action_json_v1"))
    ] == ["action"]
    replay = _replay_source(
        [action, v1, v2],
        _runtime().model_copy(update={"replay_first": True}),
    )
    assert replay == ("v2", DEFAULT_MESSAGE_ONLY_V2_PROGRAM)
    with pytest.raises(ValueError, match="across worker contracts"):
        merge_mode_payload(v1.mode_payload, v2.mode_payload)
