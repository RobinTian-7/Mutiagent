"""The evolution row collection fans out across workers (turning the hours-long
serial pre-phase into minutes) while staying byte-identical to the serial path,
tolerating individual run failures, and emitting visible progress.
"""
import masbench.evolve as evolve
from masbench.core.config import RunConfig


def _echo(inst, cfg, *, objective, skill_bank, seed, llm_client, **kwargs):
    return {"inst": inst, "obj": objective, "seed": seed}


def test_parallel_collect_rows_matches_serial(monkeypatch):
    monkeypatch.setattr(evolve, "_run_one", _echo)
    cfg = RunConfig(benchmark="silo_bench")
    insts, objs, seeds = ["a", "b", "c"], ["O1", "O2"], [1, 2]

    serial = evolve._collect_rows(
        insts, cfg, objective_variants=objs, seeds=seeds, llm_client=None, workers=1
    )
    parallel = evolve._collect_rows(
        insts, cfg, objective_variants=objs, seeds=seeds, llm_client=None, workers=8
    )

    assert serial == parallel  # identical order + content
    assert len(serial) == 3 * 2 * 2
    # inst-major, then objective, then seed (submission order preserved)
    assert serial[0] == {"inst": "a", "obj": "O1", "seed": 1}
    assert serial[1] == {"inst": "a", "obj": "O1", "seed": 2}
    assert serial[2] == {"inst": "a", "obj": "O2", "seed": 1}


def test_failed_run_is_dropped_not_aborted(monkeypatch):
    def flaky(inst, cfg, *, objective, skill_bank, seed, llm_client, **kwargs):
        if inst == "b":
            raise RuntimeError("wedged provider call")
        return {"inst": inst, "seed": seed}

    monkeypatch.setattr(evolve, "_run_one", flaky)
    cfg = RunConfig(benchmark="silo_bench")
    rows = evolve._collect_rows(
        ["a", "b", "c"], cfg, objective_variants=["O"], seeds=[1],
        llm_client=None, workers=4,
    )

    # 'b' failed -> dropped; 'a' and 'c' survive; evolution NOT aborted.
    assert {r["inst"] for r in rows} == {"a", "c"}


def test_progress_prints(monkeypatch, capsys):
    monkeypatch.setattr(evolve, "_run_one", _echo)
    cfg = RunConfig(benchmark="silo_bench")
    rows = evolve._collect_rows(
        ["a", "b", "c", "d", "e"], cfg, objective_variants=["O"], seeds=[1],
        llm_client=None, workers=2, progress=True, phase="probe",
    )
    assert len(rows) == 5
    assert "[evolve probe]" in capsys.readouterr().out
