"""Silo-Bench loader: benchmarks/{Level}-{NN}_n{agents}.json -> BenchmarkInstance."""
# ============================================================
# 【模块导读】Silo-Bench 加载器：把 benchmarks 目录下的
# {Level}-{NN}_n{agents}.json 文件加载为 BenchmarkInstance。
# 负责按文件名(或文件体)解析出难度等级与 agent 数，并按 levels/agent_counts/cases 过滤。
# ============================================================

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from masbench.core.benchmark import BenchmarkAdapter
from masbench.core.instance import BenchmarkInstance

_FILENAME_RE = re.compile(r"(?P<level>[IVX]+)-(?P<num>\d+)_n(?P<agents>\d+)\.json$")

# 中文：task_description 里的 "**Communication Protocol:**" 小节从标题起、到下一个
#   "**Heading:**" 小节或文末止——它把基准标注的拓扑（"Topology: Chain ..."）直接写进
#   每个 agent 的提示词，是拓扑泄漏，必须整段删除。
# The "**Communication Protocol:**" section of a task_description (heading up
# to the next "**Heading:**" or end of text). It spells out the benchmark's
# annotated topology in every agent prompt -- a direct topology leak, removed
# as a whole section.
_COMMUNICATION_PROTOCOL_RE = re.compile(
    r"[ \t]*\*\*Communication Protocol:?\*\*.*?(?=\n[ \t]*\*\*|\Z)",
    flags=re.DOTALL | re.IGNORECASE,
)

# 中文：instance.meta 不携带的基准标注字段：最优拓扑/最优消息数/理论复杂度是评测答案的
#   一部分，任何运行侧结构都不该拿到（不修改 third_party 原始数据，只是不搬运）。
# Benchmark-annotation fields never carried into instance.meta: the optimal
# topology / message count / complexity ARE part of the evaluation answer. The
# third_party files themselves are untouched; we simply do not carry these.
_LEAKY_METADATA_KEYS = frozenset(
    {"optimal_topology", "optimal_message_count", "theoretical_complexity"}
)


# 【职责】生成 sanitized task statement：整段删除 Communication Protocol 小节。
# - 保留任务语义、分片方式、Agent 顺序与算法目标（Task/Agent Ordering/Your Data/
#   Algorithm/Output 小节原样保留）；只裁掉规定通信拓扑的段落。
def sanitize_task_description(text: str) -> str:
    """Drop the Communication Protocol section; keep real task semantics."""
    if not text:
        return text
    sanitized = _COMMUNICATION_PROTOCOL_RE.sub("", text)
    # 中文：压掉裁剪残留的三连空行，保持提示词整洁。
    # Collapse the triple blank lines the excision can leave behind.
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip() + ("\n" if sanitized.strip() else "")


