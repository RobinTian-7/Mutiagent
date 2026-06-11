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

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from typing import Any

import masbench  # noqa: F401  (bootstraps exp_graph path)
from exp_graph.llm.base import LLMClient
from exp_graph.mas.consolidation import consolidate_skill_updates
from exp_graph.mas.evolution import ResultAnalystMinister
from exp_graph.mas.insights import (
    LLMInsightMinister,
    build_evidence_pack,
    falsify_insights,
    insight_report_to_patches,
)
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.motifs import aggregate_motif_losses, spec_motif_keys
from exp_graph.mas.runner import summary_to_aggregate_row
from exp_graph.mas.schemas import (
    EvidenceRecord,
    MASRuntimeConfig,
    ObjectiveSpec,
    PlannerRequest,
    SkillCard,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols.schedules import build_protocol_schedule
from exp_graph.protocols.spec import ProtocolGraphSpec, ProtocolStepSpec
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig

from masbench import diag
from masbench.cache import EvidenceCache, open_cache
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.engine import _build_llm_client, _plan_graph_generate
from masbench.task_classify import (
    classification_bucket,
    classification_kind,
    classify_task,
)
from masbench.transfer import (
    deployment_view,
    inject_transfer_evidence,
    namespace_motif_keys,
    snapshot_transfer_evidence,
)

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


def _executed_spec(plan: Any, n_agents: int) -> dict[str, Any] | None:
    """The executable schedule this run actually executed, as a spec dict.

    Generated plans already carry their spec. Named-topology (select) plans
    compile their schedule inside ProtocolRunner; rebuild it here with the SAME
    builder so the minister can store the schedule that actually ran. This is
    what makes select_then_refine real: skills carry executable reference
    schedules, and ``_skill_seeded_graph_candidates`` can replay/refine them at
    eval instead of receiving prompt context only.
    """
    if plan.protocol_spec is not None:
        return diag.serialize_spec(plan.protocol_spec)
    try:
        steps = build_protocol_schedule(plan.topology_name, n_agents)
    except Exception:
        return None
    if not steps:
        return None
    last_receivers = {dst for _, dst in steps[-1].transmissions}
    metadata: dict[str, Any] = {
        "source": "named_topology",
        "graph_type": "temporal_dag",
    }
    if len(last_receivers) == 1:
        metadata["selected_primary"] = last_receivers.pop()
    return ProtocolGraphSpec(
        name=plan.topology_name,
        n_agents=n_agents,
        steps=[
            ProtocolStepSpec(
                transmissions=step.transmissions,
                description=step.description,
                operator="replay",
            )
            for step in steps
        ],
        metadata=metadata,
    ).model_dump(mode="json")


def _run_one(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    objective: ObjectiveSpec,
    skill_bank: SkillBank,
    seed: int,
    llm_client: LLMClient,
    motif_stats: dict[str, dict] | None = None,
    diag_phase: str = "",
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
    # M1/M7: the case's task-feature bucket + agg kind, classified from the
    # statement text by the run's own LLM (benchmark-agnostic questions;
    # cached per text hash; heuristic fallback offline). Rows carry them so
    # the transfer ledger can attribute success per bucket/kind, and
    # deployment is gated on them below.
    classification = classify_task(
        instance.task_prompt,
        llm_client=llm_client,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        source=getattr(cfg, "task_feature_source", "llm"),
    )
    feature_bucket = classification_bucket(classification)
    feature_kind = classification_kind(classification)
    transfer_mode = (
        os.environ.get("MASBENCH_TRANSFER_GATE", "").strip()
        or getattr(cfg, "transfer_gate", "feature")
        or "feature"
    ).lower()
    abstained = False
    _planner_extra: dict[str, Any] = {}
    if cfg.planner_mode == "graph_generate":
        # Self-design evidence: GENERATE a DAG (cold, diverse via candidates) so the
        # minister + motif loop learn from real generated structures, not topology
        # picks. skill_bank is the fresh per-row bank; the motif prior is OFF here
        # (we are MEASURING which structures win, not yet biasing toward them).
        # M1 transfer gate: only skills with measured success in THIS case's
        # feature bucket may seed replay candidates; nothing trusted -> the
        # exact cold path (empty bank, no motif prior) -- do no harm on
        # representationally-uncovered cases.
        view_bank, view_motif, abstained = deployment_view(
            skill_bank, motif_stats, feature_bucket,
            kind=feature_kind, mode=transfer_mode,
        )
        plan, _planner_extra = _plan_graph_generate(
            cfg,
            n_agents=n_agents,
            task_adapter=task_adapter,
            client=llm_client,
            skill_bank=view_bank,
            motif_stats=view_motif,
        )
    else:
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
    row["task_features_key"] = feature_bucket
    row["task_agg_kind"] = feature_kind
    # A2: carry the executed schedule so minister skills can store it
    # (organization_policy.protocol_spec) and the refine eval can replay it.
    row["protocol_spec"] = _executed_spec(plan, n_agents)
    if cfg.planner_mode == "graph_generate" and plan.protocol_spec is not None:
        # Structural-motif evidence so the motif-credit loop can learn which
        # GENERATED structures (fan-in, depth, sink pattern) correlate with low
        # loss. Lower-is-better loss; offline this is topology-invariant.
        # M1: motif keys are bucket-namespaced so structural credit earned on
        # one task paradigm cannot bias generation on another.
        raw_motif_keys = spec_motif_keys(plan.protocol_spec)
        row["motif_keys"] = (
            namespace_motif_keys(raw_motif_keys, feature_bucket)
            if transfer_mode != "off"
            else raw_motif_keys
        )
        row["mean_primary_loss"] = 1.0 - float(row.get("ExactMatchRate", 0.0))
    if diag.enabled():
        record: dict[str, Any] = {
            "case_id": instance.case_id,
            "seed": seed,
            "phase": diag_phase,
            "planner_mode": cfg.planner_mode,
            "evolved_mode": cfg.evolved_mode,
            "n_agents": n_agents,
            "bank_size": len(skill_bank),
            "transfer_bucket": feature_bucket,
            "transfer_kind": feature_kind,
            "transfer_abstained": abstained,
            "topology": row.get("Topology"),
            "exact_match": row.get("ExactMatchRate"),
            "messages": row.get("MeanTotalMessages"),
            "model_calls": row.get("MeanTotalModelCalls"),
            "tokens": row.get("MeanTokenCost"),
            "motif_keys": row.get("motif_keys"),
            "spec": diag.serialize_spec(plan.protocol_spec),
            "fallback_reason": _planner_extra.get("graph_fallback_reason"),
        }
        if cfg.planner_mode == "graph_generate":
            record["retrieved_skills"] = [
                {
                    "skill_id": s.skill_id,
                    "topology": (s.organization_policy or {}).get("topology_name"),
                    "has_executable_spec": isinstance(
                        (s.organization_policy or {}).get("protocol_spec"), dict
                    ),
                }
                for s in skill_bank.retrieve(request)
            ]
        diag.dump_eval_run(record)
    return row


def _run_fixed_one(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    topology: str,
    seed: int,
    llm_client: LLMClient,
    diag_phase: str = "",
) -> dict[str, Any]:
    """Run one instance on a FIXED named topology (no planner).

    M3 portfolio evidence: the objective-variant detour only ever measures the
    planner-default topologies (peer-exponential/tree/mesh-star -- all
    aggregation organizations), so the minister could never learn a champion
    for sequential tasks. This measures explicitly-named portfolio topologies
    (e.g. ``chain``) on the same train grid so order-sensitive evidence exists
    when train contains level-II cases.
    """
    task_adapter = SiloProtocolAdapter(instance)
    global_task = task_adapter.build_global_task()
    n_agents = cfg.n_agents or instance.n_agents
    config = ProtocolRunnerConfig(
        topology_name=topology,
        n_agents=n_agents,
        seed=seed,
        merge_mode=cfg.merge_mode,
        init_mode=cfg.init_mode,
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
    )
    result = ProtocolRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        llm_client=llm_client,
    ).run()
    summary = result.to_summary_dict()
    row = summary_to_aggregate_row(summary)
    classification = classify_task(
        instance.task_prompt,
        llm_client=llm_client,
        model_name=cfg.model_name,
        llm_provider=cfg.llm_provider,
        source=getattr(cfg, "task_feature_source", "llm"),
    )
    row["case_id"] = instance.case_id
    row["seed"] = seed
    row["task_family"] = SILO_TASK_FAMILY
    row["task_features_key"] = classification_bucket(classification)
    row["task_agg_kind"] = classification_kind(classification)
    try:
        steps = build_protocol_schedule(topology, n_agents)
    except Exception:
        steps = []
    if steps:
        last_receivers = {dst for _, dst in steps[-1].transmissions}
        metadata: dict[str, Any] = {
            "source": "named_topology",
            "graph_type": "temporal_dag",
        }
        if len(last_receivers) == 1:
            metadata["selected_primary"] = last_receivers.pop()
        row["protocol_spec"] = ProtocolGraphSpec(
            name=topology,
            n_agents=n_agents,
            steps=[
                ProtocolStepSpec(
                    transmissions=step.transmissions,
                    description=step.description,
                    operator="replay",
                )
                for step in steps
            ],
            metadata=metadata,
        ).model_dump(mode="json")
    if diag.enabled():
        diag.dump_eval_run(
            {
                "case_id": instance.case_id,
                "seed": seed,
                "phase": diag_phase,
                "planner_mode": f"fixed:{topology}",
                "evolved_mode": cfg.evolved_mode,
                "n_agents": n_agents,
                "bank_size": 0,
                "transfer_bucket": row["task_features_key"],
                "topology": row.get("Topology"),
                "exact_match": row.get("ExactMatchRate"),
                "messages": row.get("MeanTotalMessages"),
                "model_calls": row.get("MeanTotalModelCalls"),
                "tokens": row.get("MeanTokenCost"),
                "spec": row.get("protocol_spec"),
            }
        )
    return row


def _portfolio_topologies(cfg: RunConfig) -> list[str]:
    raw = (
        os.environ.get("MASBENCH_EVIDENCE_PORTFOLIO")
        if os.environ.get("MASBENCH_EVIDENCE_PORTFOLIO") is not None
        else getattr(cfg, "evidence_portfolio", "chain")
    )
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _collect_portfolio_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    topologies: list[str],
    seeds: list[int],
    llm_client: LLMClient,
    workers: int = 1,
    progress: bool = False,
    phase: str = "",
) -> list[dict[str, Any]]:
    """Fixed-topology evidence rows (bank-independent -> cacheable)."""
    tasks = [
        (inst, topology, seed)
        for inst in instances
        for topology in topologies
        for seed in (seeds or [0])
    ]
    if not tasks:
        return []
    results: list[dict[str, Any] | None] = [None] * len(tasks)
    prog = _EvolveProgress(phase, len(tasks)) if progress else None
    cache = open_cache()

    def _do(index: int) -> tuple[int, dict[str, Any] | None]:
        inst, topology, seed = tasks[index]
        cache_key = (
            EvidenceCache.key(
                case_id=inst.case_id, n_agents=cfg.n_agents or inst.n_agents,
                planner_mode=f"fixed:{topology}", objective=cfg.objective,
                seed=seed, cfg=cfg,
            )
            if cache is not None
            else None
        )
        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return index, cached
        try:
            row = _run_fixed_one(
                inst, cfg, topology=topology, seed=seed, llm_client=llm_client,
                diag_phase=f"evidence:{phase}" if phase else "evidence",
            )
            if cache is not None and cache_key is not None:
                cache.put(cache_key, row)
            return index, row
        except Exception as exc:  # noqa: BLE001 - one bad run must not abort evolution
            print(
                f"  [evolve {phase}] portfolio {topology} run FAILED:"
                f" {type(exc).__name__}: {exc}",
                flush=True,
            )
            return index, None

    if workers and workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            futures = [executor.submit(_do, i) for i in range(len(tasks))]
            for future in as_completed(futures):
                index, row = future.result()
                results[index] = row
                if prog is not None:
                    prog.tick(ok=row is not None)
    else:
        for i in range(len(tasks)):
            index, row = _do(i)
            results[index] = row
            if prog is not None:
                prog.tick(ok=row is not None)
    return [row for row in results if row is not None]


