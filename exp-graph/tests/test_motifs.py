"""Structural-motif credit attribution for generated temporal DAGs.

These tests prove the Plan 3 Part G mechanism: evidence is attributed to
reusable structural motifs (interpretable "feature=value" tokens) rather than to
opaque whole-topology names, so a *newly generated* DAG with a different agent
count / labels can still inherit credit from past winners through the motifs it
shares with them.
"""

from __future__ import annotations

from exp_graph.mas.motifs import (
    aggregate_motif_losses,
    extract_motifs,
    motif_feature_keys,
    score_spec_by_motifs,
)
from exp_graph.protocols import ProtocolGraphSpec, ProtocolStepSpec


def _spec(
    name: str,
    n_agents: int,
    steps: list[list[tuple[int, int]]],
    *,
    selected_primary: int | None = None,
) -> ProtocolGraphSpec:
    metadata: dict[str, object] = {}
    if selected_primary is not None:
        metadata["selected_primary"] = selected_primary
    return ProtocolGraphSpec(
        name=name,
        n_agents=n_agents,
        steps=[ProtocolStepSpec(transmissions=edges) for edges in steps],
        metadata=metadata,
    )


def _tree_reduce_4() -> ProtocolGraphSpec:
    # Classic 4-agent tree reduction: 0->1, 2->3 then 1->3. Sink is agent 3.
    return _spec(
        "tree_reduce_4",
        4,
        [
            [(0, 1), (2, 3)],
            [(1, 3)],
        ],
        selected_primary=3,
    )


def test_extract_motifs_basic() -> None:
    motifs = extract_motifs(_tree_reduce_4())

    # Two communication rounds.
    assert motifs["n_steps"] == 2
    # Largest single-step receiver fan-in: agent 3 receives one edge per step,
    # so the per-step max fan-in is 1.
    assert motifs["max_receiver_fan_in"] == 1
    assert motifs["fan_in_bucket"] == "low"
    # Six directed messages? No: 0->1, 2->3, 1->3 == 3 messages total.
    assert motifs["total_messages"] == 3
    # Agent 3 is the unique final holder (receives, never sends afterwards).
    assert motifs["has_sink"] is True
    assert motifs["sink_count"] == 1
    # Reduces to a single holder; depth is the number of rounds until one
    # holder covers every source's information (here 2 rounds).
    assert motifs["reduction_depth"] == 2
    # The plain tree-reduce has no redundant / back-coverage edges.
    assert motifs["has_audit_edges"] is False


def test_extract_motifs_detects_fan_in_and_audit() -> None:
    # Wide star gather into agent 6 (fan-in 6) plus an audit/back-coverage edge
    # 6->0 returning the aggregate to an agent that already fed the sink.
    star_with_audit = _spec(
        "star_audit_7",
        7,
        [
            [(0, 6), (1, 6), (2, 6), (3, 6), (4, 6), (5, 6)],
            [(6, 0)],
        ],
        selected_primary=6,
    )
    motifs = extract_motifs(star_with_audit)

    assert motifs["max_receiver_fan_in"] == 6
    assert motifs["fan_in_bucket"] == "high"
    # Edge 6->0 sends information *back* to an agent that already fed the sink:
    # a redundant back-coverage / audit edge.
    assert motifs["has_audit_edges"] is True

    # A moderate 4-into-1 gather sits in the "med" bucket (low<=2 / med<=4 /
    # high otherwise), so "is there a wide gather" stays a meaningful motif.
    star4 = _spec(
        "star4",
        5,
        [[(0, 4), (1, 4), (2, 4), (3, 4)]],
        selected_primary=4,
    )
    assert extract_motifs(star4)["fan_in_bucket"] == "med"


def test_motif_keys_stable() -> None:
    # Same structure, agents relabeled (a permutation): keys must be identical.
    base = _tree_reduce_4()
    # Permute agents by mapping i -> (i + 2) % 4, i.e. 0->2,1->3,2->0,3->1.
    perm = {0: 2, 1: 3, 2: 0, 3: 1}
    relabeled = _spec(
        "tree_reduce_4_relabeled",
        4,
        [
            [(perm[0], perm[1]), (perm[2], perm[3])],
            [(perm[1], perm[3])],
        ],
        selected_primary=perm[3],
    )

    base_keys = motif_feature_keys(extract_motifs(base))
    relabeled_keys = motif_feature_keys(extract_motifs(relabeled))

    assert base_keys == relabeled_keys
    # Keys are canonical "feature=value" tokens.
    assert all("=" in key for key in base_keys)
    assert "n_steps=2" in base_keys


