"""Exponential dissemination pattern: doubling offsets, log-round coverage."""

from __future__ import annotations

from exp_graph.mas.phase_program import (
    PhaseProgram,
    compile_phase_program,
)


def _offsets(program: PhaseProgram, n_agents: int) -> list[set[int]]:
    compiled = compile_phase_program(program, n_agents=n_agents)
    per_step = []
    for step in compiled.steps:
        per_step.append(
            {
                (dst - src) % n_agents
                for src, dst in step.model_dump()["transmissions"]
            }
        )
    return per_step


def _program(kind: str, pattern: str, *, goal: str = "all_agents") -> PhaseProgram:
    phase: dict = {"kind": kind, "pattern": pattern, "max_rounds": 8}
    if kind == "consensus":
        phase["stop_when"] = "all_agents_full_information"
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": goal,
            "selected_primary": 0,
            "submit_when": "coverage_complete",
            "phases": [phase],
        }
    )


def test_consensus_exponential_offsets_double_until_coverage() -> None:
    program = _program("consensus", "exponential")
    offsets = _offsets(program, n_agents=5)
    # ceil(log2(5)) = 3 rounds to full information: offsets 1, 2, 4.
    assert [sorted(step) for step in offsets] == [[1], [2], [4]]


def test_pairwise_exponential_matches_consensus_offsets() -> None:
    program = _program("pairwise_exchange", "exponential")
    offsets = _offsets(program, n_agents=5)
    assert [sorted(step) for step in offsets][:3] == [[1], [2], [4]]


def test_exponential_offset_never_zero_on_power_of_two_agents() -> None:
    program = _program("consensus", "exponential")
    offsets = _offsets(program, n_agents=4)
    # n=4: rounds 1, 2 reach coverage; a third round would fold 4 % 4 -> 1.
    assert [sorted(step) for step in offsets] == [[1], [2]]
    for step in offsets:
        assert 0 not in step


def test_rotating_semantics_unchanged() -> None:
    # Compounding relayed knowledge reaches full information after offsets
    # 1, 2, 3 at n=5 — the pre-existing linear-offset law, untouched.
    program = _program("consensus", "rotating")
    offsets = _offsets(program, n_agents=5)
    assert [sorted(step) for step in offsets] == [[1], [2], [3]]
