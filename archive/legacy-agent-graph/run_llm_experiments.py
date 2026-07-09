import json
import os
import sys
import threading
import time
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent / "exp-graph"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ----------------- Ollama + MLX/Metal Configuration -----------------
# Point the OpenAI-compatible client at local Ollama.
# Ollama on Apple Silicon uses Metal (MLX-style GPU acceleration) by default;
# the env vars below make the configuration explicit.
BASE_URL = "http://localhost:11434/v1"
API_KEY = "ollama"           # Ollama ignores the value but the client needs one
MODEL_NAME = "gemma4:e4b"

os.environ["OPENAI_API_KEY"] = API_KEY
os.environ["OPENAI_BASE_URL"] = BASE_URL
os.environ["OPENAI_TIMEOUT"] = "300"       # Local inference can be slower than cloud
os.environ["OPENAI_MAX_RETRIES"] = "1"

# Ollama Metal / MLX acceleration (defaults on Apple Silicon, set explicitly)
os.environ.setdefault("OLLAMA_METAL", "1")           # Metal GPU backend
os.environ.setdefault("OLLAMA_FLASH_ATTENTION", "1") # Flash-attention kernel
os.environ.setdefault("OLLAMA_NUM_PARALLEL", "4")    # Ollama-side request slots

from exp_graph.configs import ExperimentConfig
from exp_graph.llm.factory import create_llm_client
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import ArraySearchTaskAdapter

import matplotlib.pyplot as plt
import pandas as pd

# ----------------- Concurrency Budget -----------------
# With 48 GB unified memory and gemma4:eb4 (Q4 weights ~13 GB + KV cache),
# cap in-flight LLM calls to 4 so we never pressure VRAM beyond ~80 % capacity.
# The ThreadPoolExecutor inside SynchronousRunner submits one Future per agent;
# this semaphore throttles how many can actually hit Ollama simultaneously.
MAX_CONCURRENT_LLM = 4


class _ThrottledClient:
    """Wraps any LLMClient with a semaphore and exponential-backoff retry.

    Handles transient 502/503/504 errors that Ollama emits when the model is
    loading or when concurrent KV-cache pressure causes a temporary failure.
    """

    def __init__(self, inner, max_concurrent: int, max_retries: int = 5) -> None:
        self._inner = inner
        self._sem = threading.Semaphore(max_concurrent)
        self._max_retries = max_retries

    def complete(self, prompt: str, model_name: str, temperature=None):
        delay = 2.0
        for attempt in range(self._max_retries):
            try:
                with self._sem:
                    return self._inner.complete(prompt, model_name, temperature)
            except Exception as exc:
                msg = str(exc)
                # Retry on transient gateway / server errors from Ollama
                is_transient = any(
                    code in msg for code in ("502", "503", "504", "Connection", "timeout")
                )
                if is_transient and attempt < self._max_retries - 1:
                    print(f"    [retry {attempt + 1}/{self._max_retries - 1}] {msg[:80]} — waiting {delay:.0f}s")
                    time.sleep(delay)
                    delay = min(delay * 2, 60.0)
                else:
                    raise


# Topology order: mesh → one_peer_exponential → ring
# (ring replaces chain — bidirectional cycle with wrap-around edges)
TOPOLOGIES = ["mesh", "one_peer_exponential", "ring"]
AGENT_COUNTS = [8, 16, 32, 64]
MAX_ROUNDS = 3
ARRAY_SIZE = 32
OUTPUT_DIR = Path(__file__).resolve().parent / "llm_experiment_v2_results"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def run_experiment_grid():
    ensure_dir(OUTPUT_DIR / "raw_data")

    # Build a single throttled client shared across all runs so the semaphore
    # is effective even when experiments overlap inside each round's thread pool.
    llm_client = _ThrottledClient(create_llm_client("openai"), MAX_CONCURRENT_LLM)

    results_list = []

    for topology in TOPOLOGIES:
        for n_agents in AGENT_COUNTS:
            print(f"\n[{topology.upper()}] Running {n_agents} agents...")

            file_name = f"{topology}_{n_agents}_agents.json"
            file_path = OUTPUT_DIR / "raw_data" / file_name
            if file_path.exists():
                print(f"  -> Skipping {topology} with {n_agents} agents (already run)")
                with open(file_path, "r") as f:
                    metrics = json.load(f)
                results_list.append(_metrics_to_row(topology, n_agents, metrics))
                continue

            task_adapter = ArraySearchTaskAdapter()
            global_task = task_adapter.build_global_task(
                array_size=ARRAY_SIZE, seed=42, ensure_present=True
            )

            config = ExperimentConfig(
                topology_name=topology,
                n_agents=n_agents,
                max_rounds=MAX_ROUNDS,
                seed=42,
                model_name=MODEL_NAME,
                llm_provider="openai",
                json_retry_attempts=2,
                trace_enabled=True,
                trace_dir=str(OUTPUT_DIR / "traces"),
            )

            try:
                runner = SynchronousRunner(
                    config=config,
                    task_adapter=task_adapter,
                    global_task=global_task,
                    llm_client=llm_client,
                )

                result = runner.run()
                metrics = result.metrics.model_dump()

                with open(OUTPUT_DIR / "raw_data" / file_name, "w") as f:
                    json.dump(metrics, f, indent=2)

                row = _metrics_to_row(topology, n_agents, metrics)
                results_list.append(row)

                print(
                    f"  -> Consensus: rounds={metrics['rounds_to_consensus']}, "
                    f"accuracy={metrics['final_accuracy']:.2f}"
                )

            except Exception as e:
                print(f"  -> Failed: {e}")

    return pd.DataFrame(results_list)


