import json

import pytest

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

from scripts.verify_beats_baselines import (
    _resolve_case_split,
    _save_skill_bank_snapshot,
    _verdict,
)


def test_save_skill_bank_snapshot_writes_json_yaml_and_metadata(tmp_path) -> None:
    skill = SkillCard(
        skill_id="generated_demo",
        task_family="silo",
        objective="accuracy_first",
        organization_policy={"topology_name": "generated:demo"},
    )

    entry = _save_skill_bank_snapshot(
        tmp_path,
        relative_name="round_01/candidate",
        skills=[skill.model_dump(mode="json")],
        metadata={"round": 1, "stage": "candidate"},
    )

    snapshot = tmp_path / "round_01" / "candidate"
    payload = json.loads((snapshot / "bank.json").read_text())
    metadata = json.loads((snapshot / "metadata.json").read_text())
    loaded = SkillBank.load_dir(snapshot / "skills")

    assert entry["n_skills"] == 1
    assert payload["skill_ids"] == ["generated_demo"]
    assert metadata == {"round": 1, "stage": "candidate"}
    assert loaded.get("generated_demo") is not None


def test_verdict_can_limit_the_paid_baseline_set() -> None:
    pairs = [
        {"evolved": 1.0, "graphgen": 0.0, "fixed": 1.0},
        {"evolved": 1.0, "graphgen": 0.0, "fixed": 0.0},
    ]

    verdict = _verdict(
        pairs,
        delta_min=0.05,
        win_margin=1,
        baselines=("graphgen", "fixed"),
    )

    assert set(verdict["per_baseline"]) == {"graphgen", "fixed"}
    assert set(verdict["arm_means"]) == {"evolved", "graphgen", "fixed"}


def test_resolve_case_split_supports_cross_level_holdout() -> None:
    train, test, mode = _resolve_case_split(
        ["I-01", "I-02", "II-11", "III-22"],
        holdout_frac=0.5,
        train_cases=["I-01", "I-02"],
        test_cases=["II-11", "III-22"],
    )

    assert train == ["I-01", "I-02"]
    assert test == ["II-11", "III-22"]
    assert mode == "explicit"


@pytest.mark.parametrize(
    ("train_cases", "test_cases", "match"),
    [
        (["I-01"], None, "must be provided together"),
        (["I-01"], ["I-01"], "overlap"),
        (["I-01"], ["III-99"], "unavailable"),
    ],
)
def test_resolve_case_split_rejects_invalid_explicit_splits(
    train_cases, test_cases, match,
) -> None:
    with pytest.raises(ValueError, match=match):
        _resolve_case_split(
            ["I-01", "II-11"],
            holdout_frac=0.5,
            train_cases=train_cases,
            test_cases=test_cases,
        )
