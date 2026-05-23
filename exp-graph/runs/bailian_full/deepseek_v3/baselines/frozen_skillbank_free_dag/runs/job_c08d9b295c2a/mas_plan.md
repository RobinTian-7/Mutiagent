planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [free-graph-fallback: Error code: 400 - {'error': {'message': '{"request_id":"779534716658898300","ResponseMeta":{"RequestId":"779534716658898300","ErrorCode":"Forbidden","ErrorMessage":"AccessKey:4TdUJvNBxCn-H-2drCpOZgMPHWF0g-JpYcn0cMATWZI IS UNAVAILABLE"}}', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_parameter_error'}, 'request_id': '35ec0bcf-dade-9354-b5f2-2efaf6c70fba'}]
protocol_steps: 2
protocol_messages: 63
