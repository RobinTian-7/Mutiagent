"""budget_guard.py: the mechanical pre-launch budget gate."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from budget_guard import check  # noqa: E402


def _ledger(tmp_path: Path, total: float) -> Path:
    p = tmp_path / "COST_LEDGER.json"
    p.write_text(json.dumps({"entries": [{"est_usd": total}], "total_est_usd": total}))
    return p


def test_within_budget_passes(tmp_path):
    ok, msg = check(_ledger(tmp_path, 10.0), planned_usd=2.0, cap_usd=40.0)
    assert ok and "OK" in msg


def test_over_budget_blocks(tmp_path):
    ok, msg = check(_ledger(tmp_path, 39.0), planned_usd=2.0, cap_usd=40.0)
    assert not ok and "OVER BUDGET" in msg


def test_exact_cap_passes(tmp_path):
    ok, _ = check(_ledger(tmp_path, 38.0), planned_usd=2.0, cap_usd=40.0)
    assert ok


def test_missing_ledger_blocks(tmp_path):
    ok, msg = check(tmp_path / "nope.json", planned_usd=1.0, cap_usd=40.0)
    assert not ok and "not found" in msg


def test_entries_sum_fallback(tmp_path):
    p = tmp_path / "L.json"
    p.write_text(json.dumps({"entries": [{"est_usd": 5.0}, {"est_usd": 4.5}]}))
    ok, msg = check(p, planned_usd=1.0, cap_usd=10.0)
    assert not ok  # 9.5 + 1.0 > 10
