planner_mode: graph_generate
skill_id: none
topology_name: generated:hybrid_reduce_audit
operators: llm_generate_dag
score: 0.0000
fallback_skill_id: none
rationale: Combines pairwise local reduce with intermediate tree reduce and an audit edge to ensure full coverage. Uses 7 messages and 3 steps, staying within constraints. Selected primary 7 receives all partial counts.
protocol_steps: 3
protocol_messages: 8
