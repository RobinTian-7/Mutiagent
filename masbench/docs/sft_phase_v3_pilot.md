# SFT Phase v3 research profile

Status: **default-off, mechanics-only**.  This document does not preregister or
claim an efficacy result.

## Purpose

`phase_v3_shadow_register` is the narrow integration surface for the Sealed
Factor-Transition Bank (SFT-Bank) research hypothesis.  It exists so that
authenticated state creation, recovery, namespace fencing, and later pilot
wiring can be tested without changing the historical QueenBee evolution path.

SFT-Bank's indivisible scientific unit is one host-proved, comparator-conditioned
single-factor transition.  The same unit must be all of the following:

1. the representation retrieved by the Bank;
2. the legal action selected among `reuse | mutate | fresh`;
3. the executed carrier transition;
4. the sole owner of paired evidence and credit;
5. the object gated, rolled back, archived, and replayed.

This is the synthesis point for the earlier PIF/FACTS/TRACER/TRIAD/TRACE-MAP/
ASUEL ideas.  It is not a claim that any one of those designs has already won.

## Default-off invariant

With the default `RunConfig.sft_profile == "off"`:

- `masbench.sft_phase_pilot` is not imported;
- `MASBENCH_SFT_STATE_KEY` is not read;
- no SFT state path or file is created;
- no additional model, planner, worker, benchmark, or verifier call occurs;
- the historical evolution implementation and defaults remain authoritative.

The flags are exposed only on `masbench evolve`:

```text
--sft-profile {off,phase_v3_shadow_register}
--sft-state-dir PATH
```

An active profile requires an absolute state path, `program_generate` for both
planner and evolved mode, `honest_v2` failure handling, `strict_dense_v2`
gating, and all legacy hot-start/insight/exploration/portfolio/recipe/exemplar
paths disabled.  Partial activation fails closed.

## Current executable behavior

`phase_v3_shadow_register` currently performs exactly these operations:

1. decode a caller-supplied `MASBENCH_SFT_STATE_KEY` (hex or strict base64,
   at least 32 bytes) before creating the state directory;
2. derive domain-separated keys for the Phase registry and FactorBank;
3. take an exclusive directory lock;
4. create or authenticate-load an empty `PhaseArtifactRegistry` and
   `FactorBankV2` wired to concrete Phase binding, action-terminal, and repair
   opportunity verifiers;
5. return a summary with zero model calls, zero tokens, no probe, and a rejected
   gate whose reason is `shadow_register_has_no_probe_or_gate`.

Synthetic held-out rows and initial legacy skills are rejected.  The summary's
status is `shadow_register_only_no_efficacy_claim`.

Example smoke invocation (mechanics only):

```bash
export MASBENCH_SFT_STATE_KEY=<at-least-32-byte-hex-or-base64-secret>
uv run masbench evolve \
  --planner-mode program_generate \
  --sft-profile phase_v3_shadow_register \
  --sft-state-dir /absolute/private/path/sft-state \
  --out /absolute/private/path/run
```

Do not place a real state key in source control, command transcripts, run
summaries, or research ledgers.

## Isolation commitments

Every future SFT namespace must commit at least:

```text
benchmark / task_family / split_role
planner_mode / carrier_kind / carrier_schema_version
information_goal (sink | all_agents)
worker_contract / objective policy
source artifact and immutable input-root commitments
```

No transition may cross any of those boundaries.  `mode_payload` content stays
inside its carrier adapter: topology, paper protocol, GraphGen, PhaseProgram,
and full Python source can share lifecycle laws but cannot share executable
payloads or worker contracts.

The Bank must reject any dependency on TEST input, answer, ground truth,
expected output, private prompt text, or evaluation seed.  Persisted failure
records may contain typed stage/signature/cost facts only; they may not retain
the forbidden content itself.

## Gates before enabling a probe profile

There is intentionally no `shadow_probe` flag yet.  It must not be added until
all of these are implemented and tested offline:

- a concrete authenticated append-only runner journal with host-owned sequence
  and generation fencing;
- crash-consistent `0/1/2-start` pair execution and reproducible raw terminal
  commitments, with Bank-owned settlement ordering;
- capacity protection for every prepared action edge;
- one durable action saga for each of `reuse`, `mutate`, and `fresh`, including
  exact mutation parent, empty fresh Bank-dependency closure, bounded invocation,
  idempotent recovery, and authenticated abort;
- transition credit blocked until the exact carrier action is terminal;
- bounded receipt retention that cannot erase a live scientific claim;
- negative tests for tamper, replay, reorder, truncation, cross-namespace use,
  forbidden-field leakage, wrong credit, and all-zero reward.

Only after those mechanics pass may a real `gpt-4o-mini` equal-budget pilot run.
The pilot must compare current QueenBee, whole-receipt ECT, SFT-Bank, shuffled
credit, uniform branch choice, and factor/lineage/diversity ablations under the
same model-call and token caps.  Quality, safety, attribution, diversity, and
tokens-per-gated-transition are joint gates; lower cost cannot compensate for
degraded V/K/U/P/S or stage score.

## Interpretation rule

Passing this smoke profile proves only that the default-off control plane and
authenticated empty-state recovery work.  It provides no evidence that
SFT-Bank improves task quality.  Before frozen TEST evaluation, the strongest
permitted description is:

> 经过代码、论文、近期 prior art、离线机制检查和多轮对抗审计后，目前最值得进行真实实验验证的 SkillBank 研究假设。

