"""Outer workflow orchestration for MAS benchmark experiments.

This module intentionally wraps the existing MAS CLI phases. It does not
replace ProtocolRunner, matrix execution, graph generation, or skill evolution.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from exp_graph.mas.role_llm import load_role_llm_profiles


WORKFLOW_NODES = [
    "train_matrix",
    "collect_train",
    "analyze_insights",
    "review_before_evolve",
    "evolve_skills",
    "test_fixed",
    "test_v0",
    "test_v1",
    "collect_test_fixed",
    "collect_test_v0",
    "collect_test_v1",
    "benchmark_report",
]

LIST_FIELDS = {
    "objectives",
    "topologies",
    "n_agents",
    "array_sizes",
    "train_seeds",
    "test_seeds",
    "graph_validation_seeds",
}
INT_LIST_FIELDS = {
    "n_agents",
    "array_sizes",
    "train_seeds",
    "test_seeds",
    "graph_validation_seeds",
}


class WorkflowNodeResult(BaseModel):
    """Execution record for one outer workflow node."""

    model_config = ConfigDict(extra="ignore")

    node_name: str
    status: str = "pending"
    started_at: str = ""
    ended_at: str = ""
    command: list[str] = Field(default_factory=list)
    log_path: str = ""
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    error: str = ""


class MASWorkflowConfig(BaseModel):
    """Configuration for the paper-style MAS workflow."""

    model_config = ConfigDict(extra="ignore")

    workflow_id: str = Field(default_factory=lambda: f"mas_workflow_{uuid.uuid4().hex[:12]}")
    repo_dir: str = ""
    python_bin: str = sys.executable
    skill_dir: str = "configs/mas_skills"
    output_dir: str = ""
    train_dir: str = ""
    test_fixed_dir: str = ""
    test_v0_dir: str = ""
    test_v1_dir: str = ""
    benchmark_dir: str = ""
    evolved_skill_dir: str = ""
    evolved_skill_md_dir: str = ""

    objectives: list[str] = Field(
        default_factory=lambda: ["accuracy_first", "budget_first", "balanced"]
    )
    topologies: list[str] = Field(
        default_factory=lambda: [
            "tree",
            "one_peer_exponential_dag_star",
            "mesh_dag",
            "balanced_log_layer",
        ]
    )
    n_agents: list[int] = Field(default_factory=lambda: [4, 8])
    array_sizes: list[int] = Field(default_factory=lambda: [32, 64])
    value_min: int = 0
    value_max: int = 9
    train_seeds: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    test_seeds: list[int] = Field(default_factory=lambda: [9, 10, 11, 12, 13])

    llm_provider: str = "fake"
    model_name: str = "fake"
    role_llm_config: str | None = None
    merge_mode: str = "deterministic"
    init_mode: str = "deterministic"
    max_parallel_runs: int = 1
    max_parallel_agents: int = 1
    max_parallel_ministers: int = 1
    max_parallel_insight_shards: int = 1
    trace: bool = True
    retain_traces: bool = True
    verbose_events: bool = False
    confirm_real_llm: bool = False

    graph_search_mode: str = "single"
    num_graph_candidates: int = 1
    graph_top_k: int = 1
    graph_candidate_score_mode: str = "objective"
    graph_max_steps: int = 4
    graph_max_messages: int = 32
    graph_max_receiver_fan_in: int = 4
    graph_repair_attempts: int = 1
    graph_validation_seeds: list[int] = Field(default_factory=list)


class WorkflowRunOptions(BaseModel):
    """Runtime/debug options for workflow execution."""

    model_config = ConfigDict(extra="ignore")

    workflow_backend: str = "shell"
    dry_run: bool = False
    debug: bool = False
    resume: bool = False
    stop_after: str | None = None
    only_node: str | None = None
    resume_from: str | None = None
    pause_before_evolve: bool = False
    inspect_artifacts: bool = False
    save_node_logs: bool = True


class MASWorkflowState(BaseModel):
    """Persistent workflow state for phase-level resume/debugging."""

    model_config = ConfigDict(extra="ignore")

    workflow_id: str
    repo_dir: str
    python_bin: str
    skill_dir: str
    output_dir: str
    evolved_skill_dir: str
    train_dir: str
    test_fixed_dir: str
    test_v0_dir: str
    test_v1_dir: str
    benchmark_dir: str
    current_node: str = ""
    node_results: dict[str, WorkflowNodeResult] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    failed_node: str = ""
    review_decision: str = ""
    debug_options: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow node fails."""


