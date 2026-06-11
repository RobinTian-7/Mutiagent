"""M1: evidence-conditioned transfer gate for skill deployment (phase 3).

A skill's executable organization may be REPLAYED onto a held-out case only
when the skill's own measured evidence shows it succeeding on tasks in the
same feature bucket (see :mod:`masbench.task_features`). When no skill in the
bank qualifies for the case's bucket, deployment ABSTAINS: the evolved arm
runs the exact cold path (empty bank, no motif prior), so on
representationally-uncovered cases it equals the baseline by construction
instead of force-replaying a mismatched organization (the P2 failure mode).

Trust demands ``n >= MIN_TRUST_ROWS`` rows in the bucket with bucket mean
exact-match ``>= MIN_TRUST_EM`` -- one lucky run cannot earn deployment
(phase-2 lesson: a 1-seed signal is a Bernoulli gate).

The ledger lives in ``skill.organization_policy["transfer_evidence"]`` as
``{bucket: {"n": int, "em_sum": float}}`` and is COMBINED (not overwritten)
across evolution rounds.

Motif credit is bucket-namespaced ("<bucket>|<motif_key>") so structural
priors learned on order-free evidence cannot bias generation on
order-sensitive cases; :func:`motif_view` projects the namespaced stats back
to raw motif keys for one bucket at deployment.
"""

from __future__ import annotations

from typing import Any

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank, is_avoid_skill

MIN_TRUST_ROWS = 2
MIN_TRUST_EM = 0.5

TRANSFER_EVIDENCE_KEY = "transfer_evidence"


def _row_em(row: dict[str, Any]) -> float:
    return float(row.get("ExactMatchRate", 0.0) or 0.0)


