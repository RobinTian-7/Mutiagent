"""Mode-specific executable payload helpers for planner skills.

The skill envelope deliberately keeps evidence and analysis fields common, but
the executable artifact is never inferred from one shared untyped dictionary
for newly-created cards.  These helpers also provide a narrow legacy reader so
existing banks can be replayed while they are migrated by normal evolution.
"""

from __future__ import annotations

import hashlib
import json

from exp_graph.mas.schemas import (
    GraphSkillPayload,
    ModeSkillPayload,
    NamedTopologySkillPayload,
    PaperTransportSkillPayload,
    PhaseProgramSkillPayload,
    PythonSkillPayload,
    SkillCard,
)


def planner_mode_from_skill(skill: SkillCard) -> str | None:
    """Return the declared planner mode, preferring the typed payload."""
    if skill.mode_payload is not None:
        return str(skill.mode_payload.planner_mode)
    value = skill.trigger.get("planner_mode") or skill.organization_policy.get(
        "planner_mode"
    )
    return str(value) if value else None


def protocol_spec_from_skill(skill: SkillCard) -> dict[str, object] | None:
    """Return an executable static schedule from the matching payload format."""
    payload = skill.mode_payload
    if isinstance(payload, (NamedTopologySkillPayload, GraphSkillPayload)):
        return payload.protocol_spec
    if isinstance(payload, PhaseProgramSkillPayload):
        return payload.compiled_protocol_spec
    legacy = skill.organization_policy.get("protocol_spec")
    return legacy if isinstance(legacy, dict) else None


def phase_program_from_skill(skill: SkillCard) -> dict[str, object] | None:
    """Return restricted DSL source only from a Phase payload or legacy card."""
    payload = skill.mode_payload
    if isinstance(payload, PhaseProgramSkillPayload):
        return payload.phase_program
    spec = protocol_spec_from_skill(skill)
    metadata = spec.get("metadata") if isinstance(spec, dict) else None
    raw = metadata.get("phase_program") if isinstance(metadata, dict) else None
    return raw if isinstance(raw, dict) else None


def python_source_from_skill(skill: SkillCard) -> str | None:
    """Return complete Python source only from a Python payload or legacy card."""
    payload = skill.mode_payload
    if isinstance(payload, PythonSkillPayload):
        return payload.source_code
    source = skill.organization_policy.get("source_code")
    return source if isinstance(source, str) else None


def python_worker_contract_from_skill(skill: SkillCard) -> str:
    """Return the worker contract a Python card was recorded under.

    Cards written before the field existed are classified as the legacy
    action_json_v1 contract, which is exactly what their source implements.
    """
    payload = skill.mode_payload
    if isinstance(payload, PythonSkillPayload):
        return str(payload.worker_contract)
    value = skill.organization_policy.get("worker_contract")
    return str(value) if value else "action_json_v1"


def program_sha256_from_skill(skill: SkillCard) -> str | None:
    """Return the canonical Python/Phase program digest when available."""
    payload = skill.mode_payload
    if isinstance(payload, (PythonSkillPayload, PhaseProgramSkillPayload)):
        return payload.program_sha256
    value = skill.organization_policy.get("program_sha256")
    return str(value) if value else None


def paper_protocol_from_skill(skill: SkillCard) -> str | None:
    """Return a dynamic SILO transport identifier when present."""
    payload = skill.mode_payload
    if isinstance(payload, PaperTransportSkillPayload):
        return payload.protocol
    dynamic = skill.organization_policy.get("dynamic_transport")
    return str(dynamic) if dynamic else None


def structure_code_from_skill(skill: SkillCard) -> dict[str, object]:
    """Return the mode-owned executable descriptor without guessing its type."""
    payload = skill.mode_payload
    if isinstance(payload, (
        NamedTopologySkillPayload,
        GraphSkillPayload,
        PaperTransportSkillPayload,
    )):
        return dict(payload.structure_code)
    legacy = skill.organization_policy.get("structure_code")
    return dict(legacy) if isinstance(legacy, dict) else {}