def test_aggregate_and_score_transfers_to_novel_spec() -> None:
    # Build evidence where specs that *do* have a high receiver fan-in (motif
    # "X" = fan_in_bucket=high) scored LOW loss, and specs without it scored
    # HIGH loss. We then prove a NOVEL spec (different agent count + labels)
    # inherits the right prediction purely from the motif it shares.

    # Low-loss winners: 6-agent and 7-agent star gathers (fan_in_bucket=high,
    # i.e. >4 incoming edges into one sink).
    star6 = _spec(
        "star6",
        6,
        [[(0, 5), (1, 5), (2, 5), (3, 5), (4, 5)]],
        selected_primary=5,
    )
    star7 = _spec(
        "star7",
        7,
        [[(0, 6), (1, 6), (2, 6), (3, 6), (4, 6), (5, 6)]],
        selected_primary=6,
    )
    # High-loss losers: sparse chains (fan_in_bucket=low, no high fan-in).
    chain4 = _spec(
        "chain4",
        4,
        [[(0, 1)], [(1, 2)], [(2, 3)]],
        selected_primary=3,
    )
    chain5 = _spec(
        "chain5",
        5,
        [[(0, 1)], [(1, 2)], [(2, 3)], [(3, 4)]],
        selected_primary=4,
    )

    rows = [
        {"protocol_spec": star6.model_dump(mode="json"), "mean_primary_loss": 0.05},
        {"protocol_spec": star7.model_dump(mode="json"), "mean_primary_loss": 0.10},
        {"protocol_spec": chain4.model_dump(mode="json"), "mean_primary_loss": 0.80},
        {"protocol_spec": chain5.model_dump(mode="json"), "mean_primary_loss": 0.90},
    ]

    motif_stats = aggregate_motif_losses(rows)

    # The high-fan-in motif must have accumulated low loss evidence; the
    # low-fan-in motif high loss.
    assert "fan_in_bucket=high" in motif_stats
    assert "fan_in_bucket=low" in motif_stats
    assert motif_stats["fan_in_bucket=high"]["mean_loss"] < 0.2
    assert motif_stats["fan_in_bucket=low"]["mean_loss"] > 0.7
    assert motif_stats["fan_in_bucket=high"]["n"] == 2

    # NOVEL spec A: a 7-agent star gather. Different agent count, never seen,
    # but it shares fan_in_bucket=high with the winners -> predicted LOW loss.
    novel_high = _spec(
        "novel_star7",
        7,
        [[(0, 6), (1, 6), (2, 6), (3, 6), (4, 6)]],
        selected_primary=6,
    )
    # NOVEL spec B: an 8-agent chain. Shares fan_in_bucket=low with the
    # losers -> predicted HIGH loss.
    novel_low = _spec(
        "novel_chain8",
        8,
        [[(0, 1)], [(1, 2)], [(2, 3)], [(3, 4)], [(4, 5)], [(5, 6)], [(6, 7)]],
        selected_primary=7,
    )

    score_high = score_spec_by_motifs(novel_high, motif_stats)
    score_low = score_spec_by_motifs(novel_low, motif_stats)

    # Lower predicted loss = predicted better. Credit transferred structurally:
    # the novel star inherits the winners' low loss, the novel chain the losers'
    # high loss, even though neither exact shape / agent count was ever seen.
    # Motifs shared by *both* groups (e.g. has_sink) carry neutral evidence and
    # pull each estimate toward the global mean, but the discriminating motif
    # still separates them by a wide margin.
    assert score_high < score_low
    assert score_high < 0.35
    assert score_low > 0.5
    # The separation must be large, not a coin-flip: the structural signal
    # dominates the neutral dilution. If credit did NOT transfer (e.g. only the
    # group-neutral motifs counted), both scores would collapse onto the global
    # mean (~0.46) and this margin would vanish -- so this guards the mechanism.
    assert score_low - score_high > 0.2

    # Direct, dilution-free proof on the discriminating motif alone: the novel
    # star is predicted far better than the novel chain when scored purely
    # against the fan-in motif evidence.
    fan_in_only = {
        "fan_in_bucket=high": motif_stats["fan_in_bucket=high"],
        "fan_in_bucket=low": motif_stats["fan_in_bucket=low"],
    }
    assert score_spec_by_motifs(novel_high, fan_in_only) < 0.2
    assert score_spec_by_motifs(novel_low, fan_in_only) > 0.7


def test_score_spec_by_motifs_unknown_is_neutral_high() -> None:
    # With no usable motif stats, a spec gets a high-uncertainty sentinel
    # (+inf) rather than a falsely-confident low loss.
    assert score_spec_by_motifs(_tree_reduce_4(), {}) == float("inf")

    # Stats exist but the spec shares NO known motif key with them: no evidence
    # applies, so again the high-uncertainty sentinel.
    disjoint_stats = {"never_seen_feature=zzz": {"mean_loss": 0.1, "n": 5}}
    assert score_spec_by_motifs(_tree_reduce_4(), disjoint_stats) == float("inf")


def test_aggregate_reads_rmse_when_primary_loss_absent() -> None:
    # CF-only evidence carries mean_rmse, not mean_primary_loss. The aggregator
    # must still attribute it to the spec's motif keys.
    rows = [
        {"motif_keys": ["fan_in_bucket=high"], "mean_rmse": 0.2},
        {"motif_keys": ["fan_in_bucket=high"], "mean_rmse": 0.4},
    ]
    stats = aggregate_motif_losses(rows)
    assert stats["fan_in_bucket=high"]["n"] == 2
    assert abs(stats["fan_in_bucket=high"]["mean_loss"] - 0.3) < 1e-9
