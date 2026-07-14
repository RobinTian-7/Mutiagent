"""Engine bridge: run one BenchmarkInstance through the exp_graph SynchronousRunner."""
# ============================================================
# 【模块导读】引擎桥：把一个 BenchmarkInstance 跑通 exp_graph 运行器并评分。
# 这是 masbench 与 exp_graph 引擎之间的核心桥接层：构建被超时/重试包装的 LLM 客户端，
# 按 cfg.use_planner 分派到 planner+ProtocolRunner 或 planner-OFF 的 SynchronousRunner，
# 并对结果做统一的(分段/整体)评分与消息/调用/token 计量。
# ============================================================

from __future__ import annotations

import json
import os
import time
from math import ceil
from pathlib import Path
from typing import Any

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.configs import ExperimentConfig
from exp_graph.llm.base import LLMClient
from exp_graph.llm.factory import WALLCLOCK_TIMEOUT_ENV, create_llm_client
from exp_graph.mas.graph_generation import GraphGenerationError, plan_free_graph
from exp_graph.mas.information_flow import (
    coverage_by_agent,
    propagate_knowledge,
)
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.phase_program_generation import (
    PhaseProgramGenerationError,
    plan_phase_program,
)
from exp_graph.mas.python_code_generation import (
    PythonCodePlanningResult,
    PythonGenerationError,
    plan_and_execute_python,
)
from exp_graph.mas.python_code import (
    MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION,
    python_source_sha256,
)
from exp_graph.mas.schemas import (
    MASRuntimeConfig,
    ObjectiveSpec,
    PlannerRequest,
    RoleLLMConfig,
    RoleLLMProfiles,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner import SynchronousRunner
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig

from masbench.adapters.silo_protocol import (
    SiloProtocolAdapter,
    score_protocol_answer,
)
from masbench.adapters.silo_paper_metrics import (
    evaluate_paper_submissions,
    paper_communication_density,
    paper_token_consumption,
)
from masbench.adapters.silo_scoring import silo_partial_score
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.final_submissions import (
    FinalSubmissionBatch,
    run_final_submission_barrier,
)
from masbench.llm.retry import RetryLLMClient
from masbench.core.task_bridge import (
    BenchmarkTaskAdapter,
    canonical_answer,
    private_answer_key,
    private_expected_outputs,
)
from masbench.llm.fake import BenchmarkFakeLLMClient

# 中文：clean GraphGen 的技能 provenance 白名单：只有 LLM 新生成的结构与同模式验证过的
#   技能重放可参与检索/入库；缺 provenance 的旧卡视为 contaminated。
# Provenance allowlist for clean GraphGen retrieval/admission.
CLEAN_GRAPHGEN_PROVENANCE = ("llm_generated", "skill_replay")
# Restricted programs have their own provenance namespace. A replay is accepted
# only after the planner confirms that the stored spec contains phase_program_v1.
CLEAN_PROGRAM_PROVENANCE = ("program_generated", "skill_replay")
CLEAN_PYTHON_PROVENANCE = ("llm_generated_python", "skill_replay")


# 【职责】为一个实例选择协议适配器：jssp 用 JSSPProtocolAdapter，默认走 SiloProtocolAdapter。
# - 延迟 import，使纯 silo 路径与改动前逐字节一致。
# - information_goal 决定适配器使用哪套提示词模板（sink / all_agents）。
def _protocol_adapter(instance: BenchmarkInstance, *, information_goal: str = "sink"):
    """Protocol adapter for one instance: JSSP instances get the JSSP adapter.

    Default stays :class:`SiloProtocolAdapter` (silo behavior unchanged); only
    ``benchmark == "jssp"`` routes to :class:`JSSPProtocolAdapter`. Imported
    lazily so the silo-only path is byte-identical to before.
    """
    if instance.benchmark == "jssp":
        from masbench.adapters.jssp_protocol import JSSPProtocolAdapter

        return JSSPProtocolAdapter(instance, information_goal=information_goal)
    return SiloProtocolAdapter(instance, information_goal=information_goal)


# 【职责】按 RunConfig 构造 LLM 客户端；fake 直接返回，真实 provider 加超时+重试包装。
# - 设置全局 wall-clock 超时环境变量，使引擎内部自建的客户端也一并受超时保护。
# - 用 RetryLLMClient 在超时之外再套一层有界的瞬时连接重试。
def _build_llm_client(cfg: RunConfig) -> LLMClient:
    if cfg.llm_provider == "fake":
        # 中文：fake 客户端瞬时且确定性，无需超时保护。
        # The fake client is instant and deterministic; no timeout guard needed.
        return BenchmarkFakeLLMClient()
    # 中文：让硬性 wall-clock 超时保护变成全局的。引擎内部许多点会用 create_llm_client
    #   自建客户端(角色客户端、图生成候选评估器、insight 大臣、ProtocolRunner 兜底)；设置
    #   该环境变量能让这些也受保护，而不仅是这里穿进去的客户端。否则某个未包装的内部客户端
    #   一旦卡住整个运行就会冻结(这正是 evolved/graphgen「无进展」卡死的真正根因)。
    # Make the hard wall-clock guard UNIVERSAL. Engine-internal sites build their
    # OWN clients via create_llm_client (role clients, the graph-generation
    # candidate evaluator, the insight minister, the ProtocolRunner fallback);
    # setting the env ensures those are guarded too -- not only the client we
    # thread in here. Without it, a hung call on an unwrapped internal client
    # freezes the whole run (this was the real root cause of the evolved/graphgen
    # "no progress" stall).
    os.environ[WALLCLOCK_TIMEOUT_ENV] = str(cfg.request_timeout)
    # 中文：在 wall-clock 保护之外再做有界的瞬时连接重试：每次尝试都有自己的超时预算，
    #   单次网络抖动不再能拖垮整个 verify/bench 评估池(round-3C 曾因一个 APIConnectionError
    #   在 32/72 次评估处崩溃)。attempts=5、基础 5s 线性退避可扛住约 75s 的中断(phase-3
    #   dev-5：一串多次抖动击穿了旧的 3x2s 预算，通过被冻结的评估池把 refine 运行搞崩)。
    # Bounded transient-connection retry OUTSIDE the wall-clock guard: each
    # attempt gets its own timeout budget, and a single network blip can no
    # longer kill a whole verify/bench eval pool (round-3C crashed at 32/72
    # eval runs on one APIConnectionError). attempts=5/base 5s linear backoff
    # rides out ~75s outages (phase-3 dev-5: a multi-blip burst beat the old
    # 3x2s budget and crashed the refine run through the frozen eval pool).
    timeout_attempts = max(1, int(getattr(cfg, "llm_timeout_attempts", 2)))
    return RetryLLMClient(
        create_llm_client(
            cfg.llm_provider,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
            thinking_enabled=cfg.thinking_enabled,
            timeout_s=cfg.request_timeout,
        ),
        attempts=max(5, timeout_attempts),
        timeout_attempts=timeout_attempts,
        base_delay=5.0,
    )


# 【职责】估算 agent 间消息数的结构上界(累加每轮拓扑的 fan-in 汇入边数)。
# - 只数拓扑暴露的边，是上界：运行器会跳过投递邻居为 None 的 outbox。
def _count_messages(result) -> int:
    """Structural upper bound on inter-agent messages.

    Sums each round's topology fan-in (``round_logs[*].neighbors``). This counts
    the edges the topology exposes, which is an upper bound: the runner skips
    delivering a neighbor's ``None`` outbox. Exact per-delivery counts arrive with
    the generic protocol runner in Plan 2.
    """
    total = 0
    for log in result.round_logs:
        total += sum(len(neighbors) for neighbors in log.neighbors.values())
    return total


# 【职责】在 masbench 侧计算最终答案的分级 partial 部分正确度([0,1])。
# - exp_graph 不动：success/精确匹配仍来自其严格评分，这里只填 ScoreResult.partial。
# - final_answer 可为实时值或规范化键字符串；silo_partial_score 两者都能强制转换。
def _partial_score(final_answer: Any, global_task: dict) -> float:
    """Graded PARTIAL-CORRECTNESS for a final answer, computed in masbench.

    exp_graph stays untouched: we recompute the [0, 1] partial signal here from
    the run's final answer + the instance ground truth carried in ``global_task``.
    ``success``/exact-match keep coming from exp_graph's strict scoring; this only
    fills ``ScoreResult.partial`` with the graded value. ``final_answer`` may be a
    live value or a canonical-key string; ``silo_partial_score`` coerces either.
    """
    # 中文：按 benchmark 路由评分：silo 打分器对 JSSP 调度无意义(真实 LLM 冒烟：一个合法的
    #   makespan-7 调度经硬编码 silo 路径竟得 partial 0.0)。默认仍走 silo，逐字节一致。
    # Benchmark-routed scoring: the silo scorer is meaningless for a JSSP
    # schedule (real-LLM smoke: a VALID makespan-7 schedule scored partial 0.0
    # through the hardwired silo path). Default stays silo, byte-identical.
    if global_task.get("benchmark") == "jssp":
        from masbench.adapters.jssp_protocol import (
            score_protocol_answer as jssp_score,
        )

        return float(jssp_score(final_answer, global_task)["partial"])
    return float(score_protocol_answer(final_answer, global_task)["partial"])


# 【职责】从最终的每 agent 信念状态给一次分段(segmented)Silo 运行评分。
# - 分段任务每个 agent 有自己的 expected_output，单一投票全局答案无意义，故逐 agent 评。
# - 逐 agent 读其最终 belief、抽取答案、规范化后与该 agent 的期望分段比对。
# - 返回(success, partial, per_agent_correct)：全部 agent 各自精确正确才 success；
#   partial 取各 agent silo_partial_score 的均值；per_agent_correct[i] 是严格精确匹配。
# - 兜底：缺失/过短的 final_agent_states 视对应 agent 为错(答案 None→partial 0.0)；
#   期望 agent 数为 0 时返回(False,0.0,[])而非空洞的成功。
def _score_segmented(
    result: Any,
    instance: BenchmarkInstance,
    adapter: SiloProtocolAdapter,
    global_task: dict,
) -> tuple[bool, float, list[bool]]:
    """Grade a SEGMENTED Silo run from the FINAL PER-AGENT states.

    Segmented tasks give every agent its OWN ``expected_output`` (carried in
    ``meta['expected_outputs'][agent_id]``), so the single voted global answer is
    meaningless. For each agent we read its final belief
    (``result.final_agent_states[agent_id].belief_state``), extract that agent's
    answer via :meth:`SiloProtocolAdapter.extract_protocol_answer`, and compare it
    (canonicalized) to that agent's expected segment.

    Returns ``(success, partial, per_agent_correct)`` where:

    * ``success`` is True iff EVERY agent is exact-correct on its own segment;
    * ``partial`` is the mean of :func:`silo_partial_score` over agents (graded
      per-agent quality in [0, 1]);
    * ``per_agent_correct[i]`` is the strict exact-match for agent ``i``.

    Robust to a missing/short ``final_agent_states``: any agent without a state is
    treated as wrong (answer ``None`` -> partial 0.0). With zero expected agents
    (degenerate) it reports ``(False, 0.0, [])`` rather than a vacuous success.
    """
    expected_outputs = instance.meta.get("expected_outputs") or []
    n_agents = len(expected_outputs)
    final_states = list(getattr(result, "final_agent_states", []) or [])
    output_type = global_task.get("output_type", "scalar")

    per_agent_correct: list[bool] = []
    partials: list[float] = []
    for agent_id in range(n_agents):
        expected = expected_outputs[agent_id]
        if agent_id < len(final_states):
            belief = final_states[agent_id].belief_state
            answer = adapter.extract_protocol_answer(belief)
        else:
            answer = None  # missing state -> treat as wrong
        correct = (
            answer is not None
            and canonical_answer(answer) == canonical_answer(expected)
        )
        per_agent_correct.append(bool(correct))
        partials.append(float(silo_partial_score(answer, expected, output_type)))

    success = n_agents > 0 and all(per_agent_correct)
    partial = (sum(partials) / len(partials)) if partials else 0.0
    return success, partial, per_agent_correct


# 【职责】从协议结果的调度结构算逐 agent 知识集合（与 LLM 答案正确性无关）。
# - 用计划内的调度边(schedule transmissions)做结构传播检测：knowledge[i] 初始 {i}，
#   每步同时执行，src->dst 使 next[dst] 并入 previous[src]。
def _structural_knowledge(result: Any, n_agents: int) -> list[set[int]]:
    steps = [
        [tuple(edge) for edge in getattr(step, "transmissions", [])]
        for step in getattr(result, "schedule", [])
    ]
    return propagate_knowledge(n_agents, steps)


# 【职责】解析 sink 模式的汇点 agent id。
# - 优先取 protocol_spec.metadata.selected_primary（生成图显式声明的汇点）；
# - 具名拓扑无显式汇点：取结构信息覆盖率最高者（并列取最小 id）——chain 末端、
#   树根、星心都会被该规则确定性选中。
def _resolve_sink_id(result: Any, n_agents: int) -> int:
    spec = getattr(result.config, "protocol_spec", None)
    if spec is not None:
        selected = (spec.metadata or {}).get("selected_primary")
        try:
            candidate = int(selected)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and 0 <= candidate < n_agents:
            return candidate
    knowledge = _structural_knowledge(result, n_agents)
    if not knowledge:
        return max(0, n_agents - 1)
    best = max(range(n_agents), key=lambda a: (len(knowledge[a]), -a))
    return best


# 【职责】从最终状态抽取某个 agent 的答案（缺状态视为 None）。
def _agent_answer(result: Any, task_adapter: Any, agent_id: int) -> Any:
    states = list(getattr(result, "final_agent_states", []) or [])
    if 0 <= agent_id < len(states):
        return task_adapter.extract_protocol_answer(states[agent_id].belief_state)
    return None


# 【职责】sink 模式评分：只有 selected_primary 的答案用于主评分。
# - 输出 sink_exact/sink_partial/sink_id/sink_information_coverage；
#   其他 agent 保留局部状态不参与主评分。分段任务以 sink 自己的期望分段为准。
def _score_sink_mode(
    result: Any,
    instance: BenchmarkInstance,
    task_adapter: Any,
    global_task: dict,
    extra: dict,
) -> tuple[bool, float, dict]:
    n_agents = int(instance.n_agents)
    sink_id = _resolve_sink_id(result, n_agents)
    answer = _agent_answer(result, task_adapter, sink_id)
    if instance.segmented:
        expected_outputs = private_expected_outputs(global_task) or (
            instance.meta.get("expected_outputs") or []
        )
        expected = expected_outputs[sink_id] if sink_id < len(expected_outputs) else None
        sink_exact = answer is not None and canonical_answer(answer) == canonical_answer(
            expected
        )
        sink_partial = float(
            silo_partial_score(answer, expected, global_task.get("output_type", "scalar"))
        )
        extra["segmented"] = True
    else:
        scored = task_adapter.score_protocol_answer(answer, global_task)
        sink_exact = bool(scored.get("exact_match", False))
        sink_partial = float(scored.get("partial", 0.0))
    knowledge = _structural_knowledge(result, n_agents)
    coverage = coverage_by_agent(knowledge)
    extra.update(
        {
            "information_goal": "sink",
            "sink_id": sink_id,
            "sink_exact": bool(sink_exact),
            "sink_partial": sink_partial,
            "sink_information_coverage": (
                coverage[sink_id] if 0 <= sink_id < len(coverage) else 0.0
            ),
        }
    )
    return bool(sink_exact), sink_partial, extra


# 【职责】all_agents 模式评分：每个 agent 必须独立正确；多数票不作数。
# - 输出 per_agent_correct / agent_success_rate S / all_agents_exact(S=1) /
#   partial P(逐 agent partial 均值) / information_coverage_by_agent /
#   mean/min_information_coverage / all_agents_full_information / communication_density。
# - 非分段任务逐 agent 与同一全局答案比较；分段任务逐 agent 与自己的期望分段比较。
def _score_all_agents_mode(
    result: Any,
    instance: BenchmarkInstance,
    task_adapter: Any,
    global_task: dict,
    extra: dict,
    answer_overrides: list[Any] | None = None,
    submitted_rounds: list[int | None] | None = None,
    additional_completion_tokens: int = 0,
    additional_rounds: int = 0,
) -> tuple[bool, float, dict]:
    n_agents = int(instance.n_agents)
    expected_outputs = private_expected_outputs(global_task) or (
        instance.meta.get("expected_outputs") or []
    )
    if len(expected_outputs) != n_agents:
        expected_outputs = [instance.ground_truth for _ in range(n_agents)]
    answers = (
        list(answer_overrides)
        if answer_overrides is not None
        else [
            _agent_answer(result, task_adapter, agent_id)
            for agent_id in range(n_agents)
        ]
    )
    if len(answers) != n_agents:
        raise ValueError("all-agent answer overrides must match n_agents")
    paper = evaluate_paper_submissions(
        case_id=instance.case_id,
        answers=answers,
        expected_outputs=list(expected_outputs),
        submitted_rounds=submitted_rounds,
    )
    per_agent_correct = list(paper["per_agent_correct"])
    agent_success_rate = float(paper["paper_S"])
    all_agents_exact = n_agents > 0 and all(per_agent_correct)
    partial = float(paper["paper_P"])
    knowledge = _structural_knowledge(result, n_agents)
    coverage = coverage_by_agent(knowledge)
    density = paper_communication_density(
        int(getattr(result, "total_messages", 0) or 0), n_agents
    )
    config = getattr(result, "config", None)
    init_rounds = 1 if getattr(config, "init_mode", None) == "llm_local_solve" else 0
    rounds_executed = int(getattr(result, "total_steps", 0) or 0) + init_rounds
    if rounds_executed <= 0 and int(getattr(result, "total_model_calls", 0) or 0) > 0:
        rounds_executed = 1
    rounds_executed += max(0, int(additional_rounds))
    paper_c = paper_token_consumption(
        int(getattr(result, "total_completion_tokens", 0) or 0)
        + max(0, int(additional_completion_tokens)),
        rounds_executed,
    )
    extra.update(
        {
            "information_goal": "all_agents",
            "per_agent_correct": per_agent_correct,
            "per_agent_answers": paper["per_agent_answers"],
            "per_agent_partial": paper["per_agent_partial"],
            "per_agent_submissions": paper["per_agent_submissions"],
            "all_submitted": all(answer is not None for answer in answers),
            "agent_success_rate": agent_success_rate,
            "all_agents_exact": bool(all_agents_exact),
            "paper_S": agent_success_rate,
            "paper_P": partial,
            "paper_C": paper_c,
            "paper_D": density,
            "rounds_executed": rounds_executed,
            "information_coverage_by_agent": coverage,
            "mean_information_coverage": (
                sum(coverage) / len(coverage) if coverage else 0.0
            ),
            "min_information_coverage": min(coverage) if coverage else 0.0,
            "all_agents_full_information": bool(
                coverage and min(coverage) >= 1.0
            ),
            "communication_density": density,
        }
    )
    return bool(all_agents_exact), partial, extra


# 【职责】把 ProtocolRunner 的结果转成分级的 ScoreResult。
# - 被 planner(select/graph_generate)与强制固定拓扑路径共用，使每个实验臂评分与计量
#   完全一致：同样的评分语义，同样从 total_* 计数器取消息/调用/token。
# - information_goal 决定主评分语义：
#   * sink：只有 selected_primary 的答案用于主评分（success = sink_exact）；
#   * all_agents：每个 agent 都必须独立正确（success = all_agents_exact，绝不用多数票）。
def _score_protocol_result(
    result: Any,
    instance: BenchmarkInstance,
    task_adapter: SiloProtocolAdapter,
    global_task: dict,
    *,
    extra: dict,
    information_goal: str = "sink",
    answer_overrides: list[Any] | None = None,
    submitted_rounds: list[int | None] | None = None,
    final_submission_batch: FinalSubmissionBatch | None = None,
) -> ScoreResult:
    """Turn a ``ProtocolRunner`` result into a graded :class:`ScoreResult`.

    Shared by the planner (select/graph_generate) and forced-fixed-topology
    paths so every arm is scored and metered identically. The main ``success``
    follows ``information_goal``: sink grades ONLY the resolved sink agent;
    all_agents requires EVERY agent to be individually correct
    (``all_agents_exact``) -- a majority vote can never mask a wrong agent.
    """
    final = result.final_result
    extra = {**extra, "aggregation_method": final.aggregation_method}
    if information_goal == "all_agents":
        if final_submission_batch is not None:
            extra["runtime_final_submission"] = final_submission_batch.audit_dict()
        success, partial, extra = _score_all_agents_mode(
            result,
            instance,
            task_adapter,
            global_task,
            extra,
            answer_overrides=answer_overrides,
            submitted_rounds=submitted_rounds,
            additional_completion_tokens=(
                final_submission_batch.completion_tokens
                if final_submission_batch is not None
                else 0
            ),
            additional_rounds=1 if final_submission_batch is not None else 0,
        )
    else:
        success, partial, extra = _score_sink_mode(
            result, instance, task_adapter, global_task, extra
        )
    return ScoreResult(
        success=success,
        partial=partial,
        n_messages=int(result.total_messages),
        n_model_calls=int(result.total_model_calls)
        + (
            final_submission_batch.model_calls
            if final_submission_batch is not None
            else 0
        ),
        tokens=int(result.total_prompt_tokens)
        + int(result.total_completion_tokens)
        + (
            final_submission_batch.prompt_tokens
            + final_submission_batch.completion_tokens
            if final_submission_batch is not None
            else 0
        ),
        final_answer=final.final_key,
        extra=extra,
    )


def _run_protocol_final_submission_barrier(
    *,
    result: Any,
    task_adapter: SiloProtocolAdapter,
    global_task: dict[str, Any],
    cfg: RunConfig,
    llm_client: LLMClient,
) -> FinalSubmissionBatch:
    """Turn every final protocol belief into an explicit, audited answer."""

    prompts: dict[int, str] = {}
    for agent_id, state in enumerate(result.final_agent_states):
        submit_context = task_adapter.format_python_submit_prompt(
            global_task=global_task,
            local_observation=state.local_observation,
        )
        belief_json = json.dumps(
            state.belief_state.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
        )
        prompts[agent_id] = (
            submit_context
            + "\n\nFINAL_PROTOCOL_BELIEF_JSON:\n"
            + belief_json
            + "\n\n"
            + MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION
        )
    return run_final_submission_barrier(
        prompts=prompts,
        llm_client=llm_client,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
        max_parallel_agents=cfg.max_parallel_agents,
        retries=cfg.final_submission_retries,
    )


# 【职责】在强制固定的协议拓扑上跑一个实例(planner-OFF 基线臂)。
# - fixed 臂把具名拓扑直接经通用 ProtocolRunner 跑：无 planner、无生成的 protocol_spec，
#   拓扑名由 build_protocol_schedule 编译成有限的通信调度。
# - 刻意走 protocol 路径而非旧的 SynchronousRunner 路径，原因：
#   * SynchronousRunner(run_instance 里 use_planner=False 的路径)只接受物理拓扑集
#     chain/ring/star/mesh/static_exponential/one_peer_exponential，且按结构上界计消息。
#   * 论文的 fixed 基线是协议调度拓扑(tree、mesh_star、one_peer_exponential_dag_star、
#     chain)，只有 build_protocol_schedule 认识，且与 select/graphgen 臂共享同一套
#     消息/调用/token 计量。
# - 在此强制拓扑，使整个实验臂对比同口径(一个 runner、一个 scorer)，同时让 fixed 臂能
#   扫过 planner 可选的同一批具名拓扑。
def run_fixed_protocol(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    topology: str,
    llm_client: LLMClient | None = None,
) -> ScoreResult:
    """Run one instance on a FORCED protocol topology (planner-OFF baseline arm).

    The "fixed" baseline arm of the paper-grade harness runs each named topology
    directly through the generalized :class:`ProtocolRunner` with NO planner and
    NO generated ``protocol_spec`` — the topology name is compiled to a finite
    communication schedule by ``build_protocol_schedule``. This is deliberately
    the *protocol* path rather than the legacy ``SynchronousRunner`` path:

    * ``SynchronousRunner`` (the ``use_planner=False`` path in ``run_instance``)
      only accepts the physical topology set
      ``chain/ring/star/mesh/static_exponential/one_peer_exponential`` and meters
      messages by a structural upper bound.
    * The paper's fixed baselines are the *protocol-schedule* topologies
      (``tree``, ``mesh_star``, ``one_peer_exponential_dag_star``, ``chain``),
      which only ``build_protocol_schedule`` understands, and they share the exact
      message/model-call/token accounting the ``select``/``graphgen`` arms use.

    Forcing the topology here therefore keeps the whole arm comparison
    apples-to-apples (one runner, one scorer) while letting the fixed arm sweep
    the same named topologies the planner can pick.
    """
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    task_adapter = _protocol_adapter(instance, information_goal=goal)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    client = llm_client or _build_llm_client(cfg)

    config = ProtocolRunnerConfig(
        topology_name=topology,
        n_agents=n_agents,
        seed=cfg.seed,
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
        max_parallel_agents=max(1, int(cfg.max_parallel_agents)),
    )
    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()
    final_submission_batch: FinalSubmissionBatch | None = None
    answer_overrides: list[Any] | None = None
    submitted_rounds: list[int | None] | None = None
    if goal == "all_agents" and cfg.require_all_submissions:
        final_submission_batch = _run_protocol_final_submission_barrier(
            result=result,
            task_adapter=task_adapter,
            global_task=global_task,
            cfg=cfg,
            llm_client=client,
        )
        answer_overrides = [
            final_submission_batch.answers[agent_id]
            for agent_id in range(n_agents)
        ]
        final_round = int(result.total_steps) + (
            1 if cfg.init_mode == "llm_local_solve" else 0
        )
        submitted_rounds = [final_round for _ in range(n_agents)]
    extra = {
        "case_id": instance.case_id,
        "planner": False,
        "topology": topology,
        "objective": cfg.objective,
        "fixed": True,
        # 中文：fixed 臂使用具名拓扑：provenance=fixed_named。它的记录/证据由此可与
        #   GraphGen 完全隔离（clean GraphGen 库拒收该来源）。
        # Fixed arm runs a named topology: provenance=fixed_named. Its records
        # and evidence are thereby isolatable from GraphGen (clean banks
        # reject this provenance).
        "provenance": "fixed_named",
        "silo_eval_mode": goal,
    }
    return _score_protocol_result(
        result,
        instance,
        task_adapter,
        global_task,
        extra=extra,
        information_goal=goal,
        answer_overrides=answer_overrides,
        submitted_rounds=submitted_rounds,
        final_submission_batch=final_submission_batch,
    )


# 【职责】把一个实例经 QueenBee planner + ProtocolRunner 跑通并评分。
# - cfg.planner_mode 决定如何选通信结构：
#   * topology_select(默认)：皇帝规划器选一个具名拓扑；技能库(暂空)时兜底到
#     default_topology_for_objective。
#   * graph_generate：皇帝 LLM 经 plan_free_graph 现造一张时序通信 DAG，生成的
#     protocol_spec 驱动运行器。遇 fake/垃圾 LLM 时会校验/修复并最终兜底到固定算子拓扑，
#     故离线也不崩。
# - 无论哪种，最终 plan.topology_name + plan.protocol_spec 驱动通用 ProtocolRunner；
#   同一 client 复用于 DAG 生成与士兵执行。motif_stats(仅 graph_generate)是累积的结构母题
#   证据，排候选时激活结构母题信用先验(见 _plan_graph_generate)。
def _run_planner(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
) -> ScoreResult:
    """Run one instance through the QueenBee planner + ProtocolRunner and score it.

    ``cfg.planner_mode`` selects how the communication structure is chosen:

    * ``"topology_select"`` (default): ``EmperorPlanner`` picks a named topology;
      with the (empty for now) SkillBank it falls back to
      ``default_topology_for_objective``.
    * ``"graph_generate"``: the emperor LLM invents a bespoke temporal DAG via
      ``plan_free_graph``; the generated ``protocol_spec`` drives the runner. With
      a fake/junk LLM, ``plan_free_graph`` validates/repairs and ultimately falls
      back to a fixed operator topology, so the run never crashes offline.

    Either way the resulting ``plan.topology_name`` + ``plan.protocol_spec`` drive
    the generalized ProtocolRunner. The same ``client`` is reused for any DAG
    generation and the soldier execution. ``motif_stats`` (graph_generate only) is
    accumulated motif evidence that activates the structural-motif credit prior
    when ranking generated candidates (see ``_plan_graph_generate``).
    """
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    task_adapter = _protocol_adapter(instance, information_goal=goal)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    client = llm_client or _build_llm_client(cfg)

    if cfg.planner_mode == "python_generate":
        return _run_python_generate(
            instance,
            cfg,
            task_adapter=task_adapter,
            global_task=global_task,
            client=client,
            motif_stats=motif_stats,
            skill_bank=skill_bank,
        )
    if cfg.planner_mode == "graph_generate":
        try:
            plan, planner_extra = _plan_graph_generate(
                cfg,
                n_agents=n_agents,
                task_adapter=task_adapter,
                client=client,
                motif_stats=motif_stats,
                skill_bank=skill_bank,
                instance=instance,
            )
        except GraphGenerationError as exc:
            # 中文：自由图生成失败：不再静默回退到具名拓扑。记录
            #   graph_generation_failed 并让该运行以失败计分（partial 0）。
            # Free-graph generation failed: no silent named fallback. Record
            # graph_generation_failed and score the run as a failure.
            return ScoreResult(
                success=False,
                partial=0.0,
                n_messages=0,
                n_model_calls=0,
                tokens=0,
                final_answer=None,
                extra={
                    "case_id": instance.case_id,
                    "planner": True,
                    "planner_mode": "graph_generate",
                    "topology": None,
                    "objective": cfg.objective,
                    "graph_generation_failed": exc.reason,
                    "silo_eval_mode": goal,
                    "information_goal": goal,
                },
            )
    elif cfg.planner_mode == "program_generate":
        try:
            plan, planner_extra = _plan_program_generate(
                cfg,
                n_agents=n_agents,
                task_adapter=task_adapter,
                client=client,
                motif_stats=motif_stats,
                skill_bank=skill_bank,
                instance=instance,
            )
        except PhaseProgramGenerationError as exc:
            return ScoreResult(
                success=False,
                partial=0.0,
                n_messages=0,
                n_model_calls=0,
                tokens=0,
                final_answer=None,
                extra={
                    "case_id": instance.case_id,
                    "planner": True,
                    "planner_mode": "program_generate",
                    "topology": None,
                    "objective": cfg.objective,
                    "program_generation_failed": exc.reason,
                    "silo_eval_mode": goal,
                    "information_goal": goal,
                },
            )
    else:
        plan, planner_extra = _plan_topology_select(cfg, n_agents=n_agents)

    # 中文：构建运行器配置。plan.config_overrides 可能带一个 protocol_spec(算子/图规划
    #   模式)，与我们显式传入的并存，故把 overrides 叠加在基础 kwargs 之上，避免重复键报错。
    # Build the runner config. ``plan.config_overrides`` may carry a protocol_spec
    # (operator/graph planner modes) alongside the one we pass explicitly, so we
    # layer overrides on top of the base kwargs to avoid duplicate-key errors.
    config_kwargs: dict = {
        "topology_name": plan.topology_name,
        "n_agents": n_agents,
        "seed": cfg.seed,
        "merge_mode": cfg.merge_mode,
        "init_mode": cfg.init_mode,
        "protocol_spec": plan.protocol_spec,
        "llm_provider": cfg.llm_provider,
        "model_name": cfg.model_name,
        "temperature": cfg.temperature,
        "max_parallel_agents": max(1, int(cfg.max_parallel_agents)),
    }
    config_kwargs.update(plan.config_overrides)
    config = ProtocolRunnerConfig(**config_kwargs)

    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()

    extra = {
        "case_id": instance.case_id,
        "planner": True,
        "topology": plan.topology_name,
        "objective": cfg.objective,
        "provenance": plan.provenance
        or (
            "fixed_named"
            if cfg.planner_mode not in {"graph_generate", "program_generate"}
            else None
        ),
        "silo_eval_mode": goal,
    }
    extra.update(planner_extra)
    return _score_protocol_result(
        result, instance, task_adapter, global_task, extra=extra, information_goal=goal
    )


# 【职责】QueenBee topology-select 规划：让皇帝规划器选一个具名拓扑。
def _plan_topology_select(cfg: RunConfig, *, n_agents: int):
    """QueenBee topology-select plan (Plan 3 B): pick a named topology."""
    request = PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name(cfg.objective),
    )
    plan = EmperorPlanner(SkillBank()).plan(request)
    return plan, {"planner_mode": "topology_select"}


