"""Emperor planners that select or construct MAS protocol plans."""
# ============================================================
# 【模块导读】皇帝(规划 LLM)侧规划器：为 MAS 挑选或构造协议方案(MASPlan)。
# EmperorPlanner 按 planner_mode 分发五种构造模式：topology_select
# (依版本化技能卡选既有拓扑)、operator_compose(操作子组合编译)、
# graph_generate(确定性生成有限图规范；LLM 自由图版在 graph_generation)、
# program_generate(受限阶段 DSL；LLM 版在 phase_program_generation)、
# python_generate(完整受限 Python；生成/执行在 python_code_generation)。
# 附带风险惩罚/反例否决/损失下限/兜底等安全决策链。
# ============================================================

from __future__ import annotations

from exp_graph.mas.operators import compose_protocol_from_operators
from exp_graph.mas.python_code import (
    default_python_program,
    validate_python_source,
)
from exp_graph.mas.phase_program import (
    PhaseProgram,
    PhaseProgramLimits,
    compile_phase_program_spec,
)
from exp_graph.mas.schemas import MASPlan, PlannerRequest, SkillCard
from exp_graph.mas.scoring import score_skill
from exp_graph.mas.skill_bank import SkillBank, is_selectable_skill
from exp_graph.mas.skill_payloads import (
    python_source_from_skill,
    python_worker_contract_from_skill,
)


# 【职责】规划请求总入口：按 planner_mode 分发到所选构造模式。
# - 五种模式相互独立；未知模式抛 ValueError
class EmperorPlanner:
    """Dispatch planner requests to the selected construction mode."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank
        self.topology_select = TopologySelectPlanner(skill_bank)
        self.operator_compose = OperatorComposePlanner(skill_bank)
        self.graph_generate = GraphGeneratePlanner(skill_bank)
        self.program_generate = ProgramGeneratePlanner(skill_bank)
        self.python_generate = PythonGeneratePlanner(skill_bank)

    def plan(self, request: PlannerRequest) -> MASPlan:
        if request.planner_mode == "topology_select":
            return self.topology_select.plan(request)
        if request.planner_mode == "operator_compose":
            return self.operator_compose.plan(request)
        if request.planner_mode == "graph_generate":
            return self.graph_generate.plan(request)
        if request.planner_mode == "program_generate":
            return self.program_generate.plan(request)
        if request.planner_mode == "python_generate":
            return self.python_generate.plan(request)
        raise ValueError(f"unsupported planner_mode: {request.planner_mode}")


# 【职责】用版本化技能卡在既有拓扑名中做选择。
# - 决策链：技能检索→评分→风险惩罚→反例否决→损失下限→兜底(见 plan)
class TopologySelectPlanner:
    """Select from existing topology names using versioned skills."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    # 【职责】完整决策链：检索→评分(减风险惩罚)→否决过滤→损失下限→组装计划。
    # - 检索无果退化为全库可选技能；仍无则 fallback_plan 兜底
    # - enforce_avoid_veto 开启时剔除被反例技能否决的拓扑；全被否决走安全兜底
    # - 最优者损失超 max_acceptable_loss(损失下限)时走下限兜底
    # - 计划记录 top1 之外的 3 个备选与评分明细；rationale 附否决说明
    def plan(self, request: PlannerRequest) -> MASPlan:
        # 中文：retrieve 读取 request.objective.min_seeds(默认 1=不设门槛)；
        #   uncertainty_weight 则流入下方的 score_skill。
        # ``retrieve`` reads request.objective.min_seeds (default 1 = no gate)
        # and request.objective.uncertainty_weight flows into score_skill below.
        min_seeds = int(getattr(request.objective, "min_seeds", 1))
        skills = self.skill_bank.retrieve(request)
        if not skills:
            skills = [
                skill
                for skill in self.skill_bank
                if is_selectable_skill(skill, min_seeds=min_seeds)
            ]
        if not skills:
            return fallback_plan(request)

        # 中文：Plan 3 Part F 旋钮。全部默认无操作，使下方代码块与此前
        #   "仅相对分"的选择逐字节一致：risk_weight=0.0 时 selection_score
        #   等于 score；enforce_avoid_veto=False 保留全部候选；
        #   max_acceptable_loss=None 跳过损失下限。
        # Plan 3 Part F knobs. All default to no-ops so the block below is
        # byte-identical to the prior relative-only selection: ``risk_weight``
        # 0.0 leaves ``selection_score`` == ``score``; ``enforce_avoid_veto``
        # False keeps every candidate; ``max_acceptable_loss`` None skips the
        # floor.
        risk_weight = float(getattr(request.objective, "risk_weight", 0.0))
        enforce_avoid_veto = bool(
            getattr(request.objective, "enforce_avoid_veto", False)
        )
        max_acceptable_loss = getattr(request.objective, "max_acceptable_loss", None)

        scored = []
        for skill in skills:
            score, breakdown = score_skill(
                skill,
                objective=request.objective,
                peers=skills,
            )
            selection_score = score - risk_weight * _skill_risk_penalty(skill)
            scored.append((selection_score, breakdown, skill))
        scored.sort(key=lambda item: item[0], reverse=True)

        veto_note = ""
        if enforce_avoid_veto:
            vetoed = _vetoed_topology_names(self.skill_bank, request)
            if vetoed:
                kept = [
                    item
                    for item in scored
                    if (item[2].topology_name or "") not in vetoed
                ]
                if not kept:
                    return _veto_fallback_plan(request, vetoed)
                if len(kept) != len(scored):
                    veto_note = (
                        " Excluded vetoed topologies "
                        f"{sorted(vetoed)} via counterexample skills."
                    )
                scored = kept

        best_score, best_breakdown, best_skill = scored[0]

        if max_acceptable_loss is not None:
            best_loss = _breakdown_loss(best_breakdown)
            if best_loss > float(max_acceptable_loss):
                return _floor_fallback_plan(
                    request,
                    best_skill=best_skill,
                    best_loss=best_loss,
                    max_acceptable_loss=float(max_acceptable_loss),
                )

        topology_name = best_skill.topology_name or default_topology_for_objective(request)
        return MASPlan(
            planner_mode="topology_select",
            topology_name=topology_name,
            skill_id=best_skill.skill_id,
            operators=best_skill.operators,
            config_overrides=config_overrides_for_skill(best_skill),
            score=best_score,
            score_breakdown=best_breakdown,
            fallback_skill_id=fallback_skill_id(best_skill),
            alternatives=[
                {
                    "skill_id": skill.skill_id,
                    "topology_name": skill.topology_name,
                    "score": score,
                    "score_breakdown": breakdown,
                }
                for score, breakdown, skill in scored[1:4]
            ],
            rationale=(
                f"Selected {topology_name} from skill {best_skill.skill_id} "
                f"for {request.objective.name}."
                + veto_note
            ),
        )


