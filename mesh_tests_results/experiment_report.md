# CF Protocol Topology Experiment

## Configuration

- Array size: `5000`
- Value range: `[1, 1000]`
- Seeds: `[1]`
- Agent counts: `[4]`
- Topologies: `['mesh']`
- Merge modes: `['llm_full_merge']`
- Init modes: `['llm_local_solve']`
- Provider: `openai`
- Model: `gpt-4o`

## Aggregate Results

| Topology | Agents | MergeMode | InitMode | Runs | MeanFinalRMSE | StdFinalRMSE | MeanAverageRMSE | ExactMatchRate | MeanVoteRMSE | MeanFinalNormalizedL1Error | MeanTotalSteps | MeanTotalMessages | MeanTotalModelCalls | MeanTotalPromptTokens | MeanTotalCompletionTokens | MeanDeterministicFallbacks | MeanVoteTopRatio | MeanVoteAverageDisagreementRMSE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mesh | 4 | llm_full_merge | llm_local_solve | 1 | 27.000000 | 0.000000 | 22.715633 | 0.000000 | 27.000000 | 0.086600 | 1.000000 | 12.000000 | 8.000000 | 88388.000000 | 64840.000000 | 0.000000 | 0.250000 | 18.330303 |

## Run Results

| Topology | Agents | MergeMode | InitMode | Seed | TotalSteps | TotalMessages | TotalModelCalls | TotalRetryAttempts | TotalDeterministicFallbacks | FinalRMSE | VoteRMSE | AverageRMSE | FinalNormalizedL1Error | FinalExactMatch | VoteTopRatio | Task | ArraySize | ValueMin | ValueMax | Provider | Model | Temperature | TotalPromptTokens | TotalCompletionTokens | AggregationMethod | SelectedPrimary | VoteNormalizedL1Error | AverageNormalizedL1Error | AverageIncludedAgents | VoteAverageDisagreementRMSE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mesh | 4 | llm_full_merge | llm_local_solve | 1 | 1 | 12 | 8 | 0 | 0 | 27.000000 | 27.000000 | 22.715633 | 0.086600 | False | 0.250000 | count_frequency_protocol | 5000 | 1 | 1000 | openai | gpt-4o | 0.000000 | 88388 | 64840 | vote | vote | 0.086600 | 0.077200 | 4 | 18.330303 |

This experiment uses the existing AgentState, BeliefState, and OutboxMessage data path. The protocol runner changes only which agents send and receive on each communication step.

Agent-step RMSE is local by default: each agent answer is compared with the scoring-only truth for the source shards currently carried by that agent. `global_rmse` is recorded in parallel against the full global answer. RMSE is computed as root-sum-squared count error over the value domain, without dividing by domain size.

## Visualizations

![Final RMSE](final_rmse.png)

![Vote RMSE](vote_rmse.png)

![Average RMSE](average_rmse.png)

![Mean Agent RMSE](mean_agent_rmse_by_step.png)

![Mean Agent Global RMSE](mean_agent_global_rmse_by_step.png)

![Mean Coverage](mean_coverage_by_step.png)

