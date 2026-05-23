planner_mode: graph_generate
skill_id: none
topology_name: generated:two_stage_merge
operators: llm_generate_dag
score: 0.0000
fallback_skill_id: none
rationale: Uses pairwise reduce in step 1, then a star to sink in step 2, ensuring all agents reach sink with low message count.
protocol_steps: 2
protocol_messages: 7
