report_id: batch_insight_report_20260523_123710
experiment_id: /Users/robintian/experiment/Agent-Expretional-Graph/exp-graph/runs/bailian_fulltest/deepseek-v4-flash/evolution/iter_2_train/collected/batch_evidence.jsonl

Batch-level MAS insights extracted from matrix evidence.

key_insights:
  - Hybrid reduce audit topology leads to full coverage but wrong answers
    type: risk_pattern
    status: observed
    confidence: 0.90
    evidence_refs: run:protocol_generated:hybrid_reduce_audit_n8_seed1_1779539795894468000, run:protocol_generated:hybrid_reduce_audit_n8_seed2_1779539757656430000, run:protocol_generated:hybrid_reduce_audit_n8_seed4_1779539785168668000
    summary: The generated hybrid reduce audit topology achieves full coverage (all agents contribute) but results in 100% wrong answers, indicating that the audit mechanism fails to correct errors and may propagate incorrect information.
    operation_recommendations:
      - {"action_type": "modify_edge_order", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Lower coverage but higher accuracy by preventing wrong answers from being aggregated.", "instruction": "Reduce fan-in to sinks in audit phase to limit propagation of incorrect information.", "target": "planner_policy"}
  - Low coverage gain indicates ineffective information sharing
    type: dynamics_pattern
    status: observed
    confidence: 0.85
    evidence_refs: trace:protocol_generated:hybrid_reduce_audit_n8_seed1_1779539795894468000, trace:protocol_generated:hybrid_reduce_audit_n8_seed2_1779539757656430000, trace:protocol_generated:hybrid_reduce_audit_n8_seed4_1779539785168668000
    summary: Mean coverage gain is only 0.1875, meaning agents barely improve their knowledge through communication. The topology fails to spread correct information.
    operation_recommendations:
      - {"action_type": "modify_sink_selection", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Higher coverage gain and final coverage.", "instruction": "Increase number of sinks or use different sink selection strategy to improve information dissemination.", "target": "planner_policy"}
  - High token cost with no accuracy benefit suggests inefficiency
    type: tradeoff
    status: observed
    confidence: 0.80
    evidence_refs: run:protocol_generated:hybrid_reduce_audit_n8_seed1_1779539795894468000, run:protocol_generated:hybrid_reduce_audit_n8_seed2_1779539757656430000, run:protocol_generated:hybrid_reduce_audit_n8_seed4_1779539785168668000
    summary: Mean token cost is high (19284) while accuracy is zero. The topology consumes resources without delivering correct answers.
    operation_recommendations:
      - {"action_type": "modify_provenance_flow", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Lower token cost without sacrificing accuracy (which is already zero).", "instruction": "Reduce number of messages or model calls by limiting redundant communication.", "target": "planner_policy"}
  - Topology may be overfitting to local solve initialization
    type: hypothesis
    status: hypothesis
    confidence: 0.60
    evidence_refs: trace:protocol_generated:hybrid_reduce_audit_n8_seed1_1779539795894468000, trace:protocol_generated:hybrid_reduce_audit_n8_seed2_1779539757656430000, trace:protocol_generated:hybrid_reduce_audit_n8_seed4_1779539785168668000
    summary: With llm_local_solve init, agents start with partial solutions. The hybrid reduce audit may be reinforcing local errors rather than correcting them.
    operation_recommendations:
      - {"action_type": "modify_trigger_buckets", "conditions": {"init_mode": "llm_local_solve"}, "expected_effect": "If accuracy improves, the topology is sensitive to initialization.", "instruction": "Test with different init modes (e.g., random) to see if accuracy improves.", "target": "planner_policy"}
  - Sparse peer exchange with top-k selection leads to full coverage but wrong answers
    type: risk_pattern
    status: hypothesis
    confidence: 0.80
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed3_1779539791688312000, trace:protocol_generated:sparse_peer_exchange_n8_seed3_1779539791688312000
    summary: The sparse peer exchange topology with top-k graph search mode achieved full coverage (mean_final_coverage=0.5625, but full_coverage_wrong_answer_rate=1.0) meaning all agents converged on an answer but it was incorrect. This suggests that the exchange of partial solutions among peers without a global reduction or verification step can propagate errors.
    operation_recommendations:
      - {"action_type": "change_edge_order", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Reduce full_coverage_wrong_answer_rate by ensuring a consensus or verification mechanism.", "instruction": "Add a final global reduction step after peer exchange to aggregate and verify answers before final output.", "target": "sparse_peer_exchange"}
      - {"action_type": "change_sink_selection", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Improve answer accuracy by introducing verification points.", "instruction": "Designate a subset of agents as sinks that collect and cross-check results from peers before finalizing.", "target": "sparse_peer_exchange"}
  - Low mean coverage gain suggests limited information propagation
    type: dynamics_pattern
    status: hypothesis
    confidence: 0.70
    evidence_refs: trace:protocol_generated:sparse_peer_exchange_n8_seed3_1779539791688312000
    summary: Mean coverage gain of 0.4375 indicates that on average, agents only improved their coverage by less than half during the protocol. Combined with low final coverage (0.5625), this suggests that the sparse peer exchange structure does not effectively propagate information across all agents.
    operation_recommendations:
      - {"action_type": "change_fan_in", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Higher mean coverage gain and final coverage.", "instruction": "Increase the number of peers each agent exchanges with (fan-in) to improve information spread.", "target": "sparse_peer_exchange"}
      - {"action_type": "change_provenance_flow", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Increase coverage gain by ensuring all agents have a baseline of shared information.", "instruction": "Add a broadcast phase after initial local solves to share all partial results before peer exchange.", "target": "sparse_peer_exchange"}
  - Top-k graph search mode may cause premature convergence on wrong answers
    type: risk_pattern
    status: hypothesis
    confidence: 0.60
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed3_1779539791688312000
    summary: Using top-k selection for graph search likely caused agents to favor high-scoring but incorrect partial solutions, leading to full coverage on a wrong answer. The mean selected candidate score (-15.4) indicates that the top-k selection was not effective at identifying correct partial solutions.
    operation_recommendations:
      - {"action_type": "change_trigger_buckets", "conditions": {"graph_search_mode": "topk"}, "expected_effect": "Reduce full_coverage_wrong_answer_rate by maintaining solution diversity.", "instruction": "Replace top-k selection with a diversity-aware selection mechanism that avoids converging on similar wrong answers.", "target": "sparse_peer_exchange"}
