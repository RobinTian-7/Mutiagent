import asyncio
import json
import os
import time
import sys

# insert the parent directory to sys.path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_policy import LLMAgentPolicy, cleanup_llm_clients
from environment import MultiAgentEnvironment
from problems.newsgroup_frequency import NewsGroupFrequencyProblem
from visualization import plot_dig_graph
from viz_interactive import create_interactive_viz

from sklearn.datasets import fetch_20newsgroups

'''
Return values:

- documents: List[Dict[str, str]]
[{
  "doc_id": str,
  "category": str,
  "text": str
}, ...]

- categories: List[str]
'''
def load_20ng_all_standardized(remove=("headers", "footers", "quotes"),):
    bunch = fetch_20newsgroups(subset="all", remove=remove, shuffle=False)
    categories = list(bunch.target_names)

    documents = []
    for i, text in enumerate(bunch.data):
        label_idx = int(bunch.target[i])
        documents.append({
            "doc_id": f"all_{i}",
            "category": categories[label_idx],
            "text": text,
        })

    return documents, categories

async def run_environment_async(env, timeout_seconds):
    """Async wrapper to run environment and cleanup properly."""
    result = await env.run(timeout_seconds=timeout_seconds)
    
    # Cleanup all LLM clients before event loop closes
    await cleanup_llm_clients()
    
    # Give async cleanup tasks a moment to complete
    await asyncio.sleep(0.1)
    return result


if __name__ == "__main__":
    docs, categories = load_20ng_all_standardized()

    timeout_seconds = 15

    problem = NewsGroupFrequencyProblem(docs, categories)

    agents = {
        f"agent_{i}": LLMAgentPolicy(name=f"agent_{i}")
        for i in range(10)
    }

    env = MultiAgentEnvironment(problem=problem, agents=agents)

    dig, winning_event, num_activations, timed_out = asyncio.run(
        run_environment_async(env, timeout_seconds)
    )

    print("\n=== Run finished ===")
    if timed_out:
        print(f"Stopped due to time limit. Total activations: {num_activations}.")
    else:
        print(f"Stopped normally. Total activations: {num_activations}.")

    if winning_event is None:
        print("No winning solution event found.")
    else:
        print("Winning event id:", winning_event.id)
        print("Winning payload:")
        print(json.dumps(winning_event.payload, indent=2))

    print("\nDIG summary")
    print(f"Total events: {len(dig.events)}")
    print(f"Total activations: {len(dig.activations)}")

    # Create output folder
    ts = int(time.time())
    output_dir = f"run_output_{ts}"
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nCreated output directory: {output_dir}")

    # Calculate reference time (first activation start)
    t0 = min(a.started_at for a in dig.activations.values()) if dig.activations else 0

    # Save DIG JSON
    json_filename = os.path.join(output_dir, "dig_data.json")

    dig_data = {
        "events": {
            eid: {
                "id": e.id,
                "payload": e.payload,
                "source_activation_id": e.source_activation_id,
                "recipients": e.recipients,
                "generated_at": e.generated_at - t0,
                "received_at": {agent: t - t0 for agent, t in e.received_at.items()},
                "delivery_policy": e.delivery_policy,
            }
            for eid, e in dig.events.items()
        },
        "activations": {
            aid: {
                "id": a.id,
                "agent_name": a.agent_name,
                "mode": a.mode.value,
                "input_event_ids": a.input_event_ids,
                "output_event_ids": a.output_event_ids,
                "started_at": a.started_at - t0,
                "ended_at": a.ended_at - t0,
            }
            for aid, a in dig.activations.items()
        },
        "metadata": {
            "timed_out": timed_out,
            "num_activations": num_activations,
            "solution_found": winning_event is not None,
            "problem_name": problem.name,
            "reference_time": t0,
        },
    }

    with open(json_filename, "w") as f:
        json.dump(dig_data, f, indent=2)
    print(f"DIG JSON saved to: {json_filename}")

    # Save activation logs in JSONL format (one line per activation)
    activations_file = os.path.join(output_dir, "activations.jsonl")
    
    with open(activations_file, "w") as f:
        for aid, activation in dig.activations.items():
            activation_log = {
                "activation_id": activation.id,
                "agent_name": activation.agent_name,
                "mode": activation.mode.value,
                "started_at": activation.started_at - t0,
                "ended_at": activation.ended_at - t0,
                "duration": activation.ended_at - activation.started_at,
                "input_event_ids": activation.input_event_ids,
                "output_event_ids": activation.output_event_ids,
                "input_events": [
                    {
                        "event_id": eid,
                        "payload": dig.events[eid].payload if eid in dig.events else None,
                        "msg": dig.events[eid].payload.get("msg", "") if eid in dig.events else "",
                    }
                    for eid in activation.input_event_ids
                ],
                "output_events": [
                    {
                        "event_id": eid,
                        "payload": dig.events[eid].payload if eid in dig.events else None,
                        "recipients": dig.events[eid].recipients if eid in dig.events else [],
                    }
                    for eid in activation.output_event_ids
                ],
            }
            f.write(json.dumps(activation_log) + "\n")
    
    print(f"Saved {len(dig.activations)} activation logs to: {activations_file}")

    # Save event logs in JSONL format (one line per event)
    events_file = os.path.join(output_dir, "events.jsonl")
    
    with open(events_file, "w") as f:
        for eid, event in dig.events.items():
            event_log = {
                "event_id": event.id,
                "generated_at": event.generated_at - t0,
                "source_activation_id": event.source_activation_id,
                "source_agent": None,
                "recipients": event.recipients,
                "payload": event.payload,
                "msg": event.payload.get("msg", ""),
                "type": event.payload.get("type", ""),
                "received_at": {agent: t - t0 for agent, t in event.received_at.items()},
                "delivery_policy": event.delivery_policy,
                "consumed_by_activations": [],
            }
            
            # Find source agent
            if event.source_activation_id and event.source_activation_id in dig.activations:
                event_log["source_agent"] = dig.activations[event.source_activation_id].agent_name
            
            # Find which activations consumed this event
            for aid, activation in dig.activations.items():
                if eid in activation.input_event_ids:
                    event_log["consumed_by_activations"].append({
                        "activation_id": aid,
                        "agent_name": activation.agent_name,
                        "mode": activation.mode.value,
                        "started_at": activation.started_at - t0,
                    })
            
            f.write(json.dumps(event_log) + "\n")
    
    print(f"Saved {len(dig.events)} event logs to: {events_file}")

    graph_filename = os.path.join(output_dir, "dig_graph.png")
    plot_dig_graph(dig, graph_filename)
    print(f"DIG graph saved to: {graph_filename}")
    
    # Create interactive HTML visualization
    interactive_filename = os.path.join(output_dir, "dig_interactive.html")
    create_interactive_viz(dig, interactive_filename, t0)
    print(f"Interactive visualization saved to: {interactive_filename}")

