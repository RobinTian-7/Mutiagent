"""Audit the deployed skill bank + per-round innovation record for provenance.

Verifies the pre-registration's Python requirements without re-running models:
  * every python_skill_v1 card stores source_code whose SHA-256 matches the
    recorded program_sha256, plus ast_policy_version + execution_contract_version;
  * revision_history records updates (which fields, incl. code via payload hash);
  * how many innovation candidates were generated vs deployed each round
    (i.e. whether any NOVEL python skill actually cleared the held-out gate, or
    the evolved policy reduced to the hot-start seeds).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def audit_bank(bank: dict[str, Any]) -> dict[str, Any]:
    skills = bank.get("skills", [])
    out: dict[str, Any] = {"n_skills": len(skills), "by_format": {}, "cards": []}
    for s in skills:
        mp = s.get("mode_payload") or {}
        fmt = mp.get("format", "none")
        out["by_format"][fmt] = out["by_format"].get(fmt, 0) + 1
        card: dict[str, Any] = {
            "skill_id": s.get("skill_id"),
            "format": fmt,
            "provenance": s.get("provenance"),
            "planner_mode": s.get("planner_mode"),
            "n_revisions": len(s.get("revision_history") or []),
            "revision_changed_fields": sorted(
                {
                    f
                    for rev in (s.get("revision_history") or [])
                    for f in (rev.get("changed_fields") or [])
                }
            ),
        }
        if fmt == "python_skill_v1":
            src = mp.get("source_code") or ""
            recorded = mp.get("program_sha256") or ""
            computed = hashlib.sha256(src.encode("utf-8")).hexdigest()
            card.update(
                {
                    "source_len": len(src),
                    "program_sha256": recorded,
                    "sha256_matches": bool(recorded and recorded == computed),
                    "ast_policy_version": mp.get("ast_policy_version"),
                    "execution_contract_version": mp.get("execution_contract_version"),
                    "repair_attempts": mp.get("repair_attempts"),
                    "payload_versions_present": bool(
                        mp.get("ast_policy_version")
                        and mp.get("execution_contract_version")
                    ),
                }
            )
        out["cards"].append(card)
    py = [c for c in out["cards"] if c["format"] == "python_skill_v1"]
    out["n_python_skills"] = len(py)
    out["all_python_hashes_consistent"] = all(c["sha256_matches"] for c in py)
    out["all_python_payload_versions_present"] = all(
        c["payload_versions_present"] for c in py
    )
    return out


def audit_rounds(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summ_path in sorted(run_dir.glob("skill_banks/round_*/evolution_summary.json")):
        summ = _load(summ_path)
        hs = summ.get("hot_start", {})
        db = hs.get("dual_branch", {}).get("branches", {})
        rows.append(
            {
                "round": summ.get("curriculum", {}).get("round"),
                "path": str(summ_path.relative_to(run_dir)),
                "gate_accepted": (summ.get("gate") or {}).get("accepted"),
                "skill_ids_after": summ.get("skill_ids_after"),
                "reuse_rows": db.get("reuse", {}).get("n_rows"),
                "reuse_success": db.get("reuse", {}).get("success_rate"),
                "innovation_rows": db.get("innovation", {}).get("n_rows"),
                "innovation_success": db.get("innovation", {}).get("success_rate"),
                "innovation_candidate_skill_ids": hs.get(
                    "innovation_candidate_skill_ids"
                ),
                "new_candidate_skill_ids": hs.get("new_candidate_skill_ids"),
                "deployed_innovation_skill_ids": hs.get(
                    "deployed_innovation_skill_ids"
                ),
            }
        )
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    run_dir = Path(args.run_dir)
    bank = _load(run_dir / "skill_banks" / "final" / "deployed" / "bank.json")
    result = {
        "final_bank": audit_bank(bank),
        "rounds": audit_rounds(run_dir),
    }
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True))

    fb = result["final_bank"]
    print(f"final bank: {fb['n_skills']} skills, formats={fb['by_format']}")
    print(
        f"python skills deployed: {fb['n_python_skills']} "
        f"(hashes_consistent={fb['all_python_hashes_consistent']}, "
        f"payload_versions_present={fb['all_python_payload_versions_present']})"
    )
    for c in fb["cards"]:
        extra = ""
        if c["format"] == "python_skill_v1":
            extra = (
                f" sha_ok={c['sha256_matches']} src_len={c['source_len']} "
                f"ast={c['ast_policy_version']} contract={c['execution_contract_version']}"
            )
        print(f"  - {c['skill_id']} [{c['format']}] revs={c['n_revisions']}{extra}")
    print("innovation per round (generated -> deployed):")
    for r in result["rounds"]:
        gen = len(r.get("new_candidate_skill_ids") or [])
        dep = len(r.get("deployed_innovation_skill_ids") or [])
        print(
            f"  round {r['round']}: innov_rows={r['innovation_rows']} "
            f"succ={r['innovation_success']} candidates={gen} deployed={dep} "
            f"gate={r['gate_accepted']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
