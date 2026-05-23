planner_mode: operator_compose
skill_id: none
topology_name: mesh_star
operators: local_solve, mesh_broadcast, star_sink
score: 0.0000
fallback_skill_id: none
rationale: Composed finite ProtocolGraphSpec from organization operators: local_solve -> mesh_broadcast -> star_sink [free-graph-fallback: Error code: 400 - {'error': {'message': "async scheduling with spec decoding doesn't yet support penalties, bad words or structured outputs in sampling parameters.", 'type': 'BadRequestError', 'param': None, 'code': 400}}]
protocol_steps: 2
protocol_messages: 63
