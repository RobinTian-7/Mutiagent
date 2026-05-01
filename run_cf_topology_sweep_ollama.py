"""Run CF topology sweeps with Ollama as the local multi-agent LLM backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent / "exp-graph"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from exp_graph.agents import BeliefState
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import CountFrequencyTaskAdapter

from run_cf_topology_sweep import (
    DEFAULT_AGENT_COUNTS,
    DEFAULT_TOPOLOGIES,
    build_failed_row,
    build_row,
    ensure_dir,
    load_row,
    print_results_table,
    raw_result_path,
    write_json,
    write_outputs,
)


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "cf_topology_sweep_ollama_results"


class OllamaChatClient:
    """Small Ollama native chat API client.

    Ollama requests are JSON over HTTP, but message content still needs to be a
    string prompt. Structured output is requested with the top-level ``format``
    field instead of putting a dict into ``message.content``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        think: bool | str,
        format_mode: str,
        timeout: float,
        num_ctx: int | None,
        num_predict: int | None,
        keep_alive: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.think = think
        self.format_mode = format_mode
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.keep_alive = keep_alive

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0.0 if temperature is None else temperature,
            },
        }
        if self.num_ctx is not None:
            payload["options"]["num_ctx"] = self.num_ctx
        if self.num_predict is not None:
            payload["options"]["num_predict"] = self.num_predict
        if self.format_mode == "json":
            payload["format"] = "json"
        elif self.format_mode == "schema":
            payload["format"] = BeliefState.model_json_schema()
        elif self.format_mode != "none":
            raise ValueError("format_mode must be one of: json, schema, none")

        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. Is `ollama serve` running?"
            ) from exc

        message = data.get("message", {})
        text = str(message.get("content") or "{}")
        thinking = str(message.get("thinking") or "")
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=int(data.get("prompt_eval_count") or estimate_tokens(prompt)),
                completion_tokens=int(data.get("eval_count") or estimate_tokens(text)),
            ),
            raw_responses=[
                json.dumps(
                    {
                        "content": text,
                        "thinking": thinking,
                    },
                    ensure_ascii=True,
                )
            ],
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare CF topology behavior using local Ollama models."
    )
    parser.add_argument("--topologies", nargs="+", default=DEFAULT_TOPOLOGIES)
    parser.add_argument("--agent-counts", nargs="+", type=int, default=DEFAULT_AGENT_COUNTS)
    parser.add_argument("--array-size", type=int, default=1000)
    parser.add_argument("--value-min", type=int, default=0)
    parser.add_argument("--value-max", type=int, default=9)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-rounds", type=int, default=40)
    parser.add_argument("--consensus-threshold", type=float, default=0.8)
    parser.add_argument("--final-accept-threshold", type=float, default=0.7)
    parser.add_argument("--adjudication-margin", type=float, default=0.1)
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        help="Ollama server URL.",
    )
    parser.add_argument(
        "--model-name",
        default=os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
        help="Installed Ollama model name, e.g. qwen3:8b or llama3.1:8b.",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--json-retry-attempts", type=int, default=2)
    parser.add_argument("--config-retries", type=int, default=0)
    parser.add_argument(
        "--max-parallel-agents",
        type=int,
        default=2,
        help="Per-round local LLM concurrency. Default 2 for a 48GB MacBook.",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="Enable Ollama thinking for models that support it. Default is off.",
    )
    parser.add_argument(
        "--think-level",
        choices=["low", "medium", "high"],
        default=None,
        help="Use GPT-OSS style thinking levels instead of boolean think.",
    )
    parser.add_argument(
        "--format-mode",
        choices=["json", "schema", "none"],
        default="json",
        help="Ollama structured output mode.",
    )
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--keep-alive", default="5m")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--retain-traces", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.llm_provider = "ollama"
    ensure_dir(args.output_dir)
    ensure_dir(args.output_dir / "raw_data")
    if args.trace:
        ensure_dir(args.output_dir / "traces")

    rows = run_grid(args)
    write_outputs(rows, args)
    print_results_table(rows)
    print(f"\nReport written to: {args.output_dir / 'experiment_report.md'}")


def run_grid(args: argparse.Namespace) -> list[dict[str, Any]]:
    task_adapter = CountFrequencyTaskAdapter()
    global_task = task_adapter.build_global_task(
        array_size=args.array_size,
        seed=args.seed,
        value_min=args.value_min,
        value_max=args.value_max,
    )
    llm_client = OllamaChatClient(
        base_url=args.ollama_url,
        think=args.think_level if args.think_level is not None else bool(args.think),
        format_mode=args.format_mode,
        timeout=args.timeout,
        num_ctx=args.num_ctx,
        num_predict=args.num_predict,
        keep_alive=args.keep_alive,
    )

    rows = []
    for topology in args.topologies:
        for n_agents in args.agent_counts:
            result_path = raw_result_path(args.output_dir, topology, n_agents, args.seed)
            if args.resume and result_path.exists():
                print(f"\n[{topology} / {n_agents}] loading cached {result_path.name}")
                rows.append(load_row(result_path))
                continue

            print(f"\n[{topology} / {n_agents}] running CF Ollama sweep item...")
            config = ExperimentConfig(
                topology_name=topology,
                n_agents=n_agents,
                max_rounds=args.max_rounds,
                seed=args.seed,
                model_name=args.model_name,
                llm_provider="ollama",
                temperature=args.temperature,
                json_retry_attempts=args.json_retry_attempts,
                max_parallel_agents=args.max_parallel_agents,
                consensus_threshold=args.consensus_threshold,
                final_accept_threshold=args.final_accept_threshold,
                adjudication_margin=args.adjudication_margin,
                trace_enabled=args.trace,
                save_prompts=args.trace,
                retain_traces=args.retain_traces,
                trace_dir=str(args.output_dir / "traces") if args.trace else None,
                run_id=f"cf_ollama_{topology}_n{n_agents}_seed{args.seed}",
            )
            row = run_one_config(
                config=config,
                task_adapter=task_adapter,
                global_task=global_task,
                llm_client=llm_client,
                topology=topology,
                n_agents=n_agents,
                args=args,
            )
            write_json(result_path, row)
            rows.append(row)
            rmse_text = "NA" if row["RMSE"] is None else f"{row['RMSE']:.4f}"
            print(
                "  -> "
                f"rounds={row['RoundsToConsensus']}, "
                f"rmse={rmse_text}, "
                f"exact={row['ExactMatch']}, "
                f"status={row['Status']}"
            )

    return rows


def run_one_config(
    *,
    config: ExperimentConfig,
    task_adapter: CountFrequencyTaskAdapter,
    global_task: dict[str, Any],
    llm_client: OllamaChatClient,
    topology: str,
    n_agents: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt_idx in range(args.config_retries + 1):
        try:
            if attempt_idx:
                print(f"  -> retrying config, attempt {attempt_idx + 1}")
            result = SynchronousRunner(
                config=config,
                task_adapter=task_adapter,
                global_task=global_task,
                llm_client=llm_client,
            ).run()
            return build_row(
                result=result,
                global_task=global_task,
                topology=topology,
                n_agents=n_agents,
                args=args,
                error=None,
            )
        except Exception as exc:
            last_error = exc
            print(f"  -> attempt {attempt_idx + 1} failed: {exc}")

    assert last_error is not None
    return build_failed_row(
        global_task=global_task,
        topology=topology,
        n_agents=n_agents,
        args=args,
        error=last_error,
    )


if __name__ == "__main__":
    main()
