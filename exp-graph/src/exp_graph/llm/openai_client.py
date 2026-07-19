"""OpenAI-backed LLM client."""
# ============================================================
# 【模块导读】基于 OpenAI SDK 的 LLM 客户端(兼容各 OpenAI 风格供应商)。
# _DEFAULT_BASE_URLS / _DEFAULT_API_KEY_ENVS：各 provider(供应商)预设的
# base_url(接口地址)与 api_key_env(存 key 的环境变量名)，构造入参可覆盖。
# 另含思考(thinking)开关到各供应商请求字段的映射，以及 usage(用量/token 计数)统计。
# ============================================================

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


# 【职责】为受支持的 OpenAI 兼容模型族生成“关闭可选思考(reasoning)”的请求字段。
# - thinking-only 模型(deepseek-r1*、kimi-k2-thinking*、qwen*thinking*)无法关闭，抛 ValueError。
# - qwen3*、deepseek-v3.1/v3.2/v4-* 返回 enable_thinking=False。
# - mimo-v2*(排除 -tts)与 kimi-k2.5 返回 thinking.type=disabled；其余模型返回空 dict。
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


# 【职责】返回与所选非思考模式兼容的温度。
# - kimi-k2.5 固定 0.6；其余模型未显式给温度时用 0.0，否则用显式温度。
def _non_thinking_temperature(model_name: str, temperature: float | None) -> float:
    """Return a temperature compatible with the selected non-thinking mode."""
    if model_name.lower() == "kimi-k2.5":
        return 0.6
    return 0.0 if temperature is None else temperature


# 【职责】把角色级思考(thinking)策略映射为各供应商专有的请求字段。
# - deepseek 或 deepseek-v4* 模型：thinking.type=enabled/disabled。
# - bailian/dashscope/qwen/alibaba 或 qwen* 模型：enable_thinking=True/False。
# - xiaomi 或 mimo-v2* 模型：thinking.type=enabled/disabled；其余返回空 dict。
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


