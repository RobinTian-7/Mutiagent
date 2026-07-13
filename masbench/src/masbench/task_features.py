"""Deterministic task-context features from the task TEXT (phase 3, M1).

STATUS (M7): these regex heuristics are the OFFLINE FALLBACK ONLY (fake-LLM
tests, explicit ablation arm). The method derives task features via
:mod:`masbench.task_classify` -- the run's own LLM answering benchmark-
agnostic questions -- so nothing here is load-bearing for generalization.
The patterns below are fitted to Silo's statement templates and validated
against its labels; that is acceptable for test scaffolding and exactly why
they must not be the method.

The phase-2 boundary finding: executable-spec replay deploys one learned
organization onto every held-out case, and when the test case's information-
flow demands differ from every case the organization was earned on, blind
replay is a net harm (P2 dev round 3: ``generated:tree_reduce_to_sink``
replayed onto II-16 scored 0/8 while cold generation scored 1/8).

These features condition deployment on the TASK, using only the task
description text -- the same text the agents themselves receive. The
benchmark's internal ``paradigm`` label is never read at run time (it is used
only as offline ground truth in the tests).

Feature vocabulary (kept deliberately coarse so evidence per bucket
accumulates quickly):

* ``order_sensitive`` -- the task statement binds agents to positions in a
  sequence (segment ordering, neighbor exchange, pipeline). Silo level-II
  statements all carry explicit markers ("Agent Ordering", "CONSECUTIVE",
  "Position {agent_id}", a numbered chain); level-I statements never do.
* ``per_agent_output`` -- each agent must submit its OWN portion of the
  answer (segmented scoring) instead of one shared global answer. A
  sink-collect organization is structurally unable to put the right answer
  in every agent unless it redistributes.

``feature_key`` collapses the features into a small bucket id used by the
transfer-evidence ledger: ``of`` (order-free), ``os`` (order-sensitive,
shared answer), plus the ``-seg`` suffix when each agent answers for itself.

Borrowed designs (citations for the round report): task-conditioned skill
retrieval (Voyager's task-similarity retrieval; AWM's induced workflows
applied to matching task types; SkillGraph arXiv:2605.12039 argues retrieval
must be task/structure-conditioned, not similarity-only) and an explicit
SKIP/abstain route when nothing matches (SkillLens arXiv:2605.08386 routes
each skill unit to ACCEPT/DECOMPOSE/REWRITE/SKIP; our abstention is SKIP at
whole-organization granularity, falling back to the exact cold path).
"""
# ============================================================
# 【模块导读】仅凭任务文本得到的确定性任务上下文特征（阶段 3，M1）。
# 状态(M7)：这些正则启发式只是离线兜底（fake-LLM 测试、显式消融臂）；正式方法经
# masbench.task_classify 由运行自身的 LLM 回答与基准无关的问题来推导任务特征，
# 因此本文件不为泛化承重。下方模式按 Silo 的题面模板拟合、并对其标签校验——
# 作为测试脚手架可以接受，这也正是它们不能成为正式方法的原因。
# 阶段 2 的边界发现：可执行 spec 回放会把一套学到的组织部署到每个留出 case 上；当测试
# case 的信息流需求与该组织当初挣得证据的所有 case 都不同时，盲目回放是净伤害
# （P2 开发第 3 轮：generated:tree_reduce_to_sink 回放到 II-16 得 0/8，冷生成得 1/8）。
# 这些特征让部署以"任务"为条件，且只用任务描述文本——与智能体收到的文本相同；
# 基准内部的 paradigm 标签在运行时绝不读取（仅在测试中作为离线真值）。
# 特征词表刻意保持粗粒度，让每个桶的证据快速积累：
# * order_sensitive —— 题面把智能体绑定到序列位置（分段排序、邻居交换、流水线）。
#   Silo level-II 题面全都带显式标记；level-I 题面从不带。
# * per_agent_output —— 每个智能体须提交自己那份答案（分段计分），而非一个共享的
#   全局答案。汇聚收集型组织除非再分发，否则结构上无法把正确答案放进每个智能体。
# feature_key 把特征折叠成迁移证据台账用的小桶 id：of（顺序无关）、os（顺序敏感、
# 共享答案），每个智能体各自作答时再加 -seg 后缀。
# 借鉴的设计（轮报告引文）：任务条件化的技能检索（Voyager 的任务相似检索；AWM 把归纳
# 出的工作流用于匹配的任务类型；SkillGraph arXiv:2605.12039 主张检索须按任务/结构
# 条件化、不能只看相似度），以及无匹配时的显式 SKIP/弃权路线（SkillLens
# arXiv:2605.08386 把每个技能单元路由为 ACCEPT/DECOMPOSE/REWRITE/SKIP；我们的弃权是
# 整组织粒度的 SKIP，兜底回到严格的冷路径）。
# ============================================================

from __future__ import annotations

import re
from typing import Any

# 中文：位置绑定智能体的标记。Silo 大写强调处(CONSECUTIVE)刻意区分大小写，
#   散文变体则不区分大小写。
# Markers of position-bound agents. Case-sensitive on purpose where Silo
# shouts (CONSECUTIVE), case-insensitive for prose variants.
_ORDER_PATTERNS = (
    re.compile(r"agent ordering", re.IGNORECASE),
    re.compile(r"CONSECUTIVE"),
    re.compile(r"consecutive (segments?|parts?|elements?|blocks?)", re.IGNORECASE),
    re.compile(r"position \{agent_id\}", re.IGNORECASE),
    re.compile(r"sequential(ly| segments?)", re.IGNORECASE),
    re.compile(r"logical chain", re.IGNORECASE),
    re.compile(r"agent 0 (?:→|->|↔|<->) ?agent 1", re.IGNORECASE),
)

