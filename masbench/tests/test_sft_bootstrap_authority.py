from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
from pathlib import Path
import pickle

import pytest
from pydantic import ValidationError

from masbench.sft_pilot.bootstrap_authority import (
    AUTHORITY_KEY_ROLES,
    REQUIRED_AUTHORITY_CODE_SOURCES,
    BootstrapAuthorityBundle,
    PilotAuthorityKeyCommitmentV1,
    PilotBootstrapAuthorityManifestV1,
    PilotDatasetReleaseEntryV1,
    PilotDatasetReleaseManifestV1,
    PilotDatasetSplitEntryV1,
    PilotDatasetSplitManifestV1,
    PilotSourceAuthorityManifestV1,
    VerifiedTrainSourceCapability,
    authority_key_commitment,
    authority_root_commitment,
    issue_source_authority,
    load_bootstrap_authority,
    load_train_catalog,
    verify_source_authority_manifest,
)
from masbench.sft_pilot.manifests import PilotCodeSourceV1, published_manifest_bytes
from masbench.sft_pilot.schema import canonical_sha256


FIXED_COMMIT = "8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@dataclass
class AuthorityFixture:
    root: Path
    manifest_path: Path
    release_path: Path
    split_path: Path
    manifest: PilotBootstrapAuthorityManifestV1
    release: PilotDatasetReleaseManifestV1
    split_manifest: PilotDatasetSplitManifestV1
    keys: dict[str, bytes]
    code_paths: dict[str, Path]

    def load(self, **overrides: object) -> BootstrapAuthorityBundle:
        values: dict[str, object] = {
            "expected_manifest_sha256": self.manifest.digest,
            "expected_fixed_git_commit": FIXED_COMMIT,
            "authority_root": self.root,
            "code_source_paths": self.code_paths,
            "key_provider": lambda role: self.keys[role],
        }
        values.update(overrides)
        return load_bootstrap_authority(self.manifest_path, **values)  # type: ignore[arg-type]


