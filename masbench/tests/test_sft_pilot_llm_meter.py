from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from masbench.sft_pilot.llm_meter import (
    PILOT_CHAT_ENVELOPE_TOKEN_ALLOWANCE,
    PilotCallBoundaryError,
    PilotCallBudget,
    PilotCallIndeterminate,
    PilotCallReplayBlocked,
    PilotMeteredLLMClient,
    PilotTransportResult,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotCapacityPreflightV1,
    PilotExecutionLeaseRequestV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
)
from masbench.sft_pilot.store import SingleWriterPilotStore


KEY = b"sft-pilot-meter-test-key-32-bytes!!"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _logical_arm() -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id="pair-meter",
        pair_arm="control",
        case_commitment_sha256=_sha("case-meter"),
        unit_commitment="unit-meter",
        split="TRAIN_UPDATE",
        operation_kind="proposal_generation",
        execution_ordinal=0,
    )


def _protocol() -> PilotProtocolV1:
    namespace = ExecutionNamespace(
        task_family="synthetic",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=2,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="runner-v1",
        binder_version="phase-binder-v1",
        compiler_version="phase-compiler-v1",
    )
    return PilotProtocolV1(
        protocol_id="pilot-meter-1",
        method_arm="sft_unified",
        namespace=namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("catalog"),
            source_policy_sha256=_sha("source-policy"),
        ),
        source_authority_sha256=_sha("source-authority"),
        dataset_split_policy_sha256=_sha("split-policy"),
        candidate_pool_manifest_sha256=_sha("candidates"),
        runner_config_sha256=_sha("runner-config"),
        model_config_sha256=_sha("model-config"),
        pair_manifest_sha256=_sha("pairs"),
        genesis_state_sha256=_sha("genesis"),
        authorized_logical_arms=(_logical_arm(),),
        phase_budgets=tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm="sft_unified",
                executions=2,
                call_slots=4,
                input_tokens=12_288,
                output_tokens=4_096,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=4,
            max_execution_leases=4,
            max_call_receipts=8,
            max_call_slots_per_execution=2,
            max_input_tokens_per_call=3_072,
            max_output_tokens_per_call=1_024,
            max_active_db_bytes=8 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=2 * 1024 * 1024,
        ),
    )


def _open_reserved(tmp_path: Path) -> SingleWriterPilotStore:
    store = SingleWriterPilotStore.open(
        tmp_path / "pilot-state",
        protocol=_protocol(),
        hmac_key=KEY,
    )
    store.record_capacity_preflight(
        PilotCapacityPreflightV1(
            planned_scientific_commits=2,
            planned_execution_leases=2,
            planned_call_receipts=4,
            planned_max_calls_per_execution=2,
            planned_max_active_db_bytes=4 * 1024 * 1024,
            planned_archive_bytes=32 * 1024,
            planned_total_stored_scalar_bytes=1024 * 1024,
            planned_max_input_tokens_per_call=3_072,
            planned_max_output_tokens_per_call=1_024,
            quarantined_carriers_reserved=1,
            indeterminate_call_reserve=1,
        ),
        operation_id="op-preflight-meter",
        request_sha256=_sha("preflight-meter"),
    )
    store.reserve_execution(
        PilotExecutionLeaseRequestV1(
            logical_execution_key="execution-meter",
            operation_kind="proposal_generation",
            request_sha256=_sha("execution-request"),
            namespace_sha256=store.protocol.namespace.digest,
            split="TRAIN_UPDATE",
            unit_commitment="unit-meter",
            action_id="action-meter",
            call_slots_reserved=2,
            input_tokens_reserved=6_144,
            output_tokens_reserved=2_048,
        ),
        logical_arm=_logical_arm(),
        operation_id="op-reserve-execution-meter",
        operation_request_sha256=_sha("reserve-execution-meter"),
    )
    return store


class _Transport:
    def __init__(
        self,
        *,
        result: PilotTransportResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or PilotTransportResult(
            text='{"ok":true}',
            input_tokens=17,
            output_tokens=5,
            provider_usage_known=True,
        )
        self.error = error
        self.invocations = 0
        self.max_completion_tokens: list[int] = []

    def complete_bounded(
        self,
        prompt: str,
        *,
        model_name: str,
        temperature: float,
        json_mode: bool,
        max_completion_tokens: int,
    ) -> PilotTransportResult:
        self.invocations += 1
        self.max_completion_tokens.append(max_completion_tokens)
        if self.error is not None:
            raise self.error
        return self.result


def _client(store: SingleWriterPilotStore, transport: _Transport) -> PilotMeteredLLMClient:
    return PilotMeteredLLMClient(
        store=store,
        transport=transport,
        logical_execution_key="execution-meter",
        call_budgets=(
            PilotCallBudget(input_tokens=3_072, output_tokens=1_024),
            PilotCallBudget(input_tokens=3_072, output_tokens=1_024),
        ),
    )


def test_metered_call_persists_only_commitments_and_exact_usage(tmp_path: Path) -> None:
    prompt = "UNIQUE_PRIVATE_PROMPT_BYTES_NEVER_PERSIST"
    transport = _Transport()
    with _open_reserved(tmp_path) as store:
        response = _client(store, transport).complete(
            prompt,
            model_name="gpt-4o-mini",
            temperature=0.0,
        )
        assert response.text == '{"ok":true}'
        assert response.usage.prompt_tokens == 17
        assert response.usage.completion_tokens == 5
        assert transport.invocations == 1
        calls = store._connection.execute("SELECT * FROM call_receipt").fetchall()
        assert len(calls) == 1
        assert calls[0]["state"] == "completed"
        assert calls[0]["input_tokens_used"] == 17
        assert calls[0]["output_tokens_used"] == 5
        dump = "\n".join(store._connection.iterdump())
        assert prompt not in dump
        assert '{"ok":true}' not in dump


def test_transport_error_is_indeterminate_and_never_retried(tmp_path: Path) -> None:
    transport = _Transport(error=RuntimeError("transport failed"))
    with _open_reserved(tmp_path) as store:
        client = _client(store, transport)
        with pytest.raises(PilotCallIndeterminate):
            client.complete("prompt", model_name="gpt-4o-mini")
        assert transport.invocations == 1
        with pytest.raises(PilotCallReplayBlocked):
            client.complete("prompt", model_name="gpt-4o-mini")
        assert transport.invocations == 1
        state = store._connection.execute(
            "SELECT state FROM call_receipt"
        ).fetchone()[0]
        assert state == "indeterminate"


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (
            PilotTransportResult(
                text="{}",
                input_tokens=1,
                output_tokens=1,
                provider_usage_known=False,
            ),
            "missing usage",
        ),
        (
            PilotTransportResult(
                text="{}",
                input_tokens=3_073,
                output_tokens=1,
                provider_usage_known=True,
            ),
            "over input cap",
        ),
        (
            PilotTransportResult(
                text="{}",
                input_tokens=1,
                output_tokens=1_025,
                provider_usage_known=True,
            ),
            "over output cap",
        ),
    ],
)
def test_invalid_provider_accounting_becomes_indeterminate(
    tmp_path: Path,
    result: PilotTransportResult,
    reason: str,
) -> None:
    transport = _Transport(result=result)
    with _open_reserved(tmp_path) as store:
        with pytest.raises(PilotCallIndeterminate, match="durable completion"):
            _client(store, transport).complete("prompt", model_name="gpt-4o-mini")
        assert transport.invocations == 1, reason
        assert store._connection.execute(
            "SELECT state FROM call_receipt"
        ).fetchone()[0] == "indeterminate"


