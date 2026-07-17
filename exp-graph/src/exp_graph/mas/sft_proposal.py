"""Pure, deterministic target proposal law for the experimental SFT-Bank.

The selector is deliberately smaller than the Bank state machine.  It accepts
only host-sealed, answer-free structural identities and portable *signs* from
exact directed edges.  It never receives an artifact payload, prompt, task
answer, local assessment, utility estimate, or LLM-produced similarity.

The returned receipt is a replayable search decision, not scientific credit.
In particular, nothing in this module can initialize a new local edge with an
efficacy observation.  A caller must still register that edge at ``n=0`` and
run its own matched source/target probes.

Version 5 preserves the v4 *lifetime* sole-UNKNOWN retirement rule without
letting a selector receipt grow once per target ever seen.  The authoritative,
capacity-bounded counter table lives in the host Bank.  A selector input carries
only the exact-cell root of that table plus witnesses for the at-most-sixteen
current candidates; a selected UNKNOWN emits at most one counter delta.  Host admission
checks the witnesses against the rooted table and applies the delta atomically.
This is not a window/cooldown reinterpretation of "lifetime": eviction from the
50-selection diversity window never resets the counter.  The v5 policy and
receipt literals, required witnesses, and counter-free cursor make every v4
shape fail closed instead of being silently reinterpreted.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.mas.factor_bank import (
    ExecutionNamespace,
    FactorCarrier,
    assert_bank_safe_public_value,
)


PortableSign = Literal["benefit", "null", "all_zero", "infrastructure", "harm"]
ProposalClass = Literal["transferable", "unknown", "all_zero_exhausted", "veto"]
SelectionMode = Literal[
    "structured_exploration",
    "portable_exploitation",
    "no_portable_support_fallback",
    "no_safe_reuse",
]
OriginBranch = Literal["reuse", "mutate", "fresh", "migration"]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_HISTORY_SHA256 = hashlib.sha256(b"[]").hexdigest()
MAX_PROPOSAL_INPUT_BYTES = 65_536
MAX_PROPOSAL_RECEIPT_BYTES = 65_536
MAX_EXACT_JOIN_ID_CHARS = 128


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_id(value: str, name: str) -> None:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a short opaque identifier")


def _require_sha(value: str, name: str) -> None:
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def reject_private_or_oracle_values(self) -> "_ClosedModel":
        assert_bank_safe_public_value(self.model_dump(mode="python"))
        return self


class ExactFactorLocusV1(_ClosedModel):
    """Host-owned factor address; no semantic matching is permitted."""

    carrier: FactorCarrier
    slot_id: str
    logical_factor_id: str
    locator_surface: Literal[
        "phase_field",
        "python_evolve_block",
        "graph_field",
        "reasoning_policy_field",
        "constraint_field",
        "insight_reference",
    ]
    locator_path: str = Field(min_length=1, max_length=256)
    locator_version: str = Field(min_length=1, max_length=80)
    binding_status: Literal["proven_factorized"] = "proven_factorized"

    @model_validator(mode="after")
    def validate_ids(self) -> "ExactFactorLocusV1":
        _require_id(self.slot_id, "slot_id")
        _require_id(self.logical_factor_id, "logical_factor_id")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ExactProposalCellV1(_ClosedModel):
    """The full namespace, locus and comparator defining one proposal cell."""

    namespace: ExecutionNamespace
    locus: ExactFactorLocusV1
    from_revision_id: str
    canonical_from_factor_key_sha256: str
    canonical_background_sha256: str

    @model_validator(mode="after")
    def validate_from_revision(self) -> "ExactProposalCellV1":
        _require_id(self.from_revision_id, "from_revision_id")
        _require_sha(
            self.canonical_from_factor_key_sha256,
            "canonical_from_factor_key_sha256",
        )
        _require_sha(
            self.canonical_background_sha256,
            "canonical_background_sha256",
        )
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)

    @property
    def scheduler_key_sha256(self) -> str:
        """Alias-stable exposure/cursor key; exact revision remains executable."""

        return _sha256(
            {
                "namespace": self.namespace,
                "locus": self.locus,
                "canonical_from_factor_key_sha256": (
                    self.canonical_from_factor_key_sha256
                ),
                "canonical_background_sha256": (
                    self.canonical_background_sha256
                ),
            }
        )


class LineageNicheV1(_ClosedModel):
    """Trusted, exact provenance family used only for exposure diversity."""

    origin_branch: OriginBranch
    root_revision_id: str
    provenance_family_sha256: str
    canonical_lineage_key_sha256: str
    host_verified: Literal[True] = True

    @model_validator(mode="after")
    def validate_identity(self) -> "LineageNicheV1":
        _require_id(self.root_revision_id, "root_revision_id")
        _require_sha(self.provenance_family_sha256, "provenance_family_sha256")
        _require_sha(
            self.canonical_lineage_key_sha256,
            "canonical_lineage_key_sha256",
        )
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)

    @property
    def exposure_key_sha256(self) -> str:
        return self.canonical_lineage_key_sha256


class PortableBackgroundSignV1(_ClosedModel):
    """One verified lifetime reduction for one distinct fixed background."""

    fixed_background_sha256: str
    sign: PortableSign
    evidence_root_sha256: str
    host_verified: Literal[True] = True

    @model_validator(mode="after")
    def validate_hashes(self) -> "PortableBackgroundSignV1":
        _require_sha(self.fixed_background_sha256, "fixed_background_sha256")
        _require_sha(self.evidence_root_sha256, "evidence_root_sha256")
        return self


class PortableCandidateV1(_ClosedModel):
    """A content-canonical target and its exact-pair portable sign ledger."""

    target_revision_id: str
    target_factor_key_sha256: str
    target_content_sha256: str
    lineage_niche: LineageNicheV1
    background_signs: tuple[PortableBackgroundSignV1, ...] = Field(
        default=(), max_length=50
    )

    @model_validator(mode="after")
    def validate_candidate(self) -> "PortableCandidateV1":
        _require_id(self.target_revision_id, "target_revision_id")
        _require_sha(
            self.target_factor_key_sha256,
            "target_factor_key_sha256",
        )
        _require_sha(self.target_content_sha256, "target_content_sha256")
        backgrounds = [item.fixed_background_sha256 for item in self.background_signs]
        if len(backgrounds) != len(set(backgrounds)):
            raise ValueError("portable signs must name distinct fixed backgrounds")
        return self


class CandidateCounterWitnessV1(_ClosedModel):
    """Exact host witness for one current candidate's lifetime counters."""

    witness_version: Literal["sft_candidate_counter_witness_v1"] = (
        "sft_candidate_counter_witness_v1"
    )
    cell_sha256: str
    target_factor_key_sha256: str
    unknown_selection_count: int = Field(default=0, ge=0)
    single_safe_unknown_selection_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_counter(self) -> "CandidateCounterWitnessV1":
        _require_sha(self.cell_sha256, "cell_sha256")
        _require_sha(
            self.target_factor_key_sha256,
            "target_factor_key_sha256",
        )
        if self.single_safe_unknown_selection_count > self.unknown_selection_count:
            raise ValueError("single-safe UNKNOWN count cannot exceed UNKNOWN count")
        return self


