# M9 design: instruction-carrying replay (structure transfers, behavior adapts)

Status: designed 2026-06-11 while dev-5 runs; source edits deferred until the
driver finishes (no mid-driver code changes). Borrowings: SkillLens
(arXiv:2605.08386) REWRITE route; AWM workflow adaptation; the operator brief
explicitly scopes "架构师的提示模板".

## Problem (dev-4 datum)

Replay is verbatim: a spec earned on II-13 carries II-13-flavored step
descriptions, and step descriptions are LOGGING-ONLY anyway — agents never
see any per-step role guidance. On capability-floor tasks (II-17 diff array)
the failing unit is the per-agent computation: a sink receiving 40 raw
elements cannot compute the full answer reliably, while a chain where each
agent computes its OWN 8-element segment (given one boundary value) and the
sink concatenates is well within model capability. No current mechanism can
express "each agent does this small local step".

## Change set (all opt-in; CF byte-identical by default)

1. `exp_graph.protocols.spec.ProtocolStepSpec.instruction: str | None = None`
   (new optional field; CF specs never set it).
2. `CommunicationStep` carries `instruction` through schedule compile
   (`spec.py` compile path only; `build_protocol_schedule` named topologies
   leave it None).
3. `ProtocolRunner._merge_receiver_belief_with_llm`: when
   `config.enable_step_instructions` AND `step.instruction` is non-empty,
   prepend to the merge prompt:
   "Step role for you this round: <instruction>\n\n" + prompt.
   New `ProtocolRunnerConfig.enable_step_instructions: bool = False`.
4. Generation side (`graph_generation._generate_graph_candidates`): when
   `runtime.replay_instruction_rewrite` is on and a real client + task_brief
   exist, ONE LLM call per seeded replay candidate produces a JSON list of
   per-step instructions (same length as steps; receiver-oriented,
   <=200 chars each) from (task brief, structure summary). Parse failure ->
   candidate keeps None instructions (do no harm). Fresh (non-seeded)
   candidates may also receive instructions from their own generation later;
   out of scope for the first cut.
5. masbench: `RunConfig.replay_rewrite: bool = True` (env
   MASBENCH_REPLAY_REWRITE=0 ablation) threads to runtime + runner config.
   Cost: +<=3 LLM calls per deployment run, +1 prompt line per merge call.

## Prompt template (generation side)

  You proved this communication structure works for a related task. Adapt it
  to THIS task by writing one short instruction for the RECEIVING agents of
  each step.
  Task: <task_brief>
  Structure: steps as "k: src->dst, ..." lines.
  Reply ONLY JSON: {"instructions": ["...", ...]} with exactly N entries.
  Each instruction tells receivers what to COMPUTE locally this step and
  what to FORWARD next (keep raw data lossless when needed).

## Tests (TDD order)

1. Spec round-trip: instruction survives model_dump/validate; absent -> None.
2. Compile: spec with instructions -> schedule steps carry them; named
   topologies -> None. CF suites untouched (field default).
3. Runner injection: fake client captures prompt; with flag+instruction the
   prompt starts with the role line; flag off OR instruction None ->
   byte-identical prompt (assert equality against pre-change golden).
4. Rewrite call: scripted client returns instruction JSON -> candidate steps
   carry them; junk reply -> None (candidate unchanged).
5. Wiring: masbench cfg flag threads to runner config + runtime knob.

## Decision experiment (after dev-5 completes)

Cheap screen first (per dev loop): single-round verify_evolve.sh-style run
or a direct probe on the dev-4 floor split (TRAIN {I-01..06,II-13} TEST
{II-17,II-18,II-20}): does instruction-carrying replay produce ANY wins on
floors (cold=0 there, so any success = pure win, 2+ wins/round would pass
the stable criteria)? Yes -> rerun stable judge; no -> the boundary report
gains its final pillar ("even adapted-instruction replay cannot beat
capability floors").