# 【职责】生成型组织结构的步数上限，随 agent 数 n 伸缩。
# - 历史固定上限 4 使 n=10 时线性深度调度无法表达(一次 chain 传递需约 n-1 步)，而具名
#   拓扑编译无上限，故生成型臂被结构性地挡在顺序任务所需的组织之外。
# - 若显式配置了非默认上限，则原样沿用。
def _effective_graph_max_steps(cfg: RunConfig, n_agents: int) -> int:
    """Step cap for GENERATED organizations, scaling with n.

    The historical fixed cap (4) made linear-depth schedules inexpressible at
    n=10 -- a chain pass needs ~n-1 steps -- while named-topology compilation
    has no cap, so generation-based arms were structurally barred from the
    organizations sequential tasks need (P2 confirmatory-2 failure analysis).
    An explicitly configured non-default cap is honored unchanged.
    """
    if cfg.graph_max_steps != 4:
        return cfg.graph_max_steps
    return max(4, n_agents + 2)


# 【职责】判定是否启用 replay 指令重写：环境变量 MASBENCH_REPLAY_REWRITE 优先，否则看 cfg。
def _replay_rewrite_enabled(cfg: RunConfig) -> bool:
    raw = os.environ.get("MASBENCH_REPLAY_REWRITE", "").strip()
    if raw:
        return raw not in {"0", "false", "off"}
    return bool(getattr(cfg, "replay_rewrite", False))


