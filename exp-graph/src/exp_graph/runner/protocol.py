"""Protocol runner that preserves AgentState while changing communication schedule."""
# ============================================================
# 【模块导读】协议执行器：保持 AgentState 数据结构不变，仅更换通信调度。
# 核心 ProtocolRunner：初始化各 agent 信念 -> 按协议调度(逐步通信计划)
# 逐通信步投递发件箱 -> 接收方合并（确定性或 LLM）-> 终局聚合与打分。
# ProtocolRunnerConfig 为运行参数；ProtocolStepLog 记录单个通信步；
# ProtocolExperimentResult 汇总全程结果与 total_* 计量字段。
# ============================================================

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from exp_graph.agents.schemas import AgentState, BeliefState, make_initial_agent_state
# 注：cf_final / cf_protocol 等 cf_* import 是 Count-Frequency 传统任务的字节兼容路径，Silo 不经过。
from exp_graph.aggregator.cf_final import CFProtocolFinalResult, run_cf_final_aggregation
from exp_graph.configs.runtime import ExperimentConfig
from exp_graph.llm.base import LLMClient, LLMResponse, combine_usage
from exp_graph.llm.factory import create_llm_client
from exp_graph.llm.parser import parse_belief_state
from exp_graph.llm.retry import build_json_retry_prompt
from exp_graph.messaging import OutboxMessage
from exp_graph.metrics.cf_protocol import (
    CFAgentStepMetric,
    CFGlobalStepMetric,
    build_cf_step_metrics,
)
from exp_graph.protocols import (
    CommunicationStep,
    ProtocolGraphSpec,
    build_protocol_schedule,
    build_protocol_schedule_from_spec,
)
from exp_graph.aggregator.protocol_final import ProtocolFinalResult
from exp_graph.metrics.protocol import ProtocolAgentStepMetric, ProtocolGlobalStepMetric
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter
from exp_graph.tracing import AgentStepTrace, append_traces_jsonl, reset_trace_jsonl


# 【职责】一次合并/初始化调用的内部结果载体（确定性与 LLM 两条路径共用）。
@dataclass
class _MergeOutcome:
    # 合并后的新信念状态（LLM 成功解析的结果，或确定性/兜底结果）
    belief_state: BeliefState
    # 本次调用（含重试）合并后的 LLM 响应；确定性路径为 None
    llm_response: LLMResponse | None = None
    # 首次调用使用的原始提示词（追踪用）
    prompt: str = ""
    # 最后一次解析/校验错误信息；成功时为 None
    parse_error: str | None = None
    # 是否触发了确定性兜底
    fallback_applied: bool = False


# 【职责】有限通信协议实验的运行时配置。
class ProtocolRunnerConfig(BaseModel):
    """Runtime config for finite communication-protocol experiments."""

    # 命名拓扑；protocol_spec 为 None 时按它编译协议调度(逐步通信计划)
    topology_name: str = "chain"
    # 士兵(执行 agent)数量
    n_agents: int = 8
    # 随机种子（random_dag 等拓扑构造与默认 run_id 使用）
    seed: int = 0
    # LLM 模型名（纯确定性模式下不会用到）
    model_name: str = "deterministic"
    # 合并模式：deterministic=确定性 / llm_belief_merge=LLM+确定性校验 / llm_full_merge=LLM 全量
    merge_mode: Literal[
        "deterministic",
        "llm_belief_merge",
        "llm_full_merge",
    ] = "deterministic"
    # 初始化模式：deterministic=确定性本地解 / llm_local_solve=LLM 本地求解
    init_mode: Literal["deterministic", "llm_local_solve"] = "deterministic"
    # LLM 提供方（"auto"=自动选择）
    llm_provider: str = "auto"
    # LLM 采样温度（默认 0.0 便于复现）
    temperature: float = 0.0
    # JSON 解析失败后的额外重试次数（总调用数 = 该值 + 1）
    json_retry_attempts: int = 2
    # 重试耗尽后是否允许确定性兜底修复；False 则直接抛错
    allow_deterministic_repair: bool = True
    # 单步内 LLM 调用（初始化/合并）的并行上限
    max_parallel_agents: int = 1
    # 是否记录逐步追踪
    trace_enabled: bool = False
    # 追踪中是否保存提示词全文
    save_prompts: bool = True
    # 是否把追踪保留在内存结果对象中
    retain_traces: bool = False
    # 追踪 JSONL 落盘目录（None=不落盘）
    trace_dir: str | None = None
    # star 拓扑的中心 agent 编号
    star_center: int = 0
    # star 拓扑是否附加中心回广播步
    include_star_broadcast: bool = False
    # 平均聚合纳入 agent 的最小覆盖率门槛（CF 终局聚合使用）
    average_include_min_coverage: float = 1.0
    # 主结果选择方式：topology_default(按拓扑默认)/vote(投票)/average(平均)
    selected_primary: Literal["topology_default", "vote", "average"] = "topology_default"
    # 是否打印详细事件日志
    verbose_events: bool = False
    # 运行 ID（缺省自动生成）
    run_id: str | None = None
    # 皇帝(规划 LLM)产出的协议规格；非 None 时优先于 topology_name
    protocol_spec: ProtocolGraphSpec | None = None
    # LLM 角色摘要（随配置记录的附加信息）
    llm_role_summary: dict[str, object] = Field(default_factory=dict)
    # 中文：M9——为 True 时，把该步可选的、面向接收方的 instruction 前置到该步的
    #   LLM 合并提示词。默认 False 且命名拓扑均不带指令，故除非同时提供该开关和
    #   带指令的规格，否则既有行为（含 CF）字节级一致。
    # M9: when True, a step's optional receiver-facing `instruction` is
    # prepended to the LLM merge prompt for that step. Default False and no
    # named topology carries instructions, so existing behavior (CF included)
    # is byte-identical unless BOTH the flag and instruction-bearing specs
    # are supplied.
    enable_step_instructions: bool = False

    # 【职责】从传统 ExperimentConfig 换算出协议执行器配置，overrides 可覆盖任意字段。
    @classmethod
    def from_experiment_config(
        cls,
        config: ExperimentConfig,
        **overrides,
    ) -> "ProtocolRunnerConfig":
        data = {
            "topology_name": config.topology_name,
            "n_agents": config.n_agents,
            "seed": config.seed,
            "model_name": config.model_name,
            "init_mode": getattr(config, "init_mode", "deterministic"),
            "llm_provider": config.llm_provider,
            "temperature": config.temperature,
            "json_retry_attempts": config.json_retry_attempts,
            "trace_enabled": config.trace_enabled,
            "save_prompts": config.save_prompts,
            "retain_traces": config.retain_traces,
            "trace_dir": config.trace_dir,
            "run_id": config.run_id,
            "verbose_events": getattr(config, "verbose_events", False),
        }
        data.update(overrides)
        return cls(**data)


