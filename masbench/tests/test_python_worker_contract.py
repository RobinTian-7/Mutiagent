"""masbench plumbing tests for the PythonGen message_only_v1 worker contract.

These cover the CLI flag, RunConfig threading, the stdin payload, offline
run_instance behaviour under both information goals, evidence-cache isolation,
and that the default action_json_v1 path stays byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path

from exp_graph.mas.python_code import (
    DEFAULT_MESSAGE_ONLY_PROGRAM,
    DEFAULT_MESSAGE_ONLY_V2_PROGRAM,
    DEFAULT_PYTHON_PROGRAM,
)

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.cache import EvidenceCache
from masbench.cli import _cfg_from_args, build_parser
from masbench.core.config import RunConfig
from masbench.engine import _build_python_execution_payload, run_instance


DATA = Path(__file__).parent / "data"


def _instance():
    return next(SiloBenchAdapter(DATA).iter_instances(cases=["I-01"]))


def _cfg(tmp_path: Path, **overrides) -> RunConfig:
    values = dict(
        use_planner=True,
        planner_mode="python_generate",
        llm_provider="fake",
        model_name="fake",
        n_agents=2,
        max_rounds=3,
        silo_eval_mode="all_agents",
        python_worker_contract="message_only_v1",
        python_artifacts_dir=str(tmp_path / "python"),
    )
    values.update(overrides)
    return RunConfig(**values)


def test_cli_flag_threads_into_runconfig() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--case",
            "I-01",
            "--n-agents",
            "2",
            "--planner",
            "--planner-mode",
            "python_generate",
            "--python-worker-contract",
            "message_only_v1",
            "--llm",
            "fake",
            "--model-name",
            "fake",
        ]
    )
    assert args.python_worker_contract == "message_only_v1"
    cfg = _cfg_from_args(args)
    assert cfg.python_worker_contract == "message_only_v1"
    default_args = parser.parse_args(
        ["run", "--case", "I-01", "--n-agents", "2"]
    )
    assert default_args.python_worker_contract == "action_json_v1"
    assert _cfg_from_args(default_args).python_worker_contract == (
        "action_json_v1"
    )
    v2_args = parser.parse_args(
        [
            "run",
            "--case",
            "I-01",
            "--n-agents",
            "2",
            "--python-worker-contract",
            "message_only_v2",
        ]
    )
    assert _cfg_from_args(v2_args).python_worker_contract == "message_only_v2"


def test_execution_payload_records_the_worker_contract(tmp_path: Path) -> None:
    instance = _instance()
    from masbench.engine import _protocol_adapter

    adapter = _protocol_adapter(instance, information_goal="all_agents")
    payload = _build_python_execution_payload(
        instance=instance,
        cfg=_cfg(tmp_path),
        task_adapter=adapter,
        global_task=adapter.build_global_task(),
        n_agents=2,
    )
    assert payload["worker_contract"] == "message_only_v1"
    assert payload["execution_contract_version"] == "python_mas_v1"
    default_payload = _build_python_execution_payload(
        instance=instance,
        cfg=_cfg(tmp_path, python_worker_contract="action_json_v1"),
        task_adapter=adapter,
        global_task=adapter.build_global_task(),
        n_agents=2,
    )
    assert default_payload["worker_contract"] == "action_json_v1"

    v2_global_task = adapter.build_global_task()
    v2_global_task["task_prompt"] = (
        "Find the GLOBAL MAXIMUM across all agents' data. "
        "You are Agent {agent_id} and hold: {input_shard}\n\n"
        "**Output:**\nA single integer representing the global maximum value."
    )
    v2_payload = _build_python_execution_payload(
        instance=instance,
        cfg=_cfg(tmp_path, python_worker_contract="message_only_v2"),
        task_adapter=adapter,
        global_task=v2_global_task,
        n_agents=2,
    )
    assert v2_payload["worker_contract"] == "message_only_v2"
    for agent in v2_payload["agents"]:
        assert set(agent) == {
            "agent_id",
            "communication_prompt",
            "submit_prompt",
        }
        assert "PUBLIC_ANSWER_REQUIREMENT:" in agent["submit_prompt"]
        assert "A single integer representing" in agent["submit_prompt"]
        for prompt in (agent["communication_prompt"], agent["submit_prompt"]):
            lowered = prompt.lower()
            assert "belief_state" not in lowered
            assert "structured_state" not in lowered
            assert "consensus_key" not in lowered
            assert "ground_truth" not in lowered


def test_offline_all_agents_run_uses_plain_text_workers(tmp_path: Path) -> None:
    score = run_instance(_instance(), _cfg(tmp_path))
    extra = score.extra
    assert extra["planner_mode"] == "python_generate"
    assert extra["worker_contract"] == "message_only_v1"
    assert extra["program_validity"] == 1.0
    assert extra["provenance"] == "fake"
    assert extra["all_agents_full_information"] is True
    submissions = extra["python_submissions"]
    assert len(submissions) == 2
    for item in submissions:
        assert item["submitted_round"] is not None
        assert isinstance(item["answer"], str) and item["answer"]
        # Plain text, not an action JSON object.
        try:
            parsed = json.loads(item["answer"])
        except json.JSONDecodeError:
            parsed = None
        assert not isinstance(parsed, dict)
    artifact_dir = Path(extra["python_artifacts_dir"])
    report = json.loads((artifact_dir / "execution_report.json").read_text())
    assert report["worker_contract"] == "message_only_v1"
    assert (artifact_dir / "final_program.py").read_text() == (
        DEFAULT_MESSAGE_ONLY_PROGRAM
    )


def test_offline_sink_run_requires_only_the_sink_submission(
    tmp_path: Path,
) -> None:
    score = run_instance(_instance(), _cfg(tmp_path, silo_eval_mode="sink"))
    extra = score.extra
    assert extra["worker_contract"] == "message_only_v1"
    assert extra["sink_information_coverage"] == 1.0
    submissions = {
        item["agent_id"]: item for item in extra["python_submissions"]
    }
    assert submissions[0]["submitted_round"] is not None
    assert submissions[1]["submitted_round"] is None
    assert submissions[1]["answer"] is None


def test_offline_v2_run_exposes_synchronized_native_answer_barrier(
    tmp_path: Path,
) -> None:
    score = run_instance(
        _instance(),
        _cfg(
            tmp_path,
            python_worker_contract="message_only_v2",
            max_rounds=2,
            python_max_model_calls=4,
        ),
    )
    extra = score.extra
    assert extra["worker_contract"] == "message_only_v2"
    assert extra["program_validity"] == 1.0
    assert extra["all_agents_full_information"] is True
    submissions = extra["python_submissions"]
    assert [item["submitted_round"] for item in submissions] == [1, 1]
    assert [item["answer"] for item in submissions] == ["UNKNOWN", "UNKNOWN"]
    barrier = extra["python_submit_barrier"]
    assert barrier["expected_agent_ids"] == [0, 1]
    assert barrier["observed_agent_ids"] == [0, 1]
    assert barrier["submit_round"] == 1
    assert barrier["synchronized"] is True
    artifact_dir = Path(extra["python_artifacts_dir"])
    assert (artifact_dir / "final_program.py").read_text() == (
        DEFAULT_MESSAGE_ONLY_V2_PROGRAM
    )
    report = json.loads((artifact_dir / "execution_report.json").read_text())
    assert report["worker_contract"] == "message_only_v2"
    assert report["submit_barrier"] == barrier


def test_default_contract_still_runs_the_action_scaffold(tmp_path: Path) -> None:
    score = run_instance(
        _instance(),
        _cfg(tmp_path, python_worker_contract="action_json_v1"),
    )
    extra = score.extra
    assert extra["worker_contract"] == "action_json_v1"
    assert extra["program_validity"] == 1.0
    artifact_dir = Path(extra["python_artifacts_dir"])
    assert (artifact_dir / "final_program.py").read_text() == (
        DEFAULT_PYTHON_PROGRAM
    )
    report = json.loads((artifact_dir / "execution_report.json").read_text())
    assert report["worker_contract"] == "action_json_v1"


def test_evidence_cache_key_isolates_contracts_without_breaking_old_keys(
    tmp_path: Path,
) -> None:
    action_cfg = _cfg(tmp_path, python_worker_contract="action_json_v1")
    message_cfg = _cfg(tmp_path)
    common = dict(
        case_id="I-01",
        n_agents=2,
        planner_mode="python_generate",
        objective="balanced",
        seed=0,
    )
    action_key = EvidenceCache.key(cfg=action_cfg, **common)
    message_key = EvidenceCache.key(cfg=message_cfg, **common)
    v2_key = EvidenceCache.key(
        cfg=_cfg(tmp_path, python_worker_contract="message_only_v2"),
        **common,
    )
    assert action_key != message_key
    assert len({action_key, message_key, v2_key}) == 3
    assert "pycontract=message_only_v1" in message_key
    assert "pycontract=message_only_v2" in v2_key
    # Pre-field cache keys (no python_worker_contract attribute at all) must
    # stay byte-identical so existing action-mode caches remain valid.
    class _LegacyCfg:
        llm_provider = "fake"
        model_name = "fake"
        merge_mode = "deterministic"
        init_mode = "deterministic"
        temperature = 0.0
        num_graph_candidates = 1
        silo_eval_mode = "all_agents"

    legacy_key = EvidenceCache.key(cfg=_LegacyCfg(), **common)
    assert legacy_key == action_key
