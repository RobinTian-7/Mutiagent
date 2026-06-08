# masbench Plan 5: experiment infra — timeout + checkpoint/resume + concurrency

> Subagents on **Opus 4.8**. Guardrails every task: exp_graph `uv run --directory exp-graph --extra dev python -m pytest -q` = **251 passed, 1 skipped**; masbench `uv run --directory masbench --extra dev python -m pytest -q` = **78 passed**. All new behavior is **masbench-only** (do not change exp_graph engine semantics) and **opt-in / backwards-compatible** (defaults preserve current behavior except the always-on incremental checkpoint write, which is additive).

**Why:** a real-LLM `masbench bench` hung for 91 min on a single stalled OpenAI call. Root causes: (1) no hard wall-clock timeout that actually frees a hung socket; (2) bench writes results only at the very end (no checkpoint → total loss on crash/kill); (3) zero concurrency — the grid (instances × arms × seeds) and the per-run agents are fully sequential, so one stalled call freezes everything.

## T1 — Per-request hard timeout (`TimeoutLLMClient`)
**Files:** `masbench/src/masbench/llm/timeout.py` (new), `masbench/src/masbench/core/config.py`, `masbench/src/masbench/engine.py`, `masbench/src/masbench/cli.py`; test `masbench/tests/test_timeout_client.py`.
- `TimeoutLLMClient(inner, timeout_s)`: `complete()` runs `inner.complete()` on a **daemon thread** + `join(timeout_s)`; if still alive → raise `LLMTimeoutError(RuntimeError)` (the hung daemon thread is abandoned, dies with the process — it does NOT block interpreter exit, unlike `ThreadPoolExecutor.__exit__`/`shutdown(wait=True)`). If finished → return the result or re-raise the inner exception. Carry through `model_name`/`temperature`.
- `RunConfig.request_timeout: float = 90.0`. `engine._build_llm_client`: wrap **non-fake** clients (`TimeoutLLMClient(real_client, cfg.request_timeout)`); leave fake unwrapped. `cli`: `--request-timeout` (default 90) on the common args.
- Test: a `SlowClient.complete` that sleeps 2s → `TimeoutLLMClient(slow, 0.2).complete(...)` raises `LLMTimeoutError`; a fast client passes through unchanged.

## T2 — Per-run isolation + checkpoint + resume (bench)
**Files:** `masbench/src/masbench/bench.py`, `masbench/src/masbench/cli.py`; test additions in `masbench/tests/test_bench.py` (or new `test_bench_resume.py`).
- **Per-run isolation:** wrap every individual run (each `(arm, case, n, seed[, topology])`) in try/except. On ANY exception (incl. `LLMTimeoutError`) → emit a *failed* run record (`success=False, partial=0.0, n_messages/calls/tokens=0, error=str(exc)`) and CONTINUE. A single hung/failed call must never abort the grid.
- **Checkpoint:** as each run record is produced, append it as one JSON line to `runs/<out>/runs.jsonl` (create dir up front). Final aggregation reads ALL records (from runs.jsonl) → results.json/csv/report.md (unchanged formats).
- **Resume:** `--resume` flag. On start, load `runs.jsonl`, build the set of completed run keys `(arm, case_id, n_agents, seed, fixed_topology_or_None)`, and SKIP those. Without `--resume`, a fresh run truncates/overwrites `runs.jsonl`. Make the run-key helper explicit and shared.
- Test: run a tiny fake bench → assert `runs.jsonl` has one line per run; pre-seed `runs.jsonl` with a completed key, run with `--resume` → that run is skipped (not re-executed) yet appears in the final aggregate; a run whose client raises is recorded as `success=False` and the grid completes.

## T3 — Concurrency (`--workers N`, bench)
**Files:** `masbench/src/masbench/bench.py`, `masbench/src/masbench/cli.py`; test additions.
- `--workers N` (default 1 = current sequential behavior). With N>1, dispatch **independent run-units** to a `ThreadPoolExecutor(max_workers=N)` (threads are fine — LLM calls are I/O-bound and release the GIL). A run-unit = one `(arm, case, n, seed[, topology])` producing one (or, for fixed, one-per-topology) record.
- **Ordering/state caveats (handle explicitly):**
  - `graphgen` motif prior: the incremental "feed prior runs' motifs forward" is a sequential dependency. Under `N>1`, **snapshot** `motif_stats` once before dispatch (from any pre-supplied rows; empty if none) and use it for all graphgen runs — do NOT mutate mid-flight. Document this (the cross-run motif accumulation is a best-effort signal; correctness of each run is unaffected).
  - `evolved`: keep the heavy `run_evolution` loop **sequential** (run once per `n_agents`, cached) BEFORE parallel dispatch; only the per-instance eval runs go through the pool.
  - **Thread-safe checkpoint:** guard the `runs.jsonl` append with a `threading.Lock`.
- Determinism: aggregates must be identical regardless of `--workers` (modulo run order) on the fake client. Test: `workers=1` vs `workers=4` on a tiny fake grid → same `results["overall"]`/per-condition success means.

## T4 — Docs + final verification
- README + `masbench/docs/experiments.md`: document `--request-timeout`, `--resume`, `--workers`; add a recommended real-LLM command (`--workers 8 --request-timeout 90 --resume`), and a note that the grid is embarrassingly parallel + crash-safe now.
- Run both suites (exp_graph 251/1 unchanged; masbench 78 + new tests). Run an end-to-end fake bench with `--workers 4 --resume` twice (second run resumes/skips) to prove it. Commit.

## Self-review
- exp_graph engine untouched (timeout wraps the client in masbench; concurrency/checkpoint live in the bench orchestrator). CF + all prior baselines stay green.
- Defaults preserve behavior: `--workers 1`, no `--resume`, `request_timeout` only affects real (non-fake) clients. The only always-on change is the additive `runs.jsonl` write.
- The timeout uses an abandoned daemon thread (can't cancel a blocking C/socket call in Python); acceptable for a research harness and the safe choice vs. blocking on `shutdown(wait=True)`.
