# SFT phase_v5_executable_sft — implementation status

Plan authority: repo-root `plan.md` (`final-v1`, 2026-07-17).
Method status ceiling for this effort: `mechanics_ready` (no efficacy claim).

| Stage | State | Commit/HEAD | Exit Gate | Tests | Paid Calls | Notes |
|---|---|---|---|---|---|---|
| 0 | done | 3c6380d0 | PASS | masbench 590P/1F(env)→green after submodule init; exp-graph 783P | 0 | see stage_00_baseline.md |
| 1 | done | fb2c52e7+ | PASS | v5 suite 34P; masbench full 631P | 0 | fail-closed profile; no runner yet |
| 2 | done | 0a2e0062+ | PASS | v5 experiment 9P; SFT targeted 213P | 0 | seal + idempotent provision + anchor genesis |
| 3 | done | 02806a16+ | PASS | engine v3 7P; regression 28P + exp-graph v3 10P | 0 | binder-dispatched edge law; image_loaded only |
| 4 | done | 59e8c483+ | PASS | v5 generation 5P; SFT targeted 225P | 0 | context/lease/abort closed; renderer + metered fake e2e |
| 5 | done | d8c71fe2+ | PASS | pair consumer 3P; SFT targeted 228P; factor bank 181P | 0 | adapter+consumer closed; one pair == one vote |
| 6 | done | 47e313d7+ | PASS | probe 9P; regression batch 50P (incl saga/store) | 0 | native-reducer scenarios; crash + half-pair settle |
| 7 | done | 32198452+ | PASS | train loop 2P | 0 | Bank-truth scheduler; capacity pre-call rejection |
| 8 | done | 2f550776+ | PASS | final_val 3P | 0 | strict gate + promotion; quiescence law |
| 9 | done | e989e852+ | PASS | result ledger 4P | 0 | roots-identical TEST; chained external ledger |
| 10 | done | ed07b60a+ | PASS | controls 3P | 0 | policy-gated backends; equal all-in verifier |
| 11 | done | 28b1c997+ | PASS | masbench full 677P; exp-graph full 783P | 0 | docs synced; order-dependence fixed |
| 12 | RUN (pilot_usable) | a1ee8941+dirty | PASS | masbench full 680P (incl 3 offline-pilot); exp-graph full 791P | 1,542 calls / ~$0.45 | 2026-07-17 real pilot: 3 replicates, gpt-4o-mini, n_agents=5, see stage_12_real_pilot.md |