# 【职责】操作子组合：先按 topology_select 选技能，再把操作子链编译(成协议调度)。
# - 技能无操作子时按目标推导；生成的 spec 同时写入 protocol_spec 与覆盖配置
class OperatorComposePlanner:
    """Compose a protocol graph spec from organization operators."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        base_plan = TopologySelectPlanner(self.skill_bank).plan(
            request.model_copy(update={"planner_mode": "topology_select"})
        )
        operators = base_plan.operators or operators_for_objective(request)
        spec = compose_protocol_from_operators(
            name=f"mas_{request.objective.name}_{request.n_agents}",
            n_agents=request.n_agents,
            operators=operators,
            max_messages=request.budget.max_messages,
        )
        topology_name = str(spec.metadata.get("compiled_from_topology", base_plan.topology_name))
        return base_plan.model_copy(
            update={
                "planner_mode": "operator_compose",
                "topology_name": topology_name,
                "operators": operators,
                "protocol_spec": spec,
                "config_overrides": {
                    **base_plan.config_overrides,
                    "protocol_spec": spec,
                },
                "rationale": (
                    "Composed finite ProtocolGraphSpec from organization operators: "
                    + " -> ".join(operators)
                ),
            }
        )


# 【职责】graph_generate 的确定性版本：按请求约束生成合法有限图规范(不调 LLM)。
# - 按目标推导操作子；预算 tight 时强制 local_solve+tree_reduce，再编译成 spec
class GraphGeneratePlanner:
    """Generate a valid finite graph spec under request constraints."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        operators = operators_for_objective(request)
        if request.budget.level == "tight":
            operators = ["local_solve", "tree_reduce"]
        spec = compose_protocol_from_operators(
            name=f"generated_{request.objective.name}_{request.n_agents}",
            n_agents=request.n_agents,
            operators=operators,
            max_messages=request.budget.max_messages,
        )
        topology_name = str(spec.metadata.get("compiled_from_topology", "custom"))
        return MASPlan(
            planner_mode="graph_generate",
            topology_name=topology_name,
            operators=operators,
            protocol_spec=spec,
            config_overrides={"protocol_spec": spec},
            score=0.0,
            score_breakdown={},
            rationale=(
                "Generated a finite ProtocolGraphSpec from objective defaults "
                "and budget constraints."
            ),
        )


