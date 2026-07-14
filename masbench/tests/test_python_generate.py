"""Independent PythonGen engine, evolution, CLI, and bench integration tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

from exp_graph.mas.evolution import ResultAnalystMinister
from exp_graph.mas.graph_generation import GraphGenerationError
from exp_graph.mas.python_code import (
    DEFAULT_PYTHON_PROGRAM,
    PythonProgramOutput,
    PythonSubmission,
    PythonUsage,
)
from exp_graph.mas.python_code_generation import (
    PythonCodePlanningResult,
    PythonGenerationError,
)
from exp_graph.mas.python_code_runner import PythonExecutionResult
from exp_graph.mas.schemas import PythonSkillPayload, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import SkillBank, is_selectable_skill

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.bench import run_benchmark
from masbench.cli import main
from masbench.core.config import RunConfig
from masbench.engine import (
    _build_python_execution_payload,
    _graph_artifacts_dir,
    _program_artifacts_dir,
    _protocol_adapter,
    _python_artifacts_dir,
    _resolved_python_execution_timeout,
    _score_python_execution,
    run_instance,
)
from masbench.evolve import (
    _paired_skill_ablation,
    _run_one,
    evolution_objective_spec,
)
from masbench.llm.fake import BenchmarkFakeLLMClient


DATA = Path(__file__).parent / "data"


def _instance():
    return next(SiloBenchAdapter(DATA).iter_instances(cases=["I-01"]))


def test_run_one_binds_explicit_seed_to_generated_planner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seen: list[tuple[int, str]] = []

    def fail_after_observing_cfg(cfg, *, instance, **kwargs):
        del kwargs
        seen.append((cfg.seed, instance.case_id))
        raise GraphGenerationError("expected test failure")

    monkeypatch.setattr(
        "masbench.evolve._plan_graph_generate",
        fail_after_observing_cfg,
    )
    cfg = RunConfig(
        planner_mode="graph_generate",
        llm_provider="fake",
        model_name="fake",
        n_agents=2,
        seed=999,
        graph_artifacts_dir=str(tmp_path),
    )
    instance = _instance()
    objective = evolution_objective_spec(cfg)

    rows = [
        _run_one(
            instance,
            cfg,
            objective=objective,
            skill_bank=SkillBank(),
            seed=seed,
            llm_client=BenchmarkFakeLLMClient(),
        )
        for seed in (11, 12)
    ]

    assert seen == [(11, "I-01"), (12, "I-01")]
    assert [row["seed"] for row in rows] == [11, 12]
    assert cfg.seed == 999


def test_generated_artifact_directories_are_seeded_and_concurrency_safe(
    tmp_path: Path,
) -> None:
    instance = _instance()
    cfg = RunConfig(
        n_agents=2,
        silo_eval_mode="all_agents",
        graph_artifacts_dir=str(tmp_path / "graph"),
        program_artifacts_dir=str(tmp_path / "program"),
        python_artifacts_dir=str(tmp_path / "python"),
    )
    builders = (_graph_artifacts_dir, _program_artifacts_dir, _python_artifacts_dir)

    def create(seed: int) -> list[Path]:
        run_cfg = replace(cfg, seed=seed)
        paths = [builder(run_cfg, instance) for builder in builders]
        for path in paths:
            (path / f"seed_{seed}.marker").write_text(str(seed), encoding="utf-8")
        return paths

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, seed) for seed in (11, 12)]
        paths_by_seed = {
            seed: future.result()
            for seed, future in zip((11, 12), futures, strict=True)
        }

    all_paths = [path for paths in paths_by_seed.values() for path in paths]
    assert len(set(all_paths)) == 6
    for seed, paths in paths_by_seed.items():
        for path in paths:
            assert f"I-01_n2_seed{seed}_all_agents_" in path.name
            assert (path / f"seed_{seed}.marker").read_text(encoding="utf-8") == str(seed)
            assert not (path / f"seed_{12 if seed == 11 else 11}.marker").exists()


def test_python_generate_fake_engine_is_independent_and_auditable(
    tmp_path: Path,
) -> None:
    score = run_instance(
        _instance(),
        RunConfig(
            use_planner=True,
            planner_mode="python_generate",
            llm_provider="fake",
            model_name="fake",
            n_agents=2,
            max_rounds=2,
            silo_eval_mode="all_agents",
            python_artifacts_dir=str(tmp_path / "python"),
        ),
    )

    assert score.success is False
    assert score.extra["planner_mode"] == "python_generate"
    assert score.extra["program_validity"] == 1.0
    assert score.extra["provenance"] == "fake"
    assert score.extra["paper_S"] == 0.0
    assert len(score.extra["per_agent_submissions"]) == 2
    artifact_dir = Path(score.extra["python_artifacts_dir"])
    assert (artifact_dir / "final_program.py").exists()
    assert (artifact_dir / "execution_report.json").exists()
    assert not (artifact_dir / "architect_call.json").exists()
    assert not (artifact_dir / "program_architect_call.json").exists()


def test_python_timeout_auto_budget_accounts_for_round_waves() -> None:
    cfg = RunConfig(
        n_agents=5,
        max_rounds=4,
        request_timeout=120.0,
        max_parallel_agents=5,
        python_execution_timeout=None,
        python_worker_contract="message_only_v2",
    )
    assert _resolved_python_execution_timeout(cfg, n_agents=5) == 510.0

    slower = replace(cfg, max_parallel_agents=2)
    assert _resolved_python_execution_timeout(slower, n_agents=5) == 1470.0

    explicit = replace(cfg, python_execution_timeout=777.0)
    assert _resolved_python_execution_timeout(explicit, n_agents=5) == 777.0

    legacy_scalar = replace(cfg, python_worker_contract="action_json_v1")
    assert _resolved_python_execution_timeout(legacy_scalar, n_agents=5) == 2430.0


def test_python_payload_authorizes_intra_task_parallelism_and_request_timeout() -> None:
    instance = _instance()
    cfg = RunConfig(
        n_agents=2,
        max_rounds=3,
        request_timeout=120.0,
        max_parallel_agents=2,
        python_worker_contract="message_only_v2",
    )
    adapter = _protocol_adapter(instance, information_goal="all_agents")
    global_task = adapter.build_global_task()

    payload = _build_python_execution_payload(
        instance=instance,
        cfg=cfg,
        task_adapter=adapter,
        global_task=global_task,
        n_agents=2,
    )

    assert payload["max_parallel_agents"] == 2
    assert payload["worker_llm"]["request_timeout"] == 120.0


def test_all_agents_one_wrong_submission_fails_even_with_full_coverage(
    tmp_path: Path,
) -> None:
    instance = _instance()
    cfg = RunConfig(
        planner_mode="python_generate",
        n_agents=2,
        silo_eval_mode="all_agents",
    )
    adapter = _protocol_adapter(instance, information_goal="all_agents")
    global_task = adapter.build_global_task()
    output = PythonProgramOutput(
        submissions=[
            PythonSubmission(agent_id=0, answer=9, submitted_round=0),
            PythonSubmission(agent_id=1, answer=8, submitted_round=0),
        ],
        rounds_executed=1,
        messages=[],
        usage=PythonUsage(model_calls=0, prompt_tokens=0, completion_tokens=0),
        errors=[],
    )
    execution = PythonExecutionResult(
        runtime_success=True,
        output=output,
        authoritative_usage=output.usage,
        final_knowledge=[[0, 1], [0, 1]],
    )
    planning = PythonCodePlanningResult(
        source=DEFAULT_PYTHON_PROGRAM,
        execution=execution,
        artifacts_dir=tmp_path,
        provenance="llm_generated_python",
        architect_prompt=None,
        attempts=[],
        planner_model_calls=1,
        repair_model_calls=0,
    )

    score = _score_python_execution(
        planning,
        instance=instance,
        cfg=cfg,
        task_adapter=adapter,
        global_task=global_task,
        extra={"program_validity": 1.0},
    )
    assert score.success is False
    assert score.extra["paper_S"] == 0.5
    assert score.extra["all_agents_full_information"] is True
    assert score.extra["per_agent_correct"] == [True, False]


def test_python_evolution_row_uses_dense_v_k_u_p_s_signal(tmp_path: Path) -> None:
    cfg = RunConfig(
        planner_mode="python_generate",
        evolved_mode="python_generate",
        llm_provider="fake",
        model_name="fake",
        n_agents=2,
        max_rounds=2,
        silo_eval_mode="all_agents",
        task_feature_source="heuristic",
        python_artifacts_dir=str(tmp_path),
    )
    row = _run_one(
        _instance(),
        cfg,
        objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(),
        seed=4,
        llm_client=BenchmarkFakeLLMClient(),
        diag_phase="test",
    )

    assert row["planner_mode"] == "python_generate"
    assert row["program_validity"] == 1.0
    assert 0.0 <= row["structural_coverage"] <= 1.0
    assert 0.0 <= row["submission_rate"] <= 1.0
    assert 0.0 <= row["evolution_partial"] <= 1.0
    assert row["mean_primary_loss"] == 1.0 - row["evolution_stage_score"]
    assert row["paper_C"] >= 0.0 and row["paper_D"] >= 0.0
    assert row["python_source"] == DEFAULT_PYTHON_PROGRAM


def test_python_failure_is_validity_zero_negative_skill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    failure_dir = tmp_path / "failed"

    def fail(*args, **kwargs):
        raise PythonGenerationError(
            "forbidden import",
            error_type="PolicyError",
            artifacts_dir=failure_dir,
        )

    monkeypatch.setattr("masbench.evolve._plan_python_generate", fail)
    cfg = RunConfig(
        planner_mode="python_generate",
        evolved_mode="python_generate",
        llm_provider="fake",
        n_agents=2,
        task_feature_source="heuristic",
    )
    row = _run_one(
        _instance(),
        cfg,
        objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(),
        seed=7,
        llm_client=BenchmarkFakeLLMClient(),
        diag_phase="test",
    )

    assert row["program_validity"] == 0.0
    assert row["evolution_stage"] == "validity"
    assert row["python_generation_failed"] == "forbidden import"
    assert row["python_failure_category"] == "PolicyError"
    patches = ResultAnalystMinister().analyze([row], task_family="silo")
    candidates = [patch.candidate_skill for patch in patches if patch.candidate_skill]
    assert candidates
    assert all("counterexample" in skill.tags for skill in candidates)
    assert all(not is_selectable_skill(skill) for skill in candidates)


def test_success_card_stores_python_program_and_reasoning_policy(
    tmp_path: Path,
) -> None:
    cfg = RunConfig(
        planner_mode="python_generate",
        evolved_mode="python_generate",
        llm_provider="fake",
        model_name="fake",
        n_agents=2,
        max_rounds=2,
        silo_eval_mode="all_agents",
        task_feature_source="heuristic",
        python_artifacts_dir=str(tmp_path),
    )
    row = _run_one(
        _instance(),
        cfg,
        objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(),
        seed=8,
        llm_client=BenchmarkFakeLLMClient(),
        diag_phase="test",
    )
    # Model-generated provenance is the clean deployable variant. The fake run
    # supplies deterministic execution evidence without pretending to solve.
    row["provenance"] = "llm_generated_python"
    patch = ResultAnalystMinister().analyze([row], task_family="silo")[0]
    skill = patch.candidate_skill
    assert skill is not None
    assert skill.organization_policy["planner_mode"] == "python_generate"
    assert skill.organization_policy["source_code"] == DEFAULT_PYTHON_PROGRAM
    assert isinstance(skill.mode_payload, PythonSkillPayload)
    assert skill.mode_payload.source_code == DEFAULT_PYTHON_PROGRAM
    assert skill.organization_policy["program_sha256"] == row["program_sha256"]
    assert skill.organization_policy["ast_policy_version"] == "python_ast_v1"
    assert (
        skill.organization_policy["execution_contract_version"]
        == "python_mas_v1"
    )
    assert skill.reasoning_policy["state_retention"]
    assert skill.reasoning_policy["submit_guard"]


def test_python_paired_ablation_distinguishes_program_hashes() -> None:
    def skill(skill_id: str, digest: str) -> SkillCard:
        return SkillCard(
            skill_id=skill_id,
            task_family="silo",
            organization_policy={
                "planner_mode": "python_generate",
                "topology_name": "python:generated",
                "program_sha256": digest,
            },
            provenance="llm_generated_python",
            information_goal="all_agents",
        )

    patches = [
        SkillPatch(
            patch_id="a",
            action="add",
            candidate_skill=skill("a", "aaa"),
        ),
        SkillPatch(
            patch_id="b",
            action="add",
            candidate_skill=skill("b", "bbb"),
        ),
    ]
    rows = [
        {
            "case_id": "II-X",
            "seed": 1,
            "Agents": 3,
            "information_goal": "all_agents",
            "Topology": "python:generated",
            "planner_mode": "python_generate",
            "program_sha256": "aaa",
            "mean_primary_loss": 0.2,
        },
        {
            "case_id": "II-X",
            "seed": 1,
            "Agents": 3,
            "information_goal": "all_agents",
            "Topology": "python:generated",
            "planner_mode": "python_generate",
            "program_sha256": "bbb",
            "mean_primary_loss": 0.8,
        },
    ]

    kept, reports = _paired_skill_ablation(patches, rows, strict=True)
    assert [patch.patch_id for patch in kept] == ["a"]
    assert {item["skill_id"]: item["status"] for item in reports} == {
        "a": "accepted_improved",
        "b": "rejected",
    }


def test_cli_accepts_python_generate(tmp_path: Path) -> None:
    rc = main(
        [
            "run",
            "--benchmark",
            "silo_bench",
            "--benchmarks-dir",
            str(DATA),
            "--case",
            "I-01",
            "--n-agents",
            "2",
            "--planner",
            "--planner-mode",
            "python_generate",
            "--llm",
            "fake",
            "--model-name",
            "fake",
            "--max-rounds",
            "2",
            "--python-artifacts-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0


def test_three_generation_arms_run_as_distinct_bench_units(tmp_path: Path) -> None:
    graph_dir = tmp_path / "graph"
    program_dir = tmp_path / "program"
    python_dir = tmp_path / "python"
    cfg = RunConfig(
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        max_rounds=2,
        graph_artifacts_dir=str(graph_dir),
        program_artifacts_dir=str(program_dir),
        python_artifacts_dir=str(python_dir),
    )
    result = run_benchmark(
        SiloBenchAdapter(DATA),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[0],
        arms=["graphgen", "programgen", "pycodegen"],
        cfg_base=cfg,
        graphgen_candidates=1,
        out=tmp_path / "bench",
        progress=False,
    )

    assert {run["arm"] for run in result["runs"]} == {
        "graphgen",
        "programgen",
        "pycodegen",
    }
    expected_modes = {
        "graphgen": "graph_generate",
        "programgen": "program_generate",
        "pycodegen": "python_generate",
    }
    assert {
        run["arm"]: run["planner_mode"] for run in result["runs"]
    } == expected_modes
    assert all(run["provenance"] == "fake" for run in result["runs"])
    assert graph_dir.exists() and program_dir.exists() and python_dir.exists()
    py_run = next(run for run in result["runs"] if run["arm"] == "pycodegen")
    assert py_run["program_validity"] == 1.0
    assert Path(py_run["python_artifacts_dir"]).is_dir()
    persisted = json.loads((tmp_path / "bench" / "results.json").read_text())
    assert persisted["arms"] == ["graphgen", "programgen", "pycodegen"]
