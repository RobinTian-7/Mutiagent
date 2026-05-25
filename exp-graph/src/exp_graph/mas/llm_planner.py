"""LLM-backed emperor planner constrained by versioned planner skills."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from exp_graph.llm.base import LLMClient, LLMResponse
from exp_graph.mas.operators import compose_protocol_from_operators
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.role_llm import create_role_llm_client, resolve_role_llm_config
from exp_graph.mas.schemas import MASPlan, MASRuntimeConfig, PlannerRequest, SkillCard
from exp_graph.mas.skill_bank import SkillBank


class LLMEmperorPlanner:
    """Use planner skills as context, then validate/fallback to deterministic plans."""

    def __init__(
        self,
        *,
        skill_bank: SkillBank,
        runtime: MASRuntimeConfig,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.skill_bank = skill_bank
        self.runtime = runtime
        self.deterministic = EmperorPlanner(skill_bank)
        self.llm_client = llm_client
        self.last_raw_response: LLMResponse | None = None
        self.last_fallback_reason: str | None = None

    def plan(self, request: PlannerRequest) -> MASPlan:
        """Return a validated MASPlan, falling back safely when needed."""
        self.last_raw_response = None
        self.last_fallback_reason = None
        role_llm = resolve_role_llm_config(self.runtime, "emperor")
        if role_llm.platform == "fake":
            return self._fallback_plan(
                request,
                reason="fake provider uses deterministic emperor planner",
            )
        try:
            client = self.llm_client or create_role_llm_client(self.runtime, "emperor")
            prompt = build_emperor_prompt(
                request=request,
                positive_skills=self.skill_bank.retrieve(request),
                avoid_skills=[
                    skill
                    for skill in self.skill_bank
                    if skill.skill_id.startswith("cf_avoid_")
                ],
            )
            response = client.complete(
                prompt,
                model_name=role_llm.model_name,
                temperature=role_llm.temperature,
            )
            self.last_raw_response = response
            plan = parse_llm_plan_response(response.text, request)
            return self._validate_or_repair_plan(plan, request)
        except Exception as exc:  # pragma: no cover - exercised by smoke/manual paths.
            return self._fallback_plan(request, reason=f"llm planner failed: {exc}")

    def _validate_or_repair_plan(
        self,
        plan_data: dict[str, Any],
        request: PlannerRequest,
    ) -> MASPlan:
        try:
            plan = MASPlan.model_validate(plan_data)
        except ValidationError as exc:
            return self._fallback_plan(request, reason=f"invalid MASPlan JSON: {exc}")
        if not plan.topology_name and plan.protocol_spec is None:
            return self._fallback_plan(request, reason="plan omitted topology/protocol")
        if plan.protocol_spec is None and plan.operators and request.planner_mode in {
            "operator_compose",
            "graph_generate",
        }:
            try:
                spec = compose_protocol_from_operators(
                    name=f"llm_{request.objective.name}_{request.n_agents}",
                    n_agents=request.n_agents,
                    operators=plan.operators,
                    max_messages=request.budget.max_messages,
                )
                plan = plan.model_copy(
                    update={
                        "protocol_spec": spec,
                        "topology_name": str(
                            spec.metadata.get(
                                "compiled_from_topology",
                                plan.topology_name,
                            )
                        ),
                        "config_overrides": {
                            **plan.config_overrides,
                            "protocol_spec": spec,
                        },
                    }
                )
            except Exception as exc:
                return self._fallback_plan(
                    request,
                    reason=f"operator composition failed: {exc}",
                )
        return plan

    def _fallback_plan(self, request: PlannerRequest, *, reason: str) -> MASPlan:
        self.last_fallback_reason = reason
        plan = self.deterministic.plan(request)
        return plan.model_copy(
            update={
                "rationale": f"{plan.rationale} [emperor-plan-fallback: {reason}]",
            }
        )


def build_emperor_prompt(
    *,
    request: PlannerRequest,
    positive_skills: list[SkillCard],
    avoid_skills: list[SkillCard],
) -> str:
    """Build a compact JSON-only prompt for the emperor planner."""
    payload = {
        "role": (
            "You are a multi-agent system organization planner. Choose or compose "
            "the communication topology and protocol operators for an LLM-based "
            "MAS; do not solve the task itself."
        ),
        "mission": (
            "Use evidence-backed skills to choose an organization that improves "
            "task accuracy under the requested budget. When free graph generation "
            "is requested, prefer explicit communication structure over simply "
            "naming a familiar topology."
        ),
        "request": request.model_dump(mode="json"),
        "positive_skills": [_skill_context(skill) for skill in positive_skills[:6]],
        "avoid_or_counterexample_skills": [
            _skill_context(skill) for skill in avoid_skills[:4]
        ],
        "planning_responsibilities": [
            "Select topology or operators based on evidence, objective, n_agents, and budget.",
            "Treat avoid skills as concrete failure modes to route around.",
            "Use skill design_insights, structure_features, and operation_recommendations as direct topology operations, not just as topology_name labels.",
            "Respect trigger condition buckets such as agent_bucket and array_size_bucket when selecting a skill.",
            "Explain the expected information flow: who aggregates, who broadcasts, and where the final answer should reside.",
            "Prefer structures that preserve source coverage and provenance for sharded count-frequency tasks.",
        ],
        "required_top_level_json_object": {
            "planner_mode": request.planner_mode,
            "topology_name": "existing topology name or compiled topology",
            "skill_id": "selected skill id or null",
            "operators": ["local_solve", "tree_reduce"],
            "score": 0.0,
            "score_breakdown": {"accuracy_fit": 0.0, "cost_fit": 0.0},
            "fallback_skill_id": "fallback skill id or null",
            "alternatives": [],
            "rationale": "short evidence-grounded explanation",
        },
        "rules": [
            "Return one json object only.",
            "The returned json object must contain planner_mode, topology_name, "
            "operators, and rationale at the top level.",
            "Do not wrap the answer in output_schema, schema, plan, or answer.",
            "Use avoid skills only as risk constraints, never as selected skill_id.",
            "All nontrivial organizations must compile to finite protocol steps.",
            "Prefer evidence-backed skills over unvalidated hypotheses.",
            "Do not select a topology only because it is cheap; accuracy and coverage must remain plausible.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def parse_llm_plan_response(text: str, request: PlannerRequest) -> dict[str, Any]:
    """Parse a model response into a MASPlan-compatible dict."""
    data = _loads_json_object(text)
    for wrapper_key in ("plan", "mas_plan", "answer"):
        wrapped = data.get(wrapper_key)
        if isinstance(wrapped, dict):
            data = wrapped
            break
    if "output_schema" in data and "topology_name" not in data:
        raise ValueError("LLM echoed the output schema instead of a MASPlan")
    if "required_top_level_json_object" in data and "topology_name" not in data:
        raise ValueError("LLM echoed the required schema instead of a MASPlan")
    data.setdefault("planner_mode", request.planner_mode)
    data.setdefault("operators", [])
    data.setdefault("config_overrides", {})
    data.setdefault("alternatives", [])
    data.setdefault("score", 0.0)
    data.setdefault("score_breakdown", {})
    data.setdefault("rationale", "")
    return data


def _skill_context(skill: SkillCard) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "version": skill.version,
        "objective": skill.objective,
        "trigger": skill.trigger,
        "organization_policy": skill.organization_policy,
        "expected_tradeoff": skill.expected_tradeoff,
        "expected_dynamics": skill.expected_dynamics,
        "design_insights": skill.design_insights[-6:],
        "risk_notes": skill.risk_notes[-5:],
        "counterexamples": skill.counterexamples[-5:],
        "fallback": skill.fallback,
        "hypotheses": skill.hypotheses[-5:],
        "confidence": skill.confidence,
        "evidence_refs": skill.evidence_refs[-12:],
    }


def _loads_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data
