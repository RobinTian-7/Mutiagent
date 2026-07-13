"""Silo-Bench behind the QueenBee temporal-DAG protocol engine.

``SiloProtocolAdapter`` lets ``exp_graph.runner.protocol.ProtocolRunner`` drive a
single :class:`~masbench.core.instance.BenchmarkInstance`. It reuses the six base
``TaskAdapter`` methods from :class:`BenchmarkTaskAdapter` (build/split/solve/
normalize/evaluate/format) and the generic finalize/step-metric/answer-holder
defaults from :class:`ProtocolTaskAdapter`; this module only adds the per-agent
belief lifecycle plus the answer/score hooks.

Belief model: every belief carries the agent's current candidate GLOBAL answer in
``structured_state={"task_name": "silo", "case_id": <id>, "answer": <value>}`` and
mirrors its canonical form in ``consensus_key`` (or ``"UNKNOWN"``).

Offline determinism: a single agent holding only one shard usually cannot know
the GLOBAL answer, so beliefs default to CANDIDATE / ``"UNKNOWN"``. For the small
set of associative-reduce cases (e.g. Global Max ``"I-01"`` -> ``max``) a shard's
local reduction is carried in ``structured_state.answer`` so neighbors can fold it
in deterministically, letting a topology whose holder reaches full coverage
converge to the correct answer without any LLM. General tasks (e.g. distributed
sort) have no offline solver: those beliefs stay ``"UNKNOWN"`` and the real merge
is the LLM's job in the online modes.
"""
# ============================================================
# 【模块导读】把 Silo-Bench 接到 QueenBee 时序通信 DAG 协议引擎之后。
# SiloProtocolAdapter 让 ProtocolRunner 驱动单个 BenchmarkInstance：复用基类六个
# TaskAdapter 方法与通用收尾/步指标/答案容器默认实现，只补每 agent 信念生命周期与
# 答案/评分钩子。信念模型：信念在 structured_state 带当前候选全局答案(task_name/
# case_id/answer)，并在 consensus_key 镜像其规范形(或 "UNKNOWN")。离线确定性：单
# agent 只持一分片通常不知全局答案，信念默认 CANDIDATE/"UNKNOWN"；仅对可结合归约案例
# (如 Global Max "I-01"->max)把分片本地归约放进 answer 供邻居确定性折叠，使覆盖全者
# 所在拓扑无需 LLM 即收敛；一般任务(如分布式排序)无离线解，合并交给在线 LLM。
# ============================================================

from __future__ import annotations

import json
from typing import Any, Callable

from exp_graph.agents.schemas import BeliefState, BeliefStatus
from exp_graph.mas.leakage_audit import assert_prompt_clean
from exp_graph.mas.schemas import InformationGoal
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter

from masbench.adapters.silo_scoring import silo_partial_score
from masbench.core.task_bridge import (
    BenchmarkTaskAdapter,
    canonical_answer,
    private_answer_key,
)
from masbench.core.task_view import task_ref

SILO_PROTOCOL_TASK_NAME = "silo"


# 【职责】给一个 Silo 全局答案评分：严格精确匹配 + 分级 partial 部分正确度。
# - primary_metric/exact_match 保持 1.0/0.0 的严格成功信号(供拓扑选择与进化用)；
#   partial 追加 [0,1] 的分级部分正确度(见 silo_scoring.silo_partial_score)。
# - 放在模块级，使 masbench 无需持有适配器实例也能由最终答案重算 partial；适配器方法委托到此。
def score_protocol_answer(answer: Any, global_task: dict[str, Any]) -> dict[str, Any]:
    """Score one Silo global answer: strict exact-match plus a graded ``partial``.

    ``primary_metric``/``exact_match`` stay the strict 1.0/0.0 success signal used
    by topology selection and evolution; ``partial`` adds the graded
    PARTIAL-CORRECTNESS value in [0, 1] (see ``silo_scoring.silo_partial_score``).
    Module-level so masbench can recompute ``partial`` from a final answer without
    holding a task-adapter instance; the adapter method delegates here.
    """
    if answer is None:
        return {"primary_metric": 0.0, "exact_match": False, "partial": 0.0}
    # 中文：ground truth 只从 private scoring payload 读取（模型上下文物理隔离）。
    # Ground truth is read only from the private scoring payload.
    ground_truth = private_answer_key(global_task)
    success = canonical_answer(answer) == ground_truth
    partial = silo_partial_score(
        answer, ground_truth, global_task.get("output_type", "scalar")
    )
    return {
        "primary_metric": 1.0 if success else 0.0,
        "exact_match": success,
        "partial": float(partial),
    }

