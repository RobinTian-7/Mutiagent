"""Orchestration entry for the ``phase_v5_executable_sft`` profile.

v5 is the only SFT profile that may ever spend scientific model calls, so this
module is fail-closed by construction: every frozen input (protocol,
experiment seal, both authority manifests) must exist as a stable non-symlink
regular file before anything else happens, the store must already be
provisioned by the external provision command, and any gap raises before a
state directory, result directory, or model call can be created.  The module
never implements Bank/Registry/store internals — it only sequences their
authorities.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from masbench.core.config import RunConfig
from masbench.sft_phase_pilot import (
    _decode_master_key,
    _derive_key,
    _load_frozen_protocol,
    _validate_v4_protocol,
)
from masbench.sft_pilot.schema import PilotProtocolV1
from masbench.sft_pilot.store import DATABASE_FILENAME

V5_PROFILE = "phase_v5_executable_sft"
_MAX_FROZEN_INPUT_BYTES = 8 * 1024 * 1024

# v5 key-derivation law.  Domains are distinct from every v3/v4 domain so a
# v5 experiment can never silently reopen (or be reopened by) an older
# profile's authenticated state.
V5_STORE_KEY_DOMAIN = b"pilot-store-v5"
V5_PHASE_KEY_DOMAIN = b"phase-registry-v5"
V5_FACTOR_KEY_DOMAIN = b"factor-bank-v5"
V5_SOURCE_AUTHORITY_KEY_DOMAIN = b"source-authority-v5"


def derive_v5_component_keys(master: bytes) -> dict[str, bytes]:
    """Derive the four v5 state keys from the host master key."""

    return {
        "store": _derive_key(master, V5_STORE_KEY_DOMAIN),
        "phase_registry": _derive_key(master, V5_PHASE_KEY_DOMAIN),
        "factor_bank": _derive_key(master, V5_FACTOR_KEY_DOMAIN),
        "source_authority": _derive_key(master, V5_SOURCE_AUTHORITY_KEY_DOMAIN),
    }


def derive_v5_runtime_role_key(master: bytes, role: str) -> bytes:
    """Derive one runtime authority role key under a role-separated domain."""

    return _derive_key(master, b"runtime-role-v5:" + role.encode("ascii"))


def derive_v5_bootstrap_role_key(master: bytes, role: str) -> bytes:
    """Derive one bootstrap authority role key under a role-separated domain."""

    return _derive_key(master, b"bootstrap-role-v5:" + role.encode("ascii"))


_ANCHOR_BRANCH_PRODUCER_EPOCH = "sft-anchor-host:v2"


class V5BranchReceiptAuthority:
    """In-process capability gating registry branch receipts.

    The registry can only register a branch receipt (and therefore
    materialize a generated target) for either the frozen structural-anchor
    receipt or an action this host explicitly authorized after the Bank
    created it under the factor authority's attestation.  Nothing ambient —
    no action registration, no materialization.
    """

    def __init__(self, *, anchor_source_manifest_sha256: str) -> None:
        self._anchor_source_manifest_sha256 = anchor_source_manifest_sha256
        self._authorized: dict[str, tuple[str, str, str, str]] = {}

    def authorize_action(self, action: Any) -> None:
        """Admit exactly one prepared/executing Bank action for reconcile."""

        if action.state not in {"prepared", "executing"}:
            raise ValueError(
                "branch authority admits only nonterminal proposal actions"
            )
        self._authorized[str(action.action_id)] = (
            str(action.action_intent_sha256),
            str(action.branch),
            str(action.producer_epoch),
            str(action.attestation_sha256),
        )

    def __call__(self, body: Any) -> bool:
        try:
            if body.producer_epoch == _ANCHOR_BRANCH_PRODUCER_EPOCH:
                return bool(
                    body.action_transaction_id is None
                    and body.branch == "mutate"
                    and body.source_manifest_sha256
                    == self._anchor_source_manifest_sha256
                )
            expected = self._authorized.get(str(body.action_transaction_id))
            if expected is None:
                return False
            intent, branch, producer_epoch, attestation = expected
            return bool(
                body.action_intent_sha256 == intent
                and body.branch == branch
                and body.producer_epoch == producer_epoch
                and body.attestation_sha256 == attestation
            )
        except AttributeError:
            return False


def pending_repair_opportunities(bank: Any) -> tuple[Any, ...]:
    """Return the Bank-truth queue of open repair opportunities.

    The scheduler owns no hidden state: an opportunity is pending exactly
    when the Bank holds it, no proposal decision has consumed it, and its
    expiry sequence has not passed.  Order is the Bank's creation order.
    """

    state = bank.to_state()
    consumed = {item.repair_opportunity_id for item in state.proposal_decisions}
    return tuple(
        item
        for item in state.repair_opportunities
        if item.opportunity_id not in consumed
        and item.expiry_seq > state.event_seq
    )


def branch_assignment_counts(bank: Any) -> dict[str, int]:
    """Bank-truth reuse/mutate/fresh exposure counters (no caller cache)."""

    counts = {"reuse": 0, "mutate": 0, "fresh": 0}
    for assignment in bank.to_state().branch_assignments:
        counts[assignment.branch] += 1
    return counts


def v5_factor_capabilities_factory(
    *,
    authority: Any,
    seal: Any,
):
    """Authority capabilities plus the sealed anchor's historical base receipt.

    The structural anchor's base snapshot was attested by the anchor builder
    (a different key role) before this experiment's factor authority existed.
    On every native reload the Bank re-verifies persisted receipts, so the
    verifier must accept exactly that one pinned historical receipt — and
    nothing else outside the authority's own signatures.
    """

    anchor = seal.structural_anchor

    def factory(registry: Any) -> dict[str, Any]:
        capabilities = authority.capabilities(registry)
        authority_base_verifier = capabilities["base_snapshot_verifier"]

        def base_snapshot_verifier(receipt: Any, state: Any) -> bool:
            if (
                receipt.receipt_id == anchor.base_receipt_id
                and receipt.composition_id == anchor.source_composition_id
                and receipt.namespace_digest == anchor.namespace_sha256
            ):
                return True
            return bool(authority_base_verifier(receipt, state))

        capabilities["base_snapshot_verifier"] = base_snapshot_verifier
        return capabilities

    return factory


def reserve_scheduled_execution(
    store: Any,
    *,
    schedule: Any,
    logical_arm: Any,
    logical_execution_key: str,
    action_id: str | None = None,
) -> Any:
    """Reserve one execution lease exactly as the frozen schedule row states."""

    from masbench.sft_pilot.schema import (
        PilotExecutionLeaseRequestV1,
        canonical_sha256,
    )

    entry = schedule.entry_for(logical_arm)
    request = PilotExecutionLeaseRequestV1(
        logical_execution_key=logical_execution_key,
        operation_kind=logical_arm.operation_kind,
        request_sha256=entry.execution_request_sha256,
        namespace_sha256=store.protocol.namespace.digest,
        split=logical_arm.split,
        unit_commitment=logical_arm.unit_commitment,
        action_id=action_id,
        call_slots_reserved=len(entry.calls),
        input_tokens_reserved=entry.input_tokens_reserved,
        output_tokens_reserved=entry.output_tokens_reserved,
    )
    payload = {
        "domain": "sft-pilot-reserve-scheduled-execution-v1",
        "logical_execution_key": logical_execution_key,
        "request_sha256": entry.execution_request_sha256,
    }
    return store.reserve_execution(
        request,
        logical_arm=logical_arm,
        operation_id=f"op-reserve-exec:{canonical_sha256(payload)[:24]}",
        operation_request_sha256=canonical_sha256(payload),
    )


def all_scientific_state_roots(*, store: Any, loaded: Any) -> dict[str, str]:
    """Every scientific-state root a frozen TEST run must leave untouched."""

    from masbench.sft_pilot.schema import canonical_sha256

    bundle = store.latest_component_bundle()
    bank_state = loaded.bank.to_state()
    return {
        "store_commit_head_sha256": store.commit_head_sha256,
        "store_budget_ledger_root_sha256": store.budget_ledger_root_sha256,
        "store_operation_ledger_root_sha256": (
            store.operation_ledger_root_sha256
        ),
        "component_bundle_sha256": bundle.metadata.bundle_sha256,
        "component_bundle_generation": str(bundle.metadata.generation),
        "factor_bank_state_sha256": loaded.bank.scientific_state_sha256,
        "phase_registry_state_sha256": loaded.registry.scientific_state_sha256,
        "deployment_heads_sha256": canonical_sha256(
            tuple(
                sorted(
                    bank_state.deployment_heads,
                    key=lambda i: i.deployment_slot_id,
                )
            )
        ),
        "proposal_counters_sha256": canonical_sha256(
            bank_state.proposal_lifetime_counters
        ),
        "failures_sha256": canonical_sha256(bank_state.failures),
    }


def run_frozen_test_readonly(
    *,
    store: Any,
    loaded: Any,
    seal: Any,
    protocol: Any,
    test_manifest: Any,
    ledger: Any,
    test_executor: Any,
) -> Any:
    """Run the sealed TEST manifest with zero writer capability.

    The executor receives only the frozen manifest and a read-only deployment
    view (Bank snapshot facade plus safe head identifiers) and must return
    ``(report_sha256, metrics)`` where metrics are safe scalars.  All
    scientific roots are captured before and after; any difference aborts
    without writing a result row.  TEST failures never enter failure memory —
    there is no writer to enter them with.
    """

    from masbench.sft_pilot.result_ledger import PilotTestManifestV1

    manifest = PilotTestManifestV1.model_validate(
        test_manifest.model_dump(mode="python")
    )
    if manifest.digest != seal.test_manifest_sha256:
        raise ValueError("TEST manifest differs from its sealed commitment")
    before = all_scientific_state_roots(store=store, loaded=loaded)
    snapshot = loaded.bank.read_only_snapshot()
    bank_state = loaded.bank.to_state()
    deployment_view = {
        "heads": tuple(
            {
                "slot_id": head.deployment_slot_id,
                "active_snapshot_id": head.active_snapshot_id,
                "active_composition_id": head.active_composition_id,
                "generation": head.generation,
            }
            for head in sorted(
                bank_state.deployment_heads,
                key=lambda item: item.deployment_slot_id,
            )
        ),
    }
    report_sha256, metrics = test_executor(
        manifest, snapshot, deployment_view
    )
    after = all_scientific_state_roots(store=store, loaded=loaded)
    if before != after:
        raise RuntimeError(
            "frozen TEST run mutated scientific state; result withheld"
        )
    return ledger.append(
        row_kind="test_report",
        experiment_seal_sha256=seal.digest,
        protocol_sha256=protocol.digest,
        report_sha256=report_sha256,
        metrics=metrics,
    )


def skip_settled_probe_blocks(
    store: Any,
    *,
    schedule: Any,
    ordinals: tuple[int, ...],
    action_id: str | None = None,
    reason: str = "probe_plan_settled_before_reserve_units",
) -> tuple[str, ...]:
    """Honestly consume unused probe blocks after early plan settlement.

    Each skipped block is reserved exactly as frozen and immediately
    terminalized as ``failed_before_start`` with a receipted reason, keeping
    the linear physical order law intact without ever starting a call.
    """

    from masbench.sft_pilot.schema import canonical_sha256

    skipped: list[str] = []
    for entry in sorted(
        schedule.entries, key=lambda item: item.physical_block_ordinal
    ):
        arm = entry.logical_arm
        if arm.operation_kind not in {"source_probe", "target_probe"}:
            continue
        if arm.execution_ordinal not in ordinals:
            continue
        key = f"skipped-probe-{arm.execution_ordinal}-{arm.pair_arm}"
        reserve_scheduled_execution(
            store,
            schedule=schedule,
            logical_arm=arm,
            logical_execution_key=key,
            action_id=action_id,
        )
        payload = {
            "domain": "sft-pilot-abandon-execution-v1",
            "logical_execution_key": key,
            "reason": reason,
        }
        store.abandon_reserved_execution(
            key,
            operation_id=f"op-abandon:{canonical_sha256(payload)[:24]}",
            operation_request_sha256=canonical_sha256(payload),
            reason=reason,
        )
        skipped.append(key)
    return tuple(skipped)


def execute_metered_generation_call(
    *,
    store: Any,
    schedule: Any,
    logical_arm: Any,
    logical_execution_key: str,
    rendered: Any,
    transport: Any,
    expected_component_recovery_root_sha256: str | None = None,
) -> Any:
    """Spend the single frozen generation call and return the LLM response.

    The store binds the frozen request envelope at reservation; the exact
    prompt-byte commitment travels in the durable operation payloads.  Any
    transport failure surfaces as the metered client's indeterminate error —
    it is never retried here.
    """

    from masbench.sft_pilot.llm_meter import (
        PilotCallBudget,
        PilotMeteredLLMClient,
    )

    entry = schedule.entry_for(logical_arm)
    if len(entry.calls) != 1:
        raise ValueError("generation execution authorizes exactly one call")
    scheduled_call = entry.calls[0]
    if scheduled_call.request_envelope_sha256 != rendered.request_envelope_sha256:
        raise ValueError(
            "rendered request envelope differs from the frozen schedule"
        )
    if scheduled_call.prompt_template_sha256 != rendered.prompt_template_sha256:
        raise ValueError(
            "rendered prompt template differs from the frozen schedule"
        )
    client = PilotMeteredLLMClient(
        store=store,
        transport=transport,
        logical_execution_key=logical_execution_key,
        call_budgets=(
            PilotCallBudget(
                input_tokens=scheduled_call.input_tokens_reserved,
                output_tokens=scheduled_call.output_tokens_reserved,
            ),
        ),
        scheduled_request_envelopes=(scheduled_call.request_envelope_sha256,),
        expected_component_recovery_root_sha256=(
            expected_component_recovery_root_sha256
        ),
    )
    response = client.complete(
        rendered.prompt_text,
        store.protocol.model_name,
        temperature=store.protocol.temperature,
        json_mode=rendered.json_mode,
    )
    client.finalize_execution()
    return response


def _read_frozen_input(path_value: str | None, *, description: str) -> bytes:
    """Read one externally frozen input without following a symlink.

    The same physical law as the v4 protocol loader: absolute path, O_NOFOLLOW
    open, stable dev/ino between descriptor and lstat, bounded byte length.
    A replaceable symlink or FIFO must never become experiment authority.
    """

    if not path_value:
        raise ValueError(f"{description} requires a configured path")
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{description} requires an absolute path")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{description} cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError(
                f"{description} must be a stable non-symlink regular file"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(_MAX_FROZEN_INPUT_BYTES + 1)
    finally:
        os.close(fd)
    if not payload or len(payload) > _MAX_FROZEN_INPUT_BYTES:
        raise ValueError(f"{description} has an invalid byte length")
    return payload


def _validate_v5_protocol(
    protocol: PilotProtocolV1,
    cfg: RunConfig,
    *,
    agent_counts: list[int] | None,
) -> None:
    """Close the frozen protocol over the v5 run configuration.

    The namespace/model/budget closure law is shared with v4; v5 additionally
    demands the recoverable-execution surface: an exact component bundle,
    the checkpoint saga, and a store-derived execution schedule.
    """

    _validate_v4_protocol(protocol, cfg, agent_counts=agent_counts)
    missing = [
        name
        for name, enabled in (
            ("component_checkpoint_saga_required", protocol.component_checkpoint_saga_required),
            ("store_derived_schedule_required", protocol.store_derived_schedule_required),
        )
        if not enabled
    ]
    if missing:
        raise ValueError(
            "phase_v5 requires a recoverable protocol: " + ", ".join(missing)
        )


def run_phase_v5_executable_sft(
    cfg: RunConfig,
    *,
    agent_counts: list[int] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Fail-closed v5 entry: verify every authority before any effect."""

    if cfg.sft_profile != V5_PROFILE:
        raise ValueError(f"unsupported v5 dispatch for profile {cfg.sft_profile!r}")
    if workers != 1:
        raise ValueError(
            "phase_v5_executable_sft requires workers=1 for single-writer authority"
        )
    _decode_master_key()  # fail before touching any path

    # Physical closure of every externally frozen input, before semantics.
    _read_frozen_input(
        cfg.sft_protocol_path, description="frozen SFT protocol"
    )
    _read_frozen_input(
        cfg.sft_experiment_manifest_path,
        description="frozen SFT experiment manifest",
    )
    _read_frozen_input(
        cfg.sft_runtime_authority_path,
        description="frozen SFT runtime authority manifest",
    )
    _read_frozen_input(
        cfg.sft_bootstrap_authority_path,
        description="frozen SFT bootstrap authority manifest",
    )

    protocol = _load_frozen_protocol(cfg.sft_protocol_path)
    _validate_v5_protocol(protocol, cfg, agent_counts=agent_counts)

    # Paid-call protection: a real provider run additionally requires an
    # explicit external authorization marker.  Nothing in this module ever
    # constructs a provider client before this point, and the fake path
    # never needs the marker.
    if cfg.llm_provider == "openai" and (
        os.environ.get("MASBENCH_SFT_PAID_PILOT_AUTHORIZED")
        != "yes-i-authorize-paid-gpt-4o-mini-calls"
    ):
        raise RuntimeError(
            "PAID_CALLS_NOT_AUTHORIZED: a real phase_v5 pilot requires the "
            "MASBENCH_SFT_PAID_PILOT_AUTHORIZED marker plus a frozen budget "
            "and external human authorization"
        )

    # Seal closure: the experiment root must bind this exact protocol and
    # both frozen authority manifests before the store may even be opened.
    from masbench.sft_pilot.experiment import (
        load_experiment_seal,
        load_sealed_authority_manifests,
        validate_experiment_seal,
    )

    seal = load_experiment_seal(str(cfg.sft_experiment_manifest_path))
    runtime_authority, bootstrap_authority = load_sealed_authority_manifests(
        seal,
        runtime_authority_path=str(cfg.sft_runtime_authority_path),
        bootstrap_authority_path=str(cfg.sft_bootstrap_authority_path),
    )
    validate_experiment_seal(
        seal,
        runtime_authority=runtime_authority,
        bootstrap_authority=bootstrap_authority,
        protocol=protocol,
    )

    state_root = Path(str(cfg.sft_state_dir))
    database_path = state_root / DATABASE_FILENAME
    try:
        database_stat = os.lstat(database_path)
    except OSError as exc:
        raise RuntimeError(
            "phase_v5 requires a pre-provisioned experiment pilot store"
        ) from exc
    if not stat.S_ISREG(database_stat.st_mode):
        raise RuntimeError(
            "phase_v5 pilot database must be a non-symlink regular file"
        )

    raise RuntimeError(
        "phase_v5_executable_sft is fail-closed: the scientific execution "
        "loop is not authorized in this build"
    )


__all__ = ["V5_PROFILE", "run_phase_v5_executable_sft"]