# 【职责】完整 QueenBee 规划：皇帝 LLM 现造一张定制时序通信 DAG。
# - 委托给 plan_free_graph：生成候选 DAG、校验/修复，离线或遇垃圾时兜底到固定算子拓扑。
# - 复用同一 client 做生成调用；plan_free_graph 需要 output_dir，故给它一个临时目录以免
#   污染仓库；默认 single 搜索模式下不会调用 task_adapter 做探针评估(传 Silo 适配器安全)。
# - 打开 use_motif_prior：让 QueenBee 排候选时部分参考各母题在过往证据中的表现。
#   motif_stats 是该证据(由 aggregate_motif_losses 聚合)；单次运行尚无累积证据，故默认
#   None、先验失效(选择不变)；bench/evolve 框架会喂入历史 motif_stats 激活它。
# - 先验只在存活候选 >1 时改变选择，故需设 cfg.num_graph_candidates > 1 才会触发。
def _graph_artifacts_dir(cfg: RunConfig, instance: BenchmarkInstance | None) -> Path:
    """Persistent (never auto-deleted) home for graph_generate audit artifacts.

    Priority: cfg.graph_artifacts_dir > MASBENCH_GRAPH_ARTIFACTS_DIR env >
    ``runs/graphgen_artifacts`` under the cwd. Each call gets its own
    subdirectory keyed by case/agents/seed/mode plus a timestamp, so reruns
    never overwrite an earlier architect audit trail.
    """
    base = (
        cfg.graph_artifacts_dir
        or os.environ.get("MASBENCH_GRAPH_ARTIFACTS_DIR", "").strip()
        or str(Path("runs") / "graphgen_artifacts")
    )
    case = instance.case_id if instance is not None else "unknown_case"
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{time.time_ns()}"
    leaf = f"{case}_n{cfg.n_agents or (instance.n_agents if instance else 0)}_seed{cfg.seed}_{goal}_{stamp}"
    path = Path(base) / leaf
    path.mkdir(parents=True, exist_ok=True)
    return path


