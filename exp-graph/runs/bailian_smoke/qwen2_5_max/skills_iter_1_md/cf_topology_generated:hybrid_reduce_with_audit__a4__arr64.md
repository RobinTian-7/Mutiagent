---
skill_id: cf_topology_generated:hybrid_reduce_with_audit__a4__arr64
version: 0.1.0
task_family: count_frequency
objective: balanced
---
# cf_topology_generated:hybrid_reduce_with_audit__a4__arr64

## Organization Policy

```json
{
  "operation_recommendations": [
    {
      "action_type": "preserve",
      "conditions": {
        "agent_bucket": "agents_4",
        "array_size_bucket": "arrays_64",
        "condition_key": "agents_4__arrays_64"
      },
      "instruction": "Apply this skill only inside the recorded agent and array-size condition bucket unless held-out evidence expands it.",
      "target": "condition_trigger"
    },
    {
      "action_type": "preserve",
      "expected_effect": {
        "final_answer_noise": "decrease"
      },
      "instruction": "Set selected_primary to the final sink and score only that answer holder for generated DAG runs.",
      "target": "final_reducer"
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
  "protocol_spec": {
    "metadata": {
      "candidate_id": "candidate_0",
      "fallback_topology": "tree",
      "generated_graph": true,
      "graph_type": "temporal_dag",
      "max_messages": 32,
      "max_receiver_fan_in": 4,
      "max_steps": 4,
      "selected_primary": 3
    },
    "n_agents": 4,
    "name": "hybrid_reduce_with_audit",
    "operators": [
      "llm_generate_dag"
    ],
    "steps": [
      {
        "description": "Pairwise local aggregation to reduce redundancy early.",
        "operator": "pairwise local reduce",
        "transmissions": [
          [
            0,
            1
          ],
          [
            2,
            3
          ]
        ]
      },
      {
        "description": "Forward aggregated partials toward the sink agent for further merging.",
        "operator": "sparse peer exchange",
        "transmissions": [
          [
            1,
            3
          ],
          [
            0,
            2
          ]
        ]
      },
      {
        "description": "Audit step to ensure completeness of counts at the selected primary.",
        "operator": "audit sink with extra edge",
        "transmissions": [
          [
            2,
            3
          ]
        ]
      }
    ]
  },
  "structure_features": {
    "aggregation_pattern": "unspecified",
    "candidate_ids": [
      "candidate_0"
    ],
    "evidence_metadata_keys": [
      "candidate_id",
      "fallback_topology",
      "generated_graph",
      "graph_type",
      "max_messages",
      "max_receiver_fan_in",
      "max_steps",
      "selected_primary"
    ],
    "generated_graph": true,
    "mean_protocol_messages": 0.0,
    "mean_protocol_steps": 0.0,
    "motifs": [
      "unspecified_generated_structure"
    ],
    "selected_primary_values": [
      3
    ],
    "sink_pattern": "single_selected_primary",
    "topology_name": "generated:hybrid_reduce_with_audit"
  },
  "topology_name": "generated:hybrid_reduce_with_audit"
}
```

## Expected Tradeoff

```json
{
  "active_evidence_count": 1,
  "exact_match_rate": 0.0,
  "lesson": "Observed CF evidence for topology generated:hybrid_reduce_with_audit.",
  "mean_messages": 5.0,
  "mean_model_calls": 9.0,
  "mean_norm_l1": 0.015625,
  "mean_rmse": 1.0,
  "mean_token_cost": 9953.0,
  "std_rmse": 0.0
}
```

## Expected Dynamics

```json
{
  "condition_scope": {
    "agent_bucket": "agents_4",
    "agent_counts": [
      4
    ],
    "array_size_bucket": "arrays_64",
    "array_sizes": [
      64
    ],
    "condition_key": "agents_4__arrays_64",
    "max_agents": 4,
    "max_array_size": 64,
    "min_agents": 4,
    "min_array_size": 64
  },
  "protocol_spec_hash": "9994960ffdea",
  "structure_features": {
    "aggregation_pattern": "unspecified",
    "candidate_ids": [
      "candidate_0"
    ],
    "evidence_metadata_keys": [
      "candidate_id",
      "fallback_topology",
      "generated_graph",
      "graph_type",
      "max_messages",
      "max_receiver_fan_in",
      "max_steps",
      "selected_primary"
    ],
    "generated_graph": true,
    "mean_protocol_messages": 0.0,
    "mean_protocol_steps": 0.0,
    "motifs": [
      "unspecified_generated_structure"
    ],
    "selected_primary_values": [
      3
    ],
    "sink_pattern": "single_selected_primary",
    "topology_name": "generated:hybrid_reduce_with_audit"
  }
}
```

## Evidence Refs

```json
[
  "run:protocol_generated:hybrid_reduce_with_audit_n4_seed1_1779530611320084000"
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
