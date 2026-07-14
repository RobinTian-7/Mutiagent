"""Schemas for the outer MAS planner and skill-evolution layer."""

# ============================================================
# 【模块导读】外层 MAS 规划器与技能进化层的 Schema 定义。
# - 定义皇帝(规划 LLM)的规划请求/输出、目标与预算规格、技能卡与补丁、
#   证据记录、进化批次/结果、运行时配置与各角色 LLM 配置等 pydantic 模型。
# ============================================================
from __future__ import annotations

import hashlib
import json

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.protocols import ProtocolGraphSpec

ObjectiveName = Literal["accuracy_first", "budget_first", "balanced"]
BudgetLevel = Literal["loose", "normal", "tight"]
PlannerMode = Literal[
    "topology_select",
    "operator_compose",
    "graph_generate",
    "program_generate",
    "python_generate",
]
LLMRoleName = Literal["emperor", "soldier", "minister"]
# 中文：评测的信息目标。sink=所有信息汇聚到单一 selected_primary，只有它被主评分；
#   all_agents=每个 agent 都必须独立持有完整信息并给出正确答案（多数票不能掩盖个体错误）。
#   两种模式的提示词、图校验、评分与技能库全部隔离。
# The evaluation's INFORMATION GOAL. "sink": all information converges on one
# selected_primary agent and only that agent is graded. "all_agents": every
# agent must independently end with full information and a correct answer (a
# majority vote must not mask individual failures). Prompts, graph validation,
# scoring, and skill banks are all namespaced by this goal.
InformationGoal = Literal["sink", "all_agents"]
# 中文：PythonGen Worker 输出合约(与 exp_graph.mas.python_code.PYTHON_WORKER_CONTRACTS
#   配对，由测试锁定一致)。action_json_v1=Worker 返回完整动作 JSON(旧默认)；
#   message_only_v1=Planner source 决定路由、Runtime 维护状态/provenance、Worker 只
#   返回纯文本；message_only_v2=完整通信后进入同步提交屏障，提交输出是单一 JSON 值。
#   三种合约的 scaffold、校验、技能检索全部隔离。
# The PythonGen worker output contract (kept in lockstep with
# exp_graph.mas.python_code.PYTHON_WORKER_CONTRACTS by a test).
# action_json_v1 = the worker returns a full action JSON (legacy default);
# message_only_v1 = the planner source decides routing, the runtime owns
# state/provenance and the worker returns plain text only. message_only_v2 adds
# a synchronized post-communication submit barrier whose answers are single
# JSON values. Scaffolds, validation and skill retrieval are isolated.
PythonWorkerContract = Literal[
    "action_json_v1",
    "message_only_v1",
    "message_only_v2",
]
PythonInnovationBranch = Literal["fresh", "mutate"]
# 中文：候选/技能卡的结构来源。llm_generated=皇帝 LLM 新生成；skill_replay=重放技能卡里
#   存的结构；fixed_named=具名固定拓扑；named_fallback=生成失败后的具名兜底；fake=离线假
#   候选。clean GraphGen 只允许 llm_generated 与同模式验证过的 skill_replay 入库。
# Structural provenance of a candidate / skill card. Clean GraphGen banks admit
# only "llm_generated" and same-goal-validated "skill_replay".
StructureProvenance = Literal[
    "llm_generated",
    "program_generated",
    "llm_generated_python",
    "skill_replay",
    "fixed_named",
    "named_fallback",
    "fake",
]
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


