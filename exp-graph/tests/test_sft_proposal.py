from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.sft_proposal import (
    CandidateCounterWitnessV1,
    EdgeProposalPolicyV1,
    ExactFactorLocusV1,
    ExactProposalCellV1,
    LineageNicheV1,
    PortableBackgroundSignV1,
    PortableCandidateV1,
    ProposalCursorV1,
    ProposalCounterDeltaV1,
    ProposalHistoryEntryV1,
    ProposalReceiptV1,
    ProposalReplayError,
    ProposalRequestV1,
    SFTProposalInputV1,
    proposal_slate_fits_byte_bounds,
    proposal_counter_state_sha256,
    replay_validate_proposal_receipt,
    select_exact_edge_proposal,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace() -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_count",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=4,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="shadow-runtime-v2",
        binder_version="facts-phase-leaf-v2",
        compiler_version="1",
    )


def _cell(
    canonical_background_sha256: str | None = None,
) -> ExactProposalCellV1:
    return ExactProposalCellV1(
        namespace=_namespace(),
        locus=ExactFactorLocusV1(
            carrier="phase_program",
            slot_id="instruction_slot",
            logical_factor_id="instruction_policy",
            locator_surface="phase_field",
            locator_path="/instruction",
            locator_version="1",
        ),
        from_revision_id="factor:source",
        canonical_from_factor_key_sha256=_h("factor-key:source"),
        canonical_background_sha256=(
            canonical_background_sha256 or _h("background:current")
        ),
    )


def _sign(target: str, index: int, sign: str) -> PortableBackgroundSignV1:
    return PortableBackgroundSignV1(
        fixed_background_sha256=_h(f"background:{index}"),
        sign=sign,
        evidence_root_sha256=_h(f"evidence:{target}:{index}:{sign}"),
    )


def _candidate(
    target: str,
    signs: tuple[str, ...],
    *,
    content: str | None = None,
    lineage: str | None = None,
    reverse_evidence_order: bool = False,
) -> PortableCandidateV1:
    evidence = tuple(_sign(target, index, sign) for index, sign in enumerate(signs))
    if reverse_evidence_order:
        evidence = tuple(reversed(evidence))
    return PortableCandidateV1(
        target_revision_id=f"factor:{target}",
        target_factor_key_sha256=_h(f"factor-key:{content or target}"),
        target_content_sha256=_h(content or f"content:{target}"),
        lineage_niche=LineageNicheV1(
            origin_branch="mutate",
            root_revision_id=f"lineage:{lineage or target}",
            provenance_family_sha256=_h(f"family:{lineage or target}"),
            canonical_lineage_key_sha256=_h(
                f"canonical-family:{lineage or target}"
            ),
        ),
        background_signs=evidence,
    )


def _proposal_input(
    candidates: tuple[PortableCandidateV1, ...],
    *,
    cursor: ProposalCursorV1 | None = None,
    opportunity: str = "opportunity:one",
    current_background_sha256: str | None = None,
    counter_witnesses: tuple[CandidateCounterWitnessV1, ...] | None = None,
    counter_state: tuple[CandidateCounterWitnessV1, ...] | None = None,
) -> SFTProposalInputV1:
    cell = _cell(current_background_sha256)
    witnesses = counter_witnesses or tuple(
        CandidateCounterWitnessV1(
            cell_sha256=cell.scheduler_key_sha256,
            target_factor_key_sha256=item.target_factor_key_sha256,
        )
        for item in sorted(
            candidates,
            key=lambda item: item.target_factor_key_sha256,
        )
    )
    return SFTProposalInputV1(
        request=ProposalRequestV1(opportunity_id=opportunity, cell=cell),
        cursor=cursor or ProposalCursorV1.empty(cell),
        candidates=candidates,
        proposal_counter_state_sha256=proposal_counter_state_sha256(
            counter_state if counter_state is not None else ()
        ),
        candidate_counter_witnesses=witnesses,
    )


