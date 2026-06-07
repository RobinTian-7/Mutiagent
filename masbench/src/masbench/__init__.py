"""masbench: a clean MAS benchmark pipeline that reuses the exp_graph engine."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("masbench")
except PackageNotFoundError:  # running from source without an install
    __version__ = "0.1.0"


def _ensure_exp_graph_importable() -> None:
    """Fallback sys.path bridge to the sibling exp_graph engine.

    Normally unnecessary: under ``uv`` exp-graph is installed editable and resolved
    via its ``.pth`` file. This fallback only matters for bare-Python invocation
    (no venv / editable install), e.g. running a script directly.

    parents: __init__.py -> masbench/ (pkg) -> src/ -> masbench/ (top) -> repo root
    """
    repo_root = Path(__file__).resolve().parents[3]
    exp_graph_src = repo_root / "exp-graph" / "src"
    candidate = str(exp_graph_src)
    if exp_graph_src.is_dir() and candidate not in sys.path:
        sys.path.insert(0, candidate)


_ensure_exp_graph_importable()
