"""Schemas for the outer MAS planner and skill-evolution layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from exp_graph.protocols import ProtocolGraphSpec

ObjectiveName = Literal["accuracy_first", "budget_first", "balanced"]
BudgetLevel = Literal["loose", "normal", "tight"]
PlannerMode = Literal["topology_select", "operator_compose", "graph_generate"]
LLMRoleName = Literal["emperor", "soldier", "minister"]
PatchAction = Literal["add", "merge", "discard", "deprecate"]
EvidenceSourceType = Literal["aggregate", "run", "trace", "insight", "manual"]
EvidenceStatus = Literal["observed", "placeholder", "deprecated"]
InsightType = Literal[
    "design_principle",
    "tradeoff",
    "scaling_pattern",
    "dynamics_pattern",
    "risk_pattern",
    "operator_rule",
    "hypothesis",
    "followup_experiment",
]
InsightStatus = Literal["observed", "inferred", "hypothesis", "rejected"]


class ObjectiveSpec(BaseModel):
    """Objective weights for selecting topology skills."""

    name: ObjectiveName = "balanced"
    accuracy_weight: float = 0.5
    cost_weight: float = 0.35
    stability_weight: float = 0.15

    @classmethod
    def from_name(cls, name: ObjectiveName) -> "ObjectiveSpec":
        if name == "accuracy_first":
            return cls(
                name=name,
                accuracy_weight=0.70,
                cost_weight=0.15,
                stability_weight=0.15,
            )
        if name == "budget_first":
            return cls(
                name=name,
                accuracy_weight=0.25,
                cost_weight=0.65,
                stability_weight=0.10,
            )
        return cls(name=name)


class BudgetSpec(BaseModel):
    """Budget constraints used by the emperor planner."""

    level: BudgetLevel = "normal"
    max_messages: int | None = None
    max_token_cost: int | None = None


class RoleLLMConfig(BaseModel):
    """OpenAI-compatible model endpoint settings for one MAS role."""

    platform: str = "openai"
    model_name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    thinking_enabled: bool | None = None


class RoleLLMProfiles(BaseModel):
    """Optional role-specific LLM profiles for the outer MAS pipeline."""

    emperor: RoleLLMConfig | None = None
    soldier: RoleLLMConfig | None = None
    minister: RoleLLMConfig | None = None

    def get_role(self, role: LLMRoleName) -> RoleLLMConfig | None:
        return getattr(self, role)


class TopologyStructure(BaseModel):
    """Compact description of the actual protocol structure executed by soldiers."""

    structure_hash: str
    topology_name: str
    n_agents: int
    selected_primary: int | str | None = None
    total_steps: int
    total_messages: int
    steps: list[dict[str, object]] = Field(default_factory=list)


class MASRuntimeConfig(BaseModel):
    """Runtime options for a transparent real/fake LLM MAS pipeline."""

    llm_provider: str = "fake"
    model_name: str = "fake"
    temperature: float = 0.0
    json_retry_attempts: int = 2
    allow_deterministic_repair: bool = True
    max_parallel_agents: int = 1
    max_parallel_ministers: int = 1
    trace_enabled: bool = False
    retain_traces: bool = False
    trace_dir: str | None = None
    verbose_events: bool = False
    output_dir: str | None = None
    value_min: int = 0
    value_max: int = 9
    graph_search_mode: str = "single"
    num_graph_candidates: int = 1
    graph_top_k: int = 1
    graph_candidate_score_mode: str = "objective"
    graph_max_steps: int = 4
    graph_max_messages: int = 32
    graph_max_receiver_fan_in: int = 4
    graph_repair_attempts: int = 1
    graph_validation_seeds: list[int] = Field(default_factory=list)
    role_llm_profiles: RoleLLMProfiles | None = None
    role_llm_config_path: str | None = None

    @model_validator(mode="after")
    def validate_value_range(self) -> "MASRuntimeConfig":
        if self.value_max < self.value_min:
            raise ValueError("value_max must be greater than or equal to value_min")
        return self


class PlannerRequest(BaseModel):
    """Input to the emperor planner."""

    task_family: str = "count_frequency"
    n_agents: int
    array_size: int | None = None
    objective: ObjectiveSpec = Field(
        default_factory=lambda: ObjectiveSpec.from_name("balanced")
    )
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    planner_mode: PlannerMode = "topology_select"
    merge_mode: str = "deterministic"
    init_mode: str = "deterministic"
    allowed_topologies: list[str] | None = None

    @model_validator(mode="after")
    def validate_request(self) -> "PlannerRequest":
        if self.n_agents < 1:
            raise ValueError("n_agents must be positive")
        return self

    @classmethod
    def from_names(
        cls,
        *,
        n_agents: int,
        objective: ObjectiveName = "balanced",
        budget: BudgetLevel = "normal",
        planner_mode: PlannerMode = "topology_select",
        **kwargs,
    ) -> "PlannerRequest":
        return cls(
            n_agents=n_agents,
            objective=ObjectiveSpec.from_name(objective),
            budget=BudgetSpec(level=budget),
            planner_mode=planner_mode,
            **kwargs,
        )


class SkillCard(BaseModel):
    """Versioned reusable organization skill for MAS planning."""

    skill_id: str
    version: str = "0.1.0"
    task_family: str = "count_frequency"
    skill_type: str = "planner_organization_policy"
    trigger: dict[str, object] = Field(default_factory=dict)
    objective: ObjectiveName = "balanced"
    organization_policy: dict[str, object] = Field(default_factory=dict)
    expected_tradeoff: dict[str, object] = Field(default_factory=dict)
    expected_dynamics: dict[str, object] = Field(default_factory=dict)
    design_insights: list[dict[str, object]] = Field(default_factory=list)
    risk_notes: list[dict[str, object]] = Field(default_factory=list)
    failure_modes: list[dict[str, object]] = Field(default_factory=list)
    evidence: list[dict[str, object]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    fallback: dict[str, object] = Field(default_factory=dict)
    counterexamples: list[dict[str, object]] = Field(default_factory=list)
    hypotheses: list[dict[str, object]] = Field(default_factory=list)
    confidence: dict[str, object] = Field(default_factory=dict)
    revision_history: list[dict[str, object]] = Field(default_factory=list)
    validation_plan: list[dict[str, object]] = Field(default_factory=list)
    update_rule: str = "batch_consolidate"
    tags: list[str] = Field(default_factory=list)

    @property
    def topology_name(self) -> str | None:
        value = self.organization_policy.get("topology_name")
        return str(value) if value else None

    @property
    def operators(self) -> list[str]:
        value = self.organization_policy.get("operators", [])
        return [str(item) for item in value] if isinstance(value, list) else []


class SkillPatch(BaseModel):
    """Candidate update proposed by a minister analyst."""

    patch_id: str
    action: PatchAction
    target_skill_id: str | None = None
    candidate_skill: SkillCard | None = None
    evidence: list[dict[str, object]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    update: dict[str, object] = Field(default_factory=dict)
    lesson: str = ""
    confidence: float = 0.0
    source: str = "result_analyst"


class EvidenceRecord(BaseModel):
    """Append-only evidence used to evolve planner skills."""

    evidence_id: str
    source_dir: str = ""
    source_type: EvidenceSourceType
    task_family: str = "count_frequency"
    topology_name: str = ""
    n_agents: int | None = None
    seed: int | None = None
    metrics: dict[str, object] = Field(default_factory=dict)
    dynamics: dict[str, object] = Field(default_factory=dict)
    risk_tags: list[str] = Field(default_factory=list)
    status: EvidenceStatus = "observed"
    created_at: str = ""


class SkillRevision(BaseModel):
    """One versioned skill-bank update entry."""

    revision_id: str
    skill_id: str
    from_version: str | None = None
    to_version: str | None = None
    batch_id: str
    patch_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    changed_fields: list[str] = Field(default_factory=list)
    summary: str = ""
    created_at: str = ""


class TraceDynamicsSummary(BaseModel):
    """Aggregated trace-to-skill dynamics for one topology/run group."""

    topology_name: str
    n_agents: int | None = None
    seed: int | None = None
    coverage_growth: dict[str, object] = Field(default_factory=dict)
    aggregation_reliability: dict[str, object] = Field(default_factory=dict)
    merge_quality: dict[str, object] = Field(default_factory=dict)
    risk_tags: list[str] = Field(default_factory=list)


class MASInsight(BaseModel):
    """Evidence-grounded LLM insight about MAS design."""

    insight_id: str
    title: str
    insight_type: InsightType
    claim_status: InsightStatus = "hypothesis"
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    metric_snapshot: dict[str, object] = Field(default_factory=dict)
    affected_skills: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    operation_recommendations: list[dict[str, object]] = Field(default_factory=list)
    condition_buckets: list[dict[str, object]] = Field(default_factory=list)
    confidence: float = 0.0
    falsification_test: str = ""


class InsightReport(BaseModel):
    """Post-experiment MAS design insight report."""

    report_id: str
    experiment_id: str
    executive_summary: str = ""
    key_insights: list[MASInsight] = Field(default_factory=list)
    rejected_insights: list[dict[str, object]] = Field(default_factory=list)
    skill_update_recommendations: list[SkillPatch] = Field(default_factory=list)
    followup_experiments: list[dict[str, object]] = Field(default_factory=list)


class MinisterSummary(BaseModel):
    """Printable post-run minister summary."""

    run_id: str
    final_rmse: float | None = None
    exact_match: bool | None = None
    total_messages: int = 0
    total_model_calls: int = 0
    token_cost: int = 0
    patch_counts: dict[str, int] = Field(default_factory=dict)
    lessons: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)


class EvolutionBatch(BaseModel):
    """Batch of minister patches to consolidate after experiments."""

    batch_id: str
    patches: list[SkillPatch] = Field(default_factory=list)
    summary: str = ""


class EvolutionResult(BaseModel):
    """Result of applying one batch of patches to a skill bank."""

    batch_id: str
    counts: dict[str, int] = Field(default_factory=dict)
    revisions: list[SkillRevision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MASPlan(BaseModel):
    """Planner output consumed by MASProtocolRunner."""

    planner_mode: PlannerMode
    topology_name: str
    skill_id: str | None = None
    operators: list[str] = Field(default_factory=list)
    protocol_spec: ProtocolGraphSpec | None = None
    config_overrides: dict[str, object] = Field(default_factory=dict)
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    fallback_skill_id: str | None = None
    alternatives: list[dict[str, object]] = Field(default_factory=list)
    rationale: str = ""
