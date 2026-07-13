"""Offline semantics, security and isolation tests for message_only_v1.

The message-only contract splits responsibilities three ways: the Planner
source decides routing (send/reflect/submit/idle plus recipients), the
runtime/bootstrap wrapper owns state, delivery and source-id provenance, and
the Worker LLM returns plain text only. These tests pin each boundary and the
fail-closed behaviour on every violation, while asserting the legacy
action_json_v1 surfaces stay untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.leakage_audit import find_leakage_tokens
from exp_graph.mas.python_code import (
    DEFAULT_MESSAGE_ONLY_PROGRAM,
    DEFAULT_PYTHON_PROGRAM,
    MESSAGE_ONLY_MESSAGE_INSTRUCTION,
    MESSAGE_ONLY_SUBMIT_INSTRUCTION,
    PYTHON_WORKER_CONTRACTS,
    default_python_program,
    validate_python_source,
)
from exp_graph.mas.python_code_generation import (
    PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION,
    PYTHON_SCAFFOLD_VERSION,
    PythonGenerationError,
    _replay_source,
    build_python_architect_prompt,
    build_python_architect_scaffold,
    build_python_repair_prompt,
    plan_and_execute_python,
)
from exp_graph.mas.python_code_runner import CodeProcessRunner
from exp_graph.mas.python_worker_bootstrap import _MeteredClient, _value_sha256
from exp_graph.mas.schemas import (
    MASRuntimeConfig,
    ObjectiveSpec,
    PlannerRequest,
    PythonSkillPayload,
    PythonWorkerContract,
    SkillCard,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.skill_payloads import (
    merge_mode_payload,
    python_worker_contract_from_skill,
)


def _request(
    goal: str = "all_agents",
    n_agents: int = 3,
    worker_contract: str = "message_only_v1",
) -> PlannerRequest:
    return PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name("balanced"),
        planner_mode="python_generate",
        information_goal=goal,
        provenance_allowlist=["llm_generated_python", "skill_replay"],
        python_worker_contract=worker_contract,
    )


def _payload(
    *,
    goal: str = "all_agents",
    n_agents: int = 3,
    max_rounds: int = 4,
    max_model_calls: int = 20,
    max_messages: int = 30,
) -> dict:
    return {
        "execution_contract_version": "python_mas_v1",
        "worker_contract": "message_only_v1",
        "task_description": "Synthetic offline wiring check.",
        "information_goal": goal,
        "selected_primary": 0,
        "n_agents": n_agents,
        "max_rounds": max_rounds,
        "budgets": {
            "max_model_calls": max_model_calls,
            "max_completion_tokens": 4000,
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
            {"agent_id": i, "local_prompt": f"PRIVATE_LOCAL_{i}"}
            for i in range(n_agents)
        ],
    }


class _TaskAdapter:
    @staticmethod
    def describe_task() -> str:
        return "Find a result from private local observations."


def _runtime(**overrides) -> MASRuntimeConfig:
    values = {
        "llm_provider": "openai",
        "model_name": "architect-test",
        "python_max_rounds": 4,
        "python_repair_attempts": 3,
        "python_execution_timeout": 10.0,
        "information_goal": "all_agents",
        "python_worker_contract": "message_only_v1",
    }
    values.update(overrides)
    return MASRuntimeConfig(**values)


class _ScriptedClient:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.prompts: list[str] = []
        self.json_modes: list[bool] = []

    def complete(self, prompt, model_name, temperature=None, json_mode=True):
        del model_name, temperature
        self.prompts.append(prompt)
        self.json_modes.append(json_mode)
        text = self.texts.pop(0)
        return LLMResponse(
            text=text,
            usage=LLMUsage(prompt_tokens=3, completion_tokens=5),
        )


# ---------------------------------------------------------------------------
# Contract constants and static validation
# ---------------------------------------------------------------------------


def test_worker_contract_literals_stay_in_lockstep() -> None:
    assert tuple(get_args(PythonWorkerContract)) == PYTHON_WORKER_CONTRACTS


def test_both_scaffolds_validate_only_under_their_own_contract() -> None:
    assert validate_python_source(DEFAULT_PYTHON_PROGRAM).valid
    assert validate_python_source(
        DEFAULT_MESSAGE_ONLY_PROGRAM,
        worker_contract="message_only_v1",
    ).valid
    assert not validate_python_source(DEFAULT_MESSAGE_ONLY_PROGRAM).valid
    assert not validate_python_source(
        DEFAULT_PYTHON_PROGRAM,
        worker_contract="message_only_v1",
    ).valid
    unknown = validate_python_source(
        DEFAULT_PYTHON_PROGRAM,
        worker_contract="bogus_v9",
    )
    assert not unknown.valid
    assert "unknown python worker contract" in unknown.errors[0]["message"]


def test_marked_message_only_scaffold_stays_valid_and_editable_regions() -> None:
    scaffold = build_python_architect_scaffold("message_only_v1")
    assert validate_python_source(
        scaffold,
        worker_contract="message_only_v1",
    ).valid
    for marker in (
        "EVOLVE-BLOCK-START: submission_policy",
        "EVOLVE-BLOCK-END: submission_policy",
        "EVOLVE-BLOCK-START: routing_policy",
        "EVOLVE-BLOCK-END: routing_policy",
    ):
        assert scaffold.count(marker) == 1
    # The worker instruction is a canonical security boundary, never an
    # editable region under message_only_v1.
    assert "EVOLVE-BLOCK-START: worker_instruction" not in scaffold


def test_default_program_selector_fails_closed() -> None:
    assert default_python_program() == DEFAULT_PYTHON_PROGRAM
    assert (
        default_python_program("message_only_v1") == DEFAULT_MESSAGE_ONLY_PROGRAM
    )
    with pytest.raises(ValueError):
        default_python_program("bogus_v9")


# ---------------------------------------------------------------------------
# Bootstrap wrapper unit semantics (authoritative runtime state)
# ---------------------------------------------------------------------------


class _EchoTextWorker:
    def __init__(self, texts: list[str] | None = None) -> None:
        self.texts = list(texts or [])
        self.json_modes: list[bool] = []

    def complete(self, prompt, model_name, temperature=None, json_mode=True):
        del prompt, model_name, temperature
        self.json_modes.append(json_mode)
        text = self.texts.pop(0) if self.texts else "worker text output"
        return LLMResponse(
            text=text,
            usage=LLMUsage(prompt_tokens=7, completion_tokens=3),
        )


def _auth(
    *,
    n_agents: int = 2,
    max_rounds: int = 4,
    goal: str = "all_agents",
    max_messages: int = 16,
    canaries: dict[str, str] | None = None,
    local_prompts: dict[str, str] | None = None,
) -> dict:
    return {
        "worker_llm": {
            "provider": "fake",
            "model_name": "fake",
            "base_url": None,
            "api_key_env": None,
            "temperature": 0.0,
        },
        "worker_contract": "message_only_v1",
        "budgets": {
            "max_model_calls": 16,
            "max_completion_tokens": 10_000,
            "max_messages": max_messages,
        },
        "agent_canaries": canaries or {},
        "max_output_bytes": 100_000,
        "n_agents": n_agents,
        "information_goal": goal,
        "selected_primary": 0,
        "max_rounds": max_rounds,
        "agent_local_prompts": (
            local_prompts
            or {str(i): f"local prompt {i}" for i in range(n_agents)}
        ),
    }


def _client(
    tmp_path: Path,
    *,
    auth: dict | None = None,
    inner: _EchoTextWorker | None = None,
) -> tuple[_MeteredClient, dict]:
    auth = auth or _auth()
    ledger = {
        "factory_calls": 1,
        "worker_contract": "message_only_v1",
        "calls": [],
        "usage": {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
        "errors": [],
    }
    client = _MeteredClient(
        inner or _EchoTextWorker(),
        auth,
        ledger,
        tmp_path / "ledger.json",
    )
    return client, auth


def _prompt(
    auth: dict,
    *,
    agent_id: int,
    round_idx: int,
    control: dict,
    known: list[int] | None = None,
    prev: str = "",
    inbox: list | None = None,
    instruction: str | None = None,
    local_prompt: str | None = None,
) -> str:
    if instruction is None:
        instruction = (
            MESSAGE_ONLY_SUBMIT_INSTRUCTION
            if control.get("mode") == "submit"
            else MESSAGE_ONLY_MESSAGE_INSTRUCTION
        )
    if local_prompt is None:
        local_prompt = auth["agent_local_prompts"][str(agent_id)]
    return (
        "PYTHON_WORKER_CONTRACT:message_only_v1\n"
        f"PYTHON_AGENT_ID:{agent_id}\n"
        f"PYTHON_ROUND:{round_idx}\n"
        "PYTHON_CONTROL_JSON:"
        + json.dumps(control, sort_keys=True)
        + "\nKNOWN_SOURCE_IDS_JSON:"
        + json.dumps(known if known is not None else [agent_id])
        + "\nPREVIOUS_OUTPUT_JSON:"
        + json.dumps(prev)
        + "\nDELIVERED_INBOX_JSON:"
        + json.dumps(inbox or [], sort_keys=True)
        + "\n"
        + instruction
        + "LOCAL_PROMPT:\n"
        + local_prompt
    )


def _call(client: _MeteredClient, prompt: str) -> LLMResponse:
    return client.complete(
        prompt,
        model_name="fake",
        temperature=0.0,
        json_mode=False,
    )


def test_send_updates_memory_creates_envelopes_and_ledger(tmp_path: Path) -> None:
    client, auth = _client(tmp_path, inner=_EchoTextWorker(["  summary text  "]))
    control = {"mode": "send", "recipients": [1]}
    _call(client, _prompt(auth, agent_id=0, round_idx=0, control=control))
    assert client.previous_outputs[0] == "summary text"
    assert len(client.pending_envelopes) == 1
    envelope = client.pending_envelopes[0]
    assert envelope["round_sent"] == 0
    assert envelope["round_delivered"] == 1
    assert envelope["src"] == 0 and envelope["dst"] == 1
    assert envelope["source_ids"] == [0]
    assert envelope["body"] == "summary text"
    entry = client.ledger["calls"][0]
    assert entry["mode"] == "send"
    assert entry["recipients"] == [1]
    assert entry["known_source_ids"] == [0]
    assert entry["worker_output_sha256"] == _value_sha256("summary text")
    # No raw text may land in the persisted ledger, only hashes and counters.
    assert "summary text" not in (tmp_path / "ledger.json").read_text()


def test_reflect_updates_memory_without_sending(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    _call(
        client,
        _prompt(
            auth,
            agent_id=0,
            round_idx=0,
            control={"mode": "reflect", "recipients": []},
        ),
    )
    assert client.previous_outputs[0] == "worker text output"
    assert client.pending_envelopes == []
    assert client.ledger["calls"][0]["mode"] == "reflect"


def test_submit_records_round_and_blocks_later_calls(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    _call(
        client,
        _prompt(
            auth,
            agent_id=0,
            round_idx=0,
            control={"mode": "submit", "recipients": []},
        ),
    )
    assert client.submitted_rounds[0] == 0
    with pytest.raises(RuntimeError, match="submitted agent was called again"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=0,
                round_idx=1,
                control={"mode": "reflect", "recipients": []},
            ),
        )


def test_worker_json_mode_must_be_text(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    prompt = _prompt(
        auth,
        agent_id=0,
        round_idx=0,
        control={"mode": "reflect", "recipients": []},
    )
    with pytest.raises(RuntimeError, match="json_mode=False"):
        client.complete(prompt, model_name="fake", temperature=0.0)
    with pytest.raises(RuntimeError, match="json_mode=False"):
        client.complete(
            prompt,
            model_name="fake",
            temperature=0.0,
            json_mode=True,
        )


@pytest.mark.parametrize(
    ("control", "match"),
    [
        ({"mode": "idle", "recipients": []}, "not send/reflect/submit"),
        ({"mode": "reflect", "recipients": [1]}, "recipients require send"),
        ({"mode": "send", "recipients": [2]}, "recipient outside"),
        ({"mode": "send", "recipients": [0]}, "recipient outside"),
        ({"mode": "send", "recipients": [1, 1]}, "duplicate recipients"),
        ({"mode": "send", "recipients": [-1]}, "recipient outside"),
        ({"mode": "send"}, "malformed planner control"),
        (
            {"mode": "send", "recipients": [1], "extra": True},
            "malformed planner control",
        ),
    ],
)
def test_planner_control_violations_fail_closed(
    tmp_path: Path, control: dict, match: str
) -> None:
    client, auth = _client(tmp_path)
    with pytest.raises(RuntimeError, match=match):
        _call(client, _prompt(auth, agent_id=0, round_idx=0, control=control))
    assert client.ledger["calls"] == []


def test_forged_known_source_ids_fail_closed(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    with pytest.raises(RuntimeError, match="runtime provenance"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=0,
                round_idx=0,
                control={"mode": "reflect", "recipients": []},
                known=[0, 1],
            ),
        )


def test_forged_previous_output_fails_closed(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    with pytest.raises(RuntimeError, match="previous output was not retained"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=0,
                round_idx=0,
                control={"mode": "reflect", "recipients": []},
                prev="fabricated memory",
            ),
        )


def test_non_canonical_instruction_fails_closed(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    with pytest.raises(RuntimeError, match="canonical"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=0,
                round_idx=0,
                control={"mode": "reflect", "recipients": []},
                instruction="INSTRUCTION:\nDo something else entirely.\n",
            ),
        )


def test_same_round_output_is_not_visible_and_delivery_is_next_round(
    tmp_path: Path,
) -> None:
    client, auth = _client(
        tmp_path,
        inner=_EchoTextWorker(["from zero", "from one", "one round later"]),
    )
    _call(
        client,
        _prompt(
            auth,
            agent_id=0,
            round_idx=0,
            control={"mode": "send", "recipients": [1]},
        ),
    )
    fresh = dict(client.pending_envelopes[0])
    fresh.pop("merged")
    # Same-round visibility of agent 0's fresh envelope must be rejected.
    with pytest.raises(RuntimeError, match="does not match runtime deliveries"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=1,
                round_idx=0,
                control={"mode": "reflect", "recipients": []},
                inbox=[fresh],
            ),
        )
    # The same envelope is the mandatory inbox one round later.
    _call(
        client,
        _prompt(
            auth,
            agent_id=1,
            round_idx=0,
            control={"mode": "reflect", "recipients": []},
        ),
    )
    _call(
        client,
        _prompt(
            auth,
            agent_id=1,
            round_idx=1,
            control={"mode": "reflect", "recipients": []},
            known=[0, 1],
            prev="from one",
            inbox=[fresh],
        ),
    )
    assert sorted(client.known_sources[1]) == [0, 1]


def test_idle_round_deliveries_merge_without_a_call(tmp_path: Path) -> None:
    auth = _auth(n_agents=3)
    client, _ = _client(tmp_path, auth=auth)
    _call(
        client,
        _prompt(
            auth,
            agent_id=0,
            round_idx=0,
            control={"mode": "send", "recipients": [1]},
        ),
    )
    envelope = dict(client.pending_envelopes[0])
    envelope.pop("merged")
    # Agent 1 idles through round 1 (no call); at round 2 the missed delivery
    # is merged into provenance but is no longer this round's inbox.
    _call(
        client,
        _prompt(
            auth,
            agent_id=1,
            round_idx=2,
            control={"mode": "reflect", "recipients": []},
            known=[0, 1],
            inbox=[],
        ),
    )
    assert sorted(client.known_sources[1]) == [0, 1]


def test_message_budget_fails_closed(tmp_path: Path) -> None:
    auth = _auth(n_agents=3, max_messages=1)
    client, _ = _client(tmp_path, auth=auth)
    _call(
        client,
        _prompt(
            auth,
            agent_id=0,
            round_idx=0,
            control={"mode": "send", "recipients": [1]},
        ),
    )
    with pytest.raises(RuntimeError, match="message budget exhausted"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=1,
                round_idx=0,
                control={"mode": "send", "recipients": [2]},
            ),
        )


def test_round_ordering_and_duplicate_calls_fail_closed(tmp_path: Path) -> None:
    client, auth = _client(tmp_path)
    _call(
        client,
        _prompt(
            auth,
            agent_id=0,
            round_idx=1,
            control={"mode": "reflect", "recipients": []},
        ),
    )
    with pytest.raises(RuntimeError, match="monotonic round ordering"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=1,
                round_idx=0,
                control={"mode": "reflect", "recipients": []},
            ),
        )
    with pytest.raises(RuntimeError, match="more than once in the same round"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=0,
                round_idx=1,
                control={"mode": "reflect", "recipients": []},
                prev="worker text output",
            ),
        )


def test_cross_agent_canary_leak_fails_closed(tmp_path: Path) -> None:
    canaries = {"0": "CANARY_ZERO_A91F", "1": "CANARY_ONE_B82E"}
    auth = _auth(
        canaries=canaries,
        local_prompts={
            "0": "CANARY_ZERO_A91F plus CANARY_ONE_B82E leaked",
            "1": "CANARY_ONE_B82E private",
        },
    )
    client, _ = _client(tmp_path, auth=auth)
    with pytest.raises(RuntimeError, match="local prompt leaked"):
        _call(
            client,
            _prompt(
                auth,
                agent_id=0,
                round_idx=0,
                control={"mode": "reflect", "recipients": []},
            ),
        )


# ---------------------------------------------------------------------------
# Subprocess runner integration (full offline demo semantics)
# ---------------------------------------------------------------------------


def test_all_agents_ring_runs_offline_with_runtime_owned_provenance() -> None:
    payload = _payload(goal="all_agents", n_agents=3, max_rounds=4)
    result = CodeProcessRunner().run(DEFAULT_MESSAGE_ONLY_PROGRAM, payload)
    assert result.runtime_success, result.failure
    output = result.output
    assert output is not None
    # Every agent submits independently with its raw worker text.
    assert all(item.submitted_round is not None for item in output.submissions)
    assert all(
        isinstance(item.answer, str) and item.answer for item in output.submissions
    )
    # Workers returned plain text, not action JSON.
    for item in output.submissions:
        with pytest.raises(json.JSONDecodeError):
            json.loads(item.answer)
    # Messages deliver exactly one round later and carry runtime provenance.
    calls = {
        (int(c["round"]), int(c["agent_id"])): c for c in result.ledger["calls"]
    }
    for message in output.messages:
        assert message.round_delivered == message.round_sent + 1
        call = calls[(message.round_sent, message.src)]
        assert call["mode"] == "send"
        assert message.dst in call["recipients"]
        assert sorted(message.source_ids) == call["known_source_ids"]
        assert _value_sha256(message.body) == call["worker_output_sha256"]
    # Planner send controls and emitted messages correspond one-to-one.
    expected = {
        (r, a, d)
        for (r, a), c in calls.items()
        if c["mode"] == "send"
        for d in c["recipients"]
    }
    actual = {(m.round_sent, m.src, m.dst) for m in output.messages}
    assert actual == expected
    # Ring propagation merged and deduplicated provenance to full coverage.
    assert result.final_knowledge == [[0, 1, 2], [0, 1, 2], [0, 1, 2]]
    submit_calls = {
        pair for pair, c in calls.items() if c["mode"] == "submit"
    }
    assert submit_calls == {
        (item.submitted_round, item.agent_id) for item in output.submissions
    }
    for item in output.submissions:
        call = calls[(item.submitted_round, item.agent_id)]
        assert call["worker_output_sha256"] == _value_sha256(item.answer)
    # Authoritative usage reconciles with the program-reported usage.
    assert output.usage == result.authoritative_usage


def test_sink_star_lets_non_primary_agents_idle() -> None:
    payload = _payload(goal="sink", n_agents=3, max_rounds=4)
    result = CodeProcessRunner().run(DEFAULT_MESSAGE_ONLY_PROGRAM, payload)
    assert result.runtime_success, result.failure
    output = result.output
    assert output is not None
    by_agent = {item.agent_id: item for item in output.submissions}
    assert by_agent[0].submitted_round is not None
    assert by_agent[0].answer
    assert by_agent[1].submitted_round is None and by_agent[1].answer is None
    assert by_agent[2].submitted_round is None and by_agent[2].answer is None
    pairs = {
        (int(c["round"]), int(c["agent_id"])) for c in result.ledger["calls"]
    }
    # The sink idles in round 0 (idle = no worker call, no message).
    assert (0, 0) not in pairs
    assert sorted(result.final_knowledge[0]) == [0, 1, 2]


def test_dry_run_canaries_pass_for_honest_message_only_scaffold() -> None:
    payload = _payload(goal="all_agents", n_agents=2, max_rounds=3)
    canaries = {"0": "PYTHON_LOCAL_CANARY_0_A91F", "1": "PYTHON_LOCAL_CANARY_1_A91F"}
    for agent in payload["agents"]:
        agent["local_prompt"] = (
            f"{canaries[str(agent['agent_id'])]}\nSynthetic private prompt."
        )
    result = CodeProcessRunner().run(
        DEFAULT_MESSAGE_ONLY_PROGRAM,
        payload,
        agent_canaries=canaries,
    )
    assert result.runtime_success, result.failure


def test_program_forging_source_ids_fails_closed() -> None:
    forged = DEFAULT_MESSAGE_ONLY_PROGRAM.replace(
        '"source_ids": list(snapshot_states[agent_id]["source_ids"]),\n'
        '                        "body": worker_output,',
        '"source_ids": [0, 1],\n'
        '                        "body": worker_output,',
    )
    assert forged != DEFAULT_MESSAGE_ONLY_PROGRAM
    assert validate_python_source(
        forged,
        worker_contract="message_only_v1",
    ).valid
    result = CodeProcessRunner().run(
        forged,
        _payload(goal="all_agents", n_agents=2, max_rounds=3),
    )
    assert not result.runtime_success
    assert result.failure is not None
    assert result.failure["error_type"] == "DataFlowError"


def test_contract_mismatched_payload_fails_static_validation() -> None:
    # An action_json payload cannot execute a message_only program: the
    # runner validates the source under the payload's declared contract.
    payload = _payload()
    payload["worker_contract"] = "action_json_v1"
    result = CodeProcessRunner().run(DEFAULT_MESSAGE_ONLY_PROGRAM, payload)
    assert not result.runtime_success
    assert result.failure["error_type"] == "PolicyError"


# ---------------------------------------------------------------------------
# Generation pipeline (prompts, fake path, repair, artifacts, no fallback)
# ---------------------------------------------------------------------------


def test_architect_prompts_embed_the_contract_specific_scaffold() -> None:
    message_prompt = build_python_architect_prompt(
        request=_request(),
        task_brief="brief",
        runtime=_runtime(),
    )
    assert PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION in message_prompt
    assert "def plan_turn(" in message_prompt
    assert "message_only_v1" in message_prompt
    assert "should_send" not in message_prompt
    assert find_leakage_tokens(message_prompt) == []
    action_prompt = build_python_architect_prompt(
        request=_request(worker_contract="action_json_v1"),
        task_brief="brief",
        runtime=_runtime(python_worker_contract="action_json_v1"),
    )
    assert PYTHON_SCAFFOLD_VERSION in action_prompt
    assert PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION not in action_prompt
    assert "should_send" in action_prompt
    assert "plan_turn" not in action_prompt


def test_repair_prompt_embeds_the_contract_specific_scaffold() -> None:
    message_repair = build_python_repair_prompt(
        source="import json",
        failure={"error_type": "PolicyError", "message": "x"},
        attempt=1,
        information_goal="all_agents",
        worker_contract="message_only_v1",
    )
    assert PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION in message_repair
    assert "def plan_turn(" in message_repair
    assert find_leakage_tokens(message_repair) == []
    action_repair = build_python_repair_prompt(
        source="import json",
        failure={"error_type": "PolicyError", "message": "x"},
        attempt=1,
        information_goal="all_agents",
    )
    assert PYTHON_SCAFFOLD_VERSION in action_repair
    assert PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION not in action_repair
    assert "worker_contract" not in action_repair.split(
        "BEGIN_REJECTED_PYTHON_SOURCE"
    )[0]


def test_fake_message_only_generation_end_to_end(tmp_path: Path) -> None:
    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(llm_provider="fake", model_name="fake"),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=_payload(),
        output_dir=tmp_path,
    )
    assert result.provenance == "fake"
    assert result.source == DEFAULT_MESSAGE_ONLY_PROGRAM
    assert result.execution.runtime_success
    report = json.loads((tmp_path / "execution_report.json").read_text())
    assert report["worker_contract"] == "message_only_v1"
    assert report["execution_contract_version"] == "python_mas_v1"
    assert report["dry_run_valid"] is True
    payload_record = json.loads(
        (tmp_path / "stdin_payload.redacted.json").read_text()
    )
    assert payload_record["worker_contract"] == "message_only_v1"


def test_scripted_generation_validates_returned_source(tmp_path: Path) -> None:
    client = _ScriptedClient([DEFAULT_MESSAGE_ONLY_PROGRAM])
    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=_payload(),
        output_dir=tmp_path,
        llm_client=client,
    )
    assert result.provenance == "llm_generated_python"
    assert client.json_modes == [False]
    assert PYTHON_MESSAGE_ONLY_SCAFFOLD_VERSION in client.prompts[0]
    assert result.execution.runtime_success


def test_generation_failure_stays_honest_without_fallback(tmp_path: Path) -> None:
    client = _ScriptedClient(["not python at all", "def broken("])
    with pytest.raises(PythonGenerationError) as excinfo:
        plan_and_execute_python(
            request=_request(),
            runtime=_runtime(python_repair_attempts=1),
            skill_bank=SkillBank(),
            task_adapter=_TaskAdapter(),
            execution_payload=_payload(),
            output_dir=tmp_path,
            llm_client=client,
        )
    assert excinfo.value.error_type is not None
    report = json.loads((tmp_path / "execution_report.json").read_text())
    assert report["runtime_success"] is False
    assert report["worker_contract"] == "message_only_v1"
    # No named-topology / graph / phase-program fallback may ever appear.
    assert "named" not in str(report["provenance"])


def test_runtime_payload_contract_mismatch_is_a_loud_error(tmp_path: Path) -> None:
    payload = _payload()
    payload["worker_contract"] = "action_json_v1"
    with pytest.raises(ValueError, match="does not match runtime configuration"):
        plan_and_execute_python(
            request=_request(),
            runtime=_runtime(),
            skill_bank=SkillBank(),
            task_adapter=_TaskAdapter(),
            execution_payload=payload,
            output_dir=tmp_path,
        )


# ---------------------------------------------------------------------------
# SkillBank isolation across worker contracts
# ---------------------------------------------------------------------------


def _python_card(skill_id: str, worker_contract: str, source: str) -> SkillCard:
    payload = PythonSkillPayload(
        source_code=source,
        ast_policy_version="python_ast_v1",
        execution_contract_version="python_mas_v1",
        worker_contract=worker_contract,
    )
    return SkillCard(
        skill_id=skill_id,
        task_family="silo",
        skill_type="python_generation_skill",
        mode_payload=payload,
        provenance="llm_generated_python",
        information_goal="all_agents",
        trigger={"planner_mode": "python_generate"},
        evidence=[{"observation_id": f"{skill_id}-obs"}],
    )


def test_retrieval_is_isolated_per_worker_contract() -> None:
    bank = SkillBank(
        [
            _python_card("action-card", "action_json_v1", DEFAULT_PYTHON_PROGRAM),
            _python_card(
                "message-card",
                "message_only_v1",
                DEFAULT_MESSAGE_ONLY_PROGRAM,
            ),
        ]
    )
    message_hits = bank.retrieve(_request())
    assert [skill.skill_id for skill in message_hits] == ["message-card"]
    action_hits = bank.retrieve(_request(worker_contract="action_json_v1"))
    assert [skill.skill_id for skill in action_hits] == ["action-card"]


def test_legacy_cards_without_the_field_are_action_json() -> None:
    card = _python_card("legacy", "action_json_v1", DEFAULT_PYTHON_PROGRAM)
    legacy = card.model_copy(
        update={
            "mode_payload": PythonSkillPayload.model_validate(
                {
                    "source_code": DEFAULT_PYTHON_PROGRAM,
                    "ast_policy_version": "python_ast_v1",
                    "execution_contract_version": "python_mas_v1",
                }
            )
        }
    )
    assert python_worker_contract_from_skill(legacy) == "action_json_v1"


def test_replay_only_accepts_same_contract_sources() -> None:
    runtime = _runtime(replay_first=True)
    action_card = _python_card(
        "action-card", "action_json_v1", DEFAULT_PYTHON_PROGRAM
    )
    message_card = _python_card(
        "message-card", "message_only_v1", DEFAULT_MESSAGE_ONLY_PROGRAM
    )
    assert _replay_source([action_card], runtime) is None
    replay = _replay_source([action_card, message_card], runtime)
    assert replay is not None
    assert replay[0] == "message-card"
    assert replay[1] == DEFAULT_MESSAGE_ONLY_PROGRAM
    action_runtime = _runtime(
        replay_first=True,
        python_worker_contract="action_json_v1",
    )
    replay = _replay_source([message_card, action_card], action_runtime)
    assert replay is not None
    assert replay[0] == "action-card"


def test_merge_rejects_cross_contract_python_payloads() -> None:
    action_payload = _python_card(
        "a", "action_json_v1", DEFAULT_PYTHON_PROGRAM
    ).mode_payload
    message_payload = _python_card(
        "b", "message_only_v1", DEFAULT_MESSAGE_ONLY_PROGRAM
    ).mode_payload
    with pytest.raises(ValueError, match="across worker contracts"):
        merge_mode_payload(action_payload, message_payload)
    merged = merge_mode_payload(message_payload, message_payload)
    assert merged is message_payload