# 中文：case_id -> 对一列扁平数字的归约器。与 masbench.llm.fake._REDUCERS 对应：只有离线
#   确定性合并能在分片+邻居答案上折叠的「可结合归约」才放这里，其余离线保持 UNKNOWN。
# case_id -> reducer over a flat list of numbers. Mirrors masbench.llm.fake._REDUCERS:
# only associative reductions that an offline deterministic merge can fold over a
# shard plus neighbor answers belong here. Everything else stays UNKNOWN offline.
_REDUCERS: dict[str, Callable[[list[float]], Any]] = {
    "I-01": max,  # Global Max
}


# 【职责】信念 JSON 形状片段（模板共享的语法说明；task_ref 为不可查表的任务摘要）。
def _belief_shape(task_ref_value: str, *, proposal_hint: str) -> str:
    return f"""{{
  "status": "candidate",
  "proposal": "{proposal_hint}",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "short",
  "open_questions": ["short"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "{SILO_PROTOCOL_TASK_NAME}",
    "task_ref": "{task_ref_value}",
    "answer": null
  }}
}}"""


# 【职责】sink 模式「初始信念」提示词模板（运行时 prompt）。
# - 角色设定：单一指定 sink 负责最终全局答案；其他 agent 的职责是让自己的分片信息
#   无损地流向 sink，而不是自己持有全局答案。
def format_sink_protocol_init_prompt(
    *,
    task_context: dict[str, Any],
    prompt_context: str,
    local_observation: dict[str, Any],
    task_ref: str,
) -> str:
    """Sink-mode init prompt: one designated sink forms the final answer."""
    return f"""You are one worker agent in a relay-style multi-agent system.
A SINGLE designated sink agent is responsible for forming the final GLOBAL
answer for this task. You are probably NOT that sink.

Your duties this round:
- Extract everything your own private shard contributes to the task.
- Package it losslessly so it can be relayed toward the designated sink.
- You are NOT required to know the global answer yourself; a precise partial
  contribution is a success for a non-sink agent.

Design of this system: information flows toward one aggregation point. Do not
assume every agent will end up with the final answer; only the designated sink
must. Never fabricate data you did not see.

Rules: output exactly one JSON object (a belief_state) and nothing outside it
(no markdown fences, no prose). Put your best current GLOBAL answer in
structured_state.answer ONLY if your shard alone determines it; otherwise use
null and set consensus_key to "UNKNOWN" while carrying your partial
contribution in the proposal.

Self-check before answering: (1) did you use only your own shard, (2) is your
contribution lossless and forwardable, (3) did you avoid claiming a global
answer you cannot justify?

TASK_FOR_AGENT:
{prompt_context}
Return belief_state:
{_belief_shape(task_ref, proposal_hint="lossless summary of what my shard contributes")}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

LOCAL_OBSERVATION_JSON:
{json.dumps(local_observation, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{{}}

INBOX_JSON:
[]
"""


