# M10 design: train-time VERIFIED recipe search (the fundamental floor attack)

Status: designed 2026-06-11; implementation after M9 (recipes carry M9
instruction fields). Borrowings: Reflexion (verbal feedback retry), STaR
(keep only verified traces), AWM (workflow induction); operator scope:
minister logic + SkillCard schema + prompt templates.

## Problem

The minister only distills ONE-SHOT runs. On capability-floor train cases
nothing succeeds once, so no positive evidence can ever enter the bank, and
test-time replay has nothing to carry (dev-4: 0 wins/72 on floors).
Train-time, the benchmark adapter exposes the training signal (ground-truth
scoring on TRAIN cases only) -- iterating proposals against it is ordinary
learning, not leakage, PROVIDED the stored artifact is a PROCEDURE
(structure + per-step instructions + assembly note), never data values.

## Generalizability contract (operator requirement)

- Inputs to the search: task STATEMENT (adapter interface), prior-attempt
  procedural feedback (per-agent correctness booleans + structural stats),
  the run's own LLM. No benchmark-internal labels, no benchmark keywords in
  prompts (tested like M7/M9).
- Output recipe lives in generic SkillCard fields; retrieval/trust/abstain
  reuse M1-M8 unchanged. Different benchmark = different adapter only.
- Leakage audit in diag: stored instructions must contain no input-shard
  literals from the train case (checked by substring scan over shards in
  the round report).

## Mechanism

In `run_evolution`, after evidence collection, for each TRAIN case whose
evidence rows show zero successes under every measured organization (the
generic floor criterion):

1. attempt <= R_MAX (4): emperor proposes a full recipe = temporal DAG +
   per-step receiver instructions (M9 field) + final-answer assembly note,
   conditioned on the task statement + compact feedback from the previous
   attempt ("agents 2,4 wrong; sink answer had wrong length; step-2
   forwarding lost raw elements").
2. Execute on the train case (1 seed). Verify via the adapter's train
   scoring. Fail -> feedback -> next attempt.
3. Success -> verify on a 2nd seed (M1 trust bar n>=2 needs 2 rows;
   1 lucky run never deploys). Both pass -> RECIPE SkillCard enters the
   minister batch with its kind/bucket ledger rows; gate vets the batch as
   usual (M5 sample size, M2 ratchet).
4. Budget: recipe search only fires for floor cases (<= 3 per round),
   <= 4+2 runs each -> <= 18 extra runs/round, cacheable per (case, recipe
   hash) is NOT possible (search is adaptive) -- cap via cfg
   recipe_search_budget (runs/round, default 18; 0 = off).

## Deployment

Nothing new: the recipe card carries an executable spec (now with
instructions) + ledger rows in its kind; M1-M8 trust gating deploys it on
same-kind held-out cases; M9 rewrite refreshes instructions for the test
statement (structure + procedure transfer, wording adapts).

## Tests

- Floor criterion: only zero-success cases trigger search (fake rows).
- Search loop: scripted LLM returns recipe JSON; failing verifier ->
  feedback included in next prompt; success -> 2nd-seed verification; card
  created with instruction-bearing spec + correct ledger rows.
- Budget cap honored; off switch = byte-identical run_evolution output.
- Prompt benchmark-keyword test; leakage scan helper unit test.
