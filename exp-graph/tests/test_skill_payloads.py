from pathlib import Path

from exp_graph.mas.consolidation import consolidate_skill_updates
from exp_graph.mas.evolution import make_skill_card
from exp_graph.mas.python_code import DEFAULT_PYTHON_PROGRAM
from exp_graph.mas.schemas import (
    GraphSkillPayload,
    PhaseProgramSkillPayload,
    PythonSkillPayload,
    SkillCard,
    SkillPatch,
)
from exp_graph.mas.skill_bank import SkillBank, dump_skill_file, load_skill_file
from exp_graph.protocols import ProtocolGraphSpec, ProtocolStepSpec


def _spec(*, metadata: dict[str, object] | None = None) -> dict[str, object]:
    return ProtocolGraphSpec(
        name="payload_test",
        n_agents=2,
        steps=[ProtocolStepSpec(transmissions=[(0, 1)])],
        metadata=metadata or {},
    ).model_dump(mode="json")


def _python_card(*, source: str, suffix: str) -> SkillCard:
    payload = PythonSkillPayload(
        source_code=source,
        ast_policy_version="python_ast_v1",
        execution_contract_version="python_mas_v1",
        runtime_trace_summary={"revision": suffix},
    )
    return SkillCard(
        skill_id="python_iterative_skill",
        task_family="silo",
        trigger={"planner_mode": "python_generate", "nested": {"old": True}},
        information_goal="all_agents",
        provenance="llm_generated_python",
        mode_payload=payload,
        organization_policy={
            "planner_mode": "python_generate",
            "topology_name": "python:iterative",
            "source_code": source,
        },
        reasoning_policy={"merge": {"dedupe": True}},
        expected_tradeoff={"mean_primary_loss": 1.0},
        expected_dynamics={"coverage": {"minimum": 0.5}},
        design_insights=[{"insight_id": f"insight_{suffix}", "summary": suffix}],
        risk_notes=[{"summary": f"risk_{suffix}"}],
        failure_modes=[{"summary": f"failure_{suffix}"}],
        evidence=[{"evidence_id": f"evidence_{suffix}"}],
        evidence_refs=[f"evidence:{suffix}"],
        fallback={"action": f"fallback_{suffix}"},
        counterexamples=[{"case": f"counterexample_{suffix}"}],
        hypotheses=[{"summary": f"hypothesis_{suffix}"}],
        confidence={"score": 0.2 if suffix == "old" else 0.8},
        validation_plan=[{"summary": f"validate_{suffix}"}],
        update_rule=f"rule_{suffix}",
        tags=[suffix],
    )


def test_mode_payload_formats_are_disjoint() -> None:
    graph = GraphSkillPayload(
        topology_name="generated:test",
        protocol_spec=_spec(metadata={"generated_graph": True}),
    )
    phase_source = {
        "format": "phase_program_v1",
        "information_goal": "all_agents",
        "phases": [{"kind": "broadcast", "hub": 0}],
    }
    phase = PhaseProgramSkillPayload(
        topology_name="program:test",
        phase_program=phase_source,
        compiled_protocol_spec=_spec(
            metadata={
                "phase_program": phase_source,
                "program_mode": "program_generate",
            }
        ),
    )
    python = PythonSkillPayload(
        source_code=DEFAULT_PYTHON_PROGRAM,
        ast_policy_version="python_ast_v1",
        execution_contract_version="python_mas_v1",
    )

    assert {graph.format, phase.format, python.format} == {
        "graph_skill_v1",
        "phase_program_skill_v1",
        "python_skill_v1",
    }
    assert "source_code" not in GraphSkillPayload.model_fields
    assert "source_code" not in PhaseProgramSkillPayload.model_fields
    assert "protocol_spec" not in PythonSkillPayload.model_fields


