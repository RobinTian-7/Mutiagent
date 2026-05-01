# Reproduction Plan

## Goal

Reproduce the DIG paper at the system level:

- asynchronous multi-agent runtime
- event-driven agent interaction
- Dynamic Interaction Graph construction
- structural error detection
- DIG-based healing
- LLM Judge baseline
- Count Frequency and 20 Newsgroups Frequency tasks
- evaluation across difficulty and agent counts

## Planned milestones

1. Build independent package and docs
2. Implement event, activation, trace, scheduler, and DIG graph
3. Implement task adapters and tools
4. Implement planners:
   - rule-based planner for deterministic tests
   - LLM planner for paper-style agent control
5. Implement detectors and healing engine
6. Implement baselines and experiment runner
7. Implement metrics and graph export
8. Add regression tests and example scripts
9. Calibrate experiment settings against paper trends

## Success criteria

1. The three systems run end to end
2. DIG graph and failure taxonomy are exported per run
3. CF and NC tasks support easy/medium/hard settings
4. RMSE, runtime, valid output rate, and detected errors are computed
5. The reproduction produces the same qualitative trends reported in the paper:
   - `MAS + DIG` is generally more reliable than `MAS-only`
   - `MAS + LLM Judge` incurs higher overhead
   - DIG healing improves valid output rate at larger scale and harder settings

## Non-goals

- Reusing `exp-graph`'s synchronous round runner
- Forcing topology abstractions into DIG
- Claim DAG or DTI integration
