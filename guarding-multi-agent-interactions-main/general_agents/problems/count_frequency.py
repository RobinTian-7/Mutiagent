"""
count_frequency.py

Defines the CountFrequencyProblem class for multi-agent frequency counting
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from ..core.dig import InteractionLog, InteractionEvent
from .problem_base import Problem, GoalStatus


class CountFrequencyProblem(Problem):
    def __init__(self, values: List[int]):
        self.values = values
        self.list_id = "P"  # Root problem ID is always "P"
        # Buffer to store problems/sub-problems by ID
        self.problem_buffer: Dict[str, Dict[str, Any]] = {}
        # Register the root problem
        self._register_problem(self.list_id, self.values)

    @property
    def name(self) -> str:
        return "CountFrequency"

    def problem_spec(self, context_limit: int | None = None) -> str:
        base = (
            f"Global task: Given a list of integers with id {self.list_id} "
            f"and length {len(self.values)}, compute the exact frequency of each "
            f"distinct integer. Agents may exchange events containing chunks, "
            f"partial counts, and merged results. The goal is to produce one "
            f"correct result together.\n\n"
            f"Problem ID Naming Convention:\n"
            f"  - Root problem: {self.list_id}\n"
            f"  - If split into 3: parent={self.list_id}(3), children={self.list_id}_1, {self.list_id}_2, {self.list_id}_3\n"
            f"  - If {self.list_id}_1 split into 2: parent={self.list_id}_1(2), children={self.list_id}_1_1, {self.list_id}_1_2\n\n"
            f"Solution Format Specification:\n"
            f"To submit a solution, send an event with:\n"
            f"  - type: \"solution\"\n"
            f"  - problem_id: \"{self.list_id}\"\n"
            f"  - solution: {{integer: count, ...}}\n\n"
            f"Example: {{\"type\": \"solution\", \"problem_id\": \"{self.list_id}\", "
            f"\"solution\": {{\"1\": 3, \"2\": 5, \"7\": 2}}}}\n"
            f"Note: Keys and values in the solution dict can be strings or integers, "
            f"they will be normalized to integers for validation."
        )
        if context_limit is not None and len(base) > context_limit:
            return base[: context_limit - 3] + "..."
        return base

    def tools_description(self) -> str:
        return (
            "1. split_problem_at_high_level(problem_id, splits)\n"
            "   - Divides the frequency counting task among multiple agents for parallel processing\n"
            "   - Each split specifies: instruction and recipients\n"
            "   - Creates N sub-problems with auto-generated IDs and data chunks\n"
            "   - Example: Split a 100-item list into 3 chunks for 3 agents\n"
            "   - Use this when you receive a large problem and want to distribute work\n"
            "\n"
            "2. get_raw_data_of_problem(problem_id, message, recipients)\n"
            "   - Retrieves the complete raw data (list of integers) for a problem YOU directly received\n"
            "   - ONLY use with problem_id from events YOU received (check payload for 'problem_id')\n"
            "   - DO NOT use this for chunk IDs mentioned by other agents\n"
            "   - If you need data for a chunk mentioned in a message, wait for that agent to send it\n"
            "   - Sends data event to specified agents\n"
            "   - Use when you need to process the entire dataset yourself\n"
        )
    
    def capability_explain(self) -> str:
        return (
            "AGENT PROCESSING CAPABILITY:\n"
            "\n"
            "Use your best judgment to decide:\n"
            "  - Whether to process a sub-problem directly (call get_raw_data_of_problem)\n"
            "  - Or to split it further among agents (call split_problem_at_high_level)\n"
            "\n"
            "Check the 'length' field in the event payload to see the size of your assigned problem.\n"
        )
    
    def event_examples(self) -> str:
        return (
            "EVENT EXAMPLES FOR THIS PROBLEM:\n"
            "\n"
            "1. Sharing partial solution (frequency count):\n"
            "   payload: {\"type\": \"solution\", \"problem_id\": \"P_1\", \"solution\": {\"1\": 5, \"2\": 3, \"7\": 2}}\n"
            "   recipients: [\"Agent1\"]\n"
            "\n"
            "2. Submitting final solution:\n"
            f"   payload: {{\"type\": \"solution\", \"problem_id\": \"{self.list_id}\", \"solution\": {{\"1\": 10, \"2\": 8, \"7\": 5}}}}\n"
            "   recipients: []\n"
        )

    def initial_events(
        self,
        dig: InteractionLog,
        agent_names: List[str],
    ) -> List[InteractionEvent]:
        first_agent = agent_names[0]

        # Payload is agent-editable (minimal)
        payload = {}
        
        # Info is system-generated (trustworthy)
        info = {
            "type": "initial_problem",
            "problem_name": self.name,
            "problem_id": self.list_id,
            "length": len(self.values),
            "description": f"Problem {self.list_id}: 1 of 1, length={len(self.values)}",
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

    def reference_solution(self) -> Dict[int, int]:
        """Return the correct frequency count for this problem."""
        return dict(Counter(self.values))
    
    def calculate_error(self, solution: Dict[int, int], reference: Dict[int, int]) -> float:
        """Calculate RMSE between solution and reference frequency counts."""
        if not solution:
            return float('inf')
        all_keys = set(solution.keys()) | set(reference.keys())
        if not all_keys:
            return 0.0
        squared_errors = [(solution.get(k, 0) - reference.get(k, 0)) ** 2 for k in all_keys]
        mse = sum(squared_errors) / len(squared_errors)
        return mse ** 0.5  # RMSE
    
    @property
    def error_metric_name(self) -> str:
        return "RMSE"

    def extract_solution(self, dig: InteractionLog) -> Dict[int, int]:
        """Extract best solution from DIG events.
        
        Only considers submitted solutions (SUBMIT inputs or submission-only events),
        then applies frequency-count-specific logic to parse and score them.
        """
        reference = self.reference_solution()
        best_solution, best_mse = {}, float('inf')
        
        def calculate_mse(predicted: dict, ref: dict) -> float:
            all_keys = set(predicted.keys()) | set(ref.keys())
            if not all_keys:
                return 0.0
            errors = [(predicted.get(k, 0) - ref.get(k, 0)) ** 2 for k in all_keys]
            return sum(errors) / len(errors)
        
        def try_solution(sol):
            nonlocal best_solution, best_mse
            if isinstance(sol, dict):
                try:
                    normalized = {int(k): int(v) for k, v in sol.items()}
                    mse = calculate_mse(normalized, reference)
                    if mse < best_mse:
                        best_mse, best_solution = mse, normalized
                except (ValueError, TypeError):
                    pass
        
        def extract_from_event(ev):
            """Extract frequency count data from an event."""
            # Check for solution field
            try_solution(ev.payload.get("solution"))
            try_solution(ev.info.get("solution"))
            
            # Check for frequency_count or partial_count keys (problem-specific)
            for key in ["frequency_count", "partial_count", "result", "count"]:
                if key in ev.payload:
                    try_solution(ev.payload.get(key))
                if key in ev.info:
                    try_solution(ev.info.get(key))
        
        # Check SUBMIT activation inputs from DIG
        for ev in dig.get_submit_activation_inputs():
            extract_from_event(ev)
        
        # Include submission-only events (created on SUBMIT)
        for ev in dig.events.values():
            if ev.info.get("submission_only"):
                extract_from_event(ev)
        
        return best_solution

    def goal_status(self, dig: InteractionLog) -> GoalStatus:
        target_counts = self.reference_solution()

        for ev in dig.events.values():
            payload = ev.payload
            if payload.get("type") != "solution":
                continue
            # Check both old 'list_id' and new 'problem_id' for compatibility
            problem_id = payload.get("problem_id") or payload.get("list_id")
            if problem_id != self.list_id:
                continue

            sol = payload.get("solution")
            if not isinstance(sol, dict):
                continue

            normalized = {int(k): int(v) for k, v in sol.items()}
            if normalized == target_counts:
                return GoalStatus(
                    done=True,
                    winning_event=ev,
                    info={"reason": "exact match"},
                )

        return GoalStatus(
            done=False,
            winning_event=None,
            info={"reason": "no correct solution found"},
        )

    def _register_problem(self, problem_id: str, data: List[int]):
        """Register a problem or sub-problem in the buffer."""
        # Determine if this is a sub-problem (has underscore followed by number)
        import re
        # Match pattern like P_1, P_1_2, etc.
        if re.search(r'_\d+$', problem_id):
            # Extract parent and chunk index from problem_id (e.g., "P_2" or "P_1_3")
            parts = problem_id.rsplit('_', 1)
            chunk_idx = int(parts[1])
            info_str = f"Problem {problem_id}: sub-problem {chunk_idx}, length={len(data)}"
        else:
            info_str = f"Problem {problem_id}: root problem, length={len(data)}"
        
        self.problem_buffer[problem_id] = {
            "id": problem_id,
            "data": data,
            "length": len(data),
            "info": info_str,
        }
    
    def _normalize_problem_id(self, problem_id: str) -> str:
        """Normalize problem_id by stripping (N) suffix if present.
        
        Accepts both 'list_500' and 'list_500(3)' formats.
        """
        import re
        # Strip (N) suffix if present: "list_500(3)" -> "list_500"
        return re.sub(r'\(\d+\)$', '', problem_id)

    def split_problem_at_high_level(
        self,
        problem_id: str,
        splits: List,  # List[ChunkAssignment]
        dig: InteractionLog,
    ) -> List[InteractionEvent]:
        """
        Split a problem into chunks and create events for each chunk.
        
        Each split is a ChunkAssignment with:
        - message: str - agent's message for recipients
        - recipients: List[str] - agent names to receive this chunk
        
        Naming convention:
        - P split into 3 -> parent becomes P(3), children are P_1, P_2, P_3
        - P_1 split into 4 -> parent becomes P_1(4), children are P_1_1, P_1_2, P_1_3, P_1_4
        """
        if problem_id not in self.problem_buffer:
            raise ValueError(f"Unknown problem_id {problem_id}")
        
        parent_data = self.problem_buffer[problem_id]["data"]
        n = len(parent_data)
        num_chunks = len(splits)
        
        # Generate all sub-problem IDs: P -> P_1, P_2, P_3 (1-indexed)
        sub_problem_ids = [f"{problem_id}_{i+1}" for i in range(num_chunks)]
        
        # Split data into equal chunks
        base = n // num_chunks
        rem = n % num_chunks
        
        events = []
        start = 0
        
        for i, split_spec in enumerate(splits):
            size = base + (1 if i < rem else 0)
            end = start + size
            
            # Create unique ID for this sub-problem (1-indexed)
            sub_id = sub_problem_ids[i]
            sub_data = parent_data[start:end]
            
            # Register sub-problem in buffer
            self._register_problem(sub_id, sub_data)
            
            # Agent-editable payload (empty to reduce noise)
            payload = {}
            
            # System/tool-generated info (trustworthy, not agent-editable)
            info = {
                "_event_type": "problem",  # Tool-generated events are always problems
                "problem_id": sub_id,
                "length": len(sub_data),
                "description": f"Problem {sub_id} of size {len(sub_data)}. Use get_raw_data tool if you want to work on it.",
            }
            
            event = dig.new_event(
                payload=payload,
                source_activation_id=None,  # Will be set by caller
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
        
        Accepts both 'problem_id' and 'problem_id(N)' formats.
        """
        normalized_id = self._normalize_problem_id(problem_id)
        if normalized_id not in self.problem_buffer:
            raise ValueError(f"Unknown problem_id {problem_id}")
        
        problem_info = self.problem_buffer[normalized_id]
        
        # Agent-editable payload (just message from agent)
        payload = {
            "message": message,
        }
        
        # System/tool-generated info (trustworthy, not agent-editable)
        info = {
            "_event_type": "problem",  # Tool-generated events are always problems
            "problem_id": normalized_id,
            "data": problem_info["data"],
            "length": problem_info["length"],
            "description": f"Problem {normalized_id} of size {problem_info['length']}. Raw data is available in this event. You can work on it.",
        }
        
        event = dig.new_event(
            payload=payload,
            source_activation_id=None,  # Will be set by caller
            recipients=recipients,
            info=info,
        )
        
        return event
