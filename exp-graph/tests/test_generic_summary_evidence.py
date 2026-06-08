from exp_graph.mas.runner import summary_to_aggregate_row


def test_generic_summary_maps_without_keyerror():
    generic = {
        "Task": "global_max", "Topology": "mesh_star", "Agents": 8, "Seed": 0,
        "MergeMode": "deterministic", "InitMode": "deterministic",
        "TotalSteps": 2, "TotalMessages": 56, "TotalModelCalls": 0,
        "TotalPromptTokens": 0, "TotalCompletionTokens": 0,
        "TotalRetryAttempts": 0, "TotalDeterministicFallbacks": 0,
        "AggregationMethod": "vote", "SelectedPrimary": "vote",
        "PrimaryMetric": 1.0, "PrimaryMetricName": "exact_match",
        "FinalExactMatch": True, "VoteTopRatio": 1.0,
        "AnswerAgentIds": [0, 1, 2, 3, 4, 5, 6, 7], "FinalKey": "9",
    }
    row = summary_to_aggregate_row(generic)
    assert row["MeanPrimaryMetric"] == 1.0
    assert row["PrimaryMetricName"] == "exact_match"
    assert row["ExactMatchRate"] == 1.0
    assert row["ArraySize"] == 0


def test_cf_summary_still_yields_mean_final_rmse():
    cf = {
        "Task": "count_frequency_protocol", "Topology": "tree", "Agents": 4,
        "ArraySize": 4, "MergeMode": "deterministic", "InitMode": "deterministic",
        "TotalSteps": 3, "TotalMessages": 7, "TotalModelCalls": 0,
        "TotalPromptTokens": 0, "TotalCompletionTokens": 0,
        "FinalRMSE": 0.0, "FinalNormalizedL1Error": 0.0, "FinalExactMatch": True,
        "VoteTopRatio": 1.0, "PrimaryMetric": 0.0, "PrimaryMetricName": "rmse",
    }
    row = summary_to_aggregate_row(cf)
    assert row["MeanFinalRMSE"] == 0.0
    assert row["MeanPrimaryMetric"] == 0.0
