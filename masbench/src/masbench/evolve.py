"""QueenBee self-evolution loop on Silo-Bench, with the Plan-3 improvements ON.

``run_evolution`` wires the improved self-evolution end to end on Silo-Bench:

1. Split the filtered Silo instances into TRAIN and HELD-OUT (VAL) sets.
2. Run every TRAIN/VAL instance through the QueenBee planner + ProtocolRunner
   (the same machinery ``engine._run_planner`` uses) across a few objective
   variants so the planner genuinely selects several topologies, and turn each
   run summary into an aggregate row via ``summary_to_aggregate_row`` (generic).
3. Have ``ResultAnalystMinister`` propose skill patches from the TRAIN rows.
4. Apply them through the held-out **validation gate**
   (``consolidate_skill_updates(gate=True, validation_rows=...)``), accepting the
   batch only if it does not regress the held-out objective ``J_val``.
5. Return a summary with the real gate decision (``j_before``/``j_after``,
   accept/reject) and the pre/post held-out success rates.

The planner requests carry an :class:`ObjectiveSpec` with the Plan-3 improvement
knobs activated, so the loop exercises:

* **D** validation gate — ``consolidate_skill_updates(gate=True)``;
* **E** uncertainty-aware selection — ``uncertainty_weight`` (kappa) + ``min_seeds``;
* **F** counterexample veto + absolute floor — ``enforce_avoid_veto`` +
  ``max_acceptable_loss`` + ``risk_weight`` in ``TopologySelectPlanner.plan``.

Offline honesty
---------------
Silo's deterministic offline path is *topology-invariant on success*: a fake-LLM
run of a given case either solves it (loss 0) or not (loss 1), the same way for
every topology. Real offline Silo rows therefore cannot, by themselves, make one
topology look better than another on the held-out objective the gate uses. To
keep the gate decision **real** offline we let the caller supply a small synthetic
multi-topology held-out set (``held_out_rows``); the CLI defaults to one. The gate
arithmetic — which topology the planner selects on held-out data before vs. after
the patch batch, and whether ``J_val`` improves — is computed by the real gate.
With a real LLM (or multi-seed Silo runs that actually differ per topology) the
synthetic rows are unnecessary and ``held_out_rows`` can be left ``None``.
"""
# ============================================================
# 【模块导读】QueenBee 在 Silo-Bench 上的自进化闭环，Plan-3 各项改进全部开启。
# run_evolution 端到端串起改进后的自进化流程：
# 1. 把筛选后的 Silo 实例切成 TRAIN（训练）与 HELD-OUT（留出/VAL）两个集合。
# 2. 让每个 TRAIN/VAL 实例经 QueenBee 规划器 + ProtocolRunner（与 engine._run_planner
#    相同的机制）在若干目标变体下运行，使规划器真正选出多种拓扑；每次运行的总结经
#    summary_to_aggregate_row（通用）转成一条聚合行。
# 3. 由 ResultAnalystMinister（大臣：分析证据、提出技能补丁的角色）从 TRAIN 行提出技能补丁。
# 4. 补丁经"留出集验证门"应用（consolidate_skill_updates(gate=True, validation_rows=...)），
#    仅当整批补丁不使留出目标 J_val 退化时才接受。
# 5. 返回带真实门决策（j_before/j_after、接受/拒绝）及进化前后留出成功率的总结。
# 规划请求携带激活了 Plan-3 改进旋钮的 ObjectiveSpec，因此闭环实际演练：
# * D 验证门 —— consolidate_skill_updates(gate=True)；
# * E 不确定性感知选择 —— uncertainty_weight(kappa) + min_seeds；
# * F 反例否决 + 绝对风险下限 —— enforce_avoid_veto + max_acceptable_loss +
#   risk_weight（作用于 TopologySelectPlanner.plan）。
# 离线诚实性：Silo 的确定性离线路径"成败与拓扑无关"——fake-LLM 跑某个 case 要么解出
# （损失 0）要么不解（损失 1），对每种拓扑结果一致。因此真实的离线 Silo 行本身无法在
# 门所用的留出目标上让某个拓扑显得更好。为了让离线的门决策依然"真实"，允许调用方提供
# 一小组合成的多拓扑留出集（held_out_rows）；CLI 默认提供一组。门的算术——补丁批前后
# 规划器在留出数据上各选哪个拓扑、J_val 是否改善——由真实的门计算。换成真实 LLM
# （或各拓扑结果确实不同的多种子 Silo 运行）后合成行就没有必要，held_out_rows 可留 None。
# ============================================================

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from typing import Any

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.llm.base import LLMClient
from exp_graph.mas.consolidation import consolidate_skill_updates
from exp_graph.mas.evolution import ResultAnalystMinister
from exp_graph.mas.graph_generation import GraphGenerationError
from exp_graph.mas.insights import (
    LLMInsightMinister,
    build_evidence_pack,
    falsify_insights,
    insight_report_to_patches,
)
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.phase_program_generation import PhaseProgramGenerationError
from exp_graph.mas.python_code_generation import PythonGenerationError
from exp_graph.mas.motifs import aggregate_motif_losses, spec_motif_keys
from exp_graph.mas.runner import summary_to_aggregate_row
from exp_graph.mas.scoring import score_skill
from exp_graph.mas.schemas import (
    EvidenceRecord,
    MASRuntimeConfig,
    NamedTopologySkillPayload,
    ObjectiveSpec,
    PaperTransportSkillPayload,
    PlannerRequest,
    SkillCard,
    SkillPatch,
)
from exp_graph.mas.skill_payloads import (
    paper_protocol_from_skill,
    planner_mode_from_skill,
    program_sha256_from_skill,
    protocol_spec_from_skill,
    skill_type_for_payload,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols.schedules import build_protocol_schedule
from exp_graph.protocols.spec import ProtocolGraphSpec, ProtocolStepSpec
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig

from masbench import diag
from masbench.cache import EvidenceCache, open_cache, open_eval_cache
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_paper_protocols import (
    PAPER_PROTOCOL_ARMS,
    normalize_paper_protocol,
    run_silo_paper_protocol,
)
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.engine import (
    _build_llm_client,
    _plan_graph_generate,
    _plan_program_generate,
    _plan_python_generate,
    _protocol_adapter,
    _score_python_execution,
    _score_protocol_result,
)
from masbench.task_classify import (
    classification_bucket,
    classification_kind,
    classification_lossless_slot,
    classify_task,
)
from masbench.recipes import recipe_skill_card, search_recipe
from masbench.transfer import (
    MIN_TRUST_EM,
    bank_state_hash,
    deployment_view,
    inject_transfer_evidence,
    merge_structural_duplicates,
    namespace_motif_keys,
    skill_trusted_for,
    snapshot_transfer_evidence,
    stamp_rule_actions,
)

# 中文：Silo 规划器/进化所处的任务族。ResultAnalyst 大臣接受 task_family 参数，并把它
#   原生盖到每张产出的技能卡、其触发器及（按族命名空间化的）skill_id 上，因此规划器检索、
#   留出门与进化后的选择探针都在同一任务族内一致运作，无需任何事后重新打标。
# Task family the Silo planner/evolution operate in. The ResultAnalyst minister
# accepts a ``task_family`` argument and stamps every emitted skill card, its
# trigger, and its (family-namespaced) skill_id with this family natively, so the
# planner retrieval, the held-out gate, and the post-evolution selection probe all
# operate consistently in one family without any post-hoc re-tagging.
SILO_TASK_FAMILY = "silo"

_HOT_START_TAG = "hot-start"
_HOT_START_SINK_TOPOLOGIES = (
    "one_peer_exponential_dag_star",
    "mesh_star",
    "star",
    "chain",
    "tree",
    "two_stage_layer",
    "balanced_log_layer",
)
_HOT_START_ALL_AGENTS_TOPOLOGIES = (
    "one_peer_exponential_dag",
    "static_exponential",
)
_HOT_START_INNOVATION_MODES = {
    "graph_generate",
    "program_generate",
    "python_generate",
}
_PAPER_PROTOCOL_REASONING: dict[str, dict[str, object]] = {
    "p2p": {
        "transport": "dynamic targeted point-to-point",
        "receive_rule": "read unread messages from prior rounds before acting",
        "design_lesson": "send only useful deltas to selected recipients",
    },
    "broadcast": {
        "transport": "dynamic one-to-all broadcast",
        "receive_rule": "read prior-round broadcasts before acting",
        "design_lesson": "broadcast shared state when every agent needs it",
    },
    "sfs": {
        "transport": "round-delayed shared file store",
        "receive_rule": "list and read visible files before writing the next state",
        "design_lesson": "persist source-tagged state for asynchronous reuse",
    },
}


def _failed_generation_row(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    seed: int,
    classification: dict[str, Any],
    error: GraphGenerationError | PhaseProgramGenerationError | PythonGenerationError,
) -> dict[str, Any]:
    """Turn a structurally invalid generated candidate into learnable evidence."""
    mode = cfg.planner_mode
    is_program = mode == "program_generate"
    is_python = mode == "python_generate"
    failure_key = (
        "python_generation_failed"
        if is_python
        else "program_generation_failed"
        if is_program
        else "graph_generation_failed"
    )
    topology = (
        "python:invalid"
        if is_python
        else "program:invalid"
        if is_program
        else "generated:invalid"
    )
    n_agents = cfg.n_agents or instance.n_agents
    array_size = sum(
        len(shard) if isinstance(shard, (list, tuple, dict)) else 1
        for shard in instance.shards
    )
    return {
        "Topology": topology,
        "Agents": n_agents,
        "ArraySize": array_size,
        "MergeMode": cfg.merge_mode,
        "InitMode": cfg.init_mode,
        "Runs": 1,
        "MeanFinalRMSE": 1.0,
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": 1.0,
        "ExactMatchRate": 0.0,
        "MeanPrimaryMetric": 0.0,
        "PrimaryMetricName": "success_rate",
        "PartialCorrectness": 0.0,
        "MeanTotalSteps": 0.0,
        "MeanTotalMessages": 0.0,
        "MeanTotalModelCalls": 0.0,
        "MeanTokenCost": 0.0,
        "MeanVoteTopRatio": 0.0,
        "case_id": instance.case_id,
        "seed": seed,
        "task_family": _task_family(instance),
        "task_features_key": classification_bucket(classification),
        "task_agg_kind": classification_kind(classification),
        "task_needs_lossless": bool(classification.get("needs_lossless")),
        "task_answer_composite": bool(classification.get("answer_composite")),
        "information_goal": getattr(cfg, "silo_eval_mode", "sink") or "sink",
        "planner_mode": mode,
        "provenance": (
            "llm_generated_python"
            if is_python
            else "program_generated"
            if is_program
            else "llm_generated"
        ),
        "program_validity": 0.0,
        "structural_coverage": 0.0,
        "submission_rate": 0.0,
        "evolution_partial": 0.0,
        "evolution_success": 0.0,
        "evolution_stage": "validity",
        "evolution_stage_score": 0.0,
        "mean_primary_loss": 1.0,
        "paper_S": 0.0,
        "paper_P": 0.0,
        "paper_C": 0.0,
        "paper_D": 0.0,
        failure_key: error.reason,
    }


def _apply_information_goal_score(
    row: dict[str, Any],
    *,
    result: Any,
    instance: BenchmarkInstance,
    task_adapter: Any,
    global_task: dict[str, Any],
    information_goal: str,
) -> None:
    """Replace aggregate-holder scoring with the configured Silo mode score.

    ``ProtocolExperimentResult.to_summary_dict`` reports the protocol finalizer's
    selected/voted answer.  That is not the SILO all-agent criterion and can make
    a gather-only graph look successful when only its sink is correct.  Evolution
    evidence and gates must consume the same scorer as bench/eval.
    """
    score = _score_protocol_result(
        result,
        instance,
        task_adapter,
        global_task,
        extra={},
        information_goal=information_goal,
    )
    _apply_precomputed_information_goal_score(
        row,
        score=score,
        information_goal=information_goal,
        result=result,
        task_adapter=task_adapter,
    )


def _apply_precomputed_information_goal_score(
    row: dict[str, Any],
    *,
    score: Any,
    information_goal: str,
    result: Any | None = None,
    task_adapter: Any | None = None,
) -> None:
    """Attach common paper metrics and dense evolution signals to a row.

    ProtocolRunner and PythonGen have intentionally different execution models.
    They nevertheless need exactly the same V/K/U/P/S curriculum signal for a
    fair evolution gate.  ``score.extra`` is the common boundary; protocol-only
    state inspection remains an optional fallback for sink submissions.
    """
    row["ExactMatchRate"] = 1.0 if score.success else 0.0
    row["MeanPrimaryMetric"] = float(score.partial or 0.0)
    row["PartialCorrectness"] = float(score.partial or 0.0)
    row["information_goal"] = information_goal
    for key in (
        "paper_S",
        "paper_P",
        "paper_C",
        "paper_D",
        "per_agent_answers",
        "per_agent_correct",
        "per_agent_partial",
        "per_agent_submissions",
        "sink_id",
        "sink_information_coverage",
        "information_coverage_by_agent",
        "mean_information_coverage",
        "min_information_coverage",
        "all_agents_full_information",
    ):
        if key in score.extra:
            row[key] = score.extra[key]

    # Dense curriculum signal for evolution. The bands are deliberately ordered:
    # a program must become structurally valid, then complete information flow,
    # then obtain submissions, then improve answer quality, and only then earn
    # full-success credit. Cost remains a separately reported tie-breaker.
    validity = float(score.extra.get("program_validity", 1.0) or 0.0)
    if information_goal == "all_agents":
        coverage = float(score.extra.get("min_information_coverage", 0.0) or 0.0)
        submissions = list(score.extra.get("per_agent_submissions", []) or [])
        submitted = sum(
            1
            for item in submissions
            if isinstance(item, dict) and _is_real_submission(item.get("answer"))
        )
        submission_rate = submitted / len(submissions) if submissions else 0.0
        partial = float(score.extra.get("paper_P", score.partial or 0.0) or 0.0)
        success_signal = float(score.extra.get("paper_S", 0.0) or 0.0)
    else:
        coverage = float(score.extra.get("sink_information_coverage", 0.0) or 0.0)
        sink_id = int(score.extra.get("sink_id", 0) or 0)
        answer = None
        python_submissions = list(score.extra.get("python_submissions", []) or [])
        for submission in python_submissions:
            if (
                isinstance(submission, dict)
                and int(submission.get("agent_id", -1)) == sink_id
            ):
                answer = submission.get("answer")
                break
        states = list(getattr(result, "final_agent_states", []) or [])
        if answer is None and task_adapter is not None and 0 <= sink_id < len(states):
            answer = task_adapter.extract_protocol_answer(states[sink_id].belief_state)
        submission_rate = 1.0 if _is_real_submission(answer) else 0.0
        partial = float(score.partial or 0.0)
        success_signal = 1.0 if score.success else 0.0

    coverage = min(1.0, max(0.0, coverage))
    submission_rate = min(1.0, max(0.0, submission_rate))
    partial = min(1.0, max(0.0, partial))
    success_signal = min(1.0, max(0.0, success_signal))
    if validity < 1.0:
        staged = 0.0
        stage = "validity"
    elif coverage < 1.0:
        staged = 0.2 * coverage
        stage = "coverage"
    elif submission_rate < 1.0:
        staged = 0.2 + 0.2 * submission_rate
        stage = "submission"
    elif partial < 1.0:
        staged = 0.4 + 0.5 * partial
        stage = "partial"
    else:
        staged = 0.9 + 0.1 * success_signal
        stage = "success"
    row.update(
        {
            "program_validity": validity,
            "structural_coverage": coverage,
            "submission_rate": submission_rate,
            "evolution_partial": partial,
            "evolution_success": success_signal,
            "evolution_stage": stage,
            "evolution_stage_score": staged,
            "mean_primary_loss": 1.0 - staged,
        }
    )


def _is_real_submission(answer: Any) -> bool:
    if answer is None:
        return False
    if isinstance(answer, str):
        return answer.strip().lower() not in {"", "none", "null", "unknown"}
    return True


def _python_score_to_aggregate_row(
    score: Any,
    *,
    instance: BenchmarkInstance,
    cfg: RunConfig,
) -> dict[str, Any]:
    """Build the aggregate-row shape without pretending Python is a graph."""
    n_agents = cfg.n_agents or instance.n_agents
    array_size = sum(
        len(shard) if isinstance(shard, (list, tuple, dict)) else 1
        for shard in instance.shards
    )
    rounds = int(score.extra.get("rounds_executed", 0) or 0)
    return {
        "Topology": "python:generated",
        "Agents": n_agents,
        "ArraySize": array_size,
        "MergeMode": cfg.merge_mode,
        "InitMode": cfg.init_mode,
        "Runs": 1,
        "MeanFinalRMSE": 0.0 if score.success else 1.0,
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": 1.0 - float(score.partial or 0.0),
        "ExactMatchRate": 1.0 if score.success else 0.0,
        "MeanPrimaryMetric": float(score.partial or 0.0),
        "PrimaryMetricName": "success_rate",
        "PartialCorrectness": float(score.partial or 0.0),
        "MeanTotalSteps": float(rounds),
        "MeanTotalMessages": float(score.n_messages),
        "MeanTotalModelCalls": float(score.n_model_calls),
        "MeanTokenCost": float(score.tokens),
        "MeanVoteTopRatio": 0.0,
    }


# 【职责】返回实例所属的行/触发器任务族。
# - Silo 沿用其历史常量（保证路径逐字节一致）；其他基准（如 jssp）用自己的标签，
#   使台账、触发器与各道门绝不跨基准混用证据。
def _task_family(instance: BenchmarkInstance) -> str:
    """Row/trigger family for an instance.

    Silo keeps its historical constant (byte-identical paths); any other
    benchmark (e.g. jssp) uses its own tag so ledgers, triggers, and gates
    never mix evidence across benchmarks.
    """
    bench = str(getattr(instance, "benchmark", "") or "")
    if not bench or bench == "silo_bench":
        return SILO_TASK_FAMILY
    return bench


# 中文：规划目标上默认激活的 Plan-3 改进旋钮：开启 E（不确定性感知选择）与
#   F（反例否决 + 风险下限）；门 D 则由 consolidate_skill_updates(gate=True) 单独开启。
# Default Plan-3 improvement knobs activated on the planner objective. These turn
# on E (uncertainty-aware selection) and F (counterexample veto + risk floor); the
# gate (D) is turned on separately via ``consolidate_skill_updates(gate=True)``.
DEFAULT_UNCERTAINTY_WEIGHT = 1.0
DEFAULT_MIN_SEEDS = 1
DEFAULT_RISK_WEIGHT = 0.5
DEFAULT_MAX_ACCEPTABLE_LOSS = 0.99


# 【职责】构建规划器目标，并把 Plan-3 改进旋钮全部打开。
# - E：uncertainty_weight + min_seeds；F：enforce_avoid_veto + risk_weight + max_acceptable_loss。
def evolution_objective_spec(
    cfg: RunConfig,
    *,
    uncertainty_weight: float = DEFAULT_UNCERTAINTY_WEIGHT,
    min_seeds: int = DEFAULT_MIN_SEEDS,
    risk_weight: float = DEFAULT_RISK_WEIGHT,
    max_acceptable_loss: float | None = DEFAULT_MAX_ACCEPTABLE_LOSS,
) -> ObjectiveSpec:
    """Build the planner objective with the Plan-3 improvement knobs turned ON."""
    spec = ObjectiveSpec.from_name(cfg.objective)  # type: ignore[arg-type]
    return spec.model_copy(
        update={
            "uncertainty_weight": uncertainty_weight,
            "min_seeds": min_seeds,
            "enforce_avoid_veto": True,
            "risk_weight": risk_weight,
            "max_acceptable_loss": max_acceptable_loss,
        }
    )


# 【职责】把本次运行实际执行的可执行调度还原为 spec 字典。
# - 生成式计划自带 spec；命名拓扑(select)计划在 ProtocolRunner 内部编译调度，这里用
#   同一个构建器重建，让大臣能存下真正跑过的调度。
# - 这正是 select_then_refine 落地的关键：技能携带可执行参考调度，评估时
#   _skill_seeded_graph_candidates 能回放/精修它们，而不是只收到提示词上下文。
def _executed_spec(plan: Any, n_agents: int) -> dict[str, Any] | None:
    """The executable schedule this run actually executed, as a spec dict.

    Generated plans already carry their spec. Named-topology (select) plans
    compile their schedule inside ProtocolRunner; rebuild it here with the SAME
    builder so the minister can store the schedule that actually ran. This is
    what makes select_then_refine real: skills carry executable reference
    schedules, and ``_skill_seeded_graph_candidates`` can replay/refine them at
    eval instead of receiving prompt context only.
    """
    if plan.protocol_spec is not None:
        return diag.serialize_spec(plan.protocol_spec)
    try:
        steps = build_protocol_schedule(plan.topology_name, n_agents)
    except Exception:
        return None
    if not steps:
        return None
    last_receivers = {dst for _, dst in steps[-1].transmissions}
    metadata: dict[str, Any] = {
        "source": "named_topology",
        "graph_type": "temporal_dag",
    }
    if len(last_receivers) == 1:
        metadata["selected_primary"] = last_receivers.pop()
    return ProtocolGraphSpec(
        name=plan.topology_name,
        n_agents=n_agents,
        steps=[
            ProtocolStepSpec(
                transmissions=step.transmissions,
                description=step.description,
                operator="replay",
            )
            for step in steps
        ],
        metadata=metadata,
    ).model_dump(mode="json")


# 【职责】让单个实例走 QueenBee 规划器路径并返回其聚合行。
# - 镜像 engine._run_planner，但使用调用方提供的（旋钮开启的）ObjectiveSpec 与共享技能库，
#   使 Plan-3 的 E/F 选择旋钮在证据收集期间真正影响拓扑选择。
def _run_one(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    objective: ObjectiveSpec,
    skill_bank: SkillBank,
    seed: int,
    llm_client: LLMClient,
    motif_stats: dict[str, dict] | None = None,
    diag_phase: str = "",
) -> dict[str, Any]:
    """Run one instance through the QueenBee planner path and return its row.

    Mirrors ``engine._run_planner`` but uses a caller-supplied (knob-on)
    ``ObjectiveSpec`` and a shared ``SkillBank`` so the Plan-3 E/F selection knobs
    genuinely influence topology selection during evidence collection.
    """
    _goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    task_adapter = _protocol_adapter(instance, information_goal=_goal)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents

    # 中文：M18 断点续跑层：温度 0 下，(case、种子、规划旋钮、技能库内容、结构母题)
    #   唯一决定这次测量；设置 MASBENCH_EVAL_CACHE 后，已完成的行可跨重启回放，被中断的
    #   冻结判定运行得以续跑而非重新购买其成对样本。环境变量未设置：空操作。
    #   M18b（dev-15 取证）：只缓存部署阶段的行（diag_phase == ""）。进化内部行
    #   （证据/探索/门）必须保持新鲜：一轮被拒后链条会重置回空技能库，此时缓存的内部行
    #   会让之后每一轮都逐字节重放被拒的那一轮——精修链曾在 j 0.44->0.67 上冻结了
    #   三"轮"，实际只是同一次缓存计算。
    # M18 resume layer: at temperature 0, (case, seed, planner knobs, BANK
    # CONTENT, motif) determines the measurement; with MASBENCH_EVAL_CACHE
    # set, finished rows replay across relaunches so an interrupted frozen-
    # judge run resumes instead of repurchasing its pairs. Env unset: no-op.
    # M18b (dev-15 forensics): DEPLOYMENT rows only (diag_phase == "").
    # Evolution-internal rows (evidence/explore/gate) must stay fresh: a
    # rejected round resets the chain to an empty bank, and cached internal
    # rows then make every subsequent round a byte-identical replay of the
    # rejected one -- the refine chain stayed frozen at j 0.44->0.67 for
    # three "rounds" that were one cached computation.
    eval_cache = open_eval_cache() if not diag_phase else None
    eval_key: str | None = None
    if eval_cache is not None:
        state_hash = bank_state_hash(skill_bank, motif_stats)
        eval_key = "evalrow|" + EvidenceCache.key(
            case_id=instance.case_id, n_agents=n_agents,
            planner_mode=f"{cfg.planner_mode}@{state_hash}",
            objective=objective.name, seed=seed, cfg=cfg,
        )
        cached_row = eval_cache.get(eval_key)
        if cached_row is not None:
            return cached_row

    request = PlannerRequest(
        task_family=SILO_TASK_FAMILY,
        n_agents=n_agents,
        objective=objective,
        planner_mode=cfg.planner_mode,
        information_goal=_goal,
    )
    # 中文：M1/M7——该 case 的任务特征桶 + 聚合类别，由运行自身的 LLM 依据题面文本分类
    #   （与基准无关的问题；按文本哈希缓存；离线兜底到启发式）。行携带它们，迁移台账才能
    #   按桶/类别归因成功，下方的部署也据此设门。
    # M1/M7: the case's task-feature bucket + agg kind, classified from the
    # statement text by the run's own LLM (benchmark-agnostic questions;
    # cached per text hash; heuristic fallback offline). Rows carry them so
    # the transfer ledger can attribute success per bucket/kind, and
    # deployment is gated on them below.
    classification = classify_task(
        instance.task_prompt,
        llm_client=llm_client,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        source=getattr(cfg, "task_feature_source", "llm"),
    )
    feature_bucket = classification_bucket(classification)
    feature_kind = classification_kind(classification)
    feature_slot = classification_lossless_slot(classification)
    transfer_mode = (
        os.environ.get("MASBENCH_TRANSFER_GATE", "").strip()
        or getattr(cfg, "transfer_gate", "feature")
        or "feature"
    ).lower()
    abstained = False
    transfer_tier = "n/a"
    _planner_extra: dict[str, Any] = {}
    if cfg.planner_mode in {
        "graph_generate",
        "program_generate",
        "python_generate",
    }:
        # 中文：自设计证据：生成一个 DAG（冷启动、靠多候选保证多样），让大臣 + 结构母题
        #   闭环从真实生成的结构中学习，而不是只看拓扑选择。skill_bank 是每行新开的库；
        #   此处母题先验关闭（我们在测量哪些结构会赢，还不向它们偏置）。
        #   M1 迁移门：只有在本 case 特征桶里有实测成功的技能才可作为回放候选的种子；
        #   无可信技能 → 走严格冷路径（空库、无母题先验）——对表征未覆盖的 case 不造成伤害。
        # Self-design evidence: GENERATE a DAG (cold, diverse via candidates) so the
        # minister + motif loop learn from real generated structures, not topology
        # picks. skill_bank is the fresh per-row bank; the motif prior is OFF here
        # (we are MEASURING which structures win, not yet biasing toward them).
        # M1 transfer gate: only skills with measured success in THIS case's
        # feature bucket may seed replay candidates; nothing trusted -> the
        # exact cold path (empty bank, no motif prior) -- do no harm on
        # representationally-uncovered cases.
        _ft_raw = os.environ.get("MASBENCH_FALLBACK_TIER", "").strip().lower()
        _ft = (
            _ft_raw not in {"0", "false", "off"}
            if _ft_raw
            else bool(getattr(cfg, "fallback_tier", False))
        )
        view_bank, view_motif, abstained, transfer_tier = deployment_view(
            skill_bank, motif_stats, feature_bucket,
            kind=feature_slot, mode=transfer_mode, fallback_tier=_ft,
        )
        try:
            if cfg.planner_mode == "python_generate":
                planning, _planner_extra = _plan_python_generate(
                    cfg,
                    instance=instance,
                    n_agents=n_agents,
                    task_adapter=task_adapter,
                    global_task=global_task,
                    client=llm_client,
                    skill_bank=view_bank,
                )
                score = _score_python_execution(
                    planning,
                    instance=instance,
                    cfg=cfg,
                    task_adapter=task_adapter,
                    global_task=global_task,
                    extra={
                        "case_id": instance.case_id,
                        "planner": True,
                        "planner_mode": "python_generate",
                        "topology": "python:generated",
                        "objective": cfg.objective,
                        "program_validity": 1.0,
                        "silo_eval_mode": _goal,
                        **_planner_extra,
                    },
                )
                row = _python_score_to_aggregate_row(
                    score,
                    instance=instance,
                    cfg=cfg,
                )
                _apply_precomputed_information_goal_score(
                    row,
                    score=score,
                    information_goal=_goal,
                )
                execution = planning.execution
                output = execution.output
                usage = execution.authoritative_usage
                row.update(
                    {
                        "case_id": instance.case_id,
                        "seed": seed,
                        "task_family": _task_family(instance),
                        "task_features_key": feature_bucket,
                        "task_agg_kind": feature_kind,
                        "task_needs_lossless": bool(
                            classification.get("needs_lossless")
                        ),
                        "task_answer_composite": bool(
                            classification.get("answer_composite")
                        ),
                        "information_goal": _goal,
                        "planner_mode": "python_generate",
                        "provenance": planning.provenance,
                        "selected_skill_id": planning.selected_skill_id,
                        "python_source": planning.source,
                        "program_sha256": _planner_extra["program_sha256"],
                        "ast_policy_version": cfg.python_ast_policy_version,
                        "execution_contract_version": (
                            cfg.python_execution_contract_version
                        ),
                        "worker_contract": getattr(
                            cfg, "python_worker_contract", "action_json_v1"
                        ),
                        "repair_attempts": max(0, len(planning.attempts) - 1),
                        "python_artifacts_dir": str(planning.artifacts_dir),
                        "runtime_trace_summary": {
                            "rounds": int(output.rounds_executed) if output else 0,
                            "messages": len(output.messages) if output else 0,
                            "worker_model_calls": int(usage.model_calls),
                            "prompt_tokens": int(usage.prompt_tokens),
                            "completion_tokens": int(usage.completion_tokens),
                        },
                    }
                )
                if diag.enabled():
                    diag.dump_eval_run(
                        {
                            "case_id": instance.case_id,
                            "seed": seed,
                            "phase": diag_phase,
                            "planner_mode": "python_generate",
                            "evolved_mode": cfg.evolved_mode,
                            "n_agents": n_agents,
                            "bank_size": len(skill_bank),
                            "transfer_bucket": feature_bucket,
                            "transfer_kind": feature_kind,
                            "transfer_slot": feature_slot,
                            "transfer_abstained": abstained,
                            "transfer_tier": transfer_tier,
                            "topology": "python:generated",
                            "exact_match": row.get("ExactMatchRate"),
                            "messages": row.get("MeanTotalMessages"),
                            "model_calls": row.get("MeanTotalModelCalls"),
                            "tokens": row.get("MeanTokenCost"),
                            "program_sha256": row.get("program_sha256"),
                            "provenance": planning.provenance,
                        }
                    )
                if eval_cache is not None and eval_key is not None:
                    eval_cache.put(eval_key, row)
                return row
            if cfg.planner_mode == "program_generate":
                plan, _planner_extra = _plan_program_generate(
                    cfg,
                    n_agents=n_agents,
                    task_adapter=task_adapter,
                    client=llm_client,
                    skill_bank=view_bank,
                    motif_stats=view_motif,
                    instance=instance,
                )
            else:
                plan, _planner_extra = _plan_graph_generate(
                    cfg,
                    n_agents=n_agents,
                    task_adapter=task_adapter,
                    client=llm_client,
                    skill_bank=view_bank,
                    motif_stats=view_motif,
                )
        except (
            PhaseProgramGenerationError,
            GraphGenerationError,
            PythonGenerationError,
        ) as exc:
            row = _failed_generation_row(
                instance,
                cfg,
                seed=seed,
                classification=classification,
                error=exc,
            )
            if isinstance(exc, PythonGenerationError) and exc.artifacts_dir is not None:
                row["python_artifacts_dir"] = str(exc.artifacts_dir)
            if isinstance(exc, PythonGenerationError):
                row["python_failure_category"] = exc.error_type
            if eval_cache is not None and eval_key is not None:
                eval_cache.put(eval_key, row)
            return row
    else:
        plan = EmperorPlanner(skill_bank).plan(request)

    config_kwargs: dict[str, Any] = {
        "topology_name": plan.topology_name,
        "n_agents": n_agents,
        "seed": seed,
        "merge_mode": cfg.merge_mode,
        "init_mode": cfg.init_mode,
        "protocol_spec": plan.protocol_spec,
        "llm_provider": cfg.llm_provider,
        "model_name": cfg.model_name,
        "temperature": cfg.temperature,
        # 中文：M9——允许学到的逐步骤角色指引进入合并提示词
        #   （仅当实际执行的 spec 真的携带指令时才生效）。
        # M9: permit learned per-step role guidance to reach merge prompts
        # (only fires when the executed spec actually carries instructions).
        "enable_step_instructions": bool(getattr(cfg, "replay_rewrite", False)),
    }
    config_kwargs.update(plan.config_overrides)
    config = ProtocolRunnerConfig(**config_kwargs)

    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=llm_client,
    ).run()
    summary = result.to_summary_dict()
    row = summary_to_aggregate_row(summary)
    _apply_information_goal_score(
        row,
        result=result,
        instance=instance,
        task_adapter=task_adapter,
        global_task=global_task,
        information_goal=_goal,
    )
    # 中文：给行打上条件 + 任务族标签，使训练/留出分组能按 (n, case) 诚实进行，
    #   留出门在 silo 任务族内评估。
    # Tag the row with its condition + family so val/train grouping is honest per
    # (n, case) and the held-out gate evaluates in the silo family.
    row["case_id"] = instance.case_id
    row["seed"] = seed
    row["task_family"] = _task_family(instance)
    row["task_features_key"] = feature_bucket
    row["task_agg_kind"] = feature_kind
    row["task_needs_lossless"] = bool(classification.get("needs_lossless"))
    row["task_answer_composite"] = bool(classification.get("answer_composite"))
    # 中文：行携带信息目标与结构来源：技能卡的模式隔离、clean 入库判定与
    #   同模式 gate 校验都读取这两个字段。
    # Rows carry the information goal + structural provenance: card namespacing,
    # clean-bank admission, and the same-goal gate check all read these.
    row["information_goal"] = _goal
    row["planner_mode"] = cfg.planner_mode
    row["provenance"] = getattr(plan, "provenance", None) or (
        "llm_generated"
        if str(plan.topology_name).startswith("generated:")
        else "fixed_named"
    )
    row["selected_skill_id"] = getattr(plan, "skill_id", None)
    # A2: carry the executed schedule so minister skills can store it
    # (organization_policy.protocol_spec) and the refine eval can replay it.
    row["protocol_spec"] = _executed_spec(plan, n_agents)
    if (
        cfg.planner_mode in {"graph_generate", "program_generate"}
        and plan.protocol_spec is not None
    ):
        # Structural-motif evidence so the motif-credit loop can learn which
        # GENERATED structures (fan-in, depth, sink pattern) correlate with low
        # loss. Lower-is-better loss; offline this is topology-invariant.
        # M1: motif keys are bucket-namespaced so structural credit earned on
        # one task paradigm cannot bias generation on another.
        raw_motif_keys = spec_motif_keys(plan.protocol_spec)
        row["motif_keys"] = (
            namespace_motif_keys(raw_motif_keys, feature_bucket)
            if transfer_mode != "off"
            else raw_motif_keys
        )
    if diag.enabled():
        record: dict[str, Any] = {
            "case_id": instance.case_id,
            "seed": seed,
            "phase": diag_phase,
            "planner_mode": cfg.planner_mode,
            "evolved_mode": cfg.evolved_mode,
            "n_agents": n_agents,
            "bank_size": len(skill_bank),
            "transfer_bucket": feature_bucket,
            "transfer_kind": feature_kind,
            "transfer_slot": feature_slot,
            "transfer_abstained": abstained,
            "transfer_tier": transfer_tier,
            "topology": row.get("Topology"),
            "exact_match": row.get("ExactMatchRate"),
            "messages": row.get("MeanTotalMessages"),
            "model_calls": row.get("MeanTotalModelCalls"),
            "tokens": row.get("MeanTokenCost"),
            "motif_keys": row.get("motif_keys"),
            "spec": diag.serialize_spec(plan.protocol_spec),
            "graph_generation_failed": _planner_extra.get("graph_generation_failed"),
            "provenance": _planner_extra.get("provenance"),
        }
        if cfg.planner_mode in {"graph_generate", "program_generate"}:
            record["retrieved_skills"] = [
                {
                    "skill_id": s.skill_id,
                    "topology": (s.organization_policy or {}).get("topology_name"),
                    "has_executable_spec": isinstance(
                        (s.organization_policy or {}).get("protocol_spec"), dict
                    ),
                }
                for s in skill_bank.retrieve(request)
            ]
        diag.dump_eval_run(record)
    if eval_cache is not None and eval_key is not None:
        eval_cache.put(eval_key, row)
    return row


