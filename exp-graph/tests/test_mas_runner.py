from pathlib import Path

from exp_graph.mas import MASProtocolRunner, PlannerRequest, SkillBank
from exp_graph.tasks import CountFrequencyTaskAdapter


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def _global_task() -> tuple[CountFrequencyTaskAdapter, dict]:
    adapter = CountFrequencyTaskAdapter()
    return adapter, adapter.build_global_task(array=[1, 2, 1, 3, 2, 3, 3, 1])


def test_mas_runner_executes_topology_select_path() -> None:
    adapter, global_task = _global_task()
    runner = MASProtocolRunner(
        skill_bank=SkillBank.load_dir(SKILL_DIR),
        task_adapter=adapter,
    )
    request = PlannerRequest.from_names(
        n_agents=4,
        objective="budget_first",
        planner_mode="topology_select",
    )

    result = runner.run(request=request, global_task=global_task)

    assert result.plan.skill_id == "cf_budget_tree"
    assert result.protocol_result.config.protocol_spec is None
    assert result.protocol_result.final_result.exact_match is True


def test_mas_runner_executes_operator_compose_protocol_spec_path() -> None:
    adapter, global_task = _global_task()
    runner = MASProtocolRunner(
        skill_bank=SkillBank.load_dir(SKILL_DIR),
        task_adapter=adapter,
    )
    request = PlannerRequest.from_names(
        n_agents=4,
        objective="accuracy_first",
        planner_mode="operator_compose",
    )

    result = runner.run(request=request, global_task=global_task)

    assert result.plan.protocol_spec is not None
    assert result.protocol_result.config.protocol_spec is not None
    assert result.protocol_result.total_steps == 3
    assert result.protocol_result.total_messages == 11
    assert result.protocol_result.final_result.exact_match is True
