from nl_sql_agent.tracing import safe_attr, trace_payload, truncate


def test_safe_attr_redacts_by_default() -> None:
    value = safe_attr("select count(*) from singer", "redacted")
    assert value.startswith("sha256:")
    assert "select" not in value


def test_safe_attr_full_preserves_content() -> None:
    assert safe_attr("select count(*) from singer", "full") == "select count(*) from singer"


def test_trace_payload_redacts_or_preserves_json() -> None:
    payload = {"sql": "select count(*) from singer", "rows": [{"count": 6}]}
    assert trace_payload(payload, "redacted").startswith("sha256:")
    full = trace_payload(payload, "full")
    assert "select count(*) from singer" in full
    assert '"count": 6' in full


def test_truncate_limits_large_values() -> None:
    value = truncate("x" * 25_000)
    assert len(value) < 25_000
    assert value.endswith("...[truncated]")