class WorkflowPaused(RuntimeError):
    """Raised internally when workflow pauses for review."""


def load_workflow_config(
    config_path: Path | str | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> MASWorkflowConfig:
    """Load workflow config JSON and apply CLI-style overrides."""
    data: dict[str, Any] = {}
    path: Path | None = Path(config_path).expanduser() if config_path else None
    if path is not None:
        data.update(json.loads(path.read_text(encoding="utf-8")))
    if not data.get("repo_dir"):
        data["repo_dir"] = str(_infer_repo_dir(path)) if path else str(Path.cwd())
    if not data.get("output_dir"):
        data["output_dir"] = str(Path(data["repo_dir"]) / "workflow_output")
    for key, value in (overrides or {}).items():
        if value is not None:
            data[key] = value
    for key in LIST_FIELDS:
        if key in data and isinstance(data[key], str):
            data[key] = _parse_list(data[key], as_int=key in INT_LIST_FIELDS)
    return MASWorkflowConfig(**data)


def run_workflow(config: MASWorkflowConfig, options: WorkflowRunOptions) -> MASWorkflowState:
    """Run the workflow with either the shell or optional LangGraph backend."""
    _validate_options(options)
    _guard_real_llm(config, options)
    if options.workflow_backend == "langgraph":
        from exp_graph.mas.langgraph_workflow import run_langgraph_workflow

        return run_langgraph_workflow(config=config, options=options)
    return run_shell_workflow(config=config, options=options)


def run_shell_workflow(
    *,
    config: MASWorkflowConfig,
    options: WorkflowRunOptions,
) -> MASWorkflowState:
    """Run the outer workflow sequentially without LangGraph."""
    state = _load_or_create_state(config, options)
    nodes = _selected_nodes(state, options)
    _ensure_output_dirs(config)
    _append_event(config, {"event": "workflow_start", "backend": "shell", "nodes": nodes})
    if options.debug or options.dry_run:
        print(_format_plan(config, nodes), flush=True)
    for node_name in nodes:
        execute_workflow_node(config=config, options=options, state=state, node_name=node_name)
        result = state.node_results.get(node_name)
        if result and result.status == "paused":
            _append_event(config, {"event": "workflow_paused", "node": node_name})
            break
        if result and result.status == "failed":
            _append_event(config, {"event": "workflow_failed", "node": node_name})
            write_workflow_report(config, state)
            raise WorkflowExecutionError(result.error)
        if options.stop_after == node_name:
            _append_event(config, {"event": "workflow_stopped", "node": node_name})
            break
    write_workflow_report(config, state)
    _append_event(config, {"event": "workflow_done", "failed_node": state.failed_node})
    return state


def execute_workflow_node(
    *,
    config: MASWorkflowConfig,
    options: WorkflowRunOptions,
    state: MASWorkflowState,
    node_name: str,
) -> MASWorkflowState:
    """Execute one workflow node and update persistent state."""
    paths = workflow_paths(config)
    idx = WORKFLOW_NODES.index(node_name) + 1
    command = build_node_command(config, node_name)
    log_path = ""
    if options.save_node_logs:
        log_dir = paths["output_dir"] / "node_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = str(log_dir / f"{idx:02d}_{node_name}.log")
    result = WorkflowNodeResult(
        node_name=node_name,
        status="running",
        started_at=_now(),
        command=command or [],
        log_path=log_path,
        artifact_paths=_node_artifacts(config, node_name),
    )
    state.current_node = node_name
    state.failed_node = ""
    state.node_results[node_name] = result
    state.debug_options = options.model_dump(mode="json")
    _write_state(config, state)
    _append_event(config, {"event": "node_start", "node": node_name})
    if options.debug:
        print(f"[workflow-node-start] {node_name}", flush=True)
        if command:
            print(f"[workflow-command] {shlex.join(command)}", flush=True)

    try:
        if options.dry_run:
            result.status = "skipped"
            result.summary = "dry-run: command was not executed"
        elif node_name == "review_before_evolve":
            _execute_review_node(config, options, state, result)
        else:
            if node_name == "evolve_skills":
                result.summary = _prepare_evolved_skill_dir(config)
            if not command:
                result.status = "succeeded"
            else:
                return_code = _run_command(config, command, log_path=log_path)
                if return_code != 0:
                    raise WorkflowExecutionError(
                        f"node {node_name} failed with exit code {return_code}"
                    )
                result.status = "succeeded"
                if not result.summary:
                    result.summary = "command completed"
    except WorkflowPaused:
        result.status = "paused"
        result.summary = "paused before evolve-skills for manual review"
    except Exception as exc:  # pragma: no cover - exercised by failed manual runs.
        result.status = "failed"
        result.error = str(exc)
        state.failed_node = node_name
    result.ended_at = _now()
    state.node_results[node_name] = result
    _write_state(config, state)
    _append_event(
        config,
        {
            "event": "node_end",
            "node": node_name,
            "status": result.status,
            "error": result.error,
        },
    )
    if options.inspect_artifacts or options.debug:
        _print_artifacts(result)
    return state


def build_workflow_plan(config: MASWorkflowConfig) -> list[dict[str, Any]]:
    """Return the full workflow node/command plan."""
    return [
        {
            "node": node,
            "command": shlex.join(command) if (command := build_node_command(config, node)) else "",
            "artifacts": _node_artifacts(config, node),
        }
        for node in WORKFLOW_NODES
    ]


def build_node_command(config: MASWorkflowConfig, node_name: str) -> list[str] | None:
    """Build the subprocess command for one workflow node."""
    paths = workflow_paths(config)
    cli = [str(paths["python_bin"]), "-m", "exp_graph.mas.cli"]
    skill_dir = str(paths["skill_dir"])
    common_matrix = [
        "--objectives",
        _join(config.objectives),
        "--planner-modes",
        "operator_compose",
        "--topologies",
        _join(config.topologies),
        "--n-agents",
        _join(config.n_agents),
        "--array-sizes",
        _join(config.array_sizes),
        "--value-min",
        str(config.value_min),
        "--value-max",
        str(config.value_max),
        "--llm-provider",
        config.llm_provider,
        "--model-name",
        config.model_name,
        *_role_llm_args(config),
        "--merge-mode",
        config.merge_mode,
        "--init-mode",
        config.init_mode,
        *_trace_args(config),
        *_graph_args(config),
        "--max-parallel-runs",
        str(config.max_parallel_runs),
        "--max-parallel-agents",
        str(config.max_parallel_agents),
        "--max-parallel-ministers",
        str(config.max_parallel_ministers),
    ]
    if node_name == "train_matrix":
        return [
            *cli,
            "run-matrix",
            "--skill-dir",
            skill_dir,
            *common_matrix,
            "--planner-policies",
            "topology_sweep",
            "--seeds",
            _join(config.train_seeds),
            "--output-dir",
            str(paths["train_dir"]),
        ]
    if node_name == "collect_train":
        return _collect_command(cli, paths["train_dir"])
    if node_name == "analyze_insights":
        return [
            *cli,
            "analyze-insights",
            "--skill-dir",
            skill_dir,
            "--evidence-file",
            str(paths["train_dir"] / "collected" / "batch_evidence.jsonl"),
            "--summary-file",
            str(paths["train_dir"] / "collected" / "cross_seed_metrics.json"),
            "--trace-summary-file",
            str(paths["train_dir"] / "collected" / "cross_seed_trace_summary.json"),
            "--llm-provider",
            config.llm_provider,
            "--model-name",
            config.model_name,
            *_role_llm_args(config),
            "--max-parallel-insight-shards",
            str(config.max_parallel_insight_shards),
            "--output-dir",
            str(paths["train_dir"] / "insights"),
        ]
    if node_name == "review_before_evolve":
        return None
    if node_name == "evolve_skills":
        return [
            *cli,
            "evolve-skills",
            "--skill-dir",
            str(paths["evolved_skill_dir"]),
            "--evidence-file",
            str(paths["train_dir"] / "collected" / "batch_evidence.jsonl"),
            "--patch-dir",
            str(paths["train_dir"] / "collected" / "batch_patches"),
            "--backup",
            "--markdown-dir",
            str(paths["evolved_skill_md_dir"]),
        ]
    if node_name == "test_fixed":
        return [
            *cli,
            "eval-matrix",
            "--skill-dir",
            skill_dir,
            "--phase",
            "test",
            *common_matrix,
            "--planner-policies",
            "fixed_topology",
            "--seeds",
            _join(config.test_seeds),
            "--output-dir",
            str(paths["test_fixed_dir"]),
        ]
    if node_name == "test_v0":
        return [
            *cli,
            "eval-matrix",
            "--skill-dir",
            skill_dir,
            "--phase",
            "test",
            *common_matrix,
            "--planner-policies",
            "skill_grounded,llm_free",
            "--seeds",
            _join(config.test_seeds),
            "--output-dir",
            str(paths["test_v0_dir"]),
        ]
    if node_name == "test_v1":
        return [
            *cli,
            "eval-matrix",
            "--skill-dir",
            str(paths["evolved_skill_dir"]),
            "--phase",
            "test",
            *common_matrix,
            "--planner-policies",
            "skill_grounded",
            "--seeds",
            _join(config.test_seeds),
            "--output-dir",
            str(paths["test_v1_dir"]),
        ]
    if node_name == "collect_test_fixed":
        return _collect_command(cli, paths["test_fixed_dir"])
    if node_name == "collect_test_v0":
        return _collect_command(cli, paths["test_v0_dir"])
    if node_name == "collect_test_v1":
        return _collect_command(cli, paths["test_v1_dir"])
    if node_name == "benchmark_report":
        return [
            *cli,
            "benchmark-report",
            "--fixed-collected-dir",
            str(paths["test_fixed_dir"] / "collected"),
            "--v0-collected-dir",
            str(paths["test_v0_dir"] / "collected"),
            "--v1-collected-dir",
            str(paths["test_v1_dir"] / "collected"),
            "--output-dir",
            str(paths["benchmark_dir"]),
        ]
    raise ValueError(f"unknown workflow node: {node_name}")


def workflow_paths(config: MASWorkflowConfig) -> dict[str, Path]:
    """Resolve all important workflow paths."""
    repo = _resolve_path(config.repo_dir or ".", Path.cwd())
    output = _resolve_path(config.output_dir, repo)
    return {
        "repo_dir": repo,
        "python_bin": _resolve_path(config.python_bin, repo),
        "skill_dir": _resolve_path(config.skill_dir, repo),
        "output_dir": output,
        "train_dir": _child_path(config.train_dir, output, "train"),
        "test_fixed_dir": _child_path(config.test_fixed_dir, output, "test_fixed"),
        "test_v0_dir": _child_path(config.test_v0_dir, output, "test_v0"),
        "test_v1_dir": _child_path(config.test_v1_dir, output, "test_v1"),
        "benchmark_dir": _child_path(config.benchmark_dir, output, "benchmark_report"),
        "evolved_skill_dir": _child_path(config.evolved_skill_dir, output, "mas_skills_v1"),
        "evolved_skill_md_dir": _child_path(
            config.evolved_skill_md_dir,
            output,
            "mas_skills_v1_md",
        ),
    }


def write_workflow_report(config: MASWorkflowConfig, state: MASWorkflowState) -> Path:
    """Write a markdown report for the current workflow state."""
    paths = workflow_paths(config)
    report_path = paths["output_dir"] / "workflow_report.md"
    rows = []
    for node in WORKFLOW_NODES:
        result = state.node_results.get(node)
        status = result.status if result else "pending"
        log = result.log_path if result else ""
        summary = result.summary if result else ""
        rows.append(f"| `{node}` | {status} | `{log}` | {summary} |")
    artifacts = "\n".join(
        f"- `{key}`: `{value}`" for key, value in sorted(state.artifact_paths.items())
    )
    report_path.write_text(
        "\n".join(
            [
                "# MAS Workflow Report",
                "",
                f"- workflow_id: `{state.workflow_id}`",
                f"- current_node: `{state.current_node}`",
                f"- failed_node: `{state.failed_node}`",
                "",
                "## Nodes",
                "",
                "| Node | Status | Log | Summary |",
                "|---|---:|---|---|",
                *rows,
                "",
                "## Artifacts",
                "",
                artifacts,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report_path


def _execute_review_node(
    config: MASWorkflowConfig,
    options: WorkflowRunOptions,
    state: MASWorkflowState,
    result: WorkflowNodeResult,
) -> None:
    paths = workflow_paths(config)
    insight_report = paths["train_dir"] / "insights" / "insight_report.md"
    patch_dir = paths["train_dir"] / "collected" / "batch_patches"
    evolve_command = build_node_command(config, "evolve_skills") or []
    result.artifact_paths.update(
        {
            "insight_report": str(insight_report),
            "batch_patches": str(patch_dir),
            "evolve_command": shlex.join(evolve_command),
        }
    )
    if options.pause_before_evolve and not (
        options.resume and state.review_decision == "paused_before_evolve"
    ):
        state.review_decision = "paused_before_evolve"
        print("[workflow-paused] review before evolve-skills", flush=True)
        print(f"insight_report: {insight_report}", flush=True)
        print(f"batch_patches: {patch_dir}", flush=True)
        print(f"resume_command_hint: rerun with --resume", flush=True)
        raise WorkflowPaused()
    state.review_decision = (
        "approved_by_resume" if options.resume else "not_requested"
    )
    result.status = "succeeded"
    result.summary = state.review_decision


def _load_or_create_state(
    config: MASWorkflowConfig,
    options: WorkflowRunOptions,
) -> MASWorkflowState:
    paths = workflow_paths(config)
    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    state_path = paths["output_dir"] / "workflow_state.json"
    if options.resume and state_path.exists():
        return MASWorkflowState.model_validate(
            json.loads(state_path.read_text(encoding="utf-8"))
        )
    return MASWorkflowState(
        workflow_id=config.workflow_id,
        repo_dir=str(paths["repo_dir"]),
        python_bin=str(paths["python_bin"]),
        skill_dir=str(paths["skill_dir"]),
        output_dir=str(paths["output_dir"]),
        evolved_skill_dir=str(paths["evolved_skill_dir"]),
        train_dir=str(paths["train_dir"]),
        test_fixed_dir=str(paths["test_fixed_dir"]),
        test_v0_dir=str(paths["test_v0_dir"]),
        test_v1_dir=str(paths["test_v1_dir"]),
        benchmark_dir=str(paths["benchmark_dir"]),
        artifact_paths=_workflow_artifacts(config),
    )


def _selected_nodes(state: MASWorkflowState, options: WorkflowRunOptions) -> list[str]:
    if options.only_node:
        _require_node(options.only_node)
        return [options.only_node]
    if options.resume_from:
        _require_node(options.resume_from)
        return WORKFLOW_NODES[WORKFLOW_NODES.index(options.resume_from) :]
    if options.resume:
        if state.failed_node:
            return WORKFLOW_NODES[WORKFLOW_NODES.index(state.failed_node) :]
        for idx, node in enumerate(WORKFLOW_NODES):
            result = state.node_results.get(node)
            if result is None or result.status != "succeeded":
                return WORKFLOW_NODES[idx:]
        return []
    return list(WORKFLOW_NODES)


def _write_state(config: MASWorkflowConfig, state: MASWorkflowState) -> None:
    path = workflow_paths(config)["output_dir"] / "workflow_state.json"
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _append_event(config: MASWorkflowConfig, event: dict[str, Any]) -> None:
    paths = workflow_paths(config)
    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    payload = {"created_at": _now(), **event}
    with (paths["output_dir"] / "workflow_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _run_command(config: MASWorkflowConfig, command: list[str], *, log_path: str) -> int:
    paths = workflow_paths(config)
    env = os.environ.copy()
    src_path = str(paths["repo_dir"] / "src")
    env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    log_handle = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_handle = Path(log_path).open("w", encoding="utf-8")
        log_handle.write(f"$ {shlex.join(command)}\n\n")
    try:
        process = subprocess.Popen(
            command,
            cwd=paths["repo_dir"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            if log_handle:
                log_handle.write(line)
        return process.wait()
    finally:
        if log_handle:
            log_handle.close()


def _prepare_evolved_skill_dir(config: MASWorkflowConfig) -> str:
    paths = workflow_paths(config)
    src = paths["skill_dir"]
    dst = paths["evolved_skill_dir"]
    md = paths["evolved_skill_md_dir"]
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    notes: list[str] = []
    if dst.exists():
        backup = dst.with_name(f"{dst.name}_backup_{stamp}")
        shutil.move(str(dst), str(backup))
        notes.append(f"moved existing skill dir to {backup}")
    if md.exists():
        backup_md = md.with_name(f"{md.name}_backup_{stamp}")
        shutil.move(str(md), str(backup_md))
        notes.append(f"moved existing markdown dir to {backup_md}")
    shutil.copytree(src, dst)
    notes.append(f"copied {src} -> {dst}")
    return "; ".join(notes)


def _ensure_output_dirs(config: MASWorkflowConfig) -> None:
    paths = workflow_paths(config)
    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    if paths["output_dir"].exists():
        (paths["output_dir"] / "node_logs").mkdir(parents=True, exist_ok=True)


def _collect_command(cli: list[str], matrix_dir: Path) -> list[str]:
    return [
        *cli,
        "collect-matrix",
        "--matrix-dir",
        str(matrix_dir),
        "--output-dir",
        str(matrix_dir / "collected"),
    ]


def _trace_args(config: MASWorkflowConfig) -> list[str]:
    args: list[str] = []
    if config.trace:
        args.append("--trace")
    if config.retain_traces:
        args.append("--retain-traces")
    if config.verbose_events:
        args.append("--verbose-events")
    return args


def _role_llm_args(config: MASWorkflowConfig) -> list[str]:
    if not config.role_llm_config:
        return []
    return ["--role-llm-config", str(config.role_llm_config)]


def _graph_args(config: MASWorkflowConfig) -> list[str]:
    return [
        "--graph-search-mode",
        config.graph_search_mode,
        "--num-graph-candidates",
        str(config.num_graph_candidates),
        "--graph-top-k",
        str(config.graph_top_k),
        "--graph-candidate-score-mode",
        config.graph_candidate_score_mode,
        "--graph-max-steps",
        str(config.graph_max_steps),
        "--graph-max-messages",
        str(config.graph_max_messages),
        "--graph-max-receiver-fan-in",
        str(config.graph_max_receiver_fan_in),
        "--graph-repair-attempts",
        str(config.graph_repair_attempts),
        "--graph-validation-seeds",
        _join(config.graph_validation_seeds),
    ]


def _node_artifacts(config: MASWorkflowConfig, node_name: str) -> dict[str, str]:
    paths = workflow_paths(config)
    mapping = {
        "train_matrix": {"matrix_dir": str(paths["train_dir"])},
        "collect_train": {"collected_dir": str(paths["train_dir"] / "collected")},
        "analyze_insights": {"insight_dir": str(paths["train_dir"] / "insights")},
        "review_before_evolve": {
            "insight_report": str(paths["train_dir"] / "insights" / "insight_report.md"),
            "batch_patches": str(paths["train_dir"] / "collected" / "batch_patches"),
        },
        "evolve_skills": {"skill_dir": str(paths["evolved_skill_dir"])},
        "test_fixed": {"matrix_dir": str(paths["test_fixed_dir"])},
        "test_v0": {"matrix_dir": str(paths["test_v0_dir"])},
        "test_v1": {"matrix_dir": str(paths["test_v1_dir"])},
        "collect_test_fixed": {"collected_dir": str(paths["test_fixed_dir"] / "collected")},
        "collect_test_v0": {"collected_dir": str(paths["test_v0_dir"] / "collected")},
        "collect_test_v1": {"collected_dir": str(paths["test_v1_dir"] / "collected")},
        "benchmark_report": {"benchmark_dir": str(paths["benchmark_dir"])},
    }
    return mapping.get(node_name, {})


def _workflow_artifacts(config: MASWorkflowConfig) -> dict[str, str]:
    paths = workflow_paths(config)
    return {
        "workflow_state": str(paths["output_dir"] / "workflow_state.json"),
        "workflow_events": str(paths["output_dir"] / "workflow_events.jsonl"),
        "workflow_report": str(paths["output_dir"] / "workflow_report.md"),
        "train_dir": str(paths["train_dir"]),
        "train_collected": str(paths["train_dir"] / "collected"),
        "insight_report": str(paths["train_dir"] / "insights" / "insight_report.md"),
        "evolved_skill_dir": str(paths["evolved_skill_dir"]),
        "test_fixed_dir": str(paths["test_fixed_dir"]),
        "test_v0_dir": str(paths["test_v0_dir"]),
        "test_v1_dir": str(paths["test_v1_dir"]),
        "benchmark_report": str(paths["benchmark_dir"] / "benchmark_report.md"),
    }


def _guard_real_llm(config: MASWorkflowConfig, options: WorkflowRunOptions) -> None:
    if options.dry_run:
        return
    if not _workflow_uses_real_llm(config):
        return
    if config.confirm_real_llm or os.environ.get("CONFIRM_REAL_LLM") == "YES":
        return
    raise RuntimeError(
        "This workflow would launch real LLM jobs. Set CONFIRM_REAL_LLM=YES "
        "or pass --confirm-real-llm when you intend to run it."
    )


def _workflow_uses_real_llm(config: MASWorkflowConfig) -> bool:
    if config.llm_provider not in {"fake"}:
        return True
    if not config.role_llm_config:
        return False
    profiles = load_role_llm_profiles(config.role_llm_config)
    if profiles is None:
        return False
    return any(
        profile is not None and profile.platform != "fake"
        for profile in (profiles.emperor, profiles.soldier, profiles.minister)
    )


def _validate_options(options: WorkflowRunOptions) -> None:
    if options.workflow_backend not in {"shell", "langgraph"}:
        raise ValueError(f"unknown workflow backend: {options.workflow_backend}")
    for value in [options.stop_after, options.only_node, options.resume_from]:
        if value:
            _require_node(value)


def _require_node(node_name: str) -> None:
    if node_name not in WORKFLOW_NODES:
        raise ValueError(f"unknown workflow node {node_name!r}; choices: {', '.join(WORKFLOW_NODES)}")


def _format_plan(config: MASWorkflowConfig, nodes: list[str]) -> str:
    lines = ["[workflow-plan]"]
    for node in nodes:
        command = build_node_command(config, node)
        lines.append(f"- {node}: {shlex.join(command) if command else '<internal>'}")
    return "\n".join(lines)


def _print_artifacts(result: WorkflowNodeResult) -> None:
    if not result.artifact_paths:
        return
    print(f"[workflow-artifacts] {result.node_name}", flush=True)
    for key, value in sorted(result.artifact_paths.items()):
        marker = "exists" if Path(value).exists() else "pending"
        if key == "evolve_command":
            marker = "command"
        print(f"  {key}: {value} ({marker})", flush=True)


def _infer_repo_dir(config_path: Path | None) -> Path:
    if config_path is None:
        return Path.cwd()
    resolved = config_path.resolve()
    if resolved.parent.name == "mas_workflows" and resolved.parent.parent.name == "configs":
        return resolved.parent.parent.parent
    return Path.cwd()


def _resolve_path(value: str | Path, base: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _child_path(value: str, output_dir: Path, default_name: str) -> Path:
    if value:
        return _resolve_path(value, output_dir)
    return (output_dir / default_name).resolve()


def _parse_list(value: str, *, as_int: bool) -> list[Any]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return [int(item) for item in parts] if as_int else parts


def _join(values: list[Any]) -> str:
    return ",".join(str(value) for value in values)


def _now() -> str:
    return datetime.now(UTC).isoformat()