def _run_fixed_one(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    topology: str,
    seed: int,
    llm_client: LLMClient,
    diag_phase: str = "",
) -> dict[str, Any]:
    """Run one instance on a FIXED named topology (no planner).

    M3 portfolio evidence: the objective-variant detour only ever measures the
    planner-default topologies (peer-exponential/tree/mesh-star -- all
    aggregation organizations), so the minister could never learn a champion
    for sequential tasks. This measures explicitly-named portfolio topologies
    (e.g. ``chain``) on the same train grid so order-sensitive evidence exists
    when train contains level-II cases.
    """
    _goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    task_adapter = _protocol_adapter(instance, information_goal=_goal)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    config = ProtocolRunnerConfig(
        topology_name=topology,
        n_agents=n_agents,
        seed=seed,
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
    )
    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=llm_client,
    ).run()
    summary = result.to_summary_dict()
    row = summary_to_aggregate_row(summary)
    _apply_information_goal_score(
        row,
        result=result,
        instance=instance,
        task_adapter=task_adapter,
        global_task=global_task,
        information_goal=_goal,
    )
    classification = classify_task(
        instance.task_prompt,
        llm_client=llm_client,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        source=getattr(cfg, "task_feature_source", "llm"),
    )
    row["case_id"] = instance.case_id
    row["seed"] = seed
    row["task_family"] = _task_family(instance)
    row["task_features_key"] = classification_bucket(classification)
    row["task_agg_kind"] = classification_kind(classification)
    row["task_needs_lossless"] = bool(classification.get("needs_lossless"))
    row["task_answer_composite"] = bool(classification.get("answer_composite"))
    # 中文：具名拓扑证据行：provenance=fixed_named + 信息目标。clean GraphGen 库
    #   由此把 fixed 臂证据挡在检索/入库之外。
    # Named-topology evidence rows: provenance=fixed_named + information goal,
    # so clean GraphGen banks can exclude fixed-arm evidence entirely.
    row["information_goal"] = _goal
    row["provenance"] = "fixed_named"
    row["planner_mode"] = "fixed_named"
    try:
        steps = build_protocol_schedule(topology, n_agents)
    except Exception:
        steps = []
    if steps:
        last_receivers = {dst for _, dst in steps[-1].transmissions}
        metadata: dict[str, Any] = {
            "source": "named_topology",
            "graph_type": "temporal_dag",
        }
        if len(last_receivers) == 1:
            metadata["selected_primary"] = last_receivers.pop()
        row["protocol_spec"] = ProtocolGraphSpec(
            name=topology,
            n_agents=n_agents,
            steps=[
                ProtocolStepSpec(
                    transmissions=step.transmissions,
                    description=step.description,
                    operator="replay",
                )
                for step in steps
            ],
            metadata=metadata,
        ).model_dump(mode="json")
    if diag.enabled():
        diag.dump_eval_run(
            {
                "case_id": instance.case_id,
                "seed": seed,
                "phase": diag_phase,
                "planner_mode": f"fixed:{topology}",
                "evolved_mode": cfg.evolved_mode,
                "n_agents": n_agents,
                "bank_size": 0,
                "transfer_bucket": row["task_features_key"],
                "topology": row.get("Topology"),
                "exact_match": row.get("ExactMatchRate"),
                "messages": row.get("MeanTotalMessages"),
                "model_calls": row.get("MeanTotalModelCalls"),
                "tokens": row.get("MeanTokenCost"),
                "spec": row.get("protocol_spec"),
            }
        )
    return row


