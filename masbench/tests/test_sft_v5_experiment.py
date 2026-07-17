"""Stage 2 closure tests: sealed experiment root + deterministic provisioning.

The seal is the trust root of a v5 experiment, so every closure it claims must
be checked against real bytes: embedded child digests, authority cross-pins,
split roots, anchor genesis, canonical file encoding, and provisioning
idempotence with fail-closed byte diffs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from masbench.sft_pilot.experiment import (
    load_experiment_seal,
    provision_phase_v5_experiment,
    validate_experiment_seal,
)
from masbench.sft_pilot.manifests import published_manifest_bytes
from masbench.sft_pilot.store import (
    DATABASE_FILENAME,
    PilotIdempotenceConflict,
    SingleWriterPilotStore,
)

from sft_v5_fixtures import build_v5_experiment


@pytest.fixture(scope="module")
def experiment(tmp_path_factory: pytest.TempPathFactory):
    return build_v5_experiment(tmp_path_factory.mktemp("v5-experiment"))


def test_seal_closes_children_and_is_canonically_loadable(experiment) -> None:
    seal = load_experiment_seal(experiment.seal_path)
    assert seal == experiment.seal
    assert seal.experiment.case_manifest_sha256 == seal.case_manifest.digest
    assert seal.state_genesis_sha256 == experiment.provision_receipt.genesis_state_sha256
    validate_experiment_seal(
        seal,
        runtime_authority=experiment.runtime_authority,
        bootstrap_authority=experiment.bootstrap_authority,
        protocol=experiment.protocol,
    )
    # The control protocol is also a sealed arm and must close.
    validate_experiment_seal(
        seal,
        runtime_authority=experiment.runtime_authority,
        bootstrap_authority=experiment.bootstrap_authority,
        protocol=experiment.control_protocol,
    )


def test_seal_rejects_noncanonical_and_tampered_bytes(
    experiment, tmp_path: Path
) -> None:
    pretty = tmp_path / "pretty-seal.json"
    pretty.write_text(
        json.dumps(json.loads(experiment.seal_path.read_bytes()), indent=2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="canonical exact JSON"):
        load_experiment_seal(pretty)

    payload = json.loads(experiment.seal_path.read_bytes())
    payload["state_genesis_sha256"] = "0" * 64
    tampered = tmp_path / "tampered-seal.json"
    tampered.write_text(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sealed PilotExperimentSealV1"):
        load_experiment_seal(tampered)

    symlink = tmp_path / "seal-symlink.json"
    symlink.symlink_to(experiment.seal_path)
    with pytest.raises(ValueError, match="non-symlink|cannot be opened"):
        load_experiment_seal(symlink)


def test_seal_model_rejects_broken_internal_closures(experiment) -> None:
    seal = experiment.seal
    for update, message in (
        ({"method_policy_sha256": "1" * 64}, "method policy root"),
        ({"train_case_manifest_sha256": "2" * 64}, "TRAIN_UPDATE case root"),
        ({"final_val_case_manifest_sha256": "3" * 64}, "FINAL_VAL case root"),
        ({"state_genesis_sha256": "4" * 64}, "genesis root"),
        ({"fixed_git_commit": "f" * 40}, "Git commit"),
        (
            {"test_manifest_sha256": seal.report_manifest_sha256},
            "distinct sealed objects",
        ),
    ):
        payload = seal.model_dump(mode="python")
        payload.update(update)
        with pytest.raises(ValueError, match=message):
            type(seal).model_validate(payload)


def test_seal_validation_rejects_wrong_authorities_and_foreign_protocol(
    experiment,
) -> None:
    wrong_runtime = experiment.runtime_authority.model_copy(
        update={"method_policy_sha256": "5" * 64}
    )
    with pytest.raises(ValueError, match="does not close over its authorities"):
        validate_experiment_seal(
            experiment.seal,
            runtime_authority=wrong_runtime,
            bootstrap_authority=experiment.bootstrap_authority,
            protocol=experiment.protocol,
        )

    foreign_protocol = experiment.protocol.model_copy(
        update={"protocol_id": "not-a-sealed-arm"}
    )
    with pytest.raises(ValueError, match="not a sealed arm"):
        validate_experiment_seal(
            experiment.seal,
            runtime_authority=experiment.runtime_authority,
            bootstrap_authority=experiment.bootstrap_authority,
            protocol=foreign_protocol,
        )


def test_control_arm_cannot_claim_anchor_genesis(experiment) -> None:
    # Tampering the protocol alone changes its digest, so it stops being a
    # sealed arm at all.
    hijacked = experiment.control_protocol.model_copy(
        update={"genesis_state_sha256": experiment.seal.state_genesis_sha256}
    )
    with pytest.raises(ValueError, match="not a sealed arm"):
        validate_experiment_seal(
            experiment.seal,
            runtime_authority=experiment.runtime_authority,
            bootstrap_authority=experiment.bootstrap_authority,
            protocol=hijacked,
        )
    # Even a seal AUTHORED with a control arm claiming the anchor genesis is
    # rejected — non-factor backends can never own the anchor's evidence.
    arms = tuple(experiment.seal.experiment.arms)
    hijacked_arms = (
        arms[0],
        arms[1].model_copy(update={"child_protocol_sha256": hijacked.digest}),
    )
    hijacked_experiment = experiment.seal.experiment.model_copy(
        update={"arms": hijacked_arms}
    )
    hijacked_seal = experiment.seal.model_copy(
        update={"experiment": hijacked_experiment}
    )
    with pytest.raises(ValueError, match="cannot claim the structural-anchor"):
        validate_experiment_seal(
            hijacked_seal,
            runtime_authority=experiment.runtime_authority,
            bootstrap_authority=experiment.bootstrap_authority,
            protocol=hijacked,
        )


def test_provision_is_idempotent_and_recovers_exact_genesis(experiment) -> None:
    first = experiment.provision_receipt
    second = provision_phase_v5_experiment(
        seal=experiment.seal,
        protocol=experiment.protocol,
        runtime_authority=experiment.runtime_authority,
        bootstrap_authority=experiment.bootstrap_authority,
        state_dir=experiment.state_dir,
        store_hmac_key=experiment.component_keys["store"],
        source_authority_key=experiment.component_keys["source_authority"],
        phase_registry_key=experiment.component_keys["phase_registry"],
        factor_bank_key=experiment.component_keys["factor_bank"],
    )
    assert second == first
    assert (experiment.state_dir / DATABASE_FILENAME).is_file()

    with SingleWriterPilotStore.open(
        experiment.state_dir,
        protocol=experiment.protocol,
        hmac_key=experiment.component_keys["store"],
        execution_schedule=experiment.seal.execution_schedule,
    ) as store:
        snapshot = store.latest_component_bundle()
        assert snapshot.metadata.generation == 0
        assert snapshot.metadata.bundle_sha256 == first.genesis_state_sha256
        assert (
            snapshot.phase_registry_envelope_bytes
            == experiment.anchor_runtime.phase_registry_envelope_bytes
        )
        assert (
            snapshot.factor_bank_envelope_bytes
            == experiment.anchor_runtime.factor_bank_envelope_bytes
        )


def test_provision_rejects_changed_bytes_and_wrong_keys(
    experiment, tmp_path: Path
) -> None:
    # Swapped component keys cannot authenticate the frozen anchor envelopes.
    with pytest.raises(ValueError, match="MAC mismatch|anchor"):
        provision_phase_v5_experiment(
            seal=experiment.seal,
            protocol=experiment.protocol,
            runtime_authority=experiment.runtime_authority,
            bootstrap_authority=experiment.bootstrap_authority,
            state_dir=experiment.state_dir,
            store_hmac_key=experiment.component_keys["store"],
            source_authority_key=experiment.component_keys["source_authority"],
            phase_registry_key=experiment.component_keys["factor_bank"],
            factor_bank_key=experiment.component_keys["phase_registry"],
        )
    # A control-arm protocol can never provision the factor state dir.
    with pytest.raises((ValueError, PilotIdempotenceConflict)):
        provision_phase_v5_experiment(
            seal=experiment.seal,
            protocol=experiment.control_protocol,
            runtime_authority=experiment.runtime_authority,
            bootstrap_authority=experiment.bootstrap_authority,
            state_dir=experiment.state_dir,
            store_hmac_key=experiment.component_keys["store"],
            source_authority_key=experiment.component_keys["source_authority"],
            phase_registry_key=experiment.component_keys["phase_registry"],
            factor_bank_key=experiment.component_keys["factor_bank"],
        )


def test_run_evolution_validates_seal_then_stays_fail_closed(
    experiment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The profile entry accepts a sealed+provisioned experiment but must not
    execute anything until the scientific loop exists."""

    import masbench.evolve as evolve

    monkeypatch.setenv("MASBENCH_SFT_STATE_KEY", experiment.master.hex())
    cfg = experiment.run_config()
    with pytest.raises(RuntimeError, match="not authorized in this build"):
        evolve.run_evolution(
            object(),
            cases=None,
            validation_cases=None,
            agent_counts=[2],
            train_seeds=[],
            val_seeds=[],
            cfg=cfg,
            held_out_rows=None,
            initial_skills=None,
            workers=1,
        )
    assert not experiment.result_dir.exists()

    # A tampered seal byte fails before the store is even opened.
    tampered_path = experiment.root / "tampered-seal.json"
    payload = bytearray(experiment.seal_path.read_bytes())
    payload[-2] = ord("x")
    tampered_path.write_bytes(bytes(payload))
    bad_cfg = experiment.run_config(
        sft_experiment_manifest_path=str(tampered_path.resolve())
    )
    with pytest.raises(ValueError, match="experiment manifest"):
        evolve.run_evolution(
            object(),
            cases=None,
            validation_cases=None,
            agent_counts=[2],
            train_seeds=[],
            val_seeds=[],
            cfg=bad_cfg,
            held_out_rows=None,
            initial_skills=None,
            workers=1,
        )


def test_authority_manifest_files_round_trip_canonically(experiment) -> None:
    assert (
        experiment.runtime_authority_path.read_bytes()
        == published_manifest_bytes(experiment.runtime_authority)
    )
    assert (
        experiment.bootstrap_authority_path.read_bytes()
        == published_manifest_bytes(experiment.bootstrap_authority)
    )