def test_wrong_model_or_temperature_fails_before_reservation(tmp_path: Path) -> None:
    transport = _Transport()
    with _open_reserved(tmp_path) as store:
        client = _client(store, transport)
        with pytest.raises(ValueError, match="model"):
            client.complete("prompt", model_name="gpt-4o")
        with pytest.raises(ValueError, match="temperature"):
            client.complete(
                "prompt",
                model_name="gpt-4o-mini",
                temperature=0.2,
            )
        assert transport.invocations == 0
        assert store._connection.execute(
            "SELECT COUNT(*) FROM call_receipt"
        ).fetchone()[0] == 0


def test_conservative_input_bound_rejects_before_transport(tmp_path: Path) -> None:
    transport = _Transport()
    with _open_reserved(tmp_path) as store:
        client = _client(store, transport)
        prompt = "x" * (3_072 - PILOT_CHAT_ENVELOPE_TOKEN_ALLOWANCE + 1)
        with pytest.raises(PilotCallBoundaryError, match="pre-transport"):
            client.complete(prompt, model_name="gpt-4o-mini")
        assert transport.invocations == 0
        assert store._connection.execute(
            "SELECT COUNT(*) FROM call_receipt"
        ).fetchone()[0] == 0


def test_provider_overage_is_retained_and_never_undercharged(tmp_path: Path) -> None:
    transport = _Transport(
        result=PilotTransportResult(
            text="{}",
            input_tokens=10_001,
            output_tokens=7,
            provider_usage_known=True,
        )
    )
    with _open_reserved(tmp_path) as store:
        with pytest.raises(PilotCallIndeterminate):
            _client(store, transport).complete("prompt", model_name="gpt-4o-mini")
        row = store._connection.execute(
            "SELECT * FROM call_receipt WHERE call_slot=0"
        ).fetchone()
        assert row["state"] == "indeterminate"
        assert row["provider_usage_known"] == 1
        assert row["input_tokens_used"] == 10_001
        assert row["output_tokens_used"] == 7
        assert row["conservative_charged_tokens"] == 10_008


def test_call_completion_cap_is_forwarded_exactly(tmp_path: Path) -> None:
    transport = _Transport()
    with _open_reserved(tmp_path) as store:
        _client(store, transport).complete("prompt", model_name="gpt-4o-mini")
    assert transport.max_completion_tokens == [1_024]


def test_dependent_calls_reserve_sequentially_then_finalize(tmp_path: Path) -> None:
    transport = _Transport()
    with _open_reserved(tmp_path) as store:
        client = _client(store, transport)
        client.complete("first prompt", model_name="gpt-4o-mini")
        client.complete("second prompt depends on first", model_name="gpt-4o-mini")
        client.finalize_execution()
        assert store.get_execution("execution-meter").state == "completed"
        states = store._connection.execute(
            "SELECT call_slot, state FROM call_receipt ORDER BY call_slot"
        ).fetchall()
        assert [(row[0], row[1]) for row in states] == [
            (0, "completed"),
            (1, "completed"),
        ]
    assert transport.invocations == 2


def test_reopen_terminalizes_completed_but_unfinished_execution(tmp_path: Path) -> None:
    transport = _Transport()
    store = _open_reserved(tmp_path)
    _client(store, transport).complete("first prompt", model_name="gpt-4o-mini")
    assert store.get_execution("execution-meter").state == "request_started"
    store.close()

    with SingleWriterPilotStore.open(
        tmp_path / "pilot-state",
        protocol=_protocol(),
        hmac_key=KEY,
    ) as reopened:
        assert reopened.recovered_indeterminate_count == 1
        assert reopened.get_execution("execution-meter").state == "indeterminate"
        completed_call = reopened._connection.execute(
            "SELECT state FROM call_receipt WHERE call_slot=0"
        ).fetchone()[0]
        assert completed_call == "completed"
