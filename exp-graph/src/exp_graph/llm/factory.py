"""LLM client factory."""
# ============================================================
# 【模块导读】LLM 客户端工厂：create_llm_client 按 provider(供应商)分发构建客户端。
# 核心机制：WALLCLOCK_TIMEOUT_ENV 环境变量(或 timeout_s 参数)给出每请求墙钟超时预算，
# 此处构建的每个非 fake 客户端都会被 TimeoutLLMClient 包上硬性墙钟超时守卫；
# masbench engine 依赖该机制，使引擎内部自建的客户端也全部带超时守卫。
# ============================================================

from __future__ import annotations

import os

from exp_graph.llm.base import LLMClient
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.llm.openai_client import OpenAIChatClient
from exp_graph.llm.timeout import TimeoutLLMClient

# 中文：该环境变量存放“每请求硬性墙钟预算(秒)”，应用到此处构建的每一个非 fake 客户端。
#   masbench 会用 cfg.request_timeout 设置它，使引擎内部自建客户端的调用点(角色客户端、
#   图生成候选评估器、insight minister、ProtocolRunner 兜底)也一并受守卫——而不只是
#   调用方显式传入的那个客户端。设为 0 或未设置则关闭守卫(向后兼容)。
#: Env var holding the per-request hard wall-clock budget (seconds) applied to
#: EVERY non-fake client built here. masbench sets it from ``cfg.request_timeout``
#: so engine-internal sites that build their own clients (role clients, the
#: graph-generation candidate evaluator, the insight minister, the
#: ``ProtocolRunner`` fallback) are guarded too -- not just the client a caller
#: explicitly threads in. ``0``/unset disables the guard (back-compat).
WALLCLOCK_TIMEOUT_ENV = "EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT"

_REAL_PROVIDERS = {
    "openai",
    "deepseek",
    "bailian",
    "dashscope",
    "qwen",
    "alibaba",
    "xiaomi",
}


# 【职责】解析实际生效的墙钟超时预算：显式入参优先于环境变量。
# - 无入参时读 WALLCLOCK_TIMEOUT_ENV；缺失/为空/非法值一律回落为 0.0(即不启用守卫)。
def _wallclock_timeout(timeout_s: float | None) -> float:
    """Resolve the effective wall-clock budget (explicit arg overrides env)."""
    if timeout_s is not None:
        return float(timeout_s)
    try:
        return float(os.environ.get(WALLCLOCK_TIMEOUT_ENV, "0") or 0)
    except ValueError:
        return 0.0


# 【职责】在配置了预算时给真实客户端包上硬性墙钟超时守卫。
# - 预算 > 0 返回 TimeoutLLMClient 包装；否则原样返回内层客户端。
def _guarded(client: LLMClient, timeout_s: float | None) -> LLMClient:
    """Wrap a real client in a hard wall-clock timeout when one is configured."""
    budget = _wallclock_timeout(timeout_s)
    if budget > 0:
        return TimeoutLLMClient(client, budget)
    return client


# 【职责】创建 LLM 客户端：引擎内构建客户端的统一入口，按 provider(供应商)分发。
# - "fake" -> 离线假客户端(确定性、零成本)，永不包超时守卫。
# - 真实供应商(openai/deepseek/bailian/dashscope/qwen/alibaba/xiaomi) -> OpenAIChatClient，
# - 可显式传 base_url(接口地址)、api_key_env(存 key 的环境变量名)、thinking_enabled。
# - "auto" -> 有 OPENAI_API_KEY 时用 OpenAI，否则退回离线假客户端以支持离线冒烟运行。
# - 配置了预算(timeout_s 参数或 EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT 环境变量)时，每个非 fake
# - 客户端都会包上硬性墙钟超时守卫：无论哪条代码路径构建的客户端，挂死的供应商调用
# - 都会快速失败，而不是冻结整个运行。未知 provider 抛 ValueError。
def create_llm_client(
    provider: str,
    *,
    base_url: str | None = None,
    api_key_env: str | None = None,
    thinking_enabled: bool | None = None,
    timeout_s: float | None = None,
) -> LLMClient:
    """Create an LLM client.

    ``auto`` uses OpenAI when `OPENAI_API_KEY` is available, otherwise the fake
    deterministic client for offline smoke runs.

    Every non-fake client is wrapped in a hard wall-clock
    :class:`~exp_graph.llm.timeout.TimeoutLLMClient` when a budget is configured
    (``timeout_s`` arg or the ``EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT`` env var), so a
    hung provider call fails fast instead of freezing the run -- no matter which
    code path constructed the client. The fake client is never wrapped.
    """
    if provider == "fake":
        return FakeLLMClient()
    if provider in _REAL_PROVIDERS:
        return _guarded(
            OpenAIChatClient(
                base_url=base_url,
                api_key_env=api_key_env,
                platform=provider,
                thinking_enabled=thinking_enabled,
            ),
            timeout_s,
        )
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            return _guarded(
                OpenAIChatClient(thinking_enabled=thinking_enabled), timeout_s
            )
        return FakeLLMClient()
    raise ValueError(
        "provider must be one of: auto, fake, openai, deepseek, bailian, dashscope, qwen, alibaba, xiaomi"
    )