# 中文："每个智能体提交答案中属于自己那份切片"的标记。
# Markers that every agent submits its OWN slice of the answer.
_PER_AGENT_PATTERNS = (
    re.compile(r"each agent submits? (their|its) (own |)?(portion|segment|part)", re.IGNORECASE),
    re.compile(r"submits? their own final segment", re.IGNORECASE),
)

# 中文：聚合语义类别，首个匹配者胜出(M6)——排列顺序是承重的：seq 优先于 count/sum
#   （II-15 的 "count the subsequence" 属顺序类），vote 优先于 count（I-03 两者都提），
#   topk 优先于 max（I-09 "10 largest"），stats 优先于 mean（I-10 两阶段题面提到 mean）。
#   类别命名的是答案所需的统计量；一个有损组织可能对某类完美（vote/max 经得起摘要），
#   对另一类致命（count 映射不行：dev-1 gen staged_aggregate_to_sink 在 I-03 vote 上
#   1.00、在 I-05 count 上只有 0.17）。仅依据文本。
# Aggregation-semantics kind, FIRST match wins (M6) -- order is load-bearing:
# `seq` outranks `count`/`sum` (II-15 "count the subsequence" is sequential),
# `vote` outranks `count` (I-03 says both), `topk` outranks `max` (I-09 "10
# largest"), `stats` outranks `mean` (I-10's two-phase text mentions mean).
# The kind names the statistic the answer requires; a LOSSY organization can
# be perfect for one kind (vote/max survive summarization) and fatal for
# another (count maps don't: dev-1 gen staged_aggregate_to_sink was 1.00 on
# I-03 vote and 0.17 on I-05 count). Text-only.
_AGG_KIND_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("vote", re.compile(r"\bvot(e|es|ing)\b", re.IGNORECASE)),
    ("seq", re.compile(
        r"prefix sum|cumulative|moving average|cellular automaton|hash chain"
        r"|difference array|\brank\b|palindrom|subsequence|trapping|elevation",
        re.IGNORECASE,
    )),
    ("topk", re.compile(r"top[- ]?k|top \d+|\b\d+ largest\b", re.IGNORECASE)),
    ("count", re.compile(r"\bcount\b|occurrences|frequency|how many", re.IGNORECASE)),
    ("max", re.compile(r"\bmaximum\b|\blargest\b", re.IGNORECASE)),
    ("min", re.compile(r"\bminimum\b|\bsmallest\b", re.IGNORECASE)),
    ("any", re.compile(r"\bANY\b|\bcontains\b.*\bsubstring\b", re.IGNORECASE)),
    ("xor", re.compile(r"\bXOR\b|checksum", re.IGNORECASE)),
    ("stats", re.compile(r"standard deviation|variance|median", re.IGNORECASE)),
    ("mean", re.compile(r"\baverage\b|\bmean\b", re.IGNORECASE)),
    ("set", re.compile(r"\bDISTINCT\b|\bunique\b|deduplicat", re.IGNORECASE)),
    ("sum", re.compile(r"\bsum\b", re.IGNORECASE)),
    ("sort", re.compile(r"\bsort(ed)?\b|ascending|descending", re.IGNORECASE)),
)


# 【职责】判断任务所需的聚合统计量类别（仅看文本，首个匹配的模式胜出，无匹配归 other）。
def agg_kind(task_text: str | None) -> str:
    """The task's required aggregation-statistic kind (text-only)."""
    text = task_text or ""
    for kind, pattern in _AGG_KIND_PATTERNS:
        if pattern.search(text):
            return kind
    return "other"


# 【职责】仅从题面文本提取布尔任务特征（order_sensitive / per_agent_output）。
def extract_task_features(task_text: str | None) -> dict[str, bool]:
    """Boolean task features from the statement text only."""
    text = task_text or ""
    return {
        "order_sensitive": any(p.search(text) for p in _ORDER_PATTERNS),
        "per_agent_output": any(p.search(text) for p in _PER_AGENT_PATTERNS),
    }


# 【职责】把特征字典折叠成规范的粗粒度桶 id：of / os，各自作答时追加 -seg 后缀。
def feature_key(features: dict[str, Any]) -> str:
    """Canonical coarse bucket id for a feature dict."""
    base = "os" if features.get("order_sensitive") else "of"
    if features.get("per_agent_output"):
        return f"{base}-seg"
    return base


# 【职责】求 BenchmarkInstance 的特征桶（仅文本；绝不读基准标签）。
def instance_feature_key(instance: Any) -> str:
    """Feature bucket of a BenchmarkInstance (text-only; never reads labels)."""
    return feature_key(extract_task_features(getattr(instance, "task_prompt", "") or ""))


# 【职责】求 BenchmarkInstance 的聚合统计量类别（仅文本）。
def instance_agg_kind(instance: Any) -> str:
    """Aggregation-kind of a BenchmarkInstance (text-only)."""
    return agg_kind(getattr(instance, "task_prompt", "") or "")
