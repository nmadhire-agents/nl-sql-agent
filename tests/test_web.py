from pathlib import Path

from nl_sql_agent.web import _sse
from nl_sql_agent.web import _demo_fallback_events


def test_sse_payload_format() -> None:
    event = _sse({"type": "status", "text": "ready"})

    assert event.startswith("data: ")
    assert '"type": "status"' in event
    assert event.endswith("\n\n")


def test_demo_fallback_answers_bundled_example() -> None:
    events = list(
        _demo_fallback_events(
            "How many singers do we have?",
            Path("data/spider/spider_data/database/concert_singer/concert_singer.sqlite"),
            "quota exceeded",
        )
    )

    assert any(event.get("type") == "sql" for event in events)
    assert events[-1]["answer"] == "There are 6 singers in the database."
