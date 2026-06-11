"""M10: train-time verified recipe search.

Round-08 screens: no org cleared the trust bar on the lone os anchor case
(chain 0/2, explore 1/1) -> correct abstention everywhere -> the bank can
never carry anything. M10 manufactures the anchor: propose (structure +
per-step instructions), execute on the TRAIN case, keep only what verifies
on 2 seeds, store as an immediately-trusted instruction-bearing skill.
"""

from __future__ import annotations

import json
from pathlib import Path

from exp_graph.llm.base import LLMResponse
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution
from masbench.recipes import (
    RECIPE_PROMPT,
    leaks_shard_literals,
    parse_recipe,
    recipe_skill_card,
    search_recipe,
)
from masbench.transfer import skill_trusted_for

DATA = Path(__file__).parent / "data"

GOOD_REPLY = json.dumps({
    "name": "segment_chain",
    "selected_primary": 1,
    "steps": [
        {"edges": [[0, 1]], "instruction": "compute your segment locally; forward your last raw element"},
    ],
})


class _Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.prompts = []

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.calls += 1
        text = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        return LLMResponse(text=text, usage={})


def test_parse_recipe_validates_and_carries_instructions():
    spec = parse_recipe(GOOD_REPLY, n_agents=2, max_steps=4)
    assert spec is not None
    assert spec.steps[0].instruction.startswith("compute your segment")
    assert spec.metadata["selected_primary"] == 1
    assert parse_recipe("junk", n_agents=2, max_steps=4) is None
    bad_edges = json.dumps({"name": "x", "steps": [{"edges": [[0, 0]], "instruction": "i"}]})
    assert parse_recipe(bad_edges, n_agents=2, max_steps=4) is None


def test_leakage_scan_blocks_shard_literals():
    spec = parse_recipe(json.dumps({
        "name": "leaky", "selected_primary": 1,
        "steps": [{"edges": [[0, 1]], "instruction": "forward the value 12345 to your neighbor"}],
    }), n_agents=2, max_steps=4)
    assert leaks_shard_literals(spec, [[12345, 7], [3]]) is True
    assert leaks_shard_literals(spec, [[1, 7], [3]]) is False


def test_search_verifies_on_both_seeds_and_uses_feedback():
    client = _Scripted([GOOD_REPLY])
    scores = {"calls": []}

    def run_and_score(spec, seed):
        scores["calls"].append(seed)
        return 1.0, {"wrong_agents": "0 of 2"}

    spec, trace = search_recipe(
        task_brief="count adjacent pairs across boundaries",
        n_agents=2, max_steps=4, shards=[[1], [2]],
        llm_client=client, model_name="m",
        run_and_score=run_and_score, verify_seeds=[1, 7920],
    )
    assert spec is not None and trace[-1]["status"] == "verified"
    assert scores["calls"] == [1, 7920], "both verify seeds must run"


def test_search_feeds_failure_back_and_can_give_up():
    client = _Scripted([GOOD_REPLY, GOOD_REPLY])

    def always_fail(spec, seed):
        return 0.0, {"wrong_agents": "2 of 2", "holder_state": "wrong"}

    spec, trace = search_recipe(
        task_brief="t", n_agents=2, max_steps=4, shards=[[1], [2]],
        llm_client=client, model_name="m",
        run_and_score=always_fail, verify_seeds=[1, 2], attempts=2,
    )
    assert spec is None
    assert len(trace) == 2 and all(t["status"] == "failed_seed0" for t in trace)
    assert "FAILED verification" in client.prompts[1]


def test_recipe_prompt_is_benchmark_agnostic():
    lowered = RECIPE_PROMPT.lower()
    for marker in ("silo", "agent ordering:", "communication protocol", "leetcode"):
        assert marker not in lowered


def test_recipe_card_is_immediately_trusted():
    spec = parse_recipe(GOOD_REPLY, n_agents=2, max_steps=4)
    card = recipe_skill_card(
        spec, task_family="silo", bucket="os", lossless_slot="lossless",
        n_agents=2, verify_count=2,
    )
    assert skill_trusted_for(card, "os", "lossless") is True
    assert card.organization_policy["protocol_spec"]["steps"][0]["instruction"]


def test_run_evolution_recipe_phase_offline_off_by_default_path():
    """Offline (fake) the recipe phase consumes no runs when budget=0 and the
    summary stays well-formed; with budget>0 + fake LLM the search records
    unparseable attempts without crashing (fake client emits CF-shaped text)."""
    cfg_off = RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="select_then_refine",
        num_graph_candidates=2, n_agents=2, recipe_search_budget=0,
    )
    s = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "ORD-50"], agent_counts=[2],
        train_seeds=[1, 2], val_seeds=[3], cfg=cfg_off, levels=["I", "ORD"],
    )
    assert s["n_recipe_runs"] == 0 and s["recipe_traces"] == []
