"""Smoke tests for runnable demo scripts."""

from __future__ import annotations

import subprocess
import sys


def test_compare_topologies_demo_smoke(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "examples/compare_topologies.py",
            "--agents",
            "8",
            "--rounds",
            "3",
            "--topologies",
            "static_exponential",
            "one_peer_exponential",
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "static_exponential" in result.stdout
    assert "one_peer_exponential" in result.stdout
    assert (tmp_path / "static_exponential" / "event_trace.jsonl").exists()
    assert (tmp_path / "one_peer_exponential" / "neighbor_trace.json").exists()