class ProgramGeneratePlanner:
    """Compile a deterministic restricted phase program without an LLM.

    The benchmark engine uses the richer LLM/CEGIS implementation in
    ``phase_program_generation``. This core planner keeps the public dispatcher
    complete and gives offline callers a small, honest executable default.
    """

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        hub = 0
        phases: list[dict[str, object]] = [
            {
                "kind": "gather",
                "hub": hub,
                "pattern": "tree",
                "instruction": (
                    "Merge source-tagged state and preserve provenance without "
                    "double counting."
                ),
            }
        ]
        if request.information_goal == "all_agents":
            phases.append(
                {
                    "kind": "broadcast",
                    "hub": hub,
                    "pattern": "tree",
                    "instruction": (
                        "Merge the complete source-tagged state and retain it for "
                        "the next round."
                    ),
                }
            )
        program = PhaseProgram.model_validate(
            {
                "information_goal": request.information_goal,
                "selected_primary": hub,
                "phases": phases,
            }
        )
        minimum_messages = (request.n_agents - 1) * len(phases)
        max_messages = request.budget.max_messages
        if max_messages is None:
            max_messages = max(0, minimum_messages)
        spec, _compiled = compile_phase_program_spec(
            program,
            n_agents=request.n_agents,
            limits=PhaseProgramLimits(
                max_steps=max(1, 2 * request.n_agents),
                max_messages=max_messages,
                max_receiver_fan_in=max(1, request.n_agents - 1),
            ),
            name=f"phase_program_{request.objective.name}_{request.n_agents}",
        )
        return MASPlan(
            planner_mode="program_generate",
            topology_name=f"program:{spec.name}",
            operators=list(spec.operators),
            protocol_spec=spec,
            config_overrides={
                "protocol_spec": spec,
                "enable_step_instructions": True,
            },
            score=0.0,
            score_breakdown={},
            rationale=(
                "Compiled a bounded restricted phase program independently of "
                "free-form GraphGen."
            ),
            provenance="program_generated",
        )


