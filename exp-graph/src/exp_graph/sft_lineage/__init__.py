"""SFTBank-style verified-lineage training for CF protocol structures.

This package transplants the queenbee-SFTbank ``masbench.sft_pilot``
card-training law (single-structure verified lineage: mint -> frozen duel on
a tier-balanced envelope -> fresh-case review -> promotion; one-shot
read-only TEST) onto this repository's Count Frequency protocol runner.

The law layer (:mod:`exp_graph.sft_lineage.law`) is a faithful port and is
task-agnostic; the CF substrate (cases, structure vocabulary, executor) is
new and drives :class:`exp_graph.runner.ProtocolRunner` with the sink
information goal: every source shard must reach ONE designated sink agent
(the highest id), and only the sink's final frequency table is scored.
"""

from exp_graph.sft_lineage.law import (
    LineageBank,
    TournamentLog,
    envelope_cases,
    envelope_cost_ratio,
    mint_task_sequence,
    review_cases,
    review_verdict,
    round_verdict,
    seed_vote,
    structure_diff,
    summarize_rows,
)

__all__ = [
    "LineageBank",
    "TournamentLog",
    "envelope_cases",
    "envelope_cost_ratio",
    "mint_task_sequence",
    "review_cases",
    "review_verdict",
    "round_verdict",
    "seed_vote",
    "structure_diff",
    "summarize_rows",
]
