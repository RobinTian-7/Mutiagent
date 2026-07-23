"""The verified-lineage training law, ported from queenbee-SFTbank.

Faithful transplant of the task-agnostic pieces of
``masbench.sft_pilot.card_train`` / ``masbench.sft_pilot.tournament``
(structure-lineage mode), so a CF campaign run here and a SiloBench campaign
run there are governed by the SAME rules:

- ``LineageBank``: immutable versions, one incumbent; a rewrite is only a
  PROPOSAL and enters the lineage as incumbent only by beating the current
  incumbent in a same-case, same-seed duel.
- ``mint_task_sequence``: hardest tier first — round 0 sets the trunk every
  later version is grafted onto, so the hardest constraint shapes it.
- ``envelope_cases``: the duel envelope is the mint case plus tier-balanced
  fill, which forces structures that generalize instead of per-task specials.
- ``review_cases`` / ``review_verdict``: a stage-1 win is a nomination, not a
  promotion — it must hold up on fresh cases the envelope never touched.
- ``seed_vote`` / ``round_verdict``: quality strictly dominates cost; cost
  speaks only when quality is level, and only beyond a 5% margin.
- ``TournamentLog``: append-only hash-chained event log; the round report is
  the checkpoint (``round_status`` / ``retire_round_dir`` implement resume).

Semantics are kept identical on purpose; only imports and docstrings differ.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CARD_SEED_BASE = 7_000
TEST_SEED_BASE = 1_000
COST_TIEBREAK_MARGIN = 0.05  # 5% cheaper/dearer decides quality ties
# Cost ceiling for promoting a quality win.  Disabled by default: quality
# dominance is unconditional — cost regressions are recoverable by later
# cost-vote wins, while a refused capability gain is a stranded opportunity.
DEFAULT_MAX_COST_INFLATION = float("inf")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False,
        separators=(",", ":"), sort_keys=True,
    )


def sha_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class TournamentLog:
    """Append-only, hash-chained decision log (host bookkeeping, auditable)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.prev_sha = "0" * 64
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    self.prev_sha = json.loads(line)["sha"]

    def append(self, event: str, payload: dict[str, Any]) -> str:
        record = {
            "event": event,
            "payload": payload,
            "prev_sha": self.prev_sha,
        }
        record["sha"] = sha_of(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        self.prev_sha = record["sha"]
        return record["sha"]


class LineageBank:
    """Single-structure verified lineage: immutable versions, one incumbent.

    A rewrite is only a PROPOSAL (challenger version); it enters the lineage
    as incumbent only by beating the current incumbent in a same-case,
    same-seed duel.  Every version — promoted, rejected, superseded — stays
    archived with its own duel record, so "is v_k better than v_1" is
    answerable from data.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.state: dict[str, Any] = {}
        if path.exists():
            self.state = json.loads(path.read_text())

    def save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2, sort_keys=True))

    def seed(
        self,
        *,
        origin: str,
        title: str,
        text: str | None = None,
        program: dict[str, Any] | None = None,
    ) -> None:
        if self.state:
            return
        self.state = {
            "origin": origin,
            "title": title,
            "incumbent": 1,
            "versions": {
                "1": {
                    "version": 1,
                    "parent": None,
                    "text": text,
                    "program": program,
                    "state": "incumbent",
                    "born_round": -1,
                    "duels": [],
                }
            },
        }
        self.save()

    def incumbent(self) -> dict[str, Any]:
        return self.state["versions"][str(self.state["incumbent"])]

    def record_duel(
        self,
        *,
        round_index: int,
        challenger_text: str | None = None,
        challenger_program: dict[str, Any] | None = None,
        verdict: str,
        votes: list[str],
    ) -> int:
        """Archive the duel and apply the promotion law; returns the
        challenger's version number.  win -> challenger becomes incumbent,
        old incumbent is superseded; anything else -> challenger rejected."""

        incumbent = self.incumbent()
        version = 1 + max(int(k) for k in self.state["versions"])
        promoted = verdict == "win"
        self.state["versions"][str(version)] = {
            "version": version,
            "parent": incumbent["version"],
            "text": challenger_text,
            "program": challenger_program,
            "state": "incumbent" if promoted else "rejected",
            "born_round": round_index,
            "duels": [
                {
                    "round": round_index,
                    "role": "challenger",
                    "verdict": verdict,
                    "votes": votes,
                }
            ],
        }
        incumbent["duels"].append(
            {
                "round": round_index,
                "role": "incumbent",
                "verdict": verdict,
                "votes": votes,
            }
        )
        if promoted:
            incumbent["state"] = "superseded"
            self.state["incumbent"] = version
        self.save()
        return version


_TIER_RANK = {"I": 1, "II": 2, "III": 3}


def tier_rank(tier: str) -> int:
    return _TIER_RANK.get(tier, len(tier))


def mint_task_sequence(
    by_tier: dict[str, list[str]], tier_order: list[str]
) -> list[str]:
    """Mint-case rotation for a serial lineage: HARDEST tier first.

    A lineage is cumulative — round 0 sets the trunk every later version is
    grafted onto, so the earliest rounds carry the most weight.  Leading
    with tier III makes the hardest constraint shape the foundation, and the
    efficiency rounds then have to preserve it.  Coverage is unchanged: each
    tier still mints equally often, just in the reverse order.
    """

    order = sorted(tier_order, key=tier_rank, reverse=True)
    sequence: list[str] = []
    depth = 0
    while any(depth < len(by_tier[tier]) for tier in order):
        for tier in order:
            if depth < len(by_tier[tier]):
                sequence.append(by_tier[tier][depth])
        depth += 1
    return sequence


def envelope_cases(
    mint_case: str,
    round_index: int,
    by_tier: dict[str, list[str]],
    tier_order: list[str],
    width: int = 6,
) -> tuple[str, ...]:
    """The duel envelope: the mint case, then filled tier-balanced.

    The challenger is minted looking at the mint case, so it plays that one
    at home; diluting its vote across a wider tier-balanced envelope is what
    forces the lineage toward structures that generalize instead of churning
    into per-task specials.  Filling always draws from the least-represented
    tier (hardest first on ties), so the mint case's own tier does not end
    up over-weighted just by leading.
    """

    mint_tier = mint_case.split("-")[0]
    cases = [mint_case]
    used = {mint_case}
    counts = {tier: 0 for tier in tier_order}
    counts[mint_tier] = counts.get(mint_tier, 0) + 1
    while len(cases) < width:
        available = [
            tier
            for tier in tier_order
            if any(case not in used for case in by_tier[tier])
        ]
        if not available:
            break
        fewest = min(counts[tier] for tier in available)
        tier = sorted(
            (tier for tier in available if counts[tier] == fewest),
            key=tier_rank,
            reverse=True,
        )[0]
        pool = [case for case in by_tier[tier] if case not in used]
        pick = pool[round_index % len(pool)]
        cases.append(pick)
        used.add(pick)
        counts[tier] += 1
    return tuple(cases)


def review_cases(
    envelope: tuple[str, ...],
    round_index: int,
    by_tier: dict[str, list[str]],
    tier_order: list[str],
    width: int = 2,
) -> tuple[str, ...]:
    """Second-stage cases: hardest tiers first, DISJOINT from the envelope.

    The envelope decides whether a challenger looks promising; this decides
    whether that held up on data the first stage never touched.  Reusing an
    envelope case would let a lucky draw carry through both stages, which is
    exactly what the review exists to catch.
    """

    used = set(envelope)
    picks: list[str] = []
    for tier in sorted(tier_order, key=tier_rank, reverse=True):
        pool = [case for case in by_tier[tier] if case not in used]
        if not pool:
            continue
        picks.append(pool[round_index % len(pool)])
        if len(picks) >= width:
            break
    return tuple(picks)


def seed_vote(candidate: dict[str, Any], baseline: dict[str, Any]) -> str:
    """Paired per-case comparison, labeled with the BASIS of the verdict.

    Returns one of: void | catastrophic | quality_win | quality_loss |
    cost_win | cost_loss | tie.  Within a case quality decides first (S,
    then stage_score); cost only speaks when quality is level, and only
    beyond a 5% margin.
    """

    if candidate.get("infra") or baseline.get("infra"):
        return "void"
    cand_fail = candidate.get("execution_class") == "algorithm_failure"
    base_fail = baseline.get("execution_class") == "algorithm_failure"
    if cand_fail and not base_fail:
        return "catastrophic"
    if base_fail and not cand_fail:
        return "quality_win"
    if cand_fail and base_fail:
        return "tie"
    eps = 1e-9
    for field in ("S", "stage_score"):
        delta = float(candidate[field]) - float(baseline[field])
        if delta > eps:
            return "quality_win"
        if delta < -eps:
            return "quality_loss"
    base_cost = float(baseline["C"])
    cand_cost = float(candidate["C"])
    if base_cost > 0:
        if cand_cost <= base_cost * (1 - COST_TIEBREAK_MARGIN):
            return "cost_win"
        if cand_cost >= base_cost * (1 + COST_TIEBREAK_MARGIN):
            return "cost_loss"
    return "tie"


def round_verdict(
    votes: list[str],
    *,
    cost_ratio: float | None = None,
    max_cost_inflation: float = DEFAULT_MAX_COST_INFLATION,
) -> str:
    """Round verdict with quality strictly dominating cost.

    Capability is what the benchmark ultimately measures and it is scarce;
    cost regressions are common and cheap to fix later, so quality votes are
    settled first and cost votes speak only when quality is level.  The
    optional ``max_cost_inflation`` brake demotes a quality win bought at an
    excessive envelope cost ratio to neutral; disabled (``inf``) by default.
    """

    if "catastrophic" in votes:
        return "loss"
    quality_wins = votes.count("quality_win")
    quality_losses = votes.count("quality_loss")
    if quality_wins > quality_losses:
        if (
            cost_ratio is not None
            and max_cost_inflation is not None
            and cost_ratio > max_cost_inflation
        ):
            return "neutral"
        return "win"
    if quality_losses > quality_wins:
        return "loss"
    cost_wins = votes.count("cost_win")
    cost_losses = votes.count("cost_loss")
    if cost_wins > cost_losses:
        return "win"
    if cost_losses > cost_wins:
        return "loss"
    return "neutral"


def review_verdict(
    votes: list[str], *, require_quality_evidence: bool
) -> tuple[bool, str]:
    """Confirm or reject a challenger on fresh cases.

    Stricter than the envelope in one specific way: no quality REGRESSION is
    tolerated on fresh data, whatever the cost story.  When the envelope win
    was cost-only, the review additionally refuses to confirm a challenger
    that turns out to cost more on fresh cases — a saving that does not
    reproduce is not a saving.
    """

    if "catastrophic" in votes:
        return False, "catastrophic_on_review"
    if "quality_loss" in votes:
        return False, "quality_regression_on_review"
    if all(vote == "void" for vote in votes):
        # No usable signal.  Infrastructure must never decide a scientific
        # question, and stage 1 already produced a win, so an unrunnable
        # review cannot veto — it is recorded as inconclusive instead.
        return True, "review_inconclusive_all_void"
    if require_quality_evidence:
        if votes.count("quality_win") == 0:
            return False, "quality_gain_did_not_reproduce"
        return True, "quality_gain_confirmed"
    if votes.count("cost_loss") > votes.count("cost_win"):
        return False, "cost_saving_did_not_reproduce"
    return True, "confirmed"


def envelope_cost_ratio(
    challenger_rows: list[dict[str, Any]],
    incumbent_rows: list[dict[str, Any]],
) -> float | None:
    """Challenger spend / incumbent spend over the scored envelope."""

    pairs = [
        (ch, inc)
        for ch, inc in zip(challenger_rows, incumbent_rows)
        if not ch.get("infra") and not inc.get("infra")
    ]
    incumbent_total = sum(float(inc["C"]) for _ch, inc in pairs)
    if not pairs or incumbent_total <= 0:
        return None
    return sum(float(ch["C"]) for ch, _inc in pairs) / incumbent_total


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scored rows, keeping voided ones out of every mean."""

    scored = [row for row in rows if not row.get("infra")]
    return {
        "aggregate": {
            "cases_total": len(rows),
            "cases_scored": len(scored),
            "success_rate": (
                sum(bool(row.get("success")) for row in scored) / len(scored)
                if scored
                else None
            ),
            "mean_S": (
                sum(float(row["S"]) for row in scored) / len(scored)
                if scored
                else None
            ),
            "mean_C": (
                sum(float(row["C"]) for row in scored) / len(scored)
                if scored
                else None
            ),
            "infra": len(rows) - len(scored),
        },
        "rows": rows,
    }


def structure_diff(
    incumbent_phases: list[dict[str, Any]],
    challenger_phases: list[dict[str, Any]],
) -> list[str]:
    """Human-readable list of exactly WHAT the challenger changed.

    Field-level diffs turn the duel history into usable feedback: without
    them an autopsy can only say "same phase kinds, lost", and the miner
    goes back to blind parameter groping.
    """

    changes: list[str] = []
    inc_kinds = [str(p.get("kind")) for p in incumbent_phases]
    ch_kinds = [str(p.get("kind")) for p in challenger_phases]
    if inc_kinds != ch_kinds:
        changes.append(f"phase sequence {inc_kinds} -> {ch_kinds}")
    for index in range(min(len(incumbent_phases), len(challenger_phases))):
        before, after = incumbent_phases[index], challenger_phases[index]
        if before.get("kind") != after.get("kind"):
            continue  # already reported by the sequence line
        label = f"[{index}]{before.get('kind')}"
        for field in ("max_rounds", "pattern", "send_mode", "stop_when", "hub"):
            old, new = before.get(field), after.get(field)
            if old != new:
                changes.append(f"{label}.{field} {old} -> {new}")
        old_text = str(before.get("instruction") or "")
        new_text = str(after.get("instruction") or "")
        if old_text != new_text:
            changes.append(
                f"{label}.instruction rewritten "
                f"({len(old_text)} -> {len(new_text)} chars)"
            )
    return changes or ["no field-level change detected"]


def parse_json_reply(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("planner reply carries no JSON object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("planner reply is not a JSON object")
    return payload


def round_status(root: Path, round_index: int) -> str | None:
    """``completed`` | ``failed`` | ``partial``, or None if never started.

    The round's own report IS the checkpoint — no parallel bookkeeping file
    to drift out of sync with it.
    """

    directory = root / f"round-{round_index}"
    if not directory.exists():
        return None
    report = directory / "round-report.json"
    if not report.exists():
        return "partial"  # died mid-round, before the report was written
    try:
        return str(json.loads(report.read_text()).get("status") or "partial")
    except (OSError, ValueError):
        return "partial"


def retire_round_dir(
    root: Path, round_index: int, log: TournamentLog
) -> None:
    """Move a failed/partial round aside instead of provisioning over it.

    The retired directory keeps the evidence of what broke.
    """

    directory = root / f"round-{round_index}"
    if not directory.exists():
        return
    attempt = 0
    while (root / "_retired" / f"round-{round_index}.{attempt}").exists():
        attempt += 1
    target = root / "_retired" / f"round-{round_index}.{attempt}"
    target.parent.mkdir(parents=True, exist_ok=True)
    directory.rename(target)
    log.append(
        "round_retired", {"round": round_index, "retired_as": target.name}
    )
