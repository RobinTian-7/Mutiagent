# Paper to Code Mapping

## Section 3: Interaction model

Paper concepts:

- agent activations
- events
- delivery policy
- execution trace

Code modules:

- `src/dig_repro/events/models.py`
- `src/dig_repro/runtime/models.py`
- `src/dig_repro/runtime/runner.py`

## DIG construction

Paper concepts:

- dynamic directed acyclic graph over activations and interactions
- causal edges
- temporal ordering

Code modules:

- `src/dig_repro/dig/graph.py`

## Section 5: Failure characterization and healing

Paper concepts:

- `ET`, `MC`, `OE`, `DL`, `ER`, `CLA`, `RSP`
- structure-driven interventions

Code modules:

- `src/dig_repro/detectors/models.py`
- `src/dig_repro/detectors/rules.py`
- `src/dig_repro/healing/engine.py`

## Section 6: Benchmarks

Paper concepts:

- Count Frequency
- 20 Newsgroups Frequency
- easy / medium / hard

Code modules:

- `src/dig_repro/tasks/base.py`
- `src/dig_repro/tasks/count_frequency.py`
- `src/dig_repro/tasks/newsgroups_frequency.py`

## Section 7: Baselines and evaluation

Paper concepts:

- MAS-only
- MAS + LLM Judge
- MAS + DIG
- RMSE
- runtime
- valid output rate
- detected error counts

Code modules:

- `src/dig_repro/baselines/systems.py`
- `src/dig_repro/metrics/eval.py`
- `src/dig_repro/runtime/runner.py`