# 【职责】all_agents 模式「初始信念」提示词模板（运行时 prompt）。
# - 角色设定：每个 agent 最终都必须独立持有并提交正确的全局答案；不存在
#   替你持有答案的 leader。
def format_all_agents_protocol_init_prompt(
    *,
    task_context: dict[str, Any],
    prompt_context: str,
    local_observation: dict[str, Any],
    task_ref: str,
) -> str:
    """All-agents init prompt: EVERY agent must end with the full answer."""
    return f"""You are one agent in a fully-accountable multi-agent system.
EVERY agent, including you, must END this task independently holding the
complete, correct GLOBAL answer. There is no leader who will hold it for you;
you will each submit your own final answer and each submission is graded.

Your duties this round:
- Work out everything your private shard tells you.
- Prepare it for broadcast: peers must be able to absorb your information and
  you must be ready to absorb theirs in later rounds.
- Track what you are still missing; you cannot finish until you have absorbed
  information originating from every other agent.

Design of this system: information must spread to ALL agents, not converge on
one point. Expect to keep re-sharing newly learned information until everyone
has everything. Never fabricate data you did not see.

Rules: output exactly one JSON object (a belief_state) and nothing outside it
(no markdown fences, no prose). Put your best current GLOBAL answer in
structured_state.answer ONLY if your shard alone determines it; otherwise use
null, set consensus_key to "UNKNOWN", and list what you still need from other
agents in open_questions.

Self-check before answering: (1) could another agent reconstruct your shard's
contribution from your message, (2) do you know which agents' information you
still lack, (3) did you avoid assuming someone else will finish for you?

TASK_FOR_AGENT:
{prompt_context}
Return belief_state:
{_belief_shape(task_ref, proposal_hint="my shard's contribution + what I still need from others")}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

LOCAL_OBSERVATION_JSON:
{json.dumps(local_observation, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{{}}

INBOX_JSON:
[]
"""


# 【职责】sink 模式「合并」提示词模板（运行时 prompt）。
# - 接收节点无损合并并继续向 sink 转发；只有指定 sink 负责形成最终全局答案。
def format_sink_protocol_merge_prompt(
    *,
    merge_mode: str,
    task_context: dict[str, Any],
    prompt_context: str,
    own_answer: Any,
    inbox_answers: list[Any],
    verified_answer: Any,
    task_ref: str,
) -> str:
    """Sink-mode merge prompt: merge losslessly, forward toward the sink."""
    return f"""You are a relay agent in a sink-oriented multi-agent system.
Only the designated sink agent is responsible for forming the FINAL global
answer. Your job as a receiver is to merge incoming partial information
LOSSLESSLY with your own and pass the combined artifact further toward the
sink. If you happen to be the sink, form the best global answer you can from
everything that has reached you.

Mode={merge_mode}. Merge YOUR_ANSWER_JSON with the incoming artifacts in
INBOX_ANSWERS_JSON. Preserve every distinct contribution: dropping or double
counting a shard's information corrupts the sink's final answer. Do not invent
data; only combine what is given plus your own shard. If a deterministic check
is provided in VERIFIED_ANSWER_JSON and is not null, prefer it.

Rules: output exactly one JSON object (a belief_state) and nothing outside it.
Put the merged answer (or merged partial artifact) in structured_state.answer
using its natural JSON type. Set consensus_key to the same value in compact
canonical form, or "UNKNOWN" if the global answer is still not determined at
your position. Non-sink agents are NOT required to reach the final answer.

Self-check before answering: (1) is every incoming contribution reflected
exactly once, (2) is the artifact still forwardable toward the sink, (3) did
you avoid inventing unseen data?

TASK_FOR_AGENT:
{prompt_context}
Return belief_state:
{_belief_shape(task_ref, proposal_hint="merged artifact now covering these contributions")}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

YOUR_ANSWER_JSON:
{json.dumps(own_answer, ensure_ascii=True)}

INBOX_ANSWERS_JSON:
{json.dumps(inbox_answers, ensure_ascii=True)}

VERIFIED_ANSWER_JSON:
{json.dumps(verified_answer, ensure_ascii=True)}
"""