def _program_artifacts_dir(
    cfg: RunConfig,
    instance: BenchmarkInstance | None,
) -> Path:
    """Persistent audit home for the independent restricted-program planner."""
    base = (
        cfg.program_artifacts_dir
        or os.environ.get("MASBENCH_PROGRAM_ARTIFACTS_DIR", "").strip()
        or str(Path("runs") / "programgen_artifacts")
    )
    case = instance.case_id if instance is not None else "unknown_case"
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{time.time_ns()}"
    leaf = (
        f"{case}_n{cfg.n_agents or (instance.n_agents if instance else 0)}_"
        f"seed{cfg.seed}_{goal}_{stamp}"
    )
    path = Path(base) / leaf
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plan_graph_generate(
    cfg: RunConfig,
    *,
    n_agents: int,
    task_adapter: SiloProtocolAdapter,
    client: LLMClient,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
    instance: BenchmarkInstance | None = None,
):
    """FULL QueenBee plan: the emperor LLM invents a bespoke temporal DAG.

    Delegates to ``exp_graph.mas.graph_generation.plan_free_graph``, which
    generates candidate DAGs, validates/repairs them, and (offline / on junk)
    falls back to a fixed operator topology. We reuse the SAME ``client`` for the
    generation call. ``plan_free_graph`` requires an ``output_dir`` for its
    artifacts; we hand it a throwaway temp dir so the repo is not polluted, and
    in the default single-search mode the ``task_adapter`` is never invoked for
    probe evaluation (so passing the Silo adapter is safe).

    Structural-motif credit prior (Plan 4 Task 5): we turn ``use_motif_prior`` ON
    so QueenBee ranks newly generated candidates partly by how their motifs
    performed in past evidence (see ``exp_graph.mas.motifs``). ``motif_stats`` is
    that evidence, aggregated by ``aggregate_motif_losses``. A single-run plan
    has no accumulated Silo evidence yet, so ``motif_stats`` defaults to None and
    the prior is inert (selection unchanged); the bench/evolve harness supplies
    ``motif_stats`` from prior runs to activate it. The prior only changes the
    pick when >1 candidate survives, so set ``cfg.num_graph_candidates > 1`` to
    let it fire.
    """
    hot_start = bool(getattr(cfg, "hot_start_enabled", False)) and any(
        "hot-start" in {tag.lower() for tag in skill.tags}
        for skill in (skill_bank or SkillBank())
    )
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        max_parallel_agents=max(1, int(cfg.max_parallel_agents)),
        # 中文：仅生成阶段的温度覆盖：探索用高温提设计(跨轮多样性)，而协议执行仍用
        #   cfg.temperature；None 表示不拆分(部署路径)。
        # Generation-only temperature override: exploration proposes designs HOT
        # (diversity across rounds) while protocol execution stays at
        # cfg.temperature; None -> no split (deployment path).
        temperature=(
            cfg.graph_gen_temperature
            if getattr(cfg, "graph_gen_temperature", None) is not None
            else cfg.temperature
        ),
        num_graph_candidates=cfg.num_graph_candidates,
        graph_max_steps=_effective_graph_max_steps(cfg, n_agents),
        graph_max_messages=cfg.graph_max_messages,
        graph_max_receiver_fan_in=cfg.graph_max_receiver_fan_in,
        use_motif_prior=True,
        motif_stats=motif_stats,
        # 中文：M4——只跑过 1 次的走运母题不得压过有实测的老将。
        # M4: a 1-run lucky motif must not outrank a measured veteran.
        motif_uncertainty_kappa=getattr(cfg, "motif_uncertainty_kappa", 0.0),
        # 中文：M9——把重放结构里每步的角色指引适配到当前任务。
        # M9: adapt replayed structures' per-step role guidance to THIS task.
        replay_instruction_rewrite=_replay_rewrite_enabled(cfg),
        # 中文：Round-10 部署稳定性：可信重放胜过同轮新生成；motif 先验只有在有真实预测
        #   损失优势时才顶替确定性首选。
        # Round-10 deployment stability: trusted replays out-compete fresh
        # same-run generations; motif prior displaces the deterministic head
        # only with a real predicted-loss margin.
        replay_first=bool(getattr(cfg, "replay_first", False)),
        failure_feedback_enabled=(
            getattr(cfg, "failure_policy", "legacy_drop") == "honest_v2"
        ),
        motif_displacement_margin=float(getattr(cfg, "motif_displacement_margin", 0.0)),
        # 中文：D2——拒绝/修复那些汇点无法从所有 agent 到达的生成 DAG(正是让生成失手的
        #   有损归约失败模式)。
        # D2: reject/repair generated DAGs whose sink isn't reachable from ALL
        # agents (the lossy-reduction failure mode that made generation lose).
        graph_require_full_sink_coverage=True,
        # 中文：D1——用 N 个验证种子(真实任务运行)对每个候选做探针评估并选最优；
        #   0 表示关闭(盲选首个有效/按母题选)。
        # D1: probe-evaluate each candidate on N validation seeds (real task runs)
        # and select the best-scoring one; 0 -> off (blind first-valid/motif pick).
        graph_search_mode=("topk" if cfg.graph_validation_seeds > 0 else "single"),
        graph_validation_seeds=list(range(cfg.graph_validation_seeds)),
        # 中文：M23(冻结士兵、更强架构师)：配置了模型拆分时，皇帝角色调用(图生成+指令重写)
        #   使用 planner 模型；None 表示逐字节一致的旧路径。
        # M23 (frozen workers, stronger architect): emperor-role calls
        # (graph generation + instruction rewrite) use the planner model
        # when the split is configured; None -> byte-identical legacy path.
        role_llm_profiles=(
            RoleLLMProfiles(
                emperor=RoleLLMConfig(
                    platform=cfg.llm_provider,
                    model_name=cfg.planner_model_name,
                )
            )
            if getattr(cfg, "planner_model_name", None)
            else None
        ),
        # 中文：信息目标决定架构师提示词模板与覆盖校验/修复谓词；Silo 的模型可见
        #   提示词全部启用泄漏审计。
        # The information goal selects the architect prompt template and the
        # coverage predicate; Silo model-visible prompts run the leakage audit.
        information_goal=getattr(cfg, "silo_eval_mode", "sink") or "sink",
        leakage_audit=True,
        leakage_allowed_tokens=(
            ["one_peer", "distance-doubling", "pow2", "exponential"]
            if hot_start
            else []
        ),
    )
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    # 中文：clean GraphGen 判定：默认 clean —— 检索只放行 llm_generated 与同模式验证过
    #   的 skill_replay，缺 provenance 的旧卡视为 contaminated，具名 fixed 证据一律不可
    #   见。select_then_refine 按定义要从具名锚点精修（fixed→graphgen 迁移），因此该
    #   evolved 模式（或显式 clean_graphgen=False）是"非 clean"路径：记录上明确标注，
    #   其产物不得用于 clean GraphGen 结论。
    # Clean-GraphGen determination: clean by default (retrieval admits only
    # llm_generated + same-goal skill_replay; no-provenance legacy cards are
    # contaminated; named fixed evidence is invisible). select_then_refine BY
    # DEFINITION refines from named anchors, so that evolved mode (or an
    # explicit clean_graphgen=False) is a NON-clean path: it is labelled on
    # every record and must not feed clean-GraphGen conclusions.
    clean_graphgen = bool(getattr(cfg, "clean_graphgen", True)) and not hot_start and (
        getattr(cfg, "evolved_mode", "topology_select") != "select_then_refine"
    )
    request = PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name(cfg.objective),
        planner_mode="graph_generate",
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        information_goal=goal,
        provenance_allowlist=(
            list(CLEAN_GRAPHGEN_PROVENANCE) if clean_graphgen else None
        ),
        include_reference_skills=hot_start,
    )
    # 中文：架构师审计产物写入持久目录（绝不再写入用完即删的 TemporaryDirectory）：
    #   渲染提示词、prompt 哈希、原始回复、解析/展开边、校验修复记录、失败与选择原因。
    # Architect audit artifacts persist (never a throwaway TemporaryDirectory).
    artifacts_dir = _graph_artifacts_dir(cfg, instance)
    result = plan_free_graph(
        request=request,
        runtime=runtime,
        skill_bank=skill_bank if skill_bank is not None else SkillBank(),
        seed=cfg.seed,
        task_adapter=task_adapter,
        output_dir=artifacts_dir,
        llm_client=client,
    )
    plan = result.plan
    spec = plan.protocol_spec
    extra = {
        "planner_mode": "graph_generate",
        "generated_steps": len(spec.steps) if spec is not None else 0,
        "graph_artifacts_dir": str(artifacts_dir),
        "provenance": getattr(plan, "provenance", None),
        "selection_reason": getattr(result, "selection_reason", None),
        "clean_graphgen": clean_graphgen,
    }
    return plan, extra


