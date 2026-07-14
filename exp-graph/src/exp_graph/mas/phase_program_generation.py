"""Independent LLM planner for the restricted ``phase_program_v1`` DSL.

This module is intentionally separate from free-form GraphGen.  It generates
typed phase programs, compiles them deterministically, validates temporal
coverage, and gives the architect bounded counterexample-driven repair turns.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.llm.base import LLMClient
from exp_graph.llm.parser import extract_json_object
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphGenerationError,
    GraphValidationOptions,
    validate_graph_plan,
)
from exp_graph.mas.leakage_audit import assert_prompt_clean
from exp_graph.mas.motifs import score_spec_by_motifs
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_FORMAT,
    CompiledPhaseProgram,
    PhaseProgram,
    PhaseProgramError,
    PhaseProgramLimits,
    compile_phase_program_spec,
)
from exp_graph.mas.role_llm import (
    create_role_llm_client,
    resolve_role_llm_config,
)
from exp_graph.mas.schemas import (
    InformationGoal,
    MASPlan,
    MASRuntimeConfig,
    PlannerRequest,
    SkillCard,
)
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.skill_payloads import (
    phase_program_from_skill,
    protocol_spec_from_skill,
)
from exp_graph.mas.topology_equivalence import protocol_metadata_with_fingerprint
from exp_graph.protocols import ProtocolGraphSpec


class PhaseProgramGenerationError(GraphGenerationError):
    """Restricted program generation failed after bounded repair attempts."""


class GeneratedPhaseProgram(BaseModel):
    """One model-authored restricted program candidate."""

    candidate_id: str = "candidate_0"
    name: str = "generated_phase_program"
    program: PhaseProgram
    rationale: str = ""
    provenance: str = "program_generated"
    source_skill_id: str | None = None


class PhaseProgramCandidateRecord(BaseModel):
    """Auditable source, expansion, validation, and repair history."""

    candidate_id: str
    name: str
    status: str
    provenance: str
    source_program: dict[str, Any]
    compiled_program: dict[str, Any] | None = None
    protocol_spec: dict[str, Any] | None = None
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    counterexamples: list[dict[str, Any]] = Field(default_factory=list)
    repair_attempts: list[dict[str, Any]] = Field(default_factory=list)
    motif_score: float | None = None


class PhaseProgramPlanningResult(BaseModel):
    """Selected executable program plus all candidate audit records."""

    plan: MASPlan
    candidates: list[PhaseProgramCandidateRecord] = Field(default_factory=list)
    selected_candidate_id: str
    architect_prompt: str | None = None
    architect_prompt_sha256: str | None = None
    raw_responses: list[str] = Field(default_factory=list)
    selection_reason: str
    information_goal: InformationGoal


def build_phase_program_prompt(
    *,
    request: PlannerRequest,
    skills: list[SkillCard],
    avoid_skills: list[SkillCard],
    max_steps: int,
    max_messages: int,
    max_receiver_fan_in: int,
    num_candidates: int,
    task_brief: str | None,
    include_failure_feedback: bool = False,
) -> str:
    """Render the strict stage-only architect contract as JSON."""
    negative_skills: list[SkillCard] = []
    seen_negative: set[str] = set()
    negative_sources = [*avoid_skills]
    if include_failure_feedback:
        negative_sources = [*skills, *negative_sources]
    for skill in negative_sources:
        if not (skill.failure_modes or skill.counterexamples or skill.risk_notes):
            continue
        if skill.skill_id in seen_negative:
            continue
        negative_skills.append(skill)
        seen_negative.add(skill.skill_id)
    payload = {
        "role": "You design executable multi-agent collaboration programs.",
        "mode": "program_generate",
        "mission": (
            "Compose a small sequence of typed phases. Do not write concrete "
            "edges, formulas, loop variables, or named topology templates."
        ),
        "request": request.model_dump(mode="json"),
        "task_brief": task_brief,
        "constraints": {
            "max_steps_after_compilation": max_steps,
            "max_messages_after_compilation": max_messages,
            "max_receiver_fan_in": max_receiver_fan_in,
            "num_candidates": num_candidates,
        },
        "state_semantics": {
            "retention": "Every agent keeps its previous state by default.",
            "optional_send": (
                "An agent absent from a compiled phase edge sends nothing; "
                "delta_or_no_send asks workers to forward only useful new state."
            ),
            "simultaneous_steps": (
                "All transfers in one compiled step read the previous state snapshot."
            ),
            "submit_guard": (
                "all_agents programs may submit only after every agent has full "
                "source coverage."
            ),
        },
        "phase_language": {
            "format": PHASE_PROGRAM_FORMAT,
            "root_fields": [
                "format",
                "information_goal",
                "selected_primary",
                "state_retention",
                "allow_no_send",
                "submit_when",
                "phases",
            ],
            "allowed_phases": {
                "gather": {
                    "fields": ["kind", "hub", "pattern", "instruction", "send_mode"],
                    "pattern": ["star", "tree"],
                },
                "broadcast": {
                    "fields": ["kind", "hub", "pattern", "instruction", "send_mode"],
                    "pattern": ["star", "tree"],
                },
                "pairwise_exchange": {
                    "fields": [
                        "kind",
                        "pattern",
                        "max_rounds",
                        "stop_when",
                        "instruction",
                        "send_mode",
                    ],
                    "pattern": ["ring", "bidirectional_ring", "rotating"],
                },
                "consensus": {
                    "fields": [
                        "kind",
                        "pattern",
                        "max_rounds",
                        "stop_when",
                        "instruction",
                        "send_mode",
                    ],
                    "pattern": ["all_to_all", "rotating"],
                },
            },
            "stop_when": [
                "fixed_rounds",
                "sink_full_information",
                "all_agents_full_information",
            ],
            "send_mode": ["full_state", "delta_or_no_send"],
            "forbidden": [
                "edge arrays",
                "endpoint expressions",
                "arithmetic formulas",
                "user-defined loops",
                "imports",
                "code",
            ],
        },
        "goal_rules": (
            [
                "All source information must reach selected_primary.",
                "Prefer bounded gather/reduction phases and avoid unnecessary dissemination.",
            ]
            if request.information_goal == "sink"
            else [
                "Every agent must finish with every source's information.",
                "A gather-only program is invalid; include dissemination or consensus.",
            ]
        ),
        "reasoning_instruction_rules": [
            "Each phase instruction tells receivers what to compute, preserve, and forward.",
            "Never include concrete task data or expected values.",
            "Preserve source provenance and avoid double counting.",
            "Keep each instruction under 300 characters.",
        ],
        "skill_evidence": [_skill_context(skill) for skill in skills[:6]],
        "failure_evidence": _bounded_context_items(
            [_failure_context(skill) for skill in negative_skills[:6]],
            max_chars=4_000,
        ),
        "required_output": {
            "candidates": [
                {
                    "candidate_id": "<short id>",
                    "name": "<short snake_case name>",
                    "program": {
                        "format": PHASE_PROGRAM_FORMAT,
                        "information_goal": request.information_goal,
                        "selected_primary": "<integer agent id>",
                        "state_retention": "keep",
                        "allow_no_send": True,
                        "submit_when": "coverage_complete",
                        "phases": ["<typed phase objects only>"],
                    },
                    "rationale": "<short explanation>",
                }
            ]
        },
        "output_rules": [
            "Return one JSON object only.",
            "Return exactly the requested number of candidates.",
            "Do not emit steps, edges, expressions, or code.",
            "Use only listed fields and enum values.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def plan_phase_program(
    *,
    request: PlannerRequest,
    runtime: MASRuntimeConfig,
    skill_bank: SkillBank,
    seed: int,
    task_adapter: Any,
    output_dir: Path,
    llm_client: LLMClient | None = None,
) -> PhaseProgramPlanningResult:
    """Generate, repair, validate, select, and persist a restricted program."""
    del seed  # deterministic selection is driven by candidate order/evidence
    goal: InformationGoal = runtime.information_goal
    options = GraphValidationOptions(
        n_agents=request.n_agents,
        max_steps=runtime.graph_max_steps,
        max_messages=runtime.graph_max_messages,
        max_receiver_fan_in=runtime.graph_max_receiver_fan_in,
        repair_attempts=0,
        require_full_sink_coverage=True,
        information_goal=goal,
    )
    limits = PhaseProgramLimits(
        max_steps=runtime.graph_max_steps,
        max_messages=runtime.graph_max_messages,
        max_receiver_fan_in=runtime.graph_max_receiver_fan_in,
    )
    describe = getattr(task_adapter, "describe_task", None)
    task_brief = describe() if callable(describe) else None
    positive = skill_bank.retrieve(request)
    context = skill_bank.retrieve_generation_context(request)
    prompt_skills = list(positive)
    seen_skill_ids = {skill.skill_id for skill in prompt_skills}
    for skill in context:
        if skill.skill_id not in seen_skill_ids:
            prompt_skills.append(skill)
            seen_skill_ids.add(skill.skill_id)
    seeded = _skill_seeded_candidates(positive, request.n_agents)
    count = max(1, runtime.num_graph_candidates)
    remaining = max(0, count - len(seeded))
    emperor = resolve_role_llm_config(runtime, "emperor")
    prompt: str | None = None
    raw_responses: list[str] = []

    try:
        if emperor.platform == "fake":
            fresh = [
                _fake_candidate(request, idx)
                for idx in range(remaining)
            ]
        elif remaining:
            prompt = build_phase_program_prompt(
                request=request,
                skills=prompt_skills,
                avoid_skills=skill_bank.retrieve_avoid(request),
                max_steps=runtime.graph_max_steps,
                max_messages=runtime.graph_max_messages,
                max_receiver_fan_in=runtime.graph_max_receiver_fan_in,
                num_candidates=remaining,
                task_brief=task_brief,
                include_failure_feedback=runtime.failure_feedback_enabled,
            )
            if runtime.leakage_audit:
                assert_prompt_clean(
                    prompt,
                    context="architect phase-program prompt",
                    allowed_tokens=runtime.leakage_allowed_tokens,
                )
            client = llm_client or create_role_llm_client(runtime, "emperor")
            response = client.complete(
                prompt,
                model_name=emperor.model_name,
                temperature=emperor.temperature,
            )
            raw_responses.append(response.text)
            fresh = parse_phase_program_candidates(
                response.text,
                expected_count=remaining,
            )
        else:
            fresh = []

        candidates = [*seeded, *fresh]
        records: list[PhaseProgramCandidateRecord] = []
        valid: list[tuple[GeneratedPhaseProgram, ProtocolGraphSpec, PhaseProgramCandidateRecord]] = []
        client = llm_client or (
            create_role_llm_client(runtime, "emperor")
            if emperor.platform != "fake"
            else None
        )
        for candidate in candidates:
            current = candidate
            record, spec = _compile_candidate(current, options=options, limits=limits)
            for repair_idx in range(max(0, runtime.program_repair_attempts)):
                if spec is not None or emperor.platform == "fake" or client is None:
                    break
                repair_prompt = build_phase_program_repair_prompt(
                    request=request,
                    candidate=current,
                    record=record,
                    attempt=repair_idx + 1,
                    max_steps=runtime.graph_max_steps,
                    max_messages=runtime.graph_max_messages,
                )
                if runtime.leakage_audit:
                    assert_prompt_clean(
                        repair_prompt,
                        context="architect phase-program counterexample repair",
                        allowed_tokens=runtime.leakage_allowed_tokens,
                    )
                response = client.complete(
                    repair_prompt,
                    model_name=emperor.model_name,
                    temperature=emperor.temperature,
                )
                raw_responses.append(response.text)
                repair_entry: dict[str, Any] = {
                    "attempt": repair_idx + 1,
                    "prompt_sha256": _sha256(repair_prompt),
                    "errors_before": list(record.validation_errors),
                    "counterexamples": list(record.counterexamples),
                }
                try:
                    repaired = parse_repaired_phase_program(
                        response.text,
                        candidate_id=current.candidate_id,
                        name=current.name,
                    )
                    next_record, next_spec = _compile_candidate(
                        repaired,
                        options=options,
                        limits=limits,
                    )
                    next_record.repair_attempts = list(record.repair_attempts)
                    repair_entry["program"] = repaired.program.model_dump(mode="json")
                    repair_entry["errors_after"] = list(next_record.validation_errors)
                    current, record, spec = repaired, next_record, next_spec
                except Exception as exc:
                    repair_entry["parse_error"] = str(exc)
                record.repair_attempts.append(repair_entry)
            records.append(record)
            if spec is not None:
                valid.append((current, spec, record))

        if not valid:
            reason = "no valid restricted phase-program candidates"
            _write_artifacts(
                output_dir,
                prompt=prompt,
                raw_responses=raw_responses,
                records=records,
                selected=None,
                failure=reason,
                information_goal=goal,
            )
            raise PhaseProgramGenerationError(reason)

        selected = _select_candidate(valid, runtime)
        candidate, spec, record = selected
        record.status = "selected"
        plan = MASPlan(
            planner_mode="program_generate",
            topology_name=f"program:{candidate.name}",
            skill_id=candidate.source_skill_id,
            operators=list(spec.operators),
            protocol_spec=spec,
            config_overrides={
                "protocol_spec": spec,
                "enable_step_instructions": True,
            },
            rationale=(
                "Generated and compiled a restricted phase program; "
                + candidate.rationale
            ),
            provenance=(
                candidate.provenance
                if candidate.provenance in {"skill_replay", "fake"}
                else "program_generated"
            ),
        )
        selection_reason = _selection_reason(selected, valid, runtime)
        _write_artifacts(
            output_dir,
            prompt=prompt,
            raw_responses=raw_responses,
            records=records,
            selected=record,
            failure=None,
            information_goal=goal,
            selection_reason=selection_reason,
        )
        return PhaseProgramPlanningResult(
            plan=plan,
            candidates=records,
            selected_candidate_id=record.candidate_id,
            architect_prompt=prompt,
            architect_prompt_sha256=_sha256(prompt) if prompt else None,
            raw_responses=raw_responses,
            selection_reason=selection_reason,
            information_goal=goal,
        )
    except PhaseProgramGenerationError:
        raise
    except Exception as exc:
        reason = str(exc)
        _write_artifacts(
            output_dir,
            prompt=prompt,
            raw_responses=raw_responses,
            records=[],
            selected=None,
            failure=reason,
            information_goal=goal,
        )
        raise PhaseProgramGenerationError(reason) from exc


def parse_phase_program_candidates(
    text: str,
    *,
    expected_count: int,
) -> list[GeneratedPhaseProgram]:
    payload = extract_json_object(text)
    raw = payload.get("candidates")
    if not isinstance(raw, list):
        raise ValueError("phase-program response must contain candidates")
    candidates: list[GeneratedPhaseProgram] = []
    errors: list[str] = []
    for idx, item in enumerate(raw[: max(1, expected_count)]):
        if not isinstance(item, dict):
            errors.append(f"candidate {idx} is not an object")
            continue
        data = dict(item)
        data.pop("provenance", None)
        data.setdefault("candidate_id", f"candidate_{idx}")
        data.setdefault("name", f"phase_program_{idx}")
        try:
            candidates.append(
                GeneratedPhaseProgram.model_validate(data).model_copy(
                    update={"provenance": "program_generated"}
                )
            )
        except Exception as exc:
            errors.append(f"candidate {idx}: {exc}")
    if not candidates:
        raise ValueError("no parseable phase programs: " + "; ".join(errors))
    return candidates


def parse_repaired_phase_program(
    text: str,
    *,
    candidate_id: str,
    name: str,
) -> GeneratedPhaseProgram:
    payload = extract_json_object(text)
    raw_program = payload.get("program", payload)
    program = PhaseProgram.model_validate(raw_program)
    return GeneratedPhaseProgram(
        candidate_id=candidate_id,
        name=name,
        program=program,
        rationale=str(payload.get("rationale", "counterexample repair")),
        provenance="program_generated",
    )


def build_phase_program_repair_prompt(
    *,
    request: PlannerRequest,
    candidate: GeneratedPhaseProgram,
    record: PhaseProgramCandidateRecord,
    attempt: int,
    max_steps: int,
    max_messages: int,
) -> str:
    """Give the architect concrete structural counterexamples, never answers."""
    payload = {
        "role": "Repair one restricted collaboration program locally.",
        "mode": "program_generate_counterexample_repair",
        "attempt": attempt,
        "information_goal": request.information_goal,
        "n_agents": request.n_agents,
        "budgets": {"max_steps": max_steps, "max_messages": max_messages},
        "current_program": candidate.program.model_dump(mode="json"),
        "compiler_or_validator_errors": record.validation_errors,
        "minimal_counterexamples": record.counterexamples,
        "warnings": record.validation_warnings,
        "repair_rules": [
            "Change only phases or bounded phase parameters needed to fix the listed failures.",
            "Use only gather, broadcast, pairwise_exchange, and consensus.",
            "Do not emit edges, endpoint formulas, code, or new fields.",
            "Do not include concrete task values.",
            "For all_agents, gather-only remains invalid.",
        ],
        "required_output": {
            "program": "<one complete phase_program_v1 object>",
            "rationale": "<what counterexample was repaired>",
        },
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def _compile_candidate(
    candidate: GeneratedPhaseProgram,
    *,
    options: GraphValidationOptions,
    limits: PhaseProgramLimits,
) -> tuple[PhaseProgramCandidateRecord, ProtocolGraphSpec | None]:
    source = candidate.program.model_dump(mode="json")
    record = PhaseProgramCandidateRecord(
        candidate_id=candidate.candidate_id,
        name=candidate.name,
        status="rejected",
        provenance=candidate.provenance,
        source_program=source,
    )
    if candidate.program.information_goal != options.information_goal:
        record.validation_errors.append(
            "program information_goal does not match the requested goal"
        )
        return record, None
    try:
        spec, compiled = compile_phase_program_spec(
            candidate.program,
            n_agents=options.n_agents,
            limits=limits,
            name=candidate.name,
        )
    except (PhaseProgramError, ValueError) as exc:
        record.validation_errors.append(str(exc))
        return record, None
    graph = _graph_from_compiled(candidate, compiled)
    validation = validate_graph_plan(graph, options)
    record.compiled_program = compiled.model_dump(mode="json")
    record.validation_errors = list(validation.errors)
    record.validation_warnings = [*compiled.warnings, *validation.warnings]
    record.counterexamples = _coverage_counterexamples(
        compiled,
        information_goal=options.information_goal,
        selected_primary=candidate.program.selected_primary,
    )
    if not validation.valid:
        return record, None
    spec = spec.model_copy(
        update={
            "metadata": {
                **spec.metadata,
                "candidate_id": candidate.candidate_id,
                "provenance": candidate.provenance,
                **protocol_metadata_with_fingerprint(spec),
            }
        }
    )
    record.status = "valid"
    record.protocol_spec = spec.model_dump(mode="json")
    return record, spec


def _graph_from_compiled(
    candidate: GeneratedPhaseProgram,
    compiled: CompiledPhaseProgram,
) -> GeneratedGraphPlan:
    return GeneratedGraphPlan(
        candidate_id=candidate.candidate_id,
        name=candidate.name,
        graph_type="temporal_dag",
        n_agents=len(compiled.final_knowledge),
        selected_primary=compiled.selected_primary,
        steps=[
            GeneratedGraphStep(
                description=step.description,
                edges=step.transmissions,
                operator_hint=f"phase:{step.phase_kind}",
                instruction=step.instruction,
            )
            for step in compiled.steps
        ],
        rationale=candidate.rationale,
        provenance=candidate.provenance,
    )


def _coverage_counterexamples(
    compiled: CompiledPhaseProgram,
    *,
    information_goal: InformationGoal,
    selected_primary: int,
) -> list[dict[str, Any]]:
    target = set(range(len(compiled.final_knowledge)))
    counterexamples: list[dict[str, Any]] = []
    if information_goal == "sink":
        missing = sorted(target - set(compiled.final_knowledge[selected_primary]))
        if missing:
            counterexamples.append(
                {"target_agent": selected_primary, "missing_source_agents": missing}
            )
        return counterexamples
    for agent_id, known in enumerate(compiled.final_knowledge):
        missing = sorted(target - set(known))
        if missing:
            counterexamples.append(
                {"target_agent": agent_id, "missing_source_agents": missing}
            )
    return counterexamples[:20]


def _skill_seeded_candidates(
    skills: list[SkillCard],
    n_agents: int,
) -> list[GeneratedPhaseProgram]:
    candidates: list[GeneratedPhaseProgram] = []
    seen: set[str] = set()
    for skill in skills[:6]:
        spec_data = protocol_spec_from_skill(skill)
        if not isinstance(spec_data, dict):
            continue
        try:
            spec = ProtocolGraphSpec.model_validate(spec_data)
        except Exception:
            continue
        raw = phase_program_from_skill(skill)
        if not isinstance(raw, dict) or spec.n_agents != n_agents:
            continue
        try:
            program = PhaseProgram.model_validate(raw)
        except Exception:
            continue
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        candidates.append(
            GeneratedPhaseProgram(
                candidate_id=f"skill_{_safe_id(skill.skill_id)}",
                name=spec.name or _safe_id(skill.skill_id),
                program=program,
                rationale=f"Replay verified phase program from {skill.skill_id}.",
                provenance="skill_replay",
                source_skill_id=skill.skill_id,
            )
        )
        if len(candidates) >= 3:
            break
    return candidates


def _fake_candidate(request: PlannerRequest, idx: int) -> GeneratedPhaseProgram:
    hub = idx % request.n_agents
    phases: list[dict[str, Any]] = [
        {
            "kind": "gather",
            "hub": hub,
            "pattern": "tree",
            "instruction": "Merge source-tagged contributions without double counting.",
        }
    ]
    if request.information_goal == "all_agents":
        phases.append(
            {
                "kind": "broadcast",
                "hub": hub,
                "pattern": "tree",
                "instruction": "Absorb the merged artifact and retain all source tags.",
            }
        )
    return GeneratedPhaseProgram(
        candidate_id=f"fake_program_{idx}",
        name=f"bounded_gather_disseminate_{idx}",
        program=PhaseProgram.model_validate(
            {
                "information_goal": request.information_goal,
                "selected_primary": hub,
                "phases": phases,
            }
        ),
        rationale="Deterministic offline restricted-program smoke candidate.",
        provenance="fake",
    )


def _select_candidate(
    valid: list[tuple[GeneratedPhaseProgram, ProtocolGraphSpec, PhaseProgramCandidateRecord]],
    runtime: MASRuntimeConfig,
) -> tuple[GeneratedPhaseProgram, ProtocolGraphSpec, PhaseProgramCandidateRecord]:
    if runtime.replay_first:
        replay = [item for item in valid if item[0].provenance == "skill_replay"]
        if replay:
            return replay[0]
    if runtime.use_motif_prior and runtime.motif_stats:
        ranked = []
        for item in valid:
            score = score_spec_by_motifs(
                item[1],
                runtime.motif_stats,
                uncertainty_kappa=runtime.motif_uncertainty_kappa,
            )
            item[2].motif_score = None if math.isinf(score) else score
            ranked.append((score, item))
        finite = [item for score, item in ranked if not math.isinf(score)]
        if finite:
            return min(
                finite,
                key=lambda item: float(item[2].motif_score or 0.0),
            )
    return valid[0]


def _selection_reason(
    selected: tuple[GeneratedPhaseProgram, ProtocolGraphSpec, PhaseProgramCandidateRecord],
    valid: list[tuple[GeneratedPhaseProgram, ProtocolGraphSpec, PhaseProgramCandidateRecord]],
    runtime: MASRuntimeConfig,
) -> str:
    candidate, _spec, record = selected
    if candidate.provenance == "skill_replay" and runtime.replay_first:
        reason = "replay-first selected a verified restricted program"
    elif record.motif_score is not None:
        reason = f"lowest finite motif loss={record.motif_score:.6f}"
    else:
        reason = "first valid restricted program"
    return f"{reason}; selected 1 of {len(valid)} valid candidates"


def _skill_context(skill: SkillCard) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "phase_program": phase_program_from_skill(skill),
        "reasoning_policy": skill.reasoning_policy,
        "expected_tradeoff": skill.expected_tradeoff,
        "design_insights": skill.design_insights[:3],
    }


def _failure_context(skill: SkillCard) -> dict[str, Any]:
    return _scrub_failure_context({
        "skill_id": skill.skill_id,
        "failure_modes": skill.failure_modes[:5],
        "counterexamples": skill.counterexamples[:5],
        "risk_notes": skill.risk_notes[:3],
    })


_FAILURE_CONTEXT_FORBIDDEN_KEYS = {
    "answer",
    "final_answer",
    "ground_truth",
    "expected_output",
    "expected_outputs",
    "expected_answer",
    "expected_answers",
    "prompt",
    "task_prompt",
    "agent_prompt",
    "local_prompt",
    "private_prompt",
    "private_data",
    "source_code",
    "python_source",
    "protocol_spec",
    "phase_program",
    "topology_program",
    "structure_code",
    "code",
    "steps",
    "edges",
    "mode_payload",
    "shard",
    "shards",
}


def _scrub_failure_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _scrub_failure_context(item)
            for key, item in value.items()
            if str(key).lower() not in _FAILURE_CONTEXT_FORBIDDEN_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_failure_context(item) for item in value]
    return value


def _bounded_context_items(
    items: list[dict[str, Any]],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Bound answer-free failure context without emitting partial JSON."""
    output: list[dict[str, Any]] = []
    used = 2
    for item in items:
        encoded = json.dumps(item, ensure_ascii=True, sort_keys=True)
        if used + len(encoded) > max_chars:
            break
        output.append(item)
        used += len(encoded) + 1
    return output


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)[:80]