def make_authority_fixture(
    tmp_path: Path,
    *,
    label: str = "one",
    release_case_ids: tuple[str, ...] = ("case-a", "case-b"),
    split_case_ids: tuple[str, ...] | None = None,
    split_values: tuple[str, ...] | None = None,
    authority_kind: str = "host_pinned",
) -> AuthorityFixture:
    base = tmp_path / label
    base.mkdir()
    root = base / "authority-root"
    code_dir = base / "code"
    code_dir.mkdir()
    code_paths: dict[str, Path] = {}
    code_sources: list[PilotCodeSourceV1] = []
    for source_id in sorted(REQUIRED_AUTHORITY_CODE_SOURCES):
        path = code_dir / f"{source_id}.py"
        payload = f"# pinned {label} {source_id}\n".encode("ascii")
        path.write_bytes(payload)
        code_paths[source_id] = path
        code_sources.append(
            PilotCodeSourceV1(
                source_id=source_id,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )

    keys = {
        role: hashlib.sha256(f"{label}:{role}".encode("ascii")).digest()
        for role in AUTHORITY_KEY_ROLES
    }
    release = PilotDatasetReleaseManifestV1(
        dataset_release_id=f"release-{label}",
        entries=tuple(
            PilotDatasetReleaseEntryV1(
                case_id=case_id,
                unit_commitment=f"unit-{case_id}",
                input_commitment_sha256=_sha(f"input:{label}:{case_id}"),
            )
            for case_id in release_case_ids
        ),
    )
    actual_split_ids = release_case_ids if split_case_ids is None else split_case_ids
    actual_splits = (
        tuple("TRAIN_UPDATE" for _ in actual_split_ids)
        if split_values is None
        else split_values
    )
    split_manifest = PilotDatasetSplitManifestV1(
        dataset_release_id=f"release-{label}",
        entries=tuple(
            PilotDatasetSplitEntryV1(case_id=case_id, split=split)  # type: ignore[arg-type]
            for case_id, split in zip(actual_split_ids, actual_splits, strict=True)
        ),
    )
    release_path = base / "release.json"
    split_path = base / "split.json"
    release_path.write_bytes(published_manifest_bytes(release))
    split_path.write_bytes(published_manifest_bytes(split_manifest))
    manifest = PilotBootstrapAuthorityManifestV1(
        authority_kind=authority_kind,  # type: ignore[arg-type]
        bootstrap_id=f"bootstrap-{label}",
        fixed_git_commit=FIXED_COMMIT,
        dataset_release_manifest_sha256=release.digest,
        dataset_split_manifest_sha256=split_manifest.digest,
        train_loader_policy_sha256=_sha(f"loader-policy:{label}"),
        namespace_template_sha256=_sha(f"namespace:{label}"),
        anchor_freeze_dir_commitment_sha256=authority_root_commitment(root),
        authority_code_sources=tuple(code_sources),
        authority_key_commitments=tuple(
            PilotAuthorityKeyCommitmentV1(
                role=role,  # type: ignore[arg-type]
                key_commitment_sha256=authority_key_commitment(
                    role=role, key=keys[role]
                ),
            )
            for role in AUTHORITY_KEY_ROLES
        ),
    )
    manifest_path = base / "bootstrap.json"
    manifest_path.write_bytes(published_manifest_bytes(manifest))
    return AuthorityFixture(
        root=root,
        manifest_path=manifest_path,
        release_path=release_path,
        split_path=split_path,
        manifest=manifest,
        release=release,
        split_manifest=split_manifest,
        keys=keys,
        code_paths=code_paths,
    )


def mint_source(fixture: AuthorityFixture):
    authority = fixture.load()
    snapshot = load_train_catalog(
        authority,
        dataset_release_manifest_path=fixture.release_path,
        dataset_split_manifest_path=fixture.split_path,
    )
    return authority, snapshot, issue_source_authority(authority, snapshot)


def test_real_source_authority_is_closed_train_only_and_opaque(tmp_path: Path) -> None:
    fixture = make_authority_fixture(tmp_path)
    authority, snapshot, source = mint_source(fixture)

    assert source.manifest.split == "TRAIN_UPDATE"
    assert source.manifest.train_case_count == 2
    assert source.manifest.train_catalog_manifest_sha256 == (
        source.train_catalog_manifest.digest
    )
    assert source.manifest.source_policy_sha256 == (
        authority.manifest.train_loader_policy_sha256
    )
    assert source.manifest.dataset_release_manifest_sha256 == fixture.release.digest
    assert source.manifest.dataset_split_manifest_sha256 == fixture.split_manifest.digest
    assert tuple(item.split for item in source.train_catalog_manifest.entries) == (
        "TRAIN_UPDATE",
        "TRAIN_UPDATE",
    )
    verify_source_authority_manifest(
        authority=authority,
        manifest=source.manifest,
        train_catalog=source.train_catalog_manifest,
    )

    assert tuple(inspect.signature(issue_source_authority).parameters) == (
        "authority",
        "verified_train_snapshot",
    )
    assert "split" not in inspect.signature(issue_source_authority).parameters
    assert "case" not in " ".join(inspect.signature(issue_source_authority).parameters)
    assert not hasattr(authority, "__dict__")
    assert bytes(fixture.keys["source_manifest_signer"]).hex() not in repr(authority)
    for capability in (authority, snapshot, source):
        with pytest.raises(TypeError):
            pickle.dumps(capability)
    with pytest.raises(TypeError):
        VerifiedTrainSourceCapability(
            _mint_token=object(),
            mint_identity=object(),
            manifest=source.manifest,
            catalog=source.train_catalog_manifest,
        )

    public = (
        published_manifest_bytes(fixture.manifest)
        + published_manifest_bytes(source.manifest)
        + published_manifest_bytes(source.train_catalog_manifest)
    ).lower()
    for forbidden in (
        b"final_val",
        b"expected_output",
        b"ground_truth",
        b"private_prompt",
        b"raw_response",
    ):
        assert forbidden not in public


def test_loader_rejects_final_val_unknown_and_missing_members(tmp_path: Path) -> None:
    final_fixture = make_authority_fixture(
        tmp_path,
        label="final",
        split_values=("TRAIN_UPDATE", "FINAL_VAL"),
    )
    final_authority = final_fixture.load()
    with pytest.raises(ValueError, match="rejects FINAL_VAL"):
        load_train_catalog(
            final_authority,
            dataset_release_manifest_path=final_fixture.release_path,
            dataset_split_manifest_path=final_fixture.split_path,
        )

    missing_fixture = make_authority_fixture(
        tmp_path,
        label="missing",
        split_case_ids=("case-a",),
    )
    missing_authority = missing_fixture.load()
    with pytest.raises(ValueError, match="does not close"):
        load_train_catalog(
            missing_authority,
            dataset_release_manifest_path=missing_fixture.release_path,
            dataset_split_manifest_path=missing_fixture.split_path,
        )

    unknown_fixture = make_authority_fixture(
        tmp_path,
        label="unknown",
        split_case_ids=("case-a", "case-z"),
    )
    unknown_authority = unknown_fixture.load()
    with pytest.raises(ValueError, match="does not close"):
        load_train_catalog(
            unknown_authority,
            dataset_release_manifest_path=unknown_fixture.release_path,
            dataset_split_manifest_path=unknown_fixture.split_path,
        )


def test_split_schema_rejects_duplicate_and_unknown_split() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        PilotDatasetSplitManifestV1(
            dataset_release_id="release-one",
            entries=(
                PilotDatasetSplitEntryV1(case_id="case-a", split="TRAIN_UPDATE"),
                PilotDatasetSplitEntryV1(case_id="case-a", split="TRAIN_UPDATE"),
            ),
        )
    with pytest.raises(ValidationError):
        PilotDatasetSplitEntryV1(case_id="case-a", split="PUBLIC")  # type: ignore[arg-type]


def test_wrong_release_split_key_code_and_commit_fail_closed(tmp_path: Path) -> None:
    fixture = make_authority_fixture(tmp_path)

    with pytest.raises(ValueError, match="Git commit"):
        fixture.load(expected_fixed_git_commit="1" * 40)

    wrong_keys = dict(fixture.keys)
    wrong_keys["source_manifest_signer"] = b"x" * 32
    with pytest.raises(ValueError, match="key commitment mismatch"):
        fixture.load(key_provider=lambda role: wrong_keys[role])

    pinned_path = fixture.code_paths["train_catalog_loader"]
    pinned_path.write_bytes(b"# substituted loader\n")
    with pytest.raises(ValueError, match="code pin mismatch"):
        fixture.load()

    # Restore code so the dataset-pin checks reach their intended boundary.
    pinned_path.write_bytes(b"# pinned one train_catalog_loader\n")
    authority = fixture.load()
    fixture.release_path.write_bytes(
        published_manifest_bytes(
            fixture.release.model_copy(update={"dataset_release_id": "release-other"})
        )
    )
    with pytest.raises(ValueError, match="expected digest"):
        load_train_catalog(
            authority,
            dataset_release_manifest_path=fixture.release_path,
            dataset_split_manifest_path=fixture.split_path,
        )

    fixture2 = make_authority_fixture(tmp_path, label="wrong-split")
    authority2 = fixture2.load()
    fixture2.split_path.write_bytes(
        published_manifest_bytes(
            fixture2.split_manifest.model_copy(
                update={"dataset_release_id": "release-substituted"}
            )
        )
    )
    with pytest.raises(ValueError, match="expected digest"):
        load_train_catalog(
            authority2,
            dataset_release_manifest_path=fixture2.release_path,
            dataset_split_manifest_path=fixture2.split_path,
        )


def test_synthetic_authority_and_cross_authority_capability_are_rejected(
    tmp_path: Path,
) -> None:
    synthetic = make_authority_fixture(
        tmp_path, label="synthetic", authority_kind="synthetic_fixture"
    )
    with pytest.raises(ValueError, match="rejects synthetic"):
        synthetic.load()

    first = make_authority_fixture(tmp_path, label="first")
    second = make_authority_fixture(tmp_path, label="second")
    first_authority = first.load()
    second_authority = second.load()
    first_snapshot = load_train_catalog(
        first_authority,
        dataset_release_manifest_path=first.release_path,
        dataset_split_manifest_path=first.split_path,
    )
    with pytest.raises(ValueError, match="different bootstrap authority"):
        issue_source_authority(second_authority, first_snapshot)


def test_hand_constructed_source_manifest_cannot_mint_or_verify(tmp_path: Path) -> None:
    fixture = make_authority_fixture(tmp_path)
    authority, _, source = mint_source(fixture)
    forged = PilotSourceAuthorityManifestV1.model_validate(
        {
            **source.manifest.model_dump(mode="python"),
            "train_catalog_manifest_sha256": _sha("forged-test-answer"),
            "attestation_sha256": _sha("self-consistent-looking-signature"),
        }
    )
    with pytest.raises(ValueError, match="binding mismatch"):
        verify_source_authority_manifest(
            authority=authority,
            manifest=forged,
            train_catalog=source.train_catalog_manifest,
        )
    with pytest.raises(TypeError):
        VerifiedTrainSourceCapability(
            _mint_token=object(),
            mint_identity=object(),
            manifest=forged,
            catalog=source.train_catalog_manifest,
        )


def test_bootstrap_manifest_requires_complete_canonical_key_and_code_pins(
    tmp_path: Path,
) -> None:
    fixture = make_authority_fixture(tmp_path)
    values = fixture.manifest.model_dump(mode="python")
    values["authority_key_commitments"] = tuple(
        reversed(fixture.manifest.authority_key_commitments)
    )
    with pytest.raises(ValidationError, match="complete, unique, and canonical"):
        PilotBootstrapAuthorityManifestV1.model_validate(values)

    values = fixture.manifest.model_dump(mode="python")
    values["authority_code_sources"] = tuple(
        item
        for item in fixture.manifest.authority_code_sources
        if item.source_id != "anchor_native_recount"
    )
    with pytest.raises(ValidationError, match="incomplete"):
        PilotBootstrapAuthorityManifestV1.model_validate(values)

    assert fixture.manifest.digest == canonical_sha256(fixture.manifest)
