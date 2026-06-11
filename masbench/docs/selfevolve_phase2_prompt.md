目标:搞清楚并做到——self-evolve 在若干轮(R≥3)进化后,在 held-out 条件上**稳定优于所有 baseline**(可复现、有机制可解释),而不是让某个测试通过。

baseline 集合(三个,缺一不可):
- `select`:空 bank 的 topology_select planner;
- `graphgen`:空 bank 的冷生a成(graph_generate);
- `fixed_best_on_train`:用 train 数据选出的单一最优具名拓扑,测试期固定(不许用测试集挑,oracle 不算 baseline)。

两层目标:
A. 机制真:多轮进化必须真的在积累知识——phase 1 已确认 rounds-curve 在第 1 轮后饱和(minister 每轮产出相同的 3 条拓扑级 skill,`skipped_already_applied`),这是本阶段要解决的核心方法问题(方向:增量提炼/自生成设计入库/motif 与 insight 的真实增益,任选但要有机制故事)。每轮 bank 的新增内容、gate 验收、以及它改变了哪些部署设计,都要能从 dump 里指认。
B. 效果真:在从未参与过开发迭代的 (case, n_agents) 条件上,evolved 对**每一个** baseline 的配对提升 ≥5pp 且方向一致(discordant margin ≥2),至少复现 2 次;且 rounds-curve 的最后 ≥3 个 round 全部高于所有 baseline(稳定性,不是单点)。

判定工具(第 0 轮先做,做完冻结):
- 写 `masbench/scripts/verify_beats_baselines.py`:同条件同 seeds 配对跑 4 臂(evolved + 三个 baseline),PASS = evolved 对每个 baseline 同时满足 delta≥5pp 与 margin≥2;另输出 rounds 稳定性判定(读 `masbench curve` 的 JSON:最后 3 个 round 均 > 全部 baseline)。该脚本一旦冻结,判定逻辑不可再改;修复永远进管线。离线(--llm fake)必须以"machinery OK + 不通过"收场作为冒烟。

工作循环(每轮):
1. 先诊断上一轮:`MASBENCH_EVOLVE_DUMP_DIR` 的 dump + `scripts/diag_report.py`(学到的规则是不是垃圾?gate 拒了什么?重放/生成选了什么设计?哪臂的失败来自组织而非模型能力?);
2. 再改方法本身,离线测试全绿(masbench + exp-graph 两套件,CF 字节不变)后才花真钱;
3. 每次真实启动前必须通过硬性成本闸门:
   `uv run python scripts/budget_guard.py --planned-usd <本轮预算> --cap-usd 40`,失败即不许启动;
4. 每轮随机换切分(--cases 轮换、--eval-seeds 现抽并先写入 protocol JSON),禁止对任何固定 test 集反复迭代;
5. 每个真实 run 结束立刻把实测成本记入 `runs/COST_LEDGER.json`(diag dump 的 tokens × $0.2625/M + 每个 graph_generate run 约 2.5k 规划 tokens);
6. 每轮结束报告:诊断结论 → 改了什么 → dev 数字。不要中途停下来问我。

实验设计(可改但必须在看结果之前定好、对所有臂对称):
- 先花 ≤$2 做一次预注册的"难度勘探":候选新条件 × {select, graphgen} × 2 seeds,据此**在看任何 evolved 结果之前**选定并写死 confirmatory 保留条件(必须有动态范围;floor/ceiling 条件没有信息量)。phase 1 已用过的条件(I-01..I-06、I-09、II-13、II-14、II-15、II-19 全部 @ n=5)不得作为新 confirmatory;候选方向:同 case 的 n=10、未用过的 II 级 case、或 III 级(未勘探,先探难度)。
- confirmatory:全新随机 seeds(抽完立刻记录进 JSON 再跑)+ 上述保留条件;最多 3 次,需 2 次 PASS;失败写清分析回到第 2 步。

结束交付(无论成败)一份证据报告(续写 `docs/selfevolve_evidence_report.md` 或新开 phase-2 报告):
- 对三个 baseline 各自的配对数字 + 不一致对 + 复现次数;rounds 稳定性曲线/表;
- 每轮新增 skills 列表 + 机制解释 + before/after 设计对比;
- gate 在多轮场景下的验收/拒绝记录(phase 1 它只在 R3C 真正开火过一次);
- 成本对照:evolved 不得靠多花 tokens/调用取胜(报告各臂每 run 的 msgs/calls/tokens;phase 1 的先例:refine 赢面伴随 ×1.7-2.2 tokens 要如实呈现,gen 模式曾以 ×1.1 近持平取胜)。

诚实条款(优先级最高):
- "在 gpt-4o-mini + level I/II 这个规模下做不到稳定优于所有 baseline"是合法且有价值的结论,如实报告它优于任何凑出来的 PASS;
- 任何让数字变好但说不出机制的改动,默认按过拟合处理,不采纳;
- 红线:不许 hardcode 任何 case 的答案或模式;不许按 confirmatory 表现选 checkpoint/调参;判定脚本冻结后不许改其判定逻辑(verify_evolve.py 同样保持冻结);不许读 masbench/.env。
预算:真实 LLM 累计 ≤ $40(含 phase 1 已花的 $3.97,台账延续 `runs/COST_LEDGER.json`);单轮 ≤ $2,超出需在 protocol JSON 里写明理由且总额不破上限。CF 测试始终保持绿。

环境与已知坑(省钱用,都已验证):
- 一律 `uv run --directory masbench ...`;真实跑用 `bash scripts/verify_evolve.sh`/同款 wrapper(它自己 source .env);
- `--levels` 默认只有 I,带 II/III case 必须显式传 `--levels I II`(否则静默丢弃);holdout 取 `--cases` 排序后的字典序尾部;
- 评测噪声参考:同 seeds 重跑空臂单 case 可摆动 ±25pp(12 seeds),配对设计 + 条件选择(空臂在 20-70% 区间)是功效来源;n=2 是 exact-match 地板;
- 诊断:`MASBENCH_EVOLVE_DUMP_DIR=<dir>` + `scripts/diag_report.py <runs/dir>`;gate 消融:`MASBENCH_GATE_MODE=off`;
- 瞬态网络错误已有重试层(masbench/llm/retry.py),勿再为单次 APIConnectionError 加补丁。
