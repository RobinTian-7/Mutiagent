"""Outer MAS protocol runner that wraps the existing ProtocolRunner."""

from __future__ import annotations

from pydantic import BaseModel

from exp_graph.mas.evolution import ResultAnalystMinister, consolidate_batch
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.schemas import EvolutionBatch, MASPlan, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner import ProtocolExperimentResult, ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks import CountFrequencyTaskAdapter


class MASRunResult(BaseModel):
    """Result of a planner-selected protocol execution."""

    request: PlannerRequest
    plan: MASPlan
    protocol_result: ProtocolExperimentResult
    evolution_batch: EvolutionBatch | None = None


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


def summary_to_aggregate_row(summary: dict) -> dict:
    """Adapt a single run summary to the aggregate-row shape used by ministers."""
    return {
        "Topology": summary["Topology"],
        "Agents": summary["Agents"],
        "ArraySize": summary["ArraySize"],
        "MergeMode": summary["MergeMode"],
        "InitMode": summary["InitMode"],
        "Runs": 1,
        "MeanFinalRMSE": summary["FinalRMSE"],
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": summary["FinalNormalizedL1Error"],
        "ExactMatchRate": 1.0 if summary["FinalExactMatch"] else 0.0,
        "MeanTotalSteps": summary["TotalSteps"],
        "MeanTotalMessages": summary["TotalMessages"],
        "MeanTotalModelCalls": summary["TotalModelCalls"],
        "MeanTokenCost": summary["TotalPromptTokens"] + summary["TotalCompletionTokens"],
        "MeanVoteTopRatio": summary["VoteTopRatio"],
    }
