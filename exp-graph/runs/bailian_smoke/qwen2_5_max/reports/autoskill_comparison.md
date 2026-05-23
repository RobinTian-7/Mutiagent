# AutoSkill Free-DAG MAS Comparison

- root: `/Users/robintian/experiment/Agent-Expretional-Graph/exp-graph/runs/bailian_smoke/qwen2_5_max`
- rows: `2`

| method | objective | planner_policy | topology_name | n_agents | array_size | run_count | mean_rmse | std_rmse | exact_match_rate | mean_messages | mean_model_calls | mean_token_cost | fallback_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| self_evolved_free_dag_best_so_far | balanced | free_graph | generated:hybrid_reduce_with_audit | 4 | 64 | 1 | 1 | 0 | 0 | 5 | 9 | 9942 | 0 |
| self_evolved_free_dag_iter_1 | balanced | free_graph | generated:hybrid_reduce_with_audit | 4 | 64 | 1 | 1 | 0 | 0 | 5 | 9 | 9942 | 0 |
