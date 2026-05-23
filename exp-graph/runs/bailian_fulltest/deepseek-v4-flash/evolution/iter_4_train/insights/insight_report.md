report_id: batch_insight_report_20260523_125417
experiment_id: /Users/robintian/experiment/Agent-Expretional-Graph/exp-graph/runs/bailian_fulltest/deepseek-v4-flash/evolution/iter_4_train/collected/batch_evidence.jsonl

Batch-level MAS insights extracted from matrix evidence.

key_insights:
  - Budget-aware partial topology leads to full coverage but zero accuracy
    type: risk_pattern
    status: hypothesis
    confidence: 0.90
    evidence_refs: run:protocol_generated:budget_aware_partial_n8_seed2_1779540828288777000, trace:protocol_generated:budget_aware_partial_n8_seed2_1779540828288777000
    summary: The budget-aware partial topology achieved full coverage (all agents covered) but all answers were wrong (full_coverage_wrong_answer_rate=1.0). This indicates that the communication structure allowed agents to reach a consensus on an incorrect answer, likely due to insufficient diversity or verification.
    operation_recommendations:
      - {"action_type": "change_edge_order", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Reduce full_coverage_wrong_answer_rate by increasing answer diversity.", "instruction": "Increase fan-in to at least 3 agents per sink to ensure diverse perspectives before merging.", "target": "sink selection"}
      - {"action_type": "change_sink_selection", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Improve accuracy by allowing intermediate verification.", "instruction": "Add an additional sink layer with 2 sinks to create intermediate aggregations before final merge.", "target": "sink count"}
  - Low protocol steps and messages correlate with wrong answers despite full coverage
    type: dynamics_pattern
    status: hypothesis
    confidence: 0.80
    evidence_refs: trace:protocol_generated:budget_aware_partial_n8_seed2_1779540828288777000
    summary: The topology used only 2 protocol steps and 7 messages on average, which is low for 8 agents on 1024-sized array. This suggests that agents did not have enough communication rounds to correct errors, leading to a consensus on wrong answers.
    operation_recommendations:
      - {"action_type": "change_edge_order", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Allow more iterative refinement and reduce wrong answer rate.", "instruction": "Increase minimum protocol steps to 3 for n_agents=8, array_size=1024.", "target": "protocol depth"}
  - Budget-aware partial topology may be unsuitable for balanced objective
    type: tradeoff
    status: hypothesis
    confidence: 0.60
    evidence_refs: run:protocol_generated:budget_aware_partial_n8_seed2_1779540828288777000
    summary: The topology was designed for budget awareness but the objective was balanced. The low cost (mean tokens 16424) came at the expense of accuracy (RMSE 15.81). This suggests a tradeoff where budget-aware structures sacrifice accuracy too much for balanced objectives.
    operation_recommendations:
      - {"action_type": "change_sink_selection", "conditions": {"objective": "balanced"}, "expected_effect": "Improve accuracy while keeping cost moderate.", "instruction": "For balanced objective, use at least 2 sinks to ensure accuracy is not sacrificed.", "target": "sink count"}
  - Sparse peer exchange leads to full coverage but zero accuracy due to error propagation
    type: risk_pattern
    status: hypothesis
    confidence: 0.80
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed1_1779540814259220000, run:protocol_generated:sparse_peer_exchange_n8_seed4_1779540794073775000, trace:protocol_generated:sparse_peer_exchange_n8_seed1_1779540814259220000, trace:protocol_generated:sparse_peer_exchange_n8_seed4_1779540794073775000
    summary: The sparse peer exchange topology achieved full coverage (mean final coverage 0.5625, but full_coverage_wrong_answer_rate=1.0) meaning all agents were reached but all final answers were incorrect. This suggests that the sparse exchange structure propagated errors without any verification or correction mechanism.
    operation_recommendations:
      - {"action_type": "change_edge_order", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Reduce error propagation by allowing the sink to compare multiple partial results.", "instruction": "Increase fan-in at the sink agent to at least 3 predecessors to allow cross-verification before final answer.", "target": "sink_selection"}
      - {"action_type": "change_sink_selection", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Improve final answer quality by routing through a more reliable agent.", "instruction": "Select the agent with highest local accuracy as the sink, or use a separate verification agent as sink.", "target": "sink_agent"}
      - {"action_type": "change_provenance_flow", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Enable error detection and correction by tracking data lineage.", "instruction": "Add provenance metadata to each message so that the sink can trace the origin of values and detect inconsistencies.", "target": "provenance_tracking"}
  - Low fan-in and no verification cause error amplification in sparse exchange
    type: design_principle
    status: hypothesis
    confidence: 0.70
    evidence_refs: trace:protocol_generated:sparse_peer_exchange_n8_seed1_1779540814259220000, trace:protocol_generated:sparse_peer_exchange_n8_seed4_1779540794073775000
    summary: With only 4 mean candidate count and 20 messages, the sparse peer exchange has low redundancy. Errors from early agents propagate to later agents without correction, leading to uniformly wrong final answers.
    operation_recommendations:
      - {"action_type": "change_fan_in", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Increase redundancy and reduce error propagation.", "instruction": "Set minimum fan-in for sink to 3 to ensure multiple inputs are merged.", "target": "sink_agent"}
      - {"action_type": "change_reducer_scope", "conditions": {"array_size": 1024, "n_agents": 8}, "expected_effect": "Improve accuracy by combining multiple estimates with weighting.", "instruction": "Use a more sophisticated merge that includes confidence weighting or majority voting instead of llm_full_merge.", "target": "merge_mode"}
  - Sparse peer exchange may be unsuitable for large arrays without verification steps
    type: scaling_pattern
    status: hypothesis
    confidence: 0.60
    evidence_refs: run:protocol_generated:sparse_peer_exchange_n8_seed1_1779540814259220000, run:protocol_generated:sparse_peer_exchange_n8_seed4_1779540794073775000
    summary: For array size 1024, the sparse exchange topology fails completely (RMSE 13.39). This suggests that for large arrays, sparse communication without verification is insufficient to aggregate accurate information.
    operation_recommendations:
      - {"action_type": "change_trigger_buckets", "conditions": {"array_size": 1024}, "expected_effect": "Prevent catastrophic accuracy loss on large arrays.", "instruction": "Avoid sparse peer exchange for array_size > 512; use hierarchical or audit-based topologies instead.", "target": "topology_selection"}

rejected_insights:
  - {"insight_id": "insight_001", "reason": "affected_skill_topology_mismatch"}
  - {"insight_id": "insight_002", "reason": "affected_skill_topology_mismatch"}
  - {"insight_id": "insight_003", "reason": "affected_skill_topology_mismatch"}