def payload_digest(payload: ModeSkillPayload | None) -> str | None:
    """Hash a complete typed payload for revision and dedupe audit."""
    if payload is None:
        return None
    serialized = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def skill_type_for_payload(payload: ModeSkillPayload | None) -> str:
    """Return the archive identity associated with one payload schema."""
    if isinstance(payload, NamedTopologySkillPayload):
        return "named_topology_skill"
    if isinstance(payload, PaperTransportSkillPayload):
        return "paper_transport_skill"
    if isinstance(payload, GraphSkillPayload):
        return "graph_generation_skill"
    if isinstance(payload, PhaseProgramSkillPayload):
        return "phase_program_skill"
    if isinstance(payload, PythonSkillPayload):
        return "python_generation_skill"
    return "planner_organization_policy"


def payload_revision(
    before: ModeSkillPayload | None,
    after: ModeSkillPayload | None,
) -> dict[str, object] | None:
    """Describe one executable revision without duplicating full source code."""
    before_digest = payload_digest(before)
    after_digest = payload_digest(after)
    if before_digest == after_digest:
        return None
    entry: dict[str, object] = {
        "before_format": before.format if before is not None else None,
        "after_format": after.format if after is not None else None,
        "before_payload_sha256": before_digest,
        "after_payload_sha256": after_digest,
    }
    if isinstance(before, (PythonSkillPayload, PhaseProgramSkillPayload)):
        entry["before_program_sha256"] = before.program_sha256
    if isinstance(after, (PythonSkillPayload, PhaseProgramSkillPayload)):
        entry["after_program_sha256"] = after.program_sha256
    return entry


def merge_mode_payload(
    current: ModeSkillPayload | None,
    incoming: ModeSkillPayload | None,
) -> ModeSkillPayload | None:
    """Replace one executable revision, rejecting cross-format contamination."""
    if incoming is None:
        return current
    if current is None:
        return incoming
    if current.format != incoming.format:
        raise ValueError(
            "cannot merge different skill payload formats: "
            f"{current.format} != {incoming.format}"
        )
    if (
        isinstance(current, PythonSkillPayload)
        and isinstance(incoming, PythonSkillPayload)
        and current.worker_contract != incoming.worker_contract
    ):
        # Both contracts share the python_skill_v1 format, so the format guard
        # above cannot see this contamination: a consolidation patch must not
        # replace an action-JSON program with a message-only one (or back) on
        # the same card identity.
        raise ValueError(
            "cannot merge python skills across worker contracts: "
            f"{current.worker_contract} != {incoming.worker_contract}"
        )
    return incoming


def compatibility_policy_from_payload(
    policy: dict[str, object],
    payload: ModeSkillPayload | None,
) -> dict[str, object]:
    """Mirror typed state for legacy readers without making it authoritative."""
    merged = dict(policy)
    if isinstance(payload, NamedTopologySkillPayload):
        merged.update(
            {
                "planner_mode": payload.planner_mode,
                "topology_name": payload.topology_name,
                "protocol_spec": payload.protocol_spec,
                "structure_code": payload.structure_code,
            }
        )
    elif isinstance(payload, GraphSkillPayload):
        merged.update(
            {
                "planner_mode": payload.planner_mode,
                "topology_name": payload.topology_name,
                "protocol_spec": payload.protocol_spec,
                "structure_code": payload.structure_code,
            }
        )
    elif isinstance(payload, PhaseProgramSkillPayload):
        merged.update(
            {
                "planner_mode": payload.planner_mode,
                "topology_name": payload.topology_name,
                "protocol_spec": payload.compiled_protocol_spec,
                "program_sha256": payload.program_sha256,
            }
        )
    elif isinstance(payload, PythonSkillPayload):
        merged.update(
            {
                "planner_mode": payload.planner_mode,
                "source_code": payload.source_code,
                "program_sha256": payload.program_sha256,
                "ast_policy_version": payload.ast_policy_version,
                "execution_contract_version": payload.execution_contract_version,
                "worker_contract": payload.worker_contract,
                "repair_attempts": payload.repair_attempts,
                "observed_runtime_trace_summary": payload.runtime_trace_summary,
            }
        )
        if payload.artifact_reference:
            merged["artifact_reference"] = payload.artifact_reference
    elif isinstance(payload, PaperTransportSkillPayload):
        merged.update(
            {
                "planner_mode": "hot_start_reference",
                "topology_name": f"paper_{payload.protocol}",
                "dynamic_transport": payload.protocol,
                "protocol_spec": None,
                "structure_code": payload.structure_code,
            }
        )
    return merged


