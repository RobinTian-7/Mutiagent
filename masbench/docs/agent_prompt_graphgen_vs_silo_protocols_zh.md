# 给 Agent 的完整实验提示词

```text
你正在 /Users/robintian/AI/queenbee-clean 仓库中工作。请完成一次小规模、可审计、不能夸大结论的实验：让 QueenBee/GraphGen 在训练集上自进化 3 轮，再在互不重叠的 SILO-BENCH II/III 测试集上，与论文原本的三种传播协议 P2P、Broadcast、SFS 做成对比较。

硬性约束：
1. 只能使用 gpt-4o-mini，provider=openai，temperature=0。不得换更强模型，也不得混用模型。
2. 只测 Level II 和 Level III，训练和测试都必须同时含 II、III；禁止使用 Level I。
3. 统一使用 --silo-eval-mode all_agents。每个 Agent 都要独立提交，只有 S=1 才算该次运行成功。
4. GraphGen 必须使用 evolved_mode=graph_generate，训练 3 轮并累积 SkillBank 与 motif；不得用 topology_select 的结果冒充 GraphGen。
5. 对照必须包含论文全部三种协议：p2p、broadcast、sfs。不得把它们替换成 chain、mesh 或其他静态图。
6. 所有 arm 使用相同题目、Agent 数、模型、种子、最大轮数和评分器。测试 case 与训练 case、eval seed 与 train/val seed必须互斥。
7. 使用论文指标与公式：逐 Agent 保存答案；S=正确 Agent 比例，S=1 才成功；P 按 Level II 的逐位置元素正确率和 Level III 的最长正确有序子序列；C=输出 token/执行轮数；D=向外信息传输数/[N(N-1)]，SFS 按其他 Agent 成功读取文件计数。
8. 不得把 expected_outputs、答案、optimal_topology 或原题中的传播结构送进模型 Prompt。发现泄漏立即停止，不得继续产出胜负结论。
9. 控制费用：n_agents=5，graphgen_candidates=2，graph_validation_seeds=0，不启用 LLM insights，max_rounds=4，workers=4。不要自行扩大网格，除非按下面的“结论不足”规则执行一次预注册扩展。
10. 不要清理或覆盖用户已有改动。所有新实验产物写入一个新的 runs/silo_paper_protocols_<timestamp>/ 目录，不提交 runs 产物到 Git。

先做预检：
- 阅读 AGENTS.md、masbench/docs/silo_paper_protocol_baselines.md、masbench/docs/leakage_and_eval_modes.md。
- 检查 git status，只处理本任务相关内容。
- 运行：
  cd exp-graph && uv run --extra dev python -m pytest -q
  cd ../masbench && uv run --extra dev python -m pytest -q
- 确认 masbench 具备 p2p/broadcast/sfs 三个 arm、逐 Agent 记录和 paper_S/P/C/D；确认 evolve.py 的训练证据使用 all_agents scorer。如果缺少任何一项，先最小修复并加测试，再继续实验。

预注册数据划分：
- TRAIN cases: II-11 II-13 III-21 III-23
- TEST cases:  II-12 II-14 III-22 III-24
- train seeds: 1
- val seeds:   2
- eval seeds:  11 12 13
- 训练 3 轮，Agent 数 5。

从 masbench/ 运行以下主实验。把 <OUT> 替换为新的时间戳目录：

uv run --extra dev python scripts/verify_beats_baselines.py \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --llm openai \
  --model-name gpt-4o-mini \
  --merge-mode llm_full_merge \
  --init-mode llm_local_solve \
  --objective accuracy_first \
  --evolved-mode graph_generate \
  --rounds 3 \
  --n-agents 5 \
  --levels II III \
  --train-cases II-11 II-13 III-21 III-23 \
  --test-cases II-12 II-14 III-22 III-24 \
  --train-seeds 1 \
  --val-seeds 2 \
  --eval-seeds 11 12 13 \
  --baselines p2p broadcast sfs \
  --graphgen-candidates 2 \
  --graph-validation-seeds 0 \
  --silo-eval-mode all_agents \
  --max-rounds 4 \
  --workers 4 \
  --request-timeout 120 \
  --delta-min 0.05 \
  --win-margin 2 \
  --max-runs 140 \
  --out <OUT>

注意：验证脚本退出码 1 表示“尚未验证胜出”，不等于程序崩溃。必须读取 <OUT>/verify_beats_baselines_n5.json 再判断。不得因为退出码 1 删除结果或重跑到好看为止。

运行后必须逐项审计：
1. clean_run=true、silo_eval_mode=all_agents，训练/测试 cases 和种子没有交集。
2. dropped_pairs=0；n_pairs 应为 4 cases x 3 seeds = 12。若有 dropped pair，先说明错误原因；不得只保留成功请求。
3. pair_details 中每个 pair 都有 evolved、p2p、broadcast、sfs；每个 arm 都有 5 条 per_agent_submissions。
4. paper_metric_means 中四个 arm 的 S/P/C/D 都是有限数；抽查 D 没有乘轮数，SFS D 来自跨 Agent 成功读取。
5. skill_banks/manifest.json 存在；每轮 before/candidate/deployed 和 final/deployed 均已保存。列出每轮技能数量、skill_id、gate 是否接受，并给出这些文件的链接。
6. 检查 GraphGen 架构师审计产物中不存在答案、optimal_*、原题传播结构或 API key；失败生成必须记失败，不能静默换成具名拓扑。
7. 汇总每个 Level、case、协议的逐 Agent 错误模式，不能只报告总平均。

统计与结论规则：
- 主要胜负指标是每个 (case, seed) 是否 S=1，以及 mean S、mean P；C、D 是成本指标，单独报告，不能把更省 token 自动说成更正确。
- 对 evolved GraphGen 分别相对 p2p、broadcast、sfs 计算成对成功率差、wins/losses/ties，并对成对成功差做固定 seed 的 bootstrap 95% CI（至少 10,000 次重采样）。把脚本和结果保存到 <OUT>/analysis.py 与 <OUT>/analysis.json。
- 只有当原始验证 criteria 通过，且 GraphGen 相对三种 baseline 的成功率差均至少 +5 个百分点、wins-losses 均至少 2，才能写“GraphGen 在本次小规模实验中更强”。
- 若 criteria 明确失败且没有 dropped pair，写“本次小规模实验不支持 GraphGen 更强”，不要模糊包装。
- 若唯一问题是 12 个 pair 的置信区间跨 0，可执行一次预注册扩展：保持训练结果和所有参数不变，仅增加 eval seeds 14、15。若现有工具不能在不重训的情况下加载 final SkillBank，就不要偷偷重训；先补一个只读加载 final/deployed bank 的 eval 入口并测试。最多扩展一次。
- 即使通过，也必须写“小规模、仅限这些 II/III cases 和 gpt-4o-mini”，不得外推为普遍优越。

最终交付：
- 一段人话结论，先说 GraphGen 是否比三种论文协议更强，再说证据强度和限制。
- 一张表：arm | solved runs | mean S | mean P | C | D | tokens。
- 一张逐 baseline 的 paired delta / wins / losses / ties / bootstrap CI 表。
- 每轮训练的 SkillBank 变化和 gate 结果。
- dropped/failed/parse-error 清单。
- 可点击链接：主 JSON、analysis.json、最终报告、skill_banks/manifest.json、final bank、每轮 snapshots。
- 报告总模型调用数、总 input/output tokens；无法获得真实费用时不要编造美元成本。
```