# 【职责】从一个装满 benchmark JSON 的目录加载 Silo-Bench 实例。
class SiloBenchAdapter(BenchmarkAdapter):
    """Load Silo-Bench instances from a directory of benchmark JSON files."""

    name = "silo_bench"

    def __init__(self, benchmarks_dir: str | Path) -> None:
        self.benchmarks_dir = Path(benchmarks_dir)

    # 【职责】遍历目录下的实例文件，按 levels/agent_counts/cases 过滤后逐个产出实例。
    # - 目录不存在则报错并提示补子模块或传 --benchmarks-dir。
    def iter_instances(
        self,
        *,
        levels: list[str] | None = None,
        agent_counts: list[int] | None = None,
        cases: list[str] | None = None,
    ) -> Iterable[BenchmarkInstance]:
        if not self.benchmarks_dir.is_dir():
            raise FileNotFoundError(
                f"Silo-Bench benchmarks dir not found: {self.benchmarks_dir}. "
                "Add the submodule or pass --benchmarks-dir (see masbench/README.md)."
            )
        for path in sorted(self.benchmarks_dir.glob("*.json")):
            resolved = self._resolve_file(path)
            if resolved is None:
                continue
            data, level, agents = resolved
            if levels is not None and level not in set(levels):
                continue
            if agent_counts is not None and agents not in set(agent_counts):
                continue
            if cases is not None and data.get("case_id") not in set(cases):
                continue
            yield self._to_instance(data)

    # 【职责】解析一个文件为(data, level, agents)三元组，无法加载则返回 None。
    # - 快路径：规范文件名 {Level}-{NN}_n{agents}.json 已编码等级+agent 数，非实例文件
    #   (如 benchmark_summary.json)无需读取即跳过。
    # - 兜底：文件名不匹配者(如 vendored 测试夹具)仅当文件体结构上是单个实例
    #   (含 case_id + agent_configs)才加载；level 由 case_id 前缀推得、agents 从文件体取。
    #   聚合文件缺这些键，故仍被跳过。
    def _resolve_file(self, path: Path) -> tuple[dict, str, int] | None:
        """Return ``(data, level, agents)`` for a loadable instance file, else None.

        Fast path: the canonical ``{Level}-{NN}_n{agents}.json`` filename encodes
        level + agent count, so non-instance files (e.g. ``benchmark_summary.json``)
        are skipped without being read. Fallback: a file whose name does not match
        (e.g. a vendored test fixture) is loaded only if its body is structurally a
        single instance (has ``case_id`` + ``agent_configs``); ``level`` is then
        derived from the ``case_id`` prefix and ``agents`` from the body. Aggregate
        files lack those keys and so are still skipped.
        """
        match = _FILENAME_RE.search(path.name)
        if match is not None:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data, match.group("level"), int(match.group("agents"))

        data = json.loads(path.read_text(encoding="utf-8"))
        if not (isinstance(data, dict) and "case_id" in data and "agent_configs" in data):
            return None
        case_id = str(data["case_id"])
        level = case_id.split("-", 1)[0] if "-" in case_id else case_id
        metadata = data.get("metadata", {})
        agents = int(metadata.get("num_agents", len(data["agent_configs"])))
        return data, level, agents

    # 【职责】把一份实例 JSON 数据转成 BenchmarkInstance(抽出分片、期望输出、元数据)。
    # - 泄漏修复：task_prompt 用 sanitized 版本(整段删 Communication Protocol)；meta 不
    #   携带 optimal_topology/optimal_message_count/theoretical_complexity。第三方原始
    #   文件不改动。expected_outputs 仍进 meta——它是宿主侧评分数据，桥接层保证它只进
    #   private scoring payload、绝不进模型上下文。
    def _to_instance(self, data: dict) -> BenchmarkInstance:
        agent_configs = data["agent_configs"]
        shards = [ac["input_shard"] for ac in agent_configs]
        expected_outputs = [ac.get("expected_output") for ac in agent_configs]
        metadata = {
            key: value
            for key, value in dict(data.get("metadata", {})).items()
            if key not in _LEAKY_METADATA_KEYS
        }
        # 中文：每 agent 的期望答案(分段任务各 agent 不同；普通任务重复同一全局答案)。
        #   总是携带，以便引擎能逐 agent 评分。
        # Per-agent expected answers (segmented tasks differ per agent; plain
        # tasks repeat the single global answer). Always carried so the engine
        # can grade per agent.
        metadata["expected_outputs"] = expected_outputs
        # 中文：把 segmented 标志归一化为真正的 bool，使引擎能无条件分支(旧/合成文件
        #   可能缺该字段→False)。
        # Normalize the segmented flag to a real bool so the engine can branch on
        # it unconditionally (older/synthetic files may omit it -> False).
        metadata["is_segmented"] = bool(metadata.get("is_segmented", False))
        return BenchmarkInstance(
            benchmark="silo_bench",
            case_id=data["case_id"],
            case_name=data.get("case_name", ""),
            n_agents=int(metadata.get("num_agents", len(agent_configs))),
            shards=shards,
            ground_truth=expected_outputs[0] if expected_outputs else None,
            task_prompt=sanitize_task_description(data.get("task_description", "")),
            meta=metadata,
        )
