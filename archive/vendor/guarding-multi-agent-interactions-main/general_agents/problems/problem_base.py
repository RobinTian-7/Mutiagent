"""
problem_base.py

Abstract Problem interface and goal status.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..core.dig import InteractionLog, InteractionEvent


@dataclass
class GoalStatus:
    """
    Represents whether a problem is solved given a DIG.
    """
    done: bool
    winning_event: Optional[InteractionEvent] = None
    info: Dict[str, Any] = None


class Problem(ABC):
    """
    Abstract base class for problems that agents can cooperate on.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Human readable name of the problem.
        """
        raise NotImplementedError

    @abstractmethod
    def problem_spec(self, context_limit: int | None = None) -> str:
        """
        Returns a textual problem specification targeted at the model.
        Must fit within context_limit characters if provided.
        """
        raise NotImplementedError
    
    @abstractmethod
    def tools_description(self) -> str:
        """
        Returns a description of available tools specific to this problem.
        This will be dynamically injected into the agent's system prompt.
        """
        raise NotImplementedError
    
    @abstractmethod
    def capability_explain(self) -> str:
        """
        Returns a description of agent capabilities and constraints for this problem.
        This explains what agents can and cannot do, processing limits, etc.
        This will be dynamically injected into the agent's system prompt.
        """
        raise NotImplementedError
    
    @abstractmethod
    def event_examples(self) -> str:
        """
        Returns domain-specific examples of event structure (payload, recipients).
        This will be dynamically injected into the agent's system prompt.
        """
        raise NotImplementedError

    @abstractmethod
    def initial_events(
        self,
        dig: InteractionLog,
        agent_names: List[str],
    ) -> List[InteractionEvent]:
        """
        Create initial InteractionEvents for this problem and add them to the DIG.
        Returns the list of created events.
        """
        raise NotImplementedError

    @abstractmethod
    def goal_status(self, dig: InteractionLog) -> GoalStatus:
        """
        Inspect the DIG and determine if the problem is solved.
        For example, by checking if a certain event type exists and is valid.
        """
        raise NotImplementedError

    @abstractmethod
    def reference_solution(self) -> Any:
        """
        Return the reference (correct) solution for this problem.
        Used to compare against submitted solutions.
        """
        raise NotImplementedError

    @abstractmethod
    def extract_solution(self, dig: InteractionLog) -> Any:
        """
        Extract the best solution from the DIG.
        
        Uses dig.get_solution_events() and dig.get_submit_activation_inputs()
        to find candidate solutions, then applies problem-specific logic
        to parse and score them.
        
        Returns the best solution found, or empty/None if no valid solution.
        """
        raise NotImplementedError

    @abstractmethod
    def calculate_error(self, solution: Any, reference: Any) -> float:
        """
        Calculate error between solution and reference.
        Returns 0.0 for exact match, higher values for worse solutions.
        Returns float('inf') if solution is invalid/empty.
        """
        raise NotImplementedError
    
    @property
    @abstractmethod
    def error_metric_name(self) -> str:
        """
        Name of the error metric (e.g., 'RMSE', 'MAE', 'Accuracy').
        Used for display in experiment results.
        """
        raise NotImplementedError
    
    def evaluate_solution(self, dig: InteractionLog) -> dict:
        """
        Evaluate the solution from the DIG.
        Returns dict with: solution, reference, error, valid, correct
        """
        solution = self.extract_solution(dig)
        reference = self.reference_solution()
        
        valid = solution is not None and (isinstance(solution, dict) and len(solution) > 0 or bool(solution))
        error = self.calculate_error(solution, reference) if valid else float('inf')
        correct = error == 0.0
        
        return {
            "solution": solution,
            "reference": reference,
            "error": error,
            "valid": valid,
            "correct": correct,
            "metric_name": self.error_metric_name,
        }

    @abstractmethod
    def split_problem_at_high_level(
        self,
        problem_id: str,
        splits: List,  # List[ChunkAssignment] but avoid circular import
        dig: InteractionLog,
    ) -> List[InteractionEvent]:
        """
        Split a problem into chunks and create events for each chunk.
        
        Args:
            problem_id: ID of the problem to split
            splits: List of dicts with 'message' and 'recipients' for each chunk
            dig: InteractionLog to create events in
        
        Returns:
            List of created InteractionEvents, one per split
        """
        raise NotImplementedError
    
    @abstractmethod
    def get_raw_data_of_problem(
        self,
        problem_id: str,
        message: str,
        recipients: List[str],
        dig: InteractionLog,
    ) -> InteractionEvent:
        """
        Get raw data for a problem and create an event with it.
        
        Args:
            problem_id: ID of the problem to get data for
            message: Message to include in event payload
            recipients: List of agent names to send the event to
            dig: InteractionLog to create event in
        
        Returns:
            Created InteractionEvent with raw data
        """
        raise NotImplementedError
