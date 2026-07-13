"""Full cross-difficulty evaluation on a local OpenAI-compatible LLM
(e.g. the VT-ARC GPT-OSS-120B endpoint). Deterministic local inference ->
NO provider drift, so gen-vs-fixed and the evolution curve are clean & reproducible.

Measures:
  1) gen evolution curve  -- held-out exact-match per evolution round (does gen improve?)
  2) gen vs fixed/select/coldgen across L1/L2/L3 (does gen per-case-adapt and beat a
     single fixed topology when difficulties need different optimal topologies?)
  over K independent evolution runs (rules out single-run luck).

Resumable: every eval cell is appended to results.jsonl; a restart skips finished cells.
So if the 24h session blips, just re-run the SAME command and it continues.

Env (required):
  GPTOSS_BASE_URL   e.g.  http://fal045:44853/v1
  GPTOSS_KEY        the API key (masbench reads it via api_key_env="GPTOSS_KEY")
  GPTOSS_MODEL      optional, default "gpt-oss-120b-F16.gguf"

Usage:
  python scripts/full_cluster_eval.py --out runs/full_gptoss
  python scripts/full_cluster_eval.py --out runs/full_gptoss --report-only   # just print summary
"""
# ============================================================
# 【模块导读】在本地 OpenAI 兼容 LLM（如 VT-ARC 的 GPT-OSS-120B 端点）上做跨难度整评。
# 确定性本地推理 -> 无 provider 漂移，故 gen-vs-fixed 与进化曲线干净且可复现。
# 测量：1) gen 进化曲线——每个进化轮的留出精确匹配（gen 是否进步？）；2) 在 L1/L2/L3 上
#   gen 对比 fixed/select/coldgen（当不同难度需要不同最优拓扑时，gen 是否逐 case 自适应
#   并胜过单一固定拓扑？）；跨 K 次独立进化运行（排除单次走运）。
# 可断点续跑：每个 eval 单元格追加写入 results.jsonl，重启时跳过已完成单元格；24h 会话
#   若中断，重跑相同命令即可继续。
# 必需环境变量：GPTOSS_BASE_URL、GPTOSS_KEY（经 api_key_env="GPTOSS_KEY" 读取）、
#   GPTOSS_MODEL（可选，默认 "gpt-oss-120b-F16.gguf"）。
# ============================================================
from __future__ import annotations
import os, json, argparse, statistics
from dataclasses import replace
from pathlib import Path

from exp_graph.mas.skill_bank import SkillBank
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.curve import _bank_and_motif, _bounded, _merge_motif
from masbench.engine import _build_llm_client, run_fixed_protocol
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution

LEVELS = ["I", "II", "III"]


# 【职责】解析命令行参数（轮数、K 次运行、各类种子、workers、训练/测试 case、固定拓扑集、
#   模型/base_url/api-key-env、--report-only）。
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="runs/full_gptoss")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--k-runs", type=int, default=3)
    p.add_argument("--eval-seeds", nargs="+", type=int, default=[401, 402, 403, 404, 405])
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    # 中文：端点约在 5 并发饱和（1.7x），再多也是浪费。
    p.add_argument("--workers", type=int, default=5)  # endpoint saturates ~5 (1.7x), more is wasted
    p.add_argument("--train", nargs="+", default=["I-01", "I-04", "II-13", "II-16", "III-22", "III-26"])
    p.add_argument("--test", nargs="+", default=["I-02", "I-07", "II-15", "II-19", "III-24", "III-28"])
    p.add_argument("--fixed", nargs="+", default=["one_peer_exponential_dag_star", "chain", "tree", "mesh_star"])
    p.add_argument("--model", default=os.environ.get("GPTOSS_MODEL", "gpt-oss-120b-F16.gguf"),
                   help="model name (e.g. gpt-4o-mini for the real OpenAI API)")
    p.add_argument("--base-url", default=os.environ.get("GPTOSS_BASE_URL"),
                   help="OpenAI-compatible base_url; omit (None) to hit the real OpenAI API")
    p.add_argument("--api-key-env", default="GPTOSS_KEY",
                   help="env var holding the API key, e.g. OPENAI_API_KEY for real OpenAI")
    p.add_argument("--report-only", action="store_true")
    return p.parse_args()


