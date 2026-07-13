"""masbench: a clean MAS benchmark pipeline that reuses the exp_graph engine."""
# ============================================================
# 【模块导读】masbench：一个整洁的 MAS(多智能体)基准流水线，复用 exp_graph 引擎。
# 本文件是包初始化：解析包版本，并在必要时把兄弟 exp-graph/src 兜底加入 sys.path，
# 保证裸 Python(无 venv/editable 安装)调用也能 import exp_graph。
# ============================================================

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("masbench")
except PackageNotFoundError:  # running from source without an install
    __version__ = "0.1.0"


# 【职责】兜底把兄弟目录 exp_graph 引擎桥接进 sys.path，保证能 import。
# - 正常无需：uv 下 exp-graph 以 editable 安装，通过其 .pth 文件解析。
# - 仅裸 Python 调用(无 venv/editable 安装，如直接跑脚本)时才需要此兜底。
# - parents 链：__init__.py->masbench/(包)->src/->masbench/(顶层)->parents[3]=仓库根。
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