def _portfolio_topologies(cfg: RunConfig) -> list[str]:
    if cfg.planner_mode == "python_generate":
        return []
    raw = (
        os.environ.get("MASBENCH_EVIDENCE_PORTFOLIO")
        if os.environ.get("MASBENCH_EVIDENCE_PORTFOLIO") is not None
        else getattr(cfg, "evidence_portfolio", "chain")
    )
    topologies = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    # M15 portfolio parity: gen-mode evidence is generated rows only, so the
    # named aggregation organizations are never measured there -- its bank
    # could not hold the generalist that fixed/select ride (dev-8 beats_gen:
    # evolved abstained everywhere, 0.0 == coldgen pairwise, while
    # fixed=one_peer_exp took 33.3%). Refine mode already measures these via
    # the objective-variant detour; gen mode gets them explicitly.
    if topologies and cfg.planner_mode == "graph_generate":
        for named in ("one_peer_exponential_dag_star", "tree", "mesh_star"):
            if named not in topologies:
                topologies.append(named)
    return topologies


def _collect_portfolio_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    topologies: list[str],
    seeds: list[int],
    llm_client: LLMClient,
    workers: int = 1,
    progress: bool = False,
    phase: str = "",
) -> list[dict[str, Any]]:
    """Fixed-topology evidence rows (bank-independent -> cacheable)."""
    tasks = [
        (inst, topology, seed)
        for inst in instances
        for topology in topologies
        for seed in (seeds or [0])
    ]
    if not tasks:
        return []
    results: list[dict[str, Any] | None] = [None] * len(tasks)
    prog = _EvolveProgress(phase, len(tasks)) if progress else None
    cache = open_cache()

    def _do(index: int) -> tuple[int, dict[str, Any] | None]:
        inst, topology, seed = tasks[index]
        cache_key = (
            EvidenceCache.key(
                case_id=inst.case_id, n_agents=cfg.n_agents or inst.n_agents,
                planner_mode=f"fixed:{topology}", objective=cfg.objective,
                seed=seed, cfg=cfg,
            )
            if cache is not None
            else None
        )
        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return index, cached
        try:
            row = _run_fixed_one(
                inst, cfg, topology=topology, seed=seed, llm_client=llm_client,
                diag_phase=f"evidence:{phase}" if phase else "evidence",
            )
            if cache is not None and cache_key is not None:
                cache.put(cache_key, row)
            return index, row
        except Exception as exc:  # noqa: BLE001 - one bad run must not abort evolution
            print(
                f"  [evolve {phase}] portfolio {topology} run FAILED:"
                f" {type(exc).__name__}: {exc}",
                flush=True,
            )
            return index, None

    if workers and workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            futures = [executor.submit(_do, i) for i in range(len(tasks))]
            for future in as_completed(futures):
                index, row = future.result()
                results[index] = row
                if prog is not None:
                    prog.tick(ok=row is not None)
    else:
        for i in range(len(tasks)):
            index, row = _do(i)
            results[index] = row
            if prog is not None:
                prog.tick(ok=row is not None)
    return [row for row in results if row is not None]


def _hot_start_items(value: object) -> list[str]:
    """Normalize a comma-separated or sequence-valued hot-start setting."""
    if isinstance(value, (list, tuple, set)):
        raw = [str(item).strip() for item in value]
    else:
        raw = [item.strip() for item in str(value or "").split(",")]
    result: list[str] = []
    for item in raw:
        if item and item not in result:
            result.append(item)
    return result


def _resolve_hot_start_settings(
    cfg: RunConfig,
    instances: list[BenchmarkInstance],
) -> dict[str, Any]:
    """Resolve goal-aware defaults and reject ambiguous hot-start inputs."""
    enabled = bool(getattr(cfg, "hot_start_enabled", False))
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    if not enabled:
        return {
            "enabled": False,
            "information_goal": goal,
            "protocols": [],
            "topologies": [],
            "seed_count": 0,
            "dual_branch": False,
            "innovation_mode": None,
        }

    protocol_setting = getattr(cfg, "hot_start_protocols", "auto") or ""
    if (
        isinstance(protocol_setting, str)
        and protocol_setting.strip().lower() == "auto"
    ):
        protocols = list(PAPER_PROTOCOL_ARMS) if goal == "all_agents" else []
    else:
        protocols = [
            normalize_paper_protocol(item)
            for item in _hot_start_items(protocol_setting)
        ]
    if protocols and goal != "all_agents":
        raise ValueError(
            "hot-start SILO paper protocols require silo_eval_mode='all_agents'; "
            "use hot_start_protocols='' for sink training"
        )

    topology_setting = getattr(cfg, "hot_start_topologies", "auto") or ""
    if (
        isinstance(topology_setting, str)
        and topology_setting.strip().lower() == "auto"
    ):
        topologies = list(
            _HOT_START_ALL_AGENTS_TOPOLOGIES
            if goal == "all_agents"
            else _HOT_START_SINK_TOPOLOGIES
        )
    else:
        topologies = _hot_start_items(topology_setting)
    for topology in topologies:
        for n_agents in sorted({inst.n_agents for inst in instances}):
            try:
                build_protocol_schedule(topology, n_agents)
            except ValueError as exc:
                raise ValueError(
                    f"invalid hot-start topology {topology!r} for n={n_agents}: {exc}"
                ) from exc

    seed_count = int(getattr(cfg, "hot_start_seed_count", 1) or 0)
    if seed_count < 1:
        raise ValueError("hot_start_seed_count must be at least 1")
    innovation = str(
        getattr(cfg, "hot_start_innovation_mode", "auto") or "auto"
    ).strip().lower()
    if innovation == "auto":
        innovation = next(
            (
                mode
                for mode in (cfg.planner_mode, cfg.evolved_mode)
                if mode in _HOT_START_INNOVATION_MODES
            ),
            "graph_generate",
        )
    if innovation not in _HOT_START_INNOVATION_MODES:
        raise ValueError(
            "hot_start_innovation_mode must be auto, graph_generate, "
            "program_generate, or python_generate"
        )
    return {
        "enabled": True,
        "information_goal": goal,
        "protocols": protocols,
        "topologies": topologies,
        "seed_count": seed_count,
        "dual_branch": bool(getattr(cfg, "hot_start_dual_branch", True)),
        "innovation_mode": innovation,
    }


def _paper_protocol_row(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    protocol: str,
    seed: int,
    llm_client: LLMClient,
) -> dict[str, Any]:
    """Run one dynamic paper transport and adapt it to evolution evidence."""
    run_cfg = replace(cfg, seed=seed)
    score = run_silo_paper_protocol(
        instance,
        run_cfg,
        protocol=protocol,
        llm_client=llm_client,
    )
    row = _python_score_to_aggregate_row(score, instance=instance, cfg=run_cfg)
    selected = normalize_paper_protocol(protocol)
    classification = classify_task(
        instance.task_prompt,
        llm_client=llm_client,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        source=getattr(cfg, "task_feature_source", "llm"),
    )
    row.update(
        {
            "Topology": f"paper_{selected}",
            "case_id": instance.case_id,
            "seed": seed,
            "task_family": _task_family(instance),
            "task_features_key": classification_bucket(classification),
            "task_agg_kind": classification_kind(classification),
            "task_needs_lossless": bool(classification.get("needs_lossless")),
            "task_answer_composite": bool(classification.get("answer_composite")),
            "information_goal": "all_agents",
            "planner_mode": "hot_start_reference",
            "provenance": "fixed_named",
            "hot_start_source": "paper_protocol",
            "hot_start_protocol": selected,
        }
    )
    _apply_precomputed_information_goal_score(
        row,
        score=score,
        information_goal="all_agents",
    )
    return row


def _collect_hot_start_protocol_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    protocols: list[str],
    seeds: list[int],
    llm_client: LLMClient,
    workers: int,
    progress: bool,
) -> list[dict[str, Any]]:
    tasks = [
        (instance, protocol, seed)
        for instance in instances
        for protocol in protocols
        for seed in (seeds or [0])
    ]
    if not tasks:
        return []
    prog = _EvolveProgress("hot-start protocols", len(tasks)) if progress else None

    def _do(task: tuple[BenchmarkInstance, str, int]) -> dict[str, Any] | None:
        instance, protocol, seed = task
        try:
            return _paper_protocol_row(
                instance,
                cfg,
                protocol=protocol,
                seed=seed,
                llm_client=llm_client,
            )
        except Exception as exc:  # noqa: BLE001 - preserve the rest of the warm-up
            print(
                f"  [evolve hot-start] paper {protocol} {instance.case_id} "
                f"seed={seed} FAILED: {type(exc).__name__}: {exc}",
                flush=True,
            )
            return None

    if workers and workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            rows = []
            for row in executor.map(_do, tasks):
                rows.append(row)
                if prog is not None:
                    prog.tick(ok=row is not None)
    else:
        rows = []
        for task in tasks:
            row = _do(task)
            rows.append(row)
            if prog is not None:
                prog.tick(ok=row is not None)
    return [row for row in rows if row is not None]


def _hot_start_evidence_summary(skill: SkillCard) -> dict[str, Any]:
    rows = [row for row in skill.evidence if isinstance(row, dict)]

    def _mean(key: str) -> float:
        values = [
            float(row[key])
            for row in rows
            if row.get(key) is not None
        ]
        return sum(values) / len(values) if values else 0.0

    return {
        "n_observations": len(rows),
        "case_ids": sorted(
            {str(row["case_id"]) for row in rows if row.get("case_id")}
        ),
        "seeds": sorted(
            {int(row["seed"]) for row in rows if row.get("seed") is not None}
        ),
        "mean_program_validity": _mean("program_validity"),
        "mean_structural_coverage": _mean("structural_coverage"),
        "mean_submission_rate": _mean("submission_rate"),
        "mean_partial": _mean("evolution_partial"),
        "mean_success": _mean("evolution_success"),
        "mean_stage_score": _mean("evolution_stage_score"),
    }


def _hot_start_structure_code(
    *,
    topology: str,
    paper_protocol: str | None,
) -> dict[str, Any]:
    """Serializable executable descriptor stored beside the compiled artifact."""
    if paper_protocol is not None:
        return {
            "schema_version": "organization_code_v1",
            "language": "silo_paper_transport_v1",
            "entrypoint": (
                "masbench.adapters.silo_paper_protocols."
                "run_silo_paper_protocol"
            ),
            "source": (
                "run_silo_paper_protocol(instance, cfg, "
                f"protocol={paper_protocol!r}, llm_client=client)"
            ),
            "parameters": {"protocol": paper_protocol},
            "execution": "direct_dynamic_runner",
        }
    return {
        "schema_version": "organization_code_v1",
        "language": "named_topology_v1",
        "entrypoint": "exp_graph.protocols.schedules.build_protocol_schedule",
        "source": f"build_protocol_schedule({topology!r}, n_agents)",
        "parameters": {"topology_name": topology},
        "compiled_artifact_field": "mode_payload.protocol_spec",
        "execution": "direct_protocol_spec",
    }


