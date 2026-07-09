"""Count Frequency benchmark."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from dig_repro.tasks.base import TaskAdapter


class CountFrequencyTask(TaskAdapter):
    task_name = "count_frequency"
    difficulty_sizes = {
        "easy": 1000,
        "medium": 5000,
        "hard": 10000,
        "case_study": 100000,
    }

    def build_problem_instance(self, *, difficulty: str, seed: int, **kwargs: Any) -> dict[str, Any]:
        rng = random.Random(seed)
        size = int(kwargs.get("array_size", self.difficulty_sizes[difficulty]))
        domain_size = int(kwargs.get("value_domain_size", 10))
        values = [rng.randrange(domain_size) for _ in range(size)]
        counts = Counter(values)
        answer = {str(value): counts.get(value, 0) for value in range(domain_size)}
        return {
            "task_name": self.task_name,
            "difficulty": difficulty,
            "array": values,
            "value_domain": [str(value) for value in range(domain_size)],
            "ground_truth": answer,
            "description": "Count the frequency of each integer value in the input array.",
        }

    def format_problem_spec(self, problem: dict[str, Any]) -> str:
        return (
            f"Task: {problem['description']}\n"
            f"Values belong to domain: {problem['value_domain']}\n"
            f"Input length: {len(problem['array'])}\n"
            "Return a frequency table over the full value domain."
        )

    def all_item_ids(self, problem: dict[str, Any]) -> list[int]:
        return list(range(len(problem["array"])))

    def split_coverage(
        self,
        problem: dict[str, Any],
        coverage_ids: list[int],
        n_parts: int,
    ) -> list[list[int]]:
        if not coverage_ids:
            return []
        n_parts = max(1, min(n_parts, len(coverage_ids)))
        chunk_size = math.ceil(len(coverage_ids) / n_parts)
        return [coverage_ids[i : i + chunk_size] for i in range(0, len(coverage_ids), chunk_size)]

    def fetch_raw_data(self, problem: dict[str, Any], coverage_ids: list[int]) -> dict[str, Any]:
        array = problem["array"]
        return {
            "indices": coverage_ids,
            "values": [array[index] for index in coverage_ids],
        }

    def solve_raw_data_payload(
        self,
        problem: dict[str, Any],
        raw_payload: dict[str, Any],
    ) -> dict[str, Any]:
        counts = Counter(int(value) for value in raw_payload.get("values", []))
        per_item_value = {
            str(index): int(value)
            for index, value in zip(raw_payload.get("indices", []), raw_payload.get("values", []))
        }
        histogram = {
            str(value): counts.get(value, 0)
            for value in map(int, problem["value_domain"])
        }
        return {
            "histogram": histogram,
            "covered_ids": list(raw_payload.get("indices", [])),
            "per_item_value": per_item_value,
        }

    def merge_solution_payloads(
        self,
        problem: dict[str, Any],
        solutions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        domain = problem["value_domain"]
        merged_per_item: dict[str, int] = {}
        for solution in solutions:
            for item_id, value in solution.get("per_item_value", {}).items():
                merged_per_item[str(item_id)] = int(value)
        merged_histogram = {str(value): 0 for value in domain}
        for value in merged_per_item.values():
            merged_histogram[str(value)] += 1
        return {
            "histogram": merged_histogram,
            "covered_ids": sorted(int(idx) for idx in merged_per_item),
            "per_item_value": merged_per_item,
        }

    def is_complete_solution(self, problem: dict[str, Any], solution_payload: dict[str, Any]) -> bool:
        covered_ids = set(int(idx) for idx in solution_payload.get("covered_ids", []))
        return covered_ids == set(self.all_item_ids(problem))

    def compute_rmse(
        self,
        problem: dict[str, Any],
        solution_payload: dict[str, Any] | None,
    ) -> float | None:
        if solution_payload is None:
            return None
        predicted = solution_payload.get("histogram", {})
        gt = problem["ground_truth"]
        values = []
        for key in problem["value_domain"]:
            values.append((int(predicted.get(str(key), 0)) - int(gt.get(str(key), 0))) ** 2)
        return math.sqrt(sum(values) / len(values)) if values else 0.0

    def normalize_solution(
        self,
        problem: dict[str, Any],
        solution_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if solution_payload is None:
            return None
        domain = problem["value_domain"]
        return {
            "histogram": {
                str(key): int(solution_payload.get("histogram", {}).get(str(key), 0))
                for key in domain
            },
            "covered_ids": sorted(int(idx) for idx in solution_payload.get("covered_ids", [])),
            "per_item_value": {
                str(key): int(value)
                for key, value in solution_payload.get("per_item_value", {}).items()
            },
        }
