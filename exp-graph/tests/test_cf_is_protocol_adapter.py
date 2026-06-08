from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter


def test_cf_is_a_protocol_task_adapter():
    a = CountFrequencyTaskAdapter()
    assert isinstance(a, ProtocolTaskAdapter)


def test_cf_answer_key_and_score():
    a = CountFrequencyTaskAdapter()
    gt = a.build_global_task(array=[1, 1, 2], value_min=0, value_max=2)
    counts = {"1": 2, "2": 1}
    key = a.protocol_answer_key(counts)
    assert key == gt["answer_key"]  # FREQ_JSON canonical
    scored = a.score_protocol_answer(counts, gt)
    assert scored["exact_match"] is True
    assert scored["primary_metric"] == 0.0  # CF primary_metric = RMSE (0 = perfect)