# 【职责】目标规格：选择拓扑技能所用的目标权重(精度/成本/稳定性三项加权)。
class ObjectiveSpec(BaseModel):
    """Objective weights for selecting topology skills."""

    name: ObjectiveName = "balanced"
    accuracy_weight: float = 0.5
    cost_weight: float = 0.35
    stability_weight: float = 0.15
    # 中文：不确定性感知选择旋钮(Plan 3 Part E)。默认均为无操作：
    #   uncertainty_weight(即 kappa)==0 时 score_skill 仍用普通平均损失；
    #   min_seeds==1 时检索放行所有技能。from_name 刻意不设置这两项，
    #   因此各命名目标的输出保持不变。
    # Uncertainty-aware selection knobs (Plan 3 Part E). Defaults are no-ops:
    # ``uncertainty_weight`` (kappa) == 0 keeps ``score_skill`` on the plain
    # mean loss, and ``min_seeds`` == 1 admits every skill in retrieval. They
    # are intentionally left unset by ``from_name`` so its output for every
    # named objective is unchanged.
    # 不确定性惩罚权重 kappa：>0 时以 LCB 惩罚高方差/小样本技能的精度信号
    uncertainty_weight: float = 0.0
    # 最少种子数门槛：独立观测数低于该值的技能在检索时被排除
    min_seeds: int = 1
    # 中文：反例否决 + 绝对下限 + 风险感知评分旋钮(Plan 3 Part F)。三者默认均为
    #   无操作，使 TopologySelectPlanner.plan 与现状逐字节一致，from_name 不设置：
    #   - enforce_avoid_veto=False：避雷技能仅作检索期约束(绝不构成选择否决)；
    #   - max_acceptable_loss=None：关闭"不得劣于基线"的绝对下限；
    #   - risk_weight=0.0：选择得分等于 score_skill(不扣减 confidence.risk_penalty)。
    # Counterexample veto + absolute floor + risk-aware scoring knobs (Plan 3
    # Part F). All three default to no-ops so ``TopologySelectPlanner.plan`` is
    # byte-identical to today and ``from_name`` leaves them unset:
    #   - ``enforce_avoid_veto`` False keeps avoid skills as retrieval-only
    #     constraints (never a selection veto);
    #   - ``max_acceptable_loss`` None disables the no-worse-than-baseline floor;
    #   - ``risk_weight`` 0.0 leaves the selection score equal to ``score_skill``
    #     (no ``confidence.risk_penalty`` subtraction).
    # True 时匹配的避雷/反例技能升级为选择否决(veto)
    enforce_avoid_veto: bool = False
    # 主损失(越低越好)的最大可接受值，"不劣于基线"的地板门槛；None=关闭
    max_acceptable_loss: float | None = None
    # 风险权重：>0 时从候选选择得分中扣减 confidence.risk_penalty
    risk_weight: float = 0.0

    # 【职责】按目标名生成预设权重：accuracy_first 偏精度、budget_first 偏成本，否则均衡。
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


# 【职责】皇帝规划器使用的预算约束(档位 loose/normal/tight、最大消息数与 token 开销)。
class BudgetSpec(BaseModel):
    """Budget constraints used by the emperor planner."""

    level: BudgetLevel = "normal"
    max_messages: int | None = None
    max_token_cost: int | None = None


# 【职责】单个 MAS 角色的 OpenAI 兼容模型端点设置(平台/模型/base_url/密钥环境变量等)。
class RoleLLMConfig(BaseModel):
    """OpenAI-compatible model endpoint settings for one MAS role."""

    platform: str = "openai"
    model_name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    thinking_enabled: bool | None = None


# 【职责】外层 MAS 流水线可选的按角色 LLM 配置(皇帝/士兵/大臣各一份，可缺省)。
class RoleLLMProfiles(BaseModel):
    """Optional role-specific LLM profiles for the outer MAS pipeline."""

    emperor: RoleLLMConfig | None = None
    soldier: RoleLLMConfig | None = None
    minister: RoleLLMConfig | None = None

    # 【职责】按角色名(emperor/soldier/minister)取对应配置，缺省为 None。
    def get_role(self, role: LLMRoleName) -> RoleLLMConfig | None:
        return getattr(self, role)


# 【职责】士兵实际执行的协议结构的紧凑描述(结构哈希/拓扑名/步数/消息数/各步明细)。
class TopologyStructure(BaseModel):
    """Compact description of the actual protocol structure executed by soldiers."""

    structure_hash: str
    topology_name: str
    n_agents: int
    selected_primary: int | str | None = None
    total_steps: int
    total_messages: int
    steps: list[dict[str, object]] = Field(default_factory=list)