# 【职责】all_agents 模式「合并」提示词模板（运行时 prompt）。
# - 每个 agent 都必须最终持有正确答案：持续传播新信息，不得只汇聚到 leader，
#   最后每个 agent 独立提交；selected_primary 不是唯一答案持有者。
def format_all_agents_protocol_merge_prompt(
    *,
    merge_mode: str,
    task_context: dict[str, Any],
    prompt_context: str,
    own_answer: Any,
    inbox_answers: list[Any],
    verified_answer: Any,
    task_ref: str,
) -> str:
    """All-agents merge prompt: absorb, rebroadcast, everyone must finish."""
    return f"""You are one agent in a fully-accountable multi-agent system.
EVERY agent must END holding the complete, correct GLOBAL answer and will
submit it independently. Merging is not enough: whatever NEW information you
learn this round must keep spreading in later rounds until every agent has
everything. Do not treat any single agent as the final answer holder.

Mode={merge_mode}. Absorb the incoming artifacts in INBOX_ANSWERS_JSON into
YOUR_ANSWER_JSON. Keep the union of all information you have seen so far and
make your outgoing state maximally informative for peers who have not seen
what you have. Do not invent data; only combine what is given plus your own
shard. If a deterministic check is provided in VERIFIED_ANSWER_JSON and is not
null, prefer it.

Rules: output exactly one JSON object (a belief_state) and nothing outside it.
Put your current best GLOBAL answer in structured_state.answer using its
natural JSON type; if you can now determine the full global answer, commit to
it. Set consensus_key to the same value in compact canonical form, or
"UNKNOWN" only if information from some agents has still never reached you.

Self-check before answering: (1) does your state now include every
contribution you have ever received, (2) would a peer reading your message
learn everything you know, (3) are you ready to submit this answer yourself
without relying on any other agent?

TASK_FOR_AGENT:
{prompt_context}
Return belief_state:
{_belief_shape(task_ref, proposal_hint="union of everything I have absorbed so far")}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

YOUR_ANSWER_JSON:
{json.dumps(own_answer, ensure_ascii=True)}

INBOX_ANSWERS_JSON:
{json.dumps(inbox_answers, ensure_ascii=True)}

VERIFIED_ANSWER_JSON:
{json.dumps(verified_answer, ensure_ascii=True)}
"""


# 【职责】尽力把值转为 float，拒绝布尔与 UNKNOWN/NONE/NULL 等哨兵(返回 None)。
def _as_number(value: Any) -> float | None:
    """Best-effort numeric coercion that rejects booleans and sentinels."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() in {"UNKNOWN", "NONE", "NULL"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_number(value: float) -> Any:
    """Render an int when the float is integral so answers stay clean (9 not 9.0)."""
    return int(value) if float(value).is_integer() else value


# 【职责】从 silo 的 structured_state 字典里取候选答案(非 silo 或无则返回 None)。
def _answer_from_structured_state(value: Any) -> Any:
    """Pull the candidate answer out of a silo structured_state dict, if present."""
    if not isinstance(value, dict):
        return None
    if value.get("task_name") != SILO_PROTOCOL_TASK_NAME:
        return None
    return value.get("answer")


# 【职责】从邻居 outbox 消息里恢复其候选答案(先看 structured_payload，再退回 consensus_key)。
def _answer_from_message(message: OutboxMessage) -> Any:
    """Recover a neighbor's candidate answer from its outbox message."""
    answer = _answer_from_structured_state(message.structured_payload)
    if answer is not None:
        return answer
    key = message.consensus_key
    if key is None or canonical_answer(key) == "UNKNOWN":
        return None
    # 中文：consensus_key 是规范化 JSON，解析回真实值好让归约看到真数。
    # consensus_key is canonical JSON; parse it back so reduce sees real values.
    try:
        return json.loads(key)
    except (TypeError, ValueError):
        return key


