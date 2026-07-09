# 大型多并发压力测试与效果对比规划 (Scaling Benchmark N=2~128)

## 需求拆解

您要求在大规模设定下验证我们之前探讨的架构理论。因为到达 $N=128$ 时，全连接结构单次合并文本量极大，而指数图的单节点合成总 API 请求次数会达到惊人的 $128 \times 7 = 896$ 次调用。

如果您要在本地跑通上述量级，必须要加入**最大并发控制器**以及**动态化测试数据集**。

## Proposed Changes (实施方案)

我们将编写一份完全独立的新基准评估脚本 `massive_scalability_benchmark.py`。

### 1. 动态探案线索流生成器 (Dynamic Clue Generation)
*   因为之前的探案只有 8 句话，我们无法喂给 128 个 Agent。
*   我会写一个生成器：固化 1 条“核心真相（管家）”，1 条“核心凶器（烛台）”，3 条极强“红鲱鱼（厨师/小刀）”和数十上百条“无意义的噪音信息（如：当晚雨很大、狗没叫等）”。
*   这极大模拟了现代系统中从海量网页中检索出的无用甚至干扰乱码。

### 2. 限流多线程改造 (Concurrency with Max limit 3)
*   **全连接基线 (FC)**：它只需要打 1 次极其庞大的 Prompt 请求，不涉及并发安全。
*   **指数图拓扑 (EXP)**：在每次迭代（如 $N=128$ 的 Iteration 0）中，本应该 128 个 Agent 同时请求。为了不把您的本地 Ollama / 显存打挂，我会引入 Python 的 `ThreadPoolExecutor(max_workers=3)`。这保证 `gemma4` 能够全速运转且绝不 OOM。

### 3. LLM 自动化裁判引擎 (Auto-Scoring Evaluator)
为了将“效果”量化画成折线图：
我们在拿回最终大模型文字后，用简单的核心实体捕捉法进行“探案得分”：
*   **+1 核心分**：找到了 Butler
*   **+1 核心分**：找到了 Candlestick
*   **-1 罚分**：相信了干扰项 Cook
*   **-1 罚分**：相信了假凶器 Knife 
*   **总分 (Effectiveness Score)** 范围在 `[-2, +2]` 之间。

### 4. 双图表自动绘制 (Dual Chart Output)
脚本跑完 7 个数组后，借助 `matplotlib` 渲染出 `massive_scale_benchmark.png`，包含两张子图：
1. **效果横向对比趋势图 (Effectiveness vs N)**：展示全连接网络在 $N$ 增大时如何遭遇“Lost in the middle”导致零分甚至负分，而我们的绿线如何稳定保持满分。
2. **总算力成本趋势图 (System Token Consumption vs N)**：直观展现全连接的暴力 Token 开销对碰。

## User Review Required
> [!WARNING]
> **运行时间预警**：
> 在 $N=32, 64, 128$ 时，哪怕有并发 3 的加持，累计发送近 1500 个本地大模型请求可能需要电脑死机般地跑上 **20~45 分钟**。
> 您确定要在本地机器上毫无保留地跑满直达 $N=128$ 吗？如果没问题，我就即刻为您把这个脚本写好并抛到后台执行！

## Verification Plan
1. 执行 `python massive_scalability_benchmark.py`。
2. 观察控制台输出线程池执行状态：`[Thread Pool] Processing 3 tasks limit...`。
3. 几个小时候后回来，提取生成的完整曲线。
