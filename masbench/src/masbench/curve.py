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
from __future__ import annotations

from dataclasses import replace
from typing import Any

from exp_graph.llm.base import LLMClient
from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.engine import _build_llm_client
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution


def _split_cases(cases: list[str], holdout_frac: float) -> tuple[list[str], list[str]]:
    """Disjoint TRAIN/TEST case split (last ``holdout_frac`` -> test)."""
    cases = sorted(cases)
    n_test = max(1, round(len(cases) * holdout_frac))
    n_test = min(n_test, len(cases) - 1) if len(cases) > 1 else 0
    if n_test == 0:
        return cases, cases  # single case -> reuse (degenerate, offline-honest)
    return cases[:-n_test], cases[-n_test:]


def _evolved_planner_mode(evolved_mode: str) -> str:
    return "graph_generate" if evolved_mode == "graph_generate" else "topology_select"


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
) -> float:
    """Mean held-out success of a policy (generate-from-bank, or select)."""
    ecfg = replace(cfg, planner_mode="graph_generate" if generate else "topology_select")
    scores: list[float] = []
    for inst in instances:
        for seed in seeds:
            row = _run_one(
                inst, ecfg, objective=objective, skill_bank=bank, seed=seed,
                llm_client=client, motif_stats=motif_stats,
            )
            scores.append(float(row.get("ExactMatchRate", 0.0)))
    return sum(scores) / len(scores) if scores else float("nan")


def _bank_and_motif(summary: dict[str, Any]) -> tuple[SkillBank, dict[str, dict]]:
    bank = SkillBank(skills=[SkillCard.model_validate(s) for s in summary.get("evolved_skills", [])])
    return bank, (summary.get("evolved_motif_stats") or {})


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
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Produce the data + rounds learning curves on a disjoint held-out set."""
    client = llm_client or _build_llm_client(cfg)
    objective = evolution_objective_spec(cfg)
    instances = list(adapter.iter_instances(levels=levels, agent_counts=[n_agents], cases=cases))
    all_cases = sorted({i.case_id for i in instances})
    train_cases, test_cases = _split_cases(all_cases, holdout_frac)
    test_set = set(test_cases)
    test_instances = [i for i in instances if i.case_id in test_set]
    generate = cfg.evolved_mode in ("graph_generate", "select_then_refine")
    train_seeds = list(seeds[:-1]) or list(seeds)
    val_seeds = [seeds[-1]] if seeds else [0]
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))

    def eval_held_out(bank, motif, gen):
        return _eval_score(bank, motif, cfg, test_instances, seeds, client, objective, generate=gen)

    baselines = {
        "select": eval_held_out(SkillBank(), None, False),
        "graphgen": eval_held_out(SkillBank(), None, True),
    }
    empty = eval_held_out(SkillBank(), None, generate)

    # DATA curve: evolve on the first k train cases (k grows), score held-out.
    ks = sorted({max(1, round(len(train_cases) * i / data_points)) for i in range(1, data_points + 1)})
    data_curve = [{"k_cases": 0, "score": empty, "n_skills": 0}]
    for k in ks:
        summ = run_evolution(
            adapter, cases=train_cases[:k], agent_counts=[n_agents],
            train_seeds=train_seeds, val_seeds=val_seeds, cfg=evo_cfg, levels=levels,
            llm_client=client,
        )
        bank, motif = _bank_and_motif(summ)
        data_curve.append({
            "k_cases": k, "score": eval_held_out(bank, motif, generate),
            "n_skills": len(bank), "gate": summ.get("gate"),
        })

    # ROUNDS curve: iterate, accumulating bank + motif across rounds.
    rounds_curve = [{"round": 0, "score": empty, "n_skills": 0}]
    bank, motif = SkillBank(), {}
    for r in range(1, rounds + 1):
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[n_agents],
            train_seeds=train_seeds, val_seeds=val_seeds, cfg=evo_cfg, levels=levels,
            llm_client=client,
            initial_skills=[s.model_dump(mode="json") for s in bank],
        )
        new_bank, new_motif = _bank_and_motif(summ)
        bank, motif = new_bank, _merge_motif(motif, new_motif)
        rounds_curve.append({
            "round": r, "score": eval_held_out(bank, motif, generate),
            "n_skills": len(bank), "gate": summ.get("gate"),
        })

    return {
        "evolved_mode": cfg.evolved_mode,
        "n_agents": n_agents,
        "train_cases": train_cases,
        "test_cases": test_cases,
        "baselines": baselines,
        "data_curve": data_curve,
        "rounds_curve": rounds_curve,
    }
