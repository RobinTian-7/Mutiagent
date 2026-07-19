# Multi-base anchor design (user-directed, 2026-07-18)

User requirement: the FIVE structures — one_peer_exponential_dag /
static_exponential / P2P / Broadcast / SFS — all join as EVOLUTION BASES
(source compositions) under information_goal=all_agents with the per-agent
submission barrier. Paper tool-action runners may additionally serve as
reference arms, but each structure gets a phase-carrier base.

Compiler: `exponential` pattern added to ConsensusPhase + PairwiseExchangePhase
(offset 2^r mod n, floor 1; exp-graph/tests/test_phase_program_exponential.py).
PHASE_PROGRAM_COMPILER_VERSION stays "1" (pure extension; existing constructs
compile byte-identically).

## Base table (each: source program, host anchor target, mutable locus)

| base_structure | phases (source) | locus | type | source→target | legal domain |
|---|---|---|---|---|---|
| one_peer_exponential_dag | consensus(exponential, stop=all_agents_full_information, max_rounds=8) | /phases/0/pattern | string | exponential→rotating | {all_to_all, rotating, exponential} |
| static_exponential | pairwise_exchange(exponential, stop=fixed_rounds, max_rounds=3) | /phases/0/max_rounds | int | 3→4 | [1, 8] |
| p2p | pairwise_exchange(rotating, stop=fixed_rounds, max_rounds=4) | /phases/0/pattern | string | rotating→ring | {ring, bidirectional_ring, rotating, exponential} |
| broadcast | consensus(all_to_all, stop=all_agents_full_information, max_rounds=2) | /phases/0/pattern | string | all_to_all→rotating | {all_to_all, rotating, exponential} |
| sfs | gather(hub=0, tree) + broadcast(hub=0, tree) | /phases/0/pattern | string | tree→star | {star, tree} |
| gather_broadcast (legacy default) | gather+broadcast tree | /phases/1/hub | int | 0→1 | [0, n) |

Rationale: SFS ≈ hub-mediated shared store (gather+broadcast); paper Broadcast
≈ one all_to_all dissemination round; paper P2P ≈ rotating pairwise rounds;
one_peer_exponential_dag ≈ coverage-stopped exponential consensus;
static_exponential ≈ fixed-round exponential pairwise schedule. Pattern loci
make STRUCTURE DIRECTION itself trainable (the generation LLM proposes a
pattern string from the closed legal domain minus registered values) — the
answer to "manual vs auto": in-skeleton scalar structure (pattern/rounds/hub)
mutates automatically in training; skeleton-level shape (phase list/kinds,
new bases) is host-authored by the anchor law (v5 locked_atomic skeleton).

## Implementation map

1. `structural_anchor.py`: `StructuralAnchorPlanV1.base_structure` (default
   "gather_broadcast", byte-compat); per-base source/target program
   properties + per-base locus/scalar-type/target-value; bundle `locus`
   field widened from the single-locator Literal to the per-plan locus;
   build/extract/branch/generated-value parameterized by base.
2. `real_experiment.py`: ANCHOR_LOCATOR/ANCHOR_SCALAR_TYPE become per-base
   (from the plan); generation envelope + schedule derive from base locus.
3. `real_train.py`: SafeSourceScalar + value_domain_description per base
   (string domains enumerate legal values minus registered; int domains give
   ranges minus registered).
4. `run_real_pilot.py`: `--bases` comma list (default the five);
   one sealed experiment per base (replicate = base), shared TEST holdout,
   baseline arm per base = its own source program (paired same-case deltas),
   plus optional paper-runner reference arms later.
5. Renderer: verify parse_generated_scalar/SafeSourceScalar accept
   scalar_type "string" (locus law allows null|bool|int|string).

Status: compiler done; anchor rework next. Real run after offline rehearsal.
