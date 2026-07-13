# Restricted Phase Program Mode

`program_generate` is an independent QueenBee planner mode. It does not replace,
wrap, or silently fall back to the existing free-form `graph_generate` mode.

## Why it exists

Free GraphGen lets the architect describe explicit temporal edges (and still
accepts the older `topology_program_v1` expression language). That is useful for
open-ended search, but a small model can also produce legal-looking degenerate
programs. The restricted mode moves edge construction into a deterministic
compiler. The LLM chooses only typed collaboration phases and bounded enums.

## Source format

```json
{
  "format": "phase_program_v1",
  "information_goal": "all_agents",
  "selected_primary": 0,
  "state_retention": "keep",
  "allow_no_send": true,
  "submit_when": "coverage_complete",
  "phases": [
    {
      "kind": "gather",
      "hub": 0,
      "pattern": "tree",
      "send_mode": "delta_or_no_send",
      "instruction": "Merge source-tagged state without double counting."
    },
    {
      "kind": "broadcast",
      "hub": 0,
      "pattern": "tree",
      "send_mode": "delta_or_no_send",
      "instruction": "Retain the complete source-tagged state."
    }
  ]
}
```

Allowed phases are `gather`, `broadcast`, `pairwise_exchange`, and `consensus`.
The model cannot emit edge arrays, endpoint expressions, imports, or unbounded
loops. Unknown fields and enum values fail schema validation.

## Execution semantics

- Every step reads a snapshot of the previous round.
- Agents not receiving in a step retain their previous state.
- `delta_or_no_send` removes a transmission when the sender has no structurally
  new source information for that receiver. `full_state` keeps the transmission.
- Loop-like exchange phases have a finite `max_rounds` and may stop at sink or
  all-agent structural coverage.
- The compiler enforces step, message, receiver fan-in, agent-id, and coverage
  constraints before `ProtocolRunner` sees the schedule.
- Per-phase instructions compile into per-step receiver instructions.

## Repair loop

The planner runs a bounded counterexample-guided loop:

```text
generate -> compile -> validate -> minimal missing-source counterexample
         -> local repair -> compile again
```

There is no named-topology fallback. Exhausting the repair budget records
`program_generation_failed` and the run fails honestly. Artifacts are written to
`runs/programgen_artifacts/` (or `MASBENCH_PROGRAM_ARTIFACTS_DIR`) separately
from GraphGen artifacts.

## Evolution signal

Evolution keeps exact success for reporting, but trains on ordered dense stages:

1. executable validity;
2. minimum required structural coverage;
3. submission rate;
4. paper partial score `P`;
5. exact/paper success `S`.

The scalar bands are `[0,.2)`, `[.2,.4)`, `[.4,.9)`, and `[.9,1]`, so reaching a
later stage always beats remaining in an earlier one. Communication/token costs
remain separate tie-break metrics.

Skill cards persist the complete DSL source and compiled schedule in an
independent `phase_program_skill_v1` payload. `reasoning_policy` remains a
separately evolvable behavior section, with stage-level `failure_modes` and
bounded counterexamples in the common audit envelope. Program and free-graph
payloads cannot merge and replay is filtered by both provenance and planner
mode.

The verifier additionally supports:

- level-preserving curriculum growth (`--curriculum`): every requested level
  remains represented from round one, while the number of cases grows by round;
- per-skill paired ablation (`--skill-ablation-strict`): each proposed card is
  compared with measured alternatives on identical `(case, seed, n, goal)`
  pairs, and its wins/losses/ties are persisted in `confidence.paired_ablation`;
- a capability-floor control (`--capability-diagnostic`): one worker receives
  all ordered shards, separating base-model inability from communication loss.

The cold generated arm and evolved generated arm already provide the other two
diagnostic controls. The capability control is reported separately and never
participates in the competitive verdict.

## Commands

Run one offline smoke:

```bash
cd masbench
uv run python -m masbench.cli run \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case II-13 --n-agents 5 --planner \
  --planner-mode program_generate --silo-eval-mode all_agents --llm fake
```

Compare the independent generated modes and paper transports:

```bash
uv run python -m masbench.cli bench \
  --levels II III --agent-counts 5 --seeds 1 2 3 \
  --arms graphgen programgen p2p broadcast sfs \
  --silo-eval-mode all_agents --llm openai --model-name gpt-4o-mini \
  --out runs/programgen_comparison
```

Train/evaluate the restricted mode through the paired verifier:

```bash
uv run python scripts/verify_beats_baselines.py \
  --levels II III --evolved-mode program_generate --rounds 3 \
  --baselines graphgen p2p broadcast sfs \
  --curriculum --skill-ablation-strict --capability-diagnostic \
  --silo-eval-mode all_agents --model-name gpt-4o-mini
```

All before/candidate/deployed/final SkillBank snapshots remain under the
verifier run directory as usual.
