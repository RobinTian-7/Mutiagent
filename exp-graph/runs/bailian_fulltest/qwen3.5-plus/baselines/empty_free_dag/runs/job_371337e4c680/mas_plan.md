planner_mode: graph_generate
skill_id: none
topology_name: generated:balanced_binary_tree_reduce
operators: llm_generate_dag
score: 0.0000
fallback_skill_id: none
rationale: Classic logarithmic depth reduction. Pairs merge in step 1, pairs of pairs in step 2, and final two merge into sink 7 in step 3. Ensures full coverage with minimal steps and balanced fan-in.
protocol_steps: 3
protocol_messages: 7
