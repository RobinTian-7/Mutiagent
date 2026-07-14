# Independent PythonGen Planner

`python_generate` is an additive fifth planner mode. It does not replace or
route through either existing generated-structure mode:

| Mode | Architect output | Execution |
|---|---|---|
| `graph_generate` | free temporal graph / `topology_program_v1` | `ProtocolRunner` |
| `program_generate` | restricted `phase_program_v1` stages | deterministic compiler, then `ProtocolRunner` |
| `python_generate` | complete constrained `program.py` | Python-only validated child process |

The corresponding non-default bench arm is `pycodegen`.

## Execution Flow

1. The architect sees only a sanitized task description, Agent count,
   information goal, budgets, and the Python contract. It never sees shards,
   local prompts, case ids, expected outputs, scores, or prior run results.
2. The architect is instructed through a text-framed contract to return raw,
   complete Python source. The host normalizes a single Python Markdown fence
   or a strict JSON string field (`source_code`, `python_source`, `code`, or
   `main`) because smaller models sometimes mirror the JSON input contract.
   Structured `main` objects and ambiguous/double-escaped source are not guessed.
3. The host runs `ast.parse`, policy checks, API checks, finite taint analysis,
   and `compile`.
4. A fake dry run injects a distinct canary into every local prompt.
5. Valid source runs in a child process. The process-local wrapper patches only
   the existing `create_llm_client` factory in that child, authorizes the host
   provider/model settings, and meters every `complete`/`complete_batch` call.
6. The host validates the sole stdout JSON object against a strict schema and
   compares its usage with the authoritative wrapper ledger.
7. On a sanitized error, the architect may return a complete `replace_code`
   source up to `python_repair_attempts` times. Exhaustion produces an honest
   `python_generation_failed`; there is no named, graph, program, or paper
   protocol fallback.

The original model response is retained as
`architect_response.raw.txt`/`repair_response_NN.raw.txt`, while only the
extracted source is written to `attempt_NN.py`, validated, executed, and later
stored in `python_skill_v1`. `response_normalization_trace.json` records the
detected format and raw/source hashes. Normalization does not bypass any AST,
policy, data-flow, dry-run, or subprocess validation.

## Architect Scaffold

Both the initial architect prompt and every repair prompt include the complete,
known-valid `python_mas_scaffold_v1` program. The model fills or revises only
three marked regions:

- `worker_instruction`: the Worker action contract and task-solving guidance;
- `fallback_routing`: who sends new Worker-produced information to whom;
- `submission_policy`: when an Agent is ready to submit its own answer.

The prompt asks the model to return the entire Python file, not a fragment. If
it has no safe specialization, it may return the scaffold unchanged. This gives
small architect models a valid output path while preserving the independent
`python_generate` search space: the scaffold is not a PhaseProgram compilation
and does not route through GraphGen.

The editable-region rule is prompt guidance, not a trusted security boundary.
The host therefore normalizes and validates the complete returned source using
the same AST policy, data-flow checks, fake dry run, subprocess limits, output
schema, and usage-ledger comparison as any freely generated Python program.

The generated code calls the repository API directly. No `ctx.send`,
`ctx.next_round`, or other model-orchestration DSL is exposed.

### Parent-aware hot-start innovation

Normal `python_generate` remains a clean, context-blind generation path. The
hot-start evolution path adds an independent
`--python-innovation-strategy` switch:

| value | paid branches per `(case, seed)` | behavior |
| --- | --- | --- |
| `fresh` | reuse + innovation | generate a complete marked scaffold from sanitized parent lessons |
| `mutate` | reuse + mutate | patch one existing Python parent `EVOLVE-BLOCK` |
| `mutate_and_fresh` | reuse + mutate + innovation | measure both local improvement and independent expansion |

The default is `mutate_and_fresh`, but it is inert unless hot-start dual-branch
Python innovation is enabled. If no same-contract validated Python parent with
editable blocks exists, mutation is recorded as `skipped_with_reason`; it is
not scored as a failed run, and the fresh branch still executes.

The parent context is an allowlist containing only `parent_skill_id`,
`reasoning_policy`, `design_insights`, answer-free failure/counterexample
summaries, aggregate V/K/U/P/S/stage metrics, and C/D/token/message costs. It
has a hard size cap. Answers, expected outputs, ground truth, task/private
prompts, shards, executable payloads, and full parent source are removed. Once
this context is exposed, the run records `clean_pythongen=false`.

