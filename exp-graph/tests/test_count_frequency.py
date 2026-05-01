import math

from exp_graph.messaging import OutboxMessage
from exp_graph.tasks import CountFrequencyTaskAdapter
from exp_graph.tasks.count_frequency import (
    build_cf_outbox_projection,
    compute_rmse,
    count_frequency_consensus_key,
    counts_to_json,
    extract_cf_structured_state,
    parse_cf_state_payload,
)


def test_count_frequency_shard_splitting_correctness() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=list(range(10)))

    observations = adapter.split_into_local_observations(global_task, n_agents=3)

    assert [obs["array_shard"] for obs in observations] == [
        [0, 1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]
    assert [obs["global_offset"] for obs in observations] == [0, 4, 7]
    assert global_task["source_answer_counts_by_n_agents"]["3"] == {
        "0": {"0": 1, "1": 1, "2": 1, "3": 1},
        "1": {"4": 1, "5": 1, "6": 1},
        "2": {"7": 1, "8": 1, "9": 1},
    }


def test_count_frequency_rmse_is_root_sum_squared() -> None:
    assert compute_rmse(
        {"1": 2},
        {"1": 1, "2": 2, "3": 0},
        ["1", "2", "3"],
    ) == math.sqrt(5)


def test_count_frequency_initial_local_solve_carries_mergeable_state() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 1, 3])
    observation = adapter.split_into_local_observations(global_task, n_agents=2)[0]

    belief = adapter.initial_local_solve(observation)
    payload = parse_cf_state_payload(belief["proposal"])

    assert belief["status"] == "candidate"
    assert belief["consensus_key"] == "UNKNOWN"
    assert payload is not None
    assert payload["covered_agents"] == [0]
    assert payload["partials"] == {"0": {"1": 1, "2": 1}}
    assert belief["structured_state"]["known_sources"] == [0]
    assert belief["structured_state"]["partials"] == {"0": {"1": 1, "2": 1}}
    assert belief["structured_state"]["source_sizes"] == {"0": 2}


def test_count_frequency_normalizes_and_evaluates_final_key() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[3, 3, 2, 1, 2, 3])
    expected_counts = {"1": 1, "2": 2, "3": 3}
    messy_key = 'FREQ_JSON:{"3":3,"1":1,"2":2}'

    assert counts_to_json(expected_counts) == '{"1":1,"2":2,"3":3}'
    assert adapter.normalize_consensus_key(messy_key) == count_frequency_consensus_key(
        expected_counts
    )
    assert adapter.evaluate_final_answer(global_task, messy_key) is True
    assert adapter.normalize_consensus_key("PARTIAL") == "UNKNOWN"


def test_count_frequency_protocol_merge_uses_structured_payload() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 1, 3])
    observations = adapter.split_into_local_observations(global_task, n_agents=2)
    left = adapter.initial_protocol_belief(observations[0])
    right = adapter.initial_protocol_belief(observations[1])

    merged = adapter.merge_protocol_inbox(
        old_belief_state=left,
        inbox=[
            OutboxMessage.from_belief_state(
                agent_id=1,
                round_idx=0,
                belief_state=right,
            )
        ],
        global_task=global_task,
    )

    assert merged.status == "final"
    assert merged.consensus_key == global_task["answer_key"]
    assert merged.structured_state["known_sources"] == [0, 1]
    assert merged.structured_state["merged_counts"] == {"1": 2, "2": 1, "3": 1}


def test_count_frequency_outbox_projection_is_answer_artifact_only() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(array=[1, 2, 1, 3])
    observation = adapter.split_into_local_observations(global_task, n_agents=2)[0]
    belief = adapter.initial_protocol_belief(observation)
    outbox = OutboxMessage.from_belief_state(
        agent_id=0,
        round_idx=0,
        belief_state=belief,
    ).model_copy(
        update={
            "consensus_key": count_frequency_consensus_key({"1": 1, "2": 1})
        }
    )

    projection = build_cf_outbox_projection(outbox)
    projection_text = str(projection)

    assert projection["schema_version"] == "cf-outbox-v1"
    assert projection["message_type"] == "answer_artifact"
    assert projection["sender_id"] == 0
    assert projection["artifact"]["kind"] == "frequency_counts"
    assert projection["artifact"]["answer"] == {"1": 1, "2": 1}
    assert projection["artifact"]["consensus_key"] == "DERIVED_FROM_MERGED_COUNTS"
    assert projection["provenance"]["source_agent_ids"] == [0]
    assert "FREQ_JSON" not in projection_text
    assert "partials" not in projection_text
    assert "source_sizes" not in projection_text


def test_count_frequency_rejects_non_cf_structured_state_with_partials() -> None:
    payload = {
        "task_name": "other_task",
        "partials": {"0": {"1": 1}},
    }

    assert extract_cf_structured_state(payload) is None
