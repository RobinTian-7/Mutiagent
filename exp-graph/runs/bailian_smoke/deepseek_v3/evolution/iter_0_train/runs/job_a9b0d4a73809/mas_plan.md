planner_mode: graph_generate
skill_id: none
topology_name: generated:two_phase_partial_aggregation
operators: llm_generate_dag
score: 0.0000
fallback_skill_id: none
rationale: Uses a first phase of pairwise local reduce to minimize messages, then converges to selected_primary via a star pattern to ensure complete coverage.
protocol_steps: 2
protocol_messages: 4
