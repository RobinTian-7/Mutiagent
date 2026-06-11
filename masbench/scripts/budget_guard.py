"""Hard budget gate for real-LLM rounds. Run BEFORE every paid launch.

Reads the ledger (runs/COST_LEDGER.json), adds the planned round cost, and
exits non-zero if the cap would be exceeded -- so "stay under budget" is a
mechanical precondition, not a promise. The driving prompt requires:

    uv run python scripts/budget_guard.py --planned-usd 2.0 || exit 1

Exit codes: 0 = within budget, 1 = would exceed (do NOT launch), 2 = bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check(ledger_path: Path, planned_usd: float, cap_usd: float) -> tuple[bool, str]:
    try:
        ledger = json.loads(ledger_path.read_text())
    except FileNotFoundError:
        return False, f"ledger not found: {ledger_path} (create it before spending)"
    spent = float(
        ledger.get("total_est_usd")
        or sum(float(e.get("est_usd", 0.0)) for e in ledger.get("entries", []))
    )
    projected = spent + planned_usd
    ok = projected <= cap_usd
    msg = (
        f"spent=${spent:.2f} + planned=${planned_usd:.2f} "
        f"= ${projected:.2f} vs cap=${cap_usd:.2f} -> "
        + ("OK" if ok else "OVER BUDGET: do not launch")
    )
    return ok, msg


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--planned-usd", type=float, required=True)
    p.add_argument("--cap-usd", type=float, default=40.0)
    p.add_argument("--ledger", default="runs/COST_LEDGER.json")
    args = p.parse_args()
    if args.planned_usd < 0:
        print("planned-usd must be >= 0")
        return 2
    ok, msg = check(Path(args.ledger), args.planned_usd, args.cap_usd)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