def _zero_counter_witnesses(
    cell: ExactProposalCellV1,
    candidates: tuple[PortableCandidateV1, ...],
) -> tuple[CandidateCounterWitnessV1, ...]:
    return tuple(
        CandidateCounterWitnessV1(
            cell_sha256=cell.scheduler_key_sha256,
            target_factor_key_sha256=item.target_factor_key_sha256,
        )
        for item in sorted(
            candidates,
            key=lambda item: item.target_factor_key_sha256,
        )
    )


def _apply_projected_counter_delta(
    table: dict[tuple[str, str], CandidateCounterWitnessV1],
    delta: ProposalCounterDeltaV1,
) -> None:
    key = (delta.cell_sha256, delta.target_factor_key_sha256)
    before = table.get(
        key,
        CandidateCounterWitnessV1(
            cell_sha256=delta.cell_sha256,
            target_factor_key_sha256=delta.target_factor_key_sha256,
        ),
    )
    table[key] = before.model_copy(
        update={
            "unknown_selection_count": (
                before.unknown_selection_count
                + delta.unknown_selection_increment
            ),
            "single_safe_unknown_selection_count": (
                before.single_safe_unknown_selection_count
                + delta.single_safe_unknown_selection_increment
            ),
        }
    )


def _history_entry(
    decision: int,
    selection: int,
    target: str,
) -> ProposalHistoryEntryV1:
    return ProposalHistoryEntryV1(
        decision_ordinal=decision,
        selection_ordinal=selection,
        target_revision_id=f"factor:{target}",
        target_factor_key_sha256=_h(f"factor-key:{target}"),
        target_content_sha256=_h(f"content:{target}"),
        lineage_niche_sha256=LineageNicheV1(
            origin_branch="mutate",
            root_revision_id=f"lineage:{target}",
            provenance_family_sha256=_h(f"family:{target}"),
            canonical_lineage_key_sha256=_h(
                f"canonical-family:{target}"
            ),
        ).exposure_key_sha256,
        proposal_class="transferable",
        selection_mode="portable_exploitation",
    )


def test_post_eviction_25_25_oldest_b_rejects_a() -> None:
    # B,A repeated gives 25/25 with B as the exact next eviction.  Appending A
    # would yield A=26,B=24, so the mature integer cap must reject A.
    history = tuple(
        _history_entry(index, index, "B" if index % 2 == 0 else "A")
        for index in range(50)
    )
    cursor = ProposalCursorV1(
        cell_sha256=_cell().scheduler_key_sha256,
        lifetime_ordinal=50,
        lifetime_selection_count=50,
        last50=history,
    )
    receipt = select_exact_edge_proposal(
        _proposal_input(
            (
                _candidate("A", ("benefit", "benefit", "benefit")),
                _candidate("B", ("benefit", "benefit")),
            ),
            cursor=cursor,
        )
    )
    manifest = {
        item.candidate.target_revision_id: item for item in receipt.candidate_manifest
    }
    assert manifest["factor:A"].target_cap_admissible is False
    assert manifest["factor:A"].lineage_cap_admissible is False
    assert manifest["factor:B"].target_cap_admissible is True
    assert manifest["factor:B"].lineage_cap_admissible is True
    assert receipt.selected_target_revision_id == "factor:B"
    assert sum(
        item.target_revision_id == "factor:A" for item in receipt.projected_cursor.last50
    ) == 25


