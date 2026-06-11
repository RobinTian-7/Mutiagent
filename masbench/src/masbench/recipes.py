"""M10: train-time VERIFIED recipe search (Reflexion/STaR-style).

The minister only distills one-shot runs; on hard train cases nothing
succeeds often enough to clear the trust bar (round-08 screens: II-13 had
chain 0/2, explore 1/1 -- correct abstention everywhere downstream, so the
bank can never carry anything). Train-time, the benchmark adapter exposes
the training signal (its scoring against the train case's expected output);
iterating proposals against it is ordinary learning. The stored artifact is
a PROCEDURE -- structure + per-step receiver instructions (M9 fields) -- and
never data values.

Generalizability contract (operator requirement): inputs are the task
STATEMENT, procedural feedback (per-step structure + which agents were
wrong), and the run's own LLM. Prompts contain no benchmark-specific
markers (tested). A leakage scan rejects recipes whose instructions embed
train-shard literals.

Borrowings: Reflexion (verbal feedback retry), STaR (keep only verified
traces), AWM (workflow induction), Voyager (skill = executable + use note).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from exp_graph.llm.base import LLMClient
from exp_graph.mas.schemas import SkillCard
from exp_graph.protocols.spec import ProtocolGraphSpec, ProtocolStepSpec

RECIPE_PROMPT = """You are designing a communication + computation procedure for {n_agents} agents that each privately hold one shard of the data. Design BOTH the message structure and what each step's receivers must do.

Task statement (placeholders like {{agent_id}}/{{input_shard}} stand for per-agent values):
---
{task_brief}
---
{feedback_block}
Constraints:
- At most {max_steps} steps; each step is a set of simultaneous src->dst messages; agent ids 0..{last_agent}; no self-loops.
- Every agent's information must be able to reach whoever produces the final answer.
- Per-step "instruction" tells the RECEIVING agents what to COMPUTE locally and what to FORWARD next (<= 200 chars; never include concrete data values).
- "selected_primary" = the agent id that holds the final answer; its last instruction must say how to ASSEMBLE the final answer (and every agent must end up submitting that same answer if the task asks for one shared answer).

