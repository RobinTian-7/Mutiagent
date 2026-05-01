"""System modes used in the DIG paper experiments."""

from __future__ import annotations

from enum import Enum


class SystemKind(str, Enum):
    MAS_ONLY = "mas_only"
    MAS_LLM_JUDGE = "mas_llm_judge"
    MAS_DIG = "mas_dig"