def _plan_program_generate(
    cfg: RunConfig,
    *,
    n_agents: int,
    task_adapter: Any,
    client: LLMClient,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
    instance: BenchmarkInstance | None = None,
):
    """Generate and compile ``phase_program_v1`` without invoking GraphGen."""
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    hot_start = bool(getattr(cfg, "hot_start_enabled", False)) and any(
        "hot-start" in {tag.lower() for tag in skill.tags}
        for skill in (skill_bank or SkillBank())
    )
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        max_parallel_agents=max(1, int(cfg.max_parallel_agents)),
        temperature=(
            cfg.graph_gen_temperature
            if getattr(cfg, "graph_gen_temperature", None) is not None
            else cfg.temperature
        ),
        num_graph_candidates=cfg.num_graph_candidates,
        graph_max_steps=_effective_graph_max_steps(cfg, n_agents),
        graph_max_messages=cfg.graph_max_messages,
        graph_max_receiver_fan_in=cfg.graph_max_receiver_fan_in,
        program_repair_attempts=max(0, cfg.program_repair_attempts),
        use_motif_prior=True,
        motif_stats=motif_stats,
        motif_uncertainty_kappa=getattr(cfg, "motif_uncertainty_kappa", 0.0),
        replay_first=bool(getattr(cfg, "replay_first", False)),
        failure_feedback_enabled=(
            getattr(cfg, "failure_policy", "legacy_drop") == "honest_v2"
        ),
        role_llm_profiles=(
            RoleLLMProfiles(
                emperor=RoleLLMConfig(
                    platform=cfg.llm_provider,
                    model_name=cfg.planner_model_name,
                )
            )
            if getattr(cfg, "planner_model_name", None)
            else None
        ),
        information_goal=goal,
        leakage_audit=True,
        leakage_allowed_tokens=(
            ["one_peer", "distance-doubling", "pow2", "exponential"]
            if hot_start
            else []
        ),
    )
    request = PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name(cfg.objective),
        planner_mode="program_generate",
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        information_goal=goal,
        provenance_allowlist=list(CLEAN_PROGRAM_PROVENANCE),
        include_reference_skills=hot_start,
    )
    artifacts_dir = _program_artifacts_dir(cfg, instance)
    result = plan_phase_program(
        request=request,
        runtime=runtime,
        skill_bank=skill_bank if skill_bank is not None else SkillBank(),
        seed=cfg.seed,
        task_adapter=task_adapter,
        output_dir=artifacts_dir,
        llm_client=client,
    )
    plan = result.plan
    spec = plan.protocol_spec
    return plan, {
        "planner_mode": "program_generate",
        "program_format": "phase_program_v1",
        "generated_steps": len(spec.steps) if spec is not None else 0,
        "program_artifacts_dir": str(artifacts_dir),
        "provenance": getattr(plan, "provenance", None),
        "selection_reason": result.selection_reason,
        "clean_programgen": not hot_start,
    }


