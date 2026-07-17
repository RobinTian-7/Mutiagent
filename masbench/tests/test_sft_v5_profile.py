"""Stage 1 closure tests for the ``phase_v5_executable_sft`` profile.

v5 is the first profile that is *allowed* to execute scientific calls, so its
configuration surface must be closed before any runner exists: every authority
path is required, absolute, and non-symlink; the model surface is frozen; the
default path stays byte-identical; and an unprovisioned experiment fails
before any state or call is created.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import masbench.evolve as evolve
from masbench.cli import build_parser
from masbench.core.config import RunConfig

V5 = "phase_v5_executable_sft"


def _v5_paths(root: Path) -> dict[str, str]:
    return {
        "sft_state_dir": str((root / "state").resolve()),
        "sft_protocol_path": str((root / "protocol.json").resolve()),
        "sft_experiment_manifest_path": str(
            (root / "experiment.json").resolve()
        ),
        "sft_runtime_authority_path": str((root / "runtime.json").resolve()),
        "sft_bootstrap_authority_path": str(
            (root / "bootstrap.json").resolve()
        ),
        "sft_result_dir": str((root / "results").resolve()),
    }


def _v5_cfg(root: Path, **updates: object) -> RunConfig:
    values: dict[str, object] = {
        "benchmark": "silo_bench",
        "use_planner": True,
        "use_skill_evolution": True,
        "sft_profile": V5,
        "planner_mode": "program_generate",
        "evolved_mode": "program_generate",
        "objective": "balanced",
        "silo_eval_mode": "sink",
        "failure_policy": "honest_v2",
        "evolution_gate_policy": "strict_dense_v2",
        "evolve_explore": 0,
        "evidence_portfolio": "",
        "recipe_search_budget": 0,
        "exemplar_search_budget": 0,
        "use_llm_insights": False,
        "hot_start_enabled": False,
        "llm_provider": "fake",
        "model_name": "fake",
        "temperature": 0.0,
    }
    values.update(_v5_paths(root))
    values.update(updates)
    return RunConfig(**values)


def _run(cfg: RunConfig, *, workers: int = 1) -> dict[str, object]:
    return evolve.run_evolution(
        object(),
        cases=None,
        validation_cases=None,
        agent_counts=[2],
        train_seeds=[],
        val_seeds=[],
        cfg=cfg,
        held_out_rows=None,
        initial_skills=None,
        workers=workers,
    )


def test_v5_default_config_and_cli_surface(tmp_path: Path) -> None:
    cfg = RunConfig()
    assert cfg.sft_profile == "off"
    assert cfg.sft_experiment_manifest_path is None
    assert cfg.sft_runtime_authority_path is None
    assert cfg.sft_bootstrap_authority_path is None
    assert cfg.sft_result_dir is None

    parser = build_parser()
    args = parser.parse_args(["evolve", "--out", str(tmp_path / "out")])
    assert args.sft_profile == "off"
    assert args.sft_experiment_manifest is None
    assert args.sft_runtime_authority is None
    assert args.sft_bootstrap_authority is None
    assert args.sft_result_dir is None

    args = parser.parse_args(
        [
            "evolve",
            "--out",
            str(tmp_path / "out"),
            "--sft-profile",
            V5,
            "--sft-protocol",
            str(tmp_path / "protocol.json"),
            "--sft-experiment-manifest",
            str(tmp_path / "experiment.json"),
            "--sft-runtime-authority",
            str(tmp_path / "runtime.json"),
            "--sft-bootstrap-authority",
            str(tmp_path / "bootstrap.json"),
            "--sft-result-dir",
            str(tmp_path / "results"),
        ]
    )
    assert args.sft_profile == V5
    # The one-off "run" command must not grow an SFT surface.
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["run", "--case", "I-01", "--n-agents", "2", "--sft-profile", V5]
        )


def test_v5_happy_config_passes_validation(tmp_path: Path) -> None:
    evolve._validate_v2_config(_v5_cfg(tmp_path))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"sft_experiment_manifest_path": None}, "sft_experiment_manifest_path"),
        ({"sft_experiment_manifest_path": "relative.json"}, "absolute"),
        ({"sft_runtime_authority_path": None}, "sft_runtime_authority_path"),
        ({"sft_runtime_authority_path": "relative.json"}, "absolute"),
        ({"sft_bootstrap_authority_path": None}, "sft_bootstrap_authority_path"),
        ({"sft_bootstrap_authority_path": "relative.json"}, "absolute"),
        ({"sft_result_dir": None}, "sft_result_dir"),
        ({"sft_result_dir": "relative-results"}, "absolute"),
        ({"sft_protocol_path": None}, "sft_protocol_path"),
        ({"sft_protocol_path": "relative.json"}, "absolute"),
        ({"planner_mode": "graph_generate"}, "program_generate"),
        ({"evolved_mode": "topology_select"}, "program_generate"),
        ({"failure_policy": "legacy_drop"}, "honest_v2"),
        ({"evolution_gate_policy": "legacy_non_regression"}, "strict_dense_v2"),
        ({"hot_start_enabled": True}, "legacy confounders"),
        ({"use_llm_insights": True}, "legacy confounders"),
        ({"evolve_explore": 1}, "legacy confounders"),
        ({"evidence_portfolio": "chain"}, "legacy confounders"),
        ({"recipe_search_budget": 18}, "legacy confounders"),
        ({"exemplar_search_budget": 6}, "legacy confounders"),
        ({"llm_provider": "deepseek"}, "openai provider"),
        ({"llm_provider": "openai", "model_name": "gpt-4o"}, "gpt-4o-mini"),
        (
            {
                "llm_provider": "openai",
                "model_name": "gpt-4o-mini",
                "base_url": "https://example.invalid/v1",
            },
            "official OpenAI",
        ),
        ({"planner_model_name": "gpt-4o"}, "frozen gpt-4o-mini"),
        ({"temperature": 0.2}, "temperature"),
    ],
)
def test_v5_config_fails_closed(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        evolve._validate_v2_config(_v5_cfg(tmp_path, **updates))


def test_v5_rejects_workers_beyond_single_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "44" * 32)
    with pytest.raises(ValueError, match="workers=1"):
        _run(_v5_cfg(tmp_path), workers=2)


def test_v5_missing_key_fails_before_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MASBENCH_SFT_STATE_KEY", raising=False)
    cfg = _v5_cfg(tmp_path)
    with pytest.raises(RuntimeError, match="MASBENCH_SFT_STATE_KEY"):
        _run(cfg)
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "results").exists()


def test_v5_missing_frozen_inputs_fail_before_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No protocol/manifest file on disk -> fail closed, zero side effects."""

    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "44" * 32)
    cfg = _v5_cfg(tmp_path)
    with pytest.raises(ValueError, match="cannot be opened"):
        _run(cfg)
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "results").exists()