def test_skill_factory_emits_graph_and_phase_payloads_in_their_own_formats() -> None:
    graph_spec = _spec(
        metadata={
            "generated_graph": True,
            "topology_program": {
                "format": "topology_program_v1",
                "steps": [],
            },
        }
    )
    graph_card = make_skill_card(
        skill_id="graph_payload",
        topology_name="generated:payload",
        objective="balanced",
        operators=["llm_generate_dag"],
        evidence=[
            {
                "planner_mode": "graph_generate",
                "protocol_spec": graph_spec,
                "n_agents": 2,
                "information_goal": "all_agents",
                "provenance": "llm_generated",
            }
        ],
        expected_tradeoff={"mean_primary_loss": 0.5},
    )
    phase_source = {
        "format": "phase_program_v1",
        "information_goal": "all_agents",
        "phases": [{"kind": "broadcast", "hub": 0}],
    }
    phase_spec = _spec(
        metadata={
            "generated_graph": True,
            "program_mode": "program_generate",
            "phase_program": phase_source,
        }
    )
    phase_card = make_skill_card(
        skill_id="phase_payload",
        topology_name="program:payload",
        objective="balanced",
        operators=["phase:broadcast"],
        evidence=[
            {
                "planner_mode": "program_generate",
                "protocol_spec": phase_spec,
                "n_agents": 2,
                "information_goal": "all_agents",
                "provenance": "program_generated",
            }
        ],
        expected_tradeoff={"mean_primary_loss": 0.5},
    )

    assert isinstance(graph_card.mode_payload, GraphSkillPayload)
    assert graph_card.mode_payload.topology_program["format"] == "topology_program_v1"
    assert isinstance(phase_card.mode_payload, PhaseProgramSkillPayload)
    assert phase_card.mode_payload.phase_program == phase_source


def test_python_payload_persists_complete_source_verbatim(tmp_path: Path) -> None:
    source = "# preserved first line\n" + DEFAULT_PYTHON_PROGRAM + "\n# preserved end\n"
    skill = _python_card(source=source, suffix="old")
    path = tmp_path / "python_skill.yaml"

    dump_skill_file(skill, path)
    restored = load_skill_file(path)

    assert isinstance(restored.mode_payload, PythonSkillPayload)
    assert restored.mode_payload.source_code == source
    assert restored.organization_policy["source_code"] == source
    assert restored.mode_payload.program_sha256


def test_consolidation_iterates_every_skill_surface_and_audits_code_revision() -> None:
    before_source = "# revision old\n" + DEFAULT_PYTHON_PROGRAM
    after_source = "# revision new\n" + DEFAULT_PYTHON_PROGRAM
    current = _python_card(source=before_source, suffix="old")
    candidate = _python_card(source=after_source, suffix="new").model_copy(
        update={
            "trigger": {
                "planner_mode": "python_generate",
                "nested": {"new": True},
            },
            "reasoning_policy": {"merge": {"provenance_guard": True}},
            "expected_tradeoff": {"mean_primary_loss": 0.25},
            "expected_dynamics": {"coverage": {"minimum": 1.0}},
        }
    )
    patch = SkillPatch(
        patch_id="iterate_all_python_fields",
        action="merge",
        target_skill_id=current.skill_id,
        candidate_skill=candidate,
        evidence=[{"evidence_id": "patch_evidence"}],
        evidence_refs=["patch:evidence"],
        update={
            "trigger": {"nested": {"patched": True}},
            "reasoning_policy": {"submit": {"coverage_required": True}},
            "expected_tradeoff": {"mean_token_cost": 50.0},
            "expected_dynamics": {"submission_rate": 1.0},
            "confidence": {"ablation_verified": True},
            "fallback": {"on_timeout": "reuse_previous"},
            "counterexamples": [{"case": "patch_counterexample"}],
            "failure_modes": [{"summary": "patch_failure"}],
            "design_insights": [
                {"insight_id": "patch_insight", "summary": "patch insight"}
            ],
            "validation_plan": [{"summary": "patch validation"}],
            "tags": ["iterated"],
            "update_rule": "paired_ablation_then_merge",
        },
        lesson="replace the program and refine every learned section",
    )

    updated, result = consolidate_skill_updates(
        bank=SkillBank([current]),
        patches=[patch],
        evidence_records=[],
        batch_id="payload_iteration",
    )
    skill = updated.get(current.skill_id)
    assert skill is not None
    assert isinstance(skill.mode_payload, PythonSkillPayload)
    assert skill.mode_payload.source_code == after_source
    assert skill.organization_policy["source_code"] == after_source
    assert skill.trigger["nested"] == {"old": True, "new": True, "patched": True}
    assert skill.reasoning_policy["merge"] == {
        "dedupe": True,
        "provenance_guard": True,
    }
    assert skill.reasoning_policy["submit"]["coverage_required"] is True
    assert skill.expected_tradeoff["mean_primary_loss"] == 0.25
    assert skill.expected_tradeoff["mean_token_cost"] == 50.0
    assert skill.expected_dynamics["coverage"]["minimum"] == 1.0
    assert skill.expected_dynamics["submission_rate"] == 1.0
    assert {item["insight_id"] for item in skill.design_insights} >= {
        "insight_old",
        "insight_new",
        "patch_insight",
    }
    assert any(item.get("case") == "patch_counterexample" for item in skill.counterexamples)
    assert any(item.get("summary") == "patch_failure" for item in skill.failure_modes)
    assert "patch:evidence" in skill.evidence_refs
    assert skill.confidence["ablation_verified"] is True
    assert skill.fallback["on_timeout"] == "reuse_previous"
    assert skill.update_rule == "paired_ablation_then_merge"
    assert "iterated" in skill.tags
    assert result.revisions[0].changed_fields

    revision = skill.revision_history[-1]
    assert "mode_payload" in revision["changed_fields"]
    assert "reasoning_policy" in revision["changed_fields"]
    payload_change = revision["mode_payload_revision"]
    assert payload_change["before_program_sha256"] != payload_change[
        "after_program_sha256"
    ]


