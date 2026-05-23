---
skill_id: cf_topology_generated:hybrid_reduce_audit__a8__arr1024
version: 0.1.1
task_family: count_frequency
objective: balanced
---
# cf_topology_generated:hybrid_reduce_audit__a8__arr1024

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
      "candidate_id": "skill_cf_topology_generated_hybrid_reduce_audit__a8__arr1024",
      "fallback_topology": "tree",
      "generated_graph": true,
      "graph_type": "temporal_dag",
      "max_messages": 32,
      "max_receiver_fan_in": 4,
      "max_steps": 4,
      "selected_primary": 7
    },
    "n_agents": 8,
    "name": "hybrid_reduce_audit",
    "operators": [
      "llm_generate_dag"
    ],
    "steps": [
      {
        "description": "Pairwise local reduce among leaves",
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
        "description": "Intermediate reduce: agents 1 and 3 send to agent 3; agents 5 and 7 send to agent 7",
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
        "description": "Final reduce: agent 3 sends to agent 7; audit edge from agent 0 to agent 7 to ensure coverage",
        "operator": "audit_sink_with_extra_edge",
        "transmissions": [
          [
            3,
            7
          ],
          [
            0,
            7
          ]
        ]
      }
    ]
  },
  "structure_features": {
    "aggregation_pattern": "unspecified",
    "candidate_ids": [
      "candidate_0",
      "skill_cf_topology_generated_hybrid_reduce_audit__a8__arr1024"
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
      7
    ],
    "sink_pattern": "single_selected_primary",
    "topology_name": "generated:hybrid_reduce_audit"
  },
  "topology_name": "generated:hybrid_reduce_audit"
}
```

## Expected Tradeoff

```json
{
  "active_evidence_count": 3,
  "exact_match_rate": 0.0,
  "lesson": "Observed CF evidence for topology generated:hybrid_reduce_audit.",
  "mean_messages": 8.0,
  "mean_model_calls": 15.0,
  "mean_norm_l1": 0.037109375,
  "mean_rmse": 15.64856888621651,
  "mean_token_cost": 19284.333333333332,
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
  "protocol_spec_hash": "4f8688cf78fc",
  "structure_features": {
    "aggregation_pattern": "unspecified",
    "candidate_ids": [
      "candidate_0",
      "skill_cf_topology_generated_hybrid_reduce_audit__a8__arr1024"
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
      7
    ],
    "sink_pattern": "single_selected_primary",
    "topology_name": "generated:hybrid_reduce_audit"
  }
}
```

## Evidence Refs

```json
[
  "run:protocol_generated:hybrid_reduce_audit_n8_seed2_1779539218226057000",
  "run:protocol_generated:hybrid_reduce_audit_n8_seed1_1779539795894468000",
  "run:protocol_generated:hybrid_reduce_audit_n8_seed2_1779539757656430000",
  "run:protocol_generated:hybrid_reduce_audit_n8_seed4_1779539785168668000"
]
```

## Evidence

```json
[]
```

## Risk Notes

```json
[
  {
    "confidence": 0.9,
    "patch_id": "cost_cf_topology_generated:hybrid_reduce_audit",
    "source": "cost_analyst",
    "summary": "generated:hybrid_reduce_audit is the lowest observed cost CF organization among compared topologies."
  }
]
```

## Fallback

```json
{
  "budget_first": "cf_budget_tree"
}
```
