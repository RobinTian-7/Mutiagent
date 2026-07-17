from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
from pathlib import Path
import pickle

import pytest
from pydantic import ValidationError

from masbench.sft_pilot.manifests import PilotCodeSourceV1, published_manifest_bytes
from masbench.sft_pilot.runtime_authority import (
    REQUIRED_RUNTIME_CODE_SOURCES,
    RUNTIME_AUTHORITY_ROLES,
    RUNTIME_ROLE_DOMAINS,
    PilotRuntimeAuthorityManifestV1,
    PilotRuntimeRoleCommitmentV1,
    RuntimeAuthorityBundle,
    RuntimeRoleCapability,
    issue_runtime_role_capabilities,
    load_runtime_authority,
    runtime_authority_key_commitment,
    runtime_authority_root_commitment,
)


FIXED_COMMIT = "8725c59c9f6cbc2bb3b17ea2b041b07bc3f7e61a"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@dataclass
class RuntimeFixture:
    root: Path
    manifest_path: Path
    manifest: PilotRuntimeAuthorityManifestV1
    keys: dict[str, bytes]
    code_paths: dict[str, Path]

    def load(self, **overrides: object) -> RuntimeAuthorityBundle:
        values: dict[str, object] = {
            "expected_manifest_sha256": self.manifest.digest,
            "expected_fixed_git_commit": FIXED_COMMIT,
            "authority_root": self.root,
            "code_source_paths": self.code_paths,
            "key_provider": lambda role: self.keys[role],
        }
        values.update(overrides)
        return load_runtime_authority(self.manifest_path, **values)  # type: ignore[arg-type]


def make_runtime_fixture(
    tmp_path: Path,
    *,
    label: str = "one",
    authority_kind: str = "host_pinned",
) -> RuntimeFixture:
    base = tmp_path / label
    base.mkdir()
    root = base / "runtime-state"
    code_dir = base / "code"
    code_dir.mkdir()
    code_paths: dict[str, Path] = {}
    code_sources: list[PilotCodeSourceV1] = []
    for source_id in sorted(REQUIRED_RUNTIME_CODE_SOURCES):
        payload = f"# pinned {label} {source_id}\n".encode("ascii")
        path = code_dir / f"{source_id}.py"
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
        for role in RUNTIME_AUTHORITY_ROLES
    }
    manifest = PilotRuntimeAuthorityManifestV1(
        authority_kind=authority_kind,  # type: ignore[arg-type]
        runtime_authority_id=f"runtime-{label}",
        fixed_git_commit=FIXED_COMMIT,
        bootstrap_authority_manifest_sha256=_sha(f"bootstrap:{label}"),
        source_authority_manifest_sha256=_sha(f"source:{label}"),
        runner_manifest_sha256=_sha(f"runner:{label}"),
        execution_schedule_sha256=_sha(f"schedule:{label}"),
        method_policy_sha256=_sha(f"policy:{label}"),
        authority_root_commitment_sha256=runtime_authority_root_commitment(root),
        authority_code_sources=tuple(code_sources),
        role_commitments=tuple(
            PilotRuntimeRoleCommitmentV1(
                role=role,  # type: ignore[arg-type]
                allowed_domains=RUNTIME_ROLE_DOMAINS[role],
                key_commitment_sha256=runtime_authority_key_commitment(
                    role=role, key=keys[role]
                ),
            )
            for role in RUNTIME_AUTHORITY_ROLES
        ),
    )
    manifest_path = base / "runtime-authority.json"
    manifest_path.write_bytes(published_manifest_bytes(manifest))
    return RuntimeFixture(
        root=root,
        manifest_path=manifest_path,
        manifest=manifest,
        keys=keys,
        code_paths=code_paths,
    )


def test_runtime_authority_loads_exact_complete_role_set(tmp_path: Path) -> None:
    fixture = make_runtime_fixture(tmp_path)
    authority = fixture.load()
    roles = issue_runtime_role_capabilities(authority)

    assert authority.manifest_sha256 == fixture.manifest.digest
    assert roles.manifest_sha256 == fixture.manifest.digest
    assert tuple(getattr(roles, name).role for name in RUNTIME_AUTHORITY_ROLES) == (
        RUNTIME_AUTHORITY_ROLES
    )
    for role in RUNTIME_AUTHORITY_ROLES:
        capability = getattr(roles, role)
        assert capability.key_commitment_sha256 == next(
            item.key_commitment_sha256
            for item in fixture.manifest.role_commitments
            if item.role == role
        )
        assert fixture.keys[role].hex() not in repr(capability)
        with pytest.raises(TypeError):
            pickle.dumps(capability)
    with pytest.raises(TypeError):
        pickle.dumps(authority)
    with pytest.raises(TypeError):
        pickle.dumps(roles)


