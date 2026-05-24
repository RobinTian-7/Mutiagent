import sys
from types import ModuleType, SimpleNamespace

import pytest

from exp_graph.llm.openai_client import OpenAIChatClient


def _request_for_model(
    monkeypatch,
    model_name: str,
    **client_kwargs,
) -> dict[str, object]:
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
        def __init__(self, **kwargs) -> None:
            request["__init__"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    openai_module = ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", openai_module)

    client = OpenAIChatClient(**client_kwargs)
    client.complete("return json", model_name=model_name)
    return request


def test_json_completion_disables_thinking_mode_for_qwen3_mixed_models(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "qwen3.5-27b")

    assert request["extra_body"] == {"enable_thinking": False}


def test_json_completion_disables_thinking_mode_for_qwen36_model(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "qwen3.6-27b")

    assert request["extra_body"] == {"enable_thinking": False}


def test_json_completion_disables_thinking_mode_for_deepseek_v4_model(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "deepseek-v4-flash")

    assert request["extra_body"] == {"enable_thinking": False}


def test_role_completion_enables_thinking_mode_for_deepseek_model(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    request = _request_for_model(
        monkeypatch,
        "deepseek-v4-flash",
        platform="deepseek",
        thinking_enabled=True,
    )

    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["__init__"]["base_url"] == "https://api.deepseek.com"
    assert request["__init__"]["api_key"] == "test-key"


def test_role_completion_disables_thinking_mode_for_deepseek_model(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    request = _request_for_model(
        monkeypatch,
        "deepseek-v4-flash",
        platform="deepseek",
        thinking_enabled=False,
    )

    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_role_completion_disables_thinking_mode_for_bailian_qwen_model(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    request = _request_for_model(
        monkeypatch,
        "qwen3.5-flash",
        platform="bailian",
        thinking_enabled=False,
    )

    assert request["extra_body"] == {"enable_thinking": False}
    assert request["__init__"]["api_key"] == "test-key"


def test_json_completion_disables_thinking_mode_for_mimo_model(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "mimo-v2-flash")

    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_json_completion_disables_thinking_mode_for_kimi_k25_model(monkeypatch) -> None:
    request = _request_for_model(monkeypatch, "kimi-k2.5")

    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert request["temperature"] == 0.6


def test_json_completion_does_not_send_thinking_option_to_non_thinking_model(
    monkeypatch,
) -> None:
    request = _request_for_model(monkeypatch, "deepseek-v3")

    assert "extra_body" not in request


@pytest.mark.parametrize("model_name", ["deepseek-r1", "kimi-k2-thinking"])
def test_json_completion_rejects_thinking_only_model(monkeypatch, model_name: str) -> None:
    with pytest.raises(ValueError, match="thinking-only"):
        _request_for_model(monkeypatch, model_name)
