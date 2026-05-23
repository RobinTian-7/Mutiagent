planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 0.8500
fallback_skill_id: none
rationale: For 8 agents, balanced objective, and count-frequency task, mesh_star skill (cf_middle_ground_mesh_star) provides good coverage and accuracy (RMSE 0.05) with moderate cost (63 messages, 2600 tokens). Avoid sparse random due to unstable coverage. Mesh broadcast ensures all agents share local counts, then star sink aggregates to a single agent for final answer.
protocol_steps: 2
protocol_messages: 63
