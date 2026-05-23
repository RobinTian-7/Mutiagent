planner_mode: operator_compose
skill_id: cf_budget_tree
topology_name: tree
operators: local_solve, tree_reduce
score: 0.9200
fallback_skill_id: none
rationale: Selected 'cf_budget_tree' logic via operator composition. With n_agents=8 and a balanced objective, the tree structure offers superior stability and coverage compared to sparse random DAGs (which are explicitly avoided due to seed sensitivity). The 'tree_reduce' operator ensures efficient aggregation with logarithmic message complexity, preserving source provenance while minimizing token costs relative to mesh-based alternatives.
protocol_steps: 3
protocol_messages: 7
alternatives:
  - {"rationale": "Fits n_agents=8 and balanced objective, but incurs higher token cost (2600) than necessary for this scale.", "skill_id": "cf_middle_ground_mesh_star"}
