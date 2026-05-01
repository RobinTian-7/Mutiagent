"""Run one Newsgroups Frequency DIG experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dig_repro.baselines import SystemKind
from dig_repro.runtime import DIGExperimentRunner, ExperimentConfig
from dig_repro.tasks import NewsgroupsFrequencyTask


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the DIG Newsgroups Frequency reproduction.")
    parser.add_argument("--system", choices=[item.value for item in SystemKind], default=SystemKind.MAS_DIG.value)
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], default="medium")
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--max-activations", type=int, default=120)
    parser.add_argument("--split-threshold", type=int, default=12)
    parser.add_argument("--num-documents", type=int, default=None)
    parser.add_argument("--judge-interval", type=int, default=8)
    parser.add_argument("--llm-provider", choices=["rule", "openai"], default="rule")
    parser.add_argument("--model-name", default="gpt-4o")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--export-dir", default="outputs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ExperimentConfig(
        task_name="newsgroups_frequency",
        system_name=args.system,
        n_agents=args.n_agents,
        difficulty=args.difficulty,
        seed=args.seed,
        max_activations=args.max_activations,
        split_threshold=args.split_threshold,
        judge_interval=args.judge_interval,
        llm_provider=args.llm_provider,
        model_name=args.model_name,
        temperature=args.temperature,
        export_dir=args.export_dir,
    )
    runner = DIGExperimentRunner(config=config, task_adapter=NewsgroupsFrequencyTask())
    problem_kwargs = {}
    if args.num_documents is not None:
        problem_kwargs["num_documents"] = args.num_documents
    result = runner.run(**problem_kwargs)
    print(json.dumps(result.metrics.model_dump(), indent=2, sort_keys=True))
    print("exports:")
    print(json.dumps(result.exports, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