def test_mature_window_does_not_waive_cap_for_a_sole_target() -> None:
    history = tuple(
        _history_entry(index, index, "B" if index % 2 == 0 else "A")
        for index in range(50)
    )
    cursor = ProposalCursorV1(
        cell_sha256=_cell().scheduler_key_sha256,
        lifetime_ordinal=50,
        lifetime_selection_count=50,
        last50=history,
    )
    receipt = select_exact_edge_proposal(
        _proposal_input(
            (_candidate("A", ("benefit", "benefit")),),
            cursor=cursor,
            opportunity="opportunity:mature-sole",
        )
    )
    assert receipt.candidate_manifest[0].target_cap_admissible is False
    assert receipt.candidate_manifest[0].lineage_cap_admissible is False
    assert receipt.selection_mode == "no_safe_reuse"
    assert receipt.target_cap_waiver_reason is None
    assert receipt.lineage_cap_waiver_reason is None


def test_exact_content_aliases_are_rejected_before_selection() -> None:
    duplicate_content = "byte-identical-canonical-content"
    with pytest.raises(ValidationError, match="content aliases"):
        _proposal_input(
            (
                _candidate("A", (), content=duplicate_content),
                _candidate("B", (), content=duplicate_content),
            )
        )


def test_storage_aliases_share_cursor_and_target_exposure_lifetime() -> None:
    left = _cell()
    right = left.model_copy(update={"from_revision_id": "factor:source-alias"})
    assert left.digest != right.digest
    assert left.scheduler_key_sha256 == right.scheduler_key_sha256
    assert ProposalCursorV1.empty(left) == ProposalCursorV1.empty(right)
    candidate = _candidate("A", ())
    first = select_exact_edge_proposal(
        _proposal_input(
            (candidate,),
            opportunity="opportunity:alias-lifetime:one",
        )
    )
    target_alias = candidate.model_copy(
        update={"target_revision_id": "factor:A-storage-alias"}
    )
    witness_one = CandidateCounterWitnessV1(
        cell_sha256=left.scheduler_key_sha256,
        target_factor_key_sha256=candidate.target_factor_key_sha256,
        unknown_selection_count=1,
        single_safe_unknown_selection_count=1,
    )
    second = select_exact_edge_proposal(
        SFTProposalInputV1(
            request=ProposalRequestV1(
                opportunity_id="opportunity:alias-lifetime:two",
                cell=right,
            ),
            cursor=first.projected_cursor,
            candidates=(target_alias,),
            proposal_counter_state_sha256=proposal_counter_state_sha256(
                (witness_one,)
            ),
            candidate_counter_witnesses=(witness_one,),
        )
    )
    witness_two = witness_one.model_copy(
        update={
            "unknown_selection_count": 2,
            "single_safe_unknown_selection_count": 2,
        }
    )
    third = select_exact_edge_proposal(
        SFTProposalInputV1(
            request=ProposalRequestV1(
                opportunity_id="opportunity:alias-lifetime:three",
                cell=left,
            ),
            cursor=second.projected_cursor,
            candidates=(candidate,),
            proposal_counter_state_sha256=proposal_counter_state_sha256(
                (witness_two,)
            ),
            candidate_counter_witnesses=(witness_two,),
        )
    )
    assert second.candidate_manifest[0].target_selection_count_before == 1
    assert second.selected_target_revision_id == "factor:A-storage-alias"
    assert third.selection_mode == "no_safe_reuse"
    assert third.candidate_manifest[0].retirement_reason == (
        "sole_unknown_lifetime_exhausted"
    )