Reply ONLY JSON:
{{"name": "short_snake_case", "selected_primary": <id>, "steps": [{{"edges": [[src,dst],...], "instruction": "..."}}, ...]}}"""

FEEDBACK_TEMPLATE = """Previous attempt '{name}' FAILED verification. Procedural feedback:
- structure tried: {structure}
- agents with wrong final answers: {wrong_agents}
- the designated answer-holder was {holder_state}.
Fix the PROCEDURE (different structure and/or clearer per-step computation roles), do not just reword.
"""


def parse_recipe(
    text: str, *, n_agents: int, max_steps: int
) -> ProtocolGraphSpec | None:
    """Parse one recipe reply into an instruction-bearing spec (None on junk)."""
    raw = (text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        steps_raw = data.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            return None
        steps = []
        for item in steps_raw[:max_steps]:
            edges = [
                (int(s), int(d))
                for s, d in (item.get("edges") or [])
                if 0 <= int(s) < n_agents and 0 <= int(d) < n_agents and int(s) != int(d)
            ]
            if not edges:
                return None
            steps.append(
                ProtocolStepSpec(
                    transmissions=edges,
                    description=str(item.get("instruction", ""))[:120],
                    operator="recipe",
                    instruction=str(item.get("instruction", "")).strip()[:300] or None,
                )
            )
        selected = data.get("selected_primary")
        metadata = {
            "graph_type": "temporal_dag",
            "source": "recipe_search",
        }
        if selected is not None and 0 <= int(selected) < n_agents:
            metadata["selected_primary"] = int(selected)
        return ProtocolGraphSpec(
            name=str(data.get("name") or "recipe")[:60],
            n_agents=n_agents,
            steps=steps,
            metadata=metadata,
        )
    except Exception:
        return None


def leaks_shard_literals(spec: ProtocolGraphSpec, shards: list[Any]) -> bool:
    """True when any instruction embeds a concrete shard value (>=3 chars)."""
    blob = " ".join(
        (step.instruction or "") + " " + step.description for step in spec.steps
    ).lower()
    for shard in shards:
        items = shard if isinstance(shard, (list, tuple)) else [shard]
        for value in items:
            text = str(value).strip().lower()
            if len(text) >= 3 and text in blob:
                return True
    return False


def search_recipe(
    *,
    task_brief: str,
    n_agents: int,
    max_steps: int,
    shards: list[Any],
    llm_client: LLMClient,
    model_name: str,
    run_and_score: Callable[[ProtocolGraphSpec, int], tuple[float, dict[str, Any]]],
    verify_seeds: list[int],
    attempts: int = 4,
) -> tuple[ProtocolGraphSpec | None, list[dict[str, Any]]]:
    """Iterate propose -> execute -> verify; return (verified spec, trace).

    ``run_and_score(spec, seed)`` returns (exact_match_rate, procedural
    feedback dict with keys like wrong_agents/holder_state). A recipe is
    VERIFIED only when every verify seed passes (>= 0.99) -- one lucky run
    never deploys (M1 bar). The trace records every attempt for diagnostics.
    """
    feedback_block = ""
    trace: list[dict[str, Any]] = []
    last_agent = n_agents - 1
    for attempt in range(1, max(1, attempts) + 1):
        prompt = RECIPE_PROMPT.format(
            n_agents=n_agents, task_brief=task_brief[:1800],
            feedback_block=feedback_block, max_steps=max_steps,
            last_agent=last_agent,
        )
        try:
            response = llm_client.complete(prompt, model_name=model_name, temperature=0.4)
            spec = parse_recipe(
                getattr(response, "text", "") or "", n_agents=n_agents, max_steps=max_steps
            )
        except Exception:
            spec = None
        if spec is None:
            trace.append({"attempt": attempt, "status": "unparseable"})
            feedback_block = "\nYour previous reply was not valid JSON in the required shape. Follow the schema exactly.\n"
            continue
        if leaks_shard_literals(spec, shards):
            trace.append({"attempt": attempt, "status": "leaked_data", "name": spec.name})
            feedback_block = "\nYour previous attempt embedded concrete data values in instructions. Describe PROCEDURE only.\n"
            continue
        em, feedback = run_and_score(spec, verify_seeds[0])
        if em < 0.99:
            structure = "; ".join(
                f"{i}:" + ",".join(f"{s}->{d}" for s, d in st.transmissions)
                for i, st in enumerate(spec.steps)
            )
            feedback_block = "\n" + FEEDBACK_TEMPLATE.format(
                name=spec.name, structure=structure,
                wrong_agents=feedback.get("wrong_agents", "unknown"),
                holder_state=feedback.get("holder_state", "unknown"),
            )
            trace.append({"attempt": attempt, "status": "failed_seed0", "name": spec.name, "em": em})
            continue
        # Seed-0 solved: confirm on the remaining verify seeds (trust bar n>=2).
        confirmations = [(em, feedback)]
        ok = True
        for seed in verify_seeds[1:]:
            em2, fb2 = run_and_score(spec, seed)
            confirmations.append((em2, fb2))
            if em2 < 0.99:
                ok = False
                break
        trace.append({
            "attempt": attempt, "status": "verified" if ok else "unstable",
            "name": spec.name, "ems": [round(e, 3) for e, _ in confirmations],
        })
        if ok:
            return spec, trace
        feedback_block = "\n" + FEEDBACK_TEMPLATE.format(
            name=spec.name, structure="(same as before)",
            wrong_agents=confirmations[-1][1].get("wrong_agents", "unknown"),
            holder_state="answer unstable across runs -- make per-step roles more explicit",
        )
    return None, trace


def recipe_skill_card(
    spec: ProtocolGraphSpec,
    *,
    task_family: str,
    bucket: str,
    lossless_slot: str,
    n_agents: int,
    verify_count: int,
) -> SkillCard:
    """Wrap a verified recipe as a deployable, immediately-trusted skill."""
    topology = f"generated:{spec.name}"
    ledger_rows = {"n": verify_count, "em_sum": float(verify_count)}
    return SkillCard(
        skill_id=f"{task_family}__recipe_{spec.name}__a{n_agents}",
        objective="balanced",
        task_family=task_family,
        trigger={"task_family": task_family, "min_agents": 1, "max_agents": 999},
        organization_policy={
            "planner_mode": "graph_generate",
            "topology_name": topology,
            "protocol_spec": spec.model_dump(mode="json"),
            "transfer_evidence": {
                bucket: dict(ledger_rows),
                f"{bucket}#{lossless_slot}": dict(ledger_rows),
            },
            "recipe_provenance": {
                "verified_seeds": verify_count,
                "source": "m10_recipe_search",
            },
        },
        expected_tradeoff={
            "mean_primary_loss": 0.0,
            "mean_rmse": 0.0,
            "active_evidence_count": verify_count,
            "lesson": "verified procedure from train-time recipe search",
        },
        confidence={"seed_count": verify_count},
        tags=["mas", "emperor-skill", task_family, "recipe"],
    )
