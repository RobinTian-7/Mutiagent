# Stage 4 — Proposal generation authority

- Date: 2026-07-17
- Start HEAD: `59e8c483`
- Scope: close the trusted generation chain for reuse/mutate/fresh actions.
  reuse spends zero generation calls; mutate/fresh spend at most one frozen,
  store-receipted call; failures become honest authority-fenced aborts.
  Zero paid calls (fake transport only).

## Changed files

- `masbench/src/masbench/sft_pilot/factor_authority.py`
  - The three previously uncovered capabilities are now implemented and
    authority-signed with new domains: generation context
    (`sft-pilot-proposal-generation-context-v1`), generation lease
    (`…-lease-v1`), proposal abort (`sft-pilot-proposal-abort-v1`), plus a
    screen-time proposal-action attestation domain. `uncovered_capabilities`
    is now `()`.
  - `make_generation_context` seals protocol-derived TRAIN source roots and
    the derived one-call generation budget; `verify_generation_context`
    checks epoch, HMAC, namespace/runtime/source-catalog joins and the exact
    budget. `make/verify_generation_lease` binds the prepared action digest
    and its request digest (signature excludes the Bank-owned
    `started_seq`). `make/verify_abort_receipt` fences honest aborts
    (signature excludes the Bank-owned `emitted_seq`).
  - `derive_generation_budget` is a shared module function so sealed
    schedules and the runtime authority can never disagree.
  - v5-protocol adaptation (planned in plan 9.1): the authority now operates
    on the probe *subset* of `authorized_logical_arms` (still exactly six
    typed pairs / twelve arms, unchanged law); protocols with exactly twelve
    probe arms behave byte-identically.
- `masbench/src/masbench/sft_pilot/request_renderer.py` — real
  implementation: frozen prompt template + strict scalar output schema with
  pinned digests; `generation_request_envelope_sha256` (outcome-before
  frozen-shape envelope — branch/failure-code/source-value change prompt
  bytes, never the reservation identity, which the Bank lease pins exactly);
  `render_generation_request` (fresh must not see the source scalar; mutate
  must; byte caps); `parse_generated_scalar` (strict `{"value": …}`, typed,
  capped — any deviation is `GeneratedScalarInvalid`, convertible only into
  an honest abort).
- `masbench/src/masbench/sft_pilot/llm_meter.py` —
  `scheduled_request_envelopes`: store-derived schedules pin one frozen
  request envelope per call slot, so the client reserves under exactly that
  identity while the runtime prompt-bytes commitment travels in the durable
  reserve/start operation payloads; `expected_component_recovery_root_sha256`
  threads the saga fence into reserve/start; `FakeDeterministicPilotTransport`
  (reply from prompt digest only — cannot read answers, guarantees nothing
  about improvement). Legacy behaviour byte-identical when the new params
  are absent.
- `masbench/src/masbench/sft_pilot/components.py` — optional
  `branch_receipt_verifier` threaded into the coordinator's registry load
  (default None keeps mechanics profiles' registries branch-read-only).
- `masbench/src/masbench/sft_pilot/scientific_runner.py` —
  `V5BranchReceiptAuthority` (in-process capability: only the frozen anchor
  receipt or an explicitly authorized nonterminal Bank action can register a
  branch receipt); `v5_factor_capabilities_factory` (authority capabilities
  plus acceptance of the sealed anchor's historical base-snapshot receipt);
  `reserve_scheduled_execution` (lease exactly as the frozen schedule row);
  `execute_metered_generation_call` (schedule/renderer envelope equality,
  one-call law, metered client, finalize).
- `masbench/tests/sft_v5_fixtures.py` — generation schedule entry now pins
  the real renderer envelope/template/policy digests; anchor namespace uses
  `n_agents=3` so the int hub domain has a fresh legal value.
- `masbench/tests/test_sft_v5_generation.py` (new, 5 tests) and an updated
  assertion in `test_sft_factor_authority.py` (uncovered set is now empty —
  the old assertion documented the pre-Stage-4 gap).

## End-to-end evidence (fake transport, real everything else)

- mutate: provisioned fixture → coordinator recovery head → real-authority
  screen/context → `action_prepared` checkpoint → scheduled execution lease →
  authority lease → `generation_start_authorized` checkpoint → rendered
  request (envelope == frozen schedule pin) → metered fake call (completed,
  provider-usage-known, saga-fenced) → strict parse → branch-authorized v3
  reconcile → committed action + new one-slot edge from the anchor source;
  raw prompt text absent from the SQLite bytes.
- fresh: invalid outputs (non-JSON, extra key, wrong type) raise and the
  action aborts honestly; no transition appears for the aborted action.
- fresh render rejects a source-scalar leak.
- reuse: zero store budget movement, no generation request, reconciles
  without generation inputs.
- authority pairs: foreign-key authority and field tampers are rejected for
  context/lease/abort; correct signatures verify.

## Tests

- `tests/test_sft_v5_generation.py` → **5 passed**.
- All `tests/test_sft_*.py` → **225 passed in 20.17s** (includes the llm
  meter, saga, store, factor-authority, manifest and v5 suites).
- Fixed during development: prepared-state cleanup abort must use a
  non-generation reason; saga call crossings require the recovery-root fence
  (now a first-class metered-client parameter); module-scoped harness broke
  the first-checkpoint saga law (function-scoped now).

## Exit Gate

- [x] reuse spends zero generation calls (budget ledger root unchanged).
- [x] mutate/fresh at most one frozen call (single scheduled slot; metered
      client structurally cannot repeat it).
- [x] Every call has a complete store receipt (lease completed, call
      completed with provider usage, saga-fenced).
- [x] Action ends committed or honestly aborted; no probe executed.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
