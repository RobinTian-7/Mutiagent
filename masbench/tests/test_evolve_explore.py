"""Per-round organization EXPLORATION (phase-2 fix for rounds saturation).

Phase 1 showed the rounds-curve saturates after round 1: evidence always comes
from the same named-topology runs, so the minister re-emits the same 3 skills
(`skipped_already_applied`) and nothing new can ever enter the bank.

Fix: in select_then_refine mode each round ALSO runs `evolve_explore` (default
1) graph_generate evidence run per train instance USING THE CURRENT BANK -- the
deployed refine path. Generated designs come back as rows carrying their
executable spec + outcome, the minister distills them into `generated:*`
skills, the avoid filter / gate vet them, and the next round's replay/refine
competes named vs generated organizations. Round-over-round growth is a
real-LLM property (generation diversity); offline we pin the mechanism:
explore rows reach the minister, motifs aggregate, and the env kill-switch
(MASBENCH_EVOLVE_EXPLORE=0) restores the old behaviour exactly.
"""
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution

DATA = Path(__file__).parent / "data"


def _cfg() -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="topology_select", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2,
    )


def _evolve(**kw):
    return run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"], **kw,
    )


def test_refine_evolution_explores_generated_designs():
    summary = _evolve()
    assert summary["n_explore_rows"] > 0, "explore rows must be collected"
    # The explored design reaches the minister as a generated:* card -- OR,
    # post-M11, it is absorbed into a structurally-identical family veteran
    # (offline fake generation often reproduces a named structure). Either
    # way the mechanism ran; the structure survives with an executable spec.
    generated = [
        s for s in summary["evolved_skills"]
        if str((s.get("organization_policy") or {}).get("topology_name", "")).startswith("generated:")
    ]
    absorbed = [
        aid
        for s in summary["evolved_skills"]
        for aid in ((s.get("organization_policy") or {}).get("absorbed_skill_ids") or [])
    ]
    assert generated or any("generated" in a for a in absorbed), (
        "explored design must persist as a card or be absorbed into a family"
    )
    holder = generated[0] if generated else next(
        s for s in summary["evolved_skills"]
        if any("generated" in a for a in ((s.get("organization_policy") or {}).get("absorbed_skill_ids") or []))
    )
    spec = (holder.get("organization_policy") or {}).get("protocol_spec")
    assert isinstance(spec, dict) and spec.get("steps"), "family carries an executable spec"
    named = [
        s for s in summary["evolved_skills"]
        if not str((s.get("organization_policy") or {}).get("topology_name", "")).startswith("generated:")
    ]
    assert named, "named-topology evidence skills still present"


def test_explore_aggregates_motif_stats_in_refine_mode():
    summary = _evolve()
    assert summary["evolved_motif_stats"], "explore rows must feed the motif credit map"


def test_explore_generates_fresh_designs_not_replays(monkeypatch):
    """Round r+1's exploration must produce NEW designs, not re-execute the
    bank's stored specs: with executable specs present, the seeded replay
    candidates fill every slot and exploration degenerates into re-measuring
    known organizations. Exploration therefore runs against a SPEC-STRIPPED
    copy of the bank: prose context (topology lessons, tradeoffs) informs the
    generation, but no executable spec can be replayed. Deployment keeps the
    full bank (phase-1 lesson: prose hurts DEPLOYMENT; exploration's bad
    designs are filtered by evidence + the gate instead)."""
    import masbench.evolve as evolve

    first = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"],
    )
    assert any(
        isinstance((s.get("organization_policy") or {}).get("protocol_spec"), dict)
        for s in first["evolved_skills"]
    ), "precondition: round-1 bank carries executable specs"

    explore_banks = []
    orig = evolve._run_one

    def spy(inst, cfg, **kwargs):
        if kwargs.get("diag_phase") == "explore":
            explore_banks.append(kwargs["skill_bank"])
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", spy)
    _evolve(initial_skills=first["evolved_skills"])
    assert explore_banks, "round 2 explored"
    bank = explore_banks[0]
    assert len(bank) > 0, "explore is INFORMED by the accumulated skills"
    assert not any(
        isinstance((s.organization_policy or {}).get("protocol_spec"), dict)
        for s in bank
    ), "explore bank must be spec-stripped (no replay short-circuit)"


def test_explore_generation_is_hot_deployment_cold(monkeypatch):
    """Diversity pressure: at temperature 0 with an identical prompt, every
    round's exploration regenerates the same designs and rounds saturate.
    Exploration runs its GENERATION call hot (cfg.graph_gen_temperature,
    default 0.7) while the protocol execution and all deployment-path
    generation stay at the configured temperature (0.0)."""
    import masbench.engine as engine
    import masbench.evolve as evolve

    seen: list[tuple[str, float]] = []
    orig = engine.plan_free_graph

    def spy(*, request, runtime, **kwargs):
        seen.append((kwargs.get("_phase", ""), runtime.temperature))
        return orig(request=request, runtime=runtime, **kwargs)

    monkeypatch.setattr(engine, "plan_free_graph", spy)

    explore_temps: list[float] = []
    orig_run_one = evolve._run_one

    def tag(inst, cfg, **kwargs):
        row = orig_run_one(inst, cfg, **kwargs)
        if kwargs.get("diag_phase") == "explore":
            explore_temps.append(cfg.graph_gen_temperature if cfg.graph_gen_temperature is not None else cfg.temperature)
        return row

    monkeypatch.setattr(evolve, "_run_one", tag)
    _evolve()
    hot = [t for _, t in seen if t == 0.7]
    cold = [t for _, t in seen if t == 0.0]
    assert hot, "explore generation must run hot (0.7)"
    assert cold, "gate/deploy generation must stay cold (0.0)"
    assert explore_temps and all(t == 0.7 for t in explore_temps)


def test_env_kill_switch_restores_old_behaviour(monkeypatch):
    monkeypatch.setenv("MASBENCH_EVOLVE_EXPLORE", "0")
    summary = _evolve()
    topologies = {
        str((s.get("organization_policy") or {}).get("topology_name", ""))
        for s in summary["evolved_skills"]
    }
    assert not any(t.startswith("generated:") for t in topologies)
    assert summary["evolved_motif_stats"] == {}
