from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import masbench.evolve as evolve
from masbench.cli import build_parser, main
from masbench.core.config import RunConfig


def _active_cfg(state_dir: Path, **updates: object) -> RunConfig:
    values: dict[str, object] = {
        "use_planner": True,
        "use_skill_evolution": True,
        "sft_profile": "phase_v3_shadow_register",
        "sft_state_dir": str(state_dir.resolve()),
        "planner_mode": "program_generate",
        "evolved_mode": "program_generate",
        "failure_policy": "honest_v2",
        "evolution_gate_policy": "strict_dense_v2",
        "evolve_explore": 0,
        "evidence_portfolio": "",
        "recipe_search_budget": 0,
        "exemplar_search_budget": 0,
        "use_llm_insights": False,
        "hot_start_enabled": False,
    }
    values.update(updates)
    return RunConfig(**values)


def _run(cfg: RunConfig) -> dict[str, object]:
    return evolve.run_evolution(
        object(),
        cases=None,
        validation_cases=None,
        agent_counts=None,
        train_seeds=[],
        val_seeds=[],
        cfg=cfg,
        held_out_rows=None,
        initial_skills=None,
    )


def test_run_config_and_cli_keep_sft_default_off(tmp_path: Path) -> None:
    assert RunConfig().sft_profile == "off"
    assert RunConfig().sft_state_dir is None
    parser = build_parser()
    args = parser.parse_args(["evolve", "--out", str(tmp_path / "out")])
    assert args.sft_profile == "off"
    assert args.sft_state_dir is None
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run",
                "--case",
                "I-01",
                "--n-agents",
                "2",
                "--sft-profile",
                "phase_v3_shadow_register",
            ]
        )


def test_default_path_does_not_import_sft_or_read_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LegacyPathReached(RuntimeError):
        pass

    sys.modules.pop("masbench.sft_phase_pilot", None)
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "not-a-key")

    def stop_before_any_legacy_model_call(_cfg: RunConfig) -> None:
        raise LegacyPathReached

    monkeypatch.setattr(evolve, "_build_llm_client", stop_before_any_legacy_model_call)
    with pytest.raises(LegacyPathReached):
        _run(RunConfig(sft_profile="off"))
    assert "masbench.sft_phase_pilot" not in sys.modules


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"planner_mode": "graph_generate"}, "program_generate"),
        ({"sft_state_dir": "relative"}, "absolute"),
        ({"failure_policy": "legacy_drop"}, "honest_v2"),
        ({"hot_start_enabled": True}, "legacy confounders"),
        ({"evidence_portfolio": "chain"}, "legacy confounders"),
    ],
)
def test_active_profile_fails_closed_on_partial_or_confounded_config(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        evolve._validate_v2_config(_active_cfg(tmp_path / "state", **updates))


def test_active_profile_missing_key_fails_before_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "never-created"
    monkeypatch.delenv("MASBENCH_SFT_STATE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MASBENCH_SFT_STATE_KEY"):
        _run(_active_cfg(state_dir))
    assert not state_dir.exists()


@pytest.mark.parametrize("encoded", ["zz-not-hex-or-base64", "00" * 16])
def test_active_profile_invalid_key_fails_before_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoded: str,
) -> None:
    state_dir = tmp_path / "never-created-invalid-key"
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", encoded)
    with pytest.raises(ValueError, match="hex or strict base64|at least 32 bytes"):
        _run(_active_cfg(state_dir))
    assert not state_dir.exists()


def test_shadow_register_is_authenticated_idempotent_and_zero_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "sft"
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "42" * 32)
    first = _run(_active_cfg(state_dir))
    second = _run(_active_cfg(state_dir))

    assert first["method_status"] == "shadow_register_only_no_efficacy_claim"
    assert first["model_calls"] == first["total_tokens"] == 0
    assert first["gate"] == {
        "accepted": False,
        "j_before": 0.0,
        "j_after": 0.0,
        "epsilon": 0.0,
        "reason": "shadow_register_has_no_probe_or_gate",
    }
    assert first["phase_registry_state_sha256"] == second[
        "phase_registry_state_sha256"
    ]
    assert first["factor_bank_state_sha256"] == second[
        "factor_bank_state_sha256"
    ]
    assert (state_dir / "phase_registry.v7.json").is_file()
    bank_path = state_dir / "factor_bank.v4.json"
    assert bank_path.is_file()

    envelope = json.loads(bank_path.read_text(encoding="utf-8"))
    envelope["state_hmac_sha256"] = "0" * 64
    bank_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="HMAC"):
        _run(_active_cfg(state_dir))


def test_shadow_register_rejects_nonempty_legacy_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "43" * 32)
    cfg = _active_cfg(tmp_path / "sft")
    with pytest.raises(ValueError, match="synthetic held-out"):
        evolve.run_evolution(
            object(),
            cases=None,
            agent_counts=None,
            train_seeds=[],
            val_seeds=[],
            cfg=cfg,
            held_out_rows=[{"topology": "mesh"}],
        )


def test_evolve_cli_runs_shadow_register_without_a_benchmark_or_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "45" * 32)
    out = tmp_path / "cli-shadow"
    assert main(
        [
            "evolve",
            "--benchmarks-dir",
            str(tmp_path / "deliberately-absent-benchmarks"),
            "--planner-mode",
            "program_generate",
            "--sft-profile",
            "phase_v3_shadow_register",
            "--out",
            str(out),
        ]
    ) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["method_status"] == "shadow_register_only_no_efficacy_claim"
    assert summary["model_calls"] == summary["total_tokens"] == 0
    assert summary["gate"]["accepted"] is False
    assert (out / "sft" / "phase_registry.v7.json").is_file()
    assert (out / "sft" / "factor_bank.v4.json").is_file()
