from __future__ import annotations

from contextlib import contextmanager, nullcontext
from hashlib import sha256
import json
import os
from urllib.parse import urlparse
from urllib.request import urlopen
from typing import Any, Iterator


_TRACER = None
_CONFIGURED = False
MAX_TRACE_VALUE_LENGTH = 20_000


def configure_tracing(endpoint: str, mode: str = "redacted") -> None:
    global _CONFIGURED
    os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
    if mode == "off" or _CONFIGURED:
        return
    if not _collector_is_available(endpoint):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": "nl-sql-agent"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=provider)
    except Exception:
        pass

    global _TRACER
    _TRACER = trace.get_tracer("nl_sql_agent")
    _CONFIGURED = True


def _collector_is_available(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return False
    base = f"{parsed.scheme}://{parsed.netloc}"
    try:
        urlopen(base, timeout=0.25).close()
        return True
    except Exception:
        return False


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    if _TRACER is None:
        with nullcontext() as ctx:
            yield ctx
        return
    with _TRACER.start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            set_span_attribute(current, key, value)
        yield current


def safe_attr(value: str, mode: str) -> str:
    if mode == "full":
        return truncate(value)
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def trace_payload(payload: Any, mode: str) -> str:
    value = json.dumps(payload, sort_keys=True, default=str)
    return safe_attr(value, mode)


def set_span_attribute(current: Any, key: str, value: Any) -> None:
    if current is None or value is None or not hasattr(current, "set_attribute"):
        return
    if isinstance(value, (str, bool, int, float)):
        current.set_attribute(key, truncate(value) if isinstance(value, str) else value)
        return
    current.set_attribute(key, truncate(json.dumps(value, sort_keys=True, default=str)))


def truncate(value: str) -> str:
    if len(value) <= MAX_TRACE_VALUE_LENGTH:
        return value
    return value[:MAX_TRACE_VALUE_LENGTH] + "...[truncated]"
