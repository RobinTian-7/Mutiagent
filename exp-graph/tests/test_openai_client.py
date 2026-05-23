import sys
from types import ModuleType, SimpleNamespace

from exp_graph.llm.openai_client import OpenAIChatClient


def _request_for_model(monkeypatch, model_name: str) -> dict[str, object]:
    request: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            request.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))
                ],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
            )

    class FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    openai_module = ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", openai_module)

    client = OpenAIChatClient()
    client.complete("return json", model_name=model_name)
    return request


def test_json_completion_disables_thinking_mode_for_qwen3_mixed_models(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "qwen3.5-27b")

    assert request["extra_body"] == {"enable_thinking": False}


def test_json_completion_disables_thinking_mode_for_qwen36_model(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "qwen3.6-27b")

    assert request["extra_body"] == {"enable_thinking": False}


def test_json_completion_does_not_send_thinking_option_to_non_thinking_model(
    monkeypatch,
) -> None:
    request = _request_for_model(monkeypatch, "qwen2.5-72b-instruct")

    assert "extra_body" not in request