class ProposalCounterDeltaV1(_ClosedModel):
    """The sole possible lifetime-counter mutation emitted by one selection."""

    delta_version: Literal["sft_proposal_counter_delta_v1"] = (
        "sft_proposal_counter_delta_v1"
    )
    cell_sha256: str
    target_factor_key_sha256: str
    unknown_selection_increment: Literal[1] = 1
    single_safe_unknown_selection_increment: Literal[0, 1]

    @model_validator(mode="after")
    def validate_delta(self) -> "ProposalCounterDeltaV1":
        _require_sha(self.cell_sha256, "cell_sha256")
        _require_sha(
            self.target_factor_key_sha256,
            "target_factor_key_sha256",
        )
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


def proposal_counter_state_sha256(
    counters: Sequence[CandidateCounterWitnessV1],
) -> str:
    """Canonical root for all bounded lifetime counters in one exact cell."""

    ordered = tuple(
        sorted(
            counters,
            key=lambda item: (item.cell_sha256, item.target_factor_key_sha256),
        )
    )
    keys = tuple(
        (item.cell_sha256, item.target_factor_key_sha256) for item in ordered
    )
    if len({item.cell_sha256 for item in ordered}) > 1:
        raise ValueError("proposal counter root cannot cross exact cells")
    if len(keys) != len(set(keys)):
        raise ValueError("proposal lifetime counters must have unique exact keys")
    return _sha256(
        {
            "root_version": "sft_proposal_counter_state_v1",
            "counters": ordered,
        }
    )


class ProposalHistoryEntryV1(_ClosedModel):
    """One selected target; candidates merely present in a slate never appear."""

    decision_ordinal: int = Field(ge=0)
    selection_ordinal: int = Field(ge=0)
    target_revision_id: str
    target_factor_key_sha256: str
    target_content_sha256: str
    lineage_niche_sha256: str
    proposal_class: Literal["transferable", "unknown"]
    selection_mode: Literal[
        "structured_exploration",
        "portable_exploitation",
        "no_portable_support_fallback",
    ]

    @model_validator(mode="after")
    def validate_entry(self) -> "ProposalHistoryEntryV1":
        _require_id(self.target_revision_id, "target_revision_id")
        _require_sha(
            self.target_factor_key_sha256,
            "target_factor_key_sha256",
        )
        _require_sha(self.target_content_sha256, "target_content_sha256")
        _require_sha(self.lineage_niche_sha256, "lineage_niche_sha256")
        return self


