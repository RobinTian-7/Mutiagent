# CF Protocol Topology Experiment

## Configuration

- Array size: `5000`
- Value range: `[1, 1000]`
- Seeds: `[1]`
- Agent counts: `[8]`
- Topologies: `['mesh']`
- Merge modes: `['llm_full_merge']`
- Provider: `openai`
- Model: `gpt-4o`

## Aggregate Results

| Topology | Agents | MergeMode | Runs | MeanFinalRMSE | StdFinalRMSE | MeanAverageRMSE | ExactMatchRate | MeanVoteRMSE | MeanFinalNormalizedL1Error | MeanTotalSteps | MeanTotalMessages | MeanTotalModelCalls | MeanTotalPromptTokens | MeanTotalCompletionTokens | MeanDeterministicFallbacks | MeanVoteTopRatio | MeanVoteAverageDisagreementRMSE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mesh | 8 | llm_full_merge | 1 | 1.595306 | 0.000000 | 1.168332 | 0.000000 | 1.595306 | 0.225000 | 1.000000 | 56.000000 | 9.000000 | 211904.000000 | 63726.000000 | 0.000000 | 0.125000 | 1.078888 |

## Run Results

| Topology | Agents | MergeMode | Seed | TotalSteps | TotalMessages | TotalModelCalls | TotalRetryAttempts | TotalDeterministicFallbacks | FinalRMSE | VoteRMSE | AverageRMSE | FinalNormalizedL1Error | FinalExactMatch | VoteTopRatio | Task | ArraySize | ValueMin | ValueMax | Provider | Model | Temperature | TotalPromptTokens | TotalCompletionTokens | AggregationMethod | SelectedPrimary | VoteNormalizedL1Error | AverageNormalizedL1Error | AverageIncludedAgents | VoteAverageDisagreementRMSE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mesh | 8 | llm_full_merge | 1 | 1 | 56 | 9 | 1 | 0 | 1.595306 | 1.595306 | 1.168332 | 0.225000 | False | 0.125000 | count_frequency_protocol | 5000 | 1 | 1000 | openai | gpt-4o | 0.000000 | 211904 | 63726 | vote | vote | 0.225000 | 0.165800 | 8 | 1.078888 |

This experiment uses the existing AgentState, BeliefState, and OutboxMessage data path. The protocol runner changes only which agents send and receive on each communication step.

## Visualizations

![Final RMSE](final_rmse.png)

![Vote RMSE](vote_rmse.png)

![Average RMSE](average_rmse.png)

![Mean Agent RMSE](mean_agent_rmse_by_step.png)

![Mean Coverage](mean_coverage_by_step.png)

