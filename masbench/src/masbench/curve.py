"""Evolution learning curves on a DISJOINT held-out case set.

Two axes (both produced):
* **data** -- evolve on the first ``k`` TRAIN cases (k grows) and score on the
  held-out TEST cases. The honest generalization curve: Silo *cases* are the real
  tasks (seeds only change run RNG), and TRAIN/TEST are disjoint by case.
* **rounds** -- iterate R self-evolution rounds on the full train set, ACCUMULATING
  the skill bank + motif prior across rounds (``run_evolution(initial_skills=)`` +
  motif merge), scoring the held-out TEST set after each round.

Baselines (no evolution) on the SAME held-out set are flat reference lines:
``select`` (planner picks a named topology) and ``graphgen`` (cold generation).

Offline (``--llm fake``) Silo is topology-invariant -> the curves are flat; this
is a REAL-LLM tool. The structure (points, baselines, disjoint split) is what the
offline tests pin.
"""
# ============================================================
# 【模块导读】在“互不相交的留出 case 集”上画进化学习曲线，两条轴都产出：
# - data：在前 k 个训练 case 上进化（k 递增），在留出的 TEST case 上评分——诚实的
#   泛化曲线（Silo 的 case 才是真任务，种子只改运行 RNG，训练/测试按 case 不相交）。
# - rounds：在整个训练集上迭代 R 轮自进化，跨轮累积技能库 + motif 先验，每轮后在留出
#   TEST 集上评分。
# 基线（无进化）在同一留出集上是水平参考线：select（规划器选命名拓扑）与 graphgen
# （冷生成）。离线（--llm fake）的 Silo 与拓扑无关 -> 曲线是平的；这是面向真实 LLM 的工具。
# ============================================================
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from exp_graph.llm.base import LLMClient
from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.engine import _build_llm_client
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution


# 【职责】包裹 LLMClient，使同时最多 max_inflight 个 complete 调用在跑。
# - --workers 在多个嵌套层扇出（eval 网格、每次运行内部的 agent 池、探针 eval），它们
#   共用一个客户端；单独调各线程池大小无法约束其乘积，包住“客户端”才行。
# - 许可仅在调用本身期间持有——父线程等待子线程时绝不持有——故无“持有并等待”死锁。
class _BoundedLLMClient:
    """Wrap an LLMClient so at most ``max_inflight`` ``complete`` calls run at once.

    ``--workers`` fans out at several nesting levels (the eval grid, the per-run
    agent pool inside each ``_run_one``, and probe-eval), and they ALL share one
    client. Sizing each thread pool independently cannot bound the product;
    wrapping the *client* does, regardless of how the pools nest. The permit is
    held only around the call itself -- never while a parent thread waits on its
    children -- so there is no hold-and-wait deadlock.
    """

    def __init__(self, inner: LLMClient, max_inflight: int) -> None:
        self._inner = inner
        self._gate = threading.BoundedSemaphore(max(1, int(max_inflight)))

    def complete(self, *args, **kwargs):
        with self._gate:
            return self._inner.complete(*args, **kwargs)


# 【职责】把并发 LLM 调用总数封顶为 workers（幂等，不重复加门）。
def _bounded(client: LLMClient, workers: int) -> LLMClient:
    """Cap total concurrent LLM calls at ``workers`` (idempotent, no double-gate)."""
    if workers <= 1 or isinstance(client, _BoundedLLMClient):
        return client
    return _BoundedLLMClient(client, workers)


# 【职责】把 case 划成互不相交的训练/测试集（末尾 holdout_frac 比例作测试）。
def _split_cases(cases: list[str], holdout_frac: float) -> tuple[list[str], list[str]]:
    """Disjoint TRAIN/TEST case split (last ``holdout_frac`` -> test)."""
    cases = sorted(cases)
    n_test = max(1, round(len(cases) * holdout_frac))
    n_test = min(n_test, len(cases) - 1) if len(cases) > 1 else 0
    if n_test == 0:
        # 中文：只有一个 case 时训练/测试复用同一集合（退化情形，离线诚实）。
        return cases, cases  # single case -> reuse (degenerate, offline-honest)
    return cases[:-n_test], cases[-n_test:]


def _evolved_planner_mode(evolved_mode: str) -> str:
    if evolved_mode == "program_generate":
        return "program_generate"
    if evolved_mode == "python_generate":
        return "python_generate"
    return "graph_generate" if evolved_mode == "graph_generate" else "topology_select"