def _metrics_to_row(topology: str, n_agents: int, metrics: dict) -> dict:
    return {
        "Topology": topology,
        "Agents": n_agents,
        "RoundsToConsensus": metrics["rounds_to_consensus"],
        "FinalAccuracy": metrics["final_accuracy"],
        "ModelCalls": metrics["total_model_calls"],
        "TokenCost": metrics["total_token_cost"],
    }


def generate_visualizations(df, output_dir):
    ensure_dir(output_dir)

    plt.style.use("seaborn-v0_8-darkgrid")

    colors = {
        "mesh": "red",
        "one_peer_exponential": "green",
        "ring": "blue",
    }

    # 1. Rounds to Consensus
    plt.figure(figsize=(8, 5))
    for topo in TOPOLOGIES:
        sub_df = df[df["Topology"] == topo]
        if sub_df.empty:
            continue
        plt.plot(
            sub_df["Agents"], sub_df["RoundsToConsensus"],
            marker="o", label=topo, color=colors[topo], linewidth=2,
        )
    plt.title("Rounds to Consensus vs Agent Count")
    plt.xlabel("Number of Agents")
    plt.ylabel("Rounds (-1 means failed)")
    plt.xticks(AGENT_COUNTS)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "rounds_to_consensus.png")
    plt.close()

    # 2. Final Accuracy
    plt.figure(figsize=(8, 5))
    for topo in TOPOLOGIES:
        sub_df = df[df["Topology"] == topo]
        if sub_df.empty:
            continue
        plt.plot(
            sub_df["Agents"], sub_df["FinalAccuracy"],
            marker="s", label=topo, color=colors[topo], linewidth=2,
        )
    plt.title("Final Accuracy vs Agent Count")
    plt.xlabel("Number of Agents")
    plt.ylabel("Accuracy")
    plt.xticks(AGENT_COUNTS)
    plt.ylim(-0.05, 1.05)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "final_accuracy.png")
    plt.close()

    # 3. Token Cost
    plt.figure(figsize=(8, 5))
    for topo in TOPOLOGIES:
        sub_df = df[df["Topology"] == topo]
        if sub_df.empty:
            continue
        plt.plot(
            sub_df["Agents"], sub_df["TokenCost"],
            marker="^", label=topo, color=colors[topo], linewidth=2,
        )
    plt.title("Total Token Cost vs Agent Count")
    plt.xlabel("Number of Agents")
    plt.ylabel("Estimated Tokens")
    plt.xticks(AGENT_COUNTS)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "token_cost.png")
    plt.close()


def generate_report(df, output_dir):
    report_path = output_dir / "experiment_report.md"
    df_md = df.to_markdown(index=False)

    with open(report_path, "w") as f:
        f.write("# LLM Multi-Agent Topology Experiment Report\n\n")
        f.write(f"**Model Used:** {MODEL_NAME} via local Ollama (Metal/MLX)\n\n")

        f.write("## Overview\n\n")
        f.write(
            "This experiment compares `mesh`, `one_peer_exponential`, and `ring` "
            "topologies on a distributed array search problem, scaling from 8 to "
            "64 agents. Inference runs locally on Apple Silicon with Ollama + "
            "Metal acceleration.\n\n"
        )

        f.write("## Raw Results Data\n\n")
        f.write(df_md + "\n\n")

        f.write("## Hypothesis & Findings\n\n")
        f.write(
            "- **Mesh**: Global visibility in one round but token cost grows O(n²).\n"
        )
        f.write(
            "- **One-Peer Exponential**: O(log n) propagation, minimising context "
            "explosion while approaching mesh quality.\n"
        )
        f.write(
            "- **Ring**: Linear propagation (O(n) rounds to reach all agents); "
            "serves as a baseline for sparse, local-only communication.\n\n"
        )

        f.write("## Visualizations\n\n")
        f.write("### 1. Rounds to Consensus\n")
        f.write(
            "*(Lower is better. `-1` means consensus was never reached within "
            "`MAX_ROUNDS`)*\n\n"
        )
        f.write("![Rounds to Consensus](rounds_to_consensus.png)\n\n")

        f.write("### 2. Final Accuracy\n")
        f.write("*(Higher is better. Max is `1.0`)*\n\n")
        f.write("![Final Accuracy](final_accuracy.png)\n\n")

        f.write("### 3. Total Token Cost\n")
        f.write("*(Lower is better)*\n\n")
        f.write("![Token Cost](token_cost.png)\n\n")


def _warmup(base_url: str, model: str) -> None:
    """Send one tiny request so Ollama loads the model before the real runs."""
    import urllib.request
    import urllib.error
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
        method="POST",
    )
    try:
        print(f"  Warming up {model} (first load may take ~30 s)...", end=" ", flush=True)
        with urllib.request.urlopen(req, timeout=120):
            pass
        print("done.")
    except Exception as exc:
        print(f"warmup failed ({exc}), continuing anyway.")


if __name__ == "__main__":
    print("Starting LLM Multi-Agent Topology Simulation Grid...")
    print(f"  Model  : {MODEL_NAME} @ {BASE_URL}")
    print(f"  Topologies: {' -> '.join(TOPOLOGIES)}")
    print(f"  Agents : {AGENT_COUNTS}")
    print(f"  Max concurrent LLM calls: {MAX_CONCURRENT_LLM}")
    print()

    _warmup(BASE_URL, MODEL_NAME)

    df = run_experiment_grid()

    print("\nGenerating Visualizations...")
    generate_visualizations(df, OUTPUT_DIR)

    print("Generating Markdown Report...")
    generate_report(df, OUTPUT_DIR)

    print(f"\nDone! All results written to {OUTPUT_DIR}")