Mutation uses `python_mutation_patch_v1`, not complete-source replacement. The
model receives only the bodies of existing `EVOLVE-BLOCK` regions and returns
one `block_id`, its replacement, the exact parent SHA-256, and any explicitly
used exposed insight ids. The host verifies the hash, block whitelist, marker
set, unchanged non-selected blocks, and insight ids before applying the patch.
The resulting complete source then passes the normal AST, dry-run, sandbox,
real execution, stdout, and usage-ledger checks. The Skill stores the final
source plus parent id, strategy, used/exposed insight ids, parent/result hashes,
per-patch diff hashes, and mutation provenance.

A strict gate may reject the first fresh Python candidate when a warm fixed
Skill is already better. In that case no unaccepted Python source enters the
deployed bank, so the following round truthfully skips mutation again. To study
mutation itself, start from a separately validated same-contract Python seed or
use a curriculum where a fresh Python program can first clear the gate; never
promote the rejected source merely to make the branch run.

The message-only contracts use separate scaffolds. `message_only_v1` retains
its existing `submission_policy` and `routing_policy` blocks.
`message_only_v2` exposes only `schedule_policy` (one global barrier round) and
`routing_policy` (communication before that barrier). Its canonical Worker
prompts, answer parser, state/provenance machinery, submitter set, barrier and
stdout schema are not editable regions.

## Runtime Semantics

The validated program maintains one state and inbox per Agent. Every active
Agent in round `r` acts once from the same previous-round snapshot. State is
copy-then-update, so omitted fields persist. A Worker may set
`should_send=false`. Messages created in round `r` are visible only in round
`r+1`; the host compares the inbox envelope in every Worker prompt against the
reported delivery ledger. Once an Agent submits, later calls and sends from that
Agent are rejected.

Worker actions use these fields:

```json
{
  "state": {},
  "should_send": false,
  "recipients": [],
  "message": null,
  "source_ids": [],
  "submit": false,
  "answer": null
}
```

Invalid recipient ids, forged source provenance, duplicate provenance, parse
errors, and budget overruns fail closed.

Agent calls from the same logical round may run concurrently. The generated
program hands the complete round batch to the trusted client wrapper; the host
caps it with `max_parallel_agents`, performs the provider calls concurrently,
and commits responses in deterministic Agent order. The next round does not
start until the entire batch finishes, so parallelism changes wall time rather
than topology or message visibility. Experiment-grid concurrency (`--workers`)
is separate and multiplies with this intra-task limit.

## Data Boundary

The stdin model is `extra="forbid"`. It permits only the documented
`python_mas_v1` fields. An accidental `ground_truth`, scoring field, SkillBank,
or other private field is rejected before the child starts. API key values are
never serialized; only the authorized environment variable name is present.

Static taint analysis proves properties only for the accepted AST subset:

- `action_json_v1` and `message_only_v1` consume only
  `agents[agent_id]["local_prompt"]`; `message_only_v2` instead consumes the
  distinct `communication_prompt` and `submit_prompt` fields;
- the agents container cannot be aliased or iterated;
- another Agent index, mixed/multiple private prompts, prompt
  parsing/transforms, and flows into state/message/answer/stdout are rejected;
- the tainted prompt may cross the declassification boundary only through
  `client.complete` or the narrowly validated same-round
  `client.complete_batch` staging path on the authorized client;
- imports, files, environment/system introspection, reflection, dynamic code,
  recursion, `while`, unbounded iteration, monkey patching, threads, processes,
  sockets, and alternate HTTP clients are rejected.

Dynamic checks complement, rather than expand, that proof:

- fake canaries detect a local prompt routed to the wrong Agent and any canary
  reaching stdout;
- canonical Agent/round/state/inbox headers let the host verify active-call and
  delayed-delivery semantics;
- actual Worker usage, calls, prompt hashes, and sanitized inbox envelopes come
  from the child wrapper, not generated self-reporting.

## Process Isolation