def payload_from_legacy(skill: SkillCard) -> ModeSkillPayload | None:
    """Best-effort adapter for cards written before mode payload schemas."""
    if skill.mode_payload is not None:
        return skill.mode_payload
    policy = skill.organization_policy or {}
    topology_name = str(policy.get("topology_name") or skill.skill_id)
    structure_code = policy.get("structure_code")
    code = dict(structure_code) if isinstance(structure_code, dict) else {}
    dynamic = policy.get("dynamic_transport")
    if dynamic:
        return PaperTransportSkillPayload(
            protocol=str(dynamic),
            structure_code=code,
        )
    source = policy.get("source_code")
    if isinstance(source, str) and source.strip():
        return PythonSkillPayload(
            source_code=source,
            program_sha256=str(policy.get("program_sha256") or ""),
            ast_policy_version=str(policy.get("ast_policy_version") or ""),
            execution_contract_version=str(
                policy.get("execution_contract_version") or ""
            ),
            worker_contract=(
                str(policy.get("worker_contract"))
                if policy.get("worker_contract")
                in {"message_only_v1", "message_only_v2"}
                else "action_json_v1"
            ),
            repair_attempts=int(policy.get("repair_attempts", 0) or 0),
            artifact_reference=(
                str(policy["artifact_reference"])
                if policy.get("artifact_reference")
                else None
            ),
            runtime_trace_summary=(
                dict(policy["observed_runtime_trace_summary"])
                if isinstance(policy.get("observed_runtime_trace_summary"), dict)
                else {}
            ),
        )
    spec = policy.get("protocol_spec")
    if not isinstance(spec, dict):
        return None
    metadata = spec.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    phase_program = metadata.get("phase_program")
    declared = planner_mode_from_skill(skill)
    if isinstance(phase_program, dict) or declared == "program_generate":
        if not isinstance(phase_program, dict):
            return None
        compilation = metadata.get("phase_program_compilation")
        compiler_version = "1"
        if isinstance(compilation, dict) and compilation.get("compiler_version"):
            compiler_version = str(compilation["compiler_version"])
        return PhaseProgramSkillPayload(
            topology_name=topology_name,
            phase_program=phase_program,
            compiled_protocol_spec=spec,
            compiler_version=compiler_version,
        )
    if metadata.get("generated_graph") or declared == "graph_generate":
        topology_program = metadata.get("topology_program")
        return GraphSkillPayload(
            topology_name=topology_name,
            protocol_spec=spec,
            topology_program=(
                dict(topology_program) if isinstance(topology_program, dict) else None
            ),
            structure_code=code,
        )
    return NamedTopologySkillPayload(
        topology_name=topology_name,
        protocol_spec=spec,
        structure_code=code,
    )


def mode_payload_from_skill(skill: SkillCard) -> ModeSkillPayload | None:
    """Return typed state or safely attempt one legacy migration."""
    if skill.mode_payload is not None:
        return skill.mode_payload
    try:
        return payload_from_legacy(skill)
    except ValueError:
        return None


def with_inferred_payload(skill: SkillCard) -> SkillCard:
    """Attach a typed payload in memory when a legacy card can be migrated."""
    if skill.mode_payload is not None:
        return skill
    payload = mode_payload_from_skill(skill)
    if payload is None:
        return skill
    update: dict[str, object] = {"mode_payload": payload}
    if skill.skill_type == "planner_organization_policy":
        update["skill_type"] = skill_type_for_payload(payload)
    return skill.model_copy(update=update)
