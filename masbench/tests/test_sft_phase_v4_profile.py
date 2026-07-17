from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import masbench.evolve as evolve
from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.phase_artifact_registry import PHASE_FULL_FACTOR_BINDER_VERSION
from exp_graph.mas.phase_program import PHASE_PROGRAM_COMPILER_VERSION
from masbench.cli import build_parser, main
from masbench.core.config import RunConfig
from masbench.sft_phase_pilot import (
    _V4_FACTOR_KEY_DOMAIN,
    _V4_PHASE_KEY_DOMAIN,
    _V4_STORE_KEY_DOMAIN,
    _derive_key,
)
from masbench.sft_pilot.components import (
    FACTOR_WORKING_FILENAME,
    PHASE_WORKING_FILENAME,
    build_empty_component_envelopes,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
    canonical_json,
)
from masbench.sft_pilot.store import (
    SingleWriterPilotStore,
    component_bundle_state_sha256,
)


MASTER = hashlib.sha256(b"phase-v4-profile-test-master").digest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace(*, objective: str = "balanced") -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="silo_bench",
        objective=objective,
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=2,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="pilot-runtime-v1",
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _arm() -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id="pair-v4",
        pair_arm="control",
        case_commitment_sha256=_sha("case-v4"),
        unit_commitment="unit-v4",
        split="TRAIN_UPDATE",
        operation_kind="proposal_generation",
        execution_ordinal=0,
    )


def _protocol(
    genesis_sha256: str,
    *,
    objective: str = "balanced",
    component_bundle_required: bool = True,
    namespace: ExecutionNamespace | None = None,
) -> PilotProtocolV1:
    return PilotProtocolV1(
        protocol_id="phase-v4-profile-test",
        method_arm="sft_unified",
        namespace=namespace or _namespace(objective=objective),
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("catalog-v4"),
            source_policy_sha256=_sha("source-policy-v4"),
        ),
        source_authority_sha256=_sha("source-authority-v4"),
        dataset_split_policy_sha256=_sha("split-policy-v4"),
        candidate_pool_manifest_sha256=_sha("candidate-pool-v4"),
        runner_config_sha256=_sha("runner-config-v4"),
        model_config_sha256=_sha("model-config-v4"),
        pair_manifest_sha256=_sha("pair-manifest-v4"),
        genesis_state_sha256=genesis_sha256,
        component_bundle_required=component_bundle_required,
        authorized_logical_arms=(_arm(),),
        phase_budgets=tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm="sft_unified",
                executions=2,
                call_slots=2,
                input_tokens=4_096,
                output_tokens=2_048,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=4,
            max_execution_leases=4,
            max_call_receipts=8,
            max_call_slots_per_execution=2,
            max_input_tokens_per_call=4_096,
            max_output_tokens_per_call=2_048,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=8 * 1024 * 1024,
        ),
    )


def _cfg(
    state_dir: Path,
    protocol_path: Path | str,
    **updates: object,
) -> RunConfig:
    values: dict[str, object] = {
        "benchmark": "silo_bench",
        "use_planner": True,
        "use_skill_evolution": True,
        "sft_profile": "phase_v4_single_writer_preliminary",
        "sft_state_dir": str(state_dir.resolve()),
        "sft_protocol_path": str(protocol_path),
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
    }
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


def _provision(
    tmp_path: Path,
) -> tuple[Path, Path, PilotProtocolV1, bytes, bytes]:
    state_dir = tmp_path / "state"
    phase_bytes, factor_bytes = build_empty_component_envelopes(
        state_dir,
        phase_registry_key=_derive_key(MASTER, _V4_PHASE_KEY_DOMAIN),
        factor_bank_key=_derive_key(MASTER, _V4_FACTOR_KEY_DOMAIN),
        manifest_verifier=lambda _manifest: False,
    )
    genesis = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    protocol = _protocol(genesis)
    protocol_path = tmp_path / "pilot-protocol.json"
    protocol_path.write_text(canonical_json(protocol), encoding="utf-8")
    with SingleWriterPilotStore.open(
        state_dir,
        protocol=protocol,
        hmac_key=_derive_key(MASTER, _V4_STORE_KEY_DOMAIN),
    ) as store:
        store.record_genesis_component_bundle(
            operation_id="phase-v4-genesis",
            request_sha256=_sha("phase-v4-genesis"),
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )
    return state_dir, protocol_path, protocol, phase_bytes, factor_bytes