The child has a temporary working directory and a minimal environment. On POSIX,
CPU, address-space, file-descriptor, and file-size limits are requested;
wall-clock timeout and a byte-counting stdout wrapper are always enforced.
The Python wall-clock timeout no longer defaults to a fixed 30 seconds. For the
parallel `message_only_v2` scaffold, with no explicit
`--python-execution-timeout`, masbench derives it as
`max_rounds * ceil(n_agents / max_parallel_agents) * request_timeout + 30s`,
with a 120-second floor. For example, n=5, four rounds, five-way Agent
parallelism, and a 120-second request timeout produce a 510-second child budget.
Legacy scalar-call contracts conservatively use one Agent per wave. An explicit
positive timeout still overrides the derived value for a preregistered run.
`RLIMIT_AS` and `RLIMIT_FSIZE` behavior varies by platform, so
`execution_report.json` records that caveat. This is a constrained execution
boundary, not a claim of kernel/container isolation. For hostile rather than
model-generated code, run the child inside an OS sandbox or container as well.

### Budget sizing for real runs

Do not use a 30-second whole-program timeout for multi-Agent execution. Size the
limits from the planned schedule, then leave explicit headroom. With five Agents,
four total rounds, and a final `message_only_v2` submission barrier, three
all-to-all communication rounds can deliver at most
`5 * (5 - 1) * 3 = 60` messages. A conservative real-run envelope is:

```text
python_max_messages          = 512
python_max_model_calls       = 128
python_max_completion_tokens = 50000
request_timeout              = 300 seconds
llm_timeout_attempts         = 5
max_parallel_agents          = 5
python_execution_timeout     = auto (1230 seconds for this schedule)
```

These are ceilings, not targets: normal execution stops as soon as its planned
rounds and synchronized submissions finish. The report records actual messages,
calls, tokens, batch width, and resolved timeout so unused headroom cannot be
mistaken for incurred cost. Experiment-grid concurrency is independent; for this
shape, `--workers 2 --max-parallel-agents 5` permits at most ten simultaneous
provider requests. Add `--require-complete-runs` when an infrastructure failure
must stop at the previous checkpoint instead of reducing the requested sample.

## Scoring And Evolution

Python runs use the same staged evolution ordering as the existing work:

- `V`: static validation, compile, dry run, real execution, output, and ledger
  checks all pass;
- `K`: host reconstruction from validated `(round, src, dst, source_ids)` events;
- `U`: actual valid submission rate;
- `P`: existing SILO partial scorer;
- `S`: existing sink or all-Agents scorer;
- `C/D`: existing paper token-per-round and communication-density definitions,
  reported separately from the staged loss.

Python SkillCards use `planner_mode=python_generate` and
`provenance=llm_generated_python`. Their canonical `python_skill_v1`
`mode_payload` stores the complete Python `source_code` verbatim, a verified
SHA-256, policy and contract versions, repair count, and runtime trace summary;
the Worker reasoning policy remains a separately evolvable section.
`organization_policy` mirrors these values only for legacy readers. Clean
retrieval admits only validated same-mode Python skills. GraphGen,
ProgramGen, fixed, fake, missing-provenance, and Python cards are mutually
isolated as appropriate. Validation failures become non-selectable
`counterexample` cards. Paired ablation identifies Python candidates by
`program_sha256`, not the shared display name `python:generated`.

## Worker Contracts

PythonGen supports three worker output contracts, selected by
`--python-worker-contract` (config `python_worker_contract`, default
`action_json_v1`). They are separate archives end to end: scaffolds,
validation headers, wrapper semantics, SkillBank retrieval/replay, cache
keys and audit records never cross.

### action_json_v1 (legacy default)

The worker LLM answers every call with one action JSON
(`state, should_send, recipients, message, source_ids, submit, answer`).
The generated program executes those actions; the wrapper and host
cross-check them against the ledger. Nothing about this mode changed.

### message_only_v1

Responsibilities are split three ways:

| Concern | Owner |
| --- | --- |
| Rounds, control flow, `recipients`, send/submit decisions | Planner source (`plan_turn`) |
| Per-agent `previous_output` memory, inbox construction, one-round delivery delay, `source_ids` merging, budgets | Runtime (scaffold loops + bootstrap wrapper) |
| Message body text, final answer text | Worker LLM |

`plan_turn` returns one control object per agent per round:
`{"mode": "send"|"reflect"|"submit"|"idle", "recipients": [...]}` —
`recipients` must be empty unless mode is `send`. Semantics: `send` calls the
worker, stores its text as the new `previous_output` and sends it as the
message body; `reflect` calls the worker and only updates memory; `submit`
calls the worker and records its raw text as the agent's final answer;
`idle` makes no call, sends nothing, and memory persists. `plan_turn` may
read only public runtime metadata (round, agent id, counts, budgets), never
message bodies or local prompts.

