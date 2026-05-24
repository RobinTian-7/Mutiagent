from __future__ import annotations

from pathlib import Path

from exp_graph.llm.base import LLMResponse
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.mas.graph_generation import plan_free_graph
from exp_graph.mas.insights import LLMInsightMinister
from exp_graph.mas.llm_planner import LLMEmperorPlanner
from exp_graph.mas.pipeline import run_mas_pipeline
from exp_graph.mas.schemas import (
    MASRuntimeConfig,
    PlannerRequest,
    RoleLLMConfig,
    RoleLLMProfiles,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.tasks import CountFrequencyTaskAdapter


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


class CapturingClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "temperature": temperature,
            }
        )
        return LLMResponse(text=self.text)


class CapturingFakeLLMClient(FakeLLMClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "model_name": model_name,
                "temperature": temperature,
            }
        )
        return super().complete(prompt, model_name, temperature)


def test_emperor_planner_uses_emperor_role_model() -> None:
    client = CapturingClient(
        """
        {
          "planner_mode": "topology_select",
          "topology_name": "tree",
          "operators": ["tree_reduce"],
          "rationale": "route to a sink"
        }
        """
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="legacy-model",
        role_llm_profiles=RoleLLMProfiles(
            emperor=RoleLLMConfig(
                platform="openai",
                model_name="emperor-model",
                temperature=0.2,
            )
        ),
    )

    planner = LLMEmperorPlanner(
        skill_bank=SkillBank([]),
        runtime=runtime,
        llm_client=client,
    )
    plan = planner.plan(
        PlannerRequest.from_names(n_agents=4, planner_mode="topology_select")
    )

    assert plan.topology_name == "tree"
    assert client.calls[0]["model_name"] == "emperor-model"
    assert client.calls[0]["temperature"] == 0.2


def test_protocol_pipeline_uses_soldier_role_client_for_runner_merge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    soldier_client = CapturingFakeLLMClient()

    def fake_create_role_client(runtime: MASRuntimeConfig, role: str):
        assert role == "soldier"
        return soldier_client

    monkeypatch.setattr(
        "exp_graph.mas.pipeline.create_role_llm_client",
        fake_create_role_client,
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="legacy-model",
        output_dir=str(tmp_path),
        role_llm_profiles=RoleLLMProfiles(
            soldier=RoleLLMConfig(
                platform="openai",
                model_name="soldier-model",
                thinking_enabled=False,
            )
        ),
    )
    request = PlannerRequest.from_names(
        n_agents=2,
        objective="accuracy_first",
        planner_mode="topology_select",
        array_size=8,
        merge_mode="llm_full_merge",
        init_mode="deterministic",
    )

    result = run_mas_pipeline(
        request=request,
        runtime=runtime,
        skill_bank=SkillBank.load_dir(SKILL_DIR),
        seed=1,
        planner_policy="fixed_topology",
        fixed_topology="tree",
    )

    assert soldier_client.calls
    assert {call["model_name"] for call in soldier_client.calls} == {"soldier-model"}
    assert result.protocol_result.config.model_name == "soldier-model"
    assert result.protocol_result.config.llm_provider == "openai"


def test_minister_uses_minister_role_model() -> None:
    client = CapturingClient(
        """
        {
          "report_id": "r1",
          "experiment_id": "exp1",
          "executive_summary": "done",
          "key_insights": []
        }
        """
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="legacy-model",
        role_llm_profiles=RoleLLMProfiles(
            minister=RoleLLMConfig(
                platform="openai",
                model_name="minister-model",
                temperature=0.3,
            )
        ),
    )

    report = LLMInsightMinister(runtime=runtime, llm_client=client).analyze(
        evidence_pack={"experiment_id": "exp1", "topologies": {}},
        skill_bank=SkillBank([]),
    )

    assert report.report_id == "r1"
    assert client.calls[0]["model_name"] == "minister-model"
    assert client.calls[0]["temperature"] == 0.3


def test_free_graph_generation_uses_emperor_and_probe_evaluation_uses_soldier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    emperor_client = CapturingClient(
        """
        {
          "candidates": [
            {
              "candidate_id": "e1",
              "name": "emperor_graph",
              "n_agents": 2,
              "selected_primary": 1,
              "steps": [
                {
                  "description": "send shard to sink",
                  "edges": [[0, 1]]
                }
              ]
            }
          ]
        }
        """
    )
    soldier_client = CapturingFakeLLMClient()

    def fake_create_role_client(runtime: MASRuntimeConfig, role: str):
        assert role == "soldier"
        return soldier_client

    monkeypatch.setattr(
        "exp_graph.mas.graph_generation.create_role_llm_client",
        fake_create_role_client,
    )
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="legacy-model",
        graph_search_mode="topk",
        num_graph_candidates=1,
        graph_validation_seeds=[1],
        role_llm_profiles=RoleLLMProfiles(
            emperor=RoleLLMConfig(platform="openai", model_name="emperor-model"),
            soldier=RoleLLMConfig(
                platform="openai",
                model_name="soldier-model",
                thinking_enabled=False,
            ),
        ),
    )
    request = PlannerRequest.from_names(
        n_agents=2,
        objective="accuracy_first",
        planner_mode="graph_generate",
        array_size=8,
        merge_mode="llm_full_merge",
        init_mode="deterministic",
    )

    result = plan_free_graph(
        request=request,
        runtime=runtime,
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
        llm_client=emperor_client,
    )

    assert result.selected_candidate_id == "e1"
    assert emperor_client.calls[0]["model_name"] == "emperor-model"
    assert soldier_client.calls
    assert {call["model_name"] for call in soldier_client.calls} == {"soldier-model"}
