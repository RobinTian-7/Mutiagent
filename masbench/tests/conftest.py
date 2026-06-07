"""Ensure both masbench/src and exp-graph/src are importable during tests."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _rel in ("masbench/src", "exp-graph/src"):
    _path = str(_REPO_ROOT / _rel)
    if _path not in sys.path:
        sys.path.insert(0, _path)
