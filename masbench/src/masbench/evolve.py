"""QueenBee self-evolution loop on Silo-Bench, with the Plan-3 improvements ON.

``run_evolution`` wires the improved self-evolution end to end on Silo-Bench:

1. Split the filtered Silo instances into TRAIN and HELD-OUT (VAL) sets.
2. Run every TRAIN/VAL instance through the QueenBee planner + ProtocolRunner
   (the same machinery ``engine._run_planner`` uses) across a few objective
   variants so the planner genuinely selects several topologies, and turn each
   run summary into an aggregate row via ``summary_to_aggregate_row`` (generic).
3. Have ``ResultAnalystMinister`` propose skill patches from the TRAIN rows.
4. Apply them through the held-out **validation gate**
   (``consolidate_skill_updates(gate=True, validation_rows=...)``), accepting the
   batch only if it does not regress the held-out objective ``J_val``.
5. Return a summary with the real gate decision (``j_before``/``j_after``,
   accept/reject) and the pre/post held-out success rates.

The planner requests carry an :class:`ObjectiveSpec` with the Plan-3 improvement
knobs activated, so the loop exercises:

* **D** validation gate — ``consolidate_skill_updates(gate=True)``;
* **E** uncertainty-aware selection — ``uncertainty_weight`` (kappa) + ``min_seeds``;
* **F** counterexample veto + absolute floor — ``enforce_avoid_veto`` +
  ``max_acceptable_loss`` + ``risk_weight`` in ``TopologySelectPlanner.plan``.

Offline honesty
---------------
Silo's deterministic offline path is *topology-invariant on success*: a fake-LLM
run of a given case either solves it (loss 0) or not (loss 1), the same way for
every topology. Real offline Silo rows therefore cannot, by themselves, make one
topology look better than another on the held-out objective the gate uses. To
keep the gate decision **real** offline we let the caller supply a small synthetic
multi-topology held-out set (``held_out_rows``); the CLI defaults to one. The gate
arithmetic — which topology the planner selects on held-out data before vs. after
the patch batch, and whether ``J_val`` improves — is computed by the real gate.
With a real LLM (or multi-seed Silo runs that actually differ per topology) the
synthetic rows are unnecessary and ``held_out_rows`` can be left ``None``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.llm.base import LLMClient
from exp_graph.mas.consolidation import consolidate_skill_updates
from exp_graph.mas.evolution import ResultAnalystMinister
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.runner import summary_to_aggregate_row
from exp_graph.mas.schemas import ObjectiveSpec, PlannerRequest, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.engine import _build_llm_client

# Task family the Silo planner/evolution operate in. The ResultAnalyst minister
# accepts a ``task_family`` argument and stamps every emitted skill card, its
# trigger, and its (family-namespaced) skill_id with this family natively, so the
# planner retrieval, the held-out gate, and the post-evolution selection probe all
# operate consistently in one family without any post-hoc re-tagging.
SILO_TASK_FAMILY = "silo"

# Default Plan-3 improvement knobs activated on the planner objective. These turn
# on E (uncertainty-aware selection) and F (counterexample veto + risk floor); the
# gate (D) is turned on separately via ``consolidate_skill_updates(gate=True)``.
DEFAULT_UNCERTAINTY_WEIGHT = 1.0
DEFAULT_MIN_SEEDS = 1
DEFAULT_RISK_WEIGHT = 0.5
DEFAULT_MAX_ACCEPTABLE_LOSS = 0.99


def evolution_objective_spec(
    cfg: RunConfig,
    *,
    uncertainty_weight: float = DEFAULT_UNCERTAINTY_WEIGHT,
    min_seeds: int = DEFAULT_MIN_SEEDS,
    risk_weight: float = DEFAULT_RISK_WEIGHT,
    max_acceptable_loss: float | None = DEFAULT_MAX_ACCEPTABLE_LOSS,
) -> ObjectiveSpec:
    """Build the planner objective with the Plan-3 improvement knobs turned ON."""
    spec = ObjectiveSpec.from_name(cfg.objective)  # type: ignore[arg-type]
    return spec.model_copy(
        update={
            "uncertainty_weight": uncertainty_weight,
            "min_seeds": min_seeds,
            "enforce_avoid_veto": True,
            "risk_weight": risk_weight,
            "max_acceptable_loss": max_acceptable_loss,
        }
    )


def _run_one(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    objective: ObjectiveSpec,
    skill_bank: SkillBank,
    seed: int,
    llm_client: LLMClient,
) -> dict[str, Any]:
    """Run one instance through the QueenBee planner path and return its row.

    Mirrors ``engine._run_planner`` but uses a caller-supplied (knob-on)
    ``ObjectiveSpec`` and a shared ``SkillBank`` so the Plan-3 E/F selection knobs
    genuinely influence topology selection during evidence collection.
    """
    task_adapter = SiloProtocolAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents

    request = PlannerRequest(
        task_family=SILO_TASK_FAMILY,
        n_agents=n_agents,
        objective=objective,
    )
    plan = EmperorPlanner(skill_bank).plan(request)

    config_kwargs: dict[str, Any] = {
        "topology_name": plan.topology_name,
        "n_agents": n_agents,
        "seed": seed,
        "merge_mode": cfg.merge_mode,
        "init_mode": cfg.init_mode,
        "protocol_spec": plan.protocol_spec,
        "llm_provider": cfg.llm_provider,
        "model_name": cfg.model_name,
        "temperature": cfg.temperature,
    }
    config_kwargs.update(plan.config_overrides)
    config = ProtocolRunnerConfig(**config_kwargs)

    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=llm_client,
    ).run()
    summary = result.to_summary_dict()
    row = summary_to_aggregate_row(summary)
    # Tag the row with its condition + family so val/train grouping is honest per
    # (n, case) and the held-out gate evaluates in the silo family.
    row["case_id"] = instance.case_id
    row["seed"] = seed
    row["task_family"] = SILO_TASK_FAMILY
    return row


def _split_train_val(
    instances: list[BenchmarkInstance],
) -> tuple[list[BenchmarkInstance], list[BenchmarkInstance]]:
    """Stable TRAIN/VAL split over the instance *set* (not over seeds).

    Silo instances are fixed per ``(case, n_agents)`` and the deterministic
    offline path is seed-invariant, so simulating seeds would yield identical
    rows and a degenerate gate. We therefore split the instance set: even sorted
    indices go to TRAIN, odd to VAL. With a single instance it lands in both so
    the loop still runs end to end (and the gate still has held-out rows).
    """
    ordered = sorted(instances, key=lambda inst: (inst.case_id, inst.n_agents))
    if len(ordered) == 1:
        return ordered, ordered
    train = [inst for idx, inst in enumerate(ordered) if idx % 2 == 0]
    val = [inst for idx, inst in enumerate(ordered) if idx % 2 == 1]
    if not train:
        train = ordered
    if not val:
        val = ordered
    return train, val


def _success_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    # ExactMatchRate is 1.0 for a solved single run, 0.0 otherwise.
    return sum(float(row.get("ExactMatchRate", 0.0)) for row in rows) / len(rows)


def _incumbent_skill(topology: str, *, objective_name: str) -> SkillCard:
    """A deliberately-advertised incumbent skill the planner can select.

    Used to give the planner a concrete starting choice so the gate measures a
    real ``J_before`` (the held-out loss of this incumbent topology) against the
    ``J_after`` produced by the minister's TRAIN-derived patches. Tagged
    ``balanced`` so it is retrieved by both the knob-on planner requests and the
    gate's internal balanced request (``balanced`` is always in the allowed
    objective set), rather than relying on the planner's no-match fallback.
    """
    return SkillCard(
        skill_id=f"silo_incumbent_{topology}",
        objective="balanced",
        task_family=SILO_TASK_FAMILY,
        trigger={"task_family": SILO_TASK_FAMILY, "min_agents": 1, "max_agents": 999},
        organization_policy={
            "planner_mode": "topology_select",
            "topology_name": topology,
        },
        expected_tradeoff={
            "mean_rmse": 0.5,
            "mean_primary_loss": 0.5,
            "mean_token_cost": 1000.0,
            "mean_messages": 10.0,
            "active_evidence_count": 1,
        },
        confidence={"seed_count": 1},
        tags=["mas", "emperor-skill", "silo", objective_name],
    )


def _collect_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    objective_variants: list[ObjectiveSpec],
    seeds: list[int],
    llm_client: LLMClient,
) -> list[dict[str, Any]]:
    """Collect real planner-run rows across objective variants.

    Each run uses a *fresh* empty ``SkillBank`` so the planner genuinely selects
    that objective's default topology (accuracy_first -> peer_star, budget_first
    -> tree, balanced -> mesh_star). Running every instance under several
    objectives yields multi-topology evidence, which is what lets the held-out
    validation gate make a non-degenerate accept/reject decision.
    """
    rows: list[dict[str, Any]] = []
    for inst in instances:
        for objective in objective_variants:
            for seed in seeds or [0]:
                rows.append(
                    _run_one(
                        inst,
                        cfg,
                        objective=objective,
                        skill_bank=SkillBank(),
                        seed=seed,
                        llm_client=llm_client,
                    )
                )
    return rows


def run_evolution(
    adapter: SiloBenchAdapter,
    *,
    cases: list[str] | None,
    agent_counts: list[int] | None,
    train_seeds: list[int],
    val_seeds: list[int],
    cfg: RunConfig,
    levels: list[str] | None = None,
    held_out_rows: list[dict[str, Any]] | None = None,
    seed_incumbent_topology: str | None = None,
    objective_variants: list[str] | None = None,
    epsilon: float = 0.0,
    batch_id: str = "silo_evolve_batch",
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Run the gated QueenBee self-evolution loop on Silo-Bench.

    Returns a JSON-serializable summary with the real gate decision and the
    pre/post held-out success rates. See the module docstring for the offline
    honesty caveat about ``held_out_rows``.
    """
    objective = evolution_objective_spec(cfg)
    client = llm_client or _build_llm_client(cfg)

    # Evidence is collected across objective variants so the minister observes
    # several topologies. Each variant carries the same Plan-3 E/F knobs.
    variant_names = objective_variants or ["accuracy_first", "budget_first", "balanced"]
    variant_specs = [
        evolution_objective_spec(
            RunConfig(**{**asdict(cfg), "objective": name})
        )
        for name in variant_names
    ]

    instances = list(
        adapter.iter_instances(
            levels=levels,
            agent_counts=agent_counts,
            cases=cases,
        )
    )
    if not instances:
        raise SystemExit(
            "no Silo-Bench instances matched the given cases/agent-counts/levels"
        )
    train_instances, val_instances = _split_train_val(instances)

    # The evolving (held-out) bank is the one the gate mutates. Optionally seed an
    # incumbent so the gate has a concrete starting selection to improve on.
    skill_bank = SkillBank()
    if seed_incumbent_topology:
        skill_bank.apply_patch(
            SkillPatch(
                patch_id=f"seed_{seed_incumbent_topology}",
                action="add",
                candidate_skill=_incumbent_skill(
                    seed_incumbent_topology, objective_name=objective.name
                ),
            )
        )

    train_rows = _collect_rows(
        train_instances,
        cfg,
        objective_variants=variant_specs,
        seeds=train_seeds,
        llm_client=client,
    )
    val_rows_real = _collect_rows(
        val_instances,
        cfg,
        objective_variants=variant_specs,
        seeds=val_seeds,
        llm_client=client,
    )

    # Held-out validation rows the gate scores against: real Silo VAL rows plus
    # any caller-supplied synthetic multi-topology rows (see module docstring).
    val_rows = [*val_rows_real, *(held_out_rows or [])]

    # The minister stamps every emitted skill (card, trigger, and namespaced id)
    # with the silo family natively, so retrieval, the held-out gate, and the
    # selection probe all operate in one family with no post-hoc re-tagging.
    patches = ResultAnalystMinister().analyze(
        train_rows, task_family=SILO_TASK_FAMILY
    )

    size_before = len(skill_bank)
    _bank, result = consolidate_skill_updates(
        bank=skill_bank,
        patches=patches,
        evidence_records=[],
        batch_id=batch_id,
        validation_rows=val_rows,
        epsilon=epsilon,
        gate=True,
    )
    size_after = len(skill_bank)

    # Post-evolution selection probe: run the knob-on planner against the (now
    # populated) evolved bank. Unlike evidence collection (which uses fresh empty
    # banks and therefore falls back to objective defaults), this genuinely
    # executes the E (LCB + min-seeds) and F (veto + floor + risk) selection logic
    # on real skills, so the improvement knobs are exercised, not merely set.
    final_selection = _selection_probe(skill_bank, cfg.n_agents or 2, objective)

    accepted = bool(result.gate_accepted)
    return {
        "benchmark": cfg.benchmark,
        "objective": cfg.objective,
        "config": asdict(cfg),
        "objective_knobs": {
            "uncertainty_weight": objective.uncertainty_weight,
            "min_seeds": objective.min_seeds,
            "enforce_avoid_veto": objective.enforce_avoid_veto,
            "risk_weight": objective.risk_weight,
            "max_acceptable_loss": objective.max_acceptable_loss,
        },
        "train_cases": [inst.case_id for inst in train_instances],
        "val_cases": [inst.case_id for inst in val_instances],
        "n_train_rows": len(train_rows),
        "n_val_rows": len(val_rows),
        "n_val_rows_real": len(val_rows_real),
        "n_synthetic_held_out_rows": len(held_out_rows or []),
        "train_success_rate": _success_rate(train_rows),
        "val_success_rate": _success_rate(val_rows_real),
        "n_patches": len(patches),
        "gate": {
            "accepted": accepted,
            "j_before": float(result.gate_j_before)
            if result.gate_j_before is not None
            else 0.0,
            "j_after": float(result.gate_j_after)
            if result.gate_j_after is not None
            else 0.0,
            "epsilon": epsilon,
            "counts": dict(result.counts),
            "warnings": list(result.warnings),
        },
        "skill_bank_size_before": size_before,
        "skill_bank_size_after": size_after,
        "skill_bank_mutated": accepted,
        "skill_ids_after": sorted(skill.skill_id for skill in skill_bank),
        "final_selection": final_selection,
    }


