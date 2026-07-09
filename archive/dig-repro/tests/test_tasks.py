from dig_repro.tasks import CountFrequencyTask, NewsgroupsFrequencyTask


def test_count_frequency_merge_dedupes_overlap():
    task = CountFrequencyTask()
    problem = task.build_problem_instance(difficulty="easy", seed=1, array_size=6, value_domain_size=3)
    left = task.solve_raw_data_payload(problem, {"indices": [0, 1, 2], "values": [0, 1, 1]})
    right = task.solve_raw_data_payload(problem, {"indices": [2, 3, 4], "values": [1, 2, 0]})
    merged = task.merge_solution_payloads(problem, [left, right])
    assert merged["covered_ids"] == [0, 1, 2, 3, 4]
    assert merged["histogram"] == {"0": 2, "1": 2, "2": 1}


def test_newsgroups_merge_dedupes_overlap():
    task = NewsgroupsFrequencyTask()
    documents = [
        {"doc_id": 0, "text": "space space", "label": "sci.space"},
        {"doc_id": 1, "text": "graphics graphics", "label": "comp.graphics"},
        {"doc_id": 2, "text": "space again", "label": "sci.space"},
    ]
    problem = task.build_problem_instance(difficulty="easy", seed=1, documents=documents, categories=["comp.graphics", "sci.space"])
    left = task.solve_raw_data_payload(problem, {"doc_ids": [0, 1], "labels_for_testing_only": ["sci.space", "comp.graphics"]})
    right = task.solve_raw_data_payload(problem, {"doc_ids": [1, 2], "labels_for_testing_only": ["comp.graphics", "sci.space"]})
    merged = task.merge_solution_payloads(problem, [left, right])
    assert merged["covered_ids"] == [0, 1, 2]
    assert merged["histogram"] == {"comp.graphics": 1, "sci.space": 2}

