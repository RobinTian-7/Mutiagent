"""M9: instruction-carrying replay — spec field, runner injection, rewrite.

Dev-4 datum: step descriptions never reach agents, so verbatim replay cannot
express "each agent computes its OWN small segment". M9 threads optional
receiver-facing instructions spec -> schedule -> merge prompt, and rewrites
them per task at deployment (SkillLens REWRITE; AWM adaptation).
"""

from __future__ import annotations

from pathlib import Path

from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    _rewrite_replay_instructions,
)
from exp_graph.mas.schemas import MASRuntimeConfig
from exp_graph.protocols.spec import (
    ProtocolGraphSpec,
    ProtocolStepSpec,
    build_protocol_schedule_from_spec,
)
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_protocol import SiloProtocolAdapter

DATA = Path(__file__).parent / "data"


def _spec(instruction: str | None) -> ProtocolGraphSpec:
    return ProtocolGraphSpec(
        name="pair",
        n_agents=2,
        steps=[
            ProtocolStepSpec(
                transmissions=[(0, 1)], description="fwd",
                operator="replay", instruction=instruction,
            )
        ],
        metadata={"graph_type": "temporal_dag", "selected_primary": 1},
    )


def test_spec_field_roundtrip_and_compile():
    spec = _spec("compute your segment only")
    data = spec.model_dump(mode="json")
    again = ProtocolGraphSpec.model_validate(data)
    assert again.steps[0].instruction == "compute your segment only"
    schedule = build_protocol_schedule_from_spec(again)
    assert schedule[0].instruction == "compute your segment only"
    assert build_protocol_schedule_from_spec(_spec(None))[0].instruction is None


from exp_graph.llm.base import LLMResponse


class _CapturingClient:
    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return LLMResponse(
            text='{"merged_belief": {}, "final_answer": "1"}',
            usage={"prompt_tokens": 1, "completion_tokens": 1},
        )


def _run(instruction: str | None, enable: bool) -> list[str]:
    inst = next(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )
    adapter = SiloProtocolAdapter(inst)
    client = _CapturingClient()
    ProtocolRunner(
        config=ProtocolRunnerConfig(
            topology_name="generated:pair", n_agents=2, seed=1,
            merge_mode="llm_full_merge", init_mode="deterministic",
            llm_provider="openai", model_name="m",
            protocol_spec=_spec(instruction),
            enable_step_instructions=enable,
        ),
        task_adapter=adapter,
        global_task=adapter.build_global_task(),
        llm_client=client,
    ).run()
    return client.prompts


def test_runner_injects_instruction_when_enabled():
    prompts = _run("compute your segment only", True)
    assert any(p.startswith("Step role for you this round: compute your segment only") for p in prompts)


def test_runner_prompt_unchanged_without_flag_or_instruction():
    base = _run(None, True)
    off = _run("compute your segment only", False)
    none_on = _run(None, False)
    for prompts in (off, none_on):
        assert prompts == base, "prompt must be byte-identical when M9 is inert"
    assert not any("Step role for you" in p for p in base)


class _ScriptedRewrite:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def complete(self, prompt, **kwargs):
        self.calls += 1
        self.last_prompt = prompt

        class R:
            pass

        r = R()
        r.text = self.text
        return r


def _plan() -> GeneratedGraphPlan:
    return GeneratedGraphPlan(
        candidate_id="skill_x", name="pair", graph_type="temporal_dag",
        n_agents=2, selected_primary=1,
        steps=[GeneratedGraphStep(description="fwd", edges=[(0, 1)], operator_hint="skill_replay")],
        rationale="replay",
    )


def test_rewrite_attaches_instructions():
    plan = _plan()
    client = _ScriptedRewrite('{"instructions": ["compute local diffs; forward your last raw element"]}')
    runtime = MASRuntimeConfig(llm_provider="openai", model_name="m", replay_instruction_rewrite=True)
    _rewrite_replay_instructions([plan], runtime=runtime, llm_client=client, task_brief="Diff array task")
    assert plan.steps[0].instruction.startswith("compute local diffs")
    assert "Diff array task" in client.last_prompt
    assert "silo" not in client.last_prompt.lower()


def test_rewrite_junk_or_disabled_is_noop():
    plan = _plan()
    runtime_off = MASRuntimeConfig(llm_provider="openai", model_name="m")
    _rewrite_replay_instructions([plan], runtime=runtime_off, llm_client=_ScriptedRewrite("x"), task_brief="t")
    assert plan.steps[0].instruction is None
    runtime_on = MASRuntimeConfig(llm_provider="openai", model_name="m", replay_instruction_rewrite=True)
    _rewrite_replay_instructions([plan], runtime=runtime_on, llm_client=_ScriptedRewrite("not json"), task_brief="t")
    assert plan.steps[0].instruction is None
