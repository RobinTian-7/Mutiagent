"""masbench: a clean MAS benchmark pipeline that reuses the exp_graph engine."""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"


def _ensure_exp_graph_importable() -> None:
    """Add the sibling exp-graph/src to sys.path (repo idiom; see run_cf_*.py)."""
    repo_root = Path(__file__).resolve().parents[3]
    exp_graph_src = repo_root / "exp-graph" / "src"
    candidate = str(exp_graph_src)
    if exp_graph_src.is_dir() and candidate not in sys.path:
        sys.path.insert(0, candidate)


_ensure_exp_graph_importable()