def _python_artifacts_dir(
    cfg: RunConfig,
    instance: BenchmarkInstance | None,
) -> Path:
    """Persistent audit root for PythonGen, isolated from both graph modes."""
    base = (
        cfg.python_artifacts_dir
        or os.environ.get("MASBENCH_PYTHON_ARTIFACTS_DIR", "").strip()
        or str(Path("runs") / "pycodegen_artifacts")
    )
    case = instance.case_id if instance is not None else "unknown_case"
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{time.time_ns()}"
    leaf = (
        f"{case}_n{cfg.n_agents or (instance.n_agents if instance else 0)}_"
        f"seed{cfg.seed}_{goal}_{stamp}"
    )
    path = Path(base) / leaf
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_python_execution_payload(
    *,
    instance: BenchmarkInstance,
    cfg: RunConfig,
    task_adapter: Any,
    global_task: dict[str, Any],
    n_agents: int,
) -> dict[str, Any]:
    observations = task_adapter.split_into_local_observations(global_task, n_agents)
    worker_contract = getattr(cfg, "python_worker_contract", "action_json_v1")
    if worker_contract == "message_only_v2":
        agents = [
            {
                "agent_id": agent_id,
                "communication_prompt": (
                    task_adapter.format_python_communication_prompt(
                        global_task=global_task,
                        local_observation=observation,
                    )
                ),
                "submit_prompt": task_adapter.format_python_submit_prompt(
                    global_task=global_task,
                    local_observation=observation,
                ),
            }
            for agent_id, observation in enumerate(observations)
        ]
    else:
        agents = [
            {
                "agent_id": agent_id,
                "local_prompt": task_adapter.format_protocol_init_prompt(
                    global_task=global_task,
                    local_observation=observation,
                ),
            }
            for agent_id, observation in enumerate(observations)
        ]
    describe = getattr(task_adapter, "describe_task", None)
    task_description = describe() if callable(describe) else "Multi-agent task."
    return {
        "execution_contract_version": cfg.python_execution_contract_version,
        "worker_contract": worker_contract,
        "task_description": task_description,
        "information_goal": getattr(cfg, "silo_eval_mode", "sink") or "sink",
        "selected_primary": 0,
        "n_agents": n_agents,
        "max_rounds": cfg.max_rounds,
        "max_parallel_agents": max(1, int(cfg.max_parallel_agents)),
        "budgets": {
            "max_model_calls": cfg.python_max_model_calls,
            "max_completion_tokens": cfg.python_max_completion_tokens,
            "max_messages": cfg.python_max_messages,
        },
        "worker_llm": {
            "provider": cfg.llm_provider,
            "model_name": cfg.model_name,
            "base_url": cfg.base_url,
            "api_key_env": cfg.api_key_env,
            "temperature": cfg.temperature,
            "request_timeout": (
                float(cfg.request_timeout) if cfg.request_timeout > 0 else None
            ),
        },
        "agents": agents,
    }