def _selection_probe(
    bank: SkillBank,
    n_agents: int,
    objective: ObjectiveSpec,
) -> dict[str, Any]:
    """Run the knob-on planner on the evolved bank and report its selection.

    This is where the Plan-3 E/F selection knobs actually execute on real skills:
    ``score_skill`` runs the LCB accuracy penalty (E), ``retrieve`` runs the
    min-seeds gate (E), and ``TopologySelectPlanner.plan`` runs the
    veto/floor/risk logic (F). Returns the chosen topology, the score breakdown
    (which carries the LCB diagnostics), and the planner rationale (which records
    any counterexample veto).
    """
    request = PlannerRequest(
        task_family=SILO_TASK_FAMILY,
        n_agents=n_agents,
        objective=objective,
    )
    plan = EmperorPlanner(bank).plan(request)
    return {
        "topology_name": plan.topology_name,
        "skill_id": plan.skill_id,
        "score": plan.score,
        "score_breakdown": plan.score_breakdown,
        "rationale": plan.rationale,
    }


# A baseline topology that exists only in the synthetic held-out rows and is
# distinct from the three topologies the minister produces (tree, mesh_star,
# one_peer_exponential_dag_star). Used as the seeded incumbent so the gate's
# accept/reject direction is decided by "incumbent vs. the three TRAIN topologies"
# and does not depend on which of the three the gate's planner happens to pick.
INCUMBENT_BASELINE_TOPOLOGY = "incumbent_baseline"

