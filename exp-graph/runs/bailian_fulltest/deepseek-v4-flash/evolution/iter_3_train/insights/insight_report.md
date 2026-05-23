report_id: batch_insight_report_20260523_124559
experiment_id: /Users/robintian/experiment/Agent-Expretional-Graph/exp-graph/runs/bailian_fulltest/deepseek-v4-flash/evolution/iter_3_train/collected/batch_evidence.jsonl

Batch-level MAS insights extracted from matrix evidence.

key_insights:
  - Budget-aware partial topology leads to full coverage but wrong answers
    type: risk_pattern
    status: hypothesis
    confidence: 0.80
    evidence_refs: run:protocol_generated:budget_aware_partial_n8_seed1_1779540325643063000, run:protocol_generated:budget_aware_partial_n8_seed2_1779540271686063000, trace:protocol_generated:budget_aware_partial_n8_seed1_1779540325643063000, trace:protocol_generated:budget_aware_partial_n8_seed2_1779540271686063000
    summary: The budget-aware partial topology achieves full coverage (all agents contribute) but the final merged answer is wrong (full_coverage_wrong_answer_rate=1.0). This suggests that the partial communication structure, while ensuring coverage, fails to propagate correct information or reconcile conflicting local solutions.
    operation_recommendations:
      - {"action_type": "change_edge_order", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Higher sink fan-in may improve accuracy by providing more information for the merge, but may increase token cost.", "instruction": "Increase fan-in to the sink agent by adding more edges from non-sink agents to the sink, ensuring that the sink receives diverse local solutions before merging.", "target": "sink_selection"}
      - {"action_type": "change_sink_selection", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Better sink selection could reduce wrong answers, but may require additional computation to evaluate agent quality.", "instruction": "Select a sink agent that has high initial accuracy or is centrally located in the communication graph to reduce error propagation.", "target": "sink_agent"}
  - Low final coverage despite full agent participation indicates ineffective merging
    type: dynamics_pattern
    status: hypothesis
    confidence: 0.70
    evidence_refs: trace:protocol_generated:budget_aware_partial_n8_seed1_1779540325643063000, trace:protocol_generated:budget_aware_partial_n8_seed2_1779540271686063000
    summary: Mean final coverage is only 0.28125, meaning that after merging, the final answer covers only 28% of the array. This is low given that all agents participated (full coverage). The merge mode 'llm_full_merge' may be discarding correct partial solutions or failing to combine them effectively.
    operation_recommendations:
      - {"action_type": "change_reducer_scope", "conditions": {"merge_mode": "llm_full_merge"}, "expected_effect": "Higher final coverage and accuracy, but may increase token cost if multiple merge rounds are needed.", "instruction": "Switch from 'llm_full_merge' to a more conservative merge strategy that preserves high-confidence local solutions, e.g., weighted voting or confidence-based selection.", "target": "merge_mode"}
      - {"action_type": "change_provenance_flow", "conditions": {"merge_mode": "llm_full_merge"}, "expected_effect": "Better understanding of merge failures, enabling future improvements.", "instruction": "Add provenance tracking to identify which local solutions contribute to the final answer, enabling targeted re-evaluation of low-coverage regions.", "target": "merge_process"}
  - Low mean candidate count suggests insufficient exploration
    type: scaling_pattern
    status: hypothesis
    confidence: 0.60
    evidence_refs: run:protocol_generated:budget_aware_partial_n8_seed1_1779540325643063000, run:protocol_generated:budget_aware_partial_n8_seed2_1779540271686063000
    summary: Mean candidate count is 4.0, which is low for array size 1024. This indicates that the budget-aware partial topology limits the number of candidate solutions generated per agent, potentially missing correct answers. The low mean_selected_candidate_score (-18.08) supports that candidates are poor.
    operation_recommendations:
      - {"action_type": "change_fan_in", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Higher candidate count may improve candidate quality and final accuracy, but increases token cost.", "instruction": "Increase the number of candidates per agent by relaxing budget constraints or allowing more local search steps.", "target": "candidate_generation"}
  - Full coverage with zero accuracy: sink merge failure
    type: risk_pattern
    status: hypothesis
    confidence: 0.85
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed3_1779540301728957000, run:protocol_generated:sparse_peer_exchange_n8_seed4_1779540303954998000, trace:protocol_generated:sparse_peer_exchange_n8_seed3_1779540301728957000, trace:protocol_generated:sparse_peer_exchange_n8_seed4_1779540303954998000
    summary: The sparse peer exchange topology achieves full coverage (mean_final_coverage=0.5625, but full_coverage_wrong_answer_rate=1.0) meaning all agents eventually have an answer but it is incorrect. This indicates that the sink merge operation (llm_full_merge) is not correcting errors; instead it may be propagating a wrong consensus.
    operation_recommendations:
      - {"action_type": "change_sink_selection", "conditions": {"array_size": 1024, "merge_mode": "llm_full_merge", "n_agents": 8}, "expected_effect": "Reduce full_coverage_wrong_answer_rate by preventing propagation of low-quality answers.", "instruction": "Replace llm_full_merge with a weighted or quality-aware merge that favors higher-confidence local solutions. Alternatively, add a verification step before final merge.", "target": "sink_merge"}
  - Low coverage gain despite high message count
    type: dynamics_pattern
    status: hypothesis
    confidence: 0.90
    evidence_refs: trace:protocol_generated:sparse_peer_exchange_n8_seed3_1779540301728957000, trace:protocol_generated:sparse_peer_exchange_n8_seed4_1779540303954998000
    summary: Mean coverage gain is only 0.4375, meaning that after initial local solves, the peer exchange only adds about 44% new coverage. With 20 messages and 25 model calls per run, the communication is inefficient: many messages do not expand coverage.
    operation_recommendations:
      - {"action_type": "change_edge_order", "conditions": {"array_size": 1024, "mean_coverage_gain": 0.4375, "n_agents": 8}, "expected_effect": "Reduce mean_messages and mean_model_calls by ~30%, while maintaining similar coverage.", "instruction": "Reduce the number of peer exchanges per agent (e.g., from 2 to 1) to lower message cost without sacrificing coverage gain, since gain per message is low.", "target": "peer_exchange_edges"}
  - Negative candidate scores indicate poor local solutions
    type: risk_pattern
    status: hypothesis
    confidence: 0.80
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed3_1779540301728957000, run:protocol_generated:sparse_peer_exchange_n8_seed4_1779540303954998000
    summary: Mean selected candidate score is -17.64, which is very negative. This suggests that the local solutions generated by llm_local_solve are of low quality (high error). The peer exchange then propagates these poor solutions, leading to final wrong answers.
    operation_recommendations:
      - {"action_type": "change_init_mode", "conditions": {"array_size": 1024, "init_mode": "llm_local_solve"}, "expected_effect": "Increase mean_selected_candidate_score and reduce RMSE, leading to better final accuracy.", "instruction": "Replace llm_local_solve with a more robust initial solver (e.g., llm_global_solve or few-shot) to improve initial candidate quality.", "target": "initial_solve"}
  - Topology may be an avoid-skill candidate for this condition
    type: operator_rule
    status: hypothesis
    confidence: 0.70
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed3_1779540301728957000, run:protocol_generated:sparse_peer_exchange_n8_seed4_1779540303954998000
    summary: Given repeated failures (full_coverage_wrong_answer_rate=1.0) and high cost (mean_token_cost=35097.5), this topology should be flagged as avoid-skill for n_agents=8, array_size=1024, objective=balanced. The sparse peer exchange structure is not suitable for this task size.
    operation_recommendations:
      - {"action_type": "flag_avoid_skill", "conditions": {"array_size": 1024, "n_agents": 8, "objective": "balanced"}, "expected_effect": "Prevent future use of this ineffective topology, saving cost and improving accuracy.", "instruction": "Add this skill to avoid list for condition n_agents=8, array_size=1024, objective=balanced. Prefer alternative topologies like binary_tree_reduce or hybrid_reduce_audit.", "target": "cf_topology_generated:sparse_peer_exchange__a8__arr1024"}
