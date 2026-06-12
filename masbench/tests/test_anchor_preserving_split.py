"""M24 (confirmatory attempt 1 root cause): bucket-stratified train/val carve.

The bucket-blind even/odd carve sent a bucket's ONLY case to VAL whenever
its sorted index was odd: the confirmatory pool's 7 level-I cases (vs
dev's 6) flipped the os anchor II-13 to index 7 -> zero os evidence ->
every deployment abstained -> all four cells FAIL. The stratified carve
guarantees every bucket contributes evidence; singleton buckets land in
BOTH train and val (existing single-instance precedent).
"""

from __future__ import annotations

from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.evolve import _split_train_val

DATA = Path(__file__).parent / "data"


class _FakeInst:
    def __init__(self, case_id: str, bucket: str):
        self.case_id = case_id
        self.n_agents = 5
        self.bucket = bucket


def _bucketer(inst):
    return inst.bucket


def test_confirmatory_shape_keeps_singleton_anchor_in_train():
    # the exact attempt-1 geometry: 7 'of' cases + 1 'os' anchor sorting last
    insts = [_FakeInst(f"I-{i:02d}", "of") for i in (1, 2, 3, 5, 6, 7, 8)]
    insts.append(_FakeInst("II-13", "os"))
    train, val = _split_train_val(insts, bucket_of=_bucketer)
    train_ids = {i.case_id for i in train}
    val_ids = {i.case_id for i in val}
    assert "II-13" in train_ids, "singleton-bucket anchor must produce evidence"
    assert "II-13" in val_ids, "singleton-bucket anchor still validates (both sides)"
    # of-bucket still genuinely split
    assert len(train_ids & {i.case_id for i in insts[:7]}) >= 3
    assert len(val_ids & {i.case_id for i in insts[:7]}) >= 3


def test_dev_shape_also_keeps_anchor():
    insts = [_FakeInst(f"I-{i:02d}", "of") for i in (1, 2, 4, 6, 7, 8)]
    insts.append(_FakeInst("II-13", "os"))
    train, val = _split_train_val(insts, bucket_of=_bucketer)
    assert "II-13" in {i.case_id for i in train}


def test_multi_case_buckets_alternate():
    insts = [_FakeInst(f"A-{i}", "of") for i in range(4)] + [
        _FakeInst(f"B-{i}", "os") for i in range(4)
    ]
    train, val = _split_train_val(insts, bucket_of=_bucketer)
    for bucket in ("of", "os"):
        t = [i for i in train if i.bucket == bucket]
        v = [i for i in val if i.bucket == bucket]
        assert len(t) == 2 and len(v) == 2
        assert not ({x.case_id for x in t} & {x.case_id for x in v})


def test_legacy_no_bucketer_unchanged():
    insts = [_FakeInst(f"C-{i}", "of") for i in range(5)]
    train, val = _split_train_val(insts)
    assert [i.case_id for i in train] == ["C-0", "C-2", "C-4"]
    assert [i.case_id for i in val] == ["C-1", "C-3"]


def test_real_instances_offline_carve_runs():
    insts = list(SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2]))
    if len(insts) >= 2:
        train, val = _split_train_val(insts, bucket_of=lambda i: "of")
        assert train and val
