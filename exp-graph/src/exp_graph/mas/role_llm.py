"""Role-specific LLM resolution for MAS emperor/soldier/minister calls."""

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


def load_role_llm_profiles(path: Path | str | None) -> RoleLLMProfiles | None:
    """Load role profiles from JSON, accepting either top-level roles or {"roles": ...}."""
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("roles"), dict):
        data = data["roles"]
    return RoleLLMProfiles.model_validate(data)


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


def role_llm_summary(runtime: MASRuntimeConfig) -> dict[str, dict[str, object]]:
    """Return a serializable summary of all resolved role model settings."""
    return {
        role: resolve_role_llm_config(runtime, role).model_dump(mode="json")
        for role in ("emperor", "soldier", "minister")
    }
