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
from exp_graph.mas.topology_equivalence import fingerprint_protocol_spec
from exp_graph.protocols import ProtocolGraphSpec

MIN_TRUST_ROWS = 2
MIN_TRUST_EM = 0.5

TRANSFER_EVIDENCE_KEY = "transfer_evidence"


def _row_em(row: dict[str, Any]) -> float:
    """Trust-ledger success value for one row.

    M21 (jssp-easy forensics): binary exact-match is the wrong trust
    currency on quality-graded benchmarks -- a 23%-quality schedule counts
    as total failure, so the learner can never earn deployment trust and
    abstains forever. Rows carry ``MeanPrimaryMetric`` (the benchmark's own
    primary success in [0,1]); prefer it when present. On Silo the two
    fields are equal by construction (pinned by test), so Silo ledgers are
    byte-identical; on JSSP trust becomes graded (quality accrues credit).
    """
    pm = row.get("MeanPrimaryMetric")
    if pm is not None:
        try:
            return float(pm)
        except (TypeError, ValueError):
            pass
    return float(row.get("ExactMatchRate", 0.0) or 0.0)


def bank_state_hash(bank: SkillBank, motif_stats: dict | None = None) -> str:
    """Deterministic content hash of (bank, motif) — the resume-cache key part.

    Two runs holding byte-identical learned state are the same measurement
    condition at temperature 0; M18 keys deployment-phase rows on this so an
    interrupted judge run can be relaunched and replay its finished pairs.
    """
    import hashlib
    import json as _json

    payload = {
        "skills": sorted(
            (_json.dumps(s.model_dump(mode="json"), sort_keys=True) for s in bank),
        ),
        "motif": motif_stats or {},
    }
    return hashlib.sha256(
        _json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def spec_struct_hash(spec_data: Any) -> str | None:
    """M11: structural identity of an executed organization.

    Generated organizations carry per-run NAMES, so a name-keyed ledger
    splits one structure's successes into n=1 fragments that never reach the
    trust bar (dev-5 gen forensics). Identity = the repo's
    topology-equivalence hash of the executed spec; the name is a label.
    """
    if not isinstance(spec_data, dict) or not spec_data.get("steps"):
        return None
    try:
        spec = ProtocolGraphSpec.model_validate(spec_data)
        return fingerprint_protocol_spec(spec).topology_equivalence_hash
    except Exception:
        return None


def _row_identity(row: dict[str, Any]) -> str | None:
    """Ledger identity for a row: structural hash, else topology name."""
    h = spec_struct_hash(row.get("protocol_spec"))
    if h:
        return h
    topology = str(row.get("Topology", "") or "")
    return topology or None


def skill_identity(skill: SkillCard) -> str | None:
    policy = skill.organization_policy or {}
    h = spec_struct_hash(policy.get("protocol_spec"))
    if h:
        return h
    topology = policy.get("topology_name") or skill.topology_name
    return str(topology) if topology else None


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
        identity = _row_identity(row)
        bucket = row.get("task_features_key")
        if not identity or not bucket:
            continue
        slots = ledger.setdefault(identity, {})
        keys = [str(bucket)]
        # M12/M16: the sub-slot key is the pair of MECHANISTIC bits the old
        # agg-kind taxonomy proxied -- does correctness survive local
        # summarization, and is the answer a single value or a composite
        # structure needing assembly. Robust to classify, fast to
        # accumulate, and they separate every measured failure mode
        # (vote-vs-count bimodality; scalar II-13/15 preserve vs composite
        # II-17/19 needing Modify).
        lossless = row.get("task_needs_lossless")
        if lossless is not None:
            shape = "composite" if row.get("task_answer_composite") else "scalar"
            keys.append(
                f"{bucket}#{'lossless' if lossless else 'lossy'}-{shape}"
            )
        case_id = row.get("case_id")
        for key in keys:
            slot = slots.setdefault(key, {"n": 0, "em_sum": 0.0})
            slot["n"] += 1
            slot["em_sum"] += _row_em(row)
            # M19: distinct-case provenance -- seeds of one case are not
            # transfer evidence (capped; diversity thresholds are tiny).
            if case_id is not None:
                cases = slot.setdefault("cases", [])
                if str(case_id) not in cases and len(cases) < 16:
                    cases.append(str(case_id))
                    cases.sort()
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
            incoming = stats.get("cases")
            if isinstance(incoming, list) and incoming:
                cases = slot.setdefault("cases", [])
                for c in incoming:
                    if str(c) not in cases and len(cases) < 16:
                        cases.append(str(c))
                cases.sort()
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
        identity = skill_identity(skill)
        # Structural identity first (M11); name kept as a secondary match so
        # named-topology skills whose stored spec failed to parse still
        # accumulate.
        fresh = ledger.get(identity or "", {})
        if not fresh:
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
            # M19a: stamp global distinct-case diversity for retrieval-side
            # pessimism (exp-graph reads expected_tradeoff.evidence_case_count;
            # CF cards never get here, so CF ranking is untouched).
            all_cases: set[str] = set()
            bare_n = 0
            for key, stats in combined.items():
                if "#" in key or not isinstance(stats, dict):
                    continue
                cases = stats.get("cases")
                if isinstance(cases, list):
                    all_cases.update(str(c) for c in cases)
                elif int(stats.get("n", 0)) > 0:
                    bare_n = 1
            count = len(all_cases) if all_cases else bare_n
            if count and isinstance(skill.expected_tradeoff, dict):
                skill.expected_tradeoff["evidence_case_count"] = count


def _ledger_total_n(skill: SkillCard) -> int:
    policy = skill.organization_policy or {}
    ledger = policy.get(TRANSFER_EVIDENCE_KEY)
    if not isinstance(ledger, dict):
        return 0
    return sum(
        int(stats.get("n", 0))
        for key, stats in ledger.items()
        if isinstance(stats, dict) and "#" not in key
    )


def merge_structural_duplicates(bank: SkillBank) -> int:
    """M11/M13c: one structure = one skill family; duplicates merge.

    Generated organizations re-enter the bank each round under fresh names;
    without this the bank grows linearly (dev rounds: 9 -> 13 -> 15) and one
    structure's trust evidence stays fragmented. Among same-identity
    selectable skills the most-evidenced card survives; ledgers combine; the
    survivor's organization_policy records the absorbed ids. Returns the
    number of cards removed.
    """
    by_identity: dict[str, list[SkillCard]] = {}
    for skill in list(bank):
        if is_avoid_skill(skill):
            continue
        identity = skill_identity(skill)
        if identity:
            by_identity.setdefault(identity, []).append(skill)
    removed = 0
    for identity, group in by_identity.items():
        if len(group) < 2:
            continue
        group.sort(key=_ledger_total_n, reverse=True)
        survivor, rest = group[0], group[1:]
        policy = survivor.organization_policy or {}
        combined = policy.get(TRANSFER_EVIDENCE_KEY)
        absorbed = list(policy.get("absorbed_skill_ids") or [])
        for dup in rest:
            dup_ledger = (dup.organization_policy or {}).get(TRANSFER_EVIDENCE_KEY)
            combined = combine_bucket_stats(combined, dup_ledger)
            absorbed.append(dup.skill_id)
            bank.skills.pop(dup.skill_id, None)
            removed += 1
        if combined:
            policy[TRANSFER_EVIDENCE_KEY] = combined
        policy["absorbed_skill_ids"] = absorbed
        policy.setdefault("structural_identity", identity)
    return removed


def stamp_rule_actions(bank: SkillBank) -> None:
    """M13: make the design-rule ACTION explicit on every card.

    Paper vocabulary (operator thesis): each rule carries Preserve / Modify
    / Avoid. Avoid cards -> "avoid"; executable-spec cards -> "preserve"
    (deployment may upgrade to Modify by rewriting per-step instructions for
    the live task -- M9); prose-only cards -> "context".
    """
    for skill in bank:
        policy = skill.organization_policy
        if policy is None:
            continue
        if is_avoid_skill(skill):
            policy["rule_action"] = "avoid"
        elif isinstance(policy.get("protocol_spec"), dict) and (
            policy["protocol_spec"] or {}
        ).get("steps"):
            policy["rule_action"] = "preserve"
        else:
            policy["rule_action"] = "context"


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


def slot_case_diversity(stats: Any) -> int:
    """Distinct evidenced cases behind a slot.

    M19 (dev-11): seeds of one case are correlated draws, not transfer
    evidence. Slots that predate case tracking (e.g. recipe cards'
    pre-seeded verification stats) conservatively count as ONE case when
    they have rows at all.
    """
    if not isinstance(stats, dict):
        return 0
    cases = stats.get("cases")
    if isinstance(cases, list):
        return len({str(c) for c in cases})
    return 1 if int(stats.get("n", 0)) > 0 else 0


def _ledger_case_diversity(ledger: dict[str, Any]) -> int | None:
    """Global distinct-case count across a skill's whole ledger.

    Returns None when NO slot carries case provenance (ledger predates M19
    tracking) so callers can keep legacy behavior for old snapshots.
    """
    cases: set[str] = set()
    tracked = False
    for stats in ledger.values():
        if not isinstance(stats, dict):
            continue
        slot_cases = stats.get("cases")
        if isinstance(slot_cases, list):
            tracked = True
            cases.update(str(c) for c in slot_cases)
    if not tracked:
        return None
    return len(cases)


# M8: extrapolating trust to a sub-slot the skill was never measured on
# demands BREADTH -- every measured sub-slot passing and at least this many
# of them. With M12's binary slots (lossless/lossy) this means: a skill with
# evidence on only ONE bit is trusted only for that bit; extrapolating to
# the other bit requires both measured-and-passing, i.e. it never happens
# blindly. "No contradiction" alone is not consistency when the evidence is
# narrow (dev round 3's inverted epistemics).
BUCKET_TRUST_MIN_KINDS = 2


def skill_trusted_for(skill: SkillCard, bucket: str, kind: str | None = None) -> bool:
    """Trust = measured competence at the finest available granularity.

    1. The bucket aggregate must pass (sanity floor).
    2. Direct kind evidence decides when it exists (pass -> trust,
       well-measured fail -> no trust).
    3. Extrapolation to an UNMEASURED kind requires breadth: >=
       ``BUCKET_TRUST_MIN_KINDS`` kinds passing and none failing.
    4. Ledgers with no kind sub-slots at all (legacy cards) keep plain
       bucket-level semantics.
    """
    policy = skill.organization_policy or {}
    ledger = policy.get(TRANSFER_EVIDENCE_KEY)
    if not isinstance(ledger, dict):
        return False
    if _slot_passes(ledger.get(bucket)) is not True:
        return False
    sub = {
        key.split("#", 1)[1]: _slot_passes(stats)
        for key, stats in ledger.items()
        if key.startswith(f"{bucket}#")
    }
    if not sub:
        return True  # legacy ledger: bucket-level semantics
    if kind:
        direct = sub.get(kind)
        if direct is not None:
            return direct
        # M16b: the two bits extrapolate differently. LOSSLESSNESS is a
        # capability boundary -- never crossed. SHAPE is an adaptation
        # boundary -- the shape-sibling slot (same losslessness, other
        # shape) authorizes deployment, and because direct evidence is
        # absent the M14 action is automatically MODIFY (rewrite the role
        # instructions for assembly). Without this, train pools whose cases
        # are all one shape starve every composite slot (dev-10b: 16/24
        # abstentions, the Modify path never fired).
        if "-" in kind:
            lossless_part, shape_part = kind.rsplit("-", 1)
            sibling_shape = "scalar" if shape_part == "composite" else "composite"
            sibling = sub.get(f"{lossless_part}-{sibling_shape}")
            if sibling is False:
                # do-no-harm: a measured failure blocks at ANY diversity
                return False
            if sibling is True:
                # M19 (dev-11): a POSITIVE verdict may only extrapolate when
                # the artifact has been exercised on >=2 distinct cases
                # ANYWHERE (global robustness prior). A recipe verified 2x on
                # one train case rode this hop onto every composite test case
                # and zeroed the curve; one_peer keeps the hop through its
                # multi-case 'of' evidence (the dev-10c winning path). The
                # single-anchor geometry makes PER-SLOT diversity impossible
                # (II-13 is the only learnable os case), so the gate is
                # global, and ledgers predating case tracking keep legacy
                # behavior.
                if _ledger_case_diversity(ledger) is None:
                    return True
                if (_ledger_case_diversity(ledger) or 0) >= 2:
                    return True
    passing = sum(1 for v in sub.values() if v is True)
    failing = any(v is False for v in sub.values())
    return passing >= BUCKET_TRUST_MIN_KINDS and not failing


def deployment_view(
    bank: SkillBank,
    motif_stats: dict[str, dict] | None,
    bucket: str,
    *,
    kind: str | None = None,
    mode: str = "feature",
    fallback_tier: bool = False,
) -> tuple[SkillBank, dict[str, dict] | None, bool, str]:
    """The per-case (bank, motif, abstained, tier) handed to generation.

    Tiers (operator bar raise: vs fixed-best, abstention BLEEDS pairs):
    ``kind``   -- skills with direct evidence for the case's slot (replay);
    ``bucket`` -- no slot evidence, but broad-uniform bucket generalists
                  exist (M8 breadth) and ``fallback_tier`` is on: deploy the
                  bank's own best general organization instead of going cold
                  (parity with a strong fixed topology on uncovered cases);
    ``cold``   -- nothing trusted: EMPTY bank + None motif, byte-equal to
                  the cold baseline path (abstained=True).
    ``mode="off"`` reproduces phase-2 behavior (full bank, full motif).
    """
    if mode == "off" or len(bank) == 0:
        return bank, motif_stats, False, "off"
    trusted = [
        skill for skill in bank
        if not is_avoid_skill(skill) and skill_trusted_for(skill, bucket, kind)
    ]
    tier = "kind"
    if not trusted and fallback_tier:
        trusted = [
            skill for skill in bank
            if not is_avoid_skill(skill) and skill_trusted_for(skill, bucket, None)
        ]
        tier = "bucket"
    if not trusted:
        return SkillBank(), None, True, "cold"
    view = SkillBank(skills=[skill.model_copy(deep=True) for skill in trusted])
    # M14: evidence-conditioned action, PER SKILL. A skill whose DIRECT slot
    # evidence passes is deployed verbatim -- PRESERVE the proven artifact
    # (dev-8 4-arm: unconditional rewriting dragged a 41.7% structure to
    # 33.3%). A skill trusted only by breadth extrapolation / legacy bucket
    # semantics is transferring into unevidenced territory -- MODIFY (rewrite
    # role instructions for the live task; the floor-cracking scenario).
    for skill in view:
        policy = skill.organization_policy
        if policy is None:
            continue
        ledger = policy.get(TRANSFER_EVIDENCE_KEY) or {}
        direct = _slot_passes(ledger.get(f"{bucket}#{kind}")) if kind else None
        policy["deploy_action"] = "preserve" if direct is True else "modify"
        # M20: surface this bucket's train-verified instruction exemplar (if
        # the card carries one) so the deploy-time Modify rewrite is anchored
        # by a VERIFIED style instead of re-rolling from scratch (dev-12b/13:
        # 6-7 distinct instruction sets per 8 seeds; EM tracked the draw).
        exemplars = policy.get("instruction_exemplars")
        if isinstance(exemplars, dict):
            ex = exemplars.get(bucket)
            if isinstance(ex, dict) and isinstance(ex.get("steps"), list):
                policy["active_instruction_exemplar"] = [
                    str(s)[:300] for s in ex["steps"]
                ]
    return view, motif_view(motif_stats, bucket), False, tier


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