# 【职责】把单个 Silo-Bench BenchmarkInstance 经 ProtocolRunner 驱动起来。
# - __init__ 与六个基础 TaskAdapter 方法继承自 BenchmarkTaskAdapter，通用收尾/步指标/
#   答案容器默认实现来自 ProtocolTaskAdapter；本类只定义信念生命周期与答案/评分钩子。
class SiloProtocolAdapter(BenchmarkTaskAdapter, ProtocolTaskAdapter):
    """Drive one Silo-Bench BenchmarkInstance through ProtocolRunner.

    ``__init__(self, instance)`` is inherited from :class:`BenchmarkTaskAdapter`;
    the six base TaskAdapter methods come from there too, and the generic
    finalize/step-metric/answer-holder defaults come from
    :class:`ProtocolTaskAdapter`. Only the belief lifecycle + answer/score hooks
    are defined here.
    """

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _case_id(self) -> str:
        return str(self.instance.case_id)

    # 【职责】模型可见的任务标识：case_id 的不可逆摘要（提示词/信念模板用它，
    #   使模型上下文不携带可直接查表的 case_id）。
    def _task_ref(self) -> str:
        return task_ref(self._case_id())

    def _reducer(self) -> Callable[[list[float]], Any] | None:
        return _REDUCERS.get(self._case_id())

    # 【职责】为确定性离线路径在本地归约单个分片(无归约器或非列表则返回 None)。
    def _local_reduce(self, shard: Any) -> Any:
        """Reduce a single shard locally for the deterministic offline path."""
        reducer = self._reducer()
        if reducer is None or not isinstance(shard, list):
            return None
        numbers = [n for n in (_as_number(v) for v in shard) if n is not None]
        if not numbers:
            return None
        return _normalize_number(float(reducer(numbers)))

    def _structured_state(self, answer: Any) -> dict[str, Any]:
        return {
            "task_name": SILO_PROTOCOL_TASK_NAME,
            "case_id": self._case_id(),
            "answer": answer,
        }

    # 【职责】由一个答案构造 BeliefState：答案非空则规范化为 consensus_key，否则 "UNKNOWN"。
    def _belief_from_answer(
        self,
        answer: Any,
        *,
        status: BeliefStatus,
        proposal: str,
        open_questions: list[str] | None = None,
        uncertainty: str = "",
        support: list[str] | None = None,
        private_notes: str = "silo protocol belief",
    ) -> BeliefState:
        key = canonical_answer(answer) if answer is not None else "UNKNOWN"
        return BeliefState(
            status=status,
            proposal=proposal,
            consensus_key=key,
            support=support if support is not None else [],
            uncertainty=uncertainty,
            open_questions=open_questions if open_questions is not None else [],
            private_notes=private_notes,
            structured_state=self._structured_state(answer),
        )

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: per-agent belief lifecycle
    # ------------------------------------------------------------------ #
    # 【职责】为一个 agent 构造初始信念：能本地确定性求全解则 FINAL，否则只作 CANDIDATE。
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState:
        agent_id = int(local_observation["agent_id"])
        n_agents = int(local_observation["n_agents"])
        shard = local_observation.get("input_shard")
        local_answer = self._local_reduce(shard)

        # 中文：有确定性本地求解器的独立 agent 能算出完整的 FINAL 答案；否则只持 CANDIDATE、
        #   绝不声称已知全局答案：consensus_key 保持 UNKNOWN，而 structured_state.answer
        #   携带本分片的局部贡献供邻居归约。
        # A lone agent with a deterministic local solver can compute the full,
        # FINAL answer. Otherwise we hold a CANDIDATE and never claim to KNOW the
        # global answer: consensus_key stays UNKNOWN, while structured_state.answer
        # carries the shard's local contribution so neighbors can reduce it.
        if n_agents == 1 and local_answer is not None:
            return self._belief_from_answer(
                local_answer,
                status=BeliefStatus.FINAL,
                proposal=f"Global answer is {local_answer}.",
                private_notes="silo single-agent deterministic local solve",
            )

        if local_answer is not None:
            belief = self._belief_from_answer(
                local_answer,
                status=BeliefStatus.CANDIDATE,
                proposal=(
                    f"Agent {agent_id} local reduction is {local_answer}; "
                    "other shards may change the global answer."
                ),
                uncertainty="Need contributions from the remaining agents.",
                open_questions=["Share your shard's contribution."],
                support=[f"agent {agent_id} local reduction={local_answer}"],
                private_notes="silo local reduction (partial)",
            )
            # 中文：为邻居携带这份局部贡献，但尚不声称已知全局答案。
            # Carry the partial contribution for neighbors, but do not yet claim a
            # known GLOBAL answer.
            return belief.model_copy(update={"consensus_key": "UNKNOWN"})

        return self._belief_from_answer(
            None,
            status=BeliefStatus.CANDIDATE,
            proposal=(
                f"Agent {agent_id} holds a private shard; the global answer is "
                "not yet known."
            ),
            uncertainty="Need information from other agents for the global answer.",
            open_questions=["What do other agents' shards contribute?"],
            support=[f"agent {agent_id} local shard only"],
            private_notes="silo local shard only",
        )

    # 【职责】确定性离线合并：把自身候选与 inbox 邻居答案按案例的归约器折叠成新信念。
    # - 无归约器的任务不臆造答案，只保留已携带的候选贡献，真正合并留给 LLM 模式。
    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState:
        reducer = self._reducer()
        if reducer is None:
            # 中文：此任务无离线求解器：真正的合并是 LLM 的活。保留已携带的候选贡献，
            #   绝不凭空臆造。
            # No offline solver for this task: the real merge is the LLM's job.
            # Preserve any candidate contribution already carried; never invent one.
            own = _answer_from_structured_state(old_belief_state.structured_state)
            return self._belief_from_answer(
                None,
                status=BeliefStatus.CANDIDATE,
                proposal="No deterministic offline merge for this task.",
                uncertainty="Use an LLM merge mode to combine neighbor answers.",
                open_questions=["Combine neighbor answers via the LLM."],
                support=(
                    [f"carried local contribution={own}"] if own is not None else []
                ),
                private_notes="silo non-reduce merge (offline UNKNOWN)",
            ).model_copy(
                update={"structured_state": self._structured_state(own)}
            )

        numbers: list[float] = []
        own = _answer_from_structured_state(old_belief_state.structured_state)
        own_num = _as_number(own)
        if own_num is not None:
            numbers.append(own_num)
        for message in inbox:
            message_num = _as_number(_answer_from_message(message))
            if message_num is not None:
                numbers.append(message_num)

        if not numbers:
            return self._belief_from_answer(
                None,
                status=BeliefStatus.CANDIDATE,
                proposal="No candidate contributions to reduce yet.",
                uncertainty="Need at least one shard contribution.",
                open_questions=["Share your shard's contribution."],
                private_notes="silo reduce merge (empty)",
            )

        reduced = _normalize_number(float(reducer(numbers)))
        return self._belief_from_answer(
            reduced,
            status=BeliefStatus.CANDIDATE,
            proposal=f"Reduced answer across known contributions is {reduced}.",
            uncertainty="Unmerged shards could still change the answer.",
            open_questions=["Share any further shard contributions."],
            support=[f"reduced {len(numbers)} visible contributions -> {reduced}"],
            private_notes="silo deterministic reduce over shard + neighbor answers",
        )

    # 【职责】按信息目标分派「初始信念」提示词：sink 与 all_agents 各用独立模板。
    # - 每个渲染出的提示词都过泄漏审计（禁止答案/最优拓扑/具名拓扑构造 token）。
    def format_protocol_init_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        if self.information_goal == "all_agents":
            prompt = format_all_agents_protocol_init_prompt(
                task_context=self.format_adjudication_context(global_task),
                prompt_context=self.format_task_prompt_context(
                    global_task, local_observation
                ),
                local_observation=local_observation,
                task_ref=self._task_ref(),
            )
        else:
            prompt = format_sink_protocol_init_prompt(
                task_context=self.format_adjudication_context(global_task),
                prompt_context=self.format_task_prompt_context(
                    global_task, local_observation
                ),
                local_observation=local_observation,
                task_ref=self._task_ref(),
            )
        return assert_prompt_clean(prompt, context="silo init prompt")

    def format_python_communication_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        prompt = super().format_python_communication_prompt(
            global_task=global_task,
            local_observation=local_observation,
        )
        return assert_prompt_clean(
            prompt,
            context="silo PythonGen v2 communication prompt",
        )

    def format_python_submit_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        prompt = super().format_python_submit_prompt(
            global_task=global_task,
            local_observation=local_observation,
        )
        return assert_prompt_clean(
            prompt,
            context="silo PythonGen v2 submit prompt",
        )

    # 【职责】按信息目标分派「合并」提示词：sink 与 all_agents 各用独立模板。
    def format_protocol_merge_prompt(
        self,
        *,
        merge_mode: str,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        deterministic_belief: BeliefState | None = None,
    ) -> str:
        task_context = self.format_adjudication_context(global_task)
        own_answer = _answer_from_structured_state(old_belief_state.structured_state)
        inbox_answers = [_answer_from_message(message) for message in inbox]
        verified_answer = (
            _answer_from_structured_state(deterministic_belief.structured_state)
            if deterministic_belief is not None
            else None
        )
        formatter = (
            format_all_agents_protocol_merge_prompt
            if self.information_goal == "all_agents"
            else format_sink_protocol_merge_prompt
        )
        prompt = formatter(
            merge_mode=merge_mode,
            task_context=task_context,
            prompt_context=self.format_task_prompt_context(
                global_task, local_observation
            ),
            own_answer=own_answer,
            inbox_answers=inbox_answers,
            verified_answer=verified_answer,
            task_ref=self._task_ref(),
        )
        return assert_prompt_clean(prompt, context="silo merge prompt")

    # 【职责】校验/规范化 LLM 产出的初始信念：抽答案、判覆盖，落到统一的信念形态。
    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState:
        n_agents = int(local_observation["n_agents"])
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is None:
            answer = self._answer_from_consensus_key(belief_state.consensus_key)
        # 中文：单 agent 覆盖整个任务；否则新鲜的分片信念只能是 candidate。
        # A single agent covers the whole task; otherwise a fresh shard belief is
        # only a candidate.
        all_covered = n_agents == 1
        return self._finalize_validated_belief(
            answer,
            all_covered=all_covered,
            llm_belief=belief_state,
        )

    # 【职责】校验/规范化每轮的信念：优先取 structured_state 答案，缺则退 consensus_key
    #   再退 transport 信念，最后落到统一形态。
    def validate_protocol_belief_state(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> BeliefState:
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is None:
            answer = self._answer_from_consensus_key(belief_state.consensus_key)
        if answer is None and transport_belief_state is not None:
            answer = _answer_from_structured_state(
                transport_belief_state.structured_state
            )
            if answer is None:
                answer = self._answer_from_consensus_key(
                    transport_belief_state.consensus_key
                )
        all_covered = n_agents == 1
        return self._finalize_validated_belief(
            answer,
            all_covered=all_covered,
            llm_belief=belief_state,
        )

    # 【职责】把 LLM 的措辞与经校验(确定性)的答案合成一个信念:留文字、信答案。
    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState:
        # 中文：保留 LLM 的措辞，但信任经校验(确定性)的答案。
        # Keep the LLM's wording but trust the verified (deterministic) answer.
        return BeliefState(
            status=verified_belief_state.status,
            proposal=llm_belief_state.proposal or verified_belief_state.proposal,
            consensus_key=verified_belief_state.consensus_key,
            support=llm_belief_state.support or verified_belief_state.support,
            uncertainty=(
                llm_belief_state.uncertainty
                if llm_belief_state.uncertainty
                else verified_belief_state.uncertainty
            ),
            open_questions=(
                []
                if verified_belief_state.status == BeliefStatus.FINAL
                else (
                    llm_belief_state.open_questions
                    or verified_belief_state.open_questions
                )
            ),
            private_notes=llm_belief_state.private_notes,
            confidence=llm_belief_state.confidence,
            structured_state=verified_belief_state.structured_state,
        )

    # 【职责】构造候选探针评估任务(D1)：直接用本 Silo 实例自身的任务。
    # - 不同于 CF 每个种子随机造数组；Silo 实例固定，探针复用同一任务，仅由 seed 变执行。
    def build_probe_global_task(
        self, *, seed: int = 0, runtime: Any = None, request: Any = None
    ) -> dict:
        """Candidate probe-eval task (D1): run the candidate on THIS Silo instance.

        Unlike CF (which generates a fresh random array per probe seed), Silo
        instances are fixed, so every probe uses the instance's own task; the
        ProtocolRunner still varies execution by ``seed``.
        """
        return self.build_global_task()

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: answer extraction / scoring / metrics
    # ------------------------------------------------------------------ #
    # 【职责】从信念抽取答案：优先 structured_state，缺则从 consensus_key 反解。
    def extract_protocol_answer(self, belief_state: BeliefState) -> Any:
        answer = _answer_from_structured_state(belief_state.structured_state)
        if answer is not None:
            return answer
        return self._answer_from_consensus_key(belief_state.consensus_key)

    def protocol_answer_key(self, answer: Any) -> str:
        return canonical_answer(answer)

    # 【职责】适配器的答案评分入口，委托到模块级 score_protocol_answer。
    def score_protocol_answer(
        self, answer: Any, global_task: dict[str, Any]
    ) -> dict[str, Any]:
        # 中文：严格精确匹配驱动 primary_metric/exact_match(不变)；分级部分正确度随行放在 partial。
        # Strict exact-match drives primary_metric/exact_match (unchanged); the
        # graded PARTIAL-CORRECTNESS value rides alongside in ``partial``.
        return score_protocol_answer(answer, global_task)

    # 【职责】计算单 agent 的指标(coverage_ratio/primary_metric/exact_match)。
    def compute_protocol_agent_metrics(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> dict[str, Any]:
        answer = self.extract_protocol_answer(belief_state)
        correct = (
            answer is not None
            and canonical_answer(answer) == private_answer_key(global_task)
        )
        # 中文：诚实的覆盖度代理：只有当该信念等于 ground truth 才算反映了完整答案；
        #   在此之前它只携带严格意义上的部分信息。
        # Honest coverage proxy: this belief reflects the full answer only once it
        # equals the ground truth; until then it carries strictly partial info.
        return {
            "coverage_ratio": 1.0 if correct else 0.0,
            "primary_metric": 1.0 if correct else 0.0,
            "exact_match": correct,
        }

    # ------------------------------------------------------------------ #
    # Internal validation helpers
    # ------------------------------------------------------------------ #
    # 【职责】从 consensus_key 反解答案：UNKNOWN/空返回 None，规范 JSON 则解析回真实值。
    def _answer_from_consensus_key(self, key: str | None) -> Any:
        if key is None or canonical_answer(key) == "UNKNOWN":
            return None
        try:
            return json.loads(key)
        except (TypeError, ValueError):
            return key

    # 【职责】把 LLM 答案归一化到 consensus_key/structured_state/status 三处。
    # - 容错：无法解析/缺失的答案坍缩为合法的 UNKNOWN candidate 而非抛错，使运行器不会因
    #   一条乱序 LLM 回复而崩(需要时由上游确定性修复兜底)。
    def _finalize_validated_belief(
        self,
        answer: Any,
        *,
        all_covered: bool,
        llm_belief: BeliefState,
    ) -> BeliefState:
        """Normalize an LLM answer onto consensus_key/structured_state/status.

        Tolerant: an unparseable/absent answer collapses to a valid UNKNOWN
        candidate rather than raising, so the runner never crashes on a stray LLM
        reply (it falls back through deterministic repair upstream as needed).
        """
        key = canonical_answer(answer) if answer is not None else "UNKNOWN"
        normalized_answer = answer if key != "UNKNOWN" else None
        status = BeliefStatus.FINAL if all_covered else BeliefStatus.CANDIDATE
        return llm_belief.model_copy(
            update={
                "status": status,
                "consensus_key": key,
                "structured_state": self._structured_state(normalized_answer),
            }
        )