def test_cross_format_candidate_is_discarded_instead_of_merged() -> None:
    graph_payload = GraphSkillPayload(
        topology_name="shared-name",
        protocol_spec=_spec(metadata={"generated_graph": True}),
    )
    phase_source = {
        "format": "phase_program_v1",
        "information_goal": "sink",
        "phases": [{"kind": "gather", "hub": 0}],
    }
    phase_payload = PhaseProgramSkillPayload(
        topology_name="shared-name",
        phase_program=phase_source,
        compiled_protocol_spec=_spec(metadata={"phase_program": phase_source}),
    )
    current = SkillCard(
        skill_id="format_guard",
        organization_policy={"topology_name": "shared-name"},
        mode_payload=graph_payload,
    )
    candidate = current.model_copy(update={"mode_payload": phase_payload})

    updated, result = consolidate_skill_updates(
        bank=SkillBank([current]),
        patches=[
            SkillPatch(
                patch_id="cross_format",
                action="merge",
                target_skill_id=current.skill_id,
                candidate_skill=candidate,
            )
        ],
        evidence_records=[],
        batch_id="format_guard",
    )

    assert result.counts["discarded"] == 1
    assert isinstance(updated.get(current.skill_id).mode_payload, GraphSkillPayload)


def test_direct_skill_bank_merge_also_updates_typed_python_revision() -> None:
    before = _python_card(
        source="# direct old\n" + DEFAULT_PYTHON_PROGRAM,
        suffix="old",
    )
    after = _python_card(
        source="# direct new\n" + DEFAULT_PYTHON_PROGRAM,
        suffix="new",
    )
    bank = SkillBank([before])

    result = bank.apply_patch(
        SkillPatch(
            patch_id="direct_typed_update",
            action="merge",
            target_skill_id=before.skill_id,
            candidate_skill=after,
            update={"reasoning_policy": {"direct_merge": True}},
        )
    )

    assert result == "merged"
    merged = bank.get(before.skill_id)
    assert isinstance(merged.mode_payload, PythonSkillPayload)
    assert merged.mode_payload.source_code.startswith("# direct new")
    assert merged.reasoning_policy["direct_merge"] is True
    assert merged.revision_history[-1]["mode_payload_revision"]