class ProposalCursorV1(_ClosedModel):
    """Bounded diversity scheduler closure; lifetime counters are host-owned."""

    cell_sha256: str
    lifetime_ordinal: int = Field(default=0, ge=0)
    lifetime_selection_count: int = Field(default=0, ge=0)
    archived_history_sha256: str = _EMPTY_HISTORY_SHA256
    last50: tuple[ProposalHistoryEntryV1, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_cursor(self) -> "ProposalCursorV1":
        _require_sha(self.cell_sha256, "cell_sha256")
        _require_sha(self.archived_history_sha256, "archived_history_sha256")
        if self.lifetime_selection_count > self.lifetime_ordinal:
            raise ValueError("selection count cannot exceed decision ordinal")
        expected_history_size = min(self.lifetime_selection_count, 50)
        if len(self.last50) != expected_history_size:
            raise ValueError("last50 must be the exact suffix of selected-target history")
        first_selection = self.lifetime_selection_count - len(self.last50)
        if tuple(item.selection_ordinal for item in self.last50) != tuple(
            range(first_selection, self.lifetime_selection_count)
        ):
            raise ValueError("last50 selection ordinals must form an exact suffix")
        decision_ordinals = [item.decision_ordinal for item in self.last50]
        if decision_ordinals != sorted(set(decision_ordinals)):
            raise ValueError("last50 decision ordinals must be unique and ordered")
        if decision_ordinals and decision_ordinals[-1] >= self.lifetime_ordinal:
            raise ValueError("history cannot name an uncommitted decision ordinal")
        if self.lifetime_selection_count > 50 and self.archived_history_sha256 == _EMPTY_HISTORY_SHA256:
            raise ValueError("archived selections require a non-empty history chain")
        return self

    @classmethod
    def empty(cls, cell: ExactProposalCellV1) -> "ProposalCursorV1":
        return cls(cell_sha256=cell.scheduler_key_sha256)

    @property
    def digest(self) -> str:
        return _sha256(self)


class EdgeProposalPolicyV1(_ClosedModel):
    """Outcome-before frozen pilot law; ratios are checked with integers."""

    policy_name: Literal["sft_exact_edge_proposal_v5"] = "sft_exact_edge_proposal_v5"
    min_positive_backgrounds: Literal[2] = 2
    sign_quorum_numerator: Literal[3] = 3
    sign_quorum_denominator: Literal[4] = 4
    max_all_zero_backgrounds: Literal[2] = 2
    max_single_safe_unknown_uses: Literal[2] = 2
    initial_exploration_decisions: Literal[2] = 2
    exploration_period: Literal[4] = 4
    exposure_window: Literal[50] = 50
    mature_target_share_numerator: Literal[1] = 1
    mature_target_share_denominator: Literal[2] = 2
    mature_lineage_share_numerator: Literal[1] = 1
    mature_lineage_share_denominator: Literal[2] = 2
    warmup_max_count_gap: Literal[1] = 1
    max_candidates: Literal[16] = 16
    max_backgrounds_per_candidate: Literal[50] = 50
    public_seed: int = 20260713

    @property
    def digest(self) -> str:
        return _sha256(self)


class ProposalRequestV1(_ClosedModel):
    opportunity_id: str
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    cell: ExactProposalCellV1

    @model_validator(mode="after")
    def validate_opportunity(self) -> "ProposalRequestV1":
        _require_id(self.opportunity_id, "opportunity_id")
        return self


class SFTProposalInputV1(_ClosedModel):
    """Complete closed input to the pure selector."""

    request: ProposalRequestV1
    policy: EdgeProposalPolicyV1 = Field(default_factory=EdgeProposalPolicyV1)
    cursor: ProposalCursorV1
    candidates: tuple[PortableCandidateV1, ...] = Field(max_length=16)
    proposal_counter_state_sha256: str
    candidate_counter_witnesses: tuple[CandidateCounterWitnessV1, ...] = Field(
        max_length=16
    )

    @model_validator(mode="after")
    def validate_closed_universe(self) -> "SFTProposalInputV1":
        _require_sha(
            self.proposal_counter_state_sha256,
            "proposal_counter_state_sha256",
        )
        if self.cursor.cell_sha256 != self.request.cell.scheduler_key_sha256:
            raise ValueError("cursor crosses its exact namespace/locus/from cell")
        target_ids = [item.target_revision_id for item in self.candidates]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("candidate target revisions must be unique")
        content_hashes = [item.target_content_sha256 for item in self.candidates]
        if len(content_hashes) != len(set(content_hashes)):
            raise ValueError("exact content aliases cannot form separate candidates")
        target_keys = [item.target_factor_key_sha256 for item in self.candidates]
        if len(target_keys) != len(set(target_keys)):
            raise ValueError("canonical target aliases cannot form separate candidates")
        if self.request.cell.canonical_from_factor_key_sha256 in target_keys:
            raise ValueError("a target cannot alias the canonical comparator")
        witness_keys = [
            item.target_factor_key_sha256
            for item in self.candidate_counter_witnesses
        ]
        if witness_keys != sorted(target_keys):
            raise ValueError(
                "counter witnesses must exactly cover canonical candidate keys"
            )
        if any(
            item.cell_sha256 != self.request.cell.scheduler_key_sha256
            for item in self.candidate_counter_witnesses
        ):
            raise ValueError("counter witness crosses its exact proposal cell")
        if len(_canonical_json(self).encode("utf-8")) > MAX_PROPOSAL_INPUT_BYTES:
            raise ValueError("canonical proposal input exceeds 65536 bytes")
        return self


class PairProposalSummaryV1(_ClosedModel):
    evidence_root_sha256: str
    benefit_background_count: int = Field(ge=0, le=50)
    null_background_count: int = Field(ge=0, le=50)
    all_zero_background_count: int = Field(ge=0, le=50)
    infrastructure_background_count: int = Field(ge=0, le=50)
    harm_background_count: int = Field(ge=0, le=50)
    current_background_sign: PortableSign | None = None
    positive_fraction_micropoints: int = Field(ge=0, le=1_000_000)
    proposal_class: ProposalClass

    @model_validator(mode="after")
    def validate_summary(self) -> "PairProposalSummaryV1":
        _require_sha(self.evidence_root_sha256, "evidence_root_sha256")
        return self


class ProposalCandidateSnapshotV1(_ClosedModel):
    candidate: PortableCandidateV1
    pair_summary: PairProposalSummaryV1
    target_selection_count_before: int = Field(ge=0, le=50)
    lineage_selection_count_before: int = Field(ge=0, le=50)
    unknown_selection_count_before: int = Field(ge=0)
    single_safe_unknown_selection_count_before: int = Field(ge=0)
    target_cap_admissible: bool
    lineage_cap_admissible: bool
    retirement_reason: Literal["sole_unknown_lifetime_exhausted"] | None = None
    seeded_tiebreak_sha256: str

    @model_validator(mode="after")
    def validate_tiebreak(self) -> "ProposalCandidateSnapshotV1":
        _require_sha(self.seeded_tiebreak_sha256, "seeded_tiebreak_sha256")
        if (
            self.single_safe_unknown_selection_count_before
            > self.unknown_selection_count_before
        ):
            raise ValueError("single-safe UNKNOWN count exceeds UNKNOWN count")
        return self


class ProposalReceiptV1(_ClosedModel):
    receipt_version: Literal["sft-target-proposal-v5"] = "sft-target-proposal-v5"
    receipt_id: str
    request: ProposalRequestV1
    policy: EdgeProposalPolicyV1
    policy_sha256: str
    cursor_before: ProposalCursorV1
    cursor_before_sha256: str
    proposal_counter_state_before_sha256: str
    candidate_counter_witnesses: tuple[CandidateCounterWitnessV1, ...] = Field(
        max_length=16
    )
    candidate_counter_witnesses_sha256: str
    candidate_manifest: tuple[ProposalCandidateSnapshotV1, ...] = Field(max_length=16)
    candidate_manifest_sha256: str
    candidate_universe_sha256: str
    candidate_slate_scheduler_sha256: str
    selection_mode: SelectionMode
    selected_target_revision_id: str | None
    selected_target_factor_key_sha256: str | None
    selected_target_content_sha256: str | None
    selected_lineage_niche_sha256: str | None
    target_cap_waiver_reason: Literal["single_safe_target"] | None = None
    lineage_cap_waiver_reason: Literal["single_safe_lineage"] | None = None
    projected_cursor: ProposalCursorV1
    projected_history_sha256: str
    projected_counter_delta: ProposalCounterDeltaV1 | None
    proposal_scheduler_decision_sha256: str

    @model_validator(mode="after")
    def validate_frozen_fields(self) -> "ProposalReceiptV1":
        _require_id(self.receipt_id, "receipt_id")
        for name in (
            "policy_sha256",
            "cursor_before_sha256",
            "proposal_counter_state_before_sha256",
            "candidate_counter_witnesses_sha256",
            "candidate_manifest_sha256",
            "candidate_universe_sha256",
            "candidate_slate_scheduler_sha256",
            "projected_history_sha256",
            "proposal_scheduler_decision_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.policy_sha256 != self.policy.digest:
            raise ValueError("policy hash mismatch")
        if self.cursor_before_sha256 != self.cursor_before.digest:
            raise ValueError("cursor-before hash mismatch")
        if self.candidate_counter_witnesses_sha256 != _sha256(
            self.candidate_counter_witnesses
        ):
            raise ValueError("candidate counter witness hash mismatch")
        if (
            self.cursor_before.cell_sha256
            != self.request.cell.scheduler_key_sha256
        ):
            raise ValueError("receipt cursor crosses its proposal cell")
        if (
            self.projected_cursor.cell_sha256
            != self.request.cell.scheduler_key_sha256
        ):
            raise ValueError("projected cursor crosses its proposal cell")
        if self.candidate_manifest_sha256 != _sha256(self.candidate_manifest):
            raise ValueError("candidate manifest hash mismatch")
        witness_by_target = {
            item.target_factor_key_sha256: item
            for item in self.candidate_counter_witnesses
        }
        manifest_target_keys = [
            item.candidate.target_factor_key_sha256
            for item in self.candidate_manifest
        ]
        if list(witness_by_target) != sorted(manifest_target_keys):
            raise ValueError("receipt counter witnesses do not cover its slate")
        if any(
            item.cell_sha256 != self.request.cell.scheduler_key_sha256
            for item in self.candidate_counter_witnesses
        ):
            raise ValueError("receipt counter witness crosses its exact cell")
        if any(
            witness_by_target[item.candidate.target_factor_key_sha256]
            .unknown_selection_count
            != item.unknown_selection_count_before
            or witness_by_target[item.candidate.target_factor_key_sha256]
            .single_safe_unknown_selection_count
            != item.single_safe_unknown_selection_count_before
            for item in self.candidate_manifest
        ):
            raise ValueError("candidate snapshots disagree with counter witnesses")
        expected_universe_sha256 = _sha256(
            tuple(
                {
                    "candidate": _scheduler_candidate_projection(item.candidate),
                    "pair_summary": item.pair_summary,
                }
                for item in self.candidate_manifest
            )
        )
        if self.candidate_universe_sha256 != expected_universe_sha256:
            raise ValueError("candidate scheduler universe hash mismatch")
        expected_slate_sha256 = _sha256(
            tuple(
                _scheduler_candidate_snapshot_projection(item)
                for item in self.candidate_manifest
            )
        )
        if self.candidate_slate_scheduler_sha256 != expected_slate_sha256:
            raise ValueError("candidate scheduler slate hash mismatch")
        if self.projected_history_sha256 != _sha256(self.projected_cursor.last50):
            raise ValueError("projected history hash mismatch")
        selected_fields = (
            self.selected_target_revision_id,
            self.selected_target_factor_key_sha256,
            self.selected_target_content_sha256,
            self.selected_lineage_niche_sha256,
        )
        if self.selection_mode == "no_safe_reuse":
            if any(item is not None for item in selected_fields):
                raise ValueError("no-safe receipt cannot name a selected target")
            if self.target_cap_waiver_reason or self.lineage_cap_waiver_reason:
                raise ValueError("no-safe receipt cannot claim a cap waiver")
        elif any(item is None for item in selected_fields):
            raise ValueError("selected receipt must freeze target content and lineage")
        else:
            selected = [
                item
                for item in self.candidate_manifest
                if item.candidate.target_revision_id
                == self.selected_target_revision_id
            ]
            if len(selected) != 1 or not (
                selected[0].candidate.target_factor_key_sha256
                == self.selected_target_factor_key_sha256
                and selected[0].candidate.target_content_sha256
                == self.selected_target_content_sha256
                and selected[0].candidate.lineage_niche.exposure_key_sha256
                == self.selected_lineage_niche_sha256
            ):
                raise ValueError("selected canonical target closure is invalid")
        selected_snapshot = next(
            (
                item
                for item in self.candidate_manifest
                if item.candidate.target_factor_key_sha256
                == self.selected_target_factor_key_sha256
            ),
            None,
        )
        if selected_snapshot is None or (
            selected_snapshot.pair_summary.proposal_class != "unknown"
        ):
            if self.projected_counter_delta is not None:
                raise ValueError("only a selected UNKNOWN may emit a counter delta")
        else:
            if self.projected_counter_delta is None or not (
                self.projected_counter_delta.cell_sha256
                == self.request.cell.scheduler_key_sha256
                and self.projected_counter_delta.target_factor_key_sha256
                == self.selected_target_factor_key_sha256
            ):
                raise ValueError("selected UNKNOWN lacks its exact counter delta")
            base_safe = tuple(
                item
                for item in self.candidate_manifest
                if item.pair_summary.proposal_class
                not in {"veto", "all_zero_exhausted"}
            )
            if self.projected_counter_delta.single_safe_unknown_selection_increment != int(
                len(base_safe) == 1
            ):
                raise ValueError("UNKNOWN counter delta has the wrong sole-safe bit")
        if self.proposal_scheduler_decision_sha256 != (
            _proposal_scheduler_decision_sha256(self)
        ):
            raise ValueError("proposal scheduler decision hash mismatch")
        if self.receipt_id != _receipt_id(self):
            raise ValueError("proposal receipt identity mismatch")
        if len(_canonical_json(self).encode("utf-8")) > MAX_PROPOSAL_RECEIPT_BYTES:
            raise ValueError("canonical proposal receipt exceeds 65536 bytes")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ProposalReplayError(ValueError):
    """A persisted proposal does not reproduce from its frozen public input."""


def _canonical_candidate(candidate: PortableCandidateV1) -> PortableCandidateV1:
    signs = tuple(
        sorted(
            candidate.background_signs,
            key=lambda item: (item.fixed_background_sha256, item.evidence_root_sha256),
        )
    )
    return candidate.model_copy(update={"background_signs": signs})


def _scheduler_candidate_projection(
    candidate: PortableCandidateV1,
) -> dict[str, Any]:
    """Alias-free fields allowed to influence search order or exposure."""

    return {
        "target_factor_key_sha256": candidate.target_factor_key_sha256,
        "target_content_sha256": candidate.target_content_sha256,
        "canonical_lineage_key_sha256": (
            candidate.lineage_niche.exposure_key_sha256
        ),
        "background_signs": candidate.background_signs,
    }


def _scheduler_cursor_projection(cursor: ProposalCursorV1) -> dict[str, Any]:
    """Exact-storage-free cursor state allowed to affect later choices."""

    return {
        "cell_sha256": cursor.cell_sha256,
        "lifetime_ordinal": cursor.lifetime_ordinal,
        "lifetime_selection_count": cursor.lifetime_selection_count,
        "archived_history_sha256": cursor.archived_history_sha256,
        "last50": tuple(
            _scheduler_history_entry_projection(item) for item in cursor.last50
        ),
    }


def _scheduler_candidate_snapshot_projection(
    snapshot: ProposalCandidateSnapshotV1,
) -> dict[str, Any]:
    """Alias-free selector facts; exact candidate IDs remain replay joins."""

    return {
        "candidate": _scheduler_candidate_projection(snapshot.candidate),
        "pair_summary": snapshot.pair_summary,
        "target_selection_count_before": snapshot.target_selection_count_before,
        "lineage_selection_count_before": snapshot.lineage_selection_count_before,
        "unknown_selection_count_before": snapshot.unknown_selection_count_before,
        "single_safe_unknown_selection_count_before": (
            snapshot.single_safe_unknown_selection_count_before
        ),
        "target_cap_admissible": snapshot.target_cap_admissible,
        "lineage_cap_admissible": snapshot.lineage_cap_admissible,
        "retirement_reason": snapshot.retirement_reason,
        "seeded_tiebreak_sha256": snapshot.seeded_tiebreak_sha256,
    }


def proposal_scheduler_decision_projection(
    receipt: ProposalReceiptV1,
) -> dict[str, Any]:
    """Canonical decision projection used by every downstream scheduler.

    Opportunity, comparator, target and lineage storage IDs are deliberately
    absent.  They remain in the enclosing receipt solely as execution and
    replay joins.
    """

    return {
        "policy_sha256": receipt.policy_sha256,
        "scheduler_cell_sha256": receipt.request.cell.scheduler_key_sha256,
        "cursor_before": _scheduler_cursor_projection(receipt.cursor_before),
        "proposal_counter_state_before_sha256": (
            receipt.proposal_counter_state_before_sha256
        ),
        "candidate_counter_witnesses": receipt.candidate_counter_witnesses,
        "candidate_universe_sha256": receipt.candidate_universe_sha256,
        "candidate_slate": tuple(
            _scheduler_candidate_snapshot_projection(item)
            for item in receipt.candidate_manifest
        ),
        "selection_mode": receipt.selection_mode,
        "selected_target_factor_key_sha256": (
            receipt.selected_target_factor_key_sha256
        ),
        "selected_target_content_sha256": receipt.selected_target_content_sha256,
        "selected_lineage_niche_sha256": receipt.selected_lineage_niche_sha256,
        "target_cap_waiver_reason": receipt.target_cap_waiver_reason,
        "lineage_cap_waiver_reason": receipt.lineage_cap_waiver_reason,
        "projected_cursor": _scheduler_cursor_projection(receipt.projected_cursor),
        "projected_counter_delta": receipt.projected_counter_delta,
    }


def _proposal_scheduler_decision_sha256(receipt: ProposalReceiptV1) -> str:
    return _sha256(proposal_scheduler_decision_projection(receipt))


def _summarize(
    candidate: PortableCandidateV1,
    policy: EdgeProposalPolicyV1,
    *,
    current_background_sha256: str,
) -> PairProposalSummaryV1:
    counts = Counter(item.sign for item in candidate.background_signs)
    benefit = counts["benefit"]
    null = counts["null"]
    harm = counts["harm"]
    # Cross-background harm is contradictory prior evidence, not a hard veto.
    # Counting it in the denominator keeps transfer conservative without
    # suppressing a new comparator-conditioned experiment.
    denominator = benefit + null + harm
    fraction = 0 if denominator == 0 else benefit * 1_000_000 // denominator
    current = next(
        (
            item.sign
            for item in candidate.background_signs
            if item.fixed_background_sha256 == current_background_sha256
        ),
        None,
    )
    scientific = [
        item.sign for item in candidate.background_signs if item.sign != "infrastructure"
    ]
    if current == "harm":
        proposal_class: ProposalClass = "veto"
    elif (
        benefit >= policy.min_positive_backgrounds
        and benefit * policy.sign_quorum_denominator
        >= denominator * policy.sign_quorum_numerator
    ):
        proposal_class = "transferable"
    elif (
        len(scientific) >= policy.max_all_zero_backgrounds
        and all(sign == "all_zero" for sign in scientific)
    ):
        proposal_class = "all_zero_exhausted"
    else:
        proposal_class = "unknown"
    return PairProposalSummaryV1(
        evidence_root_sha256=_sha256(candidate.background_signs),
        benefit_background_count=benefit,
        null_background_count=null,
        all_zero_background_count=counts["all_zero"],
        infrastructure_background_count=counts["infrastructure"],
        harm_background_count=harm,
        current_background_sign=current,
        positive_fraction_micropoints=fraction,
        proposal_class=proposal_class,
    )


def _history_counts(
    history: Sequence[ProposalHistoryEntryV1],
) -> tuple[Counter[str], Counter[str]]:
    return (
        Counter(item.target_factor_key_sha256 for item in history),
        Counter(item.lineage_niche_sha256 for item in history),
    )


def _project_entries(
    history: Sequence[ProposalHistoryEntryV1],
    entry: ProposalHistoryEntryV1,
    window: int,
) -> tuple[ProposalHistoryEntryV1, ...]:
    projected = tuple(history) + (entry,)
    return projected[-window:]


def _scheduler_history_entry_projection(
    entry: ProposalHistoryEntryV1,
) -> dict[str, Any]:
    return {
        "decision_ordinal": entry.decision_ordinal,
        "selection_ordinal": entry.selection_ordinal,
        "target_factor_key_sha256": entry.target_factor_key_sha256,
        "target_content_sha256": entry.target_content_sha256,
        "lineage_niche_sha256": entry.lineage_niche_sha256,
        "proposal_class": entry.proposal_class,
        "selection_mode": entry.selection_mode,
    }


def _warmup_balanced(counts: Counter[str], universe: Sequence[str]) -> bool:
    values = [counts[item] for item in sorted(set(universe))]
    return not values or max(values) - min(values) <= 1


def _mature_half_cap(counts: Counter[str], n: int) -> bool:
    return not counts or max(counts.values()) * 2 <= n


def _cap_admissible(
    *,
    cursor: ProposalCursorV1,
    entry: ProposalHistoryEntryV1,
    target_universe: Sequence[str],
    lineage_universe: Sequence[str],
    policy: EdgeProposalPolicyV1,
) -> tuple[bool, bool]:
    projected = _project_entries(cursor.last50, entry, policy.exposure_window)
    target_counts, lineage_counts = _history_counts(projected)
    mature = len(projected) == policy.exposure_window
    if mature:
        target_ok = _mature_half_cap(target_counts, len(projected))
    elif len(set(target_universe)) <= 1:
        target_ok = True
    else:
        target_ok = _warmup_balanced(target_counts, target_universe)
    if mature:
        lineage_ok = _mature_half_cap(lineage_counts, len(projected))
    elif len(set(lineage_universe)) <= 1:
        lineage_ok = True
    else:
        lineage_ok = _warmup_balanced(lineage_counts, lineage_universe)
    return target_ok, lineage_ok


def _counter_map(
    witnesses: Sequence[CandidateCounterWitnessV1],
) -> dict[str, CandidateCounterWitnessV1]:
    return {
        item.target_factor_key_sha256: item
        for item in witnesses
    }


def _history_entry(
    *,
    cursor: ProposalCursorV1,
    candidate: PortableCandidateV1,
    summary: PairProposalSummaryV1,
    mode: SelectionMode,
) -> ProposalHistoryEntryV1:
    if summary.proposal_class not in {"transferable", "unknown"}:
        raise ValueError("only safe proposal classes can enter selected history")
    if mode == "no_safe_reuse":
        raise ValueError("no-safe decisions cannot enter selected history")
    return ProposalHistoryEntryV1(
        decision_ordinal=cursor.lifetime_ordinal,
        selection_ordinal=cursor.lifetime_selection_count,
        target_revision_id=candidate.target_revision_id,
        target_factor_key_sha256=candidate.target_factor_key_sha256,
        target_content_sha256=candidate.target_content_sha256,
        lineage_niche_sha256=candidate.lineage_niche.exposure_key_sha256,
        proposal_class=summary.proposal_class,
        selection_mode=mode,
    )


def _project_cursor(
    cursor: ProposalCursorV1,
    *,
    entry: ProposalHistoryEntryV1 | None,
) -> ProposalCursorV1:
    if entry is None:
        return cursor.model_copy(update={"lifetime_ordinal": cursor.lifetime_ordinal + 1})

    history = tuple(cursor.last50)
    archived_root = cursor.archived_history_sha256
    if len(history) == 50:
        archived_root = _sha256(
            {
                "previous_archived_history_sha256": archived_root,
                "evicted_entry": _scheduler_history_entry_projection(
                    history[0]
                ),
            }
        )
    projected = _project_entries(history, entry, 50)
    return ProposalCursorV1(
        cell_sha256=cursor.cell_sha256,
        lifetime_ordinal=cursor.lifetime_ordinal + 1,
        lifetime_selection_count=cursor.lifetime_selection_count + 1,
        archived_history_sha256=archived_root,
        last50=projected,
    )


def _receipt_payload(receipt: ProposalReceiptV1) -> dict[str, Any]:
    payload = receipt.model_dump(mode="json")
    payload.pop("receipt_id", None)
    return payload


def _receipt_id(receipt: ProposalReceiptV1) -> str:
    return f"sft-proposal:{_sha256(_receipt_payload(receipt))[:24]}"


def _tie_sha(
    *,
    proposal_input: SFTProposalInputV1,
    manifest_sha256: str,
    candidate: PortableCandidateV1,
) -> str:
    return _sha256(
        {
            "public_seed": proposal_input.policy.public_seed,
            "scheduler_cell_sha256": (
                proposal_input.request.cell.scheduler_key_sha256
            ),
            "lifetime_ordinal": proposal_input.cursor.lifetime_ordinal,
            "lifetime_selection_count": (
                proposal_input.cursor.lifetime_selection_count
            ),
            "archived_history_sha256": (
                proposal_input.cursor.archived_history_sha256
            ),
            "last50": tuple(
                _scheduler_history_entry_projection(item)
                for item in proposal_input.cursor.last50
            ),
            "proposal_counter_state_sha256": (
                proposal_input.proposal_counter_state_sha256
            ),
            "candidate_counter_witnesses": (
                proposal_input.candidate_counter_witnesses
            ),
            "candidate_manifest_sha256": manifest_sha256,
            "candidate": _scheduler_candidate_projection(candidate),
        }
    )


def select_exact_edge_proposal(proposal_input: SFTProposalInputV1) -> ProposalReceiptV1:
    """Select one target without state mutation, similarity, randomness, or LLMs.

    With the schema bounds ``m<=16`` and ``W<=50``, deriving all summaries,
    exact projected-window caps and rank keys costs ``O(m*W)`` time and
    ``O(m+W)`` auxiliary space.
    """

    policy = proposal_input.policy
    cursor = proposal_input.cursor
    candidates = tuple(
        sorted(
            (_canonical_candidate(item) for item in proposal_input.candidates),
            key=lambda item: item.target_factor_key_sha256,
        )
    )
    summaries = {
        item.target_revision_id: _summarize(
            item,
            policy,
            current_background_sha256=(
                proposal_input.request.cell.canonical_background_sha256
            ),
        )
        for item in candidates
    }
    counters = _counter_map(proposal_input.candidate_counter_witnesses)
    target_counts, lineage_counts = _history_counts(cursor.last50)

    base_safe = [
        item
        for item in candidates
        if summaries[item.target_revision_id].proposal_class
        not in {"veto", "all_zero_exhausted"}
    ]
    sole_unknown_id: str | None = None
    retired_keys: set[str] = set()
    if len(base_safe) == 1:
        only = base_safe[0]
        if summaries[only.target_revision_id].proposal_class == "unknown":
            sole_unknown_id = only.target_factor_key_sha256
            used = counters[
                only.target_factor_key_sha256
            ].single_safe_unknown_selection_count
            if used >= policy.max_single_safe_unknown_uses:
                retired_keys.add(only.target_factor_key_sha256)

    safe = [
        item
        for item in base_safe
        if item.target_factor_key_sha256 not in retired_keys
    ]
    target_universe = [item.target_factor_key_sha256 for item in safe]
    lineage_universe = [
        item.lineage_niche.exposure_key_sha256 for item in safe
    ]

    # The manifest hash used by the public tiebreak intentionally excludes the
    # tiebreak itself.  It freezes the canonical raw universe and pair signs.
    raw_manifest_sha256 = _sha256(
        tuple(
            {
                "candidate": _scheduler_candidate_projection(item),
                "pair_summary": summaries[item.target_revision_id],
            }
            for item in candidates
        )
    )

    cap_results: dict[str, tuple[bool, bool]] = {}
    tie_hashes: dict[str, str] = {}
    for candidate in candidates:
        summary = summaries[candidate.target_revision_id]
        tie_hashes[candidate.target_revision_id] = _tie_sha(
            proposal_input=proposal_input,
            manifest_sha256=raw_manifest_sha256,
            candidate=candidate,
        )
        if candidate not in safe:
            cap_results[candidate.target_revision_id] = (False, False)
            continue
        provisional = _history_entry(
            cursor=cursor,
            candidate=candidate,
            summary=summary,
            mode="structured_exploration",
        )
        cap_results[candidate.target_revision_id] = _cap_admissible(
            cursor=cursor,
            entry=provisional,
            target_universe=target_universe,
            lineage_universe=lineage_universe,
            policy=policy,
        )

    manifest = tuple(
        ProposalCandidateSnapshotV1(
            candidate=item,
            pair_summary=summaries[item.target_revision_id],
            target_selection_count_before=target_counts[
                item.target_factor_key_sha256
            ],
            lineage_selection_count_before=lineage_counts[
                item.lineage_niche.exposure_key_sha256
            ],
            unknown_selection_count_before=(
                counters[item.target_factor_key_sha256].unknown_selection_count
            ),
            single_safe_unknown_selection_count_before=(
                counters[item.target_factor_key_sha256]
                .single_safe_unknown_selection_count
            ),
            target_cap_admissible=cap_results[item.target_revision_id][0],
            lineage_cap_admissible=cap_results[item.target_revision_id][1],
            retirement_reason=(
                "sole_unknown_lifetime_exhausted"
                if item.target_factor_key_sha256 in retired_keys
                else None
            ),
            seeded_tiebreak_sha256=tie_hashes[item.target_revision_id],
        )
        for item in candidates
    )
    manifest_sha256 = _sha256(manifest)
    admissible = [
        item
        for item in manifest
        if item.target_cap_admissible and item.lineage_cap_admissible
    ]

    selected: ProposalCandidateSnapshotV1 | None
    exploration = (
        cursor.lifetime_ordinal < policy.initial_exploration_decisions
        or cursor.lifetime_ordinal % policy.exploration_period
        == policy.exploration_period - 1
    )

    def exploration_key(item: ProposalCandidateSnapshotV1) -> tuple[Any, ...]:
        class_priority = 0 if item.pair_summary.proposal_class == "unknown" else 1
        return (
            item.target_selection_count_before,
            item.lineage_selection_count_before,
            class_priority,
            item.seeded_tiebreak_sha256,
        )

    if not admissible:
        selected = None
        mode: SelectionMode = "no_safe_reuse"
    elif exploration:
        selected = min(admissible, key=exploration_key)
        mode = "structured_exploration"
    else:
        transferable = [
            item for item in admissible if item.pair_summary.proposal_class == "transferable"
        ]
        if transferable:
            selected = max(
                transferable,
                key=lambda item: (
                    item.pair_summary.benefit_background_count,
                    item.pair_summary.positive_fraction_micropoints,
                    -item.target_selection_count_before,
                    -item.lineage_selection_count_before,
                    item.seeded_tiebreak_sha256,
                ),
            )
            mode = "portable_exploitation"
        else:
            selected = min(admissible, key=exploration_key)
            mode = "no_portable_support_fallback"

    if selected is None:
        projected_cursor = _project_cursor(
            cursor,
            entry=None,
        )
        selected_id = selected_key = selected_content = selected_lineage = None
        target_waiver = lineage_waiver = None
        projected_counter_delta = None
    else:
        entry = _history_entry(
            cursor=cursor,
            candidate=selected.candidate,
            summary=selected.pair_summary,
            mode=mode,
        )
        projected_cursor = _project_cursor(
            cursor,
            entry=entry,
        )
        selected_id = selected.candidate.target_revision_id
        selected_key = selected.candidate.target_factor_key_sha256
        selected_content = selected.candidate.target_content_sha256
        selected_lineage = (
            selected.candidate.lineage_niche.exposure_key_sha256
        )
        mature_projection = len(projected_cursor.last50) == policy.exposure_window
        target_waiver = (
            "single_safe_target"
            if not mature_projection and len(target_universe) == 1
            else None
        )
        lineage_waiver = (
            "single_safe_lineage"
            if not mature_projection and len(set(lineage_universe)) == 1
            else None
        )
        projected_counter_delta = (
            ProposalCounterDeltaV1(
                cell_sha256=proposal_input.request.cell.scheduler_key_sha256,
                target_factor_key_sha256=(
                    selected.candidate.target_factor_key_sha256
                ),
                single_safe_unknown_selection_increment=int(
                    selected.candidate.target_factor_key_sha256
                    == sole_unknown_id
                ),
            )
            if selected.pair_summary.proposal_class == "unknown"
            else None
        )

    fields = dict(
        request=proposal_input.request,
        policy=policy,
        policy_sha256=policy.digest,
        cursor_before=cursor,
        cursor_before_sha256=cursor.digest,
        proposal_counter_state_before_sha256=(
            proposal_input.proposal_counter_state_sha256
        ),
        candidate_counter_witnesses=(
            proposal_input.candidate_counter_witnesses
        ),
        candidate_counter_witnesses_sha256=_sha256(
            proposal_input.candidate_counter_witnesses
        ),
        candidate_manifest=manifest,
        candidate_manifest_sha256=manifest_sha256,
        candidate_universe_sha256=raw_manifest_sha256,
        candidate_slate_scheduler_sha256=_sha256(
            tuple(_scheduler_candidate_snapshot_projection(item) for item in manifest)
        ),
        selection_mode=mode,
        selected_target_revision_id=selected_id,
        selected_target_factor_key_sha256=selected_key,
        selected_target_content_sha256=selected_content,
        selected_lineage_niche_sha256=selected_lineage,
        target_cap_waiver_reason=target_waiver,
        lineage_cap_waiver_reason=lineage_waiver,
        projected_cursor=projected_cursor,
        projected_history_sha256=_sha256(projected_cursor.last50),
        projected_counter_delta=projected_counter_delta,
    )
    # Construct without validation to derive the scheduler digest and then the
    # exact self-excluding identity.  The authoritative construction validates
    # both closures and the independent input/receipt byte caps.
    scheduler_draft = ProposalReceiptV1.model_construct(
        receipt_id="draft:receipt",
        proposal_scheduler_decision_sha256="0" * 64,
        **fields,
    )
    fields["proposal_scheduler_decision_sha256"] = (
        _proposal_scheduler_decision_sha256(scheduler_draft)
    )
    receipt_draft = ProposalReceiptV1.model_construct(
        receipt_id="draft:receipt",
        **fields,
    )
    return ProposalReceiptV1(receipt_id=_receipt_id(receipt_draft), **fields)


def _reserved_join_id(label: str, ordinal: int) -> str:
    stem = f"{label}:{ordinal}:"
    if len(stem) > MAX_EXACT_JOIN_ID_CHARS:
        raise ValueError("reserved exact-join identifier prefix is too long")
    return stem + "x" * (MAX_EXACT_JOIN_ID_CHARS - len(stem))


def proposal_slate_fits_byte_bounds(
    *,
    request: ProposalRequestV1,
    cursor: ProposalCursorV1,
    candidates: Sequence[PortableCandidateV1],
    proposal_counter_state_sha256: str,
    candidate_counter_witnesses: Sequence[CandidateCounterWitnessV1],
    policy: EdgeProposalPolicyV1 | None = None,
) -> bool:
    """Dry-run both byte caps with fixed worst-case exact join identifiers.

    Candidate admission must not depend on the current spelling or length of a
    comparator, target, lineage or opportunity storage ID.  Every such join is
    therefore replaced by a valid 128-character reservation before constructing
    the bounded input and its receipt.  All scheduler-visible canonical fields
    remain unchanged.
    """

    reserved_cell = request.cell.model_copy(
        update={"from_revision_id": _reserved_join_id("from", 0)}
    )
    reserved_request = request.model_copy(
        update={
            "opportunity_id": _reserved_join_id("opportunity", 0),
            "cell": reserved_cell,
        }
    )
    reserved_cursor = cursor.model_copy(
        update={
            "last50": tuple(
                item.model_copy(
                    update={"target_revision_id": _reserved_join_id("history", index)}
                )
                for index, item in enumerate(cursor.last50)
            )
        }
    )
    reserved_candidates = tuple(
        candidate.model_copy(
            update={
                "target_revision_id": _reserved_join_id("target", index),
                "lineage_niche": candidate.lineage_niche.model_copy(
                    update={
                        "root_revision_id": _reserved_join_id("lineage", index)
                    }
                ),
            }
        )
        for index, candidate in enumerate(candidates)
    )
    witness_by_target = {
        item.target_factor_key_sha256: item
        for item in candidate_counter_witnesses
    }
    candidate_keys = sorted(
        item.target_factor_key_sha256 for item in reserved_candidates
    )
    if len(witness_by_target) != len(candidate_counter_witnesses) or (
        sorted(witness_by_target) != candidate_keys
    ):
        raise ValueError(
            "counter witnesses must exactly cover byte-dry-run candidates"
        )
    reserved_witnesses = tuple(
        witness_by_target[item.target_factor_key_sha256]
        for item in sorted(
            reserved_candidates,
            key=lambda item: item.target_factor_key_sha256,
        )
    )
    try:
        reserved_input = SFTProposalInputV1(
            request=reserved_request,
            policy=policy or EdgeProposalPolicyV1(),
            cursor=reserved_cursor,
            candidates=reserved_candidates,
            proposal_counter_state_sha256=proposal_counter_state_sha256,
            candidate_counter_witnesses=reserved_witnesses,
        )
        select_exact_edge_proposal(reserved_input)
    except ValueError as exc:
        message = str(exc)
        if (
            "canonical proposal input exceeds 65536 bytes" in message
            or "canonical proposal receipt exceeds 65536 bytes" in message
        ):
            return False
        raise
    return True


def replay_validate_proposal_receipt(receipt: ProposalReceiptV1) -> ProposalReceiptV1:
    """Recompute a receipt byte-for-byte from its frozen manifest and cursor."""

    if len(_canonical_json(receipt).encode("utf-8")) > MAX_PROPOSAL_RECEIPT_BYTES:
        raise ProposalReplayError("canonical proposal receipt exceeds 65536 bytes")
    replay_input = SFTProposalInputV1(
        request=receipt.request,
        policy=receipt.policy,
        cursor=receipt.cursor_before,
        candidates=tuple(item.candidate for item in receipt.candidate_manifest),
        proposal_counter_state_sha256=(
            receipt.proposal_counter_state_before_sha256
        ),
        candidate_counter_witnesses=receipt.candidate_counter_witnesses,
    )
    expected = select_exact_edge_proposal(replay_input)
    if expected.model_dump(mode="json") != receipt.model_dump(mode="json"):
        raise ProposalReplayError("proposal receipt does not replay byte-for-byte")
    return receipt


__all__ = [
    "CandidateCounterWitnessV1",
    "EdgeProposalPolicyV1",
    "ExactFactorLocusV1",
    "ExactProposalCellV1",
    "LineageNicheV1",
    "MAX_EXACT_JOIN_ID_CHARS",
    "MAX_PROPOSAL_INPUT_BYTES",
    "MAX_PROPOSAL_RECEIPT_BYTES",
    "PairProposalSummaryV1",
    "PortableBackgroundSignV1",
    "PortableCandidateV1",
    "ProposalCounterDeltaV1",
    "ProposalCandidateSnapshotV1",
    "ProposalCursorV1",
    "ProposalHistoryEntryV1",
    "ProposalReceiptV1",
    "ProposalReplayError",
    "ProposalRequestV1",
    "SFTProposalInputV1",
    "proposal_scheduler_decision_projection",
    "proposal_counter_state_sha256",
    "proposal_slate_fits_byte_bounds",
    "replay_validate_proposal_receipt",
    "select_exact_edge_proposal",
]