State: the runtime keeps `previous_output` plus this round's delivered inbox
plus the agent's local prompt — no unbounded history. Worker prompts instruct
a compact, self-contained rolling summary. `source_ids` are authored by the
runtime alone: initialized to `{agent_id}`, merged on delivery (including
deliveries during idle rounds), stamped onto outgoing envelopes, and workers
or generated code cannot forge them — the bootstrap wrapper simulates
delivery independently and any divergence (inbox, known ids, previous
output, canonical prompt bytes) fails closed. `source_ids` remain
conservative provenance: what the sender had been exposed to at send time,
not a claim that every source shaped every sentence.

Workers run in text mode (`json_mode=False`) with a canonical prompt
(`PYTHON_WORKER_CONTRACT / PYTHON_AGENT_ID / PYTHON_ROUND /
PYTHON_CONTROL_JSON / KNOWN_SOURCE_IDS_JSON / PREVIOUS_OUTPUT_JSON /
DELIVERED_INBOX_JSON / INSTRUCTION / LOCAL_PROMPT`). The instruction
constants are a security boundary and are byte-verified — the editable
EVOLVE-BLOCK regions are only `submission_policy` and `routing_policy`
inside `plan_turn`. Planner routing is still hard-checked (range, no self,
no duplicates, empty unless send, no calls/sends after submit, budgets,
next-round delivery); an illegal route fails the run — there is no ring,
star, broadcast or any other fallback.

Ledger reconciliation stores hashes only (`worker_output_sha256`): every
message body and submission answer must hash-match the same agent's
same-round worker output, message sets must correspond one-to-one with
send controls, and usage must equal the authoritative wrapper ledger.

SkillBank isolation: `PythonSkillPayload` carries
`worker_contract`; retrieval, replay and payload merges are gated on it.
Cards without the field (pre-field banks) are classified `action_json_v1`
and are never rewritten or migrated.

What this mode fixes and what it does not: it removes the action-JSON
failure class (malformed JSON, missing/forged fields, contract-violating
routing authored by a weak worker model) by shrinking the worker's job to
content generation. It does not make worker content correct — reasoning
errors inside the message or answer text are untouched.

### message_only_v2

`message_only_v2` separates communication from answer submission:

```text
round 0 ... submit_round-1:
  deliver prior messages -> freeze round snapshot -> send/reflect/idle

submit_round:
  deliver the final communication messages
  -> freeze every Agent's final state and inbox
  -> preflight the complete submit budget
  -> submit every required Agent from that frozen logical snapshot
  -> stop
```

`plan_submit_round(n_agents, max_rounds, information_goal)` selects one global
round satisfying `0 <= submit_round < max_rounds`; the default is
`max_rounds - 1`. Therefore `max_rounds` includes the barrier. The Planner's
`plan_communication_turn` may return only `send`, `reflect`, or `idle`. A
communication-time `submit`, a send at the barrier, an inconsistent barrier
round, or a per-Agent early submit fails closed.

In `all_agents`, every Agent submits at exactly the same logical round. Their
frozen prompts are dispatched as one host-bounded parallel batch, and commits
remain Agent-ordered. An earlier Agent's answer cannot enter a later Agent's
prompt. In `sink`, only `selected_primary` submits, still after the final
message delivery.

Communication Workers continue to return plain text. Submit Workers use
`json_mode=False` and must return exactly one JSON value. The runtime parses the
whole stripped response once with `json.loads` and stores the native value:

| Worker text | Stored answer |
| --- | --- |
| `42` | integer `42` |
| `[1, 2, 3]` | list `[1, 2, 3]` |
| `"accepted"` | string `accepted` |
| `{"answer": 42}` | object `{"answer": 42}`; never unwrapped |

`The answer is 42`, `Answer: 42`, Markdown fences, trailing explanation,
`NaN`, and other non-canonical responses produce `AnswerFormatError`. There is
no regex extraction, judge LLM, ground-truth repair, silent trimming, or format
retry.

The v2 stdin payload does not carry the legacy `local_prompt`. Each Agent has
two separately authorized fields:

- `communication_prompt`: task/private-shard context plus a short communication
  purpose, with no belief-state output schema;
- `submit_prompt`: task/private-shard context plus the benchmark's public
  `Output` requirement, with no belief-state/action template.

