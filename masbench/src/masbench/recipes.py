"""M10: train-time VERIFIED recipe search (Reflexion/STaR-style).

The minister only distills one-shot runs; on hard train cases nothing
succeeds often enough to clear the trust bar (round-08 screens: II-13 had
chain 0/2, explore 1/1 -- correct abstention everywhere downstream, so the
bank can never carry anything). Train-time, the benchmark adapter exposes
the training signal (its scoring against the train case's expected output);
iterating proposals against it is ordinary learning. The stored artifact is
a PROCEDURE -- structure + per-step receiver instructions (M9 fields) -- and
never data values.

Generalizability contract (operator requirement): inputs are the task
STATEMENT, procedural feedback (per-step structure + which agents were
wrong), and the run's own LLM. Prompts contain no benchmark-specific
markers (tested). A leakage scan rejects recipes whose instructions embed
train-shard literals.

Borrowings: Reflexion (verbal feedback retry), STaR (keep only verified
traces), AWM (workflow induction), Voyager (skill = executable + use note).
"""
# ============================================================
# 【模块导读】M10 训练期 verified recipe 搜索。
# 这里让 LLM 先提出“通信结构 + 每步接收者该做什么”的过程配方，再用真实训练种子验证；
# 只有所有验证种子都通过的配方才会转成 SkillCard，避免把一次走运的结构写入技能库。
# ============================================================

from __future__ import annotations

import json
from typing import Any, Callable

from exp_graph.llm.base import LLMClient
from exp_graph.mas.schemas import SkillCard
from exp_graph.protocols.spec import ProtocolGraphSpec, ProtocolStepSpec

# 【职责】让 LLM 产出可执行 recipe 的提示词模板；运行时字符串保持英文，避免影响模型行为。
RECIPE_PROMPT = """You are designing a communication + computation procedure for {n_agents} agents that each privately hold one shard of the data. Design BOTH the message structure and what each step's receivers must do.

Task statement (placeholders like {{agent_id}}/{{input_shard}} stand for per-agent values):
---
{task_brief}
---
{feedback_block}
Constraints:
- At most {max_steps} steps; each step is a set of simultaneous src->dst messages; agent ids 0..{last_agent}; no self-loops.
- Every agent's information must be able to reach whoever produces the final answer.
- Per-step "instruction" tells the RECEIVING agents what to COMPUTE locally and what to FORWARD next (<= 200 chars; never include concrete data values).
- "selected_primary" = the agent id that holds the final answer; its last instruction must say how to ASSEMBLE the final answer (and every agent must end up submitting that same answer if the task asks for one shared answer).

Reply ONLY JSON:
{{"name": "short_snake_case", "selected_primary": <id>, "steps": [{{"edges": [[src,dst],...], "instruction": "..."}}, ...]}}"""

# 【职责】失败后给 LLM 的过程级反馈模板：说明结构、错的 agent、答案持有者状态。
FEEDBACK_TEMPLATE = """Previous attempt '{name}' FAILED verification. Procedural feedback:
- structure tried: {structure}
- agents with wrong final answers: {wrong_agents}
- the designated answer-holder was {holder_state}.
Fix the PROCEDURE (different structure and/or clearer per-step computation roles), do not just reword.
"""


