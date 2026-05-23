planner_mode: operator_compose
skill_id: none
topology_name: tree
operators: local_solve, tree_reduce
score: 0.8500
fallback_skill_id: cf_budget_tree
rationale: For 8 agents, balanced objective, and count-frequency task, cf_middle_ground_mesh_star is suitable but its mesh_broadcast may be costly. Instead, compose local_solve + tree_reduce to form a budget tree, which is evidence-backed for tight budgets and preserves coverage via hierarchical aggregation. Avoid sparse random due to unstable coverage.
protocol_steps: 3
protocol_messages: 7