Communication calls can read only the first field and submit calls can read
only the second. The scaffold places the selected private context before an
immutable instruction. Consequently a submit prompt ends with
`FINAL OUTPUT CONTRACT`, including the whole-response single-JSON-value rule;
the old status/proposal/consensus template can no longer appear after that
contract. The bootstrap independently selects the mode-specific authorized
field and reconstructs the complete prompt byte-for-byte.

The authoritative `submit_barrier` ledger records the information goal,
planned/observed Agent ids, global round, synchronization result, a hash of the
frozen final snapshot, the whole-response parser identity, and answer hashes.
The main host independently reconciles these values with stdout submissions,
messages, provenance and usage.

All three contracts are separate SkillBank namespaces. Retrieval, replay,
reuse/innovation, warm start, consolidation, merge, cache keys and audit
artifacts require an exact `worker_contract` match. A v2 Python Skill preserves
its complete source and program hash, runtime/barrier summary, insight and
evidence; historical cards without the field remain `action_json_v1` and are
not rewritten.

The parallel v2 scaffold also requires every Worker call site to use
`complete_batch`; an older sequential v2 source fails current static validation
and cannot be replayed silently. It may be regenerated or repaired against the
versioned parallel scaffold, after which it must pass the normal held-out gate.

## Commands

```bash
# One offline run
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 --max-rounds 2 \
  --planner --planner-mode python_generate --llm fake --model-name fake

# One offline message-only run (planner routes, workers return plain text)
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 --max-rounds 3 \
  --planner --planner-mode python_generate \
  --python-worker-contract message_only_v1 --llm fake --model-name fake

# One offline synchronized-submit run
uv run python -m masbench.cli run --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --case I-01 --n-agents 2 --max-rounds 2 \
  --planner --planner-mode python_generate --silo-eval-mode all_agents \
  --python-worker-contract message_only_v2 --max-parallel-agents 2 \
  --llm fake --model-name fake

# Three independent generated arms
uv run python -m masbench.cli bench --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --cases I-01 --agent-counts 2 --seeds 0 \
  --arms graphgen programgen pycodegen --llm fake --model-name fake \
  --out runs/python_three_arm_smoke

# Evolve Python programs
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels II III --agent-counts 5 --train-seeds 1 2 --val-seeds 3 \
  --planner-mode python_generate --llm fake --model-name fake \
  --out runs/python_evolve_smoke

# Offline v2 hot-start wiring: reuse + local mutation + fresh generation
uv run python -m masbench.cli evolve --benchmark silo_bench \
  --benchmarks-dir third_party/acl26-silo-bench/benchmarks \
  --levels II III --agent-counts 5 --train-seeds 1 2 --val-seeds 3 \
  --silo-eval-mode all_agents --planner-mode python_generate \
  --hot-start --hot-start-protocols auto --hot-start-topologies auto \
  --hot-start-innovation-mode python_generate \
  --python-innovation-strategy mutate_and_fresh \
  --failure-policy honest_v2 --evolution-gate-policy strict_dense_v2 \
  --strict-gate-min-dense-delta 0.01 \
  --llm fake --model-name fake --out runs/python_evolve_v2_smoke

# Offline semantic demo
uv run python scripts/demo_python_generate.py
```

`scripts/verify_beats_baselines.py` also accepts
`--evolved-mode python_generate` and `--baselines pycodegen ...`. A real-model
run consumes API tokens; the tests and demo use fake clients only.

For an `all_agents` comparison where incomplete output must never be scored as a
normal answer, add `--require-all-submissions --final-submission-retries 2`.
Use `--resume` with the identical `--out` path after interruption. Evolution
rounds are checkpointed atomically with their complete before/candidate/deployed
SkillBanks; resumed runs load the last deployed Python source and evidence rather
than reconstructing or silently promoting a candidate.

## Audit Artifacts

Each generation writes its own Python-only tree containing architect prompt,
every source attempt and validation result, final source/hash, redacted stdin and
stdout, redacted stderr, repair trace, and execution report. Private local,
communication, and submit prompt text, answers, message bodies, API keys,
ground truth, and private scoring payloads are not persisted; only prompt
lengths and hashes appear in the redacted payload artifact.

For `message_only_v2`, `execution_report.json` additionally embeds the
sanitized `submit_barrier`, resolved execution timeout, and parallelism ledger
(`batch_calls`, `max_batch_size`, and `max_workers_used`). The offline fake
returns the valid JSON string `"UNKNOWN"`: this proves parsing and wiring
without fabricating a benchmark solution.
