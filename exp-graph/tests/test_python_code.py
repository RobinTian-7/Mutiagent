"""Offline security, semantics, repair, and isolation tests for PythonGen."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.leakage_audit import find_leakage_tokens
from exp_graph.mas.evolution import make_skill_card
from exp_graph.mas.python_code import (
    DEFAULT_PYTHON_PROGRAM,
    PythonProgramOutput,
    python_source_sha256,
    validate_python_source,
)
from exp_graph.mas.python_code_generation import (
    PYTHON_SCAFFOLD_VERSION,
    PythonGenerationError,
    build_python_architect_prompt,
    build_python_architect_scaffold,
    build_python_repair_prompt,
    extract_python_source,
    plan_and_execute_python,
)
from exp_graph.mas.python_code_runner import CodeProcessRunner, PythonExecutionLimits
from exp_graph.mas.schemas import (
    GraphSkillPayload,
    MASRuntimeConfig,
    ObjectiveSpec,
    PhaseProgramSkillPayload,
    PlannerRequest,
    PythonSkillPayload,
    SkillCard,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols import ProtocolGraphSpec, ProtocolStepSpec


def _request(goal: str = "all_agents", n_agents: int = 3) -> PlannerRequest:
    return PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name("balanced"),
        planner_mode="python_generate",
        information_goal=goal,
        provenance_allowlist=["llm_generated_python", "skill_replay"],
    )


def _payload(
    *,
    goal: str = "all_agents",
    n_agents: int = 3,
    max_rounds: int = 2,
    max_model_calls: int = 20,
) -> dict:
    return {
        "execution_contract_version": "python_mas_v1",
        "task_description": "Synthetic offline wiring check.",
        "information_goal": goal,
        "selected_primary": 0,
        "n_agents": n_agents,
        "max_rounds": max_rounds,
        "budgets": {
            "max_model_calls": max_model_calls,
            "max_completion_tokens": 4000,
            "max_messages": 30,
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


def _runtime(**overrides) -> MASRuntimeConfig:
    values = {
        "llm_provider": "openai",
        "model_name": "architect-test",
        "python_max_rounds": 2,
        "python_repair_attempts": 3,
        "python_execution_timeout": 10.0,
        "information_goal": "all_agents",
    }
    values.update(overrides)
    return MASRuntimeConfig(**values)


def test_default_program_validates_and_executes_round_semantics() -> None:
    report = validate_python_source(DEFAULT_PYTHON_PROGRAM)
    assert report.valid, report.errors

    result = CodeProcessRunner().run(DEFAULT_PYTHON_PROGRAM, _payload())
    assert result.runtime_success, result.failure
    assert result.output is not None
    assert result.output.rounds_executed == 2
    assert result.authoritative_usage.model_calls == 6
    assert len(result.output.messages) == 2
    assert all(
        (message.round_sent, message.round_delivered) == (0, 1)
        for message in result.output.messages
    )
    # Agent 2 deliberately chooses no-send in round 0; all agents still retain
    # their prior fake-worker state and act from the round-1 snapshot.
    assert not any(message.src == 2 for message in result.output.messages)
    round_one = [call for call in result.ledger["calls"] if call["round"] == 1]
    assert len(round_one) == 3
    assert all("status" in call["previous_state_keys"] for call in round_one)
    assert any(call["delivered_inbox"] for call in round_one)
    assert len(result.output.submissions) == 3
    assert all(item.submitted_round == 1 for item in result.output.submissions)


def test_submitted_agent_is_not_called_or_sent_again() -> None:
    source = DEFAULT_PYTHON_PROGRAM.replace(
        '"submit": round_idx + 1 >= max_rounds,',
        '"submit": agent_id == 0 or round_idx + 1 >= max_rounds,',
    )
    assert validate_python_source(source).valid
    result = CodeProcessRunner().run(source, _payload())
    assert result.runtime_success, result.failure
    assert (1, 0) not in {
        (call["round"], call["agent_id"]) for call in result.ledger["calls"]
    }
    assert not any(
        message.src == 0 and message.round_sent >= 0
        for message in result.output.messages  # type: ignore[union-attr]
    )


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\n",
        "import subprocess\n",
        "import socket\n",
        "open('x')\n",
        "eval('1')\n",
        "exec('x=1')\n",
        "while True:\n    pass\n",
    ],
)
def test_forbidden_python_constructs_are_rejected(snippet: str) -> None:
    report = validate_python_source(snippet + DEFAULT_PYTHON_PROGRAM)
    assert not report.valid
    assert report.errors[0]["error_type"] == "PolicyError"


def test_recursion_and_unknown_bound_are_rejected() -> None:
    recursive = DEFAULT_PYTHON_PROGRAM.replace(
        "def answer_from_action(action):",
        "def answer_from_action(action):\n    return answer_from_action(action)",
    )
    assert not validate_python_source(recursive).valid
    unknown = DEFAULT_PYTHON_PROGRAM.replace(
        "for round_idx in range(max_rounds):",
        "for round_idx in iter(payload['agents']):",
    )
    report = validate_python_source(unknown)
    assert not report.valid
    assert any("bounded" in error["message"] for error in report.errors)


def test_authorized_model_configuration_must_be_used_directly() -> None:
    source = DEFAULT_PYTHON_PROGRAM.replace(
        'model_name=worker_cfg["model_name"],',
        'model_name="other-model",',
    )
    report = validate_python_source(source)
    assert not report.valid
    assert any(error["error_type"] == "APIError" for error in report.errors)


def test_cross_agent_and_combined_local_prompts_are_rejected() -> None:
    cross = DEFAULT_PYTHON_PROGRAM.replace(
        'agents[agent_id]["local_prompt"]',
        'agents[(agent_id + 1) % n_agents]["local_prompt"]',
        1,
    )
    assert any(
        error["error_type"] == "DataFlowError"
        for error in validate_python_source(cross).errors
    )
    combined = DEFAULT_PYTHON_PROGRAM.replace(
        'local_prompt = agents[agent_id]["local_prompt"]',
        'local_prompt = (agents[agent_id]["local_prompt"] + '
        'agents[(agent_id + 1) % n_agents]["local_prompt"])',
    )
    report = validate_python_source(combined)
    assert any("multiple local prompts" in error["message"] for error in report.errors)


def test_fake_canary_detects_header_based_cross_agent_leak() -> None:
    source = DEFAULT_PYTHON_PROGRAM.replace(
        '"PYTHON_AGENT_ID:" + str(agent_id)',
        '"PYTHON_AGENT_ID:" + str((agent_id + 1) % n_agents)',
    )
    assert validate_python_source(source).valid
    canaries = {str(i): f"CANARY_{i}_SECRET" for i in range(3)}
    payload = _payload()
    for item in payload["agents"]:
        item["local_prompt"] = canaries[str(item["agent_id"])]
    result = CodeProcessRunner().run(
        source,
        payload,
        agent_canaries=canaries,
    )
    assert not result.runtime_success
    assert result.failure["error_type"] == "DataFlowError"  # type: ignore[index]


@pytest.mark.parametrize(
    "source",
    [
        DEFAULT_PYTHON_PROGRAM.replace(
            "worker_prompt = action_contract + local_prompt",
            'worker_prompt = action_contract + local_prompt + "HIDDEN_CHANNEL"',
        ),
        DEFAULT_PYTHON_PROGRAM.replace(
            'updated_state.update(action["state"])',
            'updated_state.update(action["state"])\n'
            '                updated_state["unreported_cross_state"] = agent_id',
        ),
        DEFAULT_PYTHON_PROGRAM.replace(
            "sys.stdout.write(json.dumps(output))",
            'messages[0]["body"] = "body-not-delivered"\n'
            "    sys.stdout.write(json.dumps(output))",
        ),
        DEFAULT_PYTHON_PROGRAM.replace(
            "sys.stdout.write(json.dumps(output))",
            'submissions[0]["answer"] = 12345\n'
            "    sys.stdout.write(json.dumps(output))",
        ),
    ],
)
def test_runtime_ledger_rejects_hidden_prompt_state_or_message_channels(
    source: str,
) -> None:
    assert validate_python_source(source).valid
    result = CodeProcessRunner().run(source, _payload())
    assert not result.runtime_success
    assert result.failure["error_type"] == "DataFlowError"  # type: ignore[index]


def test_budget_and_program_usage_lies_fail_closed() -> None:
    exhausted = CodeProcessRunner().run(
        DEFAULT_PYTHON_PROGRAM,
        _payload(max_model_calls=2),
    )
    assert not exhausted.runtime_success
    assert exhausted.failure["error_type"] == "BudgetError"  # type: ignore[index]

    lying = DEFAULT_PYTHON_PROGRAM.replace(
        '"usage": usage,',
        '"usage": {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},',
    )
    result = CodeProcessRunner().run(lying, _payload())
    assert not result.runtime_success
    assert result.failure["error_type"] == "BudgetError"  # type: ignore[index]


def test_stdin_payload_rejects_private_or_unknown_fields() -> None:
    payload = _payload()
    payload["ground_truth"] = 9
    result = CodeProcessRunner().run(DEFAULT_PYTHON_PROGRAM, payload)
    assert not result.runtime_success
    assert result.failure["error_type"] == "APIError"  # type: ignore[index]
    assert "9" not in result.failure["message"]  # type: ignore[index]


def test_stdout_limit_is_enforced_during_child_execution() -> None:
    source = DEFAULT_PYTHON_PROGRAM.replace(
        "sys.stdout.write(json.dumps(output))",
        'output["submissions"][0]["answer"] = "x" * 5000\n'
        "    sys.stdout.write(json.dumps(output))",
    )
    assert validate_python_source(source).valid
    runner = CodeProcessRunner(PythonExecutionLimits(max_output_bytes=1024))
    result = runner.run(source, _payload())
    assert not result.runtime_success
    assert result.failure["error_type"] == "BudgetError"  # type: ignore[index]


def test_python_architect_prompts_are_goal_specific_and_clean() -> None:
    runtime = _runtime()
    sink = build_python_architect_prompt(
        request=_request("sink"),
        task_brief="Find a global statistic.",
        runtime=runtime,
    )
    all_agents = build_python_architect_prompt(
        request=_request("all_agents"),
        task_brief="Find a global statistic.",
        runtime=runtime,
    )
    assert sink != all_agents
    assert hashlib.sha256(sink.encode()).hexdigest() != hashlib.sha256(
        all_agents.encode()
    ).hexdigest()
    assert "selected_primary" in sink and "gather-only" in all_agents
    assert "independently" in all_agents and "non-primary" in sink
    assert not all_agents.lstrip().startswith("{")
    assert "Do not return JSON" in all_agents
    assert f"BEGIN_KNOWN_VALID_SCAFFOLD_{PYTHON_SCAFFOLD_VERSION}" in all_agents
    assert "EVOLVE-BLOCK-START: fallback_routing" in all_agents
    assert find_leakage_tokens(sink) == []
    assert find_leakage_tokens(all_agents) == []


def test_python_architect_scaffold_is_valid_and_blocks_are_balanced() -> None:
    scaffold = build_python_architect_scaffold()

    assert validate_python_source(scaffold).valid
    for block in ("worker_instruction", "fallback_routing", "submission_policy"):
        start = f"EVOLVE-BLOCK-START: {block}"
        end = f"EVOLVE-BLOCK-END: {block}"
        assert scaffold.count(start) == 1
        assert scaffold.count(end) == 1
        assert scaffold.index(start) < scaffold.index(end)
    assert "json.load(sys.stdin)" in scaffold
    assert "create_llm_client(" in scaffold
    assert "client.complete(" in scaffold
    assert "sys.stdout.write(" in scaffold


def test_python_repair_prompt_includes_known_valid_scaffold() -> None:
    prompt = build_python_repair_prompt(
        source='{"submissions": []}',
        failure={"error_type": "APIError", "message": "missing client.complete"},
        attempt=1,
        information_goal="all_agents",
    )

    assert f"BEGIN_KNOWN_VALID_SCAFFOLD_{PYTHON_SCAFFOLD_VERSION}" in prompt
    assert "return the scaffold unchanged" in prompt
    assert "missing client.complete" in prompt
    assert find_leakage_tokens(prompt) == []


def test_extract_python_source_accepts_raw_fenced_and_json_wrappers() -> None:
    raw, raw_format = extract_python_source(DEFAULT_PYTHON_PROGRAM)
    fenced, fenced_format = extract_python_source(
        f"Here is the program:\n```python\n{DEFAULT_PYTHON_PROGRAM}\n```"
    )
    wrapped, wrapped_format = extract_python_source(
        json.dumps(
            {
                "agents": [{"id": 0}],
                "main": DEFAULT_PYTHON_PROGRAM,
            }
        )
    )
    double_escaped, double_format = extract_python_source(
        json.dumps({"main": DEFAULT_PYTHON_PROGRAM.replace("\n", "\\n")})
    )

    assert raw == DEFAULT_PYTHON_PROGRAM.strip()
    assert raw_format == "raw_python"
    assert fenced == DEFAULT_PYTHON_PROGRAM.strip()
    assert fenced_format == "markdown_fence"
    assert wrapped == DEFAULT_PYTHON_PROGRAM.strip()
    assert wrapped_format == "json:main"
    assert double_escaped == DEFAULT_PYTHON_PROGRAM.replace("\n", "\\n").strip()
    assert double_format == "json:main"
    assert not validate_python_source(double_escaped).valid


def test_extract_python_source_rejects_structured_main_object() -> None:
    response = json.dumps(
        {
            "agents": [{"id": 0}],
            "main": {"execute": "for agent in agents: pass"},
        }
    )

    source, response_format = extract_python_source(response)

    assert source == response
    assert response_format == "unrecognized_json"
    assert not validate_python_source(source).valid


def test_json_wrapped_architect_source_executes_without_repair(tmp_path: Path) -> None:
    wrapped = json.dumps(
        {
            "agents": [{"id": 0, "state": {}}],
            "main": DEFAULT_PYTHON_PROGRAM,
        }
    )
    client = _ScriptedClient([wrapped])

    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=_payload(),
        output_dir=tmp_path,
        llm_client=client,
    )

    assert result.execution.runtime_success
    assert result.repair_model_calls == 0
    assert result.source == DEFAULT_PYTHON_PROGRAM.strip()
    assert result.attempts[0]["source_format"] == "json:main"
    assert (tmp_path / "architect_response.raw.txt").read_text() == wrapped
    trace = json.loads(
        (tmp_path / "response_normalization_trace.json").read_text()
    )
    assert trace[0]["response_format"] == "json:main"
    skill = make_skill_card(
        skill_id="wrapped_python",
        topology_name="python:wrapped",
        objective="balanced",
        operators=[],
        task_family="silo",
        evidence=[
            {
                "planner_mode": "python_generate",
                "python_source": result.source,
                "program_sha256": python_source_sha256(result.source),
                "ast_policy_version": "python_ast_v1",
                "execution_contract_version": "python_mas_v1",
                "program_validity": 1.0,
                "n_agents": 3,
                "information_goal": "all_agents",
                "provenance": "llm_generated_python",
            }
        ],
        expected_tradeoff={"mean_primary_loss": 0.0},
    )
    assert isinstance(skill.mode_payload, PythonSkillPayload)
    assert skill.mode_payload.source_code == DEFAULT_PYTHON_PROGRAM.strip()
    assert not skill.mode_payload.source_code.lstrip().startswith("{")


def test_child_env_forwards_worker_api_key(monkeypatch) -> None:
    """The sandbox must forward the worker's real credential into the subprocess.

    When ``api_key_env`` is null the subprocess falls back to the provider's
    default key env var (plain openai -> the OpenAI SDK's implicit
    OPENAI_API_KEY). Previously _child_env forwarded nothing in that case, so a
    real worker call failed with 'Missing credentials'. The fake dry-run needs
    no credential and must not receive one.
    """
    runner = CodeProcessRunner(
        PythonExecutionLimits(
            timeout_seconds=10,
            cpu_seconds=10,
            memory_mb=512,
            max_output_bytes=1_000_000,
        )
    )

    def _env(provider: str, api_key_env: str | None = None) -> dict:
        return runner._child_env(
            {"worker_llm": {"provider": provider, "api_key_env": api_key_env}}
        )

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    monkeypatch.setenv("CUSTOM_WORKER_KEY", "sk-test-custom")

    # openai + null api_key_env -> forward the SDK-default OPENAI_API_KEY.
    assert _env("openai").get("OPENAI_API_KEY") == "sk-test-openai"
    # provider-default mapping is honored (deepseek -> DEEPSEEK_API_KEY).
    assert _env("deepseek").get("DEEPSEEK_API_KEY") == "sk-test-deepseek"
    # an explicit api_key_env wins over the provider default.
    assert (
        _env("openai", "CUSTOM_WORKER_KEY").get("CUSTOM_WORKER_KEY")
        == "sk-test-custom"
    )
    # the fake dry-run worker needs no credential and must not receive one.
    assert "OPENAI_API_KEY" not in _env("fake")


def test_python_generation_requests_text_mode_not_forced_json(
    tmp_path: Path,
) -> None:
    """Architect/repair must request free-form text, not a forced JSON object.

    The OpenAI client otherwise pins ``response_format={"type": "json_object"}``,
    which forces the model to emit the stdout output schema (observed with
    gpt-4o-mini: ``{"submissions": [], ...}``) instead of raw Python source. The
    code-generation calls opt out via ``json_mode=False``; worker calls inside
    the generated program keep the JSON default. Here the first response is
    exactly that output schema (one honest repair), the second is the
    known-valid scaffold returned as raw Python.
    """
    output_schema_json = (
        '{"submissions": [], "rounds_executed": 0, '
        '"messages": [], "usage": {}, "errors": []}'
    )
    client = _ScriptedClient(
        [output_schema_json, build_python_architect_scaffold()]
    )

    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=_payload(),
        output_dir=tmp_path,
        llm_client=client,
    )

    # Both code-generation calls (architect + one repair) must opt out of the
    # forced-JSON response format so the provider can return raw Python source.
    assert client.json_modes == [False, False]
    assert result.repair_model_calls == 1
    # The forced-JSON output schema is rejected honestly; the raw scaffold is
    # then extracted as raw_python (never as an output object) and executes.
    assert result.attempts[0]["source_format"] == "unrecognized_json"
    assert result.attempts[-1]["source_format"] == "raw_python"
    assert result.source == build_python_architect_scaffold().strip()
    assert not result.source.lstrip().startswith("{")
    assert result.execution.runtime_success
    assert result.execution.authoritative_usage.model_calls > 0


def test_react_repairs_syntax_once_then_executes(tmp_path: Path) -> None:
    client = _ScriptedClient(["def broken(", DEFAULT_PYTHON_PROGRAM])
    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=_payload(),
        output_dir=tmp_path,
        llm_client=client,
    )
    assert result.execution.runtime_success
    assert result.repair_model_calls == 1
    assert len(result.attempts) == 2
    assert "SyntaxError" in client.prompts[1]
    assert (tmp_path / "attempt_00.py").exists()
    assert (tmp_path / "attempt_01_validation.json").exists()


def test_repair_accepts_json_wrapped_replacement_source(tmp_path: Path) -> None:
    client = _ScriptedClient(
        ["def broken(", json.dumps({"main": DEFAULT_PYTHON_PROGRAM})]
    )

    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=_payload(),
        output_dir=tmp_path,
        llm_client=client,
    )

    assert result.execution.runtime_success
    assert result.repair_model_calls == 1
    assert result.attempts[1]["source_format"] == "json:main"
    repair_trace = json.loads((tmp_path / "repair_trace.json").read_text())
    assert repair_trace[0]["response_format"] == "json:main"


def test_three_repairs_fail_honestly_without_fallback(tmp_path: Path) -> None:
    client = _ScriptedClient(["def broken("] * 4)
    with pytest.raises(PythonGenerationError) as excinfo:
        plan_and_execute_python(
            request=_request(),
            runtime=_runtime(python_repair_attempts=3),
            skill_bank=SkillBank(),
            task_adapter=_TaskAdapter(),
            execution_payload=_payload(),
            output_dir=tmp_path,
            llm_client=client,
        )
    assert excinfo.value.error_type == "SyntaxError"
    assert len(client.prompts) == 4
    report = json.loads((tmp_path / "execution_report.json").read_text())
    assert report["runtime_success"] is False
    assert report["repair_attempts"] == 3
    assert report["failure_category"] == "SyntaxError"
    assert "named" not in report["provenance"]


def test_fake_end_to_end_is_honest_and_artifacts_are_redacted(tmp_path: Path) -> None:
    payload = _payload()
    secret = "SUPER_SECRET_LOCAL_PROMPT_987654"
    payload["agents"][0]["local_prompt"] = secret
    result = plan_and_execute_python(
        request=_request(),
        runtime=_runtime(llm_provider="fake", model_name="fake"),
        skill_bank=SkillBank(),
        task_adapter=_TaskAdapter(),
        execution_payload=payload,
        output_dir=tmp_path,
    )
    assert result.provenance == "fake"
    assert result.execution.output is not None
    assert all(item.answer is None for item in result.execution.output.submissions)
    required = {
        "architect_prompt.txt",
        "attempt_00.py",
        "attempt_00_validation.json",
        "final_program.py",
        "stdin_payload.redacted.json",
        "stdout.json",
        "stderr.redacted.txt",
        "repair_trace.json",
        "response_normalization_trace.json",
        "execution_report.json",
        "program_hash.txt",
    }
    assert required <= {path.name for path in tmp_path.iterdir()}
    persisted = "\n".join(
        path.read_text(errors="replace") for path in tmp_path.iterdir() if path.is_file()
    )
    assert secret not in persisted
    assert "SUPER_SECRET" not in persisted
    redacted_stdout = json.loads((tmp_path / "stdout.json").read_text())
    assert all(item["answer"] is None for item in redacted_stdout["submissions"])


def _skill(
    skill_id: str,
    *,
    planner_mode: str,
    provenance: str,
    source_code: str | None = None,
    counterexample: bool = False,
) -> SkillCard:
    policy: dict[str, object] = {
        "planner_mode": planner_mode,
        "topology_name": f"{planner_mode}:{skill_id}",
    }
    if source_code is not None:
        policy.update(
            {
                "source_code": source_code,
                "ast_policy_version": "python_ast_v1",
                "execution_contract_version": "python_mas_v1",
            }
        )
    spec = ProtocolGraphSpec(
        name=f"{planner_mode}:{skill_id}",
        n_agents=3,
        steps=[ProtocolStepSpec(transmissions=[(0, 1), (1, 2)])],
        metadata={"generated_graph": True},
    ).model_dump(mode="json")
    mode_payload = None
    if planner_mode == "python_generate" and source_code is not None:
        mode_payload = PythonSkillPayload(
            source_code=source_code,
            ast_policy_version="python_ast_v1",
            execution_contract_version="python_mas_v1",
        )
    elif planner_mode == "graph_generate":
        mode_payload = GraphSkillPayload(
            topology_name=f"{planner_mode}:{skill_id}",
            protocol_spec=spec,
        )
    elif planner_mode == "program_generate":
        phase_program = {
            "format": "phase_program_v1",
            "information_goal": "all_agents",
            "phases": [{"kind": "broadcast", "hub": 0}],
        }
        mode_payload = PhaseProgramSkillPayload(
            topology_name=f"{planner_mode}:{skill_id}",
            phase_program=phase_program,
            compiled_protocol_spec={
                **spec,
                "metadata": {
                    "generated_graph": True,
                    "program_mode": "program_generate",
                    "phase_program": phase_program,
                },
            },
        )
    return SkillCard(
        skill_id=skill_id,
        task_family="silo",
        trigger={
            "information_goal": "all_agents",
            "planner_mode": planner_mode,
        },
        information_goal="all_agents",
        provenance=provenance,
        mode_payload=mode_payload,
        organization_policy=policy,
        evidence=[{"seed": 1}],
        tags=["counterexample"] if counterexample else [],
    )


def test_python_skill_retrieval_is_bidirectionally_isolated() -> None:
    bank = SkillBank(
        skills=[
            _skill(
                "python",
                planner_mode="python_generate",
                provenance="llm_generated_python",
                source_code=DEFAULT_PYTHON_PROGRAM,
            ),
            _skill(
                "graph",
                planner_mode="graph_generate",
                provenance="llm_generated",
            ),
            _skill(
                "program",
                planner_mode="program_generate",
                provenance="program_generated",
            ),
            _skill(
                "bad-python",
                planner_mode="python_generate",
                provenance="llm_generated_python",
                source_code="def broken(",
                counterexample=True,
            ),
        ]
    )
    python_ids = {skill.skill_id for skill in bank.retrieve(_request())}
    assert python_ids == {"python"}
    graph_request = _request().model_copy(
        update={
            "planner_mode": "graph_generate",
            "provenance_allowlist": ["llm_generated", "skill_replay"],
        }
    )
    program_request = _request().model_copy(
        update={
            "planner_mode": "program_generate",
            "provenance_allowlist": ["program_generated", "skill_replay"],
        }
    )
    assert {skill.skill_id for skill in bank.retrieve(graph_request)} == {"graph"}
    assert {skill.skill_id for skill in bank.retrieve(program_request)} == {"program"}
    assert {skill.skill_id for skill in bank.retrieve_avoid(_request())} == {
        "bad-python"
    }


def test_output_schema_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        PythonProgramOutput.model_validate(
            {
                "submissions": [],
                "rounds_executed": 0,
                "messages": [],
                "usage": {
                    "model_calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                },
                "errors": [],
                "private_state": {},
            }
        )