def _generation_gate(
    val_instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    val_seeds: list[int],
    llm_client: LLMClient,
    evolved_bank: SkillBank,
    motif_stats: dict[str, dict] | None,
    epsilon: float,
    objective: ObjectiveSpec,
    incumbent_bank: SkillBank | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """C: accept the learned state only if it improves held-out GENERATION.

    ``j_before`` = mean held-out primary loss when GENERATING with the PRE state
    (empty bank, no motif prior); ``j_after`` = with the evolved bank + motif
    prior. Accept iff ``j_after <= j_before + epsilon`` (accept-if-improves). This
    is the objective the self-design loop optimizes -- unlike the topology-select
    gate, it can actually move because generation quality varies with the learned
    state. Offline Silo is topology-invariant so ``j_before == j_after`` (accept).
    """
    cache = open_cache()

    def _one_loss(
        task: tuple[BenchmarkInstance, int],
        bank: SkillBank,
        stats: dict[str, dict] | None,
        phase_label: str,
    ) -> float:
        inst, seed = task
        # j_before (empty bank, no prior, cold generation) is round-
        # invariant -> cacheable; j_after depends on the bank -> never.
        cache_key = (
            EvidenceCache.key(
                case_id=inst.case_id, n_agents=cfg.n_agents or inst.n_agents,
                planner_mode="gate:before", objective=objective.name,
                seed=seed, cfg=cfg,
            )
            if cache is not None and phase_label == "gate:before"
            else None
        )
        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return float(cached["loss"])
        try:
            row = _run_one(
                inst, cfg, objective=objective, skill_bank=bank, seed=seed,
                llm_client=llm_client, motif_stats=stats,
                diag_phase=phase_label,
            )
        except Exception as exc:  # noqa: BLE001 - one wedged call must not abort evolution
            # A run that cannot complete IS a deployment failure for its
            # arm: charge max loss and keep gating (per-run isolation,
            # mirroring _collect_rows).
            print(
                f"  [evolve {phase_label}] {inst.case_id} seed={seed} FAILED:"
                f" {type(exc).__name__}: {exc}",
                flush=True,
            )
            return 1.0
        loss = float(
            row.get("mean_primary_loss", 1.0 - float(row.get("ExactMatchRate", 0.0)))
        )
        if cache is not None and cache_key is not None:
            cache.put(cache_key, {"loss": loss})
        return loss

    # M5: a 3-sample binary gate is a coin flip (dev round 1 rejected a
    # genuinely-good bank on cold 3/3 vs deployed 2/3). Evaluate each arm on
    # ``gate_seed_factor`` derived seeds per val seed; the derivation is
    # deterministic and never touches eval seeds (val INSTANCES only).
    factor_raw = os.environ.get("MASBENCH_GATE_SEED_FACTOR", "").strip()
    factor = int(factor_raw) if factor_raw else int(getattr(cfg, "gate_seed_factor", 1) or 1)
    gate_seeds = [
        seed + 1009 * k for k in range(max(1, factor)) for seed in (val_seeds or [0])
    ]

    def _mean_loss(
        bank: SkillBank, stats: dict[str, dict] | None, phase_label: str
    ) -> float:
        tasks = [
            (inst, seed)
            for inst in val_instances
            for seed in gate_seeds
        ]
        if not tasks:
            return 1.0
        # The (instance, seed) gate runs are independent; replayed organizations
        # are message-heavy (many serial merge calls), so a serial gate loop was
        # the longest pole of a round. Mean is order-independent -> parallel
        # fan-out is measurement-identical.
        if workers and workers > 1 and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
                losses = list(
                    ex.map(lambda t: _one_loss(t, bank, stats, phase_label), tasks)
                )
        else:
            losses = [_one_loss(t, bank, stats, phase_label) for t in tasks]
        return sum(losses) / len(losses)

    # M2 ratchet: when this round inherited a bank, the bar is the INCUMBENT
    # state's held-out generation loss, not the empty-bank cold loss -- a
    # round update must beat what we would deploy by rejecting it. (Round 1
    # has no incumbent, so the bar stays the cold loss, as before.) The
    # incumbent is measured without the motif prior (the prior is merged
    # outside run_evolution); documented approximation.
    if incumbent_bank is not None and len(incumbent_bank) > 0:
        j_before = _mean_loss(incumbent_bank, None, "gate:incumbent")
        gate_mode_label = "generation_ratchet"
    else:
        j_before = _mean_loss(SkillBank(), None, "gate:before")
        gate_mode_label = "generation"
    j_after = _mean_loss(evolved_bank, motif_stats, "gate:after")
    # M5 noise floor: tolerate exactly ONE discordant miss across the gate
    # grid (binary outcomes make j quantized in steps of 1/n); two or more
    # extra misses still reject. epsilon keeps its caller-set floor.
    n_samples = max(1, len(val_instances) * len(gate_seeds))
    epsilon_eff = max(epsilon, 1.0 / n_samples)
    return {
        "accepted": bool(j_after <= j_before + epsilon_eff),
        "j_before": j_before,
        "j_after": j_after,
        "epsilon": epsilon_eff,
        "n_samples": n_samples,
        "mode": gate_mode_label,
    }


def _evidence_record_from_row(row: dict[str, Any]) -> EvidenceRecord:
    """Adapt an evolution aggregate row to an EvidenceRecord for the insight pack.

    Maps the row's metrics to the lower-case keys the insight minister reads
    (mean_rmse / mean_messages / mean_token_cost / exact_match_rate).
    """
    exact = float(row.get("ExactMatchRate", 0.0))
    return EvidenceRecord(
        evidence_id=(
            f"agg:{row.get('case_id')}:n{row.get('Agents')}"
            f":s{row.get('seed')}:{row.get('Topology')}"
        ),
        source_type="aggregate",
        task_family=str(row.get("task_family", SILO_TASK_FAMILY)),
        topology_name=str(row.get("Topology", "")),
        n_agents=int(row["Agents"]) if row.get("Agents") is not None else None,
        seed=int(row["seed"]) if row.get("seed") is not None else None,
        metrics={
            "mean_rmse": float(row.get("MeanFinalRMSE", row.get("MeanPrimaryMetric", 0.0))),
            "mean_messages": float(row.get("MeanTotalMessages", 0.0)),
            "mean_token_cost": float(row.get("MeanTokenCost", 0.0)),
            "exact_match_rate": exact,
            "mean_primary_loss": float(row.get("mean_primary_loss", 1.0 - exact)),
        },
        status="observed",
    )


def _held_out_rows_for_falsify(val_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Held-out rows for falsify_insights: topology_name + a lower-is-better loss."""
    rows: list[dict[str, Any]] = []
    for r in val_rows:
        exact = float(r.get("ExactMatchRate", 0.0))
        rows.append(
            {
                "topology_name": str(r.get("Topology", "")),
                "n_agents": r.get("Agents"),
                "mean_primary_loss": float(r.get("mean_primary_loss", 1.0 - exact)),
                "mean_rmse": float(r.get("MeanFinalRMSE", r.get("MeanPrimaryMetric", 0.0))),
            }
        )
    return rows


def _llm_insight_patches(
    train_rows: list[dict[str, Any]],
    val_rows: list[dict[str, Any]],
    skill_bank: SkillBank,
    cfg: RunConfig,
    client: LLMClient,
    batch_id: str,
) -> int:
    """B2: LLM design-insight minister -> falsify vs held-out -> fold VERIFIED
    insights into the bank (so they drive generation). Returns #patches applied.

    Offline (fake) the minister uses its deterministic fallback. Verified-only
    (``require_verified=True``) so a plausible-but-wrong insight can't enter.
    """
    records = [_evidence_record_from_row(r) for r in train_rows]
    pack = build_evidence_pack(
        records=records, skill_bank=skill_bank, experiment_id=batch_id
    )
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider,
        model_name=cfg.model_name,
        temperature=cfg.temperature,
    )
    report = LLMInsightMinister(runtime=runtime, llm_client=client).analyze(
        evidence_pack=pack, skill_bank=skill_bank
    )
    report = falsify_insights(report, _held_out_rows_for_falsify(val_rows))
    patches = insight_report_to_patches(report, require_verified=True)
    if patches:
        skill_bank.apply_patches(patches)
    return len(patches)


# An avoid/counterexample rule must be earned by a real aggregate gap: the
# topology's MEAN primary loss must exceed the best topology's mean by this
# absolute margin. The engine's ratio rule (loss > best * 1.75) was designed for
# continuous CF RMSE; on per-(case,seed) BINARY Silo rows best is usually 0.0,
# so every topology with any miss got an avoid skill (round 1: avoid_{tree,
# mesh_star,peer_star} ALL advertised at once -> contradictory context, held-out
# generation dropped 54.2% -> 37.5%). With ~6 binary rows per topology the
# per-mean SE is ~0.19, so 0.25 demands a >1-SE real gap.
AVOID_MEAN_LOSS_GAP = 0.25

# The dominance CHAMPION (best mean loss) must itself be measured on at least
# this many rows to anchor avoid decisions. P2 round-1 bug: one lucky explored
# run (n=1, loss 0.0) became the anchor and every named topology -- including
# the deployed winner -- earned an avoid skill, polluting the generation prompt.
AVOID_CHAMPION_MIN_ROWS = 3


def _row_loss(row: dict[str, Any]) -> float:
    return float(row.get("mean_primary_loss", 1.0 - float(row.get("ExactMatchRate", 0.0))))


def _is_avoid_patch(patch: SkillPatch) -> bool:
    if str(patch.patch_id).startswith("counterexample"):
        return True
    skill = patch.candidate_skill
    return bool(skill and "cf_avoid_" in str(skill.skill_id))


def _filter_misfired_avoids(
    patches: list[SkillPatch],
    train_rows: list[dict[str, Any]],
) -> list[SkillPatch]:
    """Drop avoid patches whose topology is not genuinely dominated on means."""
    by_topology: dict[str, list[float]] = {}
    for row in train_rows:
        by_topology.setdefault(str(row.get("Topology", "")), []).append(_row_loss(row))
    means = {t: sum(v) / len(v) for t, v in by_topology.items() if v}
    if not means:
        return patches
    anchored = {
        t: m for t, m in means.items()
        if len(by_topology[t]) >= AVOID_CHAMPION_MIN_ROWS
    }
    if not anchored:
        # No well-measured champion -> no avoid decision can be earned.
        return [patch for patch in patches if not _is_avoid_patch(patch)]
    best = min(anchored.values())

    def keep(patch: SkillPatch) -> bool:
        if not _is_avoid_patch(patch):
            return True
        topology = str(
            (patch.candidate_skill.organization_policy or {}).get("topology_name", "")
            if patch.candidate_skill
            else ""
        )
        mean = means.get(topology)
        return mean is not None and (mean - best) >= AVOID_MEAN_LOSS_GAP

    return [patch for patch in patches if keep(patch)]


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


class _EvolveProgress:
    """Thread-safe, throttled progress printer for evolution row collection.

    The evolution pre-phase is hundreds of serial protocol runs with otherwise
    ZERO output -- which is exactly why a long run looks frozen. This emits ~20
    progress lines per phase so the user can see it working.
    """

    def __init__(self, phase: str, total: int) -> None:
        self._phase = phase
        self._total = total
        self._done = 0
        self._failed = 0
        self._start = time.monotonic()
        self._lock = threading.Lock()
        self._step = max(1, total // 20)

    def tick(self, ok: bool = True) -> None:
        with self._lock:
            self._done += 1
            if not ok:
                self._failed += 1
            if self._done == self._total or self._done % self._step == 0:
                elapsed = time.monotonic() - self._start
                print(
                    f"  [evolve {self._phase}] {self._done}/{self._total} runs"
                    f" ({self._failed} failed) {elapsed:5.1f}s",
                    flush=True,
                )


def _collect_rows(
    instances: list[BenchmarkInstance],
    cfg: RunConfig,
    *,
    objective_variants: list[ObjectiveSpec],
    seeds: list[int],
    llm_client: LLMClient,
    workers: int = 1,
    progress: bool = False,
    phase: str = "",
) -> list[dict[str, Any]]:
    """Collect real planner-run rows across objective variants.

    Each run uses a *fresh* empty ``SkillBank`` so the planner genuinely selects
    that objective's default topology (accuracy_first -> peer_star, budget_first
    -> tree, balanced -> mesh_star). Running every instance under several
    objectives yields multi-topology evidence, which is what lets the held-out
    validation gate make a non-degenerate accept/reject decision.

    The (instance, objective, seed) runs are independent (fresh ``SkillBank``
    each), so with ``workers > 1`` they fan out across a thread pool -- turning
    the otherwise-serial evolution pre-phase (hundreds of runs) from hours into
    minutes. Results preserve submission order so the aggregate is byte-identical
    to the serial path. A single run that fails (e.g. a hard ``LLMTimeoutError``
    from a wedged provider call) is dropped with a logged warning rather than
    aborting the whole evolution.
    """
    tasks = [
        (inst, objective, seed)
        for inst in instances
        for objective in objective_variants
        for seed in (seeds or [0])
    ]
    total = len(tasks)
    if total == 0:
        return []
    results: list[dict[str, Any] | None] = [None] * total
    prog = _EvolveProgress(phase, total) if progress else None

    cache = open_cache()

    def _do(index: int) -> tuple[int, dict[str, Any] | None]:
        inst, objective, seed = tasks[index]
        # Named evidence rows use a FRESH EMPTY bank by construction (bank-
        # independent); at temp 0 a cached row is the same measurement.
        cache_key = (
            EvidenceCache.key(
                case_id=inst.case_id, n_agents=cfg.n_agents or inst.n_agents,
                planner_mode=cfg.planner_mode, objective=objective.name,
                seed=seed, cfg=cfg,
            )
            if cache is not None
            else None
        )
        if cache is not None and cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return index, cached
        try:
            row = _run_one(
                inst,
                cfg,
                objective=objective,
                skill_bank=SkillBank(),
                seed=seed,
                llm_client=llm_client,
                diag_phase=f"evidence:{phase}" if phase else "evidence",
            )
            if cache is not None and cache_key is not None:
                cache.put(cache_key, row)
            return index, row
        except Exception as exc:  # noqa: BLE001 - one bad run must not abort evolution
            print(
                f"  [evolve {phase}] run {index + 1}/{total} FAILED:"
                f" {type(exc).__name__}: {exc}",
                flush=True,
            )
            return index, None

    if workers and workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=min(workers, total)) as executor:
            futures = [executor.submit(_do, i) for i in range(total)]
            for future in as_completed(futures):
                index, row = future.result()
                results[index] = row
                if prog is not None:
                    prog.tick(ok=row is not None)
    else:
        for i in range(total):
            index, row = _do(i)
            results[index] = row
            if prog is not None:
                prog.tick(ok=row is not None)

    return [row for row in results if row is not None]


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
    initial_skills: list[dict[str, Any]] | None = None,
    objective_variants: list[str] | None = None,
    epsilon: float = 0.0,
    batch_id: str = "silo_evolve_batch",
    llm_client: LLMClient | None = None,
    workers: int = 1,
    progress: bool = False,
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
    # ``initial_skills`` seeds the bank from a prior round (the rounds-curve loop
    # accumulates the evolved bank across iterations).
    skill_bank = (
        SkillBank(skills=[SkillCard.model_validate(s) for s in initial_skills])
        if initial_skills
        else SkillBank()
    )
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
        workers=workers,
        progress=progress,
        phase=f"n={cfg.n_agents} train",
    )
    # M3 portfolio: explicitly-named topologies the objective-variant detour
    # never measures (chain by default), so sequential-paradigm champions can
    # be learned when train contains order-sensitive cases.
    portfolio = _portfolio_topologies(cfg)
    n_portfolio_rows = 0
    if portfolio:
        portfolio_rows = _collect_portfolio_rows(
            train_instances,
            cfg,
            topologies=portfolio,
            seeds=train_seeds,
            llm_client=client,
            workers=workers,
            progress=progress,
            phase=f"n={cfg.n_agents} portfolio",
        )
        n_portfolio_rows = len(portfolio_rows)
        train_rows = [*train_rows, *portfolio_rows]
    # Phase-2 anti-saturation EXPLORATION: in refine mode, also generate
    # designs WITH the current bank (the deployed path) so self-generated
    # organizations enter the minister with executable specs and can join the
    # bank when they win. This is what lets round r+1 know more than round r --
    # without it, the named-topology evidence re-derives the same skills every
    # round and the rounds-curve saturates (phase-1 finding).
    explore_raw = os.environ.get("MASBENCH_EVOLVE_EXPLORE", "").strip()
    explore_n = int(explore_raw) if explore_raw else int(cfg.evolve_explore)
    n_explore_rows = 0
    if cfg.evolved_mode == "select_then_refine" and explore_n > 0:
        explore_cfg = replace(
            cfg, planner_mode="graph_generate", graph_gen_temperature=0.7
        )
        # Exploration must produce NEW designs: with executable specs in the
        # bank, seeded replay candidates fill every generation slot and
        # exploration degenerates into re-measuring known organizations. Strip
        # the specs from a COPY -- prose context (lessons/tradeoffs) still
        # informs the generation, deployment keeps the full bank. Bad explored
        # designs are filtered by evidence + the held-out gate.
        explore_bank = SkillBank(
            skills=[skill.model_copy(deep=True) for skill in skill_bank]
        )
        for skill in explore_bank:
            if isinstance((skill.organization_policy or {}).get("protocol_spec"), dict):
                skill.organization_policy["protocol_spec"] = None
        explore_tasks = [
            (inst, seed)
            for inst in train_instances
            for seed in (train_seeds or [0])[:explore_n]
        ]

        def _explore(task: tuple[BenchmarkInstance, int]) -> dict[str, Any] | None:
            inst, seed = task
            try:
                return _run_one(
                    inst, explore_cfg, objective=objective, skill_bank=explore_bank,
                    seed=seed, llm_client=client, diag_phase="explore",
                )
            except Exception as exc:  # noqa: BLE001 - one bad explore run is dropped
                print(
                    f"  [evolve explore] {inst.case_id} seed={seed} FAILED:"
                    f" {type(exc).__name__}: {exc}",
                    flush=True,
                )
                return None

        if workers and workers > 1 and len(explore_tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(explore_tasks))) as ex:
                explore_rows = [r for r in ex.map(_explore, explore_tasks) if r is not None]
        else:
            explore_rows = [r for t in explore_tasks if (r := _explore(t)) is not None]
        n_explore_rows = len(explore_rows)
        train_rows = [*train_rows, *explore_rows]
    # Single-gate architecture: modes that deploy GENERATION are vetted by the
    # generation gate (its own runs below); the selection gate -- the only
    # consumer of val evidence rows besides optional insight falsification --
    # is inactive there, so collecting val evidence would be pure spend.
    deploys_generation_mode = (
        cfg.planner_mode == "graph_generate"
        or cfg.evolved_mode == "select_then_refine"
    )
    needs_val_rows = (not deploys_generation_mode) or cfg.use_llm_insights
    val_rows_real = (
        _collect_rows(
            val_instances,
            cfg,
            objective_variants=variant_specs,
            seeds=val_seeds,
            llm_client=client,
            workers=workers,
            progress=progress,
            phase=f"n={cfg.n_agents} val",
        )
        if needs_val_rows
        else []
    )
    if needs_val_rows and portfolio:
        # The selection gate scores the planner's pick on val rows; a portfolio
        # topology the minister advertises must be MEASURED there too, or the
        # unmeasured-topology penalty auto-rejects every batch containing it.
        val_rows_real = [
            *val_rows_real,
            *_collect_portfolio_rows(
                val_instances,
                cfg,
                topologies=portfolio,
                seeds=val_seeds,
                llm_client=client,
                workers=workers,
                progress=progress,
                phase=f"n={cfg.n_agents} val portfolio",
            ),
        ]

    # Held-out validation rows the gate scores against: real Silo VAL rows plus
    # any caller-supplied synthetic multi-topology rows (see module docstring).
    val_rows = [*val_rows_real, *(held_out_rows or [])]

    # The minister stamps every emitted skill (card, trigger, and namespaced id)
    # with the silo family natively, so retrieval, the held-out gate, and the
    # selection probe all operate in one family with no post-hoc re-tagging.
    patches = ResultAnalystMinister().analyze(
        train_rows, task_family=SILO_TASK_FAMILY
    )
    # Round-1 root cause: the engine's ratio dominance rule misfires on binary
    # per-case rows (best=0 -> everything "dominated") and advertises avoid
    # skills for EVERY topology. Require a real mean-loss gap instead.
    patches = _filter_misfired_avoids(patches, train_rows)

    # Held-out gate mode: "auto" gates on the DEPLOYED objective (generation loss
    # when the evolved state will GENERATE at eval, selection J otherwise);
    # "off" disables held-out gating entirely (the drift-ablation arm). The env
    # var lets frozen drivers (scripts/verify_evolve.py) run the ablation.
    gate_mode = (
        os.environ.get("MASBENCH_GATE_MODE", "").strip() or cfg.gate_mode or "auto"
    ).lower()
    pre_skills = [skill.model_dump(mode="json") for skill in skill_bank]
    # M1: the inherited per-bucket ledgers, snapshotted BEFORE patches (merge
    # patches overwrite organization_policy keys; accumulation happens at
    # inject time). M2: the incumbent the ratchet gate must beat is the bank
    # INHERITED from the previous round (initial_skills) -- not the synthetic
    # seeded incumbent, which exists only for selection-gate measurement.
    pre_transfer_ledgers = snapshot_transfer_evidence(skill_bank)
    incumbent_bank = (
        SkillBank(skills=[SkillCard.model_validate(s) for s in initial_skills])
        if initial_skills
        else None
    )

    # ONE gate per deployed objective: modes that GENERATE at eval are vetted by
    # the held-out GENERATION gate below; gating their patch application on
    # topology-SELECTION J as well both double-gates and mis-scores -- the
    # selection objective charges generated:* skills an unmeasured-topology
    # penalty on named-evidence val rows, rejecting legitimate exploration
    # (phase-2 explore rows made this bind). Selection-deploying mode keeps the
    # selection gate.
    deploys_generation = (
        cfg.planner_mode == "graph_generate"
        or cfg.evolved_mode == "select_then_refine"
    )
    selection_gate_active = gate_mode != "off" and not deploys_generation
    size_before = len(skill_bank)
    _bank, result = consolidate_skill_updates(
        bank=skill_bank,
        patches=patches,
        evidence_records=[],
        batch_id=batch_id,
        validation_rows=val_rows,
        epsilon=epsilon,
        gate=selection_gate_active,
    )
    # B2: fold VERIFIED LLM design insights into the bank so they drive generation.
    n_insight_patches = 0
    if cfg.use_llm_insights:
        n_insight_patches = _llm_insight_patches(
            train_rows, val_rows, skill_bank, cfg, client, batch_id
        )
    # M1: per-(skill, feature-bucket) success ledger -- combines this round's
    # measured rows with the inherited ledger so deployment trust accumulates
    # across rounds instead of resetting.
    inject_transfer_evidence(skill_bank, train_rows, prior=pre_transfer_ledgers)
    size_after = len(skill_bank)

    # Post-evolution selection probe: run the knob-on planner against the (now
    # populated) evolved bank. Unlike evidence collection (which uses fresh empty
    # banks and therefore falls back to objective defaults), this genuinely
    # executes the E (LCB + min-seeds) and F (veto + floor + risk) selection logic
    # on real skills, so the improvement knobs are exercised, not merely set.
    final_selection = _selection_probe(skill_bank, cfg.n_agents or 2, objective)

    accepted = bool(result.gate_accepted) if selection_gate_active else True
    # B1: in self-design mode, aggregate the GENERATED evidence into a structural-
    # motif credit map (which fan-in/depth/sink patterns correlate with low loss).
    # Carried in the summary so the eval can bias generation toward winning motifs.
    motif_stats = (
        aggregate_motif_losses(train_rows)
        if any("motif_keys" in row for row in train_rows)
        else {}
    )
    # C: when the evolved state will GENERATE at eval (graph_generate evidence, or
    # select_then_refine whose deployed eval is refine-generation), gate on
    # held-out GENERATION quality (generating with vs without the learned state)
    # rather than topology selection -- selection J is vacuously tied on small
    # held-out sets while generation is the objective that actually deploys.
    selection_gate: dict[str, Any] = {
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
    }
    if gate_mode == "off":
        gate_info: dict[str, Any] = (
            {"accepted": True, "j_before": None, "j_after": None,
             "epsilon": epsilon, "mode": "off"}
            if deploys_generation
            else {**selection_gate, "accepted": True, "mode": "off"}
        )
    elif deploys_generation:
        gate_info = _generation_gate(
            val_instances, replace(cfg, planner_mode="graph_generate"),
            val_seeds=val_seeds, llm_client=client,
            evolved_bank=skill_bank, motif_stats=motif_stats, epsilon=epsilon,
            objective=objective, incumbent_bank=incumbent_bank, workers=workers,
        )
    else:
        gate_info = selection_gate

    # Every consumer of the summary (the frozen verify_evolve.py, curve, bench)
    # rebuilds its eval bank from ``evolved_skills`` unconditionally, so a
    # REJECTED state must be withheld HERE: export the pre-evolution state and
    # keep the rejected ids for diagnostics.
    gate_accepted = bool(gate_info.get("accepted"))
    exported_skills = [skill.model_dump(mode="json") for skill in skill_bank]
    exported_motif = motif_stats
    rejected_skill_ids: list[str] = []
    if not gate_accepted:
        rejected_skill_ids = sorted(skill.skill_id for skill in skill_bank)
        exported_skills = pre_skills
        exported_motif = {}
    summary = {
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
        "n_insight_patches": n_insight_patches,
        "n_explore_rows": n_explore_rows,
        "n_portfolio_rows": n_portfolio_rows,
        "gate": gate_info,
        "gate_mode": gate_mode,
        "selection_gate": selection_gate,
        "skill_bank_size_before": size_before,
        "skill_bank_size_after": size_after,
        "skill_bank_mutated": gate_accepted,
        "skill_ids_after": sorted(skill.skill_id for skill in skill_bank),
        "rejected_skill_ids": rejected_skill_ids,
        # Serialized evolved skills so the eval can rebuild the bank across the
        # cache/parallel boundary and feed it to graph generation (evolved_mode=
        # graph_generate -> the emperor designs a DAG from these skills). On a
        # rejected gate this is the PRE state -- rejected updates never deploy.
        "evolved_skills": exported_skills,
        "evolved_motif_stats": exported_motif,
        "final_selection": final_selection,
    }
    diag.dump_evolution_summary(summary)
    return summary


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

# The topologies the ResultAnalyst minister advertises from runs across the
# default objective variants (accuracy_first/budget_first/balanced) plus the
# M3 evidence portfolio (chain). Synthetic held-out rows must cover ALL of
# them so the gate's planner choice is decided by the incumbent-vs-train
# contrast, not by an unmeasured-topology penalty on a portfolio skill.
_TRAIN_TOPOLOGIES = ("one_peer_exponential_dag_star", "tree", "mesh_star", "chain")


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
