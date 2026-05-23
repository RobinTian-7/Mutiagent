planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [emperor-plan-fallback: llm planner failed: Error code: 429 - {'path': '/v1/chat/completions', 'error': 'Too Many Requests', 'message': 'Too Many Requests in a short period, please try again later', 'timestamp': 1779546173679, 'status': 429}]
protocol_steps: 2
protocol_messages: 63
