planner_mode: operator_compose
skill_id: cf_avoid_sparse_random
topology_name: tree
operators: local_solve, tree_reduce
score: 0.9200
fallback_skill_id: cf_budget_tree
rationale: Selected 'cf_budget_tree' as the primary skill because the request specifies n_agents=8 and a balanced objective. The 'avoid_or_counterexample_skills' explicitly warn against sparse random DAGs for count-frequency tasks due to seed sensitivity and coverage issues. While 'cf_middle_ground_mesh_star' offers high accuracy, its quadratic message growth (mean_messages: 63) is less efficient than the tree structure for this agent count under a normal budget. The tree topology ensures stable source coverage and provenance with significantly lower token costs (mean_token_cost: ~1400 vs 2600) while maintaining acceptable RMSE (0.42), aligning with the evidence-backed preference for structured aggregation over unvalidated random topologies.
protocol_steps: 3
protocol_messages: 7
