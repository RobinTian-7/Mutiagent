planner_mode: graph_generate
skill_id: none
topology_name: generated:pairwise_reduce_then_star
operators: llm_generate_dag
score: 0.0000
fallback_skill_id: none
rationale: Pairwise local reduces in step1 cut messages, then star sink in step2 collects all partials; step3 audit ensures no missing coverage.
protocol_steps: 3
protocol_messages: 11
