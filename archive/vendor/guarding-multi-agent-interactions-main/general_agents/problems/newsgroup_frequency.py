"""
newsgroup_frequency.py

Defines the NewsGroupFrequencyProblem class for multi-agent frequency counting
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from ..core.dig import InteractionLog, InteractionEvent
from .problem_base import Problem, GoalStatus


class NewsGroupFrequencyProblem(Problem):
    def __init__(self, documents: List[Dict[str, Any]], categories: List[str]):
        if len(categories) != 20:
            raise ValueError(f"Expected 20 categories, got {len(categories)}")
        self.documents = documents
        self.categories = categories  # used for reference_solution + validation normalization
        self.list_id = "P"  # Root problem ID is always "P"
        # Buffer to store problems/sub-problems by ID
        self.problem_buffer: Dict[str, Dict[str, Any]] = {}
        # Register the root problem
        self._register_problem(self.list_id, self.documents)

    @property
    def name(self) -> str:
        return "NewsGroupFrequency"

    def problem_spec(self, context_limit: int | None = None) -> str:
        base = (
            f"Global task: Given a collection of raw text documents with id {self.list_id} "
            f"and size {len(self.documents)}, compute the frequency distribution over the 20 "
            f"topic categories. Agents may exchange events containing chunks, predicted labels, "
            f"partial counts, and merged results. The goal is to produce one correct result together.\n\n"
            f"Problem ID Naming Convention:\n"
            f"  - Root problem: {self.list_id}\n"
            f"  - If split into 3: parent={self.list_id}(3), children={self.list_id}_1, {self.list_id}_2, {self.list_id}_3\n"
            f"  - If {self.list_id}_1 split into 2: parent={self.list_id}_1(2), children={self.list_id}_1_1, {self.list_id}_1_2\n\n"
            f"Important:\n"
            f"- Documents exposed to agents contain ONLY raw text (doc_id + text). NO labels are provided.\n"
            f"- Agents must collaboratively classify documents and then aggregate category counts.\n\n"
            f"Categories (must choose from these exact strings):\n"
            f"{self.categories}\n\n"
            f"Solution Format Specification:\n"
            f"To submit a solution, send an event with:\n"
            f"  - type: \"solution\"\n"
            f"  - problem_id: \"{self.list_id}\"\n"
            f"  - solution: {{category: count, ...}} (missing categories treated as 0)\n\n"
            f"Example: {{\"type\": \"solution\", \"problem_id\": \"{self.list_id}\", "
            f"\"solution\": {{\"sci.space\": 120, \"rec.autos\": 95, \"alt.atheism\": 40}}}}"
        )
        if context_limit is not None and len(base) > context_limit:
            return base[: context_limit - 3] + "..."
        return base

    def tools_description(self) -> str:
        return (
            "1. split_problem_at_high_level(problem_id, splits)\n"
            "   - Divides the document set among multiple agents for parallel classification\n"
            "   - Each split specifies: message and recipients\n"
            "   - Creates N sub-problems with auto-generated IDs and document chunks\n"
            "   - Initial + split events do NOT include raw documents; use get_raw_data_of_problem to fetch\n"
            "\n"
            "2. get_raw_data_of_problem(problem_id, message, recipients)\n"
            "   - Retrieves the complete raw data (doc_id + text) for a problem YOU directly received\n"
            "   - ONLY use with problem_id from events YOU received (check event.info['problem_id'])\n"
            "   - DO NOT use this for chunk IDs mentioned by other agents\n"
            "   - If you need data for a chunk mentioned in a message, wait for that agent to send it\n"
            "   - Sends raw documents to specified agents\n"
        )

    def capability_explain(self) -> str:
        return (
            "AGENT PROCESSING CAPABILITY:\n"
            "\n"
            "Use your best judgment to decide:\n"
            "  - Whether to process a sub-problem directly (call get_raw_data_of_problem)\n"
            "  - Or to split it further among agents (call split_problem_at_high_level)\n"
            "\n"
            "Check the 'length' field in the event info to see the size of your assigned problem.\n"
        )

    def event_examples(self) -> str:
        return (
            "EVENT EXAMPLES FOR THIS PROBLEM:\n"
            "\n"
            "1. Sharing partial category counts:\n"
            "   payload: {\"type\": \"solution\", \"problem_id\": \"P_1\", \"solution\": {\"sci.space\": 3, \"rec.autos\": 1, ...}}\n"
            "   recipients: [\"Agent1\"]\n"
            "\n"
            "2. Submitting final solution:\n"
            f"   payload: {{\"type\": \"solution\", \"problem_id\": \"{self.list_id}\", "
            f"\"solution\": {{\"sci.space\": 120, \"rec.autos\": 95, \"alt.atheism\": 40, ...}}}}\n"
            "   recipients: []\n"
        )

    def initial_events(self, dig: InteractionLog, agent_names: List[str]) -> List[InteractionEvent]:
        first_agent = agent_names[0]

        # Payload is agent-editable (minimal)
        payload = {}

        # Info is system-generated (trustworthy)
        info = {
            "type": "initial_problem",
            "problem_name": self.name,
            "problem_id": self.list_id,
            "length": len(self.documents),
            "description": f"Problem {self.list_id}: 1 of 1, length={len(self.documents)}",
            # NO data in initial event - agents MUST use split() tool to get data
            # This ensures proper tracking of num_chunks
        }

        root_event = dig.new_event(
            payload=payload,
            source_activation_id=None,
            recipients=[first_agent],
            info=info,
        )
        return [root_event]

    def reference_solution(self) -> Dict[str, int]:
        counts = Counter()
        for doc in self.documents:
            cat = doc.get("category")
            if cat is not None:
                counts[cat] += 1

        # Ensure all 20 categories appear (missing → 0)
        return {cat: int(counts.get(cat, 0)) for cat in self.categories}

    def calculate_error(self, solution: Dict[str, int], reference: Dict[str, int]) -> float:
        if not solution:
            return float("inf")
        all_keys = set(solution.keys()) | set(reference.keys())
        if not all_keys:
            return 0.0
        squared = [(solution.get(k, 0) - reference.get(k, 0)) ** 2 for k in all_keys]
        mse = sum(squared) / len(squared)
        return mse ** 0.5

    @property
    def error_metric_name(self) -> str:
        return "RMSE"

    def extract_solution(self, dig: InteractionLog) -> Dict[str, int]:
        reference = self.reference_solution()
        best_solution: Dict[str, int] = {}
        best_mse = float("inf")

        def calculate_mse(pred: Dict[str, int], ref: Dict[str, int]) -> float:
            keys = set(pred.keys()) | set(ref.keys())
            if not keys:
                return 0.0
            errors = [(pred.get(k, 0) - ref.get(k, 0)) ** 2 for k in keys]
            return sum(errors) / len(errors)

        def try_solution(candidate: Any):
            nonlocal best_solution, best_mse
            normalized = self._normalize_solution(candidate)
            if normalized is None:
                return
            mse = calculate_mse(normalized, reference)
            if mse < best_mse:
                best_mse = mse
                best_solution = normalized

        def extract_from_event(ev: InteractionEvent):
            try_solution(ev.payload.get("solution"))
            try_solution(ev.info.get("solution"))

            # Problem-specific / common alt keys
            for key in ["frequency_count", "partial_count", "result", "count", "category_count"]:
                if key in ev.payload:
                    try_solution(ev.payload.get(key))
                if key in ev.info:
                    try_solution(ev.info.get(key))

        # Check SUBMIT activation inputs from DIG (authoritative for "submitted")
        for ev in dig.get_submit_activation_inputs():
            extract_from_event(ev)

        # Include submission-only events (created on SUBMIT)
        for ev in dig.events.values():
            if ev.info.get("submission_only"):
                extract_from_event(ev)

        return best_solution

    def goal_status(self, dig: InteractionLog) -> GoalStatus:
        target = self.reference_solution()

        for ev in dig.events.values():
            payload = ev.payload
            if payload.get("type") != "solution":
                continue

            pid = payload.get("problem_id") or payload.get("list_id")
            if pid != self.list_id:
                continue

            normalized = self._normalize_solution(payload.get("solution"))
            if normalized is None:
                continue

            if normalized == target:
                return GoalStatus(done=True, winning_event=ev, info={"reason": "exact match"})

        return GoalStatus(done=False, winning_event=None, info={"reason": "no correct solution found"})

    def _register_problem(self, problem_id: str, data: List[Dict[str, Any]]):
        """Register a problem or sub-problem in the buffer."""
        import re
        if re.search(r"_\d+$", problem_id):
            parts = problem_id.rsplit("_", 1)
            chunk_idx = int(parts[1])
            info_str = f"Problem {problem_id}: sub-problem {chunk_idx}, length={len(data)}"
        else:
            info_str = f"Problem {problem_id}: root problem, length={len(data)}"

        self.problem_buffer[problem_id] = {
            "id": problem_id,
            "data": data,        # internal docs (includes category for eval, but never exposed)
            "length": len(data),
            "info": info_str,
        }

    def _normalize_problem_id(self, problem_id: str) -> str:
        """Normalize problem_id by stripping (N) suffix if present: 'P(3)' -> 'P'."""
        import re
        return re.sub(r"\(\d+\)$", "", problem_id)

    def split_problem_at_high_level(
        self,
        problem_id: str,
        splits: List,  # List[ChunkAssignment]-like: each has .recipients
        dig: InteractionLog,
    ) -> List[InteractionEvent]:
        """
        Split a problem into chunks and create events for each chunk.

        Naming convention:
        - P split into 3 -> children are P_1, P_2, P_3
        - P_1 split into 4 -> children are P_1_1, P_1_2, P_1_3, P_1_4

        NOTE: Like CountFrequencyProblem, split events do NOT include raw docs.
              Agents must call get_raw_data_of_problem to fetch doc_id+text.
        """
        if problem_id not in self.problem_buffer:
            raise ValueError(f"Unknown problem_id {problem_id}")

        parent_docs = self.problem_buffer[problem_id]["data"]
        n = len(parent_docs)
        num_chunks = len(splits)

        sub_problem_ids = [f"{problem_id}_{i+1}" for i in range(num_chunks)]

        base = n // num_chunks
        rem = n % num_chunks

        events: List[InteractionEvent] = []
        start = 0

        for i, split_spec in enumerate(splits):
            size = base + (1 if i < rem else 0)
            end = start + size

            sub_id = sub_problem_ids[i]
            sub_docs = parent_docs[start:end]

            # Register sub-problem
            self._register_problem(sub_id, sub_docs)

            # Agent-editable payload (empty to reduce noise, match CountFrequency)
            payload = {}

            # Trustworthy info
            info = {
                "_event_type": "problem",
                "problem_id": sub_id,
                "length": len(sub_docs),
                "description": (
                    f"Problem {sub_id} of size {len(sub_docs)}. "
                    f"Use get_raw_data tool if you want to work on it."
                ),
            }

            event = dig.new_event(
                payload=payload,
                source_activation_id=None,  # set by caller
                recipients=split_spec.recipients,
                info=info,
            )
            events.append(event)

            start = end

        return events

    def get_raw_data_of_problem(
        self,
        problem_id: str,
        message: str,
        recipients: List[str],
        dig: InteractionLog,
    ) -> InteractionEvent:
        """
        Get raw data for a problem and create an event with it.

        Returns ONLY raw docs (doc_id + text). Category labels are never sent.
        Accepts both 'problem_id' and 'problem_id(N)' formats.
        """
        normalized_id = self._normalize_problem_id(problem_id)
        if normalized_id not in self.problem_buffer:
            raise ValueError(f"Unknown problem_id {problem_id}")

        problem_info = self.problem_buffer[normalized_id]

        # Agent-editable payload
        payload = {"message": message}

        # Expose ONLY raw text docs
        raw_docs = [{"doc_id": d.get("doc_id"), "text": d.get("text", "")} for d in problem_info["data"]]

        info = {
            "_event_type": "problem",
            "problem_id": normalized_id,
            "data": raw_docs,
            "length": problem_info["length"],
            "description": (
                f"Problem {normalized_id} of size {problem_info['length']}. "
                f"Raw data is available in this event. You can work on it."
            ),
        }

        event = dig.new_event(
            payload=payload,
            source_activation_id=None,  # set by caller
            recipients=recipients,
            info=info,
        )
        return event

    def _normalize_solution(self, sol: Any) -> Optional[Dict[str, int]]:
        """
        Convert candidate solution into a full {category: count} dict with all 20 cats.
        Rules:
        - Keys must be valid categories (exact match)
        - Counts must be int-castable
        - Missing categories are filled with 0
        """
        if not isinstance(sol, dict):
            return None

        valid = set(self.categories)
        out = {c: 0 for c in self.categories}

        for k, v in sol.items():
            cat = k if isinstance(k, str) else str(k)
            if cat not in valid:
                return None
            try:
                out[cat] = int(v)
            except Exception:
                return None

        return out
