"""M1: evidence-conditioned transfer gate for skill deployment (phase 3).

A skill's executable organization may be REPLAYED onto a held-out case only
when the skill's own measured evidence shows it succeeding on tasks in the
same feature bucket (see :mod:`masbench.task_features`). When no skill in the
bank qualifies for the case's bucket, deployment ABSTAINS: the evolved arm
runs the exact cold path (empty bank, no motif prior), so on
representationally-uncovered cases it equals the baseline by construction
instead of force-replaying a mismatched organization (the P2 failure mode).

Trust demands ``n >= MIN_TRUST_ROWS`` rows in the bucket with bucket mean
exact-match ``>= MIN_TRUST_EM`` -- one lucky run cannot earn deployment
(phase-2 lesson: a 1-seed signal is a Bernoulli gate).

The ledger lives in ``skill.organization_policy["transfer_evidence"]`` as
``{bucket: {"n": int, "em_sum": float}}`` and is COMBINED (not overwritten)
across evolution rounds.

Motif credit is bucket-namespaced ("<bucket>|<motif_key>") so structural
priors learned on order-free evidence cannot bias generation on
order-sensitive cases; :func:`motif_view` projects the namespaced stats back
to raw motif keys for one bucket at deployment.
"""
# ============================================================
# 【模块导读】M1：技能部署的证据条件迁移门（phase 3）。
# 只有当技能自身的实测证据显示它在同一特征桶的任务上成功过，其可执行组织才可被重放到
# 留出 case 上；若库中无技能达标，部署即弃权：evolved 臂走精确的冷路径（空技能库、无
# motif 先验），从而在“表征上未覆盖”的 case 上按构造等于基线，而非强行重放不匹配的组织
# （P2 的失败模式）。信任要求：桶内至少 MIN_TRUST_ROWS 行、且桶均精确匹配 >= MIN_TRUST_EM
# ——单次走运不能换来部署（1 个种子的信号是伯努利门）。账本存于
# skill.organization_policy["transfer_evidence"]，形如 {bucket: {"n": int, "em_sum": float}}，
# 跨进化轮“合并”（非覆盖）。motif 信用按桶命名空间隔离（"<bucket>|<motif_key>"），使在无序
# 证据上学到的结构先验不会偏置有序 case 的生成；motif_view 在部署时把命名空间统计投影回
# 单个桶的原始 motif 键。
# ============================================================

from __future__ import annotations

from typing import Any

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank, is_avoid_skill
from exp_graph.mas.topology_equivalence import fingerprint_protocol_spec
from exp_graph.protocols import ProtocolGraphSpec

MIN_TRUST_ROWS = 2
MIN_TRUST_EM = 0.5

TRANSFER_EVIDENCE_KEY = "transfer_evidence"


# 【职责】一行证据在信任账本里的成功度取值。
# - M21：质量分级 benchmark 上二元精确匹配是错误的信任货币（23% 质量的排程被记为完全失败，
#   学习者永远拿不到部署信任）。优先用行里的 MeanPrimaryMetric（该 benchmark 自己的 [0,1]
#   主指标）；Silo 上两字段按构造相等（账本逐字节一致），JSSP 上信任变为分级（质量可累积信用）。
def _row_em(row: dict[str, Any]) -> float:
    """Trust-ledger success value for one row.

    M21 (jssp-easy forensics): binary exact-match is the wrong trust
    currency on quality-graded benchmarks -- a 23%-quality schedule counts
    as total failure, so the learner can never earn deployment trust and
    abstains forever. Rows carry ``MeanPrimaryMetric`` (the benchmark's own
    primary success in [0,1]); prefer it when present. On Silo the two
    fields are equal by construction (pinned by test), so Silo ledgers are
    byte-identical; on JSSP trust becomes graded (quality accrues credit).
    """
    pm = row.get("MeanPrimaryMetric")
    if pm is not None:
        try:
            return float(pm)
        except (TypeError, ValueError):
            pass
    return float(row.get("ExactMatchRate", 0.0) or 0.0)


