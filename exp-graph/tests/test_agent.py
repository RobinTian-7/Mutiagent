from exp_graph.agents import AgentConfig, BeliefState, SolverAgent
from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks import ArraySearchTaskAdapter


def test_build_outbox_is_derived_from_belief_state() -> None:
    belief = BeliefState(
        status="candidate",
        proposal="Target appears to be at index 4.",
        consensus_key="FOUND:4",
        support=["a", "b", "c", "d"],
        uncertainty="low",
        open_questions=["confirm shard 4", "anything else?"],
        private_notes="do not send",
    )

    outbox = OutboxMessage.from_belief_state(
        agent_id=2,
        round_idx=5,
        belief_state=belief,
    )

    assert outbox.agent_id == 2
    assert outbox.round_idx == 5
    assert outbox.status == "candidate"
    assert outbox.consensus_key == "FOUND:4"
    assert outbox.support == ["a", "b", "c"]
    assert outbox.request == "confirm shard 4"
    assert "private_notes" not in outbox.model_dump()


def test_agent_retries_invalid_json_and_accumulates_usage() -> None:
    class FlakyLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self,
            prompt: str,
            model_name: str,
            temperature: float | None = None,
        ) -> LLMResponse:
            self.calls += 1
            self.temperature = temperature
            if self.calls == 1:
                return LLMResponse(
                    text="not json",
                    usage=LLMUsage(prompt_tokens=3, completion_tokens=2),
                )
            return LLMResponse(
                text=(
                    '{"status":"final","proposal":"Found at global index 4",'
                    '"consensus_key":"FOUND:4","support":["retry fixed json"],'
                    '"uncertainty":"","open_questions":[],"private_notes":""}'
                ),
                usage=LLMUsage(prompt_tokens=7, completion_tokens=5),
            )

    agent = SolverAgent(
        config=AgentConfig(
            agent_id=0,
            model_name="test-model",
            json_retry_attempts=1,
            temperature=0.3,
        ),
        task_adapter=ArraySearchTaskAdapter(),
        llm_client=FlakyLLMClient(),
    )

    belief, response = agent.update_belief_state(prompt="task prompt")

    assert belief.consensus_key == "FOUND:4"
    assert response.usage.model_calls == 2
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 7
    assert response.raw_prompts[0] == "task prompt"
    assert "Invalid previous response" in response.raw_prompts[1]
    assert response.raw_responses == [
        "not json",
        (
            '{"status":"final","proposal":"Found at global index 4",'
            '"consensus_key":"FOUND:4","support":["retry fixed json"],'
            '"uncertainty":"","open_questions":[],"private_notes":""}'
        ),
    ]


def test_agent_passes_temperature_to_llm_client() -> None:
    class CapturingLLMClient:
        def __init__(self) -> None:
            self.temperature = None

        def complete(
            self,
            prompt: str,
            model_name: str,
            temperature: float | None = None,
        ) -> LLMResponse:
            self.temperature = temperature
            return LLMResponse(
                text=(
                    '{"status":"unknown","proposal":"Need more information",'
                    '"consensus_key":"UNKNOWN","support":[],"uncertainty":"",'
                    '"open_questions":[],"private_notes":""}'
                )
            )

    llm_client = CapturingLLMClient()
    agent = SolverAgent(
        config=AgentConfig(
            agent_id=0,
            model_name="test-model",
            temperature=0.7,
        ),
        task_adapter=ArraySearchTaskAdapter(),
        llm_client=llm_client,
    )

    agent.update_belief_state(prompt="task prompt")

    assert llm_client.temperature == 0.7