# The three topologies the ResultAnalyst minister advertises from runs across the
# default objective variants (accuracy_first/budget_first/balanced).
_TRAIN_TOPOLOGIES = ("one_peer_exponential_dag_star", "tree", "mesh_star")


def accepting_held_out_rows() -> list[dict[str, Any]]:
    """Synthetic held-out rows that make the gate ACCEPT the TRAIN patch batch.

    Pair with ``seed_incumbent_topology=INCUMBENT_BASELINE_TOPOLOGY``. The
    incumbent baseline is the worst held-out topology (loss 1) and every topology
    the minister learns from TRAIN is good (loss 0). Before the batch the gate's
    planner can only pick the incumbent (``J_before`` = 1); after it, it picks one
    of the TRAIN topologies (``J_after`` = 0), so ``J_after`` < ``J_before`` ->
    ACCEPT, regardless of which TRAIN topology the planner's tiebreak selects.
    """
    return [
        _held_out_row(topology=INCUMBENT_BASELINE_TOPOLOGY, loss=1.0),
        *[_held_out_row(topology=topo, loss=0.0) for topo in _TRAIN_TOPOLOGIES],
    ]


def rejecting_held_out_rows() -> list[dict[str, Any]]:
    """Synthetic held-out rows that make the gate REJECT the TRAIN patch batch.

    Pair with ``seed_incumbent_topology=INCUMBENT_BASELINE_TOPOLOGY``. The mirror
    of :func:`accepting_held_out_rows`: the incumbent baseline is the *best*
    held-out topology (loss 0) and every TRAIN topology is bad (loss 1). Before the
    batch the planner picks the incumbent (``J_before`` = 0); adopting the batch
    would switch it to a worse TRAIN topology (``J_after`` = 1), so ``J_after`` >
    ``J_before`` -> REJECT and the held-out bank is left untouched.
    """
    return [
        _held_out_row(topology=INCUMBENT_BASELINE_TOPOLOGY, loss=0.0),
        *[_held_out_row(topology=topo, loss=1.0) for topo in _TRAIN_TOPOLOGIES],
    ]


def _held_out_row(
    *,
    topology: str,
    loss: float,
    agents: int = 2,
) -> dict[str, Any]:
    """One synthetic held-out aggregate row in the minister/gate row shape.

    ``MeanPrimaryMetric`` is a higher-is-better success rate (``1 - loss``) tagged
    ``PrimaryMetricName="primary"``, exactly the shape ``summary_to_aggregate_row``
    emits for Silo, so the gate's ``validation_objective`` converts it to ``loss``
    via the shared ``primary_loss`` rule.
    """
    success = 1.0 - loss
    return {
        "Topology": topology,
        "Agents": agents,
        "ArraySize": 0,
        "MergeMode": "deterministic",
        "InitMode": "deterministic",
        "Runs": 1,
        "MeanFinalRMSE": loss,
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": 0.0,
        "ExactMatchRate": success,
        "MeanPrimaryMetric": success,
        "PrimaryMetricName": "primary",
        "MeanTotalSteps": 4,
        "MeanTotalMessages": 10.0,
        "MeanTotalModelCalls": 0,
        "MeanTokenCost": 1000.0,
        "MeanVoteTopRatio": 1.0,
        "task_family": SILO_TASK_FAMILY,
    }
