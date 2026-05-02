# Hierarchy Sweep Report (M2: static multi-layer)

## Configuration

- Model: `gpt-4o-mini`
- Provider: `openai`
- Seed: `42`
- Max rounds: `12`

## Results

| Planner | Shape | Depth | Soldiers | Agents | ArraySize | RoundsToConsensus | RMSE | NormalizedRMSE | ExactMatch | ConsensusReached | RunCompleted | FallbackUsed | PlannerFallbackReason | PlannerTokens | PlannerCalls | RecursiveCalls | RecursiveFallbackCalls | TotalModelCalls | TotalTokenCost | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_fallback | 8 | 2 | 8 | 9 | 1000 | -1 | 107.474648 | 0.107475 | False | False | True | True | n_total=1057 exceeds max_n_agents=128 | 344 | 1 | 0 | 0 | 108 | 332954 | ok |

