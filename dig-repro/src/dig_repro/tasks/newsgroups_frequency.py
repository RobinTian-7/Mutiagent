"""20 Newsgroups Frequency benchmark."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from dig_repro.tasks.base import TaskAdapter


DEFAULT_CATEGORIES = [
    "alt.atheism",
    "comp.graphics",
    "comp.os.ms-windows.misc",
    "comp.sys.ibm.pc.hardware",
    "comp.sys.mac.hardware",
    "comp.windows.x",
    "misc.forsale",
    "rec.autos",
    "rec.motorcycles",
    "rec.sport.baseball",
    "rec.sport.hockey",
    "sci.crypt",
    "sci.electronics",
    "sci.med",
    "sci.space",
    "soc.religion.christian",
    "talk.politics.guns",
    "talk.politics.mideast",
    "talk.politics.misc",
    "talk.religion.misc",
]


class NewsgroupsFrequencyTask(TaskAdapter):
    task_name = "newsgroups_frequency"
    difficulty_sizes = {
        "easy": 60,
        "medium": 100,
        "hard": 150,
    }

    def build_problem_instance(self, *, difficulty: str, seed: int, **kwargs: Any) -> dict[str, Any]:
        documents = kwargs.get("documents")
        categories = list(kwargs.get("categories", DEFAULT_CATEGORIES))
        size = int(kwargs.get("num_documents", self.difficulty_sizes[difficulty]))

        if documents is None:
            rng = random.Random(seed)
            documents = []
            for index in range(size):
                category = categories[rng.randrange(len(categories))]
                text = f"Document {index} about {category}. Keywords: {category.replace('.', ' ')}."
                documents.append(
                    {
                        "doc_id": index,
                        "text": text,
                        "label": category,
                    }
                )

        counts = Counter(document["label"] for document in documents)
        answer = {category: counts.get(category, 0) for category in categories}
        return {
            "task_name": self.task_name,
            "difficulty": difficulty,
            "documents": documents,
            "categories": categories,
            "ground_truth": answer,
            "description": "Count the frequency of each 20 Newsgroups topic in the document set.",
        }

    def format_problem_spec(self, problem: dict[str, Any]) -> str:
        return (
            f"Task: {problem['description']}\n"
            f"Categories: {problem['categories']}\n"
            f"Number of documents: {len(problem['documents'])}\n"
            "Return a frequency table over all categories."
        )

    def all_item_ids(self, problem: dict[str, Any]) -> list[int]:
        return list(range(len(problem["documents"])))

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
        documents = problem["documents"]
        subset = [documents[index] for index in coverage_ids]
        return {
            "doc_ids": coverage_ids,
            "documents": [{"doc_id": doc["doc_id"], "text": doc["text"]} for doc in subset],
            "labels_for_testing_only": [doc["label"] for doc in subset],
        }

    def solve_raw_data_payload(
        self,
        problem: dict[str, Any],
        raw_payload: dict[str, Any],
    ) -> dict[str, Any]:
        categories = problem["categories"]
        counts = Counter(raw_payload.get("labels_for_testing_only", []))
        per_doc_label = {
            str(doc_id): label
            for doc_id, label in zip(raw_payload.get("doc_ids", []), raw_payload.get("labels_for_testing_only", []))
        }
        histogram = {category: counts.get(category, 0) for category in categories}
        return {
            "histogram": histogram,
            "covered_ids": list(raw_payload.get("doc_ids", [])),
            "per_doc_label": per_doc_label,
        }

    def merge_solution_payloads(
        self,
        problem: dict[str, Any],
        solutions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        categories = problem["categories"]
        merged_per_doc: dict[str, str] = {}
        for solution in solutions:
            for doc_id, label in solution.get("per_doc_label", {}).items():
                merged_per_doc[str(doc_id)] = str(label)
        merged_histogram = {category: 0 for category in categories}
        for label in merged_per_doc.values():
            merged_histogram[str(label)] += 1
        return {
            "histogram": merged_histogram,
            "covered_ids": sorted(int(idx) for idx in merged_per_doc),
            "per_doc_label": merged_per_doc,
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
        gt = problem["ground_truth"]
        predicted = solution_payload.get("histogram", {})
        values = [(int(predicted.get(key, 0)) - int(gt.get(key, 0))) ** 2 for key in problem["categories"]]
        return math.sqrt(sum(values) / len(values)) if values else 0.0

    def normalize_solution(
        self,
        problem: dict[str, Any],
        solution_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if solution_payload is None:
            return None
        return {
            "histogram": {
                category: int(solution_payload.get("histogram", {}).get(category, 0))
                for category in problem["categories"]
            },
            "covered_ids": sorted(int(idx) for idx in solution_payload.get("covered_ids", [])),
            "per_doc_label": {
                str(key): str(value)
                for key, value in solution_payload.get("per_doc_label", {}).items()
            },
        }
