from nl_sql_agent.web import _sse


def test_sse_payload_format() -> None:
    event = _sse({"type": "status", "text": "ready"})

    assert event.startswith("data: ")
    assert '"type": "status"' in event
    assert event.endswith("\n\n")