class PythonGeneratePlanner:
    """Offline core placeholder; masbench owns validated execution and scoring."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        worker_contract = str(
            getattr(request, "python_worker_contract", "action_json_v1")
            or "action_json_v1"
        )
        for skill in self.skill_bank.retrieve(request):
            source = python_source_from_skill(skill)
            if (
                isinstance(source, str)
                and python_worker_contract_from_skill(skill) == worker_contract
                and validate_python_source(
                    source,
                    worker_contract=worker_contract,
                ).valid
            ):
                return MASPlan(
                    planner_mode="python_generate",
                    topology_name="python:replay",
                    skill_id=skill.skill_id,
                    python_source=source,
                    rationale=(
                        "Prepared a statically valid same-mode Python skill for "
                        "the benchmark-owned validated subprocess runner."
                    ),
                    provenance="skill_replay",
                )
        return MASPlan(
            planner_mode="python_generate",
            topology_name="python:generated",
            python_source=default_python_program(worker_contract),
            rationale=(
                "Prepared the deterministic offline Python source. Validated "
                "subprocess execution is handled by the benchmark engine."
            ),
            provenance="fake",
        )


# 【职责】兜底方案：无任何匹配技能时按目标取默认拓扑与操作子。
def fallback_plan(request: PlannerRequest) -> MASPlan:
    topology = default_topology_for_objective(request)
    operators = operators_for_objective(request)
    return MASPlan(
        planner_mode=request.planner_mode,
        topology_name=topology,
        operators=operators,
        rationale="Fallback plan because no matching skills were available.",
    )


# 【职责】读取技能 confidence.risk_penalty(越低越安全)；缺省 0.0。
# - 由 consolidation._recompute_confidence 记为 min(0.4, 0.05*不同风险标签数)
# - 缺失/非数值按 0.0 计，风险惩罚项对无该字段的技能等于无操作
def _skill_risk_penalty(skill: SkillCard) -> float:
    """Read ``confidence.risk_penalty`` (lower is safer); default 0.0.

    Recorded by ``consolidation._recompute_confidence`` as
    ``min(0.4, 0.05 * len(distinct risk tags))``. Absent/non-numeric values
    contribute 0.0 so the risk term is a no-op for skills without it.
    """
    value = skill.confidence.get("risk_penalty")
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# 【职责】取"越低越好"损失用于绝对损失下限判断；缺失/非法视为 +inf。
# - score_skill 存于 breakdown['rmse']：通用基准为换算后的 mean_primary_loss，
#   CF 则为 mean_rmse(见 scoring.primary_loss_metric)
def _breakdown_loss(breakdown: dict[str, float]) -> float:
    """Lower-is-better loss for the absolute floor.

    ``score_skill`` stores this as ``breakdown['rmse']``, which is the converted
    ``mean_primary_loss`` when present (generic benchmarks) and otherwise
    ``mean_rmse`` (count-frequency). See ``scoring.primary_loss_metric``.
    """
    value = breakdown.get("rmse")
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


# 【职责】收集被匹配的避免/反例技能标记(否决)的拓扑名集合。
def _vetoed_topology_names(skill_bank: SkillBank, request: PlannerRequest) -> set[str]:
    """Topology names flagged by matching avoid/counterexample skills."""
    return {
        skill.topology_name
        for skill in skill_bank.retrieve_avoid(request)
        if skill.topology_name
    }


# 【职责】反例否决清空全部候选拓扑时使用的安全默认方案(兜底)。
def _veto_fallback_plan(request: PlannerRequest, vetoed: set[str]) -> MASPlan:
    """Safe-default plan used when every candidate topology is vetoed."""
    topology = default_topology_for_objective(request)
    operators = operators_for_objective(request)
    return MASPlan(
        planner_mode="topology_select",
        topology_name=topology,
        operators=operators,
        rationale=(
            "Counterexample veto excluded every candidate topology "
            f"{sorted(vetoed)}; fell back to safe default {topology} "
            f"for {request.objective.name}."
        ),
    )


# 【职责】最优候选损失越过损失下限时使用的安全默认方案(兜底)。
def _floor_fallback_plan(
    request: PlannerRequest,
    *,
    best_skill: SkillCard,
    best_loss: float,
    max_acceptable_loss: float,
) -> MASPlan:
    """Safe-default plan used when the best candidate violates the loss floor."""
    topology = default_topology_for_objective(request)
    operators = operators_for_objective(request)
    return MASPlan(
        planner_mode="topology_select",
        topology_name=topology,
        operators=operators,
        rationale=(
            f"Best candidate {best_skill.skill_id} loss {best_loss:g} exceeds the "
            f"acceptable loss floor {max_acceptable_loss:g}; fell back to safe "
            f"default {topology} for {request.objective.name}."
        ),
    )


# 【职责】按目标(accuracy_first/budget_first/balanced)与预算给出默认拓扑。
# - accuracy_first 且预算不紧 -> one_peer_exponential_dag_star；
#   budget_first 或预算紧 -> tree；其余 -> mesh_star
def default_topology_for_objective(request: PlannerRequest) -> str:
    if request.objective.name == "accuracy_first" and request.budget.level != "tight":
        return "one_peer_exponential_dag_star"
    if request.objective.name == "budget_first" or request.budget.level == "tight":
        return "tree"
    return "mesh_star"


# 【职责】按目标与预算给出默认操作子链(与上面的默认拓扑一一对应)。
def operators_for_objective(request: PlannerRequest) -> list[str]:
    if request.objective.name == "accuracy_first" and request.budget.level != "tight":
        return ["local_solve", "peer_propagate", "star_sink"]
    if request.objective.name == "budget_first" or request.budget.level == "tight":
        return ["local_solve", "tree_reduce"]
    return ["local_solve", "mesh_broadcast", "star_sink"]


# 【职责】从技能组织策略提取运行时覆盖(selected_primary、平均纳入覆盖门槛)。
def config_overrides_for_skill(skill: SkillCard) -> dict[str, object]:
    overrides: dict[str, object] = {}
    selected_primary = skill.organization_policy.get("selected_primary")
    if selected_primary is not None:
        overrides["selected_primary"] = selected_primary
    average_min = skill.organization_policy.get("average_include_min_coverage")
    if average_min is not None:
        overrides["average_include_min_coverage"] = average_min
    return overrides


# 【职责】取技能 fallback 映射中第一个非空值作为兜底技能 id；无则 None。
def fallback_skill_id(skill: SkillCard) -> str | None:
    fallback = skill.fallback
    for value in fallback.values():
        if value:
            return str(value)
    return None
