# CF Topology Sweep Report

## Configuration

- Model: `moonshotai/Kimi-K2.5`
- Provider: `openai`
- Array size: `5000`
- Value range: `[0, 9]`
- Max rounds: `20`
- Seed: `42`

## Results

| Topology | Agents | RoundsToConsensus | RMSE | NormalizedRMSE | ExactMatch | ConsensusReached | RunCompleted | FallbackUsed | TotalModelCalls | TotalTokenCost | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chain | 8 | 7 | 0.000000 | 0.000000 | True | True | True | False | 56 | 34214 | ok |
| chain | 16 | 14 | 0.000000 | 0.000000 | True | True | True | False | 224 | 120274 | ok |
| chain | 32 | 28 | 0.000000 | 0.000000 | True | True | True | False | 896 | 510570 | ok |
| mesh | 8 | 1 | 0.000000 | 0.000000 | True | True | True | False | 8 | 74117 | ok |
| mesh | 16 | 1 | 0.000000 | 0.000000 | True | True | True | False | 16 | 16704 | ok |
| mesh | 32 | 1 | 0.000000 | 0.000000 | True | True | True | False | 32 | 53424 | ok |
| one_peer_exponential | 8 | 3 | 0.000000 | 0.000000 | True | True | True | False | 24 | 13992 | ok |
| one_peer_exponential | 16 | 4 | 0.000000 | 0.000000 | True | True | True | False | 64 | 30912 | ok |
| one_peer_exponential | 32 | 5 | 0.000000 | 0.000000 | True | True | True | False | 160 | 75312 | ok |

Rows with `RunCompleted=False` are API/runtime failures. They did not reach final reducer, so they are not valid model answers.

