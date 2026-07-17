# SFT Phase v4 single-writer preliminary shell

Status: **default-off, mechanics-only, no efficacy claim**. This document adds
an integration shell after the v3 shadow-register work; it does not revise the
v3 preregistration or any frozen experimental conclusion.

## What v4 adds

`phase_v4_single_writer_preliminary` connects three already tested control-plane
primitives without adding a scientific runner:

1. a caller-owned, absolute-path `PilotProtocolV1` JSON freezes the namespace,
   method arm, source commitments, logical arms, budgets, capacities, model and
   component genesis before dispatch;
2. `SingleWriterPilotStore` authenticates that exact protocol and owns the
   durable component bytes under one stable writer lock;
3. `PilotComponentCoordinator.restore_latest()` replaces both non-authoritative
   working mirrors from SQLite and loads them through the native
   `PhaseArtifactRegistry` and `FactorBankV2` authenticated codecs.

The returned status is `component_restore_only_no_efficacy_claim`. It reports
protocol and component commitments, makes zero model calls, consumes zero
tokens, performs no benchmark/probe/update, and always reports a rejected gate
with reason `component_restore_has_no_probe_or_gate`.

## Flags and closed configuration

The profile remains available only on `masbench evolve`:

```text
--sft-profile phase_v4_single_writer_preliminary
--sft-state-dir /absolute/private/state
--sft-protocol /absolute/frozen/pilot-protocol.json
```

Activation requires all of the following:

- `planner_mode == evolved_mode == "program_generate"`;
- `failure_policy == "honest_v2"` and
  `evolution_gate_policy == "strict_dense_v2"`;
- no legacy hot start, LLM insight, explore, evidence-portfolio, recipe-search,
  or exemplar-search path;
- absolute state and protocol paths;
- one outer worker (`workers=1`);
- `llm_provider == "fake"` for offline mechanics, or exactly
  `llm_provider == "openai"` and `model_name == "gpt-4o-mini"` for a future
  real run;
- no synthetic held-out rows or legacy initial skills.

The protocol must use `method_arm="sft_unified"`, require component bundles,
name exactly one PhaseProgram namespace matching the run's benchmark,
objective, information goal and optional agent count, and budget all three
phases (`TRAIN_UPDATE`, `PROBE`, `FINAL_VAL`). A supplied `agent_counts` grid
must be the singleton frozen in that namespace. Unknown protocol fields are
rejected by the closed Pydantic schema.

The protocol also freezes `input_admission_policy` to
`utf8_bytes_plus_fixed_allowance_v1` and the model-envelope allowance to 256
token units. Before a call can cross the transport boundary, the pilot requires
`len(prompt.encode("utf-8")) + 256 <= input_tokens_reserved`. This is a
deliberately conservative upper admission rule, not the ordinary
`len(text)/4` estimate. Provider-authoritative usage remains mandatory after
the call; any reported overage is terminal-indeterminate and is durably charged
at `max(full reservation, observed provider usage)`.

The profile derives independent HMAC keys for the SQLite authority, Phase
registry and FactorBank from `MASBENCH_SFT_STATE_KEY`. The secret itself never
enters protocol JSON, summaries or ledgers. A native Phase source manifest is
admissible only when its split/catalog/policy and full source-authority digest
match the frozen protocol; empty genesis registries contain no source content.
The v4 component key domain names Factor schema v14; earlier experimental v4
component bytes are intentionally not migrated by this profile.

Factor v14 also changes proposal persistence: the 50-selection cursor remains
bounded and carries diversity history only, while exact sole-UNKNOWN lifetime
counts live in a host-owned table capped by `max_proposal_decisions`.  A v5
selector receipt carries one exact-cell counter root, at most sixteen current
candidate witnesses and at most one delta.  Selector input and receipt have
independent 65,536-byte canonical caps; they are not bounds on an enclosing
decision or the complete Bank.  Each exact `ProposalDecisionV1` is separately
preflighted at a frozen 98,304 canonical bytes after host construction and
before assignment/action publication, while the lifetime table and all
proposal/action records remain jointly charged to the 64-MiB aggregate slab.
SQLite therefore never accepts a v13 Factor envelope, a v4 proposal receipt,
or an over-cap v14 proposal decision as the new scientific state.

## Provisioning and recovery boundary

v4 intentionally does not create a new experiment from a protocol alone. A
provisioning step must first:

1. build exact authenticated empty component envelopes;
2. set `PilotProtocolV1.genesis_state_sha256` to their bundle digest and
   `component_bundle_required=true`;
3. create the single-writer store with that exact protocol;
4. call `record_genesis_component_bundle(...)` once.

If `pilot.sqlite3` is absent, v4 fails before creating the state directory.
On a normal start, SQLite is the recovery source of truth: arbitrary drift in
`phase_registry.v8.json` or `factor_bank.current.json` is overwritten by the
latest committed bytes before native loading. Protocol mismatch, HMAC failure,
schema mismatch, missing genesis, malformed envelope, wrong component key, or
non-single-writer dispatch all fail closed.

This shell does not yet expose provisioning as a CLI command because doing so
without a frozen source-authority builder would let a run invent commitments
after observing its inputs. Provisioning belongs in the dedicated preregistration
tooling that freezes source, pair, candidate, runner and model manifests.

## Default-off and compatibility invariants

`RunConfig.sft_profile` still defaults to `"off"`; `sft_state_dir` and
`sft_protocol_path` default to `None`. The default route does not import
`masbench.sft_phase_pilot`, inspect `MASBENCH_SFT_STATE_KEY`, open a protocol,
create state, or add calls. `phase_v3_shadow_register` keeps its prior files,
keys, return schema and behavior; it neither requires nor accepts the v4
protocol path.

## What remains before a preliminary LLM run

Passing this shell proves only configuration closure and exact recovery. A
dedicated runner must still bind each metered `gpt-4o-mini` call to a frozen
logical arm, execute source/target/control pairs, append terminal evidence and
component commits atomically, enforce equal budgets, and keep FINAL_VAL scoring
physically outside Bank-visible capabilities. Until that runner and its frozen
experiment manifest exist, v4 must remain mechanics-only and no result may be
described as effective or preliminarily usable.

Focused offline coverage lives in
`tests/test_sft_phase_v4_profile.py`; component atomicity and recovery remain in
`tests/test_sft_pilot_components.py` and
`tests/test_sft_single_writer_store.py`.
