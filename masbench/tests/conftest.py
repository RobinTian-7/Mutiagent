"""Make the sibling exp_graph engine importable during bare (non-uv) test runs.

`pyproject.toml`'s ``pythonpath = ["src"]`` already puts masbench/src on the path,
and under ``uv`` exp-graph is installed editable. This only adds exp-graph/src as a
fallback for running pytest without the editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXP_GRAPH_SRC = str(_REPO_ROOT / "exp-graph" / "src")
if _EXP_GRAPH_SRC not in sys.path:
    sys.path.insert(0, _EXP_GRAPH_SRC)
