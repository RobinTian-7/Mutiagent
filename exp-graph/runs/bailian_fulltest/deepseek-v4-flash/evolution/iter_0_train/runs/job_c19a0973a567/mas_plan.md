planner_mode: graph_generate
skill_id: none
topology_name: generated:budget_aware_partial
operators: llm_generate_dag
score: 0.0000
fallback_skill_id: none
rationale: First step reduces pairs, second step sends to primary 7 but only from agents that have data from two sources. Low cost (10 messages) but some agents never send.
protocol_steps: 2
protocol_messages: 7