def _decorate_hot_start_patches(
    patches: list[SkillPatch],
) -> list[SkillPatch]:
    """Mark executable fixed seeds vs dynamic context-only protocol cards."""
    decorated: list[SkillPatch] = []
    for patch in patches:
        skill = patch.candidate_skill
        if skill is None:
            decorated.append(patch)
            continue
        topology = str(skill.topology_name or "")
        is_paper = topology.startswith("paper_")
        tags = list(skill.tags)
        for tag in (
            _HOT_START_TAG,
            "hot-start-protocol" if is_paper else "hot-start-fixed",
            "reference-only" if is_paper else "executable-seed",
        ):
            if tag not in tags:
                tags.append(tag)
        policy = dict(skill.organization_policy)
        reasoning = dict(skill.reasoning_policy)
        paper_protocol: str | None = None
        if is_paper:
            paper_protocol = topology.removeprefix("paper_")
            policy.update(
                {
                    "planner_mode": "hot_start_reference",
                    "dynamic_transport": paper_protocol,
                    "protocol_spec": None,
                    "replayable": False,
                }
            )
            reasoning.update(_PAPER_PROTOCOL_REASONING.get(paper_protocol, {}))
            reasoning["submission_rule"] = "every agent independently submits"
        else:
            policy["hot_start_seed_topologies"] = [topology]
        policy["structure_code"] = _hot_start_structure_code(
            topology=topology,
            paper_protocol=paper_protocol,
        )
        if is_paper:
            mode_payload = PaperTransportSkillPayload(
                protocol=str(paper_protocol),
                structure_code=dict(policy["structure_code"]),
            )
        else:
            spec_data = policy.get("protocol_spec")
            mode_payload = (
                NamedTopologySkillPayload(
                    topology_name=topology,
                    protocol_spec=dict(spec_data),
                    structure_code=dict(policy["structure_code"]),
                )
                if isinstance(spec_data, dict)
                else skill.mode_payload
            )
        evidence_summary = _hot_start_evidence_summary(skill)
        insight_id = "hot_start_" + topology.replace(":", "_")
        insight_summary = (
            str(reasoning.get("design_lesson") or "Measured paper transport.")
            if is_paper
            else (
                f"Measured executable {topology} structure; preserve its "
                "temporal coverage pattern when the task goal matches."
            )
        )
        design_insights = list(skill.design_insights)
        if not any(item.get("insight_id") == insight_id for item in design_insights):
            design_insights.append(
                {
                    "insight_id": insight_id,
                    "type": "design_principle",
                    "status": "observed",
                    "title": f"Measured hot-start structure: {topology}",
                    "summary": insight_summary,
                    "evidence_summary": evidence_summary,
                }
            )
        expected_dynamics = dict(skill.expected_dynamics)
        expected_dynamics["hot_start_evidence_summary"] = evidence_summary
        confidence = dict(skill.confidence)
        confidence["hot_start_seed"] = True
        candidate = skill.model_copy(
            update={
                "organization_policy": policy,
                "mode_payload": mode_payload,
                "skill_type": skill_type_for_payload(mode_payload),
                "reasoning_policy": reasoning,
                "design_insights": design_insights,
                "expected_dynamics": expected_dynamics,
                "confidence": confidence,
                "tags": tags,
            }
        )
        decorated.append(
            patch.model_copy(
                update={
                    "patch_id": f"hot_start_{patch.patch_id}",
                    "candidate_skill": candidate,
                    "source": "hot_start_pretraining",
                }
            )
        )
    return decorated


def _runtime_cost_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": len(rows),
        "model_calls": int(
            sum(float(row.get("MeanTotalModelCalls", 0.0) or 0.0) for row in rows)
        ),
        "tokens": int(
            sum(float(row.get("MeanTokenCost", 0.0) or 0.0) for row in rows)
        ),
        "messages": int(
            sum(float(row.get("MeanTotalMessages", 0.0) or 0.0) for row in rows)
        ),
    }