# 【职责】透明的真实/伪造(real/fake) LLM MAS 流水线运行时选项。
# - graph_* 前缀：graph_generate 模式下时序通信 DAG 的生成与候选搜索约束；
# - use_motif_prior/motif_stats：结构母题信用先验；replay_*：技能回放相关开关；
# - 新增旋钮默认关闭/为 0，保证与历史行为逐字节一致。
class MASRuntimeConfig(BaseModel):
    """Runtime options for a transparent real/fake LLM MAS pipeline."""

    llm_provider: str = "fake"
    model_name: str = "fake"
    temperature: float = 0.0
    json_retry_attempts: int = 2
    allow_deterministic_repair: bool = True
    max_parallel_agents: int = Field(default=1, ge=1)
    max_parallel_ministers: int = 1
    trace_enabled: bool = False
    retain_traces: bool = False
    trace_dir: str | None = None
    verbose_events: bool = False
    output_dir: str | None = None
    value_min: int = 0
    value_max: int = 9
    # graph_* 生成约束：搜索模式/候选数/top-k/评分模式/步数/消息/扇入上限/修复次数/验证种子
    graph_search_mode: str = "single"
    num_graph_candidates: int = 1
    graph_top_k: int = 1
    graph_candidate_score_mode: str = "objective"
    graph_max_steps: int = 4
    graph_max_messages: int = 32
    graph_max_receiver_fan_in: int = 4
    graph_repair_attempts: int = 1
    graph_validation_seeds: list[int] = Field(default_factory=list)
    # Restricted phase-program generation is a separate planner mode. It reuses
    # the graph size budgets because both ultimately execute a ProtocolGraphSpec,
    # but owns its repair budget so tuning it cannot change GraphGen behaviour.
    program_repair_attempts: int = 2
    # PythonGen is a third, independent generated mode. These limits never
    # mutate GraphGen or phase-program settings.
    python_repair_attempts: int = 3
    python_execution_timeout: float = Field(default=300.0, gt=0)
    python_cpu_seconds: int = 10
    python_memory_mb: int = 512
    python_max_output_bytes: int = 1_000_000
    python_dry_run: bool = True
    python_ast_policy_version: str = "python_ast_v1"
    python_execution_contract_version: str = "python_mas_v1"
    # Worker output contract for PythonGen. The default keeps every existing
    # run byte-identical to the historical action-JSON behaviour.
    python_worker_contract: PythonWorkerContract = "action_json_v1"
    python_max_rounds: int = 4
    python_max_model_calls: int = 32
    python_max_completion_tokens: int = 20_000
    python_max_messages: int = 64
    # Optional hot-start innovation context. Normal PythonGen leaves the branch
    # unset and remains skill-context blind. The planner resolves the parent
    # from the same-contract SkillBank and only exposes sanitized summaries.
    python_innovation_branch: PythonInnovationBranch | None = None
    python_parent_skill_id: str | None = None
    python_architect_context_enabled: bool = False
    python_context_max_chars: int = 6_000
    python_exposed_insight_ids: list[str] = Field(default_factory=list)
    python_positive_context: dict[str, object] = Field(default_factory=dict)
    python_negative_context: list[dict[str, object]] = Field(default_factory=list)
    # Failure-cluster feedback is opt-in.  masbench enables it for honest_v2;
    # legacy runs retain their historical architect prompt byte shape.
    failure_feedback_enabled: bool = False
    # 中文：D2(可选开启)：要求生成 DAG 的汇点在时间上可从全部 agent 到达。
    #   默认关闭 -> CF 逐字节一致；masbench(Silo)开启。
    # D2 (opt-in): require the generated DAG's sink to be temporally reachable
    # from ALL agents. Default OFF -> CF byte-identical; masbench (Silo) enables it.
    graph_require_full_sink_coverage: bool = False
    # 中文：图候选选择的结构母题信用先验(Plan 4 任务 5，激活 Plan 3 Part G 机制)。
    #   两者默认均为无操作，图生成 + 候选选择与现状逐字节一致：
    #   - use_motif_prior=False 时从不查询结构母题证据；
    #   - motif_stats 为 None(或空)即无证据可用，即使开关打开先验也无效
    #     (对每个候选返回 +inf 高不确定性哨兵值，保持默认"取首个有效候选"顺序)。
    #   两者齐备时，编译有效的候选按 exp_graph.mas.motifs.score_spec_by_motifs
    #   排名(预测损失越低越好)；见 graph_generation._select_candidate。
    # Structural-motif credit prior for graph-candidate selection (Plan 4 Task
    # 5, activating the Plan 3 Part G machinery). Both default to no-ops so
    # graph generation + candidate selection stay byte-identical to today:
    #   - ``use_motif_prior`` False never consults motif evidence;
    #   - ``motif_stats`` None (or empty) means there is no evidence to apply, so
    #     even with the flag on the prior is inert (returns the +inf
    #     high-uncertainty sentinel for every candidate and the default
    #     first-valid order is kept).
    # When both are set, valid compiled candidates are ranked by
    # ``exp_graph.mas.motifs.score_spec_by_motifs`` (lower predicted loss is
    # better); see ``graph_generation._select_candidate``.
    use_motif_prior: bool = False
    motif_stats: dict[str, dict] | None = None
    # 中文：结构母题先验的 LCB 悲观项：每个母题键的预测损失变为
    #   mean_loss + kappa/sqrt(n)，使只测过 1 次的"幸运"母题压不过测量充分的
    #   老将。0.0(默认)=历史行为。
    # LCB pessimism for the motif prior: per-key predicted loss becomes
    # ``mean_loss + kappa/sqrt(n)`` so a 1-run lucky motif cannot outrank a
    # well-measured veteran. 0.0 (default) = historical behavior.
    motif_uncertainty_kappa: float = 0.0
    # 中文：M9：为 True 时，种子回放候选的逐步接收者指令会针对当前任务重写
    #   (每个种子候选一次 LLM 调用，输入为任务简介 + 已验证的结构)。
    #   默认 False -> 生成逐字节一致。
    # M9: when True, seeded replay candidates get their per-step receiver
    # instructions REWRITTEN for the current task (one LLM call per seeded
    # candidate, from the task brief + the proven structure). Default False
    # -> generation byte-identical.
    replay_instruction_rewrite: bool = False
    # 中文：Round-10 部署稳定性。replay_first：只要存在任一有效的种子(技能回放)
    #   候选，新生成候选就不参与选择竞争——每次运行的计划方差坍缩为确定性的
    #   检索顺序。motif_displacement_margin：结构母题先验仅当预测损失比现任
    #   第一名候选好出超过该边际时才可取代它(近似平手不再在轮次间来回洗牌)。
    #   默认值精确保留历史行为。
    # Round-10 deployment stability. replay_first: when any valid SEEDED
    # (skill-replay) candidate exists, fresh generations do not compete for
    # selection -- per-run plan variance collapses to the deterministic
    # retrieval order. motif_displacement_margin: the motif prior may only
    # displace the incumbent first-ranked candidate when its predicted loss
    # is better by MORE than this margin (near-ties stop reshuffling between
    # rounds). Defaults preserve historical behavior exactly.
    replay_first: bool = False
    motif_displacement_margin: float = 0.0
    role_llm_profiles: RoleLLMProfiles | None = None
    role_llm_config_path: str | None = None
    # 中文：信息目标（sink/all_agents）：决定架构师提示词模板与图覆盖校验/修复的谓词。
    #   默认 sink 保持既有 CF/核心行为不变。
    # Information goal (sink/all_agents): selects the architect prompt template
    # and the coverage predicate used by graph validation/repair. Default sink
    # keeps existing CF/core behaviour unchanged.
    information_goal: InformationGoal = "sink"
    # 中文：发送前对模型可见提示词跑泄漏审计（禁止 answer/最优拓扑/具名拓扑公式等
    #   token）。masbench(Silo) 开启；CF 默认关闭以保持字节级一致。
    # Run the leakage audit over model-visible prompts before sending
    # (forbidden answer/optimal-topology/named-formula tokens). masbench (Silo)
    # enables it; CF keeps it off for byte-identical behaviour.
    leakage_audit: bool = False
    # Hot-start runs deliberately expose measured structural references. They
    # remain non-clean experiments, but may allow only those structural token
    # names while answer/ground-truth leakage stays blocked.
    leakage_allowed_tokens: list[str] = Field(default_factory=list)

    # 【职责】校验取值范围：value_max 必须 >= value_min。
    @model_validator(mode="after")
    def validate_value_range(self) -> "MASRuntimeConfig":
        if self.value_max < self.value_min:
            raise ValueError("value_max must be greater than or equal to value_min")
        return self


