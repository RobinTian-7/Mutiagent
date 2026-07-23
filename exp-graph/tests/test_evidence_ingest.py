import json

from exp_graph.mas.evidence import ingest_experiment_evidence, write_evidence_jsonl


def test_ingest_experiment_evidence_builds_append_only_records(tmp_path):
    (tmp_path / "aggregate_summary.csv").write_text(
        "\n".join(
            [
                "Topology,Agents,ArraySize,MergeMode,InitMode,Runs,MeanFinalRMSE,StdFinalRMSE,MeanFinalNormalizedL1Error,ExactMatchRate,MeanTotalSteps,MeanTotalMessages,MeanTotalModelCalls,MeanTokenCost,MeanDeterministicFallbacks,MeanVoteTopRatio",
                "one_peer_exponential_dag_star,8,64,llm_full_merge,llm_local_solve,3,0.1,0.0,0.02,0.5,3,11,16,1200,0,0.9",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "run_summary.csv").write_text(
        "\n".join(
            [
                "Topology,Agents,ArraySize,Seed,MergeMode,InitMode,Provider,Model,TotalSteps,TotalMessages,TotalModelCalls,TotalPromptTokens,TotalCompletionTokens,TotalDeterministicFallbacks,FinalRMSE,FinalNormalizedL1Error,FinalExactMatch,VoteRMSE,AverageRMSE,VoteAverageDisagreementRMSE",
                "one_peer_exponential_dag_star,8,64,1,llm_full_merge,llm_local_solve,openai,gpt-4o-mini,3,11,16,900,300,0,0.1,0.02,False,0.1,0.11,0.01",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "global_step_metrics.csv").write_text(
        "\n".join(
            [
                "Topology,Agents,Seed,step_idx,mean_coverage,max_coverage,full_coverage_agents,vote_rmse,average_rmse",
                "one_peer_exponential_dag_star,8,1,-1,0.125,0.125,0,0.9,0.8",
                "one_peer_exponential_dag_star,8,1,2,0.75,1.0,2,0.1,0.11",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "agent_step_metrics.csv").write_text(
        "\n".join(
            [
                "Topology,Agents,Seed,step_idx,agent_id,global_rmse,coverage_ratio",
                "one_peer_exponential_dag_star,8,1,2,0,0.1,1.0",
                "one_peer_exponential_dag_star,8,1,2,7,0.2,0.75",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    trace_path = (
        trace_dir
        / "cf_protocol_llm_local_solve_llm_full_merge_one_peer_exponential_dag_star_n8_seed1.jsonl"
    )
    trace_path.write_text(
        json.dumps(
            {
                "neighbors": [0, 1, 2],
                "retry_attempts": 1,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "parse_error": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = ingest_experiment_evidence(tmp_path)

    assert {record.source_type for record in records} == {"aggregate", "run", "trace"}
    trace = next(record for record in records if record.source_type == "trace")
    assert trace.topology_name == "one_peer_exponential_dag_star"
    assert trace.dynamics["merge_quality"]["retry_attempts"] == 1
    assert "sink_quality_gap" in trace.risk_tags
    output = write_evidence_jsonl(records, tmp_path / "evidence.jsonl")
    assert output.exists()