def test_v5_symlinked_experiment_manifest_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "44" * 32)
    cfg = _v5_cfg(tmp_path)
    Path(cfg.sft_protocol_path).write_text("{}", encoding="utf-8")
    real = tmp_path / "real-manifest.json"
    real.write_text("{}", encoding="utf-8")
    Path(cfg.sft_experiment_manifest_path).symlink_to(real)
    with pytest.raises(ValueError, match="non-symlink|cannot be opened"):
        _run(cfg)
    assert not (tmp_path / "state").exists()


def test_v5_rejects_legacy_scientific_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "44" * 32)
    cfg = _v5_cfg(tmp_path)
    with pytest.raises(ValueError, match="synthetic held-out"):
        evolve.run_evolution(
            object(),
            cases=None,
            agent_counts=[2],
            train_seeds=[],
            val_seeds=[],
            cfg=cfg,
            held_out_rows=[{"topology": "mesh"}],
        )
    # Direct entry must apply the same defensive rejection.
    from masbench.sft_phase_pilot import run_sft_phase_evolution

    with pytest.raises(ValueError, match="synthetic held-out"):
        run_sft_phase_evolution(
            object(),
            cfg=cfg,
            held_out_rows=[{"topology": "mesh"}],
        )


def test_off_path_ignores_v5_fields_and_stays_lazy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off + populated v5 paths must not import SFT modules or touch disk."""

    class LegacyPathReached(RuntimeError):
        pass

    for name in [m for m in sys.modules if m.startswith("masbench.sft_")]:
        sys.modules.pop(name, None)
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", "not-a-key")

    def stop(_cfg: RunConfig) -> None:
        raise LegacyPathReached

    monkeypatch.setattr(evolve, "_build_llm_client", stop)
    cfg = _v5_cfg(tmp_path, sft_profile="off")
    with pytest.raises(LegacyPathReached):
        _run(cfg)
    assert "masbench.sft_phase_pilot" not in sys.modules
    assert not any(
        name.startswith("masbench.sft_pilot") for name in sys.modules
    )
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "results").exists()