def _level(case):  # "II-15" -> "II"
    return case.split("-")[0]


# 【职责】主流程：读断点续跑进度 -> 跑基线（cold/select/fixed）-> 跑 K 次独立进化并
#   逐轮在留出集评测 -> 打印汇总报告。
def main():
    args = parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    res_path = out / "results.jsonl"

    done = {}
    if res_path.exists():
        for line in open(res_path):
            try:
                r = json.loads(line)
                done[(r["kind"], r.get("run"), r.get("round"), r["case"], r["seed"])] = r["em"]
            except Exception:
                pass

    if not args.report_only:
        cfg = RunConfig(
            benchmark="silo_bench", objective="accuracy_first",
            merge_mode="llm_full_merge", init_mode="llm_local_solve",
            llm_provider="openai",
            model_name=args.model,
            base_url=args.base_url, api_key_env=args.api_key_env,
            evolved_mode="graph_generate", num_graph_candidates=3, n_agents=5,
            request_timeout=180.0,
        )
        adapter = SiloBenchAdapter("third_party/acl26-silo-bench/benchmarks")
        client = _bounded(_build_llm_client(cfg), args.workers)
        obj = evolution_objective_spec(cfg)
        ti = {c: list(adapter.iter_instances(levels=LEVELS, agent_counts=[5], cases=[c]))[0] for c in args.test}
        res_f = open(res_path, "a")

        # 【职责】把一个 eval 单元格去重后追加写入 results.jsonl（已存在则跳过）。
        def rec(kind, run, rnd, case, seed, em, cost=None):
            k = (kind, run, rnd, case, seed)
            if k in done:
                return
            d = {"kind": kind, "run": run, "round": rnd, "case": case, "seed": seed, "em": em}
            if cost:
                d.update(cost)  # tokens / messages / model_calls
            res_f.write(json.dumps(d) + "\n")
            res_f.flush(); done[k] = em

        def _row_cost(row):  # gen/select path: _run_one returns a score-row dict
            return {"tokens": float(row.get("MeanTokenCost", 0.0) or 0.0),
                    "messages": float(row.get("MeanTotalMessages", 0.0) or 0.0),
                    "model_calls": float(row.get("MeanTotalModelCalls", 0.0) or 0.0)}

        # 【职责】用当前技能库+motif 在一道实例上跑 graph_generate，返回 (精确匹配率, 开销)。
        def gen_em(bank, motif, inst, seed):
            row = _run_one(inst, replace(cfg, planner_mode="graph_generate"), objective=obj,
                           skill_bank=bank, seed=seed, llm_client=client, motif_stats=motif or None)
            return float(row.get("ExactMatchRate", 0.0)), _row_cost(row)

        # 中文：基线（确定性 -> 只测一次，跨 K 次运行复用）。
        # ---- baselines (deterministic -> measured once, reused across runs) ----
        for case in args.test:
            try:
                inst = ti[case]
                for seed in args.eval_seeds:
                    if ("cold", None, None, case, seed) not in done:
                        em, cost = gen_em(SkillBank(), {}, inst, seed)
                        rec("cold", None, None, case, seed, em, cost)
                    if ("select", None, None, case, seed) not in done:
                        row = _run_one(inst, replace(cfg, planner_mode="topology_select"), objective=obj,
                                       skill_bank=SkillBank(), seed=seed, llm_client=client)
                        rec("select", None, None, case, seed, float(row.get("ExactMatchRate", 0.0)), _row_cost(row))
                    for topo in args.fixed:
                        if (f"fixed:{topo}", None, None, case, seed) not in done:
                            s = run_fixed_protocol(inst, replace(cfg, seed=seed), topology=topo, llm_client=client)
                            scost = {"tokens": float(getattr(s, "tokens", 0) or 0),
                                     "messages": float(getattr(s, "n_messages", 0) or 0),
                                     "model_calls": float(getattr(s, "n_model_calls", 0) or 0)}
                            rec(f"fixed:{topo}", None, None, case, seed, 1.0 if s.success else 0.0, scost)
                print(f"[baselines] {case} done", flush=True)
            # 中文：网络抖动等 -> 跳过该 case，断点续跑会重试它。
            except Exception as e:  # network blip etc. -> skip this case, resume retries it
                print(f"[baselines] {case} FAILED ({type(e).__name__}); resume will retry", flush=True)

        # 中文：gen：K 次独立进化运行，每轮在留出集评测。
        # ---- gen: K independent evolution runs, eval held-out each round ----
        def _ckpt(run, rnd):
            return out / f"bank_run{run}_round{rnd}.json"

        for run in range(args.k_runs):
            # 中文：运行级续跑：完全跑完的运行直接整体跳过。
            # Run-level resume: skip a fully-finished run outright.
            if all(("gen", run, rnd, c, s) in done
                   for rnd in range(1, args.rounds + 1) for c in args.test for s in args.eval_seeds):
                print(f"[run {run}] all eval cells present -> skip (resume)", flush=True)
                continue
            try:
                # 中文：轮次级续跑：进化后的技能库每轮都检查点落盘，故重启从最深的已存
                #   轮次继续，而非从空库重新进化整条轨迹。
                # Round-level resume: the evolved skill bank is checkpointed to disk
                # after every round, so a restart continues from the deepest saved
                # round instead of re-evolving the whole trajectory from an empty bank.
                start_round, prev_skills, motif = 1, None, {}
                for rnd in range(args.rounds, 0, -1):
                    ck = _ckpt(run, rnd)
                    if ck.exists():
                        d = json.load(open(ck))
                        prev_skills, motif, start_round = d["skills"], d.get("motif", {}), rnd + 1
                        print(f"[run {run}] loaded round-{rnd} checkpoint -> resume at round {start_round}", flush=True)
                        break
                # 中文：每次运行用不同的训练种子，得到互异的进化轨迹。
                tseeds = [s + 1000 * run for s in args.train_seeds]  # distinct evolution trajectory per run
                for rnd in range(start_round, args.rounds + 1):
                    summ = run_evolution(adapter, cases=args.train, agent_counts=[5],
                                         train_seeds=tseeds, val_seeds=args.val_seeds,
                                         cfg=replace(cfg, planner_mode="graph_generate"), levels=LEVELS,
                                         llm_client=client, workers=args.workers, progress=False,
                                         initial_skills=prev_skills or None)
                    bank, nm = _bank_and_motif(summ); motif = _merge_motif(motif, nm)
                    for case in args.test:
                        inst = ti[case]
                        for seed in args.eval_seeds:
                            if ("gen", run, rnd, case, seed) not in done:
                                em, cost = gen_em(bank, motif, inst, seed)
                                rec("gen", run, rnd, case, seed, em, cost)
                    prev_skills = [s.model_dump(mode="json") for s in bank]
                    json.dump({"skills": prev_skills, "motif": motif}, open(_ckpt(run, rnd), "w"))
                    print(f"[run {run} round {rnd}] skills={len(bank)} done", flush=True)
            # 中文：轮次中途失败 -> 断点续跑从最后保存的检查点继续。
            except Exception as e:  # mid-round failure -> resume continues from last saved checkpoint
                print(f"[run {run}] FAILED ({type(e).__name__}); resume continues from last checkpoint", flush=True)
        res_f.close()

    # ---------------- summary ----------------
    report(done, args)


