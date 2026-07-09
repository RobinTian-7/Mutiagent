# DIG Reproduction

This subproject is a paper-faithful reproduction of **DIG to Heal: Scaling General-purpose Agent Collaboration via Explainable Dynamic Decision Paths** ([arXiv:2603.00309](https://arxiv.org/pdf/2603.00309)).

It is intentionally independent from:

- the root `src/` reproduction of `2604.02674`
- the `exp-graph/` synchronous topology experiment package

The DIG paper studies a different system shape:

- asynchronous event-driven agent collaboration
- no predefined roles or fixed control flow
- emergent routing through `consume / reroute / wait / discard / submit`
- real-time Dynamic Interaction Graph construction
- structural failure detection
- structure-driven healing

## Scope

This reproduction includes:

1. `MAS-only`
2. `MAS + LLM Judge`
3. `MAS + DIG Healing`
4. Count Frequency benchmark
5. 20 Newsgroups Frequency benchmark
6. DIG graph export
7. structural error taxonomy:
   - `ET`
   - `MC`
   - `OE`
   - `DL`
   - `ER`
   - `CLA`
   - `RSP`

## What "complete reproduction" means here

The DIG paper currently does not expose an official reference implementation in the paper artifacts we could verify against. Because of that, this project targets:

- architecture-level fidelity to the paper
- experiment-protocol fidelity
- metric fidelity
- representative-trend fidelity

and explicitly documents every engineering assumption needed where the paper leaves implementation details underspecified.

That is different from claiming byte-identical parity with an unpublished internal codebase.

## Quickstart

```bash
cd dig-repro
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,analysis,datasets]"
pytest
python examples/run_cf_experiment.py --system mas_dig --difficulty medium --n-agents 3
```

## Directory layout

```text
dig-repro/
  docs/
  examples/
  src/dig_repro/
  tests/
```

## Key outputs

The runner exports:

- execution traces
- DIG graph JSON
- activation timeline data
- detector findings
- interventions
- experiment metrics

## Current status

This codebase is under active build-out. The reproduction protocol and assumptions are pinned in:

- `docs/reproduction_plan.md`
- `docs/assumptions.md`
- `docs/paper_to_code_mapping.md`
