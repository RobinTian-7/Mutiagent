"""dev_screen: cheap 2-arm directional screener for the dev loop.

NOT a judge (the frozen verify_beats_baselines.py stays the only verdict
authority): evolved vs ONE baseline arm on the held-out tail, fewer seeds,
prints paired delta + discordants, exits 0 always (screening, not gating).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from dev_screen import main  # noqa: E402

DATA = Path(__file__).parent / "data"


def test_offline_screen_runs_and_reports(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MASBENCH_EVOLVE_DUMP_DIR", raising=False)
    monkeypatch.setenv("MASBENCH_EVIDENCE_CACHE", str(tmp_path / "ev.json"))
    argv = [
        "dev_screen.py",
        "--benchmarks-dir", str(DATA),
        "--llm", "fake", "--model-name", "fake",
        "--merge-mode", "deterministic", "--init-mode", "deterministic",
        "--levels", "I", "--cases", "I-01", "--n-agents", "2",
        "--rounds", "1", "--train-seeds", "1", "--val-seeds", "2",
        "--eval-seeds", "11", "12", "--baseline", "select",
        "--workers", "1", "--out", str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 0, "screener never gates"
    out = capsys.readouterr().out
    assert "SCREEN" in out and "delta" in out
    report = json.loads((tmp_path / "screen_select_n2.json").read_text())
    assert report["baseline"] == "select"
    assert "delta" in report and "pairs" in report
    assert report["screening_only"] is True