# 【职责】打印汇总报告：进化曲线、final gen 对比各基线（含 oracle fixed）、按难度分解。
def report(done, args):
    def cells(kind, run=None, rnd=None):
        return {(c, s): em for (k, r, rd, c, s), em in done.items()
                if k == kind and r == run and rd == rnd}

    def mean(d):
        return statistics.mean(d.values()) if d else float("nan")

    # 中文：用实际存在的最深 gen 轮次，这样 --report-only 即使没有对应的 --rounds
    #   也能汇总到正确的“最终”轮（而非 nan）。
    # use the deepest gen round actually present, so --report-only WITHOUT a
    # matching --rounds still summarizes the right "final" round (not a nan)
    gen_rounds = [rd for (k, r, rd, c, s) in done if k == "gen" and rd is not None]
    max_round = max(gen_rounds) if gen_rounds else args.rounds

    print("\n================ FULL EVAL SUMMARY ================")
    # 中文：1) 进化曲线（每轮留出平均 EM，跨 K 次运行取平均）。
    # 1) evolution curve (mean held-out EM per round, averaged over K runs)
    print("\n[1] GEN evolution curve (held-out mean EM, avg over K runs):")
    cold = cells("cold")
    print(f"  coldgen (round 0): {mean(cold):.3f}")
    for rnd in range(1, max_round + 1):
        per_run = [mean(cells("gen", run, rnd)) for run in range(args.k_runs) if cells("gen", run, rnd)]
        if per_run:
            print(f"  round {rnd}: mean={statistics.mean(per_run):.3f}  per-run={[round(x,2) for x in per_run]}")

    # 中文：2) final gen 对比各基线，按难度 + 汇总。
    # 2) final gen vs baselines, per difficulty + aggregate
    finals = [mean(cells("gen", run, max_round)) for run in range(args.k_runs) if cells("gen", run, max_round)]
    gen_final = statistics.mean(finals) if finals else float("nan")
    fixed_means = {t: mean(cells(f"fixed:{t}")) for t in args.fixed}
    fixed_best_single = max(fixed_means.values()) if fixed_means else float("nan")
    # 中文：逐 (case,seed) 的 oracle fixed = 该单元格的最优拓扑（事后最优固定拓扑）。
    # per-(case,seed) oracle fixed = best topology for that cell
    oracle = {}
    for c in args.test:
        for s in args.eval_seeds:
            vals = [done.get((f"fixed:{t}", None, None, c, s)) for t in args.fixed]
            vals = [v for v in vals if v is not None]
            if vals:
                oracle[(c, s)] = max(vals)
    print("\n[2] FINAL gen vs baselines (mean EM):")
    print(f"  gen (round {max_round}, avg K runs) = {gen_final:.3f}   per-run={[round(x,2) for x in finals]}")
    print(f"  coldgen                              = {mean(cold):.3f}")
    print(f"  select                               = {mean(cells('select')):.3f}")
    for t, m in fixed_means.items():
        print(f"  fixed:{t[:26]:26s} = {m:.3f}")
    print(f"  fixed_best_single                    = {fixed_best_single:.3f}   (gen-fixedbest = {gen_final-fixed_best_single:+.3f})")
    print(f"  per-case ORACLE fixed                = {mean(oracle):.3f}   (gen-oracle    = {gen_final-mean(oracle):+.3f})")

    # 中文：3) 按难度分解（final gen 对比 fixed_best_single）。
    # 3) per-difficulty breakdown (final gen vs fixed_best_single)
    print("\n[3] per-difficulty (final gen vs each fixed):")
    for lv in LEVELS:
        cs = [c for c in args.test if _level(c) == lv]
        gvals = [done.get(("gen", run, max_round, c, s)) for run in range(args.k_runs) for c in cs for s in args.eval_seeds]
        gvals = [v for v in gvals if v is not None]
        gm = statistics.mean(gvals) if gvals else float("nan")
        row = f"  L{lv}: gen={gm:.2f}"
        for t in args.fixed:
            fv = [done.get((f"fixed:{t}", None, None, c, s)) for c in cs for s in args.eval_seeds]
            fv = [v for v in fv if v is not None]
            row += f"  {t.split('_')[0]}={statistics.mean(fv):.2f}" if fv else ""
        print(row)
    print("===================================================")


if __name__ == "__main__":
    main()
