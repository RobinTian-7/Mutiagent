"""CF phase vocabulary: compilation, validation, and information flow."""

import pytest

from exp_graph.protocols.schedules import build_protocol_schedule
from exp_graph.sft_lineage.cf_cases import (
    build_case_bank,
    parse_tier_specs,
    split_case_bank,
    task_view,
)
from exp_graph.sft_lineage.cf_structures import (
    SEED_STRUCTURES,
    compile_cf_program,
    fake_design,
    seed_program,
    simulate_information_flow,
    validate_cf_design,
)


@pytest.mark.parametrize("name", sorted(SEED_STRUCTURES))
@pytest.mark.parametrize("n_agents", [2, 5, 8])
def test_seed_structures_compile_and_reach_sink(name: str, n_agents: int):
    program = seed_program(name, n_agents=n_agents, information_goal="sink")
    spec = compile_cf_program(program, n_agents=n_agents)
    assert spec.metadata["selected_primary"] == n_agents - 1
    knowledge = simulate_information_flow(
        [list(step.transmissions) for step in spec.steps], n_agents
    )
    assert knowledge[n_agents - 1] == set(range(n_agents))


def test_one_peer_star_sink_matches_named_schedule():
    """The seed compiles to the same steps as one_peer_exponential_dag_star."""

    n_agents = 8
    program = seed_program(
        "one_peer_star_sink", n_agents=n_agents, information_goal="sink"
    )
    spec = compile_cf_program(program, n_agents=n_agents)
    named = build_protocol_schedule("one_peer_exponential_dag_star", n_agents)
    assert [
        sorted(step.transmissions) for step in spec.steps
    ] == [sorted(step.transmissions) for step in named]


def test_validate_rejects_designs_that_starve_the_sink():
    with pytest.raises(ValueError, match="sink agent"):
        validate_cf_design(
            [
                {
                    "kind": "premix",
                    "pattern": "one_peer_exponential",
                    "max_rounds": 1,
                }
            ],
            information_goal="sink",
            n_agents=8,
        )


def test_validate_rejects_vocabulary_violations():
    with pytest.raises(ValueError, match="1..6 phases"):
        validate_cf_design([], information_goal="sink", n_agents=4)
    with pytest.raises(ValueError, match="unknown phase kind"):
        validate_cf_design(
            [{"kind": "broadcast", "pattern": "star"}],
            information_goal="sink",
            n_agents=4,
        )
    with pytest.raises(ValueError, match="unknown gather pattern"):
        validate_cf_design(
            [{"kind": "gather", "pattern": "mesh"}],
            information_goal="sink",
            n_agents=4,
        )
    with pytest.raises(ValueError, match="max_rounds"):
        validate_cf_design(
            [
                {"kind": "premix", "pattern": "ring", "max_rounds": 99},
                {"kind": "gather", "pattern": "star"},
            ],
            information_goal="sink",
            n_agents=4,
        )


def test_validate_all_agents_goal_requires_full_coverage():
    with pytest.raises(ValueError, match="all_agents"):
        validate_cf_design(
            [{"kind": "gather", "pattern": "star"}],
            information_goal="all_agents",
            n_agents=4,
        )
    program = validate_cf_design(
        [
            {
                "kind": "premix",
                "pattern": "static_exponential",
                "max_rounds": 2,
            }
        ],
        information_goal="all_agents",
        n_agents=4,
    )
    spec = compile_cf_program(program, n_agents=4)
    assert "selected_primary" not in spec.metadata


def test_fake_designs_are_valid_and_alternate():
    even = validate_cf_design(
        fake_design(0, 5), information_goal="sink", n_agents=5
    )
    odd = validate_cf_design(
        fake_design(1, 5), information_goal="sink", n_agents=5
    )
    assert even["phases"] != odd["phases"]


def test_case_bank_tiers_and_split_are_deterministic():
    bank = build_case_bank(cases_per_tier=3)
    assert list(bank) == [
        "I-cf00", "I-cf01", "I-cf02",
        "II-cf00", "II-cf01", "II-cf02",
        "III-cf00", "III-cf01", "III-cf02",
    ]
    train, test = split_case_bank(bank, test_count=3)
    assert len(test) == 3
    assert not set(train) & set(test)
    assert {case.split("-")[0] for case in test} == {"I", "II", "III"}
    again_train, again_test = split_case_bank(
        build_case_bank(cases_per_tier=3), test_count=3
    )
    assert (again_train, again_test) == (train, test)


def test_case_content_differs_by_case_and_seed():
    bank = build_case_bank(cases_per_tier=2)
    case_a, case_b = bank["I-cf00"], bank["I-cf01"]
    assert case_a.task_kwargs(7)["seed"] != case_b.task_kwargs(7)["seed"]
    assert case_a.task_kwargs(7)["seed"] != case_a.task_kwargs(8)["seed"]


def test_tier_spec_override_and_task_view_are_answer_free():
    specs = parse_tier_specs('{"I": [60, 1, 6]}')
    bank = build_case_bank(cases_per_tier=2, tier_specs=specs)
    case = bank["I-cf00"]
    assert case.array_size == 60
    view = task_view(case, n_agents=5, goal="sink")
    assert view["tier"] == "I"
    assert "agent 4" in view["task_statement"]
    assert "answer" not in view["task_statement"].lower() or "table" in view[
        "task_statement"
    ]
    with pytest.raises(ValueError):
        parse_tier_specs('{"I": [60, 1]}')
