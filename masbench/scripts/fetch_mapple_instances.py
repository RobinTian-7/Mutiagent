"""Fetch REAL JSSP instances from the M-APPLE-OS repo and convert to *.jssp.

Operator: the JSSP corroboration must run on the actual benchmark from
https://github.com/genglongling/M-APPLE-OS (arXiv:2502.18836), not on
synthetic instances. Her instances are in Taillard format under
applications/{TA,DMU}/; this pulls them via the GitHub API and converts
to the OR-library *.jssp format our adapter already reads, carrying her
published upper bound as the scoring reference.

Taillard format:
  line 0: header
  line 1: n_jobs n_machines time_seed machine_seed UPPER_BOUND lower_bound
  "Times"   then n_jobs rows of per-operation processing times
  "Machines" then n_jobs rows of 1-indexed machine order per operation

Usage:
  python scripts/fetch_mapple_instances.py --out runs/jssp_mapple \
      --files TA/TA01 TA/TA02
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path

REPO = "genglongling/M-APPLE-OS"


def _fetch(path: str) -> str:
    raw = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/applications/{path}.txt"],
        capture_output=True, text=True, check=True,
    ).stdout
    return base64.b64decode(json.loads(raw)["content"]).decode("utf-8", "replace")


def _parse_taillard(text: str) -> tuple[int, int, int, list[list[list[int]]]]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    hdr = lines[1].split()
    n_jobs, n_mach = int(hdr[0]), int(hdr[1])
    ub = int(hdr[4])
    ti = lines.index("Times")
    mi = lines.index("Machines")
    times = [[int(x) for x in lines[ti + 1 + j].split()] for j in range(n_jobs)]
    machs = [[int(x) for x in lines[mi + 1 + j].split()] for j in range(n_jobs)]
    jobs = [
        [[machs[j][k] - 1, times[j][k]] for k in range(n_mach)]
        for j in range(n_jobs)
    ]
    return n_jobs, n_mach, ub, jobs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--files", nargs="+", required=True,
                   help="repo instance stems, e.g. TA/TA01 DMU/rcmax_20_15_5")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stem in args.files:
        text = _fetch(stem)
        n_jobs, n_mach, ub, jobs = _parse_taillard(text)
        name = stem.split("/")[-1].lower()
        lines = [
            f"# REAL M-APPLE-OS instance {stem} (Taillard format -> OR-library)",
            f"# source: github.com/{REPO}/applications/{stem}.txt",
            f"# ub: {ub}",
            f"{n_jobs} {n_mach}",
        ]
        for ops in jobs:
            lines.append(" ".join(f"{m} {d}" for m, d in ops))
        (out / f"{name}.jssp").write_text("\n".join(lines) + "\n")
        print(f"wrote {out / f'{name}.jssp'}  ({n_jobs}x{n_mach}, ub={ub})")


if __name__ == "__main__":
    main()
