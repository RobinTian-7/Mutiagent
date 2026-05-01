from typing import Any

from exp_graph.agents import BeliefState
from exp_graph.llm.prompts import build_solver_prompt
from exp_graph.tasks.base import TaskAdapter


class PromptOnlyTaskAdapter(TaskAdapter):
    task_name = "prompt_only"

    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        return {"task_name": self.task_name}

    def split_into_local_observations(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> list[dict[str, Any]]:
        return [{"agent_id": idx} for idx in range(n_agents)]

    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "unknown",
            "proposal": "No task-specific answer yet.",
            "consensus_key": "UNKNOWN",
            "support": [],
            "uncertainty": "",
            "open_questions": [],
            "private_notes": "",
        }

    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        return "UNKNOWN" if key_or_proposal is None else str(key_or_proposal)

    def evaluate_final_answer(
        self,
        global_task: dict[str, Any],
        final_key: str | None,
    ) -> bool:
        return False

    def format_task_prompt_context(
        self,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        return "Task-specific prompt context without array-search keys."

    def format_consensus_key_instructions(self) -> str:
        return "Use CF:<canonical_count_map_hash>, PARTIAL, or UNKNOWN."


def test_solver_prompt_uses_task_adapter_consensus_key_instructions() -> None:
    prompt = build_solver_prompt(
        task_adapter=PromptOnlyTaskAdapter(),
        global_task={"task_name": "prompt_only"},
        local_observation={"agent_id": 0},
        old_belief_state=BeliefState(
            status="unknown",
            proposal="",
            consensus_key="UNKNOWN",
            support=[],
            uncertainty="",
            open_questions=[],
            private_notes="",
        ),
        inbox=[],
    )

    assert "Use CF:<canonical_count_map_hash>, PARTIAL, or UNKNOWN." in prompt
    assert "FOUND:<global_index>" not in prompt
