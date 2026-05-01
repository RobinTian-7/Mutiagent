from exp_graph.llm.parser import parse_belief_state


def test_parse_belief_state_allows_control_chars_inside_strings() -> None:
    raw = (
        '{"status":"candidate",'
        '"proposal":"line one\nline two",'
        '"consensus_key":"UNKNOWN",'
        '"support":["ok"],'
        '"uncertainty":"",'
        '"open_questions":[],'
        '"private_notes":""}'
    )

    belief_state = parse_belief_state(raw)

    assert belief_state.proposal == "line one\nline two"


def test_parse_belief_state_repairs_json_syntax_error() -> None:
    raw = (
        '{"status":"candidate"'
        '"proposal":"missing comma before proposal",'
        '"consensus_key":"UNKNOWN",'
        '"support":["ok"],'
        '"uncertainty":"",'
        '"open_questions":[],'
        '"private_notes":""}'
    )

    belief_state = parse_belief_state(raw)

    assert belief_state.status == "candidate"
    assert belief_state.proposal == "missing comma before proposal"
