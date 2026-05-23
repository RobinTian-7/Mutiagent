planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [emperor-plan-fallback: llm planner failed: Error code: 404 - {'error': {'message': 'The model `qwen3.5-flash-newkey` does not exist or you do not have access to it.', 'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}, 'request_id': 'bbe096ca-2e3a-928c-802d-ef4375719b71'}]
protocol_steps: 2
protocol_messages: 63