def build_transfer_ledger(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Per-(topology, feature bucket) success ledger from raw evolution rows.

    M6: each row also feeds a ``bucket#agg_kind`` sub-slot so trust can be
    REFINED to kind granularity when the bucket-level evidence is
    contradictory (an organization perfect on vote-kind tasks and fatal on
    count-kind tasks must not ride the bucket mean onto count cases).
    """
    ledger: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        topology = str(row.get("Topology", "") or "")
        bucket = row.get("task_features_key")
        if not topology or not bucket:
            continue
        slots = ledger.setdefault(topology, {})
        keys = [str(bucket)]
        kind = row.get("task_agg_kind")
        if kind:
            keys.append(f"{bucket}#{kind}")
        for key in keys:
            slot = slots.setdefault(key, {"n": 0, "em_sum": 0.0})
            slot["n"] += 1
            slot["em_sum"] += _row_em(row)
    return ledger


def combine_bucket_stats(
    old: dict[str, dict[str, float]] | None,
    new: dict[str, dict[str, float]] | None,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for source in (old or {}, new or {}):
        for bucket, stats in source.items():
            slot = out.setdefault(str(bucket), {"n": 0, "em_sum": 0.0})
            slot["n"] += int(stats.get("n", 0))
            slot["em_sum"] += float(stats.get("em_sum", 0.0))
    return out


def inject_transfer_evidence(
    bank: SkillBank,
    rows: list[dict[str, Any]],
    *,
    prior: dict[str, dict[str, dict[str, float]]] | None = None,
) -> None:
    """Fold this round's ledger into every skill's organization policy.

    ``prior`` maps skill_id -> bucket stats snapshotted from the inherited
    bank BEFORE this round's patches were applied (merge patches overwrite
    ``organization_policy`` keys, so cross-round accumulation happens here).
    """
    ledger = build_transfer_ledger(rows)
    for skill in bank:
        if is_avoid_skill(skill):
            continue
        if skill.organization_policy is None:
            continue
        topology = skill.organization_policy.get("topology_name") or skill.topology_name
        fresh = ledger.get(str(topology), {})
        old = (prior or {}).get(skill.skill_id)
        existing = skill.organization_policy.get(TRANSFER_EVIDENCE_KEY)
        # `existing` is whatever survived patch-merging this round; prefer the
        # explicit pre-round snapshot when given (it is the uncorrupted state).
        base = old if old is not None else existing
        combined = combine_bucket_stats(base, fresh)
        if combined:
            skill.organization_policy[TRANSFER_EVIDENCE_KEY] = combined


def snapshot_transfer_evidence(
    bank: SkillBank,
) -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for skill in bank:
        policy = skill.organization_policy or {}
        ledger = policy.get(TRANSFER_EVIDENCE_KEY)
        if isinstance(ledger, dict) and ledger:
            out[skill.skill_id] = {
                str(bucket): dict(stats) for bucket, stats in ledger.items()
            }
    return out


def _slot_passes(stats: Any) -> bool | None:
    """True/False when the slot has enough rows to judge, None otherwise."""
    if not isinstance(stats, dict):
        return None
    n = int(stats.get("n", 0))
    if n < MIN_TRUST_ROWS:
        return None
    return (float(stats.get("em_sum", 0.0)) / n) >= MIN_TRUST_EM


def _bucket_contradicted(ledger: dict[str, Any], bucket: str) -> bool:
    """M6: does this skill's evidence DISAGREE across kinds within the bucket?

    Trust lives at the coarsest granularity consistent with the evidence:
    only when one well-measured kind passes while another well-measured kind
    fails is bucket-level trust withdrawn in favor of kind-level trust.
    """
    verdicts = [
        _slot_passes(stats)
        for key, stats in ledger.items()
        if key.startswith(f"{bucket}#")
    ]
    return any(v is True for v in verdicts) and any(v is False for v in verdicts)


def skill_trusted_for(skill: SkillCard, bucket: str, kind: str | None = None) -> bool:
    policy = skill.organization_policy or {}
    ledger = policy.get(TRANSFER_EVIDENCE_KEY)
    if not isinstance(ledger, dict):
        return False
    if _slot_passes(ledger.get(bucket)) is not True:
        return False
    if kind and _bucket_contradicted(ledger, bucket):
        # Kind-sensitive organization: only its measured winning kinds stay
        # trusted; the case's kind must pass on its own evidence.
        return _slot_passes(ledger.get(f"{bucket}#{kind}")) is True
    return True


def deployment_view(
    bank: SkillBank,
    motif_stats: dict[str, dict] | None,
    bucket: str,
    *,
    kind: str | None = None,
    mode: str = "feature",
) -> tuple[SkillBank, dict[str, dict] | None, bool]:
    """The per-case (bank, motif, abstained) actually handed to generation.

    ``mode="off"`` reproduces phase-2 behavior (full bank, full motif).
    Abstention returns an EMPTY bank and ``None`` motif -- byte-equal inputs
    to the cold baseline path.
    """
    if mode == "off" or len(bank) == 0:
        return bank, motif_stats, False
    trusted = [
        skill for skill in bank
        if not is_avoid_skill(skill) and skill_trusted_for(skill, bucket, kind)
    ]
    if not trusted:
        return SkillBank(), None, True
    view = SkillBank(skills=[skill.model_copy(deep=True) for skill in trusted])
    return view, motif_view(motif_stats, bucket), False


def namespace_motif_keys(keys: list[str], bucket: str) -> list[str]:
    return [f"{bucket}|{key}" for key in keys]


def motif_view(
    motif_stats: dict[str, dict] | None,
    bucket: str,
) -> dict[str, dict] | None:
    """Project bucket-namespaced motif stats back to raw keys for one bucket.

    Non-namespaced keys (legacy stats) are dropped under the feature gate --
    they carry no bucket provenance, so they must not bias other buckets.
    """
    if not motif_stats:
        return motif_stats
    prefix = f"{bucket}|"
    out = {
        key[len(prefix):]: dict(value)
        for key, value in motif_stats.items()
        if key.startswith(prefix)
    }
    return out or None