# 【职责】皇帝规划器的输入：任务族、agent 数、目标/预算、规划模式与拓扑白名单。
class PlannerRequest(BaseModel):
    """Input to the emperor planner."""

    # 任务族(如 silo / count_frequency)：检索时须与技能卡一致
    task_family: str = "count_frequency"
    n_agents: int
    array_size: int | None = None
    objective: ObjectiveSpec = Field(
        default_factory=lambda: ObjectiveSpec.from_name("balanced")
    )
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    # program_generate=受限阶段 DSL；python_generate=受审计 Python 子进程；
    # 三种生成路径互相独立。
    planner_mode: PlannerMode = "topology_select"
    merge_mode: str = "deterministic"
    init_mode: str = "deterministic"
    allowed_topologies: list[str] | None = None
    # 中文：信息目标（sink/all_agents）。技能检索按它隔离：卡片 trigger 缺该字段视为
    #   legacy sink 卡。默认 sink 保持旧核心调用兼容。
    # Information goal (sink/all_agents). Skill retrieval is namespaced by it;
    # cards whose trigger lacks the field are treated as legacy sink cards.
    information_goal: InformationGoal = "sink"
    # 中文：技能检索的 provenance 白名单。None=不过滤（legacy 行为）；clean GraphGen 传
    #   ["llm_generated","skill_replay"]——缺 provenance 的旧卡视为 contaminated 被排除。
    # Provenance allowlist for retrieval. None = no filtering (legacy). Clean
    # GraphGen passes ["llm_generated", "skill_replay"]; cards with no
    # provenance are treated as contaminated and excluded when a list is set.
    provenance_allowlist: list[str] | None = None
    # Explicit hot-start escape hatch for generation prompts.  These cards are
    # context/evidence only and are never direct planner choices.  Keeping the
    # switch on the request prevents reference protocols from leaking into a
    # normal clean GraphGen run merely because they exist in a persisted bank.
    include_reference_skills: bool = False
    # 中文：python_generate 的 Worker 合约。技能检索按它隔离：payload 缺该字段的旧
    #   Python 卡视为 action_json_v1。非 python_generate 模式忽略此字段。
    # Worker contract for python_generate requests. Skill retrieval is
    # namespaced by it; legacy python cards whose payload lacks the field are
    # treated as action_json_v1. Ignored outside python_generate.
    python_worker_contract: PythonWorkerContract = "action_json_v1"

    # 【职责】校验 n_agents 为正。
    @model_validator(mode="after")
    def validate_request(self) -> "PlannerRequest":
        if self.n_agents < 1:
            raise ValueError("n_agents must be positive")
        return self

    # 【职责】便捷构造：按名称展开目标(from_name)与预算档位。
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


