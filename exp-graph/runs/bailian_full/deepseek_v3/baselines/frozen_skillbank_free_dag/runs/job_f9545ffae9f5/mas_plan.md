planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [free-graph-fallback: Error code: 400 - {'error': {'message': '{"request_id":"779534718492429396","ResponseMeta":{"RequestId":"779534718492429396","ErrorCode":"Forbidden","ErrorMessage":"AccessKey:4TdUJvNBxCn-H-2drCpOZgMPHWF0g-JpYcn0cMATWZI IS UNAVAILABLE"}}', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_parameter_error'}, 'request_id': '79bd5444-b0af-9806-b3cf-d868f5a3a217'}]
protocol_steps: 2
protocol_messages: 63
