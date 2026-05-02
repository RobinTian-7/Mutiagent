# Hierarchy Sweep Report (M1: static emperor-soldiers)

## Configuration

- Model: `moonshotai/Kimi-K2.5`
- Provider: `fake`
- Seed: `42`
- Max rounds: `6`

## Results

| Topology | Soldiers | Agents | ArraySize | RoundsToConsensus | RMSE | NormalizedRMSE | ExactMatch | ConsensusReached | RunCompleted | FallbackUsed | TotalModelCalls | TotalTokenCost | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hierarchy_static_1+N | 4 | 5 | 1000 | 2 | 0.000000 | 0.000000 | True | True | True | False | 10 | 9564 | ok |
| hierarchy_static_1+N | 8 | 9 | 1000 | 2 | 0.000000 | 0.000000 | True | True | True | False | 18 | 16020 | ok |
| hierarchy_static_1+N | 16 | 17 | 1000 | 2 | 0.000000 | 0.000000 | True | True | True | False | 34 | 33556 | ok |
| hierarchy_static_1+N | 4 | 5 | 5000 | 2 | 0.000000 | 0.000000 | True | True | True | False | 10 | 25564 | ok |
| hierarchy_static_1+N | 8 | 9 | 5000 | 2 | 0.000000 | 0.000000 | True | True | True | False | 18 | 32020 | ok |
| hierarchy_static_1+N | 16 | 17 | 5000 | 2 | 0.000000 | 0.000000 | True | True | True | False | 34 | 49636 | ok |