def test_storage_aliases_cannot_change_canonical_tiebreak_selection() -> None:
    candidate_a = _candidate("A", ())
    candidate_b = _candidate("B", ())
    base = select_exact_edge_proposal(
        _proposal_input((candidate_a, candidate_b))
    )
    alias_a = candidate_a.model_copy(
        update={
            "target_revision_id": "factor:0-alias-0002",
            "lineage_niche": candidate_a.lineage_niche.model_copy(
                update={
                    "root_revision_id": "lineage:0-alias-0002",
                    "provenance_family_sha256": _h(
                        "storage-provenance-alias-A"
                    ),
                }
            ),
        }
    )
    aliased = select_exact_edge_proposal(
        _proposal_input((alias_a, candidate_b))
    )

    def selected_key(receipt):
        return next(
            item.candidate.target_factor_key_sha256
            for item in receipt.candidate_manifest
            if item.candidate.target_revision_id
            == receipt.selected_target_revision_id
        )

    assert selected_key(base) == selected_key(aliased)
    base_ties = {
        item.candidate.target_factor_key_sha256: item.seeded_tiebreak_sha256
        for item in base.candidate_manifest
    }
    alias_ties = {
        item.candidate.target_factor_key_sha256: item.seeded_tiebreak_sha256
        for item in aliased.candidate_manifest
    }
    assert base_ties == alias_ties
    assert base.digest != aliased.digest
    assert base.selected_target_factor_key_sha256 == (
        aliased.selected_target_factor_key_sha256
    )
    assert base.proposal_scheduler_decision_sha256 == (
        aliased.proposal_scheduler_decision_sha256
    )


def test_scheduler_decision_excludes_every_exact_join_id() -> None:
    candidates = (_candidate("A", ()), _candidate("B", ()))
    base = select_exact_edge_proposal(_proposal_input(candidates))
    aliased_cell = _cell().model_copy(
        update={"from_revision_id": "factor:source-storage-alias"}
    )
    aliased_candidates = tuple(
        item.model_copy(
            update={
                "target_revision_id": f"factor:{index}-storage-alias",
                "lineage_niche": item.lineage_niche.model_copy(
                    update={
                        "root_revision_id": f"lineage:{index}-storage-alias",
                        "provenance_family_sha256": _h(
                            f"provenance-storage-alias:{index}"
                        ),
                    }
                ),
            }
        )
        for index, item in enumerate(candidates)
    )
    aliased = select_exact_edge_proposal(
        SFTProposalInputV1(
            request=ProposalRequestV1(
                opportunity_id="opportunity:storage-alias",
                cell=aliased_cell,
            ),
            cursor=ProposalCursorV1.empty(aliased_cell),
            candidates=aliased_candidates,
            proposal_counter_state_sha256=proposal_counter_state_sha256(()),
            candidate_counter_witnesses=_zero_counter_witnesses(
                aliased_cell,
                aliased_candidates,
            ),
        )
    )

    assert base.digest != aliased.digest
    assert base.proposal_scheduler_decision_sha256 == (
        aliased.proposal_scheduler_decision_sha256
    )
    assert base.selected_target_factor_key_sha256 == (
        aliased.selected_target_factor_key_sha256
    )


def test_canonical_comparator_alias_cannot_enter_candidate_slate() -> None:
    cell = _cell()
    comparator_alias = _candidate("source-alias", ()).model_copy(
        update={
            "target_factor_key_sha256": (
                cell.canonical_from_factor_key_sha256
            )
        }
    )
    with pytest.raises(ValidationError, match="canonical comparator"):
        _proposal_input((comparator_alias,))


def test_current_background_harm_is_an_exact_edge_veto() -> None:
    receipt = select_exact_edge_proposal(
        _proposal_input(
            (
                _candidate("A", ("benefit", "benefit", "benefit", "harm")),
            ),
            current_background_sha256=_h("background:3"),
        )
    )
    summary = receipt.candidate_manifest[0].pair_summary
    assert summary.proposal_class == "veto"
    assert summary.harm_background_count == 1
    assert summary.current_background_sign == "harm"
    assert receipt.selection_mode == "no_safe_reuse"
    assert receipt.selected_target_revision_id is None


def test_other_background_harm_is_bounded_prior_not_a_hard_veto() -> None:
    receipt = select_exact_edge_proposal(
        _proposal_input(
            (
                _candidate("A", ("benefit", "benefit", "benefit", "harm")),
            )
        )
    )
    summary = receipt.candidate_manifest[0].pair_summary
    assert summary.proposal_class == "transferable"
    assert summary.harm_background_count == 1
    assert summary.current_background_sign is None
    assert receipt.selected_target_revision_id == "factor:A"


