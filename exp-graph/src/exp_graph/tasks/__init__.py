"""Task adapters."""

from exp_graph.tasks.array_search import ArraySearchTaskAdapter
from exp_graph.tasks.base import TaskAdapter
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter

__all__ = ["TaskAdapter", "ArraySearchTaskAdapter", "CountFrequencyTaskAdapter"]
