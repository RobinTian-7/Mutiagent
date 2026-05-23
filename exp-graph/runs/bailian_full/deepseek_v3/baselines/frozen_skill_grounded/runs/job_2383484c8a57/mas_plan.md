planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [emperor-plan-fallback: llm planner failed: Error code: 400 - {'error': {'message': '{"request_id":"779534488965962493","ResponseMeta":{"RequestId":"779534488965962493","ErrorCode":"Forbidden","ErrorMessage":"AccessKey:4TdUJvNBxCn-H-2drCpOZgMPHWF0g-JpYcn0cMATWZI IS UNAVAILABLE"}}', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_parameter_error'}, 'request_id': '8d3006fe-c80b-90c4-83fa-daff7b13fa0b'}]
protocol_steps: 2
protocol_messages: 63
