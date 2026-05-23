---
skill_id: cf_topology_generated:sparse_peer_exchange
version: 0.1.0
task_family: count_frequency
objective: balanced
---
# cf_topology_generated:sparse_peer_exchange

## Organization Policy

```json
{
  "operation_recommendations": [
    {
      "action_type": "preserve",
      "conditions": {
        "agent_bucket": "agents_any",
        "array_size_bucket": null,
        "condition_key": "agents_any__arrays_any"
      },
      "instruction": "Apply this skill only inside the recorded agent and array-size condition bucket unless held-out evidence expands it.",
      "target": "condition_trigger"
    },
    {
      "action_type": "mutate",
      "expected_effect": {
        "candidate_diversity": "increase"
      },
      "instruction": "When exploring variants, change fan-in, sink placement, or audit edges while keeping full temporal reachability to the selected primary.",
      "target": "free_graph_generation"
    }
  ],
  "operators": [],
  "planner_mode": "graph_generate",
  "protocol_spec": null,
  "structure_features": {
    "aggregation_pattern": "peer_exchange",
    "evidence_metadata_keys": [],
    "generated_graph": true,
    "mean_protocol_messages": 0.0,
    "mean_protocol_steps": 0.0,
    "motifs": [
      "peer_exchange"
    ],
    "selected_primary_values": [],
    "sink_pattern": "not_explicit",
    "topology_name": "generated:sparse_peer_exchange"
  },
  "topology_name": "generated:sparse_peer_exchange"
}
```

## Expected Tradeoff

```json
{
  "lesson": "Observed CF evidence for topology generated:sparse_peer_exchange.",
  "trace_record_count": 1
}
```

## Expected Dynamics

```json
{
  "aggregation_reliability": {
    "mean_sink_best_rmse_gap": 0.0,
    "mean_sink_coverage": 1.0
  },
  "condition_scope": {
    "agent_bucket": "agents_any",
    "agent_counts": [],
    "condition_key": "agents_any__arrays_any",
    "max_agents": 999,
    "min_agents": 1
  },
  "coverage_growth": {
    "mean_coverage_gain": 0.4375,
    "mean_final_coverage": 0.5625,
    "mean_final_max_coverage": 1.0
  },
  "merge_quality": {
    "mean_avg_fan_in": 0.8,
    "mean_parse_errors": 0.0,
    "mean_retry_attempts": 0.0
  },
  "protocol_spec_hash": null,
  "risk_tags": [
    "full_coverage_wrong_answer"
  ],
  "structure_features": {
    "aggregation_pattern": "peer_exchange",
    "evidence_metadata_keys": [],
    "generated_graph": true,
    "mean_protocol_messages": 0.0,
    "mean_protocol_steps": 0.0,
    "motifs": [
      "peer_exchange"
    ],
    "selected_primary_values": [],
    "sink_pattern": "not_explicit",
    "topology_name": "generated:sparse_peer_exchange"
  }
}
```

## Evidence Refs

```json
[
  "trace:protocol_generated:sparse_peer_exchange_n8_seed4_1779538540115170000"
]
```

## Evidence

```json
[]
```

## Risk Notes

```json
[]
```

## Fallback

```json
{
  "budget_first": "cf_budget_tree"
}
```