# 【职责】模式专属的可执行技能载荷；各格式通过 format 判别且禁止额外字段。
class NamedTopologySkillPayload(BaseModel):
    """Executable payload for one deterministic named topology."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["named_topology_skill_v1"] = "named_topology_skill_v1"
    planner_mode: Literal["topology_select"] = "topology_select"
    topology_name: str
    protocol_spec: dict[str, object]
    structure_code: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_schedule(self) -> "NamedTopologySkillPayload":
        ProtocolGraphSpec.model_validate(self.protocol_spec)
        return self


class PaperTransportSkillPayload(BaseModel):
    """Executable payload for one SILO dynamic paper transport."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["paper_transport_skill_v1"] = "paper_transport_skill_v1"
    planner_mode: Literal["paper_protocol"] = "paper_protocol"
    protocol: Literal["p2p", "broadcast", "sfs"]
    structure_code: dict[str, object]


class GraphSkillPayload(BaseModel):
    """Independent archive format for free GraphGen programs and schedules."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["graph_skill_v1"] = "graph_skill_v1"
    planner_mode: Literal["graph_generate"] = "graph_generate"
    topology_name: str
    protocol_spec: dict[str, object]
    topology_program: dict[str, object] | None = None
    structure_code: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_artifacts(self) -> "GraphSkillPayload":
        ProtocolGraphSpec.model_validate(self.protocol_spec)
        if self.topology_program is not None and (
            self.topology_program.get("format") != "topology_program_v1"
        ):
            raise ValueError("graph topology_program must use topology_program_v1")
        return self


class PhaseProgramSkillPayload(BaseModel):
    """Independent archive format for restricted phase DSL programs."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["phase_program_skill_v1"] = "phase_program_skill_v1"
    planner_mode: Literal["program_generate"] = "program_generate"
    topology_name: str
    phase_program: dict[str, object]
    compiled_protocol_spec: dict[str, object]
    compiler_version: str = "1"
    program_sha256: str = ""

    @model_validator(mode="after")
    def populate_program_digest(self) -> "PhaseProgramSkillPayload":
        source = self.phase_program
        if not source:
            raise ValueError("phase_program payload must preserve the DSL source")
        if source.get("format") != "phase_program_v1":
            raise ValueError("phase_program payload must use phase_program_v1")
        ProtocolGraphSpec.model_validate(self.compiled_protocol_spec)
        canonical = json.dumps(
            source,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        if self.program_sha256 and self.program_sha256 != digest:
            raise ValueError("program_sha256 does not match phase_program")
        self.program_sha256 = digest
        return self


class PythonSkillPayload(BaseModel):
    """Independent archive format preserving complete generated Python source."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["python_skill_v1"] = "python_skill_v1"
    planner_mode: Literal["python_generate"] = "python_generate"
    source_code: str
    program_sha256: str = ""
    ast_policy_version: str
    execution_contract_version: str
    # Worker contract the source was validated under. The default classifies
    # every pre-field card on disk as the legacy action-JSON contract, so old
    # banks stay readable without migration while retrieval stays isolated.
    worker_contract: PythonWorkerContract = "action_json_v1"
    repair_attempts: int = 0
    artifact_reference: str | None = None
    runtime_trace_summary: dict[str, object] = Field(default_factory=dict)
    innovation_strategy: str | None = None
    parent_skill_id: str | None = None
    exposed_insight_ids: list[str] = Field(default_factory=list)
    used_insight_ids: list[str] = Field(default_factory=list)
    parent_program_sha256: str | None = None
    mutation_diff_sha256: str | None = None
    mutation_provenance: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_complete_source(self) -> "PythonSkillPayload":
        if not self.source_code.strip():
            raise ValueError("python skill payload must preserve complete source_code")
        digest = hashlib.sha256(self.source_code.encode("utf-8")).hexdigest()
        if self.program_sha256 and self.program_sha256 != digest:
            raise ValueError("program_sha256 does not match source_code")
        self.program_sha256 = digest
        return self


ModeSkillPayload = Annotated[
    NamedTopologySkillPayload
    | PaperTransportSkillPayload
    | GraphSkillPayload
    | PhaseProgramSkillPayload
    | PythonSkillPayload,
    Field(discriminator="format"),
]


# 【职责】MAS 规划用的带版本、可复用组织技能卡(技能库的基本单元)。
class SkillCard(BaseModel):
    """Versioned reusable organization skill for MAS planning."""

    skill_id: str
    version: str = "0.1.0"
    task_family: str = "count_frequency"
    skill_type: str = "planner_organization_policy"
    # 触发条件：适用范围(min/max_agents、agent_counts、array_sizes、condition_key 等)
    trigger: dict[str, object] = Field(default_factory=dict)
    objective: ObjectiveName = "balanced"
    # Executable state is mode-specific and discriminated by ``format``.  New
    # cards must use this field; ``organization_policy`` remains as a legacy
    # compatibility/index mirror so old banks stay readable during migration.
    mode_payload: ModeSkillPayload | None = None
    # 兼容/检索索引：新卡的可执行真源在 mode_payload；这里暂存旧读取方所需镜像及
    # 非执行元数据(operators、拓扑等价哈希、指令范例等)。
    organization_policy: dict[str, object] = Field(default_factory=dict)
    # Message/merge/submit semantics learned independently from the topology.
    # Keeping this separate lets evolution reuse a reasoning recipe on another
    # compatible program without pretending that the edge structure changed.
    reasoning_policy: dict[str, object] = Field(default_factory=dict)
    # 预期权衡：mean_rmse/mean_primary_loss/mean_token_cost 等聚合指标(评分优先读这里)
    expected_tradeoff: dict[str, object] = Field(default_factory=dict)
    expected_dynamics: dict[str, object] = Field(default_factory=dict)
    # 设计洞见：从证据沉淀的可复用设计要点(按 insight_id 去重)
    design_insights: list[dict[str, object]] = Field(default_factory=list)
    risk_notes: list[dict[str, object]] = Field(default_factory=list)
    failure_modes: list[dict[str, object]] = Field(default_factory=list)
    # 内嵌证据行(与 evidence_refs 外部证据引用配合)：支撑指标的观测记录
    evidence: list[dict[str, object]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    # 回退策略：主策略失效时的备选组织方案
    fallback: dict[str, object] = Field(default_factory=dict)
    # 反例：记录该技能失效的具体条件
    counterexamples: list[dict[str, object]] = Field(default_factory=list)
    hypotheses: list[dict[str, object]] = Field(default_factory=list)
    # 置信信息：seed_count/active_evidence_count 等样本量与 risk_penalty 等风险元数据
    confidence: dict[str, object] = Field(default_factory=dict)
    revision_history: list[dict[str, object]] = Field(default_factory=list)
    validation_plan: list[dict[str, object]] = Field(default_factory=list)
    update_rule: str = "batch_consolidate"
    tags: list[str] = Field(default_factory=list)
    # 中文：结构来源(provenance)。None=旧卡（缺来源即视为 contaminated，不得进入新的
    #   clean 实验，但不删除文件）。
    # Structural provenance. None = legacy card (treated as contaminated for
    # clean experiments; the file itself is never deleted).
    provenance: StructureProvenance | None = None
    # 中文：该技能观测所处的信息目标。旧卡缺省 None（视为 legacy sink）。
    # Information goal the skill was observed under. None = legacy (sink).
    information_goal: InformationGoal | None = None

    # 【职责】从组织策略读取拓扑名(缺失为 None)。
    @property
    def topology_name(self) -> str | None:
        payload = self.mode_payload
        if isinstance(
            payload,
            (NamedTopologySkillPayload, GraphSkillPayload, PhaseProgramSkillPayload),
        ):
            return payload.topology_name
        if isinstance(payload, PaperTransportSkillPayload):
            return f"paper_{payload.protocol}"
        if isinstance(payload, PythonSkillPayload):
            value = self.organization_policy.get("topology_name")
            return str(value) if value else "python:generated"
        value = self.organization_policy.get("topology_name")
        return str(value) if value else None

    # 【职责】从组织策略读取算子列表(非列表则为空)。
    @property
    def operators(self) -> list[str]:
        value = self.organization_policy.get("operators", [])
        return [str(item) for item in value] if isinstance(value, list) else []


# 【职责】大臣(结果分析器)提出的候选技能更新补丁。
class SkillPatch(BaseModel):
    """Candidate update proposed by a minister analyst."""

    patch_id: str
    # 补丁动作：add=新增 / merge=并入既有技能 / discard=丢弃 / deprecate=弃用
    action: PatchAction
    target_skill_id: str | None = None
    candidate_skill: SkillCard | None = None
    evidence: list[dict[str, object]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    update: dict[str, object] = Field(default_factory=dict)
    lesson: str = ""
    confidence: float = 0.0
    source: str = "result_analyst"


# 【职责】只追加(append-only)的证据记录，作为规划器技能进化的输入。
class EvidenceRecord(BaseModel):
    """Append-only evidence used to evolve planner skills."""

    evidence_id: str
    source_dir: str = ""
    # 证据来源类型：aggregate=聚合行 / run=单次运行 / trace=轨迹 / insight / manual
    source_type: EvidenceSourceType
    task_family: str = "count_frequency"
    topology_name: str = ""
    n_agents: int | None = None
    seed: int | None = None
    # 数值指标(mean_rmse、消息数、token 开销等)
    metrics: dict[str, object] = Field(default_factory=dict)
    # 动力学摘要(覆盖度增长、聚合可靠性、合并质量)
    dynamics: dict[str, object] = Field(default_factory=dict)
    # 风险标签(如 coverage_stall / sink_quality_gap / merge_parse_error)
    risk_tags: list[str] = Field(default_factory=list)
    # 证据状态：observed=已观测 / placeholder=占位 / deprecated=已弃用
    status: EvidenceStatus = "observed"
    created_at: str = ""


# 【职责】技能库一次版本化更新的记录条目(版本变迁、补丁与证据引用、变更字段)。
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


# 【职责】按拓扑/运行组聚合的"轨迹->技能"动力学摘要。
class TraceDynamicsSummary(BaseModel):
    """Aggregated trace-to-skill dynamics for one topology/run group."""

    topology_name: str
    n_agents: int | None = None
    seed: int | None = None
    coverage_growth: dict[str, object] = Field(default_factory=dict)
    aggregation_reliability: dict[str, object] = Field(default_factory=dict)
    merge_quality: dict[str, object] = Field(default_factory=dict)
    risk_tags: list[str] = Field(default_factory=list)


# 【职责】有证据支撑的 LLM MAS 设计洞见(类型/主张状态/证据引用/建议动作/证伪测试)。
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


# 【职责】实验后的 MAS 设计洞见报告(执行摘要/关键与被否洞见/技能更新建议/后续实验)。
class InsightReport(BaseModel):
    """Post-experiment MAS design insight report."""

    report_id: str
    experiment_id: str
    executive_summary: str = ""
    key_insights: list[MASInsight] = Field(default_factory=list)
    rejected_insights: list[dict[str, object]] = Field(default_factory=list)
    skill_update_recommendations: list[SkillPatch] = Field(default_factory=list)
    followup_experiments: list[dict[str, object]] = Field(default_factory=list)


# 【职责】可打印的运行后大臣摘要(最终指标、消息/调用/token 统计、补丁计数与教训)。
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


# 【职责】实验后待整合的一批大臣补丁(技能进化的批处理单元)。
class EvolutionBatch(BaseModel):
    """Batch of minister patches to consolidate after experiments."""

    batch_id: str
    patches: list[SkillPatch] = Field(default_factory=list)
    summary: str = ""


# 【职责】把一批补丁应用到技能库后的结果(动作计数/修订记录/警告/验证门元数据)。
class EvolutionResult(BaseModel):
    """Result of applying one batch of patches to a skill bank."""

    batch_id: str
    counts: dict[str, int] = Field(default_factory=dict)
    revisions: list[SkillRevision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # 中文：留出集(held-out)验证门元数据。门未启用(默认)时为 None，
    #   因此既有的无条件整合结果保持不变。
    # Held-out validation gate metadata. ``None`` when the gate is disabled (the
    # default), so existing unconditional consolidation results are unchanged.
    gate_accepted: bool | None = None
    gate_j_before: float | None = None
    gate_j_after: float | None = None


# 【职责】规划器输出，供 MASProtocolRunner 消费执行。
# - 含规划模式、所选拓扑/技能、算子、协议规格、得分与分解、回退技能、备选与理由。
class MASPlan(BaseModel):
    """Planner output consumed by MASProtocolRunner."""

    planner_mode: PlannerMode
    topology_name: str
    skill_id: str | None = None
    operators: list[str] = Field(default_factory=list)
    protocol_spec: ProtocolGraphSpec | None = None
    # Only python_generate uses source code; ProtocolRunner never consumes it.
    python_source: str | None = None
    config_overrides: dict[str, object] = Field(default_factory=dict)
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    fallback_skill_id: str | None = None
    alternatives: list[dict[str, object]] = Field(default_factory=list)
    rationale: str = ""
    # 中文：所执行结构的来源；graph_generate 计划为 llm_generated/skill_replay/fake，
    #   topology_select/operator_compose 计划为 fixed_named。
    # Provenance of the executed structure. graph_generate plans carry
    # llm_generated/skill_replay/fake; named-topology plans carry fixed_named.
    provenance: StructureProvenance | None = None
