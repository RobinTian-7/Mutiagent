"""Role-specific LLM resolution for MAS emperor/soldier/minister calls."""
# ============================================================
# 【模块导读】MAS 皇帝/士兵/minister 调用的角色级 LLM 解析(分模型配置)。
# 提供角色档案(role_llm_profiles)时按角色解析平台/模型/温度/thinking；
# 缺档案时兜底到旧版全局 llm_provider/model_name 路径。
# 士兵角色强制 thinking 关闭；其余角色缺省视为开启。
# ============================================================

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.schemas import (
    LLMRoleName,
    MASRuntimeConfig,
    RoleLLMConfig,
    RoleLLMProfiles,
)


# 【职责】应用角色默认与旧版兜底后的最终模型设置(平台/模型/温度等)。
class ResolvedRoleLLMConfig(BaseModel):
    """Concrete model settings after applying role defaults and legacy fallback."""

    role: LLMRoleName
    platform: str
    model_name: str
    temperature: float
    base_url: str | None = None
    api_key_env: str | None = None
    thinking_enabled: bool | None = None
    explicit_profile: bool = False


# 【职责】从 JSON 加载角色档案；顶层角色字典或 {"roles": ...} 包装皆可。
def load_role_llm_profiles(path: Path | str | None) -> RoleLLMProfiles | None:
    """Load role profiles from JSON, accepting either top-level roles or {"roles": ...}."""
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("roles"), dict):
        data = data["roles"]
    return RoleLLMProfiles.model_validate(data)


# 【职责】把单个角色解析为具体 LLM 设置——皇帝/士兵分模型的核心。
# - 缺角色档案时有意兜底到旧版全局 llm_provider/model_name 路径，
#   含其在 OpenAI 兼容客户端中现有的非 thinking 行为
# - 士兵角色显式 thinking_enabled=True 会抛错，否则强制 False；
#   其余角色缺省视为 True
def resolve_role_llm_config(
    runtime: MASRuntimeConfig,
    role: LLMRoleName,
) -> ResolvedRoleLLMConfig:
    """Resolve one role to concrete LLM settings.

    Missing role profiles intentionally fall back to the legacy global
    ``llm_provider``/``model_name`` path, including its current non-thinking
    behavior in the OpenAI-compatible client.
    """
    profile = (
        runtime.role_llm_profiles.get_role(role)
        if runtime.role_llm_profiles
        else None
    )
    if profile is None:
        return ResolvedRoleLLMConfig(
            role=role,
            platform=runtime.llm_provider,
            model_name=runtime.model_name,
            temperature=runtime.temperature,
            thinking_enabled=None,
            explicit_profile=False,
        )

    thinking_enabled = profile.thinking_enabled
    if role == "soldier":
        if thinking_enabled is True:
            raise ValueError("soldier role LLM must have thinking_enabled=false")
        thinking_enabled = False
    elif thinking_enabled is None:
        thinking_enabled = True

    return ResolvedRoleLLMConfig(
        role=role,
        platform=profile.platform,
        model_name=profile.model_name or runtime.model_name,
        temperature=runtime.temperature
        if profile.temperature is None
        else profile.temperature,
        base_url=profile.base_url,
        api_key_env=profile.api_key_env,
        thinking_enabled=thinking_enabled,
        explicit_profile=True,
    )


# 【职责】按解析结果为该 MAS 角色创建 LLM 客户端。
def create_role_llm_client(
    runtime: MASRuntimeConfig,
    role: LLMRoleName,
) -> LLMClient:
    """Create an LLM client for a resolved MAS role."""
    resolved = resolve_role_llm_config(runtime, role)
    return create_llm_client(
        resolved.platform,
        base_url=resolved.base_url,
        api_key_env=resolved.api_key_env,
        thinking_enabled=resolved.thinking_enabled,
    )


# 【职责】汇总皇帝/士兵/minister 三角色解析后的模型设置(可序列化，供落盘)。
def role_llm_summary(runtime: MASRuntimeConfig) -> dict[str, dict[str, object]]:
    """Return a serializable summary of all resolved role model settings."""
    return {
        role: resolve_role_llm_config(runtime, role).model_dump(mode="json")
        for role in ("emperor", "soldier", "minister")
    }