def test_unverified_background_sign_cannot_enter_the_closed_input() -> None:
    with pytest.raises(ValidationError):
        PortableBackgroundSignV1(
            fixed_background_sha256=_h("background"),
            sign="harm",
            evidence_root_sha256=_h("evidence"),
            host_verified=False,
        )


def test_two_pure_all_zero_backgrounds_exhaust_reuse() -> None:
    receipt = select_exact_edge_proposal(
        _proposal_input((_candidate("A", ("all_zero", "all_zero")),))
    )
    summary = receipt.candidate_manifest[0].pair_summary
    assert summary.proposal_class == "all_zero_exhausted"
    assert summary.all_zero_background_count == 2
    assert receipt.selection_mode == "no_safe_reuse"


def test_mixed_zero_null_sole_unknown_retires_after_two_lifetime_uses() -> None:
    candidate = _candidate("A", ("all_zero", "null"))
    cursor = ProposalCursorV1.empty(_cell())
    witness = CandidateCounterWitnessV1(
        cell_sha256=_cell().scheduler_key_sha256,
        target_factor_key_sha256=candidate.target_factor_key_sha256,
    )
    receipts = []
    for index in range(3):
        receipt = select_exact_edge_proposal(
            _proposal_input(
                (candidate,),
                cursor=cursor,
                opportunity=f"opportunity:mixed:{index}",
                counter_witnesses=(witness,),
                counter_state=((witness,) if index else ()),
            )
        )
        receipts.append(receipt)
        cursor = receipt.projected_cursor
        if receipt.projected_counter_delta is not None:
            witness = witness.model_copy(
                update={
                    "unknown_selection_count": (
                        witness.unknown_selection_count + 1
                    ),
                    "single_safe_unknown_selection_count": (
                        witness.single_safe_unknown_selection_count + 1
                    ),
                }
            )

    assert receipts[0].selected_target_revision_id == "factor:A"
    assert receipts[1].selected_target_revision_id == "factor:A"
    assert receipts[2].selection_mode == "no_safe_reuse"
    assert receipts[2].candidate_manifest[0].retirement_reason == (
        "sole_unknown_lifetime_exhausted"
    )
    assert receipts[1].projected_counter_delta == ProposalCounterDeltaV1(
        cell_sha256=_cell().scheduler_key_sha256,
        target_factor_key_sha256=_h("factor-key:A"),
        single_safe_unknown_selection_increment=1,
    )
    assert witness.unknown_selection_count == 2
    assert witness.single_safe_unknown_selection_count == 2


def test_1024_distinct_sole_unknown_targets_keep_receipts_and_cursor_bounded() -> None:
    """The host table may grow to its cap; no receipt copies that table."""

    cell = _cell()
    cursor = ProposalCursorV1.empty(cell)
    table: dict[tuple[str, str], CandidateCounterWitnessV1] = {}
    receipt_sizes = []
    for index in range(1024):
        candidate = _candidate(f"bounded{index:04d}", ())
        witness = CandidateCounterWitnessV1(
            cell_sha256=cell.scheduler_key_sha256,
            target_factor_key_sha256=candidate.target_factor_key_sha256,
        )
        counter_state = tuple(table[key] for key in sorted(table))
        receipt = select_exact_edge_proposal(
            _proposal_input(
                (candidate,),
                cursor=cursor,
                opportunity=f"opportunity:bounded:{index:04d}",
                counter_witnesses=(witness,),
                counter_state=counter_state,
            )
        )
        assert replay_validate_proposal_receipt(receipt) is receipt
        assert receipt.projected_counter_delta is not None
        _apply_projected_counter_delta(
            table,
            receipt.projected_counter_delta,
        )
        cursor = receipt.projected_cursor
        receipt_sizes.append(len(receipt.model_dump_json().encode("utf-8")))

    assert len(table) == 1024
    assert len(cursor.last50) == 50
    assert "lifetime_counters" not in cursor.model_dump(mode="json")
    assert max(receipt_sizes) <= 65_536
    # Fixed-width IDs/ordinals make the post-warmup receipt envelope stable;
    # the 1024-row host table is represented by one 64-byte root and witness.
    assert max(receipt_sizes[-100:]) - min(receipt_sizes[-100:]) < 256
    assert receipt_sizes[-100:] != sorted(receipt_sizes[-100:])