# 【职责】把 LLM 的 JSON 回复解析成带 step instruction 的 ProtocolGraphSpec；坏格式返回 None。
def parse_recipe(
    text: str, *, n_agents: int, max_steps: int
) -> ProtocolGraphSpec | None:
    """Parse one recipe reply into an instruction-bearing spec (None on junk)."""
    raw = (text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        steps_raw = data.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            return None
        steps = []
        for item in steps_raw[:max_steps]:
            edges = [
                (int(s), int(d))
                for s, d in (item.get("edges") or [])
                if 0 <= int(s) < n_agents and 0 <= int(d) < n_agents and int(s) != int(d)
            ]
            if not edges:
                return None
            steps.append(
                ProtocolStepSpec(
                    transmissions=edges,
                    description=str(item.get("instruction", ""))[:120],
                    operator="recipe",
                    instruction=str(item.get("instruction", "")).strip()[:300] or None,
                )
            )
        selected = data.get("selected_primary")
        metadata = {
            "graph_type": "temporal_dag",
            "source": "recipe_search",
        }
        if selected is not None and 0 <= int(selected) < n_agents:
            metadata["selected_primary"] = int(selected)
        return ProtocolGraphSpec(
            name=str(data.get("name") or "recipe")[:60],
            n_agents=n_agents,
            steps=steps,
            metadata=metadata,
        )
    except Exception:
        return None


# 【职责】检查 recipe 指令是否泄漏训练分片里的具体数据值；泄漏则拒绝入库。
def leaks_shard_literals(spec: ProtocolGraphSpec, shards: list[Any]) -> bool:
    """True when any instruction embeds a concrete shard value (>=3 chars)."""
    blob = " ".join(
        (step.instruction or "") + " " + step.description for step in spec.steps
    ).lower()
    for shard in shards:
        items = shard if isinstance(shard, (list, tuple)) else [shard]
        for value in items:
            text = str(value).strip().lower()
            if len(text) >= 3 and text in blob:
                return True
    return False


# 【职责】循环“提出 recipe -> 执行验证 -> 用反馈修正”，返回验证通过的 spec 与诊断 trace。
def search_recipe(
    *,
    task_brief: str,
    n_agents: int,
    max_steps: int,
    shards: list[Any],
    llm_client: LLMClient,
    model_name: str,
    run_and_score: Callable[[ProtocolGraphSpec, int], tuple[float, dict[str, Any]]],
    verify_seeds: list[int],
    attempts: int = 4,
) -> tuple[ProtocolGraphSpec | None, list[dict[str, Any]]]:
    """Iterate propose -> execute -> verify; return (verified spec, trace).

    ``run_and_score(spec, seed)`` returns (exact_match_rate, procedural
    feedback dict with keys like wrong_agents/holder_state). A recipe is
    VERIFIED only when every verify seed passes (>= 0.99) -- one lucky run
    never deploys (M1 bar). The trace records every attempt for diagnostics.
    """
    feedback_block = ""
    trace: list[dict[str, Any]] = []
    last_agent = n_agents - 1
    for attempt in range(1, max(1, attempts) + 1):
        prompt = RECIPE_PROMPT.format(
            n_agents=n_agents, task_brief=task_brief[:1800],
            feedback_block=feedback_block, max_steps=max_steps,
            last_agent=last_agent,
        )
        try:
            response = llm_client.complete(prompt, model_name=model_name, temperature=0.4)
            spec = parse_recipe(
                getattr(response, "text", "") or "", n_agents=n_agents, max_steps=max_steps
            )
        except Exception:
            spec = None
        if spec is None:
            trace.append({"attempt": attempt, "status": "unparseable"})
            feedback_block = "\nYour previous reply was not valid JSON in the required shape. Follow the schema exactly.\n"
            continue
        if leaks_shard_literals(spec, shards):
            trace.append({"attempt": attempt, "status": "leaked_data", "name": spec.name})
            feedback_block = "\nYour previous attempt embedded concrete data values in instructions. Describe PROCEDURE only.\n"
            continue
        em, feedback = run_and_score(spec, verify_seeds[0])
        if em < 0.99:
            structure = "; ".join(
                f"{i}:" + ",".join(f"{s}->{d}" for s, d in st.transmissions)
                for i, st in enumerate(spec.steps)
            )
            feedback_block = "\n" + FEEDBACK_TEMPLATE.format(
                name=spec.name, structure=structure,
                wrong_agents=feedback.get("wrong_agents", "unknown"),
                holder_state=feedback.get("holder_state", "unknown"),
            )
            trace.append({"attempt": attempt, "status": "failed_seed0", "name": spec.name, "em": em})
            continue
        # 中文：seed-0 通过后，再用剩余验证种子确认（信任门 n>=2），防止一次走运就部署。
        # Seed-0 solved: confirm on the remaining verify seeds (trust bar n>=2).
        confirmations = [(em, feedback)]
        ok = True
        for seed in verify_seeds[1:]:
            em2, fb2 = run_and_score(spec, seed)
            confirmations.append((em2, fb2))
            if em2 < 0.99:
                ok = False
                break
        trace.append({
            "attempt": attempt, "status": "verified" if ok else "unstable",
            "name": spec.name, "ems": [round(e, 3) for e, _ in confirmations],
        })
        if ok:
            return spec, trace
        feedback_block = "\n" + FEEDBACK_TEMPLATE.format(
            name=spec.name, structure="(same as before)",
            wrong_agents=confirmations[-1][1].get("wrong_agents", "unknown"),
            holder_state="answer unstable across runs -- make per-step roles more explicit",
        )
    return None, trace


# 【职责】把验证通过的 recipe 封装成可部署且立即可信的技能卡。
def recipe_skill_card(
    spec: ProtocolGraphSpec,
    *,
    task_family: str,
    bucket: str,
    lossless_slot: str,
    n_agents: int,
    verify_count: int,
    source_case_id: str | None = None,
) -> SkillCard:
    """Wrap a verified recipe as a deployable, immediately-trusted skill."""
    topology = f"generated:{spec.name}"
    ledger_rows: dict = {"n": verify_count, "em_sum": float(verify_count)}
    # 中文：M19（dev-11）：验证种子只来自单个案例。记录来源后，trust 逻辑能把它放进
    # 直接匹配槽位，同时拒绝从单案例证据泛化到 shape-sibling/breadth 槽位。
    # M19 (dev-11): verification seeds are ONE case's evidence. Recording the
    # provenance lets trust decide the recipe's direct slot while refusing
    # shape-sibling/breadth extrapolation from a single-case card.
    if source_case_id is not None:
        ledger_rows["cases"] = [str(source_case_id)]
    return SkillCard(
        skill_id=f"{task_family}__recipe_{spec.name}__a{n_agents}",
        objective="balanced",
        task_family=task_family,
        # 中文：与 minister 卡保持 specificity 对齐（round-9 screen 里 recipe 卡 specificity 约 2，
        # 被 condition-keyed minister 卡 12 挤出 top-3，导致验证过的 recipe 没有部署）。
        # 同一条件形状下，让 LCB loss 决定顺序。
        # Specificity parity with minister cards (round-9 screen: recipe cards
        # at specificity ~2 were pushed out of the top-3 seeded candidates by
        # condition-keyed minister cards at 12; the verified recipe never
        # deployed). Same condition shape -> LCB loss decides the order.
        trigger={
            "task_family": task_family,
            "agent_counts": [n_agents],
            "condition_key": f"recipe::{bucket}#{lossless_slot}::a{n_agents}",
        },
        organization_policy={
            "planner_mode": "graph_generate",
            "topology_name": topology,
            "protocol_spec": spec.model_dump(mode="json"),
            "transfer_evidence": {
                bucket: dict(ledger_rows),
                f"{bucket}#{lossless_slot}": dict(ledger_rows),
            },
            "recipe_provenance": {
                "verified_seeds": verify_count,
                "source": "m10_recipe_search",
            },
        },
        expected_tradeoff={
            "mean_primary_loss": 0.0,
            "mean_rmse": 0.0,
            "active_evidence_count": verify_count,
            # 中文：M19a：单案例 provenance 会喂给检索侧悲观性，避免过度泛化。
            # M19a: single-case provenance feeds retrieval-side pessimism.
            "evidence_case_count": 1,
            "lesson": "verified procedure from train-time recipe search",
        },
        confidence={"seed_count": verify_count},
        tags=["mas", "emperor-skill", task_family, "recipe"],
    )
