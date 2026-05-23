# AutoSkill Free-DAG MAS Comparison

- root: `/Users/robintian/experiment/Agent-Expretional-Graph/exp-graph/runs/bailian_fulltest/deepseek-v4-flash`
- rows: `26`

| method | objective | planner_policy | topology_name | n_agents | array_size | run_count | mean_rmse | std_rmse | exact_match_rate | mean_messages | mean_model_calls | mean_token_cost | fallback_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_empty_free_dag | balanced | free_graph | generated:binary_tree_merge | 8 | 1024 | 2 | 16.629 | 4.05918 | 0 | 7 | 13.5 | 17311.5 | 0 |
| baseline_empty_free_dag | balanced | free_graph | generated:sparse_peer_exchange | 8 | 1024 | 1 | 7.74597 | 0 | 0 | 7 | 15 | 18857 | 0 |
| baseline_empty_free_dag | balanced | free_graph | generated:two_layer_hybrid | 8 | 1024 | 1 | 84.1546 | 0 | 0 | 7 | 12 | 15368 | 0 |
| baseline_fixed_topology | balanced | fixed_topology | mesh_star | 8 | 1024 | 4 | 12.8853 | 4.8958 | 0 | 63 | 17.25 | 38133.8 | 0 |
| baseline_fixed_topology | balanced | fixed_topology | one_peer_exponential_dag_star | 8 | 1024 | 4 | 12.5322 | 4.14654 | 0 | 31 | 33 | 48122 | 0 |
| baseline_fixed_topology | balanced | fixed_topology | tree | 8 | 1024 | 4 | 15.1429 | 8.52605 | 0 | 7 | 15 | 18888 | 0 |
| baseline_frozen_skill_grounded | balanced | skill_grounded | mesh_star | 8 | 1024 | 2 | 18.6744 | 6.34558 | 0 | 63 | 17 | 36339.5 | 0 |
| baseline_frozen_skill_grounded | balanced | llm_free | tree | 8 | 1024 | 4 | 13.9884 | 6.73233 | 0 | 7 | 15 | 18932.8 | 0 |
| baseline_frozen_skill_grounded | balanced | skill_grounded | tree | 8 | 1024 | 2 | 9.24037 | 2.75963 | 0 | 7 | 15 | 19032 | 0 |
| baseline_frozen_skillbank_free_dag | balanced | free_graph | generated:pairwise_reduce_then_star | 8 | 1024 | 3 | 86.8678 | 111.94 | 0 | 9.66667 | 15.6667 | 20852 | 0 |
| baseline_frozen_skillbank_free_dag | balanced | free_graph | generated:two_layer_tree_with_audit | 8 | 1024 | 1 | 12.8841 | 0 | 0 | 8 | 14 | 18530 | 0 |
| self_evolved_free_dag_best_so_far | balanced | free_graph | generated:hybrid_reduce_audit | 8 | 1024 | 1 | 7.87401 | 0 | 0 | 8 | 15 | 19422 | 0 |
| self_evolved_free_dag_best_so_far | balanced | free_graph | generated:sparse_peer_exchange | 8 | 1024 | 3 | 14.2264 | 3.45576 | 0 | 20 | 25 | 35752.7 | 0 |
| self_evolved_free_dag_iter_1 | balanced | free_graph | generated:binary_tree_reduce | 8 | 1024 | 2 | 18.4029 | 9.2377 | 0 | 7 | 15 | 19184.5 | 0 |
| self_evolved_free_dag_iter_1 | balanced | free_graph | generated:hybrid_reduce_audit | 8 | 1024 | 1 | 15.4272 | 0 | 0 | 8 | 15 | 19245 | 0 |
| self_evolved_free_dag_iter_1 | balanced | free_graph | generated:sparse_peer_exchange | 8 | 1024 | 1 | 10.7703 | 0 | 0 | 20 | 25 | 35780 | 0 |
| self_evolved_free_dag_iter_2 | balanced | free_graph | generated:budget_aware_partial | 8 | 1024 | 1 | 12.2474 | 0 | 0 | 7 | 13 | 16533 | 0 |
| self_evolved_free_dag_iter_2 | balanced | free_graph | generated:hybrid_reduce_audit | 8 | 1024 | 3 | 15.6136 | 3.58931 | 0 | 8 | 15 | 19496 | 0 |
| self_evolved_free_dag_iter_3 | balanced | free_graph | generated:hybrid_reduce_audit | 8 | 1024 | 1 | 9.69536 | 0 | 0 | 8 | 15 | 20009 | 0 |
| self_evolved_free_dag_iter_3 | balanced | free_graph | generated:sparse_peer_exchange | 8 | 1024 | 2 | 15.3264 | 4.01269 | 0 | 20 | 25 | 35184.5 | 0 |
| self_evolved_free_dag_iter_3 | balanced | free_graph | generated:two_stage_merge | 8 | 1024 | 1 | 17.72 | 0 | 0 | 7 | 13 | 16576 | 0 |
| self_evolved_free_dag_iter_4 | balanced | free_graph | generated:hybrid_reduce_audit | 8 | 1024 | 1 | 12.5698 | 0 | 0 | 8 | 15 | 19235 | 0 |
| self_evolved_free_dag_iter_4 | balanced | free_graph | generated:pairwise_then_star | 8 | 1024 | 2 | 16.9839 | 6.78584 | 0 | 7 | 13 | 16731 | 0 |
| self_evolved_free_dag_iter_4 | balanced | free_graph | generated:sparse_peer_exchange | 8 | 1024 | 1 | 165.257 | 0 | 0 | 20 | 25 | 35001 | 0 |
| self_evolved_free_dag_iter_5 | balanced | free_graph | generated:hybrid_reduce_audit | 8 | 1024 | 1 | 7.87401 | 0 | 0 | 8 | 15 | 19422 | 0 |
| self_evolved_free_dag_iter_5 | balanced | free_graph | generated:sparse_peer_exchange | 8 | 1024 | 3 | 14.2264 | 3.45576 | 0 | 20 | 25 | 35752.7 | 0 |