def _scrub_secrets(text: str | None) -> str | None:
    if text is None:
        return None
    scrubbed = text
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(
            marker in name.upper() for marker in ("API_KEY", "APIKEY", "SECRET", "TOKEN")
        ):
            scrubbed = scrubbed.replace(value, f"[REDACTED:{name}]")
    return scrubbed


def _write_artifacts(
    output_dir: Path,
    *,
    prompt: str | None,
    raw_responses: list[str],
    records: list[PhaseProgramCandidateRecord],
    selected: PhaseProgramCandidateRecord | None,
    failure: str | None,
    information_goal: InformationGoal,
    selection_reason: str | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    scrubbed_prompt = _scrub_secrets(prompt)
    payload = {
        "planner_mode": "program_generate",
        "program_format": PHASE_PROGRAM_FORMAT,
        "information_goal": information_goal,
        "rendered_prompt": scrubbed_prompt,
        "prompt_sha256": _sha256(scrubbed_prompt) if scrubbed_prompt else None,
        "raw_responses": [_scrub_secrets(text) for text in raw_responses],
        "candidates": [record.model_dump(mode="json") for record in records],
        "selected_candidate_id": selected.candidate_id if selected else None,
        "selection_reason": selection_reason,
        "program_generation_failed": failure,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    (output_dir / "program_architect_call.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (output_dir / "selected_phase_program.json").write_text(
        json.dumps(
            selected.model_dump(mode="json") if selected else {},
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
