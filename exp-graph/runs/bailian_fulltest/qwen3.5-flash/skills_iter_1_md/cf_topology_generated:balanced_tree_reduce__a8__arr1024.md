---
skill_id: cf_topology_generated:balanced_tree_reduce__a8__arr1024
version: 0.1.0
task_family: count_frequency
objective: balanced
---
# cf_topology_generated:balanced_tree_reduce__a8__arr1024

## Organization Policy

```json
{
  "operation_recommendations": [
    {
      "action_type": "preserve",
      "conditions": {
        "agent_bucket": "agents_8",
        "array_size_bucket": "arrays_1024",
        "condition_key": "agents_8__arrays_1024"
      },
      "instruction": "Apply this skill only inside the recorded agent and array-size condition bucket unless held-out evidence expands it.",
      "target": "condition_trigger"
    },
    {
      "action_type": "preserve",
      "expected_effect": {
        "coverage": "increase",
        "message_cost": "bounded"
      },
      "instruction": "Use staged reduce edges where every receiver that aggregates partials can forward the merged state in a later step.",
      "target": "edge_schedule"
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
      "selected_primary": 7
    },
    "n_agents": 8,
    "name": "balanced_tree_reduce",
    "operators": [
      "llm_generate_dag"
    ],
    "steps": [
      {
        "description": "Pairwise local aggregation: Even agents send to odd neighbors to form initial partial sums.",
        "operator": "pairwise_local_reduce",
        "transmissions": [
          [
            0,
            1
          ],
          [
            2,
            3
          ],
          [
            4,
            5
          ],
          [
            6,
            7
          ]
        ]
      },
      {
        "description": "Cross-pair aggregation: Winners from first round merge with next available partners to halve the active set.",
        "operator": "tree_reduce",
        "transmissions": [
          [
            1,
            3
          ],
          [
            5,
            7
          ]
        ]
      },
      {
        "description": "Final convergence: The two remaining partials merge into the primary sink.",
        "operator": "tree_reduce",
        "transmissions": [
          [
            3,
            7
          ]
        ]
      }
    ]
  },
  "structure_features": {
    "aggregation_pattern": "hierarchical",
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
      "hierarchical_reduce"
    ],
    "selected_primary_values": [
      7
    ],
    "sink_pattern": "single_selected_primary",
    "topology_name": "generated:balanced_tree_reduce"
  },
  "topology_name": "generated:balanced_tree_reduce"
}
```

## Expected Tradeoff

```json
{
  "active_evidence_count": 1,
  "exact_match_rate": 0.0,
  "lesson": "Observed CF evidence for topology generated:balanced_tree_reduce.",
  "mean_messages": 7.0,
  "mean_model_calls": 15.0,
  "mean_norm_l1": 0.0390625,
  "mean_rmse": 16.61324772583615,
  "mean_token_cost": 21858.0,
  "std_rmse": 0.0
}
```

## Expected Dynamics

```json
{
  "condition_scope": {
    "agent_bucket": "agents_8",
    "agent_counts": [
      8
    ],
    "array_size_bucket": "arrays_1024",
    "array_sizes": [
      1024
    ],
    "condition_key": "agents_8__arrays_1024",
    "max_agents": 8,
    "max_array_size": 1024,
    "min_agents": 8,
    "min_array_size": 1024
  },
  "protocol_spec_hash": "621c70610c57",
  "structure_features": {
    "aggregation_pattern": "hierarchical",
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
      "hierarchical_reduce"
    ],
    "selected_primary_values": [
      7
    ],
    "sink_pattern": "single_selected_primary",
    "topology_name": "generated:balanced_tree_reduce"
  }
}
```

## Evidence Refs

```json
[
  "run:protocol_generated:balanced_tree_reduce_n8_seed4_1779541165493723000"
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
