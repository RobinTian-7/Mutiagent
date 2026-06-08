import json
from pathlib import Path

from masbench.cli import main

DATA = Path(__file__).parent / "data"


def test_run_suite_writes_summary(tmp_path):
    out = tmp_path / "smoke"
    rc = main([
        "run-suite", "--benchmark", "silo_bench",
        "--benchmarks-dir", str(DATA),
        "--cases", "I-01",
        "--topology", "mesh", "--llm", "fake", "--max-rounds", "3",
        "--out", str(out),
    ])
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["n_instances"] == 1
    assert summary["success_rate"] == 1.0
    # one per-instance record was written
    records = list(out.glob("I-01_*.json"))
    assert len(records) == 1


def test_report_reads_run_dir(tmp_path, capsys):
    out = tmp_path / "smoke"
    main([
        "run-suite", "--benchmark", "silo_bench", "--benchmarks-dir", str(DATA),
        "--cases", "I-01", "--topology", "mesh", "--llm", "fake",
        "--max-rounds", "3", "--out", str(out),
    ])
    rc = main(["report", "--run-dir", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "success_rate" in printed
