"""OpenAI-backed LLM client."""

from __future__ import annotations

import os

from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens


_DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "xiaomi": "https://api.xiaomimimo.com/v1",
}

_DEFAULT_API_KEY_ENVS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "bailian": "DASHSCOPE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "alibaba": "DASHSCOPE_API_KEY",
    "xiaomi": "XIAOMI_API_KEY",
}


def _non_thinking_request_options(model_name: str) -> dict[str, object]:
    """Disable optional reasoning for supported OpenAI-compatible model families."""
    model = model_name.lower()
    thinking_only = (
        model.startswith(("deepseek-r1", "kimi-k2-thinking"))
        or (model.startswith("qwen") and "thinking" in model)
    )
    if thinking_only:
        raise ValueError(
            f"Model {model_name!r} is thinking-only and cannot be used in "
            "non-thinking experiments."
        )
    if model.startswith("qwen3") or model.startswith(
        ("deepseek-v3.1", "deepseek-v3.2", "deepseek-v4-")
    ):
        return {"extra_body": {"enable_thinking": False}}
    if model.startswith("mimo-v2") and "-tts" not in model:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    if model == "kimi-k2.5":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def _non_thinking_temperature(model_name: str, temperature: float | None) -> float:
    """Return a temperature compatible with the selected non-thinking mode."""
    if model_name.lower() == "kimi-k2.5":
        return 0.6
    return 0.0 if temperature is None else temperature


def _explicit_thinking_request_options(
    *,
    model_name: str,
    platform: str,
    thinking_enabled: bool,
) -> dict[str, object]:
    """Map role-level thinking policy to provider-specific request fields."""
    model = model_name.lower()
    provider = platform.lower()
    if provider == "deepseek" or model.startswith("deepseek-v4"):
        thinking_type = "enabled" if thinking_enabled else "disabled"
        return {"extra_body": {"thinking": {"type": thinking_type}}}
    if provider in {"bailian", "dashscope", "qwen", "alibaba"} or model.startswith(
        "qwen"
    ):
        return {"extra_body": {"enable_thinking": thinking_enabled}}
    if provider == "xiaomi" or model.startswith("mimo-v2"):
        thinking_type = "enabled" if thinking_enabled else "disabled"
        return {"extra_body": {"thinking": {"type": thinking_type}}}
    return {}


class OpenAIChatClient:
    """Small OpenAI chat-completions wrapper.

    The dependency is optional so tests can run without network access or API
    keys. Use this client for real LLM-backed experiments.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
        platform: str = "openai",
        thinking_enabled: bool | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Install exp-graph[openai] to use OpenAIChatClient"
            ) from exc
        timeout_total = float(os.environ.get("OPENAI_TIMEOUT", "120"))
        # Fail fast on a dead/wedged connection: a short CONNECT timeout means a
        # proxy that accepts the TCP socket but never responds is abandoned
        # quickly instead of tying up the (longer) read budget. The hard
        # wall-clock TimeoutLLMClient guard still bounds the whole call regardless;
        # this just shortens the common dead-connection case.
        connect_timeout = float(
            os.environ.get("OPENAI_CONNECT_TIMEOUT", str(min(10.0, timeout_total)))
        )
        try:
            import httpx

            timeout: object = httpx.Timeout(timeout_total, connect=connect_timeout)
        except Exception:  # pragma: no cover - httpx ships with the openai SDK
            timeout = timeout_total
        max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))
        self._platform = platform.lower()
        self._thinking_enabled = thinking_enabled
        client_kwargs: dict[str, object] = {
            "timeout": timeout,
            "max_retries": max_retries,
        }
        resolved_base_url = base_url or _DEFAULT_BASE_URLS.get(self._platform)
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url
        resolved_api_key_env = api_key_env or _DEFAULT_API_KEY_ENVS.get(self._platform)
        if resolved_api_key_env:
            api_key = os.environ.get(resolved_api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"{resolved_api_key_env} is required for {platform} client"
                )
            client_kwargs["api_key"] = api_key
        self._client = OpenAI(**client_kwargs)

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        if self._thinking_enabled is None:
            request_options = _non_thinking_request_options(model_name)
            request_temperature = _non_thinking_temperature(model_name, temperature)
        else:
            request_options = _explicit_thinking_request_options(
                model_name=model_name,
                platform=self._platform,
                thinking_enabled=self._thinking_enabled,
            )
            request_temperature = 0.0 if temperature is None else temperature

        response = self._client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=request_temperature,
            response_format={"type": "json_object"},
            **request_options,
        )
        text = response.choices[0].message.content or "{}"
        usage = response.usage
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", estimate_tokens(prompt)),
                completion_tokens=getattr(
                    usage,
                    "completion_tokens",
                    estimate_tokens(text),
                ),
            ),
        )