# 【职责】某策略（从技能库生成，或 select）在留出集上的平均成功率。
# - (instance, seed) 的评测彼此独立 -> 按 workers 扇出并发。
def _eval_score(
    bank: SkillBank,
    motif_stats: dict[str, dict] | None,
    cfg: RunConfig,
    instances: list,
    seeds: list[int],
    client: LLMClient,
    objective,
    *,
    generate: bool,
    planner_mode: str | None = None,
    workers: int = 1,
) -> float:
    """Mean held-out success of a policy (generate-from-bank, or select).

    The (instance, seed) evals are independent -> fan out across ``workers``.
    """
    ecfg = replace(
        cfg,
        planner_mode=(
            planner_mode
            or ("graph_generate" if generate else "topology_select")
        ),
    )
    tasks = [(inst, seed) for inst in instances for seed in seeds]
    if not tasks:
        return float("nan")
    # 中文：全局封顶：这个网格发起的每个 LLM 调用——外层 (instance, seed) 池以及每个
    #   _run_one 内部的 agent/探针扇出——共用一个受限客户端，故在途总数永不超过 workers。
    # GLOBAL cap: every LLM call this grid makes -- across the outer (instance,
    # seed) pool AND the agent/probe fan-out inside each _run_one -- shares one
    # bounded client, so total in-flight never exceeds `workers`.
    client = _bounded(client, workers)

    def _one(task) -> float:
        inst, seed = task
        try:
            row = _run_one(
                inst, ecfg, objective=objective, skill_bank=bank, seed=seed,
                llm_client=client, motif_stats=motif_stats,
            )
        except Exception as exc:  # noqa: BLE001 - one wedged run must not kill the curve
            # 中文：无法跑完的运行对其实验臂就是失败（记 0 分）；P2 confirmatory-2 的曲线
            #   曾因一次 120s 超时而整条崩掉。
            # A run that cannot complete IS a failure for its arm (score 0);
            # P2 confirmatory-2's curve died whole on one 120s timeout.
            print(f"  [curve eval] {inst.case_id} seed={seed} FAILED: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return 0.0
        return float(row.get("ExactMatchRate", 0.0))

    if workers and workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
            scores = list(ex.map(_one, tasks))
    else:
        scores = [_one(t) for t in tasks]
    return sum(scores) / len(scores) if scores else float("nan")


# 【职责】从进化 summary 里取出技能库与 motif 统计。
def _bank_and_motif(summary: dict[str, Any]) -> tuple[SkillBank, dict[str, dict]]:
    bank = SkillBank(skills=[SkillCard.model_validate(s) for s in summary.get("evolved_skills", [])])
    return bank, (summary.get("evolved_motif_stats") or {})


# 【职责】合并两份 motif 统计：同键按样本数加权平均 mean_loss，累加 n。
def _merge_motif(a: dict[str, dict], b: dict[str, dict]) -> dict[str, dict]:
    out = {k: dict(v) for k, v in a.items()}
    for k, v in b.items():
        if k in out:
            na, nb = out[k].get("n", 0), v.get("n", 0)
            n = na + nb
            out[k] = {
                "mean_loss": (out[k]["mean_loss"] * na + v["mean_loss"] * nb) / n if n else 0.0,
                "n": n,
            }
        else:
            out[k] = dict(v)
    return out


# 【职责】在互不相交的留出集上产出 data + rounds 两条学习曲线。
# - workers 同时扇出每轮证据收集（run_evolution）与独立的留出 (instance, seed) 评测。
# - progress 为每个基线/数据点/轮次打印实时阶段行（并开启 run_evolution 的逐单位进度），
#   让长时间的真实 LLM 运行不至于静默。
def run_curves(
    adapter: SiloBenchAdapter,
    cfg: RunConfig,
    *,
    n_agents: int,
    seeds: list[int],
    levels: list[str] | None = None,
    cases: list[str] | None = None,
    holdout_frac: float = 0.3,
    data_points: int = 4,
    rounds: int = 4,
    workers: int = 1,
    progress: bool = False,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Produce the data + rounds learning curves on a disjoint held-out set.

    ``workers`` fans out both the per-round evidence collection
    (``run_evolution``) and the independent held-out (instance, seed) evals.
    ``progress`` prints a live phase line per baseline / data point / round (and
    enables ``run_evolution``'s per-unit ticks) so a long real-LLM run is not silent.
    """
    client = llm_client or _build_llm_client(cfg)
    # 中文：整条曲线共用一个全局并发帽：证据收集（run_evolution）与留出评测共享，使
    #   --workers 约束真实的并发 LLM 调用数，而非各阶段池宽度之和。
    # One global concurrency cap for the whole curve: shared by the evidence
    # collection (run_evolution) and the held-out evals so `--workers` bounds the
    # TRUE number of concurrent LLM calls, not the per-stage pool widths.
    client = _bounded(client, workers)
    objective = evolution_objective_spec(cfg)
    instances = list(adapter.iter_instances(levels=levels, agent_counts=[n_agents], cases=cases))
    all_cases = sorted({i.case_id for i in instances})
    train_cases, test_cases = _split_cases(all_cases, holdout_frac)
    test_set = set(test_cases)
    test_instances = [i for i in instances if i.case_id in test_set]
    generate = cfg.evolved_mode in (
        "graph_generate",
        "program_generate",
        "python_generate",
        "select_then_refine",
    )
    train_seeds = list(seeds[:-1]) or list(seeds)
    val_seeds = [seeds[-1]] if seeds else [0]
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))

    t0 = time.monotonic()

    def _say(msg: str) -> None:
        if progress:
            el = int(time.monotonic() - t0)
            print(f"[curve {cfg.evolved_mode}] {el // 60}:{el % 60:02d} {msg}", flush=True)

    def eval_held_out(bank, motif, gen):
        generated_mode = (
            cfg.evolved_mode
            if cfg.evolved_mode
            in {"graph_generate", "program_generate", "python_generate"}
            else "graph_generate"
        )
        return _eval_score(
            bank, motif, cfg, test_instances, seeds, client, objective,
            generate=gen,
            planner_mode=(generated_mode if gen else None),
            workers=workers,
        )

    _say(
        f"train={len(train_cases)} test={len(test_cases)} cases | "
        f"data_points={data_points} rounds={rounds} | workers={workers} (global cap)"
    )

    # 中文：留出集上的基线（无进化）——逐个打印，让最初的无进化阶段不至于静默。
    # Baselines (no evolution) on the held-out set -- printed one at a time so the
    # initial, evolution-free phase is not silent.
    _say(f"baselines: select on {len(test_instances)} test cases x {len(seeds)} seeds ...")
    select_base = eval_held_out(SkillBank(), None, False)
    generated_name = {
        "program_generate": "programgen",
        "python_generate": "pycodegen",
    }.get(cfg.evolved_mode, "graphgen")
    _say(f"baselines: select={select_base * 100:.1f}% | {generated_name} ...")
    generated_base = eval_held_out(SkillBank(), None, True)
    _say(f"baselines: {generated_name}={generated_base * 100:.1f}%")
    baselines = {"select": select_base, generated_name: generated_base}
    empty = eval_held_out(SkillBank(), None, generate)

    # 中文：DATA 曲线：在前 k 个训练 case 上进化（k 递增），在留出集上评分。
    # DATA curve: evolve on the first k train cases (k grows), score held-out.
    ks = sorted({max(1, round(len(train_cases) * i / data_points)) for i in range(1, data_points + 1)})
    data_curve = [{"k_cases": 0, "score": empty, "n_skills": 0}]
    for idx, k in enumerate(ks, 1):
        _say(f"DATA {idx}/{len(ks)}: evolving on {k} train cases ...")
        summ = run_evolution(
            adapter, cases=train_cases[:k], agent_counts=[n_agents],
            train_seeds=train_seeds, val_seeds=val_seeds, cfg=evo_cfg, levels=levels,
            llm_client=client, workers=workers, progress=progress,
        )
        bank, motif = _bank_and_motif(summ)
        score = eval_held_out(bank, motif, generate)
        _say(f"DATA {idx}/{len(ks)}: k={k} held-out={score * 100:.1f}% (skills={len(bank)})")
        data_curve.append({
            "k_cases": k, "score": score,
            "n_skills": len(bank), "gate": summ.get("gate"),
            "hot_start": summ.get("hot_start"),
        })

    # 中文：ROUNDS 曲线：迭代，跨轮累积技能库 + motif。
    # ROUNDS curve: iterate, accumulating bank + motif across rounds.
    rounds_curve = [{"round": 0, "score": empty, "n_skills": 0}]
    bank, motif = SkillBank(), {}
    for r in range(1, rounds + 1):
        _say(f"ROUNDS {r}/{rounds}: evolving (bank={len(bank)} skills) ...")
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[n_agents],
            train_seeds=train_seeds, val_seeds=val_seeds, cfg=evo_cfg, levels=levels,
            llm_client=client, workers=workers, progress=progress,
            initial_skills=[s.model_dump(mode="json") for s in bank],
        )
        new_bank, new_motif = _bank_and_motif(summ)
        bank, motif = new_bank, _merge_motif(motif, new_motif)
        score = eval_held_out(bank, motif, generate)
        _say(f"ROUNDS {r}/{rounds}: held-out={score * 100:.1f}% (skills={len(bank)})")
        rounds_curve.append({
            "round": r, "score": score,
            "n_skills": len(bank), "gate": summ.get("gate"),
            "hot_start": summ.get("hot_start"),
        })

    return {
        "evolved_mode": cfg.evolved_mode,
        "clean_run": not bool(getattr(cfg, "hot_start_enabled", False)),
        "hot_start_enabled": bool(getattr(cfg, "hot_start_enabled", False)),
        "n_agents": n_agents,
        "train_cases": train_cases,
        "test_cases": test_cases,
        "baselines": baselines,
        "data_curve": data_curve,
        "rounds_curve": rounds_curve,
    }