# 【职责】单个协议通信步的执行日志。
class ProtocolStepLog(BaseModel):
    """One protocol communication step."""

    # 通信步编号
    step_idx: int
    # 调度中的步骤描述
    description: str
    # 计划内的有向传输边 (src, dst) 列表
    transmissions: list[tuple[int, int]] = Field(default_factory=list)
    # 实际投递的消息数
    sent_messages: int
    # 实际发送过消息的 agent 编号（升序）
    active_senders: list[int] = Field(default_factory=list)
    # 实际接收过消息的 agent 编号（升序）
    active_receivers: list[int] = Field(default_factory=list)


# 【职责】一次有限协议运行的完整结果（逐步日志、双轨指标与 total_* 计量字段）。
class ProtocolExperimentResult(BaseModel):
    """Full result of one finite protocol run."""

    run_id: str
    # 本次运行的配置快照
    config: ProtocolRunnerConfig
    # 全局任务的紧凑副本（剔除 array 大字段）
    global_task: dict
    # 实际执行的协议调度(逐步通信计划)
    schedule: list[CommunicationStep] = Field(default_factory=list)
    # 逐通信步执行日志
    step_logs: list[ProtocolStepLog] = Field(default_factory=list)
    # 逐 agent 步级指标（CF 专用或通用两种类型，Silo 走通用）
    agent_step_metrics: list[CFAgentStepMetric | ProtocolAgentStepMetric] = Field(
        default_factory=list
    )
    # 逐步全局指标（CF 专用或通用两种类型）
    global_step_metrics: list[CFGlobalStepMetric | ProtocolGlobalStepMetric] = Field(
        default_factory=list
    )
    # 结束时全体 agent 的最终状态
    final_agent_states: list[AgentState] = Field(default_factory=list)
    # 终局聚合结果（CF 专用或通用 ProtocolFinalResult）
    final_result: CFProtocolFinalResult | ProtocolFinalResult
    # 通信步总数
    total_steps: int
    # 实际投递的消息总数
    total_messages: int
    # LLM 调用总数（含重试）
    total_model_calls: int = 0
    # 提示词 token 总数
    total_prompt_tokens: int = 0
    # 补全 token 总数
    total_completion_tokens: int = 0
    # 重试总次数（每 agent 每步超出首次调用的次数之和）
    total_retry_attempts: int = 0
    # 确定性兜底触发总次数
    total_deterministic_fallbacks: int = 0
    # 内存中保留的逐步追踪（retain_traces=True 时）
    agent_step_traces: list[AgentStepTrace] = Field(default_factory=list)
    # 追踪 JSONL 落盘路径（未启用为 None）
    trace_path: str | None = None

    # 【职责】导出扁平摘要字典：CF 结果走字节兼容分支，其余任务走通用证据键分支。
    def to_summary_dict(self) -> dict:
        # 中文：Count-Frequency 路径：与原始 CF 摘要字节一致（Silo 不经过此分支）。
        # Count-frequency path: byte-identical to the original CF summary.
        if isinstance(self.final_result, CFProtocolFinalResult):
            return {
                "Task": "count_frequency_protocol",
                "Topology": self.config.topology_name,
                "Agents": self.config.n_agents,
                "ArraySize": int(self.global_task["array_length"]),
                "ValueMin": int(self.global_task["value_min"]),
                "ValueMax": int(self.global_task["value_max"]),
                "Seed": self.config.seed,
                "MergeMode": self.config.merge_mode,
                "InitMode": self.config.init_mode,
                "TotalSteps": self.total_steps,
                "TotalMessages": self.total_messages,
                "TotalModelCalls": self.total_model_calls,
                "TotalPromptTokens": self.total_prompt_tokens,
                "TotalCompletionTokens": self.total_completion_tokens,
                "TotalRetryAttempts": self.total_retry_attempts,
                "TotalDeterministicFallbacks": self.total_deterministic_fallbacks,
                "AggregationMethod": self.final_result.aggregation_method,
                "SelectedPrimary": self.final_result.selected_primary,
                "FinalRMSE": self.final_result.rmse,
                "FinalNormalizedL1Error": self.final_result.normalized_l1_error,
                "FinalExactMatch": self.final_result.exact_match,
                "VoteRMSE": self.final_result.vote.rmse,
                "VoteNormalizedL1Error": self.final_result.vote.normalized_l1_error,
                "VoteTopRatio": self.final_result.vote.top_ratio,
                "AverageRMSE": (
                    self.final_result.average.rmse
                    if self.final_result.average is not None
                    else None
                ),
                "AverageNormalizedL1Error": (
                    self.final_result.average.normalized_l1_error
                    if self.final_result.average is not None
                    else None
                ),
                "AverageIncludedAgents": (
                    len(self.final_result.average.included_agents)
                    if self.final_result.average is not None
                    else 0
                ),
                "AnswerAgentIds": self.final_result.answer_agent_ids,
                "VoteAverageDisagreementRMSE": (
                    self.final_result.vote_average_disagreement_rmse
                ),
                "PrimaryMetric": self.final_result.rmse,
                "PrimaryMetricName": "rmse",
                "FinalKey": self.final_result.final_key,
            }
        # 中文：通用任务路径（Plan 2 任务 5 将通用证据键正式化）；Silo-Bench 走此分支。
        # Generic task path (Plan 2 Task 5 formalizes the generic evidence keys).
        return {
            "Task": str(self.global_task.get("task_name", "protocol")),
            "Topology": self.config.topology_name,
            "Agents": self.config.n_agents,
            "Seed": self.config.seed,
            "MergeMode": self.config.merge_mode,
            "InitMode": self.config.init_mode,
            "TotalSteps": self.total_steps,
            "TotalMessages": self.total_messages,
            "TotalModelCalls": self.total_model_calls,
            "TotalPromptTokens": self.total_prompt_tokens,
            "TotalCompletionTokens": self.total_completion_tokens,
            "TotalRetryAttempts": self.total_retry_attempts,
            "TotalDeterministicFallbacks": self.total_deterministic_fallbacks,
            "AggregationMethod": self.final_result.aggregation_method,
            "SelectedPrimary": self.final_result.selected_primary,
            "PrimaryMetric": float(getattr(self.final_result, "primary_metric", 0.0)),
            "PrimaryMetricName": str(
                self.global_task.get("primary_metric_name", "primary")
            ),
            "FinalExactMatch": bool(self.final_result.exact_match),
            "VoteTopRatio": getattr(self.final_result, "top_ratio", None),
            "AnswerAgentIds": self.final_result.answer_agent_ids,
            "FinalKey": self.final_result.final_key,
        }