def _skill_payload_audit(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize persisted mode formats and the supported update surface."""
    format_counts: dict[str, int] = defaultdict(int)
    missing_generated_payload: list[str] = []
    python_sources: list[dict[str, Any]] = []
    for skill in skills:
        payload = skill.get("mode_payload")
        payload = payload if isinstance(payload, dict) else {}
        payload_format = str(payload.get("format") or "legacy_or_context_only")
        format_counts[payload_format] += 1
        trigger = skill.get("trigger")
        trigger = trigger if isinstance(trigger, dict) else {}
        planner_mode = str(trigger.get("planner_mode") or "")
        tags = {str(tag).lower() for tag in skill.get("tags", [])}
        if (
            planner_mode in _HOT_START_INNOVATION_MODES
            and not payload
            and "counterexample" not in tags
        ):
            missing_generated_payload.append(str(skill.get("skill_id")))
        if payload_format == "python_skill_v1":
            source = payload.get("source_code")
            python_sources.append(
                {
                    "skill_id": skill.get("skill_id"),
                    "program_sha256": payload.get("program_sha256"),
                    "source_chars": len(source) if isinstance(source, str) else 0,
                    "source_persisted": bool(isinstance(source, str) and source),
                }
            )
    return {
        "format_counts": dict(sorted(format_counts.items())),
        "missing_generated_payload_skill_ids": sorted(missing_generated_payload),
        "python_sources": python_sources,
        "iterative_fields": [
            "mode_payload",
            "organization_policy",
            "reasoning_policy",
            "trigger",
            "expected_tradeoff",
            "expected_dynamics",
            "design_insights",
            "evidence",
            "evidence_refs",
            "counterexamples",
            "failure_modes",
            "risk_notes",
            "hypotheses",
            "fallback",
            "confidence",
            "validation_plan",
            "tags",
            "update_rule",
        ],
        "immutable_identity_fields": [
            "skill_id",
            "task_family",
            "information_goal",
            "provenance",
        ],
    }


def _seed_hot_start_bank(
    train_instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    settings: dict[str, Any],
    train_seeds: list[int],
    skill_bank: SkillBank,
    llm_client: LLMClient,
    workers: int,
    progress: bool,
    batch_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Measure supplied organizations once and seed the persistent bank."""
    existing_hot = [
        skill for skill in skill_bank if _HOT_START_TAG in skill.tags
    ]
    existing_hot_ids = sorted(skill.skill_id for skill in existing_hot)
    covered_topologies: set[str] = set()
    for skill in existing_hot:
        if "hot-start-fixed" not in skill.tags:
            continue
        sources = skill.organization_policy.get("hot_start_seed_topologies")
        if isinstance(sources, list):
            covered_topologies.update(str(source) for source in sources)
        else:
            covered_topologies.add(
                str(skill.topology_name)
            )
    covered_protocols = {
        str(paper_protocol_from_skill(skill))
        for skill in existing_hot
        if paper_protocol_from_skill(skill)
    }
    missing_topologies = [
        topology
        for topology in settings["topologies"]
        if topology not in covered_topologies
    ]
    missing_protocols = [
        protocol
        for protocol in settings["protocols"]
        if protocol not in covered_protocols
    ]
    if existing_hot_ids and not missing_topologies and not missing_protocols:
        return [], {
            **settings,
            "status": "reused_existing_seed",
            "bank_size_before": len(skill_bank),
            "bank_size_after": len(skill_bank),
            "seeded_skill_ids": existing_hot_ids,
            "n_pretrain_rows": 0,
            "n_fixed_rows": 0,
            "n_protocol_rows": 0,
            "cost": _runtime_cost_summary([]),
            "paired_ablation": [],
            "measured_topologies": [],
            "measured_protocols": [],
        }

    before = len(skill_bank)
    seed_count = int(settings["seed_count"])
    seeds = list(train_seeds or [0])[:seed_count]
    fixed_rows = _collect_portfolio_rows(
        train_instances,
        cfg,
        topologies=missing_topologies,
        seeds=seeds,
        llm_client=llm_client,
        workers=workers,
        progress=progress,
        phase=f"n={cfg.n_agents} hot-start fixed",
    )
    for row in fixed_rows:
        row["hot_start_source"] = "fixed_topology"
    protocol_rows = _collect_hot_start_protocol_rows(
        train_instances,
        cfg,
        protocols=missing_protocols,
        seeds=seeds,
        llm_client=llm_client,
        workers=workers,
        progress=progress,
    )
    rows = [*fixed_rows, *protocol_rows]
    if not rows:
        return [], {
            **settings,
            "status": "no_successful_pretrain_rows",
            "bank_size_before": before,
            "bank_size_after": len(skill_bank),
            "seeded_skill_ids": [],
            "n_pretrain_rows": 0,
            "n_fixed_rows": 0,
            "n_protocol_rows": 0,
            "cost": _runtime_cost_summary([]),
            "paired_ablation": [],
            "measured_topologies": missing_topologies,
            "measured_protocols": missing_protocols,
        }

    patches = ResultAnalystMinister().analyze(rows, task_family=SILO_TASK_FAMILY)
    # The warm bank is a portfolio of the explicitly supplied organizations,
    # exactly one positive card per item. Failures stay on those cards as
    # evidence/insights; separate avoid cards are learned by the normal round.
    patches = [patch for patch in patches if not _is_avoid_patch(patch)]
    patches = _filter_misfired_avoids(patches, rows)
    patches, paired_ablation = _paired_skill_ablation(
        patches,
        rows,
        strict=False,
    )
    patches = _decorate_hot_start_patches(patches)
    consolidate_skill_updates(
        bank=skill_bank,
        patches=patches,
        evidence_records=[],
        batch_id=f"{batch_id}_hot_start",
        gate=False,
    )
    # SkillBank merge intentionally preserves the incumbent card's lifecycle
    # tags.  Hot-start safety tags are semantic (especially reference-only), so
    # stamp them explicitly when a seed merged into an existing identity.
    for patch in patches:
        candidate = patch.candidate_skill
        if candidate is None:
            continue
        current = skill_bank.get(candidate.skill_id)
        if current is None:
            continue
        tags = list(current.tags)
        for tag in candidate.tags:
            if tag not in tags:
                tags.append(tag)
        skill_bank.skills[current.skill_id] = current.model_copy(update={"tags": tags})
    inject_transfer_evidence(skill_bank, rows)
    stamp_rule_actions(skill_bank)
    seeded_ids = sorted(
        skill.skill_id for skill in skill_bank if _HOT_START_TAG in skill.tags
    )
    return rows, {
        **settings,
        "status": "extended_existing_seed" if existing_hot_ids else "seeded",
        "bank_size_before": before,
        "bank_size_after": len(skill_bank),
        "seeded_skill_ids": seeded_ids,
        "n_pretrain_rows": len(rows),
        "n_fixed_rows": len(fixed_rows),
        "n_protocol_rows": len(protocol_rows),
        "cost": _runtime_cost_summary(rows),
        "paired_ablation": paired_ablation,
        "measured_topologies": missing_topologies,
        "measured_protocols": missing_protocols,
    }


def _innovation_context_bank(
    bank: SkillBank,
    *,
    parent_skill_id: str | None,
) -> tuple[SkillBank, list[str]]:
    """Keep one parent plus protocol references, but remove replay payloads."""
    selected: list[SkillCard] = []
    selected_ids: set[str] = set()
    parent = bank.get(parent_skill_id) if parent_skill_id else None
    if parent is not None:
        selected.append(parent)
        selected_ids.add(parent.skill_id)
    for skill in sorted(bank, key=lambda item: item.skill_id):
        if (
            "reference-only" in {tag.lower() for tag in skill.tags}
            and skill.skill_id not in selected_ids
        ):
            selected.append(skill)
            selected_ids.add(skill.skill_id)
    if not selected:
        selected = sorted(bank, key=lambda item: item.skill_id)[:1]
    copied = SkillBank(skills=[skill.model_copy(deep=True) for skill in selected])
    for skill in copied:
        policy = skill.organization_policy or {}
        policy["protocol_spec"] = None
        policy.pop("source_code", None)
        # Innovation may learn from the parent's evidence and insights, but it
        # must not replay any executable payload from any planner format.
        skill.mode_payload = None
    return copied, [skill.skill_id for skill in selected]


def _fallback_parent_skill_id(
    bank: SkillBank,
    cfg: RunConfig,
    *,
    n_agents: int,
    objective: ObjectiveSpec,
) -> str | None:
    request = PlannerRequest(
        task_family=SILO_TASK_FAMILY,
        n_agents=n_agents,
        objective=objective,
        planner_mode=cfg.planner_mode,
        information_goal=getattr(cfg, "silo_eval_mode", "sink") or "sink",
    )
    direct = bank.retrieve(request)
    context = bank.retrieve_generation_context(
        request.model_copy(update={"include_reference_skills": True})
    )
    candidates: list[SkillCard] = []
    seen: set[str] = set()
    for skill in [*direct, *context]:
        if skill.skill_id not in seen:
            candidates.append(skill)
            seen.add(skill.skill_id)
    if not candidates:
        return None
    ranked = []
    for skill in candidates:
        score, _breakdown = score_skill(
            skill,
            objective=objective,
            peers=candidates,
        )
        ranked.append((score, skill.skill_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][1]


def _reuse_bank_and_mode(
    bank: SkillBank,
    *,
    parent_skill_id: str | None,
    fallback_mode: str,
) -> tuple[SkillBank, str]:
    """Pin reuse to one parent and dispatch through that skill's own planner."""
    parent = bank.get(parent_skill_id) if parent_skill_id else None
    if parent is None:
        return bank, fallback_mode
    if paper_protocol_from_skill(parent):
        return SkillBank(skills=[parent.model_copy(deep=True)]), "paper_protocol"
    declared = str(
        planner_mode_from_skill(parent) or fallback_mode
    )
    mode = (
        declared
        if declared in {
            "topology_select",
            "graph_generate",
            "program_generate",
            "python_generate",
        }
        else "topology_select"
    )
    # Keep negative constraints alongside the one positive parent, but never let
    # another positive card silently replace the requested reuse candidate.
    cards = [parent.model_copy(deep=True)]
    cards.extend(
        skill.model_copy(deep=True)
        for skill in bank
        if "counterexample" in {tag.lower() for tag in skill.tags}
        and skill.skill_id != parent.skill_id
    )
    return SkillBank(skills=cards), mode


def _paper_protocol_from_skill(skill: SkillCard | None) -> str | None:
    if skill is None:
        return None
    typed = paper_protocol_from_skill(skill)
    if typed:
        return normalize_paper_protocol(typed)
    policy = skill.organization_policy or {}
    code = policy.get("structure_code")
    if isinstance(code, dict):
        parameters = code.get("parameters")
        if isinstance(parameters, dict) and parameters.get("protocol"):
            return normalize_paper_protocol(str(parameters["protocol"]))
    dynamic = policy.get("dynamic_transport")
    return normalize_paper_protocol(str(dynamic)) if dynamic else None


def _collect_hot_start_dual_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    settings: dict[str, Any],
    objective: ObjectiveSpec,
    skill_bank: SkillBank,
    seeds: list[int],
    llm_client: LLMClient,
    workers: int,
    progress: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """For every pair, run existing-skill reuse then parent-conditioned novelty."""
    if not settings.get("dual_branch"):
        return [], {
            "enabled": False,
            "innovation_mode": settings.get("innovation_mode"),
            "branches": {},
            "cost": _runtime_cost_summary([]),
        }
    tasks = [
        (instance, seed)
        for instance in instances
        for seed in (seeds or [0])
    ]
    innovation_mode = str(settings["innovation_mode"])
    prog = _EvolveProgress("hot-start dual", len(tasks) * 2) if progress else None

    def _pair(task: tuple[BenchmarkInstance, int]) -> list[dict[str, Any]]:
        instance, seed = task
        pair_id = f"{instance.case_id}|n={instance.n_agents}|seed={seed}"
        rows: list[dict[str, Any]] = []
        predicted_parent = _fallback_parent_skill_id(
            skill_bank,
            cfg,
            n_agents=cfg.n_agents or instance.n_agents,
            objective=objective,
        )
        reuse_bank, reuse_mode = _reuse_bank_and_mode(
            skill_bank,
            parent_skill_id=predicted_parent,
            fallback_mode=cfg.planner_mode,
        )
        reuse_row: dict[str, Any] | None = None
        try:
            if reuse_mode == "paper_protocol":
                parent = reuse_bank.get(predicted_parent or "")
                protocol = _paper_protocol_from_skill(parent)
                if parent is None or protocol is None:
                    raise ValueError("paper-protocol parent lacks executable code")
                reuse_row = _paper_protocol_row(
                    instance,
                    cfg,
                    protocol=protocol,
                    seed=seed,
                    llm_client=llm_client,
                )
                reuse_row["selected_skill_id"] = parent.skill_id
            else:
                reuse_row = _run_one(
                    instance,
                    replace(cfg, planner_mode=reuse_mode, replay_first=True),
                    objective=objective,
                    skill_bank=reuse_bank,
                    seed=seed,
                    llm_client=llm_client,
                    diag_phase="hot_start_reuse",
                )
            reuse_row.update(
                {
                    "hot_start_branch": "reuse",
                    "hot_start_pair_id": pair_id,
                    "hot_start_parent_skill_id": (
                        reuse_row.get("selected_skill_id") or predicted_parent
                    ),
                }
            )
            rows.append(reuse_row)
            if prog is not None:
                prog.tick(ok=True)
        except Exception as exc:  # noqa: BLE001 - innovation still runs
            print(
                f"  [evolve hot-start] reuse {pair_id} FAILED: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            if prog is not None:
                prog.tick(ok=False)

        parent_id = (
            str(reuse_row.get("selected_skill_id"))
            if reuse_row is not None and reuse_row.get("selected_skill_id")
            else predicted_parent
        )
        innovation_bank, context_ids = _innovation_context_bank(
            skill_bank,
            parent_skill_id=parent_id,
        )
        innovation_cfg = replace(
            cfg,
            planner_mode=innovation_mode,
            replay_first=False,
            graph_gen_temperature=(
                0.7 if innovation_mode != "python_generate" else cfg.graph_gen_temperature
            ),
            python_gen_temperature=(
                0.7 if innovation_mode == "python_generate" else cfg.python_gen_temperature
            ),
        )
        try:
            innovation_row = _run_one(
                instance,
                innovation_cfg,
                objective=objective,
                skill_bank=innovation_bank,
                seed=seed,
                llm_client=llm_client,
                diag_phase="hot_start_innovation",
            )
            innovation_row.update(
                {
                    "hot_start_branch": "innovation",
                    "hot_start_pair_id": pair_id,
                    "hot_start_parent_skill_id": parent_id,
                    "hot_start_context_skill_ids": context_ids,
                    "hot_start_context_exposed_to_architect": (
                        innovation_mode != "python_generate"
                    ),
                }
            )
            rows.append(innovation_row)
            if prog is not None:
                prog.tick(ok=True)
        except Exception as exc:  # noqa: BLE001 - one failed candidate is evidence loss
            print(
                f"  [evolve hot-start] innovation {pair_id} FAILED: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            if prog is not None:
                prog.tick(ok=False)
        return rows

    if workers and workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            nested = list(executor.map(_pair, tasks))
    else:
        nested = [_pair(task) for task in tasks]
    rows = [row for pair_rows in nested for row in pair_rows]
    branch_summary: dict[str, Any] = {}
    for branch in ("reuse", "innovation"):
        branch_rows = [row for row in rows if row.get("hot_start_branch") == branch]
        branch_summary[branch] = {
            "n_rows": len(branch_rows),
            "success_rate": _success_rate(branch_rows),
            "training_signal": _training_signal_summary(branch_rows),
            "selected_skill_ids": sorted(
                {
                    str(row["hot_start_parent_skill_id"])
                    for row in branch_rows
                    if row.get("hot_start_parent_skill_id")
                }
            ),
            "outputs": [
                {
                    "pair_id": row.get("hot_start_pair_id"),
                    "topology": row.get("Topology"),
                    "provenance": row.get("provenance"),
                    "program_validity": row.get("program_validity"),
                    "parent_skill_id": row.get("hot_start_parent_skill_id"),
                }
                for row in branch_rows
            ],
            "cost": _runtime_cost_summary(branch_rows),
        }
    return rows, {
        "enabled": True,
        "innovation_mode": innovation_mode,
        "n_pairs_requested": len(tasks),
        "n_rows": len(rows),
        "branches": branch_summary,
        "cost": _runtime_cost_summary(rows),
        "python_context_note": (
            "Python architect remains SkillBank-blind; innovation is independent "
            "after replay source removal."
            if innovation_mode == "python_generate"
            else None
        ),
    }


def _run_spec_on_instance(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    spec,
    seed: int,
    llm_client: LLMClient,
) -> tuple[float, dict[str, Any]]:
    """Execute one instruction-bearing spec; return (EM, procedural feedback)."""
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    task_adapter = _protocol_adapter(instance, information_goal=goal)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    config = ProtocolRunnerConfig(
        topology_name=f"generated:{spec.name}",
        n_agents=n_agents,
        seed=seed,
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
        protocol_spec=spec,
        enable_step_instructions=True,
    )
    result = ProtocolRunner(
        config=config, task_adapter=task_adapter,
        global_task=global_task, llm_client=llm_client,
    ).run()
    row = summary_to_aggregate_row(result.to_summary_dict())
    _apply_information_goal_score(
        row,
        result=result,
        instance=instance,
        task_adapter=task_adapter,
        global_task=global_task,
        information_goal=goal,
    )
    em = float(row.get("ExactMatchRate", 0.0))
    n_wrong = round((1.0 - em) * n_agents)
    feedback = {
        "wrong_agents": f"{n_wrong} of {n_agents} agents",
        "holder_state": (
            "correct" if em >= 0.99
            else "wrong or not shared by all agents"
        ),
    }
    return em, feedback


def _recipe_search_phase(
    train_instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    skill_bank: SkillBank,
    train_seeds: list[int],
    llm_client: LLMClient,
) -> tuple[list[dict[str, Any]], int]:
    """M10: manufacture VERIFIED anchor evidence where one-shot collection
    cannot (no skill trusted for a train case's bucket#slot). Returns
    (diag traces, runs spent). Verified recipes enter the bank as
    immediately-trusted, instruction-bearing skills (their ledger rows ARE
    their verification runs).
    """
    budget_raw = os.environ.get("MASBENCH_RECIPE_BUDGET", "").strip()
    budget = int(budget_raw) if budget_raw else int(getattr(cfg, "recipe_search_budget", 0))
    if budget <= 0:
        return [], 0
    traces: list[dict[str, Any]] = []
    runs_spent = 0
    base = train_seeds[0] if train_seeds else 0
    verify_seeds = [base, base + 7919]
    n_agents = cfg.n_agents or (train_instances[0].n_agents if train_instances else 2)
    max_steps = max(4, n_agents + 2)
    for inst in train_instances:
        if runs_spent >= budget:
            break
        if _task_family(inst) != SILO_TASK_FAMILY:
            # Recipe search is registered silo-scope for now: its prompt,
            # leakage scan, and verification target shard-text tasks. Other
            # benchmarks (jssp) evolve via the portfolio/minister/motif loop.
            continue
        classification = classify_task(
            inst.task_prompt, llm_client=llm_client, model_name=cfg.model_name,
            llm_provider=cfg.llm_provider,
            source=getattr(cfg, "task_feature_source", "llm"),
        )
        bucket = classification_bucket(classification)
        slot = classification_lossless_slot(classification)
        anchored = any(
            skill_trusted_for(skill, bucket, slot) for skill in skill_bank
        )
        if anchored:
            continue

        def _score(spec, seed, _inst=inst):
            nonlocal runs_spent
            runs_spent += 1
            try:
                return _run_spec_on_instance(
                    _inst, cfg, spec=spec, seed=seed, llm_client=llm_client
                )
            except Exception as exc:  # noqa: BLE001 - a failed attempt is feedback
                return 0.0, {"wrong_agents": "run failed", "holder_state": f"{type(exc).__name__}"}

        # M18: a VERIFIED recipe is a deterministic-keyed artifact -- resume
        # replays it instead of re-searching (the search is adaptive and
        # expensive; the artifact is just a spec).
        recipe_cache = open_eval_cache()
        # M23: key includes the ARCHITECT model -- a planner-model proposal
        # must never replay as a worker-model one (or vice versa).
        _arch = getattr(cfg, "planner_model_name", None) or cfg.model_name
        recipe_key = (
            f"recipe|{inst.case_id}|a{n_agents}|s{'-'.join(map(str, verify_seeds))}"
            f"|{_arch}"
        )
        spec = None
        trace: list[dict[str, Any]] = []
        if recipe_cache is not None:
            cached_spec = recipe_cache.get(recipe_key)
            if cached_spec is not None:
                from exp_graph.protocols.spec import ProtocolGraphSpec

                spec = ProtocolGraphSpec.model_validate(cached_spec["spec"])
                trace = [{"status": "resumed_from_cache"}]
        if spec is None:
            spec, trace = search_recipe(
                task_brief=(inst.task_prompt or "")[:1800],
                n_agents=n_agents, max_steps=max_steps,
                shards=list(inst.shards),
                llm_client=llm_client,
                # M23: recipe PROPOSALS are architect-side design work;
                # verification still EXECUTES on worker-model runs.
                model_name=getattr(cfg, "planner_model_name", None) or cfg.model_name,
                run_and_score=_score, verify_seeds=verify_seeds,
                attempts=4,
            )
            if spec is not None and recipe_cache is not None:
                recipe_cache.put(recipe_key, {"spec": spec.model_dump(mode="json")})
        traces.append({
            "case_id": inst.case_id, "bucket": bucket, "slot": slot,
            "verified": spec is not None, "trace": trace,
        })
        if spec is not None:
            card = recipe_skill_card(
                spec, task_family=SILO_TASK_FAMILY, bucket=bucket,
                lossless_slot=slot, n_agents=n_agents,
                verify_count=len(verify_seeds),
                source_case_id=inst.case_id,
            )
            skill_bank.apply_patch(
                SkillPatch(
                    patch_id=f"recipe_{card.skill_id}", action="add",
                    candidate_skill=card,
                )
            )
    return traces, runs_spent


def _rewrite_instructions_for_case(
    spec,
    inst: BenchmarkInstance,
    cfg: RunConfig,
    llm_client: LLMClient,
) -> list[str] | None:
    """One architect rewrite call: per-step instructions for spec on inst."""
    from exp_graph.mas.graph_generation import _INSTRUCTION_REWRITE_PROMPT

    structure = "\n".join(
        f"{idx}: " + ", ".join(f"{src}->{dst}" for src, dst in step.transmissions)
        for idx, step in enumerate(spec.steps)
    )
    prompt = _INSTRUCTION_REWRITE_PROMPT.format(
        task_brief=(inst.task_prompt or "")[:1500],
        n_steps=len(spec.steps),
        structure=structure,
    )
    architect_model = getattr(cfg, "planner_model_name", None) or cfg.model_name
    for _ in range(2):
        try:
            response = llm_client.complete(
                prompt, model_name=architect_model, temperature=cfg.temperature
            )
            raw = (getattr(response, "text", "") or "").strip()
            start, end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[start:end + 1]) if 0 <= start < end else {}
            candidate = data.get("instructions")
            if isinstance(candidate, list) and candidate:
                return [str(s).strip()[:300] for s in candidate if str(s).strip()]
        except Exception:
            continue
    return None


def _exemplar_phase(
    train_instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    skill_bank: SkillBank,
    train_seeds: list[int],
    llm_client: LLMClient,
) -> tuple[list[dict[str, Any]], int]:
    """M20: train-verified instruction exemplars for bucket champions.

    Deploy-time Modify rewrites are a fresh stochastic draw per deployment;
    dev-12b vs dev-13 measured 6-7 DISTINCT instruction sets per 8 seeds on
    the same structure with EM tracking the draw (6/8 vs 1/8). This phase
    writes instructions for the bucket champion's structure on a TRAIN
    anchor case, executes them on verification seeds, and stores a passing
    set on the card (``organization_policy.instruction_exemplars[bucket]``).
    The deployment view surfaces it; the rewrite prompt anchors on it.
    Train-time only -- zero test leakage.
    """
    budget_raw = os.environ.get("MASBENCH_EXEMPLAR_BUDGET", "").strip()
    budget = (
        int(budget_raw)
        if budget_raw
        else int(getattr(cfg, "exemplar_search_budget", 0))
    )
    if budget <= 0:
        return [], 0
    traces: list[dict[str, Any]] = []
    runs_spent = 0
    base = train_seeds[0] if train_seeds else 0
    verify_seeds = [base, base + 7919]
    done_buckets: set[str] = set()
    for inst in train_instances:
        if runs_spent >= budget:
            break
        if _task_family(inst) != SILO_TASK_FAMILY:
            continue
        classification = classify_task(
            inst.task_prompt, llm_client=llm_client, model_name=cfg.model_name,
            llm_provider=cfg.llm_provider,
            source=getattr(cfg, "task_feature_source", "llm"),
        )
        bucket = classification_bucket(classification)
        slot = classification_lossless_slot(classification)
        if bucket in done_buckets:
            continue
        view, _motif, abstained, _tier = deployment_view(
            skill_bank, None, bucket, kind=slot, mode="feature",
            fallback_tier=True,
        )
        if abstained or len(view) == 0:
            traces.append({"phase": "exemplar", "case_id": inst.case_id,
                           "bucket": bucket, "skip": "abstained"})
            continue
        # dev-14 silent no-op: the FIRST view card is often a spec-less
        # named/cf card; pick the first trusted card that carries a
        # replayable spec, and trace every skip path.
        champion = None
        spec = None
        for candidate_view in view:
            real = next(
                (s for s in skill_bank if s.skill_id == candidate_view.skill_id),
                None,
            )
            if real is None or real.organization_policy is None:
                continue
            spec_data = protocol_spec_from_skill(real)
            if not isinstance(spec_data, dict) or not spec_data.get("steps"):
                continue
            try:
                spec = ProtocolGraphSpec.model_validate(spec_data)
            except Exception:
                spec = None
                continue
            champion = real
            break
        if champion is None or spec is None:
            traces.append({"phase": "exemplar", "case_id": inst.case_id,
                           "bucket": bucket, "skip": "no_spec_bearing_champion"})
            continue
        exemplars = champion.organization_policy.get("instruction_exemplars")
        if isinstance(exemplars, dict) and bucket in exemplars:
            done_buckets.add(bucket)
            continue
        instructions = _rewrite_instructions_for_case(spec, inst, cfg, llm_client)
        if not instructions:
            traces.append({"phase": "exemplar", "case_id": inst.case_id,
                           "bucket": bucket, "skill_id": champion.skill_id,
                           "skip": "rewrite_failed"})
            continue
        instructed = spec.model_copy(
            update={
                "steps": [
                    step.model_copy(update={"instruction": instr})
                    for step, instr in zip(
                        spec.steps,
                        [*instructions, *[""] * len(spec.steps)][: len(spec.steps)],
                    )
                ]
            }
        )
        ems = []
        for seed in verify_seeds:
            if runs_spent >= budget:
                break
            em, _fb = _run_spec_on_instance(
                inst, cfg, spec=instructed, seed=seed, llm_client=llm_client
            )
            runs_spent += 1
            ems.append(em)
        verified = bool(ems) and (sum(ems) / len(ems)) >= MIN_TRUST_EM
        traces.append({
            "phase": "exemplar", "case_id": inst.case_id, "bucket": bucket,
            "skill_id": champion.skill_id, "verified": verified,
            "ems": ems,
        })
        if verified:
            store = champion.organization_policy.setdefault(
                "instruction_exemplars", {}
            )
            store[bucket] = {
                "steps": instructions[: len(spec.steps)],
                "case": inst.case_id,
                # M20b: anchors are SLOT-exact. dev-16: II-13's scalar
                # exemplar anchored II-19's composite rewrite -- variance
                # collapsed onto a BAD point (dominant set 1/6).
                "slot": slot,
                "em": sum(ems) / len(ems),
                "n": len(ems),
            }
            done_buckets.add(bucket)
    return traces, runs_spent


def _generation_gate(
    val_instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    val_seeds: list[int],
    llm_client: LLMClient,
    evolved_bank: SkillBank,
    motif_stats: dict[str, dict] | None,
    epsilon: float,
    objective: ObjectiveSpec,
    incumbent_bank: SkillBank | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """C: accept the learned state only if it improves held-out GENERATION.

    ``j_before`` = mean held-out primary loss when GENERATING with the PRE state
    (empty bank, no motif prior); ``j_after`` = with the evolved bank + motif
    prior. Accept iff ``j_after <= j_before + epsilon`` (accept-if-improves). This
    is the objective the self-design loop optimizes -- unlike the topology-select
    gate, it can actually move because generation quality varies with the learned
    state. Offline Silo is topology-invariant so ``j_before == j_after`` (accept).
    """
    cache = open_cache()

    def _one_loss(
        task: tuple[BenchmarkInstance, int],
        bank: SkillBank,
        stats: dict[str, dict] | None,
        phase_label: str,
    ) -> float:
        inst, seed = task
        # j_before (empty bank, no prior, cold generation) is round-
        # invariant -> cacheable; j_after depends on the bank -> never.
        cache_key = (
            EvidenceCache.key(
                case_id=inst.case_id, n_agents=cfg.n_agents or inst.n_agents,
                planner_mode="gate:before", objective=objective.name,
                seed=seed, cfg=cfg,
            )
            if cache is not None and phase_label == "gate:before"
            else None
        )
        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return float(cached["loss"])
        try:
            row = _run_one(
                inst, cfg, objective=objective, skill_bank=bank, seed=seed,
                llm_client=llm_client, motif_stats=stats,
                diag_phase=phase_label,
            )
        except Exception as exc:  # noqa: BLE001 - one wedged call must not abort evolution
            # A run that cannot complete IS a deployment failure for its
            # arm: charge max loss and keep gating (per-run isolation,
            # mirroring _collect_rows).
            print(
                f"  [evolve {phase_label}] {inst.case_id} seed={seed} FAILED:"
                f" {type(exc).__name__}: {exc}",
                flush=True,
            )
            return 1.0
        loss = float(
            row.get("mean_primary_loss", 1.0 - float(row.get("ExactMatchRate", 0.0)))
        )
        if cache is not None and cache_key is not None:
            cache.put(cache_key, {"loss": loss})
        return loss

    # M5: a 3-sample binary gate is a coin flip (dev round 1 rejected a
    # genuinely-good bank on cold 3/3 vs deployed 2/3). Evaluate each arm on
    # ``gate_seed_factor`` derived seeds per val seed; the derivation is
    # deterministic and never touches eval seeds (val INSTANCES only).
    factor_raw = os.environ.get("MASBENCH_GATE_SEED_FACTOR", "").strip()
    factor = int(factor_raw) if factor_raw else int(getattr(cfg, "gate_seed_factor", 1) or 1)
    gate_seeds = [
        seed + 1009 * k for k in range(max(1, factor)) for seed in (val_seeds or [0])
    ]

    def _mean_loss(
        bank: SkillBank, stats: dict[str, dict] | None, phase_label: str
    ) -> float:
        tasks = [
            (inst, seed)
            for inst in val_instances
            for seed in gate_seeds
        ]
        if not tasks:
            return 1.0
        # The (instance, seed) gate runs are independent; replayed organizations
        # are message-heavy (many serial merge calls), so a serial gate loop was
        # the longest pole of a round. Mean is order-independent -> parallel
        # fan-out is measurement-identical.
        if workers and workers > 1 and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
                losses = list(
                    ex.map(lambda t: _one_loss(t, bank, stats, phase_label), tasks)
                )
        else:
            losses = [_one_loss(t, bank, stats, phase_label) for t in tasks]
        return sum(losses) / len(losses)

    # M2 ratchet: when this round inherited a bank, the bar is the INCUMBENT
    # state's held-out generation loss, not the empty-bank cold loss -- a
    # round update must beat what we would deploy by rejecting it. (Round 1
    # has no incumbent, so the bar stays the cold loss, as before.) The
    # incumbent is measured without the motif prior (the prior is merged
    # outside run_evolution); documented approximation.
    if incumbent_bank is not None and len(incumbent_bank) > 0:
        j_before = _mean_loss(incumbent_bank, None, "gate:incumbent")
        gate_mode_label = "generation_ratchet"
    else:
        j_before = _mean_loss(SkillBank(), None, "gate:before")
        gate_mode_label = "generation"
    j_after = _mean_loss(evolved_bank, motif_stats, "gate:after")
    # M5 noise floor: tolerate exactly ONE discordant miss across the gate
    # grid (binary outcomes make j quantized in steps of 1/n); two or more
    # extra misses still reject. epsilon keeps its caller-set floor.
    n_samples = max(1, len(val_instances) * len(gate_seeds))
    epsilon_eff = max(epsilon, 1.0 / n_samples)
    return {
        "accepted": bool(j_after <= j_before + epsilon_eff),
        "j_before": j_before,
        "j_after": j_after,
        "epsilon": epsilon_eff,
        "n_samples": n_samples,
        "mode": gate_mode_label,
    }


def _evidence_record_from_row(row: dict[str, Any]) -> EvidenceRecord:
    """Adapt an evolution aggregate row to an EvidenceRecord for the insight pack.

    Maps the row's metrics to the lower-case keys the insight minister reads
    (mean_rmse / mean_messages / mean_token_cost / exact_match_rate).
    """
    exact = float(row.get("ExactMatchRate", 0.0))
    return EvidenceRecord(
        evidence_id=(
            f"agg:{row.get('case_id')}:n{row.get('Agents')}"
            f":s{row.get('seed')}:{row.get('Topology')}"
        ),
        source_type="aggregate",
        task_family=str(row.get("task_family", SILO_TASK_FAMILY)),
        topology_name=str(row.get("Topology", "")),
        n_agents=int(row["Agents"]) if row.get("Agents") is not None else None,
        seed=int(row["seed"]) if row.get("seed") is not None else None,
        metrics={
            "mean_rmse": float(row.get("MeanFinalRMSE", row.get("MeanPrimaryMetric", 0.0))),
            "mean_messages": float(row.get("MeanTotalMessages", 0.0)),
            "mean_token_cost": float(row.get("MeanTokenCost", 0.0)),
            "exact_match_rate": exact,
            "mean_primary_loss": float(row.get("mean_primary_loss", 1.0 - exact)),
        },
        status="observed",
    )


def _held_out_rows_for_falsify(val_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Held-out rows for falsify_insights: topology_name + a lower-is-better loss."""
    rows: list[dict[str, Any]] = []
    for r in val_rows:
        exact = float(r.get("ExactMatchRate", 0.0))
        rows.append(
            {
                "topology_name": str(r.get("Topology", "")),
                "n_agents": r.get("Agents"),
                "mean_primary_loss": float(r.get("mean_primary_loss", 1.0 - exact)),
                "mean_rmse": float(r.get("MeanFinalRMSE", r.get("MeanPrimaryMetric", 0.0))),
            }
        )
    return rows


def _llm_insight_patches(
    train_rows: list[dict[str, Any]],
    val_rows: list[dict[str, Any]],
    skill_bank: SkillBank,
    cfg: RunConfig,
    client: LLMClient,
    batch_id: str,
) -> int:
    """B2: LLM design-insight minister -> falsify vs held-out -> fold VERIFIED
    insights into the bank (so they drive generation). Returns #patches applied.

    Offline (fake) the minister uses its deterministic fallback. Verified-only
    (``require_verified=True``) so a plausible-but-wrong insight can't enter.
    """
    records = [_evidence_record_from_row(r) for r in train_rows]
    pack = build_evidence_pack(
        records=records, skill_bank=skill_bank, experiment_id=batch_id
    )
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
    )
    report = LLMInsightMinister(runtime=runtime, llm_client=client).analyze(
        evidence_pack=pack, skill_bank=skill_bank
    )
    report = falsify_insights(report, _held_out_rows_for_falsify(val_rows))
    patches = insight_report_to_patches(report, require_verified=True)
    if patches:
        skill_bank.apply_patches(patches)
    return len(patches)


# An avoid/counterexample rule must be earned by a real aggregate gap: the
# topology's MEAN primary loss must exceed the best topology's mean by this
# absolute margin. The engine's ratio rule (loss > best * 1.75) was designed for
# continuous CF RMSE; on per-(case,seed) BINARY Silo rows best is usually 0.0,
# so every topology with any miss got an avoid skill (round 1: avoid_{tree,
# mesh_star,peer_star} ALL advertised at once -> contradictory context, held-out
# generation dropped 54.2% -> 37.5%). With ~6 binary rows per topology the
# per-mean SE is ~0.19, so 0.25 demands a >1-SE real gap.
AVOID_MEAN_LOSS_GAP = 0.25

# The dominance CHAMPION (best mean loss) must itself be measured on at least
# this many rows to anchor avoid decisions. P2 round-1 bug: one lucky explored
# run (n=1, loss 0.0) became the anchor and every named topology -- including
# the deployed winner -- earned an avoid skill, polluting the generation prompt.
AVOID_CHAMPION_MIN_ROWS = 3


def _row_loss(row: dict[str, Any]) -> float:
    return float(row.get("mean_primary_loss", 1.0 - float(row.get("ExactMatchRate", 0.0))))


def _is_avoid_patch(patch: SkillPatch) -> bool:
    if str(patch.patch_id).startswith("counterexample"):
        return True
    skill = patch.candidate_skill
    return bool(skill and "cf_avoid_" in str(skill.skill_id))


def _filter_misfired_avoids(
    patches: list[SkillPatch],
    train_rows: list[dict[str, Any]],
) -> list[SkillPatch]:
    """Drop avoid patches whose topology is not genuinely dominated on means."""
    by_topology: dict[str, list[float]] = {}
    for row in train_rows:
        by_topology.setdefault(str(row.get("Topology", "")), []).append(_row_loss(row))
    means = {t: sum(v) / len(v) for t, v in by_topology.items() if v}
    if not means:
        return patches
    anchored = {
        t: m for t, m in means.items()
        if len(by_topology[t]) >= AVOID_CHAMPION_MIN_ROWS
    }
    if not anchored:
        # No well-measured champion -> no avoid decision can be earned.
        return [patch for patch in patches if not _is_avoid_patch(patch)]
    best = min(anchored.values())

    def keep(patch: SkillPatch) -> bool:
        if not _is_avoid_patch(patch):
            return True
        topology = str(
            (patch.candidate_skill.organization_policy or {}).get("topology_name", "")
            if patch.candidate_skill
            else ""
        )
        mean = means.get(topology)
        return mean is not None and (mean - best) >= AVOID_MEAN_LOSS_GAP

    return [patch for patch in patches if keep(patch)]


def _paired_skill_ablation(
    patches: list[SkillPatch],
    train_rows: list[dict[str, Any]],
    *,
    strict: bool,
) -> tuple[list[SkillPatch], list[dict[str, Any]]]:
    """Measure each proposed skill against alternatives on identical pairs.

    This consumes already-paid training rows: for each `(case, seed, n, goal)`
    it compares the candidate topology's dense loss with the best other measured
    topology. The result is persisted on the card. Strict mode rejects only a
    measured candidate with more losses than wins; ties and insufficient evidence
    remain visible but are not mislabelled as improvement.
    """
    grouped: dict[tuple[Any, ...], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in train_rows:
        key = (
            row.get("case_id"),
            row.get("seed"),
            row.get("Agents"),
            row.get("information_goal"),
        )
        grouped[key][_ablation_identity_from_row(row)].append(_row_loss(row))

    kept: list[SkillPatch] = []
    reports: list[dict[str, Any]] = []
    for patch in patches:
        skill = patch.candidate_skill
        if skill is None or _is_avoid_patch(patch):
            kept.append(patch)
            continue
        topology = str(skill.topology_name or "")
        candidate_identity = _ablation_identity_from_skill(skill)
        deltas: list[float] = []
        for by_topology in grouped.values():
            own = by_topology.get(candidate_identity)
            alternatives = [
                loss
                for other, losses in by_topology.items()
                if other != candidate_identity
                for loss in [sum(losses) / len(losses)]
            ]
            if own and alternatives:
                deltas.append((sum(own) / len(own)) - min(alternatives))
        wins = sum(delta < -1e-12 for delta in deltas)
        losses = sum(delta > 1e-12 for delta in deltas)
        ties = len(deltas) - wins - losses
        accepted = not deltas or not strict or losses <= wins
        status = (
            "insufficient_evidence"
            if not deltas
            else "rejected"
            if not accepted
            else "accepted_improved"
            if wins > losses
            else "accepted_no_change"
        )
        report = {
            "skill_id": skill.skill_id,
            "topology_name": topology,
            "n_pairs": len(deltas),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "mean_delta_loss": (
                sum(deltas) / len(deltas) if deltas else None
            ),
            "strict": strict,
            "status": status,
        }
        confidence = dict(skill.confidence)
        confidence["paired_ablation"] = report
        patch.candidate_skill = skill.model_copy(
            update={"confidence": confidence}
        )
        reports.append(report)
        if accepted:
            kept.append(patch)
    return kept, reports


def _ablation_identity_from_row(row: dict[str, Any]) -> str:
    if row.get("planner_mode") == "python_generate" and row.get("program_sha256"):
        return f"python:{row['program_sha256']}"
    return str(row.get("Topology", ""))


def _ablation_identity_from_skill(skill: SkillCard) -> str:
    digest = program_sha256_from_skill(skill)
    if planner_mode_from_skill(skill) == "python_generate" and digest:
        return f"python:{digest}"
    return str(skill.topology_name or "")


def _split_train_val(
    instances: list[BenchmarkInstance],
    *,
    bucket_of: Any = None,
) -> tuple[list[BenchmarkInstance], list[BenchmarkInstance]]:
    """Stable TRAIN/VAL split over the instance *set* (not over seeds).

    Silo instances are fixed per ``(case, n_agents)`` and the deterministic
    offline path is seed-invariant, so simulating seeds would yield identical
    rows and a degenerate gate. We split the instance set; with a single
    instance it lands in both so the loop still runs end to end.

    M24 (confirmatory attempt 1 root cause): the old bucket-BLIND even/odd
    carve silently sent a bucket's ONLY case to VAL when its sorted index
    was odd -- the os anchor (II-13) flipped parity when the registered
    confirmatory pool had 7 level-I cases instead of dev's 6, so NO os
    evidence was ever collected and every deployment abstained. The carve
    is now STRATIFIED PER TASK BUCKET (benchmark-agnostic classifier
    bucket; no case names): within each bucket, even local indices train /
    odd val; a bucket's SINGLETON case goes to BOTH (the function's
    existing single-instance precedent) so every measurable bucket always
    contributes evidence AND the gate keeps held-out rows.
    """
    ordered = sorted(instances, key=lambda inst: (inst.case_id, inst.n_agents))
    if len(ordered) == 1:
        return ordered, ordered
    if bucket_of is None:
        train = [inst for idx, inst in enumerate(ordered) if idx % 2 == 0]
        val = [inst for idx, inst in enumerate(ordered) if idx % 2 == 1]
    else:
        groups: dict[str, list[BenchmarkInstance]] = {}
        for inst in ordered:
            groups.setdefault(str(bucket_of(inst)), []).append(inst)
        train, val = [], []
        for _bucket, members in sorted(groups.items()):
            if len(members) == 1:
                train.extend(members)
                val.extend(members)
                continue
            train.extend(m for i, m in enumerate(members) if i % 2 == 0)
            val.extend(m for i, m in enumerate(members) if i % 2 == 1)
        order_index = {id(inst): i for i, inst in enumerate(ordered)}
        train.sort(key=lambda inst: order_index[id(inst)])
        val.sort(key=lambda inst: order_index[id(inst)])
    if not train:
        train = ordered
    if not val:
        val = ordered
    return train, val


def _curriculum_train_instances(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
) -> tuple[list[BenchmarkInstance], dict[str, Any]]:
    """Grow examples within every available level while keeping levels present."""
    enabled = bool(getattr(cfg, "curriculum_enabled", False))
    current = max(1, int(getattr(cfg, "curriculum_round", 1) or 1))
    total = max(current, int(getattr(cfg, "curriculum_total_rounds", 1) or 1))
    if not enabled or total <= 1:
        return instances, {
            "enabled": enabled,
            "round": current,
            "total_rounds": total,
            "selected_cases": [inst.case_id for inst in instances],
        }
    fraction = min(1.0, current / total)
    groups: dict[str, list[BenchmarkInstance]] = defaultdict(list)
    for inst in instances:
        level = str(inst.case_id).split("-", 1)[0]
        groups[level].append(inst)
    selected: list[BenchmarkInstance] = []
    for _level, members in sorted(groups.items()):
        ordered = sorted(members, key=lambda inst: (inst.n_agents, inst.case_id))
        count = max(1, math.ceil(len(ordered) * fraction))
        selected.extend(ordered[:count])
    selected.sort(key=lambda inst: (inst.case_id, inst.n_agents))
    return selected, {
        "enabled": True,
        "round": current,
        "total_rounds": total,
        "fraction": fraction,
        "selected_cases": [inst.case_id for inst in selected],
        "available_cases": [inst.case_id for inst in instances],
    }


def _success_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    # ExactMatchRate is 1.0 for a solved single run, 0.0 otherwise.
    return sum(float(row.get("ExactMatchRate", 0.0)) for row in rows) / len(rows)


def _training_signal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        stage = str(row.get("evolution_stage") or "unknown")
        counts[stage] = counts.get(stage, 0) + 1

    def mean(key: str) -> float:
        return (
            sum(float(row.get(key, 0.0) or 0.0) for row in rows) / len(rows)
            if rows
            else 0.0
        )

    return {
        "n_rows": len(rows),
        "stage_counts": counts,
        "mean_V": mean("program_validity"),
        "mean_K": mean("structural_coverage"),
        "mean_U": mean("submission_rate"),
        "mean_P": mean("evolution_partial"),
        "mean_S": mean("evolution_success"),
        "mean_stage_score": mean("evolution_stage_score"),
    }


def _incumbent_skill(topology: str, *, objective_name: str) -> SkillCard:
    """A deliberately-advertised incumbent skill the planner can select.

    Used to give the planner a concrete starting choice so the gate measures a
    real ``J_before`` (the held-out loss of this incumbent topology) against the
    ``J_after`` produced by the minister's TRAIN-derived patches. Tagged
    ``balanced`` so it is retrieved by both the knob-on planner requests and the
    gate's internal balanced request (``balanced`` is always in the allowed
    objective set), rather than relying on the planner's no-match fallback.
    """
    return SkillCard(
        skill_id=f"silo_incumbent_{topology}",
        objective="balanced",
        task_family=SILO_TASK_FAMILY,
        trigger={"task_family": SILO_TASK_FAMILY, "min_agents": 1, "max_agents": 999},
        organization_policy={
            "planner_mode": "topology_select",
            "topology_name": topology,
        },
        expected_tradeoff={
            "mean_rmse": 0.5,
            "mean_primary_loss": 0.5,
            "mean_token_cost": 1000.0,
            "mean_messages": 10.0,
            "active_evidence_count": 1,
        },
        confidence={"seed_count": 1},
        tags=["mas", "emperor-skill", "silo", objective_name],
    )


class _EvolveProgress:
    """Thread-safe, throttled progress printer for evolution row collection.

    The evolution pre-phase is hundreds of serial protocol runs with otherwise
    ZERO output -- which is exactly why a long run looks frozen. This emits ~20
    progress lines per phase so the user can see it working.
    """

    def __init__(self, phase: str, total: int) -> None:
        self._phase = phase
        self._total = total
        self._done = 0
        self._failed = 0
        self._start = time.monotonic()
        self._lock = threading.Lock()
        self._step = max(1, total // 20)

    def tick(self, ok: bool = True) -> None:
        with self._lock:
            self._done += 1
            if not ok:
                self._failed += 1
            if self._done == self._total or self._done % self._step == 0:
                elapsed = time.monotonic() - self._start
                print(
                    f"  [evolve {self._phase}] {self._done}/{self._total} runs"
                    f" ({self._failed} failed) {elapsed:5.1f}s",
                    flush=True,
                )


def _collect_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    objective_variants: list[ObjectiveSpec],
    seeds: list[int],
    llm_client: LLMClient,
    workers: int = 1,
    progress: bool = False,
    phase: str = "",
) -> list[dict[str, Any]]:
    """Collect real planner-run rows across objective variants.

    Each run uses a *fresh* empty ``SkillBank`` so the planner genuinely selects
    that objective's default topology (accuracy_first -> peer_star, budget_first
    -> tree, balanced -> mesh_star). Running every instance under several
    objectives yields multi-topology evidence, which is what lets the held-out
    validation gate make a non-degenerate accept/reject decision.

    The (instance, objective, seed) runs are independent (fresh ``SkillBank``
    each), so with ``workers > 1`` they fan out across a thread pool -- turning
    the otherwise-serial evolution pre-phase (hundreds of runs) from hours into
    minutes. Results preserve submission order so the aggregate is byte-identical
    to the serial path. A single run that fails (e.g. a hard ``LLMTimeoutError``
    from a wedged provider call) is dropped with a logged warning rather than
    aborting the whole evolution.
    """
    tasks = [
        (inst, objective, seed)
        for inst in instances
        for objective in objective_variants
        for seed in (seeds or [0])
    ]
    total = len(tasks)
    if total == 0:
        return []
    results: list[dict[str, Any] | None] = [None] * total
    prog = _EvolveProgress(phase, total) if progress else None

    cache = open_cache()

    def _do(index: int) -> tuple[int, dict[str, Any] | None]:
        inst, objective, seed = tasks[index]
        # Named evidence rows use a FRESH EMPTY bank by construction (bank-
        # independent); at temp 0 a cached row is the same measurement.
        cache_key = (
            EvidenceCache.key(
                case_id=inst.case_id, n_agents=cfg.n_agents or inst.n_agents,
                planner_mode=cfg.planner_mode, objective=objective.name,
                seed=seed, cfg=cfg,
            )
            if cache is not None
            else None
        )
        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return index, cached
        try:
            row = _run_one(
                inst,
                cfg,
                objective=objective,
                skill_bank=SkillBank(),
                seed=seed,
                llm_client=llm_client,
                diag_phase=f"evidence:{phase}" if phase else "evidence",
            )
            if cache is not None and cache_key is not None:
                cache.put(cache_key, row)
            return index, row
        except Exception as exc:  # noqa: BLE001 - one bad run must not abort evolution
            print(
                f"  [evolve {phase}] run {index + 1}/{total} FAILED:"
                f" {type(exc).__name__}: {exc}",
                flush=True,
            )
            return index, None

    if workers and workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=min(workers, total)) as executor:
            futures = [executor.submit(_do, i) for i in range(total)]
            for future in as_completed(futures):
                index, row = future.result()
                results[index] = row
                if prog is not None:
                    prog.tick(ok=row is not None)
    else:
        for i in range(total):
            index, row = _do(i)
            results[index] = row
            if prog is not None:
                prog.tick(ok=row is not None)

    return [row for row in results if row is not None]


def run_evolution(
    adapter: SiloBenchAdapter,
    *,
    cases: list[str] | None,
    agent_counts: list[int] | None,
    train_seeds: list[int],
    val_seeds: list[int],
    cfg: RunConfig,
    levels: list[str] | None = None,
    held_out_rows: list[dict[str, Any]] | None = None,
    seed_incumbent_topology: str | None = None,
    initial_skills: list[dict[str, Any]] | None = None,
    objective_variants: list[str] | None = None,
    epsilon: float = 0.0,
    batch_id: str = "silo_evolve_batch",
    llm_client: LLMClient | None = None,
    workers: int = 1,
    progress: bool = False,
) -> dict[str, Any]:
    """Run the gated QueenBee self-evolution loop on Silo-Bench.

    Returns a JSON-serializable summary with the real gate decision and the
    pre/post held-out success rates. See the module docstring for the offline
    honesty caveat about ``held_out_rows``.
    """
    objective = evolution_objective_spec(cfg)
    client = llm_client or _build_llm_client(cfg)

    # Evidence is collected across objective variants so the minister observes
    # several topologies. Each variant carries the same Plan-3 E/F knobs.
    variant_names = objective_variants or ["accuracy_first", "budget_first", "balanced"]
    variant_specs = [
        evolution_objective_spec(
            RunConfig(**{**asdict(cfg), "objective": name})
        )
        for name in variant_names
    ]

    instances = list(
        adapter.iter_instances(
            levels=levels,
            agent_counts=agent_counts,
            cases=cases,
        )
    )
    if not instances:
        raise SystemExit(
            "no Silo-Bench instances matched the given cases/agent-counts/levels"
        )

    # M24: the carve is stratified per classifier bucket so a bucket's only
    # case can never be silently excluded from evidence collection
    # (classification is the same benchmark-agnostic M7 call the pipeline
    # makes anyway; cached per text hash, heuristic fallback offline).
    def _carve_bucket(inst: BenchmarkInstance) -> str:
        classification = classify_task(
            inst.task_prompt, llm_client=client, model_name=cfg.model_name,
            llm_provider=cfg.llm_provider,
            source=getattr(cfg, "task_feature_source", "llm"),
        )
        return str(classification_bucket(classification))

    train_instances, val_instances = _split_train_val(
        instances, bucket_of=_carve_bucket
    )
    train_instances, curriculum = _curriculum_train_instances(
        train_instances,
        cfg,
    )
    hot_start_settings = _resolve_hot_start_settings(cfg, instances)

    # The evolving (held-out) bank is the one the gate mutates. Optionally seed an
    # incumbent so the gate has a concrete starting selection to improve on.
    # ``initial_skills`` seeds the bank from a prior round (the rounds-curve loop
    # accumulates the evolved bank across iterations).
    skill_bank = (
        SkillBank(skills=[SkillCard.model_validate(s) for s in initial_skills])
        if initial_skills
        else SkillBank()
    )
    if seed_incumbent_topology:
        skill_bank.apply_patch(
            SkillPatch(
                patch_id=f"seed_{seed_incumbent_topology}",
                action="add",
                candidate_skill=_incumbent_skill(
                    seed_incumbent_topology, objective_name=objective.name
                ),
            )
        )

    hot_start_rows: list[dict[str, Any]] = []
    hot_start_pretraining: dict[str, Any] = {
        **hot_start_settings,
        "status": "disabled",
        "n_pretrain_rows": 0,
        "n_fixed_rows": 0,
        "n_protocol_rows": 0,
        "seeded_skill_ids": [],
        "cost": _runtime_cost_summary([]),
        "paired_ablation": [],
    }
    if hot_start_settings["enabled"]:
        hot_start_rows, hot_start_pretraining = _seed_hot_start_bank(
            train_instances,
            cfg,
            settings=hot_start_settings,
            train_seeds=train_seeds,
            skill_bank=skill_bank,
            llm_client=client,
            workers=workers,
            progress=progress,
            batch_id=batch_id,
        )

    train_rows = _collect_rows(
        train_instances,
        cfg,
        objective_variants=variant_specs,
        seeds=train_seeds,
        llm_client=client,
        workers=workers,
        progress=progress,
        phase=f"n={cfg.n_agents} train",
    )
    if hot_start_rows:
        train_rows = [*hot_start_rows, *train_rows]

    hot_start_dual_rows: list[dict[str, Any]] = []
    hot_start_dual: dict[str, Any] = {
        "enabled": False,
        "innovation_mode": hot_start_settings.get("innovation_mode"),
        "branches": {},
        "cost": _runtime_cost_summary([]),
    }
    if hot_start_settings["enabled"]:
        hot_start_dual_rows, hot_start_dual = _collect_hot_start_dual_rows(
            train_instances,
            cfg,
            settings=hot_start_settings,
            objective=objective,
            skill_bank=skill_bank,
            seeds=train_seeds,
            llm_client=client,
            workers=workers,
            progress=progress,
        )
        train_rows = [*train_rows, *hot_start_dual_rows]
    # M3 portfolio: explicitly-named topologies the objective-variant detour
    # never measures (chain by default), so sequential-paradigm champions can
    # be learned when train contains order-sensitive cases.
    portfolio = _portfolio_topologies(cfg)
    n_portfolio_rows = 0
    if portfolio:
        # M27: build named-topology trust on more than the 2 train seeds
        # (single-os-anchor fragility). Derived seeds mirror M5's gate
        # expansion (s + 1009*k); factor 1 -> exactly train_seeds (no-op).
        _pf_raw = os.environ.get("MASBENCH_PORTFOLIO_SEED_FACTOR", "").strip()
        _pf = int(_pf_raw) if _pf_raw else int(getattr(cfg, "portfolio_seed_factor", 1) or 1)
        portfolio_seeds = [
            s + 1009 * k for k in range(max(1, _pf)) for s in train_seeds
        ]
        portfolio_rows = _collect_portfolio_rows(
            train_instances,
            cfg,
            topologies=portfolio,
            seeds=portfolio_seeds,
            llm_client=client,
            workers=workers,
            progress=progress,
            phase=f"n={cfg.n_agents} portfolio",
        )
        n_portfolio_rows = len(portfolio_rows)
        train_rows = [*train_rows, *portfolio_rows]
    # Phase-2 anti-saturation EXPLORATION: in refine mode, also generate
    # designs WITH the current bank (the deployed path) so self-generated
    # organizations enter the minister with executable specs and can join the
    # bank when they win. This is what lets round r+1 know more than round r --
    # without it, the named-topology evidence re-derives the same skills every
    # round and the rounds-curve saturates (phase-1 finding).
    explore_raw = os.environ.get("MASBENCH_EVOLVE_EXPLORE", "").strip()
    explore_n = int(explore_raw) if explore_raw else int(cfg.evolve_explore)
    n_explore_rows = 0
    # Round-12: exploration was refine-only; gen mode's per-round inputs were
    # therefore STATIC (cold evidence cache-hits every round, recipes only on
    # unanchored slots) and its rounds-curve provably flat (dev-7: 25.0 x3,
    # bank 10->10->10). Both generation-deploying modes now explore.
    if cfg.evolved_mode in (
        "select_then_refine",
        "graph_generate",
        "program_generate",
        "python_generate",
    ) and explore_n > 0 and not (
        hot_start_settings["enabled"] and hot_start_settings["dual_branch"]
    ):
        explore_mode = (
            cfg.evolved_mode
            if cfg.evolved_mode in {
                "graph_generate",
                "program_generate",
                "python_generate",
            }
            else "graph_generate"
        )
        explore_cfg = replace(
            cfg,
            planner_mode=explore_mode,
            graph_gen_temperature=0.7,
            python_gen_temperature=(
                0.7 if explore_mode == "python_generate" else cfg.python_gen_temperature
            ),
        )
        # Exploration must produce NEW designs: with executable specs in the
        # bank, seeded replay candidates fill every generation slot and
        # exploration degenerates into re-measuring known organizations. Strip
        # the specs from a COPY -- prose context (lessons/tradeoffs) still
        # informs the generation, deployment keeps the full bank. Bad explored
        # designs are filtered by evidence + the held-out gate.
        explore_bank = SkillBank(
            skills=[skill.model_copy(deep=True) for skill in skill_bank]
        )
        for skill in explore_bank:
            if isinstance((skill.organization_policy or {}).get("protocol_spec"), dict):
                skill.organization_policy["protocol_spec"] = None
            if explore_mode == "python_generate":
                skill.organization_policy.pop("source_code", None)
            skill.mode_payload = None
        explore_tasks = [
            (inst, seed)
            for inst in train_instances
            for seed in (train_seeds or [0])[:explore_n]
        ]

        def _explore(task: tuple[BenchmarkInstance, int]) -> dict[str, Any] | None:
            inst, seed = task
            try:
                return _run_one(
                    inst, explore_cfg, objective=objective, skill_bank=explore_bank,
                    seed=seed, llm_client=client, diag_phase="explore",
                )
            except Exception as exc:  # noqa: BLE001 - one bad explore run is dropped
                print(
                    f"  [evolve explore] {inst.case_id} seed={seed} FAILED:"
                    f" {type(exc).__name__}: {exc}",
                    flush=True,
                )
                return None

        if workers and workers > 1 and len(explore_tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(explore_tasks))) as ex:
                explore_rows = [r for r in ex.map(_explore, explore_tasks) if r is not None]
        else:
            explore_rows = [r for t in explore_tasks if (r := _explore(t)) is not None]
        n_explore_rows = len(explore_rows)
        train_rows = [*train_rows, *explore_rows]
    # Single-gate architecture: modes that deploy GENERATION are vetted by the
    # generation gate (its own runs below); the selection gate -- the only
    # consumer of val evidence rows besides optional insight falsification --
    # is inactive there, so collecting val evidence would be pure spend.
    deploys_generation_mode = (
        cfg.planner_mode
        in {"graph_generate", "program_generate", "python_generate"}
        or cfg.evolved_mode == "select_then_refine"
    )
    needs_val_rows = (not deploys_generation_mode) or cfg.use_llm_insights
    val_rows_real = (
        _collect_rows(
            val_instances,
            cfg,
            objective_variants=variant_specs,
            seeds=val_seeds,
            llm_client=client,
            workers=workers,
            progress=progress,
            phase=f"n={cfg.n_agents} val",
        )
        if needs_val_rows
        else []
    )
    if needs_val_rows and portfolio:
        # The selection gate scores the planner's pick on val rows; a portfolio
        # topology the minister advertises must be MEASURED there too, or the
        # unmeasured-topology penalty auto-rejects every batch containing it.
        val_rows_real = [
            *val_rows_real,
            *_collect_portfolio_rows(
                val_instances,
                cfg,
                topologies=portfolio,
                seeds=val_seeds,
                llm_client=client,
                workers=workers,
                progress=progress,
                phase=f"n={cfg.n_agents} val portfolio",
            ),
        ]

    # Held-out validation rows the gate scores against: real Silo VAL rows plus
    # any caller-supplied synthetic multi-topology rows (see module docstring).
    val_rows = [*val_rows_real, *(held_out_rows or [])]

    # The minister stamps every emitted skill (card, trigger, and namespaced id)
    # with the run's family natively, so retrieval, the held-out gate, and the
    # selection probe all operate in one family with no post-hoc re-tagging.
    # Family comes from the rows themselves (silo rows carry "silo" exactly as
    # before; jssp rows carry "jssp" so cross-benchmark evidence never mixes).
    _row_family = next(
        (str(r.get("task_family")) for r in train_rows if r.get("task_family")),
        SILO_TASK_FAMILY,
    )
    patches = ResultAnalystMinister().analyze(
        train_rows, task_family=_row_family
    )
    # Round-1 root cause: the engine's ratio dominance rule misfires on binary
    # per-case rows (best=0 -> everything "dominated") and advertises avoid
    # skills for EVERY topology. Require a real mean-loss gap instead.
    patches = _filter_misfired_avoids(patches, train_rows)
    patches, skill_ablation = _paired_skill_ablation(
        patches,
        train_rows,
        strict=bool(getattr(cfg, "skill_ablation_strict", False)),
    )

    # Held-out gate mode: "auto" gates on the DEPLOYED objective (generation loss
    # when the evolved state will GENERATE at eval, selection J otherwise);
    # "off" disables held-out gating entirely (the drift-ablation arm). The env
    # var lets frozen drivers (scripts/verify_evolve.py) run the ablation.
    gate_mode = (
        os.environ.get("MASBENCH_GATE_MODE", "").strip() or cfg.gate_mode or "auto"
    ).lower()
    pre_skills = [skill.model_dump(mode="json") for skill in skill_bank]
    # M1: the inherited per-bucket ledgers, snapshotted BEFORE patches (merge
    # patches overwrite organization_policy keys; accumulation happens at
    # inject time). M2: the incumbent the ratchet gate must beat is the bank
    # INHERITED from the previous round (initial_skills) -- not the synthetic
    # seeded incumbent, which exists only for selection-gate measurement.
    pre_transfer_ledgers = snapshot_transfer_evidence(skill_bank)
    incumbent_bank = (
        SkillBank(skills=[SkillCard.model_validate(s) for s in pre_skills])
        if hot_start_settings["enabled"]
        else SkillBank(skills=[SkillCard.model_validate(s) for s in initial_skills])
        if initial_skills
        else None
    )

    # ONE gate per deployed objective: modes that GENERATE at eval are vetted by
    # the held-out GENERATION gate below; gating their patch application on
    # topology-SELECTION J as well both double-gates and mis-scores -- the
    # selection objective charges generated:* skills an unmeasured-topology
    # penalty on named-evidence val rows, rejecting legitimate exploration
    # (phase-2 explore rows made this bind). Selection-deploying mode keeps the
    # selection gate.
    deploys_generation = (
        cfg.planner_mode
        in {"graph_generate", "program_generate", "python_generate"}
        or cfg.evolved_mode == "select_then_refine"
    )
    selection_gate_active = gate_mode != "off" and not deploys_generation
    size_before = len(skill_bank)
    _bank, result = consolidate_skill_updates(
        bank=skill_bank,
        patches=patches,
        evidence_records=[],
        batch_id=batch_id,
        validation_rows=val_rows,
        epsilon=epsilon,
        gate=selection_gate_active,
    )
    # B2: fold VERIFIED LLM design insights into the bank so they drive generation.
    n_insight_patches = 0
    if cfg.use_llm_insights:
        n_insight_patches = _llm_insight_patches(
            train_rows, val_rows, skill_bank, cfg, client, batch_id
        )
    # M1: per-(skill, feature-bucket) success ledger -- combines this round's
    # measured rows with the inherited ledger so deployment trust accumulates
    # across rounds instead of resetting.
    inject_transfer_evidence(skill_bank, train_rows, prior=pre_transfer_ledgers)
    # M11/M13c: same-structure cards merge into one family member so trust
    # evidence accumulates per STRUCTURE and the bank stops growing linearly.
    n_merged_duplicates = merge_structural_duplicates(skill_bank)
    # M13: explicit Preserve/Modify/Avoid design-rule action on every card.
    stamp_rule_actions(skill_bank)
    # M10: for train cases whose bucket#slot has NO trusted skill, search a
    # verified recipe (structure + per-step instructions) against the train
    # signal; verified recipes enter the bank trusted (their ledger rows are
    # their verification runs) and the gate below vets the whole state.
    if cfg.planner_mode == "python_generate":
        recipe_traces, n_recipe_runs = [], 0
    else:
        recipe_traces, n_recipe_runs = _recipe_search_phase(
            train_instances, cfg, skill_bank=skill_bank,
            train_seeds=train_seeds, llm_client=client,
        )
    # M20: train-verify an instruction EXEMPLAR for the bucket champion so
    # deploy-time Modify rewrites anchor on a proven style instead of
    # re-rolling per deployment (instruction-draw variance was the gen-vs-
    # select instability: 6-7 distinct sets per 8 seeds, EM tracked the draw).
    if cfg.planner_mode == "python_generate":
        exemplar_traces, n_exemplar_runs = [], 0
    else:
        exemplar_traces, n_exemplar_runs = _exemplar_phase(
            train_instances, cfg, skill_bank=skill_bank,
            train_seeds=train_seeds, llm_client=client,
        )
    size_after = len(skill_bank)

    # Post-evolution selection probe: run the knob-on planner against the (now
    # populated) evolved bank. Unlike evidence collection (which uses fresh empty
    # banks and therefore falls back to objective defaults), this genuinely
    # executes the E (LCB + min-seeds) and F (veto + floor + risk) selection logic
    # on real skills, so the improvement knobs are exercised, not merely set.
    final_selection = _selection_probe(skill_bank, cfg.n_agents or 2, objective)

    accepted = bool(result.gate_accepted) if selection_gate_active else True
    # B1: in self-design mode, aggregate the GENERATED evidence into a structural-
    # motif credit map (which fan-in/depth/sink patterns correlate with low loss).
    # Carried in the summary so the eval can bias generation toward winning motifs.
    motif_stats = (
        aggregate_motif_losses(train_rows)
        if any("motif_keys" in row for row in train_rows)
        else {}
    )
    # C: when the evolved state will GENERATE at eval (graph_generate evidence, or
    # select_then_refine whose deployed eval is refine-generation), gate on
    # held-out GENERATION quality (generating with vs without the learned state)
    # rather than topology selection -- selection J is vacuously tied on small
    # held-out sets while generation is the objective that actually deploys.
    selection_gate: dict[str, Any] = {
        "accepted": accepted,
        "j_before": float(result.gate_j_before)
        if result.gate_j_before is not None
        else 0.0,
        "j_after": float(result.gate_j_after)
        if result.gate_j_after is not None
        else 0.0,
        "epsilon": epsilon,
        "counts": dict(result.counts),
        "warnings": list(result.warnings),
    }
    if gate_mode == "off":
        gate_info: dict[str, Any] = (
            {"accepted": True, "j_before": None, "j_after": None,
             "epsilon": epsilon, "mode": "off"}
            if deploys_generation
            else {**selection_gate, "accepted": True, "mode": "off"}
        )
    elif deploys_generation:
        gate_planner_mode = next(
            (
                mode
                for mode in (cfg.evolved_mode, cfg.planner_mode)
                if mode
                in {"graph_generate", "program_generate", "python_generate"}
            ),
            "graph_generate",
        )
        gate_info = _generation_gate(
            val_instances, replace(cfg, planner_mode=gate_planner_mode),
            val_seeds=val_seeds, llm_client=client,
            evolved_bank=skill_bank, motif_stats=motif_stats, epsilon=epsilon,
            objective=objective, incumbent_bank=incumbent_bank, workers=workers,
        )
    else:
        gate_info = selection_gate

    # Every consumer of the summary (the frozen verify_evolve.py, curve, bench)
    # rebuilds its eval bank from ``evolved_skills`` unconditionally, so a
    # REJECTED state must be withheld HERE: export the pre-evolution state and
    # keep the rejected ids for diagnostics.
    gate_accepted = bool(gate_info.get("accepted"))
    candidate_skills = [skill.model_dump(mode="json") for skill in skill_bank]
    exported_skills = list(candidate_skills)
    exported_motif = motif_stats
    rejected_skill_ids: list[str] = []
    if not gate_accepted:
        rejected_skill_ids = sorted(skill.skill_id for skill in skill_bank)
        exported_skills = pre_skills
        exported_motif = {}
    innovation_topologies = {
        str(row.get("Topology"))
        for row in hot_start_dual_rows
        if row.get("hot_start_branch") == "innovation" and row.get("Topology")
    }
    pre_skill_ids = {str(skill.get("skill_id")) for skill in pre_skills}
    hot_start_innovation_candidates = sorted(
        str(skill.get("skill_id"))
        for skill in candidate_skills
        if str((skill.get("organization_policy") or {}).get("topology_name"))
        in innovation_topologies
    )
    hot_start_new_candidate_ids = sorted(
        skill_id
        for skill_id in hot_start_innovation_candidates
        if skill_id not in pre_skill_ids
    )
    deployed_ids = {str(skill.get("skill_id")) for skill in exported_skills}
    # 中文：gate 必须使用相同 information_goal 的 VAL 数据——混模式行违反隔离不变式。
    # The gate must judge on SAME-goal validation rows; mixed-mode rows violate
    # the isolation invariant.
    _run_goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    _mixed = {
        str(r.get("information_goal"))
        for r in [*train_rows, *val_rows]
        if r.get("information_goal")
    } - {_run_goal}
    if _mixed:
        raise ValueError(
            f"run_evolution collected rows for goals {sorted(_mixed)} while "
            f"running goal {_run_goal!r}; sink/all_agents evidence must not mix"
        )
    summary = {
        "benchmark": cfg.benchmark,
        "objective": cfg.objective,
        "information_goal": _run_goal,
        "clean_run": not bool(hot_start_settings["enabled"]),
        "config": asdict(cfg),
        "objective_knobs": {
            "uncertainty_weight": objective.uncertainty_weight,
            "min_seeds": objective.min_seeds,
            "enforce_avoid_veto": objective.enforce_avoid_veto,
            "risk_weight": objective.risk_weight,
            "max_acceptable_loss": objective.max_acceptable_loss,
        },
        "train_cases": [inst.case_id for inst in train_instances],
        "val_cases": [inst.case_id for inst in val_instances],
        "curriculum": curriculum,
        "n_train_rows": len(train_rows),
        "n_val_rows": len(val_rows),
        "n_val_rows_real": len(val_rows_real),
        "n_synthetic_held_out_rows": len(held_out_rows or []),
        "train_success_rate": _success_rate(train_rows),
        "val_success_rate": _success_rate(val_rows_real),
        "training_signal": _training_signal_summary(train_rows),
        "n_patches": len(patches),
        "skill_ablation": skill_ablation,
        "n_insight_patches": n_insight_patches,
        "n_explore_rows": n_explore_rows,
        "n_portfolio_rows": n_portfolio_rows,
        "hot_start": {
            "enabled": bool(hot_start_settings["enabled"]),
            "settings": hot_start_settings,
            "pretraining": hot_start_pretraining,
            "dual_branch": hot_start_dual,
            "innovation_candidate_skill_ids": hot_start_innovation_candidates,
            "new_candidate_skill_ids": hot_start_new_candidate_ids,
            "deployed_innovation_skill_ids": sorted(
                skill_id
                for skill_id in hot_start_innovation_candidates
                if skill_id in deployed_ids
            ),
            "total_extra_cost": _runtime_cost_summary(
                [*hot_start_rows, *hot_start_dual_rows]
            ),
        },
        "n_merged_duplicates": n_merged_duplicates,
        "n_recipe_runs": n_recipe_runs,
        "recipe_traces": recipe_traces,
        "n_exemplar_runs": n_exemplar_runs,
        "exemplar_traces": exemplar_traces,
        "gate": gate_info,
        "gate_mode": gate_mode,
        "selection_gate": selection_gate,
        "skill_bank_size_before": size_before,
        "skill_bank_size_after": size_after,
        "skill_bank_mutated": gate_accepted,
        "skill_ids_after": sorted(skill.skill_id for skill in skill_bank),
        "rejected_skill_ids": rejected_skill_ids,
        # Full audit snapshots. ``candidate`` preserves the proposed bank even
        # when the held-out gate rejects it; ``deployed`` is exactly what every
        # evaluator is allowed to rebuild and use. Keeping all three prevents a
        # rejected update from disappearing from the scientific record without
        # confusing it with the accepted policy.
        "skill_bank_snapshots": {
            "before": pre_skills,
            "candidate": candidate_skills,
            "deployed": exported_skills,
        },
        "skill_payload_audit": {
            "candidate": _skill_payload_audit(candidate_skills),
            "deployed": _skill_payload_audit(exported_skills),
        },
        # Serialized evolved skills so the eval can rebuild the bank across the
        # cache/parallel boundary and feed it to graph generation (evolved_mode=
        # graph_generate -> the emperor designs a DAG from these skills). On a
        # rejected gate this is the PRE state -- rejected updates never deploy.
        "evolved_skills": exported_skills,
        "evolved_motif_stats": exported_motif,
        "final_selection": final_selection,
    }
    diag.dump_evolution_summary(summary)
    return summary


def _selection_probe(
    bank: SkillBank,
    n_agents: int,
    objective: ObjectiveSpec,
) -> dict[str, Any]:
    """Run the knob-on planner on the evolved bank and report its selection.

    This is where the Plan-3 E/F selection knobs actually execute on real skills:
    ``score_skill`` runs the LCB accuracy penalty (E), ``retrieve`` runs the
    min-seeds gate (E), and ``TopologySelectPlanner.plan`` runs the
    veto/floor/risk logic (F). Returns the chosen topology, the score breakdown
    (which carries the LCB diagnostics), and the planner rationale (which records
    any counterexample veto).
    """
    request = PlannerRequest(
        task_family=next(
            (str(s.task_family) for s in bank if getattr(s, "task_family", None)),
            SILO_TASK_FAMILY,
        ),
        n_agents=n_agents,
        objective=objective,
    )
    plan = EmperorPlanner(bank).plan(request)
    return {
        "topology_name": plan.topology_name,
        "skill_id": plan.skill_id,
        "score": plan.score,
        "score_breakdown": plan.score_breakdown,
        "rationale": plan.rationale,
    }


# A baseline topology that exists only in the synthetic held-out rows and is
# distinct from the three topologies the minister produces (tree, mesh_star,
# one_peer_exponential_dag_star). Used as the seeded incumbent so the gate's
# accept/reject direction is decided by "incumbent vs. the three TRAIN topologies"
# and does not depend on which of the three the gate's planner happens to pick.
INCUMBENT_BASELINE_TOPOLOGY = "incumbent_baseline"

# The topologies the ResultAnalyst minister advertises from runs across the
# default objective variants (accuracy_first/budget_first/balanced) plus the
# M3 evidence portfolio (chain). Synthetic held-out rows must cover ALL of
# them so the gate's planner choice is decided by the incumbent-vs-train
# contrast, not by an unmeasured-topology penalty on a portfolio skill.
_TRAIN_TOPOLOGIES = ("one_peer_exponential_dag_star", "tree", "mesh_star", "chain")


def accepting_held_out_rows() -> list[dict[str, Any]]:
    """Synthetic held-out rows that make the gate ACCEPT the TRAIN patch batch.

    Pair with ``seed_incumbent_topology=INCUMBENT_BASELINE_TOPOLOGY``. The
    incumbent baseline is the worst held-out topology (loss 1) and every topology
    the minister learns from TRAIN is good (loss 0). Before the batch the gate's
    planner can only pick the incumbent (``J_before`` = 1); after it, it picks one
    of the TRAIN topologies (``J_after`` = 0), so ``J_after`` < ``J_before`` ->
    ACCEPT, regardless of which TRAIN topology the planner's tiebreak selects.
    """
    return [
        _held_out_row(topology=INCUMBENT_BASELINE_TOPOLOGY, loss=1.0),
        *[_held_out_row(topology=topo, loss=0.0) for topo in _TRAIN_TOPOLOGIES],
    ]


def rejecting_held_out_rows() -> list[dict[str, Any]]:
    """Synthetic held-out rows that make the gate REJECT the TRAIN patch batch.

    Pair with ``seed_incumbent_topology=INCUMBENT_BASELINE_TOPOLOGY``. The mirror
    of :func:`accepting_held_out_rows`: the incumbent baseline is the *best*
    held-out topology (loss 0) and every TRAIN topology is bad (loss 1). Before the
    batch the planner picks the incumbent (``J_before`` = 0); adopting the batch
    would switch it to a worse TRAIN topology (``J_after`` = 1), so ``J_after`` >
    ``J_before`` -> REJECT and the held-out bank is left untouched.
    """
    return [
        _held_out_row(topology=INCUMBENT_BASELINE_TOPOLOGY, loss=0.0),
        *[_held_out_row(topology=topo, loss=1.0) for topo in _TRAIN_TOPOLOGIES],
    ]


def _held_out_row(
    *,
    topology: str,
    loss: float,
    agents: int = 2,
) -> dict[str, Any]:
    """One synthetic held-out aggregate row in the minister/gate row shape.

    ``MeanPrimaryMetric`` is a higher-is-better success rate (``1 - loss``) tagged
    ``PrimaryMetricName="primary"``, exactly the shape ``summary_to_aggregate_row``
    emits for Silo, so the gate's ``validation_objective`` converts it to ``loss``
    via the shared ``primary_loss`` rule.
    """
    success = 1.0 - loss
    return {
        "Topology": topology,
        "Agents": agents,
        "ArraySize": 0,
        "MergeMode": "deterministic",
        "InitMode": "deterministic",
        "Runs": 1,
        "MeanFinalRMSE": loss,
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": 0.0,
        "ExactMatchRate": success,
        "MeanPrimaryMetric": success,
        "PrimaryMetricName": "primary",
        "MeanTotalSteps": 4,
        "MeanTotalMessages": 10.0,
        "MeanTotalModelCalls": 0,
        "MeanTokenCost": 1000.0,
        "MeanVoteTopRatio": 1.0,
        "task_family": SILO_TASK_FAMILY,
    }
