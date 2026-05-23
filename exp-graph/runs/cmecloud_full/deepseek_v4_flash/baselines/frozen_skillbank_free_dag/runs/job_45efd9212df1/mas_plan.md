planner_mode: operator_compose
skill_id: cf_middle_ground_mesh_star
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 1.0000
fallback_skill_id: cf_accuracy_peer_star
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [free-graph-fallback: Error code: 400 - {'error': {'message': "async scheduling with spec decoding doesn't yet support penalties, bad words or structured outputs in sampling parameters.", 'type': 'BadRequestError', 'param': None, 'code': 400}}]
protocol_steps: 2
protocol_messages: 63
