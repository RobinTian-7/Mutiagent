"""Outer MAS protocol runner that wraps the existing ProtocolRunner."""

# ============================================================
# 【模块导读】外层 MAS 协议运行器：封装既有的 ProtocolRunner。
# - 流程：PlannerRequest -> 皇帝(规划 LLM)产出 MASPlan -> ProtocolRunner 执行；
# - evolve=True 时由大臣分析运行摘要，生成进化批次并整合进技能库。
# ============================================================
from __future__ import annotations

from pydantic import BaseModel

from exp_graph.mas.evolution import ResultAnalystMinister, consolidate_batch
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.schemas import EvolutionBatch, MASPlan, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner import ProtocolExperimentResult, ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks import CountFrequencyTaskAdapter


# 【职责】一次由规划器选定协议的执行结果(请求/计划/协议结果/可选进化批次)。
class MASRunResult(BaseModel):
    """Result of a planner-selected protocol execution."""

    request: PlannerRequest
    plan: MASPlan
    protocol_result: ProtocolExperimentResult
    evolution_batch: EvolutionBatch | None = None


# 【职责】外层运行器：PlannerRequest -> MASPlan -> ProtocolRunner -> 可选进化批次。
class MASProtocolRunner:
    """PlannerRequest -> MASPlan -> ProtocolRunner -> optional evolution batch."""

    def __init__(
        self,
        *,
        skill_bank: SkillBank,
        task_adapter: CountFrequencyTaskAdapter | None = None,
    ) -> None:
        self.skill_bank = skill_bank
        self.task_adapter = task_adapter or CountFrequencyTaskAdapter()
        self.planner = EmperorPlanner(skill_bank)

    # 【职责】规划->组装配置->执行协议；evolve=True 时大臣分析摘要并把补丁整合进技能库。
    def run(
        self,
        *,
        request: PlannerRequest,
        global_task: dict,
        seed: int = 0,
        evolve: bool = False,
    ) -> MASRunResult:
        plan = self.planner.plan(request)
        config_data = {
            "topology_name": plan.topology_name,
            "n_agents": request.n_agents,
            "seed": seed,
            "merge_mode": request.merge_mode,
            "init_mode": request.init_mode,
            "protocol_spec": plan.protocol_spec,
        }
        config_data.update(plan.config_overrides)
        config = ProtocolRunnerConfig(**config_data)
        protocol_result = ProtocolRunner(
            config=config,
            task_adapter=self.task_adapter,
            global_task=global_task,
        ).run()
        evolution_batch = None
        if evolve:
            summary = protocol_result.to_summary_dict()
            evolution_batch = EvolutionBatch(
                batch_id=f"mas_run_{protocol_result.run_id}",
                patches=ResultAnalystMinister().analyze([summary_to_aggregate_row(summary)]),
                summary="Post-run minister analysis from one MAS execution.",
            )
            consolidate_batch(evolution_batch, self.skill_bank)
        return MASRunResult(
            request=request,
            plan=plan,
            protocol_result=protocol_result,
            evolution_batch=evolution_batch,
        )


# 【职责】把单次运行摘要适配成大臣消费的聚合行(aggregate row)格式——进化的输入。
# - 兼容 count_frequency 摘要(带 FinalRMSE)与通用协议摘要
#   (带 PrimaryMetric/PrimaryMetricName)；单次运行故 Runs=1、StdFinalRMSE=0。
def summary_to_aggregate_row(summary: dict) -> dict:
    """Adapt a single run summary to the aggregate-row shape used by ministers.

    Robust to both count-frequency summaries (which carry ``FinalRMSE``) and
    generic protocol summaries (which carry ``PrimaryMetric``/``PrimaryMetricName``).
    """
    primary = float(summary.get("PrimaryMetric", summary.get("FinalRMSE", 0.0)))
    return {
        "Topology": summary["Topology"],
        "Agents": summary["Agents"],
        "ArraySize": summary.get("ArraySize", 0),
        "MergeMode": summary["MergeMode"],
        "InitMode": summary["InitMode"],
        "Runs": 1,
        "MeanFinalRMSE": float(summary.get("FinalRMSE", primary)),
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": float(summary.get("FinalNormalizedL1Error", 0.0)),
        "ExactMatchRate": 1.0 if summary.get("FinalExactMatch") else 0.0,
        "MeanPrimaryMetric": primary,
        "PrimaryMetricName": summary.get("PrimaryMetricName", "rmse"),
        "MeanTotalSteps": summary["TotalSteps"],
        "MeanTotalMessages": summary["TotalMessages"],
        "MeanTotalModelCalls": summary["TotalModelCalls"],
        "MeanTokenCost": summary["TotalPromptTokens"] + summary["TotalCompletionTokens"],
        "MeanVoteTopRatio": summary.get("VoteTopRatio") or 0.0,
    }
