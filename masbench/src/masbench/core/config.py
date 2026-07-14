"""Run configuration for one benchmark execution."""
# ============================================================
# 【模块导读】一次 benchmark 执行的运行配置：RunConfig 汇集所有运行旋钮
# （规划器/进化/合并·初始化模式/图生成约束/超时等），逐字段控制一次运行。
# ============================================================

from __future__ import annotations

from dataclasses import dataclass


# 【职责】如何运行一道实例的全部配置旋钮。
# - use_planner 为 Plan 2/3 预留。
@dataclass
class RunConfig:
    """How to run one instance. ``use_planner`` is reserved for Plan 2/3."""

    benchmark: str = "silo_bench"
    use_planner: bool = False
    use_skill_evolution: bool = False
    # 中文：B2（可选开启）：让 LLM 设计洞察 minister（大臣）审阅进化证据，在留出集上
    #   证伪洞察，把通过验证的洞察并入技能库（形成更丰富、驱动生成的设计规则）。
    #   默认关闭（额外 LLM 调用）。
    # B2 (opt-in): run the LLM design-insight minister over the evolution evidence,
    # falsify insights against held-out, and fold the VERIFIED ones into the skill
    # bank (richer design rules that drive generation). Default off (extra LLM calls).
    use_llm_insights: bool = False
    topology: str = "mesh"
    objective: str = "balanced"
    # 中文：仅规划器路径。topology_select（默认）选择一个命名拓扑；graph_generate 让皇帝
    #   LLM 经 exp_graph.mas.graph_generation.plan_free_graph 现场设计一个专属时序通信 DAG，
    #   再执行其 protocol_spec。graph_* 系列旋钮是交给生成器的硬约束（默认值对齐
    #   MASRuntimeConfig / 论文）。
    # Planner-path only. ``topology_select`` (default) picks a named topology;
    # ``graph_generate`` has the emperor LLM invent a bespoke temporal DAG via
    # exp_graph.mas.graph_generation.plan_free_graph, then executes its
    # protocol_spec. ``program_generate`` independently generates a restricted
    # phase_program_v1 program and compiles it to the same runner contract; it
    # does not replace or route through graph_generate. The graph_* size knobs
    # are shared execution budgets for both generated structures.
    planner_mode: str = "topology_select"
    # 中文：evolved 实验臂的模式。topology_select（默认）：进化调优技能库，然后选择一个
    #   命名拓扑。graph_generate：进化调优技能库后，皇帝用这些进化出的技能生成一个专属
    #   DAG（自设计拓扑）——eval 时把进化后的技能库接入 plan_free_graph。select_then_refine：
    #   先用 topology_select 收集证据（让库里 minister 技能带上有效拓扑的参考 protocol_spec），
    #   再在 eval 时生成 DAG 并由皇帝在这些参考上精修（先锚定有效方案再精简）——相比
    #   从零开始的 graph_generate 兼取两者之长。
    # The `evolved` bench arm's mode. ``topology_select`` (default): evolution
    # tunes the skill bank, then PICKS a named topology. ``graph_generate``:
    # evolution tunes the skill bank, then the emperor GENERATES a bespoke DAG
    # from those evolved skills (self-designed topology) -- the evolved bank is
    # threaded into plan_free_graph at eval time. ``select_then_refine``: evidence
    # is collected via topology_select (so the bank's minister skills carry the
    # WORKING topologies' reference protocol_specs), then the eval GENERATES a DAG
    # the emperor refines from those references (anchor on what works, then
    # economize) -- best-of-both vs from-scratch graph_generate.
    evolved_mode: str = "topology_select"
    # 中文：Phase-2 反饱和：在 select_then_refine 进化中，每轮还会用当前技能库（即部署时的
    #   精修路径）对每个训练实例额外跑这么多次 graph_generate 证据收集，让自生成设计带着
    #   可执行 spec 进入 minister，在后续轮次与命名拓扑竞争。0 表示关闭（回到 phase-1 行为）。
    #   环境变量覆盖：MASBENCH_EVOLVE_EXPLORE（供冻结的 verify 脚本控制）。
    # Phase-2 anti-saturation: in select_then_refine evolution, each round ALSO
    # runs this many graph_generate evidence runs per train instance USING THE
    # CURRENT BANK (the deployed refine path), so self-generated designs enter
    # the minister with their executable specs and compete with named
    # topologies in later rounds. 0 disables (phase-1 behaviour). Env override:
    # MASBENCH_EVOLVE_EXPLORE (lets the frozen verify scripts control it).
    evolve_explore: int = 1
    # 中文：仅用于图生成调用的温度（None = 沿用 temperature）。探索阶段设为高温（0.7），
    #   让相邻轮次在确定性协议执行下提出不同的设计；部署阶段保持低温。
    # Temperature for the graph-GENERATION call only (None = use `temperature`).
    # Exploration sets this hot (0.7) so successive rounds propose DIFFERENT
    # designs at deterministic protocol execution; deployment stays cold.
    graph_gen_temperature: float | None = None
    # 中文：Phase-3 M1：部署时的证据条件迁移门。"feature"（默认）：只有当技能的证据账本
    #   显示它在该 case 的任务特征桶里有实测成功，其可执行 spec 才可在该 case 上重放；
    #   无可信项 -> 走精确的冷路径（空技能库、无 motif）。"off"：phase-2 行为（不看 case 的
    #   盲重放）。环境变量覆盖：MASBENCH_TRANSFER_GATE（供冻结的 verify 脚本跑消融）。
    # Phase-3 M1: evidence-conditioned transfer gate on deployment. "feature"
    # (default): a skill's executable spec is replayable on a case only when
    # the skill's ledger shows measured success in the case's task-feature
    # bucket; nothing trusted -> the exact cold path (empty bank, no motif).
    # "off": phase-2 behavior (case-blind replay). Env override:
    # MASBENCH_TRANSFER_GATE (lets frozen verify scripts run the ablation).
    transfer_gate: str = "feature"
    # 中文：Phase-3 M3：逗号分隔的命名拓扑，每轮作为额外证据测量（目标变体绕行只测量
    #   聚合默认项）。"" 表示关闭。环境变量覆盖：MASBENCH_EVIDENCE_PORTFOLIO。
    # Phase-3 M3: comma-separated named topologies measured as EXTRA evidence
    # each round (the objective-variant detour only measures aggregation
    # defaults). "" disables. Env override: MASBENCH_EVIDENCE_PORTFOLIO.
    evidence_portfolio: str = "chain"
    # 中文：Phase-3 M4：motif 先验的 LCB 悲观系数（exp_graph
    #   MASRuntimeConfig.motif_uncertainty_kappa）。单次走运的 motif 不能压过经多次实测的
    #   老将。0.0 = phase-2 行为。
    # Phase-3 M4: LCB pessimism for the motif prior (exp_graph
    # MASRuntimeConfig.motif_uncertainty_kappa). A 1-run lucky motif cannot
    # outrank a measured veteran. 0.0 = phase-2 behavior.
    motif_uncertainty_kappa: float = 0.5
    # 中文：Round-10 部署稳定性（dev-6 r3 重排）：重放优先的选择 + 粘性 motif 置换裕度。
    # Round-10 deployment stability (dev-6 r3 reshuffle): replay-first
    # selection + sticky motif displacement margin.
    replay_first: bool = True
    motif_displacement_margin: float = 0.1
    # 中文：Operator 抬高标准（对比 fixed-best，弃权会流失配对样本）：当某 case 的槽位没有
    #   可信技能时，先部署一个广度均匀的桶级通才（M8 breadth），再考虑走冷路径。
    #   环境变量：MASBENCH_FALLBACK_TIER。
    # Operator bar raise (vs fixed-best, abstention bleeds pairs): when a
    # case's slot has no trusted skill, deploy a broad-uniform bucket
    # generalist (M8 breadth) before going cold. Env: MASBENCH_FALLBACK_TIER.
    fallback_tier: bool = True
    # 中文：Phase-3 M10：训练期对无锚点 bucket#slot 做已验证配方搜索的运行预算（每个进化轮
    #   的协议执行次数）。0 = 关闭。环境变量：MASBENCH_RECIPE_BUDGET。
    # Phase-3 M10: run budget (protocol executions per evolution round) for
    # train-time VERIFIED recipe search on unanchored bucket#slots. 0 = off.
    # Env: MASBENCH_RECIPE_BUDGET.
    recipe_search_budget: int = 18
    # 中文：Phase-3 M27（高功效取证）：portfolio（命名拓扑）证据只在 train_seeds 上收集——
    #   n=5 时唯一的 os 锚点 II-13 只给每个拓扑 len(train_seeds)=2 次评估，于是一个坏的
    #   provider 漂移窗口就能把 one_peer 的 os 信任翻成 0，gen 退回到弱结构。这个因子派生额外
    #   portfolio 种子（s + 1009*k），让信任建立在 len(train_seeds)*factor 个样本上。1 = 关闭，
    #   与之前逐字节一致（不影响 CF：CF 从不使用它）。
    # Phase-3 M27 (hi-power forensics): portfolio (named-topology) evidence
    # is collected on train_seeds only -- at n=5 the sole os anchor II-13
    # gives each topology just len(train_seeds)=2 evaluations, so one bad
    # provider-drift window flips one_peer's os trust to 0 and gen falls
    # back to a weak org. This factor derives extra portfolio seeds
    # (s + 1009*k) so trust is built on len(train_seeds)*factor samples.
    # 1 = off, byte-identical to before (CF unaffected: CF never uses it).
    portfolio_seed_factor: int = 1
    # 中文：Phase-3 M20：训练期指令范例（instruction-exemplar）验证的运行预算（architect 为
    #   桶级冠军结构在一个训练锚点上写每步指令；在 verify 种子上执行；通过的指令集存到技能卡
    #   上，锚定部署时的 Modify 改写，消除每次部署抽取指令的抽签随机性）。0 = 关闭。
    # Phase-3 M20: run budget for train-time instruction-EXEMPLAR
    # verification (architect writes per-step instructions for the bucket
    # champion's structure on a train anchor; executed on verify seeds; a
    # passing set is stored on the card and anchors deploy-time Modify
    # rewrites, removing the per-deployment instruction-draw lottery). 0 = off.
    # Environment override: MASBENCH_EXEMPLAR_BUDGET.
    exemplar_search_budget: int = 6
    # 中文：Phase-3 M23（operator：更强的规划器、冻结的执行者）：设置后，architect 一侧的调用
    #   （皇帝图生成、指令改写、配方搜索、范例书写）用这个模型，而执行者仍用 model_name。
    #   None = 不拆分（与历史行为逐字节一致）。
    # Phase-3 M23 (operator: stronger PLANNER, frozen workers): when set,
    # architect-side calls (emperor graph generation, instruction rewrite,
    # recipe search, exemplar writing) use this model while workers keep
    # model_name. None = no split (byte-identical historical behavior).
    planner_model_name: str | None = None
    # 中文：Phase-3 M9：重放候选会为当前任务重写每步接收方指令（每个种子候选一次皇帝调用），
    #   ProtocolRunner 把它们注入合并提示。False = 仅结构、原样重放（M9 之前）。
    #   环境变量：MASBENCH_REPLAY_REWRITE。
    # Phase-3 M9: replay candidates get per-step receiver instructions
    # REWRITTEN for the current task (one emperor call per seeded candidate)
    # and the protocol runner injects them into merge prompts. False =
    # verbatim structure-only replay (pre-M9). Env: MASBENCH_REPLAY_REWRITE.
    replay_rewrite: bool = True
    # 中文：Phase-3 M7（泛化性）：任务特征（桶 + 聚合种类）如何从任务陈述中派生。"llm"（默认）：
    #   本次运行自己的 LLM 回答与 benchmark 无关的问题（顺序敏感性、答案局部性、统计族），
    #   温度 0，按文本哈希缓存（环境变量 MASBENCH_FEATURE_CACHE 可跨进程持久化）；fake provider
    #   退回启发式。"heuristic"：仅正则兜底（离线测试 / 消融臂；不是本方法）。
    # Phase-3 M7 (generalizability): how task features (bucket + agg kind)
    # are derived from the task statement. "llm" (default): the run's own
    # LLM answers benchmark-agnostic questions (order-sensitivity, answer
    # locality, statistic family), temp-0, cached per text hash (env
    # MASBENCH_FEATURE_CACHE persists across processes); fake provider falls
    # back to heuristics. "heuristic": regex fallback only (offline tests /
    # ablation arm; NOT the method).
    task_feature_source: str = "llm"
    # 中文：Phase-3 M5：生成门在 len(val_seeds) * gate_seed_factor 个派生种子（s, s+1009,
    #   s+2017, ...）上评估每个实验臂，而非原始 val_seeds，并容忍恰好一次不一致的失手
    #   （epsilon_eff = max(epsilon, 1/n_samples)）。3 个样本的二元门形同抛硬币：dev 第 1 轮
    #   就因冷 3/3 对部署 2/3 而否掉了一个确实不错的技能库。环境变量覆盖：MASBENCH_GATE_SEED_FACTOR。
    # Phase-3 M5: the generation gate evaluates each arm on
    # len(val_seeds) * gate_seed_factor derived seeds (s, s+1009, s+2017, ...)
    # instead of the raw val_seeds, and tolerates exactly one discordant miss
    # (epsilon_eff = max(epsilon, 1/n_samples)). A 3-sample binary gate is a
    # coin flip: dev round 1 rejected a genuinely-good bank on cold 3/3 vs
    # deployed 2/3. Env override: MASBENCH_GATE_SEED_FACTOR.
    gate_seed_factor: int = 3
    # 中文：run_evolution 的留出集验证门。auto（默认）：按部署目标验证——当进化后的状态将在
    #   eval 时生成（graph_generate / select_then_refine）就用生成损失，否则用拓扑选择目标 J。
    #   off：完全不设留出门（漂移消融臂；也可经 MASBENCH_GATE_MODE 环境变量逐次设置，让
    #   scripts/verify_evolve.py 等冻结驱动无需新增开关即可跑消融）。
    # Held-out acceptance gate for run_evolution. ``auto`` (default): gate on the
    # DEPLOYED objective -- generation loss when the evolved state will generate
    # at eval (graph_generate / select_then_refine), topology-selection J
    # otherwise. ``off``: no held-out gate at all (the drift-ablation arm; also
    # settable per-run via the MASBENCH_GATE_MODE env var so frozen drivers like
    # scripts/verify_evolve.py can run the ablation without growing flags).
    gate_mode: str = "auto"
    # Compatibility default preserves the historical scalar non-regression
    # gate. strict_dense_v2 compares paired V/K/U/P/S/stage/cost samples.
    evolution_gate_policy: str = "legacy_non_regression"
    strict_gate_min_dense_delta: float = 0.01
    strict_gate_partial_tolerance: float = 0.0
    strict_gate_bootstrap_samples: int = 2000
    strict_gate_bootstrap_seed: int = 20260713
    # Annotate every proposed skill with same-(case, seed) marginal evidence.
    # Strict mode drops a skill whose paired losses exceed its wins before the
    # whole-bank held-out gate. False preserves historical admission behavior.
    skill_ablation_strict: bool = False
    # Grow the train subset within every available level across repeated rounds.
    curriculum_enabled: bool = False
    curriculum_round: int = 1
    curriculum_total_rounds: int = 1
    # Optional evolution hot start.  When enabled, run_evolution first measures
    # supplied fixed organizations and (for all_agents SILO runs) the paper's
    # dynamic transports, then seeds the SkillBank from that evidence.  ``auto``
    # keeps the defaults goal-aware: sink uses fixed topologies only, while
    # all_agents additionally measures p2p/broadcast/sfs.  The feature is off by
    # default, so existing cold-start experiments remain byte-for-byte isolated.
    hot_start_enabled: bool = False
    hot_start_protocols: str = "auto"
    hot_start_topologies: str = "auto"
    hot_start_seed_count: int = 1
    # Per training pair, measure both an existing-skill/replay route and a fresh
    # generation route conditioned on the bank's non-executable lessons.  This
    # intentionally costs roughly two additional runs per pair.
    hot_start_dual_branch: bool = True
    # auto = keep the configured generated planner, or graph_generate when the
    # main evolution planner is topology_select/select_then_refine.
    hot_start_innovation_mode: str = "auto"
    # Python hot-start innovation can generate a fresh program, locally mutate
    # a Python parent skill, or evaluate both. It is inert outside the opt-in
    # hot-start dual-branch path.
    python_innovation_strategy: str = "mutate_and_fresh"
    # Internal per-run branch controls populated by the evolution harness.
    python_innovation_branch: str | None = None
    python_parent_skill_id: str | None = None
    python_exposed_insight_ids: tuple[str, ...] = ()
    # Historical runners dropped every exception. honest_v2 zero-scores typed
    # algorithm failures, drops only infrastructure failures, and re-raises
    # harness/unknown errors.
    failure_policy: str = "legacy_drop"
    # 中文：evolved 臂留出多少个末尾种子用于 eval（同时作为门的验证集）：train = seeds[:-K]，
    #   test = seeds[-K:]。默认 1（当前行为）；K>1 让 evolved 在更多留出种子上评估 -> 每个
    #   条件的方差大幅降低（不再是单次二元结果）。
    # How many trailing seeds the evolved arm holds out for EVAL (and the gate's
    # val): train = seeds[:-K], test = seeds[-K:]. Default 1 (current behaviour);
    # K>1 evaluates evolved on more held-out seeds -> far less per-condition
    # variance (each condition is no longer a single binary outcome).
    evolved_test_seeds: int = 1
    num_graph_candidates: int = 1
    # 中文：D1（可选开启）：>0 启用 top-k 候选探针评估——每个生成的候选实际在这么多验证种子
    #   上运行，选取得分最高者（相对默认的盲选：首个有效/motif 挑选）。0 = 关闭。
    # D1 (opt-in): >0 turns on top-k candidate PROBE-evaluation -- each generated
    # candidate is actually run on this many validation seeds and the best-scoring
    # one is selected (vs the default blind first-valid/motif pick). 0 = off.
    graph_validation_seeds: int = 0
    graph_max_steps: int = 4
    graph_max_messages: int = 32
    graph_max_receiver_fan_in: int = 4
    # Bounded counterexample-driven repair turns for program_generate only.
    # Keeping this separate ensures changing program repair cannot alter GraphGen.
    program_repair_attempts: int = 2
    # Independent PythonGen validation/execution settings. They do not reuse
    # GraphGen or phase-program repair/artifact controls.
    python_repair_attempts: int = 3
    python_gen_temperature: float | None = None
    # None derives a whole-program wall-clock budget from request_timeout,
    # max_rounds, n_agents, and max_parallel_agents. A fixed value remains
    # available for preregistered experiments that need an explicit cap.
    python_execution_timeout: float | None = None
    python_cpu_seconds: int = 10
    python_memory_mb: int = 512
    python_max_output_bytes: int = 1_000_000
    python_dry_run: bool = True
    python_ast_policy_version: str = "python_ast_v1"
    python_execution_contract_version: str = "python_mas_v1"
    # 中文：PythonGen Worker 输出合约。action_json_v1=旧动作 JSON(默认，行为不变)；
    #   message_only_v1=Planner source 决定路由、Runtime 管状态/provenance、Worker
    #   只产出纯文本；message_only_v2=通信完成后由 Runtime 执行同步提交屏障，
    #   Worker 提交单一 JSON 值。三种合约的 scaffold/校验/SkillBank 全隔离。
    # PythonGen worker output contract. action_json_v1 = legacy action JSON
    # (default, unchanged behaviour); message_only_v1 = the Planner source
    # routes, the runtime owns state/provenance, and workers emit plain text
    # only. message_only_v2 adds a synchronized submit barrier and one parsed
    # JSON answer value. Scaffolds, validation and skill banks are isolated.
    python_worker_contract: str = "action_json_v1"
    python_max_model_calls: int = 32
    python_max_completion_tokens: int = 20_000
    python_max_messages: int = 64
    # Optional strict science-run barrier. Python message_only_v2 already owns
    # its synchronized barrier; this flag gives fixed and paper transports an
    # audited completion pass instead of silently retaining null submissions.
    require_all_submissions: bool = False
    final_submission_retries: int = 2
    # Science-run reliability controls. Defaults preserve historical behavior:
    # two attempts for a wall-clock timeout, and infrastructure failures may be
    # recorded/dropped by honest_v2. Strict runs can raise both explicitly.
    llm_timeout_attempts: int = 2
    require_complete_runs: bool = False
    # 中文：仅规划器路径：士兵（soldier）在 ProtocolRunner 里如何初始化/合并信念状态
    #   （init_mode/merge_mode，即初始化/合并模式）。
    # Planner-path only: how soldiers initialize/merge beliefs in ProtocolRunner.
    merge_mode: str = "deterministic"
    init_mode: str = "deterministic"
    n_agents: int | None = None
    max_rounds: int = 4
    # Intra-task concurrency. Calls from agents in the same logical round may
    # overlap; the next round still waits for the complete round snapshot.
    max_parallel_agents: int = 5
    llm_provider: str = "fake"
    model_name: str = "fake"
    base_url: str | None = None
    api_key_env: str | None = None
    thinking_enabled: bool | None = None
    seed: int = 0
    consensus_threshold: float = 0.8
    final_accept_threshold: float = 0.7
    temperature: float = 0.0
    # 中文：非 fake LLM 调用的每次请求硬性挂钟超时（秒）。卡住的 provider 请求超过这个预算
    #   就放弃，让运行快速失败而非冻结（见 masbench.llm.timeout.TimeoutLLMClient）。
    #   <=0/None 关闭该守卫。fake 客户端瞬时返回，故从不被包裹。
    # Per-request hard wall-clock timeout (seconds) for non-fake LLM calls. A
    # hung provider request is abandoned after this budget so the run fails fast
    # instead of freezing (see masbench.llm.timeout.TimeoutLLMClient). <=0/None
    # disables the guard. The fake client is instant, so it is never wrapped.
    request_timeout: float = 90.0
    # 中文：Silo 评测的信息目标（sink / all_agents）。sink：所有信息汇聚到单一
    #   selected_primary，只有它被主评分；all_agents：每个 agent 都必须独立持有完整
    #   信息并给出正确答案（主 success = all_agents_exact，多数票不作数）。提示词、
    #   图校验/修复、评分、SkillBank、缓存与报告六层都按该模式隔离。默认 sink 兼容
    #   旧调用；科学评测脚本必须显式传参。
    # Silo evaluation information goal (sink / all_agents). Prompts, graph
    # validation/repair, scoring, skill banks, caches, and reports are all
    # namespaced by it. Default sink keeps legacy callers working; science
    # scripts must pass it explicitly.
    silo_eval_mode: str = "sink"
    # 中文：graph_generate 架构师审计产物的持久化目录（渲染提示词/哈希/原始回复/展开边/
    #   校验修复记录/失败原因/选择原因）。None：默认写到 cwd 下 runs/graphgen_artifacts/
    #   （可用环境变量 MASBENCH_GRAPH_ARTIFACTS_DIR 覆盖）。绝不再写入用完即删的临时目录。
    # Persistent dir for graph_generate architect audit artifacts. None -> the
    # default runs/graphgen_artifacts/ under cwd (env override
    # MASBENCH_GRAPH_ARTIFACTS_DIR). Never a throwaway TemporaryDirectory again.
    graph_artifacts_dir: str | None = None
    # Persistent phase_program_v1 architect/compiler audit artifacts. Kept in a
    # separate tree from GraphGen to make experimental provenance unambiguous.
    program_artifacts_dir: str | None = None
    # Persistent audit root for python_generate only.
    python_artifacts_dir: str | None = None
    # 中文：clean GraphGen 开关（默认开）。clean：graphgen 技能检索只放行
    #   llm_generated 与同模式验证过的 skill_replay，缺 provenance 的旧卡视为
    #   contaminated，具名 fixed 证据不可见。evolved_mode=select_then_refine 按定义
    #   要从具名锚点精修，属"非 clean"路径并在记录上标注 clean_graphgen=False——其
    #   结果不得用于 clean GraphGen 结论。
    # Clean-GraphGen switch (default on). select_then_refine is by definition a
    # non-clean path (refines from named anchors) and every such record is
    # labelled clean_graphgen=False.
    clean_graphgen: bool = True
    clean_pythongen: bool = True