# 【职责】在既有 agent 状态之上执行拓扑协议调度：初始化 -> 逐步投递并合并 -> 终局聚合。
class ProtocolRunner:
    """Run topology protocol schedules over existing agent states."""

    # 【职责】保存配置/任务适配器/全局任务；需要 LLM 而未注入客户端时按提供方自动创建。
    def __init__(
        self,
        *,
        config: ProtocolRunnerConfig,
        task_adapter: ProtocolTaskAdapter,
        global_task: dict,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.task_adapter = task_adapter
        self.global_task = global_task
        self.llm_client = llm_client
        if self._needs_llm() and self.llm_client is None:
            self.llm_client = create_llm_client(self.config.llm_provider)

    # 【职责】主循环：完成一次协议运行的全过程。
    # - 编译调度：有 protocol_spec 用规格编译，否则按命名拓扑构建。
    # - 初始化各 agent 信念（确定性或 LLM 本地求解），先记 phase=initial 基线指标。
    # - 逐通信步：把发送方上一步的发件箱投递到接收方收件箱 -> 合并 -> 刷新发件箱，
    #   同时累计消息/模型调用/token/重试/兜底计量，记录步日志与步级指标。
    # - 调度跑完后由任务适配器 finalize_protocol 终局聚合，组装完整结果返回。
    def run(self) -> ProtocolExperimentResult:
        run_id = self._make_run_id()
        if self.config.protocol_spec is not None:
            schedule = build_protocol_schedule_from_spec(self.config.protocol_spec)
        else:
            schedule = build_protocol_schedule(
                self.config.topology_name,
                self.config.n_agents,
                star_center=self.config.star_center,
                include_star_broadcast=self.config.include_star_broadcast,
                random_seed=self.config.seed,
            )
        step_logs: list[ProtocolStepLog] = []
        agent_step_metrics: list[CFAgentStepMetric] = []
        global_step_metrics: list[CFGlobalStepMetric] = []
        total_messages = 0
        total_model_calls = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_retry_attempts = 0
        total_deterministic_fallbacks = 0
        agent_step_traces: list[AgentStepTrace] = []
        trace_path = None
        if self.config.trace_enabled and self.config.trace_dir:
            trace_path = reset_trace_jsonl(
                Path(self.config.trace_dir) / f"{run_id}.jsonl"
            )
        self._log_event(
            "run-start",
            (
                f"run={run_id} topology={self.config.topology_name} "
                f"agents={self.config.n_agents} init_mode={self.config.init_mode} "
                f"merge_mode={self.config.merge_mode} "
                f"steps={len(schedule)}"
            ),
        )
        (
            agent_states,
            init_traces,
            init_model_calls,
            init_prompt_tokens,
            init_completion_tokens,
            init_retry_attempts,
            init_deterministic_fallbacks,
        ) = self._initialize_agent_states(run_id=run_id)
        total_model_calls += init_model_calls
        total_prompt_tokens += init_prompt_tokens
        total_completion_tokens += init_completion_tokens
        total_retry_attempts += init_retry_attempts
        total_deterministic_fallbacks += init_deterministic_fallbacks
        if init_traces:
            if self.config.retain_traces:
                agent_step_traces.extend(init_traces)
            if trace_path is not None:
                append_traces_jsonl(init_traces, trace_path)

        initial_agent_metrics, initial_global_metric = self._record_metrics(
            agent_states=agent_states,
            step_idx=-1,
            phase="initial",
            send_counts=Counter(),
            receive_counts=Counter(),
        )
        agent_step_metrics.extend(initial_agent_metrics)
        global_step_metrics.append(initial_global_metric)

        for step in schedule:
            self._log_event(
                "step",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"description={step.description} "
                    f"scheduled_transmissions={len(step.transmissions)}"
                ),
            )
            previous_outboxes = {
                agent_id: state.outbox
                for agent_id, state in enumerate(agent_states)
            }
            inbox_by_receiver: dict[int, list[OutboxMessage]] = defaultdict(list)
            send_counts: Counter[int] = Counter()
            receive_counts: Counter[int] = Counter()
            for src, dst in step.transmissions:
                outbox = previous_outboxes.get(src)
                if outbox is None:
                    self._log_event(
                        "message-skip",
                        (
                            f"run={run_id} step={step.step_idx} "
                            f"round={step.step_idx + 1} {src} -> {dst} "
                            "skipped=no_outbox"
                        ),
                    )
                    continue
                inbox_by_receiver[dst].append(outbox)
                send_counts[src] += 1
                receive_counts[dst] += 1
                self._log_event(
                    "message",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} {src} -> {dst}"
                    ),
                )

            total_messages += sum(send_counts.values())
            next_states = list(agent_states)
            round_traces: list[AgentStepTrace] = []
            outcomes = self._process_receivers(
                agent_states=agent_states,
                inbox_by_receiver=inbox_by_receiver,
                step=step,
                run_id=run_id,
            )
            for receiver_id, outcome in outcomes.items():
                old_state = agent_states[receiver_id]
                new_belief = outcome.belief_state
                new_outbox = OutboxMessage.from_belief_state(
                    agent_id=receiver_id,
                    round_idx=step.step_idx,
                    belief_state=new_belief,
                )
                next_states[receiver_id] = old_state.model_copy(
                    update={
                        "belief_state": new_belief,
                        "inbox": [],
                        "outbox": new_outbox,
                    }
                )
                if outcome.llm_response is not None:
                    usage = outcome.llm_response.usage
                    total_model_calls += int(usage.model_calls)
                    total_prompt_tokens += int(usage.prompt_tokens)
                    total_completion_tokens += int(usage.completion_tokens)
                    total_retry_attempts += max(0, int(usage.model_calls) - 1)
                    if outcome.fallback_applied:
                        total_deterministic_fallbacks += 1
                    if self.config.trace_enabled:
                        trace = self._build_trace(
                            run_id=run_id,
                            step=step,
                            receiver_id=receiver_id,
                            inbox=inbox_by_receiver[receiver_id],
                            outcome=outcome,
                            outbox=new_outbox,
                        )
                        if self.config.retain_traces:
                            agent_step_traces.append(trace)
                        if trace_path is not None:
                            round_traces.append(trace)

            agent_states = next_states
            if trace_path is not None and round_traces:
                append_traces_jsonl(round_traces, trace_path)
            self._log_event(
                "step-done",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"delivered_messages={sum(send_counts.values())} "
                    f"active_senders={sorted(send_counts)} "
                    f"active_receivers={sorted(receive_counts)}"
                ),
            )
            step_logs.append(
                ProtocolStepLog(
                    step_idx=step.step_idx,
                    description=step.description,
                    transmissions=step.transmissions,
                    sent_messages=sum(send_counts.values()),
                    active_senders=sorted(send_counts),
                    active_receivers=sorted(receive_counts),
                )
            )
            step_agent_metrics, step_global_metric = self._record_metrics(
                agent_states=agent_states,
                step_idx=step.step_idx,
                phase="after_step",
                send_counts=send_counts,
                receive_counts=receive_counts,
            )
            agent_step_metrics.extend(step_agent_metrics)
            global_step_metrics.append(step_global_metric)

        final_result = self.task_adapter.finalize_protocol(
            agent_states=agent_states,
            global_task=self.global_task,
            topology_name=self.config.topology_name,
            star_center=self.config.star_center,
            average_include_min_coverage=self.config.average_include_min_coverage,
            selected_primary=self.config.selected_primary,
            answer_agent_ids_override=self._metadata_answer_agent_ids(),
        )
        final_metric_log = (
            f"final_rmse={final_result.rmse:.6f}"
            if isinstance(final_result, CFProtocolFinalResult)
            else f"final_primary={final_result.primary_metric:.6f}"
        )
        self._log_event(
            "run-done",
            (
                f"run={run_id} steps={len(schedule)} messages={total_messages} "
                f"model_calls={total_model_calls} retries={total_retry_attempts} "
                f"deterministic_fallbacks={total_deterministic_fallbacks} "
                f"{final_metric_log} exact={final_result.exact_match}"
            ),
        )
        return ProtocolExperimentResult(
            run_id=run_id,
            config=self.config,
            global_task=self._compact_global_task(),
            schedule=schedule,
            step_logs=step_logs,
            agent_step_metrics=agent_step_metrics,
            global_step_metrics=global_step_metrics,
            final_agent_states=agent_states,
            final_result=final_result,
            total_steps=len(schedule),
            total_messages=total_messages,
            total_model_calls=total_model_calls,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_retry_attempts=total_retry_attempts,
            total_deterministic_fallbacks=total_deterministic_fallbacks,
            agent_step_traces=agent_step_traces,
            trace_path=trace_path,
        )

    # 【职责】初始化全体 agent：切分本地观测(数据分片)后按初始化模式构造初始信念。
    # - deterministic：适配器直接给出信念，零 LLM 计量。
    # - llm_local_solve：逐 agent 调 LLM 本地求解（可按上限并行），返回状态+追踪+五项计量。
    def _initialize_agent_states(
        self,
        *,
        run_id: str,
    ) -> tuple[
        list[AgentState],
        list[AgentStepTrace],
        int,
        int,
        int,
        int,
        int,
    ]:
        observations = self.task_adapter.split_into_local_observations(
            self.global_task,
            self.config.n_agents,
        )
        if self.config.init_mode == "deterministic":
            states = []
            for agent_id, observation in enumerate(observations):
                belief = self.task_adapter.initial_protocol_belief(observation)
                states.append(
                    make_initial_agent_state(
                        local_observation=observation,
                        belief_state=belief,
                        agent_id=agent_id,
                        round_idx=0,
                    )
                )
            return states, [], 0, 0, 0, 0, 0

        if self.config.init_mode != "llm_local_solve":
            raise ValueError(f"unsupported init_mode: {self.config.init_mode}")
        if self.llm_client is None:
            raise RuntimeError("llm_client is required for llm_local_solve init")

        states: list[AgentState | None] = [None] * len(observations)
        traces: list[AgentStepTrace] = []
        total_model_calls = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_retry_attempts = 0
        total_deterministic_fallbacks = 0
        init_step = CommunicationStep(
            step_idx=-1,
            transmissions=[],
            description="llm_local_solve initialization",
        )

        outcomes: dict[int, _MergeOutcome] = {}
        max_workers = min(
            max(1, int(self.config.max_parallel_agents)),
            max(1, len(observations)),
        )
        if max_workers <= 1 or len(observations) <= 1:
            outcomes = {
                agent_id: self._initialize_agent_belief_with_llm(
                    observation=observation,
                    run_id=run_id,
                )
                for agent_id, observation in enumerate(observations)
            }
        else:
            self._log_event(
                "init-parallel",
                (
                    f"run={run_id} agents={len(observations)} "
                    f"max_parallel_agents={max_workers}"
                ),
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._initialize_agent_belief_with_llm,
                        observation=observation,
                        run_id=run_id,
                    ): agent_id
                    for agent_id, observation in enumerate(observations)
                }
                for future in as_completed(futures):
                    outcomes[futures[future]] = future.result()

        for agent_id, observation in enumerate(observations):
            outcome = outcomes[agent_id]
            new_outbox = OutboxMessage.from_belief_state(
                agent_id=agent_id,
                round_idx=0,
                belief_state=outcome.belief_state,
            )
            states[agent_id] = AgentState(
                local_observation=observation,
                belief_state=outcome.belief_state,
                inbox=[],
                outbox=new_outbox,
            )
            if outcome.llm_response is not None:
                usage = outcome.llm_response.usage
                total_model_calls += int(usage.model_calls)
                total_prompt_tokens += int(usage.prompt_tokens)
                total_completion_tokens += int(usage.completion_tokens)
                total_retry_attempts += max(0, int(usage.model_calls) - 1)
                if outcome.fallback_applied:
                    total_deterministic_fallbacks += 1
                if self.config.trace_enabled:
                    traces.append(
                        self._build_trace(
                            run_id=run_id,
                            step=init_step,
                            receiver_id=agent_id,
                            inbox=[],
                            outcome=outcome,
                            outbox=new_outbox,
                        )
                    )

        return (
            [state for state in states if state is not None],
            traces,
            total_model_calls,
            total_prompt_tokens,
            total_completion_tokens,
            total_retry_attempts,
            total_deterministic_fallbacks,
        )

    # 【职责】单个 agent 的 LLM 初始化：调用 -> 解析信念 -> 任务校验；失败按重试提示词重试。
    # - 重试耗尽：允许确定性修复则回落到确定性初始信念并标记兜底，否则抛错。
    def _initialize_agent_belief_with_llm(
        self,
        *,
        observation: dict,
        run_id: str,
    ) -> _MergeOutcome:
        if self.llm_client is None:
            raise RuntimeError("llm_client is required for llm_local_solve init")

        deterministic_belief = self.task_adapter.initial_protocol_belief(observation)
        prompt = self.task_adapter.format_protocol_init_prompt(
            global_task=self.global_task,
            local_observation=observation,
        )
        current_prompt = prompt
        responses: list[LLMResponse] = []
        call_prompts: list[str] = []
        last_error: Exception | None = None
        agent_id = int(observation.get("agent_id", -1))

        for attempt_idx in range(self.config.json_retry_attempts + 1):
            call_prompts.append(current_prompt)
            self._log_event(
                "llm-init-call",
                (
                    f"run={run_id} agent={agent_id} "
                    f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1}"
                ),
            )
            try:
                response = self.llm_client.complete(
                    current_prompt,
                    model_name=self.config.model_name,
                    temperature=self.config.temperature,
                )
            except Exception as exc:
                self._log_event(
                    "llm-init-error",
                    (
                        f"run={run_id} agent={agent_id} "
                        f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1} "
                        f"provider_call_failed={type(exc).__name__}: {exc}"
                    ),
                )
                raise
            responses.append(response)
            try:
                llm_belief = parse_belief_state(response.text)
                belief = self.task_adapter.validate_protocol_initial_belief_state(
                    belief_state=llm_belief,
                    local_observation=observation,
                    global_task=self.global_task,
                )
                combined = self._combine_responses(responses, call_prompts)
                self._log_event(
                    "llm-init-success",
                    (
                        f"run={run_id} agent={agent_id} "
                        f"calls={combined.usage.model_calls} "
                        f"retries={max(0, combined.usage.model_calls - 1)} "
                        f"prompt_tokens={combined.usage.prompt_tokens} "
                        f"completion_tokens={combined.usage.completion_tokens}"
                    ),
                )
                return _MergeOutcome(
                    belief_state=belief,
                    llm_response=combined,
                    prompt=prompt,
                )
            except (ValueError, TypeError, ValidationError) as exc:
                last_error = exc
                if attempt_idx >= self.config.json_retry_attempts:
                    if self.config.allow_deterministic_repair:
                        self._log_event(
                            "init-retry-failed",
                            (
                                f"run={run_id} agent={agent_id} "
                                f"attempts={attempt_idx + 1} "
                                "deterministic_repair=applied "
                                f"last_error={exc}"
                            ),
                        )
                        return _MergeOutcome(
                            belief_state=deterministic_belief,
                            llm_response=self._combine_responses(responses, call_prompts),
                            prompt=prompt,
                            parse_error=str(exc),
                            fallback_applied=True,
                        )
                    self._log_event(
                        "init-retry-failed",
                        (
                            f"run={run_id} agent={agent_id} "
                            f"attempts={attempt_idx + 1} "
                            "deterministic_repair=disabled "
                            f"last_error={exc}"
                        ),
                    )
                    raise ValueError(
                        "LLM failed to return a valid CF local init belief_state "
                        f"after {attempt_idx + 1} call(s). Last error: {exc}"
                    ) from exc
                self._log_event(
                    "init-retry",
                    (
                        f"run={run_id} agent={agent_id} "
                        f"failed_attempt={attempt_idx + 1}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"next_attempt={attempt_idx + 2}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"error={exc}"
                    ),
                )
                current_prompt = build_json_retry_prompt(
                    original_prompt=prompt,
                    invalid_response=response.text,
                    error_message=str(exc),
                    attempt_idx=attempt_idx + 1,
                )

        if self.config.allow_deterministic_repair:
            self._log_event(
                "init-retry-failed",
                (
                    f"run={run_id} agent={agent_id} "
                    "deterministic_repair=applied "
                    f"last_error={last_error}"
                ),
            )
            return _MergeOutcome(
                belief_state=deterministic_belief,
                llm_response=self._combine_responses(responses, call_prompts),
                prompt=prompt,
                parse_error=str(last_error) if last_error else None,
                fallback_applied=True,
            )
        raise ValueError(f"LLM local init failed: {last_error}")

    # 【职责】确定性合并：委托适配器把收件箱并入旧信念（也是 LLM 模式的校验基准与兜底）。
    def _merge_receiver_belief(self, state: AgentState) -> BeliefState:
        return self.task_adapter.merge_protocol_inbox(
            old_belief_state=state.belief_state,
            inbox=state.inbox,
            global_task=self.global_task,
        )

    # 【职责】处理本步全部接收方：确定性合并模式直接计算；LLM 模式按并行上限派发线程池。
    def _process_receivers(
        self,
        *,
        agent_states: list[AgentState],
        inbox_by_receiver: dict[int, list[OutboxMessage]],
        step: CommunicationStep,
        run_id: str,
    ) -> dict[int, _MergeOutcome]:
        if self.config.merge_mode == "deterministic":
            return {
                receiver_id: _MergeOutcome(
                    belief_state=self._merge_receiver_belief(
                        agent_states[receiver_id].model_copy(update={"inbox": inbox})
                    )
                )
                for receiver_id, inbox in inbox_by_receiver.items()
            }

        max_workers = min(
            max(1, int(self.config.max_parallel_agents)),
            max(1, len(inbox_by_receiver)),
        )
        if max_workers <= 1 or len(inbox_by_receiver) <= 1:
            return {
                receiver_id: self._merge_receiver_belief_with_llm(
                    state=agent_states[receiver_id].model_copy(update={"inbox": inbox}),
                    step=step,
                    run_id=run_id,
                )
                for receiver_id, inbox in inbox_by_receiver.items()
            }

        outcomes: dict[int, _MergeOutcome] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._merge_receiver_belief_with_llm,
                    state=agent_states[receiver_id].model_copy(update={"inbox": inbox}),
                    step=step,
                    run_id=run_id,
                ): receiver_id
                for receiver_id, inbox in inbox_by_receiver.items()
            }
            for future in as_completed(futures):
                outcomes[futures[future]] = future.result()
        return outcomes

    # 【职责】单个接收方的 LLM 合并：先算确定性合并作校验基准，再调 LLM、解析并落地。
    # - llm_belief_merge=LLM 信念经确定性结果校验后落地；llm_full_merge=仅整体校验。
    # - 解析失败构造重试提示词重试；耗尽后按配置回落到确定性合并结果（兜底）或抛错。
    def _merge_receiver_belief_with_llm(
        self,
        *,
        state: AgentState,
        step: CommunicationStep,
        run_id: str,
    ) -> _MergeOutcome:
        if self.llm_client is None:
            raise RuntimeError("llm_client is required for LLM protocol merge modes")

        verified_belief = self._merge_receiver_belief(state)
        prompt = self.task_adapter.format_protocol_merge_prompt(
            merge_mode=self.config.merge_mode,
            global_task=self.global_task,
            local_observation=state.local_observation,
            old_belief_state=state.belief_state,
            inbox=state.inbox,
            deterministic_belief=verified_belief,
        )
        # 中文：M9——习得的每步角色指引在此送达 agent。仅当执行器显式开启且所执行
        #   规格为本步携带 instruction 时才生效——否则提示词字节级一致。
        # M9: learned per-step role guidance reaches the agent here. Only
        # fires when the runner opts in AND the executed spec carries an
        # instruction for this step -- otherwise the prompt is byte-identical.
        step_instruction = getattr(step, "instruction", None)
        if self.config.enable_step_instructions and step_instruction:
            prompt = (
                f"Step role for you this round: {step_instruction}\n\n{prompt}"
            )
        current_prompt = prompt
        responses: list[LLMResponse] = []
        call_prompts: list[str] = []
        last_error: Exception | None = None

        for attempt_idx in range(self.config.json_retry_attempts + 1):
            call_prompts.append(current_prompt)
            self._log_event(
                "llm-call",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"receiver={state.local_observation.get('agent_id')} "
                    f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1} "
                    f"inbox_from={[message.agent_id for message in state.inbox]}"
                ),
            )
            try:
                response = self.llm_client.complete(
                    current_prompt,
                    model_name=self.config.model_name,
                    temperature=self.config.temperature,
                )
            except Exception as exc:
                self._log_event(
                    "llm-error",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} "
                        f"receiver={state.local_observation.get('agent_id')} "
                        f"attempt={attempt_idx + 1}/{self.config.json_retry_attempts + 1} "
                        f"provider_call_failed={type(exc).__name__}: {exc}"
                    ),
                )
                raise
            responses.append(response)
            try:
                llm_belief = parse_belief_state(response.text)
                if self.config.merge_mode == "llm_belief_merge":
                    belief = self.task_adapter.apply_verified_protocol_merge(
                        llm_belief_state=llm_belief,
                        verified_belief_state=verified_belief,
                    )
                elif self.config.merge_mode == "llm_full_merge":
                    belief = self.task_adapter.validate_protocol_belief_state(
                        belief_state=llm_belief,
                        global_task=self.global_task,
                        n_agents=self.config.n_agents,
                        transport_belief_state=verified_belief,
                    )
                else:
                    raise ValueError(f"unsupported merge_mode: {self.config.merge_mode}")
                combined = self._combine_responses(responses, call_prompts)
                self._log_event(
                    "llm-success",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} "
                        f"receiver={state.local_observation.get('agent_id')} "
                        f"calls={combined.usage.model_calls} "
                        f"retries={max(0, combined.usage.model_calls - 1)} "
                        f"prompt_tokens={combined.usage.prompt_tokens} "
                        f"completion_tokens={combined.usage.completion_tokens}"
                    ),
                )
                return _MergeOutcome(
                    belief_state=belief,
                    llm_response=combined,
                    prompt=prompt,
                )
            except (ValueError, TypeError, ValidationError) as exc:
                last_error = exc
                if attempt_idx >= self.config.json_retry_attempts:
                    if self.config.allow_deterministic_repair:
                        self._log_event(
                            "retry-failed",
                            (
                                f"run={run_id} step={step.step_idx} "
                                f"round={step.step_idx + 1} "
                                f"receiver={state.local_observation.get('agent_id')} "
                                f"attempts={attempt_idx + 1} "
                                "deterministic_repair=applied "
                                f"last_error={exc}"
                            ),
                        )
                        return _MergeOutcome(
                            belief_state=verified_belief,
                            llm_response=self._combine_responses(responses, call_prompts),
                            prompt=prompt,
                            parse_error=str(exc),
                            fallback_applied=True,
                        )
                    self._log_event(
                        "retry-failed",
                        (
                            f"run={run_id} step={step.step_idx} "
                            f"round={step.step_idx + 1} "
                            f"receiver={state.local_observation.get('agent_id')} "
                            f"attempts={attempt_idx + 1} "
                            "deterministic_repair=disabled "
                            f"last_error={exc}"
                        ),
                    )
                    raise ValueError(
                        "LLM failed to return a valid CF protocol belief_state "
                        f"after {attempt_idx + 1} call(s). Last error: {exc}"
                    ) from exc
                self._log_event(
                    "retry",
                    (
                        f"run={run_id} step={step.step_idx} "
                        f"round={step.step_idx + 1} "
                        f"receiver={state.local_observation.get('agent_id')} "
                        f"failed_attempt={attempt_idx + 1}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"next_attempt={attempt_idx + 2}/"
                        f"{self.config.json_retry_attempts + 1} "
                        f"error={exc}"
                    ),
                )
                current_prompt = build_json_retry_prompt(
                    original_prompt=prompt,
                    invalid_response=response.text,
                    error_message=str(exc),
                    attempt_idx=attempt_idx + 1,
                )

        if self.config.allow_deterministic_repair:
            self._log_event(
                "retry-failed",
                (
                    f"run={run_id} step={step.step_idx} round={step.step_idx + 1} "
                    f"receiver={state.local_observation.get('agent_id')} "
                    "deterministic_repair=applied "
                    f"last_error={last_error}"
                ),
            )
            return _MergeOutcome(
                belief_state=verified_belief,
                llm_response=self._combine_responses(responses, call_prompts),
                prompt=prompt,
                parse_error=str(last_error) if last_error else None,
                fallback_applied=True,
            )
        raise ValueError(f"LLM protocol merge failed: {last_error}")

    def _log_event(self, event_type: str, message: str) -> None:
        if self.config.verbose_events:
            print(f"[{event_type}] {message}", flush=True)

    # 【职责】判断是否需要 LLM 客户端：LLM 初始化模式或任一 LLM 合并模式。
    def _needs_llm(self) -> bool:
        return (
            self.config.init_mode == "llm_local_solve"
            or self.config.merge_mode != "deterministic"
        )

    # 【职责】把多次重试的响应折叠为单个 LLMResponse：取最后文本、累加用量、保留全部原文。
    def _combine_responses(
        self,
        responses: list[LLMResponse],
        call_prompts: list[str],
    ) -> LLMResponse:
        if not responses:
            return LLMResponse(text="{}")
        return LLMResponse(
            text=responses[-1].text,
            usage=combine_usage([response.usage for response in responses]),
            raw_responses=[response.text for response in responses],
            raw_prompts=call_prompts,
        )

    # 【职责】构建单次接收方处理的逐步追踪记录；提示词是否留存由 save_prompts 决定。
    def _build_trace(
        self,
        *,
        run_id: str,
        step: CommunicationStep,
        receiver_id: int,
        inbox: list[OutboxMessage],
        outcome: _MergeOutcome,
        outbox: OutboxMessage,
    ) -> AgentStepTrace:
        response = outcome.llm_response or LLMResponse(text="")
        raw_responses = response.raw_responses or ([response.text] if response.text else [])
        raw_prompts = response.raw_prompts or ([outcome.prompt] if outcome.prompt else [])
        trace_prompts = raw_prompts if self.config.save_prompts else [""] * len(raw_prompts)
        return AgentStepTrace(
            run_id=run_id,
            round_idx=step.step_idx,
            communication_round=step.step_idx + 1,
            agent_id=receiver_id,
            topology_name=self.config.topology_name,
            neighbors=[message.agent_id for message in inbox],
            inbox=[message.model_dump() for message in inbox],
            prompt=outcome.prompt if self.config.save_prompts else "",
            raw_response=response.text,
            raw_responses=raw_responses,
            raw_prompts=trace_prompts,
            llm_calls=[
                {
                    "call_idx": idx,
                    "prompt": trace_prompts[idx] if idx < len(trace_prompts) else "",
                    "raw_response": raw_responses[idx] if idx < len(raw_responses) else "",
                }
                for idx in range(max(len(trace_prompts), len(raw_responses)))
            ],
            parsed_belief_state=outcome.belief_state.model_dump(mode="json"),
            outbox=outbox.model_dump(),
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model_calls=response.usage.model_calls,
            retry_attempts=max(0, response.usage.model_calls - 1),
            parse_error=outcome.parse_error,
        )

    # 【职责】委托任务适配器计算当前时点的逐 agent 与全局步级指标。
    def _record_metrics(
        self,
        *,
        agent_states: list[AgentState],
        step_idx: int,
        phase: str,
        send_counts: Counter[int],
        receive_counts: Counter[int],
    ) -> tuple[
        list[CFAgentStepMetric | ProtocolAgentStepMetric],
        CFGlobalStepMetric | ProtocolGlobalStepMetric,
    ]:
        return self.task_adapter.build_protocol_step_metrics(
            agent_states=agent_states,
            global_task=self.global_task,
            topology_name=self.config.topology_name,
            step_idx=step_idx,
            phase=phase,
            send_counts=send_counts,
            receive_counts=receive_counts,
            average_include_min_coverage=self.config.average_include_min_coverage,
        )

    # 【职责】生成全局任务的紧凑副本：剔除 array 大字段、保留 array_length（若有）。
    def _compact_global_task(self) -> dict:
        compact = {
            key: value
            for key, value in self.global_task.items()
            if key not in {"array"}
        }
        if "array_length" in self.global_task:
            compact["array_length"] = int(self.global_task["array_length"])
        return compact

    # 【职责】从 protocol_spec.metadata.selected_primary 解析答案 agent 覆盖；非法或越界抛错。
    def _metadata_answer_agent_ids(self) -> list[int] | None:
        spec = self.config.protocol_spec
        if spec is None:
            return None
        selected_primary = spec.metadata.get("selected_primary")
        if selected_primary is None:
            return None
        try:
            agent_id = int(selected_primary)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "protocol_spec.metadata.selected_primary must be an integer agent id"
            ) from exc
        if agent_id < 0 or agent_id >= self.config.n_agents:
            raise ValueError(
                "protocol_spec.metadata.selected_primary is outside valid "
                f"range 0..{self.config.n_agents - 1}: {agent_id}"
            )
        return [agent_id]

    def _make_run_id(self) -> str:
        if self.config.run_id:
            return self.config.run_id
        return (
            f"protocol_{self.config.topology_name}_n{self.config.n_agents}_"
            f"seed{self.config.seed}_{time_ns()}"
        )