def test_single_safe_unknown_lifetime_count_survives_50_other_selections() -> None:
    cell = _cell()
    cursor = ProposalCursorV1.empty(cell)
    table: dict[tuple[str, str], CandidateCounterWitnessV1] = {}

    def choose(candidate: PortableCandidateV1, ordinal: int):
        nonlocal cursor
        key = (cell.scheduler_key_sha256, candidate.target_factor_key_sha256)
        witness = table.get(
            key,
            CandidateCounterWitnessV1(
                cell_sha256=cell.scheduler_key_sha256,
                target_factor_key_sha256=candidate.target_factor_key_sha256,
            ),
        )
        receipt = select_exact_edge_proposal(
            _proposal_input(
                (candidate,),
                cursor=cursor,
                opportunity=f"opportunity:lifetime-return:{ordinal:03d}",
                counter_witnesses=(witness,),
                counter_state=tuple(table[key] for key in sorted(table)),
            )
        )
        assert replay_validate_proposal_receipt(receipt) is receipt
        if receipt.projected_counter_delta is not None:
            _apply_projected_counter_delta(table, receipt.projected_counter_delta)
        cursor = receipt.projected_cursor
        return receipt

    original = _candidate("persistent", ())
    first = choose(original, 0)
    assert first.selected_target_revision_id == "factor:persistent"
    for index in range(50):
        choose(_candidate(f"otherA{index:02d}", ()), index + 1)
    second = choose(original, 51)
    assert second.candidate_manifest[0].single_safe_unknown_selection_count_before == 1
    assert second.selected_target_revision_id == "factor:persistent"
    for index in range(50):
        choose(_candidate(f"otherB{index:02d}", ()), index + 52)
    retired = choose(original, 102)
    assert retired.selection_mode == "no_safe_reuse"
    assert retired.candidate_manifest[0].retirement_reason == (
        "sole_unknown_lifetime_exhausted"
    )
    persistent = table[
        (cell.scheduler_key_sha256, original.target_factor_key_sha256)
    ]
    assert persistent.single_safe_unknown_selection_count == 2


def test_v4_policy_receipt_and_counter_cursor_shapes_fail_closed() -> None:
    with pytest.raises(ValidationError):
        EdgeProposalPolicyV1(policy_name="sft_exact_edge_proposal_v4")

    cursor_payload = ProposalCursorV1.empty(_cell()).model_dump(mode="json")
    cursor_payload["lifetime_counters"] = []
    with pytest.raises(ValidationError, match="lifetime_counters"):
        ProposalCursorV1.model_validate(cursor_payload)

    receipt = select_exact_edge_proposal(
        _proposal_input((_candidate("A", ("benefit", "benefit")),))
    )
    legacy_receipt = receipt.model_dump(mode="json")
    legacy_receipt["receipt_version"] = "sft-target-proposal-v4"
    with pytest.raises(ValidationError):
        ProposalReceiptV1.model_validate(legacy_receipt)