def test_phase_v4_is_cli_opt_in_and_default_config_remains_empty(
    tmp_path: Path,
) -> None:
    assert RunConfig().sft_protocol_path is None
    args = build_parser().parse_args(
        [
            "evolve",
            "--out",
            str(tmp_path / "out"),
            "--sft-profile",
            "phase_v4_single_writer_preliminary",
            "--sft-protocol",
            str(tmp_path / "protocol.json"),
        ]
    )
    assert args.sft_profile == "phase_v4_single_writer_preliminary"
    assert args.sft_protocol == str(tmp_path / "protocol.json")


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"sft_protocol_path": "relative.json"}, "absolute"),
        ({"llm_provider": "deepseek"}, "openai provider"),
        (
            {"llm_provider": "openai", "model_name": "gpt-4o"},
            "gpt-4o-mini",
        ),
        (
            {
                "llm_provider": "openai",
                "model_name": "gpt-4o-mini",
                "base_url": "https://example.invalid/v1",
            },
            "official OpenAI",
        ),
        ({"planner_mode": "graph_generate"}, "program_generate"),
        ({"failure_policy": "legacy_drop"}, "honest_v2"),
        ({"hot_start_enabled": True}, "legacy confounders"),
    ],
)
def test_phase_v4_config_fails_closed(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    protocol_path = (tmp_path / "protocol.json").resolve()
    with pytest.raises(ValueError, match=message):
        evolve._validate_v2_config(
            _cfg(tmp_path / "state", protocol_path, **updates)
        )


def test_phase_v4_rejects_malformed_and_wrong_run_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", MASTER.hex())
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"not":"a protocol"}', encoding="utf-8")
    with pytest.raises(ValueError, match="closed PilotProtocolV1"):
        _run(_cfg(tmp_path / "state", malformed))

    wrong = tmp_path / "wrong.json"
    wrong.write_text(
        canonical_json(_protocol(_sha("genesis"), objective="accuracy_first")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="objective"):
        _run(_cfg(tmp_path / "state", wrong))

    wrong_mode_namespace = ExecutionNamespace(
        task_family="silo_bench",
        objective="balanced",
        information_goal="sink",
        planner_mode="paper_protocol_runtime",
        payload_format="paper_transport_skill_v1",
        worker_contract="not_applicable",
        n_agents=2,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="paper-runtime-v1",
        binder_version="paper-binder-v1",
        compiler_version="paper-compiler-v1",
    )
    wrong_mode = tmp_path / "wrong-mode.json"
    wrong_mode.write_text(
        canonical_json(
            _protocol(_sha("genesis"), namespace=wrong_mode_namespace)
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="planner_payload_worker_contract"):
        _run(_cfg(tmp_path / "state", wrong_mode))


def test_phase_v4_requires_component_bundle_and_single_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", MASTER.hex())
    protocol_path = tmp_path / "no-bundle.json"
    protocol_path.write_text(
        canonical_json(
            _protocol(_sha("genesis"), component_bundle_required=False)
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="component_bundle_required"):
        _run(_cfg(tmp_path / "state", protocol_path))

    valid_path = tmp_path / "valid.json"
    valid_path.write_text(
        canonical_json(_protocol(_sha("genesis"))),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="workers=1"):
        _run(_cfg(tmp_path / "state", valid_path), workers=2)


def test_phase_v4_direct_entry_rejects_legacy_scientific_inputs(
    tmp_path: Path,
) -> None:
    from masbench.sft_phase_pilot import run_sft_phase_evolution

    cfg = _cfg(tmp_path / "state", (tmp_path / "protocol.json").resolve())
    with pytest.raises(ValueError, match="synthetic held-out"):
        run_sft_phase_evolution(
            object(),
            cfg=cfg,
            held_out_rows=[{"topology": "mesh"}],
        )


def test_phase_v4_restores_exact_native_component_bytes_with_zero_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir, protocol_path, protocol, phase_bytes, factor_bytes = _provision(
        tmp_path
    )
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", MASTER.hex())
    (state_dir / PHASE_WORKING_FILENAME).write_text(
        "replaceable drift", encoding="utf-8"
    )
    (state_dir / FACTOR_WORKING_FILENAME).write_text(
        "replaceable drift", encoding="utf-8"
    )

    summary = _run(_cfg(state_dir, protocol_path))

    assert summary["method_status"] == "component_restore_only_no_efficacy_claim"
    assert summary["sft_protocol_sha256"] == protocol.digest
    assert summary["component_bundle_generation"] == 0
    assert summary["component_bundle_sha256"] == protocol.genesis_state_sha256
    assert summary["model_calls"] == summary["total_tokens"] == 0
    assert summary["gate"] == {
        "accepted": False,
        "j_before": 0.0,
        "j_after": 0.0,
        "epsilon": 0.0,
        "reason": "component_restore_has_no_probe_or_gate",
    }
    assert (state_dir / PHASE_WORKING_FILENAME).read_bytes() == phase_bytes
    assert (state_dir / FACTOR_WORKING_FILENAME).read_bytes() == factor_bytes


def test_phase_v4_cli_routes_to_mechanics_only_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir, protocol_path, protocol, _phase_bytes, _factor_bytes = _provision(
        tmp_path
    )
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", MASTER.hex())
    out = tmp_path / "cli-out"

    assert main(
        [
            "evolve",
            "--benchmarks-dir",
            str(tmp_path / "absent-benchmarks"),
            "--planner-mode",
            "program_generate",
            "--sft-profile",
            "phase_v4_single_writer_preliminary",
            "--sft-state-dir",
            str(state_dir),
            "--sft-protocol",
            str(protocol_path),
            "--out",
            str(out),
        ]
    ) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["method_status"] == "component_restore_only_no_efficacy_claim"
    assert summary["sft_protocol_sha256"] == protocol.digest
    assert summary["model_calls"] == summary["total_tokens"] == 0


def test_phase_v4_does_not_create_an_unprovisioned_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", MASTER.hex())
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(
        canonical_json(_protocol(_sha("genesis"))),
        encoding="utf-8",
    )
    state_dir = tmp_path / "absent"
    with pytest.raises(RuntimeError, match="pre-provisioned"):
        _run(_cfg(state_dir, protocol_path))
    assert not state_dir.exists()
