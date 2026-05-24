import json

import pytest

from exp_graph.mas.role_llm import load_role_llm_profiles, resolve_role_llm_config
from exp_graph.mas.schemas import MASRuntimeConfig, RoleLLMConfig, RoleLLMProfiles


def test_missing_role_profile_uses_legacy_global_config() -> None:
    runtime = MASRuntimeConfig(
        llm_provider="openai",
        model_name="gpt-4o-mini",
        temperature=0.2,
    )

    resolved = resolve_role_llm_config(runtime, "emperor")

    assert resolved.platform == "openai"
    assert resolved.model_name == "gpt-4o-mini"
    assert resolved.temperature == 0.2
    assert resolved.thinking_enabled is None
    assert resolved.explicit_profile is False


def test_explicit_emperor_and_minister_default_to_thinking() -> None:
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        role_llm_profiles=RoleLLMProfiles(
            emperor=RoleLLMConfig(platform="deepseek", model_name="deepseek-v4-flash"),
            minister=RoleLLMConfig(platform="bailian", model_name="qwen3.5-flash"),
        ),
    )

    assert resolve_role_llm_config(runtime, "emperor").thinking_enabled is True
    assert resolve_role_llm_config(runtime, "minister").thinking_enabled is True


def test_explicit_soldier_profile_forces_non_thinking() -> None:
    runtime = MASRuntimeConfig(
        llm_provider="fake",
        model_name="fake",
        role_llm_profiles=RoleLLMProfiles(
            soldier=RoleLLMConfig(platform="bailian", model_name="qwen3.5-flash"),
        ),
    )

    resolved = resolve_role_llm_config(runtime, "soldier")

    assert resolved.thinking_enabled is False


def test_explicit_soldier_thinking_enabled_is_rejected() -> None:
    runtime = MASRuntimeConfig(
        role_llm_profiles=RoleLLMProfiles(
            soldier=RoleLLMConfig(
                platform="bailian",
                model_name="qwen3.5-flash",
                thinking_enabled=True,
            ),
        ),
    )

    with pytest.raises(ValueError, match="soldier role LLM"):
        resolve_role_llm_config(runtime, "soldier")


def test_load_role_llm_profiles_accepts_roles_wrapper(tmp_path) -> None:
    path = tmp_path / "roles.json"
    path.write_text(
        json.dumps(
            {
                "roles": {
                    "soldier": {
                        "platform": "bailian",
                        "model_name": "qwen3.5-flash",
                        "thinking_enabled": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    profiles = load_role_llm_profiles(path)

    assert profiles is not None
    assert profiles.soldier is not None
    assert profiles.soldier.model_name == "qwen3.5-flash"
