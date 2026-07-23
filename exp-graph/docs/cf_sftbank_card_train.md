# CF SFTBank card training (structure lineage)

`run_cf_sftbank_card_train.py` transplants the queenbee-SFTbank
`masbench.sft_pilot.card_train --lineage structure` pipeline onto this
repository's Count Frequency protocol machinery. One campaign is a
verified single-structure lineage plus a one-shot TEST:

```
per round:
  mint case (hardest tier first)                       # mint_task_sequence
  -> planner mints a challenger phase program          # task-informed, autopsy-informed
  -> FREEZE both artifacts                             # attribution property
  -> duel on a tier-balanced case envelope             # envelope_cases, same frozen seed
  -> per-case votes, quality before cost               # seed_vote / round_verdict
  -> stage-1 win must confirm on fresh review cases    # review_cases / review_verdict
  -> only a confirmed win promotes                     # LineageBank.record_duel

after all rounds:
  one-shot read-only TEST of the final incumbent on the frozen holdout,
  with reference arms (v1 seed + named baseline structures) on the same
  cases and seeds. lineage.json must be byte-identical across TEST.
```

## The sink goal

`--goal sink` (default) is what separates this campaign from the legacy
consensus benchmarks: information must AGGREGATE at one designated sink
agent (the highest id), which submits the only scored answer. Compilation
enforces reachability (every shard can flow to the sink), the runner scores
only the sink's final table (`metadata.selected_primary`), and
dissemination back out (broadcast/consensus phases) is deliberately absent
from the vocabulary — it is pure waste under this goal.

Fact rows feed the ported duel law unchanged: `S` = 1 − normalized L1
error of the sink table (exact table ⇒ 1.0), `stage_score` = 1/(1+RMSE)
refines same-S comparisons, `C` = paid tokens (message count in
deterministic offline runs, so offline duels still have a cost axis).

## Usage

Offline smoke (no API calls; deterministic merge, deterministic designs):

```bash
python run_cf_sftbank_card_train.py --rounds 4 --envelope-cases 3
```

Real campaign, same invocation shape as the SFTBank pilot:

```bash
CF_SFT_PAID_CALLS_APPROVED=yes OPENAI_API_KEY=... \
python run_cf_sftbank_card_train.py \
    --llm openai --lineage structure --rounds 16 --envelope-cases 3 \
    --model gpt-5-mini --reasoning-effort minimal \
    --single-card one_peer_star_sink --agents 8
```

Notable flags (defaults in parentheses):

- `--single-card` (`one_peer_star_sink`): seed structure. `star_sink`,
  `tree_sink`, `chain_sink`, `static_exponential_sink`,
  `balanced_log_layer_sink` are also available; the default seed is the
  one-peer exponential premix followed by a star gather into the sink.
- `--envelope-cases` (6) / `--review-cases` (2): duel and confirmation
  widths, tier-balanced / disjoint-hardest-first respectively.
- `--cases-per-tier` (6) / `--test-cases` (6) / `--tier-spec`: the CF case
  bank. Tiers I/II/III default to arrays of 400/2000/5000 values over
  1..40/1..300/1..1000; TEST cases are frozen up front and use disjoint
  content seeds (`TEST_SEED_BASE`) from training duels (`CARD_SEED_BASE`).
- `--allow-deterministic-repair` (off): duels measure the model's real
  merge capability; repair is opt-in for data-collection runs only.
- `--test-baselines` (`v1,star_sink,tree_sink,static_exponential_sink`):
  reference arms on the frozen TEST cases.

Artifacts under `--root` (default `runs/cf_sft_v5_cards`): `lineage.json`
(the verified lineage), `events.jsonl` (hash-chained log),
`round-<i>/round-report.json` (checkpoint + autopsy; resume skips
completed rounds), `card_train_report.json` (campaign summary + TEST).

## Parity with the SFTBank pilot

Shared law (faithful port, `exp_graph/sft_lineage/law.py`): lineage bank,
mint rotation, envelope/review case draws, vote/verdict rules, cost-ratio
brake, structure diff, hash-chained log, checkpoint/retire/resume, TEST
read-only law.

Substituted substrate (CF-specific): SiloBench adapter → tiered CF case
bank; `PhaseProgram` vocabulary → CF sink dialect (`premix` + `gather`,
no instructions, compiled onto `ProtocolGraphSpec`); `real_eval` executor →
`ProtocolRunner` with sink-only scoring.

Not transplanted: `--lineage card` (strategy-text lineage), multi-card
bank training, paper-protocol baseline arms, the process-wide LLM
admission gate (bound concurrency with `--parallel-tests` ×
`--max-parallel-agents` instead).