def test_archived_cursor_dump_reload_preserves_next_action() -> None:
    candidates = (
        _candidate("A", ("benefit", "benefit")),
        _candidate("B", ("benefit", "benefit")),
    )
    cursor = ProposalCursorV1.empty(_cell())
    for index in range(55):
        receipt = select_exact_edge_proposal(
            _proposal_input(
                candidates,
                cursor=cursor,
                opportunity=f"opportunity:archive:{index}",
            )
        )
        assert receipt.selected_target_revision_id is not None
        cursor = receipt.projected_cursor

    assert cursor.lifetime_selection_count == 55
    assert len(cursor.last50) == 50
    assert cursor.archived_history_sha256 != hashlib.sha256(b"[]").hexdigest()
    reloaded = ProposalCursorV1.model_validate_json(cursor.model_dump_json())
    original_next = select_exact_edge_proposal(
        _proposal_input(candidates, cursor=cursor, opportunity="opportunity:after-reload")
    )
    reloaded_next = select_exact_edge_proposal(
        _proposal_input(candidates, cursor=reloaded, opportunity="opportunity:after-reload")
    )
    assert original_next == reloaded_next


def test_candidate_and_evidence_input_order_do_not_change_receipt() -> None:
    candidate_a = _candidate(
        "A", ("benefit", "benefit", "null"), reverse_evidence_order=False
    )
    candidate_a_reversed = _candidate(
        "A", ("benefit", "benefit", "null"), reverse_evidence_order=True
    )
    candidate_b = _candidate("B", ("infrastructure",))
    forward = select_exact_edge_proposal(_proposal_input((candidate_a, candidate_b)))
    reverse = select_exact_edge_proposal(
        _proposal_input((candidate_b, candidate_a_reversed))
    )
    assert forward == reverse
    assert replay_validate_proposal_receipt(forward) is forward


def test_shuffled_exact_edge_evidence_changes_transferable_rank() -> None:
    cursor = ProposalCursorV1(
        cell_sha256=_cell().scheduler_key_sha256,
        lifetime_ordinal=2,
        lifetime_selection_count=2,
        last50=(
            _history_entry(0, 0, "A"),
            _history_entry(1, 1, "B"),
        ),
    )
    original = select_exact_edge_proposal(
        _proposal_input(
            (
                _candidate("A", ("benefit", "benefit", "benefit", "null")),
                _candidate("B", ("benefit", "benefit")),
            ),
            cursor=cursor,
            opportunity="opportunity:rank",
        )
    )
    shuffled = select_exact_edge_proposal(
        _proposal_input(
            (
                _candidate("A", ("benefit", "benefit")),
                _candidate("B", ("benefit", "benefit", "benefit", "null")),
            ),
            cursor=cursor,
            opportunity="opportunity:rank",
        )
    )
    assert original.selection_mode == "portable_exploitation"
    assert original.selected_target_revision_id == "factor:A"
    assert shuffled.selected_target_revision_id == "factor:B"


def test_receipt_has_no_inherited_local_efficacy_fields() -> None:
    receipt = select_exact_edge_proposal(
        _proposal_input((_candidate("A", ("benefit", "benefit")),))
    )
    forbidden = {
        "V",
        "K",
        "U",
        "P",
        "S",
        "C",
        "D",
        "stage_score",
        "utility",
        "assessment",
        "dense_delta",
        "n_complete",
        "n_benefit",
        "n_harm",
        "n_null",
        "gate_state",
        "transition_id",
    }

    def all_keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from all_keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from all_keys(item)

    assert forbidden.isdisjoint(set(all_keys(receipt.model_dump(mode="json"))))
    with pytest.raises(ValidationError):
        PortableCandidateV1(
            target_revision_id="factor:bad",
            target_factor_key_sha256=_h("factor-key:bad"),
            target_content_sha256=_h("bad"),
            lineage_niche=_candidate("A", ()).lineage_niche,
            background_signs=(),
            stage_score=1.0,
        )


def test_oversized_closed_manifest_is_rejected_before_receipt_creation() -> None:
    candidates = tuple(
        _candidate(
            f"candidate{candidate_index}",
            tuple("infrastructure" for _ in range(50)),
        )
        for candidate_index in range(16)
    )
    with pytest.raises(ValidationError, match="canonical proposal input exceeds"):
        _proposal_input(candidates, opportunity="opportunity:oversized")


