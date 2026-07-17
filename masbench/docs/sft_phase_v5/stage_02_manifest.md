# Stage 2 — Experiment seal, authority closure & deterministic provisioning

- Date: 2026-07-17
- Start HEAD: `0a2e0062`
- Scope: converge the existing bootstrap/runtime/protocol/runner/pair/candidate
  manifests into one executable experiment seal, plus a provision-only entry.
  Zero model calls.

## Design note (plan adaptation, semantics preserved)

The plan sketches a `PilotExperimentManifestV1` with authority/protocol roots.
The repo already had `PilotExperimentManifestV1` (multi-arm children +
blocked orders) and `PilotRuntimeAuthorityManifestV1` (git commit, bootstrap
digest, runner/schedule/method-policy roots, role keys). Rather than mutate
those validated schemas, Stage 2 adds the missing *root* object:
`PilotExperimentSealV1` embeds the experiment manifest and its five child
manifests (case/pair/candidate/runner/schedule) plus the structural-anchor
plan+bundle, and pins by digest the two authority manifests, TEST/report
commitments (commitments only — TEST content never enters TRAIN authority),
per-split case roots, and the genesis component root. All plan-listed facts
are therefore sealed; none were weakened.

## Changed files

- `masbench/src/masbench/sft_pilot/experiment.py` (new):
  `PilotExperimentSealV1` (closed, self-validating: child digests, method
  policy root, split roots, anchor-plan binding, anchor-derived genesis,
  TEST≠report), `load_experiment_seal` (absolute, O_NOFOLLOW, canonical exact
  JSON), `validate_experiment_seal` (authority cross-pins, git commit
  equality, arm membership by protocol digest, schedule/case/pair closure via
  the existing `validate_schedule_against_protocol`, anchor namespace/source
  authority equality, genesis law: factor-backed arms must carry the anchor
  genesis, non-factor backends must NOT), `derive_method_policy_sha256`,
  `split_case_manifest_sha256`, `derive_capacity_preflight` (frozen facts
  only), `provision_phase_v5_experiment` (seal graph → anchor native reload →
  idempotent `provision_pilot_store`), `load_sealed_authority_manifests`,
  and the host-pinned code-source path law (`runtime_code_source_paths`,
  `bootstrap_code_source_paths`).
- `masbench/src/masbench/sft_pilot/store.py` — added
  `component_genesis_sha256_from_envelope_digests` sharing the existing
  `_component_bundle_body` so seal-level and byte-level genesis derivations
  cannot drift.
- `masbench/src/masbench/sft_pilot/provision.py` — optional
  `execution_schedule` pass-through (store-derived-schedule protocols could
  not otherwise be opened at provision time).
- New reserved modules pinned by the code-source law (docstring-only until
  their stages): `pair_adapter.py`, `pair_consumer.py`, `request_renderer.py`,
  `result_ledger.py`.
- `masbench/src/masbench/sft_pilot/scientific_runner.py` — v5 key-derivation
  law (four component domains + runtime/bootstrap role domains, all distinct
  from v3/v4); the entry now loads the seal, loads both authority manifests at
  their sealed digests, validates the full closure against the run's
  protocol, checks the provisioned store, and remains fail-closed ("the
  scientific execution loop is not authorized in this build").
- `masbench/tests/sft_v5_fixtures.py` (new) — the authoring factory: builds a
  real structural anchor (locus `/phases/1/hub`), all manifests, two child
  protocols (`sft_unified` + `ect_whole_transaction`), the experiment
  manifest, both authority manifests with real code pins over repo files and
  real role-key commitments, the seal, canonical frozen files, and a
  provisioned store. Everything passes through production schemas/entries.
- `masbench/tests/test_sft_v5_experiment.py` (new, 9 tests): seal closure +
  canonical load; non-canonical/tampered/symlinked seal rejection; six
  internal-closure tamper cases; wrong-authority + foreign-protocol
  rejection; control-arm anchor-genesis hijack rejection (both digest-level
  and authored-seal-level); provision idempotence + exact genesis recovery
  through a real store reopen; swapped-key and control-arm provisioning
  rejection; canonical authority file round-trip; run_evolution seal
  validation reaching the fail-closed tail with zero side effects plus
  tampered-seal rejection at the profile entry.

## Notes for later stages

- The current `SFTPilotFactorAuthority` requires the protocol's
  `authorized_logical_arms` to be exactly the 12 probe arms; the v5 protocol
  adds generation and FINAL_VAL arms, so Stage 5 will adapt the authority to
  operate on the probe subset while keeping the exact 6-pair law (plan 9.1
  "适配…保持exact 6-pair schedule").
- The `ect_whole_transaction` child protocol currently pins a synthetic
  genesis; its real backend genesis story lands in Stage 10.

## Tests

- `tests/test_sft_v5_experiment.py` → **9 passed**.
- All `tests/test_sft_*.py` (incl. new) → **213 passed in 12.76s**.
- Fixed during development: store-derived protocols could not be provisioned
  because `provision_pilot_store` never forwarded the execution schedule
  (fixed with the optional pass-through; existing provisioning tests remain
  green).

## Exit Gate

- [x] A v5 DB is deterministically provisioned from frozen bytes.
- [x] Re-provisioning identical bytes is idempotent (receipt equality).
- [x] Any difference fails closed (tamper/symlink/wrong-key/foreign-protocol
      cases tested).
- [x] Zero model calls.
- [x] Reopening the store recovers the exact generation-zero envelope bytes
      and genesis root.

Local tests passed; no CI status was available/verified.
Paid model calls: 0. Scientific status: mechanics-only; no efficacy claim.
