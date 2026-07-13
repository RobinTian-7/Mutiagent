"""Opt-in evidence cache for bank-INDEPENDENT protocol runs.

Dev-round cost profile showed ~60-70% of spend is evolution evidence, and
rounds 2..R re-measure runs whose inputs are identical to round 1's: named-
topology evidence rows use a FRESH EMPTY bank by construction, and the
generation gate's ``j_before`` uses an empty bank + cold generation. At
temperature 0 these are the same measurement; re-running them buys no new
information. With ``MASBENCH_EVIDENCE_CACHE=<file>`` such runs are served from
a persistent JSON cache (thread-safe, write-through).

NEVER cached (bank-dependent or the actual measurement): explore runs, gate
``j_after``, and all paired-eval runs. Env unset: no behaviour change.

Honesty note (also in the phase-2 prereg changelog): caching replaces "a fresh
sample each round" with "the same sample reused". At temperature 0 the two are
statistically equivalent; judgment logic in the frozen verify scripts is
untouched -- they simply call this pipeline.
"""
# ============================================================
# 【模块导读】可选启用的证据缓存，只服务"与技能库无关"(bank-independent)的协议运行。
# 开发轮成本画像显示约 60-70% 的开销花在进化证据上，而第 2..R 轮重复测量的运行与第 1 轮
# 输入完全相同：命名拓扑证据行按构造使用全新的空技能库；生成门的 j_before 用空库 + 冷生成。
# 温度 0 下这些是同一次测量，重跑买不来任何新信息。设置 MASBENCH_EVIDENCE_CACHE=<文件> 后，
# 这类运行改由持久化 JSON 缓存供给（线程安全、写穿式）。
# 绝不缓存（依赖技能库、或本身就是待测对象的）：探索运行、门的 j_after、全部成对评估运行。
# 环境变量未设置：行为完全不变。
# 诚实性说明（阶段 2 预注册变更日志亦有记载）：缓存把"每轮取一个新样本"换成"复用同一样本"；
# 温度 0 下两者统计等价；冻结 verify 脚本中的判定逻辑不受影响——它们只是调用本管线。
# ============================================================
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


# 【职责】读取 MASBENCH_EVIDENCE_CACHE 环境变量指定的缓存文件路径；未设置返回 None。
def cache_path() -> Path | None:
    raw = os.environ.get("MASBENCH_EVIDENCE_CACHE", "").strip()
    return Path(raw) if raw else None


# 【职责】以 (case, 条件, 模型) 为键的持久化证据行存储。
# - 进程内 dict + 可选 JSON 文件；构造时若文件存在则载入，文件损坏时静默回退为空。
class EvidenceCache:
    """Persistent (case, condition, model)-keyed store of evidence rows."""

    def __init__(self, path: Path | str | None) -> None:
        self._path = Path(path) if path else None
        self._data: dict[str, dict[str, Any]] = {}
        if self._path is not None and self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except Exception:
                self._data = {}

    # 【职责】拼出确定性缓存键：case/智能体数/规划模式/目标/种子 + 关键 LLM 配置字段。
    # - 任一字段（提供方、模型、合并/初始化模式、温度、候选图数、silo 评测模式）变化
    #   都得到不同键，避免把旧条件下的测量误当作新条件的结果复用。
    # - silo_eval_mode 进键：sink 与 all_agents 的测量绝不能互相复用。
    @staticmethod
    def key(
        *,
        case_id: str,
        n_agents: int,
        planner_mode: str,
        objective: str,
        seed: int,
        cfg: Any,
    ) -> str:
        parts = (
            case_id, str(n_agents), planner_mode, objective, str(seed),
            str(getattr(cfg, "llm_provider", "")), str(getattr(cfg, "model_name", "")),
            str(getattr(cfg, "merge_mode", "")), str(getattr(cfg, "init_mode", "")),
            str(getattr(cfg, "temperature", "")),
            str(getattr(cfg, "num_graph_candidates", "")),
            f"mode={getattr(cfg, 'silo_eval_mode', 'sink') or 'sink'}",
        )
        # 中文：PythonGen Worker 合约进键——两种合约的测量绝不能互相复用。仅在非默认
        #   合约时追加分量，保证既有 action_json_v1/非 Python 缓存键逐字节不变。
        # The PythonGen worker contract joins the key: the two contracts'
        # measurements must never be reused for each other. The component is
        # appended only for the non-default contract so every existing
        # action_json_v1 / non-python cache key stays byte-identical.
        worker_contract = str(
            getattr(cfg, "python_worker_contract", "action_json_v1")
            or "action_json_v1"
        )
        if worker_contract != "action_json_v1":
            parts = (*parts, f"pycontract={worker_contract}")
        return "|".join(parts)

    def get(self, key: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data.get(key)
            return dict(row) if row is not None else None

    # 【职责】写入一行并立即落盘（写穿式）；只保留 JSON 可序列化的字段。
    def put(self, key: str, row: dict[str, Any]) -> None:
        slim = {k: v for k, v in row.items() if _json_safe(v)}
        with _LOCK:
            self._data[key] = slim
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(self._data))


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


# 【职责】返回按环境变量配置的证据缓存；未启用时返回 None。
def open_cache() -> EvidenceCache | None:
    """The env-configured cache, or None when disabled."""
    path = cache_path()
    return EvidenceCache(path) if path is not None else None


def eval_cache_path() -> Path | None:
    raw = os.environ.get("MASBENCH_EVAL_CACHE", "").strip()
    return Path(raw) if raw else None


# 【职责】M18 断点续跑层：为"部署阶段"的行提供确定性键控缓存（MASBENCH_EVAL_CACHE）。
# - 依赖技能库的行（成对评估、gate:after/incumbent）通过把键定为 (case、种子、规划旋钮、
#   技能库内容哈希、结构母题哈希) 而变得可续跑：被中断的冻结判定运行带着已播种缓存重启后，
#   会回放每个已完成的配对而不是重新购买。
# - 诚实性说明与证据缓存相同——温度 0 下缓存行即同一次测量的复用；判定逻辑不受影响。
#   环境变量未设置：行为不变。
def open_eval_cache() -> EvidenceCache | None:
    """M18 resume layer: deterministic-keyed DEPLOYMENT-phase rows.

    Bank-dependent rows (paired eval, gate:after/incumbent) become resumable
    by keying on (case, seed, planner knobs, BANK CONTENT HASH, motif hash):
    an interrupted frozen-judge run relaunched with seeded caches replays
    every finished pair instead of repurchasing it. Same honesty note as the
    evidence cache -- at temperature 0 a cached row is the same measurement
    reused; judge logic is untouched. Env unset: no behaviour change.
    """
    path = eval_cache_path()
    return EvidenceCache(path) if path is not None else None
