# SILO-BENCH paper protocol baselines

masbench exposes all three transports evaluated in SILO-BENCH as benchmark
arms: `p2p`, `broadcast`, and `sfs`. They are dynamic protocol baselines rather
than aliases for named static graphs.

## Semantics

- `p2p`: each agent chooses individual recipients with `send_message`.
- `broadcast`: one `broadcast_message` action reaches every other agent.
- `sfs`: agents coordinate through `list_files`, `read_file`, `write_file`, and
  `delete_file` over a shared store.
- All three are synchronous. Information produced in round `r` first becomes
  visible in round `r + 1`.
- Every agent independently submits an answer. These arms therefore require
  `--silo-eval-mode all_agents`.

The runner uses the sanitized masbench task view, not the vendored task prompt,
because the latter can contain annotated topology hints. The implementation is
in `src/masbench/adapters/silo_paper_protocols.py`.

## Metrics

All GraphGen and paper-protocol runs use the same Section 3.3 scorer:

- `S`: fraction of agents whose submitted answer is exactly correct. A run is
  successful only when `S = 1`.
- `P`: mean per-agent quality. Level I uses the paper's one-percent tolerance,
  Level II uses position-wise local-segment accuracy, and Level III uses the
  longest correctly ordered subsequence ratio.
- `C`: generated output tokens divided by executed rounds.
- `D`: outward information transfers divided by `N(N-1)`. For SFS, a transfer
  is a successful read by another agent of a file written by agent `i`.

Raw `runs.jsonl` records retain `per_agent_submissions` and `paper_S/P/C/D`.
The shared scorer lives in `src/masbench/adapters/silo_paper_metrics.py`.

## Smoke command

```bash
cd masbench
uv run --extra dev python -m masbench.cli bench \
  --levels II III --agent-counts 5 --cases II-11 III-21 \
  --seeds 0 --arms graphgen p2p broadcast sfs \
  --silo-eval-mode all_agents --max-rounds 2 \
  --llm fake --model-name fake --out /tmp/silo-paper-smoke
```

The fake client validates wiring only and deliberately submits `null`; it must
not be used to claim model quality.