# 【职责】(bank, motif) 的确定性内容哈希——断点续跑缓存键的一部分。
# - 温度 0 下持有逐字节相同学习状态的两次运行是同一测量条件；M18 用它为部署期的行编键，
#   使被中断的 judge 运行可重启并重放已完成的配对。
def bank_state_hash(bank: SkillBank, motif_stats: dict | None = None) -> str:
    """Deterministic content hash of (bank, motif) — the resume-cache key part.

    Two runs holding byte-identical learned state are the same measurement
    condition at temperature 0; M18 keys deployment-phase rows on this so an
    interrupted judge run can be relaunched and replay its finished pairs.
    """
    import hashlib
    import json as _json

    payload = {
        "skills": sorted(
            (_json.dumps(s.model_dump(mode="json"), sort_keys=True) for s in bank),
        ),
        "motif": motif_stats or {},
    }
    return hashlib.sha256(
        _json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


# 【职责】M11：已执行组织的结构身份。
# - 生成的组织带有每次运行的名字，名字为键的账本会把同一结构的成功拆成 n=1 的碎片而永远
#   达不到信任门；身份 = 仓库对已执行 spec 的拓扑等价哈希，名字只是标签。
def spec_struct_hash(spec_data: Any) -> str | None:
    """M11: structural identity of an executed organization.

    Generated organizations carry per-run NAMES, so a name-keyed ledger
    splits one structure's successes into n=1 fragments that never reach the
    trust bar (dev-5 gen forensics). Identity = the repo's
    topology-equivalence hash of the executed spec; the name is a label.
    """
    if not isinstance(spec_data, dict) or not spec_data.get("steps"):
        return None
    try:
        spec = ProtocolGraphSpec.model_validate(spec_data)
        return fingerprint_protocol_spec(spec).topology_equivalence_hash
    except Exception:
        return None


# 【职责】一行的账本身份：优先结构哈希，否则用拓扑名。
def _row_identity(row: dict[str, Any]) -> str | None:
    """Ledger identity for a row: structural hash, else topology name."""
    h = spec_struct_hash(row.get("protocol_spec"))
    if h:
        return h
    topology = str(row.get("Topology", "") or "")
    return topology or None


# 【职责】一个技能的账本身份：优先其 spec 的结构哈希，否则用拓扑名。
def skill_identity(skill: SkillCard) -> str | None:
    policy = skill.organization_policy or {}
    h = spec_struct_hash(policy.get("protocol_spec"))
    if h:
        return h
    topology = policy.get("topology_name") or skill.topology_name
    return str(topology) if topology else None


# 【职责】从原始进化行构建 (拓扑, 特征桶) 的成功账本。
# - M6：每行还喂入一个 bucket#agg_kind 子槽，当桶级证据自相矛盾时可把信任细化到种类粒度
#   （在投票类任务完美、计数类致命的组织，不能靠桶均值骑到计数 case 上）。
def build_transfer_ledger(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Per-(topology, feature bucket) success ledger from raw evolution rows.

    M6: each row also feeds a ``bucket#agg_kind`` sub-slot so trust can be
    REFINED to kind granularity when the bucket-level evidence is
    contradictory (an organization perfect on vote-kind tasks and fatal on
    count-kind tasks must not ride the bucket mean onto count cases).
    """
    ledger: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        identity = _row_identity(row)
        bucket = row.get("task_features_key")
        if not identity or not bucket:
            continue
        slots = ledger.setdefault(identity, {})
        keys = [str(bucket)]
        # 中文：M12/M16：子槽键是旧 agg-kind 分类所代理的两个“机理”位——正确性能否在本地
        #   摘要后存活，以及答案是单个值还是需要组装的复合结构。易分类、易累积，且能分开
        #   每一种实测失败模式（投票 vs 计数的双峰；标量 II-13/15 可保留 vs 复合 II-17/19 需 Modify）。
        # M12/M16: the sub-slot key is the pair of MECHANISTIC bits the old
        # agg-kind taxonomy proxied -- does correctness survive local
        # summarization, and is the answer a single value or a composite
        # structure needing assembly. Robust to classify, fast to
        # accumulate, and they separate every measured failure mode
        # (vote-vs-count bimodality; scalar II-13/15 preserve vs composite
        # II-17/19 needing Modify).
        lossless = row.get("task_needs_lossless")
        if lossless is not None:
            shape = "composite" if row.get("task_answer_composite") else "scalar"
            keys.append(
                f"{bucket}#{'lossless' if lossless else 'lossy'}-{shape}"
            )
        case_id = row.get("case_id")
        value = _row_em(row)
        graded = abs(value) > 1e-9 and abs(value - 1.0) > 1e-9
        for key in keys:
            slot = slots.setdefault(key, {"n": 0, "em_sum": 0.0})
            slot["n"] += 1
            slot["em_sum"] += value
            # 中文：M22：货币检测——被喂入任何非 {0,1} 值的槽被视为“分级”（质量指标），适用
            #   比较式信任门。
            # M22: currency detection -- a slot fed any non-{0,1} value is
            # GRADED (quality metric) and gets the comparative trust bar.
            if graded:
                slot["graded"] = True
            # 中文：M19：不同 case 的来源——同一 case 的多个种子不是迁移证据（有上限；多样性
            #   阈值很小）。
            # M19: distinct-case provenance -- seeds of one case are not
            # transfer evidence (capped; diversity thresholds are tiny).
            if case_id is not None:
                cases = slot.setdefault("cases", [])
                if str(case_id) not in cases and len(cases) < 16:
                    cases.append(str(case_id))
                    cases.sort()
        # 中文：M22：跨所有组织的按桶“汇池”统计（保留身份 __pool__），分级信任的比较基线。
        # M22: per-bucket POOLED stats across ALL organizations (reserved
        # identity), the comparison baseline for graded trust.
        pool_slots = ledger.setdefault("__pool__", {})
        pool = pool_slots.setdefault(str(bucket), {"n": 0, "em_sum": 0.0})
        pool["n"] += 1
        pool["em_sum"] += value
        if graded:
            pool["graded"] = True
    return ledger


# 【职责】合并两份按桶统计：累加 n 与 em_sum，或运算 graded，并去重合并 cases（上限 16）。
def combine_bucket_stats(
    old: dict[str, dict[str, float]] | None,
    new: dict[str, dict[str, float]] | None,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for source in (old or {}, new or {}):
        for bucket, stats in source.items():
            slot = out.setdefault(str(bucket), {"n": 0, "em_sum": 0.0})
            slot["n"] += int(stats.get("n", 0))
            slot["em_sum"] += float(stats.get("em_sum", 0.0))
            if stats.get("graded"):
                slot["graded"] = True
            incoming = stats.get("cases")
            if isinstance(incoming, list) and incoming:
                cases = slot.setdefault("cases", [])
                for c in incoming:
                    if str(c) not in cases and len(cases) < 16:
                        cases.append(str(c))
                cases.sort()
    return out


# 【职责】把本轮账本折叠进每个技能的 organization_policy。
# - prior 映射 skill_id -> 本轮补丁应用“之前”从继承技能库快照的桶统计（合并补丁会覆盖
#   organization_policy 键，故跨轮累积在此处完成）。
def inject_transfer_evidence(
    bank: SkillBank,
    rows: list[dict[str, Any]],
    *,
    prior: dict[str, dict[str, dict[str, float]]] | None = None,
) -> None:
    """Fold this round's ledger into every skill's organization policy.

    ``prior`` maps skill_id -> bucket stats snapshotted from the inherited
    bank BEFORE this round's patches were applied (merge patches overwrite
    ``organization_policy`` keys, so cross-round accumulation happens here).
    """
    ledger = build_transfer_ledger(rows)
    for skill in bank:
        if is_avoid_skill(skill):
            continue
        if skill.organization_policy is None:
            continue
        identity = skill_identity(skill)
        # 中文：优先结构身份（M11）；名字作为次级匹配保留，使存储 spec 解析失败的命名拓扑
        #   技能仍能累积。
        # Structural identity first (M11); name kept as a secondary match so
        # named-topology skills whose stored spec failed to parse still
        # accumulate.
        fresh = ledger.get(identity or "", {})
        if not fresh:
            topology = skill.organization_policy.get("topology_name") or skill.topology_name
            fresh = ledger.get(str(topology), {})
        # 中文：M22：每张卡还带上按桶“汇池”基线（保留 "__pool__:<bucket>" 键），使分级信任能拿
        #   “本组织”对比“该桶里测过的所有组织”。重复卡合并时均值保持不变（n 与 sum 同增）。
        # M22: every card also carries the per-bucket POOLED baseline
        # (reserved "__pool__:<bucket>" keys) so graded trust can compare
        # "this org" against "all orgs measured in this bucket". Merging is
        # mean-preserving under duplicate-card merges (n and sum both add).
        pool = ledger.get("__pool__", {})
        if pool and fresh:
            fresh = {
                **fresh,
                **{f"__pool__:{b}": dict(stats) for b, stats in pool.items()},
            }
        old = (prior or {}).get(skill.skill_id)
        existing = skill.organization_policy.get(TRANSFER_EVIDENCE_KEY)
        # 中文：existing 是本轮补丁合并后残存的内容；给了显式的轮前快照就优先用它（那是
        #   未被污染的状态）。
        # `existing` is whatever survived patch-merging this round; prefer the
        # explicit pre-round snapshot when given (it is the uncorrupted state).
        base = old if old is not None else existing
        combined = combine_bucket_stats(base, fresh)
        if combined:
            skill.organization_policy[TRANSFER_EVIDENCE_KEY] = combined
            # 中文：M19a：盖上全局不同 case 多样性，供检索侧悲观（exp-graph 读取
            #   expected_tradeoff.evidence_case_count；CF 卡从不到此，故 CF 排序不受影响）。
            # M19a: stamp global distinct-case diversity for retrieval-side
            # pessimism (exp-graph reads expected_tradeoff.evidence_case_count;
            # CF cards never get here, so CF ranking is untouched).
            all_cases: set[str] = set()
            bare_n = 0
            for key, stats in combined.items():
                if "#" in key or not isinstance(stats, dict):
                    continue
                cases = stats.get("cases")
                if isinstance(cases, list):
                    all_cases.update(str(c) for c in cases)
                elif int(stats.get("n", 0)) > 0:
                    bare_n = 1
            count = len(all_cases) if all_cases else bare_n
            if count and isinstance(skill.expected_tradeoff, dict):
                skill.expected_tradeoff["evidence_case_count"] = count


# 【职责】统计一张技能账本里桶级槽（排除 # 子槽与 __pool__）的总样本数 n。
def _ledger_total_n(skill: SkillCard) -> int:
    policy = skill.organization_policy or {}
    ledger = policy.get(TRANSFER_EVIDENCE_KEY)
    if not isinstance(ledger, dict):
        return 0
    return sum(
        int(stats.get("n", 0))
        for key, stats in ledger.items()
        if isinstance(stats, dict) and "#" not in key
        and not key.startswith("__pool__")
    )


# 【职责】M11/M13c：一个结构 = 一个技能家族，重复者合并。
# - 生成的组织每轮以新名字重新进入技能库，不合并则库线性膨胀（9->13->15）、且同一结构的
#   信任证据一直碎片化。同身份可选技能中证据最多的卡存活；账本合并；存活者的
#   organization_policy 记录被吸收的 id。返回被移除的卡数。
def merge_structural_duplicates(bank: SkillBank) -> int:
    """M11/M13c: one structure = one skill family; duplicates merge.

    Generated organizations re-enter the bank each round under fresh names;
    without this the bank grows linearly (dev rounds: 9 -> 13 -> 15) and one
    structure's trust evidence stays fragmented. Among same-identity
    selectable skills the most-evidenced card survives; ledgers combine; the
    survivor's organization_policy records the absorbed ids. Returns the
    number of cards removed.
    """
    by_identity: dict[str, list[SkillCard]] = {}
    for skill in list(bank):
        if is_avoid_skill(skill):
            continue
        identity = skill_identity(skill)
        # Explicit hot-start portfolio members preserve their protocol-family
        # identity. At n=2, for example, one-peer and static exponential expand
        # to the same tiny edge schedule but have different scaling programs;
        # merging them would turn the requested five-skill bank into four.
        if identity and "hot-start" in skill.tags:
            identity = f"{identity}|hot-start:{skill.skill_id}"
        if identity:
            by_identity.setdefault(identity, []).append(skill)
    removed = 0
    for identity, group in by_identity.items():
        if len(group) < 2:
            continue
        group.sort(key=_ledger_total_n, reverse=True)
        survivor, rest = group[0], group[1:]
        policy = survivor.organization_policy or {}
        hot_group = any("hot-start" in skill.tags for skill in group)
        combined_evidence = list(survivor.evidence)
        combined_insights = list(survivor.design_insights)
        hot_start_codes: list[dict[str, Any]] = []
        hot_start_evidence_summaries: list[dict[str, Any]] = []
        if hot_group and isinstance(policy.get("structure_code"), dict):
            hot_start_codes.append(dict(policy["structure_code"]))
        survivor_hot_summary = survivor.expected_dynamics.get(
            "hot_start_evidence_summary"
        )
        if hot_group and isinstance(survivor_hot_summary, dict):
            hot_start_evidence_summaries.append(dict(survivor_hot_summary))
        combined = policy.get(TRANSFER_EVIDENCE_KEY)
        absorbed = list(policy.get("absorbed_skill_ids") or [])
        combined_tags = list(survivor.tags)
        hot_start_topologies = {
            str(item)
            for item in (policy.get("hot_start_seed_topologies") or [])
        }
        if "hot-start-fixed" in survivor.tags and not hot_start_topologies:
            hot_start_topologies.add(str(policy.get("topology_name")))
        for dup in rest:
            dup_ledger = (dup.organization_policy or {}).get(TRANSFER_EVIDENCE_KEY)
            combined = combine_bucket_stats(combined, dup_ledger)
            absorbed.append(dup.skill_id)
            for tag in dup.tags:
                if tag not in combined_tags:
                    combined_tags.append(tag)
            dup_policy = dup.organization_policy or {}
            if hot_group:
                for evidence in dup.evidence:
                    if evidence not in combined_evidence:
                        combined_evidence.append(evidence)
                for insight in dup.design_insights:
                    if insight not in combined_insights:
                        combined_insights.append(insight)
                if isinstance(dup_policy.get("structure_code"), dict):
                    code = dict(dup_policy["structure_code"])
                    if code not in hot_start_codes:
                        hot_start_codes.append(code)
                dup_hot_summary = dup.expected_dynamics.get(
                    "hot_start_evidence_summary"
                )
                if isinstance(dup_hot_summary, dict):
                    summary = dict(dup_hot_summary)
                    if summary not in hot_start_evidence_summaries:
                        hot_start_evidence_summaries.append(summary)
            dup_hot_start_topologies = dup_policy.get(
                "hot_start_seed_topologies"
            ) or []
            hot_start_topologies.update(
                str(item)
                for item in dup_hot_start_topologies
            )
            if "hot-start-fixed" in dup.tags and not dup_hot_start_topologies:
                hot_start_topologies.add(str(dup_policy.get("topology_name")))
            bank.skills.pop(dup.skill_id, None)
            removed += 1
        if combined:
            policy[TRANSFER_EVIDENCE_KEY] = combined
        policy["absorbed_skill_ids"] = absorbed
        policy.setdefault("structural_identity", identity)
        if hot_start_topologies:
            policy["hot_start_seed_topologies"] = sorted(hot_start_topologies)
        if hot_group:
            if hot_start_codes and not isinstance(policy.get("structure_code"), dict):
                policy["structure_code"] = hot_start_codes[0]
            if hot_start_codes:
                policy["hot_start_structure_codes"] = hot_start_codes
            survivor.evidence = combined_evidence
            survivor.design_insights = combined_insights
            if hot_start_evidence_summaries:
                dynamics = dict(survivor.expected_dynamics)
                dynamics["hot_start_evidence_summaries"] = (
                    hot_start_evidence_summaries
                )
                dynamics.setdefault(
                    "hot_start_evidence_summary",
                    hot_start_evidence_summaries[0],
                )
                survivor.expected_dynamics = dynamics
        survivor.tags = combined_tags
    return removed


# 【职责】M13：在每张卡上显式标注设计规则的“动作”。
# - 论文词汇（operator 论点）：每条规则带 Preserve/Modify/Avoid。Avoid 卡 -> "avoid"；
#   可执行 spec 卡 -> "preserve"（部署时可改写每步指令升级为 Modify——M9）；仅散文卡 -> "context"。
def stamp_rule_actions(bank: SkillBank) -> None:
    """M13: make the design-rule ACTION explicit on every card.

    Paper vocabulary (operator thesis): each rule carries Preserve / Modify
    / Avoid. Avoid cards -> "avoid"; executable-spec cards -> "preserve"
    (deployment may upgrade to Modify by rewriting per-step instructions for
    the live task -- M9); prose-only cards -> "context".
    """
    for skill in bank:
        policy = skill.organization_policy
        if policy is None:
            continue
        if is_avoid_skill(skill):
            policy["rule_action"] = "avoid"
        elif isinstance(policy.get("protocol_spec"), dict) and (
            policy["protocol_spec"] or {}
        ).get("steps"):
            policy["rule_action"] = "preserve"
        else:
            policy["rule_action"] = "context"


# 【职责】快照当前技能库里各技能的 transfer_evidence 账本（供轮前保存、跨轮累积用）。
def snapshot_transfer_evidence(
    bank: SkillBank,
) -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for skill in bank:
        policy = skill.organization_policy or {}
        ledger = policy.get(TRANSFER_EVIDENCE_KEY)
        if isinstance(ledger, dict) and ledger:
            out[skill.skill_id] = {
                str(bucket): dict(stats) for bucket, stats in ledger.items()
            }
    return out


GRADED_TRUST_MARGIN = 0.15
GRADED_TRUST_FLOOR = 0.2


# 【职责】槽的证据是否达标：行数够判定时返回 True/False，否则 None。
# - M22 货币感知门：二元槽（值全在 {0,1}，所有 Silo 行）沿用绝对 MIN_TRUST_EM 规则，逐字节
#   一致。分级槽（质量指标，如 JSSP makespan 比）用比较式“不伤害”门：组织须以
#   GRADED_TRUST_MARGIN 胜过该桶的汇池全组织均值（并越过绝对下限）；对质量比用绝对 0.5 会
#   把信任与任务难度混为一谈。
def _slot_passes(stats: Any, pool: Any = None) -> bool | None:
    """True/False when the slot has enough rows to judge, None otherwise.

    M22 currency-aware bar: BINARY slots (every value in {0,1} -- all Silo
    rows) keep the absolute MIN_TRUST_EM rule byte-identically. GRADED
    slots (quality metrics, e.g. JSSP makespan ratio) use a COMPARATIVE
    do-no-harm bar: the org must beat the bucket's pooled all-org mean by
    GRADED_TRUST_MARGIN (and clear an absolute floor). An absolute 0.5 on
    a quality ratio conflates trust with task hardness -- jssp-v3 measured
    permanent abstention because no schedule ever averaged 0.5 while orgs
    clearly better than cold (0.3 vs 0.05) earned nothing.
    """
    if not isinstance(stats, dict):
        return None
    n = int(stats.get("n", 0))
    if n < MIN_TRUST_ROWS:
        return None
    mean = float(stats.get("em_sum", 0.0)) / n
    if not stats.get("graded"):
        return mean >= MIN_TRUST_EM
    if mean >= MIN_TRUST_EM:
        return True
    if isinstance(pool, dict) and int(pool.get("n", 0)) >= MIN_TRUST_ROWS:
        pool_mean = float(pool.get("em_sum", 0.0)) / int(pool["n"])
        return mean >= pool_mean + GRADED_TRUST_MARGIN and mean >= GRADED_TRUST_FLOOR
    return False


# 【职责】一个槽背后不同的证据 case 数。
# - M19：同一 case 的多个种子是相关抽样，不算迁移证据；早于 case 追踪的槽只要有行就保守
#   计为 1 个 case。
def slot_case_diversity(stats: Any) -> int:
    """Distinct evidenced cases behind a slot.

    M19 (dev-11): seeds of one case are correlated draws, not transfer
    evidence. Slots that predate case tracking (e.g. recipe cards'
    pre-seeded verification stats) conservatively count as ONE case when
    they have rows at all.
    """
    if not isinstance(stats, dict):
        return 0
    cases = stats.get("cases")
    if isinstance(cases, list):
        return len({str(c) for c in cases})
    return 1 if int(stats.get("n", 0)) > 0 else 0


# 【职责】跨一张技能整个账本的全局不同 case 计数。
# - 当没有任何槽带 case 来源（账本早于 M19 追踪）返回 None，让调用方对旧快照保持旧行为。
def _ledger_case_diversity(ledger: dict[str, Any]) -> int | None:
    """Global distinct-case count across a skill's whole ledger.

    Returns None when NO slot carries case provenance (ledger predates M19
    tracking) so callers can keep legacy behavior for old snapshots.
    """
    cases: set[str] = set()
    tracked = False
    for stats in ledger.values():
        if not isinstance(stats, dict):
            continue
        slot_cases = stats.get("cases")
        if isinstance(slot_cases, list):
            tracked = True
            cases.update(str(c) for c in slot_cases)
    if not tracked:
        return None
    return len(cases)


# 中文：M8：把信任外推到技能从未测过的子槽需要“广度”——每个测过的子槽都通过、且至少这么
#   多个。配合 M12 的二元槽（lossless/lossy）即：只在一个位上有证据的技能只对该位可信；外推
#   到另一位要求两位都测过且通过，绝不盲目发生。证据狭窄时，仅“无矛盾”不等于一致（dev 第 3
#   轮的反转认识论）。
# M8: extrapolating trust to a sub-slot the skill was never measured on
# demands BREADTH -- every measured sub-slot passing and at least this many
# of them. With M12's binary slots (lossless/lossy) this means: a skill with
# evidence on only ONE bit is trusted only for that bit; extrapolating to
# the other bit requires both measured-and-passing, i.e. it never happens
# blindly. "No contradiction" alone is not consistency when the evidence is
# narrow (dev round 3's inverted epistemics).
BUCKET_TRUST_MIN_KINDS = 2

# 中文：M28（已禁用——记录的负面结果）。下面的跨桶通才救援本想在 one_peer 唯一的 os 锚点
#   （II-13）漂移到失败时保住它的信任。同窗 A/B + draw2 取证否定了它：它把 os-可信候选从 2 个
#   膨胀到 9 个（救回只在 2 个 case 上挣得的 of-过拟合 staged_*），稀释检索，以致选了 of-过拟合
#   组织而非 os-直接可信的 one_peer -> gen 崩到 4.2%。与 M27 同形：看似合理却有害的修补。以
#   默认关闭的开关保留，作为负面结果的记录。
# M28 (DISABLED -- recorded negative result). The cross-bucket-generalist
# rescue below was meant to keep one_peer trusted when its single os anchor
# (II-13) drifts to failure. The same-window A/B + draw2 forensics disproved
# it: it ballooned os-trusted candidates from 2 to 9 (rescuing of-overfit
# staged_* earned on just 2 cases), diluting retrieval so it picked an
# of-overfit org over the os-direct-trusted one_peer -> gen crashed to 4.2%.
# Same shape as M27: a plausible fix that hurt. Kept behind a default-off
# flag as documentation of the negative result.
_M28_CROSS_BUCKET_RESCUE = False


# 【职责】桶的证据是否来自 <=1 个不同 case。
# - n=5 时 os 桶只有一个可学锚点（II-13），其汇总裁决就是一个 case 的抽样，会随 provider
#   漂移窗口在 0..1.0 间摇摆，故单锚点裁决不足以单独否决一个结构。
def _bucket_single_anchor(ledger: dict, bucket: str) -> bool:
    """True if the bucket's evidence comes from <=1 distinct case.

    At n=5 the os bucket has exactly one learnable training anchor (II-13),
    so its aggregate verdict is one case's draw -- which swings 0..1.0
    across provider-drift windows (measured: same one_peer 0/10 one window,
    8/8 another). A single-anchor verdict is therefore not reliable enough
    to VETO a structure on its own.
    """
    return slot_case_diversity(ledger.get(bucket)) <= 1


# 【职责】组织是否在另一个桶里“多样地挣得”信任（>=2 个 case 且通过）。
# - M28：这样的组织是通用强结构（如 one_peer 在每个窗口对 3 个 'of' case 保持 0.67）；
#   staged_pair_gather 在 'of' 上是单 case em0——不通用——故不被救援。区分靠结构而非名字。
def _cross_bucket_generalist(ledger: dict, *, exclude: str) -> bool:
    """True if the org diverse-earns (>=2 cases, passing) in another bucket.

    M28: such an org is a GENERAL strong structure (e.g. one_peer holds
    0.67 across 3 'of' cases in every window). staged_pair_gather, by
    contrast, is single-case em0 in 'of' -- not general -- so it is NOT
    rescued. The distinction is structural, not name-based.
    """
    for key, stats in ledger.items():
        if "#" in key or key.startswith("__pool__") or key == exclude:
            continue
        if (
            _slot_passes(stats, ledger.get(f"__pool__:{key}")) is True
            and slot_case_diversity(stats) >= 2
        ):
            return True
    return False


# 【职责】信任 = 在可得的最细粒度上实测出的胜任度。
# - 1) 桶级汇总须通过（合理性下限）——除非该桶是单锚点、裁决不可靠且组织是跨桶通才（M28），
#   此时单锚点失败不否决，改走 Modify 部署。
# - 2) 有直接的 kind 证据时由它决定（通过->信任，测充分的失败->不信任）。
# - 3) 外推到未测 kind 需广度：>= BUCKET_TRUST_MIN_KINDS 个 kind 通过且无一失败。
# - 4) 完全没有 kind 子槽的账本（旧卡）保持朴素的桶级语义。
def skill_trusted_for(skill: SkillCard, bucket: str, kind: str | None = None) -> bool:
    """Trust = measured competence at the finest available granularity.

    1. The bucket aggregate must pass (sanity floor) -- UNLESS the bucket is
       a single-anchor bucket whose verdict is unreliable AND the org is a
       cross-bucket generalist (M28): then a single-anchor failure does not
       veto, and deployment proceeds via Modify (rewrite the proven general
       structure for this task).
    2. Direct kind evidence decides when it exists (pass -> trust,
       well-measured fail -> no trust).
    3. Extrapolation to an UNMEASURED kind requires breadth: >=
       ``BUCKET_TRUST_MIN_KINDS`` kinds passing and none failing.
    4. Ledgers with no kind sub-slots at all (legacy cards) keep plain
       bucket-level semantics.
    """
    policy = skill.organization_policy or {}
    ledger = policy.get(TRANSFER_EVIDENCE_KEY)
    if not isinstance(ledger, dict):
        return False
    # 中文：M22：分级槽对比该桶的汇池全组织均值。
    # M22: graded slots compare against the bucket's pooled all-org mean
    pool = ledger.get(f"__pool__:{bucket}")
    if _slot_passes(ledger.get(bucket), pool) is not True:
        # 中文：M28 跨桶救援（默认关闭——见上文开关说明，它稀释检索、有害）。启用时，单锚点
        #   桶的失败不否决跨桶通才。
        # M28 cross-bucket rescue (default OFF -- see flag note above; it
        # diluted retrieval and hurt). When enabled, a single-anchor bucket
        # failure does not veto a cross-bucket generalist.
        if (
            _M28_CROSS_BUCKET_RESCUE
            and kind
            and _bucket_single_anchor(ledger, bucket)
            and _cross_bucket_generalist(ledger, exclude=bucket)
        ):
            return True
        return False
    sub = {
        key.split("#", 1)[1]: _slot_passes(stats, pool)
        for key, stats in ledger.items()
        if key.startswith(f"{bucket}#")
    }
    if not sub:
        return True  # legacy ledger: bucket-level semantics
    if kind:
        direct = sub.get(kind)
        if direct is not None:
            return direct
        # 中文：M16b：两个位的外推方式不同。无损性是能力边界——绝不跨越；形状是适应边界——
        #   形状同胞槽（同无损性、另一形状）授权部署，且因直接证据缺失，M14 动作自动为 MODIFY
        #   （为组装改写角色指令）。否则 case 全是一种形状的训练池会饿死每个复合槽（dev-10b：
        #   16/24 弃权，Modify 路径从未触发）。
        # M16b: the two bits extrapolate differently. LOSSLESSNESS is a
        # capability boundary -- never crossed. SHAPE is an adaptation
        # boundary -- the shape-sibling slot (same losslessness, other
        # shape) authorizes deployment, and because direct evidence is
        # absent the M14 action is automatically MODIFY (rewrite the role
        # instructions for assembly). Without this, train pools whose cases
        # are all one shape starve every composite slot (dev-10b: 16/24
        # abstentions, the Modify path never fired).
        if "-" in kind:
            lossless_part, shape_part = kind.rsplit("-", 1)
            sibling_shape = "scalar" if shape_part == "composite" else "composite"
            sibling = sub.get(f"{lossless_part}-{sibling_shape}")
            if sibling is False:
                # 中文：不伤害：已测出的失败在任何多样性下都阻断。
                # do-no-harm: a measured failure blocks at ANY diversity
                return False
            if sibling is True:
                # 中文：M19（dev-11）：正面裁决只有当该产物在任意处于 >=2 个不同 case 上被试过
                #   （全局稳健先验）才可外推。一个在单个训练 case 上验证 2 次的配方曾靠这一跳骑到
                #   每个复合测试 case 上、把曲线清零；one_peer 靠其多 case 的 'of' 证据保住这一跳
                #   （dev-10c 的制胜路径）。单锚点几何使按槽多样性不可能（II-13 是唯一可学的 os
                #   case），故该门是全局的，早于 case 追踪的账本保持旧行为。
                # M19 (dev-11): a POSITIVE verdict may only extrapolate when
                # the artifact has been exercised on >=2 distinct cases
                # ANYWHERE (global robustness prior). A recipe verified 2x on
                # one train case rode this hop onto every composite test case
                # and zeroed the curve; one_peer keeps the hop through its
                # multi-case 'of' evidence (the dev-10c winning path). The
                # single-anchor geometry makes PER-SLOT diversity impossible
                # (II-13 is the only learnable os case), so the gate is
                # global, and ledgers predating case tracking keep legacy
                # behavior.
                if _ledger_case_diversity(ledger) is None:
                    return True
                if (_ledger_case_diversity(ledger) or 0) >= 2:
                    return True
    passing = sum(1 for v in sub.values() if v is True)
    failing = any(v is False for v in sub.values())
    return passing >= BUCKET_TRUST_MIN_KINDS and not failing


# 【职责】交给生成的“逐 case”四元组 (bank, motif, 是否弃权, tier)。
# - 层级（operator 抬高标准：对比 fixed-best，弃权会流失配对样本）：
#   kind——对该 case 槽位有直接证据的技能（重放）；
#   bucket——无槽证据但存在广度均匀的桶级通才（M8 breadth）且 fallback_tier 开启：部署库里
#   自身最佳通用组织而非走冷；
#   cold——无可信项：空技能库 + None motif，与冷基线路径逐字节相等（abstained=True）。
# - mode="off" 复现 phase-2 行为（完整 bank、完整 motif）。
def deployment_view(
    bank: SkillBank,
    motif_stats: dict[str, dict] | None,
    bucket: str,
    *,
    kind: str | None = None,
    mode: str = "feature",
    fallback_tier: bool = False,
) -> tuple[SkillBank, dict[str, dict] | None, bool, str]:
    """The per-case (bank, motif, abstained, tier) handed to generation.

    Tiers (operator bar raise: vs fixed-best, abstention BLEEDS pairs):
    ``kind``   -- skills with direct evidence for the case's slot (replay);
    ``bucket`` -- no slot evidence, but broad-uniform bucket generalists
                  exist (M8 breadth) and ``fallback_tier`` is on: deploy the
                  bank's own best general organization instead of going cold
                  (parity with a strong fixed topology on uncovered cases);
    ``cold``   -- nothing trusted: EMPTY bank + None motif, byte-equal to
                  the cold baseline path (abstained=True).
    ``mode="off"`` reproduces phase-2 behavior (full bank, full motif).
    """
    if mode == "off" or len(bank) == 0:
        return bank, motif_stats, False, "off"
    trusted = [
        skill for skill in bank
        if not is_avoid_skill(skill) and skill_trusted_for(skill, bucket, kind)
    ]
    tier = "kind"
    if not trusted and fallback_tier:
        trusted = [
            skill for skill in bank
            if not is_avoid_skill(skill) and skill_trusted_for(skill, bucket, None)
        ]
        tier = "bucket"
    if not trusted:
        return SkillBank(), None, True, "cold"
    view = SkillBank(skills=[skill.model_copy(deep=True) for skill in trusted])
    # 中文：M14：逐技能的证据条件动作。直接槽证据通过的技能原样部署——PRESERVE 已验证的产物
    #   （dev-8 4 臂：无条件改写把 41.7% 的结构拖到 33.3%）。仅靠广度外推/旧桶语义可信的技能
    #   是在向无证据的领域迁移——MODIFY（为当前任务改写角色指令；突破下限的场景）。
    # M14: evidence-conditioned action, PER SKILL. A skill whose DIRECT slot
    # evidence passes is deployed verbatim -- PRESERVE the proven artifact
    # (dev-8 4-arm: unconditional rewriting dragged a 41.7% structure to
    # 33.3%). A skill trusted only by breadth extrapolation / legacy bucket
    # semantics is transferring into unevidenced territory -- MODIFY (rewrite
    # role instructions for the live task; the floor-cracking scenario).
    for skill in view:
        policy = skill.organization_policy
        if policy is None:
            continue
        ledger = policy.get(TRANSFER_EVIDENCE_KEY) or {}
        direct = (
            _slot_passes(
                ledger.get(f"{bucket}#{kind}"), ledger.get(f"__pool__:{bucket}")
            )
            if kind
            else None
        )
        policy["deploy_action"] = "preserve" if direct is True else "modify"
        # 中文：M20：浮现该桶训练期已验证的指令范例（若卡带有），让部署时的 Modify 改写锚定在
        #   “已验证”的风格上，而非从零重掷（dev-12b/13：每 8 个种子有 6-7 套不同指令，EM 随抽签
        #   而变）。M20b：仅槽位精确匹配——dev-16 测到标量槽范例锚定复合槽改写到一个稳定糟糕的点
        #   （方差塌缩，均值随之塌缩）；跨槽 case 自由改写。
        # M20: surface this bucket's train-verified instruction exemplar (if
        # the card carries one) so the deploy-time Modify rewrite is anchored
        # by a VERIFIED style instead of re-rolling from scratch (dev-12b/13:
        # 6-7 distinct instruction sets per 8 seeds; EM tracked the draw).
        # M20b: SLOT-exact only -- dev-16 measured a scalar-slot exemplar
        # anchoring a composite-slot rewrite onto a stably-bad point
        # (variance collapsed, mean collapsed with it). Cross-slot cases
        # rewrite freely.
        exemplars = policy.get("instruction_exemplars")
        if isinstance(exemplars, dict):
            ex = exemplars.get(bucket)
            if (
                isinstance(ex, dict)
                and isinstance(ex.get("steps"), list)
                and kind is not None
                and ex.get("slot") == kind
            ):
                policy["active_instruction_exemplar"] = [
                    str(s)[:300] for s in ex["steps"]
                ]
    return view, motif_view(motif_stats, bucket), False, tier


def namespace_motif_keys(keys: list[str], bucket: str) -> list[str]:
    return [f"{bucket}|{key}" for key in keys]


# 【职责】把按桶命名空间的 motif 统计投影回单个桶的原始键。
# - 特征门下丢弃非命名空间键（旧统计）：它们无桶来源，不能偏置其他桶。
def motif_view(
    motif_stats: dict[str, dict] | None,
    bucket: str,
) -> dict[str, dict] | None:
    """Project bucket-namespaced motif stats back to raw keys for one bucket.

    Non-namespaced keys (legacy stats) are dropped under the feature gate --
    they carry no bucket provenance, so they must not bias other buckets.
    """
    if not motif_stats:
        return motif_stats
    prefix = f"{bucket}|"
    out = {
        key[len(prefix):]: dict(value)
        for key, value in motif_stats.items()
        if key.startswith(prefix)
    }
    return out or None