def _resolved_python_execution_timeout(cfg: RunConfig, *, n_agents: int) -> float:
    """Return a whole-program wall budget that cannot undercut normal LLM waves.

    A generated program is synchronous between logical rounds, but Agent calls
    inside one round may overlap. The automatic budget therefore counts the
    maximum number of parallel waves per round and gives each wave one complete
    per-request allowance plus a small process/setup margin.
    """
    configured = cfg.python_execution_timeout
    if configured is not None:
        if float(configured) <= 0:
            raise ValueError("python_execution_timeout must be positive")
        return float(configured)
    # message_only_v2's immutable scaffold guarantees complete_batch. Older
    # worker contracts still permit scalar complete calls, so their automatic
    # timeout must conservatively budget a sequential Agent wave.
    parallel_agents = 1
    if getattr(cfg, "python_worker_contract", "action_json_v1") == "message_only_v2":
        parallel_agents = min(
            max(1, int(cfg.max_parallel_agents)),
            max(1, int(n_agents)),
        )
    waves_per_round = ceil(max(1, int(n_agents)) / parallel_agents)
    per_request = (
        float(cfg.request_timeout) if float(cfg.request_timeout) > 0 else 120.0
    )
    return max(
        120.0,
        float(max(1, int(cfg.max_rounds)) * waves_per_round) * per_request + 30.0,
    )


def _plan_python_generate(
    cfg: RunConfig,
    *,
    instance: BenchmarkInstance,
    n_agents: int,
    task_adapter: Any,
    global_task: dict[str, Any],
    client: LLMClient,
    skill_bank: SkillBank | None = None,
) -> tuple[PythonCodePlanningResult, dict[str, Any]]:
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    innovation_branch = getattr(cfg, "python_innovation_branch", None)
    parent_skill_id = getattr(cfg, "python_parent_skill_id", None)
    context_exposed = bool(innovation_branch and parent_skill_id)
    clean_pythongen = bool(getattr(cfg, "clean_pythongen", True)) and not context_exposed
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=(
            cfg.python_gen_temperature
            if cfg.python_gen_temperature is not None
            else cfg.temperature
        ),
        replay_first=bool(getattr(cfg, "replay_first", False)),
        max_parallel_agents=max(1, int(cfg.max_parallel_agents)),
        python_repair_attempts=cfg.python_repair_attempts,
        python_execution_timeout=_resolved_python_execution_timeout(
            cfg,
            n_agents=n_agents,
        ),
        python_cpu_seconds=cfg.python_cpu_seconds,
        python_memory_mb=cfg.python_memory_mb,
        python_max_output_bytes=cfg.python_max_output_bytes,
        python_dry_run=cfg.python_dry_run,
        python_ast_policy_version=cfg.python_ast_policy_version,
        python_execution_contract_version=cfg.python_execution_contract_version,
        python_worker_contract=getattr(
            cfg, "python_worker_contract", "action_json_v1"
        ),
        python_max_rounds=cfg.max_rounds,
        python_max_model_calls=cfg.python_max_model_calls,
        python_max_completion_tokens=cfg.python_max_completion_tokens,
        python_max_messages=cfg.python_max_messages,
        python_innovation_branch=innovation_branch,
        python_parent_skill_id=parent_skill_id,
        python_architect_context_enabled=context_exposed,
        python_exposed_insight_ids=list(
            getattr(cfg, "python_exposed_insight_ids", ()) or ()
        ),
        failure_feedback_enabled=(
            getattr(cfg, "failure_policy", "legacy_drop") == "honest_v2"
        ),
        role_llm_profiles=(
            RoleLLMProfiles(
                emperor=RoleLLMConfig(
                    platform=cfg.llm_provider,
                    model_name=cfg.planner_model_name,
                )
            )
            if getattr(cfg, "planner_model_name", None)
            else None
        ),
        information_goal=goal,
        leakage_audit=True,
        leakage_allowed_tokens=(
            ["one_peer", "distance-doubling", "pow2", "exponential"]
            if context_exposed
            else []
        ),
    )
    request = PlannerRequest(
        task_family=("silo" if instance.benchmark == "silo_bench" else instance.benchmark),
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name(cfg.objective),
        planner_mode="python_generate",
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        information_goal=goal,
        provenance_allowlist=(
            list(CLEAN_PYTHON_PROVENANCE)
            if clean_pythongen
            else None
        ),
        python_worker_contract=getattr(
            cfg, "python_worker_contract", "action_json_v1"
        ),
    )
    payload = _build_python_execution_payload(
        instance=instance,
        cfg=cfg,
        task_adapter=task_adapter,
        global_task=global_task,
        n_agents=n_agents,
    )
    artifacts_dir = _python_artifacts_dir(cfg, instance)
    result = plan_and_execute_python(
        request=request,
        runtime=runtime,
        skill_bank=skill_bank if skill_bank is not None else SkillBank(),
        task_adapter=task_adapter,
        execution_payload=payload,
        output_dir=artifacts_dir,
        llm_client=client,
    )
    return result, {
        "planner_mode": "python_generate",
        "python_artifacts_dir": str(artifacts_dir),
        "program_sha256": python_source_sha256(result.source),
        "worker_contract": getattr(
            cfg, "python_worker_contract", "action_json_v1"
        ),
        "max_parallel_agents": max(1, int(cfg.max_parallel_agents)),
        "python_execution_timeout": _resolved_python_execution_timeout(
            cfg,
            n_agents=n_agents,
        ),
        "provenance": result.provenance,
        "planner_model_calls": result.planner_model_calls,
        "repair_model_calls": result.repair_model_calls,
        "selected_skill_id": result.selected_skill_id,
        "clean_pythongen": clean_pythongen,
        "python_innovation_strategy": (
            result.innovation_metadata.get("strategy")
        ),
        "python_parent_skill_id": result.innovation_metadata.get(
            "parent_skill_id"
        ),
        "python_exposed_insight_ids": result.innovation_metadata.get(
            "exposed_insight_ids", []
        ),
        "python_used_insight_ids": result.innovation_metadata.get(
            "used_insight_ids", []
        ),
        "python_mutation_provenance": result.innovation_metadata,
    }


def _run_python_generate(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    task_adapter: Any,
    global_task: dict[str, Any],
    client: LLMClient,
    motif_stats: dict[str, dict] | None,
    skill_bank: SkillBank | None,
) -> ScoreResult:
    del motif_stats  # Python code has no static topology motif prior.
    n_agents = cfg.n_agents or instance.n_agents
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    try:
        planning, extra = _plan_python_generate(
            cfg,
            instance=instance,
            n_agents=n_agents,
            task_adapter=task_adapter,
            global_task=global_task,
            client=client,
            skill_bank=skill_bank,
        )
    except PythonGenerationError as exc:
        return ScoreResult(
            success=False,
            partial=0.0,
            n_messages=0,
            n_model_calls=0,
            tokens=0,
            final_answer=None,
            extra={
                "case_id": instance.case_id,
                "planner": True,
                "planner_mode": "python_generate",
                "topology": None,
                "objective": cfg.objective,
                "python_generation_failed": exc.reason,
                "python_failure_category": exc.error_type,
                "python_artifacts_dir": (
                    str(exc.artifacts_dir) if exc.artifacts_dir else None
                ),
                "program_validity": 0.0,
                "silo_eval_mode": goal,
                "information_goal": goal,
                "provenance": "llm_generated_python",
            },
        )
    return _score_python_execution(
        planning,
        instance=instance,
        cfg=cfg,
        task_adapter=task_adapter,
        global_task=global_task,
        extra={
            "case_id": instance.case_id,
            "planner": True,
            "topology": "python:generated",
            "objective": cfg.objective,
            "program_validity": 1.0,
            "silo_eval_mode": goal,
            **extra,
        },
    )


