# Assumptions

This reproduction makes the following explicit assumptions because the paper does not fully publish an official implementation or all low-level runtime details.

## 1. Reproduction target

The target is **paper-faithful reproduction**, not source-level parity with a hidden upstream codebase.

## 2. Scheduler

The paper describes asynchronous message-driven activations over logical time. We implement this as a stochastic single-activation scheduler over agents with non-empty buffers. This preserves asynchrony and causal ordering while remaining reproducible under a random seed.

## 3. Event model

The paper defines events as payload plus delivery policy. We implement delivery policies as explicit recipient sets and per-event metadata, which is sufficient to reconstruct causal propagation and intervention effects.

## 4. Agent control

The paper provides prompt templates but not a full parsing implementation. We therefore:

- provide a structured LLM planner that follows the published prompt template
- provide a deterministic rule planner for tests and offline regression

The rule planner is not claimed to match the paper's hidden prompt dynamics; it exists to make the system testable.

## 5. DIG detection and healing

The taxonomy itself is paper-grounded. Detector thresholds such as reroute counts, deadlock windows, or missing-termination timeout windows are engineering parameters exposed via config.

## 6. 20 Newsgroups data loading

The paper references the 20 Newsgroups dataset. This reproduction uses `scikit-learn` dataset utilities when available. Tests do not depend on network downloads and instead use synthetic labeled documents.

## 7. Count Frequency value domain

The paper states that Count Frequency counts frequencies in an integer array, but the public PDF excerpt available here does not pin down the integer value distribution. To keep the solution objects bounded and mergeable, this reproduction uses a configurable finite value domain for generated CF instances.

## 8. Model choice

The current PDF excerpt does not clearly disclose every model and sampling setting used in the experiments. This reproduction therefore makes model provider and temperature configurable and records them in outputs.

## 9. Valid output

A run is considered valid when it emits a parseable final solution that covers the full root problem. This matches the paper's intent but requires explicit operationalization in code.