# 【职责】OpenAI chat-completions 接口的轻量封装；真实 LLM 实验用这个客户端。
# - openai 依赖为可选安装，测试可以在无网络、无 API key 的环境下运行。
class OpenAIChatClient:
    """Small OpenAI chat-completions wrapper.

    The dependency is optional so tests can run without network access or API
    keys. Use this client for real LLM-backed experiments.
    """

    # 【职责】构建底层 OpenAI 客户端：解析 base_url(接口地址)与 api_key_env(存 key 的环境变量名)。
    # - 未安装 openai 包时抛 RuntimeError(提示安装 exp-graph[openai])。
    # - 入参优先，缺省回落到该 provider(供应商)的预设；openai 平台无预设，走 SDK 默认行为。
    # - 解析出的 api_key_env 环境变量缺失时抛 RuntimeError(快速失败)。
    # - 超时读 OPENAI_TIMEOUT / OPENAI_CONNECT_TIMEOUT，重试次数读 OPENAI_MAX_RETRIES。
    # - 默认换用不持久化 cookie 的 httpx 客户端(OPENAI_KEEP_COOKIES=1 恢复默认)。
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
        platform: str = "openai",
        thinking_enabled: bool | None = None,
        max_retries: int | None = None,
        max_completion_tokens: int | None = None,
        require_provider_usage: bool = False,
        reasoning_effort: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Install exp-graph[openai] to use OpenAIChatClient"
            ) from exc
        timeout_total = float(os.environ.get("OPENAI_TIMEOUT", "120"))
        # 中文：对死掉/卡住的连接快速失败——较短的 CONNECT 超时让“接受 TCP 连接
        #   却从不响应”的代理被尽快放弃，而不是耗满(更长的)读超时预算。硬性墙钟守卫
        #   TimeoutLLMClient 无论如何仍兜底整个调用；这里只是缩短常见的死连接场景。
        # Fail fast on a dead/wedged connection: a short CONNECT timeout means a
        # proxy that accepts the TCP socket but never responds is abandoned
        # quickly instead of tying up the (longer) read budget. The hard
        # wall-clock TimeoutLLMClient guard still bounds the whole call regardless;
        # this just shortens the common dead-connection case.
        connect_timeout = float(
            os.environ.get("OPENAI_CONNECT_TIMEOUT", str(min(10.0, timeout_total)))
        )
        http_client: object | None = None
        try:
            import httpx

            timeout: object = httpx.Timeout(timeout_total, connect=connect_timeout)

            # 【职责】cookie 罐永不持久化任何内容的 httpx 客户端。
            # - httpx 会把 cookies= 参数重新包装成普通 cookie 罐，子类化 Cookies 无法绕开，
            # - 钉死 cookies 属性才是可靠的切入点。
            # - API 本不需要 cookie；但会下发会话 cookie 的代理/负载均衡会让默认 cookie 罐
            # - 在单进程长跑的数千次调用中持续膨胀，直到仅 Cookie 头就触发请求上限
            # - (phase-3 dev-10：与实验臂无关的“431 请求头过大”失败毒害了所有 judge 臂)。
            # - 设 OPENAI_KEEP_COOKIES=1 可恢复默认客户端。
            class _NoCookieHTTPClient(httpx.Client):
                """An httpx client whose cookie jar never persists anything.

                httpx re-wraps any ``cookies=`` argument into a plain jar, so
                a Cookies subclass cannot opt out; pinning the property is
                the reliable seam. The API needs no cookies, but a proxy/
                load-balancer that sets session cookies makes the default jar
                GROW across the thousands of calls a long run makes in one
                process, until the Cookie header alone trips request limits
                (phase-3 dev-10: arm-agnostic '431 Request headers are too
                large' failures poisoned every judge arm).
                OPENAI_KEEP_COOKIES=1 restores the default client.
                """

                @property
                def cookies(self):  # noqa: D102
                    return httpx.Cookies()

                @cookies.setter
                def cookies(self, value):  # noqa: D102
                    return None

            if os.environ.get("OPENAI_KEEP_COOKIES", "").strip() not in {"1", "true"}:
                http_client = _NoCookieHTTPClient(timeout=timeout)
        # 中文：httpx 随 openai SDK 一并安装，此分支实际不会走到；兜底为仅用总超时数值。
        except Exception:  # pragma: no cover - httpx ships with the openai SDK
            timeout = timeout_total
        resolved_max_retries = (
            int(os.environ.get("OPENAI_MAX_RETRIES", "2"))
            if max_retries is None
            else max_retries
        )
        if (
            isinstance(resolved_max_retries, bool)
            or not isinstance(resolved_max_retries, int)
            or resolved_max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if max_completion_tokens is not None and (
            isinstance(max_completion_tokens, bool)
            or not isinstance(max_completion_tokens, int)
            or max_completion_tokens < 1
        ):
            raise ValueError("max_completion_tokens must be a positive integer")
        if not isinstance(require_provider_usage, bool):
            raise TypeError("require_provider_usage must be boolean")
        self._platform = platform.lower()
        self._thinking_enabled = thinking_enabled
        # OpenAI reasoning models take reasoning_effort and reject sampling
        # temperature; when an effort is pinned the request omits temperature.
        self._reasoning_effort = reasoning_effort
        self._max_completion_tokens = max_completion_tokens
        self._require_provider_usage = require_provider_usage
        client_kwargs: dict[str, object] = {
            "timeout": timeout,
            "max_retries": resolved_max_retries,
        }
        if http_client is not None:
            client_kwargs["http_client"] = http_client
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

    # 【职责】发起一次 chat.completions 调用并回填用量(token 计数)。
    # - thinking_enabled 未配置(None)时走“非思考”默认映射；否则按显式思考策略映射请求字段。
    # - 以 response_format=json_object 约束仅输出 JSON；空内容兜底为 "{}"。
    # - 供应商未返回 usage 字段时以 estimate_tokens 估算兜底。
    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        json_mode: bool = True,
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

        # 中文：json_mode(默认)以 response_format=json_object 约束仅输出 JSON；
        #   PythonGen 架构师/修复调用需返回原始 Python 源码，故 json_mode=False
        #   时不加该约束，走自由文本输出。
        # json_mode (default) constrains output to a single JSON object; the
        # PythonGen architect/repair calls pass json_mode=False so the provider
        # can return raw Python source instead of being forced into JSON.
        if json_mode:
            request_options = {
                **request_options,
                "response_format": {"type": "json_object"},
            }
        if self._max_completion_tokens is not None:
            request_options = {
                **request_options,
                "max_completion_tokens": self._max_completion_tokens,
            }
        if self._reasoning_effort is not None:
            request_options = {
                **request_options,
                "reasoning_effort": self._reasoning_effort,
            }
            response = self._client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                **request_options,
            )
        else:
            response = self._client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=request_temperature,
                **request_options,
            )
        text = response.choices[0].message.content or ("{}" if json_mode else "")
        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        prompt_usage_known = bool(
            isinstance(prompt_tokens, int)
            and not isinstance(prompt_tokens, bool)
            and prompt_tokens >= 0
        )
        completion_usage_known = bool(
            isinstance(completion_tokens, int)
            and not isinstance(completion_tokens, bool)
            and completion_tokens >= 0
        )
        provider_usage_known = prompt_usage_known and completion_usage_known
        if self._require_provider_usage and not provider_usage_known:
            raise RuntimeError(
                "provider-authoritative prompt/completion usage is required"
            )
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=(
                    prompt_tokens
                    if prompt_usage_known
                    else estimate_tokens(prompt)
                ),
                completion_tokens=(
                    completion_tokens
                    if completion_usage_known
                    else estimate_tokens(text)
                ),
            ),
        )
