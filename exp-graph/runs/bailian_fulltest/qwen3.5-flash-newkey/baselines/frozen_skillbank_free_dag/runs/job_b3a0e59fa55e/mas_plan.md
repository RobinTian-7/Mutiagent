planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [free-graph-fallback: Error code: 404 - {'error': {'message': 'The model `qwen3.5-flash-newkey` does not exist or you do not have access to it.', 'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}, 'request_id': 'c4f10ece-f025-96a2-a4b7-a633bb4fd333'}]
protocol_steps: 2
protocol_messages: 63