def test_roles_are_domain_separated_and_no_partial_issuer_exists(
    tmp_path: Path,
) -> None:
    fixture = make_runtime_fixture(tmp_path)
    roles = issue_runtime_role_capabilities(fixture.load())
    value = {"execution_root_sha256": _sha("execution")}
    signature = roles.exact_phase_engine._sign(
        domain="sft-exact-phase-runtime-terminal-v1", value=value
    )
    assert roles.exact_phase_engine._verify(
        domain="sft-exact-phase-runtime-terminal-v1",
        value=value,
        signature=signature,
    )
    with pytest.raises(ValueError, match="outside its frozen domains"):
        roles.train_scorer._sign(
            domain="sft-exact-phase-runtime-terminal-v1", value=value
        )
    assert tuple(inspect.signature(issue_runtime_role_capabilities).parameters) == (
        "authority",
    )
    assert "key" not in inspect.signature(issue_runtime_role_capabilities).parameters
    assert "role" not in inspect.signature(issue_runtime_role_capabilities).parameters


@pytest.mark.parametrize(
    "override,match",
    (
        ({"expected_fixed_git_commit": "f" * 40}, "Git commit"),
        ({"authority_root": Path("/tmp/wrong-runtime-root")}, "state root"),
    ),
)
def test_runtime_authority_rejects_external_pin_substitution(
    tmp_path: Path,
    override: dict[str, object],
    match: str,
) -> None:
    fixture = make_runtime_fixture(tmp_path)
    with pytest.raises(ValueError, match=match):
        fixture.load(**override)


def test_runtime_authority_rejects_wrong_key_code_and_missing_material(
    tmp_path: Path,
) -> None:
    fixture = make_runtime_fixture(tmp_path)
    wrong_keys = dict(fixture.keys)
    wrong_keys["train_scorer"] = hashlib.sha256(b"wrong-scorer").digest()
    with pytest.raises(ValueError, match="key commitment mismatch: train_scorer"):
        fixture.load(key_provider=lambda role: wrong_keys[role])

    scorer_path = fixture.code_paths["train_scalar_evaluator"]
    scorer_path.write_bytes(b"# substituted evaluator\n")
    with pytest.raises(ValueError, match="code pin mismatch: train_scalar_evaluator"):
        fixture.load()

    missing = dict(fixture.code_paths)
    missing.pop("single_use_pair_consumer")
    with pytest.raises(ValueError, match="code path set"):
        fixture.load(code_source_paths=missing)


def test_real_loader_rejects_synthetic_fixture_manifest(tmp_path: Path) -> None:
    fixture = make_runtime_fixture(
        tmp_path, label="synthetic", authority_kind="synthetic_fixture"
    )
    with pytest.raises(ValueError, match="rejects synthetic"):
        fixture.load()


def test_manifest_requires_exact_roles_domains_and_code_pins(tmp_path: Path) -> None:
    fixture = make_runtime_fixture(tmp_path)
    values = fixture.manifest.model_dump(mode="python")

    with pytest.raises(ValidationError, match="runtime roles must be complete"):
        PilotRuntimeAuthorityManifestV1.model_validate(
            {**values, "role_commitments": values["role_commitments"][:-1]}
        )

    changed_domains = list(values["role_commitments"])
    changed_domains[0] = {
        **changed_domains[0],
        "allowed_domains": ("sft-train-outcome-v2",),
    }
    with pytest.raises(ValidationError, match="closed role law"):
        PilotRuntimeAuthorityManifestV1.model_validate(
            {**values, "role_commitments": tuple(changed_domains)}
        )

    with pytest.raises(ValidationError, match="code pins are incomplete"):
        PilotRuntimeAuthorityManifestV1.model_validate(
            {**values, "authority_code_sources": values["authority_code_sources"][:-1]}
        )


def test_capability_constructors_and_key_commitments_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = make_runtime_fixture(tmp_path)
    with pytest.raises(TypeError, match="no public constructor"):
        RuntimeAuthorityBundle(
            _mint_token=object(), manifest=fixture.manifest, keys=fixture.keys
        )
    with pytest.raises(TypeError, match="no public constructor"):
        RuntimeRoleCapability(
            _mint_token=object(),
            authority_identity=object(),
            manifest_sha256=fixture.manifest.digest,
            role="train_scorer",
            key=fixture.keys["train_scorer"],
        )
    with pytest.raises(ValueError, match="unknown runtime authority role"):
        runtime_authority_key_commitment(role="caller", key=b"x" * 32)
    with pytest.raises(ValueError, match="at least 32 bytes"):
        runtime_authority_key_commitment(role="train_scorer", key=b"short")


def test_public_manifest_contains_only_commitments(tmp_path: Path) -> None:
    fixture = make_runtime_fixture(tmp_path)
    payload = published_manifest_bytes(fixture.manifest).lower()
    for role, key in fixture.keys.items():
        assert key.hex().encode("ascii") not in payload, role
    for forbidden in (
        b"expected_output",
        b"ground_truth",
        b"private_prompt",
        b"raw_response",
        b"test_case",
    ):
        assert forbidden not in payload
