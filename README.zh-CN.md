# Agent Expressional Graph

这是论文 **"Laws of Collective Cognition in LLM Multi-Agent Systems"**（arXiv 2604.02674v1）的可运行复现脚手架。

本仓库优先复现论文中的结构机制，而不是复现 benchmark 分数。它实现了基于事件轨迹的多智能体协作系统，包括物理通信拓扑、独立的逻辑 Claim DAG、cascade 重建、强化式 claim routing，以及 Deficit-Triggered Integration（DTI）。

## 论文来源

实现映射主要来自本地 TeX 源文件：

```bash
files/arXiv-2604.02674v1/sec/
```

相关文档：

- `docs/paper_to_code_mapping.md`：论文证据与代码映射。
- `docs/assumptions.md`：论文未完全指定的工程假设。
- `docs/architecture.md`：运行时架构设计。

## 仓库结构

```text
src/schemas/          Claim、Event、Subtask、Cascade schema
src/topology/         Chain、star、mesh、exponential 通信拓扑
src/routing/          Topology visibility 与 reinforced claim routing
src/simulation/       LangGraph 编排 workflow
src/interventions/    Deficit-Triggered Integration
src/reconstruction/   Claim DAG、subtask tree、cascade 重建
src/analysis/         TCE、cascade size、top-k contribution、event metrics
examples/             可运行 demo 与 DTI 对比脚本
tests/                单元测试与 smoke tests
configs/              默认实验配置
```

本地论文和参考文件放在 `files/`，并被 Git 忽略。

## 环境安装

需要 Python 3.11+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

可选分析依赖：

```bash
pip install -e ".[analysis]"
```

## 运行测试

```bash
pytest
```

当前测试覆盖 schema 校验、Claim DAG 重建、cascade 提取、topology 邻居行为、routing 行为、DTI 触发/不触发路径，以及端到端 smoke run。

## 运行最小 Demo

默认运行：

```bash
python examples/run_demo.py
```

Mesh topology + DTI：

```bash
python examples/run_demo.py --topology mesh --dti --agents 8 --rounds 20
```

One-peer exponential topology，并输出 neighbor schedule：

```bash
python examples/run_demo.py --topology one_peer_exponential --agents 8 --rounds 4 --print-neighbors
```

对比不同 topology 下的物理传播行为：

```bash
python examples/compare_topologies.py --agents 8 --rounds 4
```

生成输出：

```text
examples/output/event_trace.jsonl
examples/output/claims.jsonl
examples/output/neighbor_trace.json
examples/output/reconstructed_claim_dag.json
examples/output/cascade_summary.json
examples/output/top_k_contribution_metrics.json
```

定性对比 DTI 开/关：

```bash
python examples/compare_dti.py
```

## 复现边界

### 论文直接支持

- 从 `parent_claim_ids` 重建 Claim DAG `G = (C, E_c)`（Sec 3.2）
- Cascades `C_r = {c_i | root(c_i) = c_r}`（Sec 3.2）
- Event 类型：propose、revise、contradict、merge、delegate（Table 1）
- Reinforced routing `P(c_i) ∝ x_i(t)^β`（Sec 4.2, Eq. 3）
- DTI 的 per-cascade deficit monitoring 与 threshold trigger（Sec 6, Algorithm 1）
- 所有 observables：TCE、cascade size、top-k contribution、revision waves、contradiction bursts、merge fan-in（Sec 3.3）
- Task tree 与 Claim DAG 在设计上保持分离（Appendix B.1）
- Append-only traces 作为主要运行时记录（Appendix B.3）
- Static 与 one-peer exponential neighbor schedules 基于 arXiv 2110.13363 中的通信拓扑。

### 基于工程假设

- Mock agent action selection，不调用真实 LLM，见 Assumption A12。
- 默认 `β = 0.15`，来自论文中 GPT-4o-mini 的估计值，见 Assumption A9。
- DTI 参数 `a_c`、`δ_c` 使用 demo 默认值，见 Assumption A10。
- Exponential graphs 只作为物理 neighbor communication schedules，不替代 Claim DAG 或 DTI，见 Assumption A14。
- 当 agent 数量不是 2 的整数次幂时，one-peer exponential 仍可运行，但只是工程启发式 mixing schedule，不声称满足论文中的 exact averaging guarantee，见 Assumption A15。
- 常规 cross-root merge 限制在同一 cascade 内，见 Assumption A13。

完整假设见 [docs/assumptions.md](docs/assumptions.md)。

### 后续工作

- 接入真实 LLM-backed agents 与结构化 prompts
- Benchmark-conditioned task expansion module（GAIA、SWE-bench、REALM、MultiAgentBench）
- Tree、hierarchical、sparse mesh、dynamic reputation topologies
- 按 condition class 从 baseline traces 估计 DTI 参数
- 统计分析 pipeline：power-law fitting、CCDF plots、EVT scaling
- 多 seed 实验 runner 与聚合分析
