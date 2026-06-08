"""Live-progress-printer tests for ``masbench.bench`` (Plan 5 T5).

A long real-LLM ``run_benchmark`` grid used to print nothing until the very end,
so a 90-minute hang was invisible. ``run_benchmark`` now emits a built-in live
progress stream to stdout: one startup ``bench:`` header line, then one
``[done/to_run] ...`` line per finished run-unit (success or failed), gated by a
``progress`` flag (``--quiet`` turns it off). These tests pin:

* **per-run lines printed** -- a default-progress fake grid prints the startup
  ``bench:`` line and at least one ``[k/`` per-run line carrying a ``success``
  token;
* **--quiet suppresses** -- ``progress=False`` (and ``--quiet`` via the CLI)
  prints no per-run ``[k/`` lines;
* **counts with workers** -- the SAME per-unit hook fires under ``workers>1`` so
  the number of ``[k/`` lines equals the number of executed units and the
  running counter reaches ``to_run``.

All offline via ``--llm fake`` (deterministic, no network). Progress goes to
stdout with ``flush=True`` so ``capsys`` captures it.
"""

from __future__ import annotations

import re
from pathlib import Path

from masbench.bench import run_benchmark
from masbench.core.config import RunConfig

from masbench.adapters.silo_bench import SiloBenchAdapter

DATA = Path(__file__).parent / "data"

# One ``[k/to_run]`` per-run progress line, capturing the running ``done`` index
# and the ``to_run`` denominator.
_RUN_LINE = re.compile(r"^\[(\d+)/(\d+)\]")


def _adapter() -> SiloBenchAdapter:
    return SiloBenchAdapter(DATA)


def _cfg() -> RunConfig:
    return RunConfig(
        use_planner=False,
        llm_provider="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        objective="accuracy_first",
    )


def _run_lines(captured: str) -> list[re.Match]:
    return [m for line in captured.splitlines() if (m := _RUN_LINE.match(line))]


def test_progress_prints_per_run(tmp_path, capsys) -> None:
    """Default progress: prints the startup ``bench:`` line + per-run lines."""
    run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree"],
        out=tmp_path / "paper",
    )
    out = capsys.readouterr().out

    # Startup header line.
    assert "bench:" in out, "expected a startup 'bench:' header line"
    # At least one per-run [k/to_run] line.
    matches = _run_lines(out)
    assert matches, "expected at least one '[k/...]' per-run progress line"
    # Per-run lines carry a running success token.
    assert "success" in out
    # fixed (1 topo x 1 seed) + select (1 seed) = 2 executed run-units.
    assert len(matches) == 2


def test_quiet_suppresses_progress(tmp_path, capsys) -> None:
    """progress=False prints no per-run [k/...] lines."""
    run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree"],
        out=tmp_path / "paper",
        progress=False,
    )
    out = capsys.readouterr().out
    assert not _run_lines(out), "progress=False must not print per-run lines"
    assert "bench:" not in out, "progress=False must not print the header"


def test_quiet_cli_suppresses_progress(tmp_path, capsys) -> None:
    """`masbench bench --quiet` prints no per-run [k/...] lines (still exits 0)."""
    from masbench.cli import main

    rc = main(
        [
            "bench",
            "--benchmark",
            "silo_bench",
            "--benchmarks-dir",
            str(DATA),
            "--cases",
            "I-01",
            "--agent-counts",
            "2",
            "--seeds",
            "1",
            "--arms",
            "fixed",
            "select",
            "--fixed-topologies",
            "tree",
            "--llm",
            "fake",
            "--objective",
            "accuracy_first",
            "--quiet",
            "--out",
            str(tmp_path / "paper"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert not _run_lines(out), "--quiet must not print per-run lines"
    # The existing final summary prints are kept regardless of --quiet.
    assert "overall success:" in out
    assert "wrote" in out


def test_progress_default_on_via_cli(tmp_path, capsys) -> None:
    """Without --quiet the CLI prints the header + per-run lines (default ON)."""
    from masbench.cli import main

    rc = main(
        [
            "bench",
            "--benchmark",
            "silo_bench",
            "--benchmarks-dir",
            str(DATA),
            "--cases",
            "I-01",
            "--agent-counts",
            "2",
            "--seeds",
            "1",
            "--arms",
            "fixed",
            "select",
            "--fixed-topologies",
            "tree",
            "--llm",
            "fake",
            "--objective",
            "accuracy_first",
            "--out",
            str(tmp_path / "paper"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "bench:" in out
    assert _run_lines(out), "default CLI run must print per-run progress lines"


def test_progress_counts_with_workers(tmp_path, capsys) -> None:
    """workers=4: the per-run hook still fires; counter reaches to_run exactly.

    The shared ``_run_unit`` chokepoint covers BOTH the sequential and the
    parallel path, so the parallel grid must emit the same per-unit lines and the
    running ``done`` index must hit ``to_run`` (every executed unit is ticked).
    """
    run_benchmark(
        _adapter(),
        cases=["I-01", "III-21"],
        agent_counts=[2],
        seeds=[1, 2],
        arms=["fixed", "select", "graphgen"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=tmp_path / "par",
        workers=4,
    )
    out = capsys.readouterr().out

    matches = _run_lines(out)
    assert matches, "workers>1 must still print per-run progress lines"
    # fixed (2 topo x 2 cases x 2 seeds = 8) + select (2x2=4) + graphgen (2x2=4)
    # = 16 executed run-units -> 16 per-run lines.
    assert len(matches) == 16
    # Every line shares the same to_run denominator, and the running done index
    # reaches it (the last finished unit is [16/16]).
    to_runs = {int(m.group(2)) for m in matches}
    assert to_runs == {16}
    done_indices = {int(m.group(1)) for m in matches}
    assert max(done_indices) == 16
    # The running counter is a clean 1..16 with no gaps/dupes (lock-guarded).
    assert done_indices == set(range(1, 17))


def test_progress_header_reports_resume(tmp_path, capsys) -> None:
    """On resume the header notes the already-done count and shrinks to_run."""
    out = tmp_path / "paper"
    common = dict(
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree"],
    )
    run_benchmark(_adapter(), out=out, **common)
    capsys.readouterr()  # drop the first run's output

    run_benchmark(_adapter(), out=out, resume=True, **common)
    out_text = capsys.readouterr().out
    # Resumed run: header still prints, notes the resumed count, and nothing reran.
    assert "bench:" in out_text
    assert "resume" in out_text or "already done" in out_text
    assert not _run_lines(out_text), "a fully-resumed grid executes no units"
