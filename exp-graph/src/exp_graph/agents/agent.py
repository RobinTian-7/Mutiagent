"""LLM-backed solver agent."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from exp_graph.agents.schemas import AgentConfig, AgentState, BeliefState
from exp_graph.llm.base import LLMClient, LLMResponse, combine_usage
from exp_graph.llm.parser import parse_belief_state
from exp_graph.llm.prompts import build_solver_prompt
from exp_graph.llm.retry import build_json_retry_prompt
from exp_graph.messaging.messages import OutboxMessage
from exp_graph.tasks.base import TaskAdapter
from exp_graph.tracing import AgentStepTrace


class SolverAgent:
    """One synchronous solver agent."""

    def __init__(
        self,
        config: AgentConfig,
        task_adapter: TaskAdapter,
        llm_client: LLMClient,
    ) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.llm_client = llm_client

    def build_prompt(
        self,
        *,
        global_task: dict[str, Any],
        state: AgentState,
    ) -> str:
        return build_solver_prompt(
            task_adapter=self.task_adapter,
            global_task=global_task,
            local_observation=state.local_observation,
            old_belief_state=state.belief_state,
            inbox=state.inbox,
        )

    def update_belief_state(
        self,
        *,
        prompt: str,
    ) -> tuple[BeliefState, LLMResponse]:
        responses: list[LLMResponse] = []
        call_prompts: list[str] = []
        current_prompt = prompt
        last_error: Exception | None = None
        belief_state: BeliefState | None = None

        for attempt_idx in range(self.config.json_retry_attempts + 1):
            call_prompts.append(current_prompt)
            response = self.llm_client.complete(
                current_prompt,
                model_name=self.config.model_name,
                temperature=self.config.temperature,
            )
            responses.append(response)
            try:
                belief_state = parse_belief_state(response.text)
                break
            except (ValueError, TypeError, ValidationError) as exc:
                last_error = exc
                if attempt_idx >= self.config.json_retry_attempts:
                    raise ValueError(
                        "LLM failed to return a valid belief_state JSON object "
                        f"after {attempt_idx + 1} call(s). Last error: {exc}"
                    ) from exc
                current_prompt = build_json_retry_prompt(
                    original_prompt=prompt,
                    invalid_response=response.text,
                    error_message=str(exc),
                    attempt_idx=attempt_idx + 1,
                )

        if belief_state is None:
            raise ValueError(f"LLM JSON retry failed: {last_error}")

        normalized_key = self.task_adapter.normalize_consensus_key(
            belief_state.consensus_key or belief_state.proposal
        )
        belief_state.consensus_key = normalized_key
        return belief_state, LLMResponse(
            text=responses[-1].text,
            usage=combine_usage([item.usage for item in responses]),
            raw_responses=[item.text for item in responses],
            raw_prompts=call_prompts,
        )

    def build_outbox(
        self,
        *,
        belief_state: BeliefState,
        round_idx: int,
    ) -> OutboxMessage:
        return OutboxMessage.from_belief_state(
            agent_id=self.config.agent_id,
            round_idx=round_idx,
            belief_state=belief_state,
        )

    def step(
        self,
        *,
        global_task: dict[str, Any],
        state: AgentState,
        round_idx: int,
    ) -> tuple[BeliefState, OutboxMessage, LLMResponse]:
        """Run one update without mutating shared global state."""
        prompt = self.build_prompt(global_task=global_task, state=state)
        belief_state, response = self.update_belief_state(prompt=prompt)
        outbox = self.build_outbox(belief_state=belief_state, round_idx=round_idx)
        return belief_state, outbox, response

    def step_with_trace(
        self,
        *,
        global_task: dict[str, Any],
        state: AgentState,
        round_idx: int,
        run_id: str,
        topology_name: str,
        neighbors: list[int],
        include_prompt: bool,
    ) -> tuple[BeliefState, OutboxMessage, LLMResponse, AgentStepTrace]:
        """Run one update and return an auditable prompt/response trace."""
        prompt = self.build_prompt(global_task=global_task, state=state)
        belief_state, response = self.update_belief_state(prompt=prompt)
        outbox = self.build_outbox(belief_state=belief_state, round_idx=round_idx)
        raw_responses = response.raw_responses or [response.text]
        raw_prompts = response.raw_prompts or [prompt]
        trace_prompts = raw_prompts if include_prompt else [""] * len(raw_prompts)
        trace = AgentStepTrace(
            run_id=run_id,
            round_idx=round_idx,
            communication_round=round_idx + 1,
            agent_id=self.config.agent_id,
            topology_name=topology_name,
            neighbors=neighbors,
            inbox=[message.model_dump() for message in state.inbox],
            prompt=prompt if include_prompt else "",
            raw_response=response.text,
            raw_responses=raw_responses,
            raw_prompts=trace_prompts,
            llm_calls=[
                {
                    "call_idx": idx,
                    "prompt": trace_prompts[idx] if idx < len(trace_prompts) else "",
                    "raw_response": raw_responses[idx] if idx < len(raw_responses) else "",
                }
                for idx in range(max(len(trace_prompts), len(raw_responses)))
            ],
            parsed_belief_state=belief_state.model_dump(mode="json"),
            outbox=outbox.model_dump(),
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model_calls=response.usage.model_calls,
            retry_attempts=max(0, response.usage.model_calls - 1),
        )
        return belief_state, outbox, response, trace
