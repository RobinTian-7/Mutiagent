"""Opt-in diagnostics dump (MASBENCH_EVOLVE_DUMP_DIR).

verify_evolve.py is the frozen judgment target, so mechanism evidence (what the
bank learned, which DAG each arm ran) is exported from the PIPELINE side: when
the env var is set, ``run_evolution`` dumps its full summary and every
``_run_one`` appends a per-run JSONL record. Env unset -> no files, behaviour
byte-identical (CF honesty).
"""
import json
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution
from masbench.llm.fake import BenchmarkFakeLLMClient
from exp_graph.mas.skill_bank import SkillBank

DATA = Path(__file__).parent / "data"


def _cfg(planner_mode: str = "topology_select") -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode=planner_mode, merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2,
    )


def _instance():
    return next(
        iter(SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"]))
    )


def test_run_evolution_dumps_summary_and_evidence_runs(monkeypatch, tmp_path):
    diag = tmp_path / "diag"
    monkeypatch.setenv("MASBENCH_EVOLVE_DUMP_DIR", str(diag))
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"],
    )
    evo_files = sorted(diag.glob("evolution_*.json"))
    assert len(evo_files) == 1
    payload = json.loads(evo_files[0].read_text())
    assert payload["evolved_skills"] == summary["evolved_skills"]
    assert payload["gate"] == summary["gate"]

    lines = [json.loads(l) for l in (diag / "eval_runs.jsonl").read_text().splitlines()]
    assert lines, "evidence runs must be dumped"
    required = {"case_id", "seed", "phase", "planner_mode", "bank_size",
                "topology", "exact_match", "messages", "model_calls", "tokens"}
    assert all(required <= set(line) for line in lines)
    phases = {line["phase"] for line in lines}
    assert any(p.startswith("evidence") for p in phases)
    # refine mode deploys generation -> its held-out gate runs are dumped too
    assert {"gate:before", "gate:after"} <= phases


def test_run_one_dumps_generated_spec_and_retrieval(monkeypatch, tmp_path):
    diag = tmp_path / "diag"
    monkeypatch.setenv("MASBENCH_EVOLVE_DUMP_DIR", str(diag))
    cfg = _cfg(planner_mode="graph_generate")
    row = _run_one(
        _instance(), cfg, objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(), seed=7, llm_client=BenchmarkFakeLLMClient(),
    )
    assert row["case_id"] == "I-01"
    lines = [json.loads(l) for l in (diag / "eval_runs.jsonl").read_text().splitlines()]
    assert len(lines) == 1
    rec = lines[0]
    assert rec["planner_mode"] == "graph_generate"
    assert rec["phase"] == ""  # external caller (e.g. verify_evolve paired eval)
    assert rec["seed"] == 7 and rec["bank_size"] == 0
    spec = rec["spec"]
    assert isinstance(spec, dict) and spec.get("steps"), "generated DAG spec must be dumped"
    assert "retrieved_skills" in rec and isinstance(rec["retrieved_skills"], list)


def test_no_dump_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = _cfg()
    _run_one(
        _instance(), cfg, objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(), seed=1, llm_client=BenchmarkFakeLLMClient(),
    )
    assert list(tmp_path.iterdir()) == [], "no diagnostics files when env unset"