def _score_python_execution(
    planning: PythonCodePlanningResult,
    *,
    instance: BenchmarkInstance,
    cfg: RunConfig,
    task_adapter: Any,
    global_task: dict[str, Any],
    extra: dict[str, Any],
) -> ScoreResult:
    execution = planning.execution
    output = execution.output
    if output is None:
        raise RuntimeError("successful Python planning result lacks output")
    n_agents = cfg.n_agents or instance.n_agents
    answers_by_id = {item.agent_id: item.answer for item in output.submissions}
    answers = [answers_by_id.get(agent_id) for agent_id in range(n_agents)]
    knowledge = [set(items) for items in execution.final_knowledge]
    coverage = coverage_by_agent(knowledge)
    usage = execution.authoritative_usage
    density = paper_communication_density(len(output.messages), n_agents)
    paper_c = paper_token_consumption(
        int(usage.completion_tokens),
        int(output.rounds_executed),
    )
    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    if goal == "all_agents":
        expected_outputs = private_expected_outputs(global_task) or (
            instance.meta.get("expected_outputs") or []
        )
        if len(expected_outputs) != n_agents:
            expected_outputs = [instance.ground_truth for _ in range(n_agents)]
        paper = evaluate_paper_submissions(
            case_id=instance.case_id,
            answers=answers,
            expected_outputs=list(expected_outputs),
            submitted_rounds=[
                item.submitted_round
                for item in sorted(output.submissions, key=lambda item: item.agent_id)
            ],
        )
        correct = list(paper["per_agent_correct"])
        success = n_agents > 0 and all(correct)
        partial = float(paper["paper_P"])
        final_answer = answers[0] if answers else None
        extra.update(
            {
                "information_goal": "all_agents",
                "per_agent_answers": paper["per_agent_answers"],
                "per_agent_correct": correct,
                "per_agent_partial": paper["per_agent_partial"],
                "per_agent_submissions": paper["per_agent_submissions"],
                "paper_S": float(paper["paper_S"]),
                "paper_P": partial,
                "all_agents_exact": success,
                "information_coverage_by_agent": coverage,
                "mean_information_coverage": (
                    sum(coverage) / len(coverage) if coverage else 0.0
                ),
                "min_information_coverage": min(coverage) if coverage else 0.0,
                "all_agents_full_information": bool(
                    coverage and min(coverage) >= 1.0
                ),
            }
        )
    else:
        sink_id = 0
        answer = answers[sink_id] if answers else None
        if instance.segmented:
            expected_outputs = private_expected_outputs(global_task) or (
                instance.meta.get("expected_outputs") or []
            )
            expected = expected_outputs[sink_id] if expected_outputs else None
            success = answer is not None and canonical_answer(answer) == canonical_answer(
                expected
            )
            partial = float(
                silo_partial_score(
                    answer,
                    expected,
                    global_task.get("output_type", "scalar"),
                )
            )
        else:
            scored = task_adapter.score_protocol_answer(answer, global_task)
            success = bool(scored.get("exact_match", False))
            partial = float(scored.get("partial", 0.0))
        final_answer = answer
        extra.update(
            {
                "information_goal": "sink",
                "sink_id": sink_id,
                "sink_exact": success,
                "sink_partial": partial,
                "sink_information_coverage": (
                    coverage[sink_id] if coverage else 0.0
                ),
            }
        )
    extra.update(
        {
            "paper_C": paper_c,
            "paper_D": density,
            "communication_density": density,
            "rounds_executed": output.rounds_executed,
            "worker_model_calls": usage.model_calls,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "python_messages": [
                message.model_dump(mode="json") for message in output.messages
            ],
            "python_submissions": [
                submission.model_dump(mode="json")
                for submission in output.submissions
            ],
            "python_submit_barrier": execution.ledger.get("submit_barrier"),
        }
    )
    return ScoreResult(
        success=bool(success),
        partial=float(partial),
        n_messages=len(output.messages),
        n_model_calls=int(usage.model_calls),
        tokens=int(usage.prompt_tokens) + int(usage.completion_tokens),
        final_answer=final_answer,
        extra=extra,
    )


# 【职责】跑一个实例并评分——引擎对外主入口。
# - cfg.use_planner 为真走 QueenBee planner + 通用 ProtocolRunner；否则走 planner-OFF 的
#   SynchronousRunner 路径(行为不变)。
# - motif_stats 转发给 graph_generate 规划器以激活结构母题信用先验(其它路径失效)。
# - skill_bank(仅 graph_generate)是皇帝据以设计 DAG 的进化 design_insights 之库；默认空库
#   (冷启动生成，即普通 graphgen 行为)。
def run_instance(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None = None,
    motif_stats: dict[str, dict] | None = None,
    skill_bank: SkillBank | None = None,
) -> ScoreResult:
    """Run one instance and score it.

    ``cfg.use_planner`` selects the QueenBee planner + generalized ProtocolRunner;
    otherwise the planner-OFF SynchronousRunner path runs unchanged. ``motif_stats``
    is forwarded to the graph_generate planner so accumulated motif evidence can
    activate the structural-motif credit prior (inert on the other paths).
    ``skill_bank`` (graph_generate only) is the bank whose evolved design_insights
    the emperor uses to DESIGN the DAG; defaults to an empty bank (cold generation,
    the plain graphgen behaviour).
    """
    if cfg.use_planner:
        return _run_planner(
            instance,
            cfg,
            llm_client=llm_client,
            motif_stats=motif_stats,
            skill_bank=skill_bank,
        )

    goal = getattr(cfg, "silo_eval_mode", "sink") or "sink"
    task_adapter = BenchmarkTaskAdapter(instance, information_goal=goal)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents

    experiment_config = ExperimentConfig(
        topology_name=cfg.topology,
        n_agents=n_agents,
        max_rounds=cfg.max_rounds,
        seed=cfg.seed,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        temperature=cfg.temperature,
        consensus_threshold=cfg.consensus_threshold,
        final_accept_threshold=cfg.final_accept_threshold,
        max_parallel_agents=max(1, int(cfg.max_parallel_agents)),
        trace_enabled=False,
    )
    client = llm_client or _build_llm_client(cfg)
    result = SynchronousRunner(
        config=experiment_config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=client,
    ).run()

    # 中文：分级 partial 归 masbench(exp_graph 不动)。planner-OFF 的最终答案是规范化键，
    #   由它+ground truth 重算 partial。
    # masbench owns the graded partial (exp_graph untouched). The planner-OFF
    # final answer is the canonical key; recompute partial from it + ground truth.
    extra = {
        "case_id": instance.case_id,
        "topology": cfg.topology,
        "stop_reason": result.stop_reason,
        "consensus_reached": result.final_result.consensus_reached,
        "aggregation_method": result.final_result.aggregation_method,
        "silo_eval_mode": goal,
    }
    if goal == "all_agents":
        # 中文：all_agents：逐 agent 独立判分（分段任务对各自分段、普通任务对同一全局
        #   答案），主 success = 全员正确；旧的投票/共识准确率不再作数。
        # all_agents: grade every agent independently; the main success is
        # all_agents_exact -- the legacy voted accuracy never counts here.
        adapter = _protocol_adapter(instance, information_goal=goal)
        expected_outputs = private_expected_outputs(global_task) or (
            instance.meta.get("expected_outputs") or []
        )
        per_agent_correct: list[bool] = []
        partials: list[float] = []
        output_type = global_task.get("output_type", "scalar")
        for agent_id in range(n_agents):
            answer = _agent_answer(result, adapter, agent_id)
            if instance.segmented:
                expected = (
                    expected_outputs[agent_id]
                    if agent_id < len(expected_outputs)
                    else None
                )
                correct = answer is not None and canonical_answer(
                    answer
                ) == canonical_answer(expected)
                partials.append(
                    float(silo_partial_score(answer, expected, output_type))
                )
            else:
                correct = answer is not None and canonical_answer(
                    answer
                ) == private_answer_key(global_task)
                partials.append(
                    float(
                        silo_partial_score(
                            answer, private_answer_key(global_task), output_type
                        )
                    )
                )
            per_agent_correct.append(bool(correct))
        success = n_agents > 0 and all(per_agent_correct)
        partial = sum(partials) / len(partials) if partials else 0.0
        extra["per_agent_correct"] = per_agent_correct
        extra["agent_success_rate"] = (
            sum(per_agent_correct) / n_agents if n_agents else 0.0
        )
        extra["all_agents_exact"] = bool(success)
        extra["information_goal"] = "all_agents"
        if instance.segmented:
            extra["segmented"] = True
    elif instance.segmented:
        # 中文：从最终信念状态逐 agent 评分。SynchronousRunner 的信念模型与协议版一致，故
        #   Silo 协议适配器的 extract_protocol_answer 以同样方式读每个 agent 的答案。
        # Per-agent grading from the final belief states. The synchronous runner
        # belief model matches the protocol one, so the Silo protocol adapter's
        # extract_protocol_answer reads each agent's answer the same way.
        success, partial, per_agent_correct = _score_segmented(
            result, instance, _protocol_adapter(instance), global_task
        )
        extra["segmented"] = True
        extra["per_agent_correct"] = per_agent_correct
    else:
        success = bool(result.metrics.final_accuracy)
        partial = _partial_score(result.final_result.final_key, global_task)
    return ScoreResult(
        success=success,
        partial=partial,
        n_messages=_count_messages(result),
        n_model_calls=int(result.metrics.total_model_calls),
        tokens=int(result.metrics.total_token_cost),
        final_answer=result.final_result.final_key,
        extra=extra,
    )