def test_dense_slate_is_greedily_reduced_under_both_byte_caps() -> None:
    dense = tuple(
        _candidate(
            f"dense{candidate_index}",
            tuple("infrastructure" for _ in range(12)),
        )
        for candidate_index in range(16)
    )
    cell = _cell()
    request = ProposalRequestV1(opportunity_id="opportunity:dense", cell=cell)
    cursor = ProposalCursorV1.empty(cell)
    counter_root = proposal_counter_state_sha256(())
    assert not proposal_slate_fits_byte_bounds(
        request=request,
        cursor=cursor,
        candidates=dense,
        proposal_counter_state_sha256=counter_root,
        candidate_counter_witnesses=_zero_counter_witnesses(cell, dense),
    )

    admitted = []
    for candidate in dense:
        proposed = (*admitted, candidate)
        if proposal_slate_fits_byte_bounds(
            request=request,
            cursor=cursor,
            candidates=proposed,
            proposal_counter_state_sha256=counter_root,
            candidate_counter_witnesses=_zero_counter_witnesses(
                cell,
                proposed,
            ),
        ):
            admitted.append(candidate)
    assert 0 < len(admitted) < 16
    receipt = select_exact_edge_proposal(
        SFTProposalInputV1(
            request=request,
            cursor=cursor,
            candidates=tuple(admitted),
            proposal_counter_state_sha256=counter_root,
            candidate_counter_witnesses=_zero_counter_witnesses(
                cell,
                tuple(admitted),
            ),
        )
    )
    assert replay_validate_proposal_receipt(receipt) is receipt


def test_sparse_max_join_ids_fit_and_replay_after_json_reload() -> None:
    def max_id(label: str, ordinal: int) -> str:
        stem = f"{label}:{ordinal}:"
        return stem + "x" * (128 - len(stem))

    cell = _cell().model_copy(
        update={"from_revision_id": max_id("from", 0)}
    )
    request = ProposalRequestV1(
        opportunity_id=max_id("opportunity", 0),
        cell=cell,
    )
    universe = tuple(
        _candidate(f"sparse{index}", ()).model_copy(
            update={
                "target_revision_id": max_id("target", index),
                "lineage_niche": _candidate(
                    f"sparse{index}", ()
                ).lineage_niche.model_copy(
                    update={"root_revision_id": max_id("lineage", index)}
                ),
            }
        )
        for index in range(21)
    )
    slate = universe[:16]
    cursor = ProposalCursorV1.empty(cell)
    assert proposal_slate_fits_byte_bounds(
        request=request,
        cursor=cursor,
        candidates=slate,
        proposal_counter_state_sha256=proposal_counter_state_sha256(()),
        candidate_counter_witnesses=_zero_counter_witnesses(cell, slate),
    )
    receipt = select_exact_edge_proposal(
        SFTProposalInputV1(
            request=request,
            cursor=cursor,
            candidates=slate,
            proposal_counter_state_sha256=proposal_counter_state_sha256(()),
            candidate_counter_witnesses=_zero_counter_witnesses(cell, slate),
        )
    )
    reloaded = ProposalReceiptV1.model_validate_json(receipt.model_dump_json())
    assert replay_validate_proposal_receipt(reloaded) == receipt


def test_replay_validator_rejects_a_tampered_decision() -> None:
    receipt = select_exact_edge_proposal(
        _proposal_input(
            (
                _candidate("A", ("benefit", "benefit")),
                _candidate("B", ("benefit", "benefit")),
            )
        )
    )
    alternate = "factor:B" if receipt.selected_target_revision_id == "factor:A" else "factor:A"
    tampered = receipt.model_copy(update={"selected_target_revision_id": alternate})
    with pytest.raises(ProposalReplayError):
        replay_validate_proposal_receipt(tampered)
