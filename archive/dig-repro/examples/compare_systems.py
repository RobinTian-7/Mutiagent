"""Compare MAS-only, MAS+LLM Judge, and MAS+DIG on one task setting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dig_repro.baselines import SystemKind
from dig_repro.runtime import DIGExperimentRunner, ExperimentConfig
from dig_repro.tasks import CountFrequencyTask


def main() -> None:
    rows = []
    for system in [SystemKind.MAS_ONLY.value, SystemKind.MAS_LLM_JUDGE.value, SystemKind.MAS_DIG.value]:
        config = ExperimentConfig(
            task_name="count_frequency",
            system_name=system,
            n_agents=6,
            difficulty="medium",
            seed=4,
            max_activations=90,
            split_threshold=20,
        )
        result = DIGExperimentRunner(config=config, task_adapter=CountFrequencyTask()).run(
            array_size=180,
            value_domain_size=5,
        )
        rows.append(
            {
                "system": system,
                "valid_output": result.metrics.valid_output,
                "rmse": result.metrics.rmse,
                "interventions": len(result.interventions),
                "error_counts": result.metrics.detected_error_counts,
            }
        )
    print(json.dumps(rows, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

